"""Activation, disclosure, authorisation, fair use and teardown (PRD 3.5, 3.6, 3.9)."""

from datetime import timedelta

from flask import Blueprint

import accounts
import capacity
import serialize
from auth import own_subscription, roles
from clock import clock
from constants import (
    API_PREFIX,
    AUTHORIZATION_MODES,
    AUTHORIZATION_STATES,
    DISCLOSURE_ACK_WINDOW_DAYS,
    PRIORITY_STATES,
    SERVICE_STATES,
    TIER_WEIGHT,
)
from db import db, new_record, ordered, touch
from errors import fail
from numeric import dec, q
from response import list_response, object_response
from validators import (
    body_dict,
    filter_enum,
    filter_value,
    pagination,
    paginate,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("service", __name__, url_prefix=API_PREFIX)


def find_subscription(subscription_id):
    record = db.subscriptions.get(subscription_id)
    if record is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found.")
    return record


# ---------------------------------------------------------------- activation ---

@bp.post("/subscriptions")
@roles("ProvisioningAgent")
def activate_subscription():
    body = body_dict()
    order_id = req_str(body, "service_order_id", 1, 100)
    terminal_id = req_str(body, "terminal_id", 1, 100)
    expected_cell_version = req_int(body, "expected_service_cell_version")

    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_SERVICE_ORDER_NOT_FOUND", "Service order not found.")
    terminal = db.terminals.get(terminal_id)
    if terminal is None:
        fail("ERR_TERMINAL_NOT_FOUND", "Terminal not found.")

    cell = db.cells.get(order["service_cell_id"])
    if cell is None:
        fail("ERR_SERVICE_CELL_NOT_FOUND", "Service cell not found.")

    if expected_cell_version != cell["version"]:
        fail(
            "ERR_STALE_SERVICE_CELL_VERSION",
            "The service cell has moved on since it was read.",
        )

    if order["order_state"] != "RESERVED":
        fail("ERR_ORDER_STATE_INVALID", "Activation requires a RESERVED order.")
    if terminal["terminal_state"] != "INSTALLED":
        fail("ERR_TERMINAL_NOT_INSTALLED", "The terminal is not INSTALLED.")
    if terminal["subscriber_id"] != order["subscriber_id"]:
        fail(
            "ERR_TERMINAL_SUBSCRIBER_MISMATCH",
            "The terminal belongs to another subscriber.",
        )

    subscriber = db.subscribers.get(order["subscriber_id"])
    if subscriber is None:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "Subscriber not found.")
    if subscriber["jurisdiction_code"] != cell["jurisdiction_code"]:
        fail(
            "ERR_JURISDICTION_NOT_PERMITTED",
            "The subscriber's jurisdiction does not match the cell's.",
        )

    now = clock.now()
    if order["reservation_expires_at"] is None or order["reservation_expires_at"] <= now:
        fail("ERR_RESERVATION_EXPIRED", "The reservation hold has lapsed.")

    if capacity.admission_free(cell, self_reservation=1) < 1:
        fail("ERR_CELL_CAPACITY_EXHAUSTED", "The cell has no free slot.")

    plan = db.plans.get(order["requested_plan_id"])
    if plan is None:
        fail("ERR_SERVICE_PLAN_NOT_FOUND", "Service plan not found.")

    beam = capacity.beam_of_cell(cell)
    if beam is None:
        fail("ERR_BEAM_NOT_FOUND", "Beam not found.")

    delta = dec(plan["committed_rate_mbps"]) * TIER_WEIGHT[plan["priority_tier"]]
    if not capacity.has_headroom(beam, delta):
        fail("ERR_BEAM_OVERSUBSCRIBED", "The beam has no headroom for this plan.")

    if beam["beam_state"] != "ACTIVE":
        fail("ERR_BEAM_SUSPENDED", "The governing beam is out of service.")

    license_record = capacity.license_of_beam(beam)
    record = new_record()
    record.update(
        {
            "subscriber_id": order["subscriber_id"],
            "service_order_id": order["id"],
            "service_cell_id": cell["id"],
            "service_plan_id": plan["id"],
            "terminal_id": terminal["id"],
            "deauthorized_by_license_id": None,
            "service_state": "PENDING_ACTIVATION",
            "authorization_state": "UNAUTHORIZED",
            "priority_state": "PRIORITY",
            "disclosure_ack_state": "PENDING_ACK",
            "disclosure_version_issued": license_record["consumer_disclosure_version"]
            if license_record
            else None,
            "disclosure_ack_deadline_at": now
            + timedelta(days=DISCLOSURE_ACK_WINDOW_DAYS),
            "cycle_priority_gb_used": q(0, 3),
            "cycle_billing_index": beam["billing_cycle_index"],
            "cycle_charge_cents": 0,
            "activated_at": now,
            "deprioritized_at": None,
            "terminated_at": None,
            "suspension_reason": None,
        }
    )
    db.subscriptions[record["id"]] = record

    order["order_state"] = "ACTIVATED"
    touch(order)
    accounts.mark_active(subscriber)
    touch(cell)
    capacity.recompute_beam(beam)

    return object_response(serialize.subscription(record), 201)


