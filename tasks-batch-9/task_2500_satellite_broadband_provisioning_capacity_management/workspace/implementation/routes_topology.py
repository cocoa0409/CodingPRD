"""Beams, coverage cells, the plan catalogue and the billing-cycle ops run."""

from flask import Blueprint

import capacity
import serialize
from auth import roles
from billing import cycle_charge_cents
from clock import clock, fmt
from constants import (
    API_PREFIX,
    AUTHORIZED_STATES,
    AVAILABILITY_STATES,
    BEAM_STATES,
    CAPACITY_STATES,
    DEFAULT_OVERSUBSCRIPTION_LIMIT,
    PRIORITY_TIERS,
    WAITLIST_CAP_PER_CELL,
)
from db import db, new_record, ordered, touch
from errors import fail
from licensing import expire_license
from numeric import q
from response import list_response, object_response
from validators import (
    body_dict,
    filter_enum,
    filter_value,
    opt_bool,
    opt_int,
    opt_num,
    pagination,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_jurisdiction,
    req_num,
    req_str,
)

bp = Blueprint("topology", __name__, url_prefix=API_PREFIX)


def find_beam(beam_id):
    record = db.beams.get(beam_id)
    if record is None:
        fail("ERR_BEAM_NOT_FOUND", "Beam not found.")
    return record


def find_cell(cell_id):
    record = db.cells.get(cell_id)
    if record is None:
        fail("ERR_SERVICE_CELL_NOT_FOUND", "Service cell not found.")
    return record


# ------------------------------------------------------------------- beams ----

@bp.post("/beams")
@roles("NetworkOpsEngineer")
def create_beam():
    body = body_dict()
    beam_code = req_str(body, "beam_code", 1, 40)
    satellite_code = req_str(body, "satellite_code", 1, 100)
    license_id = req_str(body, "spectrum_license_id", 1, 100)
    forward_capacity = req_num(body, "forward_capacity_mbps", gt=0)
    limit = opt_num(
        body,
        "oversubscription_limit",
        ge=1.0,
        le=20.0,
        default=DEFAULT_OVERSUBSCRIPTION_LIMIT,
    )
    grace = opt_int(body, "deprioritization_grace_gb", minimum=0, default=0)

    license_record = db.licenses.get(license_id)
    if license_record is None:
        fail("ERR_SPECTRUM_LICENSE_NOT_FOUND", "Spectrum licence not found.")

    for existing in db.beams.values():
        if existing["beam_code"] == beam_code:
            fail("ERR_INVALID_REQUEST", "beam_code is already in use.")

    record = new_record()
    record.update(
        {
            "beam_code": beam_code,
            "satellite_code": satellite_code,
            "spectrum_license_id": license_id,
            "forward_capacity_mbps": forward_capacity,
            "oversubscription_limit": limit,
            "deprioritization_grace_gb": grace,
            "beam_state": "ACTIVE"
            if license_record["license_state"] == "ACTIVE"
            else "SUSPENDED",
            "billing_cycle_index": 0,
            "last_cycle_closed_at": None,
        }
    )
    db.beams[record["id"]] = record
    return object_response(serialize.beam(record), 201)


@bp.get("/beams/<beam_id>")
@roles("NetworkOpsEngineer", "ProvisioningAgent", "ComplianceOfficer")
def read_beam(beam_id):
    return object_response(serialize.beam(find_beam(beam_id)))


@bp.get("/beams")
@roles("NetworkOpsEngineer", "ProvisioningAgent", "ComplianceOfficer")
def list_beams():
    limit, offset = pagination()
    license_id = filter_value("spectrum_license_id")
    capacity_filter = filter_enum("capacity_state", CAPACITY_STATES)
    state_filter = filter_enum("beam_state", BEAM_STATES)

    records = ordered(list(db.beams.values()))
    if license_id is not None:
        records = [r for r in records if r["spectrum_license_id"] == license_id]
    if state_filter is not None:
        records = [r for r in records if r["beam_state"] == state_filter]
    if capacity_filter is not None:
        records = [r for r in records if capacity.capacity_state(r) == capacity_filter]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.beam), limit, offset, len(records)
    )


@bp.post("/beams/<beam_id>/capacity-policy")
@roles("NetworkOpsEngineer")
def write_capacity_policy(beam_id):
    body = body_dict()
    limit = req_num(body, "oversubscription_limit", ge=1.0, le=20.0)
    grace = req_int(body, "deprioritization_grace_gb", minimum=0)
    expected_version = req_int(body, "expected_beam_version")

    beam = find_beam(beam_id)
    if expected_version != beam["version"]:
        fail("ERR_STALE_BEAM_VERSION", "The beam has moved on since it was read.")

    beam["oversubscription_limit"] = limit
    beam["deprioritization_grace_gb"] = grace
    touch(beam)

    for subscription in capacity.subscriptions_of_beam(beam):
        capacity.apply_fair_use_threshold(subscription, beam=beam)

    capacity.recompute_cells_of_beam(beam)
    return object_response(serialize.beam(beam))


