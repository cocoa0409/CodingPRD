"""ManagementFeeAccrual routes (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import dates, fee, lookup, serialize
import validation as V

bp = Blueprint("fee_accruals", __name__)

READ_OPS_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer"]


def _overlaps(a_start, a_end, b_start, b_end):
    # Half-open intervals [start, end). Adjacency at a shared endpoint allowed.
    return a_start < b_end and b_start < a_end


@bp.route("/funds/<fid>/fee-accruals", methods=["POST"])
def create_fee_accrual(fid):
    caller = authenticate()
    require_role(caller, ["FundAdministrator"])
    body = V.get_json_body()
    period_start = V.require(body, "period_start")
    period_end = V.require(body, "period_end")

    with db.lock:
        fund = lookup.get_fund(fid)

        start_dt = dates.parse_dt(period_start)
        end_dt = dates.parse_dt(period_end)
        if start_dt is None or end_dt is None:
            errors.fail(errors.ERR_INVALID_PERIOD, "Invalid period dates.")
        # period_end must be strictly after period_start.
        if not (end_dt > start_dt):
            errors.fail(errors.ERR_INVALID_PERIOD, "period_end must be after period_start.")

        # Must not overlap an existing non-REVERSED accrual on the same fund.
        for acc in db.management_fee_accruals.values():
            if acc["fund_id"] != fid or acc["status"] == "REVERSED":
                continue
            os = dates.parse_dt(acc["period_start"])
            oe = dates.parse_dt(acc["period_end"])
            if _overlaps(start_dt, end_dt, os, oe):
                errors.fail(
                    errors.ERR_FEE_PERIOD_OVERLAP,
                    "Period overlaps an existing non-REVERSED accrual.",
                )

        gross, offset_applied, net = fee.compute_fee(fund, period_start, period_end)
        obj = db.stamp_new(
            {
                "fund_id": fid,
                "period_start": period_start,
                "period_end": period_end,
                "gross_fee_cents": gross,
                "offset_applied_cents": offset_applied,
                "net_fee_cents": net,
                "status": "ACCRUED",
            }
        )
        db.management_fee_accruals[obj["id"]] = obj
    return success(serialize.management_fee_accrual(obj), status=201)


@bp.route("/funds/<fid>/fee-accruals", methods=["GET"])
def list_fee_accruals(fid):
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    lookup.get_fund(fid)
    limit, offset = V.parse_pagination()
    status = request.args.get("status")
    items = [a for a in db.management_fee_accruals.values() if a["fund_id"] == fid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.management_fee_accrual(o) for o in page], pagination=meta)


@bp.route("/fee-accruals/<aid>", methods=["GET"])
def read_fee_accrual(aid):
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    obj = lookup.get_fee_accrual(aid)
    return success(serialize.management_fee_accrual(obj))
