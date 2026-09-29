"""Endpoint-level behaviour: the operations sweep, the clock, the admin patch,
bias evaluation and the session audit trail.

Every test builds its own preconditions from scratch through the documented
endpoints, because the database is empty and the logical clock is reset before
each test runs.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    TEST_USERS,
    add_cohort_metric,
    complete_session,
    finalize_attempt,
    make_compliance_officer_headers,
    open_attempt,
    open_bias_audit,
    open_session,
    read_client,
    read_method_profile,
    read_policy,
    read_session,
    register_client,
    register_method_profile,
    set_clock,
    setup_client_with_published_policy,
    setup_session_in_manual_review_from_fraud,
    submit_document_capture,
    submit_liveness_check,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]


def _instant(value):
    """Compare logical-clock instants without depending on fractional digits."""
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    text = value[:-1] if value.endswith("Z") else value
    return text.split(".")[0]


class TestOperationsSweep:
    """One pass of the sweep across all three deadline families."""

    def test_sweep_reports_the_three_counters_from_one_pass(self, api):
        """PRD §3.10: "It takes no input and reports four figures:
        `expired_session_count`, `withdrawn_case_count`, `deleted_template_count`, and
        `swept_at`, the clock instant at which the sweep ran."
        PRD §3.10: "The abandoned session moves `MANUAL_REVIEW → REJECTED` with
        `disposition_reason` of `REVIEW_LAPSED` and `completed_at` set to the clock,
        `assurance_score_final` is written, the retention rules are applied to every
        template still in `STORED`, and an audit event of type `SESSION_TERMINAL` is
        appended."
        PRD §3.10: "Any template in `PURGE_SCHEDULED` whose `retention_expires_at` the
        clock has reached or passed moves `PURGE_SCHEDULED → DELETED` with `deleted_at`
        set to the clock and `deletion_reason` of `RETENTION_EXPIRED`, and an audit event
        of type `TEMPLATE_DELETED` is appended; a template whose deadline exactly equals
        the clock is deleted, the comparison being inclusive."

        Design: Corner/endpoints/retention_sweep_reports_the_three_counters_from_one_pass
        """
        set_clock("2026-08-10T09:00:00Z")
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN", "BIOMETRIC_COMPARISON"),
            client_overrides={
                "name": "Acme Sweep3",
                "biometric_retention_mode": "RETAIN_90_DAYS",
                "granted_review_credits": 1,
            },
            policy_overrides={"min_assurance_score": 20},
        )
        client_id = env["client"]["id"]

        verified = open_session(
            client_id,
            external_subject_ref="subj-sw1",
            requested_assurance_tier="BASIC",
            biometric_consent=True,
        )
        biometric_attempt = open_attempt(
            verified["id"], client_id, env["profiles"]["BIOMETRIC_COMPARISON"]["id"]
        )
        submit_liveness_check(
            biometric_attempt["id"],
            client_id,
            capture_modality="ACTIVE",
            pad_score_bps=9000,
            match_score_bps=9200,
        )
        finalize_attempt(biometric_attempt["id"], client_id)
        completed = complete_session(verified["id"], client_id)
        assert completed["identity_state"] == "VERIFIED", (
            f"the biometric session must verify, got {completed['identity_state']}"
        )

        escalated = open_session(
            client_id, external_subject_ref="subj-sw2", requested_assurance_tier="BASIC"
        )
        document_attempt = open_attempt(
            escalated["id"], client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
        )
        submit_document_capture(
            document_attempt["id"],
            client_id,
            document_type="RESIDENCE_PERMIT",
            required_feature_count=10,
            passed_feature_count=5,
            tamper_signal_count=3,
            mrz_checksum_valid=False,
        )
        finalize_attempt(document_attempt["id"], client_id)
        cases, _ = validate_paginated(
            api.list_manual_review_cases(
                escalated["id"], TEST_USERS["review_manager_headers"]
            )
        )
        lapsing_case = cases[0]
        assert lapsing_case["state"] == "QUEUED"
        assert _instant(lapsing_case["sla_due_at"]) == _instant("2026-08-12T09:00:00Z"), (
            f"the case deadline is 48 hours out, got {lapsing_case['sla_due_at']}"
        )

        set_clock("2026-11-08T07:00:00Z")
        lapsing_session = open_session(
            client_id, external_subject_ref="subj-sw3", requested_assurance_tier="BASIC"
        )
        set_clock("2026-11-08T09:00:00Z")

        report = validate_success(api.run_retention_sweep(ADMIN_HEADERS), 200)
        assert report["expired_session_count"] == 1, (
            f"exactly one session is past its window, got {report['expired_session_count']}"
        )
        assert report["withdrawn_case_count"] == 1, (
            f"exactly one case has blown its deadline, got {report['withdrawn_case_count']}"
        )
        assert report["deleted_template_count"] == 1, (
            f"exactly one template is due for purge, got {report['deleted_template_count']}"
        )
        assert _instant(report["swept_at"]) == _instant("2026-11-08T09:00:00Z"), (
            f"swept_at is the clock instant of the pass, got {report['swept_at']}"
        )

        lapsed = read_session(lapsing_session["id"], client_id)
        assert lapsed["identity_state"] == "EXPIRED", (
            f"the overdue session lapses, got {lapsed['identity_state']}"
        )
        assert lapsed["disposition_reason"] == "EXPIRED_TTL", (
            f"the lapse reason is EXPIRED_TTL, got {lapsed['disposition_reason']}"
        )
        assert lapsed["completed_at"] is not None, "the lapse stamps completed_at"

        withdrawn, _ = validate_paginated(
            api.list_manual_review_cases(
                escalated["id"], TEST_USERS["review_manager_headers"]
            )
        )
        assert withdrawn[0]["state"] == "WITHDRAWN", (
            f"the overdue case is withdrawn, got {withdrawn[0]['state']}"
        )
        abandoned = read_session(escalated["id"], client_id)
        assert abandoned["identity_state"] == "REJECTED", (
            f"the abandoned session is rejected, not expired, got {abandoned['identity_state']}"
        )
        assert abandoned["disposition_reason"] == "REVIEW_LAPSED", (
            f"the abandonment reason is REVIEW_LAPSED, got {abandoned['disposition_reason']}"
        )
        assert abandoned["assurance_score_final"] == 0, (
            "no attempt of the abandoned session was accepted, so its final score is 0, got "
            f"{abandoned['assurance_score_final']}"
        )

        templates, _ = validate_paginated(
            api.list_biometric_templates(verified["id"], ADMIN_HEADERS)
        )
        assert len(templates) == 1
        assert templates[0]["state"] == "DELETED", (
            f"the scheduled template is purged, got {templates[0]['state']}"
        )
        assert templates[0]["deletion_reason"] == "RETENTION_EXPIRED", (
            f"the purge reason is RETENTION_EXPIRED, got {templates[0]['deletion_reason']}"
        )

        client = read_client(client_id)
        assert client["stored_template_count"] == 0, (
            f"no template remains in custody, got {client['stored_template_count']}"
        )
        assert client["reserved_review_credits"] == 0, (
            f"a queued withdrawal reserved nothing, got {client['reserved_review_credits']}"
        )
        assert client["available_review_credits"] == 1, (
            f"the grant is intact, got {client['available_review_credits']}"
        )
        assert client["consumed_review_count"] == 0, (
            f"a withdrawal is not a decision, got {client['consumed_review_count']}"
        )

        _, purge_events = validate_paginated(
            api.list_audit_events(
                verified["id"], ADMIN_HEADERS, params={"event_type": "TEMPLATE_DELETED"}
            )
        )
        assert purge_events["total_count"] == 1, (
            f"the purge appends exactly one deletion event, got {purge_events['total_count']}"
        )
        assert read_session(verified["id"], client_id)["identity_state"] == "VERIFIED", (
            "the purge leaves the verified outcome standing"
        )


class TestClockEndpoint:
    """Moving the logical clock and observing it in freshly derived instants."""

    def test_clock_move_is_echoed_and_visible_in_derived_fields(self, api):
        """PRD §2.4: "A `PlatformAdmin` may move it by supplying `current_utc`, and the
        response echoes the resulting `current_utc`; no business entity is mutated by that
        call."
        PRD §3.2: "`expires_at` is set to the session's `created_at` plus sixty minutes on
        the logical clock."

        Design: Corner/endpoints/clock_endpoint_moves_time_and_the_move_is_visible_in_derived_fields
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"name": "Acme Clock"},
            policy_overrides={"min_assurance_score": 40},
        )
        client_id = env["client"]["id"]
        version_before = read_client(client_id)["version"]

        echoed = validate_success(
            api.set_clock("2026-09-15T14:30:00Z", ADMIN_HEADERS), 200
        )
        assert _instant(echoed["current_utc"]) == _instant("2026-09-15T14:30:00Z"), (
            f"the clock response echoes the new instant, got {echoed['current_utc']}"
        )

        session = open_session(
            client_id, external_subject_ref="subj-clock", requested_assurance_tier="BASIC"
        )
        assert _instant(session["created_at"]) == _instant("2026-09-15T14:30:00Z"), (
            f"the session is stamped with the moved clock, got {session['created_at']}"
        )
        assert _instant(session["expires_at"]) == _instant("2026-09-15T15:30:00Z"), (
            f"the window closes sixty minutes later, got {session['expires_at']}"
        )

        assert read_client(client_id)["version"] == version_before, (
            "the clock move mutates no business entity"
        )
        assert _instant(read_policy(env["policy"]["id"])["published_at"]) == _instant(
            DEFAULT_CLOCK
        ), "the policy keeps the instant at which it was actually published"


