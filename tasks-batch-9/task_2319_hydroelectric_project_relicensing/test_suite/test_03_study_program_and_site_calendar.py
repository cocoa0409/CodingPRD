"""Resource-study review rounds, site fieldwork calendars and comment compensation."""
from test_helpers import (
    U_LICENSEE_A,
    api_client,
    assert_plan_counters,
    assert_postures,
    decide_plan,
    decide_study_review,
    leave_comment,
    make_agency_reviewer_headers,
    make_licensee_headers,
    move_fieldwork,
    new_study,
    read_comment,
    read_project,
    read_study,
    read_study_plan,
    report_study,
    resolve_comment,
    setup_agency_party,
    setup_plan_under_agency_review,
    setup_study_phase_project,
    study_payload,
    submit_plan,
    validate_error,
)

LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
HIGH_SENSITIVITY_SITE = dict(
    site_code="S9", river_mile=9.0, min_rest_buffer_days=14, cultural_sensitivity="HIGH"
)
BUFFERED_SITE = dict(
    site_code="S2", river_mile=7.5, min_rest_buffer_days=14, cultural_sensitivity="NONE"
)


def _attempt_study(study_plan_id, site_id, **overrides):
    """Create a study without pre-validating, so a rejection can be inspected."""
    return api_client.create_study(
        study_payload(study_plan_id, site_id, **overrides), LICENSEE_HEADERS
    )


class TestAdditionalReviewRounds:
    def _study_awaiting_first_decision(self):
        ctx = setup_plan_under_agency_review(
            study_overrides=dict(
                resource_category="WATER_QUALITY", study_title="Dissolved oxygen profile"
            ),
            site_overrides=dict(river_mile=6.0),
            project_name="Two Dimension Creek",
            installed_capacity_mw=12.0,
            license_expiration_date="2033-12-31",
        )
        ctx["agency_party"] = setup_agency_party(
            ctx["project"]["id"], party_name="State DEQ Reviewer"
        )
        move_fieldwork(ctx["study"]["id"], "START")
        move_fieldwork(ctx["study"]["id"], "COMPLETE")
        report_study(ctx["study"]["id"])
        return ctx

    def test_require_additional_drags_completed_fieldwork_back_into_progress(self):
        """One decision writes both status dimensions and counts the round.

        PRD §3.4: "A `decision` of `REQUIRE_ADDITIONAL` moves `review_status` `UNDER_REVIEW → ADDITIONAL_REQUIRED`, increments `additional_round_count` by 1, and — uniquely among the study transitions — reaches across dimensions to move `fieldwork_status` `COMPLETED → IN_PROGRESS` on the same row, because more data means more field effort."

        Design: Difficulty/non_linear_state_machine/resource_study_additional_round_writes_across_parallel_dimensions
        """
        ctx = self._study_awaiting_first_decision()

        after_first = decide_study_review(ctx["study"]["id"], "REQUIRE_ADDITIONAL")

        assert after_first["fieldwork_status"] == "IN_PROGRESS"
        assert after_first["review_status"] == "ADDITIONAL_REQUIRED"
        assert after_first["additional_round_count"] == 1

    def test_a_third_additional_round_is_refused_once_the_count_reaches_two(self):
        """The loop is capped at two rounds and the refused decision changes nothing.

        PRD §3.4: "The additional-study loop is bounded at two rounds: once `additional_round_count` has reached 2, a further `REQUIRE_ADDITIONAL` decision is rejected with `ERR_STUDY_STATE_INVALID`, forcing the reviewer either to accept or to leave the study unaccepted."

        Design: Difficulty/non_linear_state_machine/resource_study_additional_round_writes_across_parallel_dimensions
        """
        ctx = self._study_awaiting_first_decision()
        study_id = ctx["study"]["id"]
        decide_study_review(study_id, "REQUIRE_ADDITIONAL")
        move_fieldwork(study_id, "COMPLETE")
        report_study(study_id)
        after_second = decide_study_review(study_id, "REQUIRE_ADDITIONAL")
        assert after_second["additional_round_count"] == 2
        move_fieldwork(study_id, "COMPLETE")
        report_study(study_id)

        response = api_client.decide_study_review(
            study_id,
            {"decision": "REQUIRE_ADDITIONAL"},
            make_agency_reviewer_headers(ctx["agency_party"]["contact_user_id"]),
        )

        validate_error(response, "ERR_STUDY_STATE_INVALID", 409)
        unchanged = read_study(study_id)
        assert unchanged["additional_round_count"] == 2
        assert unchanged["review_status"] == "UNDER_REVIEW"
        assert unchanged["fieldwork_status"] == "COMPLETED"