@bp.get("/subscriptions/<subscription_id>")
@roles("ProvisioningAgent", "NetworkOpsEngineer", "ComplianceOfficer", "Subscriber")
def read_subscription(subscription_id):
    own_subscription(subscription_id)
    return object_response(serialize.subscription(find_subscription(subscription_id)))


@bp.get("/subscriptions")
@roles("ProvisioningAgent", "NetworkOpsEngineer", "ComplianceOfficer", "Subscriber")
def list_subscriptions():
    limit, offset = pagination()
    filters = {
        "subscriber_id": filter_value("subscriber_id"),
        "service_order_id": filter_value("service_order_id"),
        "service_cell_id": filter_value("service_cell_id"),
        "service_plan_id": filter_value("service_plan_id"),
        "terminal_id": filter_value("terminal_id"),
        "deauthorized_by_license_id": filter_value("deauthorized_by_license_id"),
        "service_state": filter_enum("service_state", SERVICE_STATES),
        "authorization_state": filter_enum("authorization_state", AUTHORIZATION_STATES),
        "priority_state": filter_enum("priority_state", PRIORITY_STATES),
    }

    records = ordered(list(db.subscriptions.values()))
    for field, expected in filters.items():
        if expected is not None:
            records = [r for r in records if r[field] == expected]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.subscription), limit, offset, len(records)
    )


# ---------------------------------------------------------------- disclosure ---

@bp.post("/subscriptions/<subscription_id>/disclosure-acknowledgement")
@roles("Subscriber")
def acknowledge_disclosure(subscription_id):
    own_subscription(subscription_id)
    body = body_dict()
    acknowledged_version = req_str(body, "acknowledged_version", 1, 20)

    record = find_subscription(subscription_id)
    if (
        record["disclosure_ack_state"] != "PENDING_ACK"
        or record["service_state"] == "TERMINATED"
    ):
        fail(
            "ERR_SUBSCRIPTION_STATE_INVALID",
            "Acknowledgement requires a PENDING_ACK disclosure on a live subscription.",
        )
    if acknowledged_version != record["disclosure_version_issued"]:
        fail(
            "ERR_DISCLOSURE_VERSION_MISMATCH",
            "acknowledged_version does not match the pinned disclosure version.",
        )

    record["disclosure_ack_state"] = "ACKNOWLEDGED"
    touch(record)
    return object_response(serialize.subscription(record))


# ------------------------------------------------------------- authorisation ---

