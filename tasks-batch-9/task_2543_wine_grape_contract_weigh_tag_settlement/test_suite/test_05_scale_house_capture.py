"""The scale house: which gate refuses a truck that is both late and unwelcome, and
the exact pound at which a tare stops being legal."""
from test_helpers import (
    SCALE_OPERATOR,
    ApiErrorId,
    appointment_version,
    cancel_appointment,
    capture_gross,
    create_weigh_tag_payload,
    move_clock,
    read_appointment,
    read_weigh_tag,
    setup_harvest_ready,
    setup_scheduled_appointment,
    single_installment_plan,
    tare_payload,
    validate_error,
    validate_success,
)

CANCELLED_SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
FUTURE_SLOT = ("2026-08-27T14:00:00Z", "2026-08-27T16:00:00Z")
BETWEEN_THE_TWO_SLOTS = "2026-08-26T10:00:00Z"

ARRIVAL_AT = "2026-08-25T14:30:00Z"
GROSS_WEIGHT_LBS = 20000


# --- Appointment state against the arrival envelope -----------------------------


def _cancelled_slot_and_a_slot_not_yet_due() -> dict:
    """Two slots on one lane: the first cancelled and long past, the second still two
    days away, with the clock parked between them so neither is receivable."""
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
    setup_scheduled_appointment(ctx, CANCELLED_SLOT[0], CANCELLED_SLOT[1], planned_tons=22.000)
    setup_scheduled_appointment(ctx, FUTURE_SLOT[0], FUTURE_SLOT[1], planned_tons=18.000)
    cancel_appointment(ctx["appointments"][0]["id"], reason="crew reassigned to another block")
    move_clock(BETWEEN_THE_TWO_SLOTS)
    return ctx


def _gross_pass(ctx: dict, appointment: dict, gross_weight_lbs: int = 44000):
    """An inbound pass carrying the slot's freshest version, so the stale-version guard
    of rank 12 cannot pre-empt the gate under test."""
    return create_weigh_tag_payload(
        appointment["id"], ctx["block"]["id"], gross_weight_lbs, appointment_version(appointment["id"])
    )


def test_a_closed_slot_answers_before_the_arrival_envelope_does(api):
    """The truck presents at a cancelled slot hours after its window closed, so both
    the state gate and the envelope gate are breached; the state gate answers.

    PRD: "And when a truck presents against an appointment that is neither scheduled
    nor arrived *and* does so outside the arrival envelope, the answer is
    `ERR_APPOINTMENT_NOT_OPEN` — state legality outranks the temporal envelope."

    Design: Difficulty/priority_pair_validation_conflict/appointment_state_outranks_arrival_window
    """
    ctx = _cancelled_slot_and_a_slot_not_yet_due()

    response = api.create_weigh_tag(_gross_pass(ctx, ctx["appointments"][0]), SCALE_OPERATOR)
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_OPEN.value, 409)


def test_an_open_slot_that_is_simply_early_answers_on_the_envelope(api):
    """The second slot is perfectly legal — `SCHEDULED` — but the clock has not
    reached its `window_start`, so the same operator gets the envelope refusal instead.

    PRD: "And the truck must present inside the **arrival envelope**: the logical clock
    must be at or after the appointment's `window_start` and strictly before its
    `window_end` plus 60 minutes of late-arrival grace — one hour, no more. Outside that
    band the tag is refused with `ERR_OUTSIDE_APPOINTMENT_WINDOW` and HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/appointment_state_outranks_arrival_window
    """
    ctx = _cancelled_slot_and_a_slot_not_yet_due()

    response = api.create_weigh_tag(_gross_pass(ctx, ctx["appointments"][1]), SCALE_OPERATOR)
    validate_error(response, ApiErrorId.ERR_OUTSIDE_APPOINTMENT_WINDOW.value, 409)


