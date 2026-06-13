"""Capital-call routes (PRD §3.3) with OCC on Fund.version (§2.7)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import capital_call as cc_service
from services import dates, lookup, serialize
import validation as V

bp = Blueprint("capital_calls", __name__)

READ_ALL_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer", "LimitedPartnerUser"]
PURPOSES = ("INVESTMENT", "MANAGEMENT_FEE", "EXPENSE")


@bp.route("/capital-calls", methods=["POST"])
def issue_capital_call():
    caller = authenticate()
    require_role(caller, ["FundManager"])
    body = V.get_json_body()

    fund_id = V.require_string(body, "fund_id")
    purpose = V.require_enum(body, "purpose", PURPOSES)
    called_amount_cents = V.require_int(body, "called_amount_cents")
    due_date = V.require(body, "due_date")
    expected_fund_version = V.require_int(body, "expected_fund_version")

    with db.lock:
        # Existence (404) before body validation effects.
        fund = lookup.get_fund(fund_id)

        # Range: called_amount_cents >= 1.
        V.check_range(called_amount_cents, "called_amount_cents", lo=1)

        # due_date must be a valid date not in the past (ERR_INVALID_PERIOD).
        parsed_due = dates.parse_dt(due_date)
        if parsed_due is None:
            errors.fail(errors.ERR_INVALID_PERIOD, "due_date is not a valid date.")
        if parsed_due < dates.now_utc():
            errors.fail(errors.ERR_INVALID_PERIOD, "due_date is in the past.")

        # OCC: expected_fund_version must equal current Fund.version (412).
        if expected_fund_version != fund["version"]:
            errors.fail(errors.ERR_STALE_FUND_VERSION, "Stale fund version.")

        call = cc_service.issue_call(fund, purpose, called_amount_cents, due_date)
        # Issuance increments Fund.version by 1.
        db.touch(fund)
    return success(serialize.capital_call(call), status=201)


@bp.route("/capital-calls/<call_id>", methods=["GET"])
def read_capital_call(call_id):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    obj = lookup.get_capital_call(call_id)
    return success(serialize.capital_call(obj))


@bp.route("/capital-calls", methods=["GET"])
def list_capital_calls():
    caller = authenticate()
    require_role(caller, ["FundManager", "FundAdministrator", "ComplianceOfficer"])
    limit, offset = V.parse_pagination()
    fund_id = request.args.get("fund_id")
    status = request.args.get("status")
    items = list(db.capital_calls.values())
    if fund_id is not None:
        items = [c for c in items if c["fund_id"] == fund_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.capital_call(o) for o in page], pagination=meta)


@bp.route("/capital-calls/<call_id>/cancel", methods=["POST"])
def cancel_capital_call(call_id):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        call = lookup.get_capital_call(call_id)
        if call["status"] != "ISSUED":
            errors.fail(errors.ERR_INVALID_STATE, "Call is not ISSUED.")
        allocs = [
            a
            for a in db.capital_call_allocations.values()
            if a["capital_call_id"] == call_id
        ]
        if any(a["status"] == "PAID" for a in allocs):
            errors.fail(errors.ERR_INVALID_STATE, "Call has a PAID allocation.")
        call["status"] = "CANCELLED"
        db.touch(call)
        # Cascade: every allocation -> WAIVED.
        for a in allocs:
            a["status"] = "WAIVED"
            db.touch(a)
    return success(serialize.capital_call(call))


@bp.route("/capital-calls/<call_id>/allocations", methods=["GET"])
def list_call_allocations(call_id):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    lookup.get_capital_call(call_id)
    limit, offset = V.parse_pagination()
    items = [
        a
        for a in db.capital_call_allocations.values()
        if a["capital_call_id"] == call_id
    ]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.capital_call_allocation(o) for o in page], pagination=meta)
