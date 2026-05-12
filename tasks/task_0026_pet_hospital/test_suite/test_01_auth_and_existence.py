"""Auth, RBAC, and existence checks (PRD §2.1, §2.5, §5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_owner_payload,
    create_pet_payload,
    create_visit_payload,
    setup_owner_and_pet,
    validate_error,
    validate_paginated,
)


# ===========================================================================
# §2.1 — auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'If either header is missing or blank the request
        is rejected with ERR_AUTH_MISSING.'"""
        bad_headers = {"X-User-Role": "OwnerService"}
        res = api.create_owner(create_owner_payload(), bad_headers)
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'If either header is missing or blank the request
        is rejected with ERR_AUTH_MISSING.'"""
        bad_headers = {"X-User-ID": "owner-svc-001"}
        res = api.create_owner(create_owner_payload(), bad_headers)
        validate_error(res, "ERR_AUTH_MISSING")

    def test_blank_user_id_header_rejected(self, api):
        """PRD §2.1: 'If either header is missing or blank the request
        is rejected with ERR_AUTH_MISSING.'"""
        bad_headers = {"X-User-ID": "", "X-User-Role": "OwnerService"}
        res = api.create_owner(create_owner_payload(), bad_headers)
        validate_error(res, "ERR_AUTH_MISSING")

    def test_blank_user_role_header_rejected(self, api):
        """PRD §2.1: 'If either header is missing or blank the request
        is rejected with ERR_AUTH_MISSING.'"""
        bad_headers = {"X-User-ID": "owner-svc-001", "X-User-Role": ""}
        res = api.create_owner(create_owner_payload(), bad_headers)
        validate_error(res, "ERR_AUTH_MISSING")

    def test_unrecognized_role_value_rejected(self, api):
        """PRD §2.1: 'If X-User-Role is present but does not match one of
        the recognized role names, the request is rejected with
        ERR_AUTH_INVALID_ROLE.'"""
        bad_headers = build_user_headers("svc-1", "RandomRole")
        res = api.create_owner(create_owner_payload(), bad_headers)
        validate_error(res, "ERR_AUTH_INVALID_ROLE")