class TestClientAdminPatch:
    """The admin patch touches only what the request carried."""

    def test_patch_mutates_only_the_supplied_field(self, api):
        """PRD §3.1: "It accepts any non-empty subset of `integration_state`,
        `biometric_retention_mode`, `daily_session_quota` and `granted_review_credits`; a
        patch carrying none of them is rejected with `ERR_INVALID_REQUEST`."
        PRD §3.1: "After a grant change the available-credit figure is re-derived from the
        client's currently assigned cases so that the pool invariant of §2.8 still holds,
        and the client's `version` increments by one — which, per §2.7, invalidates any
        publish request an operator had prepared from an earlier read."

        Design: Corner/endpoints/client_patch_mutates_only_the_supplied_field
        """
        set_clock(DEFAULT_CLOCK)
        client = register_client(
            name="Acme Patch Scope",
            home_jurisdiction_code="GB",
            biometric_retention_mode="RETAIN_WITH_CONSENT",
            daily_session_quota=25,
            granted_review_credits=3,
        )

        patched = validate_success(
            api.patch_client(client["id"], {"daily_session_quota": 40}, ADMIN_HEADERS), 200
        )
        assert patched["daily_session_quota"] == 40, (
            f"the supplied field takes the new value, got {patched['daily_session_quota']}"
        )
        assert patched["integration_state"] == "SANDBOX", (
            f"the omitted posture is untouched, got {patched['integration_state']}"
        )
        assert patched["biometric_retention_mode"] == "RETAIN_WITH_CONSENT", (
            f"the omitted retention mode is untouched, got {patched['biometric_retention_mode']}"
        )
        assert patched["granted_review_credits"] == 3, (
            f"the omitted grant is untouched, got {patched['granted_review_credits']}"
        )
        assert patched["reserved_review_credits"] == 0, (
            f"nothing is reserved, got {patched['reserved_review_credits']}"
        )
        assert patched["available_review_credits"] == 3, (
            f"the whole grant stays available, got {patched['available_review_credits']}"
        )
        assert patched["version"] == 2, (
            f"one mutation lifts the version to 2, got {patched['version']}"
        )
        assert patched["home_jurisdiction_code"] == "GB", (
            f"registration data is untouched, got {patched['home_jurisdiction_code']}"
        )

        reread = validate_success(api.get_client(client["id"], ADMIN_HEADERS), 200)
        assert reread["daily_session_quota"] == 40
        assert reread["integration_state"] == "SANDBOX"
        assert reread["biometric_retention_mode"] == "RETAIN_WITH_CONSENT"
        assert reread["granted_review_credits"] == 3
        assert reread["available_review_credits"] == 3
        assert reread["version"] == 2, (
            f"the read agrees with the patch response, got version {reread['version']}"
        )


