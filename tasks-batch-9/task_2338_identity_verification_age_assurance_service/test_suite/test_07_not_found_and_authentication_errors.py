"""Authentication of the declared role, and path-identifier resolution.

Every test here drives a request whose subject identifier resolves to nothing,
or whose declared capacity is not a role the service knows, and pins the exact
error the contract promises.
"""
from test_helpers import (
    COMPLIANCE_OFFICER_USER_ID,
    DEFAULT_CLOCK,
    MANUAL_REVIEWER_USER_ID,
    NON_EXISTENT_UUID,
    REVIEW_MANAGER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    assign_case_payload,
    build_user_headers,
    create_client_payload,
    create_cohort_metric_payload,
    create_live_client,
    make_client_integrator_headers,
    make_compliance_officer_headers,
    make_inclusion_reviewer_headers,
    make_review_manager_headers,
    pathway_decision_payload,
    publish_policy_payload,
    read_client,
    read_session,
    set_clock,
    setup_session,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_client_registration_declaring_an_unknown_role_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six
    role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "`ERR_UNAUTHENTICATED` (401) — headers present and the role recognised. Every endpoint."

    Design: Corner/errors/request_with_an_unrecognised_role_header_is_unauthenticated
    """
    set_clock(DEFAULT_CLOCK)

    ghost_headers = build_user_headers("ghost-1", "SecurityAuditor")
    payload = create_client_payload(
        name="Ghost Co",
        home_jurisdiction_code="US",
        biometric_retention_mode="DELETE_ON_COMPLETE",
        daily_session_quota=10,
        granted_review_credits=1,
    )

    response = api.create_client(payload, ghost_headers)

    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, (
        "an unrecognised role value must fail authentication, not authorisation"
    )


class TestUnknownPathIdentifiers:
    """The first identifier that does not resolve decides the 404 returned."""

    def test_publish_with_an_unknown_policy_id_returns_not_found(self, api):
        """PRD §2.6: "`ERR_POLICY_NOT_FOUND` (404) — the verification policy named by the
        path exists. `POST /idv/verification-policies/{id}/publish`, `GET /idv/verification-policies/{id}`."
        PRD §2.9: "Existence resolution always precedes ownership, schema, state and
        business checks, exactly as ordered in §2.6."

        Design: Corner/errors/publish_with_an_unknown_policy_id_returns_not_found
        """
        set_clock(DEFAULT_CLOCK)
        client = create_live_client(name="Acme PolNF")
        current_version = client["version"]

        response = api.publish_verification_policy(
            NON_EXISTENT_UUID,
            publish_policy_payload(current_version),
            make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
        )

        error = validate_error(response, ApiErrorId.ERR_POLICY_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ERR_STALE_CLIENT_VERSION.value, (
            "path resolution runs before the client-version guard"
        )
        assert read_client(client["id"])["version"] == 2, (
            "the rejected publish must perform no write on the client"
        )

    def test_session_retrieval_with_an_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "`ERR_SESSION_NOT_FOUND` (404) — the verification session named by
        the path exists. Every `/idv/verification-sessions/{id}/...` endpoint and
        `GET /idv/verification-sessions/{id}`."
        PRD §2.9: "Existence resolution always precedes ownership, schema, state and
        business checks, exactly as ordered in §2.6."

        Design: Corner/errors/session_retrieval_with_an_unknown_id_returns_not_found
        """
        set_clock(DEFAULT_CLOCK)
        client = create_live_client(name="Acme SessNF")

        response = api.get_verification_session(
            NON_EXISTENT_UUID, make_client_integrator_headers(client["id"])
        )

        error = validate_error(response, ApiErrorId.ERR_SESSION_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ERR_CLIENT_SCOPE_VIOLATION.value, (
            "an unresolvable session id is reported before any ownership comparison"
        )

    def test_finalize_with_an_unknown_attempt_id_returns_not_found(self, api):
        """PRD §2.6: "`ERR_ATTEMPT_NOT_FOUND` (404) — the method attempt named by the
        path exists. Every `/idv/method-attempts/{id}/...` endpoint and
        `GET /idv/method-attempts/{id}`."

        Design: Corner/errors/finalize_with_an_unknown_attempt_id_returns_not_found
        """
        env = setup_session(
            client_overrides={"name": "Acme AttNF"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-attnf"},
        )

        response = api.finalize_method_attempt(NON_EXISTENT_UUID, env["headers"])

        error = validate_error(response, ApiErrorId.ERR_ATTEMPT_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ERR_ATTEMPT_STATE_INVALID.value, (
            "finalisation resolves the attempt before any state reasoning"
        )
        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["assurance_score_provisional"] == 0, (
            "a rejected finalisation must not move the running provisional score"
        )

    def test_pathway_decision_with_an_unknown_pathway_id_returns_not_found(self, api):
        """PRD §2.6: "`ERR_PATHWAY_NOT_FOUND` (404) — the alternative pathway named by
        the path exists. `POST /idv/alternative-pathways/{id}/decision`."

        Design: Corner/errors/pathway_decision_with_an_unknown_pathway_id_returns_not_found
        """
        set_clock(DEFAULT_CLOCK)

        response = api.decide_alternative_pathway(
            NON_EXISTENT_UUID,
            pathway_decision_payload("APPROVE"),
            make_inclusion_reviewer_headers(),
        )

        error = validate_error(response, ApiErrorId.ERR_PATHWAY_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ERR_NO_ELIGIBLE_METHOD.value, (
            "the pathway is resolved before any candidate-selection work"
        )
        _, meta = validate_paginated(api.list_method_attempts(ADMIN))
        assert meta["total_count"] == 0, "no attempt may be minted by a rejected decision"

    def test_assignment_with_an_unknown_review_case_id_returns_not_found(self, api):
        """PRD §2.6: "`ERR_REVIEW_CASE_NOT_FOUND` (404) — the manual review case named by
        the path exists. `POST /idv/manual-review-cases/{id}/assign`,
        `POST /idv/manual-review-cases/{id}/decision`."

        Design: Corner/errors/assignment_with_an_unknown_review_case_id_returns_not_found
        """
        set_clock(DEFAULT_CLOCK)

        response = api.assign_manual_review_case(
            NON_EXISTENT_UUID,
            assign_case_payload(MANUAL_REVIEWER_USER_ID),
            make_review_manager_headers(REVIEW_MANAGER_USER_ID),
        )

        error = validate_error(response, ApiErrorId.ERR_REVIEW_CASE_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ERR_REVIEW_CAPACITY_EXHAUSTED.value, (
            "the case is resolved before any credit-pool reasoning"
        )

    def test_cohort_submission_with_an_unknown_audit_id_returns_not_found(self, api):
        """PRD §2.6: "`ERR_AUDIT_NOT_FOUND` (404) — the bias audit named by the path
        exists. Every `/idv/bias-audits/{id}/...` endpoint and `GET /idv/bias-audits/{id}`."
        PRD §2.9: "A request for the cohort rows of a non-existent audit reports
        `ERR_AUDIT_NOT_FOUND`; a request for the liveness checks of a non-existent attempt
        reports `ERR_ATTEMPT_NOT_FOUND`."

        Design: Corner/errors/cohort_submission_with_an_unknown_audit_id_returns_not_found
        """
        set_clock(DEFAULT_CLOCK)

        response = api.create_cohort_metric(
            NON_EXISTENT_UUID,
            create_cohort_metric_payload("AGE_18_24", 100, 5, 2),
            make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
        )

        error = validate_error(response, ApiErrorId.ERR_AUDIT_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ERR_AUDIT_STATE_INVALID.value, (
            "an unresolvable audit id is reported before the audit-state check"
        )
