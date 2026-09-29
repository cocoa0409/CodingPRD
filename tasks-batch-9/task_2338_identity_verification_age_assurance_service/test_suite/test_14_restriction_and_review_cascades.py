"""Transitive cascades: bias restriction, fraud escalation and service-level lapse."""
from test_helpers import (
    RESTRICTING_COHORTS,
    SUSPECT_CAPTURE,
    assign_case_payload,
    complete_session,
    evaluate_audit,
    finalize_attempt,
    list_session_audit_events,
    list_session_cases,
    list_session_templates,
    make_review_manager_headers,
    open_attempt,
    read_attempt,
    read_client,
    read_method_profile,
    read_policy,
    read_session,
    run_sweep,
    set_clock,
    setup_bias_audit_with_cohorts,
    setup_scored_document_attempt,
    setup_session_in_manual_review_from_fraud,
    setup_stored_biometric_template,
    submit_document_capture,
    validate_success,
)

RESTRICTION_POLICY = {
    "min_assurance_score": 60,
    "doc_authenticity_floor_bps": 8000,
    "required_min_age_years": 0,
    "step_up_max_rounds": 2,
}


def _scored_attempt_then_restricting_evaluation():
    """A live session holding one SCORED attempt when its vendor is restricted."""
    env = setup_scored_document_attempt(
        capture_overrides={
            "document_type": "PASSPORT",
            "required_feature_count": 16,
            "passed_feature_count": 14,
            "tamper_signal_count": 0,
            "mrz_checksum_valid": True,
        },
        method_codes=("DOCUMENT_SCAN", "DATABASE_CHECK"),
        client_overrides={"granted_review_credits": 2},
        policy_overrides=dict(RESTRICTION_POLICY),
        session_overrides={"external_subject_ref": "subj-r4a"},
    )
    audit = setup_bias_audit_with_cohorts(
        env["profiles"]["DOCUMENT_SCAN"]["id"], cohorts=tuple(RESTRICTING_COHORTS)
    )
    env["audit"] = evaluate_audit(audit["id"])
    return env


class TestBiasEvaluationCascadesToTheClientCounter:
    def test_a_gating_ratio_at_the_restriction_threshold_restricts_the_profile(self):
        """PRD §3.9: "When the gating ratio reaches 12500, the audit moves
        `COLLECTING → REMEDIATION_REQUIRED`, all disparity fields are written, and the
        restriction cascades transitively through everything the profile touches. The profile's
        `bias_state` becomes `RESTRICTED` and its `restricted_at` records the clock."

        Design: Difficulty/transitive_cascade/bias_evaluation_cascades_five_levels_to_client_stepup_counter
        """
        env = _scored_attempt_then_restricting_evaluation()

        assert env["audit"]["state"] == "REMEDIATION_REQUIRED"
        assert env["audit"]["disparity_ratio_max_to_pooled_bps"] == 12500
        profile = read_method_profile(env["profiles"]["DOCUMENT_SCAN"]["id"])
        assert profile["bias_state"] == "RESTRICTED"
        assert profile["restricted_at"].startswith("2026-08-01T00:00:00")

    def test_the_scored_attempt_is_sent_back_for_rescore_with_its_contribution_cleared(self):
        """PRD §3.9: "Every method attempt on that profile sitting in `AWAITING_EVIDENCE`,
        `SCORED` or `REQUIRES_RESCORE` moves to `REQUIRES_RESCORE` with its
        `contribution_points` set back to null."

        Design: Difficulty/transitive_cascade/bias_evaluation_cascades_five_levels_to_client_stepup_counter
        """
        env = _scored_attempt_then_restricting_evaluation()
        attempt = read_attempt(env["attempt"]["id"], env["client"]["id"])

        assert attempt["state"] == "REQUIRES_RESCORE"
        assert attempt["contribution_points"] is None
        assert attempt["evidence_quality_bps"] == 8750

    def test_the_session_parks_for_evidence_and_lifts_the_client_step_up_counter(self):
        """PRD §3.9: "Every affected non-terminal session at `IN_PROGRESS` moves
        `IN_PROGRESS → AWAITING_EVIDENCE`, and the owning client's `pending_stepup_count` rises
        by one for each such session." "Each affected session's `assurance_score_provisional` is
        recomputed — and because attempts in `REQUIRES_RESCORE` count for nothing, a mid-flight
        restriction visibly lowers the running score."

        Design: Difficulty/transitive_cascade/bias_evaluation_cascades_five_levels_to_client_stepup_counter
        """
        env = _scored_attempt_then_restricting_evaluation()
        client_id = env["client"]["id"]

        session = read_session(env["session"]["id"], client_id)
        assert session["identity_state"] == "AWAITING_EVIDENCE"
        assert session["assurance_score_provisional"] == 0
        assert read_client(client_id)["pending_stepup_count"] == 1

    def test_the_pinned_policy_is_flagged_degraded_and_the_session_trail_records_the_restriction(self):
        """PRD §3.9: "Every pinned verification policy whose `allowed_method_codes` admits the
        restricted method has its `degraded_flag` set to true." "Each affected session receives
        an audit event of type `METHOD_RESTRICTION_APPLIED`."

        Design: Difficulty/transitive_cascade/bias_evaluation_cascades_five_levels_to_client_stepup_counter
        """
        env = _scored_attempt_then_restricting_evaluation()

        assert read_policy(env["policy"]["id"])["degraded_flag"] is True
        events, meta = list_session_audit_events(
            env["session"]["id"], event_type="METHOD_RESTRICTION_APPLIED"
        )
        assert meta["total_count"] == 1
        assert events[0]["event_type"] == "METHOD_RESTRICTION_APPLIED"


