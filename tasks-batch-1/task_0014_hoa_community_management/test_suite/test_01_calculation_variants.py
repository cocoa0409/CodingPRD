"""Dual-variant and combinatorial-formula tests on late-fee accrual and
reserve-obligation calculations (PRD §3.3 and §3.8).

Each pair of tests below exercises one design-index instance from queue (A).
"""
from test_helpers import (
    DEFAULT_RESERVE_INFLATION_BPS,
    bootstrap_assessment_overdue_by_clock,
    create_community,
    create_reserve_component,
    create_reserve_study,
    get_assessment,
    validate_success,
)
from test_helpers.test_users import make_treasurer_headers


# ─────────────────────────────────────────────────────────────────────────────
# Rule 1 instance 1: late_fee chronological vs forward-looking on same Assessment
# ─────────────────────────────────────────────────────────────────────────────

def test_chronological_late_fee_accrued_per_cycle_floor_then_sum(api):
    """PRD §3.3: "For each cycle, the system adds the flat per-cycle charge
    `late_fee_flat_cents` and adds the percentage component computed as
    `principal_cents` multiplied by `late_fee_pct_bps`, divided by 10000,
    rounded down to whole cents per cycle before summing."
    PRD §3.3: "The nesting of the rounding matters: per-cycle floors are
    summed, never the other way around — summing exact fractional cents
    first and flooring once at the end would produce a different total."

    Setup: principal 30000, default knobs (grace=15, flat=2500, pct_bps=1000).
    Clock advanced to 2026-02-01: elapsed_days=31, cycles=2.
    Per cycle: 2500 + floor(30000*1000/10000) = 2500 + 3000 = 5500.
    Total: 2 * 5500 = 11000.

    Design: Difficulty/dual_variant_calc/late_fee_chronological_vs_forward_looking_on_same_assessment
    """
    _community, _owner, _prop, assessment = bootstrap_assessment_overdue_by_clock(
        community_name="Pinegrove",
        owner_email="a@x.com",
        owner_name="A",
        unit_label="U-1",
        principal_cents=30000,
        due_date="2026-01-01T00:00:00Z",
        advance_to="2026-02-01T00:00:00Z",
    )
    a = get_assessment(assessment["id"])
    assert a["late_fee_cents"] == 11000, (
        f"chronological per-cycle late fee must be 11000, got {a['late_fee_cents']}"
    )
    assert a["status"] == "OVERDUE", f"expected OVERDUE, got {a['status']}"


