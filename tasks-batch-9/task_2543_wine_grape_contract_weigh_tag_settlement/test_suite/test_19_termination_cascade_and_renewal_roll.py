"""Two ways a multi-year agreement ends. Notice reaches down three levels of the harvest and
then waits out its own period; and when nobody renews, the clock alone decides — one contract
rolls its own term forward and the other stops renewing for good.
"""
from test_helpers import (
    MANAGER,
    accept_contract,
    acknowledge_pick_call,
    book_appointment,
    book_sampling_visit,
    create_allocation,
    create_contract,
    create_crew,
    create_lane,
    issue_pick_call,
    move_clock,
    offer_contract,
    read_appointment,
    read_contract,
    read_lane,
    read_pick_call,
    read_sampling_visit,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    validate_paginated,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"
SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
SLOT_TONS = 20.000

# 2026-08-20T08:00:00Z plus the contractual 90 days is 2026-11-18T08:00:00Z, so a notice
# effective ninety-two days out clears the floor.
TERMINATION_EFFECTIVE_AT = "2026-11-20T08:00:00Z"
THE_DAY_BEFORE_IT_BITES = "2026-11-19T08:00:00Z"

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"
RENEWAL_WINDOW_OPENS_AT = "2026-08-03T00:00:00Z"
RENEWAL_WINDOW_CLOSES_AT = "2026-11-01T00:00:00Z"
ONE_SECOND_BEFORE_THE_WINDOW_OPENS = "2026-08-02T23:59:59Z"
ROLLED_WINDOW_OPENS_AT = "2027-08-03T00:00:00Z"
ROLLED_WINDOW_CLOSES_AT = "2027-11-01T00:00:00Z"

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
LANE = {
    "lane_code": "L1",
    "daily_capacity_tons": 80.000,
    "turnaround_buffer_minutes": 30,
    "max_load_tons": 40.0,
}
TONNAGE_TERMS = {
    "contract_basis": "TONNAGE",
    "base_price_per_ton_cents": 450000,
    "committed_tons": 40.000,
    "over_delivery_policy": "ACCEPT_AT_CONTRACT",
}


# --- Notice reaches down three levels ----------------------------------------------


def _a_two_vintage_contract_with_the_harvest_already_booked() -> dict:
    """An ACTIVE 2026–2027 contract with a recorded sampling visit, an acknowledged call and
    one 20.000-ton slot reserved on lane L1."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["lane"] = create_lane(**LANE)
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-TERMINATE",
        installment_plan=single_installment_plan(),
        term_start_vintage=2026,
        term_end_vintage=2027,
        **TONNAGE_TERMS,
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], SAMPLING_WINDOW[0], SAMPLING_WINDOW[1]
    )
    ctx["visit"] = record_sampling_visit(
        visit["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    call = issue_pick_call(contract["id"], ctx["block"]["id"], TARGET_PICK_AT, 45.000)
    ctx["pick_call"] = acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    ctx["appointment"] = book_appointment(
        call["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], SLOT_TONS
    )
    return ctx


def _notice_served(api, ctx) -> dict:
    return validate_success(
        api.serve_termination_notice(
            ctx["contract"]["id"],
            {"effective_at": TERMINATION_EFFECTIVE_AT, "reason": "winery exits the varietal"},
            MANAGER,
        )
    )


def test_the_booked_slot_had_already_loaded_the_lane_ledger(api):
    """Before any notice, the reservation is carried on the lane it was booked against — which
    is what the cascade later has to unwind.

    PRD: "A successful booking creates the appointment in status `SCHEDULED` and recomputes
    both the lane's `committed_tons` and `scheduled_appointment_count` and the pick call's
    `appointed_tons`."

    Design: Corner/state_machines/termination_notice_cascades_over_pick_calls_appointments_and_lane_tonnage
    """
    ctx = _a_two_vintage_contract_with_the_harvest_already_booked()

    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == 20.000
    assert lane["scheduled_appointment_count"] == 1


def test_notice_moves_the_lifecycle_and_reaches_across_into_the_renewal_dimension(api):
    """The ninety-two-day notice is accepted, and it is the one lifecycle edge that also
    writes the renewal dimension.

    PRD: "The notice stores `termination_effective_at` from the `effective_at` input, sets
    `renewal_status` to `NOT_RENEWING`, and clears the harvest"

    Design: Corner/state_machines/termination_notice_cascades_over_pick_calls_appointments_and_lane_tonnage
    """
    ctx = _a_two_vintage_contract_with_the_harvest_already_booked()

    noticed = _notice_served(api, ctx)
    assert noticed["lifecycle_status"] == "TERMINATION_PENDING"
    assert noticed["termination_effective_at"] == TERMINATION_EFFECTIVE_AT
    assert noticed["renewal_status"] == "NOT_RENEWING"


def test_the_live_call_and_its_slot_are_both_closed_out(api):
    """The cascade goes two levels down: the acknowledged call is withdrawn and the slot it
    had reserved is cancelled.

    PRD: "every pick call of the contract in `ISSUED` or `ACKNOWLEDGED` transitions to
    `WITHDRAWN`, each withdrawn call's `SCHEDULED` appointments transition to `CANCELLED`"

    Design: Corner/state_machines/termination_notice_cascades_over_pick_calls_appointments_and_lane_tonnage
    """
    ctx = _a_two_vintage_contract_with_the_harvest_already_booked()
    _notice_served(api, ctx)

    assert read_pick_call(ctx["pick_call"]["id"])["status"] == "WITHDRAWN"
    assert read_appointment(ctx["appointment"]["id"])["status"] == "CANCELLED"


def test_the_lane_ledger_is_recomputed_rather_than_left_stale(api):
    """The third level down: with the appointment cancelled the lane holds no tonnage and no
    reservations, recomputed from the surviving rows.

    PRD: "each affected lane's `committed_tons` and `scheduled_appointment_count` are
    recomputed, and every `SCHEDULED` sampling visit of the contract transitions to
    `CANCELLED` with its crew's `scheduled_visit_count` recomputed."

    Design: Corner/state_machines/termination_notice_cascades_over_pick_calls_appointments_and_lane_tonnage
    """
    ctx = _a_two_vintage_contract_with_the_harvest_already_booked()
    _notice_served(api, ctx)

    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == 0.000
    assert lane["scheduled_appointment_count"] == 0


def test_the_completed_field_sample_is_not_disturbed(api):
    """Only `SCHEDULED` visits are cancelled, so the visit that already produced its readings
    keeps them.

    PRD: "Recording the readings is likewise a `HarvestCoordinator` action and drives the visit
    `SCHEDULED → COMPLETED`."

    Design: Corner/state_machines/termination_notice_cascades_over_pick_calls_appointments_and_lane_tonnage
    """
    ctx = _a_two_vintage_contract_with_the_harvest_already_booked()
    _notice_served(api, ctx)

    visit = read_sampling_visit(ctx["visit"]["id"])
    assert visit["status"] == "COMPLETED"
    assert float(visit["measured_brix"]) == 24.5


def test_the_notice_period_is_waited_out_and_not_collapsed(api):
    """A day short of the effective instant the contract is still merely pending; at the
    instant itself it is terminated, and no client asked for either.

    PRD: "When the clock later reaches or passes `termination_effective_at`, the contract
    transitions `TERMINATION_PENDING → TERMINATED`, which is terminal."

    Design: Corner/state_machines/termination_notice_cascades_over_pick_calls_appointments_and_lane_tonnage
    """
    ctx = _a_two_vintage_contract_with_the_harvest_already_booked()
    _notice_served(api, ctx)

    move_clock(THE_DAY_BEFORE_IT_BITES)
    assert read_contract(ctx["contract"]["id"])["lifecycle_status"] == "TERMINATION_PENDING"

    move_clock(TERMINATION_EFFECTIVE_AT)
    assert read_contract(ctx["contract"]["id"])["lifecycle_status"] == "TERMINATED"


# --- When nobody renews, the flag decides ------------------------------------------


def _one_producer_with_an_evergreen_and_a_finite_contract() -> dict:
    """Two ACTIVE 2026 contracts on the same block of the same producer, identical except
    that one rolls its own term forward and the other does not."""
    move_clock(CLOCK_PINNED_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )

    for key, contract_code, terms in (
        ("evergreen", "GC-EVER", {"evergreen_flag": True, "evergreen_term_years": 1}),
        ("finite", "GC-STOP", {"evergreen_flag": False}),
    ):
        contract = create_contract(
            ctx["grower"]["id"],
            ctx["spec"]["id"],
            contract_code=contract_code,
            installment_plan=single_installment_plan(),
            term_start_vintage=2026,
            term_end_vintage=2026,
            **TONNAGE_TERMS,
            **terms,
        )
        create_allocation(contract["id"], ctx["block"]["id"])
        offer_contract(contract["id"])
        ctx[key] = accept_contract(contract["id"], ctx["grower"]["id"])
    return ctx


def test_acceptance_fixes_the_same_renewal_window_on_both_contracts(api):
    """The window is derived from the closing vintage and the notice period, so two contracts
    with the same term and the same notice period share it exactly.

    PRD: "The renewal window is fixed: `renewal_window_closes_at` becomes midnight UTC on the
    first of November of the year given by `term_end_vintage` (the year, then
    `-11-01T00:00:00Z`), and `renewal_window_opens_at` becomes that closing instant less
    `termination_notice_days` days."

    Design: Corner/state_machines/evergreen_contract_rolls_at_window_close_while_the_other_stops_renewing
    """
    ctx = _one_producer_with_an_evergreen_and_a_finite_contract()

    for contract in (ctx["evergreen"], ctx["finite"]):
        assert contract["renewal_window_opens_at"] == RENEWAL_WINDOW_OPENS_AT
        assert contract["renewal_window_closes_at"] == RENEWAL_WINDOW_CLOSES_AT
        assert contract["renewal_status"] == "NOT_DUE"


def test_a_second_before_the_window_opens_neither_renewal_dimension_has_moved(api):
    """The opening edge is driven by the clock reaching the interval, and a second short of it
    is still outside.

    PRD: "It starts at `NOT_DUE` on creation and, while the lifecycle stays `ACTIVE`, cycles
    across terms: `NOT_DUE → RENEWAL_WINDOW_OPEN`, and equally `RENEWED →
    RENEWAL_WINDOW_OPEN` and `EVERGREEN_ROLLED → RENEWAL_WINDOW_OPEN` once the window has been
    recomputed for the new term."

    Design: Corner/state_machines/evergreen_contract_rolls_at_window_close_while_the_other_stops_renewing
    """
    ctx = _one_producer_with_an_evergreen_and_a_finite_contract()

    move_clock(ONE_SECOND_BEFORE_THE_WINDOW_OPENS)
    assert read_contract(ctx["evergreen"]["id"])["renewal_status"] == "NOT_DUE"
    assert read_contract(ctx["finite"]["id"])["renewal_status"] == "NOT_DUE"


def test_at_the_opening_instant_exactly_both_windows_are_open(api):
    """The interval begins inclusively, so the instant itself is inside it — and no client
    called anything to make that happen.

    PRD: "they require the lifecycle to be `ACTIVE` and the clock to have moved into the
    half-open interval that begins at `renewal_window_opens_at` and ends strictly before
    `renewal_window_closes_at`."

    Design: Corner/state_machines/evergreen_contract_rolls_at_window_close_while_the_other_stops_renewing
    """
    ctx = _one_producer_with_an_evergreen_and_a_finite_contract()

    move_clock(RENEWAL_WINDOW_OPENS_AT)
    assert read_contract(ctx["evergreen"]["id"])["renewal_status"] == "RENEWAL_WINDOW_OPEN"
    assert read_contract(ctx["finite"]["id"])["renewal_status"] == "RENEWAL_WINDOW_OPEN"


def test_the_evergreen_contract_rolls_its_own_term_forward_at_the_close(api):
    """Nobody renewed, and the flag turns the closing instant into a new term with a window
    recomputed from it so the cycle can repeat.

    PRD: "With the flag true, the term rolls itself forward: `RENEWAL_WINDOW_OPEN →
    EVERGREEN_ROLLED`, `term_end_vintage` increases by `evergreen_term_years`, and the window
    is recomputed from the new `term_end_vintage` so the cycle can repeat."

    Design: Corner/state_machines/evergreen_contract_rolls_at_window_close_while_the_other_stops_renewing
    """
    ctx = _one_producer_with_an_evergreen_and_a_finite_contract()
    move_clock(RENEWAL_WINDOW_OPENS_AT)

    move_clock(RENEWAL_WINDOW_CLOSES_AT)
    rolled = read_contract(ctx["evergreen"]["id"])
    assert rolled["renewal_status"] == "EVERGREEN_ROLLED"
    assert rolled["term_end_vintage"] == 2027
    assert rolled["renewal_window_closes_at"] == ROLLED_WINDOW_CLOSES_AT
    assert rolled["renewal_window_opens_at"] == ROLLED_WINDOW_OPENS_AT
    assert rolled["base_price_per_ton_cents"] == 450000


def test_the_finite_contract_stops_renewing_with_its_term_untouched(api):
    """The same instant, the opposite flag: the renewal dimension reaches its only terminal
    state and the term it was written for does not move.

    PRD: "With the flag false, `RENEWAL_WINDOW_OPEN → NOT_RENEWING`, and the renewal dimension
    stops there for good."

    Design: Corner/state_machines/evergreen_contract_rolls_at_window_close_while_the_other_stops_renewing
    """
    ctx = _one_producer_with_an_evergreen_and_a_finite_contract()
    move_clock(RENEWAL_WINDOW_OPENS_AT)

    move_clock(RENEWAL_WINDOW_CLOSES_AT)
    stopped = read_contract(ctx["finite"]["id"])
    assert stopped["renewal_status"] == "NOT_RENEWING"
    assert stopped["term_end_vintage"] == 2026
    assert stopped["renewal_window_opens_at"] == RENEWAL_WINDOW_OPENS_AT
    assert stopped["renewal_window_closes_at"] == RENEWAL_WINDOW_CLOSES_AT


def test_neither_renewal_outcome_touched_the_lifecycle_dimension(api):
    """Both contracts are still live agreements: the renewal dimension moved on its own and a
    renewal never changes the lifecycle.

    PRD: "The two never constrain each other's vocabulary: a contract can be `ACTIVE` and
    `RENEWAL_WINDOW_OPEN` at once, and a renewal never changes the lifecycle dimension."

    Design: Corner/state_machines/evergreen_contract_rolls_at_window_close_while_the_other_stops_renewing
    """
    ctx = _one_producer_with_an_evergreen_and_a_finite_contract()
    move_clock(RENEWAL_WINDOW_OPENS_AT)
    move_clock(RENEWAL_WINDOW_CLOSES_AT)

    assert read_contract(ctx["evergreen"]["id"])["lifecycle_status"] == "ACTIVE"
    assert read_contract(ctx["finite"]["id"])["lifecycle_status"] == "ACTIVE"


def test_the_renewal_filter_separates_the_two_outcomes(api):
    """Filtering the producer's contracts on the terminal renewal state returns exactly the
    one that stopped renewing.

    PRD: "Contracts are read individually and listed with the optional filters `grower_id`,
    `quality_spec_id`, `lifecycle_status`, `renewal_status` and `tonnage_status`, newest first
    by `created_at` descending."

    Design: Corner/state_machines/evergreen_contract_rolls_at_window_close_while_the_other_stops_renewing
    """
    ctx = _one_producer_with_an_evergreen_and_a_finite_contract()
    move_clock(RENEWAL_WINDOW_OPENS_AT)
    move_clock(RENEWAL_WINDOW_CLOSES_AT)

    rows, meta = validate_paginated(
        api.list_grape_contracts(
            MANAGER,
            params={"grower_id": ctx["grower"]["id"], "renewal_status": "NOT_RENEWING"},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [ctx["finite"]["id"]]
