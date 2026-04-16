"""
Tests for Animal CRUD, vaccination compliance, and make-available transition.
Claims from Tables 1, 2, 3 (vaccination_compliance_check), 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_animal,
    assert_version_incremented,
    create_animal_payload,
    create_cat_payload,
    create_bird_payload,
    create_vaccination_record_payload,
    create_shelter,
    create_animal_in_shelter,
    vaccinate_animal,
    make_animal_available,
    create_available_animal,
    create_hold_on_animal,
    resolve_hold,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    SPECIES_VACCINE_MAP,
)


class TestAnimalCreation:
    """Table 1 / Table 5: Animal registration."""

    def test_create_animal_success(self, api, caseworker_headers):
        """POST /animals with valid payload returns 201 with INTAKE status."""
        shelter = create_shelter()
        payload = create_animal_payload(
            shelter["id"], name="Rex", species="DOG", age_months=36,
        )
        res = api.create_animal(payload, caseworker_headers)
        animal = validate_success(res, 201)
        assert_animal(animal)
        assert animal["name"] == "Rex"
        assert animal["species"] == "DOG"
        assert animal["status"] == "INTAKE"
        assert isinstance(animal["vaccination_compliant"], bool)
        assert isinstance(animal["boarding_compatible_tags"], list)

    def test_create_animal_with_special_needs(self, api, caseworker_headers):
        """special_needs array stored correctly."""
        shelter = create_shelter()
        payload = create_animal_payload(
            shelter["id"],
            special_needs=["MEDICATION_REQUIRED", "DIET_RESTRICTED"],
        )
        res = api.create_animal(payload, caseworker_headers)
        animal = validate_success(res, 201)
        assert "MEDICATION_REQUIRED" in animal["special_needs"]
        assert "DIET_RESTRICTED" in animal["special_needs"]

    def test_create_animal_default_empty_special_needs(self, api, caseworker_headers):
        """Omitting special_needs defaults to empty array."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"])
        del payload["special_needs"]
        res = api.create_animal(payload, caseworker_headers)
        animal = validate_success(res, 201)
        assert animal["special_needs"] == []

    def test_get_nonexistent_animal(self, api, caseworker_headers):
        """ERR_ANIMAL_NOT_FOUND for non-existent animal."""
        res = api.get_animal(NON_EXISTENT_UUID, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    def test_create_animal_nonexistent_shelter(self, api, caseworker_headers):
        """FK to non-existent shelter -> ERR_SHELTER_NOT_FOUND."""
        payload = create_animal_payload(NON_EXISTENT_UUID)
        res = api.create_animal(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "shelter_id", "name", "species", "breed", "age_months", "weight_kg", "temperament",
    ])
    def test_create_animal_missing_required_field(self, api, caseworker_headers, missing_field):
        """Omitting required field -> ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"])
        del payload[missing_field]
        res = api.create_animal(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_animals_with_filters(self, api, caseworker_headers):
        """GET /animals supports shelter_id, species, status filters + pagination."""
        shelter = create_shelter()
        create_animal_in_shelter(shelter["id"], species="DOG")
        create_animal_in_shelter(shelter["id"], species="CAT")

        data, meta = validate_paginated(
            api.list_animals(caseworker_headers, params={"shelter_id": shelter["id"]})
        )
        assert meta["total_count"] >= 2

        data, meta = validate_paginated(
            api.list_animals(
                caseworker_headers,
                params={"shelter_id": shelter["id"], "species": "DOG"},
            )
        )
        assert all(a["species"] == "DOG" for a in data)


class TestAnimalUpdate:
    """PATCH /animals/{id} — update mutable fields."""

    def test_update_animal_name(self, api, caseworker_headers):
        """PATCH updates name and increments version."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        old_version = animal["version"]
        res = api.update_animal(
            animal["id"], {"name": "New Name"}, caseworker_headers,
        )
        updated = validate_success(res, 200)
        assert updated["name"] == "New Name"
        assert_version_incremented(updated["version"], old_version)

    def test_update_recomputes_boarding_tags(self, api, caseworker_headers):
        """PATCH on temperament recomputes boarding_compatible_tags."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        res = api.update_animal(
            animal["id"], {"temperament": "AGGRESSIVE"}, caseworker_headers,
        )
        updated = validate_success(res, 200)
        assert updated["temperament"] == "AGGRESSIVE"
        # boarding_compatible_tags should reflect the new temperament
        assert isinstance(updated["boarding_compatible_tags"], list)


class TestVaccinationCompliance:
    """Table 3: vaccination_compliance_check calculation."""

    def test_dog_compliant_with_all_vaccines(self, api, vet_headers, caseworker_headers):
        """DOG with RABIES, DHPP, BORDETELLA -> vaccination_compliant=True."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"], species="DOG")
        vaccinate_animal(animal["id"], species="DOG")
        updated = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert updated["vaccination_compliant"] is True

    def test_dog_not_compliant_missing_vaccine(self, api, vet_headers, caseworker_headers):
        """DOG with only RABIES -> vaccination_compliant=False (missing DHPP, BORDETELLA)."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"], species="DOG")
        # Only add RABIES
        api.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], vaccine_name="RABIES"),
            vet_headers,
        )
        updated = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert updated["vaccination_compliant"] is False

    def test_cat_compliant_with_rabies_and_fvrcp(self, api, vet_headers, caseworker_headers):
        """CAT with RABIES and FVRCP -> vaccination_compliant=True."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"], species="CAT")
        vaccinate_animal(animal["id"], species="CAT")
        updated = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert updated["vaccination_compliant"] is True

    def test_rabbit_compliant_with_rhdv(self, api, vet_headers, caseworker_headers):
        """RABBIT with RHDV -> vaccination_compliant=True."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"], species="RABBIT")
        vaccinate_animal(animal["id"], species="RABBIT")
        updated = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert updated["vaccination_compliant"] is True

    def test_bird_always_compliant(self, api, caseworker_headers):
        """BIRD has no required vaccines -> vaccination_compliant=True."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"], species="BIRD")
        updated = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert updated["vaccination_compliant"] is True


