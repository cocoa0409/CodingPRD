"""Transitive cascades: one write whose effect propagates link by link through
allocation, matter, partner and cycle."""

from test_helpers import (
    adjudicate_claim,
    advance_cycle,
    allocate_origination_credit,
    approx2,
    approx4,
    contribute_capital,
    create_billable_record,
    create_credit_arbiter,
    create_cycle,
    create_matter,
    create_partner,
    create_verified_billable_hours,
    dispute_claim,
    file_claim,
    find_allocation,
    matter_allocations,
    post_financials,
    read_award,
    read_cycle,
    read_matter,
    read_partner,
    setup_formula_matter,
    setup_split_adjudicated_matter,
    setup_trued_up_award,
    submit_claim,
    verify_record,
)


def _disputed_rounding_scenario(api):
    """Cycle, three partners, one OPEN matter at 200020/100010/0 with 5.00
    verified billable hours, and a claim sitting in DISPUTED at 50.00."""
    cycle = create_cycle(api)
    claimant = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    disputer = create_partner(
        api, full_name="Ben Counter", compensation_model="FORMULA", admission_year=2011
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=claimant["id"],
        responsible_attorney_id=claimant["id"],
        client_key="CLI-R1",
        client_display_name="Rounding Industries",
    )
    post_financials(
        api,
        matter["id"],
        billed_delta_cents=200_020,
        collected_delta_cents=100_010,
        direct_cost_delta_cents=0,
    )
    create_verified_billable_hours(
        api,
        partner_id=claimant["id"],
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        hours=5.00,
        service_period_start="2026-02-01",
        service_period_end="2026-02-28",
    )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
    )
    submit_claim(api, claim["id"], claimant["id"])
    dispute_claim(
        api,
        claim["id"],
        disputer["id"],
        contested_pct=50.00,
        dispute_grounds="Introduction came from my existing relationship.",
    )
    return {
        "cycle": cycle,
        "claimant": claimant,
        "disputer": disputer,
        "arbiter": arbiter,
        "matter": matter,
        "claim": claim,
    }


def test_split_writes_both_rows_and_lifts_the_matter_capacity(api):
    """PRD 3.4: "The same cascade follows — `origination_pct_assigned` and the
    matter's `version`, then credited collections on every active allocation of
    the matter and on both partners, then `formula_score_provisional` and
    `formula_score_final` and the cycle's `total_formula_score` — and the claim's
    `version` increments."

    Design: Difficulty/transitive_cascade/split_adjudication_cascade_matter_allocation_partner_cycle
    """
    scenario = _disputed_rounding_scenario(api)
    assert read_matter(api, scenario["matter"]["id"])["origination_pct_assigned"] == approx2(0.00)

    claim = adjudicate_claim(
        api,
        claim_id=scenario["claim"]["id"],
        arbiter_id=scenario["arbiter"]["id"],
        decision="SPLIT",
        matter_id=scenario["matter"]["id"],
        approved_pct=50.00,
        counterparty_pct=50.00,
    )
    assert claim["state"] == "ALLOCATED"

    rows = matter_allocations(api, scenario["matter"]["id"], state="ACTIVE")
    originating = [row for row in rows if row["credit_role"] == "ORIGINATING"]
    assert len(originating) == 2
    claimant_row = find_allocation(rows, "ORIGINATING", scenario["claimant"]["id"])
    disputer_row = find_allocation(rows, "ORIGINATING", scenario["disputer"]["id"])
    assert claimant_row["credit_pct"] == approx2(50.00)
    assert claimant_row["source"] == "CLAIM_ALLOCATED"
    assert disputer_row["credit_pct"] == approx2(50.00)
    assert disputer_row["source"] == "SHARING_CONVENTION"
    assert read_matter(api, scenario["matter"]["id"])["origination_pct_assigned"] == approx2(100.00)

    # The cascade reaches the cycle: only the ACTIVE FORMULA partners contribute
    # to total_formula_score, so the cycle total is the sum of their scores.
    contributors = [
        read_partner(api, scenario[key]["id"])["formula_score_provisional"]
        for key in ("claimant", "disputer", "arbiter")
    ]
    assert read_cycle(api, scenario["cycle"]["id"])["total_formula_score"] == approx4(
        round(sum(contributors), 4)
    )


