"""Six scheduling guards stacked on one delivery with every input placed exactly on its legal
edge — the notice floor, the delivery envelope's lower edge, the buffered lane adjacency, the
lane's daily budget, its single-load ceiling and the arrival envelope's opening instant. Every
one of them is a boundary the rule admits, so the whole chain has to go through.
"""
from test_helpers import (
    COORDINATOR,
    accept_contract,
    acknowledge_pick_call,
    appointment_version,
    book_appointment,
    book_sampling_visit,
    capture_gross,
    create_allocation,
    create_contract,
    create_crew,
    create_lane,
    create_pick_call_payload,
    issue_pick_call,
    move_clock,
    offer_contract,
    read_appointment,
    read_lane,
    read_pick_call,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"
FIELD_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")

# 2026-08-22T08:00:00Z is exactly 48 whole hours after the setup instant, and it is also the
# opening edge of the first slot and the instant the first truck presents.
TARGET_PICK_AT = "2026-08-22T08:00:00Z"
FIRST_SLOT = ("2026-08-22T08:00:00Z", "2026-08-22T10:00:00Z")
# 10:30 is the first window's end plus exactly one 30-minute cleanout buffer.
SECOND_SLOT = ("2026-08-22T10:30:00Z", "2026-08-22T12:30:00Z")
TRUCK_PRESENTS_AT = "2026-08-22T08:00:00Z"

MIN_PICK_NOTICE_HOURS = 48
TURNAROUND_BUFFER_MINUTES = 30
MAX_LOAD_TONS = 40.000
DAILY_CAPACITY_TONS = 80.000
ESTIMATED_TONS = 80.000
GROSS_WEIGHT_LBS = 57000

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


def _an_active_contract_and_one_lane() -> dict:
    """An ACTIVE 100.000-ton contract with a PICK_READY block behind it and one open lane whose
    every capacity setting is the figure the probes sit exactly on."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides=dict(SPEC),
    )
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)
    ctx["lane"] = create_lane(
        lane_code="L1",
        daily_capacity_tons=DAILY_CAPACITY_TONS,
        turnaround_buffer_minutes=TURNAROUND_BUFFER_MINUTES,
        max_load_tons=MAX_LOAD_TONS,
    )

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-BOUNDARY-PASS",
        contract_basis="TONNAGE",
        committed_tons=100.000,
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
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], FIELD_WINDOW[0], FIELD_WINDOW[1]
    )
    record_sampling_visit(visit["id"], **RIPE_SAMPLE)
    return ctx


def _a_call_on_the_notice_floor(ctx: dict) -> dict:
    """The call the whole chain hangs from, issued with exactly the minimum notice and answered
    at once so that scheduling may begin."""
    call = issue_pick_call(
        ctx["contract"]["id"], ctx["block"]["id"], TARGET_PICK_AT, ESTIMATED_TONS
    )
    ctx["pick_call"] = acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    return ctx["pick_call"]


def _both_slots_on_one_lane(ctx: dict) -> dict:
    """Two full-size slots on the same lane and the same calendar date, the second beginning
    exactly one cleanout buffer after the first ends."""
    _a_call_on_the_notice_floor(ctx)
    ctx["first_slot"] = book_appointment(
        ctx["pick_call"]["id"], ctx["lane"]["id"], FIRST_SLOT[0], FIRST_SLOT[1], MAX_LOAD_TONS
    )
    ctx["second_slot"] = book_appointment(
        ctx["pick_call"]["id"], ctx["lane"]["id"], SECOND_SLOT[0], SECOND_SLOT[1], MAX_LOAD_TONS
    )
    return ctx


def test_notice_of_exactly_the_contractual_minimum_is_enough(api):
    """Forty-eight hours to the second is at least forty-eight hours, so the call goes out and
    reports the whole hours of warning it gave.

    PRD: "The **notice gate** follows: `target_pick_at` must be at least the contract's
    `min_pick_notice_hours` after the logical clock's current instant, and a shorter horizon is
    refused with `ERR_INSUFFICIENT_PICK_NOTICE` and HTTP 422."

    Design: Corner/validations/every_guard_sitting_exactly_on_its_inclusive_boundary_still_admits_the_load
    """
    ctx = _an_active_contract_and_one_lane()

    call = validate_success(
        api.create_pick_call(
            create_pick_call_payload(
                ctx["contract"]["id"], ctx["block"]["id"], TARGET_PICK_AT, ESTIMATED_TONS
            ),
            COORDINATOR,
        ),
        201,
    )
    assert call["status"] == "ISSUED"
    assert call["notice_hours"] == MIN_PICK_NOTICE_HOURS


def test_a_slot_that_opens_on_the_called_instant_is_inside_the_envelope(api):
    """The grace band runs forward from the called instant, and its lower edge is the instant
    itself — a slot that begins the moment the winery asked for the fruit is admitted.

    PRD: "Next the **delivery envelope**: the appointment's `window_start` must be at or after
    the pick call's `target_pick_at`, and no later than 72 hours after that same
    `target_pick_at` — three days of grace, no more."

    Design: Corner/validations/every_guard_sitting_exactly_on_its_inclusive_boundary_still_admits_the_load
    """
    ctx = _an_active_contract_and_one_lane()
    call = _a_call_on_the_notice_floor(ctx)
    assert call["target_pick_at"] == FIRST_SLOT[0]

    booked = book_appointment(
        call["id"], ctx["lane"]["id"], FIRST_SLOT[0], FIRST_SLOT[1], MAX_LOAD_TONS
    )
    assert booked["status"] == "SCHEDULED"
    assert booked["window_start"] == FIRST_SLOT[0]


def test_a_truckload_of_exactly_the_lanes_ceiling_is_accepted(api):
    """The per-load ceiling is a may-not-exceed, so a slot reserved for precisely the lane's
    maximum is legal.

    PRD: "Last, the **single-load ceiling**: `planned_tons` may not exceed the lane's
    `max_load_tons`, else `ERR_LOAD_EXCEEDS_LANE_MAX`."

    Design: Corner/validations/every_guard_sitting_exactly_on_its_inclusive_boundary_still_admits_the_load
    """
    ctx = _an_active_contract_and_one_lane()
    call = _a_call_on_the_notice_floor(ctx)

    booked = book_appointment(
        call["id"], ctx["lane"]["id"], FIRST_SLOT[0], FIRST_SLOT[1], MAX_LOAD_TONS
    )
    assert float(booked["planned_tons"]) == MAX_LOAD_TONS


def test_two_windows_that_touch_once_the_buffer_is_applied_do_not_conflict(api):
    """The incumbent's buffered window ends at 10:30 and the newcomer starts at 10:30, so the two
    touch without overlapping and the lane takes both.

    PRD: "Windows that merely touch once the buffer has been applied are accepted; a genuine
    overlap is `ERR_LANE_WINDOW_CONFLICT` with HTTP 409."

    Design: Corner/validations/every_guard_sitting_exactly_on_its_inclusive_boundary_still_admits_the_load
    """
    ctx = _an_active_contract_and_one_lane()
    _both_slots_on_one_lane(ctx)

    assert ctx["second_slot"]["status"] == "SCHEDULED"
    assert ctx["second_slot"]["window_start"] == SECOND_SLOT[0]
    assert ctx["first_slot"]["window_end"] == FIRST_SLOT[1]


def test_a_daily_total_that_lands_exactly_on_the_budget_is_accepted(api):
    """Two forty-ton slots on one calendar date make eighty tons against a budget of eighty, and
    equality is explicitly admitted rather than treated as a breach.

    PRD: "summing `planned_tons` over the appointments on the same lane in status `SCHEDULED` or
    `ARRIVED` whose `window_start` falls on the same UTC calendar date as the requested
    `window_start`, and adding the requested `planned_tons`, the total may not exceed the lane's
    `daily_capacity_tons`; equality is accepted, and a breach is
    `ERR_LANE_DAILY_CAPACITY_EXCEEDED`."

    Design: Corner/validations/every_guard_sitting_exactly_on_its_inclusive_boundary_still_admits_the_load
    """
    ctx = _an_active_contract_and_one_lane()
    _both_slots_on_one_lane(ctx)
    assert MAX_LOAD_TONS * 2 == DAILY_CAPACITY_TONS

    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == DAILY_CAPACITY_TONS


def test_a_truck_presenting_on_the_opening_instant_is_inside_the_arrival_envelope(api):
    """The arrival band is inclusive where it opens, so a truck on the scale at the very instant
    the slot begins is weighed rather than turned away.

    PRD: "And the truck must present inside the **arrival envelope**: the logical clock must be
    at or after the appointment's `window_start` and strictly before its `window_end` plus 60
    minutes of late-arrival grace — one hour, no more."

    Design: Corner/validations/every_guard_sitting_exactly_on_its_inclusive_boundary_still_admits_the_load
    """
    ctx = _an_active_contract_and_one_lane()
    _both_slots_on_one_lane(ctx)

    move_clock(TRUCK_PRESENTS_AT)
    tag = capture_gross(
        ctx["first_slot"]["id"],
        ctx["block"]["id"],
        GROSS_WEIGHT_LBS,
        appointment_version(ctx["first_slot"]["id"]),
    )
    assert tag["weigh_status"] == "GROSS_CAPTURED"
    assert read_appointment(ctx["first_slot"]["id"])["status"] == "ARRIVED"


def test_the_arrived_slot_still_counts_against_the_lanes_ledger(api):
    """The ledger spans both live statuses, so the truck that has already presented has not
    released its reservation — and the whole chain of six boundaries has left the lane exactly
    full with two live slots.

    PRD: "Two derived figures round out the row: `committed_tons`, the sum of `planned_tons` over
    the lane's appointments in status `SCHEDULED` or `ARRIVED` to 3 decimals, and
    `scheduled_appointment_count`, the count of those same appointments."

    Design: Corner/validations/every_guard_sitting_exactly_on_its_inclusive_boundary_still_admits_the_load
    """
    ctx = _an_active_contract_and_one_lane()
    _both_slots_on_one_lane(ctx)
    move_clock(TRUCK_PRESENTS_AT)
    capture_gross(
        ctx["first_slot"]["id"],
        ctx["block"]["id"],
        GROSS_WEIGHT_LBS,
        appointment_version(ctx["first_slot"]["id"]),
    )

    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == DAILY_CAPACITY_TONS
    assert lane["scheduled_appointment_count"] == 2
    assert float(read_pick_call(ctx["pick_call"]["id"])["appointed_tons"]) == DAILY_CAPACITY_TONS
