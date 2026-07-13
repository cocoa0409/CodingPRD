"""Consultant submittals: the dual review clock, the revision loop and the closed review desk."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_submittal, assert_instant_equals,
    state_payload, create_submittal_payload,
    make_consultant_rep_headers,
    setup_project, setup_project_with_consultant, register_consultant,
    lodge_submittal, start_submittal_review, set_clock, read_submittal,
)

MONDAY_0900 = "2026-06-01T09:00:00Z"
CALENDAR_DUE = "2026-06-15T09:00:00Z"   # 14 calendar days, weekends included
BUSINESS_DUE = "2026-06-19T09:00:00Z"   # 14 business days, both weekends skipped


class TestReviewDueDualVariant:

    def test_calendar_days_advances_by_fourteen_plain_days(self, api):
        """PRD §3.7: "On a `CALENDAR_DAYS` contract, `review_due_at` is simply the start instant
        advanced by that many periods of 24 hours, weekends included: a fourteen-day review begun on
        Monday 2026-06-01 at 09:00 UTC is due on 2026-06-15 at 09:00 UTC."
        PRD §3.7: "On success, `review_started_at` is stamped from the logical clock and
        `review_due_at` is computed from it."

        Design: Difficulty/dual_variant_calc/submittal_review_due_calendar_vs_business_days_diverges
        """
        bundle = setup_project_with_consultant(
            project_number="CAL-001", name="Calendar Court",
            capacity=2, review_clock_basis="CALENDAR_DAYS", submittal_review_period_days=14,
            with_architect=False,
        )
        submittal = lodge_submittal(bundle, spec_section="05 12 00")
        set_clock(MONDAY_0900)

        started = validate_success(
            api.set_submittal_state(
                submittal["id"], state_payload("UNDER_REVIEW"), bundle["pm_headers"]
            )
        )
        assert_submittal(started)
        assert started["status"] == "UNDER_REVIEW"
        assert_instant_equals(started["review_started_at"], MONDAY_0900, "review_started_at")
        assert_instant_equals(started["review_due_at"], CALENDAR_DUE, "review_due_at")

    def test_business_days_skips_both_weekends_and_diverges_from_calendar_days(self, api):
        """PRD §3.7: "On a `BUSINESS_DAYS` contract, the clock advances one 24-hour step at a time
        and only counts a step when the day it lands on is not a Saturday and not a Sunday,
        continuing until it has counted the required number of days; the time of day is carried
        through unchanged. The same fourteen-day review begun on Monday 2026-06-01 at 09:00 UTC is
        therefore due on 2026-06-19 at 09:00 UTC."
        PRD §3.7: "That due date is where the contract's `review_clock_basis` earns its keep,
        because the two bases give materially different answers from the same start."

        Design: Difficulty/dual_variant_calc/submittal_review_due_calendar_vs_business_days_diverges
        """
        firm = register_consultant(concurrent_review_capacity=2)
        firm_headers = make_consultant_rep_headers(firm["id"])

        calendar = setup_project_with_consultant(
            project_number="CAL-002", name="Calendar Close",
            capacity=2, review_clock_basis="CALENDAR_DAYS", submittal_review_period_days=14,
            with_architect=False,
        )
        business = setup_project_with_consultant(
            project_number="BUS-001", name="Business Barn",
            capacity=2, review_clock_basis="BUSINESS_DAYS", submittal_review_period_days=14,
            with_architect=False,
        )
        # Lodge one submittal on each project from the SAME firm, so only the contract's
        # review_clock_basis differs between the two review windows.
        cal_sub = validate_success(
            api.create_submittal(
                create_submittal_payload(calendar["project_id"], firm["id"],
                                         spec_section="05 12 00"),
                firm_headers,
            ),
            201,
        )
        bus_sub = validate_success(
            api.create_submittal(
                create_submittal_payload(business["project_id"], firm["id"],
                                         spec_section="05 12 00"),
                firm_headers,
            ),
            201,
        )
        set_clock(MONDAY_0900)

        cal_started = validate_success(
            api.set_submittal_state(
                cal_sub["id"], state_payload("UNDER_REVIEW"), calendar["pm_headers"]
            )
        )
        bus_started = validate_success(
            api.set_submittal_state(
                bus_sub["id"], state_payload("UNDER_REVIEW"), business["pm_headers"]
            )
        )

        assert_instant_equals(cal_started["review_started_at"], MONDAY_0900)
        assert_instant_equals(bus_started["review_started_at"], MONDAY_0900)
        assert_instant_equals(cal_started["review_due_at"], CALENDAR_DUE, "calendar review_due_at")
        assert_instant_equals(bus_started["review_due_at"], BUSINESS_DUE, "business review_due_at")

        assert cal_started["review_due_at"] != bus_started["review_due_at"], (
            "the same start instant and the same 14-day period must diverge across the two bases"
        )


class TestReviseAndResubmitCycle:

    def test_the_revision_loop_increments_revision_number_and_clears_the_window(self, api):
        """PRD §3.7: "On `REVISE_AND_RESUBMIT` the window is released by clearing both
        `review_started_at` and `review_due_at` back to null, and the ball returns to the consultant:
        the owning `ConsultantRep` — and only the firm named by the submittal's
        `consultant_firm_id`, on pain of `ERR_NOT_OWNER` — drives the submittal from
        `REVISE_AND_RESUBMIT` back to `RECEIVED`, which increments `revision_number` by 1 and clears
        `review_notes` back to null."

        Design: Difficulty/non_linear_state_machine/submittal_revise_and_resubmit_cycle_increments_revision_number
        """
        bundle = setup_project_with_consultant(
            project_number="CYC-001", name="Cycle Center",
            capacity=1, review_clock_basis="CALENDAR_DAYS", submittal_review_period_days=14,
            with_architect=False,
        )
        submittal = lodge_submittal(bundle, spec_section="05 12 00")
        assert submittal["status"] == "RECEIVED"
        assert submittal["revision_number"] == 0

        set_clock(MONDAY_0900)
        start_submittal_review(submittal["id"], bundle)

        validate_success(
            api.set_submittal_state(
                submittal["id"],
                state_payload("REVISE_AND_RESUBMIT", review_notes="Coordinate with MEP."),
                bundle["pm_headers"],
            )
        )

        resubmitted = validate_success(
            api.set_submittal_state(
                submittal["id"], state_payload("RECEIVED"), bundle["firm_headers"]
            )
        )
        assert_submittal(resubmitted)
        assert resubmitted["status"] == "RECEIVED"
        assert resubmitted["revision_number"] == 1
        assert resubmitted["review_notes"] is None
        assert resubmitted["review_started_at"] is None
        assert resubmitted["review_due_at"] is None

    def test_a_second_review_start_after_the_loop_restamps_a_fresh_window(self, api):
        """PRD §3.7: "That loop from `RECEIVED` through `UNDER_REVIEW` to `REVISE_AND_RESUBMIT` and
        back to `RECEIVED` is unbounded; a stubborn spec section may go round it many times."
        PRD §3.7: "On a `CALENDAR_DAYS` contract, `review_due_at` is simply the start instant
        advanced by that many periods of 24 hours, weekends included: a fourteen-day review begun on
        Monday 2026-06-01 at 09:00 UTC is due on 2026-06-15 at 09:00 UTC."

        Design: Difficulty/non_linear_state_machine/submittal_revise_and_resubmit_cycle_increments_revision_number
        """
        bundle = setup_project_with_consultant(
            project_number="CYC-002", name="Cycle Court",
            capacity=1, review_clock_basis="CALENDAR_DAYS", submittal_review_period_days=14,
            with_architect=False,
        )
        submittal = lodge_submittal(bundle, spec_section="05 12 00")

        set_clock(MONDAY_0900)
        start_submittal_review(submittal["id"], bundle)
        validate_success(
            api.set_submittal_state(
                submittal["id"],
                state_payload("REVISE_AND_RESUBMIT", review_notes="Coordinate with MEP."),
                bundle["pm_headers"],
            )
        )
        validate_success(
            api.set_submittal_state(
                submittal["id"], state_payload("RECEIVED"), bundle["firm_headers"]
            )
        )

        set_clock("2026-07-01T09:00:00Z")
        restarted = validate_success(
            api.set_submittal_state(
                submittal["id"], state_payload("UNDER_REVIEW"), bundle["pm_headers"]
            )
        )
        assert_submittal(restarted)
        assert restarted["status"] == "UNDER_REVIEW"
        assert restarted["revision_number"] == 1
        assert_instant_equals(restarted["review_started_at"], "2026-07-01T09:00:00Z")
        assert_instant_equals(restarted["review_due_at"], "2026-07-15T09:00:00Z")


class TestClosedReviewDeskCapacity:

    def test_a_second_review_touching_the_first_windows_due_instant_is_rejected(self, api):
        """PRD §3.7: "Two windows overlap when the new window's start is at or before the other's
        due instant **and** the other's start is at or before the new window's due instant. Note the
        asymmetry with the timesheet rule of §3.4: here the interval is closed, so windows that
        merely touch — a new review starting at precisely the instant an existing review is due —
        **do** collide and count against capacity. A firm at capacity rejects the start with
        `ERR_CONSULTANT_REVIEW_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/consultant_review_desk_closed_interval_capacity_rejects_touching_windows
        """
        bundle = setup_project_with_consultant(
            project_number="CAP-001", name="Capacity Cottage",
            capacity=1, review_clock_basis="CALENDAR_DAYS", submittal_review_period_days=14,
            with_architect=False,
        )
        first = lodge_submittal(bundle, spec_section="05 12 00")
        second = lodge_submittal(bundle, spec_section="05 21 00")

        set_clock(MONDAY_0900)
        started = start_submittal_review(first["id"], bundle)
        assert_instant_equals(started["review_started_at"], MONDAY_0900)
        assert_instant_equals(started["review_due_at"], CALENDAR_DUE)

        # The second review would start at exactly the first window's due instant. On a CLOSED
        # interval that is an overlap, and the firm's capacity of 1 is already taken.
        set_clock(CALENDAR_DUE)
        response = api.set_submittal_state(
            second["id"], state_payload("UNDER_REVIEW"), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_CONSULTANT_REVIEW_CAPACITY.value)

    def test_the_rejected_submittal_keeps_a_null_review_window(self, api):
        """PRD §3.7: "That desk holds at most `concurrent_review_capacity` submittals with
        overlapping windows. Starting a review is therefore rejected when the number of that firm's
        *other* submittals in status `UNDER_REVIEW` whose closed windows overlap the proposed one
        has already reached the firm's `concurrent_review_capacity`."
        PRD §3.7: "It arrives in status `RECEIVED` with `revision_number` at 0, `review_started_at`
        null, `review_due_at` null and `review_notes` null."

        Design: Difficulty/resource_temporal_overlap/consultant_review_desk_closed_interval_capacity_rejects_touching_windows
        """
        bundle = setup_project_with_consultant(
            project_number="CAP-002", name="Capacity Croft",
            capacity=1, review_clock_basis="CALENDAR_DAYS", submittal_review_period_days=14,
            with_architect=False,
        )
        first = lodge_submittal(bundle, spec_section="05 12 00")
        second = lodge_submittal(bundle, spec_section="05 21 00")

        set_clock(MONDAY_0900)
        start_submittal_review(first["id"], bundle)

        set_clock(CALENDAR_DUE)
        validate_error(
            api.set_submittal_state(
                second["id"], state_payload("UNDER_REVIEW"), bundle["pm_headers"]
            ),
            ApiErrorId.ERR_CONSULTANT_REVIEW_CAPACITY.value,
        )

        blocked = read_submittal(bundle, second["id"])
        assert_submittal(blocked)
        assert blocked["status"] == "RECEIVED"
        assert blocked["review_started_at"] is None
        assert blocked["review_due_at"] is None


class TestConsultantAvailability:

    def test_submittal_against_a_suspended_firm_is_rejected(self, api):
        """PRD §3.1: "A suspended firm may not have new submittals lodged against it; the attempt
        is rejected with `ERR_CONSULTANT_SUSPENDED`."
        PRD §3.7: "A submittal may not be lodged against a firm whose `status` is `SUSPENDED`
        (`ERR_CONSULTANT_SUSPENDED`)."

        Design: Corner/validations/submittal_from_suspended_consultant_is_rejected
        """
        bundle = setup_project(project_number="SUS-002", name="Suspended Consultant Co",
                               labor_budget_cents=500_000, with_architect=False)
        firm = register_consultant(
            name="Lapsed Loads", discipline="MEP",
            concurrent_review_capacity=2, status="SUSPENDED",
        )
        firm_headers = make_consultant_rep_headers(firm["id"])

        response = api.create_submittal(
            create_submittal_payload(bundle["project_id"], firm["id"], spec_section="23 05 00"),
            firm_headers,
        )
        validate_error(response, ApiErrorId.ERR_CONSULTANT_SUSPENDED.value)

        rows, meta = validate_paginated(
            api.list_submittals(firm_headers, params={"consultant_firm_id": firm["id"]})
        )
        assert meta["total_count"] == 0
        assert len(rows) == 0