def test_split_cascade_reaches_partner_scores_and_the_cycle_total(api):
    """PRD 3.5: "Only partners whose `status` is `ACTIVE` or `NOTICE_GIVEN` and
    whose `compensation_model` is `FORMULA` contribute to the cycle's
    `total_formula_score`; a departed partner is dropped from that total while
    keeping their own stored scores."

    Design: Difficulty/transitive_cascade/split_adjudication_cascade_matter_allocation_partner_cycle
    """
    scenario = setup_split_adjudicated_matter(api)
    rows = matter_allocations(api, scenario["matter"]["id"], state="ACTIVE")
    assert sorted(row["credited_collection_provisional_cents"] for row in rows) == [
        15_002,
        20_001,
        20_002,
        20_002,
        25_003,
    ]
    assert sum(row["credited_collection_provisional_cents"] for row in rows) == 100_010

    claimant = read_partner(api, scenario["claimant"]["id"])
    disputer = read_partner(api, scenario["disputer"]["id"])
    arbiter = read_partner(api, scenario["arbiter"]["id"])
    assert claimant["credited_collection_provisional_cents"] == 80_008
    assert claimant["formula_score_provisional"] == approx4(35.2917)
    assert disputer["credited_collection_provisional_cents"] == 20_002
    assert disputer["formula_score_provisional"] == approx4(15.0000)
    assert arbiter["formula_score_provisional"] == approx4(0.0000)
    assert read_cycle(api, scenario["cycle"]["id"])["total_formula_score"] == approx4(50.2917)


def test_capital_contribution_settles_the_award_and_clears_the_close_gate(api):
    """PRD 3.9: "That settlement re-derives the cycle's `unsettled_award_count`,
    which is the single gate standing between `TRUE_UP_OPEN` and `CLOSED` — so
    capital collection is, quite literally, the last thing that closes a
    compensation year."

    Design: Difficulty/transitive_cascade/capital_contribution_cascade_partner_award_cycle
    """
    bundle = setup_trued_up_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    subject_id = bundle["subject"]["id"]
    assert read_partner(api, subject_id)["capital_account_balance_cents"] == 17_333_334
    assert read_cycle(api, bundle["cycle"]["id"])["unsettled_award_count"] == 1

    contribute_capital(api, partner_id=subject_id, amount_cents=12_666_666)

    award = read_award(api, bundle["award"]["id"])
    assert read_partner(api, subject_id)["capital_account_balance_cents"] == 30_000_000
    assert award["capital_shortfall_cents"] == 0
    assert award["payment_state"] == "SETTLED"
    assert read_cycle(api, bundle["cycle"]["id"])["unsettled_award_count"] == 0


def test_settlement_lets_the_year_close_without_touching_the_cash_ledger(api):
    """PRD 3.9: "That append re-derives the award's `draw_paid_cents` — the signed
    sum of `amount_cents` over its rows of kind `SCHEDULED_DRAW` and
    `DRAW_REVERSAL` — and sets the payment dimension to `DRAWING`, which in turn
    re-derives the partner's `ytd_draw_paid_cents` and the cycle's
    `undistributed_cash_cents`, the latter being `distributable_pool_cents` less
    the signed sum of `amount_cents` over every ledger row belonging to any award
    of the cycle."

    Design: Difficulty/transitive_cascade/capital_contribution_cascade_partner_award_cycle
    """
    bundle = setup_trued_up_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    contribute_capital(api, partner_id=bundle["subject"]["id"], amount_cents=12_666_666)

    closed = advance_cycle(api, bundle["cycle"]["id"], "CLOSED")
    award = read_award(api, bundle["award"]["id"])
    assert closed["state"] == "CLOSED"
    assert closed["undistributed_cash_cents"] == 80_000_000
    assert award["award_state"] == "FINALIZED"
    assert award["true_up_delta_cents"] == 17_333_334


