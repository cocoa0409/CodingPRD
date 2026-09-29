"""The pinned evaluation order of the community impact fund waterfall, and the
money boundaries of its two rate tiers.

Both groups here award requests out of one cycle's undesignated pool. The first
pins which figure keys which rate; the second walks the inclusive offset-tier
floor one cent at a time and drives step two onto an exact half cent.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_date_equals,
    assert_money,
    assert_pool_conservation,
    to_decimal,
)
from test_helpers.factories import award_payload, designation_line
from test_helpers.fixtures import (
    certify_review,
    create_active_employer,
    create_agency,
    create_confirmed_pledge,
    create_open_campaign,
    create_open_cycle,
    create_panel_approved_request,
    create_submitted_request,
    current_cycle_version,
    file_review,
    file_score,
    finalize,
    remit,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_allocations_director_headers,
)


def _agency_certified_at_one_hundred(legal_name, ein, priority_area):
    """An agency whose certified review scores 100.00, so it is GOOD_STANDING."""
    agency = create_agency(
        legal_name=legal_name, ein=ein, primary_priority_area=priority_area
    )
    review = file_review(
        agency["id"],
        fiscal_year=2025,
        program_expense_ratio="0.9000",
        admin_expense_ratio="0.1000",
        months_operating_reserve="6.00",
        governance_checklist_passed_count=10,
        audit_opinion="UNQUALIFIED",
    )
    certify_review(
        agency["id"],
        review["id"],
        audited_program_expense_ratio="0.9000",
        audited_admin_expense_ratio="0.1000",
        audited_months_operating_reserve="6.00",
    )
    return validate_success(api_client.get_agency(agency["id"], make_admin_headers()))


def _approved_request(cycle, panelists, agency, requested_amount, priority_area,
                      triple, narrative):
    """Submit a request, file the same triple from every seat, and close review."""
    alignment, evidence, capacity = triple
    return create_panel_approved_request(
        cycle["id"],
        agency["id"],
        panelists,
        {
            "priority_alignment_score": alignment,
            "outcome_evidence_score": evidence,
            "capacity_score": capacity,
        },
        requested_amount=requested_amount,
        priority_area=priority_area,
        narrative_summary=narrative,
    )


def _award(cycle_id, request_id):
    """Issue the award under the cycle's current version, then re-read the request."""
    validate_success(
        api_client.create_award(
            cycle_id,
            award_payload(request_id, current_cycle_version(cycle_id)),
            make_allocations_director_headers(),
        )
    )
    return validate_success(
        api_client.get_allocation_request(request_id, make_admin_headers())
    )


