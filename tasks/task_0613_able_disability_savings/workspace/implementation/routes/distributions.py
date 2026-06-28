"""Distribution lifecycle + QDERecord routes."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from middleware import get_identity, require_role
from response import ok, created, ok_list
from errors import err
from services import domain
from services.calc import earnings_split, nonqualified_additional_tax
from routes.common import (
    get_body, find_or_404, require_enum, require_positive_amount,
    require_string, paginate, check_account_owner, check_occ,
)

bp = Blueprint("distributions", __name__)

ALL_ROLES = {"ProgramAdministrator", "Beneficiary", "AuthorizedRepresentative"}
CATEGORIES = {"HOUSING", "EDUCATION", "HEALTH", "TRANSPORTATION", "BASIC_LIVING", "LEGAL", "OTHER"}


# ---------------------------------------------------------------------------
# Request a distribution
# ---------------------------------------------------------------------------
@bp.post("/able/accounts/<aid>/distributions")
def request_distribution(aid):
    user_id, role = get_identity()
    require_role(role, ALL_ROLES)
    a = find_or_404(db.accounts, aid, "Account")
    check_account_owner(a, role, user_id)
    body = get_body()
    amount = require_positive_amount(body, "amount_cents")
    category = require_enum(body, "category", CATEGORIES)
    d = {
        "account_id": aid,
        "amount_cents": amount,
        "category": category,
        "status": "REQUESTED",
        "earnings_portion_cents": 0,
        "qualified_amount_cents": 0,
        "nonqualified_amount_cents": 0,
        "additional_tax_cents": 0,
        "counts_against_ssi_housing": False,
    }
    stamp_new(d)
    db.distributions[d["id"]] = d
    return created(domain.serialize_distribution(d))


@bp.get("/able/distributions/<did>")
def get_distribution(did):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    d = find_or_404(db.distributions, did, "Distribution")
    return ok(domain.serialize_distribution(d))


@bp.get("/able/distributions")
def list_distributions():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    account_id = request.args.get("account_id")
    items = list(db.distributions.values())
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_distribution(d) for d in page],
                   limit, offset, total)


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------
@bp.post("/able/distributions/<did>/approve")
def approve_distribution(did):
    user_id, role = get_identity()
    require_role(role, {"Beneficiary", "AuthorizedRepresentative"})
    d = find_or_404(db.distributions, did, "Distribution")
    a = db.accounts[d["account_id"]]
    check_account_owner(a, role, user_id)
    # state (priority 6)
    if d["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Distribution is not REQUESTED")
    # account-open (priority 8)
    if a["status"] != "OPEN":
        raise err("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN")
    # insufficient balance (priority 16)
    if d["amount_cents"] > a["balance_cents"]:
        raise err("ERR_INSUFFICIENT_BALANCE", "Distribution amount exceeds balance")
    d["status"] = "APPROVED"
    touch(d)
    return ok(domain.serialize_distribution(d))


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------
@bp.post("/able/distributions/<did>/reject")
def reject_distribution(did):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    d = find_or_404(db.distributions, did, "Distribution")
    if d["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Distribution is not REQUESTED")
    d["status"] = "REJECTED"
    touch(d)
    return ok(domain.serialize_distribution(d))


# ---------------------------------------------------------------------------
# Disburse (OCC + earnings split)
# ---------------------------------------------------------------------------
@bp.post("/able/distributions/<did>/disburse")
def disburse_distribution(did):
    user_id, role = get_identity()
    require_role(role, {"Beneficiary", "AuthorizedRepresentative"})
    d = find_or_404(db.distributions, did, "Distribution")
    a = db.accounts[d["account_id"]]
    check_account_owner(a, role, user_id)
    body = get_body()
    # body well-formedness: expected_account_version present (priority 5)
    if "expected_account_version" not in body or body["expected_account_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_account_version is required")
    # state (priority 6)
    if d["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Distribution is not APPROVED")
    # OCC (priority 7)
    check_occ(body, a)
    # account-open (priority 8)
    if a["status"] != "OPEN":
        raise err("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN")
    # insufficient balance (priority 16)
    if d["amount_cents"] > a["balance_cents"]:
        raise err("ERR_INSUFFICIENT_BALANCE", "Distribution amount exceeds balance")
    # earnings split captured now
    earnings_portion, basis_portion = earnings_split(
        d["amount_cents"], a["balance_cents"], a["earnings_cents"])
    d["earnings_portion_cents"] = earnings_portion
    d["status"] = "DISBURSED"
    touch(d)
    a["earnings_cents"] -= earnings_portion
    a["basis_cents"] -= basis_portion
    a["balance_cents"] -= d["amount_cents"]
    domain.recompute_ssi_posture(a)
    touch(a)
    return ok(domain.serialize_distribution(d))


# ---------------------------------------------------------------------------
# Substantiate
# ---------------------------------------------------------------------------
@bp.post("/able/distributions/<did>/substantiate")
def substantiate_distribution(did):
    user_id, role = get_identity()
    require_role(role, {"Beneficiary", "AuthorizedRepresentative"})
    d = find_or_404(db.distributions, did, "Distribution")
    a = db.accounts[d["account_id"]]
    check_account_owner(a, role, user_id)
    # state (priority 6)
    if d["status"] != "DISBURSED":
        raise err("ERR_INVALID_STATE", "Distribution is not DISBURSED")
    # QDE sum must equal amount (priority 17)
    qde_sum = sum(q["amount_cents"] for q in db.qde_records.values()
                  if q["distribution_id"] == did)
    if qde_sum != d["amount_cents"]:
        raise err("ERR_QDE_MISMATCH",
                  "Attached QDE records do not sum to the distribution amount")
    d["status"] = "SUBSTANTIATED"
    d["qualified_amount_cents"] = d["amount_cents"]
    d["nonqualified_amount_cents"] = 0
    d["additional_tax_cents"] = 0
    touch(d)
    return ok(domain.serialize_distribution(d))


# ---------------------------------------------------------------------------
# Clawback (non-qualified penalty)
# ---------------------------------------------------------------------------
@bp.post("/able/distributions/<did>/clawback")
def clawback_distribution(did):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    d = find_or_404(db.distributions, did, "Distribution")
    if d["status"] != "DISBURSED":
        raise err("ERR_INVALID_STATE", "Distribution is not DISBURSED")
    a = db.accounts[d["account_id"]]
    program = db.programs[db.beneficiaries[a["beneficiary_id"]]["program_id"]]
    qde_sum = sum(q["amount_cents"] for q in db.qde_records.values()
                  if q["distribution_id"] == did)
    qualified, nonqualified, additional_tax = nonqualified_additional_tax(
        d["amount_cents"], d["earnings_portion_cents"], qde_sum,
        program["nonqualified_additional_tax_pct"])
    d["status"] = "CLAWED_BACK"
    d["qualified_amount_cents"] = qualified
    d["nonqualified_amount_cents"] = nonqualified
    d["additional_tax_cents"] = additional_tax
    touch(d)
    return ok(domain.serialize_distribution(d))


# ---------------------------------------------------------------------------
# QDERecord — attach to a disbursed distribution
# ---------------------------------------------------------------------------
@bp.post("/able/distributions/<did>/qde-records")
def create_qde_record(did):
    user_id, role = get_identity()
    require_role(role, {"Beneficiary", "AuthorizedRepresentative"})
    d = find_or_404(db.distributions, did, "Distribution")
    a = db.accounts[d["account_id"]]
    check_account_owner(a, role, user_id)
    body = get_body()
    expense_category = require_enum(body, "expense_category", CATEGORIES)
    amount = require_positive_amount(body, "amount_cents")
    receipt_reference = require_string(body, "receipt_reference")
    expense_date = require_string(body, "expense_date")
    q = {
        "distribution_id": did,
        "expense_category": expense_category,
        "amount_cents": amount,
        "receipt_reference": receipt_reference,
        "expense_date": expense_date,
    }
    stamp_new(q)
    db.qde_records[q["id"]] = q
    return created(domain.serialize_qde_record(q))


@bp.get("/able/qde-records/<qid>")
def get_qde_record(qid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    q = find_or_404(db.qde_records, qid, "QDERecord")
    return ok(domain.serialize_qde_record(q))


@bp.get("/able/qde-records")
def list_qde_records():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    distribution_id = request.args.get("distribution_id")
    items = list(db.qde_records.values())
    if distribution_id is not None:
        items = [q for q in items if q["distribution_id"] == distribution_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_qde_record(q) for q in page],
                   limit, offset, total)
