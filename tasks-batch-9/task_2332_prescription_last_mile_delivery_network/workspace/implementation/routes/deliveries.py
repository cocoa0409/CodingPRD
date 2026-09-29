"""The delivery lifecycle: reservation, routing, custody, the door-step run, settlement."""

from datetime import timedelta

from flask import Blueprint

import middleware
import response
import serializers
import validation as v
from constants import (
    COLD_CLASSES,
    COLD_EXCURSION_BUDGET_MINUTES,
    DISCLOSURE_PURPOSES,
    ID_VERIFICATION_METHODS,
    ID_VERIFICATION_RANK,
    MAX_DELIVERY_ATTEMPTS,
    REATTEMPT_COOLDOWN_STAGE1_MINUTES,
    REATTEMPT_COOLDOWN_STAGE2_MINUTES,
    RECIPIENT_RELATIONSHIPS,
    REQUESTED_OUTCOMES,
)
from db import db, new_row, touch
from errors import api_error
from middleware import (
    ROLE_COURIER,
    ROLE_OPS,
    ROLE_PATIENT,
    ROLE_PHARMACY,
    require_roles,
)
from services import cascades
from services import couriers as courier_service
from services import derive
from services import hipaa
from services import money
from services import orders as order_service
from services import reservations
from services import windows as window_service

bp = Blueprint("deliveries", __name__)

COOLDOWN_MINUTES = {
    1: REATTEMPT_COOLDOWN_STAGE1_MINUTES,
    2: REATTEMPT_COOLDOWN_STAGE2_MINUTES,
}


def load_delivery(delivery_id, order_scope=False, plan_scope=False, courier_scope=False):
    """Scope (rungs 3-6) decides before existence (rung 8) can leak a 404."""
    delivery = db.deliveries.get(delivery_id)
    if delivery is not None:
        order = db.pharmacy_orders.get(delivery["order_id"])
        if order_scope:
            middleware.guard_order_scope(order)
        if plan_scope:
            middleware.guard_plan_scope_on_order(order)
        if courier_scope:
            middleware.guard_courier_scope(delivery["courier_id"])
    if delivery is None:
        raise api_error("ERR_DELIVERY_NOT_FOUND")
    return delivery


# --------------------------------------------------------------------------
# reservation
# --------------------------------------------------------------------------
@bp.post("/deliveries")
@require_roles(ROLE_PHARMACY)
def create_delivery():
    # Rung 3 acts on the claimed order before the body is strictly validated.
    claimed = v.soft_body().get("order_id")
    if isinstance(claimed, str):
        middleware.guard_order_scope(db.pharmacy_orders.get(claimed))

    body = v.json_body()
    order_id = v.string_field(body, "order_id")
    window_id = v.string_field(body, "window_id")
    expected_version = v.int_field(body, "expected_window_version", minimum=0)

    order = db.pharmacy_orders.get(order_id)
    if order is None:
        raise api_error("ERR_ORDER_NOT_FOUND")
    window = db.delivery_windows.get(window_id)
    if window is None:
        raise api_error("ERR_WINDOW_NOT_FOUND")

    if order["status"] != "READY":
        raise api_error("ERR_ORDER_NOT_READY")

    reservations.assert_window_not_blocked(window, reservation=True)

    grant = money.select_grant(order, window)

    if expected_version != window["version"]:
        raise api_error("ERR_STALE_WINDOW_VERSION",
                        "The target window has moved since it was last read.")

    patient = db.patients.get(order["patient_id"])
    if patient is None or patient["hipaa_consent_status"] != "GRANTED":
        raise api_error("ERR_CONSENT_NOT_GRANTED")

    handling_class = order_service.handling_class(order)
    zone = reservations.zone_of(window)
    reservations.assert_zone_policy(zone, handling_class)
    reservations.assert_patient_zone(order, window)
    reservations.assert_no_duplicate_active(order)
    reservations.assert_window_timing(window, new_reservation=True)
    reservations.assert_capacity(window)

    values = money.plan_allocation(order, window, zone, handling_class,
                                   "PROVISIONAL", None, grant)

    delivery = reservations.new_delivery(order, window)
    window_service.occupancy_changed(window)
    order["status"] = "DISPATCHED"
    touch(order)
    cascades.commit_allocation(delivery, values)
    return response.single(serializers.delivery(delivery), 201)


