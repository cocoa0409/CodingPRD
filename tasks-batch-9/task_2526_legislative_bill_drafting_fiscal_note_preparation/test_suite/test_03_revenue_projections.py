"""Revenue is projected off the base year, rounding each year before summing."""

from test_helpers import (
    append_cost_estimates,
    assert_note_total_invariants,
    route_fiscal_note,
    setup_introduced_bill,
    setup_world,
    submit_note,
)

# The base-year row seeds the curve; the out-year row is kept for the record.
REVENUE_LINES = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 14_000_000,
        "operating_cost_cents": 4_100_000,
        "one_time_cost_cents": 3_000_000,
        "fte_count": 1.0,
        "revenue_impact_cents": 3_333_333,
        "assumption_note": "Base-year net revenue gain.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 10_400_000,
        "operating_cost_cents": 3_500_000,
        "one_time_cost_cents": 0,
        "fte_count": 0.4,
        "revenue_impact_cents": 1_000_000,
        "assumption_note": "Out-year figure, not used to seed the curve.",
    },
]


def _submitted_revenue_note():
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=4,
        requested_sections_count=4,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=12_000_000,
    )
    note = route_fiscal_note(world, bill, methodology="INCREMENTAL_COST")
    append_cost_estimates(world, note, REVENUE_LINES)
    return submit_note(world, note)


def test_baseline_projection_rounds_each_fiscal_year_before_summing():
    """PRD: "From a seed the projection runs over four fiscal years at an annual
    growth rate of 0.0325." and "**The rounding order is pinned: round each
    fiscal year to whole cents first, then sum the four rounded years.**" and
    "As an illustration, a baseline base-year `revenue_impact_cents` of
    3,333,333 yields per-year figures of 3,333,333, 3,441,666, 3,553,520 and
    3,669,010 for a `projected_revenue_total_cents` of 13,997,529 — where
    rounding the exact sum once instead would have produced 13,997,530."

    Design: Difficulty/combinatorial_formula/revenue_projection_rounds_each_fiscal_year_before_summing
    """
    note = _submitted_revenue_note()

    assert note["status"] == "SUBMITTED"
    assert note["projected_revenue_total_cents"] == 13_997_529
    # Summing exact rationals and rounding once at the end is the wrong answer.
    assert note["projected_revenue_total_cents"] != 13_997_530
    assert_note_total_invariants(note)


def test_missing_scenario_lines_seed_from_the_baseline_and_out_year_revenue_never_enters():
    """PRD: "If no such line exists for `HIGH`, the seed is the `BASELINE` seed
    multiplied by 1.15 and rounded half up; if none exists for `LOW`, the seed
    is the `BASELINE` seed multiplied by 0.85 and rounded half up." and
    "Later-year lines carry their own `revenue_impact_cents` for the record but
    never enter the projection, which is a growth curve off the base year rather
    than a sum of supplied years." and "With no `HIGH` line supplied, the high seed
    is 3,833,333 and the per-year figures 3,833,333, 3,957,916, 4,086,549 and
    4,219,361 total 16,097,159."

    Design: Difficulty/combinatorial_formula/revenue_projection_rounds_each_fiscal_year_before_summing
    """
    note = _submitted_revenue_note()

    assert note["high_scenario_total_cents"] == 16_097_159
    # Seed 2,833,333 from the 0.85 fallback, then the same pinned rounding.
    assert note["low_scenario_total_cents"] == 11_897_899
    totals = (
        note["projected_revenue_total_cents"],
        note["high_scenario_total_cents"],
        note["low_scenario_total_cents"],
    )
    # The FY2028 revenue figure of 1,000,000 is nowhere in the growth curve.
    assert 1_000_000 not in totals
    assert all(total > 1_000_000 for total in totals)
