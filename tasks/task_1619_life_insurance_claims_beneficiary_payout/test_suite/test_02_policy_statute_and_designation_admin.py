"""Policy issuance and lapsing, statute configuration, and the beneficiary
designation rulebook: OCC on the policy version, half-open designation
windows, and the per-type share pool capacity."""
from test_helpers import (
    ApiErrorId,
    assert_policy,
    create_designation,
    create_designation_payload,
    create_policy,
    create_policy_payload,
    create_policy_with_statute,
    create_statute,
    create_statute_payload,
    file_claim,
    get_policy,
    is_valid_uuid,
    list_designations,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPolicyCreation:
    def test_policy_create_defaults_and_system_fields(
        self, api, policy_administrator_headers
    ):
        """PRD §3.1: "Issuance captures the carrier-assigned `policy_number`,
        which must be unique across all policies; the insured's full legal
        `insured_name` and date of birth `insured_dob`; the optional
        `insured_ssn_last4` and `insured_zip`, both defaulting to null and both
        consumed later by death-master matching; the two-letter `state_code` of
        issue; the `face_amount_cents`, which must be greater than zero; the
        coverage `issue_date`; and an optional `contestability_months` that
        defaults to 24 when omitted."
        PRD §3.1: "A new policy stands in `ACTIVE` status."
        PRD §2.4: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Corner/entities/c_policy_create_defaults_and_system_fields
        """
        resp = api.create_policy(
            create_policy_payload(policy_number="P-COR-1", state_code="IL"),
            policy_administrator_headers)
        data = validate_success(resp, expected_status=201)
        assert_policy(data)
        assert data["contestability_months"] == 24, "default must be applied"
        assert data["status"] == "ACTIVE"
        assert is_valid_uuid(data["id"])
        assert isinstance(data["version"], int)
        assert data["insured_ssn_last4"] is None and data["insured_zip"] is None
        assert data["created_at"].startswith("2026-08-01"), (
            f"created_at must come from the fixed startup clock, got "
            f"{data['created_at']!r}")

    def test_policy_create_missing_face_amount_rejected(
        self, api, policy_administrator_headers
    ):
        """PRD §2.10: "Request body shape — required fields present, enum values
        inside their domains, integers positive where required (`face_amount_cents`
        and `amount_cents` must be greater than zero; `share_percent` must be
        greater than zero, at most 100, and carry at most two decimal places) —
        rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/c_policy_create_missing_required_returns_invalid_request
        """
        payload = create_policy_payload(policy_number="P-COR-2")
        del payload["face_amount_cents"]
        resp = api.create_policy(payload, policy_administrator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _data, meta = validate_paginated(api.list_policies(policy_administrator_headers))
        assert meta["total_count"] == 0, "No policy may be persisted"


class TestStatuteConfiguration:
    def test_statute_duplicate_state_code_rejected(
        self, api, compliance_officer_headers
    ):
        """PRD §3.1: "Only one statute may exist per state; a second
        configuration for an already-configured `state_code` is rejected with
        `ERR_STATUTE_ALREADY_EXISTS`."
        PRD §3.1: "The statute list view accepts a `state_code` filter."

        Design: Corner/entities/c_statute_duplicate_state_code_rejected
        """
        create_statute("IL")
        resp = api.create_state_statute(
            create_statute_payload(state_code="IL", annual_interest_rate_bp=500,
                                   interest_basis="PROOF_OF_LOSS_COMPLETE",
                                   grace_days=10, payment_deadline_days=60,
                                   dormancy_years=5, raa_minimum_cents=50000,
                                   raa_annual_interest_rate_bp=200),
            compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_STATUTE_ALREADY_EXISTS)

        data, meta = validate_paginated(
            api.list_state_statutes(compliance_officer_headers,
                                    params={"state_code": "IL"}))
        assert meta["total_count"] == 1
        assert data[0]["annual_interest_rate_bp"] == 1000, (
            "The original statute row must be retained")


class TestDesignationShapeValidation:
    def test_designation_invalid_beneficiary_type_rejected(
        self, api, policy_administrator_headers
    ):
        """PRD §2.10: "Request body shape — required fields present, enum values
        inside their domains, integers positive where required (`face_amount_cents`
        and `amount_cents` must be greater than zero; `share_percent` must be
        greater than zero, at most 100, and carry at most two decimal places) —
        rejected as `ERR_INVALID_REQUEST`."
        PRD §3.2: "a `beneficiary_type` of `PRIMARY` or `CONTINGENT`".

        Design: Corner/validations/c_invalid_enum_returns_invalid_request
        """
        policy = create_policy(policy_number="P-VAL-2")
        payload = create_designation_payload(
            beneficiary_type="TERTIARY", share_percent=50,
            expected_policy_version=policy["version"])
        resp = api.create_beneficiary_designation(policy["id"], payload,
                                                  policy_administrator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert list_designations(policy["id"]) == []


class TestPolicyStateGatesDesignations:
    def test_lapsed_policy_blocks_new_designation(
        self, api, policy_administrator_headers
    ):
        """PRD §3.1: "Lapsing requires the policy to be `ACTIVE` — any other
        state is rejected with `ERR_POLICY_NOT_ACTIVE` — and stamps `lapse_date`
        with the logical clock date as the policy moves from `ACTIVE` to the
        terminal `LAPSED` state, incrementing the policy's `version` by one."
        PRD §3.2: "Adding a designation requires the policy to be `ACTIVE` (a
        lapsed policy rejects the operation with `ERR_POLICY_NOT_ACTIVE`)".

        Design: Corner/validations/c_lapsed_policy_blocks_new_designation
        """
        policy = create_policy_with_statute("IL", policy_number="P-VAL-9")
        set_clock("2026-01-15T00:00:00Z")
        lapsed = validate_success(api.lapse_policy(policy["id"],
                                                   policy_administrator_headers))
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_date"] == "2026-01-15"

        fresh = get_policy(policy["id"])
        payload = create_designation_payload(
            beneficiary_name="Bob Doe", share_percent=100,
            effective_date="2026-01-01",
            expected_policy_version=fresh["version"])
        resp = api.create_beneficiary_designation(policy["id"], payload,
                                                  policy_administrator_headers)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)

    def test_designation_frozen_after_claim_filed(
        self, api, policy_administrator_headers
    ):
        """PRD §3.2: "Both creation and revocation are frozen the moment a claim
        exists on the policy: from that point on, either operation is rejected
        with `ERR_DESIGNATION_FROZEN_AFTER_CLAIM`, because the beneficiary
        structure as of the insured's death must remain reconstructible."

        Design: Corner/validations/c_designation_frozen_after_claim_filed
        """
        policy = create_policy_with_statute("IL", policy_number="P-VAL-8")
        designation = create_designation(policy["id"], beneficiary_name="Alice Doe",
                                         share_percent=100)
        set_clock("2026-03-05T00:00:00Z")
        file_claim(policy["id"], "2026-03-01")

        fresh = get_policy(policy["id"])
        create_resp = api.create_beneficiary_designation(
            policy["id"],
            create_designation_payload(
                beneficiary_name="Bob Doe", beneficiary_type="CONTINGENT",
                share_percent=100, expected_policy_version=fresh["version"]),
            policy_administrator_headers)
        validate_error(create_resp, ApiErrorId.ERR_DESIGNATION_FROZEN_AFTER_CLAIM)

        revoke_resp = api.revoke_beneficiary_designation(designation["id"],
                                                         policy_administrator_headers)
        validate_error(revoke_resp, ApiErrorId.ERR_DESIGNATION_FROZEN_AFTER_CLAIM)
        remaining = list_designations(policy["id"])
        assert remaining[0]["id"] == designation["id"]
        assert remaining[0]["status"] == "ACTIVE"


class TestDesignationOptimisticConcurrency:
    def test_occ_stale_policy_version_rejected(self, api,
                                               policy_administrator_headers):
        """PRD §2.8: "adding a beneficiary designation to a policy requires
        `expected_policy_version`, holding the policy `version` the client last
        observed. Because every designation creation or revocation restructures
        the policy's beneficiary pool and increments the policy's `version`, a
        stale writer would allocate shares against a pool composition it never
        saw; a mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/c_occ_stale_policy_version_rejected
        """
        policy = create_policy(policy_number="P-OCC-2")
        stale_version = policy["version"]
        first = validate_success(
            api.create_beneficiary_designation(
                policy["id"],
                create_designation_payload(beneficiary_name="Alice Doe",
                                           share_percent=60,
                                           expected_policy_version=stale_version),
                policy_administrator_headers),
            expected_status=201)
        assert first["status"] == "ACTIVE"

        # The first creation bumped the policy version; replaying the stale one fails.
        resp = api.create_beneficiary_designation(
            policy["id"],
            create_designation_payload(beneficiary_name="Bob Doe", share_percent=40,
                                       expected_policy_version=stale_version),
            policy_administrator_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION)

        # Replaying with the freshly observed version succeeds.
        fresh_version = get_policy(policy["id"])["version"]
        assert fresh_version != stale_version
        second = validate_success(
            api.create_beneficiary_designation(
                policy["id"],
                create_designation_payload(beneficiary_name="Bob Doe",
                                           share_percent=40,
                                           expected_policy_version=fresh_version),
                policy_administrator_headers),
            expected_status=201)
        assert second["status"] == "ACTIVE"


class TestDesignationWindowSemantics:
    def test_designation_window_overlap_rejected(self, api,
                                                 policy_administrator_headers):
        """PRD §3.2: "a designation's active window is the half-open interval
        beginning on its `effective_date` (inclusive) and ending on the date of
        its `revoked_at` (exclusive), and designations sharing the same policy,
        the same `beneficiary_type`, and the same `beneficiary_name` may not
        have overlapping active windows — windows that merely touch, where one
        designation's revocation date equals another's effective date, are
        permitted, but genuine overlap is rejected with
        `ERR_DESIGNATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/designation_window_overlap_vs_half_open_adjacency
        """
        policy = create_policy_with_statute("IL", policy_number="P-OV-1")
        set_clock("2026-01-15T00:00:00Z")
        create_designation(policy["id"], beneficiary_name="Alice Doe",
                           share_percent=40, effective_date="2026-01-01")

        # Same (policy, type, name); D1's window is still open -> genuine overlap.
        resp = api.create_beneficiary_designation(
            policy["id"],
            create_designation_payload(
                beneficiary_name="Alice Doe", share_percent=50,
                effective_date="2026-02-01",
                expected_policy_version=get_policy(policy["id"])["version"]),
            policy_administrator_headers)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_WINDOW_OVERLAP)

    def test_designation_half_open_adjacency_accepted(
        self, api, policy_administrator_headers
    ):
        """PRD §3.2: "a designation's active window is the half-open interval
        beginning on its `effective_date` (inclusive) and ending on the date of
        its `revoked_at` (exclusive), and designations sharing the same policy,
        the same `beneficiary_type`, and the same `beneficiary_name` may not
        have overlapping active windows — windows that merely touch, where one
        designation's revocation date equals another's effective date, are
        permitted, but genuine overlap is rejected with
        `ERR_DESIGNATION_WINDOW_OVERLAP`."

        Adjacent leg: after revoking D1 at the 2026-03-01 logical clock, a new
        designation effective exactly that date touches the old window without
        overlapping it.

        Design: Difficulty/resource_temporal_overlap/designation_window_overlap_vs_half_open_adjacency
        """
        policy = create_policy_with_statute("IL", policy_number="P-OV-1")
        set_clock("2026-01-15T00:00:00Z")
        d1 = create_designation(policy["id"], beneficiary_name="Alice Doe",
                                share_percent=40, effective_date="2026-01-01")

        set_clock("2026-03-01T00:00:00Z")
        revoked = validate_success(
            api.revoke_beneficiary_designation(d1["id"],
                                               policy_administrator_headers))
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_at"].startswith("2026-03-01")

        d3_resp = api.create_beneficiary_designation(
            policy["id"],
            create_designation_payload(
                beneficiary_name="Alice Doe", share_percent=100,
                effective_date="2026-03-01",
                expected_policy_version=get_policy(policy["id"])["version"]),
            policy_administrator_headers)
        d3 = validate_success(d3_resp, expected_status=201)
        assert d3["status"] == "ACTIVE", "Adjacent windows (touching, not overlapping) are permitted"

        listed = list_designations(policy["id"])
        by_id = {d["id"]: d for d in listed}
        assert by_id[d1["id"]]["status"] == "REVOKED"
        assert by_id[d3["id"]]["status"] == "ACTIVE"
        assert len(listed) == 2, "The rejected overlapping designation must not persist"


class TestSharePoolCapacity:
    def test_share_pool_capacity_exceeded_rejected(
        self, api, policy_administrator_headers
    ):
        """PRD §3.2: "the sum of `share_percent` across all `ACTIVE`
        designations of the same type on the policy, including the candidate,
        must not exceed 100, else the creation fails with
        `ERR_SHARE_TOTAL_EXCEEDED`."

        60 + 50 = 110 exceeds the pool; the candidate names a different
        beneficiary, so only the share-capacity rule can fire.

        Design: Difficulty/resource_temporal_overlap/share_pool_aggregate_capacity_exceeded
        """
        policy = create_policy_with_statute("IL", policy_number="P-OV-2")
        set_clock("2026-01-15T00:00:00Z")
        create_designation(policy["id"], beneficiary_name="Alice Doe",
                           share_percent=60, effective_date="2026-01-01")

        resp = api.create_beneficiary_designation(
            policy["id"],
            create_designation_payload(
                beneficiary_name="Bob Doe", share_percent=50,
                effective_date="2026-02-01",
                expected_policy_version=get_policy(policy["id"])["version"]),
            policy_administrator_headers)
        validate_error(resp, ApiErrorId.ERR_SHARE_TOTAL_EXCEEDED)

    def test_share_pool_capacity_exact_hundred_accepted(
        self, api, policy_administrator_headers
    ):
        """PRD §3.2: "the sum of `share_percent` across all `ACTIVE`
        designations of the same type on the policy, including the candidate,
        must not exceed 100, else the creation fails with
        `ERR_SHARE_TOTAL_EXCEEDED`."

        Boundary leg: 60 + 40 lands exactly on the capacity, and "must not
        exceed 100" admits it.

        Design: Difficulty/resource_temporal_overlap/share_pool_aggregate_capacity_exceeded
        """
        policy = create_policy_with_statute("IL", policy_number="P-OV-2")
        set_clock("2026-01-15T00:00:00Z")
        create_designation(policy["id"], beneficiary_name="Alice Doe",
                           share_percent=60, effective_date="2026-01-01")

        resp = api.create_beneficiary_designation(
            policy["id"],
            create_designation_payload(
                beneficiary_name="Bob Doe", share_percent=40,
                effective_date="2026-02-01",
                expected_policy_version=get_policy(policy["id"])["version"]),
            policy_administrator_headers)
        d2 = validate_success(resp, expected_status=201)
        assert d2["status"] == "ACTIVE"

        listed = list_designations(policy["id"])
        assert len(listed) == 2, "Two concurrent PRIMARY designations (60/40) must coexist"
        assert sorted(float(d["share_percent"]) for d in listed) == [40.0, 60.0]