class TestBiasEvaluationEndpoint:
    """Evaluating an audit whose cohorts are all below the inclusion sample."""

    def test_three_undersized_cohorts_leave_both_ratios_null(self, api):
        """PRD §3.9: "The row is marked `included_in_ratio` true when its `attempt_count`
        is at least 50, and false below that — small cohorts are recorded and disclosed but
        do not drive the gate."
        PRD §3.9: "`included_cohort_count` is the size of that set and
        `excluded_cohort_count` is the number of in-scope rows less that size.
        `insufficient_sample` is true when fewer than two rows are included; when it is
        true both disparity ratios stay null, the audit still moves `COLLECTING →
        EVALUATED`, and the profile's `bias_state` is left exactly as it was."
        PRD §3.9: "If fewer than 3 rows are in scope, the evaluation is refused with
        `ERR_INSUFFICIENT_COHORT_COVERAGE` before any figure is computed."

        Design: Corner/endpoints/evaluation_with_three_undersized_cohorts_leaves_both_ratios_null
        """
        set_clock(DEFAULT_CLOCK)
        profile = register_method_profile("DOCUMENT_SCAN")
        audit = open_bias_audit(
            profile["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
        )
        add_cohort_metric(audit["id"], "AGE_18_24", 40, 2)
        add_cohort_metric(audit["id"], "AGE_25_44", 40, 1)
        add_cohort_metric(audit["id"], "AGE_45_64", 40, 3)

        evaluated = validate_success(
            api.evaluate_bias_audit(audit["id"], make_compliance_officer_headers()), 200
        )
        assert evaluated["state"] == "EVALUATED", (
            f"the audit still reaches EVALUATED, got {evaluated['state']}"
        )
        assert evaluated["insufficient_sample"] is True, (
            f"no row clears the inclusion sample, got {evaluated['insufficient_sample']}"
        )
        assert evaluated["disparity_ratio_max_to_min_bps"] is None, (
            f"the disclosure ratio stays null, got {evaluated['disparity_ratio_max_to_min_bps']}"
        )
        assert evaluated["disparity_ratio_max_to_pooled_bps"] is None, (
            f"the gating ratio stays null, got {evaluated['disparity_ratio_max_to_pooled_bps']}"
        )
        assert evaluated["included_cohort_count"] == 0, (
            f"no row is included, got {evaluated['included_cohort_count']}"
        )
        assert evaluated["excluded_cohort_count"] == 3, (
            f"all three in-scope rows are excluded, got {evaluated['excluded_cohort_count']}"
        )
        assert evaluated["worst_cohort_code"] is None, (
            f"no included cohort can be the worst, got {evaluated['worst_cohort_code']}"
        )
        assert evaluated["pooled_frr_bps"] is None, (
            f"no pooled rate is derived, got {evaluated['pooled_frr_bps']}"
        )
        assert evaluated["max_frr_bps"] is None, (
            f"no maximum rate is derived, got {evaluated['max_frr_bps']}"
        )
        assert evaluated["min_frr_bps"] is None, (
            f"no minimum rate is derived, got {evaluated['min_frr_bps']}"
        )

        rows, meta = validate_paginated(
            api.list_cohort_metrics(audit["id"], OFFICER_HEADERS)
        )
        assert meta["total_count"] == 3
        for row in rows:
            assert row["included_in_ratio"] is False, (
                f"{row['cohort_code']} holds 40 attempts and must be excluded"
            )

        stored_profile = read_method_profile(profile["id"])
        assert stored_profile["bias_state"] == "CLEARED", (
            f"the profile's posture is left exactly as it was, got {stored_profile['bias_state']}"
        )
        assert stored_profile["restricted_at"] is None, (
            f"no restriction instant is stamped, got {stored_profile['restricted_at']}"
        )
        assert stored_profile["version"] == 1, (
            f"the profile is not mutated at all, got version {stored_profile['version']}"
        )


class TestSessionAuditTrailEndpoint:
    """Listing and filtering the trail an escalation leaves behind."""

    def test_trail_lists_the_escalation_history_in_clock_order(self, api):
        """PRD §3.2: "Creation appends an audit event of type `SESSION_CREATED`."
        PRD §3.6: "Either outcome stamps `finalized_at` with the clock, recomputes the
        session's provisional score, and appends an audit event of type
        `ATTEMPT_FINALIZED`."
        PRD §2.9: "A session's audit trail may be filtered by `event_type`, and it is
        ordered by `occurred_at` ascending and then `created_at` ascending."

        Design: Corner/endpoints/session_audit_trail_lists_and_filters_the_escalation_history
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session_in_manual_review_from_fraud(
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"name": "Acme Trail"},
            session_overrides={
                "external_subject_ref": "subj-trail",
                "requested_assurance_tier": "BASIC",
            },
        )
        session_id = env["session"]["id"]
        client_id = env["client"]["id"]

        events, meta = validate_paginated(
            api.list_audit_events(session_id, OFFICER_HEADERS)
        )
        assert meta["total_count"] == 3, (
            f"creation, finalisation and escalation are all recorded, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            f"three events fit in one page, got has_more {meta['has_more']}"
        )
        assert events[0]["event_type"] == "SESSION_CREATED", (
            f"the earliest event is the session's creation, got {events[0]['event_type']}"
        )
        assert {event["event_type"] for event in events[1:]} == {
            "ESCALATED_TO_REVIEW",
            "ATTEMPT_FINALIZED",
        }, (
            "finalisation and escalation both belong to the trail, got "
            f"{[event['event_type'] for event in events[1:]]}"
        )
        for event in events:
            assert _instant(event["occurred_at"]) == _instant(DEFAULT_CLOCK), (
                f"every event is stamped with the frozen clock, got {event['occurred_at']}"
            )
            assert event["session_id"] == session_id, (
                f"every event describes this session, got {event['session_id']}"
            )
            assert event["actor_user_id"] == client_id, (
                f"the integrator drove every transition, got {event['actor_user_id']}"
            )

    def test_trail_filter_narrows_to_one_event_type(self, api):
        """PRD §2.9: "A session's audit trail may be filtered by `event_type`, and it is
        ordered by `occurred_at` ascending and then `created_at` ascending."
        PRD §3.6: "When a rejection carries `tamper_flag` true, the session moves
        `IN_PROGRESS → MANUAL_REVIEW` in the same request: `fraud_signal_count` — the count
        of that session's attempts whose `tamper_flag` is true — increases by one, a manual
        review case is created in `QUEUED` with `trigger_reason` of `FRAUD_SIGNAL` and its
        service-level deadline set as in §3.8, the provisional score is recomputed, and an
        audit event of type `ESCALATED_TO_REVIEW` is appended."

        Design: Corner/endpoints/session_audit_trail_lists_and_filters_the_escalation_history
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session_in_manual_review_from_fraud(
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"name": "Acme Trail Filter"},
            session_overrides={
                "external_subject_ref": "subj-trail-filter",
                "requested_assurance_tier": "BASIC",
            },
        )
        session_id = env["session"]["id"]
        client_id = env["client"]["id"]

        events, meta = validate_paginated(
            api.list_audit_events(
                session_id, OFFICER_HEADERS, params={"event_type": "ESCALATED_TO_REVIEW"}
            )
        )
        assert meta["total_count"] == 1, (
            f"one escalation happened on this session, got {meta['total_count']}"
        )
        assert events[0]["event_type"] == "ESCALATED_TO_REVIEW", (
            f"the filter admits only escalations, got {events[0]['event_type']}"
        )

        session = read_session(session_id, client_id)
        assert session["identity_state"] == "MANUAL_REVIEW", (
            f"the tampered finalisation escalates the session, got {session['identity_state']}"
        )
        assert session["fraud_signal_count"] == 1, (
            f"one attempt carried a tamper flag, got {session['fraud_signal_count']}"
        )