def _forged_document_finalisation():
    """A forged capture finalised into a fraud escalation."""
    return setup_session_in_manual_review_from_fraud(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 2},
        policy_overrides=dict(RESTRICTION_POLICY),
        session_overrides={"external_subject_ref": "subj-r4b"},
    )


class TestForgedFinalisationCascadesToReviewQueue:
    def test_a_forged_capture_rejects_the_attempt_with_a_tamper_flag(self, api):
        """PRD §3.6: "A document-scan attempt whose capture was assessed `FORGED` records
        `DOCUMENT_FORGED` and additionally sets the attempt's `tamper_flag` to true; a document-scan
        attempt whose capture was assessed anything else records `DOCUMENT_SUSPECT`." PRD §3.4:
        "when `mrz_checksum_valid` is false, `authenticity_score_bps` is the lesser of the raw
        score and 4000 basis points".

        Design: Difficulty/transitive_cascade/forged_document_finalization_cascades_to_queued_review_case_and_audit_event
        """
        env = _forged_document_finalisation()
        captures = validate_success(
            api.list_document_captures(env["attempt"]["id"], env["headers"])
        )

        assert captures[0]["base_score_bps"] == 5000
        assert captures[0]["tamper_tier_multiplier_bps"] == 20000
        assert captures[0]["tamper_penalty_bps"] == 2700
        assert captures[0]["authenticity_score_bps"] == 2300
        assert captures[0]["assessment"] == "FORGED"

        attempt = read_attempt(env["attempt"]["id"], env["client"]["id"])
        assert attempt["state"] == "REJECTED"
        assert attempt["tamper_flag"] is True
        assert attempt["rejection_reason"] == "DOCUMENT_FORGED"

    def test_the_tampered_rejection_escalates_the_session_and_queues_a_fraud_case(self):
        """PRD §3.6: "When a rejection carries `tamper_flag` true, the session moves
        `IN_PROGRESS → MANUAL_REVIEW` in the same request: `fraud_signal_count` — the count of
        that session's attempts whose `tamper_flag` is true — increases by one, a manual review
        case is created in `QUEUED` with `trigger_reason` of `FRAUD_SIGNAL` and its service-level
        deadline set as in §3.8, the provisional score is recomputed, and an audit event of type
        `ESCALATED_TO_REVIEW` is appended."

        Design: Difficulty/transitive_cascade/forged_document_finalization_cascades_to_queued_review_case_and_audit_event
        """
        env = _forged_document_finalisation()

        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["identity_state"] == "MANUAL_REVIEW"
        assert session["fraud_signal_count"] == 1
        assert session["assurance_score_provisional"] == 0

        cases, meta = list_session_cases(env["session"]["id"])
        assert meta["total_count"] == 1
        assert cases[0]["state"] == "QUEUED"
        assert cases[0]["trigger_reason"] == "FRAUD_SIGNAL"
        assert cases[0]["sla_due_at"].startswith("2026-08-03T00:00:00")

    def test_a_queued_escalation_reserves_no_review_credit_and_appends_one_event(self):
        """PRD §3.8: "Queued cases hold no credit at all, which is deliberate: escalation itself
        can never be blocked by exhausted capacity, only its assignment can." PRD §3.6: "an audit
        event of type `ESCALATED_TO_REVIEW` is appended".

        Design: Difficulty/transitive_cascade/forged_document_finalization_cascades_to_queued_review_case_and_audit_event
        """
        env = _forged_document_finalisation()

        client = read_client(env["client"]["id"])
        assert client["available_review_credits"] == 2
        assert client["reserved_review_credits"] == 0

        _, meta = list_session_audit_events(
            env["session"]["id"], event_type="ESCALATED_TO_REVIEW"
        )
        assert meta["total_count"] == 1