def test_neither_refusal_touches_the_appointments(api):
    """No tag was written against either slot, and the still-open slot has not been
    marked a no-show because the clock has not reached its own `window_end`.

    PRD: "And if the logical clock advances to or past `window_end` while the
    appointment is still `SCHEDULED` with `weigh_tag_count` at 0, it transitions
    `SCHEDULED → NO_SHOW`"

    Design: Difficulty/priority_pair_validation_conflict/appointment_state_outranks_arrival_window
    """
    ctx = _cancelled_slot_and_a_slot_not_yet_due()
    api.create_weigh_tag(_gross_pass(ctx, ctx["appointments"][0]), SCALE_OPERATOR)
    api.create_weigh_tag(_gross_pass(ctx, ctx["appointments"][1]), SCALE_OPERATOR)

    cancelled = read_appointment(ctx["appointments"][0]["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["weigh_tag_count"] == 0

    still_open = read_appointment(ctx["appointments"][1]["id"])
    assert still_open["status"] == "SCHEDULED"
    assert still_open["weigh_tag_count"] == 0


# --- The tare boundary: equality legal, one pound over refused ------------------


def _two_identical_gross_passes() -> dict:
    """Two trucks on one slot, each weighing 20000 lb on the way in."""
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
        estimated_tons=40.000,
    )
    setup_scheduled_appointment(ctx, CANCELLED_SLOT[0], CANCELLED_SLOT[1], planned_tons=22.000)
    move_clock(ARRIVAL_AT)
    ctx["zero_tag"] = capture_gross(ctx["appointment"]["id"], ctx["block"]["id"], GROSS_WEIGHT_LBS)
    ctx["over_tag"] = capture_gross(ctx["appointment"]["id"], ctx["block"]["id"], GROSS_WEIGHT_LBS)
    return ctx


def test_a_tare_equal_to_the_gross_is_legal_and_yields_a_zero_net_load(api):
    """The whole load was condemned in the field and dumped, so the empty truck weighs
    exactly what the full one did; the pass is accepted and the net is zero.

    PRD: "The tare may not exceed the gross: a `tare_weight_lbs` greater than
    `gross_weight_lbs` is refused with `ERR_TARE_EXCEEDS_GROSS` and HTTP 422, while
    **equality is explicitly legal** — it records the case where the whole load was
    condemned in the field and dumped before the outbound pass."

    Design: Difficulty/boundary_precision_check/zero_net_weight_tare_equals_gross_boundary
    """
    ctx = _two_identical_gross_passes()

    response = api.tare_weigh_tag(
        ctx["zero_tag"]["id"], tare_payload(GROSS_WEIGHT_LBS), SCALE_OPERATOR
    )
    tag = validate_success(response, 200)
    assert tag["net_weight_lbs"] == 0
    assert float(tag["net_tons"]) == 0.000


def test_a_zero_net_load_is_a_finished_weighing_not_a_missing_tare(api):
    """Zero pounds of fruit is still a completed outbound pass: the weight dimension
    reaches its terminal state and the receipt decision has not started.

    PRD: "An equal tare therefore yields `net_weight_lbs` 0 and `net_tons` 0.000. No
    other row participates in this conversion."

    Design: Difficulty/boundary_precision_check/zero_net_weight_tare_equals_gross_boundary
    """
    ctx = _two_identical_gross_passes()
    api.tare_weigh_tag(ctx["zero_tag"]["id"], tare_payload(GROSS_WEIGHT_LBS), SCALE_OPERATOR)

    tag = read_weigh_tag(ctx["zero_tag"]["id"])
    assert tag["weigh_status"] == "NET_FINAL"
    assert tag["disposition"] == "PENDING"
    assert tag["tare_weight_lbs"] == GROSS_WEIGHT_LBS


def test_a_single_pound_of_overshoot_is_refused(api):
    """One pound past equality flips the boundary, and the refused tag keeps every
    weight field it had before the attempt.

    PRD: "(46) tare not exceeding gross, else `ERR_TARE_EXCEEDS_GROSS` with HTTP 422"

    Design: Difficulty/boundary_precision_check/zero_net_weight_tare_equals_gross_boundary
    """
    ctx = _two_identical_gross_passes()
    api.tare_weigh_tag(ctx["zero_tag"]["id"], tare_payload(GROSS_WEIGHT_LBS), SCALE_OPERATOR)

    response = api.tare_weigh_tag(
        ctx["over_tag"]["id"], tare_payload(GROSS_WEIGHT_LBS + 1), SCALE_OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_TARE_EXCEEDS_GROSS.value, 422)

    tag = read_weigh_tag(ctx["over_tag"]["id"])
    assert tag["tare_weight_lbs"] is None
    assert tag["net_weight_lbs"] is None
    assert tag["weigh_status"] == "GROSS_CAPTURED"


def test_the_slot_counts_both_trucks_and_captures_no_tonnage(api):
    """The appointment arrived on the first pass and counts both tags, yet the tonnage
    it has captured is zero.

    PRD: "The tare also recomputes the appointment's `captured_net_tons`, and it leaves
    the receipt-decision dimension untouched at `PENDING`."

    Design: Difficulty/boundary_precision_check/zero_net_weight_tare_equals_gross_boundary
    """
    ctx = _two_identical_gross_passes()
    api.tare_weigh_tag(ctx["zero_tag"]["id"], tare_payload(GROSS_WEIGHT_LBS), SCALE_OPERATOR)
    api.tare_weigh_tag(ctx["over_tag"]["id"], tare_payload(GROSS_WEIGHT_LBS + 1), SCALE_OPERATOR)

    appointment = read_appointment(ctx["appointment"]["id"])
    assert appointment["status"] == "ARRIVED"
    assert appointment["weigh_tag_count"] == 2
    assert float(appointment["captured_net_tons"]) == 0.000
