"""Optimistic concurrency, risk-aware method selection and immediate visibility.

Exactly two write endpoints supersede a decision another operator may have based
work on, and both guard the parent entity's version. The method ladder is the
other place where one request's outcome depends on what an earlier request
already settled. Finally, every cascade this service runs must be observable in
the very response that triggered it and in the reads that immediately follow.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    FORGED_CAPTURE,
    create_live_client,
    draft_policy,
    evaluate_audit,
    finalize_attempt,
    list_session_audit_events,
    make_client_integrator_headers,
    make_compliance_officer_headers,
    make_review_manager_headers,
    open_attempt,
    publish_policy,
    publish_policy_payload,
    read_attempt,
    read_bias_audit,
    read_client,
    read_method_profile,
    read_policy,
    read_session,
    register_method_profile,
    remediation_payload,
    set_clock,
    setup_bias_audit_with_cohorts,
    setup_scored_document_attempt,
    setup_session,
    submit_document_capture,
    validate_error,
    validate_paginated,
    validate_success,
)

# Cohort rates of 500, 150 and 233 basis points against a pooled rate of 250
# basis points, so the gating ratio is 20000 basis points.
RESTRICTING_AUDIT_COHORTS = [
    ("AGE_18_24", 100, 5),
    ("AGE_25_44", 200, 3),
    ("AGE_65_PLUS", 300, 7),
]

CLEAN_PASSPORT_CAPTURE = {
    "document_type": "PASSPORT",
    "required_feature_count": 10,
    "passed_feature_count": 10,
    "tamper_signal_count": 0,
    "mrz_checksum_valid": True,
}


def _instant(value: str) -> datetime:
    """Parse a server-written ISO 8601 UTC instant for comparison."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestClientVersionConcurrencyOnPublication:
    def test_second_publication_presenting_the_superseded_client_version_is_rejected(self, api):
        """PRD §2.7: "`POST /idv/verification-policies/{id}/publish` therefore requires
        `expected_client_version` carrying the client's `version` as the caller last
        observed it. If that value does not equal the client's current `version`, the
        publish is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412); on success the
        client's `version` increments by one, so an operator working from an earlier read
        of the client is rejected rather than silently replacing a policy it never saw."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_client_version_on_a_second_publication_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        client = create_live_client(name="Acme OCC1")
        stale_version = client["version"]
        register_method_profile("DOCUMENT_SCAN")

        policy_v1 = draft_policy(client["id"], policy_version=1, min_assurance_score=40)
        publish_policy(policy_v1["id"], stale_version)
        policy_v2 = draft_policy(
            client["id"],
            policy_version=2,
            allowed_method_codes=["DOCUMENT_SCAN", "DATABASE_CHECK"],
            min_assurance_score=50,
        )

        response = api.publish_verification_policy(
            policy_v2["id"],
            publish_policy_payload(stale_version),
            make_compliance_officer_headers("co-1"),
        )
        validate_error(response, ApiErrorId.ERR_STALE_CLIENT_VERSION)

        second = read_policy(policy_v2["id"])
        assert second["state"] == "DRAFT", f"the refused draft stays DRAFT, got {second['state']}"
        assert second["published_at"] is None

        first = read_policy(policy_v1["id"])
        assert first["state"] == "PUBLISHED", f"v1 stays PUBLISHED, got {first['state']}"
        assert first["retired_at"] is None

        assert read_client(client["id"])["version"] == 3, "the rejected publish changed nothing"

    def test_republication_at_the_current_client_version_succeeds_and_bumps_it(self, api):
        """PRD §2.7: "If that value does not equal the client's current `version`, the
        publish is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412); on success the
        client's `version` increments by one, so an operator working from an earlier read
        of the client is rejected rather than silently replacing a policy it never saw."
        PRD §3.1: "On success the policy moves `DRAFT → PUBLISHED` with `published_at`
        set to the clock, and in the same request the client's previously `PUBLISHED`
        policy, if any, moves `PUBLISHED → RETIRED` with `retired_at` set to the clock;
        the client's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_client_version_on_a_second_publication_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        client = create_live_client(name="Acme OCC1")
        register_method_profile("DOCUMENT_SCAN")

        policy_v1 = draft_policy(client["id"], policy_version=1, min_assurance_score=40)
        publish_policy(policy_v1["id"], client["version"])
        policy_v2 = draft_policy(
            client["id"],
            policy_version=2,
            allowed_method_codes=["DOCUMENT_SCAN", "DATABASE_CHECK"],
            min_assurance_score=50,
        )

        current_version = read_client(client["id"])["version"]
        assert current_version == 3, (
            f"registration, the LIVE patch and one publish leave version 3, got {current_version}"
        )

        published = validate_success(
            api.publish_verification_policy(
                policy_v2["id"],
                publish_policy_payload(current_version),
                make_compliance_officer_headers("co-1"),
            )
        )
        assert published["state"] == "PUBLISHED"
        assert published["published_at"] is not None

        assert read_policy(policy_v1["id"])["state"] == "RETIRED"
        assert read_client(client["id"])["version"] == 4, (
            "the successful publish pushes the client to version 4"
        )