def _assigned_case_at_its_service_level_deadline(api):
    """A session in review whose single reserved case has just reached its deadline."""
    set_clock("2026-08-10T09:00:00Z")
    env = setup_stored_biometric_template(
        method_codes=("BIOMETRIC_COMPARISON", "DOCUMENT_SCAN"),
        client_overrides={
            "biometric_retention_mode": "RETAIN_90_DAYS",
            "granted_review_credits": 1,
        },
        policy_overrides={
            "min_assurance_score": 60,
            "pad_threshold_bps": 7500,
            "doc_authenticity_floor_bps": 8000,
            "required_min_age_years": 0,
            "step_up_max_rounds": 0,
        },
        session_overrides={"external_subject_ref": "subj-r4c", "biometric_consent": True},
    )
    client_id = env["client"]["id"]
    session_id = env["session"]["id"]

    document_attempt = open_attempt(
        session_id, client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
    )
    submit_document_capture(document_attempt["id"], client_id, **dict(SUSPECT_CAPTURE))
    finalize_attempt(document_attempt["id"], client_id)

    env["session"] = complete_session(session_id, client_id)
    cases, _ = list_session_cases(session_id)
    env["case"] = validate_success(
        api.assign_manual_review_case(
            cases[0]["id"], assign_case_payload("mr-1"), make_review_manager_headers("rm-1")
        )
    )

    set_clock("2026-08-12T09:00:00Z")
    return env


class TestServiceLevelLapseCascadesToTemplateCustody:
    def test_the_sweep_withdraws_the_overdue_case_and_releases_its_credit(self, api):
        """PRD §3.10: "Any case in `QUEUED` or `ASSIGNED` whose `sla_due_at` the clock has
        reached or passed moves to `WITHDRAWN` with `decided_at` set to the clock; a case at
        exactly its deadline is withdrawn, the comparison being inclusive. A credit is released
        only when the withdrawn case was `ASSIGNED` — a case withdrawn straight out of `QUEUED` had
        reserved nothing, so nothing is released, and `consumed_review_count` does not move for a
        withdrawal in either case since it counts only cases that reached `DECIDED`."

        Design: Difficulty/transitive_cascade/sla_lapse_sweep_cascades_from_case_withdrawal_to_template_purge_schedule
        """
        env = _assigned_case_at_its_service_level_deadline(api)
        sweep = run_sweep()

        assert sweep["withdrawn_case_count"] == 1
        assert sweep["expired_session_count"] == 0
        assert sweep["deleted_template_count"] == 0
        assert sweep["swept_at"].startswith("2026-08-12T09:00:00")

        cases, _ = list_session_cases(env["session"]["id"])
        assert cases[0]["state"] == "WITHDRAWN"
        assert cases[0]["decision"] is None
        assert cases[0]["decided_at"].startswith("2026-08-12T09:00:00")

        client = read_client(env["client"]["id"])
        assert client["reserved_review_credits"] == 0
        assert client["available_review_credits"] == 1
        assert client["consumed_review_count"] == 0

    def test_the_abandoned_session_is_rejected_with_its_final_score_written(self, api):
        """PRD §3.10: "The abandoned session moves `MANUAL_REVIEW → REJECTED` with
        `disposition_reason` of `REVIEW_LAPSED` and `completed_at` set to the clock,
        `assurance_score_final` is written, the retention rules are applied to every template
        still in `STORED`, and an audit event of type `SESSION_TERMINAL` is appended."

        Design: Difficulty/transitive_cascade/sla_lapse_sweep_cascades_from_case_withdrawal_to_template_purge_schedule
        """
        env = _assigned_case_at_its_service_level_deadline(api)
        run_sweep()

        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["identity_state"] == "REJECTED"
        assert session["disposition_reason"] == "REVIEW_LAPSED"
        assert session["completed_at"].startswith("2026-08-12T09:00:00")
        assert session["assurance_score_final"] == 31

    def test_the_retained_template_is_scheduled_for_purge_ninety_days_out(self, api):
        """PRD §3.10: "the template moves `STORED → PURGE_SCHEDULED` and its
        `retention_expires_at` is set to the session's `completed_at` plus ninety days on the
        logical clock, preserving the time of day." "the client's `stored_template_count`
        decrements exactly once, at the moment the template leaves `STORED`."

        Design: Difficulty/transitive_cascade/sla_lapse_sweep_cascades_from_case_withdrawal_to_template_purge_schedule
        """
        env = _assigned_case_at_its_service_level_deadline(api)
        run_sweep()

        templates, meta = list_session_templates(env["session"]["id"])
        assert meta["total_count"] == 1
        assert templates[0]["state"] == "PURGE_SCHEDULED"
        assert templates[0]["retention_expires_at"].startswith("2026-11-10T09:00:00")
        assert templates[0]["deleted_at"] is None
        assert read_client(env["client"]["id"])["stored_template_count"] == 0
