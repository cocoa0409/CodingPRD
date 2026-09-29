"""Two derivations that turn on a single boundary. Twenty cents of gross decide whether a
vintage earns a prompt-payment credit at all, and the turn of the calendar year decides how
much of a producer's past misbehaviour still counts against it.
"""
from test_helpers import (
    CLERK,
    accept_contract,
    acknowledge_pick_call,
    appointment_version,
    book_appointment,
    book_sampling_visit,
    capture_gross,
    capture_tare,
    close_settlement,
    create_allocation,
    create_contract,
    create_crew,
    create_lane,
    issue_pick_call,
    list_installments,
    move_clock,
    offer_contract,
    read_contract,
    read_grower,
    read_pick_call,
    read_settlement_summary,
    record_grading,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
)

SETUP_AT = "2026-08-20T08:00:00Z"
CLOSED_AT = "2026-08-28T09:00:00Z"

# Two non-overlapping sampling windows for one crew, then two crush-pad slots on the same
# lane separated by more than the 30-minute cleanout buffer.
FIRST_SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
SECOND_SAMPLING_WINDOW = ("2026-08-20T12:00:00Z", "2026-08-20T14:00:00Z")
FIRST_PICK_AT = "2026-08-25T14:00:00Z"
SECOND_PICK_AT = "2026-08-25T17:00:00Z"
FIRST_SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
SECOND_SLOT = ("2026-08-25T17:00:00Z", "2026-08-25T19:00:00Z")
FIRST_TRUCK_ARRIVES_AT = "2026-08-25T14:30:00Z"
SECOND_TRUCK_ARRIVES_AT = "2026-08-25T17:30:00Z"

GROSS_LBS = 57000
TARE_LBS = 17000
LOAD_TONS = 20.000

# Brix 23.0 sits between the penalty start (22.0) and the bonus start (24.0), so the load
# prices at the contract's base rate with no adjustment at all.
CLEAN_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

ON_THE_TIER_FLOOR_PER_TON = 250000  # 250000 x 20.000 tons = 5,000,000 cents exactly
JUST_UNDER_THE_FLOOR_PER_TON = 249999  # 249999 x 20.000 tons = 4,999,980 cents

ON_THE_FLOOR_GROSS = 5000000
UNDER_THE_FLOOR_GROSS = 4999980
ON_THE_FLOOR_CREDIT = 25000
ON_THE_FLOOR_HOLDBACK = 250000
UNDER_THE_FLOOR_HOLDBACK = 249999
ON_THE_FLOOR_NET_PAYABLE = 4775000
UNDER_THE_FLOOR_NET_PAYABLE = 4749981

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


# --- One tier boundary, two vintages twenty cents apart ------------------------------