@bp.post("/deliveries/<delivery_id>/reschedule")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT)
def reschedule_delivery(delivery_id):
    delivery = load_delivery(delivery_id, order_scope=True)
    order = db.pharmacy_orders.get(delivery["order_id"])
    current_window = db.delivery_windows.get(delivery["window_id"])

    body = v.json_body()
    window_id = v.string_field(body, "window_id")

    window = db.delivery_windows.get(window_id)
    if window is None:
        raise api_error("ERR_WINDOW_NOT_FOUND")

    if delivery["custody_status"] not in {"QUEUED", "ASSIGNED"}:
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "Only an unpicked delivery may be rescheduled.")

    reservations.assert_window_not_blocked(window, reservation=True)

    released = cascades.released_funds(delivery)
    grant = money.select_grant(order, window, released)

    zone = reservations.zone_of(window)
    reservations.assert_zone_policy(zone, delivery["handling_class"])
    reservations.assert_patient_zone(order, window)
    reservations.assert_mode_match(current_window, window)
    reservations.assert_window_timing(window, new_reservation=True)
    reservations.assert_capacity(window)

    values = money.plan_allocation(order, window, zone, delivery["handling_class"],
                                   "PROVISIONAL", None, grant, released)

    cascades.revoke_live_assignments(delivery)
    delivery["window_id"] = window["id"]
    if current_window is not None and current_window["id"] != window["id"]:
        window_service.occupancy_changed(current_window)
    window_service.occupancy_changed(window)
    cascades.replace_allocation(delivery, "SUPERSEDED", values)
    touch(delivery)
    return response.single(serializers.delivery(delivery), 200)


@bp.post("/deliveries/<delivery_id>/cancel")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT)
def cancel_delivery(delivery_id):
    delivery = load_delivery(delivery_id, order_scope=True)
    order = db.pharmacy_orders.get(delivery["order_id"])
    window = db.delivery_windows.get(delivery["window_id"])

    body = v.json_body()
    v.string_field(body, "notes", required=False, default=None, max_len=1000)

    if delivery["custody_status"] not in {"QUEUED", "ASSIGNED"}:
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "A delivery at PICKED_UP or beyond can no longer be cancelled.")

    cascades.revoke_live_assignments(delivery)
    delivery["custody_status"] = "CANCELLED"
    delivery["settlement_status"] = "VOIDED"
    cascades.close_out_allocation(delivery, "VOIDED")
    delivery["fee_subtotal_cents"] = 0
    window_service.occupancy_changed(window)

    if order["status"] == "DISPATCHED":
        others = [d for d in db.deliveries.values()
                  if d["order_id"] == order["id"] and d["id"] != delivery["id"]
                  and d["custody_status"] != "CANCELLED"]
        if not others:
            order["status"] = "READY"
            touch(order)
    touch(delivery)
    return response.single(serializers.delivery(delivery), 200)


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------
@bp.post("/deliveries/<delivery_id>/dispatch")
@require_roles(ROLE_OPS)
def dispatch_delivery(delivery_id):
    delivery = load_delivery(delivery_id)
    window = db.delivery_windows.get(delivery["window_id"])
    zone = reservations.zone_of(window)

    body = v.json_body()
    courier_id = v.string_field(body, "courier_id", required=False, default=None)

    named = None
    if courier_id is not None:
        named = db.couriers.get(courier_id)
        if named is None:
            raise api_error("ERR_COURIER_NOT_FOUND")

    if delivery["custody_status"] != "QUEUED":
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "Only a QUEUED delivery may be offered to a courier.")

    if named is not None:
        if named["status"] == "SUSPENDED":
            raise api_error("ERR_COURIER_SUSPENDED")
        if named["status"] == "OFFLINE":
            raise api_error("ERR_COURIER_UNAVAILABLE")
        handling = delivery["handling_class"]
        if handling in COLD_CLASSES and not named["cold_chain_equipped"]:
            raise api_error("ERR_COURIER_NOT_COLD_CERTIFIED")
        if handling in {"CONTROLLED", "COLD_CHAIN_CONTROLLED"} and not named["controlled_certified"]:
            raise api_error("ERR_COURIER_NOT_CONTROLLED_CERTIFIED")
        if zone["zone_code"] not in named["served_zone_codes"]:
            raise api_error("ERR_COURIER_ZONE_NOT_SERVED")
        if named["mode"] != window["courier_mode"]:
            raise api_error("ERR_COURIER_MODE_MISMATCH")

    reservations.assert_window_timing(window)

    if named is not None:
        if courier_service.has_overlap_conflict(named, window,
                                                exclude_delivery_id=delivery["id"]):
            raise api_error("ERR_COURIER_OVERLAP_CONFLICT")
        assignment = courier_service.create_offer(delivery, named, money.Decimal("0.00"))
    else:
        selected = courier_service.select_courier(delivery, window, zone)
        if selected is None:
            raise api_error("ERR_NO_ELIGIBLE_COURIER",
                            "No eligible courier is available for this delivery.")
        assignment = courier_service.create_offer(
            delivery, selected, derive.rolling_reliability_score(selected))

    return response.single(serializers.courier_assignment(assignment), 201)


