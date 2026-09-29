"""Creation, read and listing contracts for the identity-verification resources.

Covers the field-level guarantees the contract makes when a client, vendor
method profile, verification policy, verification session, method attempt,
document capture, bias audit or cohort row is minted or read back.
"""
from datetime import datetime

from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    assert_bias_audit,
    assert_client,
    assert_credit_pool_invariant,
    assert_document_capture,
    assert_method_attempt,
    assert_method_profile,
    assert_verification_policy,
    assert_verification_session,
    create_client_payload,
    create_cohort_metric_payload,
    create_verification_policy_payload,
    create_verification_session_payload,
    draft_policy,
    is_valid_uuid,
    make_client_integrator_headers,
    open_attempt,
    open_bias_audit,
    read_client,
    read_method_profile,
    register_client,
    register_method_profile,
    set_clock,
    setup_client_with_published_policy,
    setup_scored_document_attempt,
    setup_session,
    validate_error,
    validate_paginated,
    validate_success,
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


class TestClientRegistry:
    def test_client_registration_starts_in_sandbox_with_a_full_credit_pool(
        self, api, platform_admin_headers
    ):
        """PRD §3.1: "Registration always lands the client in the `SANDBOX` integration
        posture: `integration_state` is one of `SANDBOX`, `LIVE` or `SUSPENDED`, and only
        the admin patch moves it to `LIVE` or `SUSPENDED`."
        PRD §3.1: "At registration `reserved_review_credits`, `stored_template_count`,
        `pending_stepup_count` and `consumed_review_count` all start at 0, and
        `available_review_credits` starts equal to `granted_review_credits`."
        PRD §2.4: "Every resource the API mints carries an `id` that is a server-generated
        UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with
        three fractional digits."
        PRD §2.4: "The clock starts at the mandatory default instant `2026-08-01T00:00:00Z`."

        Design: Corner/entities/client_creation_returns_sandbox_posture_with_a_full_review_credit_pool
        """
        set_clock(DEFAULT_CLOCK)

        response = api.create_client(
            create_client_payload(
                name="Northwind Bank",
                home_jurisdiction_code="US",
                biometric_retention_mode="RETAIN_90_DAYS",
                daily_session_quota=25,
                granted_review_credits=3,
            ),
            platform_admin_headers,
        )
        data = validate_success(response, 201)
        assert response.json()["response_type"] == "object"

        assert_client(data)
        assert data["integration_state"] == "SANDBOX", (
            f"a fresh client must land in SANDBOX, got {data['integration_state']}"
        )
        assert data["granted_review_credits"] == 3
        assert data["reserved_review_credits"] == 0
        assert data["available_review_credits"] == 3
        assert_credit_pool_invariant(data)
        assert data["consumed_review_count"] == 0
        assert data["stored_template_count"] == 0
        assert data["pending_stepup_count"] == 0
        assert data["version"] == 1
        assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
            f"created_at must be the logical clock instant, got {data['created_at']}"
        )
        assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"

    def test_client_read_echoes_the_registered_configuration(
        self, api, platform_admin_headers
    ):
        """PRD §3.1: "A relying party enters the system as a **Client**, registered by a
        `PlatformAdmin` with a `name` between 1 and 120 characters, a
        `home_jurisdiction_code` that is exactly two uppercase letters in ISO 3166-1
        alpha-2 form, a `biometric_retention_mode` that is one of `DELETE_ON_COMPLETE`,
        `RETAIN_90_DAYS` or `RETAIN_WITH_CONSENT`, a `daily_session_quota` of at least 1,
        and a `granted_review_credits` grant of 0 or more."
        PRD §3.1: "Registration always lands the client in the `SANDBOX` integration
        posture: `integration_state` is one of `SANDBOX`, `LIVE` or `SUSPENDED`, and only
        the admin patch moves it to `LIVE` or `SUSPENDED`."
        PRD §2.2: "The `data` field contains the resource object or an array of resource
        objects."

        Design: Corner/entities/client_retrieval_returns_the_stored_configuration_unchanged
        """
        set_clock(DEFAULT_CLOCK)
        created = register_client(
            name="Northwind Bank",
            home_jurisdiction_code="US",
            biometric_retention_mode="RETAIN_90_DAYS",
            daily_session_quota=25,
            granted_review_credits=3,
        )

        data = validate_success(api.get_client(created["id"], platform_admin_headers))

        assert data["id"] == created["id"]
        assert data["name"] == "Northwind Bank"
        assert data["home_jurisdiction_code"] == "US"
        assert data["biometric_retention_mode"] == "RETAIN_90_DAYS"
        assert data["daily_session_quota"] == 25
        assert data["granted_review_credits"] == 3
        assert data["integration_state"] == "SANDBOX"
        assert data["version"] == 1, "an unpatched client is still at version 1"

    def test_client_patch_with_an_unminted_id_reports_client_not_found(
        self, api, platform_admin_headers
    ):
        """PRD §2.6: "`ERR_CLIENT_NOT_FOUND` (404) — the client named by the path exists.
        `PATCH /idv/clients/{id}`, `GET /idv/clients/{id}`."

        Design: Corner/entities/client_patch_with_unknown_id_returns_not_found
        """
        existing = register_client(
            name="Other Co",
            biometric_retention_mode="DELETE_ON_COMPLETE",
            daily_session_quota=50,
            granted_review_credits=1,
        )

        response = api.patch_client(
            "11111111-1111-4111-8111-111111111111",
            {"daily_session_quota": 9},
            platform_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND)

        untouched = read_client(existing["id"])
        assert untouched["daily_session_quota"] == 50
        assert untouched["version"] == 1, "a rejected patch performs no write"


