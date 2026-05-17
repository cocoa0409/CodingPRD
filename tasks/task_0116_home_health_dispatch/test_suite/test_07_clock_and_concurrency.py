"""Logical clock advance + optimistic concurrency control.

PRD §2.7 (clock), §2.8 (OCC).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_clock_state,
    create_clinician,
    create_patient,
    get_clock,
    patch_clinician,
    patch_clinician_payload,
    patch_patient,
    patch_patient_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Clock — basic advance + monotonic guard
# ===========================================================================
class TestClockAdvance:

    def test_admin_can_advance_clock(self, api):
        """PRD §2.7: "The current_date on the ClockState singleton is
        advanced monotonically through an admin-only test-driving
        capability that takes a target_date ISO date in the request
        body."

        Claim: PlatformAdmin can advance the clock to a future date.
        """
        anchor_clock("2026-01-01")
        res = api.clock_advance(
            {"target_date": "2026-06-01"},
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert_clock_state(data)
        assert data["current_date"] == "2026-06-01"

    def test_clock_advance_to_past_rejected(self, api):
        """PRD §2.7: "The target must be on or after the existing
        current_date; attempting to move the clock backward is rejected
        with ERR_CLOCK_BACKWARDS."

        Claim: advancing to a target_date strictly before the existing
        current_date returns ERR_CLOCK_BACKWARDS.
        """
        anchor_clock("2026-06-01")
        res = api.clock_advance(
            {"target_date": "2026-01-01"},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, "ERR_CLOCK_BACKWARDS")

    def test_get_clock_returns_current_date(self, api):
        """PRD §2.4 / §2.7: "Its sole exposed attribute is current_date."

        Claim: GET /_clock returns the current ClockState with
        current_date.
        """
        anchor_clock("2026-03-15")
        data = get_clock()
        assert_clock_state(data)
        assert data["current_date"] == "2026-03-15"


# ===========================================================================
# OCC — Patient and Clinician version-conflict checks
# ===========================================================================
class TestOptimisticConcurrency:

    def test_patient_stale_version_returns_conflict(self, api):
        """PRD §2.8: "When the caller includes version, the server
        compares it to the resource's current version; on mismatch the
        request is rejected with ERR_VERSION_CONFLICT."

        Claim: PATCH /patients with a stale version → ERR_VERSION_CONFLICT.
        """
        p = create_patient()
        stale = p["version"]
        # First patch bumps version to 2.
        patch_patient(patient=p, full_name="Updated Once")
        # Submit again with the OLD version.
        res = api.patch_patient(
            p["id"],
            patch_patient_payload(full_name="Update Two", version=stale),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_clinician_stale_version_returns_conflict(self, api):
        """PRD §2.8: "When the caller includes version, the server
        compares it to the resource's current version; on mismatch the
        request is rejected with ERR_VERSION_CONFLICT."

        Claim: PATCH /clinicians with a stale version →
        ERR_VERSION_CONFLICT.
        """
        c = create_clinician(discipline="SN")
        stale = c["version"]
        patch_clinician(clinician=c, status="SUSPENDED")
        res = api.patch_clinician(
            c["id"],
            patch_clinician_payload(
                status="AVAILABLE", version=stale,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")
