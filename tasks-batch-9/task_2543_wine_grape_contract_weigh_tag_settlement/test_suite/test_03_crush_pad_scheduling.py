"""Booking crush-pad slots: which refusal wins when a booking breaches two rules at
once, and where the lane's daily ceiling actually falls."""
from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    create_delivery_appointment_payload,
    read_grower,
    read_lane,
    read_pick_call,
    reinstate_grower,
    setup_harvest_ready,
    setup_scheduled_appointment,
    single_installment_plan,
    suspend_grower,
    validate_error,
    validate_success,
)

FIRST_SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
SECOND_SLOT = ("2026-08-25T17:00:00Z", "2026-08-25T19:00:00Z")
BUFFER_BREACHING_SLOT = ("2026-08-25T16:00:00Z", "2026-08-25T18:00:00Z")
BEFORE_TARGET_SLOT = ("2026-08-25T09:00:00Z", "2026-08-25T11:00:00Z")
EVENING_SLOT = ("2026-08-25T20:00:00Z", "2026-08-25T22:00:00Z")
LATE_SLOT = ("2026-08-25T23:00:00Z", "2026-08-25T23:30:00Z")


def _booking(ctx: dict, slot: tuple, planned_tons: float) -> dict:
    return create_delivery_appointment_payload(
        ctx["pick_call"]["id"], ctx["lane"]["id"], slot[0], slot[1], planned_tons
    )


# --- A suspended producer booking into an already-occupied lane window ----------


def _suspended_producer_on_a_busy_lane() -> dict:
    """One 22.000-ton slot on a 30-minute-buffer lane, then the producer is suspended.

    A booking for 16:00-18:00 breaches the buffered window of the 14:00-16:00 slot
    (which runs to 16:30) *and* belongs to a suspended producer.
    """
    ctx = setup_harvest_ready(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "installment_plan": single_installment_plan(),
        },
        lane_overrides={
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 40.0,
        },
        estimated_tons=45.000,
    )
    setup_scheduled_appointment(ctx, FIRST_SLOT[0], FIRST_SLOT[1], planned_tons=22.000)
    suspend_grower(ctx["grower"]["id"], reason="licence documentation lapsed")
    return ctx


def test_producer_suspension_outranks_the_lane_window_conflict(api):
    """The booking breaches both compliance and scheduling; compliance answers first,
    with a 403 rather than the 409 the lane conflict would have produced.

    PRD: "When a delivery appointment is booked for a suspended producer into a lane
    window that also conflicts with an existing booking, the answer is
    `ERR_GROWER_SUSPENDED`, not `ERR_LANE_WINDOW_CONFLICT` — compliance outranks
    scheduling."

    Design: Difficulty/priority_pair_validation_conflict/suspended_grower_outranks_lane_window_conflict
    """
    ctx = _suspended_producer_on_a_busy_lane()

    response = api.create_delivery_appointment(
        _booking(ctx, BUFFER_BREACHING_SLOT, 18.000), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_GROWER_SUSPENDED.value, 403)


def test_the_compliance_refusal_leaves_the_lane_exactly_as_it_was(api):
    """A refused booking books nothing: the lane still carries only the first slot's
    22.000 tons.

    PRD: "Two derived figures round out the row: `committed_tons`, the sum of
    `planned_tons` over the lane's appointments in status `SCHEDULED` or `ARRIVED` to 3
    decimals, and `scheduled_appointment_count`, the count of those same appointments."

    Design: Difficulty/priority_pair_validation_conflict/suspended_grower_outranks_lane_window_conflict
    """
    ctx = _suspended_producer_on_a_busy_lane()
    api.create_delivery_appointment(_booking(ctx, BUFFER_BREACHING_SLOT, 18.000), COORDINATOR)

    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 1
    assert float(lane["committed_tons"]) == 22.000


def test_reinstatement_exposes_the_scheduling_conflict_underneath(api):
    """With the compliance gate cleared, the identical booking reaches rank 33 and is
    refused for overlapping the first slot's buffered window.

    PRD: "the requested half-open window must not overlap the buffered window of any
    other appointment on the same lane in status `SCHEDULED` or `ARRIVED`, where the
    buffered window of an existing appointment runs from its `window_start` less the
    lane's `turnaround_buffer_minutes` to its `window_end` plus the same buffer."

    Design: Difficulty/priority_pair_validation_conflict/suspended_grower_outranks_lane_window_conflict
    """
    ctx = _suspended_producer_on_a_busy_lane()
    reinstated = reinstate_grower(ctx["grower"]["id"])
    assert reinstated["status"] == "ACTIVE"

    response = api.create_delivery_appointment(
        _booking(ctx, BUFFER_BREACHING_SLOT, 18.000), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_LANE_WINDOW_CONFLICT.value, 409)

    assert read_grower(ctx["grower"]["id"])["status"] == "ACTIVE"
    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 1
    assert float(lane["committed_tons"]) == 22.000


# --- The delivery envelope against the lane's daily tonnage ---------------------


def _tight_daily_lane() -> dict:
    """A lane whose whole day holds 30.000 tons, already carrying 22.000 of them."""
    ctx = setup_harvest_ready(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 60.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "installment_plan": single_installment_plan(),
        },
        lane_overrides={
            "lane_code": "L2",
            "daily_capacity_tons": 30.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 40.0,
        },
        estimated_tons=60.000,
    )
    setup_scheduled_appointment(ctx, FIRST_SLOT[0], FIRST_SLOT[1], planned_tons=22.000)
    return ctx