class TestMethodProfileVersionConcurrencyOnRemediation:
    def _restricted_profile_and_audit(self):
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
        return profile, audit

    def test_remediation_presenting_the_pre_restriction_profile_version_is_rejected(self, api):
        """PRD §2.7: "`POST /idv/bias-audits/{id}/remediation` therefore requires
        `expected_method_profile_version` carrying the audited profile's `version` as
        observed when the remediation evidence was gathered. If that value does not equal
        the profile's current `version`, the remediation is rejected with
        `ERR_STALE_METHOD_PROFILE_VERSION` (HTTP 412); on success the profile's `version`
        increments by one."
        PRD §3.9: "The profile's `bias_state` becomes `RESTRICTED` and its `restricted_at`
        records the clock."
        PRD §2.8: "Each mutated resource independently refreshes its own `updated_at` and
        increments its own `version`; a cascade that touches five sessions bumps five
        session versions."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_method_profile_version_on_remediation_is_rejected
        """
        profile, audit = self._restricted_profile_and_audit()
        stale_version = profile["version"]
        assert stale_version == 1, f"a freshly registered profile is version 1, got {stale_version}"

        response = api.remediate_bias_audit(
            audit["id"],
            remediation_payload(stale_version, remediation_note="vendor recalibration"),
            make_compliance_officer_headers("co-2"),
        )
        error = validate_error(response, ApiErrorId.ERR_STALE_METHOD_PROFILE_VERSION)
        assert error["error_id"] != "ERR_SEGREGATION_OF_DUTIES", "co-2 did not evaluate the audit"

        profile_after = read_method_profile(profile["id"])
        assert profile_after["bias_state"] == "RESTRICTED"
        assert _instant(profile_after["restricted_at"]) == _instant("2026-08-01T00:00:00Z")
        assert profile_after["version"] == 2, (
            f"the restriction cascade bumped the profile to version 2, got {profile_after['version']}"
        )

        audit_after = read_bias_audit(audit["id"])
        assert audit_after["state"] == "REMEDIATION_REQUIRED"
        assert audit_after["remediation_round"] == 0
        assert audit_after["remediated_at"] is None

    def test_remediation_at_the_current_profile_version_succeeds_and_bumps_it(self, api):
        """PRD §2.7: "If that value does not equal the profile's current `version`, the
        remediation is rejected with `ERR_STALE_METHOD_PROFILE_VERSION` (HTTP 412); on
        success the profile's `version` increments by one."
        PRD §3.9: "The profile moves `RESTRICTED → MONITORED` with `restricted_at` set
        back to null, and its `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_method_profile_version_on_remediation_is_rejected
        """
        profile, audit = self._restricted_profile_and_audit()

        current_version = read_method_profile(profile["id"])["version"]
        assert current_version == 2, (
            f"the restriction cascade left the profile at version 2, got {current_version}"
        )

        validate_success(
            api.remediate_bias_audit(
                audit["id"],
                remediation_payload(current_version, remediation_note="vendor recalibration"),
                make_compliance_officer_headers("co-2"),
            )
        )

        profile_after = read_method_profile(profile["id"])
        assert profile_after["bias_state"] == "MONITORED"
        assert profile_after["restricted_at"] is None
        assert profile_after["version"] == 3, (
            f"the successful remediation pushes the profile to version 3, got "
            f"{profile_after['version']}"
        )


