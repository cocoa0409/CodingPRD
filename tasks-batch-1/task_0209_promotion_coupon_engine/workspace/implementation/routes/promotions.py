"""Promotion lifecycle endpoints (PRD §3.2, §3.3)."""
from flask import Blueprint, request

from db import db, parse_dt
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_field,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)

bp = Blueprint("promotions", __name__)

PROMO_TYPES = {"PERCENT_OFF", "BOGO", "THRESHOLD"}
STACKING_CLASSES = {"EXCLUSIVE", "STACKABLE"}
ELIGIBILITY_MODES = {"ALL", "SEGMENT", "FIRST_ORDER"}


def _validate_threshold_tiers(tiers):
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise err("ERR_INVALID_REQUEST", "threshold_tiers must be a non-empty array")
    prev = None
    cleaned = []
    for t in tiers:
        if not isinstance(t, dict):
            raise err("ERR_INVALID_REQUEST", "threshold tier must be an object")
        if "min_subtotal_cents" not in t or "discount_cents" not in t:
            raise err("ERR_INVALID_REQUEST", "threshold tier missing fields")
        ms = t["min_subtotal_cents"]
        dc = t["discount_cents"]
        if isinstance(ms, bool) or not isinstance(ms, int):
            raise err("ERR_INVALID_REQUEST", "min_subtotal_cents must be an integer")
        if isinstance(dc, bool) or not isinstance(dc, int):
            raise err("ERR_INVALID_REQUEST", "discount_cents must be an integer")
        if prev is not None and ms <= prev:
            raise err(
                "ERR_INVALID_REQUEST", "threshold_tiers must be strictly ascending"
            )
        prev = ms
        cleaned.append({"min_subtotal_cents": ms, "discount_cents": dc})
    return cleaned


def _serialize_promotion(p):
    return serialize(p)


@bp.post("/promotions")
@require_roles("MerchantAdmin")
def create_promotion():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        name = require_str(body, "name")
        promo_type = require_field(body, "promo_type")
        if promo_type not in PROMO_TYPES:
            raise err("ERR_INVALID_REQUEST", "Invalid promo_type")
        stacking_class = require_field(body, "stacking_class")
        if stacking_class not in STACKING_CLASSES:
            raise err("ERR_INVALID_REQUEST", "Invalid stacking_class")

        eligibility_mode = body.get("eligibility_mode", "ALL")
        if eligibility_mode is None:
            eligibility_mode = "ALL"
        if eligibility_mode not in ELIGIBILITY_MODES:
            raise err("ERR_INVALID_REQUEST", "Invalid eligibility_mode")

        # Type-specific fields (validated for well-formedness at create; presence
        # for the chosen type is re-checked at activation, but bad shapes here are
        # ERR_INVALID_REQUEST per §3.2).
        percent_off = body.get("percent_off")
        bogo_sku = body.get("bogo_sku")
        threshold_tiers = body.get("threshold_tiers")

        if percent_off is not None:
            if isinstance(percent_off, bool) or not isinstance(
                percent_off, (int, float)
            ):
                raise err("ERR_INVALID_REQUEST", "percent_off must be a number")
            if not (0 < percent_off <= 1):
                raise err("ERR_INVALID_REQUEST", "percent_off must be in (0, 1]")
        if bogo_sku is not None and (not isinstance(bogo_sku, str) or bogo_sku == ""):
            raise err("ERR_INVALID_REQUEST", "bogo_sku must be a non-empty string")
        if threshold_tiers is not None:
            threshold_tiers = _validate_threshold_tiers(threshold_tiers)

        max_stacked = body.get("max_stacked_discount_pct")
        if max_stacked is not None:
            if isinstance(max_stacked, bool) or not isinstance(
                max_stacked, (int, float)
            ):
                raise err("ERR_INVALID_REQUEST", "max_stacked_discount_pct must be a number")
            if not (0 < max_stacked <= 1):
                raise err(
                    "ERR_INVALID_REQUEST", "max_stacked_discount_pct must be in (0, 1]"
                )

        budget_cap_cents = body.get("budget_cap_cents")
        if budget_cap_cents is not None:
            if isinstance(budget_cap_cents, bool) or not isinstance(
                budget_cap_cents, int
            ):
                raise err("ERR_INVALID_REQUEST", "budget_cap_cents must be an integer")
            if budget_cap_cents <= 0:
                raise err("ERR_INVALID_REQUEST", "budget_cap_cents must be > 0")

        max_per_customer = body.get("max_redemptions_per_customer")
        if max_per_customer is not None:
            if isinstance(max_per_customer, bool) or not isinstance(
                max_per_customer, int
            ):
                raise err(
                    "ERR_INVALID_REQUEST", "max_redemptions_per_customer must be an integer"
                )
            if max_per_customer <= 0:
                raise err(
                    "ERR_INVALID_REQUEST", "max_redemptions_per_customer must be > 0"
                )

        eligible_segment_id = body.get("eligible_segment_id")

        active_from = require_field(body, "active_from")
        active_until = require_field(body, "active_until")
        af = parse_dt(active_from)
        au = parse_dt(active_until)
        if af is None or au is None:
            raise err("ERR_INVALID_REQUEST", "active_from/active_until must be ISO 8601")
        # Window validity (priority 8).
        if not (au > af):
            raise err("ERR_INVALID_WINDOW", "active_until must be after active_from")

        # FK existence for eligible_segment_id (priority 4) when provided.
        if eligible_segment_id is not None:
            if eligible_segment_id not in db.segments:
                raise err(
                    "ERR_FK_NOT_FOUND",
                    "eligible_segment_id does not reference a segment",
                )

        rec = new_record(
            {
                "name": name,
                "promo_type": promo_type,
                "percent_off": percent_off,
                "bogo_sku": bogo_sku,
                "threshold_tiers": threshold_tiers,
                "stacking_class": stacking_class,
                "max_stacked_discount_pct": max_stacked,
                "eligibility_mode": eligibility_mode,
                "eligible_segment_id": eligible_segment_id,
                "active_from": active_from,
                "active_until": active_until,
                "budget_cap_cents": budget_cap_cents,
                "budget_consumed_cents": 0,
                "max_redemptions_per_customer": max_per_customer,
                "status": "DRAFT",
            }
        )
        db.promotions[rec["id"]] = rec
        return success(_serialize_promotion(rec), 201)