def test_delivery_envelope_outranks_the_daily_tonnage_it_also_breaches(api):
    """A 15.000-ton slot at 09:00 starts before `target_pick_at` and would also take
    the lane's day to 37.000 tons; the timing problem is the one reported.

    PRD: "When the same booking both falls outside the pick call's delivery envelope
    and would breach the lane's daily tonnage, the answer is
    `ERR_APPOINTMENT_OUTSIDE_PICK_WINDOW` — the temporal envelope outranks fiscal
    capacity."

    Design: Difficulty/priority_pair_validation_conflict/pick_window_temporal_outranks_lane_daily_capacity
    """
    ctx = _tight_daily_lane()

    response = api.create_delivery_appointment(
        _booking(ctx, BEFORE_TARGET_SLOT, 15.000), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_OUTSIDE_PICK_WINDOW.value, 422)


def test_moving_the_same_load_inside_the_envelope_exposes_the_daily_breach(api):
    """The same 15.000 tons, now legally timed at 20:00, hits the capacity rule the
    envelope refusal had masked.

    PRD: "summing `planned_tons` over the appointments on the same lane in status
    `SCHEDULED` or `ARRIVED` whose `window_start` falls on the same UTC calendar date
    as the requested `window_start`, and adding the requested `planned_tons`, the total
    may not exceed the lane's `daily_capacity_tons`; equality is accepted, and a breach
    is `ERR_LANE_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/pick_window_temporal_outranks_lane_daily_capacity
    """
    ctx = _tight_daily_lane()

    response = api.create_delivery_appointment(_booking(ctx, EVENING_SLOT, 15.000), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_LANE_DAILY_CAPACITY_EXCEEDED.value, 409)

    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 1
    assert float(lane["committed_tons"]) == 22.000


def test_trimming_the_load_to_the_remaining_headroom_is_accepted(api):
    """8.000 tons into the same 20:00 slot takes the day to exactly 30.000 tons, and
    equality is accepted.

    PRD: "equality is accepted, and a breach is `ERR_LANE_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/pick_window_temporal_outranks_lane_daily_capacity
    """
    ctx = _tight_daily_lane()

    response = api.create_delivery_appointment(_booking(ctx, EVENING_SLOT, 8.000), COORDINATOR)
    appointment = validate_success(response, 201)
    assert appointment["status"] == "SCHEDULED"
    assert float(appointment["planned_tons"]) == 8.000

    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 2
    assert float(lane["committed_tons"]) == 30.000


# --- The daily ceiling reached exactly ------------------------------------------


def _lane_with_two_thirds_of_its_day_booked() -> dict:
    """An 80.000-ton day carrying two 22.000-ton slots, so 36.000 tons remain."""
    ctx = setup_harvest_ready(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 85.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "installment_plan": single_installment_plan(),
        },
        lane_overrides={
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 70.0,
        },
        estimated_tons=85.000,
        block_overrides={"acres": 45.000},
    )
    setup_scheduled_appointment(ctx, FIRST_SLOT[0], FIRST_SLOT[1], planned_tons=22.000)
    setup_scheduled_appointment(ctx, SECOND_SLOT[0], SECOND_SLOT[1], planned_tons=22.000)
    return ctx


def test_a_booking_that_lands_exactly_on_the_daily_ceiling_is_accepted(api):
    """22.000 + 22.000 + 36.000 is exactly the lane's 80.000-ton day, and the third
    booking succeeds because equality is not a breach.

    PRD: "the total may not exceed the lane's `daily_capacity_tons`; equality is
    accepted, and a breach is `ERR_LANE_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/lane_daily_capacity_exact_equality_accepted
    """
    ctx = _lane_with_two_thirds_of_its_day_booked()

    response = api.create_delivery_appointment(_booking(ctx, EVENING_SLOT, 36.000), COORDINATOR)
    appointment = validate_success(response, 201)
    assert appointment["status"] == "SCHEDULED"
    assert float(appointment["planned_tons"]) == 36.000

    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 3
    assert float(lane["committed_tons"]) == 80.000


def test_the_pick_call_records_the_whole_ceiling_as_appointed(api):
    """Every accepted slot rolls into the call's reserved tonnage, so the call reads
    the lane's full day.

    PRD: "`appointed_tons` is the sum of `planned_tons` over the call's appointments in
    status `SCHEDULED` or `ARRIVED`, to 3 decimals."

    Design: Difficulty/boundary_precision_check/lane_daily_capacity_exact_equality_accepted
    """
    ctx = _lane_with_two_thirds_of_its_day_booked()
    api.create_delivery_appointment(_booking(ctx, EVENING_SLOT, 36.000), COORDINATOR)

    assert float(read_pick_call(ctx["pick_call"]["id"])["appointed_tons"]) == 80.000


def test_a_full_day_refuses_even_five_more_tons(api):
    """With the ceiling reached exactly, a further slot at 23:00 — clear of every
    buffered window and well inside the single-load limit — fails on tonnage alone.

    PRD: "Then the lane's **daily tonnage**: summing `planned_tons` over the
    appointments on the same lane in status `SCHEDULED` or `ARRIVED` whose
    `window_start` falls on the same UTC calendar date as the requested `window_start`,
    and adding the requested `planned_tons`, the total may not exceed the lane's
    `daily_capacity_tons`"

    Design: Difficulty/boundary_precision_check/lane_daily_capacity_exact_equality_accepted
    """
    ctx = _lane_with_two_thirds_of_its_day_booked()
    api.create_delivery_appointment(_booking(ctx, EVENING_SLOT, 36.000), COORDINATOR)

    response = api.create_delivery_appointment(_booking(ctx, LATE_SLOT, 5.000), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_LANE_DAILY_CAPACITY_EXCEEDED.value, 409)

    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 3
    assert float(lane["committed_tons"]) == 80.000
