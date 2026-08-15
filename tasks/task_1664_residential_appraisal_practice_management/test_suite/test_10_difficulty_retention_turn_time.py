"""Difficulty queue A: retention standard-vs-judicial variants, calendar vs
business turn-time variants, and the 0.7500 on-time standing boundary
(PRD 3.2, 3.8)."""
from test_helpers import (
    accept_order,
    add_standard_locked_comps,
    assign_order,
    close_complaint,
    create_appraiser,
    create_client,
    create_complaint,
    create_fee_schedule,
    create_membership,
    create_order,
    create_report,
    deliver_report,
    draft_complaint,
    first_workfile_of_type,
    get_order,
    get_scorecard,
    qc_pass,
    scope_order,
    set_clock,
    setup_delivered_order,
    start_analysis,
    submit_complaint,
    submit_for_qc,
    validate_success,
)
from test_helpers import ADMIN


def _setup_two_orders_one_sanctioned():
    """Two desktop STANDARD orders for the same client/appraiser, both first
    delivered 2026-08-02; the second later draws a complaint closed
    CLOSED_SANCTIONED at 2030-06-01."""
    ctx1 = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")
    ctx = ctx1
    # second order on the same client / appraiser / reviewer
    order2 = create_order(ctx["client"]["id"], property_address="20 Oak Ave")
    order2 = scope_order(order2["id"], requires_inspection=False)
    order2 = accept_order(order2["id"])
    order2 = assign_order(order2["id"], ctx["appraiser"]["id"])
    start_analysis(order2["id"], ctx["appraiser"]["id"])
    ctx2 = {"order": order2, "appraiser": ctx["appraiser"]}
    add_standard_locked_comps(ctx2)
    report2 = create_report(order2["id"], ctx["appraiser"]["id"])
    submit_for_qc(report2["id"], ctx["appraiser"]["id"])
    qc_pass(report2["id"], ctx["reviewer"]["id"])
    deliver_report(report2["id"], ctx["appraiser"]["id"])

    # complaint on order 2: received 2030-05-10, closed SANCTIONED 2030-06-01
    set_clock("2030-05-10T00:00:00Z")
    complaint = create_complaint(order2["id"], ctx["appraiser"]["id"])
    draft_complaint(complaint["id"])
    submit_complaint(complaint["id"])
    set_clock("2030-06-01T00:00:00Z")
    close_complaint(complaint["id"], "SANCTIONED")

    return ctx1["order"], order2


def test_retention_standard_variant_after_five_years(api):
    """PRD 3.8: "The standard pin is five calendar years after
    `first_delivered_at`, where year addition is calendar-based, preserving
    the month and day."

    Design: Difficulty/dual_variant_calc/retention_standard_vs_judicial_variant
    """
    order1, _ = _setup_two_orders_one_sanctioned()
    record = first_workfile_of_type(order1["id"], "ORDER_FORM")
    # delivered 2026-08-02, no sanctioned complaint -> 2031-08-02
    assert record["retention_until"] == "2031-08-02T00:00:00Z"


def test_retention_judicial_variant_extends_beyond_standard(api):
    """PRD 3.8: "When any complaint on the order has closed
    `CLOSED_SANCTIONED`, a judicial variant computes two calendar years after
    the latest such complaint's `closed_at`, and the pin becomes the later of
    the standard and the judicial dates; two otherwise-identical orders can
    therefore diverge in retention purely because one drew a sanctioned
    complaint."

    Design: Difficulty/dual_variant_calc/retention_standard_vs_judicial_variant
    """
    order1, order2 = _setup_two_orders_one_sanctioned()
    record1 = first_workfile_of_type(order1["id"], "ORDER_FORM")
    record2 = first_workfile_of_type(order2["id"], "ORDER_FORM")
    # max(2031-08-02 standard, 2030-06-01 + 2 years judicial) = 2032-06-01
    assert record2["retention_until"] == "2032-06-01T00:00:00Z"
    assert record1["retention_until"] != record2["retention_until"]


def _setup_single_delivery_for_turn_time():
    """One desktop STANDARD order accepted at the 2026-08-01 default clock
    (turn 7, due 2026-08-08T00:00) and delivered 2026-08-05T12:00."""
    return setup_delivered_order(delivery_clock="2026-08-05T12:00:00Z")


def test_turn_time_calendar_variant_measures_elapsed_days(api):
    """PRD 3.2: "`avg_calendar_turn_days` is the mean elapsed time from
    `accepted_at` to `first_delivered_at`, measured in days across completed
    orders and rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/turn_time_calendar_vs_business_day_variants
    """
    ctx = _setup_single_delivery_for_turn_time()
    scorecard = get_scorecard(ctx["appraiser"]["id"])
    # 2026-08-05T12:00 minus 2026-08-01T00:00 -> 4.5 days
    assert scorecard["avg_calendar_turn_days"] == 4.5


