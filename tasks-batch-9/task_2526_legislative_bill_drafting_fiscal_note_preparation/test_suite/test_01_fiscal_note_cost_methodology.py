"""Fiscal note cost totals: the two methodologies and the contingency tier order."""

from test_helpers import (
    assert_fiscal_note_request,
    assert_note_total_invariants,
    append_cost_estimates,
    route_fiscal_note,
    setup_introduced_bill,
    setup_world,
    submit_note,
)

# Two BASELINE rows filed byte-identically on both notes. The second row sits
# below the half-FTE floor, which is the only difference the methodologies see.
IDENTICAL_LINES = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 14_000_000,
        "operating_cost_cents": 4_100_000,
        "one_time_cost_cents": 3_000_000,
        "fte_count": 1.0,
        "revenue_impact_cents": 3_333_333,
        "assumption_note": "Two new inspectors, full year.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 10_400_000,
        "operating_cost_cents": 3_500_000,
        "one_time_cost_cents": 0,
        "fte_count": 0.4,
        "revenue_impact_cents": 1_000_000,
        "assumption_note": "Residual part-time support absorbed by existing staff.",
    },
]


def _revenue_world():
    """A convened session with the revenue agency and roomy drafting capacity."""
    return setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
        drafter_overrides={"max_concurrent_engagements": 4},
        counsel_overrides={"max_concurrent_engagements": 4},
    )


def _submitted_note(world, methodology, subject, start_utc, end_utc, lines=None):
    """Introduce an appropriating bill, route its note and submit the given lines."""
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=9,
        requested_sections_count=6,
        target_code_chapter="Title 12",
        subject=subject,
        summary=f"{subject}.",
        appropriation_requested_cents=12_000_000,
        engagement_start_utc=start_utc,
        engagement_end_utc=end_utc,
    )
    note = route_fiscal_note(world, bill, methodology=methodology)
    append_cost_estimates(world, note, lines or IDENTICAL_LINES)
    return bill, submit_note(world, note)


def test_incremental_cost_excludes_the_sub_half_fte_personnel_line():
    """PRD: "A line whose `fte_count` is below 0.5 contributes its operating and
    one-time costs but not a cent of personnel cost." and "the incremental
    subtotal of 24,600,000 draws the 0.08 rate for a contingency of 1,968,000
    and a `certified_total_cents` of 26,568,000".

    Design: Difficulty/dual_variant_calc/fiscal_note_incremental_cost_vs_full_absorption_diverge_on_identical_lines
    """
    world = _revenue_world()
    _bill, note = _submitted_note(
        world,
        "INCREMENTAL_COST",
        "Transit capital funding",
        "2026-09-02T00:00:00Z",
        "2026-09-05T00:00:00Z",
    )

    assert_fiscal_note_request(note)
    assert note["methodology"] == "INCREMENTAL_COST"
    assert note["status"] == "SUBMITTED"
    # 4,100,000 + 3,000,000 + 14,000,000 from the full-FTE row, then only
    # 3,500,000 of operating cost from the 0.4-FTE row, and no overhead at all.
    assert note["direct_cost_cents"] == 24_600_000
    assert float(note["contingency_pct"]) == 0.08
    assert note["contingency_cents"] == 1_968_000
    assert note["certified_total_cents"] == 26_568_000
    assert note["late_submission"] is False
    assert_note_total_invariants(note)


def test_full_absorption_prices_the_identical_rows_16107120_cents_higher():
    """PRD: "Under `FULL_ABSORPTION` the agency must show fully loaded cost." and
    "take the sum of `personnel_cost_cents` over the same lines, multiply by
    0.185, round half up to whole cents once, and add that single figure to the
    subtotal." and "the full-absorption subtotal of 39,514,000 draws the same
    rate for a contingency of 3,161,120 and a `certified_total_cents` of
    42,675,120".

    Design: Difficulty/dual_variant_calc/fiscal_note_incremental_cost_vs_full_absorption_diverge_on_identical_lines
    """
    world = _revenue_world()
    _bill_a, note_a = _submitted_note(
        world,
        "INCREMENTAL_COST",
        "Transit capital funding",
        "2026-09-02T00:00:00Z",
        "2026-09-05T00:00:00Z",
    )
    _bill_b, note_b = _submitted_note(
        world,
        "FULL_ABSORPTION",
        "Transit operating funding",
        "2026-09-06T00:00:00Z",
        "2026-09-09T00:00:00Z",
    )

    assert note_b["methodology"] == "FULL_ABSORPTION"
    # 24,400,000 of personnel cost carries an indirect overhead of 4,514,000.
    assert note_b["direct_cost_cents"] == 39_514_000
    assert float(note_b["contingency_pct"]) == 0.08
    assert note_b["contingency_cents"] == 3_161_120
    assert note_b["certified_total_cents"] == 42_675_120
    assert note_b["status"] == "SUBMITTED"
    assert note_b["late_submission"] is False
    # The very same rows, priced apart only by the methodology on the note.
    assert note_b["certified_total_cents"] - note_a["certified_total_cents"] == 16_107_120
    assert_note_total_invariants(note_b)