def test_projected_balance_forward_looking_variant_diverges_from_chronological(api):
    """PRD §3.3: "The projection variant rounds up to a whole number the
    count of cycles inclusive of the partial cycle the caller asked about
    (so a date partway through a grace cycle is treated as having entered
    the next cycle) and applies the final floor only at the very end of
    the projection rather than per cycle."
    PRD §3.3: "The two variants therefore produce different numbers for the
    same inputs on dates that fall mid-cycle, which is intentional: the
    chronological variant is the ledger of record, the forward-looking
    variant is an estimate."

    Setup: same Assessment as the chronological test, projected at 2026-02-01.
    The projection counts cycles via ceil((02-01 − 01-01)/15) = ceil(31/15) = 3
    cycles, total = 3 * (2500 + 30000*1000/10000) = 3 * 5500 = 16500.
    The chronological ledger shows 11000 — the 5500-cent delta is the
    intentional variant divergence on the same Assessment.

    Design: Difficulty/dual_variant_calc/late_fee_chronological_vs_forward_looking_on_same_assessment
    """
    _community, owner, _prop, assessment = bootstrap_assessment_overdue_by_clock(
        community_name="Pinegrove",
        owner_email="a@x.com",
        owner_name="A",
        unit_label="U-1",
        principal_cents=30000,
        due_date="2026-01-01T00:00:00Z",
        advance_to="2026-02-01T00:00:00Z",
    )
    a = get_assessment(assessment["id"])
    resp = api.get_projected_balance(
        assessment["id"], "2026-02-01T00:00:00Z", make_treasurer_headers(),
    )
    data = validate_success(resp, expected_status=200)
    assert data["projected_late_fee_cents"] == 16500, (
        f"forward-looking projected late fee must be 16500, "
        f"got {data['projected_late_fee_cents']}"
    )
    assert data["projected_late_fee_cents"] != a["late_fee_cents"], (
        "PRD §3.3 requires the two variants to produce different numbers"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 1 instance 2: reserve_obligation COMPONENT vs CASH_FLOW on same Community
# ─────────────────────────────────────────────────────────────────────────────

def test_reserve_obligation_component_method_inflated_per_component(api):
    """PRD §3.8: "Under the `COMPONENT` method, the system iterates every
    `ReserveComponent` for the community. For each component, it computes
    the inflation factor as one plus `reserve_inflation_bps` divided by
    10000, then raised to the power of the component's `remaining_life_years`.
    The per-component inflated cost is `replacement_cost_cents` multiplied
    by that factor and rounded down to whole cents at this per-component
    stage. The per-component inflated costs are summed to give
    `projected_obligation_cents`."

    Setup: One ReserveComponent (cost=1000000, remaining=2, useful=10) under
    a Community with default reserve_inflation_bps=300.
    COMPONENT: floor(1000000 * 1.03^2) = floor(1060900.0) = 1060900.
    accumulated_funds=2000000 → percent_funded_bps =
      floor(2000000 * 10000 / 1060900) = floor(18851.918…) = 18851.

    Design: Difficulty/dual_variant_calc/reserve_obligation_component_vs_cash_flow_on_same_community
    """
    community = create_community(name="Pinegrove")
    create_reserve_component(
        community["id"], label="Roof", useful_life_years=10,
        remaining_life_years=2, replacement_cost_cents=1000000,
    )
    study = create_reserve_study(
        community["id"], fiscal_year=2026, method="COMPONENT",
        accumulated_funds_cents=2000000,
    )
    assert study["projected_obligation_cents"] == 1060900, (
        f"COMPONENT obligation must be 1060900, "
        f"got {study['projected_obligation_cents']}"
    )
    assert study["percent_funded_bps"] == 18851, (
        f"COMPONENT percent_funded_bps must be 18851, "
        f"got {study['percent_funded_bps']}"
    )
    # Reference: default community has reserve_inflation_bps=300.
    assert DEFAULT_RESERVE_INFLATION_BPS == 300


def test_reserve_obligation_cash_flow_method_thirty_year_horizon(api):
    """PRD §3.8: "Under the `CASH_FLOW` method, the system rolls the
    replacement schedule forward over a fixed 30-year horizon: for each
    component, it places a draw in the year given by `remaining_life_years`,
    then again every `useful_life_years` after that for as long as the year
    index remains strictly less than 30, with each draw equal to
    `replacement_cost_cents` multiplied by the same inflation factor
    evaluated at that draw's year. All draws across all components are
    summed, and the final sum is rounded down to whole cents only at the
    very end."

    Setup: Same single ReserveComponent (cost=1000000, remaining=2, useful=10)
    under a Community with reserve_inflation_bps=300.
    Draws at years 2, 12, 22 (years 32 would be ≥30, excluded):
      year 2: 1000000 * 1.03^2  = 1060900.0
      year 12: 1000000 * 1.03^12 = 1425760.886848…
      year 22: 1000000 * 1.03^22 = 1916103.426 …
      sum  ≈ 4402764.31… → floor = 4402764.
    accumulated_funds=2000000 → percent_funded_bps =
      floor(2000000*10000 / 4402764) = floor(4542.79…) = 4542.

    Design: Difficulty/dual_variant_calc/reserve_obligation_component_vs_cash_flow_on_same_community
    """
    community = create_community(name="Pinegrove")
    create_reserve_component(
        community["id"], label="Roof", useful_life_years=10,
        remaining_life_years=2, replacement_cost_cents=1000000,
    )
    # First study (COMPONENT for fiscal_year 2026) — created so the divergence
    # is observable on the SAME community as PRD §3.8 requires.
    component_study = create_reserve_study(
        community["id"], fiscal_year=2026, method="COMPONENT",
        accumulated_funds_cents=2000000,
    )
    cash_study = create_reserve_study(
        community["id"], fiscal_year=2027, method="CASH_FLOW",
        accumulated_funds_cents=2000000,
    )
    assert cash_study["projected_obligation_cents"] == 4402764, (
        f"CASH_FLOW obligation must be 4402764, "
        f"got {cash_study['projected_obligation_cents']}"
    )
    assert cash_study["percent_funded_bps"] == 4542, (
        f"CASH_FLOW percent_funded_bps must be 4542, "
        f"got {cash_study['percent_funded_bps']}"
    )
    assert component_study["projected_obligation_cents"] != \
        cash_study["projected_obligation_cents"], (
        "PRD §3.8 requires the two methods to produce different numbers from "
        "the same components"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2 instance 1: reserve_obligation COMPONENT formula — three-input
# non-linear interaction across multiple components.
# ─────────────────────────────────────────────────────────────────────────────

def test_reserve_obligation_component_method_three_components_summed(api):
    """PRD §3.8: "Under the `COMPONENT` method, the system iterates every
    `ReserveComponent` for the community. For each component, it computes
    the inflation factor as one plus `reserve_inflation_bps` divided by
    10000, then raised to the power of the component's `remaining_life_years`.
    The per-component inflated cost is `replacement_cost_cents` multiplied
    by that factor and rounded down to whole cents at this per-component
    stage. The per-component inflated costs are summed to give
    `projected_obligation_cents`."

    Setup: three components share the community (cost=500000 remaining=3),
    (cost=200000 remaining=7), (cost=800000 remaining=0); inflation 300 bps.
      C1: floor(500000 * 1.03^3) = floor(546363.5) = 546363
      C2: floor(200000 * 1.03^7) = floor(245974.7…) = 245974
      C3: floor(800000 * 1.03^0) = 800000
      sum = 1592337.

    Design: Difficulty/combinatorial_formula/reserve_obligation_three_input_non_linear_component_method
    """
    community = create_community(name="MultiComp")
    create_reserve_component(
        community["id"], label="C1", useful_life_years=20,
        remaining_life_years=3, replacement_cost_cents=500000,
    )
    create_reserve_component(
        community["id"], label="C2", useful_life_years=20,
        remaining_life_years=7, replacement_cost_cents=200000,
    )
    create_reserve_component(
        community["id"], label="C3", useful_life_years=20,
        remaining_life_years=0, replacement_cost_cents=800000,
    )
    study = create_reserve_study(
        community["id"], fiscal_year=2026, method="COMPONENT",
        accumulated_funds_cents=1_000_000,
    )
    assert study["projected_obligation_cents"] == 1592337, (
        f"three-component COMPONENT obligation must be 1592337, "
        f"got {study['projected_obligation_cents']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2 instance 2: late-fee nested rounding — per-cycle floor then sum
# ─────────────────────────────────────────────────────────────────────────────

def test_late_fee_nested_rounding_per_cycle_floor_with_fractional_pct(api):
    """PRD §3.3: "For each cycle, the system adds the flat per-cycle charge
    `late_fee_flat_cents` and adds the percentage component computed as
    `principal_cents` multiplied by `late_fee_pct_bps`, divided by 10000,
    rounded down to whole cents per cycle before summing."
    PRD §3.3: "The nesting of the rounding matters: per-cycle floors are
    summed, never the other way around — summing exact fractional cents
    first and flooring once at the end would produce a different total."

    Setup: principal 33333, default knobs. Clock at 2026-02-01 → cycles=2.
    Per cycle: 2500 + floor(33333*1000/10000) = 2500 + floor(3333.3) = 2500 + 3333 = 5833.
    Total: 2 * 5833 = 11666.

    Design: Difficulty/combinatorial_formula/late_fee_nested_rounding_per_cycle_floor_then_sum
    """
    _community, _owner, _prop, assessment = bootstrap_assessment_overdue_by_clock(
        community_name="RoundTown",
        owner_email="b@x.com",
        owner_name="B",
        unit_label="U-2",
        principal_cents=33333,
        due_date="2026-01-01T00:00:00Z",
        advance_to="2026-02-01T00:00:00Z",
        regular_assessment_cents=33333,
    )
    a = get_assessment(assessment["id"])
    assert a["late_fee_cents"] == 11666, (
        f"per-cycle-floor late fee must be 11666 (2 * floor(3333.3)+2*2500), "
        f"got {a['late_fee_cents']}"
    )
    assert a["status"] == "OVERDUE", f"expected OVERDUE, got {a['status']}"
