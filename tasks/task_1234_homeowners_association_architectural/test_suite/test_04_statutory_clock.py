"""Statutory review clock: counting modes, inclusive boundary, applicant holds."""
from test_helpers import (
    validate_success, TEST_USERS,
    create_association, register_owner, register_property, register_committee,
    create_complete_draft, create_under_review_application, submit_application,
    start_review, read_application, get_single_permit, set_logical_clock,
    run_daily_sweep, setup_review_ready,
    make_homeowner_headers, make_committee_member_headers,
)

MANAGER = TEST_USERS["manager_headers"]


def _calendar_application_under_review(statutory_days=5):
    """One CALENDAR association with a complete application UNDER_REVIEW at 05-01."""
    bundle = setup_review_ready(
        ballots=None,
        assoc_overrides={"statutory_response_days": statutory_days,
                         "counting_mode": "CALENDAR"})
    return bundle


class TestCalendarVsBusinessDeadline:
    """Identical submission instants diverge purely from the counting mode."""

    def test_calendar_mode_deems_at_five_elapsed_days(self, api):
        """CALENDAR counting deems the application on 2026-05-06 and issues a permit.

        PRD §2.6: "Under `CALENDAR` counting, every day counts."
        PRD §3.5: "When the elapsed count reaches the association's
        `statutory_response_days` — the boundary is inclusive, so the clock fires at
        exactly that many days — the daily ops checkpoint deems the application
        approved."
        PRD §3.5: "The same permit cascade as a committee approval follows: an
        `ACTIVE` construction permit is created with the requested window"

        Design: Difficulty/dual_variant_calc/deemed_approval_calendar_vs_business_deadline
        """
        bundle = _calendar_application_under_review()
        app_id = bundle["application"]["id"]
        set_logical_clock("2026-05-06T09:00:00Z")
        report = run_daily_sweep()
        assert report["applications_deemed_approved"] == 1
        app = read_application(app_id)
        assert app["status"] == "DEEMED_APPROVED"
        assert app["decision_outcome"] == "APPROVED"
        permit = get_single_permit(app_id)
        assert permit["status"] == "ACTIVE"
        assert permit["window_start"] == "2026-06-01"
        assert permit["window_end"] == "2026-07-15"

    def test_business_mode_skips_weekend_and_deems_later(self, api):
        """BUSINESS counting skips the weekend: still under review on 05-06, deemed on 05-08.

        PRD §2.6: "Under `BUSINESS` counting, only Monday through Friday count;
        Saturdays and Sundays are skipped, so for an identical submission instant
        the deemed-approval date lands strictly later whenever a weekend intervenes."
        PRD §3.5: "the elapsed review time is the number of countable days strictly
        after the `submitted_at` date up to and including the current logical date —
        every day under `CALENDAR` counting, weekdays only under `BUSINESS` counting"

        Design: Difficulty/dual_variant_calc/deemed_approval_calendar_vs_business_deadline
        """
        cal = _calendar_application_under_review()
        biz = setup_review_ready(
            ballots=None,
            assoc_overrides={"name": "BIZ HOA", "statutory_response_days": 5,
                             "counting_mode": "BUSINESS"})

        set_logical_clock("2026-05-06T09:00:00Z")
        report = run_daily_sweep()
        assert report["applications_deemed_approved"] == 1, "only CAL fires at day 5"
        assert read_application(cal["application"]["id"])["status"] == "DEEMED_APPROVED"
        # business days in (2026-05-01, 2026-05-06] = Mon 04, Tue 05, Wed 06 = 3 < 5
        assert read_application(biz["application"]["id"])["status"] == "UNDER_REVIEW"

        set_logical_clock("2026-05-08T09:00:00Z")
        report2 = run_daily_sweep()
        assert report2["applications_deemed_approved"] == 1, "BIZ fires at 5 weekdays"
        assert read_application(biz["application"]["id"])["status"] == "DEEMED_APPROVED"


