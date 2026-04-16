"""Tests for ComplianceHold creation and resolution.

Covers: PRD Section 3.7 (Compliance Holds), Table 2 (ComplianceHold state machine),
Table 4 priority 9.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_compliance_hold,
    create_compliance_hold_payload, resolve_hold_payload,
    create_shelter, create_animal_intake, create_available_animal,
    create_active_hold, user_id_from_headers,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]
_vet = TEST_USERS["vet_headers"]


class TestComplianceHoldCreation:
    """PRD 3.7: Veterinarian or ShelterManager create compliance holds."""

    def test_create_hold_vet(self):
        animal = create_animal_intake()
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(
                animal["id"], hold_type="HEALTH_CONCERN", severity="MEDIUM",
                reason="Routine check"
            ),
            _vet,
        )
        data = validate_success(resp, 201)
        assert_compliance_hold(data)
        assert data["status"] == "ACTIVE"
        assert data["imposed_role"] == "VETERINARIAN"
        assert data["imposed_by"] == user_id_from_headers(_vet)

    def test_create_hold_manager(self):
        animal = create_animal_intake()
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(
                animal["id"], hold_type="BEHAVIOR_INCIDENT", severity="HIGH",
                reason="Aggression reported"
            ),
            _manager,
        )
        data = validate_success(resp, 201)
        assert data["imposed_role"] == "SHELTER_MANAGER"

    def test_create_hold_animal_not_found(self):
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(NON_EXISTENT_UUID), _vet
        )
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    @pytest.mark.parametrize("hold_type", [
        "VACCINATION_OVERDUE", "HEALTH_CONCERN", "BEHAVIOR_INCIDENT", "QUARANTINE"
    ])
    def test_create_hold_all_types(self, hold_type):
        animal = create_animal_intake()
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], hold_type=hold_type), _vet
        )
        validate_success(resp, 201)

    @pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    def test_create_hold_all_severities(self, severity):
        animal = create_animal_intake()
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity=severity), _vet
        )
        validate_success(resp, 201)

    def test_create_hold_invalid_severity(self):
        animal = create_animal_intake()
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="EXTREME"), _vet
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAnimalStatusChangesOnHold:
    """PRD 3.7: HIGH/CRITICAL hold pushes AVAILABLE/BOARDING animal to UNAVAILABLE."""

    def test_high_hold_pushes_to_unavailable(self):
        animal = create_available_animal()
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="HIGH"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "UNAVAILABLE"
        assert refreshed["active_hold_count"] == 1

    def test_critical_hold_pushes_to_unavailable(self):
        animal = create_available_animal()
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="CRITICAL"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "UNAVAILABLE"

    def test_low_hold_does_not_change_status(self):
        animal = create_available_animal()
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="LOW"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "AVAILABLE"
        assert refreshed["active_hold_count"] == 1

    def test_medium_hold_does_not_change_status(self):
        animal = create_available_animal()
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="MEDIUM"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "AVAILABLE"


class TestResolveHold:
    """PRD 3.7: ShelterManager resolves a hold."""

    def test_resolve_success(self):
        animal = create_animal_intake()
        hold = create_active_hold(animal["id"], severity="MEDIUM")
        resp = api_client.resolve_compliance_hold(
            hold["id"], resolve_hold_payload("All clear"), _manager
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED"
        assert data["resolved_by"] == user_id_from_headers(_manager)
        assert data["resolution_notes"] == "All clear"

    def test_resolve_missing_notes_rejected(self):
        animal = create_animal_intake()
        hold = create_active_hold(animal["id"], severity="MEDIUM")
        resp = api_client.resolve_compliance_hold(hold["id"], {}, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_resolve_already_resolved_rejected(self):
        animal = create_animal_intake()
        hold = create_active_hold(animal["id"], severity="MEDIUM")
        get_success_data(api_client.resolve_compliance_hold(
            hold["id"], resolve_hold_payload("done"), _manager
        ))
        resp = api_client.resolve_compliance_hold(
            hold["id"], resolve_hold_payload("again"), _manager
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_resolve_restores_animal_status(self):
        """Resolving the last HIGH hold returns animal to AVAILABLE."""
        animal = create_available_animal()
        hold = create_active_hold(animal["id"], severity="HIGH")
        get_success_data(api_client.resolve_compliance_hold(
            hold["id"], resolve_hold_payload("Cleared"), _manager
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "AVAILABLE"

    def test_resolve_keeps_unavailable_if_other_high_hold_present(self):
        """If another HIGH hold remains, animal stays UNAVAILABLE."""
        animal = create_available_animal()
        hold1 = create_active_hold(animal["id"], severity="HIGH")
        hold2 = create_active_hold(animal["id"], severity="HIGH")
        get_success_data(api_client.resolve_compliance_hold(
            hold1["id"], resolve_hold_payload("Cleared 1"), _manager
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "UNAVAILABLE"
        assert refreshed["active_hold_count"] == 1
        # Resolve the second — should restore
        get_success_data(api_client.resolve_compliance_hold(
            hold2["id"], resolve_hold_payload("Cleared 2"), _manager
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "AVAILABLE"
        assert refreshed["active_hold_count"] == 0


class TestHoldRetrieval:
    def test_get_hold(self):
        animal = create_animal_intake()
        hold = create_active_hold(animal["id"])
        resp = api_client.get_compliance_hold(hold["id"], _manager)
        data = validate_success(resp)
        assert_compliance_hold(data)

    def test_get_hold_not_found(self):
        resp = api_client.get_compliance_hold(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_FOUND)

    def test_list_holds(self):
        animal = create_animal_intake()
        create_active_hold(animal["id"])
        resp = api_client.list_compliance_holds(_manager)
        validate_success(resp)
