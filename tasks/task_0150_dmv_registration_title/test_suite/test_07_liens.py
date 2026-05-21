"""Lien creation, release, references; effect on transfer flow.

PRD §3.6.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_lien_record,
    create_lien_on_title,
    create_lien_record_payload,
    create_owner,
    get_vehicle,
    release_lien_payload,
    release_lien_record,
    setup_application_at_emissions_passed,
    setup_application_completed_titled,
    validate_error,
    validate_success,
)


class TestLienCreation:

    def test_create_lien_initial_state(self, api):
        """PRD §3.6: "The LienRecord starts with status set to ACTIVE,
        released_at null, and release_reference null. Creating the
        lien also flips Vehicle.lien_status to ACTIVE."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-lien-001",
            plate_issuer_operator_id="plate-op-lien-001",
        )
        # The completed application produced a Title; the vehicle's
        # current_title_id points at it.
        vehicle = get_vehicle(base["vehicle"]["id"])
        title_id = vehicle["current_title_id"]
        assert title_id is not None
        lien = create_lien_on_title(
            title_id, lienholder_name="First National Bank",
            principal_amount=12000.00,
        )
        assert_lien_record(lien)
        assert lien["status"] == "ACTIVE"
        assert lien["released_at"] is None
        v_after = get_vehicle(vehicle["id"])
        assert v_after["lien_status"] == "ACTIVE"


class TestLienRelease:

    def test_release_lien_with_reference_succeeds(self, api):
        """PRD §3.6: "A successful release transitions the lien's
        status from ACTIVE to RELEASED, stamps released_at to the
        current time, and — if no other ACTIVE LienRecord remains on
        the same title — flips Vehicle.lien_status to RELEASED."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-rel-001",
            plate_issuer_operator_id="plate-op-rel-001",
        )
        vehicle = get_vehicle(base["vehicle"]["id"])
        title_id = vehicle["current_title_id"]
        lien = create_lien_on_title(title_id)
        released = release_lien_record(
            lien["id"], release_reference="REL-12345",
        )
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None
        v_after = get_vehicle(vehicle["id"])
        assert v_after["lien_status"] == "RELEASED"

    def test_release_lien_empty_reference_rejected(self, api):
        """PRD §3.6: "An empty or missing release_reference is rejected
        with ERR_RELEASE_REFERENCE_REQUIRED."

        Claim: empty string release_reference → ERR_RELEASE_REFERENCE_REQUIRED.
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-rel-002",
            plate_issuer_operator_id="plate-op-rel-002",
        )
        vehicle = get_vehicle(base["vehicle"]["id"])
        title_id = vehicle["current_title_id"]
        lien = create_lien_on_title(title_id)
        resp = api.release_lien(
            lien["id"],
            release_lien_payload(release_reference=""),
            TEST_USERS["lien_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_REFERENCE_REQUIRED.value)

    def test_release_lien_missing_reference_rejected(self, api):
        """PRD §3.6: "An empty or missing release_reference is rejected
        with ERR_RELEASE_REFERENCE_REQUIRED."

        Claim: omitted release_reference field → ERR_RELEASE_REFERENCE_REQUIRED.
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-rel-003",
            plate_issuer_operator_id="plate-op-rel-003",
        )
        vehicle = get_vehicle(base["vehicle"]["id"])
        title_id = vehicle["current_title_id"]
        lien = create_lien_on_title(title_id)
        resp = api.release_lien(
            lien["id"], {},  # no release_reference
            TEST_USERS["lien_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_REFERENCE_REQUIRED.value)

    def test_release_with_version_conflict(self, api):
        """PRD §2.5: "When version is present, the server compares it
        against the target resource's current version; if they differ,
        the call is rejected with ERR_VERSION_CONFLICT at HTTP 409."
        PRD §3.6: "The release endpoint accepts an optional version
        field for optimistic concurrency control."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-ver-001",
            plate_issuer_operator_id="plate-op-ver-001",
        )
        vehicle = get_vehicle(base["vehicle"]["id"])
        lien = create_lien_on_title(vehicle["current_title_id"])
        # Pass a wrong version.
        wrong_version = lien["version"] + 99
        resp = api.release_lien(
            lien["id"],
            release_lien_payload(
                release_reference="REL-VER",
                version=wrong_version,
            ),
            TEST_USERS["lien_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestLienBlocksTransfer:

    def test_active_lien_blocks_assess_fees(self, api):
        """PRD §3.6: "While Vehicle.lien_status is ACTIVE, no
        TransferApplication on that vehicle may progress past
        EMISSIONS_PASSED into TAX_ASSESSED — the assess-fees call is
        rejected with ERR_LIEN_ACTIVE."

        Setup: completed prior application has a Title; place a lien
        on it. Then a new application reaching EMISSIONS_PASSED on the
        same vehicle is blocked at assess-fees.
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-lien-blk-001",
            plate_issuer_operator_id="plate-op-lien-blk-001",
        )
        vehicle = get_vehicle(base["vehicle"]["id"])
        title_id = vehicle["current_title_id"]
        create_lien_on_title(title_id)  # Vehicle.lien_status -> ACTIVE
        # Now stand up a second transfer application on the same
        # vehicle, drive it to EMISSIONS_PASSED, and try assess-fees.
        second_base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
        )
        # ^ that creates a new vehicle. Override: we instead drive a
        # new application against the LIEN-encumbered vehicle.
        # Build a fresh owner with approved REAL ID on the encumbered
        # vehicle:
        from test_helpers import (
            create_transfer_application,
            date_for_age,
            drive_vehicle_to_emissions_passed,
            setup_owner_with_real_id_approved,
            verify_vin,
        )
        new_owner = setup_owner_with_real_id_approved(
            residency_state="CA", age_years=30,
        )
        new_app = create_transfer_application(
            new_owner["id"], vehicle["id"],
            application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], new_app["id"])
        # Drive a fresh PASSED inspection on this vehicle so the
        # application advances to EMISSIONS_PASSED.
        drive_vehicle_to_emissions_passed(vehicle["id"], odometer_reading=20000)
        resp = api.assess_fees(
            new_app["id"], TEST_USERS["tax_assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LIEN_ACTIVE.value)
