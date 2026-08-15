"""Inventory recalculation: input-set filtering, pinned rounding order, the
dual location/market scope-2 variants, dual final/provisional scope-3
variants, the market waterfall, factor pinning, and instrument/record
conservation pairs."""
import pytest

from test_helpers import (
    ANALYST, MANAGER, approve_record, create_approved_record, cycle_version,
    decide_engagement, make_collecting_cycle, make_engagement, make_factor,
    make_instrument, make_site, monthly_periods, recalc_inventory,
    respond_to_engagement, retire_instrument, review_record, submit_record,
    transition_payload, validate_paginated, validate_success,
)


def _ca_lab():
    """Site in CA with PUBLISHED grid 0.4 and residual-mix 0.5 factors."""
    site = make_site(name="Alpha", grid_region_code="CA")
    grid = make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
    )
    residual = make_factor(
        scope_category="SCOPE2_RESIDUAL_MIX", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.5,
    )
    return site, grid, residual


def _approve_electricity(cycle_id, site_id, factor_id, quantity, period):
    start, end = period
    return create_approved_record(
        cycle_id, site_id, factor_id, activity_type="ELECTRICITY",
        quantity=quantity, unit="MWh", period_start=start, period_end=end,
    )


# ---------------------------------------------------------------------------
# Input-set filtering and zero case
# ---------------------------------------------------------------------------

def test_recalc_includes_only_approved_records(api, manager_headers):
    """PRD §3.7: "Only `APPROVED` records feed these totals; `SUBMITTED`,
    `UNDER_REVIEW`, `REJECTED`, and `VOIDED` records are excluded."

    Design: Corner/calculations/recalc_includes_only_approved_records
    """
    site = make_site()
    factor = make_factor(value_tco2e_per_unit=1.0)
    cycle = make_collecting_cycle()
    create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=10,
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    # SUBMITTED (never reviewed) and REJECTED records contribute nothing.
    submit_record(
        cycle["id"], site["id"], factor["id"], quantity=999,
        period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
    )
    rejected = submit_record(
        cycle["id"], site["id"], factor["id"], quantity=999,
        period_start="2026-03-01T00:00:00Z", period_end="2026-04-01T00:00:00Z",
    )
    review_record(rejected["id"])
    validate_success(
        api.transition_activity_record(
            rejected["id"], transition_payload("REJECTED", reason="Bad meter read"),
            ANALYST,
        )
    )

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope1_tco2e"] == pytest.approx(10.0, abs=0.005)
    assert inventory["total_tco2e"] == pytest.approx(10.0, abs=0.005)


def test_recalc_with_zero_records_yields_zeros(api, manager_headers):
    """PRD §3.2: "Creation also materializes the cycle's singleton Inventory
    Result — exactly one per cycle, created with the cycle — with status
    `STALE`, every scope total at 0.0, and `computed_at` null until the first
    recalculation." PRD §3.4: "with no approved records it is 0.0."

    Design: Corner/calculations/recalc_with_zero_records_yields_zeros
    """
    cycle = make_collecting_cycle()
    assert cycle["readiness_pct"] == pytest.approx(0.0, abs=0.05), (
        "readiness starts at 0.0 with an empty approved set"
    )
    inventory = recalc_inventory(cycle["id"])
    assert inventory["status"] == "CURRENT"
    for field in ("scope1_tco2e", "scope2_location_tco2e", "scope2_market_tco2e",
                  "scope3_tco2e", "scope3_provisional_tco2e", "total_tco2e"):
        assert inventory[field] == pytest.approx(0.0, abs=0.005), (
            f"{field} must be 0.0 on an empty inventory, got {inventory[field]}"
        )


# ---------------------------------------------------------------------------
# Pinned nested rounding (difficulty: combinatorial_formula mode b)
# ---------------------------------------------------------------------------

