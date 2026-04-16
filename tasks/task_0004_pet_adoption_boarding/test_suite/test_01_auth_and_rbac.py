"""Tests for authentication and RBAC.

Covers: PRD Section 2.1 (Authentication and Role Model), Table 4 priorities 1-3,
Table 7 (RBAC matrix).
"""
import pytest
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    create_shelter_payload, create_animal_payload, create_adopter_payload,
    create_vaccination_record_payload, create_compliance_hold_payload,
    create_fee_schedule_payload, create_settlement_batch_payload,
    create_adoption_application_payload, blacklist_adopter_payload,
    create_shelter, create_available_animal, create_adopter,
    setup_basic_adoption_scenario, create_reviewed_application,
    create_boarding_requested, create_application_under_review,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]
_vet = TEST_USERS["vet_headers"]


class TestAuthRequired:
    """PRD 2.1 + Table 4 priority 1-2: X-User-ID and X-User-Role must be present."""

    def test_missing_user_id_header(self):
        """Request missing X-User-ID returns ERR_AUTH_REQUIRED."""
        resp = api_client._request("GET", "/petcare/shelters",
                                    headers={"X-User-Role": "ShelterManager",
                                             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_missing_user_role_header(self):
        """Request missing X-User-Role returns ERR_AUTH_REQUIRED."""
        resp = api_client._request("GET", "/petcare/shelters",
                                    headers={"X-User-ID": "u1",
                                             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_invalid_role_value(self):
        """Unknown X-User-Role value returns ERR_AUTH_REQUIRED."""
        resp = api_client._request("GET", "/petcare/shelters",
                                    headers={"X-User-ID": "u1", "X-User-Role": "Hacker",
                                             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_empty_user_id(self):
        """Empty X-User-ID header returns ERR_AUTH_REQUIRED."""
        resp = api_client._request("GET", "/petcare/shelters",
                                    headers={"X-User-ID": "", "X-User-Role": "ShelterManager",
                                             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)


class TestForbiddenOperations:
    """PRD 2.1 + Table 7: only authorized roles may perform write ops."""

    def test_case_worker_cannot_create_shelter(self):
        """CaseWorker cannot POST /shelters (ShelterManager only)."""
        resp = api_client.create_shelter(create_shelter_payload(), _case_worker)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_vet_cannot_create_shelter(self):
        """Veterinarian cannot create a shelter."""
        resp = api_client.create_shelter(create_shelter_payload(), _vet)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_worker_cannot_suspend_shelter(self):
        """CaseWorker cannot suspend a shelter."""
        shelter = create_shelter()
        resp = api_client.suspend_shelter(shelter["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_register_animal(self):
        """ShelterManager cannot register animals (CaseWorker only)."""
        shelter = create_shelter()
        resp = api_client.create_animal(create_animal_payload(shelter["id"]), _manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_vet_cannot_register_animal(self):
        """Veterinarian cannot register animals."""
        shelter = create_shelter()
        resp = api_client.create_animal(create_animal_payload(shelter["id"]), _vet)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_worker_cannot_create_vaccination_record(self):
        """CaseWorker cannot create vaccination records (Veterinarian only)."""
        shelter = create_shelter()
        animal = get_success_data(api_client.create_animal(
            create_animal_payload(shelter["id"]), _case_worker
        ))
        resp = api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_create_vaccination_record(self):
        """ShelterManager cannot create vaccination records."""
        shelter = create_shelter()
        animal = get_success_data(api_client.create_animal(
            create_animal_payload(shelter["id"]), _case_worker
        ))
        resp = api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _manager
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_worker_cannot_approve_application(self):
        """CaseWorker cannot approve applications (ShelterManager only)."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application()
        resp = api_client.approve_application(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_vet_cannot_approve_application(self):
        """Veterinarian cannot approve applications."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application()
        resp = api_client.approve_application(app["id"], _vet)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_worker_cannot_confirm_reservation(self):
        """CaseWorker cannot confirm boarding (ShelterManager only)."""
        shelter, animal, res = create_boarding_requested()
        resp = api_client.confirm_boarding_reservation(res["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_worker_cannot_create_fee_schedule(self):
        """CaseWorker cannot create fee schedules."""
        shelter = create_shelter()
        resp = api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter["id"]), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_worker_cannot_create_settlement_batch(self):
        """CaseWorker cannot create settlement batches."""
        shelter = create_shelter()
        resp = api_client.create_settlement_batch(
            create_settlement_batch_payload(shelter["id"]), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_vet_cannot_resolve_hold(self):
        """Veterinarian cannot resolve holds (ShelterManager only)."""
        shelter = create_shelter()
        animal = get_success_data(api_client.create_animal(
            create_animal_payload(shelter["id"]), _case_worker
        ))
        hold = get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"]), _vet
        ))
        resp = api_client.resolve_compliance_hold(
            hold["id"], {"resolution_notes": "Done"}, _vet
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_worker_cannot_blacklist_adopter(self):
        """CaseWorker cannot blacklist adopters."""
        adopter = create_adopter()
        resp = api_client.blacklist_adopter(
            adopter["id"], blacklist_adopter_payload(), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSharedReadAccess:
    """PRD 2.1 + Table 7: all roles can GET most resources."""

    def test_all_roles_can_list_shelters(self):
        """ShelterManager, CaseWorker, Veterinarian can list shelters."""
        create_shelter()
        for headers in (_manager, _case_worker, _vet):
            resp = api_client.list_shelters(headers)
            validate_success(resp)

    def test_all_roles_can_list_animals(self):
        """All roles can list animals."""
        create_shelter()
        for headers in (_manager, _case_worker, _vet):
            resp = api_client.list_animals(headers)
            validate_success(resp)


class TestComplianceHoldSharedWrite:
    """PRD 2.1 + Table 7: compliance-hold creation is shared by Veterinarian and ShelterManager."""

    def test_veterinarian_can_create_compliance_hold(self):
        """Veterinarian can create a ComplianceHold."""
        shelter = create_shelter()
        animal = get_success_data(api_client.create_animal(
            create_animal_payload(shelter["id"]), _case_worker
        ))
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"]), _vet
        )
        data = validate_success(resp, 201)
        assert data["imposed_role"] == "VETERINARIAN"

    def test_shelter_manager_can_create_compliance_hold(self):
        """ShelterManager can create a ComplianceHold."""
        shelter = create_shelter()
        animal = get_success_data(api_client.create_animal(
            create_animal_payload(shelter["id"]), _case_worker
        ))
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"]), _manager
        )
        data = validate_success(resp, 201)
        assert data["imposed_role"] == "SHELTER_MANAGER"

    def test_case_worker_cannot_create_compliance_hold(self):
        """CaseWorker cannot create ComplianceHolds."""
        shelter = create_shelter()
        animal = get_success_data(api_client.create_animal(
            create_animal_payload(shelter["id"]), _case_worker
        ))
        resp = api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"]), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
