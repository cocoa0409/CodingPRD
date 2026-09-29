"""Lifecycle transitions for sessions, attempts, policies, pathways and review cases.

Covers the declared initial states, the forward transitions that evidence and
decisions drive, the guards that refuse a repeated transition out of a terminal
state, and the lapse sweep.
"""
from datetime import datetime

from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    assert_alternative_pathway,
    assert_audit_event,
    assert_document_capture,
    assert_event_recorded,
    assert_manual_review_case,
    assert_method_attempt,
    assert_verification_policy,
    assert_verification_session,
    attestation_pathway_payload,
    create_document_capture_payload,
    draft_policy,
    finalize_attempt,
    list_session_audit_events,
    make_compliance_officer_headers,
    make_manual_reviewer_headers,
    make_platform_admin_headers,
    open_attempt,
    pathway_decision_payload,
    patch_client,
    publish_policy,
    publish_policy_payload,
    read_attempt,
    read_client,
    read_policy,
    read_session,
    register_client,
    register_method_profile,
    request_pathway,
    review_decision_payload,
    set_clock,
    setup_assigned_review_case,
    setup_finalized_document_attempt,
    setup_scored_document_attempt,
    setup_session,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    vouching_pathway_payload,
)

CLEAN_PASSPORT = {
    "document_type": "PASSPORT",
    "required_feature_count": 10,
    "passed_feature_count": 10,
    "tamper_signal_count": 0,
    "mrz_checksum_valid": True,
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so equality ignores fractional rendering."""
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestDeclaredInitialStates:
    def test_new_attempt_and_both_session_axes_hold_their_initial_states(self, api):
        """PRD §3.2: "The identity axis, `identity_state`, starts at `IN_PROGRESS` and
        moves among `IN_PROGRESS`, `AWAITING_EVIDENCE`, `MANUAL_REVIEW`, `VERIFIED`,
        `REJECTED` and `EXPIRED`, of which the last three are terminal."
        PRD §3.2: "The age axis, `age_state`, moves among `NOT_REQUIRED`, `PENDING`,
        `ASSURED` and `FAILED`; it starts at `NOT_REQUIRED` when the pinned policy sets
        `required_min_age_years` to 0, and at `PENDING` otherwise."
        PRD §3.3: "The attempt opens in `AWAITING_EVIDENCE`, one of `AWAITING_EVIDENCE`,
        `SCORED`, `REQUIRES_RESCORE`, `ACCEPTED`, `REJECTED` and `EXPIRED`, of which the
        last three are terminal."
        PRD §3.3: "Its scoring fields start empty: `evidence_quality_bps` null,
        `match_score_bps` null, `contribution_points` null, `tamper_flag` false,
        `rejection_reason` null and `finalized_at` null."

        Design: Corner/state_machines/attempt_and_both_session_axes_start_in_their_declared_initial_states
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme Init"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-init",
                "requested_assurance_tier": "BASIC",
            },
        )

        response = api.create_method_attempt(
            env["session"]["id"],
            {"method_profile_id": env["profiles"]["DOCUMENT_SCAN"]["id"]},
            env["headers"],
        )
        attempt = validate_success(response, 201)

        assert_method_attempt(attempt)
        assert attempt["state"] == "AWAITING_EVIDENCE"
        assert attempt["evidence_quality_bps"] is None
        assert attempt["contribution_points"] is None
        assert attempt["tamper_flag"] is False
        assert attempt["rejection_reason"] is None
        assert attempt["finalized_at"] is None

        session = read_session(env["session"]["id"])
        assert session["identity_state"] == "IN_PROGRESS"
        assert session["age_state"] == "NOT_REQUIRED"
        assert session["assurance_score_provisional"] == 0

    def test_pathway_initial_state_follows_the_requested_pathway_type(self, api):
        """PRD §3.7: "The request names the owning `session_id` and a `pathway_type` of
        either `VOUCHING` or `ATTESTATION`, and it forks immediately on that choice: a
        `VOUCHING` request must carry `voucher_reference`, the reference of an accredited
        voucher, and opens in `VOUCH_PENDING`; an `ATTESTATION` request must carry
        `attestation_document_ref`, the reference of the self-attestation package, and
        opens in `ATTESTATION_PENDING`."
        PRD §3.7: "While pending, `reviewer_user_id`, `granted_points` and `decided_at`
        are all null."
        PRD §3.2: "The remaining derived fields start at their baselines:
        `assurance_score_provisional` at 0, `assurance_score_final` null,
        `assurance_ceiling` at 100, `resolved_age_band` null, `fraud_signal_count` at 0,
        `step_up_round` at 0, `manual_override_flag` false, `disposition_reason` null and
        `completed_at` null."

        Design: Corner/state_machines/pathway_initial_state_is_keyed_on_pathway_type
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme Path"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-path",
                "requested_assurance_tier": "BASIC",
                "documentation_status": "NO_STANDARD_DOCS",
            },
            extra_profiles={"VOUCHING_ATTESTATION": {}},
        )
        session_id = env["session"]["id"]

        vouching = validate_success(
            api.create_alternative_pathway(session_id, vouching_pathway_payload(), env["headers"]),
            201,
        )
        attestation = validate_success(
            api.create_alternative_pathway(
                session_id, attestation_pathway_payload(), env["headers"]
            ),
            201,
        )

        assert_alternative_pathway(vouching)
        assert vouching["pathway_type"] == "VOUCHING"
        assert vouching["state"] == "VOUCH_PENDING"

        assert_alternative_pathway(attestation)
        assert attestation["pathway_type"] == "ATTESTATION"
        assert attestation["state"] == "ATTESTATION_PENDING"

        for pathway in (vouching, attestation):
            assert pathway["reviewer_user_id"] is None
            assert pathway["granted_points"] is None
            assert pathway["decided_at"] is None

        session = read_session(session_id)
        assert session["assurance_ceiling"] == 100, (
            "a merely requested pathway must not move the ceiling"
        )


class TestForwardTransitions:
    def test_clean_capture_scores_the_attempt_and_lifts_the_provisional_score(self, api):
        """PRD §3.4: "A document where every required feature validated scores exactly
        10000."
        PRD §3.4: "Second, `tamper_tier_multiplier_bps` is read off the *pre-penalty* base
        score, never off any later figure. A `base_score_bps` of 9000 or more yields a
        multiplier of 10000; a `base_score_bps` of at least 7000 and below 9000 yields
        15000; a `base_score_bps` below 7000 yields 20000."
        PRD §3.4: "Third, `tamper_penalty_bps` is 450 basis points per tamper signal,
        scaled by that tier multiplier: 450 multiplied by `tamper_signal_count`,
        multiplied by `tamper_tier_multiplier_bps`, divided by ten thousand, truncated
        toward zero."
        PRD §3.4: "Sixth, the `assessment` verdict is `AUTHENTIC` when
        `authenticity_score_bps` is at or above the pinned policy's
        `doc_authenticity_floor_bps`, `SUSPECT` when it is at least 5000 basis points but
        below that floor, and `FORGED` otherwise."
        PRD §3.4: "The capture's `authenticity_score_bps` becomes the attempt's
        `evidence_quality_bps` verbatim, and the attempt's `contribution_points` is the
        resolved profile's `assurance_weight` multiplied by that quality, divided by ten
        thousand, truncated toward zero."
        PRD §3.4: "The attempt advances `AWAITING_EVIDENCE → SCORED`, and the session's
        `assurance_score_provisional` is recomputed as described in §3.8."

        Design: Corner/state_machines/clean_document_capture_transitions_the_attempt_to_scored
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme Clean"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-clean",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_id = env["client"]["id"]
        attempt = open_attempt(
            env["session"]["id"], client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
        )

        capture = validate_success(
            api.create_document_capture(
                attempt["id"],
                create_document_capture_payload(**CLEAN_PASSPORT),
                env["headers"],
            ),
            201,
        )

        assert_document_capture(capture)
        assert capture["base_score_bps"] == 10000
        assert capture["tamper_tier_multiplier_bps"] == 10000
        assert capture["tamper_penalty_bps"] == 0
        assert capture["authenticity_score_bps"] == 10000
        assert capture["assessment"] == "AUTHENTIC"

        scored = read_attempt(attempt["id"], client_id)
        assert scored["state"] == "SCORED"
        assert scored["evidence_quality_bps"] == 10000
        assert scored["contribution_points"] == 45

        session = read_session(env["session"]["id"])
        assert session["assurance_score_provisional"] == 45
        assert session["identity_state"] == "IN_PROGRESS"

        assert read_client(client_id)["stored_template_count"] == 0, (
            "a document scan produces no biometric template"
        )

    def test_publication_stamps_published_at_and_bumps_the_owning_client_version(self, api):
        """PRD §3.1: "On success the policy moves `DRAFT → PUBLISHED` with `published_at`
        set to the clock, and in the same request the client's previously `PUBLISHED`
        policy, if any, moves `PUBLISHED → RETIRED` with `retired_at` set to the clock;
        the client's `version` increments by one."
        PRD §2.7: "on success the client's `version` increments by one, so an operator
        working from an earlier read of the client is rejected rather than silently
        replacing a policy it never saw."
        PRD §2.9: "Verification policies may be filtered by `client_id` and `state`."

        Design: Corner/state_machines/policy_publication_stamps_published_at_and_bumps_the_client_version
        """
        set_clock(DEFAULT_CLOCK)
        client = register_client(name="Acme Pub")
        live = patch_client(client["id"], integration_state="LIVE")
        assert live["version"] == 2, "registration then the LIVE patch leaves version 2"
        register_method_profile("DOCUMENT_SCAN")
        policy = draft_policy(
            client["id"],
            policy_version=1,
            allowed_method_codes=["DOCUMENT_SCAN"],
            min_assurance_score=40,
        )

        response = api.publish_verification_policy(
            policy["id"],
            publish_policy_payload(live["version"]),
            make_compliance_officer_headers(),
        )
        published = validate_success(response, 200)

        assert_verification_policy(published)
        assert published["state"] == "PUBLISHED"
        assert _instant(published["published_at"]) == _instant("2026-08-01T00:00:00Z")
        assert published["retired_at"] is None
        assert published["degraded_flag"] is False

        assert read_client(client["id"])["version"] == 3, (
            "publication increments the client version by one, from 2 to 3"
        )

        rows, meta = validate_paginated(
            api.list_verification_policies(
                make_compliance_officer_headers(),
                params={"client_id": client["id"], "state": "PUBLISHED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == policy["id"]

    def test_session_creation_appends_a_session_created_audit_event(self, api):
        """PRD §3.2: "Creation appends an audit event of type `SESSION_CREATED`."
        PRD §2.10: "An audit event records the `session_id` it describes, an `event_type`
        drawn from `SESSION_CREATED`, `ATTEMPT_FINALIZED`, `STEP_UP_TRIGGERED`,
        `ESCALATED_TO_REVIEW`, `REVIEW_DECIDED`, `PATHWAY_DECIDED`,
        `METHOD_RESTRICTION_APPLIED`, `TEMPLATE_DELETED` and `SESSION_TERMINAL`, the
        `actor_role` that caused it, the `actor_user_id` that caused it, a
        `payload_summary` naming the fields the transition mutated, and the `occurred_at`
        instant read off the logical clock."
        PRD §2.10: "For a caller-driven event, `actor_role` is the caller's `X-User-Role`
        and `actor_user_id` is the caller's `X-User-ID`."
        PRD §2.1: "When `X-User-Role` is `ClientIntegrator`, `X-User-ID` is the `id` of the
        acting `Client`; ownership checks on any resource that references a `Client`
        compare the resource's client foreign-key field to `X-User-ID`, walking through
        the owning session where the resource does not carry the client reference
        directly."
        PRD §2.9: "A session's audit trail may be filtered by `event_type`, and it is
        ordered by `occurred_at` ascending and then `created_at` ascending."

        Design: Corner/state_machines/session_creation_appends_a_session_created_audit_event
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme Audit"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-audit",
                "requested_assurance_tier": "BASIC",
            },
        )
        session_id = env["session"]["id"]

        # The audit trail is a PlatformAdmin / ComplianceOfficer read (PRD §5
        # endpoint table), so the trail is inspected as the admin even though the
        # event it records was caused by the ClientIntegrator.
        rows, meta = validate_paginated(
            api.list_audit_events(
                session_id,
                make_platform_admin_headers(),
                params={"event_type": "SESSION_CREATED"},
            )
        )

        assert meta["total_count"] == 1
        event = rows[0]
        assert_audit_event(event)
        assert event["event_type"] == "SESSION_CREATED"
        assert event["session_id"] == session_id
        assert event["actor_role"] == "ClientIntegrator"
        assert event["actor_user_id"] == env["client"]["id"], (
            "a ClientIntegrator's actor id is the acting client's id"
        )
        assert _instant(event["occurred_at"]) == _instant("2026-08-01T00:00:00Z")
        assert "version" not in event, "an audit event is a write-once observation"


class TestTerminalAndGuardedTransitions:
    def test_completion_is_blocked_while_an_attempt_awaits_finalisation(self, api):
        """PRD §3.8: "It further requires that no attempt of the session is still open in
        `AWAITING_EVIDENCE`, `SCORED` or `REQUIRES_RESCORE`, otherwise
        `ERR_ATTEMPT_PENDING_FINALIZATION`; that no pathway of the session is still in
        `VOUCH_PENDING` or `ATTESTATION_PENDING`, otherwise
        `ERR_PENDING_PATHWAY_BLOCKS_COMPLETION`; and that, when the pinned policy sets
        `required_min_age_years` above zero, `age_state` is no longer `PENDING`, otherwise
        `ERR_AGE_ASSURANCE_MISSING`."
        PRD §3.8: "`assurance_score_final` is written exactly once, by the transition that
        gives the session a terminal identity state or escalates it to manual review at
        completion, and it is null before that."

        Design: Corner/state_machines/completion_with_an_unfinalized_attempt_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme Pend"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-pend",
                "requested_assurance_tier": "BASIC",
            },
        )
        session_id = env["session"]["id"]
        attempt = open_attempt(
            session_id, env["client"]["id"], env["profiles"]["DOCUMENT_SCAN"]["id"]
        )

        response = api.complete_session(session_id, env["headers"])
        validate_error(response, ApiErrorId.ERR_ATTEMPT_PENDING_FINALIZATION)

        session = read_session(session_id)
        assert_verification_session(session)
        assert session["identity_state"] == "IN_PROGRESS"
        assert session["assurance_score_final"] is None
        assert session["completed_at"] is None
        assert session["disposition_reason"] is None
        assert read_attempt(attempt["id"])["state"] == "AWAITING_EVIDENCE"

    def test_vouching_approval_without_an_eligible_profile_is_rejected(self, api, inclusion_reviewer_headers):
        """PRD §3.7: "Approval of a `VOUCHING` pathway (`VOUCH_PENDING → APPROVED`)
        requires the pathway to be pending, the session's identity axis to be at
        `IN_PROGRESS` or `AWAITING_EVIDENCE`, the clock not to be past `expires_at`, and
        at least one method profile with `method_code` of `VOUCHING_ATTESTATION` and a
        `bias_state` other than `RESTRICTED` to exist — an empty candidate set is rejected
        with `ERR_NO_ELIGIBLE_METHOD`."
        PRD §3.7: "While pending, `reviewer_user_id`, `granted_points` and `decided_at`
        are all null."

        Design: Corner/state_machines/pathway_approval_without_any_vouching_profile_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme NoVouch"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-novouch",
                "requested_assurance_tier": "BASIC",
                "documentation_status": "NO_STANDARD_DOCS",
            },
        )
        session_id = env["session"]["id"]
        pathway = request_pathway(session_id, env["client"]["id"], "VOUCHING")

        response = api.decide_alternative_pathway(
            pathway["id"], pathway_decision_payload("APPROVE"), inclusion_reviewer_headers
        )
        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_METHOD)

        rows, meta = validate_paginated(
            api.list_alternative_pathways(session_id, env["headers"])
        )
        assert meta["total_count"] == 1
        assert rows[0]["state"] == "VOUCH_PENDING"
        assert rows[0]["granted_points"] is None
        assert rows[0]["reviewer_user_id"] is None
        assert rows[0]["decided_at"] is None

        session = read_session(session_id)
        assert session["assurance_score_provisional"] == 0
        assert session["assurance_ceiling"] == 100

    def test_step_up_from_in_progress_is_rejected(self, api):
        """PRD §3.6: "Requesting step-up requires the session to be at
        `AWAITING_EVIDENCE`, requires the clock not to be past `expires_at`, and requires
        `step_up_round` to still be below `step_up_max_rounds` — a session that has
        already consumed its budget is rejected with `ERR_STEP_UP_LIMIT_REACHED`."
        PRD §3.6: "On success the session moves `AWAITING_EVIDENCE → IN_PROGRESS`,
        `step_up_round` increases by one, the client's `pending_stepup_count` decreases by
        one, and an audit event of type `STEP_UP_TRIGGERED` is appended."
        PRD §2.6: "`ERR_SESSION_STATE_INVALID` (409) — the session is in a state the
        operation admits. Every session-mutating endpoint."

        Design: Corner/state_machines/step_up_from_an_in_progress_session_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme Step"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-step",
                "requested_assurance_tier": "BASIC",
            },
        )
        session_id = env["session"]["id"]

        response = api.step_up_session(session_id, env["headers"])
        validate_error(response, ApiErrorId.ERR_SESSION_STATE_INVALID)

        session = read_session(session_id)
        assert session["identity_state"] == "IN_PROGRESS"
        assert session["step_up_round"] == 0
        assert read_client(env["client"]["id"])["pending_stepup_count"] == 0

        events, _ = list_session_audit_events(session_id)
        assert_event_recorded(events, "STEP_UP_TRIGGERED", expected_count=0)

    def test_second_capture_on_a_scored_attempt_reports_evidence_already_submitted(self, api):
        """PRD §3.3: "An attempt accepts exactly one evidence row, and the kind of
        evidence must match its `method_code`."
        PRD §3.3: "A mismatched kind is refused with `ERR_EVIDENCE_METHOD_MISMATCH`; a
        second submission of any kind is refused with `ERR_EVIDENCE_ALREADY_SUBMITTED`,
        which per §2.6 takes precedence over the `ERR_ATTEMPT_STATE_INVALID` that the
        now-`SCORED` attempt would otherwise produce."

        Design: Corner/state_machines/second_document_capture_on_a_scored_attempt_is_rejected_as_already_submitted
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_scored_document_attempt(
            capture_overrides=dict(CLEAN_PASSPORT),
            client_overrides={"name": "Acme Dup"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-dup",
                "requested_assurance_tier": "BASIC",
            },
        )
        attempt_id = env["attempt"]["id"]

        response = api.create_document_capture(
            attempt_id,
            create_document_capture_payload(**CLEAN_PASSPORT),
            env["headers"],
        )
        validate_error(response, ApiErrorId.ERR_EVIDENCE_ALREADY_SUBMITTED)

        rows, meta = validate_paginated(api.list_document_captures(attempt_id, env["headers"]))
        assert meta["total_count"] == 1, "the refused resubmission stored no second row"
        assert rows[0]["authenticity_score_bps"] == 10000

        attempt = read_attempt(attempt_id)
        assert attempt["state"] == "SCORED"
        assert attempt["evidence_quality_bps"] == 10000
        assert attempt["contribution_points"] == 45
        assert read_session(env["session"]["id"])["assurance_score_provisional"] == 45

    def test_verified_session_refuses_a_second_completion(self, api):
        """PRD §3.8: "It requires the identity axis to be at `IN_PROGRESS` and the clock
        not to be past `expires_at`."
        PRD §3.8: "When the age axis is not failed and the freshly written
        `assurance_score_final` is at or above the pinned policy's `min_assurance_score`,
        the session moves `IN_PROGRESS → VERIFIED` with `disposition_reason` set to
        `SCORE_SATISFIED`, `completed_at` set to the clock, the same retention schedule
        applied and the same `SESSION_TERMINAL` event appended."
        PRD §2.6: "`ERR_SESSION_STATE_INVALID` (409) — the session is in a state the
        operation admits. Every session-mutating endpoint."

        Design: Corner/state_machines/verified_session_rejects_a_second_completion
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_finalized_document_attempt(
            capture_overrides=dict(CLEAN_PASSPORT),
            client_overrides={"name": "Acme Done"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-done",
                "requested_assurance_tier": "BASIC",
            },
        )
        session_id = env["session"]["id"]

        completed = validate_success(api.complete_session(session_id, env["headers"]), 200)
        assert completed["identity_state"] == "VERIFIED"
        assert completed["assurance_score_final"] == 45
        assert completed["disposition_reason"] == "SCORE_SATISFIED"
        assert _instant(completed["completed_at"]) == _instant("2026-08-01T00:00:00Z")

        response = api.complete_session(session_id, env["headers"])
        validate_error(response, ApiErrorId.ERR_SESSION_STATE_INVALID)

        session = read_session(session_id)
        assert session["identity_state"] == "VERIFIED"
        assert session["assurance_score_final"] == 45
        assert session["disposition_reason"] == "SCORE_SATISFIED"

        events, _ = list_session_audit_events(session_id)
        assert_event_recorded(events, "SESSION_TERMINAL", expected_count=1)

    def test_second_finalisation_of_an_accepted_attempt_is_rejected(self, api):
        """PRD §3.6: "A `SCORED` attempt whose `evidence_quality_bps` is at or above the
        resolved profile's `acceptance_floor_bps` advances `SCORED → ACCEPTED`; one below
        the floor advances `SCORED → REJECTED`."
        PRD §3.6: "Either outcome stamps `finalized_at` with the clock, recomputes the
        session's provisional score, and appends an audit event of type
        `ATTEMPT_FINALIZED`."
        PRD §2.6: "`ERR_ATTEMPT_STATE_INVALID` (409) — the attempt is in a state the
        operation admits. The three evidence-submission endpoints and
        `POST /idv/method-attempts/{id}/finalize`."

        Design: Corner/state_machines/second_finalize_of_an_accepted_attempt_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_finalized_document_attempt(
            capture_overrides=dict(CLEAN_PASSPORT),
            client_overrides={"name": "Acme Fin"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-fin",
                "requested_assurance_tier": "BASIC",
            },
        )
        attempt_id = env["attempt"]["id"]
        assert env["attempt"]["state"] == "ACCEPTED"

        response = api.finalize_method_attempt(attempt_id, env["headers"])
        validate_error(response, ApiErrorId.ERR_ATTEMPT_STATE_INVALID)

        attempt = read_attempt(attempt_id)
        assert attempt["state"] == "ACCEPTED"
        assert _instant(attempt["finalized_at"]) == _instant("2026-08-01T00:00:00Z")
        assert attempt["contribution_points"] == 45
        assert read_session(env["session"]["id"])["assurance_score_provisional"] == 45

        events, _ = list_session_audit_events(env["session"]["id"])
        assert_event_recorded(events, "ATTEMPT_FINALIZED", expected_count=1)

    def test_publishing_an_already_published_policy_is_rejected(self, api):
        """PRD §3.1: "It requires the policy to still be in `DRAFT` — otherwise
        `ERR_POLICY_STATE_INVALID` — and requires the owning client not to be
        `SUSPENDED`, otherwise `ERR_CLIENT_NOT_LIVE`."
        PRD §2.6: "`ERR_POLICY_STATE_INVALID` (409) — the policy is `DRAFT`.
        `POST /idv/verification-policies/{id}/publish`."
        PRD §3.1: "On success the policy moves `DRAFT → PUBLISHED` with `published_at` set
        to the clock, and in the same request the client's previously `PUBLISHED` policy,
        if any, moves `PUBLISHED → RETIRED` with `retired_at` set to the clock; the
        client's `version` increments by one."

        Design: Corner/state_machines/republishing_an_already_published_policy_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        client = register_client(name="Acme Twice")
        live = patch_client(client["id"], integration_state="LIVE")
        register_method_profile("DOCUMENT_SCAN")
        policy = draft_policy(
            client["id"],
            policy_version=1,
            allowed_method_codes=["DOCUMENT_SCAN"],
            min_assurance_score=40,
        )
        publish_policy(policy["id"], live["version"])
        version_after_publication = read_client(client["id"])["version"]
        assert version_after_publication == 3

        response = api.publish_verification_policy(
            policy["id"],
            publish_policy_payload(version_after_publication),
            make_compliance_officer_headers(),
        )
        validate_error(response, ApiErrorId.ERR_POLICY_STATE_INVALID)

        stored = read_policy(policy["id"])
        assert stored["state"] == "PUBLISHED"
        assert _instant(stored["published_at"]) == _instant("2026-08-01T00:00:00Z")
        assert stored["retired_at"] is None
        assert read_client(client["id"])["version"] == 3, (
            "the refused republication performs no second version bump"
        )

    def test_decided_case_refuses_a_second_decision(self, api):
        """PRD §3.8: "It requires the case to be `ASSIGNED`, requires the caller's
        `X-User-ID` to equal `assigned_reviewer_user_id`, and requires the caller's
        `X-User-ID` to differ from `assigned_by_user_id`."
        PRD §2.6: "`ERR_REVIEW_CASE_STATE_INVALID` (409) — the case is `QUEUED` for
        assignment and `ASSIGNED` for a decision."
        PRD §3.8: "On success the case moves `ASSIGNED → DECIDED` with `decision`,
        `decided_by_user_id` and `decided_at` written, the reserved credit is released
        back to `available_review_credits`, and the client's `consumed_review_count` rises
        by one."
        PRD §3.8: "`APPROVE` moves the session `MANUAL_REVIEW → VERIFIED`, sets
        `manual_override_flag` to true, sets `disposition_reason` to `MANUAL_OVERRIDE`,
        sets `completed_at` to the clock, writes `assurance_score_final`, and applies the
        retention schedule to every template still in `STORED`."

        Design: Corner/state_machines/decided_review_case_rejects_a_second_decision
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_assigned_review_case(
            client_overrides={"name": "Acme Case"},
            session_overrides={
                "external_subject_ref": "subj-case",
                "requested_assurance_tier": "BASIC",
            },
        )
        case_id = env["case"]["id"]
        reviewer_headers = make_manual_reviewer_headers()

        decided = validate_success(
            api.decide_manual_review_case(
                case_id, review_decision_payload("APPROVE"), reviewer_headers
            ),
            200,
        )
        assert_manual_review_case(decided)
        assert decided["state"] == "DECIDED"
        assert decided["decision"] == "APPROVE"

        response = api.decide_manual_review_case(
            case_id, review_decision_payload("REJECT"), reviewer_headers
        )
        # The approval drove the session terminal as well as the case, so both the
        # session-state check (§2.6 #16, "every session-mutating endpoint") and the
        # case-state check (§2.6 #20) now fail. §3.8 enumerates only the case,
        # assignee and segregation requirements for a verdict, so whether #16 is in
        # scope for this endpoint is not settled by the PRD; either state-invalid
        # error is a faithful reading.
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_REVIEW_CASE_STATE_INVALID,
                ApiErrorId.ERR_SESSION_STATE_INVALID,
            ],
        )

        session = read_session(env["session"]["id"])
        assert session["identity_state"] == "VERIFIED"
        assert session["manual_override_flag"] is True
        assert session["disposition_reason"] == "MANUAL_OVERRIDE"

        client = read_client(env["client"]["id"])
        assert client["reserved_review_credits"] == 0
        assert client["available_review_credits"] == 1
        assert client["consumed_review_count"] == 1, (
            "the refused second decision consumes no further credit"
        )


class TestLapseAndReviewReturn:
    def test_expiry_sweep_expires_only_the_non_terminal_attempts(self, api, platform_admin_headers):
        """PRD §3.10: "Any session whose identity axis is at `IN_PROGRESS` or
        `AWAITING_EVIDENCE` and whose `expires_at` the clock has passed moves to
        `EXPIRED`. Every attempt of that session in `AWAITING_EVIDENCE`, `SCORED` or
        `REQUIRES_RESCORE` moves to `EXPIRED` with `rejection_reason` of `EXPIRED_WINDOW`
        and `finalized_at` set to the clock."
        PRD §3.10: "The session's `disposition_reason` becomes `EXPIRED_TTL` and its
        `completed_at` is stamped, the retention rules above are applied to every template
        still in `STORED`, and an audit event of type `SESSION_TERMINAL` is appended."
        PRD §3.10: "Lapse writes no `assurance_score_final`: an expired session's final
        score stays null, because nothing was ever adjudicated."
        PRD §3.10: "It takes no input and reports four figures: `expired_session_count`,
        `withdrawn_case_count`, `deleted_template_count`, and `swept_at`, the clock instant
        at which the sweep ran."
        PRD §3.6: "Either outcome stamps `finalized_at` with the clock, recomputes the
        session's provisional score, and appends an audit event of type
        `ATTEMPT_FINALIZED`."

        Design: Corner/state_machines/expiry_sweep_expires_only_the_non_terminal_attempts_of_the_lapsed_session
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme Sweep"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-sweep",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_id = env["client"]["id"]
        session_id = env["session"]["id"]
        profile_id = env["profiles"]["DOCUMENT_SCAN"]["id"]

        accepted = open_attempt(session_id, client_id, profile_id)
        validate_success(
            api.create_document_capture(
                accepted["id"], create_document_capture_payload(**CLEAN_PASSPORT), env["headers"]
            ),
            201,
        )
        finalize_attempt(accepted["id"], client_id)
        open_attempt_row = open_attempt(session_id, client_id, profile_id)

        set_clock("2026-08-01T01:00:01Z")
        sweep = validate_success(api.run_retention_sweep(platform_admin_headers), 200)

        assert sweep["expired_session_count"] == 1
        assert sweep["withdrawn_case_count"] == 0
        assert sweep["deleted_template_count"] == 0
        assert _instant(sweep["swept_at"]) == _instant("2026-08-01T01:00:01Z")

        survivor = read_attempt(accepted["id"])
        assert survivor["state"] == "ACCEPTED", "a terminal attempt is left alone"
        assert survivor["rejection_reason"] is None
        assert _instant(survivor["finalized_at"]) == _instant("2026-08-01T00:00:00Z")

        lapsed = read_attempt(open_attempt_row["id"])
        assert lapsed["state"] == "EXPIRED"
        assert lapsed["rejection_reason"] == "EXPIRED_WINDOW"
        assert _instant(lapsed["finalized_at"]) == _instant("2026-08-01T01:00:01Z")

        session = read_session(session_id)
        assert session["identity_state"] == "EXPIRED"
        assert session["disposition_reason"] == "EXPIRED_TTL"
        assert _instant(session["completed_at"]) == _instant("2026-08-01T01:00:01Z")
        assert session["assurance_score_final"] is None
        assert session["assurance_score_provisional"] == 45

        assert read_client(client_id)["pending_stepup_count"] == 0

    def test_return_for_step_up_releases_the_credit_and_reopens_the_session(self, api):
        """PRD §3.8: "`RETURN_FOR_STEP_UP` additionally requires the clock not to be past
        `expires_at`, and moves the session `MANUAL_REVIEW → AWAITING_EVIDENCE`: the
        client's `pending_stepup_count` rises by one, and because the session is not
        terminal, no `assurance_score_final` is written, no `completed_at` is stamped,
        `manual_override_flag` stays false and no template is touched."
        PRD §3.8: "In all three cases the credit release and the `consumed_review_count`
        increment happen identically."
        PRD §3.8: "An audit event of type `REVIEW_DECIDED` is appended for all three
        verdicts."

        Design: Corner/state_machines/review_return_for_step_up_releases_the_credit_and_reopens_the_session
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_assigned_review_case(
            client_overrides={"name": "Acme Return"},
            session_overrides={
                "external_subject_ref": "subj-return",
                "requested_assurance_tier": "BASIC",
            },
        )
        session_id = env["session"]["id"]

        decided = validate_success(
            api.decide_manual_review_case(
                env["case"]["id"],
                review_decision_payload("RETURN_FOR_STEP_UP"),
                make_manual_reviewer_headers(),
            ),
            200,
        )

        assert decided["state"] == "DECIDED"
        assert decided["decision"] == "RETURN_FOR_STEP_UP"

        session = read_session(session_id)
        assert session["identity_state"] == "AWAITING_EVIDENCE"
        assert session["manual_override_flag"] is False
        assert session["disposition_reason"] is None
        assert session["assurance_score_final"] is None
        assert session["completed_at"] is None
        assert session["step_up_round"] == 0, "the return does not itself consume a round"
        assert session["fraud_signal_count"] == 1

        client = read_client(env["client"]["id"])
        assert client["reserved_review_credits"] == 0
        assert client["available_review_credits"] == 1
        assert client["consumed_review_count"] == 1
        assert client["pending_stepup_count"] == 1

        _, meta = validate_paginated(
            api.list_audit_events(
                session_id,
                make_platform_admin_headers(),
                params={"event_type": "REVIEW_DECIDED"},
            )
        )
        assert meta["total_count"] == 1