# --------------------------------------------------------------------------
# custody
# --------------------------------------------------------------------------
@bp.post("/deliveries/<delivery_id>/pickup")
@require_roles(ROLE_COURIER)
def pickup(delivery_id):
    delivery = load_delivery(delivery_id, courier_scope=True)
    order = db.pharmacy_orders.get(delivery["order_id"])

    body = v.json_body()
    seal_id = v.string_field(body, "cold_chain_seal_id", required=False, default=None)

    if order["status"] != "DISPATCHED":
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "The order behind this delivery is not DISPATCHED.")
    if delivery["custody_status"] != "ASSIGNED":
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "Only an ASSIGNED delivery may be picked up.")
    if delivery["handling_class"] in COLD_CLASSES and not seal_id:
        raise api_error("ERR_COLD_SEAL_REQUIRED",
                        "A cold-chain bag requires a cold_chain_seal_id at pickup.")

    delivery["custody_status"] = "PICKED_UP"
    if delivery["handling_class"] in COLD_CLASSES:
        delivery["cold_chain_seal_id"] = seal_id
    elif seal_id is not None:
        # Ignored for STANDARD and CONTROLLED bags.
        pass
    delivery["picked_up_at"] = db.clock
    touch(delivery)
    return response.single(serializers.delivery(delivery), 200)


@bp.post("/deliveries/<delivery_id>/depart")
@require_roles(ROLE_COURIER)
def depart(delivery_id):
    delivery = load_delivery(delivery_id, courier_scope=True)
    window = db.delivery_windows.get(delivery["window_id"])

    if delivery["custody_status"] not in {"PICKED_UP", "ATTEMPT_FAILED"}:
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "Departure runs from PICKED_UP or ATTEMPT_FAILED only.")

    reservations.assert_window_not_blocked(window, reservation=False)
    reservations.assert_window_timing(window)

    if delivery["custody_status"] == "ATTEMPT_FAILED":
        attempts = derive.attempt_count(delivery)
        cooldown = COOLDOWN_MINUTES.get(attempts, 0)
        last_attempt = derive.last_attempt_at(delivery)
        if last_attempt is not None and cooldown:
            if db.clock < last_attempt + timedelta(minutes=cooldown):
                raise api_error("ERR_REATTEMPT_COOLDOWN_ACTIVE",
                                "The re-attempt cooldown has not elapsed.")

    delivery["custody_status"] = "OUT_FOR_DELIVERY"
    touch(delivery)
    return response.single(serializers.delivery(delivery), 200)


