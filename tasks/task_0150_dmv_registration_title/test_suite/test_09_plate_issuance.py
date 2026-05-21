"""Plate issuance gates, segregation of duties, plate-number uniqueness,
completion side effects.

PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    assert_plate,
    create_owner,
    create_transfer_application,
    create_vehicle,
    current_clock,
    drive_vehicle_to_emissions_passed,
    get_plate,
    get_transfer_application,
    get_vehicle,
    issue_plate,
    issue_plate_payload,
    make_plate_issuer_headers,
    make_tax_assessor_headers,
    mark_paid,
    parse_iso,
    random_plate_number,
    setup_application_at_tax_assessed,
    setup_application_completed_titled,
    setup_owner_with_real_id_approved,
    validate_error,
    validate_success,
    verify_vin,
)


class TestPlateIssuanceSuccess:

    def test_issue_plate_basic_success(self, api):
        """PRD §3.8: "The successful issuance creates a new Plate row
        whose status lands at ACTIVE after the system's immediate
        follow-on from ISSUED to ACTIVE, stamps activated_at to the
        current time."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-iss-001",
            plate_issuer_operator_id="plate-op-iss-001",
        )
        plate_id = base["application"]["plate_id"]
        plate = get_plate(plate_id)
        assert_plate(plate)
        assert plate["status"] == "ACTIVE"
        assert plate["activated_at"] is not None

    def test_completed_application_status_chain(self, api):
        """PRD §3.8: "transitions the application's status from
        TAX_ASSESSED to PLATE_ISSUED, and the system follows on from
        PLATE_ISSUED to COMPLETED in the same call."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-chain-001",
            plate_issuer_operator_id="plate-op-chain-001",
        )
        assert base["application"]["status"] == "COMPLETED"


class TestPlateIssuanceGates:

    def test_unpaid_application_blocked(self, api):
        """PRD §3.8: "paid_at is not null (otherwise
        ERR_PAYMENT_REQUIRED)."
        """
        base = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("tax-op-pay-001"),
        )
        # Skip mark_paid.
        resp = api.issue_plate(
            base["application"]["id"],
            issue_plate_payload(plate_number="ABC123"),
            make_plate_issuer_headers("plate-op-pay-001"),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_REQUIRED.value)

    def test_segregation_of_duties_same_user_blocked(self, api):
        """PRD §3.8: "the X-User-ID of this PlateIssuer call differs
        from the X-User-ID that originally ran fee assessment on this
        same application (otherwise ERR_SEGREGATION_OF_DUTIES)."

        Claim: assess-fees and issue-plate run under SAME X-User-ID →
        ERR_SEGREGATION_OF_DUTIES.
        """
        # Assess fees as operator "same-op-sod-001" wearing TaxAssessor.
        base = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("same-op-sod-001"),
        )
        mark_paid(base["owner"]["id"], base["application"]["id"])
        # Now issue plate as SAME operator id, role PlateIssuer.
        resp = api.issue_plate(
            base["application"]["id"],
            issue_plate_payload(plate_number=random_plate_number(6)),
            make_plate_issuer_headers("same-op-sod-001"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_plate_number_taken_blocked(self, api):
        """PRD §3.8: "the supplied plate_number is unique among Plate
        rows whose status is in the set ISSUED, ACTIVE, or SUSPENDED
        (a duplicate yields ERR_PLATE_NUMBER_TAKEN)."
        """
        plate_no = random_plate_number(6)
        first = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-num-A",
            plate_issuer_operator_id="plate-op-num-A",
            plate_number=plate_no,
        )
        assert first["application"]["status"] == "COMPLETED"
        # Second application against a different vehicle/owner; try to
        # claim the same plate_number.
        second_base = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("tax-op-num-B"),
        )
        mark_paid(second_base["owner"]["id"], second_base["application"]["id"])
        resp = api.issue_plate(
            second_base["application"]["id"],
            issue_plate_payload(plate_number=plate_no),
            make_plate_issuer_headers("plate-op-num-B"),
        )
        validate_error(resp, ApiErrorId.ERR_PLATE_NUMBER_TAKEN.value)

    def test_plate_number_pattern_invalid_rejected(self, api):
        """PRD §3.8: "plate_number must match the pattern of 2 to 8
        characters of uppercase A-Z or digit 0-9."

        Claim: plate_number with lowercase letters → ERR_VALIDATION.
        """
        base = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("tax-op-bad-001"),
        )
        mark_paid(base["owner"]["id"], base["application"]["id"])
        resp = api.issue_plate(
            base["application"]["id"],
            {"plate_number": "abc"},  # lowercase
            make_plate_issuer_headers("plate-op-bad-001"),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_plate_number_too_short_rejected(self, api):
        """PRD §3.8: "2 to 8 characters."

        Claim: 1-char plate_number → ERR_VALIDATION.
        """
        base = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("tax-op-len-001"),
        )
        mark_paid(base["owner"]["id"], base["application"]["id"])
        resp = api.issue_plate(
            base["application"]["id"],
            {"plate_number": "A"},
            make_plate_issuer_headers("plate-op-len-001"),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestCompletionSideEffects:

    def test_new_title_created_for_applicant_owner(self, api):
        """PRD §3.8: "The completion side effects create a brand-new
        Title row for the application's applicant_owner_id ..."
        PRD §3.8: "Vehicle.current_title_id is updated to point at the
        new title row."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-title-001",
            plate_issuer_operator_id="plate-op-title-001",
        )
        v_after = get_vehicle(base["vehicle"]["id"])
        assert v_after["current_title_id"] is not None

    def test_title_transfer_surrenders_prior_plate(self, api):
        """PRD §3.8: "If application_type is TITLE_TRANSFER and a prior
        plate existed on the vehicle, that prior plate is surrendered
        with its status flipping to SURRENDERED and surrender_reason set
        to TRANSFER_COMPLETE."
        """
        # Step 1: initial registration completes — vehicle V has Plate
        # P_old ACTIVE and Title T_old.
        first = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-trans-001",
            plate_issuer_operator_id="plate-op-trans-001",
        )
        vehicle = get_vehicle(first["vehicle"]["id"])
        old_plate_id = first["application"]["plate_id"]
        # Step 2: a NEW owner triggers a TITLE_TRANSFER on the same
        # vehicle.
        new_owner = setup_owner_with_real_id_approved(residency_state="CA")
        new_app = create_transfer_application(
            new_owner["id"], vehicle["id"],
            application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], new_app["id"])
        drive_vehicle_to_emissions_passed(vehicle["id"], odometer_reading=20000)
        # Assess and issue with distinct operator ids
        ta_headers = make_tax_assessor_headers("tax-op-trans-002")
        pi_headers = make_plate_issuer_headers("plate-op-trans-002")
        api.assess_fees(new_app["id"], ta_headers)
        mark_paid(new_owner["id"], new_app["id"])
        api.issue_plate(
            new_app["id"],
            issue_plate_payload(plate_number=random_plate_number(7)),
            pi_headers,
        )
        # Old plate should now be SURRENDERED with reason
        # TRANSFER_COMPLETE.
        old_plate = get_plate(old_plate_id)
        assert old_plate["status"] == "SURRENDERED"
        assert old_plate["surrender_reason"] == "TRANSFER_COMPLETE"
