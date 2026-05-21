"""Owner creation / residency and Vehicle intake / VIN validation.

PRD §3.1 (owners), §3.2 (vehicles).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_owner,
    assert_vehicle,
    create_owner,
    create_owner_payload,
    create_vehicle,
    create_vehicle_payload,
    random_vin,
    validate_error,
    validate_success,
)


class TestOwnerCreation:

    def test_create_owner_resident_state_ca(self, api):
        """PRD §3.1: "the server computes is_resident by checking
        whether residency_state equals the jurisdiction code CA — the
        boolean is true if and only if the codes match."

        Claim: residency_state='CA' → is_resident == true.
        """
        resp = api.create_owner(
            create_owner_payload(residency_state="CA"),
            TEST_USERS["applicant_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_owner(data)
        assert data["is_resident"] is True

    def test_create_owner_non_resident_state(self, api):
        """PRD §3.1: "the boolean is true if and only if the codes
        match."

        Claim: residency_state='NV' → is_resident == false.
        """
        resp = api.create_owner(
            create_owner_payload(residency_state="NV"),
            TEST_USERS["applicant_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["is_resident"] is False

    def test_create_owner_initial_state(self, api):
        """PRD §3.1: "outstanding_holds_count starts at 0 ... The
        owner's real_id_status initializes to NOT_APPLIED, and the
        related fields real_id_score and real_id_expires_at initialize
        to null."

        Claim: new Owner has outstanding_holds_count=0,
        real_id_status=NOT_APPLIED, real_id_score=null,
        real_id_expires_at=null.
        """
        owner = create_owner()
        assert owner["outstanding_holds_count"] == 0
        assert owner["real_id_status"] == "NOT_APPLIED"
        assert owner["real_id_score"] is None
        assert owner["real_id_expires_at"] is None

    def test_create_owner_missing_full_name_rejected(self, api):
        """PRD §3.1: "full_name (1 to 100 characters)."

        Claim: empty full_name → ERR_VALIDATION.
        """
        resp = api.create_owner(
            create_owner_payload(full_name=""),
            TEST_USERS["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_create_owner_full_name_too_long_rejected(self, api):
        """PRD §3.1: "full_name (1 to 100 characters)."

        Claim: 101-character full_name → ERR_VALIDATION.
        """
        resp = api.create_owner(
            create_owner_payload(full_name="X" * 101),
            TEST_USERS["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestVehicleIntake:

    def test_create_vehicle_initial_state(self, api):
        """PRD §3.2: "New vehicles start with vin_verification_status
        set to UNVERIFIED and vin_verified_at set to null, title_status
        set to CLEAN, lien_status set to NONE, current_title_id and
        emissions_expires_at both null."
        """
        vehicle = create_vehicle()
        assert vehicle["vin_verification_status"] == "UNVERIFIED"
        assert vehicle["vin_verified_at"] is None
        assert vehicle["title_status"] == "CLEAN"
        assert vehicle["lien_status"] == "NONE"
        assert vehicle["current_title_id"] is None
        assert vehicle["emissions_expires_at"] is None
        assert_vehicle(vehicle)

    def test_create_vehicle_vin_must_be_17_chars(self, api):
        """PRD §3.2: "The vin must be 17 characters drawn from
        uppercase A through Z and digits 0 through 9, excluding the
        letters I, O, and Q."

        Claim: 16-character VIN → ERR_VALIDATION.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(vin="A" * 16),
            TEST_USERS["vin_verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("forbidden_char", ["I", "O", "Q"])
    def test_create_vehicle_vin_excludes_ioq(self, api, forbidden_char):
        """PRD §3.2: "excluding the letters I, O, and Q."

        Claim: VIN containing I/O/Q → ERR_VALIDATION.
        """
        # Build a 17-character VIN with the forbidden char at position 0.
        vin = forbidden_char + "A" * 16
        resp = api.create_vehicle(
            create_vehicle_payload(vin=vin),
            TEST_USERS["vin_verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_create_vehicle_vin_must_be_unique(self, api):
        """PRD §3.2: "is globally unique across the entire vehicle
        table."

        Claim: creating a second vehicle with the same VIN →
        ERR_VALIDATION.
        """
        vin = random_vin()
        first = api.create_vehicle(
            create_vehicle_payload(vin=vin),
            TEST_USERS["vin_verifier_headers"],
        )
        validate_success(first, expected_status=201)
        second = api.create_vehicle(
            create_vehicle_payload(vin=vin),
            TEST_USERS["vin_verifier_headers"],
        )
        # PRD doesn't pin a specific error_id for duplicate VIN; it falls
        # under priority 21 body conformance (regex/range). Accept either
        # ERR_VALIDATION or a non-2xx response.
        assert second.status_code >= 400
        body = second.json().get("data", {}) or {}
        assert body.get("error_id") == ApiErrorId.ERR_VALIDATION.value

    @pytest.mark.parametrize("year", [1899, 2101])
    def test_create_vehicle_model_year_range(self, api, year):
        """PRD §3.2: "model_year is a four-digit integer between 1900
        and 2100."

        Claim: out-of-range model_year → ERR_VALIDATION.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(model_year=year),
            TEST_USERS["vin_verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("weight", [199, 40001])
    def test_create_vehicle_curb_weight_range(self, api, weight):
        """PRD §3.2: "curb_weight_lbs is an integer between 200 and
        40000."

        Claim: out-of-range curb_weight_lbs → ERR_VALIDATION.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(curb_weight_lbs=weight),
            TEST_USERS["vin_verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_create_vehicle_unknown_fuel_type_rejected(self, api):
        """PRD §3.2: "fuel_type is one of GASOLINE, DIESEL, HYBRID, or
        ELECTRIC."

        Claim: unknown fuel_type → ERR_VALIDATION.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(fuel_type="STEAM"),
            TEST_USERS["vin_verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
