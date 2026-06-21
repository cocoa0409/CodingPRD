"""Purchase routes: ingest, list, read, cancel-duplicate, promote."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_EXTERNAL_PURCHASE,
    ERR_STALE_VERSION,
)
from middleware import require_auth, current_role, current_user_id, get_json_body
from response import ok_object, ok_array, paginate
from services.pagination import parse_pagination, sort_by_created
from services.wedding import (
    get_registry_item_or_404,
    get_purchase_or_404,
    assert_couple_owns,
    assert_not_archived,
)
from services.registry import classify_new_purchase, recompute_after_purchase_mutation
from services.thankyou import auto_create_thank_you, delete_thank_you_for_purchase

bp = Blueprint("purchases", __name__)


# -------- POST /registry-items/{id}/purchases --------------------------------

@bp.route("/registry-items/<rid>/purchases", methods=["POST"])
def ingest_purchase(rid):
    require_auth(["PlatformIntegration", "Couple"])()
    ri = get_registry_item_or_404(rid)
    w = db.weddings.get(ri["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "RegistryItem has no wedding")
    if current_role() == "Couple":
        assert_couple_owns(w)
    assert_not_archived(w)

    body = get_json_body()
    platform_code = body.get("platform_code")
    external_purchase_id = body.get("external_purchase_id")
    purchaser_name = body.get("purchaser_name")
    quantity = body.get("quantity")
    occurred_at = body.get("occurred_at")

    if not isinstance(platform_code, str) or not platform_code:
        raise APIError(ERR_INVALID_REQUEST, 400, "platform_code is required")
    if not isinstance(external_purchase_id, str) or not external_purchase_id:
        raise APIError(ERR_INVALID_REQUEST, 400, "external_purchase_id is required")
    if not isinstance(purchaser_name, str) or not purchaser_name:
        raise APIError(ERR_INVALID_REQUEST, 400, "purchaser_name is required")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "quantity must be an integer >= 1")
    if not isinstance(occurred_at, str) or not occurred_at:
        raise APIError(ERR_INVALID_REQUEST, 400, "occurred_at is required")
    try:
        db.parse_iso(occurred_at)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "occurred_at must be ISO-8601")

    # Idempotency on (platform_code, external_purchase_id).
    for p in db.purchases.values():
        if (p.get("platform_code") == platform_code
                and p.get("external_purchase_id") == external_purchase_id):
            if int(p.get("quantity", 0)) != int(quantity):
                # True conflict.
                raise APIError(ERR_DUPLICATE_EXTERNAL_PURCHASE, 409,
                               "Same external key with different quantity")
            # Idempotent replay: return existing row WITHOUT mutation, status 200.
            return ok_object(p, 200)

    # RegistryItem must be OPEN at ingest time.
    if ri.get("status") != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409,
                       "RegistryItem must be OPEN to accept new purchases")

    # Create purchase row.
    new_purchase = {
        "registry_item_id": rid,
        "platform_code": platform_code,
        "external_purchase_id": external_purchase_id,
        "purchaser_name": purchaser_name,
        "quantity": quantity,
        "occurred_at": occurred_at,
        "status": "CONFIRMED",  # tentative; classify will adjust
        "dup_of_purchase_id": None,
    }
    db.stamp_common(new_purchase)
    db.purchases[new_purchase["id"]] = new_purchase

    # Classify (mutates new_purchase and recomputes aggregates on registry_item).
    classify_new_purchase(ri, new_purchase)

    # Auto-create ThankYouNote if the resulting status is CONFIRMED.
    if new_purchase.get("status") == "CONFIRMED":
        auto_create_thank_you(new_purchase, ri["wedding_id"])

    return ok_object(new_purchase, 201)


# -------- GET /registry-items/{id}/purchases ---------------------------------

@bp.route("/registry-items/<rid>/purchases", methods=["GET"])
def list_purchases_of_registry_item(rid):
    require_auth(["Couple", "PlatformIntegration", "PlatformAdmin"])()
    ri = get_registry_item_or_404(rid)
    if current_role() == "Couple":
        w = db.weddings.get(ri["wedding_id"])
        if w:
            assert_couple_owns(w)
    limit, offset = parse_pagination()
    raw_include = request.args.get("include_pending")
    include_pending = (raw_include is not None and raw_include.lower() in ("true", "1", "yes"))
    status_filter = request.args.get("status")
    rows = [p for p in db.purchases.values() if p.get("registry_item_id") == rid]
    if status_filter is not None:
        rows = [p for p in rows if p.get("status") == status_filter]
    elif not include_pending:
        # Default: surface CONFIRMED and CANCELLED only, not PENDING_REVIEW.
        rows = [p for p in rows if p.get("status") != "PENDING_REVIEW"]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


# -------- GET /purchases/{id} ------------------------------------------------

@bp.route("/purchases/<pid>", methods=["GET"])
def get_purchase(pid):
    require_auth(["Couple", "PlatformIntegration", "PlatformAdmin"])()
    p = get_purchase_or_404(pid)
    if current_role() == "Couple":
        ri = db.registry_items.get(p["registry_item_id"])
        if ri:
            w = db.weddings.get(ri["wedding_id"])
            if w:
                assert_couple_owns(w)
    return ok_object(p)


# -------- GET /purchases -----------------------------------------------------

@bp.route("/purchases", methods=["GET"])
def list_purchases():
    require_auth(["Couple", "PlatformIntegration", "PlatformAdmin"])()
    limit, offset = parse_pagination()
    dup_of = request.args.get("dup_of_purchase_id")
    status_f = request.args.get("status")
    rows = list(db.purchases.values())
    if current_role() == "Couple":
        # Scope to weddings owned by this couple.
        owned = {w["id"] for w in db.weddings.values()
                 if w.get("couple_user_id") == current_user_id()}
        owned_ri_ids = {r["id"] for r in db.registry_items.values()
                        if r.get("wedding_id") in owned}
        rows = [p for p in rows if p.get("registry_item_id") in owned_ri_ids]
    if dup_of is not None:
        rows = [p for p in rows if p.get("dup_of_purchase_id") == dup_of]
    if status_f is not None:
        rows = [p for p in rows if p.get("status") == status_f]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


# -------- POST /purchases/{id}/cancel-duplicate -----------------------------

@bp.route("/purchases/<pid>/cancel-duplicate", methods=["POST"])
def cancel_purchase(pid):
    require_auth(["Couple"])()
    p = get_purchase_or_404(pid)
    ri = db.registry_items.get(p["registry_item_id"])
    if ri is None:
        raise APIError(ERR_INVALID_STATE, 409, "RegistryItem missing")
    w = db.weddings.get(ri["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)

    body = get_json_body()
    expected = body.get("expected_registry_item_version")
    if expected is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_registry_item_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_registry_item_version must be an integer")

    # State precondition: cancellable from CONFIRMED or PENDING_REVIEW.
    if p.get("status") not in ("CONFIRMED", "PENDING_REVIEW"):
        raise APIError(ERR_INVALID_STATE, 409, "Purchase is not cancellable")
    if expected != ri.get("version"):
        raise APIError(ERR_STALE_VERSION, 412, "expected_registry_item_version mismatch")

    p["status"] = "CANCELLED"
    db.bump(p)
    # Hard-delete any ThankYouNote on this purchase.
    delete_thank_you_for_purchase(p["id"])
    # Recompute aggregates on registry item.
    recompute_after_purchase_mutation(ri)
    return ok_object(p)


# -------- POST /purchases/{id}/promote --------------------------------------

@bp.route("/purchases/<pid>/promote", methods=["POST"])
def promote_purchase(pid):
    require_auth(["Couple"])()
    p = get_purchase_or_404(pid)
    ri = db.registry_items.get(p["registry_item_id"])
    if ri is None:
        raise APIError(ERR_INVALID_STATE, 409, "RegistryItem missing")
    w = db.weddings.get(ri["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)

    body = get_json_body()
    expected = body.get("expected_registry_item_version")
    if expected is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_registry_item_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_registry_item_version must be an integer")

    if p.get("status") != "PENDING_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Purchase must be PENDING_REVIEW to promote")
    if ri.get("status") != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "RegistryItem must be OPEN to promote a purchase")
    if expected != ri.get("version"):
        raise APIError(ERR_STALE_VERSION, 412, "expected_registry_item_version mismatch")

    p["status"] = "CONFIRMED"
    p["dup_of_purchase_id"] = None
    db.bump(p)
    recompute_after_purchase_mutation(ri)
    auto_create_thank_you(p, ri["wedding_id"])
    return ok_object(p)