def _order_pin_scenario():
    """A 92750.00 passthrough ledger and one PANEL_APPROVED 250000.00 request."""
    employer = create_active_employer(
        legal_name="Metro Transit Authority",
        employee_count=3000,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=600,
    )
    agency = _agency_certified_at_one_hundred(
        "Summit Youth Alliance", "300000001", "EDUCATION"
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    pledge = create_confirmed_pledge(
        campaign["id"],
        donor_reference="D-200",
        giving_method="PAYROLL_DEDUCTION",
        gross_amount="100000.00",
        designations=[designation_line(agency["id"], "100000.00")],
    )
    remit(pledge["id"], "100000.00")
    cycle, panelists = create_open_cycle(
        3,
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="500000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="250000.00",
        priority_area="EDUCATION",
        narrative_summary="Out-of-school-time literacy expansion across six schools.",
    )
    triples = ((85, 80, 78), (80, 75, 73), (75, 70, 68))
    for panelist, (alignment, evidence, capacity) in zip(panelists, triples):
        file_score(
            request["id"],
            panelist["id"],
            priority_alignment_score=alignment,
            outcome_evidence_score=evidence,
            capacity_score=capacity,
        )
    request = finalize(request["id"])
    assert request["status"] == "PANEL_APPROVED", "the request must reach the award gate"
    return agency, cycle, request


def test_the_supplement_rate_is_keyed_on_the_net_and_not_on_the_base_award():
    """PRD 3.8: "Step five is the strategic supplement, and its rate is keyed on the
    net figure that step four just produced, namely `base_award` minus
    `designation_offset`."

    The base award of 175960.00 would select the 0.01 rate; the net of 114374.00
    selects 0.03, and only the second reading reaches 117805.22.

    Design: Difficulty/combinatorial_formula/impact_fund_offset_then_supplement_evaluation_order_pin
    """
    _, cycle, request = _order_pin_scenario()

    assert_money(request["composite_score"], "87.98", "composite_score")

    awarded = _award(cycle["id"], request["id"])

    assert_money(awarded["base_award"], "175960.00", "base_award")
    assert_money(awarded["designation_offset"], "61586.00", "designation_offset")
    assert_money(awarded["strategic_supplement"], "3431.22", "strategic_supplement")
    assert_money(awarded["total_award"], "117805.22", "total_award")
    assert awarded["total_award"] not in ("115517.74", 115517.74), (
        "115517.74 is the figure produced by keying the supplement rate on base_award"
    )


def test_the_offset_cap_is_the_agencys_own_designated_passthrough_ledger():
    """PRD 3.8: "`designation_offset` is `base_award` multiplied by that rate, rounded
    half up to two decimals, and then capped at the agency's
    `designated_passthrough_ytd` — an agency cannot be offset by more designation
    income than it actually received."

    The ledger carries 92750.00 and the rated offset is 61586.00, so the cap is
    present but does not bite.

    Design: Difficulty/combinatorial_formula/impact_fund_offset_then_supplement_evaluation_order_pin
    """
    agency, cycle, request = _order_pin_scenario()
    admin = make_admin_headers()

    reread_agency = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(
        reread_agency["designated_passthrough_ytd"],
        "92750.00",
        "designated_passthrough_ytd",
    )

    awarded = _award(cycle["id"], request["id"])

    assert_money(awarded["designation_offset"], "61586.00", "designation_offset")
    assert awarded["designation_offset"] != reread_agency["designated_passthrough_ytd"], (
        "the cap is not reached, so the rated figure survives untouched"
    )


def test_a_successful_award_stamps_the_report_due_date_one_hundred_eighty_days_out():
    """PRD 3.8: "A successful award advances the request `PANEL_APPROVED → AWARDED`,
    stamps `awarded_at` from the logical clock, and sets `outcome_report_due_date` to
    the date part of `awarded_at` plus 180 calendar days."

    Design: Difficulty/combinatorial_formula/impact_fund_offset_then_supplement_evaluation_order_pin
    """
    _, cycle, request = _order_pin_scenario()
    admin = make_admin_headers()

    awarded = _award(cycle["id"], request["id"])

    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_at"] is not None, "awarded_at is stamped from the clock"
    assert awarded["awarded_at"].startswith("2026-08-01"), (
        "the logical clock sits at its 2026-08-01T00:00:00Z default"
    )
    assert_date_equals(
        awarded["outcome_report_due_date"], "2027-01-28", "outcome_report_due_date"
    )

    reread_cycle = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert_money(reread_cycle["awarded_total"], "117805.22", "awarded_total")
    assert_money(
        reread_cycle["available_undesignated_pool"],
        "382194.78",
        "available_undesignated_pool",
    )
    assert_pool_conservation(reread_cycle)


def test_the_impact_fund_summary_reports_the_three_award_components_separately():
    """PRD 3.8: "The cycle's overall fund position is available as a computed read that
    reports, for one cycle, its `cycle_id` and `posture`, the
    `opening_undesignated_pool`, the `available_undesignated_pool`, the
    `awarded_total`, a `base_award_total` and a `designation_offset_total` and a
    `strategic_supplement_total` summing those three components across the cycle's
    awarded requests, an `awarded_request_count`, plus the `suspended_request_count`,
    the `suspended_request_ratio` and the `awards_blocked` flag."

    Design: Difficulty/combinatorial_formula/impact_fund_offset_then_supplement_evaluation_order_pin
    """
    _, cycle, request = _order_pin_scenario()

    _award(cycle["id"], request["id"])

    summary = validate_success(
        api_client.get_impact_fund_summary(cycle["id"], make_admin_headers())
    )

    assert summary["cycle_id"] == cycle["id"]
    assert summary["posture"] == "OPEN"
    assert summary["awarded_request_count"] == 1
    assert_money(summary["opening_undesignated_pool"], "500000.00", "opening pool")
    assert_money(summary["base_award_total"], "175960.00", "base_award_total")
    assert_money(summary["designation_offset_total"], "61586.00", "designation_offset_total")
    assert_money(summary["strategic_supplement_total"], "3431.22", "strategic_supplement_total")
    assert_money(summary["awarded_total"], "117805.22", "awarded_total")
    assert_money(
        summary["available_undesignated_pool"], "382194.78", "available_undesignated_pool"
    )
    assert summary["suspended_request_count"] == 0
    assert summary["awards_blocked"] is False


def _tier_scenario():
    """Three PANEL_APPROVED requests on one 400000.00 cycle.

    The two BASIC_NEEDS agencies carry an identical 9275.00 passthrough ledger, so
    the only thing separating their awards is `base_award`: 50000.00 exactly
    against 49999.99. The third agency carries nothing and asks for 200.20.
    """
    employer = create_active_employer(
        legal_name="Harborline Shipping",
        employee_count=800,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=600,
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    at_floor = _agency_certified_at_one_hundred(
        "Beacon Hill Housing Trust", "120000001", "BASIC_NEEDS"
    )
    below_floor = _agency_certified_at_one_hundred(
        "Cornerstone Youth Homes", "120000002", "BASIC_NEEDS"
    )
    half_cent = _agency_certified_at_one_hundred(
        "Willow Creek Mentors", "120000003", "EDUCATION"
    )
    for donor_reference, agency in (("D-BND-1", at_floor), ("D-BND-2", below_floor)):
        pledge = create_confirmed_pledge(
            campaign["id"],
            donor_reference=donor_reference,
            giving_method="PAYROLL_DEDUCTION",
            gross_amount="10000.00",
            designations=[designation_line(agency["id"], "10000.00")],
        )
        remit(pledge["id"], "10000.00")
    cycle, panelists = create_open_cycle(
        3,
        cycle_year=2026,
        focus_priority_area="FINANCIAL_STABILITY",
        opening_undesignated_pool="400000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )
    request_at_floor = _approved_request(
        cycle, panelists, at_floor, "50000.00", "BASIC_NEEDS", (100, 100, 100),
        "Transitional housing beds.",
    )
    request_below_floor = _approved_request(
        cycle, panelists, below_floor, "49999.99", "BASIC_NEEDS", (100, 100, 100),
        "Emergency youth shelter.",
    )
    request_half_cent = _approved_request(
        cycle, panelists, half_cent, "200.20", "EDUCATION", (72, 72, 74),
        "Mentor training stipends.",
    )
    agencies = (at_floor, below_floor, half_cent)
    requests = (request_at_floor, request_below_floor, request_half_cent)
    return cycle, agencies, requests


def test_the_offset_tier_floor_is_inclusive_at_exactly_fifty_thousand():
    """PRD 3.8: "The rate is 0.00 when `base_award` is below 50000.00; it is 0.15 when
    `base_award` is at least 50000.00 and below 150000.00; and it is 0.35 when
    `base_award` is 150000.00 or more."

    Design: Difficulty/boundary_precision_check/designation_offset_tier_floor_and_money_half_cent_rounding
    """
    cycle, agencies, requests = _tier_scenario()
    at_floor, _, _ = agencies
    request_at_floor, _, _ = requests

    ledger = validate_success(api_client.get_agency(at_floor["id"], make_admin_headers()))
    assert_money(ledger["designated_passthrough_ytd"], "9275.00", "designated_passthrough_ytd")
    assert_money(request_at_floor["composite_score"], "100.00", "composite_score")

    awarded = _award(cycle["id"], request_at_floor["id"])

    assert_money(awarded["base_award"], "50000.00", "base_award")
    assert_money(awarded["designation_offset"], "7500.00", "designation_offset")
    assert awarded["designation_offset"] not in ("0.00", 0.00), (
        "an exclusive reading of the 50000.00 floor would leave the offset at 0.00"
    )
    assert_money(awarded["strategic_supplement"], "2550.00", "strategic_supplement")
    assert_money(awarded["total_award"], "45050.00", "total_award")


def test_one_cent_below_the_offset_tier_floor_earns_no_offset_at_all():
    """PRD 3.8: "The rate is 0.00 when `base_award` is below 50000.00; it is 0.15 when
    `base_award` is at least 50000.00 and below 150000.00; and it is 0.35 when
    `base_award` is 150000.00 or more."

    Design: Difficulty/boundary_precision_check/designation_offset_tier_floor_and_money_half_cent_rounding
    """
    cycle, agencies, requests = _tier_scenario()
    _, below_floor, _ = agencies
    _, request_below_floor, _ = requests

    ledger = validate_success(
        api_client.get_agency(below_floor["id"], make_admin_headers())
    )
    assert_money(ledger["designated_passthrough_ytd"], "9275.00", "designated_passthrough_ytd")

    awarded = _award(cycle["id"], request_below_floor["id"])

    assert_money(awarded["base_award"], "49999.99", "base_award")
    assert_money(awarded["designation_offset"], "0.00", "designation_offset")
    assert_money(awarded["strategic_supplement"], "3000.00", "strategic_supplement")
    assert_money(awarded["total_award"], "52999.99", "total_award")


def test_the_offset_tier_flip_inverts_the_ranking_of_the_two_asks():
    """PRD 3.8: "That net figure attracts a rate of 0.06 when it is below 50000.00, 0.03
    when it is at least 50000.00 and below 120000.00, and 0.01 when it is 120000.00 or
    more; smaller awards are topped up proportionally more."

    Both nets — 42500.00 and 49999.99 — sit in the same 0.06 supplement band, so the
    smaller ask winning the larger award is attributable to the offset tier alone.

    Design: Difficulty/boundary_precision_check/designation_offset_tier_floor_and_money_half_cent_rounding
    """
    cycle, _, requests = _tier_scenario()
    request_at_floor, request_below_floor, _ = requests

    awarded_at_floor = _award(cycle["id"], request_at_floor["id"])
    awarded_below_floor = _award(cycle["id"], request_below_floor["id"])

    assert_money(awarded_at_floor["total_award"], "45050.00", "at-floor total_award")
    assert_money(awarded_below_floor["total_award"], "52999.99", "below-floor total_award")
    assert_money(awarded_at_floor["strategic_supplement"], "2550.00", "at-floor supplement")
    assert_money(awarded_below_floor["strategic_supplement"], "3000.00", "below-floor supplement")

    assert to_decimal(awarded_below_floor["total_award"]) > to_decimal(
        awarded_at_floor["total_award"]
    ), (
        "the smaller 49999.99 ask wins the larger award because it misses the offset tier"
    )


def test_step_two_landing_on_an_exact_half_cent_rounds_up_and_propagates():
    """PRD 3.8: "Step two lets the panel's judgement scale the ask: the score-scaled
    figure is the eligible request amount multiplied by the `composite_score` divided
    by 100, rounded half up to two decimals."

    200.20 times 0.7250 is exactly 145.1450, so the base award is 145.15 and the
    supplement and total follow from it.

    Design: Difficulty/boundary_precision_check/designation_offset_tier_floor_and_money_half_cent_rounding
    """
    cycle, _, requests = _tier_scenario()
    _, _, request_half_cent = requests

    assert_money(request_half_cent["composite_score"], "72.50", "composite_score")

    awarded = _award(cycle["id"], request_half_cent["id"])

    assert_money(awarded["base_award"], "145.15", "base_award")
    assert awarded["base_award"] not in ("145.14", 145.14), (
        "145.14 is the float-pipeline answer for the exact product 145.1450"
    )
    assert_money(awarded["designation_offset"], "0.00", "designation_offset")
    assert_money(awarded["strategic_supplement"], "8.71", "strategic_supplement")
    assert_money(awarded["total_award"], "153.86", "total_award")
    assert awarded["total_award"] not in ("153.85", 153.85), (
        "153.85 is what a float base of 145.14 propagates into the total"
    )


def test_the_pool_conserves_exactly_across_all_three_tier_awards():
    """PRD 3.8: "The cycle's invariant holds at all times and with zero drift:
    `available_undesignated_pool` plus `awarded_total` always equals
    `opening_undesignated_pool`."

    Design: Difficulty/boundary_precision_check/designation_offset_tier_floor_and_money_half_cent_rounding
    """
    cycle, _, requests = _tier_scenario()
    admin = make_admin_headers()

    opening = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert_money(opening["awarded_total"], "0.00", "awarded_total before any award")
    assert_pool_conservation(opening)

    for request in requests:
        _award(cycle["id"], request["id"])
        assert_pool_conservation(
            validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
        )

    final = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert_money(final["awarded_total"], "98203.85", "awarded_total")
    assert_money(
        final["available_undesignated_pool"], "301796.15", "available_undesignated_pool"
    )
    assert_money(final["opening_undesignated_pool"], "400000.00", "opening_undesignated_pool")
    assert_pool_conservation(final)
