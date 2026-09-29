"""Four guards that the receiving lane and the pick call impose on scheduling. A lane that is
shut refuses a booking however idle its windows are, a single truck may not exceed the lane's
per-load ceiling however much daily budget is left, and the notice a producer is owed is
re-checked every time the coordinator moves the date.
"""
from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    accept_contract,
    acknowledge_pick_call,
    book_sampling_visit,
    create_allocation,
    create_contract,
    create_crew,
    create_delivery_appointment_payload,
    create_lane,
    create_pick_call_payload,
    issue_pick_call,
    move_clock,
    offer_contract,
    read_lane,
    read_pick_call,
    record_sampling_visit,
    revise_pick_call,
    setup_reference_book,
    single_installment_plan,
    validate_error,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"
SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")

# The lane's per-load ceiling, one thousandth of a ton above it, and a modest load that would
# have been perfectly bookable had the lane been open.
MAX_LOAD_TONS = 40.000
OVERSIZE_TONS = 40.500
MODEST_TONS = 20.000
DAILY_CAPACITY_TONS = 80.000

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
BLOCK = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
SPEC = {
    "spec_code": "CAB-STD-2026",
    "min_brix_accept": 20.0,
    "brix_bonus_start": 24.0,
    "brix_penalty_start": 22.0,
    "rot_rejection_pct": 8.0,
    "min_brix_pick_call": 21.0,
}
RIPE_SAMPLE = {
    "measured_brix": 24.5,
    "measured_ta_gl": 6.5,
    "measured_ph": 3.40,
    "measured_rot_pct": 1.0,
}


