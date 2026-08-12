"""Delivery scheduling: parallel order tracks, job lifecycle, crew overlap and climate
rules (PRD §2.8, §2.9, §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_available_instrument, create_order, order_line,
    post_payment, pay_order_in_full, get_order, get_instrument,
    create_delivery_crew, create_delivery_job, create_delivery_job_payload,
    TEST_USERS,
)

ASSOCIATE = TEST_USERS["sales_associate_headers"]
COORDINATOR = TEST_USERS["service_coordinator_headers"]


def create_paid_order_with(customer, instrument, unit_price, **overrides):
    order = create_order(customer["id"], [order_line(instrument["id"], unit_price)], **overrides)
    return pay_order_in_full(order)


def test_fulfillment_advances_while_payment_stays_deposit(api):
    """PRD §2.9: "A `SalesOrder` carries two independent status machines that advance in
    parallel. Its `payment_status` tracks money (`UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`,
    `FINANCED_ACTIVE`, `COLLECTIONS`, `REFUNDED`), while its `fulfillment_status` tracks the
    physical instrument (`AWAITING_SCHEDULING`, `DELIVERY_SCHEDULED`, `OUT_FOR_DELIVERY`,
    `DELIVERED`, `INSTALLED`, `RETURNED`, `CANCELLED`)."
    PRD §3.6: "Scheduling requires the order's `fulfillment_status` to be
    `AWAITING_SCHEDULING` and its `payment_status` to be one of `DEPOSIT_PAID`,
    `PAID_IN_FULL`, or `FINANCED_ACTIVE`; otherwise the request is rejected with
    `ERR_DELIVERY_NOT_ACTIONABLE`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dims
    """
    customer = create_customer(full_name="Pat Parallel", email="pat@x.com")
    instrument = create_available_instrument(
        serial_number="SN-P-1", category="GRAND", manufacturer="Steinway", model="O",
        year_built=2022, list_price_cents=500_000, floor_price_cents=400_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 500_000)])
    crew = create_delivery_crew(crew_name="Crew Alpha", climate_certified=True)

    deposit = post_payment(order["id"], 200_000)
    assert deposit["payment_status"] == "DEPOSIT_PAID"
    assert deposit["fulfillment_status"] == "AWAITING_SCHEDULING"

    job = create_delivery_job(order["id"], crew["id"],
                              "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)
    validate_success(api.complete_delivery_job(job["id"], COORDINATOR), 200)

    mid = get_order(order["id"])
    assert mid["fulfillment_status"] == "DELIVERED"
    assert mid["payment_status"] == "DEPOSIT_PAID", (
        "fulfillment advances to DELIVERED while payment stays DEPOSIT_PAID")


def test_final_payment_completes_independently_after_delivery(api):
    """PRD §2.9: "Many operations gate on one track and mutate the other — a delivery may
    only be scheduled once money has moved, and completing a return rewrites both tracks at
    once — so each workflow in §3 names the exact states it requires on each track."
    PRD §3.5: "A payment exactly equal to the balance settles the order: `payment_status`
    moves to `PAID_IN_FULL`, every reserved line instrument moves from `RESERVED` to `SOLD`,
    and the consignment payouts of §3.1 are posted to the consignor ledgers."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dims
    """
    customer = create_customer(full_name="Pat Parallel", email="pat@x.com")
    instrument = create_available_instrument(
        serial_number="SN-P-1", category="GRAND", manufacturer="Steinway", model="O",
        year_built=2022, list_price_cents=500_000, floor_price_cents=400_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 500_000)])
    crew = create_delivery_crew(crew_name="Crew Alpha", climate_certified=True)

    post_payment(order["id"], 200_000)
    job = create_delivery_job(order["id"], crew["id"],
                              "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)
    validate_success(api.complete_delivery_job(job["id"], COORDINATOR), 200)

    final = post_payment(order["id"], 315_000)
    assert final["payment_status"] == "PAID_IN_FULL"
    assert final["fulfillment_status"] == "DELIVERED", (
        "payment completes independently of the delivered fulfillment track")
    assert final["balance_cents"] == 0


def test_delivery_complete_from_scheduled_rejected(api):
    """PRD §3.6: "Completing a job requires `EN_ROUTE` and finishes the physical delivery:
    the job reaches its terminal `COMPLETED`, the order's fulfillment moves to `DELIVERED`
    with `delivered_at` stamped from the logical clock, and every line instrument moves from
    `SOLD` to `DELIVERED`. Any start, complete, fail, or reschedule attempted against a job
    in the wrong state is rejected with `ERR_DELIVERY_NOT_ACTIONABLE`."

    Design: Corner/state_machines/delivery_complete_from_scheduled_rejected
    """
    customer = create_customer(full_name="Skip Start", email="skip@x.com")
    instrument = create_available_instrument(
        serial_number="SN-SK-1", category="UPRIGHT", manufacturer="Yamaha", model="U1",
        year_built=2024, list_price_cents=400_000, floor_price_cents=300_000)
    order = create_paid_order_with(customer, instrument, 400_000)
    crew = create_delivery_crew(crew_name="Crew Kappa", climate_certified=False)
    job = create_delivery_job(order["id"], crew["id"],
                              "2026-06-06T09:00:00Z", "2026-06-06T11:00:00Z")

    res = api.complete_delivery_job(job["id"], COORDINATOR)
    validate_error(res, "ERR_DELIVERY_NOT_ACTIONABLE")
    after_job = validate_success(api.get_delivery_job(job["id"], COORDINATOR), 200)
    assert after_job["status"] == "SCHEDULED"
    after_order = get_order(order["id"])
    assert after_order["fulfillment_status"] == "DELIVERY_SCHEDULED"


def test_delivery_fail_reschedule_cycle(api):
    """PRD §3.6: "Failing a job requires `EN_ROUTE`, drops the job to `FAILED`, and returns
    the order to `DELIVERY_SCHEDULED` so the coordinator can reschedule."
    PRD §3.6: "The same overlap and climate checks apply, unchanged, when a failed job is
    rescheduled with a fresh `window_start` and `window_end`."

    Design: Corner/state_machines/delivery_fail_reschedule_cycle
    """
    customer = create_customer(full_name="Fred Fail", email="fred@x.com")
    instrument = create_available_instrument(
        serial_number="SN-FL-1", category="UPRIGHT", manufacturer="Yamaha", model="U1",
        year_built=2024, list_price_cents=400_000, floor_price_cents=300_000)
    order = create_paid_order_with(customer, instrument, 400_000)
    crew = create_delivery_crew(crew_name="Crew Lambda", climate_certified=False)
    job = create_delivery_job(order["id"], crew["id"],
                              "2026-06-07T09:00:00Z", "2026-06-07T11:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)

    failed = validate_success(api.fail_delivery_job(job["id"], COORDINATOR), 200)
    assert failed["status"] == "FAILED"
    assert get_order(order["id"])["fulfillment_status"] == "DELIVERY_SCHEDULED"

    rescheduled = validate_success(api.reschedule_delivery_job(
        job["id"], {"window_start": "2026-06-08T09:00:00Z",
                    "window_end": "2026-06-08T11:00:00Z"}, COORDINATOR), 200)
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["window_start"].startswith("2026-06-08T09:00")
    assert rescheduled["window_end"].startswith("2026-06-08T11:00")


def _climate_priority_setup(api):
    """Non-certified crew occupied 10:00-12:00; second paid order requires climate."""
    customer = create_customer(full_name="Clara Climate", email="clara@x.com")
    i1 = create_available_instrument(
        serial_number="SN-C-1", category="UPRIGHT", manufacturer="Yamaha", model="U1",
        year_built=2024, list_price_cents=500_000, floor_price_cents=400_000)
    i2 = create_available_instrument(
        serial_number="SN-C-2", category="GRAND", manufacturer="Steinway", model="S",
        year_built=2024, list_price_cents=500_000, floor_price_cents=400_000)
    crew = create_delivery_crew(crew_name="Crew NonClimate", climate_certified=False)
    o1 = create_paid_order_with(customer, i1, 500_000)
    create_delivery_job(o1["id"], crew["id"], "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")
    o2 = create_paid_order_with(customer, i2, 500_000, climate_controlled_required=True)
    assert o2["total_cents"] == 535_000
    return crew, o2


def test_climate_safety_error_wins_over_crew_conflict(api):
    """PRD §2.8: "When a request violates several rules at once, the rejection it receives
    is determined by a fixed priority order, evaluated as follows." with "Sixth, physical
    safety: the climate-control requirement on delivery scheduling
    (`ERR_CLIMATE_REQUIREMENT_UNMET`, HTTP 422)" ahead of "Eighth, uniqueness, overlap, and
    capacity: duplicate serials (`ERR_DUPLICATE_SERIAL`, 409), crew window conflicts
    (`ERR_CREW_WINDOW_CONFLICT`, 409)".
    PRD §3.6: "When the order's `climate_controlled_required` flag is set, the assigned crew
    must be `climate_certified`; a non-certified crew is rejected with
    `ERR_CLIMATE_REQUIREMENT_UNMET` (HTTP 422)."
    (The 11:00-13:00 request violates both climate safety and the crew's buffered window.)

    Design: Difficulty/priority_pair_validation_conflict/delivery_climate_safety_beats_crew_conflict_constraint
    """
    crew, o2 = _climate_priority_setup(api)
    res = api.create_delivery_job(
        create_delivery_job_payload(o2["id"], crew["id"],
                                    "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z"),
        COORDINATOR)
    validate_error(res, "ERR_CLIMATE_REQUIREMENT_UNMET")


def test_climate_rejection_leaves_order_awaiting_scheduling(api):
    """PRD §3.6: "When the order's `climate_controlled_required` flag is set, the assigned
    crew must be `climate_certified`; a non-certified crew is rejected with
    `ERR_CLIMATE_REQUIREMENT_UNMET` (HTTP 422)."
    PRD §3.6: "On successful scheduling the job is created in `SCHEDULED` and the order's
    fulfillment advances to `DELIVERY_SCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/delivery_climate_safety_beats_crew_conflict_constraint
    """
    crew, o2 = _climate_priority_setup(api)
    validate_error(api.create_delivery_job(
        create_delivery_job_payload(o2["id"], crew["id"],
                                    "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z"),
        COORDINATOR), "ERR_CLIMATE_REQUIREMENT_UNMET")
    after = get_order(o2["id"])
    assert after["fulfillment_status"] == "AWAITING_SCHEDULING"


def _buffer_setup(api):
    """Crew with one committed job 10:00-12:00; second paid order awaiting scheduling."""
    customer = create_customer(full_name="Buffy Buffer", email="buffy@x.com")
    i1 = create_available_instrument(
        serial_number="SN-BF-1", category="UPRIGHT", manufacturer="Yamaha", model="U1",
        year_built=2024, list_price_cents=400_000, floor_price_cents=300_000)
    i2 = create_available_instrument(
        serial_number="SN-BF-2", category="UPRIGHT", manufacturer="Yamaha", model="U1",
        year_built=2024, list_price_cents=400_000, floor_price_cents=300_000)
    crew = create_delivery_crew(crew_name="Crew Zeta", climate_certified=False)
    o1 = create_paid_order_with(customer, i1, 400_000)
    o2 = create_paid_order_with(customer, i2, 400_000)
    create_delivery_job(o1["id"], crew["id"], "2026-06-02T10:00:00Z", "2026-06-02T12:00:00Z")
    return crew, o2


def test_crew_window_starting_at_prior_end_conflicts(api):
    """PRD §3.6: "Crew time is protected against double-booking under half-open window
    semantics with a mandatory thirty-minute travel buffer: a new job conflicts when its
    window overlaps — after extending each committed job's window by thirty minutes beyond
    its end — another job of the same crew that is `SCHEDULED` or `EN_ROUTE`. A window that
    begins exactly when another job's buffered window ends is acceptable; anything tighter
    is rejected with `ERR_CREW_WINDOW_CONFLICT`."
    (Committed 10:00-12:00 buffers occupation to 12:30; a 12:00 start is tighter.)

    Design: Difficulty/resource_temporal_overlap/crew_half_open_window_with_travel_buffer
    """
    crew, o2 = _buffer_setup(api)
    res = api.create_delivery_job(
        create_delivery_job_payload(o2["id"], crew["id"],
                                    "2026-06-02T12:00:00Z", "2026-06-02T14:00:00Z"),
        COORDINATOR)
    validate_error(res, "ERR_CREW_WINDOW_CONFLICT")


def test_crew_window_starting_at_buffered_end_succeeds(api):
    """PRD §3.6: "Crew time is protected against double-booking under half-open window
    semantics with a mandatory thirty-minute travel buffer: a new job conflicts when its
    window overlaps — after extending each committed job's window by thirty minutes beyond
    its end — another job of the same crew that is `SCHEDULED` or `EN_ROUTE`. A window that
    begins exactly when another job's buffered window ends is acceptable; anything tighter
    is rejected with `ERR_CREW_WINDOW_CONFLICT`."
    PRD §3.6: "On successful scheduling the job is created in `SCHEDULED` and the order's
    fulfillment advances to `DELIVERY_SCHEDULED`."
    (12:30 is exactly the prior job's buffered end, so it is acceptable.)

    Design: Difficulty/resource_temporal_overlap/crew_half_open_window_with_travel_buffer
    """
    crew, o2 = _buffer_setup(api)
    job = validate_success(api.create_delivery_job(
        create_delivery_job_payload(o2["id"], crew["id"],
                                    "2026-06-02T12:30:00Z", "2026-06-02T14:30:00Z"),
        COORDINATOR), 201)
    assert job["status"] == "SCHEDULED"
    assert get_order(o2["id"])["fulfillment_status"] == "DELIVERY_SCHEDULED"
