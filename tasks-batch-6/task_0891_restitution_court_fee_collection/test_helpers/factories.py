"""Payload factories — one per entity, input fields only."""


def create_case_payload(**overrides) -> dict:
    defaults = {
        "case_number": "C-TEST-001",
        "defendant_name": "Test Defendant",
    }
    defaults.update(overrides)
    return defaults


def create_victim_payload(**overrides) -> dict:
    defaults = {"name": "Test Victim"}
    defaults.update(overrides)
    return defaults


def create_obligation_payload(**overrides) -> dict:
    """case_id, obligation_type, assessed_amount_cents required.
    victim_id and priority_rank are optional and only included when overridden.
    """
    defaults = {
        "case_id": None,
        "obligation_type": "COURT_FEE",
        "assessed_amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "monthly_income_cents": 400000,
        "monthly_expenses_cents": 250000,
        "ability_to_pay_method": "NET_DISPOSABLE",
        "expected_case_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "amount_cents": 10000,
        "allocation_method": "STATUTORY_PRIORITY",
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "victim_id": None,
        "case_id": None,
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_wage_assignment_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "employer_name": "Test Employer",
        "monthly_withhold_cents": 10000,
        "effective_start_date": "2026-06-01T00:00:00Z",
        "effective_end_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_request_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "obligation_id": None,
        "requested_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_amnesty_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Amnesty",
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2026-12-01T00:00:00Z",
        "waiver_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