@bp.post("/deliveries/<delivery_id>/attempts")
@require_roles(ROLE_COURIER)
def record_attempt(delivery_id):
    delivery = load_delivery(delivery_id, courier_scope=True)
    order = db.pharmacy_orders.get(delivery["order_id"])
    window = db.delivery_windows.get(delivery["window_id"])
    pharmacy = db.pharmacies.get(order["pharmacy_id"])

    body = v.json_body()
    requested = v.enum_field(body, "requested_outcome", REQUESTED_OUTCOMES)
    id_method = v.enum_field(body, "id_verification_method", ID_VERIFICATION_METHODS,
                             required=False, default="NONE")
    signature = v.bool_field(body, "signature_captured", default=False)
    relationship = v.enum_field(body, "recipient_relationship", RECIPIENT_RELATIONSHIPS,
                                required=False, default="SELF")
    pod_photo_ref = v.string_field(body, "pod_photo_ref", required=False, default=None,
                                   max_len=200)

    if delivery["custody_status"] != "OUT_FOR_DELIVERY":
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "A door-step run may only be recorded while OUT_FOR_DELIVERY.")

    # The cold-excursion override is decided before any proof gate runs.
    elapsed = None
    if delivery["picked_up_at"] is not None:
        elapsed = int((db.clock - delivery["picked_up_at"]).total_seconds() // 60)
    cold = delivery["handling_class"] in COLD_CLASSES
    forced_breach = (cold and elapsed is not None
                     and elapsed >= COLD_EXCURSION_BUDGET_MINUTES)

    if forced_breach:
        outcome = "COLD_BREACH"
    else:
        outcome = requested
        if outcome == "DELIVERED":
            if delivery["signature_required"]:
                if not signature:
                    raise api_error("ERR_SIGNATURE_REQUIRED",
                                    "This bag requires a captured signature.")
                if relationship == "UNATTENDED":
                    raise api_error("ERR_UNATTENDED_NOT_PERMITTED",
                                    "A signed handoff may not be recorded as UNATTENDED.")
            required_rank = ID_VERIFICATION_RANK[delivery["required_id_verification"]]
            if ID_VERIFICATION_RANK[id_method] < required_rank:
                raise api_error("ERR_ID_VERIFICATION_INSUFFICIENT",
                                "The identity verification performed is below the "
                                "required level.")

    attempt = new_row(versioned=False)
    attempt["delivery_id"] = delivery["id"]
    attempt["courier_id"] = delivery["courier_id"]
    attempt["attempt_no"] = derive.attempt_count(delivery) + 1
    attempt["attempted_at"] = db.clock
    attempt["requested_outcome"] = requested
    attempt["outcome"] = outcome
    attempt["id_verification_method"] = id_method
    attempt["signature_captured"] = signature
    attempt["recipient_relationship"] = relationship
    attempt["pod_photo_ref"] = pod_photo_ref
    attempt["elapsed_since_pickup_minutes"] = elapsed
    attempt["reliability_credit"] = derive.CREDIT_BY_OUTCOME[outcome]
    db.delivery_attempts[attempt["id"]] = attempt

    attempt_total = derive.attempt_count(delivery)
    courier = db.couriers.get(delivery["courier_id"])
    assignment = cascades.accepted_assignment(delivery)
    leg_closed = False

    if outcome == "DELIVERED":
        delivery["custody_status"] = "DELIVERED"
        delivery["delivered_at"] = db.clock
        if assignment is not None:
            assignment["status"] = "COMPLETED"
            touch(assignment)
            leg_closed = True
        window_service.occupancy_changed(window)
    elif outcome == "COLD_BREACH":
        delivery["custody_status"] = "RETURN_PENDING"
        delivery["return_due_at"] = db.clock + timedelta(
            minutes=pharmacy["return_window_minutes"])
        cascades.open_system_case(delivery, "COLD_BREACH")
        cascades.close_out_allocation(delivery, "VOIDED")
        delivery["settlement_status"] = "VOIDED"
        delivery["fee_subtotal_cents"] = 0
        if assignment is not None:
            assignment["status"] = "RELEASED"
            touch(assignment)
            leg_closed = True
        window_service.occupancy_changed(window)
    elif attempt_total >= MAX_DELIVERY_ATTEMPTS:
        delivery["custody_status"] = "RETURN_PENDING"
        delivery["return_due_at"] = db.clock + timedelta(
            minutes=pharmacy["return_window_minutes"])
        cascades.open_system_case(
            delivery,
            "ID_MISMATCH_EXHAUSTED" if outcome == "ID_MISMATCH" else "ATTEMPTS_EXHAUSTED")
        if assignment is not None:
            assignment["status"] = "RELEASED"
            touch(assignment)
            leg_closed = True
        window_service.occupancy_changed(window)
    else:
        # The bag is still out against this window: the slot stays reserved.
        delivery["custody_status"] = "ATTEMPT_FAILED"

    if courier is not None:
        if leg_closed and courier["status"] == "ON_ROUTE" \
                and derive.active_delivery_count(courier) == 0:
            courier["status"] = "AVAILABLE"
        courier_service.apply_reliability(courier)
        touch(courier)

    touch(delivery)
    return response.single(serializers.delivery_attempt(attempt), 201)


@bp.post("/deliveries/<delivery_id>/confirm-return")
@require_roles(ROLE_PHARMACY)
def confirm_return(delivery_id):
    delivery = load_delivery(delivery_id, order_scope=True)
    order = db.pharmacy_orders.get(delivery["order_id"])

    if delivery["custody_status"] != "RETURN_PENDING":
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "Only a RETURN_PENDING delivery may be confirmed back in hand.")

    delivery["custody_status"] = "RETURNED"
    touch(delivery)
    if order["status"] == "DISPATCHED":
        order["status"] = "RETURNED_TO_STOCK"
        touch(order)
    return response.single(serializers.delivery(delivery), 200)


