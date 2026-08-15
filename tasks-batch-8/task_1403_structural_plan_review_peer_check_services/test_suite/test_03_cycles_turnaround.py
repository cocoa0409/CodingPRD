"""Review cycles: opening, single-slot exclusion, supersession, turnaround
SLA variants (BUSINESS vs CALENDAR, expedite halving), and on-time evaluation
boundaries (PRD §3.3, §2.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_timestamp_equals,
    assign_cycle,
    get_cycle,
    get_engagement,
    issue_comments,
    make_applicant_headers,
    make_engagement,
    make_jurisdiction,
    make_reviewer,
    make_reviewer_headers,
    open_cycle,
    raise_comment,
    set_clock,
    setup_in_review_cycle,
    setup_registered_engagement,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestBusinessVsCalendarSla:
    def _setup_pair(self, api):
        jur_biz = make_jurisdiction(state_code="CA", sla_mode="BUSINESS",
                                    turnaround_days=15)
        jur_cal = make_jurisdiction(state_code="NV", sla_mode="CALENDAR",
                                    turnaround_days=15)
        rev = make_reviewer(
            name="R Two", state_code="CA",
            extra_licenses=[{"state_code": "NV", "license_type": "PE",
                             "license_number": "P3", "expires_on": "2030-01-01"}])
        eng_biz = make_engagement(jur_biz, rev, project_name="Biz SLA")
        eng_cal = make_engagement(jur_cal, rev, project_name="Cal SLA")
        set_clock("2026-08-03T10:00:00Z")
        cyc_biz = open_cycle(eng_biz["id"], documents_ref="s3://biz-v1")
        cyc_cal = open_cycle(eng_cal["id"], documents_ref="s3://cal-v1")
        return cyc_biz, cyc_cal

    def test_business_mode_skips_weekends_and_lands_end_of_day(self, api):
        """PRD §3.3: "Under the `BUSINESS` mode, the count starts from the
        calendar date of `received_at` — the received day itself is never
        counted — and advances one calendar day at a time, skipping over every
        Saturday and Sunday, until the effective number of business days has
        been counted; `due_at` is then end-of-day `23:59:59.999Z` on that final
        day, at millisecond precision."

        Design: Difficulty/dual_variant_calc/turnaround_business_vs_calendar_due_at
        """
        cyc_biz, cyc_cal = self._setup_pair(api)
        # 15th business day after Mon 2026-08-03 is Mon 2026-08-24
        assert_timestamp_equals(cyc_biz["due_at"], "2026-08-24T23:59:59.999Z",
                                "BUSINESS due_at")
        assert_timestamp_equals(cyc_biz["received_at"], "2026-08-03T10:00:00Z",
                                "received_at")

    def test_calendar_mode_adds_plain_24h_periods(self, api):
        """PRD §3.3: "Under the `CALENDAR` mode, `due_at` is simply
        `received_at` plus the effective number of 24-hour periods, preserving
        the time of day."
        PRD §3.3: "Business mode therefore always yields a strictly later
        deadline than calendar mode for the same receipt instant and day
        count."

        Design: Difficulty/dual_variant_calc/turnaround_business_vs_calendar_due_at
        """
        cyc_biz, cyc_cal = self._setup_pair(api)
        assert_timestamp_equals(cyc_cal["due_at"], "2026-08-18T10:00:00Z",
                                "CALENDAR due_at")
        assert cyc_biz["due_at"] != cyc_cal["due_at"]


class TestCycleInitialState:
    def test_cycle_starts_in_open_with_computed_due_at(self, api):
        """PRD §3.3: "The cycle's `received_at` is stamped from the logical
        clock at creation, and the new cycle is born `OPEN`."
        PRD §3.3: "Cycle numbering is 1-based and monotonic per engagement —
        the engagement's `cycle_count` increments and the new cycle's
        `cycle_number` takes that value."
        PRD §3.3: "Until completion, both `completed_at` and `is_on_time` are
        null."
        PRD §3.3: "Opening the first cycle walks the engagement `REGISTERED →
        IN_PROGRESS`."

        Design: Corner/state_machines/cycle_starts_in_open_with_computed_due_at
        """
        bundle = setup_registered_engagement(
            jur_overrides={"sla_mode": "CALENDAR"})
        set_clock("2026-08-03T10:00:00Z")
        resp = api.create_cycle(
            {"engagement_id": bundle["engagement"]["id"],
             "documents_ref": "s3://init-v1"}, COORD)
        cyc = validate_success(resp, 201)
        assert cyc["status"] == "OPEN"
        assert cyc["cycle_number"] == 1
        assert_timestamp_equals(cyc["received_at"], "2026-08-03T10:00:00Z")
        assert_timestamp_equals(cyc["due_at"], "2026-08-18T10:00:00Z")
        assert cyc["completed_at"] is None
        assert cyc["is_on_time"] is None
        assert get_engagement(bundle["engagement"]["id"])["status"] == "IN_PROGRESS"


class TestExpediteSla:
    def test_expedite_halves_business_sla_with_ceil(self, api):
        """PRD §3.3: "The cycle's `due_at` is computed at creation from the
        pinned turnaround policy and the engagement's expedite flag, in a
        pinned order: first the effective day count is derived — when
        `requested_expedite` is set, half of `pinned_turnaround_days` rounded
        *up* to a whole number of days; otherwise `pinned_turnaround_days`
        unchanged — and only then is the day-counting mode applied."

        Design: Corner/calculations/expedite_halves_business_sla_with_ceil
        """
        bundle = setup_registered_engagement(
            jur_overrides={"sla_mode": "BUSINESS", "turnaround_days": 15},
            eng_overrides={"requested_expedite": True})
        set_clock("2026-08-03T10:00:00Z")
        cyc = open_cycle(bundle["engagement"]["id"], documents_ref="s3://exp-v1")
        # ceil(15/2) = 8 business days from Mon 2026-08-03 -> Thu 2026-08-13 EOD
        assert_timestamp_equals(cyc["due_at"], "2026-08-13T23:59:59.999Z")


class TestOnTimeBoundary:
    def _setup_due_boundary_cycle(self, api):
        bundle = setup_registered_engagement(
            jur_overrides={"sla_mode": "BUSINESS", "turnaround_days": 15})
        rev = bundle["reviewer"]
        set_clock("2026-08-03T10:00:00Z")
        cyc = open_cycle(bundle["engagement"]["id"], documents_ref="s3://edge-v1")
        assign_cycle(cyc, rev["id"])
        raise_comment(cyc["id"], rev["id"], code_section_ref="1607.1",
                      comment_text="Live load reduction unsupported")
        return bundle, cyc

    def test_on_time_boundary_completed_exactly_at_due_at(self, api):
        """PRD §3.3: "At completion, `completed_at` is stamped from the logical
        clock and `is_on_time` is computed as whether `completed_at` is no
        later than `due_at` — an exact tie counts as on time."

        Design: Difficulty/boundary_precision_check/on_time_boundary_completed_exactly_at_due_at
        """
        bundle, cyc = self._setup_due_boundary_cycle(api)
        set_clock("2026-08-24T23:59:59.999Z")
        resp = api.issue_comments(
            cyc["id"], make_reviewer_headers(bundle["reviewer"]["id"]))
        done = validate_success(resp, 200)
        assert_timestamp_equals(done["due_at"], "2026-08-24T23:59:59.999Z")
        assert_timestamp_equals(done["completed_at"], "2026-08-24T23:59:59.999Z")
        assert done["is_on_time"] is True

    def test_on_time_boundary_is_inclusive_not_strict(self, api):
        """PRD §3.3: "At completion, `completed_at` is stamped from the logical
        clock and `is_on_time` is computed as whether `completed_at` is no
        later than `due_at` — an exact tie counts as on time."

        Design: Difficulty/boundary_precision_check/on_time_boundary_completed_exactly_at_due_at
        """
        bundle, cyc = self._setup_due_boundary_cycle(api)
        set_clock("2026-08-24T23:59:59.999Z")
        api.issue_comments(cyc["id"], make_reviewer_headers(bundle["reviewer"]["id"]))
        fetched = get_cycle(cyc["id"])
        assert fetched["status"] == "COMMENTS_ISSUED"
        assert fetched["is_on_time"] is True

    def test_late_completion_sets_is_on_time_false(self, api):
        """PRD §3.3: "At completion, `completed_at` is stamped from the logical
        clock and `is_on_time` is computed as whether `completed_at` is no
        later than `due_at` — an exact tie counts as on time."

        Design: Corner/calculations/late_completion_sets_is_on_time_false
        """
        bundle = setup_registered_engagement(
            jur_overrides={"sla_mode": "CALENDAR", "turnaround_days": 15})
        rev = bundle["reviewer"]
        set_clock("2026-08-03T10:00:00Z")
        cyc = open_cycle(bundle["engagement"]["id"], documents_ref="s3://late-v1")
        assign_cycle(cyc, rev["id"])
        raise_comment(cyc["id"], rev["id"], code_section_ref="1607.1",
                      comment_text="Roof live load not shown")
        set_clock("2026-08-18T10:00:01Z")  # one second past due
        resp = api.issue_comments(cyc["id"], make_reviewer_headers(rev["id"]))
        done = validate_success(resp, 200)
        assert_timestamp_equals(done["due_at"], "2026-08-18T10:00:00Z")
        assert done["is_on_time"] is False


class TestCycleSlotExclusion:
    def _setup(self, api):
        bundle = setup_registered_engagement(
            jur_overrides={"sla_mode": "CALENDAR"})
        cyc1 = open_cycle(bundle["engagement"]["id"], documents_ref="s3://slot-v1")
        return bundle, cyc1

    def test_second_cycle_rejected_while_open_or_in_review(self, api):
        """PRD §3.3: "Cycles are strictly single-slot. If the engagement
        already has an `OPEN` or `IN_REVIEW` cycle, opening another is rejected
        with `ERR_CYCLE_STILL_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/cycle_slot_strict_exclusion_with_adjacent_handoff
        """
        bundle, cyc1 = self._setup(api)
        # Collision against the OPEN cycle
        resp = api.create_cycle(
            {"engagement_id": bundle["engagement"]["id"],
             "documents_ref": "s3://slot-v1b"}, COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_STILL_ACTIVE, 409)
        # Now IN_REVIEW; collision again
        assign_cycle(cyc1, bundle["reviewer"]["id"])
        resp = api.create_cycle(
            {"engagement_id": bundle["engagement"]["id"],
             "documents_ref": "s3://slot-v1c"}, COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_STILL_ACTIVE, 409)
        assert get_cycle(cyc1["id"])["status"] == "IN_REVIEW"

    def test_comments_issued_cycle_hands_off_atomically(self, api):
        """PRD §3.3: "If the previous cycle rests at `COMMENTS_ISSUED`, the new
        cycle supersedes it: the old cycle moves `COMMENTS_ISSUED → SUPERSEDED`
        — a terminal state, like `APPROVED` and `CANCELLED` — and any `ACTIVE`
        assignments on it move to `COMPLETED`."

        Design: Difficulty/resource_temporal_overlap/cycle_slot_strict_exclusion_with_adjacent_handoff
        """
        bundle, cyc1 = self._setup(api)
        assign_cycle(cyc1, bundle["reviewer"]["id"])
        raise_comment(cyc1["id"], bundle["reviewer"]["id"],
                      code_section_ref="1613.1",
                      comment_text="Seismic design category misstated")
        issue_comments(cyc1["id"], bundle["reviewer"]["id"])
        resp = api.create_cycle(
            {"engagement_id": bundle["engagement"]["id"],
             "documents_ref": "s3://slot-v2"}, COORD)
        cyc2 = validate_success(resp, 201)
        assert cyc2["status"] == "OPEN"
        assert cyc2["cycle_number"] == 2
        assert get_cycle(cyc1["id"])["status"] == "SUPERSEDED"


class TestCycleNumbering:
    def test_cycle_numbers_monotonic_across_resubmittals(self, api):
        """PRD §3.3: "Cycle numbering is 1-based and monotonic per engagement —
        the engagement's `cycle_count` increments and the new cycle's
        `cycle_number` takes that value — and numbers are never reused, even
        after cancellations."

        Design: Corner/calculations/cycle_numbers_monotonic_across_resubmittals
        """
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        cyc1 = bundle["cycle"]
        raise_comment(cyc1["id"], rev["id"], code_section_ref="1604.3",
                      comment_text="Base plate thickness missing")
        issue_comments(cyc1["id"], rev["id"])
        cyc2 = open_cycle(bundle["engagement"]["id"], documents_ref="s3://num-v2")
        assert get_cycle(cyc1["id"])["cycle_number"] == 1
        assert cyc2["cycle_number"] == 2
        assert get_engagement(bundle["engagement"]["id"])["cycle_count"] == 2


class TestResponseWindowClosedAfterSupersession:
    def test_response_after_cycle_superseded_rejected(self, api):
        """PRD §3.5: "Posting a response with `response_text` requires the
        comment to be `OPEN` or `REOPENED` and the engagement's current
        non-terminal cycle to be `COMMENTS_ISSUED`; a violation of either
        condition is rejected with `ERR_COMMENT_NOT_AWAITING_RESPONSE`."

        Design: Corner/validations/response_after_cycle_superseded_rejected
        """
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        com = raise_comment(bundle["cycle"]["id"], rev["id"],
                            code_section_ref="1604.3",
                            comment_text="strap schedule missing")
        issue_comments(bundle["cycle"]["id"], rev["id"])
        # Resubmittal supersedes the letter cycle; new cycle is OPEN.
        open_cycle(bundle["engagement"]["id"], documents_ref="s3://rw-v2")
        resp = api.create_response(com["id"], {"response_text": "too late"},
                                   make_applicant_headers("app-1"))
        validate_error(resp, ApiErrorId.ERR_COMMENT_NOT_AWAITING_RESPONSE, 409)
        from test_helpers import get_comment
        assert get_comment(com["id"])["status"] == "OPEN"
