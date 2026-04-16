"""
Tests for Shelter CRUD operations and state transitions (OPEN <-> SUSPENDED).
Claims from Tables 1, 2, 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_shelter,
    assert_shelter_invariants,
    assert_version_incremented,
    create_shelter_payload,
    create_shelter,
    create_available_animal,
    create_hold_on_animal,
    resolve_hold,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
)


class TestShelterCreation:
    """Table 1 / Table 5: Shelter creation and retrieval."""

    def test_create_shelter_success(self, api, manager_headers):
        """POST /shelters with valid payload returns 201 with all fields."""
        payload = create_shelter_payload(name="Sunshine Shelter", boarding_capacity=15)
        res = api.create_shelter(payload, manager_headers)
        shelter = validate_success(res, 201)
        assert_shelter(shelter)
        assert shelter["name"] == "Sunshine Shelter"
        assert shelter["address"] == payload["address"]
        assert shelter["boarding_capacity"] == 15
        assert shelter["status"] == "OPEN"
        assert shelter["current_boarding_count"] == 0
        assert shelter["adoption_count"] == 0
        assert shelter["compliance_score"] == 100
        assert shelter["revenue_balance"] == 0

    def test_get_shelter(self, api, manager_headers):
        """GET /shelters/{id} returns the created shelter."""
        shelter = create_shelter(name="Get Test Shelter")
        res = api.get_shelter(shelter["id"], manager_headers)
        retrieved = validate_success(res, 200)
        assert retrieved["id"] == shelter["id"]
        assert retrieved["name"] == "Get Test Shelter"

    def test_get_nonexistent_shelter(self, api, manager_headers):
        """GET /shelters/{id} with non-existent UUID -> ERR_SHELTER_NOT_FOUND."""
        res = api.get_shelter(NON_EXISTENT_UUID, manager_headers)
        validate_error(res, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    def test_list_shelters_pagination(self, api, manager_headers):
        """GET /shelters supports pagination with limit/offset."""
        for i in range(3):
            create_shelter(name=f"Paginate Shelter {i}")
        data, meta = validate_paginated(api.list_shelters(manager_headers))
        assert meta["total_count"] >= 3

        data, meta = validate_paginated(
            api.list_shelters(manager_headers, params={"limit": 1})
        )
        assert len(data) == 1
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_shelters(manager_headers, params={"offset": 99999})
        )
        assert len(data) == 0
        assert meta["has_more"] is False

    @pytest.mark.parametrize("missing_field", ["name", "address", "boarding_capacity"])
    def test_create_shelter_missing_required_field(self, api, manager_headers, missing_field):
        """Omitting required field -> ERR_INVALID_REQUEST."""
        payload = create_shelter_payload()
        del payload[missing_field]
        res = api.create_shelter(payload, manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestShelterStateTransitions:
    """Table 2: Shelter OPEN <-> SUSPENDED transitions."""

    def test_suspend_open_shelter(self, api, manager_headers):
        """OPEN -> SUSPENDED via POST /shelters/{id}/suspend."""
        shelter = create_shelter()
        assert shelter["status"] == "OPEN"
        old_version = shelter["version"]
        res = api.suspend_shelter(shelter["id"], manager_headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "SUSPENDED"
        assert_version_incremented(updated["version"], old_version)

    def test_reopen_suspended_shelter(self, api, manager_headers):
        """SUSPENDED -> OPEN via POST /shelters/{id}/reopen."""
        shelter = create_shelter()
        api.suspend_shelter(shelter["id"], manager_headers)
        res = api.reopen_shelter(shelter["id"], manager_headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "OPEN"

    def test_suspend_already_suspended(self, api, manager_headers):
        """Suspending an already-SUSPENDED shelter -> ERR_INVALID_STATE."""
        shelter = create_shelter()
        api.suspend_shelter(shelter["id"], manager_headers)
        res = api.suspend_shelter(shelter["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_reopen_already_open(self, api, manager_headers):
        """Reopening an already-OPEN shelter -> ERR_INVALID_STATE."""
        shelter = create_shelter()
        res = api.reopen_shelter(shelter["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_reopen_blocked_by_critical_hold(self, api, manager_headers):
        """
        Reopen fails with ERR_COMPLIANCE_HOLD_ACTIVE if any animal has a
        CRITICAL compliance hold.
        """
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        api.suspend_shelter(shelter["id"], manager_headers)
        # Create CRITICAL hold on animal
        create_hold_on_animal(animal["id"], severity="CRITICAL")
        res = api.reopen_shelter(shelter["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE)

    def test_reopen_succeeds_after_critical_hold_resolved(self, api, manager_headers):
        """Reopen succeeds once CRITICAL hold is resolved."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        api.suspend_shelter(shelter["id"], manager_headers)
        hold = create_hold_on_animal(animal["id"], severity="CRITICAL")
        resolve_hold(hold["id"])
        res = api.reopen_shelter(shelter["id"], manager_headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "OPEN"