# --------------------------------------------------------------------------
# settlement
# --------------------------------------------------------------------------
@bp.post("/deliveries/<delivery_id>/settle")
@require_roles(ROLE_OPS)
def settle(delivery_id):
    delivery = load_delivery(delivery_id)
    order = db.pharmacy_orders.get(delivery["order_id"])
    window = db.delivery_windows.get(delivery["window_id"])
    zone = reservations.zone_of(window)

    if delivery["custody_status"] not in {"DELIVERED", "RETURNED"}:
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "The physical question must be answered before the financial one.")
    if delivery["settlement_status"] != "PROVISIONAL":
        raise api_error("ERR_INVALID_SETTLEMENT_STATE",
                        "Only a PROVISIONAL delivery may be settled.")

    released = cascades.released_funds(delivery)
    grant = money.select_grant(order, window, released)
    values = money.plan_allocation(order, window, zone, delivery["handling_class"],
                                   "FINAL", delivery, grant, released)

    for case in db.exception_cases.values():
        if case["delivery_id"] == delivery["id"] and case["status"] in {"OPEN", "UNDER_REVIEW"}:
            raise api_error("ERR_EXCEPTION_PENDING",
                            "Money may not be finalised while an exception is live.")

    cascades.replace_allocation(delivery, "SUPERSEDED", values)
    delivery["settlement_status"] = "FINALIZED"
    if delivery["custody_status"] == "DELIVERED" and order["status"] == "DISPATCHED":
        order["status"] = "CLOSED"
        touch(order)
    touch(delivery)
    return response.single(serializers.delivery(delivery), 200)


# --------------------------------------------------------------------------
# HIPAA projection and audit trail
# --------------------------------------------------------------------------
@bp.get("/deliveries/<delivery_id>/courier-view")
@require_roles(ROLE_COURIER, ROLE_OPS)
def courier_view(delivery_id):
    delivery = db.deliveries.get(delivery_id)
    if delivery is None:
        raise api_error("ERR_DELIVERY_NOT_FOUND")

    courier_id = None
    if middleware.actor_role() == ROLE_COURIER:
        courier_id = middleware.actor_id()
        holds = delivery["courier_id"] == courier_id
        if not holds:
            for assignment in db.courier_assignments.values():
                if (assignment["delivery_id"] == delivery["id"]
                        and assignment["courier_id"] == courier_id
                        and assignment["status"] in {"OFFERED", "ACCEPTED", "COMPLETED"}):
                    holds = True
                    break
        if not holds:
            raise api_error("ERR_HIPAA_SCOPE_VIOLATION",
                            "No live or historical assignment means no disclosure at all.")

    purpose = v.query_enum("purpose", DISCLOSURE_PURPOSES) or "DELIVERY_EXECUTION"

    order = db.pharmacy_orders.get(delivery["order_id"])
    patient = db.patients.get(order["patient_id"])
    window = db.delivery_windows.get(delivery["window_id"])
    row = hipaa.record_disclosure(delivery, courier_id, purpose)
    projection = hipaa.build_projection(delivery, order, patient, window, row["id"])
    return response.single(projection, 200)


@bp.get("/deliveries/<delivery_id>/disclosures")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT, ROLE_OPS)
def delivery_disclosures(delivery_id):
    delivery = db.deliveries.get(delivery_id)
    if delivery is None:
        raise api_error("ERR_DELIVERY_NOT_FOUND")
    limit, offset = v.pagination()
    from db import sort_rows

    rows = sort_rows([d for d in db.disclosures.values()
                      if d["delivery_id"] == delivery["id"]])
    page, total = response.paginate(rows, limit, offset)
    return response.collection([serializers.disclosure(r) for r in page],
                               limit, offset, total)