def _one_vintage_booked(
    ctx: dict,
    contract_code: str,
    base_price_per_ton_cents: int,
    sampling_window,
    target_pick_at: str,
    slot,
) -> dict:
    """Walk one contract to an acknowledged call with its crush-pad slot reserved.

    The whole preamble runs while the clock is still at `SETUP_AT`, because the pick
    call's notice gate is measured against the logical clock at issuance: "`target_pick_at`
    must be at least the contract's `min_pick_notice_hours` after the logical clock's
    current instant".  Advancing the clock into one vintage's arrival window before the
    other vintage's call is issued would leave that second call short of the 48-hour floor.
    """
    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code=contract_code,
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=base_price_per_ton_cents,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2026,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], sampling_window[0], sampling_window[1]
    )
    record_sampling_visit(
        visit["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    call = issue_pick_call(contract["id"], ctx["block"]["id"], target_pick_at, LOAD_TONS)
    acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    appointment = book_appointment(call["id"], ctx["lane"]["id"], slot[0], slot[1], LOAD_TONS)
    return {
        "contract_id": contract["id"],
        "pick_call_id": call["id"],
        "appointment_id": appointment["id"],
    }


def _deliver_and_price_the_vintage(ctx: dict, booked: dict, truck_arrives_at: str) -> dict:
    """Present the truck inside its arrival envelope, tare it and grade it clean."""
    move_clock(truck_arrives_at)
    tag = capture_gross(
        booked["appointment_id"],
        ctx["block"]["id"],
        GROSS_LBS,
        appointment_version(booked["appointment_id"]),
    )
    capture_tare(tag["id"], TARE_LBS)
    record_grading(tag["id"], **CLEAN_READING)
    booked["tag_id"] = tag["id"]
    return booked


def _two_vintages_straddling_the_tier_floor() -> dict:
    """One producer, two closed vintages: one priced exactly on the prompt-payment floor and
    one twenty cents below it."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["lane"] = create_lane(**LANE)
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    # Both calls are issued and both slots reserved before the clock leaves SETUP_AT.
    ctx["on_the_floor"] = _one_vintage_booked(
        ctx,
        "GC-TIER-A",
        ON_THE_TIER_FLOOR_PER_TON,
        FIRST_SAMPLING_WINDOW,
        FIRST_PICK_AT,
        FIRST_SLOT,
    )
    ctx["under_the_floor"] = _one_vintage_booked(
        ctx,
        "GC-TIER-B",
        JUST_UNDER_THE_FLOOR_PER_TON,
        SECOND_SAMPLING_WINDOW,
        SECOND_PICK_AT,
        SECOND_SLOT,
    )

    _deliver_and_price_the_vintage(ctx, ctx["on_the_floor"], FIRST_TRUCK_ARRIVES_AT)
    _deliver_and_price_the_vintage(ctx, ctx["under_the_floor"], SECOND_TRUCK_ARRIVES_AT)

    move_clock(CLOSED_AT)
    ctx["closed_on_the_floor"] = close_settlement(ctx["on_the_floor"]["contract_id"])
    ctx["closed_under_the_floor"] = close_settlement(ctx["under_the_floor"]["contract_id"])
    return ctx


def test_a_vintage_landing_exactly_on_the_tier_floor_earns_the_credit():
    """5,000,000 cents is not below the first tier's floor, so the rate is 0.5 percent and the
    credit is 25,000 — the answer a `<=` in place of the declared `<` would invert.

    PRD: "Step two looks up a prompt-payment tier **on that pre-credit total**: below 5,000,000
    cents the rate is 0.0 percent; from 5,000,000 up to but not including 10,000,000 cents it is
    0.5 percent; from 10,000,000 up to but not including 15,000,000 cents it is 1.0 percent; and
    at or above 15,000,000 cents it is 1.5 percent."

    Design: Corner/calculations/prompt_pay_tier_boundary_at_exactly_five_million_cents
    """
    ctx = _two_vintages_straddling_the_tier_floor()

    assert ctx["closed_on_the_floor"]["final_settlement_cents"] == ON_THE_FLOOR_GROSS
    assert ctx["closed_on_the_floor"]["prompt_pay_credit_cents"] == ON_THE_FLOOR_CREDIT


def test_twenty_cents_short_of_the_floor_earns_no_credit_at_all():
    """4,999,980 cents is below the floor, so the rate is the tier-zero 0.0 percent and the
    credit computes to nothing.

    PRD: "Step three computes `prompt_pay_credit_cents` as the settlement total multiplied by
    that rate divided by 100, rounded half up to whole cents."

    Design: Corner/calculations/prompt_pay_tier_boundary_at_exactly_five_million_cents
    """
    ctx = _two_vintages_straddling_the_tier_floor()

    assert ctx["closed_under_the_floor"]["final_settlement_cents"] == UNDER_THE_FLOOR_GROSS
    assert ctx["closed_under_the_floor"]["prompt_pay_credit_cents"] == 0


def test_the_statutory_holdback_is_keyed_on_the_same_pre_credit_total():
    """The holdback tracks the gross and not the credited subtotal, so it moves by a single
    cent between the two vintages — which is what leaves the tier flip solely responsible for
    the rest of the gap.

    PRD: "Step four computes the statutory producer-lien holdback, `lien_holdback_cents`, **also
    keyed on the pre-credit total**: the settlement total multiplied by the contract's
    `lien_holdback_pct` divided by 100, rounded half up to whole cents."

    Design: Corner/calculations/prompt_pay_tier_boundary_at_exactly_five_million_cents
    """
    ctx = _two_vintages_straddling_the_tier_floor()

    assert ctx["closed_on_the_floor"]["lien_holdback_cents"] == ON_THE_FLOOR_HOLDBACK
    assert ctx["closed_under_the_floor"]["lien_holdback_cents"] == UNDER_THE_FLOOR_HOLDBACK


def test_the_net_payable_adds_the_credit_and_subtracts_the_holdback():
    """Twenty cents of gross became 25,019 cents of net payable: the twenty cents itself, plus
    25,000 from the tier flip, plus the one cent of holdback the smaller gross does not attract.

    PRD: "Step five computes `net_payable_cents` as the settlement total plus
    `prompt_pay_credit_cents` less `lien_holdback_cents`."

    Design: Corner/calculations/prompt_pay_tier_boundary_at_exactly_five_million_cents
    """
    ctx = _two_vintages_straddling_the_tier_floor()

    assert ctx["closed_on_the_floor"]["net_payable_cents"] == ON_THE_FLOOR_NET_PAYABLE
    assert ctx["closed_under_the_floor"]["net_payable_cents"] == UNDER_THE_FLOOR_NET_PAYABLE
    assert (
        ctx["closed_on_the_floor"]["net_payable_cents"]
        - ctx["closed_under_the_floor"]["net_payable_cents"]
        == 25019
    )


def test_each_vintage_schedules_its_whole_net_payable_on_its_one_installment():
    """A single 100-percent row leaves no rounding residual to absorb, so each plan carries
    exactly its own contract's net payable.

    PRD: "After every close, the sum of the installments' `planned_amount_cents` equals
    `net_payable_cents` exactly."

    Design: Corner/calculations/prompt_pay_tier_boundary_at_exactly_five_million_cents
    """
    ctx = _two_vintages_straddling_the_tier_floor()

    for closed in (ctx["closed_on_the_floor"], ctx["closed_under_the_floor"]):
        rows = list_installments(contract_id=closed["id"])
        assert [row["status"] for row in rows] == ["SCHEDULED"]
        assert sum(row["planned_amount_cents"] for row in rows) == closed["net_payable_cents"]
        assert closed["lifecycle_status"] == "SETTLED"


def test_the_producers_statutory_lien_carries_both_closed_vintages():
    """The lien is producer-wide, so the two lien-protected rows sit on one balance until they
    are paid.

    PRD: "the producer's `outstanding_lien_balance_cents`, which is the sum, over every
    installment of every contract of that producer whose `lien_protected` flag is true and whose
    status is `SCHEDULED`, `PARTIALLY_PAID` or `DELINQUENT`, of `planned_amount_cents` less
    `paid_amount_cents`."

    Design: Corner/calculations/prompt_pay_tier_boundary_at_exactly_five_million_cents
    """
    ctx = _two_vintages_straddling_the_tier_floor()

    grower = read_grower(ctx["grower"]["id"])
    assert grower["outstanding_lien_balance_cents"] == (
        ON_THE_FLOOR_NET_PAYABLE + UNDER_THE_FLOOR_NET_PAYABLE
    )


def test_the_reconciliation_read_agrees_with_each_contracts_own_figures():
    """The clerk's reconciliation is the same pipeline seen through the summary endpoint, one
    contract at a time.

    PRD: "A dedicated computed read reconciles tonnage against money for a contract in one
    payload, available to the `GrowerRelationsManager`, the `AccountsPayableClerk` and the owning
    `Grower`."

    Design: Corner/calculations/prompt_pay_tier_boundary_at_exactly_five_million_cents
    """
    ctx = _two_vintages_straddling_the_tier_floor()

    for closed in (ctx["closed_on_the_floor"], ctx["closed_under_the_floor"]):
        summary = read_settlement_summary(closed["id"], CLERK)
        assert summary["final_settlement_cents"] == closed["final_settlement_cents"]
        assert summary["prompt_pay_credit_cents"] == closed["prompt_pay_credit_cents"]
        assert summary["lien_holdback_cents"] == closed["lien_holdback_cents"]
        assert summary["net_payable_cents"] == closed["net_payable_cents"]
        assert summary["installment_planned_total_cents"] == closed["net_payable_cents"]


# --- The calendar year, and nothing else, decays the penalty --------------------------


CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"
DECAY_SAMPLING_WINDOW = ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")
DECAY_TARGET_PICK_AT = "2026-08-06T14:00:00Z"
ONE_SECOND_PAST_THE_ACK_DEADLINE = "2026-08-02T00:00:01Z"
LAST_INSTANT_OF_THE_VINTAGE = "2026-12-31T23:59:59Z"
FIRST_INSTANT_OF_THE_NEXT_VINTAGE = "2027-01-01T00:00:00Z"


def _a_producer_carrying_one_expired_call() -> dict:
    """A 2026-2028 contract whose only blemish is a single pick call nobody answered, allowed
    to expire one second past its deadline. No rejected loads and no no-shows."""
    move_clock(CLOCK_PINNED_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-DECAY",
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2028,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"],
        ctx["block"]["id"],
        ctx["crew"]["id"],
        DECAY_SAMPLING_WINDOW[0],
        DECAY_SAMPLING_WINDOW[1],
    )
    record_sampling_visit(
        visit["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    ctx["pick_call"] = issue_pick_call(
        contract["id"], ctx["block"]["id"], DECAY_TARGET_PICK_AT, LOAD_TONS
    )

    move_clock(ONE_SECOND_PAST_THE_ACK_DEADLINE)
    return ctx


def test_an_unanswered_call_costs_five_units_of_the_current_vintage():
    """The expiry is charged where it happened: one call in the current vintage's counter and
    nothing in the prior-vintage bucket.

    PRD: "The current-vintage penalty is 8 times `rejected_load_count_vintage`, plus 5 times
    `expired_pick_call_count_vintage`, plus 3 times `no_show_appointment_count_vintage`, where
    the vintage is the UTC calendar year of the logical clock."

    Design: Corner/calculations/reliability_penalties_decay_by_half_when_the_vintage_rolls_over
    """
    ctx = _a_producer_carrying_one_expired_call()

    assert read_pick_call(ctx["pick_call"]["id"])["status"] == "EXPIRED"
    grower = read_grower(ctx["grower"]["id"])
    assert grower["expired_pick_call_count_vintage"] == 1
    assert grower["prior_vintage_penalty_units"] == 0
    assert float(grower["reliability_score_vintage"]) == 95.0
    assert float(grower["reliability_score_lifetime"]) == 95.0


def test_the_final_second_of_the_year_still_counts_the_call_as_current():
    """The bucket boundary is the calendar year of the clock, not an elapsed-days count, so
    five months of waiting change nothing.

    PRD: "The counters are populated from weigh tags whose disposition is `REJECTED_QUALITY` or
    `REJECTED_OVER_CAP`, pick calls in `EXPIRED` and appointments in `NO_SHOW`, all reached
    through the producer's contracts and bucketed by each row's own `created_at` UTC calendar
    year"

    Design: Corner/calculations/reliability_penalties_decay_by_half_when_the_vintage_rolls_over
    """
    ctx = _a_producer_carrying_one_expired_call()

    move_clock(LAST_INSTANT_OF_THE_VINTAGE)
    grower = read_grower(ctx["grower"]["id"])
    assert grower["expired_pick_call_count_vintage"] == 1
    assert grower["prior_vintage_penalty_units"] == 0
    assert float(grower["reliability_score_vintage"]) == 95.0
    assert float(grower["reliability_score_lifetime"]) == 95.0


def test_the_turn_of_the_year_rebuckets_the_same_stored_row():
    """No call was made other than moving the clock, and the identical stored pick call has
    left the current vintage for the prior-vintage total.

    PRD: "`prior_vintage_penalty_units` is the same weighted sum computed over every UTC
    calendar year strictly before the current vintage."

    Design: Corner/calculations/reliability_penalties_decay_by_half_when_the_vintage_rolls_over
    """
    ctx = _a_producer_carrying_one_expired_call()
    move_clock(LAST_INSTANT_OF_THE_VINTAGE)

    move_clock(FIRST_INSTANT_OF_THE_NEXT_VINTAGE)
    grower = read_grower(ctx["grower"]["id"])
    assert grower["expired_pick_call_count_vintage"] == 0
    assert grower["prior_vintage_penalty_units"] == 5


def test_the_vintage_scoped_score_forgets_the_previous_year_entirely():
    """With the blemish re-bucketed, the vintage-scoped view of the producer is spotless
    again.

    PRD: "`reliability_score_vintage` is 100 less the current-vintage penalty, floored at 0.0,
    ignoring prior vintages entirely."

    Design: Corner/calculations/reliability_penalties_decay_by_half_when_the_vintage_rolls_over
    """
    ctx = _a_producer_carrying_one_expired_call()

    move_clock(FIRST_INSTANT_OF_THE_NEXT_VINTAGE)
    assert float(read_grower(ctx["grower"]["id"])["reliability_score_vintage"]) == 100.0


def test_the_lifetime_score_halves_the_prior_penalty_to_a_whole_unit_first():
    """Five units halved is 2.5, and the rounding happens before the subtraction, so the
    lifetime score is 97.0 — not the 97.5 that halving after subtraction would leave.

    PRD: "`reliability_score_lifetime` is 100 less the current-vintage penalty less the
    prior-vintage penalty halved, floored at 0.0 — and the halved prior term is rounded half up
    to a **whole unit before** it is subtracted, so an odd prior penalty of 5 units costs 3
    rather than 2.5."

    Design: Corner/calculations/reliability_penalties_decay_by_half_when_the_vintage_rolls_over
    """
    ctx = _a_producer_carrying_one_expired_call()

    move_clock(FIRST_INSTANT_OF_THE_NEXT_VINTAGE)
    assert float(read_grower(ctx["grower"]["id"])["reliability_score_lifetime"]) == 97.0


def test_the_decay_is_not_an_artefact_of_the_agreement_ending():
    """The contract still has two vintages to run, so the re-bucketing came from the clock
    alone.

    PRD: "The term is bounded by `term_start_vintage` and `term_end_vintage`, whole calendar
    years between 2000 and 2100 with the end no earlier than the start."

    Design: Corner/calculations/reliability_penalties_decay_by_half_when_the_vintage_rolls_over
    """
    ctx = _a_producer_carrying_one_expired_call()

    move_clock(FIRST_INSTANT_OF_THE_NEXT_VINTAGE)
    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["term_end_vintage"] == 2028
