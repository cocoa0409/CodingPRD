"""Order placement, modification, cancellation."""

from datetime import timedelta

from flask import Blueprint, g

from clock import CLOCK
from db import DB, LOCK, new_id
from errors import (
    addon_exhausted,
    cross_project,
    forbidden,
    invalid_state,
    modification_window_closed,
    not_found,
    reward_exhausted,
    shipping_required,
    validation_error,
)
from middleware import require_roles
from response import success_object
from services.audit import append_audit, append_escrow
from services.common import bump_version, check_occ, get_json_body, require_positive_int, stamp_create
from services.projects import recompute_provisional
from services.serializers import order_view


bp = Blueprint("orders", __name__)


def _validate_addons_payload(addons):
    if addons is None:
        return []
    if not isinstance(addons, list):
        raise validation_error("add_ons must be a list")
    cleaned = []
    for entry in addons:
        if not isinstance(entry, dict):
            raise validation_error("each add_ons entry must be an object")
        ao_id = entry.get("add_on_item_id")
        qty = entry.get("quantity")
        if not isinstance(ao_id, str) or not ao_id:
            raise validation_error("add_ons entry requires add_on_item_id")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise validation_error("add_ons quantity must be a positive integer")
        cleaned.append({"add_on_item_id": ao_id, "quantity": qty})
    return cleaned


def _resolve_reward_for_order(reward_id, project_id):
    reward = DB.rewards.get(reward_id)
    if reward is None:
        raise not_found()
    if reward["project_id"] != project_id:
        raise cross_project()
    return reward


def _resolve_addons_for_order(addons, project_id):
    """Return list of (addon_record, quantity) pairs after validating cross-project membership."""
    out = []
    for entry in addons:
        ao = DB.add_on_items.get(entry["add_on_item_id"])
        if ao is None:
            raise not_found()
        if ao["project_id"] != project_id:
            raise cross_project()
        out.append((ao, entry["quantity"]))
    return out


def _shipping_required_for(reward, addon_pairs):
    if reward["reward_type"] == "PHYSICAL":
        return True
    for ao, _qty in addon_pairs:
        if ao.get("requires_shipping", False):
            return True
    return False


def _compute_locked_at(project, created_at):
    deadline = project.get("deadline")
    plus72 = created_at + timedelta(hours=72)
    if deadline is None:
        return plus72
    return min(deadline, plus72)


def _aggregate_addon_quantities(addons):
    """Aggregate quantities across duplicate add_on_item_id entries: returns dict[id]=qty."""
    out = {}
    for entry in addons:
        out[entry["add_on_item_id"]] = out.get(entry["add_on_item_id"], 0) + entry["quantity"]
    return out


