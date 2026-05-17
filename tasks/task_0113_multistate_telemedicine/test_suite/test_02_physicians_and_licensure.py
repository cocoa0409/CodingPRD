"""Physician registration, license registration, license overlap, and
status projection.

PRD §3.1 (registration / portfolio), PRD §2.9 (status projection),
PRD §3.6 (revocation — link 1).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_physician,
    assert_state_license,
    create_physician,
    create_physician_payload,
    create_state_license,
    create_state_license_payload,
    random_dea_number,
    random_npi_number,
    revoke_state_license,
    re_get_state_license,
    setup_physician_with_license,
    setup_physician_with_one_license_for_overlap,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 Physician registration
# ===========================================================================
class TestPhysicianRegistration:

    def test_create_physician_succeeds_with_minimum_fields(self, api):
        """PRD §3.1: "A PlatformAdmin registers a physician by submitting
        a payload containing the physician's full_name, their 10-digit
        npi_number ... and an optional dea_number".

        Claim: minimum-required payload (full_name + npi_number)
        creates an ACTIVE physician.
        """
        res = api.create_physician(
            create_physician_payload(),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(res, 201)
        assert_physician(data)
        # PRD §3.1: "A new physician is created in ACTIVE status by
        # default".
        assert data["status"] == "ACTIVE"
        # PRD §3.1: "The imlc_compact_member flag defaults to false and
        # dea_number defaults to null when omitted."
        # We do not pin the wire representation of "null" (None vs missing)
        # because PRD does not specify — see Silence rule default-value.

    def test_create_physician_with_dea_number_persists(self, api):
        """PRD §3.1: "an optional dea_number for controlled-substance
        authority (matching the pattern of two uppercase letters
        followed by seven digits, unique across physicians when
        present)."

        Claim: a valid DEA number is accepted and the physician created.
        """
        dea = random_dea_number()
        res = api.create_physician(
            create_physician_payload(dea_number=dea),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(res, 201)
        assert_physician(data)
        assert data.get("dea_number") == dea


# ===========================================================================
# §3.1 StateLicense registration — license_type + interval rules
# ===========================================================================
class TestStateLicenseRegistration:

    def test_create_full_license_succeeds(self, api):
        """PRD §3.1: "A StateLicense is registered by submitting a
        state_code (two uppercase letters matching the US-state
        pattern), the issuing board's license_number, the license_type
        (either FULL for a traditional single-state license or
        IMLC_EXPEDITED for one issued through the Compact), issued_at,
        and expires_at."

        Claim: a valid FULL license payload returns 201.
        """
        physician = create_physician()
        res = api.create_state_license(
            physician["id"],
            create_state_license_payload(
                state_code="CA", license_type="FULL",
            ),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(res, 201)
        assert_state_license(data)
        assert data["state_code"] == "CA"
        assert data["license_type"] == "FULL"

    def test_create_imlc_license_succeeds(self, api):
        """PRD §3.1: "the license_type (either FULL for a traditional
        single-state license or IMLC_EXPEDITED for one issued through
        the Compact)".

        Claim: an IMLC_EXPEDITED license is accepted.
        """
        physician = create_physician(
            imlc_compact_member=True, imlc_home_state="CA",
        )
        res = api.create_state_license(
            physician["id"],
            create_state_license_payload(
                state_code="CA", license_type="IMLC_EXPEDITED",
            ),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(res, 201)
        assert data["license_type"] == "IMLC_EXPEDITED"


# ===========================================================================
# §3.1 License-overlap rule — half-open intervals
# ===========================================================================
class TestLicensePeriodOverlap:
    """PRD §3.1: "two licenses for the same (physician_id, state_code)
    are considered to overlap when the start of one is strictly before
    the end of the other and vice versa. Back-to-back licenses — where
    the first ends at exactly the same instant the second begins — are
    explicitly permitted; an attempted registration that overlaps is
    rejected with ERR_LICENSE_PERIOD_OVERLAP.\""""

    def test_overlapping_license_rejected(self, api):
        """PRD §3.1: "an attempted registration that overlaps is
        rejected with ERR_LICENSE_PERIOD_OVERLAP."

        Claim: registering a license whose [issued_at, expires_at)
        overlaps an existing license for the same (physician_id,
        state_code) returns ERR_LICENSE_PERIOD_OVERLAP.

        difficulty: resource_temporal_overlap/state_license_period_half_open_interval_overlap
        """
        physician, _ = setup_physician_with_one_license_for_overlap()
        # Existing license: [2026-01-01, 2026-12-31).
        # New license [2026-06-01, 2027-06-01) overlaps strictly.
        res = api.create_state_license(
            physician["id"],
            create_state_license_payload(
                state_code="CA",
                issued_at="2026-06-01T00:00:00.000Z",
                expires_at="2027-06-01T00:00:00.000Z",
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_LICENSE_PERIOD_OVERLAP")

    def test_back_to_back_licenses_permitted(self, api):
        """PRD §3.1: "Back-to-back licenses — where the first ends at
        exactly the same instant the second begins — are explicitly
        permitted".

        Claim: a license whose issued_at equals the prior license's
        expires_at is accepted (half-open semantics).

        difficulty: resource_temporal_overlap/state_license_period_half_open_interval_overlap
        """
        physician, _ = setup_physician_with_one_license_for_overlap()
        # New license [2026-12-31, 2027-12-31) — issued_at == prior
        # expires_at → non-overlap under half-open semantics.
        res = api.create_state_license(
            physician["id"],
            create_state_license_payload(
                state_code="CA",
                issued_at="2026-12-31T00:00:00.000Z",
                expires_at="2027-12-31T00:00:00.000Z",
            ),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(res, 201)
        assert_state_license(data)

    def test_different_state_does_not_conflict(self, api):
        """PRD §3.1: "Multiple licenses for the same physician in the
        same state are permitted only when their active intervals do
        not collide: each license's active interval is the half-open
        range from issued_at (inclusive) to expires_at (exclusive),
        and two licenses for the same (physician_id, state_code) are
        considered to overlap when the start of one is strictly before
        the end of the other and vice versa."

        Claim: registering an overlapping-time license under a
        DIFFERENT state_code is accepted (overlap is scoped to the same
        physician_id + state_code).
        """
        physician, _ = setup_physician_with_one_license_for_overlap()
        # Same time window but different state.
        res = api.create_state_license(
            physician["id"],
            create_state_license_payload(
                state_code="NY",
                issued_at="2026-06-01T00:00:00.000Z",
                expires_at="2027-06-01T00:00:00.000Z",
            ),
            TEST_USERS["admin_headers"],
        )
        validate_success(res, 201)


# ===========================================================================
# §2.9 License status projection — EXPIRED via clock advance
# ===========================================================================
class TestLicenseStatusProjection:
    """PRD §2.9: license status is a per-read projection: ACTIVE,
    EXPIRED (once clock ≥ expires_at), or REVOKED (once a revoke event
    is recorded)."""

    def test_status_projects_to_expired_after_clock_advance(self, api):
        """PRD §2.9: "if an AuditEvent of type LICENSE_REVOKED exists
        whose subject_id is the license's id, the license projects to
        REVOKED; else if the simulated clock's "now" is at or after the
        license's expires_at, it projects to EXPIRED; else it projects
        to ACTIVE."

        Claim: after advancing the clock past expires_at, listing the
        physician's licenses returns the license with status=EXPIRED.
        """
        anchor_clock("2026-01-01T00:00:00.000Z")
        physician, lic = setup_physician_with_license(
            issued_at="2026-01-01T00:00:00.000Z",
            expires_at="2026-06-01T00:00:00.000Z",
        )
        # Advance past expires_at.
        advance_clock_to("2026-06-02T00:00:00.000Z")
        refreshed = re_get_state_license(physician["id"], lic["id"])
        assert refreshed["status"] == "EXPIRED"

    def test_status_projects_to_revoked_after_revoke(self, api):
        """PRD §2.9: "if an AuditEvent of type LICENSE_REVOKED exists
        whose subject_id is the license's id, the license projects to
        REVOKED".

        Claim: after POST /revoke, the license projects to REVOKED.
        """
        physician, lic = setup_physician_with_license()
        revoke_state_license(physician["id"], lic["id"])
        refreshed = re_get_state_license(physician["id"], lic["id"])
        assert refreshed["status"] == "REVOKED"