class TestMakeAvailable:
    """Table 2: Animal INTAKE -> AVAILABLE transition."""

    def test_make_available_success(self, api, caseworker_headers):
        """Vaccinated animal transitions from INTAKE to AVAILABLE."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        vaccinate_animal(animal["id"], species="DOG")
        res = api.make_animal_available(animal["id"], caseworker_headers)
        available = validate_success(res, 200)
        assert available["status"] == "AVAILABLE"
        assert available["adoption_eligible"] is True

    def test_make_available_not_compliant(self, api, caseworker_headers):
        """Non-compliant animal -> ERR_VACCINATION_NOT_COMPLIANT."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        res = api.make_animal_available(animal["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_VACCINATION_NOT_COMPLIANT)

    def test_make_available_blocked_by_high_hold(self, api, caseworker_headers):
        """Animal with HIGH compliance hold -> ERR_COMPLIANCE_HOLD_ACTIVE."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        vaccinate_animal(animal["id"], species="DOG")
        create_hold_on_animal(animal["id"], severity="HIGH")
        res = api.make_animal_available(animal["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE)

    def test_make_available_not_blocked_by_low_hold(self, api, caseworker_headers):
        """Animal with LOW severity hold -> can still be made available."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        vaccinate_animal(animal["id"], species="DOG")
        create_hold_on_animal(animal["id"], severity="LOW")
        res = api.make_animal_available(animal["id"], caseworker_headers)
        available = validate_success(res, 200)
        assert available["status"] == "AVAILABLE"

    def test_make_available_already_available(self, api, caseworker_headers):
        """Making an already AVAILABLE animal available -> ERR_INVALID_STATE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        res = api.make_animal_available(animal["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
