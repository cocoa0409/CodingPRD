"""Calculations: clamps, filters, tier edges, projections, counters and windows."""

from test_helpers import (
    CLERK,
    STANDARD_COST_LINES,
    add_member,
    api_client,
    append_cost_estimates,
    assert_agency_responsiveness_invariants,
    assert_drafting_request,
    assert_enrolled_bill,
    assert_instant,
    assert_note_total_invariants,
    assign_request,
    certify_draft,
    cheap_cost_lines,
    complete_research,
    create_drafting_request_payload,
    create_fiscal_note_request_payload,
    file_statutory_conflict,
    get_success_data,
    introduce_bill,
    pass_bill,
    read_agency,
    read_amendment,
    read_bill,
    read_session,
    refer_bill,
    report_referral,
    request_amendment,
    return_note,
    route_fiscal_note,
    set_clock,
    setup_adopted_amendment,
    setup_introduced_bill,
    setup_request_in_research,
    setup_world,
    submit_note,
    validate_success,
)

CANONICAL_CLOCK = "2026-09-01T00:00:00Z"


def test_the_sla_window_clamps_at_the_ceiling_before_the_priority_halving():
    """PRD: "A confidential priority request naming six sections and asking for
    12,000,000 cents therefore scores twenty-four for its sections, twelve for
    confidentiality, eight for priority and fifteen for the top appropriation band,
    for an `intake_complexity_estimate` of 59." and "First a base window in hours is
    computed as the complexity score multiplied by six, then clamped into the range
    from a floor of 24 hours to a ceiling of 240 hours — the clamp is applied here,
    before any multiplier." and "A score of 71 on a priority request, for instance,
    produces a base of 426 hours, clamped to the 240-hour ceiling, halved to 120
    hours by priority, left unmultiplied when the clock has not yet reached the
    pressure window, and added to the research completion instant as a flat five
    days."

    Design: Corner/calculations/sla_due_date_clamps_at_the_ceiling_then_halves_once_for_priority
    """
    world = setup_world()
    request = setup_request_in_research(
        world,
        subject="Water quality standards overhaul",
        summary="Overhaul the state water quality standards.",
        requested_sections_count=6,
        target_code_chapter="Title 25",
        confidentiality="CONFIDENTIAL",
        priority_flag=True,
        appropriation_requested_cents=12_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-20T00:00:00Z",
    )
    assert request["intake_complexity_estimate"] == 59

    for citation, severity in (
        ("25-4-101", "ADVISORY"),
        ("25-4-102", "ADVISORY"),
        ("25-4-103", "BLOCKING"),
    ):
        file_statutory_conflict(
            world,
            request,
            severity=severity,
            code_citation=citation,
            conflict_type="AMENDS_SAME_SECTION",
        )
    set_clock("2026-09-11T00:00:00Z")

    drafting = complete_research(world, request, affected_sections_count=9)

    assert_drafting_request(drafting)
    assert drafting["actual_complexity_score"] == 71
    assert_instant(drafting["research_completed_utc"], "2026-09-11T00:00:00Z")
    # 71 * 6 = 426 hours, clamped to 240, then halved to a flat five days.
    assert_instant(drafting["sla_due_utc"], "2026-09-16T00:00:00Z")
    assert drafting["status"] == "DRAFTING"
    assert drafting["revision_round"] == 0
    # The intake estimate is frozen and never rescaled by the research findings.
    assert drafting["intake_complexity_estimate"] == 59


def _priced_note(world, methodology, lines, appropriation_requested_cents=6_000_000):
    """Route a note for a fresh appropriating bill and submit the given lines."""
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Fleet electrification pilot",
        summary="Run a fleet electrification pilot.",
        target_code_chapter="Title 43",
        appropriation_requested_cents=appropriation_requested_cents,
    )
    note = route_fiscal_note(world, bill, methodology=methodology)
    append_cost_estimates(world, note, lines)
    return bill, note


