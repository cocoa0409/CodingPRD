"""Boundaries: the realization tier floor, the zero-cardinality edge of the
working role, and the diminishing-return threshold on non-billable hours."""

from test_helpers import (
    adjudicate_claim,
    allocate_origination_credit,
    approx2,
    approx4,
    approx6,
    create_credit_arbiter,
    create_cycle,
    create_matter,
    create_non_billable_record,
    create_partner,
    file_claim,
    find_allocation,
    matter_allocations,
    post_financials,
    read_matter,
    read_partner,
    setup_formula_matter,
    submit_claim,
    verify_record,
)


def _sole_credit_holder_one_hundredth_below_the_tier(api):
    """One FORMULA partner holding all four credit roles on a matter whose
    realization is 0.9499, one hundredth of a point under the top tier."""
    scenario = setup_formula_matter(
        api,
        billed_delta_cents=10_000_000,
        collected_delta_cents=9_499_000,
        direct_cost_delta_cents=1_000_000,
        verified_hours=200.00,
        matter_overrides={
            "client_key": "CLI-T1",
            "client_display_name": "Tier Test Corp",
        },
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
    return scenario


def test_realization_of_exactly_ninety_five_hundredths_takes_the_top_tier(api):
    """PRD 3.5: "Select the realization tier multiplier from that blended figure:
    1.10 when it is at least 0.9500, otherwise 1.00 when it is at least 0.8500,
    otherwise 0.90 when it is at least 0.7500, and otherwise 0.75. Exactly 0.9500
    therefore selects the top tier and exactly 0.8500 selects the second, never
    the first."

    Design: Difficulty/boundary_precision_check/realization_exactly_at_ninety_five_hundredths_takes_top_tier
    """
    scenario = _sole_credit_holder_one_hundredth_below_the_tier(api)
    matter_id = scenario["matter"]["id"]
    partner_id = scenario["partner"]["id"]

    below = read_partner(api, partner_id)
    assert below["blended_realization_pct"] == approx4(0.9499)
    assert below["formula_score_provisional"] == approx4(61.3262)

    lifted = post_financials(
        api,
        matter_id,
        billed_delta_cents=0,
        collected_delta_cents=1_000,
        direct_cost_delta_cents=0,
    )
    at_tier = read_partner(api, partner_id)

    assert lifted["realization_pct"] == approx4(0.9500)
    assert at_tier["blended_realization_pct"] == approx4(0.9500)
    assert at_tier["formula_score_provisional"] == approx4(67.4610)
    assert at_tier["normalized_credit_index_provisional"] == approx6(1.000000)
    assert read_partner(api, scenario["arbiter"]["id"])["formula_score_provisional"] == approx4(
        0.0000
    )


def test_the_thousand_cents_that_lifts_the_tier_also_moves_profitability(api):
    """PRD 3.5: "The tier multiplier is applied to the unrounded sum and the
    rounding happens once, afterwards; rounding the weighted sum first and
    multiplying second can move the fourth decimal place."

    Design: Difficulty/boundary_precision_check/realization_exactly_at_ninety_five_hundredths_takes_top_tier
    """
    scenario = _sole_credit_holder_one_hundredth_below_the_tier(api)
    matter_id = scenario["matter"]["id"]
    partner_id = scenario["partner"]["id"]
    assert read_matter(api, matter_id)["profitability_index_fully_loaded"] == approx4(0.7052)
    score_below = read_partner(api, partner_id)["formula_score_provisional"]

    lifted = post_financials(
        api,
        matter_id,
        billed_delta_cents=0,
        collected_delta_cents=1_000,
        direct_cost_delta_cents=0,
    )
    score_at = read_partner(api, partner_id)["formula_score_provisional"]
    assert lifted["profitability_index_fully_loaded"] == approx4(0.7053)
    assert score_at - score_below == approx4(6.1348)

    reverted = post_financials(
        api,
        matter_id,
        billed_delta_cents=0,
        collected_delta_cents=-1_000,
        direct_cost_delta_cents=0,
    )
    score_back = read_partner(api, partner_id)["formula_score_provisional"]
    assert reverted["realization_pct"] == approx4(0.9499)
    assert reverted["profitability_index_fully_loaded"] == approx4(0.7052)
    assert score_back == approx4(61.3262)


def _matter_awaiting_allocation_with_no_verified_hours(api):
    """A 200000-cent matter whose working role has no allocation at all, with a
    SUBMITTED claim ready for adjudication."""
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-F1",
        client_display_name="Fold Fabricators",
    )
    post_financials(
        api,
        matter["id"],
        billed_delta_cents=200_000,
        collected_delta_cents=200_000,
        direct_cost_delta_cents=0,
    )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=partner["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
        narrative="Originated Fold Fabricators alone.",
    )
    submit_claim(api, claim["id"], partner["id"])
    return {
        "cycle": cycle,
        "partner": partner,
        "arbiter": arbiter,
        "matter": matter,
        "claim": claim,
    }