@bp.post("/beams/<beam_id>/billing-cycle-close")
@roles("NetworkOpsEngineer")
def billing_cycle_close(beam_id):
    beam = find_beam(beam_id)
    now = clock.now()

    # 1. cycle epoch advances
    beam["billing_cycle_index"] += 1
    beam["last_cycle_closed_at"] = now
    touch(beam)

    # 2. licence expiry
    license_expired = False
    license_record = capacity.license_of_beam(beam)
    if (
        license_record is not None
        and license_record["license_state"] == "ACTIVE"
        and license_record["expires_at"] <= now
    ):
        expire_license(license_record)
        license_expired = True

    subscriptions = capacity.subscriptions_of_beam(beam)
    cells = sorted(capacity.cells_of_beam(beam), key=lambda c: c["cell_code"])

    # 3. disclosure-deadline enforcement
    disclosure_expired_count = 0
    for subscription in subscriptions:
        if (
            subscription["disclosure_ack_state"] == "PENDING_ACK"
            and subscription["disclosure_ack_deadline_at"] is not None
            and subscription["disclosure_ack_deadline_at"] <= now
        ):
            subscription["disclosure_ack_state"] = "EXPIRED"
            if subscription["authorization_state"] in AUTHORIZED_STATES:
                subscription["authorization_state"] = "DEAUTHORIZED"
            touch(subscription)
            disclosure_expired_count += 1

    # 4. reservation expiry sweep
    expired_order_count = 0
    for cell in cells:
        for order in capacity.orders_of_cell(cell):
            if (
                order["order_state"] == "RESERVED"
                and order["reservation_expires_at"] is not None
                and order["reservation_expires_at"] <= now
            ):
                order["order_state"] = "EXPIRED"
                touch(order)
                expired_order_count += 1

    # 5. cycle charges (before the reset, so the closing cycle's usage is seen)
    charged_subscription_count = 0
    for subscription in subscriptions:
        if subscription["service_state"] != "ACTIVE":
            continue
        plan = capacity.plan_of_subscription(subscription)
        if plan is None:
            continue
        charge = cycle_charge_cents(
            plan, capacity.overage_gb(subscription, plan=plan, beam=beam)
        )
        subscription["cycle_charge_cents"] = charge
        touch(subscription)
        subscriber = db.subscribers.get(subscription["subscriber_id"])
        if subscriber is not None:
            subscriber["pending_charge_cents"] += charge
            touch(subscriber)
        charged_subscription_count += 1

    # 6. fair-use reset and PRIORITY restoration
    restored_subscription_count = 0
    for subscription in subscriptions:
        if subscription["service_state"] != "ACTIVE":
            continue
        subscription["cycle_priority_gb_used"] = q(0, 3)
        subscription["deprioritized_at"] = None
        subscription["cycle_billing_index"] = beam["billing_cycle_index"]
        if subscription["priority_state"] == "DEPRIORITIZED":
            subscription["priority_state"] = "PRIORITY"
            restored_subscription_count += 1
        touch(subscription)

    # 7. beam recompute
    capacity.recompute_beam(beam)

    # 8. waitlist promotion, swept in cell_code ascending order
    promoted_order_count = 0
    for cell in cells:
        promoted_order_count += capacity.run_promotion(cell)

    # 9. cell recompute
    for cell in cells:
        touch(cell)

    return object_response(
        {
            "beam_id": beam["id"],
            "billing_cycle_index": beam["billing_cycle_index"],
            "license_expired": license_expired,
            "disclosure_expired_count": disclosure_expired_count,
            "expired_order_count": expired_order_count,
            "charged_subscription_count": charged_subscription_count,
            "restored_subscription_count": restored_subscription_count,
            "promoted_order_count": promoted_order_count,
            "capacity_state": capacity.capacity_state(beam),
        }
    )


# ------------------------------------------------------------------- cells ----