def test_incremental_costing_drops_personnel_on_the_line_below_the_half_fte_floor():
    """PRD: "A line whose `fte_count` is below 0.5 contributes its operating and
    one-time costs but not a cent of personnel cost." and "Under `INCREMENTAL_COST`
    the second line's personnel cost is excluded because 0.4 is below the half-FTE
    floor, and no overhead is added, giving a `direct_cost_cents` of 24,600,000." and
    "Second, `contingency_cents` is `direct_cost_cents` multiplied by
    `contingency_pct` and rounded half up to whole cents, once."

    Design: Corner/calculations/incremental_costing_drops_personnel_on_lines_below_the_half_fte_floor
    """
    world = setup_world(with_agency=True)
    _bill, note = _priced_note(world, "INCREMENTAL_COST", STANDARD_COST_LINES)

    submitted = submit_note(
        world,
        note,
        submission_note="Incremental costing, FY2028 personnel absorbed.",
    )

    # 35,000,000 would be the answer if the 0.4-FTE personnel row counted.
    assert submitted["direct_cost_cents"] == 24_600_000
    assert submitted["direct_cost_cents"] != 35_000_000
    assert float(submitted["contingency_pct"]) == 0.08
    assert submitted["contingency_cents"] == 1_968_000
    assert submitted["certified_total_cents"] == 26_568_000
    assert submitted["status"] == "SUBMITTED"
    assert submitted["late_submission"] is False
    assert_note_total_invariants(submitted)
    # Submission alone never posts anything to the session ledger.
    assert read_session(world)["certified_fiscal_total_cents"] == 0


TEN_MILLION_LINES = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 5_000_000,
        "operating_cost_cents": 1_000_000,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2027 pilot crew.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 3_000_000,
        "operating_cost_cents": 1_000_000,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2028 pilot crew.",
    },
]


def test_the_contingency_tier_boundary_is_inclusive_at_exactly_ten_million_cents():
    """PRD: "First the tier is selected **from the direct subtotal, never from the
    running certified total**: `contingency_pct` is 0.05 when `direct_cost_cents` is
    at most 10,000,000 cents, 0.08 when it is at most 100,000,000 cents, and 0.12
    for anything larger — both boundaries inclusive on the lower band, so a direct
    subtotal of exactly 10,000,000 takes the 0.05 rate." and "At the low boundary, a
    direct subtotal of exactly 10,000,000 yields a contingency of 500,000 and a
    certified total of 10,500,000."

    Design: Corner/calculations/contingency_tier_boundary_is_inclusive_at_exactly_ten_million_direct_cents
    """
    world = setup_world(with_agency=True)
    _bill, note = _priced_note(world, "INCREMENTAL_COST", TEN_MILLION_LINES)

    submitted = submit_note(world, note)

    assert submitted["direct_cost_cents"] == 10_000_000
    assert float(submitted["contingency_pct"]) == 0.05
    # The exclusive reading of the boundary would give 800,000 and 10,800,000.
    assert submitted["contingency_cents"] == 500_000
    assert submitted["contingency_cents"] != 800_000
    assert submitted["certified_total_cents"] == 10_500_000
    assert submitted["certified_total_cents"] != 10_800_000
    assert_note_total_invariants(submitted)


REVENUE_ONLY_LINES = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 0,
        "operating_cost_cents": 0,
        "one_time_cost_cents": 0,
        "fte_count": 0.0,
        "revenue_impact_cents": 3_333_333,
        "assumption_note": "Baseline base-year revenue gain.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 0,
        "operating_cost_cents": 0,
        "one_time_cost_cents": 0,
        "fte_count": 0.0,
        "revenue_impact_cents": 900_000,
        "assumption_note": "Out-year figure kept for the record only.",
    },
    {
        "fiscal_year": 2027,
        "scenario": "LOW",
        "personnel_cost_cents": 0,
        "operating_cost_cents": 0,
        "one_time_cost_cents": 0,
        "fte_count": 0.0,
        "revenue_impact_cents": 2_000_000,
        "assumption_note": "Pessimistic base-year revenue gain, supplied outright.",
    },
]


