"""Fund routes (PRD §3.1) + fee-accrual sub-resource list (§3.8)."""
from flask import Blueprint

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import derive, lookup, serialize
import validation as V

bp = Blueprint("funds", __name__)


@bp.route("/funds", methods=["POST"])
def create_fund():
    caller = authenticate()
    require_role(caller, ["FundManager"])
    body = V.get_json_body()

    name = V.require_string(body, "name")
    vintage_year = V.require_int(body, "vintage_year")
    target_size_cents = V.require_int(body, "target_size_cents")
    mgmt_fee_rate_bps = V.require_int(body, "mgmt_fee_rate_bps")
    carry_rate_bps = V.require_int(body, "carry_rate_bps")
    pref_rate_bps = V.require_int(body, "pref_rate_bps")
    gp_catchup_rate_bps = V.optional_int(body, "gp_catchup_rate_bps", 10000)
    recycling_cap_pct_bps = V.optional_int(body, "recycling_cap_pct_bps", 0)
    fee_offset_pct_bps = V.optional_int(body, "fee_offset_pct_bps", 0)

    # Range checks -> ERR_VALIDATION_LIMIT (422) (PRD §2.8 / §3.1).
    V.check_range(target_size_cents, "target_size_cents", lo=0)
    V.check_range(mgmt_fee_rate_bps, "mgmt_fee_rate_bps", lo=0, hi=1000)
    V.check_range(carry_rate_bps, "carry_rate_bps", lo=0, hi=5000)
    V.check_range(pref_rate_bps, "pref_rate_bps", lo=0, hi=3000)
    V.check_range(gp_catchup_rate_bps, "gp_catchup_rate_bps", lo=0, hi=10000)
    V.check_range(recycling_cap_pct_bps, "recycling_cap_pct_bps", lo=0)
    V.check_range(fee_offset_pct_bps, "fee_offset_pct_bps", lo=0, hi=10000)

    with db.lock:
        obj = db.stamp_new(
            {
                "name": name,
                "vintage_year": vintage_year,
                "target_size_cents": target_size_cents,
                "mgmt_fee_rate_bps": mgmt_fee_rate_bps,
                "carry_rate_bps": carry_rate_bps,
                "pref_rate_bps": pref_rate_bps,
                "gp_catchup_rate_bps": gp_catchup_rate_bps,
                "recycling_cap_pct_bps": recycling_cap_pct_bps,
                "fee_offset_pct_bps": fee_offset_pct_bps,
                "status": "FORMING",
            }
        )
        db.funds[obj["id"]] = obj
    return success(serialize.fund(obj), status=201)


READ_ALL_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer", "LimitedPartnerUser"]


@bp.route("/funds/<fid>", methods=["GET"])
def read_fund(fid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    obj = lookup.get_fund(fid)
    return success(serialize.fund(obj))


@bp.route("/funds", methods=["GET"])
def list_funds():
    caller = authenticate()
    require_role(caller, ["FundManager", "FundAdministrator", "ComplianceOfficer"])
    limit, offset = V.parse_pagination()
    from flask import request

    status = request.args.get("status")
    items = list(db.funds.values())
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.fund(o) for o in page], pagination=meta)


@bp.route("/funds/<fid>/activate", methods=["POST"])
def activate_fund(fid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        fund = lookup.get_fund(fid)
        if fund["status"] != "FORMING":
            errors.fail(errors.ERR_INVALID_STATE, "Fund is not in FORMING.")
        has_active = any(
            c["fund_id"] == fid and c["status"] == "ACTIVE"
            for c in db.commitments.values()
        )
        if not has_active:
            errors.fail(
                errors.ERR_COMMITMENT_NOT_ACCEPTED,
                "Fund has no accepted (ACTIVE) commitment.",
            )
        fund["status"] = "INVESTING"
        db.touch(fund)
    return success(serialize.fund(fund))


@bp.route("/funds/<fid>/begin-harvest", methods=["POST"])
def begin_harvest(fid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        fund = lookup.get_fund(fid)
        if fund["status"] != "INVESTING":
            errors.fail(errors.ERR_INVALID_STATE, "Fund is not in INVESTING.")
        fund["status"] = "HARVESTING"
        db.touch(fund)
    return success(serialize.fund(fund))


@bp.route("/funds/<fid>/wind-down", methods=["POST"])
def wind_down(fid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        fund = lookup.get_fund(fid)
        if fund["status"] != "HARVESTING":
            errors.fail(errors.ERR_INVALID_STATE, "Fund is not in HARVESTING.")
        # Blocked by an ISSUED call or an ACTIVE investment.
        has_issued_call = any(
            c["fund_id"] == fid and c["status"] == "ISSUED"
            for c in db.capital_calls.values()
        )
        has_active_inv = any(
            i["fund_id"] == fid and i["status"] == "ACTIVE"
            for i in db.investments.values()
        )
        if has_issued_call or has_active_inv:
            errors.fail(
                errors.ERR_WIND_DOWN_BLOCKED,
                "Wind-down blocked by an ISSUED call or ACTIVE investment.",
            )
        fund["status"] = "WOUND_DOWN"
        # Cascade: every ACTIVE commitment on this fund -> CLOSED.
        for c in db.commitments.values():
            if c["fund_id"] == fid and c["status"] == "ACTIVE":
                c["status"] = "CLOSED"
                db.touch(c)
        db.touch(fund)
    return success(serialize.fund(fund))


@bp.route("/funds/<fid>/nav", methods=["GET"])
def fund_nav(fid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    fund = lookup.get_fund(fid)
    data = {
        "fund_nav_cents": derive.fund_nav(fid),
        "total_called_cents": derive.fund_total_called(fid),
        "total_distributed_cents": derive.fund_total_distributed(fid),
        "recycled_to_date_cents": derive.fund_recycled_to_date(fid),
    }
    return success(data)