def test_inventory_rounding_rounds_each_record_before_summing(api, manager_headers):
    """PRD §2.7: "Rounding order inside the inventory is pinned: each line is
    rounded first, the rounded lines are summed, and the scope-level sum is
    then rounded — summing unrounded inputs and rounding once at the end is
    expressly forbidden." PRD §3.3: "`tco2e` is computed as the `quantity`
    multiplied by that snapshot, rounded half-up to four decimal places".

    Design: Difficulty/combinatorial_formula/inventory_nested_rounding_order
    """
    site = make_site(name="BoilerHouse")
    factor = make_factor(value_tco2e_per_unit=0.00099)
    cycle = make_collecting_cycle()
    records = []
    for start, end in monthly_periods(2026, 5):
        records.append(
            create_approved_record(
                cycle["id"], site["id"], factor["id"], quantity=1,
                period_start=start, period_end=end,
            )
        )
    # Each line: round_half_up(1 x 0.00099, 4) = 0.0010.
    assert records[-1]["tco2e"] == pytest.approx(0.001, abs=0.00005)

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope1_tco2e"] == pytest.approx(0.01, abs=0.005), (
        "sum of rounded lines 0.0050 -> round_half_up 2dp = 0.01; "
        "the forbidden sum-then-round order would give round2(0.00495) = 0.00"
    )


def test_record_tco2e_rounds_half_up_on_exact_tie(api, analyst_headers):
    """PRD §2.7: "All emissions arithmetic uses decimal math with
    round-half-up rounding" and PRD §3.3: "`tco2e` is computed as the
    `quantity` multiplied by that snapshot, rounded half-up to four decimal
    places".

    Design: Difficulty/combinatorial_formula/inventory_nested_rounding_order
    """
    site = make_site()
    factor = make_factor(value_tco2e_per_unit=0.00001)
    cycle = make_collecting_cycle()
    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=5)
    review_record(record["id"])
    approved = approve_record(record["id"])
    # 5 x 0.00001 = 0.00005 exactly: round-half-up to 4dp gives 0.0001.
    assert approved["tco2e"] == pytest.approx(0.0001, abs=0.00005), (
        "an exact 4dp tie must round up (round-half-even would give 0.0000)"
    )


# ---------------------------------------------------------------------------
# Dual scope-2 variants (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------

def test_scope2_location_and_market_diverge_with_retirement(api, manager_headers):
    """PRD §3.7: "`scope2_location_tco2e` is the rounded sum over `APPROVED`
    `ELECTRICITY` records — the location-based variant, which prices
    electricity purely at the factors chosen on the records and ignores
    instrument retirements and residual mix entirely." and "Retired energy is
    treated as zero-emission, so the site's market-based line is the residual
    multiplied by the residual rate, rounded half-up to four decimal places."

    Design: Difficulty/dual_variant_calc/scope2_location_vs_market_divergence
    """
    site, grid, _residual = _ca_lab()
    cycle = make_collecting_cycle()
    _approve_electricity(
        cycle["id"], site["id"], grid["id"], 100,
        ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    )
    instrument = make_instrument(serial_number="S-100", technology="SOLAR",
                                 vintage_year=2026, quantity_mwh=30)
    retire_instrument(instrument["id"], cycle["id"], site["id"])

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope2_location_tco2e"] == pytest.approx(40.0, abs=0.005), (
        "location ignores retirements: 100 MWh x grid 0.4"
    )
    assert inventory["scope2_market_tco2e"] == pytest.approx(35.0, abs=0.005), (
        "market: covered min(100, 30) = 30 at zero + residual 70 x 0.5"
    )
    assert inventory["scope2_location_tco2e"] != inventory["scope2_market_tco2e"]


def test_scope2_market_falls_back_to_grid_factor(api, manager_headers):
    """PRD §3.7: "The residual rate resolves at the cycle midpoint, midnight
    UTC on July 1 of the `reporting_year`: first the `PUBLISHED`
    `SCOPE2_RESIDUAL_MIX` factor for the site's `grid_region_code` whose
    closed validity window contains the midpoint; failing that, the
    `PUBLISHED` `SCOPE2_GRID` factor for the same `grid_region_code` covering
    the midpoint; failing both, zero."

    Design: Difficulty/dual_variant_calc/scope2_location_vs_market_divergence
    """
    # No residual-mix factor for CA: market must fall back to the grid rate.
    site = make_site(name="Alpha", grid_region_code="CA")
    grid = make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
    )
    cycle = make_collecting_cycle()
    _approve_electricity(
        cycle["id"], site["id"], grid["id"], 100,
        ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    )
    instrument = make_instrument(serial_number="S-100", quantity_mwh=30)
    retire_instrument(instrument["id"], cycle["id"], site["id"])

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope2_location_tco2e"] == pytest.approx(40.0, abs=0.005)
    assert inventory["scope2_market_tco2e"] == pytest.approx(28.0, abs=0.005), (
        "covered 30 at zero + residual 70 priced at the grid fallback 0.4"
    )