class TestStudyCreationErrorPrecedence:
    def _plan_with_one_cultural_study(self):
        ctx = setup_study_phase_project(
            sites=[HIGH_SENSITIVITY_SITE],
            project_name="Sacred Reach",
            installed_capacity_mw=16.0,
            license_expiration_date="2033-12-31",
        )
        ctx["site"] = ctx["sites"][0]
        ctx["study"] = new_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="CULTURAL",
            study_title="Ethnographic survey",
            cultural_clearance_reference="THPO-2026-01",
        )
        return ctx

    def test_the_window_conflict_outranks_the_missing_cultural_clearance(self):
        """A request that breaks both rules answers with the temporal code, not the clearance one.

        PRD §2.12: "When a single request violates more than one rule, the response is determined by a fixed precedence ladder rather than by whichever check the implementation happens to reach first."
        PRD §2.12: "32. A study's buffered fieldwork window does not overlap another active study's buffered window at the same site — `ERR_SITE_WINDOW_CONFLICT` (409)."

        Design: Difficulty/priority_pair_validation_conflict/study_creation_window_conflict_precedes_cultural_clearance_error
        """
        ctx = self._plan_with_one_cultural_study()

        response = _attempt_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="RECREATION",
            study_title="Overlapping recreation survey",
            fieldwork_window_start="2026-10-14",
            fieldwork_window_end="2026-11-14",
        )

        validate_error(response, "ERR_SITE_WINDOW_CONFLICT", 409)

    def test_the_doubly_invalid_study_is_never_attached_to_the_plan(self):
        """The rejected creation leaves the plan carrying its single original study.

        PRD §3.4: "A study at a `HIGH`-sensitivity site without one is rejected with `ERR_CULTURAL_CLEARANCE_MISSING`."
        PRD §3.4: "Creation sets `fieldwork_status` `PLANNED` and `review_status` `NOT_SUBMITTED`, leaves `additional_round_count` at 0 and `report_submitted_at` and `report_submitted_by_user_id` unset, and increments the owning plan's `attached_study_count` and `version`."

        Design: Difficulty/priority_pair_validation_conflict/study_creation_window_conflict_precedes_cultural_clearance_error
        """
        ctx = self._plan_with_one_cultural_study()

        _attempt_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="RECREATION",
            study_title="Overlapping recreation survey",
            fieldwork_window_start="2026-10-14",
            fieldwork_window_end="2026-11-14",
        )

        assert read_study_plan(ctx["plan"]["id"])["attached_study_count"] == 1
        assert ctx["study"]["fieldwork_window_end"] == "2026-10-01"


class TestBufferedFieldworkWindowBoundary:
    def _site_occupied_through_the_buffer(self):
        ctx = setup_study_phase_project(
            sites=[BUFFERED_SITE],
            project_name="Buffer Reach",
            installed_capacity_mw=14.0,
            license_expiration_date="2033-12-31",
        )
        ctx["site"] = ctx["sites"][0]
        ctx["study_a"] = new_study(
            ctx["plan"]["id"], ctx["site"]["id"], study_title="Study A"
        )
        submit_plan(ctx["plan"]["id"])
        return ctx

    def test_the_last_buffer_day_conflicts_but_the_boundary_day_does_not(self):
        """A 14-day rest buffer blocks 2026-10-14 and releases the site on 2026-10-15.

        PRD §3.4: "Extend the new study's half-open window at its end by the site's `min_rest_buffer_days` to obtain its **buffered window**."
        PRD §3.4: "Two buffered windows that touch exactly at the boundary do not overlap, so a new window may begin on the very day a predecessor's buffer expires."

        Design: Difficulty/resource_temporal_overlap/study_site_half_open_window_plus_rest_buffer_boundary
        """
        ctx = self._site_occupied_through_the_buffer()

        inside_the_buffer = _attempt_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="WATER_QUALITY",
            study_title="Study B one day inside the buffer",
            fieldwork_window_start="2026-10-14",
            fieldwork_window_end="2026-11-14",
        )
        validate_error(inside_the_buffer, "ERR_SITE_WINDOW_CONFLICT", 409)

        touching = new_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="WATER_QUALITY",
            study_title="Study C touching the buffered boundary",
            fieldwork_window_start="2026-10-15",
            fieldwork_window_end="2026-11-15",
        )

        assert touching["fieldwork_status"] == "PLANNED"

    def test_a_completed_study_stops_occupying_its_original_window(self):
        """Occupancy is status-filtered, so a finished field effort frees the calendar.

        PRD §3.4: "That buffered window must not overlap the buffered window of any other study at the same site whose `fieldwork_status` is anything other than `COMPLETED` — a `PLANNED`, `IN_PROGRESS` or `SUSPENDED` study all continue to occupy the calendar, and a suspended study is emphatically not a vacancy."
        PRD §3.4: "Each of the four increments the study's `version` and touches `fieldwork_status` alone — `review_status` is never modified by a fieldwork action."

        Design: Difficulty/resource_temporal_overlap/study_site_half_open_window_plus_rest_buffer_boundary
        """
        ctx = self._site_occupied_through_the_buffer()
        new_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="WATER_QUALITY",
            study_title="Study C touching the buffered boundary",
            fieldwork_window_start="2026-10-15",
            fieldwork_window_end="2026-11-15",
        )
        move_fieldwork(ctx["study_a"]["id"], "START")
        completed = move_fieldwork(ctx["study_a"]["id"], "COMPLETE")

        reused = new_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="RECREATION",
            study_title="Study D reusing the freed window",
            fieldwork_window_start="2026-09-10",
            fieldwork_window_end="2026-09-20",
        )

        assert completed["fieldwork_status"] == "COMPLETED"
        assert completed["review_status"] == "NOT_SUBMITTED"
        assert reused["fieldwork_status"] == "PLANNED"
        assert read_study_plan(ctx["plan"]["id"])["attached_study_count"] == 3


