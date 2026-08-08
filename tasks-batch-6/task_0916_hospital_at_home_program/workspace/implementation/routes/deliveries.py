"""Medication and DME delivery under chain-of-custody rules (PRD 3.6)."""

from flask import Blueprint

import calc
import envelope
import errors
import ladder
import serializers
import store
from domain import escalations as escalation_service
from errors import fail
from routes.common import apply_filter, endpoint
from store import DB

bp = Blueprint("deliveries", __name__)

ORDER_KINDS = ("MEDICATION", "DME")
DELIVERY_LIST_ROLES = [
    "ProgramAdmin", "AdmittingPhysician", "LogisticsCoordinator",
    "PharmacyAuthorizer", "CommunityParamedic",
]


def _recompute_fee(order):
    order["handling_fee_usd"] = calc.delivery_handling_fee(
        order["is_controlled"], order["cold_chain_required"],
        order["weight_kg"], order["redelivery_count"],
    )


@endpoint(bp, "/delivery-orders", ["POST"], ["LogisticsCoordinator", "AdmittingPhysician"])
def create_delivery_order(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, [
        "episode_id", "order_kind", "is_controlled", "cold_chain_required",
        "weight_kg", "requested_by_user_id",
    ])
    # rung 4b
    ladder.check_enum(body, "order_kind", ORDER_KINDS)
    # rung 4c
    ladder.check_boolean(body, "is_controlled")
    ladder.check_boolean(body, "cold_chain_required")
    ladder.check_number_min(body, "weight_kg", 0)
    ladder.check_string(body, "requested_by_user_id")
    # rung 5
    episode = ladder.body_episode(body)
    # rung 8
    ladder.require_episode_active(episode)

    order = store.make_row("delivery_orders", {
        "episode_id": episode["id"],
        "order_kind": body["order_kind"],
        "is_controlled": body["is_controlled"],
        "cold_chain_required": body["cold_chain_required"],
        "weight_kg": body["weight_kg"],
        "requested_by_user_id": body["requested_by_user_id"],
        "authorized_by_user_id": None,
        "witness_staff_id": None,
        "status": "PENDING_AUTHORIZATION",
        "redelivery_count": 0,
        "last_excursion_minutes": None,
        "handling_fee_usd": calc.ZERO,
    })
    _recompute_fee(order)
    return envelope.ObjResult(order, serializers.delivery_order, 201)


@endpoint(bp, "/episodes/<episode_id>/delivery-orders", ["GET"], DELIVERY_LIST_ROLES)
def list_delivery_orders(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [o for o in DB.delivery_orders.values() if o["episode_id"] == episode_id]
    rows = apply_filter(rows, "status")
    return envelope.ListResult(store.ordered(rows), serializers.delivery_order, limit, offset)


@endpoint(bp, "/delivery-orders/<order_id>/authorize", ["POST"], ["PharmacyAuthorizer"])
def authorize_order(caller, order_id):
    # rung 3
    order = ladder.path_row("delivery_orders", order_id)
    # rung 7
    ladder.require_state(order["status"] == "PENDING_AUTHORIZATION")
    # rung 8
    ladder.require_episode_active(DB.episodes[order["episode_id"]])
    # rung 10
    if order["is_controlled"] and caller.user_id == order["requested_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES)

    order["status"] = "AUTHORIZED"
    order["authorized_by_user_id"] = caller.user_id
    store.touch(order)
    return envelope.ObjResult(order, serializers.delivery_order, 200)


@endpoint(bp, "/delivery-orders/<order_id>/dispatch", ["POST"], ["LogisticsCoordinator"])
def dispatch_order(caller, order_id):
    # rung 3
    order = ladder.path_row("delivery_orders", order_id)
    # rung 7 -- REFUSED stays a legal from-state until both redeliveries are spent
    ladder.require_state(order["status"] in ("AUTHORIZED", "REFUSED"))
    # rung 8
    ladder.require_episode_active(DB.episodes[order["episode_id"]])
    redelivering = order["status"] == "REFUSED"
    # rung 14c
    if redelivering and order["redelivery_count"] >= calc.MAX_REDELIVERY_ATTEMPTS:
        fail(errors.ERR_REDELIVERY_LIMIT_EXCEEDED)

    order["status"] = "OUT_FOR_DELIVERY"
    if redelivering:
        order["redelivery_count"] = order["redelivery_count"] + 1
        _recompute_fee(order)
    store.touch(order)
    return envelope.ObjResult(order, serializers.delivery_order, 200)


@endpoint(bp, "/delivery-orders/<order_id>/deliver", ["POST"],
          ["LogisticsCoordinator", "CommunityParamedic"])
def deliver_order(caller, order_id):
    # rung 3
    order = ladder.path_row("delivery_orders", order_id)
    body = ladder.json_body()
    # rung 4c
    ladder.check_integer_range(body, "excursion_minutes", 0)
    # rung 7
    ladder.require_state(order["status"] == "OUT_FOR_DELIVERY")
    # rung 11a
    witness = body.get("witness_staff_id")
    if order["is_controlled"]:
        if not isinstance(witness, str) or witness.strip() == "":
            fail(errors.ERR_WITNESS_REQUIRED)
    # rung 11b
    excursion = body.get("excursion_minutes")
    if order["cold_chain_required"]:
        if excursion is None or excursion > calc.COLD_CHAIN_MAX_EXCURSION_MINUTES:
            fail(errors.ERR_COLD_CHAIN_EXCURSION)

    order["status"] = "DELIVERED"
    if witness is not None:
        order["witness_staff_id"] = witness
    if excursion is not None:
        order["last_excursion_minutes"] = excursion
    _recompute_fee(order)
    store.touch(order)
    return envelope.ObjResult(order, serializers.delivery_order, 200)


@endpoint(bp, "/delivery-orders/<order_id>/refuse", ["POST"],
          ["LogisticsCoordinator", "CommunityParamedic"])
def refuse_order(caller, order_id):
    # rung 3
    order = ladder.path_row("delivery_orders", order_id)
    # rung 7 -- abandonment is permitted only once both redeliveries are spent
    ladder.require_state(order["status"] in ("OUT_FOR_DELIVERY", "REFUSED"))
    if order["status"] == "REFUSED":
        ladder.require_state(order["redelivery_count"] == calc.MAX_REDELIVERY_ATTEMPTS)
        order["status"] = "FAILED"
        store.touch(order)
        episode = DB.episodes[order["episode_id"]]
        escalation_service.open_escalation(episode, "MEDICATION_FAILURE", caller.user_id)
    else:
        order["status"] = "REFUSED"
        store.touch(order)
    return envelope.ObjResult(order, serializers.delivery_order, 200)