def test_turn_time_business_variant_counts_weekdays_only(api):
    """PRD 3.2: "`avg_business_turn_days` applies the same averaging but
    counts only the dates after the acceptance date, up to and including the
    delivery date, whose weekday is Monday through Friday: an order accepted
    on Saturday 2026-08-01 and delivered on Wednesday 2026-08-05 counts 4
    calendar days but 3 business days."
    PRD 3.2: "Its `on_time_count` counts the subset delivered on or before the
    order's `due_at`."

    Design: Difficulty/dual_variant_calc/turn_time_calendar_vs_business_day_variants
    """
    ctx = _setup_single_delivery_for_turn_time()
    scorecard = get_scorecard(ctx["appraiser"]["id"])
    # Mon 08-03, Tue 08-04, Wed 08-05 fall in (accept, deliver]
    assert scorecard["avg_business_turn_days"] == 3.0
    # delivered 2026-08-05T12:00 <= due 2026-08-08T00:00 -> on time
    assert scorecard["on_time_rate"] == 1.0
    # one completion is below the four-completion rating threshold
    assert scorecard["standing"] == "GOOD_STANDING"


def _prepare_qc_passed_desktop_order(client, appraiser, reviewer, address):
    """Create a desktop STANDARD order for ``appraiser`` and drive it to
    QC_PASSED at the current logical clock (acceptance stamps `accepted_at`
    now). Returns the report."""
    order = create_order(client["id"], property_address=address)
    order = scope_order(order["id"], requires_inspection=False)
    order = accept_order(order["id"])
    assign_order(order["id"], appraiser["id"])
    start_analysis(order["id"], appraiser["id"])
    ctx = {"order": order, "appraiser": appraiser}
    add_standard_locked_comps(ctx)
    report = create_report(order["id"], appraiser["id"])
    submit_for_qc(report["id"], appraiser["id"])
    qc_pass(report["id"], reviewer["id"])
    return report


def _deliver(report, appraiser, delivery_clock):
    set_clock(delivery_clock)
    deliver_report(report["id"], appraiser["id"])


def _setup_two_rated_appraisers():
    """Appraiser A: 4 desktop orders accepted 2026-08-01 (due 2026-08-08),
    3 delivered on time (2026-08-05T12:00) and 1 late (2026-08-09).
    Appraiser B: 4 desktop orders accepted 2026-08-09 (due 2026-08-16),
    2 on time (08-09) and 2 late (08-20)."""
    set_clock("2026-08-01T00:00:00Z")
    client = create_client(name="AMC Thirteen")
    create_fee_schedule(client["id"])
    appraiser_a = create_appraiser(full_name="Ann Appraiser", license_number="CR-1001")
    appraiser_b = create_appraiser(full_name="Bob Appraiser", license_number="CR-1002")
    reviewer = create_appraiser(full_name="Quinn Reviewer", license_number="CR-2001")
    create_membership(client["id"], appraiser_a["id"])
    create_membership(client["id"], appraiser_b["id"])

    # A: all four accepted at 2026-08-01 (due 2026-08-08T00:00)
    reports_a = [
        _prepare_qc_passed_desktop_order(client, appraiser_a, reviewer, f"A{i} St")
        for i in (1, 2, 3, 4)
    ]
    for report in reports_a[:3]:
        _deliver(report, appraiser_a, "2026-08-05T12:00:00Z")
    _deliver(reports_a[3], appraiser_a, "2026-08-09T00:00:00Z")

    # B: all four accepted at the current clock 2026-08-09 (due 2026-08-16)
    reports_b = [
        _prepare_qc_passed_desktop_order(client, appraiser_b, reviewer, f"B{i} St")
        for i in (1, 2, 3, 4)
    ]
    for report in reports_b[:2]:
        _deliver(report, appraiser_b, "2026-08-09T00:00:00Z")
    for report in reports_b[2:]:
        _deliver(report, appraiser_b, "2026-08-20T00:00:00Z")
    return appraiser_a, appraiser_b


def test_standing_boundary_rate_07500_is_probation(api):
    """PRD 3.2: "The boundaries are exact — a rate of exactly 0.7500 remains
    `PROBATION` rather than suspended, a rate of exactly 0.9000 is
    `GOOD_STANDING`, and the fourth completed order is the first one that
    makes the scorecard rated at all."

    Design: Difficulty/boundary_precision_check/standing_boundary_07500_is_probation_not_suspension
    """
    appraiser_a, _ = _setup_two_rated_appraisers()
    scorecard = get_scorecard(appraiser_a["id"])
    assert scorecard["completed_count"] == 4
    assert scorecard["on_time_count"] == 3
    assert scorecard["on_time_rate"] == 0.75
    assert scorecard["standing"] == "PROBATION"


def test_standing_below_075_is_panel_suspended(api):
    """PRD 3.2: "Standing follows a strict ladder: `PANEL_SUSPENDED` whenever
    `sanction_override` is in force; otherwise, once at least four orders are
    complete, an `on_time_rate` below 0.75 forces `PANEL_SUSPENDED` and a rate
    below 0.90 yields `PROBATION`; everyone else is `GOOD_STANDING`."

    Design: Difficulty/boundary_precision_check/standing_boundary_07500_is_probation_not_suspension
    """
    _, appraiser_b = _setup_two_rated_appraisers()
    scorecard = get_scorecard(appraiser_b["id"])
    assert scorecard["completed_count"] == 4
    assert scorecard["on_time_count"] == 2
    assert scorecard["on_time_rate"] == 0.5
    assert scorecard["standing"] == "PANEL_SUSPENDED"