class TestDeferredCommentReopening:
    def _plan_with_one_mandatory_comment(self):
        ctx = setup_study_phase_project(
            sites=[dict(river_mile=2.5)],
            project_name="Reopen Reach",
            installed_capacity_mw=10.0,
            license_expiration_date="2033-12-31",
        )
        ctx["site"] = ctx["sites"][0]
        new_study(
            ctx["plan"]["id"],
            ctx["site"]["id"],
            resource_category="CULTURAL",
            study_title="Ethnographic overview",
            cultural_clearance_reference="THPO-2026-09",
        )
        ctx["agency_party"] = setup_agency_party(ctx["project"]["id"])
        ctx["comment"] = leave_comment(
            ctx["plan"]["id"],
            ctx["agency_party"],
            resource_category="CULTURAL",
            comment_text="Add a tribal monitoring protocol",
            is_mandatory_condition=True,
        )
        ctx["plan"] = submit_plan(ctx["plan"]["id"])
        return ctx

    def test_deferring_the_mandatory_comment_relaxes_plan_and_project(self):
        """Resolution as DEFERRED zeroes both plan counters and returns the project to OPEN.

        PRD §3.3: "Resolution stores the supplied `disposition` and stamps `resolved_at` with the logical clock; it decrements the plan's `open_comment_count` and, when the comment was mandatory, also the plan's `unresolved_mandatory_comment_count`, incrementing the plan's `version`; and it recomputes the project's `unresolved_mandatory_comment_count` and then `regulatory_posture`, which returns a project from `RESTRICTED` to `OPEN` once the count reaches zero and nothing else restricts it."

        Design: Difficulty/compensating_invariant/comment_reopen_restores_plan_counters_and_project_posture
        """
        ctx = self._plan_with_one_mandatory_comment()
        assert_plan_counters(ctx["plan"], open_comment_count=1, unresolved_mandatory_comment_count=1)
        before = read_project(ctx["project"]["id"])
        assert before["unresolved_mandatory_comment_count"] == 1
        assert_postures(before, regulatory_posture="RESTRICTED")

        resolved = resolve_comment(
            ctx["comment"]["id"],
            "DEFERRED",
            resolution_note="Deferred to the settlement process",
        )

        assert resolved["resolution_status"] == "RESOLVED"
        assert resolved["disposition"] == "DEFERRED"
        assert_plan_counters(
            read_study_plan(ctx["plan"]["id"]),
            open_comment_count=0,
            unresolved_mandatory_comment_count=0,
        )
        during = read_project(ctx["project"]["id"])
        assert during["unresolved_mandatory_comment_count"] == 0
        assert_postures(during, regulatory_posture="OPEN")

    def test_require_revision_with_reopen_restores_the_counters_and_the_posture(self):
        """The compensating sweep restores 1/1, clears the disposition and re-restricts the project.

        PRD §3.3: "When `reopen_deferred_comments` is true, it also performs a compensating sweep over the plan's comments: every comment whose `resolution_status` is `RESOLVED` and whose `disposition` is `DEFERRED` goes back `RESOLVED → OPEN`, has its `disposition` cleared to unset, and has its `reopen_count` incremented by 1."
        PRD §3.3: "That reopening recomputes the plan's `open_comment_count` and `unresolved_mandatory_comment_count`, which recompute the project's `unresolved_mandatory_comment_count`, which recomputes `regulatory_posture` — taking a project from `OPEN` back to `RESTRICTED` when the restored count is greater than zero."

        Design: Difficulty/compensating_invariant/comment_reopen_restores_plan_counters_and_project_posture
        """
        ctx = self._plan_with_one_mandatory_comment()
        resolve_comment(
            ctx["comment"]["id"],
            "DEFERRED",
            resolution_note="Deferred to the settlement process",
        )

        revised = decide_plan(
            ctx["plan"]["id"],
            "REQUIRE_REVISION",
            reopen_deferred_comments=True,
            determination_note="Deferral not acceptable",
        )

        assert revised["status"] == "REVISION_REQUIRED"
        assert revised["revision_round"] == 1
        assert_plan_counters(
            revised,
            open_comment_count=1,
            unresolved_mandatory_comment_count=1,
            attached_study_count=1,
        )
        reopened = read_comment(ctx["comment"]["id"])
        assert reopened["resolution_status"] == "OPEN"
        assert reopened["disposition"] is None
        assert reopened["reopen_count"] == 1
        after = read_project(ctx["project"]["id"])
        assert after["unresolved_mandatory_comment_count"] == 1
        assert_postures(after, regulatory_posture="RESTRICTED")