def test_absent_working_role_hands_its_whole_quarter_to_origination(api):
    """PRD 3.5: "A matter with no active allocation of any role leaves its whole
    basis unallocated and every credited figure at 0; a matter with only an
    originating allocation sees origination receive the entire basis through the
    fold-in rule."

    Design: Difficulty/boundary_precision_check/empty_working_role_folds_whole_quarter_into_originating
    """
    scenario = _matter_awaiting_allocation_with_no_verified_hours(api)
    matter_id = scenario["matter"]["id"]
    partner_id = scenario["partner"]["id"]
    assert read_matter(api, matter_id)["verified_billable_hours"] == approx2(0.00)
    before = matter_allocations(api, matter_id, state="ACTIVE")
    assert [row for row in before if row["credit_role"] == "WORKING"] == []

    allocated = adjudicate_claim(
        api,
        claim_id=scenario["claim"]["id"],
        arbiter_id=scenario["arbiter"]["id"],
        decision="ALLOCATE",
        matter_id=matter_id,
        approved_pct=100.00,
    )
    assert allocated["state"] == "ALLOCATED"

    rows = matter_allocations(api, matter_id, state="ACTIVE")
    assert [row for row in rows if row["credit_role"] == "WORKING"] == []
    assert find_allocation(rows, "ORIGINATING", partner_id)[
        "credited_collection_provisional_cents"
    ] == 130_000
    assert find_allocation(rows, "BILLING", partner_id)[
        "credited_collection_provisional_cents"
    ] == 40_000
    assert find_allocation(rows, "RESPONSIBLE", partner_id)[
        "credited_collection_provisional_cents"
    ] == 30_000
    assert sum(row["credited_collection_provisional_cents"] for row in rows) == 200_000
    assert read_partner(api, partner_id)["credited_collection_provisional_cents"] == 200_000
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)


def test_origination_never_folds_so_its_pool_waits_unallocated(api):
    """PRD 3.5: "Then any of the billing, responsibility and working roles that
    has no active allocation folds its entire pool into the origination pool and
    is left at 0 — origination itself never folds." "A role with no rows, or with
    a pool of 0, is skipped."

    Design: Difficulty/boundary_precision_check/empty_working_role_folds_whole_quarter_into_originating
    """
    scenario = _matter_awaiting_allocation_with_no_verified_hours(api)
    matter_id = scenario["matter"]["id"]
    partner_id = scenario["partner"]["id"]

    rows = matter_allocations(api, matter_id, state="ACTIVE")
    assert [row["credit_role"] for row in rows if row["credit_role"] == "ORIGINATING"] == []
    assert find_allocation(rows, "BILLING", partner_id)[
        "credited_collection_provisional_cents"
    ] == 40_000
    assert find_allocation(rows, "RESPONSIBLE", partner_id)[
        "credited_collection_provisional_cents"
    ] == 30_000
    assert sum(row["credited_collection_provisional_cents"] for row in rows) == 70_000
    assert read_partner(api, partner_id)["credited_collection_provisional_cents"] == 70_000
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(0.00)


def _four_non_billable_categories(api):
    """Firm management 300.00, pro bono 60.00, training 40.00 and recruiting
    1.00 booked for one FORMULA partner, with only the first two verified."""
    cycle = create_cycle(api)
    partner = create_partner(
        api,
        full_name="Nina Nonbillable",
        practice_group="REGULATORY",
        compensation_model="FORMULA",
        admission_year=2014,
    )
    records = {}
    for category, hours in (
        ("FIRM_MANAGEMENT", 300.00),
        ("PRO_BONO", 60.00),
        ("TRAINING", 40.00),
        ("RECRUITING", 1.00),
    ):
        records[category] = create_non_billable_record(
            api,
            partner_id=partner["id"],
            cycle_id=cycle["id"],
            category=category,
            hours=hours,
            service_period_start="2026-01-01",
            service_period_end="2026-06-30",
        )
    verify_record(api, records["FIRM_MANAGEMENT"]["id"])
    verify_record(api, records["PRO_BONO"]["id"])
    return {"cycle": cycle, "partner": partner, "records": records}


def test_capped_total_of_exactly_four_hundred_escapes_the_discount(api):
    """PRD 3.3: "Note that the average weight is deliberately taken from the
    capped weighted base rather than from raw hours, so raising an uncapped
    category changes the discount that lands on every other category; and note
    that a capped total of exactly 400 hours attracts no discount at all, because
    the comparison is strict."

    Design: Difficulty/boundary_precision_check/capped_non_billable_hours_exactly_at_diminishing_threshold
    """
    scenario = _four_non_billable_categories(api)
    partner_id = scenario["partner"]["id"]
    assert read_partner(api, partner_id)["non_billable_points"] == approx2(525.00)

    verify_record(api, scenario["records"]["TRAINING"]["id"])

    assert read_partner(api, partner_id)["non_billable_points"] == approx2(555.00)


def test_one_hour_past_the_threshold_earns_only_a_third_of_its_weight(api):
    """PRD 3.3: "The hours in excess of 400 are multiplied by the base's average
    weight — the weighted base divided by the capped total — and by one half, and
    that product is subtracted from the base."

    Design: Difficulty/boundary_precision_check/capped_non_billable_hours_exactly_at_diminishing_threshold
    """
    scenario = _four_non_billable_categories(api)
    partner_id = scenario["partner"]["id"]
    verify_record(api, scenario["records"]["TRAINING"]["id"])
    points_at_threshold = read_partner(api, partner_id)["non_billable_points"]

    verified = verify_record(api, scenario["records"]["RECRUITING"]["id"])
    points_over = read_partner(api, partner_id)["non_billable_points"]

    assert verified["verified"] is True
    assert verified["hours"] == approx2(1.00)
    assert points_at_threshold == approx2(555.00)
    assert points_over == approx2(555.31)
    assert points_over - points_at_threshold == approx2(0.31)
