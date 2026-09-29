"""Role boundaries, client isolation and the two segregation-of-duties controls.

Six roles act on this service and each has a narrow lane. These tests walk one
escalation through every lane that legitimately owns a step, then probe the
refusals: a role reaching outside its remit, one relying party reaching for
another's session, and the two paired-step controls that stop a single operator
from both raising and closing the same decision.
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    FORGED_CAPTURE,
    assign_case_payload,
    build_user_headers,
    create_live_client,
    create_verification_session_payload,
    make_client_integrator_headers,
    make_compliance_officer_headers,
    make_inclusion_reviewer_headers,
    make_manual_reviewer_headers,
    make_review_manager_headers,
    open_attempt,
    read_attempt,
    read_bias_audit,
    read_client,
    read_method_profile,
    read_session,
    remediation_payload,
    review_decision_payload,
    set_clock,
    setup_assigned_review_case,
    setup_bias_audit_with_cohorts,
    setup_client_with_published_policy,
    setup_pending_pathway,
    setup_session,
    setup_session_in_manual_review_from_fraud,
    list_session_pathways,
    evaluate_audit,
    register_method_profile,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

# The cohort rows below drive the gating ratio well past the restriction
# threshold: cohort rates of 500, 150 and 233 basis points against a pooled rate
# of 250 basis points.
RESTRICTING_AUDIT_COHORTS = [
    ("AGE_18_24", 100, 5),
    ("AGE_25_44", 200, 3),
    ("AGE_65_PLUS", 300, 7),
]


class TestOwnLanePermitted:
    def test_every_role_completes_its_own_step_of_one_escalation(self, api):
        """PRD §2.1: "A `PlatformAdmin` is the verification provider's own operator. It
        onboards relying-party clients and vendor method profiles, runs the operations
        sweep, drives the logical clock, and may read every resource."
        PRD §3.8: "On success the case moves `ASSIGNED → DECIDED` with `decision`,
        `decided_by_user_id` and `decided_at` written, the reserved credit is released
        back to `available_review_credits`, and the client's `consumed_review_count`
        rises by one."
        PRD §3.8: "`APPROVE` moves the session `MANUAL_REVIEW → VERIFIED`, sets
        `manual_override_flag` to true, sets `disposition_reason` to `MANUAL_OVERRIDE`,
        sets `completed_at` to the clock, writes `assurance_score_final`, and applies
        the retention schedule to every template still in `STORED`."

        Design: Corner/rbac/each_role_performs_its_own_operations_across_one_escalation
        """
        set_clock(DEFAULT_CLOCK)
        # PlatformAdmin onboards the client and the vendor profile; the relying party
        # drafts the policy and the compliance officer publishes it.
        env = setup_client_with_published_policy(policy_overrides={"min_assurance_score": 60})
        client = env["client"]
        profile = env["profiles"]["DOCUMENT_SCAN"]
        integrator = make_client_integrator_headers(client["id"])

        session = validate_success(
            api.create_verification_session(
                create_verification_session_payload(
                    client["id"],
                    external_subject_ref="subj-roles",
                    requested_assurance_tier="BASIC",
                ),
                integrator,
            ),
            201,
        )
        attempt = validate_success(
            api.create_method_attempt(
                session["id"], {"method_profile_id": profile["id"]}, integrator
            ),
            201,
        )
        validate_success(
            api.create_document_capture(attempt["id"], dict(FORGED_CAPTURE), integrator), 201
        )
        rejected = validate_success(api.finalize_method_attempt(attempt["id"], integrator))
        assert rejected["state"] == "REJECTED", (
            f"a forged capture must reject the attempt, got {rejected['state']}"
        )

        cases, meta = validate_paginated(
            api.list_manual_review_cases(session["id"], make_review_manager_headers("rm-1"))
        )
        assert meta["total_count"] == 1, f"one escalation expected, got {meta['total_count']}"
        assigned = validate_success(
            api.assign_manual_review_case(
                cases[0]["id"], assign_case_payload("mr-1"), make_review_manager_headers("rm-1")
            )
        )
        assert assigned["state"] == "ASSIGNED"

        decided = validate_success(
            api.decide_manual_review_case(
                assigned["id"], review_decision_payload("APPROVE"), make_manual_reviewer_headers("mr-1")
            )
        )
        assert decided["state"] == "DECIDED", f"expected DECIDED, got {decided['state']}"
        assert decided["decided_by_user_id"] == "mr-1"
        assert decided["assigned_by_user_id"] == "rm-1"

        session_after = read_session(session["id"], client["id"])
        assert session_after["identity_state"] == "VERIFIED"
        assert session_after["manual_override_flag"] is True
        assert session_after["disposition_reason"] == "MANUAL_OVERRIDE"

        client_after = read_client(client["id"])
        assert client_after["consumed_review_count"] == 1, (
            f"consumed_review_count must be 1, got {client_after['consumed_review_count']}"
        )
        assert client_after["reserved_review_credits"] == 0, (
            "the reserved credit must be released on decision, got "
            f"{client_after['reserved_review_credits']}"
        )


class TestRoleExclusivity:
    def test_compliance_officer_cannot_open_a_verification_session(self, api):
        """PRD §2.1: "A `ComplianceOfficer` owns policy publication and the entire
        bias-testing programme — opening audits, recording cohort metrics, evaluating
        disparity and recording remediation — and may read every resource, but may never
        open a session or submit subject evidence."
        PRD §2.1: "If both headers are well-formed but the declared role is not
        authorised for the endpoint being called, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_open_a_verification_session
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_client_with_published_policy(policy_overrides={"min_assurance_score": 40})
        client = env["client"]

        response = api.create_verification_session(
            create_verification_session_payload(
                client["id"],
                external_subject_ref="subj-co",
                requested_assurance_tier="BASIC",
            ),
            make_compliance_officer_headers("co-1"),
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

        sessions, meta = validate_paginated(
            api.list_verification_sessions(
                TEST_USERS["platform_admin_headers"], params={"client_id": client["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused request must mint no session, got {meta['total_count']}"
        )
        assert sessions == []

        # The very officer that was refused had legitimately published this policy.
        assert env["policy"]["state"] == "PUBLISHED"

    def test_review_manager_cannot_decide_a_case_it_assigned(self, api):
        """PRD §2.1: "A `ReviewManager` triages the manual-review queue and assigns
        cases, reserving review capacity as it does so, and may never decide a case."
        PRD §2.6: "Checks are evaluated strictly in the order listed below, and the
        first failing check determines the response."

        Design: Corner/rbac/review_manager_cannot_decide_a_case_at_all
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_assigned_review_case()
        case = env["case"]

        response = api.decide_manual_review_case(
            case["id"], review_decision_payload("APPROVE"), make_review_manager_headers("rm-1")
        )
        error = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        assert error["error_id"] != "ERR_SEGREGATION_OF_DUTIES", (
            "the role check is listed before the segregation-of-duties check"
        )

        cases, _ = validate_paginated(
            api.list_manual_review_cases(env["session"]["id"], make_review_manager_headers())
        )
        assert cases[0]["state"] == "ASSIGNED"
        assert cases[0]["decision"] is None
        assert cases[0]["decided_by_user_id"] is None

        assert read_session(env["session"]["id"], env["client"]["id"])["identity_state"] == "MANUAL_REVIEW"
        client_after = read_client(env["client"]["id"])
        assert client_after["reserved_review_credits"] == 1
        assert client_after["consumed_review_count"] == 0

    def test_manual_reviewer_cannot_assign_a_queued_case(self, api):
        """PRD §2.1: "A `ManualReviewer` decides the case assigned to it and nothing
        else."
        PRD §3.8: "Queued cases hold no credit at all, which is deliberate: escalation
        itself can never be blocked by exhausted capacity, only its assignment can."

        Design: Corner/rbac/manual_reviewer_cannot_assign_a_queued_case
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session_in_manual_review_from_fraud()

        # The reviewer may read the queue it cannot triage.
        cases, meta = validate_paginated(
            api.list_manual_review_cases(env["session"]["id"], make_manual_reviewer_headers("mr-1"))
        )
        assert meta["total_count"] == 1, f"one queued case expected, got {meta['total_count']}"
        assert cases[0]["state"] == "QUEUED"

        response = api.assign_manual_review_case(
            cases[0]["id"], assign_case_payload("mr-1"), make_manual_reviewer_headers("mr-1")
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

        after, _ = validate_paginated(
            api.list_manual_review_cases(env["session"]["id"], make_review_manager_headers())
        )
        assert after[0]["state"] == "QUEUED"
        assert after[0]["assigned_reviewer_user_id"] is None
        assert read_client(env["client"]["id"])["reserved_review_credits"] == 0

    def test_inclusion_reviewer_cannot_submit_subject_evidence(self, api):
        """PRD §2.1: "An `InclusionReviewer` adjudicates accessibility pathways and
        touches nothing else."
        PRD §2.1: "If both headers are well-formed but the declared role is not
        authorised for the endpoint being called, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/inclusion_reviewer_cannot_submit_subject_evidence
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_pending_pathway("VOUCHING", policy_overrides={"min_assurance_score": 40})
        client = env["client"]
        attempt = open_attempt(
            env["session"]["id"], client["id"], env["profiles"]["DOCUMENT_SCAN"]["id"]
        )

        response = api.create_document_capture(
            attempt["id"],
            {
                "document_type": "PASSPORT",
                "required_feature_count": 10,
                "passed_feature_count": 10,
                "tamper_signal_count": 0,
                "mrz_checksum_valid": True,
            },
            make_inclusion_reviewer_headers("ir-1"),
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

        captures, meta = validate_paginated(
            api.list_document_captures(attempt["id"], make_client_integrator_headers(client["id"]))
        )
        assert meta["total_count"] == 0, (
            f"the refused submission must store no capture, got {meta['total_count']}"
        )
        assert captures == []

        session_after = read_session(env["session"]["id"], client["id"])
        assert session_after["assurance_score_provisional"] == 0

        pathways, _ = list_session_pathways(env["session"]["id"], client["id"])
        assert pathways[0]["state"] == "VOUCH_PENDING", (
            "the pathway the reviewer may legitimately decide is untouched"
        )
        assert read_attempt(attempt["id"], client["id"])["state"] == "AWAITING_EVIDENCE"


class TestClientIsolation:
    def test_client_integrator_cannot_read_another_clients_session(self, api):
        """PRD §2.1: "A `ClientIntegrator` that addresses a policy, session, attempt,
        evidence row, pathway or client record belonging to any other client is rejected
        with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.9: "Existence resolution always precedes ownership, schema, state and
        business checks, exactly as ordered in §2.6."

        Design: Corner/rbac/client_integrator_cannot_read_another_clients_session
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-tenanta",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_a = env["client"]
        session = env["session"]
        client_b = create_live_client(name="Acme Tenant B")

        response = api.get_verification_session(
            session["id"], make_client_integrator_headers(client_b["id"])
        )
        error = validate_error(response, ApiErrorId.ERR_CLIENT_SCOPE_VIOLATION)
        assert error["error_id"] != "ERR_SESSION_NOT_FOUND", "the session does exist"

        owner_read = validate_success(
            api.get_verification_session(
                session["id"], make_client_integrator_headers(client_a["id"])
            )
        )
        assert owner_read["id"] == session["id"]

        _, meta = validate_paginated(
            api.list_verification_sessions(
                make_client_integrator_headers(client_b["id"]),
                params={"client_id": client_b["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            f"client B holds no sessions of its own, got {meta['total_count']}"
        )


class TestSegregationOfDuties:
    def test_same_user_cannot_assign_and_then_decide_the_same_case(self, api):
        """PRD §2.1: "In manual review, the `ManualReviewer` recorded as
        `decided_by_user_id` must differ from the `ReviewManager` recorded as
        `assigned_by_user_id`; separately, that reviewer's `X-User-ID` must equal
        `assigned_reviewer_user_id`, and a different reviewer submitting the verdict is
        rejected with `ERR_REVIEW_ASSIGNEE_MISMATCH` (HTTP 403)."
        PRD §2.1: "Two controls are enforced by segregation of duties, and both fail
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/same_user_id_cannot_assign_and_then_decide_the_same_case
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_assigned_review_case(reviewer_user_id="u-9", manager_user_id="u-9")
        case = env["case"]
        assert case["assigned_by_user_id"] == "u-9"
        assert case["assigned_reviewer_user_id"] == "u-9"

        response = api.decide_manual_review_case(
            case["id"],
            review_decision_payload("APPROVE"),
            build_user_headers("u-9", "ManualReviewer"),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        cases, _ = validate_paginated(
            api.list_manual_review_cases(env["session"]["id"], make_review_manager_headers())
        )
        assert cases[0]["state"] == "ASSIGNED"
        assert cases[0]["decision"] is None
        assert cases[0]["decided_at"] is None

        client_after = read_client(env["client"]["id"])
        assert client_after["reserved_review_credits"] == 1
        assert client_after["available_review_credits"] == 0
        assert client_after["consumed_review_count"] == 0

        assert read_session(env["session"]["id"], env["client"]["id"])["identity_state"] == "MANUAL_REVIEW"

    def test_non_assigned_reviewer_cannot_decide_another_reviewers_case(self, api):
        """PRD §2.1: "In manual review, the `ManualReviewer` recorded as
        `decided_by_user_id` must differ from the `ReviewManager` recorded as
        `assigned_by_user_id`; separately, that reviewer's `X-User-ID` must equal
        `assigned_reviewer_user_id`, and a different reviewer submitting the verdict is
        rejected with `ERR_REVIEW_ASSIGNEE_MISMATCH` (HTTP 403)."
        PRD §3.8: "It requires the case to be `ASSIGNED`, requires the caller's
        `X-User-ID` to equal `assigned_reviewer_user_id`, and requires the caller's
        `X-User-ID` to differ from `assigned_by_user_id`."

        Design: Corner/rbac/non_assigned_reviewer_cannot_decide_another_reviewers_case
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_assigned_review_case(reviewer_user_id="mr-1", manager_user_id="rm-1")
        case = env["case"]

        response = api.decide_manual_review_case(
            case["id"], review_decision_payload("APPROVE"), make_manual_reviewer_headers("mr-2")
        )
        error = validate_error(response, ApiErrorId.ERR_REVIEW_ASSIGNEE_MISMATCH)
        assert error["error_id"] != "ERR_ROLE_NOT_PERMITTED", "mr-2 holds the deciding role"
        assert error["error_id"] != "ERR_SEGREGATION_OF_DUTIES", "mr-2 did not assign the case"

        cases, _ = validate_paginated(
            api.list_manual_review_cases(env["session"]["id"], make_review_manager_headers())
        )
        assert cases[0]["state"] == "ASSIGNED"
        assert cases[0]["assigned_reviewer_user_id"] == "mr-1"
        assert cases[0]["decision"] is None

        session_after = read_session(env["session"]["id"], env["client"]["id"])
        assert session_after["identity_state"] == "MANUAL_REVIEW"
        assert session_after["assurance_score_final"] is None

    def test_evaluating_officer_cannot_record_the_remediation(self, api):
        """PRD §2.1: "In bias remediation, the `ComplianceOfficer` recorded as
        `remediated_by_user_id` must differ from the `ComplianceOfficer` recorded as
        `evaluated_by_user_id` for the most recent evaluation of that audit."
        PRD §3.9: "It requires the audit to be `REMEDIATION_REQUIRED`, carries the
        profile-version guard of §2.7 through `expected_method_profile_version`,
        requires the acting `X-User-ID` to differ from `evaluated_by_user_id`, and takes
        a `remediation_note` recording what was done."

        Design: Corner/rbac/evaluating_officer_cannot_record_the_remediation
        """
        set_clock(DEFAULT_CLOCK)
        profile = register_method_profile("DOCUMENT_SCAN")
        audit = setup_bias_audit_with_cohorts(
            profile["id"],
            cohorts=RESTRICTING_AUDIT_COHORTS,
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-07-01T00:00:00Z",
            officer_user_id="co-1",
        )
        evaluated = evaluate_audit(audit["id"], officer_user_id="co-1")
        assert evaluated["state"] == "REMEDIATION_REQUIRED"

        # The officer re-reads the profile, so the version it presents is current.
        current_version = read_method_profile(profile["id"])["version"]

        response = api.remediate_bias_audit(
            audit["id"],
            remediation_payload(current_version, remediation_note="retrained matcher"),
            make_compliance_officer_headers("co-1"),
        )
        error = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert error["error_id"] != "ERR_STALE_METHOD_PROFILE_VERSION", (
            "the presented profile version was current"
        )

        audit_after = read_bias_audit(audit["id"])
        assert audit_after["state"] == "REMEDIATION_REQUIRED"
        assert audit_after["remediation_round"] == 0
        assert audit_after["remediated_by_user_id"] is None
        assert audit_after["remediated_at"] is None
        assert audit_after["evaluated_by_user_id"] == "co-1"

        profile_after = read_method_profile(profile["id"])
        assert profile_after["bias_state"] == "RESTRICTED"
        assert profile_after["version"] == 2, (
            f"the restriction bumped the profile to version 2, got {profile_after['version']}"
        )
