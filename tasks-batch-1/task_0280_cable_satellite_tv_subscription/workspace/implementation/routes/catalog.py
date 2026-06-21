"""Catalog configuration endpoints (PRD §3.1, §4).

ChannelPackage, PremiumChannel, EquipmentModel, PromotionOffer,
RegionalSportsFeeRule, Technician.

Creation is BillingAdmin-exclusive; listing is shared per the §4 role table.
ChannelPackage/PremiumChannel/EquipmentModel/PromotionOffer carry created_at,
updated_at, version. Technician and RegionalSportsFeeRule are immutable
reference data carrying only id and created_at (PRD §2.4).
"""

from flask import Blueprint, request

import db
import errors
from clock import now_iso8601
from middleware import get_identity, require_role
from response import object_response
from services import common

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# ChannelPackage
# ---------------------------------------------------------------------------
@bp.route("/channel-packages", methods=["POST"])
def create_channel_package():
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    body = common.get_json_body()
    tier_code = common.require_str(body, "tier_code")
    if tier_code not in ("BASIC", "PLUS", "PREMIER"):
        raise errors.validation("tier_code must be one of BASIC, PLUS, PREMIER")
    name = common.require_str(body, "name")
    monthly_fee_cents = common.require_int(body, "monthly_fee_cents", minimum=0)
    channel_count = common.require_int(body, "channel_count", minimum=0)
    rank = common.require_int(body, "rank")
    if rank < 1 or rank > 3:
        raise errors.validation("rank must be 1..3")
    active = common.optional_bool(body, "active", True)
    created_at, updated_at, version = db.stamp_new()
    rec = {
        "id": db.new_id(),
        "tier_code": tier_code,
        "name": name,
        "monthly_fee_cents": monthly_fee_cents,
        "channel_count": channel_count,
        "rank": rank,
        "active": active,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.channel_packages[rec["id"]] = rec
    return object_response(rec, 201)


@bp.route("/channel-packages", methods=["GET"])
def list_channel_packages():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    items = list(db.channel_packages.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    return common.paginate_and_respond(items)


@bp.route("/channel-packages/<pid>", methods=["GET"])
def get_channel_package(pid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    rec = db.channel_packages.get(pid)
    if rec is None:
        raise errors.catalog_not_found("Channel package not found")
    return object_response(rec, 200)


# ---------------------------------------------------------------------------
# PremiumChannel
# ---------------------------------------------------------------------------
@bp.route("/premium-channels", methods=["POST"])
def create_premium_channel():
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    body = common.get_json_body()
    code = common.require_str(body, "code")
    name = common.require_str(body, "name")
    kind = common.require_str(body, "kind")
    if kind not in ("PREMIUM", "ADD_ON"):
        raise errors.validation("kind must be PREMIUM or ADD_ON")
    monthly_fee_cents = common.require_int(body, "monthly_fee_cents", minimum=0)
    min_package_rank = common.require_int(body, "min_package_rank")
    if min_package_rank < 1 or min_package_rank > 3:
        raise errors.validation("min_package_rank must be 1..3")
    active = common.optional_bool(body, "active", True)
    created_at, updated_at, version = db.stamp_new()
    rec = {
        "id": db.new_id(),
        "code": code,
        "name": name,
        "kind": kind,
        "monthly_fee_cents": monthly_fee_cents,
        "min_package_rank": min_package_rank,
        "active": active,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.premium_channels[rec["id"]] = rec
    return object_response(rec, 201)


@bp.route("/premium-channels", methods=["GET"])
def list_premium_channels():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    items = list(db.premium_channels.values())
    kind = request.args.get("kind")
    if kind is not None:
        items = [p for p in items if p["kind"] == kind]
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    return common.paginate_and_respond(items)


# ---------------------------------------------------------------------------
# EquipmentModel
# ---------------------------------------------------------------------------
@bp.route("/equipment-models", methods=["POST"])
def create_equipment_model():
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    body = common.get_json_body()
    model_code = common.require_str(body, "model_code")
    kind = common.require_str(body, "kind")
    if kind not in ("BOX", "DVR"):
        raise errors.validation("kind must be BOX or DVR")
    monthly_lease_cents = common.require_int(body, "monthly_lease_cents", minimum=0)
    replacement_cost_cents = common.require_int(body, "replacement_cost_cents", minimum=0)
    active = common.optional_bool(body, "active", True)
    created_at, updated_at, version = db.stamp_new()
    rec = {
        "id": db.new_id(),
        "model_code": model_code,
        "kind": kind,
        "monthly_lease_cents": monthly_lease_cents,
        "replacement_cost_cents": replacement_cost_cents,
        "active": active,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.equipment_models[rec["id"]] = rec
    return object_response(rec, 201)


@bp.route("/equipment-models", methods=["GET"])
def list_equipment_models():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.equipment_models.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    return common.paginate_and_respond(items)


# ---------------------------------------------------------------------------
# PromotionOffer
# ---------------------------------------------------------------------------
@bp.route("/promotion-offers", methods=["POST"])
def create_promotion_offer():
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    body = common.get_json_body()
    code = common.require_str(body, "code")
    discount_kind = common.require_str(body, "discount_kind")
    if discount_kind not in ("PERCENT_OFF_PACKAGE", "FLAT_OFF_TOTAL", "EQUIPMENT_WAIVER"):
        raise errors.validation("invalid discount_kind")
    # percent_off in 0..1 (number), defaults 0
    percent_off = body.get("percent_off", 0)
    if percent_off is None:
        percent_off = 0
    if isinstance(percent_off, bool) or not isinstance(percent_off, (int, float)):
        raise errors.invalid_request("percent_off must be a number")
    if percent_off < 0 or percent_off > 1:
        raise errors.validation("percent_off must be in 0..1")
    flat_off_cents = common.optional_int(body, "flat_off_cents", 0, minimum=0)
    promo_months = common.require_int(body, "promo_months", minimum=1)
    requires_min_rank = common.require_int(body, "requires_min_rank")
    if requires_min_rank < 1 or requires_min_rank > 3:
        raise errors.validation("requires_min_rank must be 1..3")
    rollback_protected = common.optional_bool(body, "rollback_protected", False)
    active = common.optional_bool(body, "active", True)
    created_at, updated_at, version = db.stamp_new()
    rec = {
        "id": db.new_id(),
        "code": code,
        "discount_kind": discount_kind,
        "percent_off": percent_off,
        "flat_off_cents": flat_off_cents,
        "promo_months": promo_months,
        "requires_min_rank": requires_min_rank,
        "rollback_protected": rollback_protected,
        "active": active,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.promotion_offers[rec["id"]] = rec
    return object_response(rec, 201)


@bp.route("/promotion-offers", methods=["GET"])
def list_promotion_offers():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.promotion_offers.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    return common.paginate_and_respond(items)


# ---------------------------------------------------------------------------
# RegionalSportsFeeRule (immutable reference data — id + created_at only)
# ---------------------------------------------------------------------------
@bp.route("/regional-sports-fee-rules", methods=["POST"])
def create_rsf_rule():
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    body = common.get_json_body()
    state_code = common.require_str(body, "state_code")
    base_fee_cents = common.require_int(body, "base_fee_cents", minimum=0)
    premier_surcharge_cents = common.require_int(body, "premier_surcharge_cents", minimum=0)
    active = common.optional_bool(body, "active", True)
    rec = {
        "id": db.new_id(),
        "state_code": state_code,
        "base_fee_cents": base_fee_cents,
        "premier_surcharge_cents": premier_surcharge_cents,
        "active": active,
        "created_at": now_iso8601(),
    }
    db.regional_sports_fee_rules[rec["id"]] = rec
    return object_response(rec, 201)


@bp.route("/regional-sports-fee-rules", methods=["GET"])
def list_rsf_rules():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.regional_sports_fee_rules.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    return common.paginate_and_respond(items)


# ---------------------------------------------------------------------------
# Technician (immutable reference data — id + created_at only)
# ---------------------------------------------------------------------------
@bp.route("/technicians", methods=["POST"])
def create_technician():
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    body = common.get_json_body()
    name = common.require_str(body, "name")
    home_state_code = common.require_str(body, "home_state_code")
    active = common.optional_bool(body, "active", True)
    rec = {
        "id": db.new_id(),
        "name": name,
        "home_state_code": home_state_code,
        "active": active,
        "created_at": now_iso8601(),
    }
    db.technicians[rec["id"]] = rec
    return object_response(rec, 201)


@bp.route("/technicians", methods=["GET"])
def list_technicians():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.technicians.values())
    home_state_code = request.args.get("home_state_code")
    if home_state_code is not None:
        items = [t for t in items if t["home_state_code"] == home_state_code]
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [t for t in items if t["active"] == want]
    return common.paginate_and_respond(items)
