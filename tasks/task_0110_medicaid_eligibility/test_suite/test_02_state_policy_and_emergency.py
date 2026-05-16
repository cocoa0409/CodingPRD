"""StatePolicy CRUD and EmergencyDeclaration creation tests.

Exercises PRD §3.1 (state policy fields and emergency declarations) and
PRD §3.5 (emergency overlay basics).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_emergency_declaration,
    assert_state_policy,
    create_emergency_declaration_payload,
    create_state_policy,
    create_state_policy_payload,
    iso_now,
    iso_offset,
    issue_emergency_declaration,
    random_state_code,
    server_now_dt,
    server_now_iso,
    validate_error,
    validate_success,
)


# ===========================================================================
# StatePolicy creation — PRD §3.1
# ===========================================================================
class TestStatePolicyCreation:

    def test_create_state_policy_returns_201_and_shape(
            self, api, policy_admin_headers):
        """PRD §4: "POST /state-policies ... 201" returns the newly
        created resource. PRD §3.1: a StatePolicy carries fpl_base_amount,
        fpl_per_member_amount, magi_income_limit_pct.

        Claim: a valid create returns 201 with the documented entity
        fields.
        """
        code = random_state_code()
        res = api.create_state_policy(
            create_state_policy_payload(
                state_code=code,
                fpl_base_amount=15_000.00,
                fpl_per_member_amount=5_000.00,
                magi_income_limit_pct=138.0,
            ),
            policy_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_state_policy(data)
        assert data["state_code"] == code

    def test_state_policy_default_asset_test_applies_false(
            self, api, policy_admin_headers):
        """PRD §3.1: "The asset_test_applies flag defaults to false,
        reflecting that most MAGI-based categories carry no asset test."

        Claim: omitting asset_test_applies results in a policy whose
        asset_test_applies is false.
        """
        code = random_state_code()
        payload = create_state_policy_payload(state_code=code)
        # Ensure we explicitly omit asset_test_applies.
        payload.pop("asset_test_applies", None)
        res = api.create_state_policy(payload, policy_admin_headers)
        data = validate_success(res, expected_status=201)
        assert data["asset_test_applies"] is False, (
            "asset_test_applies must default to false per PRD §3.1, "
            f"got {data.get('asset_test_applies')!r}"
        )

    def test_state_policy_default_state_disregard_amount_zero(
            self, api, policy_admin_headers):
        """PRD §3.1: "Each policy may also publish a
        state_disregard_amount that is subtracted from raw MAGI before
        the FPL percentage is computed (defaulting to zero)."

        Claim: omitting state_disregard_amount results in a policy
        whose state_disregard_amount is 0.
        """
        code = random_state_code()
        payload = create_state_policy_payload(state_code=code)
        payload.pop("state_disregard_amount", None)
        res = api.create_state_policy(payload, policy_admin_headers)
        data = validate_success(res, expected_status=201)
        assert float(data["state_disregard_amount"]) == 0.0, (
            "state_disregard_amount must default to zero per PRD §3.1, "
            f"got {data.get('state_disregard_amount')!r}"
        )

    def test_get_state_policy_by_state_code(
            self, api, policy_admin_headers):
        """PRD §4: "GET /state-policies/:state_code".

        Claim: GET round-trips the created policy by state_code.
        """
        policy = create_state_policy()
        res = api.get_state_policy(policy["state_code"], policy_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["state_code"] == policy["state_code"]


# ===========================================================================
# EmergencyDeclaration — PRD §3.1, §3.5
# ===========================================================================
class TestEmergencyDeclaration:

    def test_create_federal_declaration_returns_201(
            self, api, policy_admin_headers):
        """PRD §3.1: "Each declaration carries a scope of FEDERAL or
        STATE."
        PRD §3.1: "when the scope is FEDERAL, state_code must be null."

        Claim: a FEDERAL declaration with state_code=null returns 201
        and the resource shape.
        """
        res = api.create_emergency_declaration(
            create_emergency_declaration_payload(
                scope="FEDERAL", state_code=None,
                declared_at=iso_now(), expires_at=iso_offset(days=30),
            ),
            policy_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_emergency_declaration(data)
        assert data["scope"] == "FEDERAL"
        assert data["state_code"] is None

    def test_create_state_scoped_declaration_requires_state_code(
            self, api, policy_admin_headers):
        """PRD §3.1: "When the scope is STATE, a state_code is required
        and identifies the affected state."

        Claim: a STATE declaration without state_code → ERR_INVALID_REQUEST.
        """
        payload = create_emergency_declaration_payload(
            scope="STATE", state_code=None,
            declared_at=iso_now(), expires_at=iso_offset(days=30),
        )
        # Force state_code missing from the body.
        payload.pop("state_code", None)
        res = api.create_emergency_declaration(payload, policy_admin_headers)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_emergency_declaration_is_append_only_no_version(
            self, api, policy_admin_headers):
        """PRD §2.4: "The EmergencyDeclaration is also append-only and
        likewise carries only id and created_at."

        Claim: a created EmergencyDeclaration does not carry a `version`
        field.
        """
        decl = issue_emergency_declaration(
            scope="FEDERAL", state_code=None,
            declared_at=iso_now(), expires_at=iso_offset(days=30),
        )
        assert "version" not in decl, (
            "EmergencyDeclaration must not carry a `version` field per "
            f"PRD §2.4; got {list(decl.keys())}"
        )

    def test_emergency_declaration_active_status_when_within_window(
            self, api, policy_admin_headers):
        """PRD §3.1: "It is ACTIVE when declared_at <= clock_now <
        expires_at."

        Claim: a freshly-created declaration with declared_at=now and
        expires_at=now+30d returns status=ACTIVE.
        """
        decl = issue_emergency_declaration(
            scope="FEDERAL", state_code=None,
            declared_at=iso_now(), expires_at=iso_offset(days=30),
        )
        # Refetch via GET to read derived status.
        res = api.get_emergency_declaration(decl["id"], policy_admin_headers)
        data = validate_success(res)
        assert data["status"] == "ACTIVE", (
            f"status must be ACTIVE when within window per PRD §3.1, "
            f"got {data['status']!r}"
        )


# ===========================================================================
# Clock advance — PRD §2.11
# ===========================================================================
class TestClockAdvance:

    def test_clock_advance_backwards_rejected(self, api, policy_admin_headers):
        """PRD §2.11: "The advance must be monotonic forward — a `to`
        value that is strictly earlier than the current clock_now is
        rejected with ERR_INVALID_REQUEST."

        Claim: advancing to a past instant → ERR_INVALID_REQUEST.
        """
        from test_helpers import advance_clock_to, clock_advance_payload
        # First advance forward, then attempt to go back.
        future = iso_offset(days=1)
        advance_clock_to(future)
        past = iso_offset(days=-1, base=server_now_dt())
        res = api.clock_advance(
            clock_advance_payload(to=past), policy_admin_headers,
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_clock_advance_expires_emergency_declaration(
            self, api, policy_admin_headers):
        """PRD §2.11: "Advancing the clock has two automatic side
        effects: any EmergencyDeclaration whose expires_at is at or
        before the new clock_now transitions to EXPIRED."

        Claim: advancing past expires_at flips the declaration's
        status from ACTIVE to EXPIRED.
        """
        from test_helpers import advance_clock_to
        # Create a declaration with a short window.
        expires = iso_offset(days=1)
        decl = issue_emergency_declaration(
            scope="FEDERAL", state_code=None,
            declared_at=iso_now(), expires_at=expires,
        )
        # Sanity: still ACTIVE before advance.
        res = api.get_emergency_declaration(decl["id"], policy_admin_headers)
        assert validate_success(res)["status"] == "ACTIVE"
        # Advance clock to expires.
        advance_clock_to(expires)
        res = api.get_emergency_declaration(decl["id"], policy_admin_headers)
        data = validate_success(res)
        assert data["status"] == "EXPIRED", (
            f"status must be EXPIRED after clock reaches expires_at per "
            f"PRD §2.11, got {data['status']!r}"
        )