# ---------------------------------------------------------------------------
# Dual scope-3 variants (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------

def _eeio_factor():
    return make_factor(
        scope_category="SCOPE3_EEIO_SPEND", region_code="GLOBAL", unit="USD",
        value_tco2e_per_unit=0.0005,
    )


def test_scope3_final_uses_supplier_figure_provisional_uses_spend(api, manager_headers):
    """PRD §3.7: "`scope3_tco2e` is the rounded two-decimal sum of the travel
    line, plus the `supplier_tco2e` of each `ACCEPTED` engagement, plus the
    spend-based line of every engagement not in `ACCEPTED`.
    `scope3_provisional_tco2e` is the rounded two-decimal sum of the travel
    line plus the spend-based lines of all engagements — identical inputs,
    but accepted rows are priced spend-based, so the two columns diverge
    whenever an accepted supplier figure differs from its spend-based line."

    Design: Difficulty/dual_variant_calc/scope3_supplier_specific_vs_spend_based
    """
    _eeio_factor()
    cycle = make_collecting_cycle()
    engagement = make_engagement(
        cycle["id"], spend_usd=10000, contact_user_id="supplier-1"
    )
    respond_to_engagement(engagement["id"], 7.5, contact_user_id="supplier-1")
    decide_engagement(engagement["id"], "ACCEPT")

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope3_tco2e"] == pytest.approx(7.5, abs=0.005), (
        "final scope 3 takes the ACCEPTED supplier figure 7.50"
    )
    assert inventory["scope3_provisional_tco2e"] == pytest.approx(5.0, abs=0.005), (
        "provisional prices the same engagement spend-based: 10000 x 0.0005 = 5.00"
    )


def test_scope3_variants_diverge_across_mixed_engagement_states(api, manager_headers):
    """PRD §3.7: "`scope3_tco2e` is the rounded two-decimal sum of the travel
    line, plus the `supplier_tco2e` of each `ACCEPTED` engagement, plus the
    spend-based line of every engagement not in `ACCEPTED`." and
    "`scope3_provisional_tco2e` is the rounded two-decimal sum of the travel
    line plus the spend-based lines of all engagements".

    Design: Difficulty/dual_variant_calc/scope3_supplier_specific_vs_spend_based
    """
    _eeio_factor()
    cycle = make_collecting_cycle()
    accepted = make_engagement(
        cycle["id"], supplier_name="Acme Steel", spend_usd=10000,
        contact_user_id="supplier-1",
    )
    respond_to_engagement(accepted["id"], 7.5, contact_user_id="supplier-1")
    decide_engagement(accepted["id"], "ACCEPT")
    # A second engagement stays INVITED: priced spend-based in both columns.
    make_engagement(
        cycle["id"], supplier_name="Bolt Co", spend_usd=4000,
        contact_user_id="supplier-2",
    )

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope3_tco2e"] == pytest.approx(9.5, abs=0.005), (
        "final: supplier 7.50 + spend line 4000 x 0.0005 = 2.00"
    )
    assert inventory["scope3_provisional_tco2e"] == pytest.approx(7.0, abs=0.005), (
        "provisional: spend lines 5.00 + 2.00"
    )


# ---------------------------------------------------------------------------
# Market scope-2 waterfall (difficulty: combinatorial_formula mode a)
# ---------------------------------------------------------------------------

