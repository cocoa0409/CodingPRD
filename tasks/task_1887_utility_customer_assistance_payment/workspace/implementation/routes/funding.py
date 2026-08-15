"""FundingSource + FundAllocation endpoints (PRD §3.8)."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_INVALID_STATE,
                    ERR_ENROLLMENT_REQUIRED, ERR_ENROLLMENT_NO_LONGER_ACTIVE,
                    ERR_INSUFFICIENT_ASSISTANCE_FUNDS, ERR_ALLOCATION_NOT_PLEDGED)
from middleware import authenticate
from response import success_object, success_list
from serializers import funding_source as ser_fund, fund_allocation as ser_alloc
from services.common import (touch_account, adjust_arrearage, active_enrollment,
                             auto_cancel_open_order)
from services.funds import (recompute_fund_counters, eligible_funds,
                            run_waterfall, report_for)
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("funding", __name__)

FUNDER_TYPES = {"LIHEAP", "UTILITY_TRUST", "STATE_GRANT"}
FUND_STATUSES = {"OPEN", "SUSPENDED", "CLOSED"}
ALLOC_STATUSES = {"PLEDGED", "DISBURSED", "RELEASED"}
TIERS = {"TIER_1", "TIER_2", "TIER_3"}
RW_ROLES = ["CustomerServiceRep", "ProgramAdmin"]


def get_fund_or_404(source_id):
    f = db.funding_sources.get(source_id)
    if f is None:
        raise not_found("Funding source not found")
    return f


def get_alloc_or_404(allocation_id):
    a = db.fund_allocations.get(allocation_id)
    if a is None:
        raise not_found("Fund allocation not found")
    return a


# --- funding sources ----------------------------------------------------------

@bp.route("/assistance/funding-sources", methods=["POST"])
def create_fund():
    authenticate(["ProgramAdmin"])
    body = validate_shape(get_body(allow_empty=False), [
        ("name", "string", True, None),
        ("funder_type", "enum", True, FUNDER_TYPES),
        ("fiscal_year", "int", True, None),
        ("appropriated_cents", "int", True, (1, None)),
        ("priority_rank", "int", True, None),
        ("eligible_tiers", "enum_list", True, TIERS),
        ("requires_completed_referral", "bool", False, None),
    ])
    fund = {
        "id": db.new_id(),
        "name": body["name"],
        "funder_type": body["funder_type"],
        "fiscal_year": body["fiscal_year"],
        "appropriated_cents": body["appropriated_cents"],
        "priority_rank": body["priority_rank"],
        "eligible_tiers": list(dict.fromkeys(body["eligible_tiers"])),
        "requires_completed_referral": bool(body.get("requires_completed_referral") or False),
        "status": "OPEN",
        "pledged_cents": 0,
        "disbursed_cents": 0,
        "released_cents": 0,
        "available_cents": body["appropriated_cents"],
    }
    db.stamp_common(fund)
    db.funding_sources[fund["id"]] = fund
    return success_object(ser_fund(fund), status=201)


@bp.route("/assistance/funding-sources/<source_id>", methods=["GET"])
def get_fund(source_id):
    authenticate(RW_ROLES)
    f = get_fund_or_404(source_id)
    recompute_fund_counters(f)
    return success_object(ser_fund(f))


@bp.route("/assistance/funding-sources", methods=["GET"])
def list_funds():
    authenticate(RW_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"status": FUND_STATUSES, "fiscal_year": "int"})
    items = sort_by_creation(db.funding_sources.values())
    for f in items:
        recompute_fund_counters(f)
    if "status" in filters:
        items = [x for x in items if x["status"] == filters["status"]]
    if "fiscal_year" in filters:
        items = [x for x in items if x["fiscal_year"] == filters["fiscal_year"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_fund(x) for x in page], limit, offset, total)


@bp.route("/assistance/funding-sources/<source_id>/suspend", methods=["POST"])
def suspend_fund(source_id):
    authenticate(["ProgramAdmin"])
    f = get_fund_or_404(source_id)
    if f["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Suspend requires fund status OPEN")
    f["status"] = "SUSPENDED"
    db.touch(f)
    recompute_fund_counters(f)
    return success_object(ser_fund(f))


@bp.route("/assistance/funding-sources/<source_id>/close", methods=["POST"])
def close_fund(source_id):
    authenticate(["ProgramAdmin"])
    f = get_fund_or_404(source_id)
    if f["status"] not in ("OPEN", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Close requires fund status OPEN|SUSPENDED")
    f["status"] = "CLOSED"
    db.touch(f)
    # every PLEDGED allocation on this fund -> RELEASED
    for a in db.fund_allocations.values():
        if a["funding_source_id"] == f["id"] and a["status"] == "PLEDGED":
            a["status"] = "RELEASED"
            db.touch(a)
    recompute_fund_counters(f)
    return success_object(ser_fund(f))


@bp.route("/assistance/funding-sources/<source_id>/report", methods=["GET"])
def fund_report(source_id):
    authenticate(["ProgramAdmin"])
    f = get_fund_or_404(source_id)
    recompute_fund_counters(f)
    return success_object(report_for(f))


# --- fund allocations ---------------------------------------------------------

@bp.route("/assistance/fund-allocations", methods=["POST"])
def create_allocations():
    authenticate(["ProgramAdmin"])
    body = validate_shape(get_body(allow_empty=False), [
        ("account_id", "string", True, None),
        ("amount_cents", "int", True, (1, None)),
    ])
    account = db.accounts.get(body["account_id"])
    if account is None:
        raise not_found("Account not found")
    # enrollment check precedes fund sufficiency (PRD §3.8)
    enrollment = active_enrollment(account["id"])
    if enrollment is None:
        raise ApiError(ERR_ENROLLMENT_REQUIRED, 422,
                       "Fund allocation requires an ACTIVE enrollment on the account")
    ordered = eligible_funds(account, enrollment)
    if sum(f["available_cents"] for f in ordered) < body["amount_cents"]:
        raise ApiError(ERR_INSUFFICIENT_ASSISTANCE_FUNDS, 422,
                       "Eligible-fund pool available total is below the request")
    created = run_waterfall(account, enrollment, body["amount_cents"])
    return success_list([ser_alloc(a) for a in created],
                        len(created), 0, len(created), status=201)


@bp.route("/assistance/fund-allocations/<allocation_id>", methods=["GET"])
def get_allocation(allocation_id):
    authenticate(RW_ROLES)
    a = get_alloc_or_404(allocation_id)
    return success_object(ser_alloc(a))


@bp.route("/assistance/fund-allocations", methods=["GET"])
def list_allocations():
    authenticate(RW_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"funding_source_id": "str", "account_id": "str",
                             "enrollment_id": "str", "status": ALLOC_STATUSES,
                             "batch_id": "str"})
    items = sort_by_creation(db.fund_allocations.values())
    for key in ("funding_source_id", "account_id", "enrollment_id", "status",
                "batch_id"):
        if key in filters:
            items = [x for x in items if x[key] == filters[key]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_alloc(x) for x in page], limit, offset, total)


@bp.route("/assistance/fund-allocations/<allocation_id>/disburse", methods=["POST"])
def disburse(allocation_id):
    authenticate(["ProgramAdmin"])
    a = get_alloc_or_404(allocation_id)
    if a["status"] != "PLEDGED":
        raise ApiError(ERR_ALLOCATION_NOT_PLEDGED, 409,
                       "Disburse requires allocation status PLEDGED")
    enrollment = db.enrollments.get(a["enrollment_id"])
    if enrollment is None or enrollment["status"] != "ACTIVE":
        raise ApiError(ERR_ENROLLMENT_NO_LONGER_ACTIVE, 422,
                       "Pinned enrollment is no longer ACTIVE")
    account = db.accounts.get(a["account_id"])
    a["status"] = "DISBURSED"
    db.touch(a)
    fund = db.funding_sources.get(a["funding_source_id"])
    if fund is not None:
        recompute_fund_counters(fund)
        db.touch(fund)
    if account is not None:
        applied = min(a["amount_cents"], account["arrearage_balance_cents"])
        adjust_arrearage(account, -applied)
        remainder = a["amount_cents"] - applied
        if remainder > 0:
            account["credit_balance_cents"] += remainder
        auto_cancel_open_order(account)
        touch_account(account)
    return success_object(ser_alloc(a))


@bp.route("/assistance/fund-allocations/<allocation_id>/release", methods=["POST"])
def release(allocation_id):
    authenticate(["ProgramAdmin"])
    a = get_alloc_or_404(allocation_id)
    if a["status"] != "PLEDGED":
        raise ApiError(ERR_ALLOCATION_NOT_PLEDGED, 409,
                       "Release requires allocation status PLEDGED")
    a["status"] = "RELEASED"
    db.touch(a)
    fund = db.funding_sources.get(a["funding_source_id"])
    if fund is not None:
        recompute_fund_counters(fund)
        db.touch(fund)
    return success_object(ser_alloc(a))