def test_the_high_seed_is_derived_while_a_supplied_low_seed_is_used_verbatim():
    """PRD: "If the agency filed such a line, that value is used verbatim and the
    scenario multiplier is **not** applied on top of it." and "If no such line exists
    for `HIGH`, the seed is the `BASELINE` seed multiplied by 1.15 and rounded half
    up; if none exists for `LOW`, the seed is the `BASELINE` seed multiplied by 0.85
    and rounded half up." and "With no `HIGH` line supplied, the high seed is
    3,833,333 and the per-year figures 3,833,333, 3,957,916, 4,086,549 and 4,219,361
    total 16,097,159." and "With a `LOW` line supplied as 2,000,000, the multiplier
    is not applied and the per-year figures 2,000,000, 2,065,000, 2,132,113 and
    2,201,406 total 8,398,519."

    Design: Corner/calculations/derived_high_scenario_multiplies_the_base_while_a_supplied_low_row_is_used_verbatim
    """
    world = setup_world(with_agency=True)
    _bill, note = _priced_note(world, "INCREMENTAL_COST", REVENUE_ONLY_LINES)

    submitted = submit_note(world, note)

    assert submitted["projected_revenue_total_cents"] == 13_997_529
    assert submitted["high_scenario_total_cents"] == 16_097_159
    # Re-applying the 0.85 multiplier over the supplied seed would give 7,138,741.
    assert submitted["low_scenario_total_cents"] == 8_398_519
    assert submitted["low_scenario_total_cents"] != 7_138_741
    assert submitted["direct_cost_cents"] == 0
    assert float(submitted["contingency_pct"]) == 0.05
    assert submitted["certified_total_cents"] == 0
    # The FY2028 baseline revenue row never enters any of the three curves.
    assert 900_000 not in (
        submitted["projected_revenue_total_cents"],
        submitted["high_scenario_total_cents"],
        submitted["low_scenario_total_cents"],
    )