def test_market_scope2_waterfall_cap_and_grid_fallback(api, manager_headers):
    """PRD §3.7: "Covered megawatt-hours are the smaller of consumption and
    retired coverage — the cap prevents over-allocation — and the residual is
    consumption minus covered." and "The residual rate resolves at the cycle
    midpoint, midnight UTC on July 1 of the `reporting_year`: first the
    `PUBLISHED` `SCOPE2_RESIDUAL_MIX` factor for the site's `grid_region_code`
    whose closed validity window contains the midpoint; failing that, the
    `PUBLISHED` `SCOPE2_GRID` factor for the same `grid_region_code` covering
    the midpoint; failing both, zero."

    Design: Difficulty/combinatorial_formula/market_scope2_waterfall_cap_and_fallback
    """
    site_a = make_site(name="A", grid_region_code="CA")
    site_b = make_site(name="B", grid_region_code="CA")
    site_c = make_site(name="C", grid_region_code="CB")
    grid_ca = make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
    )
    make_factor(
        scope_category="SCOPE2_RESIDUAL_MIX", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.5,
    )
    grid_cb = make_factor(
        scope_category="SCOPE2_GRID", region_code="CB", unit="MWh",
        value_tco2e_per_unit=0.9,
    )
    cycle = make_collecting_cycle()
    jan = ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
    _approve_electricity(cycle["id"], site_a["id"], grid_ca["id"], 100, jan)
    _approve_electricity(cycle["id"], site_b["id"], grid_ca["id"], 50, jan)
    _approve_electricity(cycle["id"], site_c["id"], grid_cb["id"], 10, jan)
    retire_instrument(
        make_instrument(serial_number="S-A30", quantity_mwh=30)["id"],
        cycle["id"], site_a["id"],
    )
    retire_instrument(
        make_instrument(serial_number="S-B80", technology="WIND", quantity_mwh=80)["id"],
        cycle["id"], site_b["id"],
    )

    inventory = recalc_inventory(cycle["id"])
    # A: (100 - 30) x 0.5 = 35.0000; B: covered min(50, 80) = 50 -> residual 0;
    # C: no residual-mix factor -> grid fallback 0.9 -> 10 x 0.9 = 9.0000.
    assert inventory["scope2_market_tco2e"] == pytest.approx(44.0, abs=0.005)
    assert inventory["scope2_location_tco2e"] == pytest.approx(69.0, abs=0.005), (
        "location: 40.0000 + 20.0000 + 9.0000 at the records' grid factors"
    )


def test_market_scope2_cap_binds_when_retired_exceeds_consumption(api, manager_headers):
    """PRD §3.7: "Covered megawatt-hours are the smaller of consumption and
    retired coverage — the cap prevents over-allocation — and the residual is
    consumption minus covered. Retired energy is treated as zero-emission, so
    the site's market-based line is the residual multiplied by the residual
    rate, rounded half-up to four decimal places."

    Design: Difficulty/combinatorial_formula/market_scope2_waterfall_cap_and_fallback
    """
    site, grid, _residual = _ca_lab()
    cycle = make_collecting_cycle()
    _approve_electricity(
        cycle["id"], site["id"], grid["id"], 50,
        ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    )
    retire_instrument(
        make_instrument(serial_number="S-CAP", technology="WIND", quantity_mwh=80)["id"],
        cycle["id"], site["id"],
    )

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope2_market_tco2e"] == pytest.approx(0.0, abs=0.005), (
        "covered min(50, 80) = 50, residual 0 — the cap prevents over-allocation"
    )
    assert inventory["scope2_location_tco2e"] == pytest.approx(20.0, abs=0.005)


# ---------------------------------------------------------------------------
# Factor snapshot pinning (corner: version_pinning_on_approval)
# ---------------------------------------------------------------------------

def test_factor_snapshot_pinned_at_approval(api, manager_headers):
    """PRD §3.3: "On approval the system pins the factor value:
    `factor_value_snapshot` copies the factor's current
    `value_tco2e_per_unit` and is immutable thereafter, `tco2e` is computed
    as the `quantity` multiplied by that snapshot, rounded half-up to four
    decimal places, and `reviewed_by_user_id` records the approver." PRD
    §3.7: "`scope1_tco2e` is the rounded sum of `tco2e` over the cycle's
    `APPROVED` `STATIONARY_FUEL` records."

    Design: Corner/cross_cutting_layers/factor_snapshot_pinned_at_approval
    """
    site = make_site()
    factor_v1 = make_factor(value_tco2e_per_unit=0.5)
    cycle = make_collecting_cycle()
    record = submit_record(cycle["id"], site["id"], factor_v1["id"], quantity=100)
    review_record(record["id"])
    approved = approve_record(record["id"])
    assert approved["factor_value_snapshot"] == pytest.approx(0.5, abs=1e-9)

    # Retire the 0.5 factor and publish a 0.9 replacement for the same
    # key/window: the approved record's pinned snapshot must be unaffected.
    validate_success(
        api.transition_emission_factor(factor_v1["id"], transition_payload("RETIRED"), MANAGER)
    )
    make_factor(value_tco2e_per_unit=0.9, library_version=2)

    inventory = recalc_inventory(cycle["id"])
    assert inventory["scope1_tco2e"] == pytest.approx(50.0, abs=0.005), (
        "recalc must use the pinned 0.5 snapshot, not the live 0.9 factor"
    )


# ---------------------------------------------------------------------------
# Conservation pairs (difficulty: compensating_invariant)
# ---------------------------------------------------------------------------

