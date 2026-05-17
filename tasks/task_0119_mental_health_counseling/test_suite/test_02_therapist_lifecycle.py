"""Therapist creation, validation, and credential-status lifecycle.

PRD §3.1 (create + invariants), §3.2 (activate / suspend / reinstate /
deactivate cascade), §2.4 (versioning).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    REQUIRED_HOURS_FOR_LICENSURE,
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_appointment,
    assert_therapist,
    assert_version_incremented_by_one,
    create_appointment_payload,
    create_state_license,
    create_state_license_payload,
    create_supervision_assignment,
    create_supervisor,
    create_therapist,
    create_therapist_payload,
    iso_anchor_offset,
    iso_midnight,
    occ_payload,
    patch_therapist_payload,
    re_get_appointment,
    re_get_therapist,
    reinstate_therapist,
    schedule_appointment,
    setup_active_licensed_therapist,
    setup_pre_licensed_therapist_with_supervision,
    setup_scheduled_appointment,
    suspend_therapist,
    validate_error,
    validate_success,
    verify_state_license,
)


# ===========================================================================
# §3.1 Create
# ===========================================================================
class TestCreateTherapist:
    """PRD §3.1: 'A practice administrator brings a new clinician into
    the system by recording the therapist's full_name and npi.'"""

    def test_create_therapist_initial_state(self, api):
        """PRD §3.1: "A new therapist is born in credential_status =
        PROVISIONAL, with supervision_hours_accrued initialised to 0.00
        and licensure_exam_eligible initialised to false."

        Claim: a freshly-created therapist has credential_status=
        PROVISIONAL, supervision_hours_accrued=0.00,
        licensure_exam_eligible=false.
        """
        res = api.create_therapist(
            create_therapist_payload(supervision_track="LICENSED"),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_therapist(data)
        assert data["credential_status"] == "PROVISIONAL"
        assert data["supervision_hours_accrued"] == pytest.approx(0.00)
        assert data["licensure_exam_eligible"] is False
        assert data["version"] == 1

    def test_create_therapist_negative_rack_rate_rejected(self, api):
        """PRD §2.6 / §3.1: "Negative monetary inputs are rejected
        with ERR_INVALID_AMOUNT (HTTP 422)." PRD §3.1: rack rates "both
        required to be at least zero."

        Claim: negative pricing_rack_90834_cents returns
        ERR_INVALID_AMOUNT.
        """
        payload = create_therapist_payload(
            pricing_rack_90834_cents=-1,
        )
        res = api.create_therapist(
            payload, TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_INVALID_AMOUNT")

    def test_create_therapist_zero_rack_rate_accepted(self, api):
        """PRD §3.1: "both required to be at least zero." Zero is the
        inclusive lower boundary.

        Claim: pricing_rack_90834_cents=0 is accepted.
        """
        payload = create_therapist_payload(
            pricing_rack_90834_cents=0,
        )
        res = api.create_therapist(
            payload, TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["pricing_rack_90834_cents"] == 0

    def test_create_therapist_invalid_npi_rejected(self, api):
        """PRD §3.1: "The npi is the National Provider Identifier, a
        ten-digit numeric string that must match the regular shape of
        ten digits and be unique within the practice."

        Claim: an NPI that is not exactly 10 digits returns
        ERR_VALIDATION.
        """
        payload = create_therapist_payload(npi="123")
        res = api.create_therapist(
            payload, TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# §3.2 Activation preconditions
# ===========================================================================
class TestActivateTherapist:
    """PRD §3.2: 'A PROVISIONAL therapist is promoted to ACTIVE by an
    administrative activation.'"""

    def test_activate_without_active_license_rejected(self, api):
        """PRD §3.2: "The system requires at least one of the
        therapist's licenses to be in status = ACTIVE; without it, the
        request is rejected with ERR_NO_ACTIVE_LICENSE."

        Claim: activating a therapist with no ACTIVE license returns
        ERR_NO_ACTIVE_LICENSE.
        """
        therapist = create_therapist(supervision_track="LICENSED")
        # No license at all.
        res = api.activate_therapist(
            therapist["id"], TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_NO_ACTIVE_LICENSE")

    def test_activate_licensed_with_active_license_succeeds(self, api):
        """PRD §3.2: "A LICENSED therapist needs only the active-license
        requirement to activate."

        Claim: LICENSED therapist with one ACTIVE license is admitted
        to credential_status=ACTIVE.
        """
        therapist = create_therapist(supervision_track="LICENSED")
        license_ = create_state_license(therapist["id"], state_code="NY")
        verify_state_license(therapist["id"], license_["id"])
        res = api.activate_therapist(
            therapist["id"], TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["credential_status"] == "ACTIVE"

    def test_activate_pre_licensed_without_supervision_assignment_rejected(
        self, api,
    ):
        """PRD §3.2: "For a PRE_LICENSED therapist the system
        additionally requires two things: the therapist must have
        accumulated at least 3000.00 hours in supervision_hours_accrued
        ... and there must be a SupervisionAssignment with status =
        ACTIVE pairing this therapist with a supervisor. If either
        requirement is unmet, the request is rejected with
        ERR_SUPERVISION_INCOMPLETE."

        Claim: PRE_LICENSED therapist with ACTIVE license but no
        SupervisionAssignment returns ERR_SUPERVISION_INCOMPLETE.
        """
        therapist = create_therapist(supervision_track="PRE_LICENSED")
        license_ = create_state_license(therapist["id"], state_code="NY")
        verify_state_license(therapist["id"], license_["id"])
        res = api.activate_therapist(
            therapist["id"], TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_SUPERVISION_INCOMPLETE")

    def test_activate_pre_licensed_with_zero_hours_rejected(self, api):
        """PRD §3.2: "the therapist must have accumulated at least
        3000.00 hours in supervision_hours_accrued (the boundary is
        inclusive, so exactly 3000.00 qualifies)... If either
        requirement is unmet, the request is rejected with
        ERR_SUPERVISION_INCOMPLETE."

        Claim: PRE_LICENSED therapist with ACTIVE assignment but 0.00
        hours accrued returns ERR_SUPERVISION_INCOMPLETE.
        """
        therapist = create_therapist(supervision_track="PRE_LICENSED")
        license_ = create_state_license(therapist["id"], state_code="NY")
        verify_state_license(therapist["id"], license_["id"])
        supervisor = create_supervisor()
        create_supervision_assignment(
            therapist_id=therapist["id"],
            supervisor_id=supervisor["id"],
        )
        # supervision_hours_accrued is still 0.00 — below 3000.00.
        assert therapist["supervision_hours_accrued"] == pytest.approx(0.0)
        assert REQUIRED_HOURS_FOR_LICENSURE == 3000.00
        res = api.activate_therapist(
            therapist["id"], TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_SUPERVISION_INCOMPLETE")


# ===========================================================================
# §3.2 Suspend / reinstate / deactivate
# ===========================================================================
class TestSuspendReinstateCascade:
    """PRD §3.2: 'every future SCHEDULED appointment ... transitions to
    HELD with hold_reason = LICENSE_GAP. The reinstatement ... cascade
    unholds every appointment ...'."""

    def test_suspend_active_therapist_holds_future_appointment(self, api):
        """PRD §3.2: "The suspension transition takes the therapist
        from ACTIVE to SUSPENDED with no clinical preconditions and
        writes credential_status := SUSPENDED. It then cascades: every
        future SCHEDULED appointment (where scheduled_start is after
        the current clock) for this therapist transitions to HELD with
        hold_reason = LICENSE_GAP."

        Claim: suspending an ACTIVE therapist HOLDs their future
        SCHEDULED appointments with hold_reason=LICENSE_GAP.
        """
        bundle = setup_scheduled_appointment()
        before = bundle["therapist"]["version"]
        suspended = suspend_therapist(bundle["therapist"]["id"])
        assert suspended["credential_status"] == "SUSPENDED"
        assert_version_incremented_by_one(
            before, suspended["version"], "Therapist",
        )
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "LICENSE_GAP"

    def test_reinstate_suspended_therapist_unholds_appointment(self, api):
        """PRD §3.2: "the cascade unholds every appointment that was
        placed in HELD with hold_reason = LICENSE_GAP for this
        therapist, returning each from HELD back to SCHEDULED."

        Claim: after reinstate, a previously held appointment returns
        to SCHEDULED with hold_reason=null.
        """
        bundle = setup_scheduled_appointment()
        suspend_therapist(bundle["therapist"]["id"])
        reinstate_therapist(bundle["therapist"]["id"])
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "SCHEDULED"
        assert appt.get("hold_reason") is None

    def test_reinstate_without_active_license_rejected(self, api):
        """PRD §3.2: "an administrator returns the therapist from
        SUSPENDED to ACTIVE, provided the therapist still has at least
        one ACTIVE license."

        Claim: reinstate after the only ACTIVE license was revoked
        returns ERR_NO_ACTIVE_LICENSE.
        """
        anchor_clock()
        therapist, license_ = setup_active_licensed_therapist()
        suspend_therapist(therapist["id"])
        # Revoke the only license while suspended.
        from test_helpers import revoke_state_license
        revoke_state_license(therapist["id"], license_["id"])
        res = api.reinstate_therapist(
            therapist["id"], TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_NO_ACTIVE_LICENSE")

    def test_deactivate_with_scheduled_appointment_rejected(self, api):
        """PRD §3.2: "Deactivation is the irreversible end of a
        therapist's lifecycle: an administrator may move the therapist
        from ACTIVE to DEACTIVATED or from SUSPENDED to DEACTIVATED,
        but only when no appointment for the therapist remains in any
        of SCHEDULED, HELD, or CHECKED_IN."

        Claim: attempting to deactivate while a SCHEDULED appointment
        exists returns ERR_INVALID_STATE.
        """
        bundle = setup_scheduled_appointment()
        res = api.deactivate_therapist(
            bundle["therapist"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_deactivate_with_no_open_appointments_succeeds(self, api):
        """PRD §3.2: "but only when no appointment for the therapist
        remains in any of SCHEDULED, HELD, or CHECKED_IN."

        Claim: deactivating a therapist with zero open appointments
        succeeds and writes credential_status=DEACTIVATED.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        res = api.deactivate_therapist(
            therapist["id"], TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["credential_status"] == "DEACTIVATED"


# ===========================================================================
# §2.4 OCC
# ===========================================================================
class TestVersioning:
    """PRD §2.4: optimistic concurrency on PATCH and version-accepting
    POST."""

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.4: "When the client supplies version in the request
        body, the server compares it against the current entity
        version; a mismatch is rejected with ERR_VERSION_CONFLICT
        (HTTP 409)."

        Claim: PATCH /practice/therapists/{id} with stale version
        returns ERR_VERSION_CONFLICT.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        # Bump version via one PATCH.
        api.patch_therapist(
            therapist["id"],
            patch_therapist_payload(pricing_rack_90834_cents=99_999),
            TEST_USERS["practice_admin_headers"],
        )
        # Second PATCH with the stale (pre-bump) version.
        stale = patch_therapist_payload(
            pricing_rack_90834_cents=88_888,
            version=therapist["version"],
        )
        res = api.patch_therapist(
            therapist["id"], stale,
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_increments_version_by_one(self, api):
        """PRD §2.4: "an integer version that begins at 1 and
        increments by exactly 1 on every successful mutation."

        Claim: PATCH /practice/therapists/{id} increments version by
        exactly one.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        before = therapist["version"]
        res = api.patch_therapist(
            therapist["id"],
            patch_therapist_payload(psypact_enrolled=True),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert_version_incremented_by_one(before, data["version"],
                                          "Therapist")
        assert data["psypact_enrolled"] is True