def test_the_two_chamber_counters_advance_independently_and_never_reuse_a_number():
    """PRD: "A `HOUSE` bill takes the current value of `next_house_bill_number`,
    renders `bill_number` as the two characters `HB`, a single space, and that number
    in decimal with no zero padding, and then raises `next_house_bill_number` by
    one." and "The counters never interact, so `HB 1` and `SB 1` coexist in one
    session; a counter is never decremented and never reused, so a bill that later
    goes `DEAD` does not return its number to the pool, and introduction order within
    a chamber is therefore always recoverable from `bill_number`."

    Design: Corner/calculations/bill_numbering_uses_independent_chamber_counters_and_never_reuses_a_dead_bills_number
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Judiciary",
            "is_fiscal_committee": False,
            "max_concurrent_referrals": 2,
        },
    )
    senator, senate_headers = add_member(
        world, full_name="Sen Beta", chamber="SENATE", party="IND", priority_slots_total=2
    )

    _dr1, bill_one = setup_introduced_bill(
        world,
        affected_sections_count=1,
        requested_sections_count=1,
        subject="House measure one",
        summary="First house measure.",
        target_code_chapter="Title 4",
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )

    senate_request = get_success_data(
        api_client.create_drafting_request(
            create_drafting_request_payload(
                world["session"]["id"],
                subject="Senate measure one",
                summary="First senate measure.",
                requested_sections_count=1,
                target_code_chapter="Title 4",
            ),
            senate_headers,
        )
    )
    assign_request(
        world,
        senate_request,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    complete_research(world, senate_request, affected_sections_count=1)
    certify_draft(world, senate_request)
    bill_two = introduce_bill(world, senate_request)

    _dr3, bill_three = setup_introduced_bill(
        world,
        affected_sections_count=1,
        requested_sections_count=1,
        subject="House measure two",
        summary="Second house measure.",
        target_code_chapter="Title 4",
        engagement_start_utc="2026-09-06T00:00:00Z",
        engagement_end_utc="2026-09-07T00:00:00Z",
    )

    assert bill_one["bill_number"] == "HB 1"
    assert bill_one["chamber"] == "HOUSE"
    assert bill_two["bill_number"] == "SB 1"
    assert bill_two["chamber"] == "SENATE"
    assert bill_two["sponsor_member_id"] == senator["id"]
    assert bill_three["bill_number"] == "HB 2"

    referral = refer_bill(world, bill_one)
    set_clock("2026-10-06T00:00:00Z")
    report_referral(world, referral, outcome="UNFAVORABLE")
    assert read_bill(world, bill_one["id"])["legislative_status"] == "DEAD"

    _dr4, bill_four = setup_introduced_bill(
        world,
        affected_sections_count=1,
        requested_sections_count=1,
        subject="House measure three",
        summary="Third house measure, filed after the first died.",
        target_code_chapter="Title 4",
        engagement_start_utc="2026-10-07T00:00:00Z",
        engagement_end_utc="2026-10-08T00:00:00Z",
    )

    # The dead bill's number never returns to the pool.
    assert bill_four["bill_number"] == "HB 3"
    assert bill_four["bill_number"] != "HB 1"

    session = read_session(world)
    assert session["next_house_bill_number"] == 4
    assert session["next_senate_bill_number"] == 2
    assert session["bills_introduced_count"] == 4


def test_enrollment_sequence_puts_committee_amendments_first_then_orders_by_creation():
    """PRD: "Its `enrollment_sequence` is the ordered list of those amendments'
    identifiers, sorted with all `COMMITTEE`-stage amendments before all `FLOOR`-stage
    ones — committee work engrosses first — and, within a stage, by `created_at`
    ascending." and "And `origin_signature_role` is `SPEAKER` when the bill's
    `chamber` is `HOUSE` and `SENATE_PRESIDENT` when it is `SENATE` — the presiding
    officer of the originating chamber, who must sign first — with
    `expected_next_signature` initialised to that same value." and "The new
    enrollment opens in `status` `PREPARED` with `corrections_applied_count` and
    `open_corrections_count` at 0 and `origin_signed_utc`, `second_signed_utc` and
    `transmitted_utc` all null."

    Design: Corner/calculations/enrollment_sequence_puts_committee_amendments_ahead_of_floor_amendments_then_orders_by_created_at
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Uniform bond covenants",
        summary="Standardize the state bond covenants.",
        target_code_chapter="Title 41",
        appropriation_requested_cents=0,
    )
    referral = refer_bill(
        world,
        bill,
        hearing_window_start_utc="2026-10-20T14:00:00Z",
        hearing_window_end_utc="2026-10-20T16:00:00Z",
    )
    amendment_a = setup_adopted_amendment(
        world,
        bill,
        stage="COMMITTEE",
        committee_referral_id=referral["id"],
        fiscal_impact_delta_cents=0,
        summary="Committee amendment A, filed first.",
        drafting_start_utc="2026-09-02T00:00:00Z",
        drafting_due_utc="2026-09-03T00:00:00Z",
    )
    amendment_b = setup_adopted_amendment(
        world,
        bill,
        stage="COMMITTEE",
        committee_referral_id=referral["id"],
        fiscal_impact_delta_cents=0,
        summary="Committee amendment B, filed second.",
        drafting_start_utc="2026-09-04T00:00:00Z",
        drafting_due_utc="2026-09-05T00:00:00Z",
    )
    set_clock("2026-10-21T00:00:00Z")
    report_referral(world, referral, outcome="FAVORABLE")
    assert read_bill(world, bill["id"])["legislative_status"] == "REPORTED"
    amendment_c = setup_adopted_amendment(
        world,
        bill,
        stage="FLOOR",
        fiscal_impact_delta_cents=0,
        summary="Floor amendment C, the newest row of the three.",
        drafting_start_utc="2026-10-22T00:00:00Z",
        drafting_due_utc="2026-10-23T00:00:00Z",
    )
    pass_bill(world, bill)

    response = api_client.enroll_bill(bill["id"], CLERK)

    enrollment = validate_success(response, 201)
    assert_enrolled_bill(enrollment)
    assert enrollment["status"] == "PREPARED"
    assert enrollment["adopted_amendment_count"] == 3
    assert enrollment["net_fiscal_delta_cents"] == 0
    assert enrollment["enrollment_sequence"] == [
        amendment_a["id"],
        amendment_b["id"],
        amendment_c["id"],
    ]
    # The floor amendment is the newest row yet sorts last on the stage key.
    assert enrollment["enrollment_sequence"][2] == amendment_c["id"]
    assert enrollment["origin_signature_role"] == "SPEAKER"
    assert enrollment["expected_next_signature"] == "SPEAKER"
    assert enrollment["open_corrections_count"] == 0
    assert enrollment["corrections_applied_count"] == 0
    assert enrollment["origin_signed_utc"] is None
    assert enrollment["second_signed_utc"] is None
    assert enrollment["transmitted_utc"] is None
    assert read_bill(world, bill["id"])["legislative_status"] == "ENROLLED"
    assert read_session(world)["bills_enrolled_count"] == 1


