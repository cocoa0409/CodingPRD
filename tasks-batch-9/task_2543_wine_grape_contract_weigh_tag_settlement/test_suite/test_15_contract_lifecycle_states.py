"""The contract's two independent dimensions, from the states a fresh row opens in,
through the negotiation loop and the pivot that derives the harvest, to the terminal
state that refuses everything."""
from test_helpers import (
    CLERK,
    COORDINATOR,
    MANAGER,
    ApiErrorId,
    accept_contract,
    book_sampling_visit,
    counter_contract,
    create_allocation,
    create_block,
    create_contract,
    create_crew,
    create_sampling_visit_payload,
    list_installments,
    make_grower_headers,
    move_clock,
    offer_contract,
    read_allocation,
    read_contract,
    setup_reference_book,
    single_installment_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"
SETUP_AT = "2026-08-20T08:00:00Z"
VISIT_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")

RENEWAL_WINDOW_CLOSES_AT = "2026-11-01T00:00:00Z"
RENEWAL_WINDOW_OPENS_AT = "2026-08-03T00:00:00Z"

THREE_INSTALLMENTS = [
    {"installment_no": 1, "pct_of_settlement": 40.0, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 2, "pct_of_settlement": 30.0, "due_offset_days": 60, "lien_protected": True},
    {"installment_no": 3, "pct_of_settlement": 30.0, "due_offset_days": 90, "lien_protected": False},
]
TWO_INSTALLMENTS = [
    {"installment_no": 1, "pct_of_settlement": 50.0, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 2, "pct_of_settlement": 50.0, "due_offset_days": 60, "lien_protected": True},
]

TONNAGE_TERMS = {
    "contract_basis": "TONNAGE",
    "base_price_per_ton_cents": 450000,
    "committed_tons": 40.000,
    "over_delivery_policy": "ACCEPT_AT_CONTRACT",
    "term_start_vintage": 2026,
    "term_end_vintage": 2026,
}


# --- Where a fresh row opens -------------------------------------------------------


def _a_draft_and_its_first_sampling_window() -> dict:
    """A drafted contract, its allocation, and one booked sampling window."""
    move_clock(SETUP_AT)
    book = setup_reference_book(
        grower_overrides={
            "name": "Ridgeline Vineyards",
            "license_number": "PL-44821",
            "region_code": "NAPA-NORTH",
        },
        block_overrides={
            "block_code": "B-12",
            "varietal": "CABERNET_SAUVIGNON",
            "acres": 20.000,
            "expected_yield_tons_per_acre": 2.000,
            "ava_code": "NAPA-VALLEY",
        },
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    crew = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)
    contract = create_contract(
        book["grower"]["id"], book["spec"]["id"], contract_code="GC-INIT",
        installment_plan=single_installment_plan(), **TONNAGE_TERMS,
    )
    allocation = create_allocation(contract["id"], book["block"]["id"])
    visit = book_sampling_visit(
        contract["id"], book["block"]["id"], crew["id"], VISIT_WINDOW[0], VISIT_WINDOW[1]
    )
    book.update({"crew": crew, "contract": contract, "allocation": allocation, "visit": visit})
    return book


def test_a_fresh_contract_initialises_both_of_its_dimensions_independently():
    """The lifecycle and the renewal dimension are separate machines, and creation seeds
    both — the renewal dimension is not left null waiting for a lifecycle event.

    PRD: "Contracts carry **two independent state dimensions**. `lifecycle_status` moves
    through `DRAFT`, `OFFERED`, `COUNTERED`, `ACTIVE`, `SETTLED`, `CLOSED`,
    `TERMINATION_PENDING`, `TERMINATED` and `WITHDRAWN`, of which `CLOSED`, `TERMINATED` and
    `WITHDRAWN` are terminal. `renewal_status` moves independently through `NOT_DUE`,
    `RENEWAL_WINDOW_OPEN`, `RENEWED`, `EVERGREEN_ROLLED` and `NOT_RENEWING`, of which
    `NOT_RENEWING` is terminal."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    ctx = _a_draft_and_its_first_sampling_window()

    assert ctx["contract"]["lifecycle_status"] == "DRAFT"
    assert ctx["contract"]["renewal_status"] == "NOT_DUE"
    assert ctx["contract"]["tonnage_status"] == "OPEN"
    assert ctx["contract"]["offer_round"] == 0


def test_a_fresh_sampling_visit_is_scheduled_with_no_maturity_verdict_yet():
    """Maturity is not a default to be guessed at: until the readings are recorded, the flag
    and all four measurements say nothing at all.

    PRD: "A successful booking creates the visit in status `SCHEDULED` and recomputes the
    crew's `scheduled_visit_count`." … "All four are null while the visit is merely
    `SCHEDULED`." … "`maturity_flag` is also null while the visit is `SCHEDULED`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    ctx = _a_draft_and_its_first_sampling_window()

    assert ctx["visit"]["status"] == "SCHEDULED"
    assert ctx["visit"]["maturity_flag"] is None
    assert ctx["visit"]["measured_brix"] is None
    assert ctx["visit"]["measured_ta_gl"] is None
    assert ctx["visit"]["measured_ph"] is None
    assert ctx["visit"]["measured_rot_pct"] is None


def test_a_block_can_be_committed_while_the_contract_is_still_a_draft():
    """Allocation is a child write the draft state admits, and the caps it will eventually
    carry are null until the contract is accepted.

    PRD: "Allocations may be created while the contract is `DRAFT`, `OFFERED` or `ACTIVE`;
    anything else is `ERR_CONTRACT_STATE_INVALID`. At creation time `block_cap_tons` and
    `block_hard_cap_tons` are null and stay null until the contract is accepted."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    ctx = _a_draft_and_its_first_sampling_window()

    allocation = read_allocation(ctx["allocation"]["id"])
    assert allocation["contract_id"] == ctx["contract"]["id"]
    assert allocation["block_cap_tons"] is None
    assert allocation["block_hard_cap_tons"] is None
    assert float(allocation["delivered_net_tons"]) == 0.000


def test_the_payment_schedule_is_not_materialised_at_draft_time(api):
    """The plan is a template on the contract; no installment row exists until the pivot
    that creates them runs.

    PRD: "And the payment schedule is materialised: one installment row is created for each
    element of `installment_plan`, copying `installment_no`, `pct_of_settlement`,
    `due_offset_days` and `lien_protected` verbatim, each starting in status
    `PENDING_SETTLEMENT` with `planned_amount_cents` 0 and `paid_amount_cents` 0."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    ctx = _a_draft_and_its_first_sampling_window()

    rows, meta = validate_paginated(
        api.list_installments(CLERK, params={"contract_id": ctx["contract"]["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


# --- The pivot: what the offer and the acceptance derive --------------------------


def _offered_at_a_revised_price_then_accepted(installment_plan=None) -> dict:
    """A draft put on the table at 460000 cents rather than the 450000 it was drafted at,
    then accepted by its producer."""
    move_clock(CLOCK_PINNED_AT)
    book = setup_reference_book(
        grower_overrides={
            "name": "Ridgeline Vineyards",
            "license_number": "PL-44821",
            "region_code": "NAPA-NORTH",
        },
        block_overrides={
            "block_code": "B-12",
            "varietal": "CABERNET_SAUVIGNON",
            "acres": 20.000,
            "expected_yield_tons_per_acre": 2.000,
            "ava_code": "NAPA-VALLEY",
        },
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    contract = create_contract(
        book["grower"]["id"], book["spec"]["id"], contract_code="GC-ACCEPT",
        installment_plan=installment_plan or THREE_INSTALLMENTS, **TONNAGE_TERMS,
    )
    allocation = create_allocation(contract["id"], book["block"]["id"])
    book["offered"] = offer_contract(contract["id"], base_price_per_ton_cents=460000)
    book["contract"] = accept_contract(contract["id"], book["grower"]["id"])
    book["allocation"] = allocation
    return book


def test_putting_a_contract_on_the_table_counts_the_round_and_applies_the_new_price():
    """The offer is a price event as well as a state event: the override supplied in the body
    replaces the drafted price and the negotiation counter advances.

    PRD: "Putting a contract on the table is a `GrowerRelationsManager` action that drives
    `DRAFT → OFFERED`, and — because the negotiation is a genuine cycle — also `COUNTERED →
    OFFERED`. It accepts an optional `base_price_per_ton_cents`, and when that value is
    supplied it replaces the stored price. Every such transition increments `offer_round` by
    1, and it is permitted only while `offer_round` is strictly less than 3."

    Design: Corner/state_machines/offer_then_accept_applies_every_declared_side_effect
    """
    ctx = _offered_at_a_revised_price_then_accepted()

    assert ctx["offered"]["lifecycle_status"] == "OFFERED"
    assert ctx["offered"]["offer_round"] == 1
    assert ctx["offered"]["base_price_per_ton_cents"] == 460000


def test_acceptance_moves_the_lifecycle_and_leaves_the_renewal_dimension_alone():
    """The pivot drives one machine only; the renewal dimension has not been touched by it.

    PRD: "The two never constrain each other's vocabulary: a contract can be `ACTIVE` and
    `RENEWAL_WINDOW_OPEN` at once, and a renewal never changes the lifecycle dimension."

    Design: Corner/state_machines/offer_then_accept_applies_every_declared_side_effect
    """
    ctx = _offered_at_a_revised_price_then_accepted()

    assert ctx["contract"]["lifecycle_status"] == "ACTIVE"
    assert ctx["contract"]["renewal_status"] == "NOT_DUE"


def test_acceptance_derives_the_scope_and_both_tonnage_caps():
    """A tonnage contract caps at its committed tonnage, and the hard cap is that figure
    dilated by the tolerance.

    PRD: "On a `TONNAGE` contract it is simply `committed_tons`, and `cap_scope` is
    `PER_CONTRACT`."

    Design: Corner/state_machines/offer_then_accept_applies_every_declared_side_effect
    """
    ctx = _offered_at_a_revised_price_then_accepted()

    assert ctx["contract"]["cap_scope"] == "PER_CONTRACT"
    assert float(ctx["contract"]["contract_cap_tons"]) == 40.000
    assert float(ctx["contract"]["hard_cap_tons"]) == 44.000
    assert ctx["contract"]["tonnage_status"] == "OPEN"


def test_acceptance_fixes_both_ends_of_the_renewal_window():
    """The window closes at the first of November of the closing vintage and opens a
    termination-notice period earlier — ninety days, so the third of August.

    PRD: "The renewal window is fixed: `renewal_window_closes_at` becomes midnight UTC on the
    first of November of the year given by `term_end_vintage` (the year, then
    `-11-01T00:00:00Z`), and `renewal_window_opens_at` becomes that closing instant less
    `termination_notice_days` days."

    Design: Corner/state_machines/offer_then_accept_applies_every_declared_side_effect
    """
    ctx = _offered_at_a_revised_price_then_accepted()

    assert ctx["contract"]["renewal_window_closes_at"] == RENEWAL_WINDOW_CLOSES_AT
    assert ctx["contract"]["renewal_window_opens_at"] == RENEWAL_WINDOW_OPENS_AT


def test_a_per_contract_scope_leaves_the_per_block_caps_null():
    """The caps live on the contract, not on the allocation: a `PER_CONTRACT` scope means the
    allocation's own cap fields stay empty after the pivot.

    PRD: "On `PER_CONTRACT` contracts the per-allocation `block_cap_tons` and
    `block_hard_cap_tons` remain null."

    Design: Corner/state_machines/offer_then_accept_applies_every_declared_side_effect
    """
    ctx = _offered_at_a_revised_price_then_accepted()

    allocation = read_allocation(ctx["allocation"]["id"])
    assert allocation["block_cap_tons"] is None
    assert allocation["block_hard_cap_tons"] is None


def test_the_pivot_materialises_one_installment_row_per_plan_element():
    """Three plan elements become three rows, each copying its own template values verbatim
    and each unpriced and undated until the vintage closes.

    PRD: "And the payment schedule is materialised: one installment row is created for each
    element of `installment_plan`, copying `installment_no`, `pct_of_settlement`,
    `due_offset_days` and `lien_protected` verbatim, each starting in status
    `PENDING_SETTLEMENT` with `planned_amount_cents` 0 and `paid_amount_cents` 0."

    Design: Corner/state_machines/offer_then_accept_applies_every_declared_side_effect
    """
    ctx = _offered_at_a_revised_price_then_accepted()

    rows = sorted(
        list_installments(contract_id=ctx["contract"]["id"]), key=lambda row: row["installment_no"]
    )
    assert len(rows) == 3
    assert [row["installment_no"] for row in rows] == [1, 2, 3]
    assert [float(row["pct_of_settlement"]) for row in rows] == [40.0, 30.0, 30.0]
    assert [row["due_offset_days"] for row in rows] == [30, 60, 90]
    assert [row["lien_protected"] for row in rows] == [True, True, False]
    for row in rows:
        assert row["status"] == "PENDING_SETTLEMENT"
        assert row["planned_amount_cents"] == 0
        assert row["paid_amount_cents"] == 0
        assert row["due_at"] is None


# --- The negotiation cycle ---------------------------------------------------------


def _a_contract_haggled_over_three_rounds() -> dict:
    """450000 offered, countered at 520000, re-offered at 480000, countered at 500000,
    re-offered at 495000 and accepted there."""
    move_clock(CLOCK_PINNED_AT)
    book = setup_reference_book(
        grower_overrides={
            "name": "Ridgeline Vineyards",
            "license_number": "PL-44821",
            "region_code": "NAPA-NORTH",
        },
        block_overrides={
            "block_code": "B-12",
            "varietal": "CABERNET_SAUVIGNON",
            "acres": 20.000,
            "expected_yield_tons_per_acre": 2.000,
            "ava_code": "NAPA-VALLEY",
        },
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    contract = create_contract(
        book["grower"]["id"], book["spec"]["id"], contract_code="GC-CYCLE",
        installment_plan=single_installment_plan(), **TONNAGE_TERMS,
    )
    create_allocation(contract["id"], book["block"]["id"])
    grower_id = book["grower"]["id"]

    book["first_offer"] = offer_contract(contract["id"])
    book["first_counter"] = counter_contract(contract["id"], grower_id, 520000)
    book["second_offer"] = offer_contract(contract["id"], base_price_per_ton_cents=480000)
    book["second_counter"] = counter_contract(contract["id"], grower_id, 500000)
    book["third_offer"] = offer_contract(contract["id"], base_price_per_ton_cents=495000)
    book["accepted"] = accept_contract(contract["id"], grower_id)
    book["contract"] = contract
    return book


def test_an_offer_without_an_override_leaves_the_drafted_price_standing():
    """The price override is optional; omitting it puts the drafted number on the table
    unchanged while still counting the round.

    PRD: "It accepts an optional `base_price_per_ton_cents`, and when that value is supplied
    it replaces the stored price."

    Design: Corner/state_machines/counter_offer_loop_returns_to_offered_and_carries_the_negotiated_price
    """
    ctx = _a_contract_haggled_over_three_rounds()

    assert ctx["first_offer"]["lifecycle_status"] == "OFFERED"
    assert ctx["first_offer"]["offer_round"] == 1
    assert ctx["first_offer"]["base_price_per_ton_cents"] == 450000


def test_a_counter_records_the_producers_number_without_applying_it():
    """The counter is a proposal, not a price change: the contract's own price is still the
    offered one, with the producer's figure parked in its own field.

    PRD: "Countering drives `OFFERED → COUNTERED`, is permitted only to the `Grower` whose
    identifier matches the contract's `grower_id`, and requires a
    `counter_base_price_per_ton_cents` in the body, which is stored on the contract as
    `countered_price_per_ton_cents`. That field is null until the first counter occurs."

    Design: Corner/state_machines/counter_offer_loop_returns_to_offered_and_carries_the_negotiated_price
    """
    ctx = _a_contract_haggled_over_three_rounds()

    assert ctx["contract"]["countered_price_per_ton_cents"] is None
    assert ctx["first_counter"]["lifecycle_status"] == "COUNTERED"
    assert ctx["first_counter"]["countered_price_per_ton_cents"] == 520000
    assert ctx["first_counter"]["base_price_per_ton_cents"] == 450000


def test_the_re_offer_closes_the_loop_and_is_what_actually_moves_the_price():
    """`COUNTERED → OFFERED` is a real edge, so the second lap returns to the offered state
    with the round counted again — and this time the override does change the price.

    PRD: "Putting a contract on the table is a `GrowerRelationsManager` action that drives
    `DRAFT → OFFERED`, and — because the negotiation is a genuine cycle — also `COUNTERED →
    OFFERED`."

    Design: Corner/state_machines/counter_offer_loop_returns_to_offered_and_carries_the_negotiated_price
    """
    ctx = _a_contract_haggled_over_three_rounds()

    assert ctx["second_offer"]["lifecycle_status"] == "OFFERED"
    assert ctx["second_offer"]["offer_round"] == 2
    assert ctx["second_offer"]["base_price_per_ton_cents"] == 480000


def test_the_third_lap_is_still_legal_because_the_ceiling_is_the_round_already_reached():
    """The guard reads the counter *before* the increment, so an offer made at round 2 is
    permitted and lands the contract on round 3.

    PRD: "Every such transition increments `offer_round` by 1, and it is permitted only while
    `offer_round` is strictly less than 3."

    Design: Corner/state_machines/counter_offer_loop_returns_to_offered_and_carries_the_negotiated_price
    """
    ctx = _a_contract_haggled_over_three_rounds()

    assert ctx["second_counter"]["lifecycle_status"] == "COUNTERED"
    assert ctx["second_counter"]["offer_round"] == 2
    assert ctx["third_offer"]["lifecycle_status"] == "OFFERED"
    assert ctx["third_offer"]["offer_round"] == 3
    assert ctx["third_offer"]["base_price_per_ton_cents"] == 495000


def test_acceptance_out_of_the_middle_of_the_cycle_locks_the_last_offered_price():
    """The producer accepted after a counter of 500000, but what binds is the winery's last
    offer of 495000 — neither the opening 450000 nor the counter.

    PRD: "Acceptance is the pivot of the whole system. It is a `Grower` action on the
    contract's own producer, it drives `OFFERED → ACTIVE`, it takes no request body"

    Design: Corner/state_machines/counter_offer_loop_returns_to_offered_and_carries_the_negotiated_price
    """
    ctx = _a_contract_haggled_over_three_rounds()

    assert ctx["accepted"]["lifecycle_status"] == "ACTIVE"
    assert ctx["accepted"]["base_price_per_ton_cents"] == 495000
    assert read_contract(ctx["contract"]["id"])["base_price_per_ton_cents"] == 495000


def test_the_last_counter_survives_on_the_active_contract_as_an_audit_trace():
    """The countered figure is retained but plays no part in the binding price.

    PRD: "requires a `counter_base_price_per_ton_cents` in the body, which is stored on the
    contract as `countered_price_per_ton_cents`."

    Design: Corner/state_machines/counter_offer_loop_returns_to_offered_and_carries_the_negotiated_price
    """
    ctx = _a_contract_haggled_over_three_rounds()

    assert ctx["accepted"]["countered_price_per_ton_cents"] == 500000
    assert ctx["accepted"]["base_price_per_ton_cents"] != 500000


# --- A terminal state, and everything it refuses -----------------------------------


TERMINATION_EFFECTIVE_AT = "2027-01-01T00:00:00Z"
LOCKED_DOWN_VISIT_WINDOW = ("2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z")


def _an_offer_pulled_back_off_the_table(api) -> dict:
    """An OFFERED contract with one allocation, withdrawn. A second block and a region-matched
    crew exist, so the child writes can only fail on the contract's state."""
    move_clock(CLOCK_PINNED_AT)
    book = setup_reference_book(
        grower_overrides={
            "name": "Ridgeline Vineyards",
            "license_number": "PL-44821",
            "region_code": "NAPA-NORTH",
        },
        block_overrides={
            "block_code": "B-12",
            "varietal": "CABERNET_SAUVIGNON",
            "acres": 20.000,
            "expected_yield_tons_per_acre": 2.000,
            "ava_code": "NAPA-VALLEY",
        },
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    book["second_block"] = create_block(
        book["grower"]["id"], block_code="B-13", varietal="MERLOT", acres=10.000,
        expected_yield_tons_per_acre=1.500, ava_code="NAPA-VALLEY",
    )
    book["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)
    contract = create_contract(
        book["grower"]["id"], book["spec"]["id"], contract_code="GC-WITHDRAWN",
        installment_plan=single_installment_plan(), **TONNAGE_TERMS,
    )
    create_allocation(contract["id"], book["block"]["id"])
    offer_contract(contract["id"])
    book["contract"] = validate_success(api.withdraw_offer(contract["id"], MANAGER))
    return book


def _every_further_trigger(api, ctx: dict) -> list:
    """The three negotiation edges, the three later-lifecycle edges, and the two child
    writes — eight calls, every one of them made against a withdrawn contract."""
    contract_id = ctx["contract"]["id"]
    grower_headers = make_grower_headers(ctx["grower"]["id"])
    return [
        api.offer_contract(contract_id, MANAGER),
        api.counter_contract(
            contract_id, {"counter_base_price_per_ton_cents": 520000}, grower_headers
        ),
        api.accept_contract(contract_id, grower_headers),
        api.withdraw_offer(contract_id, MANAGER),
        api.close_settlement(contract_id, MANAGER),
        api.serve_termination_notice(
            contract_id, {"effective_at": TERMINATION_EFFECTIVE_AT}, MANAGER
        ),
        api.create_allocation(
            {"contract_id": contract_id, "block_id": ctx["second_block"]["id"]}, MANAGER
        ),
        api.create_sampling_visit(
            create_sampling_visit_payload(
                contract_id,
                ctx["block"]["id"],
                ctx["crew"]["id"],
                LOCKED_DOWN_VISIT_WINDOW[0],
                LOCKED_DOWN_VISIT_WINDOW[1],
            ),
            COORDINATOR,
        ),
    ]


def test_pulling_the_offer_ends_the_lifecycle_and_the_renewal_dimension_together(api):
    """Withdrawal is the one edge that drives both machines at once: the lifecycle reaches a
    terminal state and the renewal dimension reaches its own.

    PRD: "Alternatively the winery can pull the offer, driving `OFFERED → WITHDRAWN`;
    withdrawal takes no body, and it also drives the renewal dimension straight to
    `NOT_RENEWING`, because a contract that never existed will never renew."

    Design: Corner/state_machines/withdrawn_contract_is_terminal_and_rejects_every_further_trigger
    """
    ctx = _an_offer_pulled_back_off_the_table(api)

    assert ctx["contract"]["lifecycle_status"] == "WITHDRAWN"
    assert ctx["contract"]["renewal_status"] == "NOT_RENEWING"


def test_no_outgoing_edge_exists_from_a_withdrawn_contract(api):
    """Re-offer, counter, accept, a second withdrawal, a settlement close and a termination
    notice: six lifecycle triggers, one answer.

    PRD: "No write of any kind is accepted against a contract whose `lifecycle_status` has
    reached `CLOSED`, `TERMINATED` or `WITHDRAWN`; every such attempt is
    `ERR_CONTRACT_STATE_INVALID`."

    Design: Corner/state_machines/withdrawn_contract_is_terminal_and_rejects_every_further_trigger
    """
    ctx = _an_offer_pulled_back_off_the_table(api)

    for response in _every_further_trigger(api, ctx)[:6]:
        validate_error(response, ApiErrorId.ERR_CONTRACT_STATE_INVALID.value, 409)


def test_the_child_writes_a_draft_would_have_allowed_are_locked_down_too(api):
    """An allocation and a sampling visit are legal in `DRAFT`, `OFFERED` and `ACTIVE` — which
    is exactly why they must be refused here, on the same identifier, for the same reason.

    PRD: "Allocations may be created while the contract is `DRAFT`, `OFFERED` or `ACTIVE`;
    anything else is `ERR_CONTRACT_STATE_INVALID`." … "The contract must be in `DRAFT`,
    `OFFERED` or `ACTIVE`; anything else is `ERR_CONTRACT_STATE_INVALID`."

    Design: Corner/state_machines/withdrawn_contract_is_terminal_and_rejects_every_further_trigger
    """
    ctx = _an_offer_pulled_back_off_the_table(api)

    for response in _every_further_trigger(api, ctx)[6:]:
        validate_error(response, ApiErrorId.ERR_CONTRACT_STATE_INVALID.value, 409)


def test_not_one_of_the_eight_refusals_touched_the_row(api):
    """A refused write is not a write: the state is unchanged and the optimistic-concurrency
    counter never moved.

    PRD: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on
    every mutation of that row."

    Design: Corner/state_machines/withdrawn_contract_is_terminal_and_rejects_every_further_trigger
    """
    ctx = _an_offer_pulled_back_off_the_table(api)
    withdrawn_version = ctx["contract"]["version"]

    _every_further_trigger(api, ctx)

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "WITHDRAWN"
    assert contract["version"] == withdrawn_version


def test_the_refused_allocation_created_nothing(api):
    """The second block never joined the contract; the commitment list still holds only the
    one allocation made while the contract was a draft.

    PRD: "Allocations are listed with the optional filters `contract_id` and `block_id`, which
    is how either side of the many-to-many between contracts and blocks is walked."

    Design: Corner/state_machines/withdrawn_contract_is_terminal_and_rejects_every_further_trigger
    """
    ctx = _an_offer_pulled_back_off_the_table(api)

    _every_further_trigger(api, ctx)

    rows, meta = validate_paginated(
        api.list_allocations(MANAGER, params={"contract_id": ctx["contract"]["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["block_id"] for row in rows] == [ctx["block"]["id"]]


# --- Accept is not idempotent ------------------------------------------------------


def _a_contract_accepted_once_on_a_two_element_plan() -> dict:
    """An ACTIVE contract whose plan has two elements, accepted exactly once."""
    move_clock(CLOCK_PINNED_AT)
    book = setup_reference_book(
        grower_overrides={
            "name": "Ridgeline Vineyards",
            "license_number": "PL-44821",
            "region_code": "NAPA-NORTH",
        },
        block_overrides={
            "block_code": "B-12",
            "varietal": "CABERNET_SAUVIGNON",
            "acres": 20.000,
            "expected_yield_tons_per_acre": 2.000,
            "ava_code": "NAPA-VALLEY",
        },
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    contract = create_contract(
        book["grower"]["id"], book["spec"]["id"], contract_code="GC-TWICE",
        installment_plan=TWO_INSTALLMENTS, **TONNAGE_TERMS,
    )
    create_allocation(contract["id"], book["block"]["id"])
    offer_contract(contract["id"])
    book["contract"] = accept_contract(contract["id"], book["grower"]["id"])
    return book


def test_a_second_acceptance_is_refused_rather_than_silently_re_run(api):
    """Accept requires `OFFERED`, and the contract is already `ACTIVE` — so the repeat is a
    state error, not a no-op.

    PRD: "It is a `Grower` action on the contract's own producer, it drives `OFFERED →
    ACTIVE`, it takes no request body"

    Design: Corner/state_machines/accepting_an_already_active_contract_twice_returns_409
    """
    ctx = _a_contract_accepted_once_on_a_two_element_plan()

    validate_error(
        api.accept_contract(ctx["contract"]["id"], make_grower_headers(ctx["grower"]["id"])),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID.value,
        409,
    )


def test_the_refused_acceptance_does_not_duplicate_the_payment_schedule(api):
    """The pivot cascade-creates one row per plan element, so a tolerant second accept would
    leave four installments behind instead of two.

    PRD: "And the payment schedule is materialised: one installment row is created for each
    element of `installment_plan`, copying `installment_no`, `pct_of_settlement`,
    `due_offset_days` and `lien_protected` verbatim, each starting in status
    `PENDING_SETTLEMENT` with `planned_amount_cents` 0 and `paid_amount_cents` 0."

    Design: Corner/state_machines/accepting_an_already_active_contract_twice_returns_409
    """
    ctx = _a_contract_accepted_once_on_a_two_element_plan()

    api.accept_contract(ctx["contract"]["id"], make_grower_headers(ctx["grower"]["id"]))

    rows = list_installments(contract_id=ctx["contract"]["id"])
    assert len(rows) == 2
    assert sorted(row["installment_no"] for row in rows) == [1, 2]


def test_the_refused_acceptance_left_the_version_where_it_was(api):
    """One successful accept, one refusal: the row was mutated exactly once.

    PRD: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on
    every mutation of that row."

    Design: Corner/state_machines/accepting_an_already_active_contract_twice_returns_409
    """
    ctx = _a_contract_accepted_once_on_a_two_element_plan()
    active_version = ctx["contract"]["version"]

    api.accept_contract(ctx["contract"]["id"], make_grower_headers(ctx["grower"]["id"]))

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["version"] == active_version
