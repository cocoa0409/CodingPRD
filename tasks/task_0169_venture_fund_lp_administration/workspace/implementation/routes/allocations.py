"""CapitalCallAllocation routes (PRD §3.3)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import capitalcall_state, lookup, serialize
import validation as V

bp = Blueprint("allocations", __name__)

READ_ALL_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer", "LimitedPartnerUser"]


@bp.route("/capital-call-allocations/<aid>", methods=["GET"])
def read_allocation(aid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    obj = lookup.get_allocation(aid)
    return success(serialize.capital_call_allocation(obj))


@bp.route("/capital-call-allocations", methods=["GET"])
def list_allocations():
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    limit, offset = V.parse_pagination()
    commitment_id = request.args.get("commitment_id")
    capital_call_id = request.args.get("capital_call_id")
    status = request.args.get("status")
    items = list(db.capital_call_allocations.values())
    if commitment_id is not None:
        items = [a for a in items if a["commitment_id"] == commitment_id]
    if capital_call_id is not None:
        items = [a for a in items if a["capital_call_id"] == capital_call_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.capital_call_allocation(o) for o in page], pagination=meta)


@bp.route("/capital-call-allocations/<aid>/fund", methods=["POST"])
def fund_allocation(aid):
    caller = authenticate()
    require_role(caller, ["FundAdministrator", "LimitedPartnerUser"])
    body = V.get_json_body()
    paid_amount_cents = V.require_int(body, "paid_amount_cents")

    with db.lock:
        alloc = lookup.get_allocation(aid)
        commitment = db.commitments[alloc["commitment_id"]]

        # Ownership (priority 3): LimitedPartnerUser must own the commitment.
        if caller.role == "LimitedPartnerUser" and caller.user_id != commitment["lp_id"]:
            errors.fail(errors.ERR_NOT_COMMITMENT_OWNER, "Not the commitment owner.")

        # State: allocation must be PENDING (transition PENDING -> PAID).
        if alloc["status"] != "PENDING":
            errors.fail(errors.ERR_INVALID_STATE, "Allocation is not PENDING.")

        # Full funding only: paid_amount_cents == allocated_amount_cents.
        if paid_amount_cents != alloc["allocated_amount_cents"]:
            errors.fail(
                errors.ERR_PARTIAL_FUNDING_NOT_ALLOWED,
                "Partial funding not allowed; must equal allocated amount.",
            )

        alloc["paid_amount_cents"] = alloc["allocated_amount_cents"]
        alloc["status"] = "PAID"
        db.touch(alloc)
        # Commitment.drawn_cents recomputed (derived); bump commitment.
        db.touch(commitment)
        # Parent call may settle (bubble up).
        call = db.capital_calls[alloc["capital_call_id"]]
        capitalcall_state.reevaluate_after_fund(call)
    return success(serialize.capital_call_allocation(alloc))


@bp.route("/capital-call-allocations/<aid>/default", methods=["POST"])
def default_allocation(aid):
    caller = authenticate()
    require_role(caller, ["FundAdministrator"])
    with db.lock:
        alloc = lookup.get_allocation(aid)
        # State: allocation must be PENDING (transition PENDING -> DEFAULTED).
        if alloc["status"] != "PENDING":
            errors.fail(errors.ERR_INVALID_STATE, "Allocation is not PENDING.")

        alloc["status"] = "DEFAULTED"
        db.touch(alloc)
        # Owning LP.default_strike_count recomputed (derived); bump the LP.
        commitment = db.commitments[alloc["commitment_id"]]
        lp = db.limited_partners.get(commitment["lp_id"])
        if lp:
            db.touch(lp)
        # Re-evaluate parent call: ISSUED -> PARTIALLY_DEFAULTED or DEFAULTED.
        call = db.capital_calls[alloc["capital_call_id"]]
        capitalcall_state.reevaluate_after_default(call)
    return success(serialize.capital_call_allocation(alloc))