@bp.route("/orders", methods=["POST"])
@require_roles("Backer")
def create_order():
    body = get_json_body()
    project_id = body.get("project_id")
    reward_id = body.get("reward_id")
    if not isinstance(project_id, str) or not project_id:
        raise validation_error("project_id required")
    if not isinstance(reward_id, str) or not reward_id:
        raise validation_error("reward_id required")
    add_ons = _validate_addons_payload(body.get("add_ons"))
    shipping_address = body.get("shipping_address")
    if shipping_address is not None and not isinstance(shipping_address, dict):
        raise validation_error("shipping_address must be an object")
    payment_method_token = body.get("payment_method_token")
    if not isinstance(payment_method_token, str) or not payment_method_token:
        raise validation_error("payment_method_token required")

    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        if project["status"] != "LIVE":
            raise invalid_state("Project not LIVE")

        reward = _resolve_reward_for_order(reward_id, project_id)
        addon_pairs = _resolve_addons_for_order(add_ons, project_id)

        if _shipping_required_for(reward, addon_pairs) and not shipping_address:
            raise shipping_required()

        # Inventory checks: reward then add-ons
        if reward.get("inventory_limit") is not None:
            if int(reward.get("inventory_claimed", 0)) + 1 > int(reward["inventory_limit"]):
                raise reward_exhausted()
        # Aggregate add-on requested quantities (duplicates summed)
        addon_qty = {}
        for ao, qty in addon_pairs:
            addon_qty[ao["id"]] = addon_qty.get(ao["id"], 0) + qty
        for ao_id, qty in addon_qty.items():
            ao = DB.add_on_items[ao_id]
            if ao.get("inventory_limit") is not None:
                if int(ao.get("inventory_claimed", 0)) + qty > int(ao["inventory_limit"]):
                    raise addon_exhausted()

        # All checks pass — claim inventory atomically
        reward["inventory_claimed"] = int(reward.get("inventory_claimed", 0)) + 1
        bump_version(reward)
        for ao_id, qty in addon_qty.items():
            ao = DB.add_on_items[ao_id]
            ao["inventory_claimed"] = int(ao.get("inventory_claimed", 0)) + qty
            bump_version(ao)

        # Snapshot pledge & compute totals
        pledge_amount_cents = int(reward["pledge_amount_cents"])
        add_ons_total_cents = sum(int(DB.add_on_items[ao_id]["price_cents"]) * qty for ao_id, qty in addon_qty.items())
        order_total_cents = pledge_amount_cents + add_ons_total_cents

        now = CLOCK.now()
        order = stamp_create({
            "id": new_id(),
            "project_id": project_id,
            "backer_id": g.user_id,
            "reward_id": reward_id,
            "add_ons": list(add_ons),
            "shipping_address": shipping_address,
            "payment_method_token": payment_method_token,
            "pledge_amount_cents": pledge_amount_cents,
            "add_ons_total_cents": add_ons_total_cents,
            "order_total_cents": order_total_cents,
            "payment_status": "AUTHORIZED",
            # PRD §3.4: 'the order is persisted with payment_status
            # AUTHORIZED and fulfillment_status NOT_STARTED.' Even DIGITAL
            # orders begin at NOT_STARTED; transition to NOT_APPLICABLE is
            # a downstream side effect (PRD §3.7).
            "fulfillment_status": "NOT_STARTED",
            "charge_attempts": 0,
            "order_modification_locked_at": _compute_locked_at(project, now),
            "refundable_remainder_cents": 0,
        })
        DB.orders[order["id"]] = order

        append_escrow(project_id, order["id"], "AUTH_HOLD", amount_cents=order_total_cents)
        append_audit(
            subject_type="ORDER",
            subject_id=order["id"],
            event_type="STATUS_CHANGE",
            payload={"from": None, "to": "AUTHORIZED", "amount_cents": order_total_cents},
            actor_role=g.role,
            actor_id=g.user_id,
        )
        recompute_provisional(project)

    return success_object(order_view(order), status=201)


@bp.route("/orders/<id>", methods=["GET"])
@require_roles("Backer", "Initiator", "PlatformAdmin")
def get_order(id):
    with LOCK:
        order = DB.orders.get(id)
        if order is None:
            raise not_found()
        # Ownership: backers see own orders; initiators see orders on their project
        if g.role == "Backer" and order["backer_id"] != g.user_id:
            raise forbidden()
        if g.role == "Initiator":
            project = DB.projects.get(order["project_id"])
            if project is None or project["initiator_id"] != g.user_id:
                raise forbidden()
        return success_object(order_view(order))


