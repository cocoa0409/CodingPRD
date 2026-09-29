"""The inclusive panel approval bound, and the focus multiplier that lands a
composite score exactly on a half cent.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_is_null, assert_money
from test_helpers.factories import panel_score_payload
from test_helpers.fixtures import (
    certify_review,
    create_agency,
    create_open_cycle,
    create_submitted_request,
    file_review,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_allocations_director_headers,
    make_panelist_headers,
)


def _agency_certified_at_one_hundred(legal_name, ein, priority_area):
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


def _panel_scenario():
    """An OPEN cycle whose focus is EDUCATION with three conflict-free seats."""
    return create_open_cycle(
        3,
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="400000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )


def _scored_request(cycle, panelists, agency, priority_area, triple, narrative):
    """Submit a 40000.00 request and file the same triple from all three seats."""
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="40000.00",
        priority_area=priority_area,
        narrative_summary=narrative,
    )
    alignment, evidence, capacity = triple
    for panelist in panelists:
        validate_success(
            api_client.create_panel_score(
                request["id"],
                panel_score_payload(alignment, evidence, capacity),
                make_panelist_headers(panelist["id"]),
            ),
            201,
        )
    return request


def test_a_composite_exactly_at_the_approval_threshold_is_approved():
    """PRD 3.7: "A composite of 72.00 or more advances the request
    `UNDER_PANEL_REVIEW → PANEL_APPROVED`; anything below advances it to the terminal
    `UNDER_PANEL_REVIEW → PANEL_DECLINED`."

    Design: Difficulty/boundary_precision_check/panel_approval_threshold_inclusive_bound_and_focus_multiplier_half_cent
    """
    cycle, panelists = _panel_scenario()
    agency = _agency_certified_at_one_hundred(
        "Bayview Health Partners", "110000001", "HEALTH"
    )
    request = _scored_request(
        cycle, panelists, agency, "HEALTH", (72, 72, 72), "Mobile clinic hours."
    )

    finalized = validate_success(
        api_client.finalize_review(request["id"], make_allocations_director_headers())
    )

    assert_money(finalized["composite_score"], "72.00", "composite_score")
    assert finalized["status"] == "PANEL_APPROVED", (
        "72.00 is an inclusive lower bound, so the request is approved at the bound"
    )
    assert finalized["eligible_score_count"] == 3, "a pool of three is never trimmed"

    scores, meta = validate_paginated(
        api_client.list_request_scores(request["id"], make_admin_headers())
    )
    assert meta["total_count"] == 3
    for score in scores:
        assert score["eligible"] is True, "no score is dropped below the trim size"


def test_a_composite_one_step_below_the_approval_threshold_is_declined():
    """PRD 3.7: "A composite of 72.00 or more advances the request
    `UNDER_PANEL_REVIEW → PANEL_APPROVED`; anything below advances it to the terminal
    `UNDER_PANEL_REVIEW → PANEL_DECLINED`."

    The three raw judgements are integers, so 71.95 is the largest representable
    composite below the bound.

    Design: Difficulty/boundary_precision_check/panel_approval_threshold_inclusive_bound_and_focus_multiplier_half_cent
    """
    cycle, panelists = _panel_scenario()
    agency = _agency_certified_at_one_hundred(
        "Stonegate Wellness Center", "110000002", "HEALTH"
    )
    request = _scored_request(
        cycle, panelists, agency, "HEALTH", (71, 73, 72), "Wellness screening days."
    )

    finalized = validate_success(
        api_client.finalize_review(request["id"], make_allocations_director_headers())
    )

    assert_money(finalized["composite_score"], "71.95", "composite_score")
    assert finalized["status"] == "PANEL_DECLINED"
    assert finalized["eligible_score_count"] == 3


def test_the_focus_multiplier_product_on_a_half_cent_rounds_half_up():
    """PRD 3.7: "The `composite_score` is that base multiplied by the multiplier,
    capped at 100, and rounded half up to two decimals — cap first, round last."

    The base of 76.50 times the focus multiplier of 1.15 is exactly 87.9750, which
    rounds half up to 87.98.

    Design: Difficulty/boundary_precision_check/panel_approval_threshold_inclusive_bound_and_focus_multiplier_half_cent
    """
    cycle, panelists = _panel_scenario()
    agency = _agency_certified_at_one_hundred(
        "Lantern Literacy Project", "110000003", "EDUCATION"
    )
    request = _scored_request(
        cycle,
        panelists,
        agency,
        "EDUCATION",
        (75, 80, 74),
        "After-school literacy tutoring.",
    )

    finalized = validate_success(
        api_client.finalize_review(request["id"], make_allocations_director_headers())
    )

    assert_money(finalized["composite_score"], "87.98", "composite_score")
    assert finalized["composite_score"] not in ("87.97", 87.97), (
        "87.97 is the float-pipeline answer; the exact product 87.9750 rounds up"
    )
    assert finalized["status"] == "PANEL_APPROVED"

    reread = validate_success(
        api_client.get_allocation_cycle(cycle["id"], make_admin_headers())
    )
    assert_money(reread["awarded_total"], "0.00", "awarded_total")
    assert_money(
        reread["available_undesignated_pool"], "400000.00", "available_undesignated_pool"
    )


def test_each_filed_score_rounds_its_own_weighted_value_before_any_averaging():
    """PRD 3.7: "Each filed score immediately computes its own `weighted_score`: the
    priority alignment judgement weighted at 0.40, the outcome evidence judgement at
    0.35 and the capacity judgement at 0.25, summed and then rounded half up to two
    decimal places."

    Design: Difficulty/boundary_precision_check/panel_approval_threshold_inclusive_bound_and_focus_multiplier_half_cent
    """
    cycle, panelists = _panel_scenario()
    admin = make_admin_headers()
    at_bound = _agency_certified_at_one_hundred(
        "Bayview Health Partners", "110000001", "HEALTH"
    )
    below = _agency_certified_at_one_hundred(
        "Stonegate Wellness Center", "110000002", "HEALTH"
    )
    precision = _agency_certified_at_one_hundred(
        "Lantern Literacy Project", "110000003", "EDUCATION"
    )

    cases = (
        (at_bound, "HEALTH", (72, 72, 72), "72.00", "Mobile clinic hours."),
        (below, "HEALTH", (71, 73, 72), "71.95", "Wellness screening days."),
        (precision, "EDUCATION", (75, 80, 74), "76.50", "After-school literacy tutoring."),
    )
    for agency, priority_area, triple, expected, narrative in cases:
        request = _scored_request(cycle, panelists, agency, priority_area, triple, narrative)
        scores, meta = validate_paginated(api_client.list_request_scores(request["id"], admin))
        assert meta["total_count"] == 3
        for score in scores:
            assert_money(score["weighted_score"], expected, "weighted_score")
        under_review = validate_success(
            api_client.get_allocation_request(request["id"], admin)
        )
        assert under_review["status"] == "UNDER_PANEL_REVIEW", (
            "the first filed score moved the request under panel review"
        )
        assert_is_null(under_review["composite_score"], "composite_score before finalization")
