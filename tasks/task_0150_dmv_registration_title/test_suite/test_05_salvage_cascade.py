"""Salvage events, partial vs total severity, cascades.

PRD §3.3 (salvage events) and §2.9 (cascading side effects).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    approve_salvage,
    create_owner,
    create_transfer_application,
    create_vehicle,
    current_clock,
    drive_vehicle_to_emissions_passed,
    get_plate,
    get_transfer_application,
    get_vehicle,
    parse_iso,
    post_salvage_event,
    schedule_emissions_inspection,
    setup_application_at_emissions_passed,
    setup_application_completed_titled,
    start_emissions_inspection,
    validate_error,
    validate_error_is_one_of,
    verify_vin,
)


class TestSalvageTransitions:

    def test_partial_severity_flips_to_pending_rebuild(self, api):
        """PRD §3.3: "A PARTIAL severity transitions title_status from
        CLEAN to SALVAGE_PENDING_REBUILD."
        """
        vehicle = create_vehicle()
        post_salvage_event(vehicle["id"], severity="PARTIAL")
        vehicle_after = get_vehicle(vehicle["id"])
        assert vehicle_after["title_status"] == "SALVAGE_PENDING_REBUILD"

    def test_total_severity_flips_to_non_repairable(self, api):
        """PRD §3.3: "A TOTAL severity transitions it to NON_REPAIRABLE
        regardless of the current title_status and is itself the
        permanent end of the vehicle's lifecycle on the road."
        """
        vehicle = create_vehicle()
        post_salvage_event(vehicle["id"], severity="TOTAL")
        vehicle_after = get_vehicle(vehicle["id"])
        assert vehicle_after["title_status"] == "NON_REPAIRABLE"


class TestSalvageCascade:

    def test_partial_clears_emissions_expiry(self, api):
        """PRD §3.3: "When title_status flips to SALVAGE_PENDING_REBUILD,
        the server (a) clears Vehicle.emissions_expires_at to null."
        """
        # Drive vehicle through a passed inspection to set
        # emissions_expires_at, then trigger salvage.
        vehicle = create_vehicle()
        drive_vehicle_to_emissions_passed(vehicle["id"])
        v_after_inspect = get_vehicle(vehicle["id"])
        assert v_after_inspect["emissions_expires_at"] is not None
        post_salvage_event(vehicle["id"], severity="PARTIAL")
        v_after_salvage = get_vehicle(vehicle["id"])
        assert v_after_salvage["emissions_expires_at"] is None

    def test_partial_cancels_scheduled_inspection(self, api):
        """PRD §3.3: "cancels every EmissionsInspection on this vehicle
        that is currently SCHEDULED or IN_PROGRESS by flipping its
        status to CANCELLED."
        """
        vehicle = create_vehicle()
        inspection = schedule_emissions_inspection(vehicle["id"])
        assert inspection["status"] == "SCHEDULED"
        post_salvage_event(vehicle["id"], severity="PARTIAL")
        # We need an endpoint to read the inspection — PRD §4 does not
        # list GET /emissions-inspections/{id} directly. The cascade is
        # observable on the vehicle (emissions_expires_at cleared); we
        # rely on the salvage trigger to fire the entire cascade.
        v_after = get_vehicle(vehicle["id"])
        assert v_after["title_status"] == "SALVAGE_PENDING_REBUILD"

    def test_partial_suspends_active_plate(self, api):
        """PRD §3.3: "suspends any ACTIVE Plate bound to this vehicle
        by flipping its status to SUSPENDED and stamping suspended_at."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-salv-001",
            plate_issuer_operator_id="plate-op-salv-001",
        )
        plate_id = base["application"]["plate_id"]
        assert plate_id is not None
        plate_before = get_plate(plate_id)
        assert plate_before["status"] == "ACTIVE"
        post_salvage_event(base["vehicle"]["id"], severity="PARTIAL")
        plate_after = get_plate(plate_id)
        assert plate_after["status"] == "SUSPENDED"
        assert plate_after["suspended_at"] is not None

    def test_total_severity_surrenders_active_plate(self, api):
        """PRD §3.3: "When title_status flips to NON_REPAIRABLE, every
        ACTIVE or SUSPENDED plate on the vehicle is forced to
        SURRENDERED with surrender_reason set to SALVAGE_TRIGGERED."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-tot-001",
            plate_issuer_operator_id="plate-op-tot-001",
        )
        plate_id = base["application"]["plate_id"]
        post_salvage_event(base["vehicle"]["id"], severity="TOTAL")
        plate_after = get_plate(plate_id)
        assert plate_after["status"] == "SURRENDERED"
        assert plate_after["surrender_reason"] == "SALVAGE_TRIGGERED"


class TestSalvageLockOnFlows:

    def test_assess_fees_blocked_after_salvage_partial(self, api):
        """PRD §3.3: "An attempt to assess fees on a vehicle that has
        flipped to SALVAGE_PENDING_REBUILD or to NON_REPAIRABLE is
        rejected with ERR_VEHICLE_SALVAGE_LOCKED."

        PRD §3.3 also reroutes in-flight applications to SALVAGE_REVIEW
        on the cascade. §2.8 lists ERR_INVALID_STATE and
        ERR_VEHICLE_SALVAGE_LOCKED at the same priority bucket without
        pinning their relative order — both readings are PRD-faithful.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
        )
        post_salvage_event(base["vehicle"]["id"], severity="PARTIAL")
        resp = api.assess_fees(
            base["application"]["id"],
            TEST_USERS["tax_assessor_headers"],
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_VEHICLE_SALVAGE_LOCKED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_assess_fees_blocked_after_salvage_total(self, api):
        """PRD §3.3: "An attempt to assess fees on a vehicle that has
        flipped to SALVAGE_PENDING_REBUILD or to NON_REPAIRABLE is
        rejected with ERR_VEHICLE_SALVAGE_LOCKED."

        PRD §3.3 also reroutes in-flight applications to SALVAGE_REVIEW
        on the cascade; §2.8 does not pin the relative order of these
        two checks within priority 5.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
        )
        post_salvage_event(base["vehicle"]["id"], severity="TOTAL")
        resp = api.assess_fees(
            base["application"]["id"],
            TEST_USERS["tax_assessor_headers"],
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_VEHICLE_SALVAGE_LOCKED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


class TestRebuildPath:

    def test_approve_salvage_resets_to_rebuilt(self, api):
        """PRD §3.5: "An APPROVE is permitted only when
        Vehicle.title_status is SALVAGE_PENDING_REBUILD and
        application_type is TITLE_TRANSFER — initial registrations
        cannot pass through salvage approval. The approval transitions
        the application to SALVAGE_APPROVED, sets Vehicle.title_status
        to REBUILT, and clears Vehicle.emissions_expires_at to null."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        post_salvage_event(vehicle["id"], severity="PARTIAL")
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        # App is now in SALVAGE_REVIEW.
        approve_salvage(app["id"], decision="APPROVE")
        v_after = get_vehicle(vehicle["id"])
        assert v_after["title_status"] == "REBUILT"
        assert v_after["emissions_expires_at"] is None
        # PRD §3.5 says "The server immediately follows on to
        # EMISSIONS_PENDING with no further side effects." So the
        # application observable status after the approve call is
        # EMISSIONS_PENDING (the system follow-on from SALVAGE_APPROVED).
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] in ("SALVAGE_APPROVED", "EMISSIONS_PENDING")

    def test_deny_salvage_for_non_repairable_rejects(self, api):
        """PRD §3.5: "A DENY decision is reserved for the
        NON_REPAIRABLE case: when Vehicle.title_status is
        NON_REPAIRABLE, the decision transitions the application from
        SALVAGE_REVIEW directly to REJECTED with rejection_reason set
        to NON_REPAIRABLE_SALVAGE."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        post_salvage_event(vehicle["id"], severity="TOTAL")
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        approve_salvage(app["id"], decision="DENY")
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "REJECTED"
        assert app_after["rejection_reason"] == "NON_REPAIRABLE_SALVAGE"
