"""Access events (turnstile entry)."""
from flask import Blueprint, request, g
from db import state, new_id, next_order
from clock import now
from errors import raise_err
from response import success_object
from middleware import require_roles
from routes.helpers import get_json
from services import card as card_svc


bp = Blueprint("access", __name__)


@bp.route("/access-events", methods=["POST"])
def create_access():
    require_roles("StaffOps", "PlatformAdmin")
    body = get_json()
    card_id = body.get("card_id")
    member_id = body.get("member_id")
    if not card_id or not member_id:
        raise_err("ERR_VALIDATION", "card_id and member_id required")
    card = state["cards"].get(card_id)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    member = state["members"].get(member_id)
    if not member:
        raise_err("ERR_NOT_FOUND", "member not found")
    # Active card?
    if card["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "card not ACTIVE")
    # Family share rule
    if card["holder_member_id"] != member_id:
        holder = state["members"].get(card["holder_member_id"])
        fg_h = holder.get("family_group_id") if holder else None
        fg_m = member.get("family_group_id")
        if not fg_h or fg_h != fg_m:
            raise_err("ERR_FAMILY_SHARE_NOT_AUTHORIZED", "family group mismatch")
    # Visits remaining
    ct = state["card_types"].get(card["card_type_id"])
    vr = card_svc.visits_remaining(card)
    if vr is not None and vr <= 0:
        raise_err("ERR_CARD_VISITS_EXHAUSTED", "card visits exhausted")
    # Consume
    card["visits_consumed"] = card.get("visits_consumed", 0) + 1
    from db import bump
    bump(card)
    # Expire if exhausted on PER_VISIT
    if ct and ct.get("visit_quota", 0) > 0 and card["visits_consumed"] >= ct["visit_quota"]:
        card_svc.expire_card(card)
    return success_object({
        "card_id": card_id,
        "member_id": member_id,
        "visits_consumed": card["visits_consumed"],
        "card_status": card["status"],
        "recorded_at": now().isoformat().replace("+00:00", "Z"),
    }, status=201)
