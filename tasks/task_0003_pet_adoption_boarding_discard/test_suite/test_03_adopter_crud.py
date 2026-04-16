"""
Tests for Adopter CRUD and blacklisting.
Claims from Tables 1, 2, 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_adopter,
    assert_version_incremented,
    create_adopter_payload,
    create_shelter,
    create_adopter_in_shelter,
    create_available_animal,
    submit_application,
    start_application_review,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
)


class TestAdopterCreation:
    """Table 1 / Table 5: Adopter registration."""

    def test_create_adopter_success(self, api, caseworker_headers):
        """POST /adopters with valid payload returns 201 with ACTIVE status."""
        shelter = create_shelter()
        payload = create_adopter_payload(
            shelter["id"], full_name="John Smith", email="john@example.com",
        )
        res = api.create_adopter(payload, caseworker_headers)
        adopter = validate_success(res, 201)
        assert_adopter(adopter)
        assert adopter["full_name"] == "John Smith"
        assert adopter["email"] == "john@example.com"
        assert adopter["status"] == "ACTIVE"
        assert adopter["adoption_history_count"] == 0
        assert adopter["home_visit_passed"] is False

    def test_get_nonexistent_adopter(self, api, caseworker_headers):
        """ERR_ADOPTER_NOT_FOUND for non-existent adopter."""
        res = api.get_adopter(NON_EXISTENT_UUID, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ADOPTER_NOT_FOUND)

    def test_create_adopter_nonexistent_shelter(self, api, caseworker_headers):
        """FK to non-existent shelter -> ERR_SHELTER_NOT_FOUND."""
        payload = create_adopter_payload(NON_EXISTENT_UUID)
        res = api.create_adopter(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "shelter_id", "full_name", "email", "phone", "home_type", "has_yard", "has_other_pets",
    ])
    def test_create_adopter_missing_required_field(self, api, caseworker_headers, missing_field):
        """Omitting required field -> ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        payload = create_adopter_payload(shelter["id"])
        del payload[missing_field]
        res = api.create_adopter(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_adopter_default_empty_other_pet_species(self, api, caseworker_headers):
        """Omitting other_pet_species defaults to empty array."""
        shelter = create_shelter()
        payload = create_adopter_payload(shelter["id"])
        del payload["other_pet_species"]
        res = api.create_adopter(payload, caseworker_headers)
        adopter = validate_success(res, 201)
        assert adopter["other_pet_species"] == []

    def test_list_adopters_pagination(self, api, caseworker_headers):
        """GET /adopters supports pagination."""
        shelter = create_shelter()
        for i in range(3):
            create_adopter_in_shelter(shelter["id"], full_name=f"Adopter {i}")

        data, meta = validate_paginated(
            api.list_adopters(caseworker_headers, params={"shelter_id": shelter["id"]})
        )
        assert meta["total_count"] >= 3


class TestAdopterUpdate:
    """PATCH /adopters/{id} — update mutable fields."""

    def test_update_adopter_name(self, api, caseworker_headers):
        """PATCH updates full_name and increments version."""
        shelter = create_shelter()
        adopter = create_adopter_in_shelter(shelter["id"])
        old_version = adopter["version"]
        res = api.update_adopter(
            adopter["id"], {"full_name": "Updated Name"}, caseworker_headers,
        )
        updated = validate_success(res, 200)
        assert updated["full_name"] == "Updated Name"
        assert_version_incremented(updated["version"], old_version)


class TestAdopterBlacklist:
    """Table 2 / Table 5: Blacklisting an adopter and cascading effects."""

    def test_blacklist_adopter(self, api, manager_headers):
        """POST /adopters/{id}/blacklist -> status BLACKLISTED."""
        shelter = create_shelter()
        adopter = create_adopter_in_shelter(shelter["id"])
        res = api.blacklist_adopter(adopter["id"], manager_headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "BLACKLISTED"

    def test_blacklist_cascades_to_submitted_applications(self, api, manager_headers, caseworker_headers):
        """
        Blacklisting an adopter withdraws all SUBMITTED/UNDER_REVIEW applications.
        """
        shelter = create_shelter()
        animal1 = create_available_animal(shelter["id"])
        animal2 = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])

        app1 = submit_application(animal1["id"], adopter["id"])
        assert app1["status"] == "SUBMITTED"

        app2 = submit_application(animal2["id"], adopter["id"])
        app2 = start_application_review(app2["id"])
        assert app2["status"] == "UNDER_REVIEW"

        api.blacklist_adopter(adopter["id"], manager_headers)

        app1_after = validate_success(
            api.get_adoption_application(app1["id"], caseworker_headers), 200,
        )
        assert app1_after["status"] == "WITHDRAWN"

        app2_after = validate_success(
            api.get_adoption_application(app2["id"], caseworker_headers), 200,
        )
        assert app2_after["status"] == "WITHDRAWN"