def _allocated_matter_with_unverified_hours(api):
    """One FORMULA partner holding ORIGINATING 100.00 on a matter carrying an
    unverified 200.00-hour billable record."""
    scenario = setup_formula_matter(
        api,
        billed_delta_cents=10_000_000,
        collected_delta_cents=8_500_000,
        direct_cost_delta_cents=1_000_000,
        verified_hours=None,
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    allocate_origination_credit(
        api,
        cycle_id=scenario["cycle"]["id"],
        matter_id=scenario["matter"]["id"],
        claimant_id=scenario["partner"]["id"],
        arbiter_id=arbiter["id"],
        approved_pct=100.00,
    )
    scenario["arbiter"] = arbiter
    scenario["record"] = create_billable_record(
        api,
        partner_id=scenario["partner"]["id"],
        cycle_id=scenario["cycle"]["id"],
        matter_id=scenario["matter"]["id"],
        hours=200.00,
        standard_rate_cents=50_000,
        service_period_start="2026-01-15",
        service_period_end="2026-06-30",
    )
    return scenario


def test_verification_creates_the_working_row_and_re_prices_the_matter(api):
    """PRD 3.3: "A verified billable record raises the partner's
    `verified_billable_hours` and the matter's `verified_billable_hours`, and it
    upserts the `WORKING` credit allocation for that pairing of matter and
    partner — `source` of `WORKING_DERIVED`, `credit_from` equal to the matter's
    `opened_on`, `credit_through` null — after which `credit_pct` is recomputed on
    *every* working allocation of that matter as 100 multiplied by that partner's
    verified billable hours on the matter, divided by the matter's total
    `verified_billable_hours`, rounded half up to 2 decimal places."

    Design: Difficulty/transitive_cascade/hours_verification_cascade_allocation_matter_partner_cycle
    """
    scenario = _allocated_matter_with_unverified_hours(api)
    matter_id = scenario["matter"]["id"]
    partner_id = scenario["partner"]["id"]

    before = read_matter(api, matter_id)
    assert before["verified_billable_hours"] == approx2(0.00)
    assert before["profitability_index_fully_loaded"] == approx4(0.8824)
    originating_before = find_allocation(
        matter_allocations(api, matter_id, state="ACTIVE"), "ORIGINATING", partner_id
    )
    assert originating_before["credited_collection_provisional_cents"] == 5_525_000

    verified = verify_record(api, scenario["record"]["id"])
    assert verified["verified"] is True

    after = read_matter(api, matter_id)
    assert after["verified_billable_hours"] == approx2(200.00)
    assert after["profitability_index_fully_loaded"] == approx4(0.6706)
    assert after["profitability_index_contribution"] == approx4(0.8824)

    rows = matter_allocations(api, matter_id, state="ACTIVE")
    working = find_allocation(rows, "WORKING", partner_id)
    assert working["credit_pct"] == approx2(100.00)
    assert working["source"] == "WORKING_DERIVED"
    assert working["credit_from"] == "2026-01-15"
    assert working["credit_through"] is None
    assert working["credited_collection_provisional_cents"] == 2_125_000
    assert find_allocation(rows, "ORIGINATING", partner_id)[
        "credited_collection_provisional_cents"
    ] == 3_400_000


def test_verification_lowers_the_partner_score_and_the_cycle_total(api):
    """PRD 3.3: "The matter's changed hour total then re-derives
    `profitability_index_fully_loaded`, which re-derives each credited partner's
    `weighted_profitability_points`, which re-derives `formula_score_provisional`
    and `formula_score_final` and finally the cycle's `total_formula_score`."

    Design: Difficulty/transitive_cascade/hours_verification_cascade_allocation_matter_partner_cycle
    """
    scenario = _allocated_matter_with_unverified_hours(api)
    partner_id = scenario["partner"]["id"]

    before = read_partner(api, partner_id)
    assert before["weighted_profitability_points"] == approx4(0.8824)
    assert before["formula_score_provisional"] == approx4(62.6480)

    verify_record(api, scenario["record"]["id"])

    after = read_partner(api, partner_id)
    assert after["weighted_profitability_points"] == approx4(0.6706)
    assert after["formula_score_provisional"] == approx4(60.6342)
    assert after["credited_collection_provisional_cents"] == 8_500_000
    assert read_cycle(api, scenario["cycle"]["id"])["total_formula_score"] == approx4(60.6342)
