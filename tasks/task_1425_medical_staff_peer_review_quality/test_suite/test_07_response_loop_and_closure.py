"""The provider response loop and case closure: the inclusive deadline
boundary, the post-deadline close path, the depth-3 resolution cascade, and
the divergent terminal branches (screen-out vs external referral)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assign_reviewer,
    committee_review,
    create_case,
    create_provider,
    finalize_after_response,
    get_case,
    make_provider_headers,
    respond_to_case,
    screen_case_in,
    seat_member,
    set_clock,
    setup_case_notified,
    submit_scores,
    validate_error,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]


class TestResponseDeadlineBoundary:
    def test_close_no_response_rejected_at_exact_deadline(self, quality_director_headers):
        """PRD §3.6: "Once the current logical time is strictly after
        `response_deadline`, the `QualityDirector` may close a `NOTIFIED` case
        directly; attempting this at or before the deadline is rejected with
        `ERR_RESPONSE_WINDOW_OPEN` (409)."
        PRD §3.6: "The two rules interlock at the boundary: at the exact
        deadline instant, a provider response is still accepted and
        close-no-response is still rejected."

        Design: Difficulty/boundary_precision_check/response_deadline_inclusive_boundary
        """
        ctx = setup_case_notified(scores=((5, None), (4, None), (5, None)))
        set_clock("2026-08-15T00:00:00Z")  # sent_at + 14 days exactly
        resp = api_client.close_no_response(ctx["case"]["id"], quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_RESPONSE_WINDOW_OPEN.value, expected_status=409)
        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "NOTIFIED"

    def test_provider_response_accepted_at_exact_deadline(self):
        """PRD §3.6: "the response is accepted while the current logical time
        is at or before the notification's `response_deadline`, inclusive, and
        rejected with `ERR_RESPONSE_WINDOW_CLOSED` (422) once the deadline has
        passed."
        PRD §3.6: "At most one response exists per case; a successful
        submission creates it with `submitted_at` stamped and moves the case
        to `RESPONDED`, incrementing the case's `version`."

        Design: Difficulty/boundary_precision_check/response_deadline_inclusive_boundary
        """
        ctx = setup_case_notified(scores=((5, None), (4, None), (5, None)))
        set_clock("2026-08-15T00:00:00Z")  # sent_at + 14 days exactly
        resp = api_client.create_case_response(
            ctx["case"]["id"],
            {"response_text": "submitted at the deadline instant"},
            make_provider_headers(ctx["subject"]["id"]))
        data = validate_success(resp, expected_status=201)
        assert_instant_equals(data["submitted_at"], "2026-08-15T00:00:00Z")
        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "RESPONDED"

    def test_response_after_deadline_rejected_then_close_allowed(self):
        """PRD §3.6: "the response is accepted while the current logical time
        is at or before the notification's `response_deadline`, inclusive, and
        rejected with `ERR_RESPONSE_WINDOW_CLOSED` (422) once the deadline has
        passed."
        PRD §3.6: "Closing this way sets `closure_basis` to `NO_RESPONSE`,
        stamps `closed_at`, increments the case's `version`, and runs the same
        resolution cascade as a post-response closure."

        Design: Corner/validations/response_after_deadline_rejected
        """
        ctx = setup_case_notified(scores=((5, None), (5, None), (5, None)))
        set_clock("2026-08-15T00:00:01Z")  # one second past the deadline
        resp = api_client.create_case_response(
            ctx["case"]["id"], {"response_text": "one second too late"},
            make_provider_headers(ctx["subject"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED.value, expected_status=422)

        responses = validate_success(api_client.get_case_response(ctx["case"]["id"], QD))
        assert responses == [], "the rejected response must not be persisted"

        closed = validate_success(api_client.close_no_response(ctx["case"]["id"], QD))
        assert closed["status"] == "CLOSED"
        assert closed["closure_basis"] == "NO_RESPONSE"
        assert_instant_equals(closed["closed_at"], "2026-08-15T00:00:01Z")


class TestFinalizeAfterResponseCascade:
    def _setup_committee_review_case(self):
        """Scores (2,2,4) -> MAJOR_OFI; provider responds; chair marks the
        response committee-reviewed."""
        ctx = setup_case_notified(scores=((2, None), (2, None), (4, None)),
                                  subject_specialty="PSYCHIATRY",
                                  member_specialties=("PSYCHIATRY", "SURGERY", "CARDIOLOGY"))
        respond_to_case(ctx["case"]["id"], ctx["subject"]["id"],
                        "context for the committee")
        committee_review(ctx["case"]["id"], ctx["chair"]["id"])
        return ctx

    def test_finalize_after_response_closes_case_with_post_response_basis(self):
        """PRD §3.6: "Finalizing after response re-runs the
        severity-precedence aggregation over the case's current three
        `SUBMITTED` assignments, picking up any revised scores; the
        Deliberation's `rating` is updated, the chair's optional
        `reconsideration_note` is stored, `reconsidered_at` is stamped with
        the current logical time, and the Deliberation's `version` increments.
        The case then moves to `CLOSED` with `closure_basis` set to
        `POST_RESPONSE` and `closed_at` stamped, its `version` incrementing —
        and the resolution cascade of §3.7 runs."

        Design: Difficulty/transitive_cascade/finalize_after_response_depth3_focus_cascade
        """
        ctx = self._setup_committee_review_case()
        deliberation = finalize_after_response(
            ctx["case"]["id"], ctx["chair"]["id"], "rating stands")
        assert deliberation["rating"] == "MAJOR_OFI", (
            f"recomputed over current scores (2,2,4), got {deliberation['rating']}")
        assert deliberation["reconsideration_note"] == "rating stands"
        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "CLOSED"
        assert case_after["closure_basis"] == "POST_RESPONSE"
        assert case_after["closed_at"] is not None

    def test_resolution_cascade_creates_automatic_focused_review_with_snapshot(self):
        """PRD §3.8: "the focused-review trigger evaluates four predicates
        against the freshly computed, already-rounded values, and fires when
        any one holds: `rated_case_count` is at least 3;
        `avg_care_appropriateness` is below 3.0, evaluated only when
        `rated_case_count` is greater than zero; `major_ofi_case_count` is at
        least 1; or `unacceptable_case_count` is at least 1."
        PRD §3.8: "When the trigger fires and the provider has no `ACTIVE`
        focused review, the server creates one with `trigger_type` `AUTOMATIC`,
        status `ACTIVE`, `opened_at` stamped, and a `trigger_snapshot` object
        capturing the evidence: `window_start`, `window_end`,
        `rated_case_count`, `avg_care_appropriateness`,
        `major_ofi_case_count`, and `unacceptable_case_count`."

        Design: Difficulty/transitive_cascade/finalize_after_response_depth3_focus_cascade
        """
        ctx = self._setup_committee_review_case()
        finalize_after_response(ctx["case"]["id"], ctx["chair"]["id"], "rating stands")

        reviews = validate_success(
            api_client.list_provider_focused_reviews(ctx["subject"]["id"], QD))
        assert len(reviews) == 1, "exactly one AUTOMATIC FocusedReview must be created"
        review = reviews[0]
        assert review["trigger_type"] == "AUTOMATIC"
        assert review["status"] == "ACTIVE"
        snapshot = review["trigger_snapshot"]
        assert snapshot["rated_case_count"] == 1
        assert snapshot["major_ofi_case_count"] == 1
        assert snapshot["unacceptable_case_count"] == 0
        assert snapshot["avg_care_appropriateness"] == pytest.approx(2.67, abs=0.001)
        assert_instant_equals(snapshot["window_start"], "2025-08-01T00:00:00Z")
        assert_instant_equals(snapshot["window_end"], "2026-08-01T00:00:00Z")

    def test_resolution_cascade_creates_auto_conflict_declarations(self):
        """PRD §3.7: "Third, for each `SUBMITTED` assignment on the resolved
        case, a conflict declaration is created linking the assignment's
        reviewer (`member_id`) to the subject provider (`provider_id`) with
        `source` set to `AUTO_CASE_RESOLVED` — unless an identical
        (`member_id`, `provider_id`) declaration already exists, in which case
        none is added."

        Design: Difficulty/transitive_cascade/finalize_after_response_depth3_focus_cascade
        """
        ctx = self._setup_committee_review_case()
        finalize_after_response(ctx["case"]["id"], ctx["chair"]["id"], "rating stands")

        for member in ctx["members"]:
            declarations = validate_success(
                api_client.list_member_conflict_declarations(member["id"], QD))
            assert len(declarations) == 1, (
                f"reviewer {member['id']} must hold exactly one AUTO declaration")
            assert declarations[0]["source"] == "AUTO_CASE_RESOLVED"
            assert declarations[0]["provider_id"] == ctx["subject"]["id"]
            assert declarations[0]["member_id"] == member["id"]


class TestTerminalBranchDivergence:
    def _setup_two_cases(self):
        """caseA left REFERRED; caseB driven to DELIBERATION with (4,4,4).
        Both cases are created before either is screened, so the cooldown
        armed by caseA's screen-out cannot block caseB's intake."""
        subject = create_provider("Subj Six", "EMERGENCY_MEDICINE")
        members = [seat_member(create_provider(n, s)["id"], "MEMBER")
                   for n, s in [("Rev B", "EMERGENCY_MEDICINE"), ("Rev C", "SURGERY"),
                                ("Rev D", "CARDIOLOGY")]]
        case_a = create_case(subject["id"], description="branch case A")
        case_b = create_case(subject["id"], referral_source="STAFF_REFERRAL",
                             referred_at="2026-07-21T00:00:00Z",
                             description="branch case B")
        screen_case_in(case_b["id"])
        assignments = [assign_reviewer(case_b["id"], m["id"]) for m in members]
        for asg, m in zip(assignments, members):
            submit_scores(asg["id"], m["id"], case_b["id"], 4)
        return subject, case_a, case_b

    def test_screen_out_branch_stamps_reason_and_locks_case(self, quality_director_headers):
        """PRD §3.2: "A `decision` of `SCREEN_OUT` requires a
        `screened_out_reason` of `DUPLICATE`, `FRIVOLOUS`, `OUT_OF_SCOPE`, or
        `OTHER` — omitting it is rejected with
        `ERR_SCREEN_OUT_REASON_REQUIRED` — and moves the case to
        `SCREENED_OUT`, stamping `screened_out_at` with the current logical
        time and thereby arming the cooldown described above."
        PRD §3.2: "`SCREENED_OUT` is one of the case's three terminal states,
        alongside `CLOSED` and `EXTERNAL_REVIEW`, and any further action
        attempted on a terminal case is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/non_linear_state_machine/case_branching_screen_and_terminal_forks
        """
        _, case_a, _ = self._setup_two_cases()
        screened = validate_success(api_client.screen_case(
            case_a["id"], {"decision": "SCREEN_OUT", "screened_out_reason": "FRIVOLOUS"},
            quality_director_headers))
        assert screened["status"] == "SCREENED_OUT"
        assert screened["screened_out_reason"] == "FRIVOLOUS"
        assert_instant_equals(screened["screened_out_at"], "2026-08-01T00:00:00Z")

        resp = api_client.screen_case(case_a["id"], {"decision": "SCREEN_IN"},
                                      quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value, expected_status=409)

        referrals = validate_success(api_client.list_external_referrals(case_a["id"], QD))
        assert referrals == [], "the SCREENED_OUT branch creates no ExternalReferral"

    def test_external_referral_branch_creates_referral_record(self, quality_director_headers):
        """PRD §3.7: "From `DELIBERATION`, the `QualityDirector` may refer the
        case externally by supplying a non-empty `reason`; the same referral
        is available from `COMMITTEE_REVIEW`, after the response loop has
        produced a finalized rating. Either way, the referral creates the
        case's ExternalReferral record — at most one per case — with
        `referred_at` stamped at the current logical time, moves the case to
        `EXTERNAL_REVIEW`, increments its `version`, and runs the resolution
        cascade."
        PRD §3.2: "The `screened_out_reason` and `screened_out_at` fields
        remain null on any case that was never screened out."

        Design: Difficulty/non_linear_state_machine/case_branching_screen_and_terminal_forks
        """
        _, _, case_b = self._setup_two_cases()
        referral = validate_success(api_client.refer_external(
            case_b["id"], {"reason": "committee split; outside expertise needed"},
            quality_director_headers), expected_status=201)
        assert_instant_equals(referral["referred_at"], "2026-08-01T00:00:00Z")

        referrals = validate_success(api_client.list_external_referrals(case_b["id"], QD))
        assert len(referrals) == 1

        case_after = validate_success(api_client.get_case(case_b["id"], QD))
        assert case_after["status"] == "EXTERNAL_REVIEW"
        assert case_after["screened_out_reason"] is None, (
            "the EXTERNAL_REVIEW branch creates no screened_out_reason")
