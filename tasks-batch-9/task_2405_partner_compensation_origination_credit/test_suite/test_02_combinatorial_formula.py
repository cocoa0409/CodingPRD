"""Multi-factor formula chains: two-layer credited-collection rounding, the
five-step non-billable points pipeline, and the pinned firm normalization."""

from test_helpers import (
    approx2,
    approx4,
    approx6,
    create_cycle,
    create_matter,
    create_non_billable_record,
    create_partner,
    find_allocation,
    matter_allocations,
    post_financials,
    read_cycle,
    read_matter,
    read_partner,
    setup_split_adjudicated_matter,
    verify_record,
)


def test_two_layer_split_pins_every_allocation_to_whole_cents(api):
    """PRD 3.5: "In the first layer, each of the four role pools is computed as
    the basis multiplied by that role's weight and rounded half up to whole
    cents." "Finally the first layer's rounding residual, the basis less the sum
    of the four pools, is added to the origination pool, so the four pools sum to
    the basis exactly."

    Design: Difficulty/combinatorial_formula/credited_collection_two_layer_rounding_residuals_pinned
    """
    scenario = setup_split_adjudicated_matter(api)
    matter = read_matter(api, scenario["matter"]["id"])
    assert matter["realization_pct"] == approx4(0.5000)
    assert matter["origination_pct_assigned"] == approx2(100.00)

    rows = matter_allocations(api, matter["id"], state="ACTIVE")
    claimant_id = scenario["claimant"]["id"]
    disputer_id = scenario["disputer"]["id"]

    assert find_allocation(rows, "ORIGINATING", claimant_id)[
        "credited_collection_provisional_cents"
    ] == 20_001
    assert find_allocation(rows, "ORIGINATING", disputer_id)[
        "credited_collection_provisional_cents"
    ] == 20_002
    assert find_allocation(rows, "BILLING", claimant_id)[
        "credited_collection_provisional_cents"
    ] == 20_002
    assert find_allocation(rows, "RESPONSIBLE", claimant_id)[
        "credited_collection_provisional_cents"
    ] == 15_002
    assert find_allocation(rows, "WORKING", claimant_id)[
        "credited_collection_provisional_cents"
    ] == 25_003


def test_two_layer_shares_resum_to_the_basis_and_final_basis_stays_empty(api):
    """PRD 3.5: "In the second layer, each role's pool is distributed across that
    role's active allocations taken in `created_at` ascending order: each
    allocation's share is the pool multiplied by that allocation's `credit_pct`
    divided by 100 and rounded half up to whole cents, and the pool's own
    residual — the pool less the sum of those shares — is handed to the single
    allocation with the largest `credit_pct`, ties broken in favour of the
    earlier `created_at`."

    Design: Difficulty/combinatorial_formula/credited_collection_two_layer_rounding_residuals_pinned
    """
    scenario = setup_split_adjudicated_matter(api)
    rows = matter_allocations(api, scenario["matter"]["id"], state="ACTIVE")

    assert len(rows) == 5
    assert sum(row["credited_collection_provisional_cents"] for row in rows) == 100_010
    assert all(row["credited_collection_final_cents"] == 0 for row in rows)

    claimant = read_partner(api, scenario["claimant"]["id"])
    disputer = read_partner(api, scenario["disputer"]["id"])
    assert claimant["credited_collection_provisional_cents"] == 80_008
    assert disputer["credited_collection_provisional_cents"] == 20_002


def test_non_billable_points_cap_diminish_and_pro_bono_floor_compose(api):
    """PRD 3.3: "Third, a diminishing return is applied when the capped total is
    strictly greater than 400 hours. The hours in excess of 400 are multiplied by
    the base's average weight — the weighted base divided by the capped total —
    and by one half, and that product is subtracted from the base."

    Design: Difficulty/combinatorial_formula/non_billable_points_cap_then_diminishing_then_floor_penalty
    """
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    for category, hours in (
        ("FIRM_MANAGEMENT", 320.00),
        ("RECRUITING", 100.00),
        ("PRO_BONO", 40.00),
    ):
        record = create_non_billable_record(
            api,
            partner_id=partner["id"],
            cycle_id=cycle["id"],
            category=category,
            hours=hours,
            service_period_start="2026-01-01",
            service_period_end="2026-03-31",
        )
        verify_record(api, record["id"])

    assert read_partner(api, partner["id"])["non_billable_points"] == approx2(515.45)


