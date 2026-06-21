"""SideLetter routes (PRD §3.7)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import lookup, serialize
import validation as V

bp = Blueprint("side_letters", __name__)

READ_OPS_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer"]
PURPOSES = ("INVESTMENT", "MANAGEMENT_FEE", "EXPENSE")


@bp.route("/side-letters", methods=["POST"])
def create_side_letter():
    caller = authenticate()
    require_role(caller, ["ComplianceOfficer"])
    body = V.get_json_body()
    fund_id = V.require_string(body, "fund_id")
    lp_id = V.require_string(body, "lp_id")
    mfn_rank = V.require_int(body, "mfn_rank")
    fee_discount_bps = V.optional_int(body, "fee_discount_bps", 0)
    excused_purposes = V.optional_array(body, "excused_purposes", [])

    # Referential: Fund and LP must both exist (422).
    fund = db.funds.get(fund_id)
    lp = db.limited_partners.get(lp_id)
    if fund is None or lp is None:
        errors.fail(
            errors.ERR_INVALID_REFERENCE,
            "Side letter references a non-existent Fund or LP.",
        )

    # Range: mfn_rank >= 1; fee_discount_bps 0..1000.
    V.check_range(mfn_rank, "mfn_rank", lo=1)
    V.check_range(fee_discount_bps, "fee_discount_bps", lo=0, hi=1000)
    # excused_purposes must contain valid CapitalCall.purpose values.
    for p in excused_purposes:
        if p not in PURPOSES:
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "excused_purposes contains an invalid purpose.",
            )

    with db.lock:
        # mfn_rank unique per fund among PROPOSED/EXECUTED side letters.
        for sl in db.side_letters.values():
            if (
                sl["fund_id"] == fund_id
                and sl["status"] in ("PROPOSED", "EXECUTED")
                and sl["mfn_rank"] == mfn_rank
            ):
                errors.fail(errors.ERR_MFN_RANK_TAKEN, "mfn_rank already taken on this fund.")

        obj = db.stamp_new(
            {
                "fund_id": fund_id,
                "lp_id": lp_id,
                "mfn_rank": mfn_rank,
                "fee_discount_bps": fee_discount_bps,
                "excused_purposes": list(excused_purposes),
                "status": "PROPOSED",
            }
        )
        db.side_letters[obj["id"]] = obj
    return success(serialize.side_letter(obj), status=201)


@bp.route("/side-letters/<sid>", methods=["GET"])
def read_side_letter(sid):
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    obj = lookup.get_side_letter(sid)
    return success(serialize.side_letter(obj))


@bp.route("/side-letters", methods=["GET"])
def list_side_letters():
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    limit, offset = V.parse_pagination()
    fund_id = request.args.get("fund_id")
    lp_id = request.args.get("lp_id")
    status = request.args.get("status")
    items = list(db.side_letters.values())
    if fund_id is not None:
        items = [s for s in items if s["fund_id"] == fund_id]
    if lp_id is not None:
        items = [s for s in items if s["lp_id"] == lp_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.side_letter(o) for o in page], pagination=meta)


@bp.route("/side-letters/<sid>/execute", methods=["POST"])
def execute_side_letter(sid):
    caller = authenticate()
    require_role(caller, ["ComplianceOfficer"])
    with db.lock:
        sl = lookup.get_side_letter(sid)
        if sl["status"] != "PROPOSED":
            errors.fail(errors.ERR_INVALID_STATE, "Side letter is not PROPOSED.")
        sl["status"] = "EXECUTED"
        db.touch(sl)
    return success(serialize.side_letter(sl))
