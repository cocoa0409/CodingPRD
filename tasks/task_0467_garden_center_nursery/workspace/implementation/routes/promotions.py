"""SeasonalPromotion endpoints."""
from flask import Blueprint, request

import errors
from clock import parse_iso8601, to_iso8601_millis
from db import db, base_versioned, touch
from errors import err
from lookups import body, get_nursery
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from validation import req_str, req_enum, req_int_in_range, req_datetime

bp = Blueprint("promotions", __name__)

SCOPES = {"LIVE_PLANT", "BULK_MATERIAL", "DRY_GOOD", "ALL"}


def promotion_view(p):
    return {
        "id": p["id"],
        "nursery_id": p["nursery_id"],
        "name": p["name"],
        "category_scope": p["category_scope"],
        "discount_pct": p["discount_pct"],
        "starts_at": to_iso8601_millis(p["starts_at"]),
        "ends_at": to_iso8601_millis(p["ends_at"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _scopes_collide(a, b):
    return a == b or a == "ALL" or b == "ALL"


@bp.post("/nurseries/<nursery_id>/promotions")
@require_roles("SalesClerk")
def create_promotion(nursery_id):
    get_nursery(nursery_id)
    data = body()
    name = req_str(data, "name")
    scope = req_enum(data, "category_scope", SCOPES)
    discount_pct = req_int_in_range(data, "discount_pct", 0, 60)
    starts_at = req_datetime(data, "starts_at")
    ends_at = req_datetime(data, "ends_at")
    if not (ends_at > starts_at):
        err(errors.ERR_INVALID_REQUEST, "ends_at must be after starts_at")

    # Promotion-window overlap vs colliding-scope SCHEDULED/ACTIVE on same nursery.
    # Plain half-open [starts_at, ends_at) intersection, no buffer; abutting ok.
    for other in db.promotions.values():
        if other["nursery_id"] != nursery_id:
            continue
        if other["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if not _scopes_collide(scope, other["category_scope"]):
            continue
        if starts_at < other["ends_at"] and other["starts_at"] < ends_at:
            err(errors.ERR_PROMOTION_WINDOW_CONFLICT, "promotion window overlaps")

    p = base_versioned()
    p.update({
        "nursery_id": nursery_id,
        "name": name,
        "category_scope": scope,
        "discount_pct": discount_pct,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
    })
    db.promotions[p["id"]] = p
    return created(promotion_view(p))


@bp.get("/nurseries/<nursery_id>/promotions")
@require_roles("SalesClerk", "InventoryManager")
def list_promotions(nursery_id):
    get_nursery(nursery_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    scope = request.args.get("category_scope")
    items = [p for p in db.promotions.values() if p["nursery_id"] == nursery_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if scope is not None:
        items = [p for p in items if p["category_scope"] == scope]
    items.sort(key=lambda p: p["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([promotion_view(p) for p in page], limit, offset, total)


@bp.post("/promotions/<promo_id>/activate")
@require_roles("SalesClerk")
def activate_promotion(promo_id):
    p = db.promotions.get(promo_id)
    if p is None:
        # No dedicated promotion-not-found error in catalogue; nearest path-id is
        # nursery scope but the promo id itself is path-referenced. Use 404 via
        # a generic not-found is not catalogued; the spec only lists the resource
        # not-founds it enumerates. Promotion id resolution failures are not
        # exercised by a dedicated error; treat as nursery-style 404 fallback.
        err(errors.ERR_NURSERY_NOT_FOUND, "promotion not found")
    p["status"] = "ACTIVE"
    touch(p)
    return ok(promotion_view(p))