def test_verifying_a_further_category_reshapes_the_whole_diminishing_discount(api):
    """PRD 3.3: "Note that the average weight is deliberately taken from the
    capped weighted base rather than from raw hours, so raising an uncapped
    category changes the discount that lands on every other category; and note
    that a capped total of exactly 400 hours attracts no discount at all, because
    the comparison is strict."

    Design: Difficulty/combinatorial_formula/non_billable_points_cap_then_diminishing_then_floor_penalty
    """
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    for category, hours in (
        ("FIRM_MANAGEMENT", 320.00),
        ("RECRUITING", 100.00),
        ("PRO_BONO", 40.00),
    ):
        record = create_non_billable_record(
            api,
            partner_id=partner["id"],
            cycle_id=cycle["id"],
            category=category,
            hours=hours,
            service_period_start="2026-01-01",
            service_period_end="2026-03-31",
        )
        verify_record(api, record["id"])
    training = create_non_billable_record(
        api,
        partner_id=partner["id"],
        cycle_id=cycle["id"],
        category="TRAINING",
        hours=60.00,
        service_period_start="2026-01-01",
        service_period_end="2026-03-31",
    )

    points_before = read_partner(api, partner["id"])["non_billable_points"]
    verified = verify_record(api, training["id"])
    points_after = read_partner(api, partner["id"])["non_billable_points"]

    assert verified["verified"] is True
    assert points_before == approx2(515.45)
    assert points_after == approx2(522.45)
    assert points_after - points_before == approx2(7.00)
    assert read_partner(api, partner["id"])["verified_billable_hours"] == approx2(0.00)


def test_normalization_factor_is_pinned_before_each_index_consumes_it(api):
    """PRD 3.5: "Compute the normalization factor as the firm normalization
    target of 1,000,000,000 cents — ten million dollars — divided by the firm
    total, rounded half up to 6 decimal places."

    Design: Difficulty/combinatorial_formula/formula_score_normalization_pinned_before_index_consumption
    """
    scenario = setup_split_adjudicated_matter(api)
    arbiter = scenario["arbiter"]
    second = create_matter(
        api,
        billing_attorney_id=arbiter["id"],
        responsible_attorney_id=arbiter["id"],
        client_key="CLI-R2",
        client_display_name="Second Sector",
        matter_type="EXISTING",
        practice_group="REGULATORY",
        opened_on="2026-02-01",
    )
    post_financials(
        api,
        second["id"],
        billed_delta_cents=100_000,
        collected_delta_cents=100_000,
        direct_cost_delta_cents=0,
    )

    claimant = read_partner(api, scenario["claimant"]["id"])
    disputer = read_partner(api, scenario["disputer"]["id"])
    arbiter = read_partner(api, arbiter["id"])

    assert claimant["credited_collection_provisional_cents"] == 80_008
    assert disputer["credited_collection_provisional_cents"] == 20_002
    assert arbiter["credited_collection_provisional_cents"] == 35_000
    assert claimant["normalized_credit_index_provisional"] == approx6(0.592608)
    assert disputer["normalized_credit_index_provisional"] == approx6(0.148152)
    assert arbiter["normalized_credit_index_provisional"] == approx6(0.259240)


def test_empty_working_pool_folds_into_origination_and_scores_follow(api):
    """PRD 3.5: "Then any of the billing, responsibility and working roles that
    has no active allocation folds its entire pool into the origination pool and
    is left at 0 — origination itself never folds."

    Design: Difficulty/combinatorial_formula/formula_score_normalization_pinned_before_index_consumption
    """
    scenario = setup_split_adjudicated_matter(api)
    arbiter_id = scenario["arbiter"]["id"]
    second = create_matter(
        api,
        billing_attorney_id=arbiter_id,
        responsible_attorney_id=arbiter_id,
        client_key="CLI-R2",
        client_display_name="Second Sector",
        matter_type="EXISTING",
        practice_group="REGULATORY",
        opened_on="2026-02-01",
    )
    post_financials(
        api,
        second["id"],
        billed_delta_cents=100_000,
        collected_delta_cents=100_000,
        direct_cost_delta_cents=0,
    )

    rows = matter_allocations(api, second["id"], state="ACTIVE")
    assert find_allocation(rows, "BILLING", arbiter_id)[
        "credited_collection_provisional_cents"
    ] == 20_000
    assert find_allocation(rows, "RESPONSIBLE", arbiter_id)[
        "credited_collection_provisional_cents"
    ] == 15_000
    assert [row for row in rows if row["credit_role"] == "WORKING"] == []

    assert read_partner(api, scenario["claimant"]["id"])["formula_score_provisional"] == approx4(
        28.2922
    )
    assert read_partner(api, scenario["disputer"]["id"])["formula_score_provisional"] == approx4(
        13.2501
    )
    assert read_partner(api, arbiter_id)["formula_score_provisional"] == approx4(34.8324)
    assert read_cycle(api, scenario["cycle"]["id"])["total_formula_score"] == approx4(76.3747)
