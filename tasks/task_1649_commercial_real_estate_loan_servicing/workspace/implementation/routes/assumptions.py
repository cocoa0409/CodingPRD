from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services import posture
from services.common import add_months_clamped, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import assumption as ser_assumption
from services.validate import body_json, require_fields, req_enum, req_int, req_str

bp = Blueprint("assumptions", __name__)

ASSUMPTION_OUTSTANDING_PCT = Decimal("0.01")
ASSUMPTION_ORIGINAL_PCT = Decimal("0.005")
ASSUMPTION_FLAT_CENTS = 25000
ASSUMPTION_FEE_MIN_CENTS = 1000000
ASSUMPTION_FEE_MAX_CENTS = 25000000

NON_TERMINAL = ("SUBMITTED", "UNDER_REVIEW", "APPROVED")


def _load(aid):
    a = db.assumption_requests.get(aid)
    if a is None:
        raise errors.not_found("AssumptionRequest not found")
    return a


def _open_assessments(loan_id):
    return posture.loan_open_assessments(loan_id)


def _estoppels_ok(loan):
    clock = db.get_clock()
    for lease in db.leases.values():
        prop = db.properties.get(lease["property_id"])
        if not prop or prop["loan_id"] != loan["id"]:
            continue
        if not lease["estoppel_required"]:
            continue
        ok = False
        for e in db.estoppels.values():
            if (
                e["lease_id"] == lease["id"]
                and e["status"] == "EXECUTED"
                and e.get("expires_at_dt")
                and e["expires_at_dt"] > clock
            ):
                ok = True
                break
        if not ok:
            return False
    return True


def _inspections_fresh(loan):
    clock = db.get_clock()
    cutoff = add_months_clamped(clock, -12)
    props = [p for p in db.properties.values() if p["loan_id"] == loan["id"]]
    for p in props:
        ok = False
        for insp in db.inspections.values():
            if (
                insp["property_id"] == p["id"]
                and insp["status"] == "COMPLETED"
                and insp["completed_at_dt"] >= cutoff
                and insp["condition_rating"] != "CRITICAL"
            ):
                ok = True
                break
        if not ok:
            return False
    return True


