"""Commitment routes (PRD §3.2) + LP statement (§3.8)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import capitalcall_state, derive, lookup, serialize, statement
import validation as V

bp = Blueprint("commitments", __name__)

READ_ALL_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer", "LimitedPartnerUser"]


@bp.route("/commitments", methods=["POST"])
def create_commitment():
    caller = authenticate()
    require_role(caller, ["FundManager", "FundAdministrator"])
    body = V.get_json_body()

    fund_id = V.require_string(body, "fund_id")
    lp_id = V.require_string(body, "lp_id")
    committed_cents = V.require_int(body, "committed_cents")

    # Existence (404) is checked before referential (422), per §2.8.
    # FK resolution left-to-right.
    fund = db.funds.get(fund_id)
    lp = db.limited_partners.get(lp_id)
    if fund is None or lp is None:
        errors.fail(errors.ERR_INVALID_REFERENCE, "Commitment references a non-existent Fund or LP.")

    # committed_cents must be at least 1 cent.
    V.check_range(committed_cents, "committed_cents", lo=1)

    with db.lock:
        obj = db.stamp_new(
            {
                "fund_id": fund_id,
                "lp_id": lp_id,
                "committed_cents": committed_cents,
                "status": "PENDING",
                "recycled_restored_cents": 0,
            }
        )
        db.commitments[obj["id"]] = obj
    return success(serialize.commitment(obj), status=201)


@bp.route("/commitments/<cid>", methods=["GET"])
def read_commitment(cid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    obj = lookup.get_commitment(cid)
    return success(serialize.commitment(obj))


@bp.route("/commitments", methods=["GET"])
def list_commitments():
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    limit, offset = V.parse_pagination()
    fund_id = request.args.get("fund_id")
    lp_id = request.args.get("lp_id")
    status = request.args.get("status")
    items = list(db.commitments.values())
    if fund_id is not None:
        items = [c for c in items if c["fund_id"] == fund_id]
    if lp_id is not None:
        items = [c for c in items if c["lp_id"] == lp_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.commitment(o) for o in page], pagination=meta)


@bp.route("/commitments/<cid>/accept", methods=["POST"])
def accept_commitment(cid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        commitment = lookup.get_commitment(cid)
        fund = db.funds[commitment["fund_id"]]
        if commitment["status"] != "PENDING":
            errors.fail(errors.ERR_INVALID_STATE, "Commitment is not PENDING.")
        if fund["status"] not in ("FORMING", "INVESTING"):
            errors.fail(errors.ERR_INVALID_STATE, "Fund is not in FORMING or INVESTING.")
        commitment["status"] = "ACTIVE"
        db.touch(commitment)
        # Acceptance recomputes the fund's total_committed_cents (derived at
        # read time); bump the fund so version/updated_at reflect the change.
        db.touch(fund)
    return success(serialize.commitment(commitment))


@bp.route("/commitments/<cid>/declare-default", methods=["POST"])
def declare_default(cid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        commitment = lookup.get_commitment(cid)
        if commitment["status"] != "ACTIVE":
            errors.fail(errors.ERR_INVALID_STATE, "Commitment is not ACTIVE.")
        # Permitted only when the owning LP's default_strike_count >= 1.
        strikes = derive.lp_default_strike_count(commitment["lp_id"])
        if strikes < 1:
            errors.fail(
                errors.ERR_INVALID_STATE,
                "LP has not reached the strike limit.",
            )
        commitment["status"] = "DEFAULTED"
        db.touch(commitment)
        # Cascade: PENDING allocations on this commitment -> DEFAULTED.
        affected_calls = set()
        for a in db.capital_call_allocations.values():
            if a["commitment_id"] == cid and a["status"] == "PENDING":
                a["status"] = "DEFAULTED"
                db.touch(a)
                affected_calls.add(a["capital_call_id"])
        # Re-evaluate affected parent calls (ISSUED -> PARTIALLY_DEFAULTED/DEFAULTED).
        for call_id in affected_calls:
            call = db.capital_calls.get(call_id)
            if call:
                capitalcall_state.reevaluate_after_default(call)
    return success(serialize.commitment(commitment))


@bp.route("/commitments/<cid>/statement", methods=["GET"])
def commitment_statement(cid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    commitment = lookup.get_commitment(cid)
    # LimitedPartnerUser ownership (priority 3): X-User-ID == commitment.lp_id.
    if caller.role == "LimitedPartnerUser" and caller.user_id != commitment["lp_id"]:
        errors.fail(errors.ERR_NOT_COMMITMENT_OWNER, "Not the commitment owner.")
    return success(statement.build_statement(commitment))