class TestVendorMethodProfiles:
    def test_method_profile_creation_seeds_cleared_bias_posture_and_estimation_defaults(
        self, api, platform_admin_headers
    ):
        """PRD §3.1: "Every new profile starts with `bias_state` at `CLEARED` and
        `restricted_at` null, and neither field is ever writable by a direct profile
        write — only the bias-testing transitions of §3.9 move them."
        PRD §3.1: "Age-estimation vendors additionally declare `estimation_mae_months`,
        the documented mean absolute error of the estimator in whole months, which
        defaults to 0 and is 0 for every non-estimation method, and `band_accuracy_bps`,
        a map whose keys are a subset of `U13`, `B13_15`, `B16_17`, `B18_20` and
        `A21_PLUS` and whose values are basis points between 0 and 10000; the map
        defaults to empty."
        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation, and `version`, an integer that starts at 1
        on creation and increments by one on every mutation of that resource."

        Design: Corner/entities/method_profile_creation_mints_system_fields_and_defaults_bias_state_to_cleared
        """
        set_clock(DEFAULT_CLOCK)

        response = api.create_method_profile(
            {
                "method_code": "DOCUMENT_SCAN",
                "vendor_code": "docv1",
                "assurance_weight": 45,
                "acceptance_floor_bps": 8000,
                "far_bps": 30,
                "frr_bps": 400,
                "strong_evidence": True,
                "cost_cents": 120,
            },
            platform_admin_headers,
        )
        data = validate_success(response, 201)

        assert_method_profile(data)
        assert data["bias_state"] == "CLEARED"
        assert data["restricted_at"] is None
        assert data["estimation_mae_months"] == 0
        assert data["band_accuracy_bps"] == {}
        assert data["version"] == 1
        assert _instant(data["created_at"]) == _instant(data["updated_at"]), (
            "an unmutated profile carries the same created_at and updated_at instant"
        )