@bp.post("/subscriptions/<subscription_id>/authorize")
@roles("ProvisioningAgent")
def authorize_subscription(subscription_id):
    body = body_dict()
    mode = req_enum(body, "authorization_mode", AUTHORIZATION_MODES)

    record = find_subscription(subscription_id)
    if (
        record["service_state"] not in ("PENDING_ACTIVATION", "ACTIVE")
        or record["authorization_state"] != "UNAUTHORIZED"
    ):
        fail(
            "ERR_SUBSCRIPTION_STATE_INVALID",
            "Authorisation requires a live, UNAUTHORIZED subscription.",
        )

    beam = capacity.beam_of_subscription(record)
    license_record = capacity.license_of_beam(beam)
    if license_record is None or license_record["license_state"] != "ACTIVE":
        fail("ERR_LICENSE_NOT_ACTIVE", "The governing licence is not ACTIVE.")
    if license_record["coordination_state"] != "COORDINATED":
        fail("ERR_SPECTRUM_NOT_COORDINATED", "The governing licence is not COORDINATED.")
    if record["disclosure_ack_state"] != "ACKNOWLEDGED":
        fail(
            "ERR_DISCLOSURE_NOT_ACKNOWLEDGED",
            "The consumer disclosure has not been acknowledged.",
        )

    if mode == "IN_MOTION":
        plan = capacity.plan_of_subscription(record)
        if (
            plan is None
            or not plan["in_motion_allowed"]
            or not license_record["in_motion_permitted"]
        ):
            fail(
                "ERR_IN_MOTION_NOT_PERMITTED",
                "In-motion operation is not permitted for this plan or licence.",
            )

    if beam is None or beam["beam_state"] != "ACTIVE":
        fail("ERR_BEAM_SUSPENDED", "The governing beam is out of service.")

    record["authorization_state"] = (
        "AUTHORIZED_IN_MOTION" if mode == "IN_MOTION" else "AUTHORIZED_FIXED"
    )
    if record["service_state"] == "PENDING_ACTIVATION":
        record["service_state"] = "ACTIVE"
    touch(record)
    capacity.recompute_beam(beam)

    return object_response(serialize.subscription(record))


# ------------------------------------------------------------- plan re-assign --

@bp.post("/subscriptions/<subscription_id>/plan-change")
@roles("ProvisioningAgent")
def change_plan(subscription_id):
    body = body_dict()
    new_plan_id = req_str(body, "new_service_plan_id", 1, 100)
    expected_beam_version = req_int(body, "expected_beam_version")

    record = find_subscription(subscription_id)
    new_plan = db.plans.get(new_plan_id)
    if new_plan is None:
        fail("ERR_SERVICE_PLAN_NOT_FOUND", "Service plan not found.")

    beam = capacity.beam_of_subscription(record)
    if beam is None:
        fail("ERR_BEAM_NOT_FOUND", "Beam not found.")
    if expected_beam_version != beam["version"]:
        fail("ERR_STALE_BEAM_VERSION", "The beam has moved on since it was read.")

    if record["service_state"] not in ("PENDING_ACTIVATION", "ACTIVE"):
        fail(
            "ERR_SUBSCRIPTION_STATE_INVALID",
            "A plan change requires a live subscription.",
        )

    outgoing_plan = capacity.plan_of_subscription(record)
    incoming_weight = (
        capacity.DEPRIORITIZED_WEIGHT
        if record["priority_state"] == "DEPRIORITIZED"
        else TIER_WEIGHT[new_plan["priority_tier"]]
    )
    added = dec(new_plan["committed_rate_mbps"]) * incoming_weight
    removed = capacity.subscription_contribution(record) if outgoing_plan else dec(0)
    if not capacity.has_headroom(beam, added - removed):
        fail("ERR_BEAM_OVERSUBSCRIBED", "The beam has no headroom for the new plan.")

    record["service_plan_id"] = new_plan["id"]
    touch(record)
    capacity.apply_fair_use_threshold(record, plan=new_plan, beam=beam)
    capacity.recompute_beam(beam)
    capacity.recompute_cells_of_beam(beam)

    return object_response(serialize.subscription(record))


# ------------------------------------------------------------------ teardown ---

