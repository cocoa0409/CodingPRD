"""Card lifecycle endpoints."""
from flask import Blueprint, request, g
from clock import now, to_iso_ms, whole_days_between
from db import state, new_id
from errors import raise_err
from response import success_object, success_array
from middleware import require_roles, is_role
from routes.helpers import get_json, parse_pagination, paginate, sort_by_created, require_member_ownership
from serializers import (
    serialize_card, serialize_freeze_episode, serialize_transfer_record,
    serialize_renewal_reminder,
)
from services import card as card_svc


bp = Blueprint("cards", __name__)


def _ownership_check(card):
    """Member callers must own the card."""
    if is_role("Member") and card["holder_member_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN", "member does not own card")


@bp.route("/cards", methods=["POST"])
def issue_card_route():
    require_roles("PlatformAdmin", "StaffOps")
    body = get_json()
    card_type_id = body.get("card_type_id")
    holder_member_id = body.get("holder_member_id")
    if not card_type_id or not holder_member_id:
        raise_err("ERR_VALIDATION", "card_type_id and holder_member_id required")
    card = card_svc.issue_card(card_type_id, holder_member_id)
    return success_object(serialize_card(card), status=201)


@bp.route("/cards/<id_>", methods=["GET"])
def get_card_route(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    _ownership_check(card)
    return success_object(serialize_card(card))


@bp.route("/cards", methods=["GET"])
def list_cards():
    require_roles("PlatformAdmin", "StaffOps", "Member")
    limit, offset = parse_pagination()
    items = list(state["cards"].values())
    holder = request.args.get("holder_member_id")
    if holder:
        items = [c for c in items if c["holder_member_id"] == holder]
    if is_role("Member"):
        items = [c for c in items if c["holder_member_id"] == g.user_id]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    items = sort_by_created(items)
    sliced, meta = paginate(items, limit, offset)
    return success_array([serialize_card(x) for x in sliced], meta)


@bp.route("/cards/<id_>/activate", methods=["POST"])
def activate(id_):
    require_roles("PlatformAdmin", "StaffOps")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    card_svc.activate_card(card)
    return success_object(serialize_card(card))


@bp.route("/cards/<id_>/freeze", methods=["POST"])
def freeze(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    _ownership_check(card)
    body = get_json()
    reason = body.get("reason")
    requested_days = body.get("requested_days")
    if reason not in ("ILLNESS", "BUSINESS_TRIP"):
        raise_err("ERR_VALIDATION", "reason invalid")
    if not isinstance(requested_days, int) or requested_days < 1:
        raise_err("ERR_VALIDATION", "requested_days >= 1")
    fe = card_svc.freeze_card(card, reason, requested_days)
    return success_object(serialize_freeze_episode(fe), status=201)


@bp.route("/cards/<id_>/unfreeze", methods=["POST"])
def unfreeze(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    _ownership_check(card)
    body = get_json()
    fe_id = body.get("freeze_episode_id")
    if not fe_id:
        raise_err("ERR_VALIDATION", "freeze_episode_id required")
    fe = card_svc.cancel_freeze_early(card, fe_id)
    return success_object(serialize_freeze_episode(fe))


@bp.route("/cards/<id_>/refund", methods=["POST"])
def refund(id_):
    require_roles("PlatformAdmin", "StaffOps")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    # Refund and write audit
    card_svc.refund_card(card)
    # Write audit
    from db import next_order
    audit = {
        "id": new_id(),
        "actor_role": g.user_role,
        "actor_id": g.user_id,
        "action": "CARD_REFUND",
        "target_entity": f"Card:{card['id']}",
        "payload": {"after": {"status": "REFUNDED"}},
        "created_at": now(),
        "_order": next_order(),
    }
    state["audit_log"][audit["id"]] = audit
    return success_object(serialize_card(card))


@bp.route("/cards/<id_>/refund-preview", methods=["GET"])
def refund_preview(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    _ownership_check(card)
    fwd = card_svc.remaining_value_forward(card)
    chrono = card_svc.remaining_value_chronological(card)
    return success_object({
        "card_id": card["id"],
        "forward_looking_remaining_value_cents": fwd,
        "chronological_remaining_value_cents": chrono,
    })


@bp.route("/cards/<id_>/transfer", methods=["POST"])
def transfer(id_):
    require_roles("PlatformAdmin", "StaffOps")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    body = get_json()
    to_member_id = body.get("to_member_id")
    if not to_member_id:
        raise_err("ERR_VALIDATION", "to_member_id required")
    tr = card_svc.transfer_card(card, to_member_id, g.user_role, g.user_id)
    return success_object(serialize_transfer_record(tr))


@bp.route("/cards/<id_>/renewal-quote", methods=["GET"])
def renewal_quote_route(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    _ownership_check(card)
    return success_object(card_svc.renewal_quote(card))


@bp.route("/cards/<id_>/send-reminder", methods=["POST"])
def send_reminder_route(id_):
    require_roles("PlatformAdmin", "StaffOps")
    card = state["cards"].get(id_)
    if not card:
        raise_err("ERR_NOT_FOUND", "card not found")
    body = get_json()
    tier = body.get("tier")
    r = card_svc.send_reminder(card, tier)
    return success_object(serialize_renewal_reminder(r), status=201)
