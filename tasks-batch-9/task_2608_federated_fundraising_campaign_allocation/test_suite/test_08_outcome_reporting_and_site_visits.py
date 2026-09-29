"""The outcome report's revision cycle and its round cap, and the closed-interval
travel buffer on a volunteer monitor's own calendar.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_REVISION_LIMIT_REACHED,
    ERR_SITE_VISIT_BUFFER_CONFLICT,
)
from test_helpers.assertions import (
    assert_date_equals,
    assert_decimal_equals,
    assert_is_null,
    assert_money,
    require_by,
)
from test_helpers.factories import (
    outcome_report_payload,
    resubmit_payload,
    revision_request_payload,
    site_visit_findings_payload,
    site_visit_payload,
)
from test_helpers.fixtures import (
    award,
    certify_review,
    create_agency,
    create_open_cycle,
    create_panel_approved_request,
    create_submitted_request,
    current_cycle_version,
    file_review,
    file_score,
    finalize,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_agency_rep_headers,
    make_panelist_headers,
)


PERFECT_TRIPLE = {
    "priority_alignment_score": 100,
    "outcome_evidence_score": 100,
    "capacity_score": 100,
}


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


def _schedule(report_id, panelist_id, window_start, window_end):
    return api_client.schedule_site_visit(
        report_id,
        site_visit_payload(window_start, window_end),
        make_panelist_headers(panelist_id),
    )


def _complete(report_id, panelist_id, findings):
    return validate_success(
        api_client.complete_site_visit(
            report_id,
            site_visit_findings_payload(site_visit_findings=findings),
            make_panelist_headers(panelist_id),
        )
    )


def _request_revision(report_id, note):
    return api_client.request_outcome_report_revision(
        report_id, revision_request_payload(revision_note=note), make_admin_headers()
    )


def _resubmit(report_id, agency_id, **kwargs):
    return validate_success(
        api_client.resubmit_outcome_report(
            report_id, resubmit_payload(**kwargs), make_agency_rep_headers(agency_id)
        )
    )


def _read_report(report_id):
    return validate_success(
        api_client.get_outcome_report(report_id, make_admin_headers())
    )


def _read_request(request_id):
    return validate_success(
        api_client.get_allocation_request(request_id, make_admin_headers())
    )


def _read_cycle(cycle_id):
    return validate_success(
        api_client.get_allocation_cycle(cycle_id, make_admin_headers())
    )


def _revision_loop_scenario():
    """An awarded 37303.52 request whose report is one revision round in.

    Four conflict-free seats are filled: three panelists score the request and the
    fourth files nothing at all, so the monitoring visits are open to him.
    """
    agency = _agency_certified_at_one_hundred(
        "Bright Futures Tutoring", "500000001", "EDUCATION"
    )
    cycle, panelists = create_open_cycle(
        4,
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="500000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )
    scorers, monitor = panelists[:3], panelists[3]
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="40000.00",
        priority_area="EDUCATION",
        narrative_summary="After-school tutoring for 1200 students.",
    )
    for panelist, (alignment, evidence, capacity) in zip(
        scorers, ((85, 80, 78), (80, 75, 73), (75, 70, 68))
    ):
        file_score(
            request["id"],
            panelist["id"],
            priority_alignment_score=alignment,
            outcome_evidence_score=evidence,
            capacity_score=capacity,
        )
    request = finalize(request["id"])
    award(cycle["id"], request["id"], current_cycle_version(cycle["id"]))
    report = validate_success(
        api_client.create_outcome_report(
            request["id"],
            outcome_report_payload(
                reporting_period_end="2026-07-31",
                persons_served=1200,
                outcome_metric_name="Students reading at grade level",
                outcome_metric_value="640",
                funds_expended="37303.52",
            ),
            make_agency_rep_headers(agency["id"]),
        ),
        201,
    )
    validate_success(_schedule(report["id"], monitor["id"], "2026-09-01", "2026-09-05"))
    _complete(
        report["id"],
        monitor["id"],
        "Program delivered as described; expenditure detail incomplete.",
    )
    validate_success(
        _request_revision(report["id"], "Restate expenditure detail by cost center.")
    )
    report = _resubmit(
        report["id"],
        agency["id"],
        persons_served=1180,
        outcome_metric_value="630",
        funds_expended="35000.00",
    )
    return agency, cycle, request, report, monitor


def test_resubmission_recomputes_the_variance_and_keeps_the_historic_window():
    """PRD 3.9: "It clears `site_visit_findings`, since the previous visit's narrative no
    longer describes the corrected report, but it deliberately keeps
    `site_visit_panelist_id`, `site_visit_window_start` and `site_visit_window_end` so
    that the historic window remains on the record."

    Design: Difficulty/non_linear_state_machine/outcome_report_revision_loop_and_round_cap
    """
    _, _, request, report, monitor = _revision_loop_scenario()

    awarded = _read_request(request["id"])
    assert_money(awarded["total_award"], "37303.52", "total_award")

    assert report["status"] == "SUBMITTED", "the loop returned the report to its own start"
    assert report["revision_round_count"] == 1
    assert report["persons_served"] == 1180
    assert_decimal_equals(
        report["expenditure_variance_pct"], "-6.18", "expenditure_variance_pct"
    )
    assert_is_null(report["site_visit_findings"], "site_visit_findings")
    assert report["site_visit_panelist_id"] == monitor["id"], (
        "the monitor who ran the first visit stays on the record"
    )
    assert_date_equals(report["site_visit_window_start"], "2026-09-01", "window start")
    assert_date_equals(report["site_visit_window_end"], "2026-09-05", "window end")


def test_the_second_pass_around_the_loop_increments_the_round_counter_to_two():
    """PRD 3.9: "Requesting a revision instead advances the report `SITE_VISIT_COMPLETED
    → REVISION_REQUESTED`, carries a `revision_note` explaining what must change, and
    increments `revision_round_count` by one."

    Design: Difficulty/non_linear_state_machine/outcome_report_revision_loop_and_round_cap
    """
    agency, _, _, report, monitor = _revision_loop_scenario()

    validate_success(_schedule(report["id"], monitor["id"], "2026-09-10", "2026-09-12"))
    scheduled = _read_report(report["id"])
    assert scheduled["status"] == "SITE_VISIT_SCHEDULED"

    _complete(
        report["id"],
        monitor["id"],
        "Second visit: cost-center restatement still partial.",
    )
    revised = validate_success(
        _request_revision(report["id"], "Second and final revision round.")
    )

    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["revision_round_count"] == 2, "the second lap reaches the ceiling"

    resubmitted = _resubmit(
        report["id"],
        agency["id"],
        persons_served=1190,
        outcome_metric_value="635",
        funds_expended="37303.52",
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round_count"] == 2
    assert_decimal_equals(
        resubmitted["expenditure_variance_pct"], "0.00", "expenditure_variance_pct"
    )


def test_a_third_revision_request_is_refused_once_the_counter_has_reached_two():
    """PRD 3.9: "The revision loop is capped: once `revision_round_count` has reached 2,
    a further revision request is refused with `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/outcome_report_revision_loop_and_round_cap
    """
    agency, _, _, report, monitor = _revision_loop_scenario()

    validate_success(_schedule(report["id"], monitor["id"], "2026-09-10", "2026-09-12"))
    _complete(
        report["id"],
        monitor["id"],
        "Second visit: cost-center restatement still partial.",
    )
    validate_success(_request_revision(report["id"], "Second and final revision round."))
    _resubmit(
        report["id"],
        agency["id"],
        persons_served=1190,
        outcome_metric_value="635",
        funds_expended="37303.52",
    )
    validate_success(_schedule(report["id"], monitor["id"], "2026-09-20", "2026-09-22"))
    _complete(report["id"], monitor["id"], "Third visit: restatement accepted by monitor.")

    completed = _read_report(report["id"])
    assert completed["status"] == "SITE_VISIT_COMPLETED"

    validate_error(
        _request_revision(report["id"], "Attempted third revision round."),
        ERR_REVISION_LIMIT_REACHED,
        409,
    )

    unchanged = _read_report(report["id"])
    assert unchanged["revision_round_count"] == 2, "the refused request incremented nothing"
    assert unchanged["status"] == "SITE_VISIT_COMPLETED", "and moved the report nowhere"


def test_the_funded_request_stays_in_reporting_for_every_lap_of_the_loop():
    """PRD 3.9: "Filing advances the parent request `AWARDED → REPORTING`."

    Design: Difficulty/non_linear_state_machine/outcome_report_revision_loop_and_round_cap
    """
    agency, cycle, request, report, monitor = _revision_loop_scenario()

    assert _read_request(request["id"])["status"] == "REPORTING", "after the first lap"

    validate_success(_schedule(report["id"], monitor["id"], "2026-09-10", "2026-09-12"))
    assert _read_request(request["id"])["status"] == "REPORTING", "with a visit scheduled"

    _complete(
        report["id"],
        monitor["id"],
        "Second visit: cost-center restatement still partial.",
    )
    validate_success(_request_revision(report["id"], "Second and final revision round."))
    assert _read_request(request["id"])["status"] == "REPORTING", "with a revision pending"

    _resubmit(
        report["id"],
        agency["id"],
        persons_served=1190,
        outcome_metric_value="635",
        funds_expended="37303.52",
    )
    reporting = _read_request(request["id"])
    assert reporting["status"] == "REPORTING", "and after the second resubmission"
    assert_money(reporting["total_award"], "37303.52", "total_award is never re-derived")

    ledger = _read_cycle(cycle["id"])
    assert_money(ledger["awarded_total"], "37303.52", "awarded_total counts REPORTING")


def _buffer_scenario():
    """Three SUBMITTED reports on one cycle, and two monitors who never scored.

    Five conflict-free seats are filled: the first three panelists score every
    request, and the last two file nothing, so both are free to monitor.
    """
    agencies = (
        _agency_certified_at_one_hundred(
            "Aurora Community Kitchen", "140000001", "BASIC_NEEDS"
        ),
        _agency_certified_at_one_hundred(
            "Brightwater Health Access", "140000002", "HEALTH"
        ),
        _agency_certified_at_one_hundred(
            "Cardinal Tutoring Network", "140000003", "EDUCATION"
        ),
    )
    cycle, panelists = create_open_cycle(
        5,
        cycle_year=2026,
        focus_priority_area="FINANCIAL_STABILITY",
        opening_undesignated_pool="300000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )
    scorers = panelists[:3]
    first_monitor, second_monitor = panelists[3], panelists[4]
    specs = (
        (agencies[0], "BASIC_NEEDS", "Weekend meal service.", 480, "meals_served", "12000.00"),
        (agencies[1], "HEALTH", "Mobile screening van.", 260, "screenings_completed", "900.00"),
        (agencies[2], "EDUCATION", "Reading buddies expansion.", 150,
         "reading_levels_gained", "340.00"),
    )
    reports = []
    for agency, area, narrative, persons, metric_name, metric_value in specs:
        request = create_panel_approved_request(
            cycle["id"],
            agency["id"],
            scorers,
            PERFECT_TRIPLE,
            requested_amount="20000.00",
            priority_area=area,
            narrative_summary=narrative,
        )
        award(cycle["id"], request["id"], current_cycle_version(cycle["id"]))
        reports.append(
            validate_success(
                api_client.create_outcome_report(
                    request["id"],
                    outcome_report_payload(
                        reporting_period_end="2026-07-31",
                        persons_served=persons,
                        outcome_metric_name=metric_name,
                        outcome_metric_value=metric_value,
                        funds_expended="21200.00",
                    ),
                    make_agency_rep_headers(agency["id"]),
                ),
                201,
            )
        )
    return cycle, reports, first_monitor, second_monitor


def _site_visit_count(panelist_id):
    panelist = validate_success(
        api_client.get_panelist(panelist_id, make_admin_headers())
    )
    return panelist["site_visit_count"]


def test_scheduling_stores_the_window_and_counts_it_against_the_volunteer():
    """PRD 3.9: "Scheduling stores the window and increments the volunteer's
    `site_visit_count`."

    Design: Difficulty/resource_temporal_overlap/panelist_site_visit_windows_closed_intervals_plus_three_day_buffer
    """
    cycle, reports, monitor, _ = _buffer_scenario()

    assert _site_visit_count(monitor["id"]) == 0, "the monitor has no visits yet"

    scheduled = validate_success(
        _schedule(reports[0]["id"], monitor["id"], "2026-08-10", "2026-08-14")
    )

    assert scheduled["status"] == "SITE_VISIT_SCHEDULED"
    assert scheduled["site_visit_panelist_id"] == monitor["id"], (
        "the acting volunteer's own identity is taken from the request headers"
    )
    assert_date_equals(scheduled["site_visit_window_start"], "2026-08-10", "window start")
    assert_date_equals(scheduled["site_visit_window_end"], "2026-08-14", "window end")
    assert _site_visit_count(monitor["id"]) == 1

    assignments, meta = validate_paginated(
        api_client.list_panelist_panel_assignments(monitor["id"], make_admin_headers())
    )
    assert meta["total_count"] == 1, "the monitor holds exactly one seat"
    seat = require_by(assignments, "cycle_id", cycle["id"])
    assert seat["submitted_score_count"] == 0, (
        "the monitor filed no score, so duties are never the reason for a refusal"
    )


def test_a_window_starting_on_another_windows_end_date_already_collides():
    """PRD 3.9: "Two windows collide when the new start falls on or before the existing
    end plus 3 days **and** the existing start falls on or before the new end plus 3
    days; a collision is refused with `ERR_SITE_VISIT_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/panelist_site_visit_windows_closed_intervals_plus_three_day_buffer
    """
    _, reports, monitor, _ = _buffer_scenario()

    validate_success(_schedule(reports[0]["id"], monitor["id"], "2026-08-10", "2026-08-14"))

    validate_error(
        _schedule(reports[1]["id"], monitor["id"], "2026-08-14", "2026-08-16"),
        ERR_SITE_VISIT_BUFFER_CONFLICT,
        409,
    )

    untouched = _read_report(reports[1]["id"])
    assert untouched["status"] == "SUBMITTED", "the refused attempt left no trace"
    assert_is_null(untouched["site_visit_panelist_id"], "site_visit_panelist_id")
    assert_is_null(untouched["site_visit_window_start"], "site_visit_window_start")
    assert _site_visit_count(monitor["id"]) == 1, "and counted nothing"


def test_a_gap_of_exactly_the_buffer_collides_while_one_day_more_is_clean():
    """PRD 3.9: "Fourth, spacing: the requested window, which is a closed interval
    including both endpoints, must be separated by more than 3 calendar days from every
    other window already held by the same volunteer on a report whose status is
    `SITE_VISIT_SCHEDULED`, `SITE_VISIT_COMPLETED`, `REVISION_REQUESTED` or `ACCEPTED`."

    Design: Difficulty/resource_temporal_overlap/panelist_site_visit_windows_closed_intervals_plus_three_day_buffer
    """
    _, reports, monitor, _ = _buffer_scenario()

    validate_success(_schedule(reports[0]["id"], monitor["id"], "2026-08-10", "2026-08-14"))

    validate_error(
        _schedule(reports[1]["id"], monitor["id"], "2026-08-17", "2026-08-20"),
        ERR_SITE_VISIT_BUFFER_CONFLICT,
        409,
    )
    before = _read_report(reports[1]["id"])
    assert before["status"] == "SUBMITTED"
    assert_is_null(before["site_visit_panelist_id"], "site_visit_panelist_id")

    accepted = validate_success(
        _schedule(reports[1]["id"], monitor["id"], "2026-08-18", "2026-08-21")
    )

    assert accepted["status"] == "SITE_VISIT_SCHEDULED", (
        "2026-08-18 clears 2026-08-14 by four days, which is more than the buffer"
    )
    assert_date_equals(accepted["site_visit_window_start"], "2026-08-18", "window start")
    assert_date_equals(accepted["site_visit_window_end"], "2026-08-21", "window end")
    assert _site_visit_count(monitor["id"]) == 2


def test_the_travel_buffer_is_scoped_to_one_volunteers_own_calendar():
    """PRD 3.9: "Fourth, spacing: the requested window, which is a closed interval
    including both endpoints, must be separated by more than 3 calendar days from every
    other window already held by the same volunteer on a report whose status is
    `SITE_VISIT_SCHEDULED`, `SITE_VISIT_COMPLETED`, `REVISION_REQUESTED` or `ACCEPTED`."

    A second volunteer takes the byte-identical window and is admitted, because the
    buffer guards one volunteer's travel calendar and not a fund-wide one.

    Design: Difficulty/resource_temporal_overlap/panelist_site_visit_windows_closed_intervals_plus_three_day_buffer
    """
    _, reports, first_monitor, second_monitor = _buffer_scenario()

    validate_success(
        _schedule(reports[0]["id"], first_monitor["id"], "2026-08-10", "2026-08-14")
    )

    twin = validate_success(
        _schedule(reports[2]["id"], second_monitor["id"], "2026-08-10", "2026-08-14")
    )

    assert twin["status"] == "SITE_VISIT_SCHEDULED"
    assert twin["site_visit_panelist_id"] == second_monitor["id"]
    assert_date_equals(twin["site_visit_window_start"], "2026-08-10", "window start")
    assert_date_equals(twin["site_visit_window_end"], "2026-08-14", "window end")
    assert _site_visit_count(second_monitor["id"]) == 1
    assert _site_visit_count(first_monitor["id"]) == 1, (
        "the first volunteer's calendar is unaffected by the second's"
    )


def test_scheduling_site_visits_never_moves_the_undesignated_pool():
    """PRD 3.8: "It then re-derives the cycle's `awarded_total` as the sum of
    `total_award` over that cycle's requests whose status is `AWARDED`, `REPORTING` or
    `CLOSED_SATISFIED`, and `available_undesignated_pool` as
    `opening_undesignated_pool` minus `awarded_total`."

    Design: Difficulty/resource_temporal_overlap/panelist_site_visit_windows_closed_intervals_plus_three_day_buffer
    """
    cycle, reports, first_monitor, second_monitor = _buffer_scenario()

    before = _read_cycle(cycle["id"])
    assert_money(before["awarded_total"], "63600.00", "awarded_total")
    assert_money(
        before["available_undesignated_pool"], "236400.00", "available_undesignated_pool"
    )

    validate_success(
        _schedule(reports[0]["id"], first_monitor["id"], "2026-08-10", "2026-08-14")
    )
    validate_error(
        _schedule(reports[1]["id"], first_monitor["id"], "2026-08-14", "2026-08-16"),
        ERR_SITE_VISIT_BUFFER_CONFLICT,
        409,
    )
    validate_success(
        _schedule(reports[1]["id"], first_monitor["id"], "2026-08-18", "2026-08-21")
    )
    validate_success(
        _schedule(reports[2]["id"], second_monitor["id"], "2026-08-10", "2026-08-14")
    )

    after = _read_cycle(cycle["id"])
    assert_money(after["awarded_total"], "63600.00", "awarded_total")
    assert_money(
        after["available_undesignated_pool"], "236400.00", "available_undesignated_pool"
    )
