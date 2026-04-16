"""Tests for VaccinationRecord creation and vaccination_compliant derivation.

Covers: PRD Section 3.2, Table 1 (VaccinationRecord), Table 3 (vaccination_compliance),
Table 4 priority 23.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_vaccination_record,
    create_vaccination_record_payload, create_animal_payload,
    create_shelter, create_animal_intake,
    future_date, past_date, iso_now_offset,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]
_vet = TEST_USERS["vet_headers"]


class TestVaccinationRecordCreation:
    """PRD 3.2: Veterinarian creates vaccination records."""

    def test_create_vaccination_success(self):
        """Valid record created with veterinarian_id captured from caller."""
        animal = create_animal_intake()
        payload = create_vaccination_record_payload(animal["id"], "RABIES")
        resp = api_client.create_vaccination_record(payload, _vet)
        data = validate_success(resp, 201)
        assert_vaccination_record(data)
        assert data["animal_id"] == animal["id"]
        assert data["vaccine_name"] == "RABIES"
        assert data["is_currently_valid"] is True
        assert data["veterinarian_id"]  # Server-side from X-User-ID

    def test_create_vaccination_animal_not_found(self):
        """FK to non-existent animal returns ERR_ANIMAL_NOT_FOUND."""
        payload = create_vaccination_record_payload(NON_EXISTENT_UUID, "RABIES")
        resp = api_client.create_vaccination_record(payload, _vet)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    def test_expiry_date_must_exceed_administered(self):
        """expiry_date <= administered_date returns ERR_INVALID_DATES."""
        animal = create_animal_intake()
        payload = create_vaccination_record_payload(animal["id"], "RABIES")
        # Set expiry == administered
        payload["expiry_date"] = payload["administered_date"]
        resp = api_client.create_vaccination_record(payload, _vet)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATES)

    def test_administered_date_in_future_rejected(self):
        """administered_date in the future rejected with ERR_INVALID_DATES."""
        animal = create_animal_intake()
        payload = create_vaccination_record_payload(animal["id"], "RABIES")
        payload["administered_date"] = future_date(days=1)
        payload["expiry_date"] = future_date(days=365)
        resp = api_client.create_vaccination_record(payload, _vet)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATES)

    def test_invalid_vaccine_name(self):
        """vaccine_name outside enum returns ERR_INVALID_REQUEST."""
        animal = create_animal_intake()
        payload = create_vaccination_record_payload(animal["id"], "RABIES")
        payload["vaccine_name"] = "UNKNOWN_VACCINE"
        resp = api_client.create_vaccination_record(payload, _vet)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_vaccination_record(self):
        """GET /vaccination-records/:id returns the record."""
        animal = create_animal_intake()
        rec = get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _vet
        ))
        resp = api_client.get_vaccination_record(rec["id"], _vet)
        data = validate_success(resp)
        assert data["id"] == rec["id"]

    def test_get_vaccination_record_not_found(self):
        resp = api_client.get_vaccination_record(NON_EXISTENT_UUID, _vet)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_RECORD_NOT_FOUND)

    def test_list_vaccination_records(self):
        animal = create_animal_intake()
        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _vet
        ))
        resp = api_client.list_vaccination_records(_vet)
        validate_success(resp)


class TestVaccinationComplianceDog:
    """PRD 3.2 + Table 3: vaccination_compliance rule for DOG (adoption variant)."""

    def test_dog_needs_rabies_and_dhpp(self):
        """DOG adoption-compliance requires RABIES AND DHPP."""
        animal = create_animal_intake(species="DOG")
        # Only RABIES
        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["vaccination_compliant"] is False

        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "DHPP"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["vaccination_compliant"] is True


class TestVaccinationComplianceCat:
    def test_cat_needs_rabies_and_fvrcp(self):
        """CAT needs RABIES AND FVRCP."""
        animal = create_animal_intake(species="CAT")
        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["vaccination_compliant"] is False
        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "FVRCP"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["vaccination_compliant"] is True


class TestVaccinationComplianceRabbit:
    def test_rabbit_needs_rhdv(self):
        """RABBIT requires only RHDV."""
        animal = create_animal_intake(species="RABBIT")
        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RHDV"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["vaccination_compliant"] is True


class TestVaccinationComplianceBirdOther:
    def test_bird_auto_compliant(self):
        """BIRD has no required vaccines; vaccination_compliant is True at intake."""
        animal = create_animal_intake(species="BIRD")
        assert animal["vaccination_compliant"] is True

    def test_other_auto_compliant(self):
        """OTHER species has no required vaccines."""
        animal = create_animal_intake(species="OTHER")
        assert animal["vaccination_compliant"] is True


class TestVaccinationExpiryValidity:
    def test_is_currently_valid_true_for_future_expiry(self):
        animal = create_animal_intake()
        rec = get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES",
                                               expiry_days_from_now=30), _vet
        ))
        assert rec["is_currently_valid"] is True