@bp.get("/promotions/<promotion_id>")
@require_roles("MerchantAdmin", "Shopper")
def get_promotion(promotion_id):
    with db.lock:
        p = db.promotions.get(promotion_id)
        if not p:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        return success(_serialize_promotion(p), 200)


@bp.get("/promotions")
@require_roles("MerchantAdmin", "Shopper")
def list_promotions():
    with db.lock:
        limit, offset = paginate(request.args)
        status = request.args.get("status")
        promo_type = request.args.get("promo_type")
        eligible_segment_id = request.args.get("eligible_segment_id")
        items = list(db.promotions.values())
        if status is not None:
            items = [p for p in items if p["status"] == status]
        if promo_type is not None:
            items = [p for p in items if p["promo_type"] == promo_type]
        if eligible_segment_id is not None:
            items = [
                p for p in items if p["eligible_segment_id"] == eligible_segment_id
            ]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list(
            [_serialize_promotion(p) for p in page], limit, offset, total
        )


@bp.post("/promotions/<promotion_id>/activate")
@require_roles("MerchantAdmin")
def activate_promotion(promotion_id):
    with db.lock:
        p = db.promotions.get(promotion_id)
        if not p:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        status = p["status"]
        if status not in ("DRAFT", "PAUSED"):
            raise err("ERR_INVALID_STATE", "Promotion cannot be activated from this state")

        if status == "DRAFT":
            # Type-specific config present (priority 7).
            ptype = p["promo_type"]
            if ptype == "PERCENT_OFF" and p["percent_off"] is None:
                raise err("ERR_PROMO_CONFIG_INVALID", "percent_off required")
            if ptype == "BOGO" and not p["bogo_sku"]:
                raise err("ERR_PROMO_CONFIG_INVALID", "bogo_sku required")
            if ptype == "THRESHOLD" and not p["threshold_tiers"]:
                raise err("ERR_PROMO_CONFIG_INVALID", "threshold_tiers required")
            if p["eligibility_mode"] == "SEGMENT":
                seg_id = p["eligible_segment_id"]
                if not seg_id or seg_id not in db.segments:
                    raise err(
                        "ERR_PROMO_CONFIG_INVALID",
                        "eligible_segment_id required for SEGMENT mode",
                    )
            # Window validity (priority 8).
            af = parse_dt(p["active_from"])
            au = parse_dt(p["active_until"])
            if not (au > af):
                raise err("ERR_INVALID_WINDOW", "active_until must be after active_from")
        else:  # PAUSED -> ACTIVE
            au = parse_dt(p["active_until"])
            if not (db.clock < au):
                raise err("ERR_INVALID_WINDOW", "clock is at or past active_until")

        p["status"] = "ACTIVE"
        touch(p)
        return success(_serialize_promotion(p), 200)


@bp.post("/promotions/<promotion_id>/pause")
@require_roles("MerchantAdmin")
def pause_promotion(promotion_id):
    with db.lock:
        p = db.promotions.get(promotion_id)
        if not p:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        if p["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Promotion is not ACTIVE")
        p["status"] = "PAUSED"
        touch(p)
        return success(_serialize_promotion(p), 200)


@bp.post("/promotions/<promotion_id>/archive")
@require_roles("MerchantAdmin")
def archive_promotion(promotion_id):
    with db.lock:
        p = db.promotions.get(promotion_id)
        if not p:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        status = p["status"]
        if status not in ("DRAFT", "PAUSED", "EXPIRED"):
            raise err("ERR_INVALID_STATE", "Promotion cannot be archived from this state")

        if status == "DRAFT":
            has_confirmed = any(
                r["promotion_id"] == promotion_id and r["status"] == "CONFIRMED"
                for r in db.coupon_redemptions.values()
            )
            if has_confirmed:
                raise err("ERR_INVALID_STATE", "Confirmed redemptions exist")
        elif status == "PAUSED":
            has_reserved = any(
                r["promotion_id"] == promotion_id and r["status"] == "RESERVED"
                for r in db.coupon_redemptions.values()
            )
            if has_reserved:
                raise err(
                    "ERR_PROMO_HAS_RESERVATIONS",
                    "Outstanding reserved redemptions exist",
                )

        p["status"] = "ARCHIVED"
        touch(p)
        # Cascade: disable all child coupons.
        for c in db.coupons.values():
            if c["promotion_id"] == promotion_id and c["status"] != "DISABLED":
                c["status"] = "DISABLED"
                touch(c)
        return success(_serialize_promotion(p), 200)