def test_record_approve_void_restores_approved_totals(api, manager_headers):
    """PRD §3.3: "A `SustainabilityManager` may later void an approved record
    — `APPROVED` to the terminal `VOIDED` — which is the compensating
    reversal of approval: the record leaves the approved set, the same
    three-link cascade fires, `readiness_pct` is recomputed, and again both
    versions advance." PRD §3.7: "Only `APPROVED` records feed these totals;
    `SUBMITTED`, `UNDER_REVIEW`, `REJECTED`, and `VOIDED` records are
    excluded."

    Design: Difficulty/compensating_invariant/record_approve_void_conserves_approved_totals
    """
    site = make_site()
    factor = make_factor(value_tco2e_per_unit=1.0)
    cycle = make_collecting_cycle()
    first = create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=10,
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    assert recalc_inventory(cycle["id"])["total_tco2e"] == pytest.approx(10.0, abs=0.005)

    second = create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=5,
        period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
    )
    voided = validate_success(
        api.transition_activity_record(second["id"], transition_payload("VOIDED"), MANAGER)
    )
    assert voided["status"] == "VOIDED"

    inventory = recalc_inventory(cycle["id"])
    assert inventory["total_tco2e"] == pytest.approx(10.0, abs=0.005), (
        "approve-then-void restores the approved total exactly — no drift"
    )
    approved_rows, meta = validate_paginated(
        api.list_activity_records(
            MANAGER, params={"cycle_id": cycle["id"], "status": "APPROVED"}
        )
    )
    assert meta["total_count"] == 1 and len(approved_rows) == 1
    assert approved_rows[0]["id"] == first["id"], (
        "the VOIDED record is excluded from the approved set"
    )


def test_record_approve_void_mid_state_and_version_advance(api, manager_headers):
    """PRD §3.3: "A `SustainabilityManager` may later void an approved record
    — `APPROVED` to the terminal `VOIDED` — which is the compensating
    reversal of approval: the record leaves the approved set, the same
    three-link cascade fires, `readiness_pct` is recomputed, and again both
    versions advance." PRD §2.4: "The `version` is a system-managed integer
    that increments by exactly one on every mutation of the resource — every
    state transition counts as a mutation — and where a workflow also
    advances the parent cycle's `version`, §3 says so explicitly."

    Design: Difficulty/compensating_invariant/record_approve_void_conserves_approved_totals
    """
    site = make_site()
    factor = make_factor(value_tco2e_per_unit=1.0)
    cycle = make_collecting_cycle()
    create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=10,
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    cycle_version_before = cycle_version(cycle["id"])
    second = create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=5,
        period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
    )
    assert recalc_inventory(cycle["id"])["total_tco2e"] == pytest.approx(15.0, abs=0.005), (
        "the mid-state includes the newly approved record (10 + 5)"
    )

    voided = validate_success(
        api.transition_activity_record(second["id"], transition_payload("VOIDED"), MANAGER)
    )
    assert voided["status"] == "VOIDED"
    assert cycle_version(cycle["id"]) > cycle_version_before, (
        "approval and voiding each advance the parent cycle's version"
    )
    assert recalc_inventory(cycle["id"])["total_tco2e"] == pytest.approx(10.0, abs=0.005)


# ---------------------------------------------------------------------------
# Inventory list filter (corner: computed_read)
# ---------------------------------------------------------------------------

def test_inventory_results_filter_by_cycle(api, manager_headers):
    """PRD §3.7: "Inventory results can be read individually or listed, with
    the list optionally filtered by `cycle_id`." PRD §3.2: "Creation also
    materializes the cycle's singleton Inventory Result — exactly one per
    cycle, created with the cycle".

    Design: Corner/endpoints/inventory_results_filter_by_cycle
    """
    cycle_a = make_collecting_cycle(name="FY2025", reporting_year=2025)
    recalc_inventory(cycle_a["id"])
    cycle_b = make_collecting_cycle(name="FY2026", reporting_year=2026)
    recalc_inventory(cycle_b["id"])

    rows, meta = validate_paginated(
        api.list_inventory_results(manager_headers, params={"cycle_id": cycle_a["id"]})
    )
    assert meta["total_count"] == 1 and len(rows) == 1, (
        "the filtered list returns exactly the singleton result of the requested cycle"
    )
    assert rows[0]["cycle_id"] == cycle_a["id"]
    assert rows[0]["status"] == "CURRENT"