@bp.route("/orders/<id>", methods=["PATCH"])
@require_roles("Backer")
def patch_order(id):
    body = get_json_body()
    with LOCK:
        order = DB.orders.get(id)
        if order is None:
            raise not_found()
        if order["backer_id"] != g.user_id:
            raise forbidden()
        # Project state check first
        project = DB.projects.get(order["project_id"])
        if project is None:
            raise not_found()
        if project["status"] != "LIVE":
            raise invalid_state("Project not LIVE")
        # Order payment state must be AUTHORIZED for modification
        if order["payment_status"] != "AUTHORIZED":
            raise invalid_state("Order not AUTHORIZED")
        now = CLOCK.now()
        if now >= order["order_modification_locked_at"]:
            raise modification_window_closed()
        check_occ(order, body)

        new_reward_id = body.get("reward_id", order["reward_id"])
        new_add_ons = _validate_addons_payload(body["add_ons"]) if "add_ons" in body else list(order["add_ons"])
        new_shipping = body.get("shipping_address", order["shipping_address"]) if "shipping_address" in body else order["shipping_address"]
        new_token = body.get("payment_method_token", order["payment_method_token"])
        if not isinstance(new_token, str) or not new_token:
            raise validation_error("payment_method_token must be non-empty")

        new_reward = _resolve_reward_for_order(new_reward_id, project["id"])
        new_addon_pairs = _resolve_addons_for_order(new_add_ons, project["id"])

        if _shipping_required_for(new_reward, new_addon_pairs) and not new_shipping:
            raise shipping_required()

        # Compute reward-claim delta
        old_reward = DB.rewards.get(order["reward_id"])
        reward_changed = old_reward is None or old_reward["id"] != new_reward["id"]

        if reward_changed and new_reward.get("inventory_limit") is not None:
            if int(new_reward.get("inventory_claimed", 0)) + 1 > int(new_reward["inventory_limit"]):
                raise reward_exhausted()

        # Add-on deltas: aggregate old vs new
        old_qty = _aggregate_addon_quantities(order["add_ons"])
        new_qty = _aggregate_addon_quantities(new_add_ons)
        delta = {}
        for ao_id, q in new_qty.items():
            delta[ao_id] = delta.get(ao_id, 0) + q
        for ao_id, q in old_qty.items():
            delta[ao_id] = delta.get(ao_id, 0) - q

        # Validate add-on inventory accommodating delta
        for ao_id, d in delta.items():
            if d <= 0:
                continue
            ao = DB.add_on_items.get(ao_id)
            if ao is None:
                raise not_found()
            if ao["project_id"] != project["id"]:
                raise cross_project()
            if ao.get("inventory_limit") is not None:
                if int(ao.get("inventory_claimed", 0)) + d > int(ao["inventory_limit"]):
                    raise addon_exhausted()

        # Apply changes
        if reward_changed:
            if old_reward is not None:
                old_reward["inventory_claimed"] = max(0, int(old_reward.get("inventory_claimed", 0)) - 1)
                bump_version(old_reward)
            new_reward["inventory_claimed"] = int(new_reward.get("inventory_claimed", 0)) + 1
            bump_version(new_reward)
        for ao_id, d in delta.items():
            if d == 0:
                continue
            ao = DB.add_on_items[ao_id]
            ao["inventory_claimed"] = max(0, int(ao.get("inventory_claimed", 0)) + d)
            bump_version(ao)

        order["reward_id"] = new_reward["id"]
        order["add_ons"] = list(new_add_ons)
        order["shipping_address"] = new_shipping
        order["payment_method_token"] = new_token
        order["pledge_amount_cents"] = int(new_reward["pledge_amount_cents"])
        order["add_ons_total_cents"] = sum(int(DB.add_on_items[ao_id]["price_cents"]) * q for ao_id, q in new_qty.items())
        order["order_total_cents"] = int(order["pledge_amount_cents"]) + int(order["add_ons_total_cents"])
        # PRD §3.4 enumerates which fields are recomputed on modification
        # (pledge_amount_cents, add_ons_total_cents, order_total_cents,
        # provisional_raised_cents, version). fulfillment_status is not
        # touched here.
        bump_version(order)

        recompute_provisional(project)
        return success_object(order_view(order))


@bp.route("/orders/<id>/cancel", methods=["POST"])
@require_roles("Backer", "PlatformAdmin")
def cancel_order(id):
    with LOCK:
        order = DB.orders.get(id)
        if order is None:
            raise not_found()
        # Backer must own the order
        if g.role == "Backer" and order["backer_id"] != g.user_id:
            raise forbidden()
        # Order must be AUTHORIZED
        if order["payment_status"] != "AUTHORIZED":
            raise invalid_state("Order not AUTHORIZED")
        project = DB.projects.get(order["project_id"])
        if project is None:
            raise not_found()
        # If backer-initiated: must still be in window and project LIVE
        if g.role == "Backer":
            if project["status"] != "LIVE":
                raise invalid_state("Project not LIVE")
            now = CLOCK.now()
            if now >= order["order_modification_locked_at"]:
                raise modification_window_closed()

        order["payment_status"] = "VOIDED"
        bump_version(order)
        # Reverse inventory
        reward = DB.rewards.get(order["reward_id"])
        if reward is not None:
            reward["inventory_claimed"] = max(0, int(reward.get("inventory_claimed", 0)) - 1)
            bump_version(reward)
        for entry in order["add_ons"]:
            ao = DB.add_on_items.get(entry["add_on_item_id"])
            if ao is None:
                continue
            ao["inventory_claimed"] = max(0, int(ao.get("inventory_claimed", 0)) - int(entry["quantity"]))
            bump_version(ao)

        append_escrow(project["id"], order["id"], "CHARGE_VOID", amount_cents=0)
        append_audit(
            subject_type="ORDER",
            subject_id=order["id"],
            event_type="STATUS_CHANGE",
            payload={"from": "AUTHORIZED", "to": "VOIDED"},
            actor_role=g.role,
            actor_id=g.user_id,
        )
        recompute_provisional(project)
        return success_object(order_view(order))