def test_a_struggling_agency_is_granted_five_extra_days_on_its_next_routing():
    """PRD: "Each agency carries a `responsiveness_score` derived from its own history
    across all of its notes in every session: start at 100, subtract twelve for each
    entry in `late_submission_count`, subtract five for each entry in
    `revision_count`, then clamp the result into the range 0 through 100 inclusive."
    and "The score selects an extension band on top of the session's
    `fiscal_note_default_days`: no extra days when the score is 70 or above; five
    extra days when the score is at least 40 but below 70; ten extra days when the
    score is below 40." and "The total grant in whole days is added to `routed_utc`
    to produce `due_utc`, preserving `routed_utc`'s time-of-day exactly."

    Design: Corner/calculations/fiscal_note_grant_extends_by_five_days_once_the_agency_drops_below_the_seventy_point_band
    """
    world = setup_world(with_agency=True)
    _request_one, bill_one = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Ferry terminal repairs",
        summary="Repair the ferry terminals.",
        target_code_chapter="Title 43",
        appropriation_requested_cents=6_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, bill_two = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Ferry fare schedule",
        summary="Restate the ferry fare schedule.",
        target_code_chapter="Title 43",
        appropriation_requested_cents=6_000_000,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    note_one = route_fiscal_note(world, bill_one)
    assert_instant(note_one["routed_utc"], CANONICAL_CLOCK)
    # A pristine agency scores 100 and gets the bare session default of 21 days.
    assert_instant(note_one["due_utc"], "2026-09-22T00:00:00Z")

    append_cost_estimates(world, note_one, cheap_cost_lines())
    set_clock("2026-09-25T00:00:00Z")
    late_first = submit_note(world, note_one)
    assert late_first["late_submission"] is True
    return_note(world, note_one)
    append_cost_estimates(world, note_one, cheap_cost_lines())
    submit_note(world, note_one)
    returned = return_note(world, note_one)

    assert returned["status"] == "RETURNED_FOR_REVISION"
    assert returned["revision_round"] == 2
    assert returned["late_submission"] is True

    agency = read_agency(world)
    assert agency["late_submission_count"] == 2
    assert agency["revision_count"] == 2
    assert agency["responsiveness_score"] == 66
    assert_agency_responsiveness_invariants(agency)

    note_two = validate_success(
        api_client.create_fiscal_note_request(
            bill_two["id"],
            create_fiscal_note_request_payload(world["agency"]["id"]),
            world["fiscal_officer_headers"],
        ),
        201,
    )

    assert_instant(note_two["routed_utc"], "2026-09-25T00:00:00Z")
    # 21 default days plus the middle band's five, preserving the time of day.
    assert_instant(note_two["due_utc"], "2026-10-21T00:00:00Z")
    assert read_agency(world)["open_request_count"] == 2


