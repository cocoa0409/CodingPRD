"""Account lifecycle, means-test, fee assessment, investment changes."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from middleware import get_identity, require_role
from response import ok, created, ok_list
from errors import err
from services import domain
from services.calc import management_fee
from clock import clock
from routes.common import (
    get_body, find_or_404, require_string, optional_int, paginate,
    check_account_owner, require_int,
)

bp = Blueprint("accounts", __name__)

ALL_ROLES = {"ProgramAdministrator", "Beneficiary", "AuthorizedRepresentative"}


@bp.post("/able/accounts")
def open_account():
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    body = get_body()
    require_string(body, "beneficiary_id")
    require_string(body, "investment_option_id")
    find_or_404(db.beneficiaries, body["beneficiary_id"], "Beneficiary")
    find_or_404(db.investment_options, body["investment_option_id"], "InvestmentOption")
    a = {
        "beneficiary_id": body["beneficiary_id"],
        "investment_option_id": body["investment_option_id"],
        "status": "OPEN",
        "balance_cents": 0,
        "basis_cents": 0,
        "earnings_cents": 0,
        "ssi_posture": "SSI_OK",
        "medicaid_paid_since_open_cents": optional_int(body, "medicaid_paid_since_open_cents", 0),
        "premiums_paid_by_beneficiary_cents": optional_int(body, "premiums_paid_by_beneficiary_cents", 0),
        "_investment_change_dates": [],
    }
    stamp_new(a)
    domain.recompute_ssi_posture(a)
    db.accounts[a["id"]] = a
    return created(domain.serialize_account(a))


@bp.get("/able/accounts/<aid>")
def get_account(aid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    a = find_or_404(db.accounts, aid, "Account")
    return ok(domain.serialize_account(a))


@bp.get("/able/accounts")
def list_accounts():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    beneficiary_id = request.args.get("beneficiary_id")
    investment_option_id = request.args.get("investment_option_id")
    items = list(db.accounts.values())
    if beneficiary_id is not None:
        items = [a for a in items if a["beneficiary_id"] == beneficiary_id]
    if investment_option_id is not None:
        items = [a for a in items if a["investment_option_id"] == investment_option_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_account(a) for a in page], limit, offset, total)


@bp.get("/able/accounts/<aid>/means-test")
def means_test(aid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    a = find_or_404(db.accounts, aid, "Account")
    variant = request.args.get("variant")
    if variant is None:
        # also accept body for robustness
        variant = get_body().get("variant")
    if variant not in ("SSI", "MEDICAID"):
        raise err("ERR_INVALID_REQUEST", "variant must be SSI or MEDICAID")
    b = db.beneficiaries[a["beneficiary_id"]]
    program = db.programs[b["program_id"]]
    able_countable = domain.ssi_able_countable(a, program)
    other = b["other_countable_resources_cents"]
    if variant == "SSI":
        total = other + able_countable
        posture = "SSI_SUSPENDED" if total > program["ssi_resource_limit_cents"] else "SSI_OK"
        affects = posture == "SSI_SUSPENDED"
        result = {
            "variant": "SSI",
            "able_countable_for_ssi_cents": able_countable,
            "total_countable_cents": total,
            "ssi_posture": posture,
            "affects_benefit": affects,
        }
    else:  # MEDICAID — entire ABLE balance disregarded
        total = other
        posture = a["ssi_posture"]
        result = {
            "variant": "MEDICAID",
            "able_countable_for_ssi_cents": 0,
            "total_countable_cents": total,
            "ssi_posture": posture,
            "affects_benefit": False,
        }
    return ok(result)


@bp.post("/able/accounts/<aid>/suspend")
def suspend_account(aid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    a = find_or_404(db.accounts, aid, "Account")
    if a["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Account is not OPEN")
    a["status"] = "SUSPENDED"
    touch(a)
    return ok(domain.serialize_account(a))


@bp.post("/able/accounts/<aid>/reinstate")
def reinstate_account(aid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    a = find_or_404(db.accounts, aid, "Account")
    if a["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Account is not SUSPENDED")
    # ERR_NOT_CERTIFIED if beneficiary eligibility != CERTIFIED (priority 9)
    if domain.compute_eligibility_status(a["beneficiary_id"]) != "CERTIFIED":
        raise err("ERR_NOT_CERTIFIED", "Beneficiary is not CERTIFIED")
    a["status"] = "OPEN"
    touch(a)
    return ok(domain.serialize_account(a))


@bp.post("/able/accounts/<aid>/assess-fee")
def assess_fee(aid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    a = find_or_404(db.accounts, aid, "Account")
    body = get_body()
    period_end_balance = require_int(body, "period_end_balance_cents")
    months = require_int(body, "months")
    program = db.programs[db.beneficiaries[a["beneficiary_id"]]["program_id"]]
    total_fee = management_fee(period_end_balance, months, program["program_fee_bps"])
    a["balance_cents"] -= total_fee
    domain.recompute_ssi_posture(a)
    touch(a)
    return ok(domain.serialize_account(a))


@bp.post("/able/accounts/<aid>/investment-changes")
def investment_change(aid):
    user_id, role = get_identity()
    require_role(role, {"Beneficiary", "AuthorizedRepresentative"})
    a = find_or_404(db.accounts, aid, "Account")
    check_account_owner(a, role, user_id)
    body = get_body()
    require_string(body, "investment_option_id")
    find_or_404(db.investment_options, body["investment_option_id"], "InvestmentOption")
    program = db.programs[db.beneficiaries[a["beneficiary_id"]]["program_id"]]
    # ERR_INVESTMENT_CHANGE_LIMIT (priority 18)
    if domain.investment_changes_ytd(a) >= program["max_investment_changes_per_year"]:
        raise err("ERR_INVESTMENT_CHANGE_LIMIT",
                  "Investment-option change limit reached for the calendar year")
    a["investment_option_id"] = body["investment_option_id"]
    a.setdefault("_investment_change_dates", []).append(clock.iso())
    touch(a)
    return ok(domain.serialize_account(a))
