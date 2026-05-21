"""Park provisioning, OCC, posture transitions, Visitor CRUD, passes.

Covers PRD §2.4 (common-fields + version), §2.5 (OCC),
§2.7 (park posture transitions), §2.10 (timed_entry_window_minutes),
§3.1 (Visitor, wallet, passes), §3.2 (park config).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PASS_TYPES,
    TEST_USERS,
    api_client,
    assert_pass,
    assert_park,
    assert_version_incremented_by,
    assert_visitor,
    create_park,
    create_park_payload,
    create_visitor,
    create_visitor_with_wallet,
    deposit_wallet,
    freeze_park,
    get_park,
    get_visitor,
    issue_pass,
    issue_pass_payload,
    iso_utc,
    make_visitor_headers,
    patch_park_payload,
    reopen_park,
    restrict_park,
    revoke_pass,
    utcnow,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestParkCreate:

    def test_create_park_returns_open_status(self, api, park_admin_headers):
        """PRD §3.2: "A newly created park starts in the OPEN status."
        """
        resp = api.create_park(create_park_payload(), park_admin_headers)
        park = validate_success(resp, 201)
        assert_park(park)
        assert park["status"] == "OPEN"

    def test_create_park_default_window_minutes_is_60(self, api,
                                                     park_admin_headers):
        """PRD §3.2: "optionally its timed_entry_window_minutes
        (defaulting to 60 when not supplied; must evenly divide 1440)."
        """
        payload = create_park_payload()
        payload.pop("timed_entry_window_minutes", None)
        resp = api.create_park(payload, park_admin_headers)
        park = validate_success(resp, 201)
        assert park["timed_entry_window_minutes"] == 60

    def test_create_park_window_minutes_must_divide_1440(self, api,
                                                        park_admin_headers):
        """PRD §2.10: "Each park exposes a timed_entry_window_minutes
        (default 60), which must evenly divide 1440".
        """
        resp = api.create_park(
            create_park_payload(timed_entry_window_minutes=77),
            park_admin_headers,
        )
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_VALIDATION.value, (
            f"non-divisor must reject; got error_id={err!r}, body={body}"
        )

    def test_park_code_uniqueness(self, api, park_admin_headers):
        """PRD §3.2: "its short code (2 through 10 characters of
        uppercase letters and digits, unique, matching the pattern
        ^[A-Z0-9]+$)".
        """
        p1 = create_park(code="DUPLICATE")
        resp = api.create_park(
            create_park_payload(code="DUPLICATE"), park_admin_headers,
        )
        assert resp.status_code >= 400, (
            "duplicate code must be rejected; got 2xx"
        )


class TestParkPatchAndOCC:

    def test_patch_park_with_matching_version(self, api, park_admin_headers):
        """PRD §2.5: "When version is supplied and does not equal the
        resource's current version on the server, the request is
        rejected with ERR_VERSION_CONFLICT."

        Claim: PATCH with current version succeeds and bumps version.
        """
        park = create_park()
        resp = api.patch_park(
            park["id"],
            patch_park_payload(version=park["version"], name="Renamed"),
            park_admin_headers,
        )
        updated = validate_success(resp, 200)
        assert updated["name"] == "Renamed"
        assert_version_incremented_by(park, updated, delta=1)

    def test_patch_park_with_stale_version_rejected(self, api,
                                                   park_admin_headers):
        """PRD §2.5: "The same OCC mechanism is the serialisation point
        for the concurrent PATCH race: two callers updating the same
        Campground with stale version values resolve such that the
        higher-version writer wins and the stale one receives
        ERR_VERSION_CONFLICT."
        """
        park = create_park()
        # First PATCH advances version.
        first = validate_success(
            api.patch_park(
                park["id"],
                patch_park_payload(version=park["version"], name="V2"),
                park_admin_headers,
            ),
            200,
        )
        # Stale PATCH using the original version must fail.
        resp = api.patch_park(
            park["id"],
            patch_park_payload(version=park["version"], name="Stale"),
            park_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_park_without_version_skips_occ(self, api,
                                                 park_admin_headers):
        """PRD §2.5: "When version is omitted, the server performs the
        mutation without an OCC check."
        """
        park = create_park()
        resp = api.patch_park(
            park["id"],
            patch_park_payload(name="NoVersion"),
            park_admin_headers,
        )
        updated = validate_success(resp, 200)
        assert updated["name"] == "NoVersion"


class TestParkPostureTransitions:

    def test_open_to_restricted_transitions(self, api):
        """PRD §2.7: "From OPEN the park may be moved to RESTRICTED."
        """
        park = create_park()
        assert park["status"] == "OPEN"
        updated = restrict_park(park["id"])
        assert updated["status"] == "RESTRICTED"

    def test_open_to_frozen_direct_transitions(self, api):
        """PRD §2.7: "From OPEN the park may be moved to RESTRICTED ...
        or directly to FROZEN."
        """
        park = create_park()
        updated = freeze_park(park["id"])
        assert updated["status"] == "FROZEN"

    def test_restricted_to_frozen_transitions(self, api):
        """PRD §2.7: "From RESTRICTED the park may be moved back to
        OPEN or onward to FROZEN."
        """
        park = create_park()
        restrict_park(park["id"])
        updated = freeze_park(park["id"])
        assert updated["status"] == "FROZEN"

    def test_frozen_to_open_transitions(self, api):
        """PRD §2.7: "From FROZEN the park may only be returned to OPEN."
        """
        park = create_park()
        freeze_park(park["id"])
        updated = reopen_park(park["id"])
        assert updated["status"] == "OPEN"

    def test_restricted_to_open_transitions(self, api):
        """PRD §2.7: "From RESTRICTED the park may be moved back to OPEN."
        """
        park = create_park()
        restrict_park(park["id"])
        updated = reopen_park(park["id"])
        assert updated["status"] == "OPEN"

    def test_invalid_transition_rejected(self, api, park_admin_headers):
        """PRD §2.7: "Each transition checks the park's current status
        and rejects mismatched attempts with ERR_INVALID_STATE."

        Claim: freezing an already-FROZEN park → ERR_INVALID_STATE.
        """
        park = create_park()
        freeze_park(park["id"])
        # PRD §2.7 allows only FROZEN -> OPEN, so a second freeze must fail.
        resp = api.freeze_park(park["id"], park_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestVisitorCRUD:

    def test_create_visitor_starts_with_zero_wallet_and_strikes(self, api):
        """PRD §3.1: "wallet_balance_cents, which begins at 0, and
        lottery_strikes, which also begins at 0."
        """
        v = create_visitor()
        assert_visitor(v)
        assert v["wallet_balance_cents"] == 0
        assert v["lottery_strikes"] == 0

    def test_visitor_email_uniqueness(self, api, system_operator_headers):
        """PRD §3.1: "The record carries an email (RFC 5322 compliant,
        unique across the system)".
        """
        v = create_visitor(email="dup@example.com")
        # Second create with the same email must fail.
        from test_helpers import create_visitor_payload
        resp = api.create_visitor(
            create_visitor_payload(email="dup@example.com"),
            system_operator_headers,
        )
        assert resp.status_code >= 400

    def test_get_visitor_includes_computed_counters(self, api):
        """PRD §4: "GET /visitors/{visitor_id} ... Read a visitor (with
        computed wallet balance and strike count)".
        """
        v = create_visitor_with_wallet(wallet_cents=5000)
        fetched = get_visitor(v["id"])
        assert "wallet_balance_cents" in fetched
        assert "lottery_strikes" in fetched

    def test_wallet_deposit_credits_balance_and_records_ledger(self, api):
        """PRD §3.1: "Each deposit writes one LedgerEntry with kind of
        DEPOSIT and a positive amount_cents."

        PRD §2.9: "Visitor.wallet_balance_cents is the running sum of
        all amount_cents values for that visitor."
        """
        v = create_visitor()
        deposit_wallet(v["id"], 10_000)
        deposit_wallet(v["id"], 5_000)
        fetched = get_visitor(v["id"])
        assert fetched["wallet_balance_cents"] == 15_000

    def test_visitor_cannot_view_another_visitor(self, api):
        """PRD §2.1: "Ownership checks on any resource that references
        a visitor ... compare the resource's foreign-key field to
        X-User-ID."

        Claim: V2 GET on V1's visitor record → ERR_FORBIDDEN.
        """
        v1 = create_visitor()
        v2 = create_visitor()
        resp = api.get_visitor(v1["id"], make_visitor_headers(v2["id"]))
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        # PRD §2.1 names ERR_FORBIDDEN as the ownership-violation code.
        assert err == ApiErrorId.ERR_FORBIDDEN.value, (
            f"cross-visitor read should be forbidden; got {err!r}"
        )


class TestPasses:

    def test_park_admin_issues_pass(self, api, park_admin_headers):
        """PRD §3.1: "A ParkAdmin may issue an America the Beautiful
        Pass to a visitor."
        """
        v = create_visitor()
        resp = api.issue_pass(
            v["id"],
            issue_pass_payload(pass_type="ANNUAL"),
            park_admin_headers,
        )
        pass_ = validate_success(resp, 201)
        assert_pass(pass_)
        assert pass_["visitor_id"] == v["id"]
        assert pass_["pass_type"] == "ANNUAL"
        assert pass_["status"] == "ACTIVE"

    def test_pass_serial_is_twelve_chars(self, api):
        """PRD §3.1: "a server-minted twelve-character unique serial".
        """
        v = create_visitor()
        pass_ = issue_pass(v["id"])
        assert isinstance(pass_["serial"], str)
        assert len(pass_["serial"]) == 12, (
            f"serial must be exactly 12 chars, got {pass_['serial']!r}"
        )

    @pytest.mark.parametrize("pass_type", sorted(PASS_TYPES))
    def test_each_pass_type_accepted(self, api, pass_type):
        """PRD §3.1: "a pass_type drawn from {ANNUAL, SENIOR_ANNUAL,
        SENIOR_LIFETIME, MILITARY, ACCESS, VOLUNTEER, FOURTH_GRADE}".
        """
        v = create_visitor()
        pass_ = issue_pass(v["id"], pass_type=pass_type)
        assert pass_["pass_type"] == pass_type

    def test_revoke_pass_sets_revoked_status(self, api):
        """PRD §3.1: "The ParkAdmin may also revoke an active pass; the
        pass status moves to REVOKED and the pass is no longer accepted
        for entry-fee waivers."
        """
        v = create_visitor()
        pass_ = issue_pass(v["id"])
        revoked = revoke_pass(v["id"], pass_["id"])
        assert revoked["status"] == "REVOKED"

    def test_visitor_cannot_issue_pass_to_self(self, api):
        """PRD §4: "POST /visitors/{visitor_id}/passes ... ParkAdmin"
        (only). Visitor role is excluded.
        """
        v = create_visitor()
        resp = api.issue_pass(
            v["id"], issue_pass_payload(), make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
