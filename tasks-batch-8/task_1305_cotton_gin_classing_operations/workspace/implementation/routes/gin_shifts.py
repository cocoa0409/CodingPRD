"""GinShift routes."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_GIN_SHIFT_NOT_FOUND,
    ERR_SHIFT_NOT_OPEN,
    ERR_SHIFT_NOT_CLOSED,
    ERR_MODULES_STILL_GINNING,
    ERR_MASS_BALANCE_VIOLATION,
)
from middleware import get_context, require_role, parse_pagination, get_json_body, require_fields
from response import success_object
from services.core import stamp_new, touch, sorted_entities, paginate
from services.calc import allocate_seed_largest_remainder

bp = Blueprint("gin_shifts", __name__)


def shift_out(s):
    return {
        "id": s["id"],
        "season": s["season"],
        "stand_label": s["stand_label"],
        "status": s["status"],
        "actual_lint_scale_lbs": s.get("actual_lint_scale_lbs"),
        "actual_seed_scale_lbs": s.get("actual_seed_scale_lbs"),
        "waste_lbs": s.get("waste_lbs"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/gin-ops/gin-shifts", methods=["POST"])
def create_shift():
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    body = get_json_body()
    require_fields(body, ["season", "stand_label"])
    season = body["season"]
    stand_label = body["stand_label"]
    if not isinstance(season, str) or not season:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "season must be a non-empty string", status)
    if not isinstance(stand_label, str) or not stand_label:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "stand_label must be a non-empty string", status)
    shift = stamp_new({
        "season": season,
        "stand_label": stand_label,
        "status": "OPEN",
        "actual_lint_scale_lbs": None,
        "actual_seed_scale_lbs": None,
        "waste_lbs": None,
    })
    db.gin_shifts[shift["id"]] = shift
    return success_object(shift_out(shift), 201)


@bp.route("/gin-ops/gin-shifts/<sid>", methods=["GET"])
def get_shift(sid):
    user_id, role = get_context()
    s = db.gin_shifts.get(sid)
    if s is None:
        err_id, status = ERR_GIN_SHIFT_NOT_FOUND
        raise ApiError(err_id, "Gin shift not found", status)
    return success_object(shift_out(s))


@bp.route("/gin-ops/gin-shifts/<sid>/close", methods=["POST"])
def close_shift(sid):
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    shift = db.gin_shifts.get(sid)
    if shift is None:
        err_id, status = ERR_GIN_SHIFT_NOT_FOUND
        raise ApiError(err_id, "Gin shift not found", status)
    body = get_json_body()
    require_fields(body, ["actual_lint_scale_lbs", "actual_seed_scale_lbs", "waste_lbs"])
    vals = {}
    for f in ("actual_lint_scale_lbs", "actual_seed_scale_lbs", "waste_lbs"):
        v = body[f]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, f"{f} must be a non-negative integer", status)
        vals[f] = v
    if shift["status"] != "OPEN":
        err_id, status = ERR_SHIFT_NOT_OPEN
        raise ApiError(err_id, "Shift is not OPEN", status)
    # no module of this shift may be GINNING
    for m in db.modules.values():
        if m.get("gin_shift_id") == sid and m["status"] == "GINNING":
            err_id, status = ERR_MODULES_STILL_GINNING
            raise ApiError(err_id, "A module of this shift is still GINNING", status)
    ginned = [
        m for m in db.modules.values()
        if m.get("gin_shift_id") == sid and m["status"] == "GINNED"
    ]
    sum_net = sum(m["net_weight_lbs"] for m in ginned)
    sum_lint = sum(m.get("actual_lint_lbs", 0) for m in ginned)
    if sum_net != vals["actual_lint_scale_lbs"] + vals["actual_seed_scale_lbs"] + vals["waste_lbs"]:
        err_id, status = ERR_MASS_BALANCE_VIOLATION
        raise ApiError(err_id, "Mass balance violation: module net weights do not equal lint + seed + waste", status)
    if vals["actual_lint_scale_lbs"] != sum_lint:
        err_id, status = ERR_MASS_BALANCE_VIOLATION
        raise ApiError(err_id, "Mass balance violation: actual_lint_scale_lbs != sum of module lint", status)
    shift["actual_lint_scale_lbs"] = vals["actual_lint_scale_lbs"]
    shift["actual_seed_scale_lbs"] = vals["actual_seed_scale_lbs"]
    shift["waste_lbs"] = vals["waste_lbs"]
    shift["status"] = "CLOSED"
    touch(shift)
    return success_object(shift_out(shift))


@bp.route("/gin-ops/gin-shifts/<sid>/reconcile", methods=["POST"])
def reconcile_shift(sid):
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    shift = db.gin_shifts.get(sid)
    if shift is None:
        err_id, status = ERR_GIN_SHIFT_NOT_FOUND
        raise ApiError(err_id, "Gin shift not found", status)
    if shift["status"] != "CLOSED":
        err_id, status = ERR_SHIFT_NOT_CLOSED
        raise ApiError(err_id, "Shift is not CLOSED", status)
    allocate_seed_largest_remainder(shift)
    shift["status"] = "RECONCILED"
    touch(shift)
    return success_object(shift_out(shift))


@bp.route("/gin-ops/gin-shifts/<sid>/seed-sales", methods=["GET"])
def list_shift_seed_sales(sid):
    user_id, role = get_context()
    shift = db.gin_shifts.get(sid)
    if shift is None:
        err_id, status = ERR_GIN_SHIFT_NOT_FOUND
        raise ApiError(err_id, "Gin shift not found", status)
    limit, offset = parse_pagination()
    items = [s for s in db.seed_sales.values() if s["gin_shift_id"] == sid]
    items = sorted_entities(items)
    from routes.seed_sales import seed_sale_out
    return paginate([seed_sale_out(s) for s in items], limit, offset)