class TestMethodLadderSelection:
    def test_server_selector_skips_a_method_code_already_accepted(self, api):
        """PRD §3.3: "A profile is a candidate when all four of the following hold: its
        `method_code` appears in the pinned policy's `allowed_method_codes`; its
        `bias_state` is not `RESTRICTED`; either the session's `risk_level` is not `HIGH`
        or the profile's `strong_evidence` is true; and no attempt of this session
        already carries that same `method_code` in the `ACCEPTED` state."
        PRD §3.3: "Candidates are ranked by `assurance_weight` descending, then by
        `cost_cents` ascending, then by `created_at` ascending; identifiers are never
        used as a ranking or tie-break key, and `created_at` ascending is the final
        arbiter."
        PRD §3.3: "The top-ranked candidate is used and `selection_mode` is recorded as
        `SERVER_SELECTED`."

        Design: Corner/cross_cutting_complexity_layers/ladder_selector_skips_the_method_code_already_accepted
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            method_codes=("DOCUMENT_SCAN", "DATABASE_CHECK"),
            policy_overrides={"min_assurance_score": 60},
            session_overrides={
                "external_subject_ref": "subj-sel",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_id = env["client"]["id"]
        headers = make_client_integrator_headers(client_id)
        document_profile = env["profiles"]["DOCUMENT_SCAN"]
        database_profile = env["profiles"]["DATABASE_CHECK"]

        first = open_attempt(env["session"]["id"], client_id)
        assert first["method_profile_id"] == document_profile["id"], (
            "the highest assurance_weight wins the first selection"
        )
        submit_document_capture(first["id"], client_id, **CLEAN_PASSPORT_CAPTURE)
        finalize_attempt(first["id"], client_id)

        second = validate_success(
            api.create_method_attempt(env["session"]["id"], {}, headers), 201
        )
        assert second["method_profile_id"] == database_profile["id"], (
            f"expected the database-check profile, got {second['method_profile_id']}"
        )
        assert second["method_code"] == "DATABASE_CHECK"
        assert second["method_profile_id"] != document_profile["id"], (
            "the already-accepted method code is excluded despite its higher weight"
        )
        assert second["selection_mode"] == "SERVER_SELECTED"
        assert second["retry_index"] == 0
        assert second["state"] == "AWAITING_EVIDENCE"

        accepted = read_attempt(first["id"], client_id)
        assert accepted["state"] == "ACCEPTED"
        assert accepted["contribution_points"] == 45

        assert read_session(env["session"]["id"], client_id)["assurance_score_provisional"] == 45


class TestImmediateVisibilityOfEscalation:
    def _scored_forged_attempt(self):
        set_clock(DEFAULT_CLOCK)
        return setup_scored_document_attempt(
            capture_overrides=dict(FORGED_CAPTURE),
            policy_overrides={"min_assurance_score": 60},
            session_overrides={
                "external_subject_ref": "subj-now",
                "requested_assurance_tier": "BASIC",
            },
        )

    def test_forged_finalisation_exposes_the_rejection_and_escalation_in_one_request(self, api):
        """PRD §3.6: "A document-scan attempt whose capture was assessed `FORGED` records
        `DOCUMENT_FORGED` and additionally sets the attempt's `tamper_flag` to true; a
        document-scan attempt whose capture was assessed anything else records
        `DOCUMENT_SUSPECT`."
        PRD §3.6: "When a rejection carries `tamper_flag` true, the session moves
        `IN_PROGRESS → MANUAL_REVIEW` in the same request: `fraud_signal_count` — the
        count of that session's attempts whose `tamper_flag` is true — increases by one,
        a manual review case is created in `QUEUED` with `trigger_reason` of
        `FRAUD_SIGNAL` and its service-level deadline set as in §3.8, the provisional
        score is recomputed, and an audit event of type `ESCALATED_TO_REVIEW` is
        appended."

        Design: Corner/consistency_model/escalation_is_fully_visible_in_the_same_response_and_immediate_reads
        """
        env = self._scored_forged_attempt()
        client_id = env["client"]["id"]
        headers = make_client_integrator_headers(client_id)
        assert env["attempt"]["state"] == "SCORED"
        assert env["attempt"]["contribution_points"] == 10

        rejected = validate_success(api.finalize_method_attempt(env["attempt"]["id"], headers))
        assert rejected["state"] == "REJECTED"
        assert rejected["rejection_reason"] == "DOCUMENT_FORGED"
        assert rejected["tamper_flag"] is True
        assert _instant(rejected["finalized_at"]) == _instant("2026-08-01T00:00:00Z")

        session_after = read_session(env["session"]["id"], client_id)
        assert session_after["identity_state"] == "MANUAL_REVIEW", (
            f"the escalation is visible at once, got {session_after['identity_state']}"
        )
        assert session_after["fraud_signal_count"] == 1
        assert session_after["assurance_score_provisional"] == 0
        assert session_after["assurance_score_final"] is None

    def test_escalated_case_is_immediately_readable_with_its_service_level_deadline(self, api):
        """PRD §3.6: "When a rejection carries `tamper_flag` true, the session moves
        `IN_PROGRESS → MANUAL_REVIEW` in the same request: `fraud_signal_count` — the
        count of that session's attempts whose `tamper_flag` is true — increases by one,
        a manual review case is created in `QUEUED` with `trigger_reason` of
        `FRAUD_SIGNAL` and its service-level deadline set as in §3.8, the provisional
        score is recomputed, and an audit event of type `ESCALATED_TO_REVIEW` is
        appended."
        PRD §3.8: "Its `sla_due_at` is its `created_at` plus forty-eight hours on the
        logical clock, and the sweep withdraws it once the clock reaches or passes that
        instant."
        PRD §3.8: "Queued cases hold no credit at all, which is deliberate: escalation
        itself can never be blocked by exhausted capacity, only its assignment can."
        PRD §2.8: "Cascades are always immediate and always complete within the request
        that triggers them."

        Design: Corner/consistency_model/escalation_is_fully_visible_in_the_same_response_and_immediate_reads
        """
        env = self._scored_forged_attempt()
        client_id = env["client"]["id"]
        headers = make_client_integrator_headers(client_id)

        validate_success(api.finalize_method_attempt(env["attempt"]["id"], headers))

        cases, meta = validate_paginated(
            api.list_manual_review_cases(env["session"]["id"], make_review_manager_headers("rm-1"))
        )
        assert meta["total_count"] == 1, (
            f"the escalation is readable immediately, got {meta['total_count']}"
        )
        assert cases[0]["state"] == "QUEUED"
        assert cases[0]["trigger_reason"] == "FRAUD_SIGNAL"
        assert _instant(cases[0]["sla_due_at"]) == _instant("2026-08-03T00:00:00Z"), (
            f"sla_due_at must be 48 hours on, got {cases[0]['sla_due_at']}"
        )

        assert read_client(client_id)["reserved_review_credits"] == 0, (
            "a queued case reserves nothing"
        )

        events, _ = list_session_audit_events(env["session"]["id"])
        escalations = [e for e in events if e["event_type"] == "ESCALATED_TO_REVIEW"]
        assert len(escalations) == 1, (
            f"one ESCALATED_TO_REVIEW event expected, found {len(escalations)}"
        )
