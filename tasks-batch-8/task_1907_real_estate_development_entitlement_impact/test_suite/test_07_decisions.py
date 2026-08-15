"""Decision rendering: segregation of duties, the statutory deadline, OCC on
the application version, terminal lockout, and the appeal window's bounds."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_appeal,
    assert_decision,
    file_appeal_payload,
    get_application,
    make_decision_authority_headers,
    post_comment,
    record_outreach,
    render_decision_payload,
    set_clock,
    setup_approved_application,
    setup_decision_pending_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_segregation_of_duties_reviewer_cannot_decide(api):
    """PRD 3.6: "segregation of duties forbids the rendering authority from
    being any staff reviewer who authored a review comment on this application
    — a violation is `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/validations/segregation_of_duties_reviewer_cannot_decide
    """
    ctx = setup_under_review_application()
    reviewer = ctx["reviewer"]
    post_comment(ctx, severity="INFO", comment_text="comment by conflicted reviewer")
    advanced = validate_success(
        api.advance_to_decision(ctx["application"]["id"], ctx["reviewer_headers"])
    )
    assert advanced["status"] == "DECISION_PENDING"

    # The rendering authority's id matches the reviewer who authored a comment.
    auth_headers = make_decision_authority_headers(reviewer["id"])
    payload = render_decision_payload(
        decided_by=reviewer["id"],
        expected_application_version=advanced["version"],
        decision="APPROVE",
    )
    response = api.render_decision(ctx["application"]["id"], payload, auth_headers)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
    assert after["status"] == "DECISION_PENDING", (
        f"rejected decision must leave the application DECISION_PENDING, "
        f"got {after['status']}"
    )


class TestDecisionDeadlineAndStatePrecedence:
    def test_render_from_under_review_past_deadline_reports_state(self, api):
        """PRD 2.9: "every operation passes through eight ordered validation
        gates, and a failure at an earlier gate masks every later check" — the
        state gate ("4. **State.** ... else `ERR_INVALID_STATE` (409)") precedes
        the temporal gate ("5. **Statutory and temporal windows.**").
        PRD 3.6: "Rendering is only possible from `DECISION_PENDING`, else
        `ERR_INVALID_STATE`."

        An application still UNDER_REVIEW whose decision deadline has also
        passed must report the state failure, not the temporal one.

        Design: Difficulty/priority_pair_validation_conflict/decision_state_vs_temporal_deadline_priority
        """
        ctx = setup_under_review_application(with_authority=True)
        # Submitted at the default instant; decision_due_date is 90 days later.
        assert ctx["application"]["decision_due_date"]
        set_clock("2026-12-01T00:00:00Z")

        app_id = ctx["application"]["id"]
        current = get_application(app_id, ctx["authority_headers"])
        payload = render_decision_payload(
            decided_by=ctx["authority"]["id"],
            expected_application_version=current["version"],
            decision="APPROVE",
        )
        response = api.render_decision(app_id, payload, ctx["authority_headers"])
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_render_after_decision_due_date_rejected(self, api):
        """PRD 3.6: "the statutory clock forbids rendering after
        `decision_due_date`. A render attempted after that deadline is rejected
        with `ERR_DECISION_DEADLINE_PASSED`."
        PRD 3.3: "The same event stamps `decision_due_date` as 90 days after
        the submission instant".

        Design: Difficulty/priority_pair_validation_conflict/decision_state_vs_temporal_deadline_priority
        """
        ctx = setup_decision_pending_application(with_authority=True)
        set_clock("2026-12-01T00:00:00Z")  # past submitted_at + 90 days

        app_id = ctx["application"]["id"]
        current = get_application(app_id, ctx["authority_headers"])
        payload = render_decision_payload(
            decided_by=ctx["authority"]["id"],
            expected_application_version=current["version"],
            decision="APPROVE",
        )
        response = api.render_decision(app_id, payload, ctx["authority_headers"])
        validate_error(response, ApiErrorId.ERR_DECISION_DEADLINE_PASSED)


def test_occ_stale_application_version_on_decision(api):
    """PRD 2.7: "Rendering a decision requires the request to carry
    `expected_application_version`, the decision-maker's last observed
    `version` of the application. If the application's version has advanced in
    the meantime — a new blocking comment, a posture flip from fresh outreach —
    the render is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_application_version_on_decision
    """
    ctx = setup_decision_pending_application(with_authority=True)
    app_id = ctx["application"]["id"]
    observed = get_application(app_id, ctx["authority_headers"])
    stale_version = observed["version"]

    # Fresh outreach mutates the application, advancing its version.
    record_outreach(ctx, "OPPOSE", "2026-08-03T00:00:00Z", attendee_count=5)

    payload = render_decision_payload(
        decided_by=ctx["authority"]["id"],
        expected_application_version=stale_version,
        decision="APPROVE",
    )
    response = api.render_decision(app_id, payload, ctx["authority_headers"])
    validate_error(response, ApiErrorId.ERR_STALE_APPLICATION_VERSION)

    after = get_application(app_id, ctx["authority_headers"])
    assert after["status"] == "DECISION_PENDING", (
        f"rejected render must leave the application DECISION_PENDING, "
        f"got {after['status']}"
    )


class TestAppealWindowBounds:
    def test_appeal_filed_at_deadline_refused(self, api):
        """PRD 3.9: "a filing whose `filed_at` falls on or after the decision's
        `appeal_deadline` is refused with `ERR_APPEAL_WINDOW_CLOSED`" — the
        window's upper bound is exclusive.

        Design: Difficulty/resource_temporal_overlap/appeal_window_half_open_interval
        """
        ctx = setup_approved_application()
        decision = ctx["decision"]
        assert_decision(decision)

        payload = file_appeal_payload(
            appellant_name="AtDeadline",
            filed_at=decision["appeal_deadline"],
            grounds="too late",
        )
        response = api.file_appeal(ctx["application"]["id"], payload, ADMIN)
        validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    def test_appeal_filed_at_effective_date_accepted_and_stays_decision(self, api):
        """PRD 3.9: "Filing inside the window moves the decision from
        `RENDERED` to `STAYED_ON_APPEAL`" — filing at the
        `decision_effective_date` itself (the window's inclusive lower edge) is
        inside the window, since only a `filed_at` "on or after the decision's
        `appeal_deadline` is refused with `ERR_APPEAL_WINDOW_CLOSED`".

        Design: Difficulty/resource_temporal_overlap/appeal_window_half_open_interval
        """
        ctx = setup_approved_application()
        decision = ctx["decision"]

        payload = file_appeal_payload(
            appellant_name="DayOne",
            filed_at=decision["decision_effective_date"],
            grounds="traffic",
        )
        appeal = validate_success(
            api.file_appeal(ctx["application"]["id"], payload, ADMIN),
            expected_status=201,
        )
        assert_appeal(appeal)
        assert appeal["status"] == "FILED"

        stayed = validate_success(
            api.get_decision(decision["id"], ctx["authority_headers"])
        )
        assert stayed["status"] == "STAYED_ON_APPEAL", (
            f"in-window filing must stay the decision, got {stayed['status']}"
        )
