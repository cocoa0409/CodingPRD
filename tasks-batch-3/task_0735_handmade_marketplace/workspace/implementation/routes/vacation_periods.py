"""VacationPeriod endpoints."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner
from db import store, new_id, now, parse_iso
from envelope import success
from errors import (
    raise_err, ERR_VALIDATION, ERR_VACATION_PERIOD_NOT_FOUND,
    ERR_SHOP_NOT_FOUND, ERR_VACATION_OVERLAP,
)
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import vacation_period_view
from services import find_shop

bp = Blueprint("vacation_periods", __name__)


@bp.route("/seller/vacation-periods", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    body = get_json_body()
    shop_id = require_field(body, "shop_id", str)
    starts_s = require_field(body, "starts_at", str)
    ends_s = require_field(body, "ends_at", str)
    require_shop_owner(user_id, role, shop_id)
    if find_shop(shop_id) is None:
        raise_err(ERR_SHOP_NOT_FOUND, "shop not found")
    try:
        starts_at = parse_iso(starts_s)
        ends_at = parse_iso(ends_s)
    except Exception:
        raise_err(ERR_VALIDATION, "invalid ISO timestamp")
    if not (ends_at > starts_at):
        raise_err(ERR_VALIDATION, "ends_at must be strictly greater than starts_at")

    # Overlap check on half-open intervals: [a, b) overlaps [c, d) iff a < d AND c < b.
    for vp in store.vacation_periods.values():
        if vp["shop_id"] != shop_id:
            continue
        if vp["status"] != "SCHEDULED":
            continue
        a = vp["starts_at"]; b = vp["ends_at"]
        if starts_at < b and a < ends_at:
            raise_err(ERR_VACATION_OVERLAP, "overlaps existing vacation period")

    message = opt_field(body, "message", str, None)
    rec = {
        "id": new_id(),
        "created_at": now(),
        "shop_id": shop_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
        "message": message,
        "_seq": store.next_seq(),
    }
    store.vacation_periods[rec["id"]] = rec
    return success(vacation_period_view(rec), status=201)


@bp.route("/seller/vacation-periods/<vp_id>", methods=["GET"])
def fetch(vp_id):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    vp = store.vacation_periods.get(vp_id)
    if vp is None:
        raise_err(ERR_VACATION_PERIOD_NOT_FOUND, "not found")
    require_shop_owner(user_id, role, vp["shop_id"])
    return success(vacation_period_view(vp))


@bp.route("/seller/vacation-periods", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    status = request.args.get("status")
    items = list(store.vacation_periods.values())
    if shop_id is not None:
        items = [x for x in items if x["shop_id"] == shop_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if role == "Seller":
        items = [x for x in items if x["shop_id"] == user_id]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([vacation_period_view(x) for x in page], response_type="array", pagination=pmeta)