class TestPolicyDrafting:
    def test_policy_draft_applies_every_declared_default(self, api):
        """PRD §3.1: "Four tuning knobs carry defaults: `doc_authenticity_floor_bps`, the
        score at or above which a document is judged authentic, defaults to 8000 and must
        lie between 5001 and 10000; `pad_threshold_bps`, the baseline
        presentation-attack-detection threshold before any adjustment, defaults to 7500
        and must lie between 1000 and 9500; `age_buffer_multiplier_bps`, the multiplier
        applied to an estimator's documented error to derive the safety buffer, defaults
        to 15000 and must lie between 10000 and 30000; and `step_up_max_rounds`, the
        number of step-up rounds a session may consume, defaults to 2 and must lie
        between 0 and 5."
        PRD §3.1: "The `required_min_age_years` gate defaults to 0 and must lie between 0
        and 25, where 0 disables the age axis entirely."
        PRD §3.1: "Finally `alternative_pathway_enabled` defaults to true and decides
        whether subjects without standard documentation may request an inclusion pathway."
        PRD §3.1: "A fresh draft sits in `DRAFT` with `published_at` and `retired_at` null
        and `degraded_flag` false."

        Design: Corner/entities/policy_creation_applies_every_declared_default_for_omitted_optionals
        """
        client = register_client(name="Acme Def")

        response = api.create_verification_policy(
            {
                "client_id": client["id"],
                "policy_version": 1,
                "allowed_method_codes": ["DOCUMENT_SCAN"],
                "min_assurance_score": 55,
            },
            make_client_integrator_headers(client["id"]),
        )
        data = validate_success(response, 201)

        assert_verification_policy(data)
        assert data["state"] == "DRAFT"
        assert data["doc_authenticity_floor_bps"] == 8000
        assert data["pad_threshold_bps"] == 7500
        assert data["required_min_age_years"] == 0
        assert data["age_buffer_multiplier_bps"] == 15000
        assert data["step_up_max_rounds"] == 2
        assert data["alternative_pathway_enabled"] is True
        assert data["degraded_flag"] is False
        assert data["published_at"] is None
        assert data["retired_at"] is None
        assert data["version"] == 1

    def test_policy_draft_naming_a_foreign_client_is_refused_for_scope(self, api):
        """PRD §2.1: "A `ClientIntegrator` that addresses a policy, session, attempt,
        evidence row, pathway or client record belonging to any other client is rejected
        with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.6: "`ERR_CLIENT_SCOPE_VIOLATION` (403) — for a `ClientIntegrator` caller,
        the target resource resolves to the client whose `id` equals `X-User-ID`. Every
        endpoint whose authorised roles include `ClientIntegrator`."

        Design: Corner/entities/policy_creation_referencing_another_clients_id_is_rejected_for_scope
        """
        caller = register_client(name="Acme Scope A")
        other = register_client(name="Acme Scope B")

        response = api.create_verification_policy(
            create_verification_policy_payload(
                other["id"],
                policy_version=1,
                allowed_method_codes=["DOCUMENT_SCAN"],
                min_assurance_score=40,
            ),
            make_client_integrator_headers(caller["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CLIENT_SCOPE_VIOLATION)

        rows, meta = validate_paginated(
            api.list_verification_policies(
                make_client_integrator_headers(other["id"]),
                params={"client_id": other["id"]},
            )
        )
        assert meta["total_count"] == 0, "the rejected draft must not have been stored"
        assert rows == []

    def test_policy_listing_pages_report_total_count_and_has_more(self, api, compliance_officer_headers):
        """PRD §2.3: "`limit` caps the number of records returned; it defaults to 10, its
        minimum accepted value is 1, and its maximum accepted value is 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the number of
        records matching the filter before pagination is applied and `has_more` indicates
        whether records remain beyond the returned page."
        PRD §2.9: "Verification policies may be filtered by `client_id` and `state`."
        PRD §3.1: "A fresh draft sits in `DRAFT` with `published_at` and `retired_at` null
        and `degraded_flag` false."

        Design: Corner/entities/policy_listing_paginates_with_total_count_and_has_more
        """
        client = register_client(name="Paginate Co", daily_session_quota=50)
        client_id = client["id"]
        first = draft_policy(
            client_id, policy_version=1, allowed_method_codes=["DOCUMENT_SCAN"], min_assurance_score=40
        )
        second = draft_policy(
            client_id, policy_version=2, allowed_method_codes=["DOCUMENT_SCAN"], min_assurance_score=40
        )
        third = draft_policy(
            client_id,
            policy_version=3,
            allowed_method_codes=["DOCUMENT_SCAN", "DATABASE_CHECK"],
            min_assurance_score=40,
        )

        page_one_response = api.list_verification_policies(
            compliance_officer_headers, params={"client_id": client_id, "limit": 2, "offset": 0}
        )
        page_one, meta_one = validate_paginated(page_one_response)
        assert page_one_response.json()["response_type"] == "array"
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert len(page_one) == 2

        page_two, meta_two = validate_paginated(
            api.list_verification_policies(
                compliance_officer_headers,
                params={"client_id": client_id, "limit": 2, "offset": 2},
            )
        )
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert len(page_two) == 1

        for row in page_one + page_two:
            assert row["state"] == "DRAFT"
            assert row["client_id"] == client_id

        seen = [row["id"] for row in page_one + page_two]
        assert sorted(seen) == sorted([first["id"], second["id"], third["id"]])
        assert len(set(seen)) == 3, "each policy appears exactly once across the two pages"


class TestSessionOpening:
    def test_session_creation_without_subject_jurisdiction_code_is_rejected(self, api, platform_admin_headers):
        """PRD §3.2: "A `ClientIntegrator` opens a **VerificationSession** by naming the
        `client_id` it acts for, a `external_subject_ref` of 1 to 64 characters that is
        the client's own pseudonymous handle for the subject, a `requested_assurance_tier`
        of `BASIC`, `STANDARD` or `ENHANCED`, and a `subject_jurisdiction_code` of exactly
        two uppercase letters."
        PRD §3.2: "Three inputs are optional: `declared_transaction_value_cents`, the
        value of the transaction being protected, defaults to 0 and must not be negative;
        `biometric_consent` defaults to false; and `documentation_status` defaults to
        `STANDARD_DOCS` and may instead be `NO_STANDARD_DOCS`."
        PRD §2.6: "`ERR_INVALID_REQUEST` (422) — the body parses, carries no unknown key,
        contains every required field, and satisfies every declared enum, range, length
        and conditional-presence constraint. Every endpoint that accepts a body."

        Design: Corner/entities/session_creation_missing_subject_jurisdiction_code_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_client_with_published_policy(
            client_overrides={"name": "Acme Req"},
            policy_overrides={"min_assurance_score": 40},
        )
        client_id = env["client"]["id"]

        response = api.create_verification_session(
            {
                "client_id": client_id,
                "external_subject_ref": "subj-req",
                "requested_assurance_tier": "BASIC",
            },
            make_client_integrator_headers(client_id),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_verification_sessions(platform_admin_headers, params={"client_id": client_id})
        )
        assert meta["total_count"] == 0, "the rejected session must not have been stored"

    def test_session_creation_with_a_lowercase_jurisdiction_code_is_rejected(self, api, platform_admin_headers):
        """PRD §3.2: "A `ClientIntegrator` opens a **VerificationSession** by naming the
        `client_id` it acts for, a `external_subject_ref` of 1 to 64 characters that is
        the client's own pseudonymous handle for the subject, a `requested_assurance_tier`
        of `BASIC`, `STANDARD` or `ENHANCED`, and a `subject_jurisdiction_code` of exactly
        two uppercase letters."
        PRD §2.6: "`ERR_INVALID_REQUEST` (422) — the body parses, carries no unknown key,
        contains every required field, and satisfies every declared enum, range, length
        and conditional-presence constraint. Every endpoint that accepts a body."

        Design: Corner/entities/session_creation_with_a_lowercase_jurisdiction_code_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_client_with_published_policy(
            client_overrides={"name": "Acme Type"},
            policy_overrides={"min_assurance_score": 40},
        )
        client_id = env["client"]["id"]

        response = api.create_verification_session(
            create_verification_session_payload(
                client_id,
                external_subject_ref="subj-type",
                requested_assurance_tier="BASIC",
                subject_jurisdiction_code="usa",
            ),
            make_client_integrator_headers(client_id),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_verification_sessions(platform_admin_headers, params={"client_id": client_id})
        )
        assert meta["total_count"] == 0, "the rejected session must not have been stored"

    def test_session_creation_freezes_risk_pins_the_policy_and_sets_expiry(self, api):
        """PRD §3.2: "The score begins from the requested tier: 10 points for `BASIC`, 30
        for `STANDARD`, 60 for `ENHANCED`."
        PRD §3.2: "A transaction-value bump is added next: nothing for a declared value of
        at most 24,999 cents, 10 points for a declared value above 24,999 cents and at
        most 999,999 cents, and 20 points for a declared value above 999,999 cents."
        PRD §3.2: "A further 20 points are added when the `subject_jurisdiction_code` the
        subject presents differs from the client's `home_jurisdiction_code`."
        PRD §3.2: "A further 10 points are added when `documentation_status` is
        `NO_STANDARD_DOCS`."
        PRD §3.2: "`expires_at` is set to the session's `created_at` plus sixty minutes on
        the logical clock."
        PRD §3.2: "The remaining derived fields start at their baselines:
        `assurance_score_provisional` at 0, `assurance_score_final` null,
        `assurance_ceiling` at 100, `resolved_age_band` null, `fraud_signal_count` at 0,
        `step_up_round` at 0, `manual_override_flag` false, `disposition_reason` null and
        `completed_at` null."

        Design: Corner/entities/session_creation_computes_frozen_risk_fields_and_expiry
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_client_with_published_policy(
            client_overrides={"name": "Acme Risk", "home_jurisdiction_code": "US"},
            policy_overrides={"min_assurance_score": 40},
        )
        client_id = env["client"]["id"]

        response = api.create_verification_session(
            create_verification_session_payload(
                client_id,
                external_subject_ref="subj-risk",
                requested_assurance_tier="ENHANCED",
                subject_jurisdiction_code="GB",
                declared_transaction_value_cents=500000,
                documentation_status="NO_STANDARD_DOCS",
            ),
            make_client_integrator_headers(client_id),
        )
        data = validate_success(response, 201)

        assert_verification_session(data)
        assert data["risk_score"] == 100, (
            f"60 for ENHANCED plus 10 mid-value plus 20 jurisdiction plus 10 no-docs is 100, "
            f"got {data['risk_score']}"
        )
        assert data["risk_level"] == "HIGH"
        assert data["policy_id"] == env["policy"]["id"], "the server pins the published policy"
        assert _instant(data["expires_at"]) == _instant("2026-08-01T01:00:00Z")
        assert data["identity_state"] == "IN_PROGRESS"
        assert data["age_state"] == "NOT_REQUIRED", (
            "the pinned policy leaves required_min_age_years at 0, which disables the age axis"
        )
        assert data["assurance_score_provisional"] == 0
        assert data["assurance_score_final"] is None
        assert data["assurance_ceiling"] == 100
        assert data["step_up_round"] == 0
        assert data["fraud_signal_count"] == 0
        assert data["manual_override_flag"] is False


class TestAttemptAndEvidenceReads:
    def test_attempt_creation_with_an_unknown_method_profile_reports_not_found(self, api, platform_admin_headers):
        """PRD §2.6: "`ERR_METHOD_PROFILE_NOT_FOUND` (404) — a method profile referenced
        by a body field exists. `POST /idv/bias-audits`,
        `POST /idv/verification-sessions/{id}/method-attempts`,
        `POST /idv/verification-sessions/{id}/age-assurance-results`."
        PRD §3.2: "The identity axis, `identity_state`, starts at `IN_PROGRESS` and moves
        among `IN_PROGRESS`, `AWAITING_EVIDENCE`, `MANUAL_REVIEW`, `VERIFIED`, `REJECTED`
        and `EXPIRED`, of which the last three are terminal."

        Design: Corner/entities/attempt_creation_with_an_unknown_method_profile_id_returns_not_found
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_session(
            client_overrides={"name": "Acme FK"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-fk", "requested_assurance_tier": "BASIC"},
        )
        session_id = env["session"]["id"]

        response = api.create_method_attempt(
            session_id,
            {"method_profile_id": "22222222-2222-4222-8222-222222222222"},
            env["headers"],
        )
        validate_error(response, ApiErrorId.ERR_METHOD_PROFILE_NOT_FOUND)

        _, meta = validate_paginated(
            api.list_method_attempts(platform_admin_headers, params={"session_id": session_id})
        )
        assert meta["total_count"] == 0, "the rejected attempt must not have been stored"

        session = validate_success(api.get_verification_session(session_id, platform_admin_headers))
        assert session["identity_state"] == "IN_PROGRESS"

    def test_document_capture_is_a_write_once_observation(self, api):
        """PRD §2.4: "Five record kinds are write-once observations rather than mutable
        resources, and they carry only `id` and `created_at` — both `updated_at` and
        `version` are absent from their representations entirely: document captures,
        liveness checks, age assurance results, cohort metrics, and audit events."
        PRD §3.4: "A document where every required feature validated scores exactly 10000."
        PRD §3.4: "Fifth, the machine-readable-zone cap is applied *after* the tamper
        penalty, never before it: when `mrz_checksum_valid` is false,
        `authenticity_score_bps` is the lesser of the raw score and 4000 basis points;
        when the checksum validated, `authenticity_score_bps` is the raw score unchanged."

        Design: Corner/entities/document_capture_is_immutable_with_no_version_field_and_no_update_endpoint
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_scored_document_attempt(
            capture_overrides=dict(CLEAN_PASSPORT),
            client_overrides={"name": "Acme Immut"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-immut", "requested_assurance_tier": "BASIC"},
        )
        attempt_id = env["attempt"]["id"]

        rows, meta = validate_paginated(api.list_document_captures(attempt_id, env["headers"]))

        assert meta["total_count"] == 1
        capture = rows[0]
        assert_document_capture(capture)
        assert "version" not in capture, "a write-once capture exposes no version"
        assert "updated_at" not in capture, "a write-once capture exposes no updated_at"
        assert capture["attempt_id"] == attempt_id
        assert capture["authenticity_score_bps"] == 10000

    def test_scored_attempt_read_exposes_evidence_quality_and_contribution(self, api):
        """PRD §3.3: "The named profile is used, `selection_mode` is recorded as
        `CLIENT_REQUESTED`, and three gates apply in the order fixed by §2.6"
        PRD §3.3: "Its `retry_index` is the number of attempts that already exist on the
        same session with the same `method_code`, so the first document scan of a session
        has index 0 and a second has index 1; this figure matters later for liveness
        tuning."
        PRD §3.4: "The capture's `authenticity_score_bps` becomes the attempt's
        `evidence_quality_bps` verbatim, and the attempt's `contribution_points` is the
        resolved profile's `assurance_weight` multiplied by that quality, divided by ten
        thousand, truncated toward zero."
        PRD §3.5: "The comparison score is accepted only here and is stored on the owning
        attempt; no other endpoint accepts it, and it stays null for every non-biometric
        method."

        Design: Corner/entities/scored_attempt_retrieval_exposes_evidence_and_contribution_fields
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_scored_document_attempt(
            capture_overrides=dict(CLEAN_PASSPORT),
            client_overrides={"name": "Acme Read"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-read", "requested_assurance_tier": "BASIC"},
        )

        data = validate_success(api.get_method_attempt(env["attempt"]["id"], env["headers"]))

        assert_method_attempt(data)
        assert data["state"] == "SCORED"
        assert data["method_code"] == "DOCUMENT_SCAN"
        assert data["selection_mode"] == "CLIENT_REQUESTED"
        assert data["retry_index"] == 0
        assert data["evidence_quality_bps"] == 10000
        assert data["contribution_points"] == 45, (
            f"assurance weight 45 times quality 10000 divided by 10000 is 45, "
            f"got {data['contribution_points']}"
        )
        assert data["tamper_flag"] is False
        assert data["rejection_reason"] is None
        assert data["match_score_bps"] is None
        assert data["finalized_at"] is None

    def test_attempt_listing_filters_by_state_within_one_session(self, api, platform_admin_headers):
        """PRD §2.9: "Method attempts may be filtered by `session_id`,
        `method_profile_id` and `state`."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the number of
        records matching the filter before pagination is applied and `has_more` indicates
        whether records remain beyond the returned page."
        PRD §3.3: "Its scoring fields start empty: `evidence_quality_bps` null,
        `match_score_bps` null, `contribution_points` null, `tamper_flag` false,
        `rejection_reason` null and `finalized_at` null."
        PRD §3.8: "it sums the `contribution_points` of every attempt of the session
        currently in `SCORED` or `ACCEPTED`, and caps the sum at 100."

        Design: Corner/entities/attempt_listing_filters_by_state_within_one_session
        """
        set_clock(DEFAULT_CLOCK)
        env = setup_scored_document_attempt(
            capture_overrides=dict(CLEAN_PASSPORT),
            client_overrides={"name": "Acme List"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-list", "requested_assurance_tier": "BASIC"},
        )
        session_id = env["session"]["id"]
        scored_attempt = env["attempt"]
        second_attempt = open_attempt(
            session_id, env["client"]["id"], env["profiles"]["DOCUMENT_SCAN"]["id"]
        )

        filtered, filtered_meta = validate_paginated(
            api.list_method_attempts(
                env["headers"], params={"session_id": session_id, "state": "SCORED"}
            )
        )
        assert filtered_meta["total_count"] == 1
        assert filtered_meta["has_more"] is False
        assert filtered[0]["id"] == scored_attempt["id"]

        everything, all_meta = validate_paginated(
            api.list_method_attempts(env["headers"], params={"session_id": session_id})
        )
        assert all_meta["total_count"] == 2
        assert {row["id"] for row in everything} == {scored_attempt["id"], second_attempt["id"]}

        fresh = validate_success(api.get_method_attempt(second_attempt["id"], env["headers"]))
        assert fresh["state"] == "AWAITING_EVIDENCE"
        assert fresh["evidence_quality_bps"] is None
        assert fresh["contribution_points"] is None

        session = validate_success(api.get_verification_session(session_id, platform_admin_headers))
        assert session["assurance_score_provisional"] == 45


class TestBiasProgrammeRecords:
    def test_bias_audit_opens_collecting_with_every_disparity_field_null(self, api, compliance_officer_headers):
        """PRD §3.9: "A new audit opens in `COLLECTING`, one of `COLLECTING`, `EVALUATED`,
        `REMEDIATION_REQUIRED` and `REMEDIATED`, of which only `REMEDIATED` is terminal,
        with `remediation_round` at 0, `remediated_at` null, `evaluated_by_user_id` and
        `remediated_by_user_id` null, `included_cohort_count` and `excluded_cohort_count`
        at 0, `insufficient_sample` false, and `max_frr_bps`, `min_frr_bps`,
        `pooled_frr_bps`, `disparity_ratio_max_to_min_bps`,
        `disparity_ratio_max_to_pooled_bps` and `worst_cohort_code` all null."
        PRD §3.1: "Every new profile starts with `bias_state` at `CLEARED` and
        `restricted_at` null, and neither field is ever writable by a direct profile
        write — only the bias-testing transitions of §3.9 move them."

        Design: Corner/entities/bias_audit_creation_starts_collecting_with_zeroed_cohort_counters
        """
        set_clock(DEFAULT_CLOCK)
        profile = register_method_profile("KNOWLEDGE_BASED")

        response = api.create_bias_audit(
            {
                "method_profile_id": profile["id"],
                "window_start": "2026-06-01T00:00:00Z",
                "window_end": "2026-07-01T00:00:00Z",
            },
            compliance_officer_headers,
        )
        data = validate_success(response, 201)

        assert_bias_audit(data)
        assert data["state"] == "COLLECTING"
        assert data["remediation_round"] == 0
        assert data["included_cohort_count"] == 0
        assert data["excluded_cohort_count"] == 0
        assert data["insufficient_sample"] is False
        for field in (
            "max_frr_bps",
            "min_frr_bps",
            "pooled_frr_bps",
            "disparity_ratio_max_to_min_bps",
            "disparity_ratio_max_to_pooled_bps",
            "worst_cohort_code",
        ):
            assert data[field] is None, f"{field} must be null on a fresh audit"
        assert data["evaluated_by_user_id"] is None
        assert data["remediated_at"] is None

        assert read_method_profile(profile["id"])["bias_state"] == "CLEARED"

    def test_cohort_metric_with_more_false_rejects_than_attempts_is_rejected(
        self, api, compliance_officer_headers
    ):
        """PRD §3.9: "It supplies the `attempt_count` observed for that cohort inside the
        window, which must not be negative, along with `false_reject_count` and
        `false_accept_count`, each between 0 and `attempt_count`."
        PRD §2.6: "`ERR_INVALID_REQUEST` (422) — the body parses, carries no unknown key,
        contains every required field, and satisfies every declared enum, range, length
        and conditional-presence constraint. Every endpoint that accepts a body."

        Design: Corner/entities/cohort_metric_with_false_reject_count_above_attempt_count_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        profile = register_method_profile("KNOWLEDGE_BASED")
        audit = open_bias_audit(
            profile["id"], window_start="2026-06-01T00:00:00Z", window_end="2026-07-01T00:00:00Z"
        )

        response = api.create_cohort_metric(
            audit["id"],
            create_cohort_metric_payload("AGE_18_24", 100, 150, 2),
            compliance_officer_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_cohort_metrics(audit["id"], compliance_officer_headers)
        )
        assert meta["total_count"] == 0, "the rejected cohort row must not have been stored"

        reread = validate_success(api.get_bias_audit(audit["id"], compliance_officer_headers))
        assert reread["included_cohort_count"] == 0
        assert reread["state"] == "COLLECTING"
