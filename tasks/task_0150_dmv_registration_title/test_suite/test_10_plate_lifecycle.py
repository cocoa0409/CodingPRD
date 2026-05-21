"""Plate suspend / reinstate / surrender lifecycle, including the
REAL ID revocation cascade.

PRD §3.9 and §3.10 revocation cascade.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    REAL_ID_ENFORCEMENT_INSTANT_ISO,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    approve_owner_to_real_id,
    create_owner,
    date_for_age,
    get_owner,
    get_plate,
    get_vehicle,
    parse_iso,
    post_salvage_event,
    reinstate_plate,
    revoke_real_id,
    setup_application_completed_titled,
    surrender_plate,
    surrender_plate_payload,
    suspend_plate,
    validate_error,
    validate_success,
)


class TestSuspendReinstate:

    def test_suspend_active_plate(self, api):
        """PRD §3.9: "A PlatformAdmin may suspend an ACTIVE plate by
        stamping suspended_at."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-susp-001",
            plate_issuer_operator_id="plate-op-susp-001",
        )
        plate_id = base["application"]["plate_id"]
        suspended = suspend_plate(plate_id)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspended_at"] is not None

    def test_reinstate_suspended_plate(self, api):
        """PRD §3.9: "the cyclic counterpart reinstates a SUSPENDED
        plate to ACTIVE and clears suspended_at to null."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-rein-001",
            plate_issuer_operator_id="plate-op-rein-001",
        )
        plate_id = base["application"]["plate_id"]
        suspend_plate(plate_id)
        reinstated = reinstate_plate(plate_id)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspended_at"] is None

    def test_reinstate_blocked_when_salvage_pending(self, api):
        """PRD §3.9: "Reinstatement is permitted only when
        Vehicle.title_status is in the set CLEAN or REBUILT."

        Claim: title_status SALVAGE_PENDING_REBUILD blocks reinstate
        with ERR_VEHICLE_SALVAGE_LOCKED.
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-relock-001",
            plate_issuer_operator_id="plate-op-relock-001",
        )
        plate_id = base["application"]["plate_id"]
        # Salvage event also suspends the plate per §3.3 cascade.
        post_salvage_event(base["vehicle"]["id"], severity="PARTIAL")
        # Try reinstate — vehicle is SALVAGE_PENDING_REBUILD.
        resp = api.reinstate_plate(
            plate_id, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_SALVAGE_LOCKED.value)

    def test_reinstate_blocked_when_owner_real_id_revoked_post_cutoff(self, api):
        """PRD §3.9: "Reinstatement is permitted only when ... Owner.
        real_id_status is not REVOKED OR the current time is strictly
        earlier than 2027-05-07T00:00:00Z."

        Claim: with REAL ID REVOKED AND clock past the cutoff,
        reinstate is blocked with ERR_OWNER_REAL_ID_REVOKED.
        """
        # Build a completed application; capture the owner's REAL ID
        # application via approve helper return so we can revoke later.
        owner = create_owner(date_of_birth=date_for_age(30))
        real_id_app = approve_owner_to_real_id(owner["id"])
        # Reuse the rest of the pipeline by re-running setup that
        # owners-and-vehicles-with-this-owner. The fixture builds its
        # own owner, so we cannot inject ours. Instead, finish a
        # completion flow then revoke a separately-created owner's REAL
        # ID to expose the gate. Since reinstate's gate is the OWNER of
        # the plate's vehicle, we need the plate's owner to be `owner`.
        # The simplest path: build the completion manually so the
        # owner is `owner`.
        from test_helpers import (
            assess_fees,
            create_transfer_application,
            create_vehicle,
            drive_vehicle_to_emissions_passed,
            issue_plate,
            make_plate_issuer_headers,
            make_tax_assessor_headers,
            mark_paid,
            verify_vin,
        )
        vehicle = create_vehicle()
        t_app = create_transfer_application(
            owner["id"], vehicle["id"],
            application_type="INITIAL_REGISTRATION",
        )
        verify_vin(vehicle["id"], t_app["id"])
        drive_vehicle_to_emissions_passed(vehicle["id"])
        assess_fees(t_app["id"], make_tax_assessor_headers("tax-op-rein-cut-001"))
        mark_paid(owner["id"], t_app["id"])
        issued = issue_plate(
            t_app["id"], plate_number="REIN01",
            headers=make_plate_issuer_headers("plate-op-rein-cut-001"),
        )
        plate_id = issued["plate_id"]
        # Suspend it (manually, so reinstate is the next action).
        suspend_plate(plate_id)
        # Advance clock past the REAL ID enforcement cutoff
        # 2027-05-07T00:00:00Z.
        advance_clock_to(parse_iso(REAL_ID_ENFORCEMENT_INSTANT_ISO))
        # Revoke the owner's REAL ID.
        revoke_real_id(real_id_app["id"])
        # Attempt reinstate — should be blocked by REAL ID revocation.
        resp = api.reinstate_plate(
            plate_id, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_REAL_ID_REVOKED.value)