def test_amendment_turnaround_compresses_at_exactly_forty_eight_hours_from_sine_die():
    """PRD: "A `COMMITTEE`-stage amendment is allowed a base window of four hours; a
    `FLOOR`-stage amendment is allowed one hour." and "If the interval from
    `requested_utc` to the session's `sine_die_utc` is 48 hours or less, that base
    window is halved and then floored to whole minutes; otherwise the base window
    stands unchanged." and "The result is added to `requested_utc` to give
    `turnaround_deadline_utc`." and "A new amendment lands in `status` `REQUESTED`
    with `requested_by_member_id` stamped from `X-User-ID`, `requested_utc` stamped
    from the logical clock, `drafted_by_drafter_id`, `drafted_utc` and `adopted_utc`
    all null, and `rescind_count` at 0."

    Design: Corner/calculations/amendment_turnaround_compresses_at_exactly_forty_eight_hours_before_sine_die
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Uniform bond covenants",
        summary="Standardize the state bond covenants.",
        target_code_chapter="Title 41",
        appropriation_requested_cents=0,
    )
    assert_instant(read_session(world)["sine_die_utc"], "2026-11-20T18:00:00Z")
    referral = refer_bill(
        world,
        bill,
        hearing_window_start_utc="2026-10-20T14:00:00Z",
        hearing_window_end_utc="2026-10-20T16:00:00Z",
    )

    committee_amendment = request_amendment(
        world,
        bill,
        stage="COMMITTEE",
        committee_referral_id=referral["id"],
        fiscal_impact_delta_cents=0,
        summary="Committee amendment far from sine die.",
        drafting_start_utc="2026-09-02T00:00:00Z",
        drafting_due_utc="2026-09-03T00:00:00Z",
    )

    assert_instant(committee_amendment["requested_utc"], CANONICAL_CLOCK)
    # Four uncompressed hours, because sine die is months away.
    assert_instant(committee_amendment["turnaround_deadline_utc"], "2026-09-01T04:00:00Z")

    set_clock("2026-10-21T00:00:00Z")
    report_referral(world, referral, outcome="FAVORABLE")
    set_clock("2026-11-18T17:59:59Z")

    outside_window = request_amendment(
        world,
        bill,
        stage="FLOOR",
        fiscal_impact_delta_cents=0,
        summary="Floor amendment one second outside the compression window.",
        drafting_start_utc="2026-11-18T18:00:00Z",
        drafting_due_utc="2026-11-18T20:00:00Z",
    )

    assert_instant(outside_window["requested_utc"], "2026-11-18T17:59:59Z")
    # 48 hours and one second out, so the full hour stands.
    assert_instant(outside_window["turnaround_deadline_utc"], "2026-11-18T18:59:59Z")

    set_clock("2026-11-18T18:00:00Z")

    on_the_boundary = request_amendment(
        world,
        bill,
        stage="FLOOR",
        fiscal_impact_delta_cents=0,
        summary="Floor amendment exactly at the compression boundary.",
        drafting_start_utc="2026-11-18T18:30:00Z",
        drafting_due_utc="2026-11-18T20:30:00Z",
    )

    assert_instant(on_the_boundary["requested_utc"], "2026-11-18T18:00:00Z")
    # Exactly 48 hours out, and the comparison is inclusive, so 60 halves to 30.
    assert_instant(on_the_boundary["turnaround_deadline_utc"], "2026-11-18T18:30:00Z")

    for amendment in (committee_amendment, outside_window, on_the_boundary):
        stored = read_amendment(world, amendment["id"])
        assert stored["status"] == "REQUESTED"
        assert stored["drafted_utc"] is None
        assert stored["rescind_count"] == 0