@bp.post("/service-cells")
@roles("NetworkOpsEngineer")
def create_cell():
    body = body_dict()
    cell_code = req_str(body, "cell_code", 1, 40)
    beam_id = req_str(body, "beam_id", 1, 100)
    jurisdiction_code = req_jurisdiction(body, "jurisdiction_code")
    max_active_terminals = req_int(body, "max_active_terminals", minimum=0)

    if beam_id not in db.beams:
        fail("ERR_BEAM_NOT_FOUND", "Beam not found.")

    for existing in db.cells.values():
        if existing["cell_code"] == cell_code:
            fail("ERR_INVALID_REQUEST", "cell_code is already in use.")

    record = new_record()
    record.update(
        {
            "cell_code": cell_code,
            "beam_id": beam_id,
            "jurisdiction_code": jurisdiction_code,
            "max_active_terminals": max_active_terminals,
        }
    )
    db.cells[record["id"]] = record
    return object_response(serialize.service_cell(record), 201)


@bp.get("/service-cells/<cell_id>")
@roles("NetworkOpsEngineer", "ProvisioningAgent", "ComplianceOfficer", "Subscriber")
def read_cell(cell_id):
    return object_response(serialize.service_cell(find_cell(cell_id)))


@bp.get("/service-cells")
@roles("NetworkOpsEngineer", "ProvisioningAgent", "ComplianceOfficer", "Subscriber")
def list_cells():
    limit, offset = pagination()
    beam_id = filter_value("beam_id")
    jurisdiction_code = filter_value("jurisdiction_code")
    availability = filter_enum("availability_state", AVAILABILITY_STATES)

    records = ordered(list(db.cells.values()))
    if beam_id is not None:
        records = [r for r in records if r["beam_id"] == beam_id]
    if jurisdiction_code is not None:
        records = [r for r in records if r["jurisdiction_code"] == jurisdiction_code]
    if availability is not None:
        records = [r for r in records if capacity.availability_state(r) == availability]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.service_cell), limit, offset, len(records)
    )


@bp.get("/service-cells/<cell_id>/availability")
@roles("NetworkOpsEngineer", "ProvisioningAgent", "ComplianceOfficer", "Subscriber")
def cell_availability(cell_id):
    """A pure projection: the advertised reading never expires a reservation."""
    cell = find_cell(cell_id)
    beam = capacity.beam_of_cell(cell)
    return object_response(
        {
            "service_cell_id": cell["id"],
            "availability_state": capacity.availability_state(cell),
            "advertised_free_slot_count": capacity.free_slot_count(cell),
            "committed_terminal_count": capacity.committed_terminal_count(cell),
            "reserved_slot_count": capacity.reserved_slot_count(cell),
            "waitlist_depth": capacity.waitlist_depth(cell),
            "waitlist_cap": WAITLIST_CAP_PER_CELL,
            "beam_capacity_state": capacity.capacity_state(beam) if beam else None,
            "beam_state": beam["beam_state"] if beam else None,
        }
    )


# ------------------------------------------------------------------- plans ----

@bp.post("/service-plans")
@roles("ProvisioningAgent")
def publish_plan():
    body = body_dict()
    plan_code = req_str(body, "plan_code", 1, 40)
    committed_rate = req_num(body, "committed_rate_mbps", gt=0)
    priority_tier = req_enum(body, "priority_tier", PRIORITY_TIERS)
    monthly_fee_cents = req_int(body, "monthly_fee_cents", minimum=1)
    priority_data_gb = req_int(body, "priority_data_gb", minimum=0)
    deprioritized_rate = req_num(body, "deprioritized_rate_mbps", gt=0)
    overage_rate = opt_int(body, "overage_rate_cents_per_gb", minimum=0, default=25)
    roaming_allowed = opt_bool(body, "roaming_allowed", False)
    in_motion_allowed = opt_bool(body, "in_motion_allowed", False)

    for existing in db.plans.values():
        if existing["plan_code"] == plan_code:
            fail("ERR_INVALID_REQUEST", "plan_code is already in use.")

    record = new_record()
    record.update(
        {
            "plan_code": plan_code,
            "committed_rate_mbps": committed_rate,
            "priority_tier": priority_tier,
            "monthly_fee_cents": monthly_fee_cents,
            "priority_data_gb": priority_data_gb,
            "deprioritized_rate_mbps": deprioritized_rate,
            "overage_rate_cents_per_gb": overage_rate,
            "roaming_allowed": roaming_allowed,
            "in_motion_allowed": in_motion_allowed,
        }
    )
    db.plans[record["id"]] = record
    return object_response(serialize.service_plan(record), 201)


# ------------------------------------------------------------------- clock ----

@bp.post("/_clock/set_current_utc")
@roles(
    "NetworkOpsEngineer", "ProvisioningAgent", "ComplianceOfficer", "LogisticsCoordinator"
)
def set_clock():
    """Moving the clock is inert: no entity is mutated and no sweep runs."""
    body = body_dict()
    target = req_dt(body, "to_iso8601")
    clock.set(target)
    return object_response({"current_utc": fmt(clock.now())})
