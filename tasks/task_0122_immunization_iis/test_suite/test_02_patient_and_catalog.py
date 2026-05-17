"""Patient registration, vaccine product/lot catalog, provider org CRUD.

PRD §3.1 (Patient), §3.2 (VaccineProduct, VaccineLot, ProviderOrganization),
§2.4 (common fields), §2.7 (OCC).
"""
from __future__ import annotations


from test_helpers import (
    TEST_USERS,
    assert_patient,
    assert_provider_organization,
    assert_vaccine_lot,
    assert_vaccine_product,
    create_patient,
    create_patient_payload,
    create_provider_organization,
    create_provider_organization_payload,
    create_vaccine_lot,
    create_vaccine_lot_payload,
    create_vaccine_product,
    create_vaccine_product_payload,
    iso_anchor_offset,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 Patient
# ===========================================================================
class TestPatientRegistration:
    """PRD §3.1 Patient registration."""

    def test_create_patient_returns_active_status(self, api):
        """PRD §3.1: "Each patient carries a system-managed status
        that starts at ACTIVE."

        Claim: a newly registered Patient.status == 'ACTIVE'.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "ACTIVE", (
            f"PRD §3.1: new Patient.status must be 'ACTIVE', "
            f"got {data['status']!r}"
        )
        assert_patient(data)

    def test_create_patient_default_state_resident_true(self, api):
        """PRD §3.1: "state_resident (a boolean defaulting to true,
        indicating residency in the state operating this IIS)."

        Claim: when state_resident is omitted, the persisted value
        defaults to true.
        """
        payload = create_patient_payload()
        payload.pop("state_resident", None)
        res = api.create_patient(
            payload, TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["state_resident"] is True, (
            "PRD §3.1: state_resident defaults to true"
        )

    def test_create_patient_default_medical_exemption_false(self, api):
        """PRD §3.1: "The optional medical_exemption_on_file flag
        defaults to false."

        Claim: when medical_exemption_on_file is omitted, the persisted
        value is false.
        """
        payload = create_patient_payload()
        payload.pop("medical_exemption_on_file", None)
        res = api.create_patient(
            payload, TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["medical_exemption_on_file"] is False, (
            "PRD §3.1: medical_exemption_on_file defaults to false"
        )

    def test_create_patient_future_dob_rejected(self, api):
        """PRD §3.1: "date_of_birth (an ISO 8601 calendar date that must
        lie strictly in the past relative to the server's current time)."

        Claim: a future DOB returns ERR_VALIDATION.
        """
        future_dob = "2999-01-01"
        res = api.create_patient(
            create_patient_payload(date_of_birth=future_dob),
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_VALIDATION")

    def test_create_patient_first_name_too_long_rejected(self, api):
        """PRD §3.1: "first_name (1 to 80 characters)."

        Claim: first_name exceeding 80 chars returns ERR_VALIDATION.
        """
        res = api.create_patient(
            create_patient_payload(first_name="A" * 81),
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_VALIDATION")

    def test_create_patient_first_name_empty_rejected(self, api):
        """PRD §3.1: "first_name (1 to 80 characters)."

        Claim: empty first_name returns ERR_VALIDATION.
        """
        res = api.create_patient(
            create_patient_payload(first_name=""),
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_VALIDATION")

    def test_get_patient_round_trips(self, api):
        """PRD §3.1: "individual-patient reads are broader and
        available to all four roles."

        Claim: a GET on a created patient returns the same record.
        """
        p = create_patient(first_name="Alice", last_name="Wonder")
        res = api.get_patient(
            p["id"], TEST_USERS["school_registrar_headers"],
        )
        data = validate_success(res)
        assert data["id"] == p["id"]
        assert data["first_name"] == "Alice"
        assert data["last_name"] == "Wonder"


# ===========================================================================
# §3.2 VaccineProduct
# ===========================================================================
class TestVaccineProduct:

    def test_create_vaccine_product_initial_status_active(self, api):
        """PRD §3.2: "a system-managed status that begins at ACTIVE
        and may transition to DISCONTINUED."

        Claim: new VaccineProduct.status == 'ACTIVE'.
        """
        res = api.create_vaccine_product(
            create_vaccine_product_payload(),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert_vaccine_product(data)

    def test_create_vaccine_product_min_age_negative_rejected(self, api):
        """PRD §3.2: "an integer min_age_days (at least zero) marking
        the earliest age in days."

        Claim: min_age_days = -1 returns ERR_VALIDATION.
        """
        res = api.create_vaccine_product(
            create_vaccine_product_payload(min_age_days=-1),
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_VALIDATION")

    def test_create_vaccine_product_empty_antigens_rejected(self, api):
        """PRD §3.2: "an antigens array of one or more antigen
        identifiers."

        Claim: empty antigens array returns ERR_VALIDATION.
        """
        res = api.create_vaccine_product(
            create_vaccine_product_payload(antigens=[]),
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_VALIDATION")

    def test_create_vaccine_product_null_max_age_accepted(self, api):
        """PRD §3.2: "an integer max_age_days marking the latest such
        age (a null value indicates no upper bound)."

        Claim: max_age_days = null is accepted and persisted as null.
        """
        res = api.create_vaccine_product(
            create_vaccine_product_payload(max_age_days=None),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["max_age_days"] is None


# ===========================================================================
# §3.2 VaccineLot
# ===========================================================================
class TestVaccineLot:

    def test_create_vaccine_lot_initial_status_available(self, api):
        """PRD §3.2: "The lot's status begins at AVAILABLE."

        Claim: new VaccineLot.status == 'AVAILABLE'.
        """
        provider_org = create_provider_organization()
        product = create_vaccine_product()
        res = api.create_vaccine_lot(
            create_vaccine_lot_payload(
                product["id"], provider_org["id"], doses_on_hand=5,
            ),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "AVAILABLE"
        assert data["doses_on_hand"] == 5
        assert_vaccine_lot(data)

# ===========================================================================
# §3.2 ProviderOrganization
# ===========================================================================
class TestProviderOrganization:

    def test_create_provider_org_initial_score_100_and_active(self, api):
        """PRD §3.2: "The system maintains reporting_compliance_score
        (a derived number on the closed interval from zero to 100,
        defaulting to 100.00) and a status of either ACTIVE or
        SUSPENDED."

        Claim: new ProviderOrganization has
        reporting_compliance_score == 100.00 and status == 'ACTIVE'.
        """
        res = api.create_provider_organization(
            create_provider_organization_payload(),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert float(data["reporting_compliance_score"]) == 100.00
        assert_provider_organization(data)

    def test_create_provider_org_bad_npi_rejected(self, api):
        """PRD §3.2: "a 10-digit npi."

        Claim: a 9-digit NPI returns ERR_VALIDATION.
        """
        res = api.create_provider_organization(
            create_provider_organization_payload(npi="123456789"),
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_VALIDATION")