class TestSurrender:

    def test_surrender_active_plate(self, api):
        """PRD §3.9: "A surrender call carries surrender_reason ... and
        may be issued from either ACTIVE or SUSPENDED. Both source
        states carry equal weight — both lead to SURRENDERED with
        surrender_reason recorded on the plate."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-surr-001",
            plate_issuer_operator_id="plate-op-surr-001",
        )
        plate_id = base["application"]["plate_id"]
        surrendered = surrender_plate(plate_id, surrender_reason="OWNER_REQUEST")
        assert surrendered["status"] == "SURRENDERED"
        assert surrendered["surrender_reason"] == "OWNER_REQUEST"

    def test_surrender_from_suspended(self, api):
        """PRD §3.9: "may be issued from either ACTIVE or SUSPENDED.
        Both source states carry equal weight."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-surr-002",
            plate_issuer_operator_id="plate-op-surr-002",
        )
        plate_id = base["application"]["plate_id"]
        suspend_plate(plate_id)
        surrendered = surrender_plate(plate_id, surrender_reason="OWNER_REQUEST")
        assert surrendered["status"] == "SURRENDERED"


class TestRealIDRevocationCascade:

    def test_revoke_suspends_active_plate(self, api):
        """PRD §3.10: "every ACTIVE plate on every vehicle whose
        currently-active Title.owner_id is this owner is suspended with
        suspended_at stamped."
        """
        # Build a completion flow where the owner is `owner` (capture
        # the REAL ID app id so we can revoke it).
        owner = create_owner(date_of_birth=date_for_age(30))
        real_id_app = approve_owner_to_real_id(owner["id"])
        from test_helpers import (
            assess_fees,
            create_transfer_application,
            create_vehicle,
            drive_vehicle_to_emissions_passed,
            issue_plate,
            make_plate_issuer_headers,
            make_tax_assessor_headers,
            mark_paid,
            verify_vin,
        )
        vehicle = create_vehicle()
        t_app = create_transfer_application(
            owner["id"], vehicle["id"],
            application_type="INITIAL_REGISTRATION",
        )
        verify_vin(vehicle["id"], t_app["id"])
        drive_vehicle_to_emissions_passed(vehicle["id"])
        assess_fees(t_app["id"], make_tax_assessor_headers("tax-op-rev-001"))
        mark_paid(owner["id"], t_app["id"])
        issued = issue_plate(
            t_app["id"], plate_number="REVC01",
            headers=make_plate_issuer_headers("plate-op-rev-001"),
        )
        plate_id = issued["plate_id"]
        # Revoke REAL ID — plate should be SUSPENDED.
        revoke_real_id(real_id_app["id"])
        plate_after = get_plate(plate_id)
        assert plate_after["status"] == "SUSPENDED"
        assert plate_after["suspended_at"] is not None