@bp.post("/subscriptions/<subscription_id>/suspend")
@roles("ProvisioningAgent")
def suspend_subscription(subscription_id):
    body = body_dict()
    suspend_reason = req_str(body, "suspend_reason", 1, 500)

    record = find_subscription(subscription_id)
    if record["service_state"] not in ("PENDING_ACTIVATION", "ACTIVE"):
        fail(
            "ERR_SUBSCRIPTION_STATE_INVALID",
            "Suspension requires a PENDING_ACTIVATION or ACTIVE subscription.",
        )

    record["service_state"] = "SUSPENDED"
    record["suspension_reason"] = suspend_reason
    touch(record)

    beam = capacity.beam_of_subscription(record)
    capacity.recompute_beam(beam)
    capacity.recompute_cells_of_beam(beam)
    accounts.settle_after_suspension(db.subscribers.get(record["subscriber_id"]))

    return object_response(serialize.subscription(record))


@bp.post("/subscriptions/<subscription_id>/terminate")
@roles("ProvisioningAgent")
def terminate_subscription(subscription_id):
    body = body_dict()
    # The reason is a mandatory audit input; the entity has no field for it.
    req_str(body, "termination_reason", 1, 500)

    record = find_subscription(subscription_id)
    if record["service_state"] == "TERMINATED":
        fail(
            "ERR_SUBSCRIPTION_STATE_INVALID",
            "The subscription is already TERMINATED.",
        )

    record["service_state"] = "TERMINATED"
    record["authorization_state"] = "DEAUTHORIZED"
    record["terminated_at"] = clock.now()
    touch(record)

    cell = capacity.cell_of_subscription(record)
    if cell is not None:
        touch(cell)
        capacity.run_promotion(cell)

    beam = capacity.beam_of_subscription(record)
    capacity.recompute_beam(beam)

    terminal = db.terminals.get(record["terminal_id"])
    if terminal is not None and terminal["terminal_state"] == "INSTALLED":
        terminal["terminal_state"] = "RETURN_INITIATED"
        touch(terminal)

    for roaming in ordered(list(db.roaming.values())):
        if roaming["subscription_id"] != record["id"]:
            continue
        if roaming["auth_state"] in ("REQUESTED", "NEEDS_INFO", "APPROVED"):
            roaming["auth_state"] = "REVOKED"
            roaming["revoked_reason"] = "SUBSCRIPTION_TERMINATED"
            touch(roaming)

    accounts.settle_after_termination(db.subscribers.get(record["subscriber_id"]))
    return object_response(serialize.subscription(record))


# --------------------------------------------------------------- fair use -----

@bp.post("/subscriptions/<subscription_id>/usage-records")
@roles("NetworkOpsEngineer")
def ingest_usage(subscription_id):
    body = body_dict()
    gb_used = req_num(body, "gb_used", ge=0)
    billing_cycle_index = req_int(body, "billing_cycle_index", minimum=0)

    subscription = find_subscription(subscription_id)
    if subscription["service_state"] == "TERMINATED":
        fail(
            "ERR_SUBSCRIPTION_STATE_INVALID",
            "Usage cannot be ingested for a TERMINATED subscription.",
        )

    counted = billing_cycle_index == subscription["cycle_billing_index"]
    record = new_record(with_common_fields=False)
    record.update(
        {
            "subscription_id": subscription["id"],
            "billing_cycle_index": billing_cycle_index,
            "gb_used": gb_used,
            "counted": counted,
            "recorded_at": clock.now(),
        }
    )
    db.usage_records[record["id"]] = record

    if counted:
        subscription["cycle_priority_gb_used"] = q(
            dec(subscription["cycle_priority_gb_used"]) + gb_used, 3
        )
        touch(subscription)
        if capacity.apply_fair_use_threshold(subscription):
            beam = capacity.beam_of_subscription(subscription)
            capacity.recompute_beam(beam)
            capacity.recompute_cells_of_beam(beam)

    return object_response(serialize.usage_record(record), 201)


@bp.get("/subscriptions/<subscription_id>/usage-records")
@roles("ProvisioningAgent", "NetworkOpsEngineer", "ComplianceOfficer", "Subscriber")
def list_usage(subscription_id):
    own_subscription(subscription_id)
    limit, offset = pagination()
    subscription = find_subscription(subscription_id)

    records = [
        r
        for r in db.usage_records.values()
        if r["subscription_id"] == subscription["id"]
    ]
    records.sort(key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]))

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.usage_record), limit, offset, len(records)
    )