@bp.post("/loans/<lid>/assumption-requests")
def create_assumption(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    loan = db.loans.get(lid)
    if loan is None:
        raise errors.not_found("Loan not found")
    mw.require_borrower_ownership(actor, "loan", loan)
    data = body_json()
    require_fields(data, [
        "proposed_assumptor_name", "proposed_assumptor_tax_id",
        "proposed_net_worth_cents", "expected_loan_version",
    ])
    name = req_str(data, "proposed_assumptor_name")
    tax_id = req_str(data, "proposed_assumptor_tax_id")
    net_worth = req_int(data, "proposed_net_worth_cents", minimum=0)
    expected = data.get("expected_loan_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_loan_version must be an integer")
    # OCC (priority 6)
    if expected != loan["version"]:
        raise errors.stale_version("Loan version has advanced since last read")
    # In-progress constraint (priority 25)
    for a in db.assumption_requests.values():
        if a["loan_id"] == lid and a["status"] in NON_TERMINAL:
            raise errors.ApiError(
                errors.ERR_ASSUMPTION_IN_PROGRESS,
                "A non-terminal assumption request already exists for this loan", 409)
    a = {
        "id": db.new_id(),
        "loan_id": lid,
        "proposed_assumptor_name": name,
        "proposed_assumptor_tax_id": tax_id,
        "proposed_net_worth_cents": net_worth,
        "status": "SUBMITTED",
        "fee_cents": None,
        "decided_at": None,
        "decided_at_dt": None,
        "approval_expires_at": None,
        "approval_expires_at_dt": None,
        "rejection_reason": None,
    }
    stamp_new(a)
    db.assumption_requests[a["id"]] = a
    touch(loan)  # creating the request advances loan.version
    return success(ser_assumption(a), status=201)


@bp.get("/loans/<lid>/assumption-requests")
def list_assumptions(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    limit, offset = get_pagination()
    items = [a for a in db.assumption_requests.values() if a["loan_id"] == lid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, pg = paginate([ser_assumption(a) for a in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/assumption-requests/<aid>/start-review")
def start_review(aid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    a = _load(aid)
    if a["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED request can move to UNDER_REVIEW")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success(ser_assumption(a))


@bp.post("/assumption-requests/<aid>/decide")
def decide(aid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    a = _load(aid)
    data = body_json()
    require_fields(data, ["decision"])
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    rejection_reason = data.get("rejection_reason")
    if decision == "REJECT":
        if not isinstance(rejection_reason, str) or not rejection_reason:
            raise errors.invalid_request("rejection_reason is required when decision is REJECT")
    if a["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Only an UNDER_REVIEW request can be decided")
    loan = db.loans.get(a["loan_id"])
    now = db.get_clock()
    if decision == "APPROVE":
        # Pipeline order: covenant (9) -> currency (10) -> estoppel (14) -> inspection (32)
        if _open_assessments(loan["id"]):
            raise errors.ApiError(
                errors.ERR_OPEN_COVENANT_BREACH,
                "OPEN covenant assessment blocks assumption approval", 409)
        if loan["payment_status"] != "CURRENT":
            raise errors.ApiError(
                errors.ERR_LOAN_NOT_CURRENT, "Loan must be CURRENT", 409)
        if not _estoppels_ok(loan):
            raise errors.ApiError(
                errors.ERR_ESTOPPEL_REQUIRED,
                "Every estoppel-required lease needs an EXECUTED unexpired certificate", 409)
        if not _inspections_fresh(loan):
            raise errors.ApiError(
                errors.ERR_INSPECTION_STALE,
                "Every property needs a COMPLETED inspection within 12 months, rating != CRITICAL",
                409)
        if loan["assumption_fee_basis"] == "OUTSTANDING":
            fee = int(
                (Decimal(loan["current_balance_cents"]) * ASSUMPTION_OUTSTANDING_PCT)
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            fee = max(ASSUMPTION_FEE_MIN_CENTS, min(ASSUMPTION_FEE_MAX_CENTS, fee))
        else:
            fee = int(
                (Decimal(loan["original_principal_cents"]) * ASSUMPTION_ORIGINAL_PCT)
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            ) + ASSUMPTION_FLAT_CENTS
        a["fee_cents"] = fee
        a["status"] = "APPROVED"
        a["decided_at_dt"] = now
        a["decided_at"] = db.fmt_ts(now)
        a["approval_expires_at_dt"] = now + timedelta(days=60)
        a["approval_expires_at"] = db.fmt_ts(a["approval_expires_at_dt"])
    else:
        a["status"] = "REJECTED"
        a["rejection_reason"] = rejection_reason
        a["decided_at_dt"] = now
        a["decided_at"] = db.fmt_ts(now)
    touch(a)
    return success(ser_assumption(a))


@bp.post("/assumption-requests/<aid>/execute")
def execute(aid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    a = _load(aid)
    if a["status"] != "APPROVED":
        raise errors.invalid_state("Only an APPROVED request can be executed")
    now = db.get_clock()
    if now > a["approval_expires_at_dt"]:
        raise errors.ApiError(
            errors.ERR_ASSUMPTION_APPROVAL_EXPIRED,
            "Approval validity has lapsed", 409)
    loan = db.loans.get(a["loan_id"])
    if _open_assessments(loan["id"]):
        raise errors.ApiError(
            errors.ERR_OPEN_COVENANT_BREACH,
            "OPEN covenant assessment blocks execution", 409)
    if loan["payment_status"] != "CURRENT":
        raise errors.ApiError(
            errors.ERR_LOAN_NOT_CURRENT, "Loan must be CURRENT", 409)
    # Register the assumptor as a brand-new borrower and reassign the loan.
    new_borrower = {
        "id": db.new_id(),
        "legal_name": a["proposed_assumptor_name"],
        "tax_id": a["proposed_assumptor_tax_id"],
        "contact_email": "",
    }
    stamp_new(new_borrower)
    db.borrowers[new_borrower["id"]] = new_borrower
    a["status"] = "EXECUTED"
    touch(a)
    loan["borrower_id"] = new_borrower["id"]
    touch(loan)
    return success(ser_assumption(a))


@bp.post("/assumption-requests/<aid>/withdraw")
def withdraw(aid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    a = _load(aid)
    mw.require_borrower_ownership(actor, "assumption", a)
    if a["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise errors.invalid_state("Only SUBMITTED or UNDER_REVIEW requests can be withdrawn")
    a["status"] = "WITHDRAWN"
    touch(a)
    return success(ser_assumption(a))