# ===========================================================================
# §2.1 — RBAC (sample — full coverage in per-feature files)
# ===========================================================================
class TestRBACSample:
    @pytest.mark.parametrize(
        "role",
        ["TriageNurse", "DraftingVet", "ReviewingVet",
         "Pharmacist", "Cashier"],
    )
    def test_create_drug_requires_platform_admin(self, api, role):
        """PRD §4 endpoint table row: '| POST | /pet-hospital/drugs |
        Create drug. | PlatformAdmin |'.

        PRD §2.1: 'If the role is recognized but is not authorized for
        the endpoint per the role-to-endpoint mapping in §4, the request
        is rejected with ERR_FORBIDDEN.'"""
        headers = build_user_headers(f"svc-{role}", role)
        # Minimal valid drug payload (RBAC must be checked before payload validation).
        payload = {
            "code": "TESTRBAC1",
            "name": "rbac-test",
            "controlled": False,
            "dosage_min_mg_per_kg": 1.0,
            "dosage_max_mg_per_kg": 10.0,
            "stock_units": 0,
        }
        res = api.create_drug(payload, headers)
        validate_error(res, "ERR_FORBIDDEN")

    @pytest.mark.parametrize(
        "role",
        ["TriageNurse", "DraftingVet", "ReviewingVet",
         "Pharmacist", "OwnerService"],
    )
    def test_create_bill_requires_cashier(self, api, role):
        """PRD §4 endpoint table row: '| POST | /pet-hospital/bills |
        Create bill. | Cashier |'.

        PRD §2.1: 'If the role is recognized but is not authorized for
        the endpoint per the role-to-endpoint mapping in §4, the request
        is rejected with ERR_FORBIDDEN.'"""
        headers = build_user_headers(f"svc-{role}", role)
        res = api.create_bill({"visit_id": NON_EXISTENT_UUID}, headers)
        validate_error(res, "ERR_FORBIDDEN")

    @pytest.mark.parametrize(
        "role",
        ["TriageNurse", "DraftingVet", "ReviewingVet",
         "Cashier", "OwnerService"],
    )
    def test_dispense_requires_pharmacist(self, api, role):
        """PRD §4 endpoint table row: '| POST |
        /pet-hospital/prescriptions/{rx_id}/dispense | Dispense approved
        prescription. | Pharmacist |'.

        PRD §2.1: 'If the role is recognized but is not authorized for
        the endpoint per the role-to-endpoint mapping in §4, the request
        is rejected with ERR_FORBIDDEN.'"""
        headers = build_user_headers(f"svc-{role}", role)
        res = api.dispense_prescription(NON_EXISTENT_UUID, headers)
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.5 — Path parameter existence (left-to-right validation)
# ===========================================================================
class TestPathParamExistence:
    def test_get_pet_unknown_id_returns_not_found(self, api, owner_service_headers):
        """PRD §2.5: 'A request to a path of the form /pets/{pet_id}/visits
        first verifies that pet_id resolves to an existing Pet; if it
        does not, the response is ERR_NOT_FOUND with no further checking
        of the inner segment.'"""
        res = api.get_pet(NON_EXISTENT_UUID, owner_service_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_visit_unknown_pet_returns_not_found(self, api, triage_nurse_headers):
        """PRD §2.5: 'A request to a path of the form /pets/{pet_id}/visits
        first verifies that pet_id resolves to an existing Pet; if it
        does not, the response is ERR_NOT_FOUND with no further checking
        of the inner segment.'"""
        res = api.create_visit(
            NON_EXISTENT_UUID, create_visit_payload(),
            triage_nurse_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_visit_unknown_id_returns_not_found(self, api, triage_nurse_headers):
        """PRD §2.5: 'Path parameters are validated left to right.'
        PRD §5 ERR_NOT_FOUND has HTTP 404."""
        res = api.get_visit(NON_EXISTENT_UUID, triage_nurse_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_due_list_unknown_pet_returns_not_found(self, api, drafting_vet_headers):
        """PRD §2.5: 'Path parameters are validated left to right.'"""
        res = api.get_due_list(NON_EXISTENT_UUID, drafting_vet_headers)
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.5 — Body FK existence
# ===========================================================================
class TestBodyForeignKeyExistence:
    def test_create_pet_unknown_owner_returns_reference_not_found(
        self, api, owner_service_headers,
    ):
        """PRD §2.5: 'foreign keys named in the request body — owner_id,
        visit_id, drug_code, cage_id, and similar — are verified after
        path parameters. A request-body FK that fails to resolve produces
        ERR_REFERENCE_NOT_FOUND with HTTP 422.'"""
        payload = create_pet_payload(owner_id=NON_EXISTENT_UUID)
        res = api.create_pet(payload, owner_service_headers)
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_create_treatment_record_unknown_visit_returns_reference_not_found(
        self, api, drafting_vet_headers,
    ):
        """PRD §2.5: 'A request-body FK that fails to resolve produces
        ERR_REFERENCE_NOT_FOUND with HTTP 422.'"""
        payload = {
            "visit_id": NON_EXISTENT_UUID,
            "consultation_notes": "x",
            "diagnosis_code": "K30",
            "treatment_plan": "y",
            "consent_recorded": False,
        }
        res = api.create_treatment_record(payload, drafting_vet_headers)
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_create_bill_unknown_visit_returns_reference_not_found(
        self, api, cashier_headers,
    ):
        """PRD §2.5: 'A request-body FK that fails to resolve produces
        ERR_REFERENCE_NOT_FOUND with HTTP 422.'"""
        res = api.create_bill({"visit_id": NON_EXISTENT_UUID}, cashier_headers)
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# §2.3 — Pagination defaults
# ===========================================================================
class TestPagination:
    def test_list_pet_visits_paginated_envelope(self, api):
        """PRD §2.3: 'The pagination block in meta exposes four fields —
        limit, offset, total_count, and has_more — where total_count is
        the absolute count of matching rows server-side and has_more is
        true when offset + limit is less than total_count.'"""
        owner, pet = setup_owner_and_pet()
        res = api.list_pet_visits(
            pet["id"], TEST_USERS["owner_service_headers"],
        )
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
