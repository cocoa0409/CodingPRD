"""State license lifecycle and license-coverage cascades.

PRD §3.1 (PENDING -> ACTIVE on verify, ACTIVE -> EXPIRED on clock,
ACTIVE -> REVOKED on revoke), §3.6 (appointment-hold cascade), §2.8
(deterministic clock).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_state_license,
    create_state_license,
    create_state_license_payload,
    create_therapist,
    iso_anchor_offset,
    iso_midnight,
    re_get_appointment,
    revoke_state_license,
    setup_active_licensed_therapist,
    setup_scheduled_appointment,
    validate_error,
    validate_success,
    verify_state_license,
)


# ===========================================================================
# §3.1 Create + verify
# ===========================================================================
class TestStateLicenseCreation:

    def test_create_state_license_initial_status_pending(self, api):
        """PRD §3.1: "A new license is born in status = PENDING."

        Claim: a freshly-created StateLicense returns status=PENDING.
        """
        therapist = create_therapist(supervision_track="LICENSED")
        res = api.create_state_license(
            therapist["id"],
            create_state_license_payload(state_code="NY"),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_state_license(data)
        assert data["status"] == "PENDING"

    def test_verify_license_outside_validity_window_rejected(self, api):
        """PRD §3.1: "transitioning it from PENDING to ACTIVE, but only
        when the current clock date is on or after issued_on and
        strictly before expires_on."

        Claim: verify on a license whose expires_on has already passed
        (current clock >= expires_on) returns ERR_INVALID_STATE.
        """
        anchor_clock()  # 2026-05-17T10:00Z
        therapist = create_therapist(supervision_track="LICENSED")
        license_ = create_state_license(
            therapist["id"], state_code="NY",
            issued_on=iso_midnight(2024, 1, 1),
            expires_on=iso_midnight(2025, 1, 1),  # already past anchor
        )
        res = api.verify_state_license(
            therapist["id"], license_["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_verify_license_before_issued_on_rejected(self, api):
        """PRD §3.1: "transitioning it from PENDING to ACTIVE, but only
        when the current clock date is on or after issued_on ..."

        Claim: verifying a license whose issued_on is in the future
        returns ERR_INVALID_STATE.
        """
        anchor_clock()
        therapist = create_therapist(supervision_track="LICENSED")
        license_ = create_state_license(
            therapist["id"], state_code="NY",
            issued_on=iso_midnight(2030, 1, 1),
            expires_on=iso_midnight(2031, 1, 1),
        )
        res = api.verify_state_license(
            therapist["id"], license_["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.1 Expiry by clock advance (depth-2 cascade)
# ===========================================================================
class TestLicenseExpiryCascade:

    def test_clock_advance_to_expires_on_expires_license(self, api):
        """PRD §3.1: "when the deterministic clock advances to an
        instant on or after the license's expires_on, the license
        transitions from ACTIVE to EXPIRED."

        Claim: advancing the clock to exactly expires_on transitions
        the only ACTIVE license to EXPIRED.
        """
        anchor_clock()
        therapist, license_ = setup_active_licensed_therapist(
            license_expires_on=iso_midnight(2026, 6, 1),
        )
        advance_clock_to("2026-06-01T00:00:00.000Z")
        res = api.list_state_licenses(
            therapist["id"], TEST_USERS["practice_admin_headers"],
        )
        # Re-read this license individually via the list and look it up.
        from prd_bench_local_runner.testing import validate_paginated
        items, _ = validate_paginated(res)
        target = next(li for li in items if li["id"] == license_["id"])
        assert target["status"] == "EXPIRED"

    def test_clock_advance_expiry_holds_future_appointment(self, api):
        """PRD §3.1: "if the owning therapist no longer has any other
        ACTIVE license, the system propagates the loss of coverage
        downstream: every future SCHEDULED appointment for that
        therapist transitions to HELD with hold_reason = LICENSE_GAP."

        Claim: clock-driven license expiry cascades a hold on the
        therapist's future SCHEDULED appointment with hold_reason=
        LICENSE_GAP.
        """
        anchor_clock()
        therapist, license_ = setup_active_licensed_therapist(
            license_expires_on=iso_midnight(2026, 6, 1),
        )
        from test_helpers import (
            create_patient,
            schedule_appointment,
        )
        patient = create_patient(state_of_residence="NY")
        sched_start = "2026-06-02T10:00:00.000Z"
        sched_end = "2026-06-02T10:45:00.000Z"
        appt = schedule_appointment(
            therapist["id"], patient["id"],
            cpt_code="90834", modality="IN_PERSON",
            patient_state_on_day="NY",
            scheduled_start=sched_start, scheduled_end=sched_end,
        )
        advance_clock_to("2026-06-01T00:00:00.000Z")
        appt = re_get_appointment(appt["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "LICENSE_GAP"


# ===========================================================================
# §3.1 Revoke cascade
# ===========================================================================
class TestLicenseRevokeCascade:

    def test_revoke_active_license_transitions_to_revoked(self, api):
        """PRD §3.1: "an administrator may also revoke the license
        directly, transitioning it from ACTIVE to REVOKED."

        Claim: revoke returns status=REVOKED.
        """
        anchor_clock()
        therapist, license_ = setup_active_licensed_therapist()
        res = api.revoke_state_license(
            therapist["id"], license_["id"],
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REVOKED"

    def test_revoke_holds_future_appointment_when_no_other_active(self, api):
        """PRD §3.1: "In both cases [expiry and revoke], if the owning
        therapist no longer has any other ACTIVE license, the system
        propagates the loss of coverage downstream: every future
        SCHEDULED appointment for that therapist transitions to HELD
        with hold_reason = LICENSE_GAP."

        Claim: revoking the only ACTIVE license HOLDs the future
        SCHEDULED appointment with hold_reason=LICENSE_GAP.
        """
        bundle = setup_scheduled_appointment()
        revoke_state_license(
            bundle["therapist"]["id"], bundle["license"]["id"],
        )
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "LICENSE_GAP"
