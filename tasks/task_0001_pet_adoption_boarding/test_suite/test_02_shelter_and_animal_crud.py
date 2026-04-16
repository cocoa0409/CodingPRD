"""Shelter and Animal CRUD — covers PRD §3.1 (intake) and §2.4 (OCC)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error,
    assert_shelter, assert_animal, assert_shelter_slot_invariant,
    create_shelter_payload, create_animal_payload,
    create_shelter, create_animal,
)


class TestShelterCreate:
    def test_create_shelter_succeeds(self):
        """PRD §3.1: "A ShelterAdmin opens operations by creating a shelter"."""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         TEST_USERS["shelter_admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert_shelter(data)

    def test_new_shelter_status_is_open(self):
        """PRD §3.1: "The new shelter is materialised with status set to OPEN"."""
        shelter = create_shelter()
        assert shelter["status"] == "OPEN"

    def test_new_shelter_reserved_slots_zero(self):
        """PRD §3.1: "its reserved_slots counter starts at zero"."""
        shelter = create_shelter()
        assert shelter["reserved_slots"] == 0

    def test_new_shelter_available_slots_equal_capacity(self):
        """PRD §3.1: "available_slots ... therefore equals the declared capacity"."""
        shelter = create_shelter(boarding_capacity=7)
        assert shelter["available_slots"] == 7

    def test_create_shelter_missing_name_rejected(self):
        """PRD §2.7: "request body well-formedness — ERR_INVALID_REQUEST"."""
        payload = create_shelter_payload()
        payload.pop("name")
        resp = api_client.create_shelter(payload, TEST_USERS["shelter_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_shelter_missing_boarding_capacity_rejected(self):
        """PRD §2.7: missing required field → ERR_INVALID_REQUEST."""
        payload = create_shelter_payload()
        payload.pop("boarding_capacity")
        resp = api_client.create_shelter(payload, TEST_USERS["shelter_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestShelterRead:
    def test_get_shelter(self):
        """PRD §4: GET /shelters/{sid} — `Any` role, returns the shelter."""
        shelter = create_shelter()
        resp = api_client.get_shelter(shelter["id"], TEST_USERS["adopter_headers"])
        data = validate_success(resp)
        assert data["id"] == shelter["id"]
        assert_shelter(data)

    def test_get_shelter_not_found(self):
        """PRD §2.5: "ERR_SHELTER_NOT_FOUND ... reserved for their respective segments"."""
        resp = api_client.get_shelter(NON_EXISTENT_UUID, TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND.value)


class TestAnimalCreate:
    def test_create_animal_sets_status_available(self):
        """PRD §3.1: "initialises status to AVAILABLE"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        assert animal["status"] == "AVAILABLE"
        assert_animal(animal)

    def test_create_animal_shelter_not_found(self):
        """PRD §2.5: path-parameter existence, ERR_SHELTER_NOT_FOUND."""
        resp = api_client.create_animal(NON_EXISTENT_UUID, create_animal_payload(),
                                        TEST_USERS["shelter_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND.value)

    def test_create_animal_default_temperament_tags_empty(self):
        """PRD §3.1: "optionally a list of temperament_tags ... (defaulting to an empty array)"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        assert animal["temperament_tags"] == []

    def test_create_animal_default_special_care_none(self):
        """PRD §3.1 / scaffold Table 1: special_care_level default is NONE."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        assert animal["special_care_level"] == "NONE"

    def test_create_animal_bad_species_rejected(self):
        """PRD §2.7: "enum values recognized ... ERR_INVALID_REQUEST"."""
        shelter = create_shelter()
        resp = api_client.create_animal(
            shelter["id"], create_animal_payload(species="DINOSAUR"),
            TEST_USERS["shelter_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_animal_sets_intake_date(self):
        """PRD §3.1: "The platform stamps intake_date at creation"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        assert animal["intake_date"]


class TestAnimalRead:
    def test_get_animal(self):
        """PRD §4: GET /shelters/{sid}/animals/{aid} — role Any."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        resp = api_client.get_animal(shelter["id"], animal["id"],
                                     TEST_USERS["adopter_headers"])
        data = validate_success(resp)
        assert data["id"] == animal["id"]

    def test_get_animal_not_found(self):
        """PRD §2.5: ERR_ANIMAL_NOT_FOUND for missing animal id."""
        shelter = create_shelter()
        resp = api_client.get_animal(shelter["id"], NON_EXISTENT_UUID,
                                     TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND.value)

    def test_shelter_validated_before_animal(self):
        """PRD §2.5: "Path parameters are validated left-to-right"."""
        resp = api_client.get_animal(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                     TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND.value)


class TestAnimalPatchAndOCC:
    def test_patch_animal_bumps_version(self):
        """PRD §2.4: "On every mutation the server ... increments version by exactly one"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        v0 = animal["version"]
        resp = api_client.patch_animal(
            shelter["id"], animal["id"],
            {"name": "Biscuit II", "version": v0},
            TEST_USERS["shelter_admin_headers"])
        data = validate_success(resp)
        assert data["version"] == v0 + 1
        assert data["name"] == "Biscuit II"

    def test_patch_animal_stale_version_rejected(self):
        """PRD §2.4: "returns ERR_VERSION_CONFLICT if the two diverge"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        v0 = animal["version"]
        # first patch succeeds and bumps version
        api_client.patch_animal(shelter["id"], animal["id"],
                                {"name": "N1", "version": v0},
                                TEST_USERS["shelter_admin_headers"])
        # second patch with stale version
        resp = api_client.patch_animal(shelter["id"], animal["id"],
                                       {"name": "N2", "version": v0},
                                       TEST_USERS["shelter_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_animal_without_version_allowed(self):
        """PRD §2.4: "Omitting version skips the check — a deliberate escape hatch"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        resp = api_client.patch_animal(
            shelter["id"], animal["id"],
            {"name": "No Version Patch"},
            TEST_USERS["shelter_admin_headers"])
        data = validate_success(resp)
        assert data["name"] == "No Version Patch"
