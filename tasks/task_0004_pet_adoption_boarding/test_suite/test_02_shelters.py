"""Tests for Shelter CRUD and lifecycle.

Covers: PRD Section 3.1 (Shelters, Their Lifecycle), Table 2 (Shelter state machine),
Table 4 priorities 4, 10, 31.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_shelter,
    create_shelter_payload, create_animal_payload, create_compliance_hold_payload,
    create_shelter, create_suspended_shelter, create_available_animal,
    create_animal_intake,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]
_vet = TEST_USERS["vet_headers"]


class TestShelterCreation:
    """PRD 3.1: ShelterManager creates a shelter."""

    def test_create_shelter_success(self):
        """A fresh shelter is OPEN with all counters zero and compliance_score 100.00."""
        payload = create_shelter_payload()
        resp = api_client.create_shelter(payload, _manager)
        data = validate_success(resp, 201)
        assert_shelter(data)
        assert data["status"] == "OPEN"
        assert data["name"] == payload["name"]
        assert data["boarding_capacity"] == payload["boarding_capacity"]
        assert data["tax_rate"] == payload["tax_rate"]
        assert data["current_boarding_count"] == 0
        assert data["adoption_count"] == 0
        assert data["revenue_pending_cents"] == 0
        assert data["revenue_settled_cents"] == 0
        assert data["compliance_score"] == 100.00

    def test_create_shelter_boarding_capacity_zero_rejected(self):
        """boarding_capacity < 1 rejected with ERR_INVALID_REQUEST."""
        payload = create_shelter_payload(boarding_capacity=0)
        resp = api_client.create_shelter(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_shelter_boarding_capacity_negative_rejected(self):
        """Negative boarding_capacity rejected."""
        payload = create_shelter_payload(boarding_capacity=-5)
        resp = api_client.create_shelter(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    @pytest.mark.parametrize("tax_rate", [-0.01, 0.31, 0.5, 1.0])
    def test_create_shelter_tax_rate_out_of_range(self, tax_rate):
        """tax_rate outside [0, 0.30] is rejected."""
        payload = create_shelter_payload(tax_rate=tax_rate)
        resp = api_client.create_shelter(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_shelter_tax_rate_boundary_zero(self):
        """tax_rate == 0.0 is inclusive."""
        payload = create_shelter_payload(tax_rate=0.0)
        resp = api_client.create_shelter(payload, _manager)
        data = validate_success(resp, 201)
        assert data["tax_rate"] == 0.0

    def test_create_shelter_tax_rate_boundary_max(self):
        """tax_rate == 0.30 is inclusive."""
        payload = create_shelter_payload(tax_rate=0.30)
        resp = api_client.create_shelter(payload, _manager)
        data = validate_success(resp, 201)
        assert abs(data["tax_rate"] - 0.30) < 1e-9

    def test_create_shelter_missing_required_field(self):
        """Missing a required field returns ERR_INVALID_REQUEST."""
        payload = create_shelter_payload()
        del payload["name"]
        resp = api_client.create_shelter(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestShelterRetrieval:
    """PRD 2.6 + Section 4: get and list shelters."""

    def test_get_shelter(self):
        shelter = create_shelter()
        resp = api_client.get_shelter(shelter["id"], _manager)
        data = validate_success(resp)
        assert_shelter(data)
        assert data["id"] == shelter["id"]

    def test_get_shelter_not_found(self):
        resp = api_client.get_shelter(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    def test_list_shelters(self):
        create_shelter()
        create_shelter()
        resp = api_client.list_shelters(_manager)
        validate_success(resp)


class TestShelterLifecycle:
    """PRD 3.1 + Table 2: Shelter.status transitions."""

    def test_suspend_open_shelter(self):
        """OPEN shelter transitions to SUSPENDED."""
        shelter = create_shelter()
        resp = api_client.suspend_shelter(shelter["id"], _manager)
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"

    def test_suspend_already_suspended_shelter(self):
        """Cannot suspend a SUSPENDED shelter (ERR_INVALID_STATE)."""
        shelter = create_suspended_shelter()
        resp = api_client.suspend_shelter(shelter["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reopen_suspended_shelter(self):
        """SUSPENDED shelter transitions back to OPEN."""
        shelter = create_suspended_shelter()
        resp = api_client.reopen_shelter(shelter["id"], _manager)
        data = validate_success(resp)
        assert data["status"] == "OPEN"

    def test_reopen_open_shelter(self):
        """Cannot reopen an already-OPEN shelter (ERR_INVALID_STATE)."""
        shelter = create_shelter()
        resp = api_client.reopen_shelter(shelter["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reopen_blocked_by_critical_hold(self):
        """PRD 3.1: reopen blocked by any ACTIVE CRITICAL hold on an animal."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"])
        # Put a CRITICAL hold on the animal.
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="CRITICAL"), _vet
        ))
        # Suspend then try to reopen.
        get_success_data(api_client.suspend_shelter(shelter["id"], _manager))
        resp = api_client.reopen_shelter(shelter["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_CRITICAL_HOLD_PRESENT)

    def test_reopen_allowed_after_high_hold_only(self):
        """Reopen is NOT blocked by HIGH holds — only CRITICAL blocks."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"])
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="HIGH"), _vet
        ))
        get_success_data(api_client.suspend_shelter(shelter["id"], _manager))
        resp = api_client.reopen_shelter(shelter["id"], _manager)
        data = validate_success(resp)
        assert data["status"] == "OPEN"


class TestSuspendedShelterBlocksWrites:
    """PRD 3.1 + Table 4 priority 6: suspended shelter rejects new applications and reservations."""

    def test_suspended_shelter_rejects_new_application(self):
        """POST /adoption-applications against a SUSPENDED shelter fails ERR_SHELTER_SUSPENDED."""
        from test_helpers import create_adopter
        shelter = create_shelter()
        animal = create_available_animal(shelter_id=shelter["id"])
        adopter = create_adopter(shelter_id=shelter["id"])
        # Suspend after setup.
        get_success_data(api_client.suspend_shelter(shelter["id"], _manager))
        from test_helpers import create_adoption_application_payload
        resp = api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]),
            _case_worker,
        )
        validate_error(resp, ApiErrorId.ERR_SHELTER_SUSPENDED)

    def test_suspended_shelter_rejects_new_boarding_reservation(self):
        """POST /boarding-reservations against SUSPENDED shelter fails ERR_SHELTER_SUSPENDED."""
        from test_helpers import create_boarding_ready_animal, create_boarding_reservation_payload
        shelter = create_shelter()
        animal = create_boarding_ready_animal(shelter_id=shelter["id"])
        get_success_data(api_client.suspend_shelter(shelter["id"], _manager))
        resp = api_client.create_boarding_reservation(
            create_boarding_reservation_payload(shelter["id"], animal["id"]),
            _case_worker,
        )
        validate_error(resp, ApiErrorId.ERR_SHELTER_SUSPENDED)