def _a_producer_ready_to_be_scheduled(contract_code: str) -> dict:
    """An ACTIVE 80.000-ton contract with a COMPLETED PICK_READY visit behind it, the clock
    parked so that every notice figure is exact."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides=dict(SPEC),
    )
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code=contract_code,
        contract_basis="TONNAGE",
        committed_tons=DAILY_CAPACITY_TONS,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2027,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"],
        ctx["block"]["id"],
        ctx["crew"]["id"],
        SAMPLING_WINDOW[0],
        SAMPLING_WINDOW[1],
    )
    record_sampling_visit(visit["id"], **RIPE_SAMPLE)
    return ctx


# --- The lane is not a passive lookup -------------------------------------------------


def _one_open_lane_and_one_shut_one() -> dict:
    """Two lanes of identical capacity, differing only in whether they are taking trucks, with
    an acknowledged call waiting to be served."""
    ctx = _a_producer_ready_to_be_scheduled("GC-LANE-GUARD")
    ctx["open_lane"] = create_lane(
        lane_code="L1",
        daily_capacity_tons=DAILY_CAPACITY_TONS,
        turnaround_buffer_minutes=30,
        max_load_tons=MAX_LOAD_TONS,
    )
    ctx["shut_lane"] = create_lane(
        lane_code="L-SHUT",
        daily_capacity_tons=DAILY_CAPACITY_TONS,
        max_load_tons=MAX_LOAD_TONS,
        status="CLOSED",
    )

    call = issue_pick_call(
        ctx["contract"]["id"], ctx["block"]["id"], TARGET_PICK_AT, MAX_LOAD_TONS
    )
    ctx["pick_call"] = acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    return ctx


def _a_booking(api, ctx: dict, lane_key: str, planned_tons: float):
    """A booking request that is legal in every respect except the one under test."""
    return api.create_delivery_appointment(
        create_delivery_appointment_payload(
            ctx["pick_call"]["id"], ctx[lane_key]["id"], SLOT[0], SLOT[1], planned_tons
        ),
        COORDINATOR,
    )


def test_an_entirely_idle_window_on_a_shut_lane_is_still_unbookable(api):
    """The shut lane has never held an appointment, so nothing about the window or the tonnage
    can be the reason — only its standing.

    PRD: "The pick call must be in status `ACKNOWLEDGED` — a call that is merely `ISSUED`, or has
    been suspended, expired, fulfilled or withdrawn, yields `ERR_PICK_CALL_STATE_INVALID` — and
    the lane's `status` must be `OPEN`, else `ERR_LANE_CLOSED`."

    Design: Corner/validations/delivery_appointment_lane_guards_reject_closed_lane_and_oversize_load
    """
    ctx = _one_open_lane_and_one_shut_one()

    validate_error(
        _a_booking(api, ctx, "shut_lane", MODEST_TONS),
        ApiErrorId.ERR_LANE_CLOSED.value,
        409,
    )


def test_a_load_over_the_lanes_single_truck_ceiling_is_refused(api):
    """40.500 tons is half a ton over the per-load ceiling while sitting comfortably inside the
    lane's untouched 80.000-ton daily budget, so the two capacity rules are genuinely separate.

    PRD: "Last, the **single-load ceiling**: `planned_tons` may not exceed the lane's
    `max_load_tons`, else `ERR_LOAD_EXCEEDS_LANE_MAX`."

    Design: Corner/validations/delivery_appointment_lane_guards_reject_closed_lane_and_oversize_load
    """
    ctx = _one_open_lane_and_one_shut_one()
    assert OVERSIZE_TONS < DAILY_CAPACITY_TONS

    validate_error(
        _a_booking(api, ctx, "open_lane", OVERSIZE_TONS),
        ApiErrorId.ERR_LOAD_EXCEEDS_LANE_MAX.value,
        409,
    )


def test_a_load_of_exactly_the_ceiling_is_accepted(api):
    """The ceiling is a may-not-exceed and not a must-stay-under, so a truck loaded to precisely
    the lane's maximum is booked.

    PRD: "`max_load_tons`, the largest single appointment the lane will accept, defaulting to
    40.0 and required to be positive with at most 3 decimals"

    Design: Corner/validations/delivery_appointment_lane_guards_reject_closed_lane_and_oversize_load
    """
    ctx = _one_open_lane_and_one_shut_one()

    booked = validate_success(_a_booking(api, ctx, "open_lane", MAX_LOAD_TONS), 201)
    assert booked["status"] == "SCHEDULED"
    assert float(booked["planned_tons"]) == MAX_LOAD_TONS


def test_only_the_accepted_booking_moved_the_open_lanes_ledger(api):
    """The lane's committed tonnage counts the one slot that survived, at exactly the tonnage it
    reserved.

    PRD: "Two derived figures round out the row: `committed_tons`, the sum of `planned_tons` over
    the lane's appointments in status `SCHEDULED` or `ARRIVED` to 3 decimals, and
    `scheduled_appointment_count`, the count of those same appointments."

    Design: Corner/validations/delivery_appointment_lane_guards_reject_closed_lane_and_oversize_load
    """
    ctx = _one_open_lane_and_one_shut_one()
    _a_booking(api, ctx, "shut_lane", MODEST_TONS)
    _a_booking(api, ctx, "open_lane", OVERSIZE_TONS)
    _a_booking(api, ctx, "open_lane", MAX_LOAD_TONS)

    lane = read_lane(ctx["open_lane"]["id"])
    assert float(lane["committed_tons"]) == MAX_LOAD_TONS
    assert lane["scheduled_appointment_count"] == 1


def test_the_shut_lane_was_left_without_a_trace(api):
    """A refusal at rank 23 writes nothing, so the closed lane's ledger is exactly as it was
    opened — empty.

    PRD: "When a single request violates several rules, exactly one error comes back, and which
    one is fully determined."

    Design: Corner/validations/delivery_appointment_lane_guards_reject_closed_lane_and_oversize_load
    """
    ctx = _one_open_lane_and_one_shut_one()
    _a_booking(api, ctx, "shut_lane", MODEST_TONS)

    lane = read_lane(ctx["shut_lane"]["id"])
    assert lane["status"] == "CLOSED"
    assert float(lane["committed_tons"]) == 0.000
    assert lane["scheduled_appointment_count"] == 0


# --- The notice a producer is owed, re-checked on every revision -----------------------


ONE_SECOND_SHORT_OF_THE_FLOOR = "2026-08-22T07:59:59Z"
EXACTLY_THE_NOTICE_FLOOR = "2026-08-22T08:00:00Z"
ACK_DEADLINE_AT = "2026-08-21T08:00:00Z"
PULLED_TO_TWENTY_FOUR_HOURS_OUT = "2026-08-21T08:00:00Z"
FIRST_REVISED_DATE = "2026-08-23T08:00:00Z"
SECOND_REVISED_DATE = "2026-08-24T08:00:00Z"
THIRD_REVISED_DATE = "2026-08-26T08:00:00Z"

MIN_PICK_NOTICE_HOURS = 48
ESTIMATED_TONS = 10.000
REVISED_ESTIMATED_TONS = 12.000


def _a_call_at_the_notice_floor(ctx: dict) -> dict:
    """A call issued with exactly the minimum notice, then acknowledged so that it is eligible
    to be revised."""
    call = issue_pick_call(
        ctx["contract"]["id"], ctx["block"]["id"], EXACTLY_THE_NOTICE_FLOOR, ESTIMATED_TONS
    )
    return acknowledge_pick_call(call["id"], ctx["grower"]["id"])


def _both_revisions_spent(ctx: dict) -> dict:
    """The call moved twice, each revision followed by a fresh acknowledgement, leaving the
    revision counter at its ceiling."""
    call = _a_call_at_the_notice_floor(ctx)
    revise_pick_call(
        call["id"], FIRST_REVISED_DATE, revised_estimated_tons=REVISED_ESTIMATED_TONS
    )
    acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    revise_pick_call(call["id"], SECOND_REVISED_DATE)
    acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    return call


def test_one_second_short_of_the_notice_floor_is_refused(api):
    """47 hours 59 minutes 59 seconds of warning is not the 48 whole hours the agreement
    promises, and the floor is not rounded in the winery's favour.

    PRD: "The **notice gate** follows: `target_pick_at` must be at least the contract's
    `min_pick_notice_hours` after the logical clock's current instant, and a shorter horizon is
    refused with `ERR_INSUFFICIENT_PICK_NOTICE` and HTTP 422."

    Design: Corner/validations/pick_call_notice_floor_and_revision_ceiling_are_enforced
    """
    ctx = _a_producer_ready_to_be_scheduled("GC-NOTICE")

    validate_error(
        api.create_pick_call(
            create_pick_call_payload(
                ctx["contract"]["id"],
                ctx["block"]["id"],
                ONE_SECOND_SHORT_OF_THE_FLOOR,
                ESTIMATED_TONS,
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_INSUFFICIENT_PICK_NOTICE.value,
        422,
    )


def test_exactly_the_notice_floor_is_accepted_and_derives_both_instants(api):
    """At least means at least: the horizon is admitted, the whole hours of warning come back as
    48, and the acknowledgement clock starts from the moment of issue.

    PRD: "`notice_hours` is the number of whole hours between `issued_at` and `target_pick_at` —
    the elapsed seconds between the two instants divided by 3600 and rounded down to a whole
    number. `ack_deadline_at` is `issued_at` plus the contract's `pick_call_ack_window_hours`
    hours."

    Design: Corner/validations/pick_call_notice_floor_and_revision_ceiling_are_enforced
    """
    ctx = _a_producer_ready_to_be_scheduled("GC-NOTICE")

    call = validate_success(
        api.create_pick_call(
            create_pick_call_payload(
                ctx["contract"]["id"],
                ctx["block"]["id"],
                EXACTLY_THE_NOTICE_FLOOR,
                ESTIMATED_TONS,
            ),
            COORDINATOR,
        ),
        201,
    )
    assert call["notice_hours"] == MIN_PICK_NOTICE_HOURS
    assert call["ack_deadline_at"] == ACK_DEADLINE_AT
    assert call["status"] == "ISSUED"
    assert call["revision_count"] == 0


def test_the_same_floor_is_re_checked_when_the_date_is_moved(api):
    """This is the half that lets a coordinator pull the harvest forward to tomorrow if it is
    forgotten: the revised date gets its notice recomputed and refused on exactly the same rule.

    PRD: "The recomputed notice must still satisfy the contract's `min_pick_notice_hours`, else
    `ERR_INSUFFICIENT_PICK_NOTICE`."

    Design: Corner/validations/pick_call_notice_floor_and_revision_ceiling_are_enforced
    """
    ctx = _a_producer_ready_to_be_scheduled("GC-NOTICE")
    call = _a_call_at_the_notice_floor(ctx)

    validate_error(
        api.revise_pick_call(
            call["id"], {"revised_target_pick_at": PULLED_TO_TWENTY_FOUR_HOURS_OUT}, COORDINATOR
        ),
        ApiErrorId.ERR_INSUFFICIENT_PICK_NOTICE.value,
        422,
    )
    assert read_pick_call(call["id"])["revision_count"] == 0


def test_each_accepted_revision_sends_the_call_back_for_acknowledgement(api):
    """A revised call is a new promise, so it returns to the issued state with the previous
    acknowledgement erased — and the optional tonnage replaces the estimate when it is supplied.

    PRD: "On success `revision_count` increments by 1, `acknowledged_at` is cleared, and
    `issued_at`, `notice_hours` and `ack_deadline_at` are all recomputed from the logical clock."

    Design: Corner/validations/pick_call_notice_floor_and_revision_ceiling_are_enforced
    """
    ctx = _a_producer_ready_to_be_scheduled("GC-NOTICE")
    call = _a_call_at_the_notice_floor(ctx)

    once = revise_pick_call(
        call["id"], FIRST_REVISED_DATE, revised_estimated_tons=REVISED_ESTIMATED_TONS
    )
    assert once["status"] == "ISSUED"
    assert once["acknowledged_at"] is None
    assert once["revision_count"] == 1
    assert float(once["estimated_tons"]) == REVISED_ESTIMATED_TONS

    acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    twice = revise_pick_call(call["id"], SECOND_REVISED_DATE)
    assert twice["status"] == "ISSUED"
    assert twice["acknowledged_at"] is None
    assert twice["revision_count"] == 2


def test_the_third_revision_terminates_the_cycle(api):
    """The issued-and-acknowledged loop is genuinely a cycle, so something has to stop it: two
    revisions is the ceiling and the counter is compared strictly.

    PRD: "It is permitted only while `revision_count` is strictly less than 2, so the third
    revision is refused with `ERR_MAX_PICK_CALL_REVISIONS_EXCEEDED` and HTTP 409, terminating the
    cycle; and only while the call is `ACKNOWLEDGED`, any other status being
    `ERR_PICK_CALL_STATE_INVALID`."

    Design: Corner/validations/pick_call_notice_floor_and_revision_ceiling_are_enforced
    """
    ctx = _a_producer_ready_to_be_scheduled("GC-NOTICE")
    call = _both_revisions_spent(ctx)

    validate_error(
        api.revise_pick_call(
            call["id"], {"revised_target_pick_at": THIRD_REVISED_DATE}, COORDINATOR
        ),
        ApiErrorId.ERR_MAX_PICK_CALL_REVISIONS_EXCEEDED.value,
        409,
    )


def test_the_refused_third_revision_changed_nothing_about_the_call(api):
    """The call still carries the second revision's date and the acknowledgement that followed
    it, so the refusal neither moved the harvest nor reset the state.

    PRD: "The revision carries a mandatory `revised_target_pick_at` which replaces
    `target_pick_at`, and an optional `revised_estimated_tons` which replaces `estimated_tons`
    when supplied."

    Design: Corner/validations/pick_call_notice_floor_and_revision_ceiling_are_enforced
    """
    ctx = _a_producer_ready_to_be_scheduled("GC-NOTICE")
    call = _both_revisions_spent(ctx)
    api.revise_pick_call(
        call["id"], {"revised_target_pick_at": THIRD_REVISED_DATE}, COORDINATOR
    )

    final = read_pick_call(call["id"])
    assert final["revision_count"] == 2
    assert final["target_pick_at"] == SECOND_REVISED_DATE
    assert final["status"] == "ACKNOWLEDGED"