class TestExactStatutoryBoundary:
    """Elapsed review days fire the deemed approval AT the threshold, not before."""

    def test_day_before_threshold_deems_nothing(self, api):
        """At elapsed == statutory_response_days - 1 the sweep deems nothing.

        PRD §3.5: "When the elapsed count reaches the association's
        `statutory_response_days` — the boundary is inclusive, so the clock fires at
        exactly that many days — the daily ops checkpoint deems the application
        approved."

        Design: Difficulty/boundary_precision_check/deemed_approval_at_exact_statutory_day
        """
        bundle = _calendar_application_under_review(statutory_days=5)
        app_id = bundle["application"]["id"]
        set_logical_clock("2026-05-05T09:00:00Z")  # elapsed == 4
        report = run_daily_sweep()
        assert report["applications_deemed_approved"] == 0
        assert read_application(app_id)["status"] == "UNDER_REVIEW"

    def test_exact_threshold_day_deems_and_cascades(self, api):
        """At elapsed == statutory_response_days the sweep deems and issues the permit.

        PRD §3.5: "the boundary is inclusive, so the clock fires at exactly that many
        days"
        PRD §3.5: "Deemed approval moves the application to `DEEMED_APPROVED`, sets
        `decision_outcome` to `APPROVED`, stamps `decided_at`, and increments
        `version` by one."

        Design: Difficulty/boundary_precision_check/deemed_approval_at_exact_statutory_day
        """
        bundle = _calendar_application_under_review(statutory_days=5)
        app_id = bundle["application"]["id"]
        set_logical_clock("2026-05-06T09:00:00Z")  # elapsed == 5
        report = run_daily_sweep()
        assert report["applications_deemed_approved"] == 1
        app = read_application(app_id)
        assert app["status"] == "DEEMED_APPROVED"
        assert app["decision_outcome"] == "APPROVED"
        assert app.get("decided_at"), "decided_at must be stamped by the deemed approval"
        permit = get_single_permit(app_id)
        assert permit["status"] == "ACTIVE"


def test_review_clock_excludes_applicant_hold_days(api):
    """A 3-day applicant hold shifts the deemed-approval date by exactly 3 days.

    PRD §3.5: "For an application in `SUBMITTED` or `UNDER_REVIEW`, the elapsed
    review time is the number of countable days strictly after the `submitted_at`
    date up to and including the current logical date — every day under `CALENDAR`
    counting, weekdays only under `BUSINESS` counting — minus the application's
    accumulated `applicant_hold_days`."
    PRD §3.5: "an application sitting in `REVISION_REQUESTED` is not examined,
    because its clock is frozen."

    Design: Corner/calculations/review_clock_excludes_applicant_hold_days
    """
    assoc = create_association(name="Hold HOA", statutory_response_days=5,
                               counting_mode="CALENDAR")
    owner = register_owner(assoc["id"], full_name="Ann A", email="ann.a@x.com")
    member = register_owner(assoc["id"], full_name="Cid B", email="cid.b@x.com")
    prop = register_property(assoc["id"], owner["id"], lot_number="H-1",
                             address="1 Hold Ct")
    set_logical_clock("2026-05-01T09:00:00Z")
    app = create_complete_draft(prop["id"], owner, project_type="PAINT",
                                guideline_section="SEC-3.1", description="repaint")
    submit_application(app["id"], owner["id"])
    start_review(app["id"])
    set_logical_clock("2026-05-02T09:00:00Z")
    validate_success(api.request_revision(
        app["id"], {"revision_notes": "add color board"},
        make_committee_member_headers(member["id"])), 200)
    set_logical_clock("2026-05-05T09:00:00Z")
    resub = validate_success(api.resubmit_application(
        app["id"], make_homeowner_headers(owner["id"])), 200)
    assert resub["applicant_hold_days"] == 3, "whole days in (2026-05-02, 2026-05-05]"

    set_logical_clock("2026-05-08T09:00:00Z")
    report = run_daily_sweep()
    assert report["applications_deemed_approved"] == 0, "elapsed 7 - hold 3 = 4 < 5"
    assert read_application(app["id"])["status"] == "UNDER_REVIEW"

    set_logical_clock("2026-05-09T09:00:00Z")
    report2 = run_daily_sweep()
    assert report2["applications_deemed_approved"] == 1, "elapsed 8 - hold 3 = 5 >= 5"
    assert read_application(app["id"])["status"] == "DEEMED_APPROVED"
