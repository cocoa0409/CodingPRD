"""Community / Household / Resident bootstrap and lifecycle tests.

Covers PRD §3.1 — Community creation, Household creation, Resident
registration, identity verification, restriction, and the sweep that lifts
expired restrictions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_community,
    create_community_payload,
    create_household,
    create_household_payload,
    create_resident,
    create_resident_payload,
    fetch_household,
    fetch_resident,
    iso_z,
    make_community_admin_headers,
    make_resident_headers,
    make_system_operator_headers,
    restrict_resident_payload,
    run_sweep,
    setup_verified_resident,
    submit_disposal,
    verify_resident,
    verify_resident_payload,
)
from test_helpers import api_client as api_singleton


# ===========================================================================
# Community
# ===========================================================================
class TestCommunity:
    def test_create_community_returns_active_status(self, api):
        """PRD §3.1: 'Communities are born ACTIVE; the alternative state in
        the enumeration is ARCHIVED.'"""
        community = create_community()
        assert community["status"] == "ACTIVE"
        assert community["code"].startswith("CMTY-")

    def test_create_community_with_default_timezone_utc(self, api):
        """PRD §3.1: 'an optional timezone IANA identifier defaulting to UTC.'"""
        community = create_community()
        assert community["timezone"] == "UTC"

    def test_create_community_duplicate_code_rejected(self, api):
        """PRD §3.1: 'a code matching the pattern CMTY- followed by three
        to six digits and also globally unique.'"""
        first = create_community()
        resp = api.create_community(
            create_community_payload(code=first["code"]),
            make_system_operator_headers(),
        )
        # The PRD names uniqueness — implementation may surface this as
        # ERR_VALIDATION (a pattern/uniqueness violation under field
        # constraints in §2.10 priority 20).
        body = resp.json()
        assert resp.status_code in (400, 409), (
            f"Expected validation/conflict, got {resp.status_code}: {body}"
        )

    def test_create_community_invalid_code_pattern_rejected(self, api):
        """PRD §3.1: 'a code matching the pattern CMTY- followed by three
        to six digits.'"""
        resp = api.create_community(
            create_community_payload(code="NOTACODE"),
            make_system_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Household
# ===========================================================================
class TestHousehold:
    def test_create_household_born_active(self, api):
        """PRD §3.1: 'Households are born ACTIVE; the lifecycle enumeration
        also recognizes SUSPENDED and ARCHIVED.'"""
        community = create_community()
        household = create_household(community["id"])
        assert household["status"] == "ACTIVE"
        assert household["points_balance"] == 0
        assert household["lifetime_points_earned"] == 0
        assert household["head_resident_id"] is None

    def test_create_household_initializes_counters_to_zero(self, api):
        """PRD §3.1: 'Two reconciled counters - points_balance and
        lifetime_points_earned - are both initialized to zero.'"""
        community = create_community()
        household = create_household(community["id"])
        assert household["points_balance"] == 0
        assert household["lifetime_points_earned"] == 0


# ===========================================================================
# Resident — registration, verification, head_resident_id
# ===========================================================================
class TestResident:
    def test_new_resident_is_pending_and_inactive(self, api):
        """PRD §3.1: 'New residents are born with identity_status of PENDING
        and account_status of INACTIVE.'"""
        community = create_community()
        household = create_household(community["id"])
        resident = create_resident(community["id"], household["id"])
        assert resident["identity_status"] == "PENDING"
        assert resident["account_status"] == "INACTIVE"

    def test_verify_approve_flips_to_verified_and_active(self, api):
        """PRD §3.1: 'an APPROVE decision transitions identity_status from
        PENDING to VERIFIED, and additionally sets account_status to ACTIVE
        provided the account is not currently RESTRICTED.'"""
        community = create_community()
        household = create_household(community["id"])
        resident = create_resident(community["id"], household["id"])
        verified = verify_resident(
            community["id"], household["id"], resident["id"], "APPROVE",
        )
        assert verified["identity_status"] == "VERIFIED"
        assert verified["account_status"] == "ACTIVE"

    def test_verify_reject_flips_identity_to_rejected_only(self, api):
        """PRD §3.1: 'a REJECT decision flips identity_status to REJECTED
        while leaving account_status as INACTIVE.'"""
        community = create_community()
        household = create_household(community["id"])
        resident = create_resident(community["id"], household["id"])
        rejected = verify_resident(
            community["id"], household["id"], resident["id"], "REJECT",
        )
        assert rejected["identity_status"] == "REJECTED"
        assert rejected["account_status"] == "INACTIVE"

    def test_first_verified_resident_becomes_head(self, api):
        """PRD §3.1: 'the system sets head_resident_id to that resident's
        id at the moment its identity_status flips to VERIFIED.'"""
        community = create_community()
        household = create_household(community["id"])
        resident = create_resident(community["id"], household["id"])
        verify_resident(community["id"], household["id"], resident["id"])
        hh = fetch_household(community["id"], household["id"])
        assert hh["head_resident_id"] == resident["id"]


# ===========================================================================
# Resident — restriction and the sweep
# ===========================================================================
class TestResidentRestriction:
    def test_restrict_keeps_identity_verified_sets_account_restricted(
        self, api,
    ):
        """PRD §3.1: 'The restrict transition keeps identity_status unchanged
        at VERIFIED and sets account_status to RESTRICTED and
        restricted_until to the supplied until.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        until_iso = "2030-01-02T00:00:00.000Z"
        resp = api.restrict_resident(
            community["id"], household["id"], resident["id"],
            restrict_resident_payload(until=until_iso, reason="test"),
            make_community_admin_headers(),
        )
        data = validate_success(resp)
        assert data["identity_status"] == "VERIFIED"
        assert data["account_status"] == "RESTRICTED"
        assert data["restricted_until"] == until_iso

    def test_sweep_lifts_expired_restrictions(self, api):
        """PRD §3.1: 'the system operator's sweep capability lifts each
        expired restriction (transitioning account_status back to ACTIVE
        when restricted_until is at or before the logical clock) and reports
        the count of residents unrestricted under the response field
        residents_unrestricted.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        until_iso = "2030-01-02T00:00:00.000Z"
        api.restrict_resident(
            community["id"], household["id"], resident["id"],
            restrict_resident_payload(until=until_iso, reason="test"),
            make_community_admin_headers(),
        )
        # Before expiry: sweep does nothing.
        result_before = run_sweep()
        assert result_before["residents_unrestricted"] == 0
        # Advance past expiry and sweep again.
        advance_clock("2030-01-02T00:00:01.000Z")
        result_after = run_sweep()
        assert result_after["residents_unrestricted"] == 1
        # Resident is now ACTIVE.
        r = fetch_resident(community["id"], household["id"], resident["id"])
        assert r["account_status"] == "ACTIVE"


# ===========================================================================
# Resident ownership for resident-issued endpoints (PRD §2.1, §3.3)
# ===========================================================================
class TestResidentOwnership:
    def test_resident_cannot_submit_disposal_for_other_resident(self, api):
        """PRD §2.1: 'ownership checks on any resource that references a
        Resident compare the resource's resident_id foreign-key field to
        X-User-ID ... Ownership failures surface as ERR_FORBIDDEN.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        c_a, hh_a, r_a = setup_verified_resident()
        c_b, hh_b, r_b = setup_verified_resident()
        # r_b tries to submit a disposal claiming r_a is the submitter,
        # under hh_a's path. r_b's X-User-ID != r_a.id, ownership fails.
        resp = api.create_disposal(
            c_a["id"], hh_a["id"],
            {
                "resident_id": r_a["id"],
                "disposal_time": "2030-01-01T00:00:00.000Z",
                "location_code": "BIN-1",
                "declared_category": "RECYCLABLE",
                "actual_category": "RECYCLABLE",
                "scoring_method": "MANUAL",
                "accuracy_score": 1.000,
                "evidence_uri": "https://x.example/e",
                "weight_kg": 1.0,
            },
            make_resident_headers(r_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
