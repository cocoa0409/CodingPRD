"""Two deadlines examined one unit either side of the line that decides them.

The fifteen-business-day agency filing deadline is inclusive, so a filing on the
due date itself is on time and one second past midnight is not. The seven-day
panel changeover buffer is inclusive too, so a candidate window that buffers back
onto the incumbent's last printed day collides and one further day of separation
does not.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_PANEL_WINDOW_OVERLAP
from test_helpers.assertions import assert_calendar_date, assert_posture, assert_risk_index
from test_helpers.constants import (
    AER_SUBMITTED_TO_FDA,
    AER_TRIAGED_SERIOUS,
    OUTCOME_HOSPITALIZATION,
    PANEL_STATUS_DRAFT,
    POSTURE_RESTRICTED,
    REPORTER_CONSUMER,
    TIMELINESS_LATE,
    TIMELINESS_TIMELY,
    WARNING_PEDIATRIC,
)
from test_helpers.factories import aer_submission_payload, label_panel_payload
from test_helpers.fixtures import (
    make_draft_panel,
    make_grandfathered_ingredient,
    make_line,
    make_product,
    make_triaged_serious_aer,
    product_version,
    set_clock,
)


def _two_serious_reports(api, specialist_headers, quality_headers):
    """One product carrying two serious reports, both received Monday 2026-08-03."""
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Joint Relief",
        net_quantity_g=60,
        servings_per_container=30,
    )
    first = make_triaged_serious_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-08-03",
        narrative="Consumer hospitalised after four days of use",
        outcome_codes=[OUTCOME_HOSPITALIZATION],
    )
    second = make_triaged_serious_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-08-03",
        narrative="Second consumer hospitalised in the same lot window",
        outcome_codes=[OUTCOME_HOSPITALIZATION],
    )
    return product, first, second


def test_a_filing_on_the_due_date_itself_is_timely(
    api, specialist_headers, quality_headers
):
    """The last legal instant of the due date still counts as on time.

    PRD §3.8: "``submission_timeliness`` is then set by comparing the logical clock's
    UTC calendar date against ``submission_due_date``: on or before the due date it is
    ``TIMELY``, strictly after it is ``LATE``." The deadline itself comes from the
    business-day walk: "Starting from ``received_date`` as day zero, which is itself
    never counted, the calendar is walked forward one day at a time; a day that falls
    on Monday, Tuesday, Wednesday, Thursday or Friday increments the count, while a
    Saturday or a Sunday is skipped without counting."

    Design: Difficulty/boundary_precision_check/serious_ae_fifteen_business_day_deadline_boundary
    """
    product, first, _second = _two_serious_reports(
        api, specialist_headers, quality_headers
    )
    assert first["aer_status"] == AER_TRIAGED_SERIOUS
    assert_calendar_date(first["submission_due_date"], "2026-08-24")
    assert_calendar_date(first["retention_until"], "2032-08-03")

    loaded = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert loaded["serious_ae_count"] == 2
    assert_risk_index(loaded, 55)

    set_clock(api, "2026-08-24T23:59:59Z", specialist_headers)
    filed = validate_success(
        api.submit_aer_to_fda(
            first["id"], aer_submission_payload("SAE-2026-0001"), specialist_headers
        ),
        200,
    )
    assert filed["aer_status"] == AER_SUBMITTED_TO_FDA
    assert filed["submission_timeliness"] == TIMELINESS_TIMELY
    assert filed["submitted_at"] is not None

    unpenalised = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert unpenalised["late_notification_count"] == 0
    assert unpenalised["serious_ae_count"] == 2
    assert_risk_index(unpenalised, 55)


def test_a_filing_one_second_later_is_late_and_costs_the_product_its_open_posture(
    api, specialist_headers, quality_headers
):
    """One second across midnight moves the calendar date and the whole posture.

    PRD §3.8: "A ``LATE`` filing increments the product's ``late_notification_count``
    by 1 — the same counter a late claim notification feeds — which recomputes
    ``compliance_risk_index`` and then ``label_posture``." PRD §2.9 supplies the
    arithmetic: "add 20 for each serious adverse event, add 6 for each non-serious
    adverse event, add 15 for each late agency filing", and "a base of 60 or more
    attracts a surcharge of 12".

    Design: Difficulty/boundary_precision_check/serious_ae_fifteen_business_day_deadline_boundary
    """
    product, first, second = _two_serious_reports(
        api, specialist_headers, quality_headers
    )
    set_clock(api, "2026-08-24T23:59:59Z", specialist_headers)
    validate_success(
        api.submit_aer_to_fda(
            first["id"], aer_submission_payload("SAE-2026-0001"), specialist_headers
        ),
        200,
    )

    set_clock(api, "2026-08-25T00:00:00Z", specialist_headers)
    late = validate_success(
        api.submit_aer_to_fda(
            second["id"], aer_submission_payload("SAE-2026-0002"), specialist_headers
        ),
        200,
    )
    assert late["aer_status"] == AER_SUBMITTED_TO_FDA
    assert late["submission_timeliness"] == TIMELINESS_LATE
    assert_calendar_date(late["submission_due_date"], "2026-08-24")

    penalised = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert penalised["late_notification_count"] == 1
    assert penalised["serious_ae_count"] == 2
    assert_risk_index(penalised, 77)
    assert_posture(penalised, POSTURE_RESTRICTED)
    assert penalised["requires_label_revision"] is True


def _c500_with_a_panel_through_year_end(api, specialist_headers):
    """One draft panel printed from 2026-09-01 through 2026-12-31, and the product version."""
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="C-500",
        net_quantity_g=120,
        servings_per_container=60,
    )
    make_line(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        amount_per_serving_mg=500,
        panel_position=1,
    )
    incumbent = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=60,
        effective_from="2026-09-01",
        effective_until="2026-12-31",
        declared_warning_codes=[WARNING_PEDIATRIC],
    )
    return product, incumbent, product_version(api, product["id"], specialist_headers)


def _candidate(api, product_id, version, effective_from, specialist_headers):
    """Offer a replacement window starting on the given date and running to mid-2027."""
    return api.create_label_panel(
        label_panel_payload(
            product_id,
            version,
            servings_per_container_declared=60,
            effective_from=effective_from,
            effective_until="2027-06-30",
            declared_warning_codes=[WARNING_PEDIATRIC],
        ),
        specialist_headers,
    )


def test_a_candidate_buffering_back_onto_the_incumbent_end_date_collides(
    api, specialist_headers
):
    """Seven days of buffer land the candidate exactly on the last printed day.

    PRD §3.5: "Before an incoming panel is created, its own window is widened by a
    seven-day changeover buffer on **both** sides — the buffer exists because printed
    stock takes about a week to flush through a co-packer — and that buffered candidate
    interval is intersected against the occupied interval of every other live panel of
    the same product. A collision exists when the buffered candidate's start falls on or
    before an existing panel's ``effective_until`` **and** that existing panel's
    ``effective_from`` falls on or before the buffered candidate's end; because both
    comparisons are inclusive, windows that merely touch do collide."

    Design: Difficulty/boundary_precision_check/panel_changeover_buffer_seven_day_boundary
    """
    product, incumbent, version = _c500_with_a_panel_through_year_end(
        api, specialist_headers
    )
    assert_calendar_date(incumbent["effective_until"], "2026-12-31")

    refused = _candidate(
        api, product["id"], version, "2027-01-07", specialist_headers
    )
    validate_error(refused, ERR_PANEL_WINDOW_OVERLAP, 409)

    assert product_version(api, product["id"], specialist_headers) == version
    held = validate_success(
        api.get_label_panel(incumbent["id"], specialist_headers), 200
    )
    assert held["panel_status"] == PANEL_STATUS_DRAFT
    assert_calendar_date(held["effective_until"], "2026-12-31")


def test_one_further_day_of_separation_admits_the_replacement(
    api, specialist_headers
):
    """The eighth day clears the buffer and the second panel is created outright.

    PRD §3.5: "A panel **occupies** the closed calendar-date interval running from its
    ``effective_from`` through its ``effective_until``, both bounds inclusive, and only
    panels in ``DRAFT``, ``VALIDATED`` or ``LOCKED`` occupy anything — a ``SUPERSEDED``
    panel has vacated its window." PRD §3.5 also fixes the opening state of the panel
    that survives the screen: "A new panel opens in ``panel_status`` ``DRAFT`` with
    ``required_warning_codes`` empty, ``panel_lines_required``, ``panel_lines_allowed``
    and ``panel_total_dv_coverage_pct`` all null, and ``validated_at`` and ``locked_at``
    null."

    Design: Difficulty/boundary_precision_check/panel_changeover_buffer_seven_day_boundary
    """
    product, incumbent, version = _c500_with_a_panel_through_year_end(
        api, specialist_headers
    )
    validate_error(
        _candidate(api, product["id"], version, "2027-01-07", specialist_headers),
        ERR_PANEL_WINDOW_OVERLAP,
        409,
    )

    admitted = validate_success(
        _candidate(api, product["id"], version, "2027-01-08", specialist_headers), 201
    )
    assert admitted["panel_status"] == PANEL_STATUS_DRAFT
    assert_calendar_date(admitted["effective_from"], "2027-01-08")
    assert_calendar_date(admitted["effective_until"], "2027-06-30")
    assert admitted["validated_at"] is None
    assert admitted["locked_at"] is None
    assert admitted["id"] != incumbent["id"]

    panels, meta = validate_paginated(
        api.list_label_panels(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["panel_status"] for row in panels} == {PANEL_STATUS_DRAFT}
