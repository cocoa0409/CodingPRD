"""
Tests for VaccinationRecord CRUD and compliance recomputation.
Claims from Tables 1, 3, 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_vaccination_record,
    create_vaccination_record_payload,
    create_shelter,
    create_animal_in_shelter,
    vaccinate_animal,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.factories import _future_iso, _past_iso


class TestVaccinationRecordCreation:
    """Table 1 / Table 5: VaccinationRecord creation."""

    def test_create_vaccination_record_success(self, api, vet_headers):
        """POST /vaccination-records returns 201 with all fields."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        payload = create_vaccination_record_payload(animal["id"], vaccine_name="RABIES")
        res = api.create_vaccination_record(payload, vet_headers)
        record = validate_success(res, 201)
        assert_vaccination_record(record)
        assert record["vaccine_name"] == "RABIES"
        assert record["animal_id"] == animal["id"]
        assert record["is_valid"] is True

    def test_create_vaccination_record_nonexistent_animal(self, api, vet_headers):
        """FK to non-existent animal -> ERR_ANIMAL_NOT_FOUND."""
        payload = create_vaccination_record_payload(NON_EXISTENT_UUID)
        res = api.create_vaccination_record(payload, vet_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    def test_get_nonexistent_vaccination_record(self, api, vet_headers):
        """ERR_VACCINATION_RECORD_NOT_FOUND for non-existent record."""
        res = api.get_vaccination_record(NON_EXISTENT_UUID, vet_headers)
        validate_error(res, ApiErrorId.ERR_VACCINATION_RECORD_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "animal_id", "vaccine_name", "administered_date", "expiry_date",
        "batch_number", "veterinarian_name",
    ])
    def test_create_vaccination_record_missing_field(self, api, vet_headers, missing_field):
        """Omitting required field -> ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        payload = create_vaccination_record_payload(animal["id"])
        del payload[missing_field]
        res = api.create_vaccination_record(payload, vet_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_vaccination_records_by_animal(self, api, vet_headers):
        """GET /vaccination-records?animal_id= filters correctly."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        vaccinate_animal(animal["id"], species="DOG")

        data, meta = validate_paginated(
            api.list_vaccination_records(vet_headers, params={"animal_id": animal["id"]})
        )
        assert meta["total_count"] == 3  # RABIES, DHPP, BORDETELLA


class TestVaccinationComplianceRecomputation:
    """Table 3: Adding vaccination records recomputes animal.vaccination_compliant."""

    def test_compliance_recomputed_on_vaccination_add(self, api, vet_headers, caseworker_headers):
        """Adding final required vaccine flips vaccination_compliant to True."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"], species="DOG")

        # Initially not compliant
        animal_state = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_state["vaccination_compliant"] is False

        # Add RABIES
        api.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], vaccine_name="RABIES"),
            vet_headers,
        )
        # Add DHPP
        api.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], vaccine_name="DHPP"),
            vet_headers,
        )
        # Still not compliant (missing BORDETELLA)
        animal_state = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_state["vaccination_compliant"] is False

        # Add BORDETELLA -> now compliant
        api.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], vaccine_name="BORDETELLA"),
            vet_headers,
        )
        animal_state = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_state["vaccination_compliant"] is True

    def test_expired_vaccination_not_counted(self, api, vet_headers, caseworker_headers):
        """Vaccination record with past expiry_date -> is_valid=False and not counted."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"], species="RABBIT")
        payload = create_vaccination_record_payload(
            animal["id"],
            vaccine_name="RHDV",
            expiry_date=_past_iso(days=1),  # expired yesterday
        )
        res = api.create_vaccination_record(payload, vet_headers)
        record = validate_success(res, 201)
        assert record["is_valid"] is False

        animal_state = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_state["vaccination_compliant"] is False
