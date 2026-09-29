"""Input, uniqueness and gate-order validation across the verification service.

Every test builds its own preconditions from scratch through the documented
endpoints, because the database is empty and the logical clock is reset before
each test runs.
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    TEST_USERS,
    client_version,
    create_cohort_metric_payload,
    create_document_capture_payload,
    create_liveness_check_payload,
    create_verification_policy_payload,
    create_verification_session_payload,
    document_scan_profile_payload,
    draft_policy,
    estimation_result_payload,
    make_client_integrator_headers,
    make_compliance_officer_headers,
    open_attempt,
    open_bias_audit,
    add_cohort_metric,
    open_session,
    publish_policy,
    read_attempt,
    read_bias_audit,
    read_client,
    read_method_profile,
    read_policy,
    read_session,
    record_estimation_result,
    register_method_profile,
    request_pathway,
    set_clock,
    setup_age_gated_session,
    setup_client_with_published_policy,
    setup_session,
    validate_error,
    validate_paginated,
    validate_success,
    vouching_pathway_payload,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]


class TestUniquenessConstraints:
    """Uniqueness rules on vendor profiles, policy versions and cohort rows."""

    def test_repeat_method_and_vendor_pair_is_rejected(self, api):
        """PRD §3.1: "The combination of method and vendor must be unique across all
        profiles; a repeat is rejected with `ERR_METHOD_PROFILE_DUPLICATE`."

        Design: Corner/validations/duplicate_method_code_and_vendor_code_pair_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        first = register_method_profile("DOCUMENT_SCAN")

        response = api.create_method_profile(
            document_scan_profile_payload(
                assurance_weight=40,
                acceptance_floor_bps=7000,
                far_bps=50,
                frr_bps=500,
                cost_cents=90,
            ),
            ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_METHOD_PROFILE_DUPLICATE)

        stored = read_method_profile(first["id"])
        assert stored["assurance_weight"] == 45, (
            f"the stored profile must keep assurance_weight 45, got {stored['assurance_weight']}"
        )
        assert stored["cost_cents"] == 120, (
            f"the stored profile must keep cost_cents 120, got {stored['cost_cents']}"
        )
        assert stored["version"] == 1, (
            f"the rejected registration must perform no write, got version {stored['version']}"
        )

    def test_repeat_policy_version_for_the_same_client_is_rejected(self, api):
        """PRD §3.1: "Each draft carries a client-scoped `policy_version` of at least 1,
        unique within the client; a repeat is rejected with `ERR_POLICY_VERSION_DUPLICATE`."

        Design: Corner/validations/duplicate_client_and_policy_version_pair_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"name": "Acme PolDup"},
            policy_overrides={"policy_version": 1, "min_assurance_score": 40},
        )
        client_id = env["client"]["id"]
        headers = make_client_integrator_headers(client_id)

        response = api.create_verification_policy(
            create_verification_policy_payload(
                client_id,
                policy_version=1,
                allowed_method_codes=["DATABASE_CHECK"],
                min_assurance_score=20,
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_POLICY_VERSION_DUPLICATE)

        _, meta = validate_paginated(
            api.list_verification_policies(headers, params={"client_id": client_id})
        )
        assert meta["total_count"] == 1, (
            f"the rejected draft must not be stored, got total_count {meta['total_count']}"
        )

        policy = read_policy(env["policy"]["id"])
        assert policy["allowed_method_codes"] == ["DOCUMENT_SCAN"], (
            "the published policy must be untouched, got "
            f"{policy['allowed_method_codes']}"
        )
        assert policy["state"] == "PUBLISHED", (
            f"the published policy must stay PUBLISHED, got {policy['state']}"
        )

    def test_repeat_cohort_code_within_one_audit_is_rejected(self, api):
        """PRD §3.9: "Each row names a `cohort_code` — one of `AGE_13_17`, `AGE_18_24`,
        `AGE_25_44`, `AGE_45_64`, `AGE_65_PLUS`, `SKIN_TONE_I_III` or `SKIN_TONE_IV_VI` —
        which must be unique within the audit, a repeat being rejected with
        `ERR_COHORT_DUPLICATE`."
        PRD §3.9: "Two rates are derived on submission: `frr_bps` is ten thousand
        multiplied by `false_reject_count`, divided by `attempt_count`, rounded half up,
        and `far_bps` is the same computation over `false_accept_count`; both are 0 when
        `attempt_count` is 0."

        Design: Corner/validations/duplicate_cohort_code_within_one_audit_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        profile = register_method_profile("DOCUMENT_SCAN")
        audit = open_bias_audit(
            profile["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
        )
        add_cohort_metric(audit["id"], "AGE_18_24", 100, 5, 2)

        response = api.create_cohort_metric(
            audit["id"],
            create_cohort_metric_payload("AGE_18_24", 400, 40, 3),
            make_compliance_officer_headers(),
        )
        validate_error(response, ApiErrorId.ERR_COHORT_DUPLICATE)

        rows, meta = validate_paginated(
            api.list_cohort_metrics(audit["id"], OFFICER_HEADERS)
        )
        assert meta["total_count"] == 1, (
            f"the duplicate cohort row must not be stored, got {meta['total_count']}"
        )
        assert rows[0]["attempt_count"] == 100, (
            f"the surviving row keeps attempt_count 100, got {rows[0]['attempt_count']}"
        )
        assert rows[0]["frr_bps"] == 500, (
            f"5 false rejects over 100 attempts is 500 bps, got {rows[0]['frr_bps']}"
        )

        stored_audit = read_bias_audit(audit["id"])
        assert stored_audit["state"] == "COLLECTING", (
            f"the audit stays COLLECTING, got {stored_audit['state']}"
        )
        assert stored_audit["pooled_frr_bps"] is None, (
            f"no pooled rate is derived before evaluation, got {stored_audit['pooled_frr_bps']}"
        )


class TestEvidenceAndAgeValidation:
    """Evidence-kind matching and the age-accuracy documentation obligation."""

    def test_document_capture_on_a_database_check_attempt_is_rejected(self, api):
        """PRD §3.3: "An attempt accepts exactly one evidence row, and the kind of
        evidence must match its `method_code`. A mismatched kind is refused with
        `ERR_EVIDENCE_METHOD_MISMATCH`; a second submission of any kind is refused with
        `ERR_EVIDENCE_ALREADY_SUBMITTED`, which per §2.6 takes precedence over the
        `ERR_ATTEMPT_STATE_INVALID` that the now-`SCORED` attempt would otherwise produce."

        Design: Corner/validations/document_capture_on_a_database_check_attempt_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            method_codes=("DOCUMENT_SCAN", "DATABASE_CHECK"),
            client_overrides={"name": "Acme Mismatch"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-mismatch",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_id = env["client"]["id"]
        headers = env["headers"]
        attempt = open_attempt(
            env["session"]["id"], client_id, env["profiles"]["DATABASE_CHECK"]["id"]
        )

        response = api.create_document_capture(
            attempt["id"],
            create_document_capture_payload(
                required_feature_count=10, passed_feature_count=10
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_EVIDENCE_METHOD_MISMATCH)

        stored = read_attempt(attempt["id"], client_id)
        assert stored["state"] == "AWAITING_EVIDENCE", (
            f"the attempt must stay AWAITING_EVIDENCE, got {stored['state']}"
        )
        assert stored["method_code"] == "DATABASE_CHECK", (
            f"the attempt's method is unchanged, got {stored['method_code']}"
        )
        assert stored["evidence_quality_bps"] is None, (
            f"no quality is scored, got {stored['evidence_quality_bps']}"
        )
        assert stored["contribution_points"] is None, (
            f"no contribution is derived, got {stored['contribution_points']}"
        )

        _, meta = validate_paginated(api.list_document_captures(attempt["id"], headers))
        assert meta["total_count"] == 0, (
            f"the rejected capture must not be stored, got {meta['total_count']}"
        )

        session = read_session(env["session"]["id"], client_id)
        assert session["assurance_score_provisional"] == 0, (
            "the provisional score must stay 0, got "
            f"{session['assurance_score_provisional']}"
        )

    def test_age_estimate_resolving_to_an_undocumented_band_is_rejected(self, api):
        """PRD §3.7: "The server snapshots that profile's `vendor_code` into
        `source_vendor_code` and its `estimation_mae_months` into `mae_months_snapshot`,
        then derives the safety buffer: `buffer_months` is `mae_months_snapshot`
        multiplied by the pinned policy's `age_buffer_multiplier_bps`, divided by ten
        thousand, rounded *up* to a whole month."
        PRD §3.7: "The `resolved_band` follows from `effective_age_months` alone: `U13` at
        155 months or fewer, `B13_15` above 155 and at most 191, `B16_17` above 191 and at
        most 215, `B18_20` above 215 and at most 251, and `A21_PLUS` above 251."
        PRD §3.7: "For an estimation result the server then reads
        `documented_accuracy_bps` out of the estimating profile's `band_accuracy_bps` map
        at exactly that band; if the vendor has published no accuracy figure for the band
        the estimate landed in, the result is not stored at all and the request is
        rejected with `ERR_AGE_ACCURACY_UNDOCUMENTED`."

        Design: Corner/validations/age_estimate_resolving_to_an_undocumented_band_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_age_gated_session(
            required_min_age_years=18,
            age_buffer_multiplier_bps=15000,
            estimation_mae_months=12,
            band_accuracy_bps={"U13": 8500, "B16_17": 9100, "B18_20": 9400, "A21_PLUS": 9600},
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"name": "Acme Band"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-band",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_id = env["client"]["id"]
        headers = env["headers"]
        session_id = env["session"]["id"]

        response = api.create_age_assurance_result(
            session_id,
            estimation_result_payload(env["profiles"]["AGE_ESTIMATION"]["id"], 190),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_AGE_ACCURACY_UNDOCUMENTED)

        _, meta = validate_paginated(api.list_age_assurance_results(session_id, headers))
        assert meta["total_count"] == 0, (
            f"the rejected estimate must not be stored, got {meta['total_count']}"
        )

        session = read_session(session_id, client_id)
        assert session["age_state"] == "PENDING", (
            f"the age axis stays PENDING, got {session['age_state']}"
        )
        assert session["resolved_age_band"] is None, (
            f"no band is resolved, got {session['resolved_age_band']}"
        )
        assert session["identity_state"] == "IN_PROGRESS", (
            f"the identity axis is untouched, got {session['identity_state']}"
        )


class TestMethodAndQuotaGates:
    """Direct-attemptability, rolling quota and the inclusion-pathway switch."""

    def test_explicit_request_for_a_vouching_profile_is_not_directly_attemptable(self, api):
        """PRD §3.3: "The named profile is used, `selection_mode` is recorded as
        `CLIENT_REQUESTED`, and three gates apply in the order fixed by §2.6: first, a
        profile whose `method_code` is `VOUCHING_ATTESTATION` or `AGE_ESTIMATION` is
        refused with `ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE`, because those two methods are
        granted by adjudication and by the age axis respectively and can never appear in a
        policy's admitted list; then a profile whose `method_code` falls outside the pinned
        policy's `allowed_method_codes` is refused with `ERR_METHOD_NOT_IN_POLICY`; then a
        profile whose `bias_state` is `RESTRICTED` is refused with
        `ERR_METHOD_RESTRICTED_BY_BIAS`."
        PRD §2.6: "This check deliberately precedes the admitted-method check at position
        33, because neither of the two non-attemptable methods can ever appear in a
        policy's admitted list."

        Design: Corner/validations/explicit_request_for_a_vouching_profile_is_rejected_as_not_attemptable
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            method_codes=("DOCUMENT_SCAN",),
            extra_profiles={"VOUCHING_ATTESTATION": {}},
            client_overrides={"name": "Acme NotAtt"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-notatt",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_id = env["client"]["id"]
        headers = env["headers"]
        session_id = env["session"]["id"]

        response = api.create_method_attempt(
            session_id,
            {"method_profile_id": env["profiles"]["VOUCHING_ATTESTATION"]["id"]},
            headers,
        )
        validate_error(response, ApiErrorId.ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE)

        _, meta = validate_paginated(
            api.list_method_attempts(headers, params={"session_id": session_id})
        )
        assert meta["total_count"] == 0, (
            f"no attempt may be opened on a vouching profile, got {meta['total_count']}"
        )

        session = read_session(session_id, client_id)
        assert session["assurance_score_provisional"] == 0, (
            "the provisional score must stay 0, got "
            f"{session['assurance_score_provisional']}"
        )

    def test_session_creation_one_below_the_rolling_quota_succeeds(self, api):
        """PRD §3.2: "If usage has already reached `daily_session_quota`, the request is
        rejected with `ERR_CLIENT_DAILY_QUOTA_EXCEEDED`; otherwise the session is created."
        PRD §3.2: "The derived `risk_level` is `HIGH` when the score is 70 or more,
        `MEDIUM` when the score is at least 40 and below 70, and `LOW` otherwise — so a
        `STANDARD` request declaring exactly 25,000 cents scores exactly 40 and lands
        precisely on the `MEDIUM` boundary."

        Design: Corner/validations/session_creation_one_below_the_quota_still_succeeds
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"name": "Acme Quota", "daily_session_quota": 2},
            policy_overrides={"min_assurance_score": 40},
        )
        client_id = env["client"]["id"]
        headers = make_client_integrator_headers(client_id)
        open_session(
            client_id, external_subject_ref="subj-q1", requested_assurance_tier="BASIC"
        )

        response = api.create_verification_session(
            create_verification_session_payload(
                client_id,
                external_subject_ref="subj-q2",
                requested_assurance_tier="BASIC",
            ),
            headers,
        )
        session = validate_success(response, 201)
        assert session["identity_state"] == "IN_PROGRESS", (
            f"a new session opens at IN_PROGRESS, got {session['identity_state']}"
        )
        assert session["policy_id"] == env["policy"]["id"], (
            f"the session pins the published policy, got {session['policy_id']}"
        )
        assert session["risk_level"] == "LOW", (
            f"a BASIC domestic request with no declared value bands LOW, got {session['risk_level']}"
        )

        _, meta = validate_paginated(
            api.list_verification_sessions(headers, params={"client_id": client_id})
        )
        assert meta["total_count"] == 2, (
            f"both sessions inside the window must exist, got {meta['total_count']}"
        )

        client = read_client(client_id)
        assert client["daily_session_quota"] == 2, (
            f"the quota itself is unchanged, got {client['daily_session_quota']}"
        )

    def test_pathway_request_follows_the_pinned_policys_inclusion_switch(self, api):
        """PRD §3.7: "Subjects without standard documentation are served by an
        **AlternativePathway**, requestable by the `ClientIntegrator` while the session's
        identity axis is at `IN_PROGRESS` or `AWAITING_EVIDENCE` and only when the pinned
        policy's `alternative_pathway_enabled` is true; otherwise the request is rejected
        with `ERR_ALTERNATIVE_PATHWAY_DISABLED`."
        PRD §3.1: "On success the policy moves `DRAFT → PUBLISHED` with `published_at` set
        to the clock, and in the same request the client's previously `PUBLISHED` policy,
        if any, moves `PUBLISHED → RETIRED` with `retired_at` set to the clock; the
        client's `version` increments by one."
        PRD §3.2: "The pin survives the pinned policy's later retirement: `policy_id`
        continues to point at the retired policy and its thresholds continue to govern the
        session."

        Design: Corner/validations/pathway_request_depends_on_the_pinned_policys_alternative_pathway_flag
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            method_codes=("DOCUMENT_SCAN",),
            extra_profiles={"VOUCHING_ATTESTATION": {}},
            client_overrides={"name": "Acme Flag"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-flag1",
                "requested_assurance_tier": "BASIC",
            },
        )
        client_id = env["client"]["id"]
        headers = env["headers"]
        first_session = env["session"]
        first_pathway = request_pathway(
            first_session["id"], client_id, "VOUCHING", voucher_reference="vr-1"
        )

        second_policy = draft_policy(
            client_id,
            policy_version=2,
            allowed_method_codes=["DOCUMENT_SCAN"],
            min_assurance_score=40,
            alternative_pathway_enabled=False,
        )
        publish_policy(second_policy["id"], client_version(client_id))
        second_session = open_session(
            client_id,
            external_subject_ref="subj-flag2",
            requested_assurance_tier="BASIC",
            documentation_status="NO_STANDARD_DOCS",
        )

        response = api.create_alternative_pathway(
            second_session["id"], vouching_pathway_payload("vr-2"), headers
        )
        validate_error(response, ApiErrorId.ERR_ALTERNATIVE_PATHWAY_DISABLED)

        _, meta = validate_paginated(
            api.list_alternative_pathways(second_session["id"], headers)
        )
        assert meta["total_count"] == 0, (
            f"no pathway may be opened on the second session, got {meta['total_count']}"
        )

        surviving, _ = validate_paginated(
            api.list_alternative_pathways(first_session["id"], headers)
        )
        assert len(surviving) == 1 and surviving[0]["id"] == first_pathway["id"]
        assert surviving[0]["state"] == "VOUCH_PENDING", (
            f"the pathway on the session pinned to v1 is untouched, got {surviving[0]['state']}"
        )

        assert read_session(second_session["id"], client_id)["policy_id"] == second_policy["id"], (
            "the second session must pin the newly published policy"
        )
        assert read_session(first_session["id"], client_id)["policy_id"] == env["policy"]["id"], (
            "the first session keeps its original pin after retirement"
        )
        assert read_policy(env["policy"]["id"])["state"] == "RETIRED", (
            "publishing v2 retires v1"
        )
        assert read_policy(second_policy["id"])["state"] == "PUBLISHED", (
            "the freshly published policy is PUBLISHED"
        )


class TestGateOrdering:
    """Which guard reports first when a request violates two of them at once."""

    def test_minor_biometric_prohibition_outranks_missing_consent(self, api):
        """PRD §3.5: "If the session's `resolved_age_band` is one of the minor bands
        `U13`, `B13_15` or `B16_17`, biometric processing is prohibited outright and the
        submission is rejected with `ERR_MINOR_BIOMETRIC_PROHIBITED`. If the session
        recorded `biometric_consent` as false, the submission is rejected with
        `ERR_BIOMETRIC_CONSENT_REQUIRED`. The minor-band gate is evaluated before the
        consent gate."

        Design: Corner/validations/minor_biometric_prohibition_outranks_the_missing_consent_error
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_age_gated_session(
            required_min_age_years=18,
            age_buffer_multiplier_bps=15000,
            estimation_mae_months=12,
            method_codes=("BIOMETRIC_COMPARISON",),
            client_overrides={"name": "Acme MinorPri"},
            policy_overrides={"min_assurance_score": 20},
            session_overrides={
                "external_subject_ref": "subj-minorpri",
                "requested_assurance_tier": "BASIC",
                "biometric_consent": False,
            },
        )
        client_id = env["client"]["id"]
        headers = env["headers"]
        session_id = env["session"]["id"]

        record_estimation_result(
            session_id, client_id, env["profiles"]["AGE_ESTIMATION"]["id"], 190
        )
        attempt = open_attempt(
            session_id, client_id, env["profiles"]["BIOMETRIC_COMPARISON"]["id"]
        )

        response = api.create_liveness_check(
            attempt["id"],
            create_liveness_check_payload(
                capture_modality="PASSIVE", pad_score_bps=9000, match_score_bps=9200
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_MINOR_BIOMETRIC_PROHIBITED)

        session = read_session(session_id, client_id)
        assert session["resolved_age_band"] == "B13_15", (
            "190 months less an 18 month buffer bands at B13_15, got "
            f"{session['resolved_age_band']}"
        )
        assert session["age_state"] == "FAILED", (
            f"172 effective months misses the 216 month gate, got {session['age_state']}"
        )
        assert session["biometric_consent"] is False, (
            "the session also lacks biometric consent"
        )

        stored = read_attempt(attempt["id"], client_id)
        assert stored["state"] == "AWAITING_EVIDENCE", (
            f"the attempt must stay AWAITING_EVIDENCE, got {stored['state']}"
        )
        assert stored["evidence_quality_bps"] is None, (
            f"no quality is scored, got {stored['evidence_quality_bps']}"
        )

        _, meta = validate_paginated(
            api.list_biometric_templates(session_id, ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0, (
            f"a minor's session holds no template, got {meta['total_count']}"
        )
        assert read_client(client_id)["stored_template_count"] == 0, (
            "the custody counter must stay at zero"
        )
