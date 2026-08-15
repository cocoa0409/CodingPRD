"""Funder reports: outcome metrics, headline selection, and submission flow."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_funder_report,
    create_active_member,
    create_report,
    create_report_payload,
    director_headers,
    make_funder_contact_headers,
    run_day,
    setup_site_with_director,
    sign_in_member,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_report_scenario(api):
    """Site capacity 60; four members approved on 2026-08-01; club days
    08-03 (4 sign-ins), 08-04 (2), 08-05 (1), all CLOSED.
    member_days_attended = 7, member_days_enrolled = 4 x 3 = 12.
    Returns (site, director)."""
    site, director = setup_site_with_director(clock="2026-08-01T09:00:00Z")
    members = [
        create_active_member(site["id"], director["id"], legal_name=n)
        for n in ("Kid A", "Kid B", "Kid C", "Kid D")
    ]
    ids = [m["id"] for m in members]
    for date, day_members in (
        ("2026-08-03", ids),
        ("2026-08-04", ids[:2]),
        ("2026-08-05", ids[:1]),
    ):
        run_day(site["id"], director["id"], date, member_ids=day_members,
                close=True)
    return site, director


def test_report_counts_and_bases(api):
    """PRD 3.9: "`member_days_attended` counts attendance records on them, with
    `ON_SITE`, `SIGNED_OUT`, and `MISSING_SIGNOUT` all counting as attended;
    `member_days_enrolled` sums, over each included day, the members whose
    `approved_at` is no later than that day's end and whose `withdrawn_at` is
    either null or later than that day's start — a suspended member still
    counts as enrolled. From those bases: ... `attendance_rate_enrollment_basis`
    is `member_days_attended` divided by `member_days_enrolled` (zero when
    enrollment is zero); `attendance_rate_capacity_basis` is
    `member_days_attended` divided by the product of the site's
    `youth_capacity` and `operating_days` (zero when there are no operating
    days); all three are carried to four decimal places, rounded half-up."

    Design: Difficulty/dual_variant_calc/funder_report_attendance_rate_enrollment_vs_capacity_basis
    """
    site, director = _setup_report_scenario(api)
    report = create_report(site["id"], director["id"], "2026-08", "UNITED_WAY")
    assert_funder_report(report)
    assert report["operating_days"] == 3
    assert report["member_days_attended"] == 7
    assert report["member_days_enrolled"] == 12
    assert report["attendance_rate_enrollment_basis"] == pytest.approx(0.5833), (
        "7 / 12 at 4dp, round_half_up"
    )
    assert report["attendance_rate_capacity_basis"] == pytest.approx(0.0389), (
        "7 / (60 x 3) at 4dp, round_half_up"
    )


def test_report_headline_selection_and_average(api):
    """PRD 3.9: "The `headline_attendance_rate` is the enrollment basis for
    `UNITED_WAY` funders and the capacity basis for `STATE_GRANT` funders." and
    "`average_daily_attendance` is `member_days_attended` divided by
    `operating_days` (zero when there are no operating days)".

    Design: Difficulty/dual_variant_calc/funder_report_attendance_rate_enrollment_vs_capacity_basis
    """
    site, director = _setup_report_scenario(api)
    report = create_report(site["id"], director["id"], "2026-08", "UNITED_WAY")
    assert report["headline_attendance_rate"] == pytest.approx(
        report["attendance_rate_enrollment_basis"]
    )
    assert report["headline_attendance_rate"] == pytest.approx(0.5833)
    assert report["average_daily_attendance"] == pytest.approx(2.3333), (
        "7 / 3 at 4dp, round_half_up"
    )


def test_report_accept_draft_returns_not_submitted(api):
    """PRD 3.9: "the report must be `SUBMITTED` (`ERR_REPORT_NOT_SUBMITTED`)".

    Design: Corner/state_machines/c_report_accept_draft_returns_not_submitted
    """
    site, director = setup_site_with_director()
    report = create_report(site["id"], director["id"], "2026-08", "STATE_GRANT")
    res = api.accept_funder_report(report["id"],
                                   make_funder_contact_headers("funder-9"))
    validate_error(res, ApiErrorId.ERR_REPORT_NOT_SUBMITTED, expected_status=409)
    data, _ = validate_paginated(api.list_funder_reports(site["id"], ADMIN))
    assert data[0]["status"] == "DRAFT"


def test_report_submit_twice_returns_not_submittable(api):
    """PRD 3.9: "Submitting the report (a `SiteDirector`) requires `DRAFT`
    (`ERR_REPORT_NOT_SUBMITTABLE`)".

    Design: Corner/state_machines/c_report_submit_twice_returns_not_submittable
    """
    site, director = setup_site_with_director()
    report = create_report(site["id"], director["id"], "2026-08", "UNITED_WAY")
    submitted = validate_success(
        api.submit_funder_report(report["id"], director_headers(director)), 200
    )
    assert submitted["status"] == "SUBMITTED"
    res = api.submit_funder_report(report["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_REPORT_NOT_SUBMITTABLE,
                   expected_status=409)
    data, _ = validate_paginated(api.list_funder_reports(site["id"], ADMIN))
    assert data[0]["status"] == "SUBMITTED"


def test_report_duplicate_month_rejected(api):
    """PRD 3.9: "with one report per site per month
    (`ERR_DUPLICATE_REPORT_MONTH`)".

    Design: Corner/errors/c_report_duplicate_month_rejected
    """
    site, director = setup_site_with_director()
    create_report(site["id"], director["id"], "2026-08", "UNITED_WAY")
    res = api.create_funder_report(
        create_report_payload(site["id"], "2026-08", "STATE_GRANT"),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_REPORT_MONTH, expected_status=409)


def test_report_segregation_of_duties(api):
    """PRD 3.9: "Acceptance belongs to the external `FunderContact`: the report
    must be `SUBMITTED` (`ERR_REPORT_NOT_SUBMITTED`) and the acceptor's
    `X-User-ID` must differ from the submitter's (`ERR_SEGREGATION_OF_DUTIES`).
    Acceptance moves the report to `ACCEPTED`."

    Design: Corner/rbac/c_report_segregation_of_duties
    """
    site, director = setup_site_with_director()
    report = create_report(site["id"], director["id"], "2026-08", "UNITED_WAY")
    submitted = validate_success(
        api.submit_funder_report(report["id"], director_headers(director)), 200
    )
    assert submitted["submitted_by_user_id"] == director["id"]

    # an acceptor presenting the submitter's user id is rejected
    res = api.accept_funder_report(
        report["id"], make_funder_contact_headers(director["id"])
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    accepted = validate_success(
        api.accept_funder_report(report["id"],
                                 make_funder_contact_headers("funder-9")),
        200,
    )
    assert accepted["status"] == "ACCEPTED"
