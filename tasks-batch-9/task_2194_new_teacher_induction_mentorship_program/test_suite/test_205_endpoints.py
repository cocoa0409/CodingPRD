"""Endpoint surfaces: the immutable-config CRUD triple, an action endpoint with two
outcomes on one row, a junction creation, a computed read and a conditional action.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_COHORT_MISMATCH,
    ERR_MATCH_STATE_INVALID,
    ERR_NOVICE_NOT_FOUND,
    ERR_OBSERVATION_PHASE_INVALID,
)
from test_helpers.assertions import (
    assert_ascending_by,
    assert_four_decimals,
    assert_immutable_system_fields,
    assert_instant_equals,
    assert_pagination_defaults,
    assert_two_decimals,
    ids_of,
)
from test_helpers.constants import CLOCK_INITIAL_UTC
from test_helpers.fixtures import (
    build_program,
    create_cohort,
    create_novice,
    create_site,
    define_milestone,
    document_observation_cycle,
    open_observation_cycle,
    read_cycle,
    read_match,
    read_mentor,
    read_novice,
    read_session,
    read_site,
    schedule_seminar_session,
    set_clock,
    submit_and_verify_contact_log,
)
from test_helpers.test_users import (
    ADMIN,
    make_mentor_headers,
    make_novice_headers,
    make_site_lead_headers,
)

FEEDBACK_NARRATIVE = (
    "The novice opened with a clearly posted objective, circulated purposefully "
    "during independent practice, and used exit ticket data to close the lesson "
    "with targeted reteaching for the small group that struggled with proportional "
    "reasoning."
)


class TestMilestoneConfigurationSurface:
    """Create, read and list is the whole surface of the config entity."""

    def test_milestone_create_read_and_reverse_filtered_list(
        self, api: InductionApiClient
    ):
        """The read echoes every threshold, the filter reverses the prerequisite edge.

        The PRD fixes the ordering and the two available filters: "Milestone
        listings are returned in `sequence_index` ascending order and may be
        narrowed by `prerequisite_milestone_id` or by
        `gates_license_recommendation`."

        Design: Corner/endpoints/milestone_create_read_and_reverse_filtered_list
        """
        root = define_milestone(
            api,
            "IND_M1",
            1,
            title="Orientation complete",
            gates_license_recommendation=False,
        )
        dependent = define_milestone(
            api,
            "IND_M2",
            2,
            title="Mid-year review complete",
            required_contact_minutes=300,
            required_observation_cycles=1,
            required_credited_seminars=1,
            license_stage_unlocked="CLEAR",
            gates_license_recommendation=True,
            prerequisite_milestone_id=root["id"],
        )

        read_response = api.get_milestone(dependent["id"], ADMIN)
        stored = validate_success(read_response)
        assert read_response.json()["response_type"] == "object", (
            "a single-row read carries the object envelope"
        )
        assert stored["code"] == "IND_M2"
        assert stored["sequence_index"] == 2
        assert stored["required_contact_minutes"] == 300
        assert stored["required_observation_cycles"] == 1
        assert stored["required_credited_seminars"] == 1
        assert stored["license_stage_unlocked"] == "CLEAR"
        assert stored["gates_license_recommendation"] is True
        assert stored["prerequisite_milestone_id"] == root["id"], (
            f"the edge is stored as supplied, got {stored['prerequisite_milestone_id']}"
        )
        assert_immutable_system_fields(stored)

        filtered_response = api.list_milestones(
            ADMIN, {"prerequisite_milestone_id": root["id"]}
        )
        filtered, filtered_meta = validate_paginated(filtered_response)
        assert filtered_response.json()["response_type"] == "array", (
            "a list read carries the array envelope"
        )
        assert filtered_meta["total_count"] == 1, (
            "the reverse lookup returns only the dependent milestone, got "
            f"{filtered_meta['total_count']}"
        )
        assert ids_of(filtered) == [dependent["id"]]

        unfiltered_response = api.list_milestones(ADMIN)
        rows, meta = validate_paginated(unfiltered_response)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert_pagination_defaults(meta)
        assert ids_of(rows)[0] == root["id"], (
            f"the list is ordered by sequence_index ascending, got {ids_of(rows)}"
        )
        assert_ascending_by(rows, "sequence_index")
        for response in (read_response, filtered_response, unfiltered_response):
            envelope_meta = response.json()["meta"]
            assert envelope_meta.get("api_request_id"), "every response is traceable"
            assert envelope_meta.get("api_request_timestamp"), (
                "every response is timestamped"
            )


class TestMatchRejectionAction:
    """One action endpoint, two outcomes on the same row."""

    def test_match_reject_action_releases_novice_and_blocks_repeat(
        self, api: InductionApiClient, proposed_program: dict
    ):
        """Rejection hands the novice back and the identical second call is refused.

        The PRD describes the release precisely: "Rejection requires a `reason`,
        stamps `ended_at` from the logical clock and `end_reason` from that reason,
        and returns the novice from `MATCHED` to `ENROLLED` when no other match of
        that novice remains in `PROPOSED`, `ACTIVE` or `SUSPENDED`."

        Design: Corner/endpoints/match_reject_action_releases_novice_and_blocks_repeat
        """
        program = proposed_program
        reason = "Novice reassigned to a same-subject mentor at the receiving site"

        rejected = validate_success(
            api.dispose_match(
                program["match_id"], f.disposition_payload("REJECT", reason=reason), ADMIN
            )
        )
        assert rejected["match_status"] == "REJECTED"
        assert_instant_equals(rejected["ended_at"], CLOCK_INITIAL_UTC, "ended_at")
        assert rejected["end_reason"] == reason, (
            f"the supplied reason becomes the end reason, got {rejected['end_reason']}"
        )
        assert rejected["version"] == 2, (
            f"one mutation since creation, got version {rejected['version']}"
        )
        assert rejected["activated_at"] is None, (
            f"a rejected match was never activated, got {rejected['activated_at']}"
        )
        assert rejected["pinned_stipend_rate_cents_per_hour"] is None, (
            "the rate is pinned only by activation, got "
            f"{rejected['pinned_stipend_rate_cents_per_hour']}"
        )

        assert read_novice(api, program["novice_id"])["program_status"] == "ENROLLED", (
            "no other live match remains, so the novice returns to ENROLLED"
        )
        assert read_mentor(api, program["mentor_id"])["active_caseload_count"] == 0, (
            "a rejection never touched the caseload"
        )
        assert read_site(api, program["site_id"])["active_match_count"] == 0

        repeat = api.dispose_match(
            program["match_id"],
            f.disposition_payload("REJECT", reason="Duplicate rejection filed by the site office"),
            ADMIN,
        )
        validate_error(repeat, ERR_MATCH_STATE_INVALID, 409)
        assert read_match(api, program["match_id"])["version"] == 2, (
            "the refused repeat mutated nothing"
        )


class TestSeminarAttendanceJunction:
    """The junction row demands that both ends resolve and agree on cohort."""

    def test_seminar_attendance_links_session_and_novice_of_same_cohort(
        self, api: InductionApiClient
    ):
        """A foreign-cohort novice, an unknown novice and the cohort's own novice.

        The PRD states the agreement rule for the junction: "The novice must belong
        to the cohort that owns the session, or the row is refused with
        `ERR_COHORT_MISMATCH`."

        Design: Corner/endpoints/seminar_attendance_links_session_and_novice_of_same_cohort
        """
        site = create_site(api)
        north = create_cohort(api, name="Induction North 2026-27", region_code="NORTH")
        south = create_cohort(api, name="Induction South 2026-27", region_code="SOUTH")
        lead = make_site_lead_headers(site["id"])
        own_novice = create_novice(api, site["id"], north["id"], full_name="Dana Pike")
        foreign_novice = create_novice(
            api, site["id"], south["id"], full_name="Ira Vance", subject_area="ELA"
        )
        session = schedule_seminar_session(
            api,
            north["id"],
            1,
            "2026-08-05T15:00:00Z",
            "2026-08-05T17:00:00Z",
            topic="Classroom routines and equitable participation",
        )

        mismatched = api.create_attendance(
            f.attendance_payload(session["id"], foreign_novice["id"], "PRESENT", 120), lead
        )
        validate_error(mismatched, ERR_COHORT_MISMATCH, 422)

        unknown = api.create_attendance(
            f.attendance_payload(session["id"], NON_EXISTENT_UUID, "PRESENT", 120), lead
        )
        validate_error(unknown, ERR_NOVICE_NOT_FOUND, 404)

        row = validate_success(
            api.create_attendance(
                f.attendance_payload(session["id"], own_novice["id"], "PRESENT", 120), lead
            ),
            201,
        )
        assert_four_decimals(row["credit_ratio"], 1.0000, "credit_ratio")
        assert row["credited"] is True, (
            f"a full-length present row is credited, got {row['credited']}"
        )
        assert row["recorded_by_user_id"] == site["id"], (
            f"the acting lead is recorded, got {row['recorded_by_user_id']}"
        )

        stored_session = read_session(api, session["id"])
        assert stored_session["credited_attendance_count"] == 1
        assert stored_session["status"] == "SCHEDULED", (
            "attendance is taken before the session is closed out, got "
            f"{stored_session['status']}"
        )

        rows, meta = validate_paginated(
            api.list_attendances(ADMIN, {"session_id": session["id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the accepted row exists, got total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [row["id"]]
        assert read_novice(api, foreign_novice["id"])["credited_seminar_sessions"] == 0, (
            "the refused link left no row behind"
        )


class TestReadinessComputedRead:
    """The computed read must agree with the formula term by term."""

    def test_readiness_computed_read_exposes_components_and_denominator_floor(
        self, api: InductionApiClient
    ):
        """240 minutes and one documented cycle give 33.00 with the denominator at 1.

        The PRD floors the seminar denominator so the arithmetic is always defined:
        "Third, the seminar denominator is `held_sessions` less `excused_sessions`,
        floored at 1 so the arithmetic never divides by zero — this is where an
        excused absence pays off, by shrinking the denominator rather than counting
        as a miss."

        Design: Corner/endpoints/readiness_computed_read_exposes_components_and_denominator_floor
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-15T12:00:00Z")
        submit_and_verify_contact_log(
            api,
            program["match_id"],
            program["mentor_id"],
            "2026-08-03T09:00:00Z",
            minutes=180,
            contact_type="ONE_ON_ONE",
            verifier=lead,
            description=(
                "Weekly one-on-one planning conference with the novice teacher and "
                "formative data review"
            ),
        )
        submit_and_verify_contact_log(
            api,
            program["match_id"],
            program["mentor_id"],
            "2026-08-04T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            verifier=lead,
            description="Follow-up one-on-one conference on assessment design",
        )
        cycle = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
        )
        document_observation_cycle(
            api, cycle["id"], program["mentor_id"], program["site_id"]
        )

        response = api.get_readiness(
            program["novice_id"], make_novice_headers(program["novice_id"])
        )
        readiness = validate_success(response)
        assert response.json()["response_type"] == "object"
        assert readiness["novice_id"] == program["novice_id"]
        assert_two_decimals(readiness["readiness_index_live"], 33.00, "readiness_index_live")
        assert_four_decimals(readiness["contact_component"], 0.4000, "contact_component")
        assert_four_decimals(
            readiness["observation_component"], 0.5000, "observation_component"
        )
        assert_four_decimals(readiness["seminar_component"], 0.0000, "seminar_component")
        assert readiness["held_sessions"] == 0, (
            f"no session has been held, got {readiness['held_sessions']}"
        )
        assert readiness["excused_sessions"] == 0
        assert readiness["seminar_denominator"] == 1, (
            f"the denominator is floored at one and never zero, got "
            f"{readiness['seminar_denominator']}"
        )
        assert_two_decimals(
            readiness["readiness_index_snapshot"], 0.00, "readiness_index_snapshot"
        )
        assert readiness["snapshot_source_attainment_id"] is None, (
            "no milestone has been attained, so nothing froze the evidence"
        )
        assert readiness["meets_readiness_gate"] is False, (
            f"33.00 sits below the gate, got {readiness['meets_readiness_gate']}"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["verified_contact_minutes"] == 240
        assert novice["documented_observation_cycles"] == 1


class TestFeedbackPhaseGating:
    """One endpoint, two different phase predicates keyed on the submit flag."""

    def test_feedback_submission_allowed_only_in_post_conference_phase(
        self, api: InductionApiClient
    ):
        """Drafting is legal at OBSERVED; submitting is not until POST_CONFERENCE.

        The PRD gives the draft path the wider predicate: "With `submit` false and
        the dimension at `NONE`, the write parks a draft: the dimension becomes
        `DRAFT`, and the phase must be either `OBSERVED` or `POST_CONFERENCE`."
        Submission is narrower — the three routes into `SUBMITTED` "all three of
        these require the phase to be exactly `POST_CONFERENCE` and enforce the
        completeness rules above, replacing the stored `narrative`,
        `growth_area_codes` and `rubric_scores` from the request body and
        recomputing `composite_rubric_score`."

        Design: Corner/endpoints/feedback_submission_allowed_only_in_post_conference_phase
        """
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        set_clock(api, "2026-08-15T12:00:00Z")
        cycle = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
        )
        draft_body = f.feedback_payload(
            submit=False,
            narrative=FEEDBACK_NARRATIVE,
            growth_area_codes=["PLANNING"],
            rubric_scores={
                "planning": 2,
                "instruction": 2,
                "environment": 2,
                "assessment": 2,
            },
        )
        submit_body = f.feedback_payload(
            submit=True,
            narrative=FEEDBACK_NARRATIVE,
            growth_area_codes=["PLANNING", "INSTRUCTION"],
            rubric_scores={
                "planning": 4,
                "instruction": 4,
                "environment": 4,
                "assessment": 3,
            },
        )

        too_early = api.write_feedback(cycle["id"], draft_body, mentor_headers)
        validate_error(too_early, ERR_OBSERVATION_PHASE_INVALID, 409)

        observed = validate_success(
            api.advance_cycle(cycle["id"], f.advance_payload("OBSERVED"), mentor_headers)
        )
        assert observed["phase"] == "OBSERVED"
        assert observed["feedback_review_status"] == "NONE"

        drafted = validate_success(api.write_feedback(cycle["id"], draft_body, mentor_headers))
        assert drafted["feedback_review_status"] == "DRAFT"
        assert_two_decimals(drafted["composite_rubric_score"], 2.00, "composite_rubric_score")
        assert drafted["phase"] == "OBSERVED", (
            f"the two dimensions move independently, got phase {drafted['phase']}"
        )

        premature_submit = api.write_feedback(cycle["id"], submit_body, mentor_headers)
        validate_error(premature_submit, ERR_OBSERVATION_PHASE_INVALID, 409)
        unchanged = read_cycle(api, cycle["id"])
        assert unchanged["feedback_review_status"] == "DRAFT", (
            "the refused submission stored nothing, got "
            f"{unchanged['feedback_review_status']}"
        )
        assert_two_decimals(
            unchanged["composite_rubric_score"], 2.00, "composite_rubric_score"
        )

        validate_success(
            api.advance_cycle(
                cycle["id"], f.advance_payload("POST_CONFERENCE"), mentor_headers
            )
        )
        submitted = validate_success(
            api.write_feedback(cycle["id"], submit_body, mentor_headers)
        )
        assert submitted["feedback_review_status"] == "SUBMITTED"
        assert_two_decimals(
            submitted["composite_rubric_score"], 3.75, "composite_rubric_score"
        )
        assert submitted["phase"] == "POST_CONFERENCE"
