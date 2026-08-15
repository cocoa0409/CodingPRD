"""Market assumption active-set invariant and scenario construction/computation
rules (PRD §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_assumption,
    assert_exactly_one_assumption_active,
    assert_scenario,
    cast_vote,
    create_deal,
    create_memo_fresh,
    create_scenario_fresh,
    get_success_data,
    make_asset_manager_headers,
    setup_canonical_computed_scenario,
    setup_computed_scenario,
    setup_underwriting_env,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_first_assumption_active_by_default(api, analyst_headers):
    """PRD §3.3: "Exactly one assumption set per deal is active at any moment,
    tracked by the `is_active` flag."
    PRD §3.3: "The very first `MarketAssumption` created on a deal is
    automatically set to `is_active=true`."

    Design: Difficulty/compensating_invariant/assumption_activate_deactivate_conserves_exactly_one_active
    """
    deal = create_deal()
    a1 = validate_success(
        api.create_assumption(deal["id"], {"label": "A1", "market_rent_growth_yr1_bps": 200,
                                           "market_rent_growth_steady_bps": 200,
                                           "expense_growth_bps": 200, "exit_cap_rate_bps": 600,
                                           "hold_period_years": 5, "capex_per_unit_cents": 100_000,
                                           "lease_up_months": 0}, analyst_headers),
        201,
    )
    a2 = validate_success(
        api.create_assumption(deal["id"], {"label": "A2", "market_rent_growth_yr1_bps": 300,
                                           "market_rent_growth_steady_bps": 300,
                                           "expense_growth_bps": 300, "exit_cap_rate_bps": 650,
                                           "hold_period_years": 7, "capex_per_unit_cents": 200_000,
                                           "lease_up_months": 3}, analyst_headers),
        201,
    )
    assert a1["is_active"] is True, "first assumption set must become active by default"
    assert a2["is_active"] is False, (
        f"second set must not be active while A1 holds the flag, got {a2['is_active']!r}"
    )
    rows, _ = validate_paginated(api.list_assumptions(deal["id"], analyst_headers))
    assert_exactly_one_assumption_active(rows)


def test_activate_flips_other_assumptions(api, analyst_headers):
    """PRD §3.3: "Activating a different assumption set is a dedicated action: it
    sets `is_active=true` on the target set, flips every other set on the same
    deal to `is_active=false`, and increments the target set's `version` by 1."

    Design: Difficulty/compensating_invariant/assumption_activate_deactivate_conserves_exactly_one_active
    """
    deal = create_deal()
    a1 = get_success_data(api.create_assumption(
        deal["id"], {"label": "A1", "market_rent_growth_yr1_bps": 200,
                     "market_rent_growth_steady_bps": 200, "expense_growth_bps": 200,
                     "exit_cap_rate_bps": 600, "hold_period_years": 5,
                     "capex_per_unit_cents": 100_000, "lease_up_months": 0},
        analyst_headers,
    ))
    a2 = get_success_data(api.create_assumption(
        deal["id"], {"label": "A2", "market_rent_growth_yr1_bps": 300,
                     "market_rent_growth_steady_bps": 300, "expense_growth_bps": 300,
                     "exit_cap_rate_bps": 650, "hold_period_years": 7,
                     "capex_per_unit_cents": 200_000, "lease_up_months": 3},
        analyst_headers,
    ))

    activated = validate_success(api.activate_assumption(a2["id"], analyst_headers), 200)
    assert activated["is_active"] is True
    assert activated["version"] == a2["version"] + 1, (
        f"activate must increment the target set's version: {a2['version']} -> {activated['version']}"
    )

    a1_after = validate_success(api.get_assumption(a1["id"], analyst_headers), 200)
    a2_after = validate_success(api.get_assumption(a2["id"], analyst_headers), 200)
    assert a2_after["is_active"] is True
    assert a1_after["is_active"] is False, "A1 must be flipped off by the activation of A2"
    rows, _ = validate_paginated(api.list_assumptions(deal["id"], analyst_headers))
    assert len(rows) == 2, "activation conserves the total row count"
    assert_exactly_one_assumption_active(rows)


def test_scenario_create_cross_deal_assumption_rejected(api, analyst_headers):
    """PRD §3.4: "The referenced `assumption_id` must resolve to a
    `MarketAssumption` belonging to the same deal; a cross-deal reference is
    rejected with `ERR_ASSUMPTION_MISMATCH` (HTTP 422)."

    Design: Corner/validations/assumption_mismatch_on_scenario_create
    """
    d2 = create_deal(deal_code="D-AM2", deal_name="A2", target_purchase_price_cents=100)
    a_d2 = add_assumption(d2["id"], label="D2 set")
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-AM3"})
    payload = {
        "scenario_kind": "BASE",
        "assumption_id": a_d2["id"],
        "occupancy_stress_pct": 90,
        "expected_deal_version": env["deal"]["version"],
    }
    res = api.create_scenario(env["deal"]["id"], payload, analyst_headers)
    validate_error(res, ApiErrorId.ERR_ASSUMPTION_MISMATCH)


def test_scenario_list_filter_by_status(api, analyst_headers):
    """PRD §4: "List scenarios for a deal (filterable by `status`,
    `scenario_kind`, `assumption_id`, `superseded_by_id`)".
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."
    PRD §3.4: "A new scenario starts in `DRAFT` status."

    Design: Corner/entities/scenario_list_filter_by_status
    """
    env = setup_underwriting_env()
    s1 = create_scenario_fresh(env["deal"]["id"], env["assumption"]["id"],
                               scenario_kind="BASE", occupancy_stress_pct=90)
    s1 = validate_success(api.compute_scenario(s1["id"], analyst_headers), 200)
    assert_scenario(s1)
    assert s1["status"] == "COMPUTED"
    s2 = create_scenario_fresh(env["deal"]["id"], env["assumption"]["id"],
                               scenario_kind="DOWNSIDE", occupancy_stress_pct=80)
    assert s2["status"] == "DRAFT"

    computed_rows, meta = validate_paginated(
        api.list_scenarios(env["deal"]["id"], analyst_headers, params={"status": "COMPUTED"})
    )
    assert [r["id"] for r in computed_rows] == [s1["id"]], (
        f"status=COMPUTED must return only the computed scenario, got {[r['id'] for r in computed_rows]}"
    )
    draft_rows, _ = validate_paginated(
        api.list_scenarios(env["deal"]["id"], analyst_headers, params={"status": "DRAFT"})
    )
    assert [r["id"] for r in draft_rows] == [s2["id"]], (
        f"status=DRAFT must return only the draft scenario, got {[r['id'] for r in draft_rows]}"
    )
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination meta missing {field}"


def test_compute_rejected_when_deal_in_draft(api, analyst_headers):
    """PRD §3.4: "Computation requires that the parent deal is in `UNDERWRITING`
    status; attempting to compute a scenario while the deal is in any other state
    is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.1: "If the team decides to step back, the analyst may reopen the deal,
    transitioning it `UNDERWRITING → DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/scenario_compute_requires_deal_underwriting
    """
    env = setup_underwriting_env(
        deal_overrides={"deal_code": "D-X1"},
        property_overrides={"property_type": "OFFICE"},
        rent_rolls=[{"period_month": "2026-06", "occupied_units": 9, "total_units": 10,
                     "gross_potential_rent_cents": 1_000_000, "collected_rent_cents": 900_000,
                     "source_doc_ref": "rr"}],
        expenses=[{"period_year": 2025, "category": "TAXES", "amount_cents": 1_000_000}],
    )
    scenario = create_scenario_fresh(env["deal"]["id"], env["assumption"]["id"],
                                     scenario_kind="BASE", occupancy_stress_pct=90)
    assert scenario["status"] == "DRAFT"

    reopened = validate_success(api.reopen_deal(env["deal"]["id"], analyst_headers), 200)
    assert reopened["status"] == "DRAFT"

    res = api.compute_scenario(scenario["id"], analyst_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_scenario(scenario["id"], analyst_headers), 200)
    assert after["status"] == "DRAFT", "rejected compute must leave the scenario in DRAFT"


def test_compute_rejected_when_deal_rejected(api, analyst_headers):
    """PRD §3.4: "Computation requires that the parent deal is in `UNDERWRITING`
    status; attempting to compute a scenario while the deal is in any other state
    is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.8: "If any `NO` vote is cast, the memo cascades `UNDER_VOTE → REJECTED`
    and the deal cascades `IC_REVIEW → REJECTED`."

    Design: Difficulty/cross_entity_state_dependency/scenario_compute_requires_deal_underwriting
    """
    env = setup_computed_scenario(deal_overrides={"deal_code": "D-X3"})
    scenario_computed = env["scenario"]
    # A second scenario stays in DRAFT through the whole IC walk.
    scenario_draft = create_scenario_fresh(
        env["deal"]["id"], env["assumption"]["id"],
        scenario_kind="DOWNSIDE", occupancy_stress_pct=80,
    )
    memo = create_memo_fresh(env["deal"]["id"], scenario_computed["id"])
    get_success_data(api.submit_ic_memo(memo["id"], analyst_headers))
    get_success_data(
        api.submit_ic(env["deal"]["id"], make_asset_manager_headers(env["asset_manager_id"]))
    )
    get_success_data(cast_vote(memo["id"], "NO", comment="no"))
    deal = get_success_data(api.get_deal(env["deal"]["id"], analyst_headers))
    assert deal["status"] == "REJECTED"

    res = api.compute_scenario(scenario_draft["id"], analyst_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_noi_uses_latest_period_year_expenses_only(api, analyst_headers):
    """PRD §3.4.1: "The relevant rent roll is the one with the latest
    `period_month`; the relevant expense set is all `OperatingExpense` rows on the
    property for the latest `period_year`, summed."
    PRD §3.4.1: "Year-one NOI is the chosen effective-gross-income variant minus
    year-one operating expenses, rounded half-up to integer cents."
    With zero growth, zero capex, zero lease-up, and zero concessions this pins
    NOI = 10_000_000 * 12 * 0.92 - 14_000_000 = 96_400_000 cents (only the 2025
    row enters; the 2024 row and the 26_000_000 sum are both wrong inputs).

    Design: Corner/calculations/noi_uses_latest_period_year_expenses_only
    """
    env = setup_underwriting_env(
        deal_overrides={"deal_code": "D-NOIY", "target_purchase_price_cents": 1_000_000_000},
        property_overrides={"units": 100, "rentable_sqft": 100_000, "year_built": 2000},
        rent_rolls=[{"period_month": "2026-06", "occupied_units": 92, "total_units": 100,
                     "gross_potential_rent_cents": 10_000_000, "collected_rent_cents": 9_200_000,
                     "concessions_cents": 0, "source_doc_ref": "rr"}],
        expenses=[
            {"period_year": 2024, "category": "TAXES", "amount_cents": 12_000_000},
            {"period_year": 2025, "category": "TAXES", "amount_cents": 14_000_000},
        ],
        assumption_overrides={
            "market_rent_growth_yr1_bps": 0, "market_rent_growth_steady_bps": 0,
            "expense_growth_bps": 0, "exit_cap_rate_bps": 500, "hold_period_years": 5,
            "capex_per_unit_cents": 0, "lease_up_months": 0,
        },
    )
    scenario = create_scenario_fresh(env["deal"]["id"], env["assumption"]["id"],
                                     scenario_kind="BASE", occupancy_stress_pct=92)
    computed = validate_success(api.compute_scenario(scenario["id"], analyst_headers), 200)
    assert computed["computed_noi_yr1_cents"] == 96_400_000, (
        f"expected 96400000 (latest expense year only), got {computed['computed_noi_yr1_cents']}"
    )


def test_noi_combinatorial_inputs_at_occupancy_85(api, analyst_headers):
    """PRD §3.4.1: "The occupancy factor is `occupancy_stress_pct` divided by 100.
    The year-one growth factor is one plus `market_rent_growth_yr1_bps` divided by
    10000."
    PRD §3.4.1: "- The **provisional** variant — used while the scenario is still
    in `DRAFT` at the moment compute is invoked — subtracts annualized concessions
    after applying the growth factor: annualized gross potential rent is
    multiplied by the occupancy factor, multiplied by the year-one growth factor,
    and only then are annualized concessions subtracted."
    PRD §3.4.1: "Third, year-one operating expenses are computed. The summed
    expenses from the latest `period_year` are grown by one plus
    `expense_growth_bps` divided by 10000. Two additional charges are added on
    top. The capex budget — `capex_per_unit_cents` multiplied by the property's
    `units` — is straight-line amortized across the hold period by dividing by the
    larger of 1 and `hold_period_years`. The lease-up cost — `lease_up_months`
    multiplied by the monthly gross potential rent, then multiplied by one minus
    the occupancy factor — is charged fully to year one."
    Pinned arithmetic: EGI = 120_000_000 * 0.85 * 1.025 - 2_400_000 = 102_150_000;
    opex = 25_200_000 * 1.02 + 50_000_000 / 5 + 6 * 10_000_000 * 0.15 =
    44_704_000; NOI = 57_446_000 cents.

    Design: Difficulty/combinatorial_formula/noi_year1_three_input_conditional_branching
    """
    env = setup_canonical_computed_scenario(
        deal_code="D-COMB1", occupancy_stress_pct=85, scenario_kind="DOWNSIDE"
    )
    scenario = env["scenario"]
    assert scenario["status"] == "COMPUTED"
    assert scenario["computed_noi_yr1_cents"] == 57_446_000, (
        f"expected 57446000 from the three-input interaction, "
        f"got {scenario['computed_noi_yr1_cents']}"
    )


def test_noi_occupancy_stress_branch_contrast(api, analyst_headers):
    """PRD §3.4.1: "The occupancy factor is `occupancy_stress_pct` divided by 100.
    The year-one growth factor is one plus `market_rent_growth_yr1_bps` divided by
    10000."
    PRD §3.4.1: "Year-one NOI is the chosen effective-gross-income variant minus
    year-one operating expenses, rounded half-up to integer cents."
    The occupancy factor enters multiplicatively (EGI side) and subtractively
    (lease-up side), so on identical inputs an occupancy_stress_pct of 92 must
    yield a strictly higher year-1 NOI than 85 — the conditional branches of the
    formula are non-linear in the occupancy input.

    Design: Difficulty/combinatorial_formula/noi_year1_three_input_conditional_branching
    """
    env = setup_canonical_computed_scenario(
        deal_code="D-COMB2", occupancy_stress_pct=92, scenario_kind="BASE"
    )
    noi_92 = env["scenario"]["computed_noi_yr1_cents"]
    downside = create_scenario_fresh(
        env["deal"]["id"], env["assumption"]["id"],
        scenario_kind="DOWNSIDE", occupancy_stress_pct=85,
    )
    noi_85 = validate_success(api.compute_scenario(downside["id"], analyst_headers), 200)[
        "computed_noi_yr1_cents"
    ]
    assert noi_85 == 57_446_000, f"expected 57446000, got {noi_85}"
    assert noi_92 > noi_85, (
        f"higher occupancy stress assumption must raise NOI: {noi_92} !> {noi_85}"
    )