def test_indirect_overhead_folds_into_the_direct_subtotal_before_the_tier_is_selected():
    """PRD: "First the tier is selected **from the direct subtotal, never from
    the running certified total**: `contingency_pct` is 0.05 when
    `direct_cost_cents` is at most 10,000,000 cents, 0.08 when it is at most
    100,000,000 cents, and 0.12 for anything larger — both boundaries inclusive
    on the lower band, so a direct subtotal of exactly 10,000,000 takes the 0.05
    rate."

    Design: Difficulty/combinatorial_formula/contingency_tier_selected_after_indirect_overhead_folds_into_direct_subtotal
    """
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Corrections",
            "agency_code": "DOC",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Reentry services expansion",
        summary="Expand reentry case management.",
        target_code_chapter="Title 17",
        appropriation_requested_cents=9_000_000,
    )
    note = route_fiscal_note(world, bill, methodology="FULL_ABSORPTION")
    append_cost_estimates(
        world,
        note,
        [
            {
                "fiscal_year": 2027,
                "scenario": "BASELINE",
                "personnel_cost_cents": 5_000_000,
                "operating_cost_cents": 1_000_000,
                "one_time_cost_cents": 0,
                "fte_count": 1.0,
                "revenue_impact_cents": 0,
                "assumption_note": "One case manager.",
            },
            {
                "fiscal_year": 2028,
                "scenario": "BASELINE",
                "personnel_cost_cents": 3_000_000,
                "operating_cost_cents": 1_000_000,
                "one_time_cost_cents": 0,
                "fte_count": 1.0,
                "revenue_impact_cents": 0,
                "assumption_note": "Same case manager, partial year.",
            },
        ],
    )
    submitted = submit_note(world, note)

    # The rows themselves sum to exactly 10,000,000, which would take the 0.05
    # rate; the 1,480,000 overhead lands the subtotal in the 0.08 band instead.
    assert submitted["direct_cost_cents"] == 11_480_000
    assert float(submitted["contingency_pct"]) == 0.08
    assert submitted["contingency_cents"] == 918_400
    assert submitted["certified_total_cents"] == 12_398_400
    assert submitted["status"] == "SUBMITTED"
    assert_note_total_invariants(submitted)


def test_certified_total_is_not_the_low_boundary_answer_of_10500000():
    """PRD: "At the low boundary, a direct subtotal of exactly 10,000,000 yields
    a contingency of 500,000 and a certified total of 10,500,000." and "Every
    submission also recomputes three four-year revenue projections."

    Design: Difficulty/combinatorial_formula/contingency_tier_selected_after_indirect_overhead_folds_into_direct_subtotal
    """
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Corrections",
            "agency_code": "DOC",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Reentry services expansion",
        summary="Expand reentry case management.",
        target_code_chapter="Title 17",
        appropriation_requested_cents=9_000_000,
    )
    note = route_fiscal_note(world, bill, methodology="FULL_ABSORPTION")
    append_cost_estimates(
        world,
        note,
        [
            {
                "fiscal_year": 2027,
                "scenario": "BASELINE",
                "personnel_cost_cents": 5_000_000,
                "operating_cost_cents": 1_000_000,
                "one_time_cost_cents": 0,
                "fte_count": 1.0,
                "revenue_impact_cents": 0,
                "assumption_note": "One case manager.",
            },
            {
                "fiscal_year": 2028,
                "scenario": "BASELINE",
                "personnel_cost_cents": 3_000_000,
                "operating_cost_cents": 1_000_000,
                "one_time_cost_cents": 0,
                "fte_count": 1.0,
                "revenue_impact_cents": 0,
                "assumption_note": "Same case manager, partial year.",
            },
        ],
    )
    submitted = submit_note(world, note)

    # Selecting the tier before the overhead folded in would have produced the
    # low-boundary answer of 10,500,000 cents.
    assert submitted["certified_total_cents"] != 10_500_000
    assert submitted["certified_total_cents"] == 12_398_400
    assert float(submitted["contingency_pct"]) != 0.05
    # Every row reports no revenue impact, so the baseline projection is zero.
    assert submitted["projected_revenue_total_cents"] == 0
