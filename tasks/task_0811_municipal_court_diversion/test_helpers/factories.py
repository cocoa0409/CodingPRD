"""Payload factories — one per entity, input fields only."""


def create_defendant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Defendant",
        "date_of_birth": "1990-01-01",
        "email": "defendant@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(defendant_id, **overrides) -> dict:
    defaults = {
        "defendant_id": defendant_id,
        "citation_number": "C-0001",
        "offense_date": "2026-03-01",
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(**overrides) -> dict:
    defaults = {
        "offense_code": "MC-14",
        "severity": "MISDEMEANOR",
        "base_fine_amount": 200,
    }
    defaults.update(overrides)
    return defaults


def create_courtroom_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Courtroom",
        "room_code": "TR",
    }
    defaults.update(overrides)
    return defaults


def create_arraignment_payload(courtroom_id, **overrides) -> dict:
    defaults = {
        "courtroom_id": courtroom_id,
        "scheduled_start": "2026-03-05T10:00:00Z",
        "scheduled_end": "2026-03-05T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_diversion_payload(**overrides) -> dict:
    defaults = {
        "mandated_service_hours": 10,
        "required_class_sessions": 0,
        "program_fee": 100,
        "program_deadline": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Site",
        "site_type": "COMMUNITY_SERVICE",
        "concurrent_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_service_assignment_payload(service_site_id, **overrides) -> dict:
    defaults = {
        "service_site_id": service_site_id,
        "assignment_type": "COMMUNITY_SERVICE",
        "required_hours": 10,
        "session_start": "2026-03-10T09:00:00Z",
        "session_end": "2026-03-10T19:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_amnesty_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Amnesty",
        "penalty_waiver_pct": 0.5,
        "reinstatement_fee": 40,
        "active_from": "2026-06-01T00:00:00Z",
        "active_to": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_installment_plan_payload(num_installments, expected_ledger_account_version, **overrides) -> dict:
    defaults = {
        "num_installments": num_installments,
        "expected_ledger_account_version": expected_ledger_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount, **overrides) -> dict:
    defaults = {"amount": amount}
    defaults.update(overrides)
    return defaults


def plea_payload(plea="GUILTY", **overrides) -> dict:
    defaults = {"plea": plea}
    defaults.update(overrides)
    return defaults


def progress_payload(hours_logged, **overrides) -> dict:
    defaults = {"hours_logged": hours_logged}
    defaults.update(overrides)
    return defaults
