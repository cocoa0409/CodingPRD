"""
Tests for RBAC enforcement and security (auth headers, role restrictions, SQL injection).
Claims from Tables 4, 7.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_shelter_payload,
    create_animal_payload,
    create_vaccination_record_payload,
    create_adopter_payload,
    create_adoption_application_payload,
    create_compliance_hold_payload,
    create_fee_schedule_payload,
    create_shelter,
    create_available_animal,
    create_adopter_in_shelter,
    submit_application,
    start_application_review,
    complete_application_review,
    application_to_reviewed,
    create_shelter_with_fee_schedules,
    approve_application,
    pay_invoice_fully,
    create_boarding_reservation,
    confirm_boarding,
    create_hold_on_animal,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
)


class TestAuthHeaders:
    """Table 4 P1: Missing auth headers -> ERR_AUTH_REQUIRED."""

    def test_missing_all_headers(self, api):
        """No headers at all -> ERR_AUTH_REQUIRED."""
        res = api.list_shelters(headers={})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_missing_user_id(self, api):
        """X-User-Role present but X-User-ID missing -> ERR_AUTH_REQUIRED."""
        res = api.list_shelters(headers={"X-User-Role": "ShelterManager"})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_missing_user_role(self, api):
        """X-User-ID present but X-User-Role missing -> ERR_AUTH_REQUIRED."""
        res = api.list_shelters(headers={"X-User-ID": "test-user"})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_invalid_role(self, api):
        """Invalid role value -> ERR_AUTH_REQUIRED."""
        headers = build_user_headers("test-user", "InvalidRole")
        res = api.list_shelters(headers=headers)
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED)


class TestRBACExclusiveOperations:
    """Table 7: Role-specific exclusive operations enforcement."""

    # ── ShelterManager exclusives ──

    def test_caseworker_cannot_create_shelter(self, api, caseworker_headers):
        """CaseWorker cannot POST /shelters -> ERR_FORBIDDEN."""
        res = api.create_shelter(create_shelter_payload(), caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_vet_cannot_create_shelter(self, api, vet_headers):
        """Veterinarian cannot POST /shelters -> ERR_FORBIDDEN."""
        res = api.create_shelter(create_shelter_payload(), vet_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_suspend_shelter(self, api, caseworker_headers):
        """CaseWorker cannot suspend shelter -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        res = api.suspend_shelter(shelter["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_approve_application(self, api, caseworker_headers):
        """CaseWorker cannot approve application -> ERR_FORBIDDEN."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        res = api.approve_application(app["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_reject_application(self, api, caseworker_headers):
        """CaseWorker cannot reject application -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        res = api.reject_application(app["id"], {"rejection_reason": "test"}, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_confirm_boarding(self, api, caseworker_headers):
        """CaseWorker cannot confirm boarding -> ERR_FORBIDDEN."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)
        reservation = create_boarding_reservation(shelter["id"], animal["id"])
        res = api.confirm_boarding_reservation(reservation["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_refund_invoice(self, api, caseworker_headers, manager_headers):
        """CaseWorker cannot refund invoice -> ERR_FORBIDDEN."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])
        pay_invoice_fully(app["fee_invoice_id"])
        res = api.refund_invoice(app["fee_invoice_id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_void_invoice(self, api, caseworker_headers):
        """CaseWorker cannot void invoice -> ERR_FORBIDDEN."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])
        res = api.void_invoice(app["fee_invoice_id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_resolve_hold(self, api, caseworker_headers):
        """CaseWorker cannot resolve compliance hold -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold = create_hold_on_animal(animal["id"], severity="LOW")
        res = api.resolve_compliance_hold(
            hold["id"], {"resolution_notes": "test"}, caseworker_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_blacklist_adopter(self, api, caseworker_headers):
        """CaseWorker cannot blacklist adopter -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        adopter = create_adopter_in_shelter(shelter["id"])
        res = api.blacklist_adopter(adopter["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_create_fee_schedule(self, api, caseworker_headers):
        """CaseWorker cannot create fee schedule -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        res = api.create_fee_schedule(
            create_fee_schedule_payload(shelter["id"]), caseworker_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    # ── CaseWorker exclusives ──

    def test_manager_cannot_register_animal(self, api, manager_headers):
        """ShelterManager cannot POST /animals -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        res = api.create_animal(create_animal_payload(shelter["id"]), manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_register_adopter(self, api, manager_headers):
        """ShelterManager cannot POST /adopters -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        res = api.create_adopter(create_adopter_payload(shelter["id"]), manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_submit_application(self, api, manager_headers):
        """ShelterManager cannot submit adoption application -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        payload = create_adoption_application_payload(animal["id"], adopter["id"])
        res = api.create_adoption_application(payload, manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_start_review(self, api, manager_headers):
        """ShelterManager cannot start-review -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        res = api.start_review(app["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_pay_invoice(self, api, manager_headers):
        """ShelterManager cannot pay invoice -> ERR_FORBIDDEN."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])
        res = api.pay_invoice(
            app["fee_invoice_id"], {"amount": 1.0}, manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    # ── Veterinarian exclusives ──

    def test_manager_cannot_create_vaccination_record(self, api, manager_headers):
        """ShelterManager cannot POST /vaccination-records -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_vaccination_record_payload(animal["id"])
        res = api.create_vaccination_record(payload, manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_caseworker_cannot_create_vaccination_record(self, api, caseworker_headers):
        """CaseWorker cannot POST /vaccination-records -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_vaccination_record_payload(animal["id"])
        res = api.create_vaccination_record(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    # ── Shared operations ──

    def test_vet_can_create_compliance_hold(self, api, vet_headers):
        """Veterinarian can create compliance hold (shared with ShelterManager)."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_compliance_hold_payload(animal["id"], severity="LOW")
        res = api.create_compliance_hold(payload, vet_headers)
        validate_success(res, 201)

    def test_manager_can_create_compliance_hold(self, api, manager_headers):
        """ShelterManager can also create compliance hold."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_compliance_hold_payload(animal["id"], severity="LOW")
        res = api.create_compliance_hold(payload, manager_headers)
        validate_success(res, 201)

    def test_vet_cannot_create_compliance_hold_caseworker(self, api, caseworker_headers):
        """CaseWorker cannot create compliance hold -> ERR_FORBIDDEN."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_compliance_hold_payload(animal["id"], severity="LOW")
        res = api.create_compliance_hold(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestSQLInjection:
    """Security: SQL injection attempts should not produce 500 errors."""

    SQL_PAYLOADS = [
        "'; DROP TABLE shelters; --",
        "' OR '1'='1",
        "' UNION SELECT * FROM users--",
    ]
    SQL_ERROR_PATTERNS = [
        "sql syntax", "sqlstate", "database error",
        "sqlite", "pg_", "mysql_",
    ]

    @pytest.mark.parametrize("injection", SQL_PAYLOADS)
    def test_sql_injection_in_shelter_name(self, api, manager_headers, injection):
        """SQL injection in shelter name -> no 500, no SQL error leak."""
        res = api.create_shelter(
            create_shelter_payload(name=injection), manager_headers,
        )
        assert res.status_code != 500
        assert res.status_code in (201, 400)
        for pattern in self.SQL_ERROR_PATTERNS:
            assert pattern not in res.text.lower()

    @pytest.mark.parametrize("injection", SQL_PAYLOADS)
    def test_sql_injection_in_animal_name(self, api, caseworker_headers, injection):
        """SQL injection in animal name -> no 500, no SQL error leak."""
        shelter = create_shelter()
        res = api.create_animal(
            create_animal_payload(shelter["id"], name=injection), caseworker_headers,
        )
        assert res.status_code != 500
        assert res.status_code in (201, 400)
        for pattern in self.SQL_ERROR_PATTERNS:
            assert pattern not in res.text.lower()


class TestMassAssignment:
    """Security: Extra/system fields in payloads should be ignored."""

    def test_shelter_status_ignored_on_creation(self, api, manager_headers):
        """Providing status=SUSPENDED in creation payload -> ignored, starts OPEN."""
        payload = create_shelter_payload()
        payload["status"] = "SUSPENDED"
        payload["revenue_balance"] = 999999.99
        res = api.create_shelter(payload, manager_headers)
        shelter = validate_success(res, 201)
        assert shelter["status"] == "OPEN"
        assert shelter["revenue_balance"] == 0

    def test_animal_status_ignored_on_creation(self, api, caseworker_headers):
        """Providing status=ADOPTED in creation payload -> ignored, starts INTAKE."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"])
        payload["status"] = "ADOPTED"
        payload["adoption_eligible"] = True
        res = api.create_animal(payload, caseworker_headers)
        animal = validate_success(res, 201)
        assert animal["status"] == "INTAKE"
