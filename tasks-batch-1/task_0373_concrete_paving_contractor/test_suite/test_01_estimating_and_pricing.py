"""Estimating: cubic-yard volume variants, tiered/finish/reinforcement pricing,
and the tier boundary. Covers the two cubic-yard math variants (§3.1) and the
estimate_total formula (§3.2).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_project_payload, create_segment_payload, create_estimate_payload,
    approve_estimate_payload,
    create_estimating_project, create_approved_project,
    create_project, add_segment, create_estimate, project_version,
    place_material_order, assert_estimate,
    TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["project_manager_headers"]

FIVE_150_SEGMENTS = [dict(label=f"s{i}", area_sqft=150, thickness_in=4) for i in range(1, 6)]
COMBO_840 = [
    dict(label="driveway", area_sqft=600, thickness_in=4, finish_grade="BROOM", reinforcement="REBAR"),
    dict(label="patio", area_sqft=240, thickness_in=5, finish_grade="STAMPED", reinforcement="REBAR"),
]


class TestCubicYardVariants:
    """The planning (sum-then-ceil) and ordering (per-segment ceil-to-quarter
    then sum then ceil) variants diverge on identical segments."""

    def test_provisional_cubic_yards_sum_then_ceil_is_11(self, api):
        """PRD §3.1: "The planning figure, provisional_cubic_yards, sums the
        waste-adjusted volumes of all the project's segments first and only then
        rounds the grand total up to the next whole cubic yard."

        Design: Difficulty/dual_variant_calc/cubic_yards_provisional_vs_material_order_variant
        """
        proj, est = create_estimating_project(segments=FIVE_150_SEGMENTS, site_name="Lot 5")
        assert est["provisional_cubic_yards"] == 11

    def test_order_cubic_yards_per_segment_ceil_is_12(self, api):
        """PRD §3.1: "The ordering figure, order_cubic_yards, instead rounds each
        segment's waste-adjusted volume up to the next quarter-yard ticket
        increment first - multiply the segment's adjusted volume by 4, round that
        up to the next whole number, and divide by 4 - then sums those per-segment
        ticket quantities and rounds the sum up to the next whole cubic yard."
        PRD §3.5: "At placement the system snapshots order_cubic_yards using the
        ordering variant of §3.1"

        Design: Difficulty/dual_variant_calc/cubic_yards_provisional_vs_material_order_variant
        """
        proj, est = create_approved_project(segments=FIVE_150_SEGMENTS, site_name="Lot 5")
        mo = place_material_order(proj["id"])
        assert mo["order_cubic_yards"] == 12

    def test_order_variant_strictly_exceeds_planning_variant(self, api):
        """PRD §3.1: "Because the rounding happens per line item before summing,
        the ordering figure can come out strictly larger than the planning figure
        on the very same segments; this reflects supplier truck-ticket reality,
        where each delivery is billed in quarter-yard increments."

        Design: Difficulty/dual_variant_calc/cubic_yards_provisional_vs_material_order_variant
        """
        proj, est = create_approved_project(segments=FIVE_150_SEGMENTS, site_name="Lot 5")
        mo = place_material_order(proj["id"])
        assert mo["order_cubic_yards"] == 12
        assert est["provisional_cubic_yards"] == 11
        assert mo["order_cubic_yards"] > est["provisional_cubic_yards"]

    def test_rounding_order_mode_b_prov_11_order_12(self, api):
        """PRD §3.1: "The planning figure, provisional_cubic_yards, sums the
        waste-adjusted volumes of all the project's segments first and only then
        rounds the grand total up to the next whole cubic yard."
        PRD §3.1: "The ordering figure, order_cubic_yards, instead rounds each
        segment's waste-adjusted volume up to the next quarter-yard ticket
        increment first - multiply the segment's adjusted volume by 4, round that
        up to the next whole number, and divide by 4 - then sums those per-segment
        ticket quantities and rounds the sum up to the next whole cubic yard."

        Design: Difficulty/combinatorial_formula/cubic_yards_rounding_order_mode_b
        """
        proj, est = create_approved_project(segments=FIVE_150_SEGMENTS, site_name="Round B")
        mo = place_material_order(proj["id"])
        assert est["provisional_cubic_yards"] == 11
        assert mo["order_cubic_yards"] == 12

    def test_per_line_item_rounding_yields_larger_order_total(self, api):
        """PRD §3.1: "Because the rounding happens per line item before summing,
        the ordering figure can come out strictly larger than the planning figure
        on the very same segments; this reflects supplier truck-ticket reality,
        where each delivery is billed in quarter-yard increments."

        Design: Difficulty/combinatorial_formula/cubic_yards_rounding_order_mode_b
        """
        proj, est = create_approved_project(segments=FIVE_150_SEGMENTS, site_name="Round B2")
        mo = place_material_order(proj["id"])
        # The per-segment-ceil-quarter rounding order makes the order total strictly
        # larger than the planning sum-then-ceil total on identical segments.
        assert mo["order_cubic_yards"] > est["provisional_cubic_yards"]


class TestEstimateTotalFormula:
    """Tiered marginal labor + finish multiplier + reinforcement add."""

    def test_combo_840_labor_material_total(self, api):
        """PRD §3.2: "The labor_subtotal is the scaled labor base plus the
        reinforcement add, rounded to two decimal places."
        PRD §3.2: "The material_subtotal is the estimate's provisional_cubic_yards
        multiplied by the mix rate of 145.00 per cubic yard, rounded to two
        decimal places."
        PRD §3.2: "The estimate_total is then the rounded labor_subtotal added to
        the rounded material_subtotal."

        Design: Difficulty/combinatorial_formula/estimate_total_tiered_finish_reinforcement_mode_a
        """
        proj, est = create_estimating_project(segments=COMBO_840, site_name="Combo A")
        assert est["labor_subtotal"] == 10567.50
        assert est["material_subtotal"] == 1885.00
        assert est["estimate_total"] == 12452.50

    def test_finish_multiplier_is_max_over_segments(self, api):
        """PRD §3.2: "That labor base is then scaled by a single finish
        multiplier, taken as the maximum finish multiplier across all the
        project's segments, where a BROOM finish multiplies by 1.00,
        EXPOSED_AGGREGATE by 1.20, and STAMPED by 1.35."
        PRD §3.2: "On top of the scaled labor, a reinforcement add is applied as
        the sum over every segment of that segment's per-square-foot reinforcement
        rate times its area_sqft, where NONE adds 0.00 per square foot, MESH adds
        0.60, and REBAR adds 1.25."

        Design: Difficulty/combinatorial_formula/estimate_total_tiered_finish_reinforcement_mode_a
        """
        proj, est = create_estimating_project(segments=COMBO_840, site_name="Combo A2")
        # STAMPED (1.35) dominates BROOM (1.00); labor base 7050 -> *1.35 + REBAR add 1050.
        assert est["labor_subtotal"] == 10567.50
        assert est["estimate_total"] == 12452.50

    def test_exposed_aggregate_mesh_single_segment(self, api):
        """PRD §3.2: "That labor base is then scaled by a single finish
        multiplier, taken as the maximum finish multiplier across all the
        project's segments, where a BROOM finish multiplies by 1.00,
        EXPOSED_AGGREGATE by 1.20, and STAMPED by 1.35."

        Design: Corner/calculations/estimate_exposed_aggregate_finish_multiplier
        """
        proj, est = create_estimating_project(
            segments=[dict(label="s", area_sqft=400, thickness_in=4,
                           finish_grade="EXPOSED_AGGREGATE", reinforcement="MESH")],
            site_name="EA")
        assert est["labor_subtotal"] == 4560.00
        assert est["material_subtotal"] == 870.00
        assert est["estimate_total"] == 5430.00


class TestTierBoundary:
    """The marginal tier-1 ceiling is exactly 500 sqft (X-1, X, X+1)."""

    def _labor_subtotal_for(self, api, area_sqft, name):
        proj = create_project(site_name=name)
        add_segment(proj["id"], label="s", area_sqft=area_sqft, thickness_in=4)
        est = create_estimate(proj["id"])
        return est["labor_subtotal"]

    def test_at_500_sqft_all_tier1(self, api):
        """PRD §3.2: "The first 500 square feet are billed at 9.00 per square
        foot."

        Design: Difficulty/boundary_precision_check/estimate_tier_boundary_500_vs_501_sqft
        """
        assert self._labor_subtotal_for(api, 500, "B500") == 4500.00

    def test_at_501_sqft_first_tier2_unit(self, api):
        """PRD §3.2: "Square footage above 500 and up to 1,500 - that is, the next
        1,000 square feet - is billed at 7.50 per square foot."

        Design: Difficulty/boundary_precision_check/estimate_tier_boundary_500_vs_501_sqft
        """
        # 500*9.00 + 1*7.50 == 4507.50: the 501st sqft is the first billed at tier 2.
        assert self._labor_subtotal_for(api, 501, "B501") == 4507.50

    def test_at_499_sqft_below_boundary(self, api):
        """PRD §3.2: "The first 500 square feet are billed at 9.00 per square
        foot."

        Design: Difficulty/boundary_precision_check/estimate_tier_boundary_500_vs_501_sqft
        """
        # 499 sqft, all within tier 1: 499 * 9.00 == 4491.00.
        assert self._labor_subtotal_for(api, 499, "B499") == 4491.00


def test_estimate_computed_fields_system_minted(api):
    """PRD §3.2: "The estimate is created in DRAFT status, and the system
    computes its figures in one shot."
    PRD §2.4: "Each such resource has an id - a server-minted UUID with no type
    prefix, used for identity only and never as a business-decision input."

    Design: Corner/entities/estimate_id_and_computed_fields_are_system_minted
    """
    proj = create_project(site_name="Sys")
    add_segment(proj["id"], label="s", area_sqft=400, thickness_in=4)
    res = api.create_estimate(proj["id"], create_estimate_payload(estimate_total=999.99), EST)
    est = validate_success(res, 201)
    assert_estimate(est)
    assert est["estimate_total"] == 4470.00


def test_estimate_total_returned_in_create_response(api):
    """PRD §3.2: "The estimate is created in DRAFT status, and the system
    computes its figures in one shot."

    Design: Corner/consistency_model/immediate_visibility_of_computed_fields_on_create
    """
    proj = create_project(site_name="Imm")
    add_segment(proj["id"], label="s", area_sqft=400, thickness_in=4)
    res = api.create_estimate(proj["id"], create_estimate_payload(), EST)
    est = validate_success(res, 201)
    assert est["estimate_total"] == 4470.00
