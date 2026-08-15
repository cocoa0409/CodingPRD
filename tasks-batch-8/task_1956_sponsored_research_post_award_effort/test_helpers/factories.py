"""Payload factories — one per entity, input fields only (PRD §3)."""

_DEFAULT_SPONSOR = {
    "name": "NSF-LOC",
    "sponsor_type": "FEDERAL",
    "payment_method": "LETTER_OF_CREDIT",
    "salary_cap_annual_cents": 20_000_000,
    "f_and_a_rate_bps": 5000,
    "late_payment_apr_bps": 0,
}


def create_sponsor_payload(**overrides) -> dict:
    defaults = dict(_DEFAULT_SPONSOR)
    defaults.update(overrides)
    return defaults


def create_person_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr. Prime",
        "role_type": "PRINCIPAL_INVESTIGATOR",
        "institutional_base_salary_annual_cents": 12_000_000,
        "appointment_months": 12,
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(sponsor_id: str, pi_id: str, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "pi_id": pi_id,
        "award_number": "AWD-001",
        "title": "Test award",
        "project_start_date": "2026-01-01T00:00:00Z",
        "original_end_date": "2026-12-31T00:00:00Z",
        "total_obligated_cents": 150_000,
        "fringe_rate_bps": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(award_id: str, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "category": "TRAVEL",
        "authorized_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_effort_commitment_payload(award_id: str, person_id: str, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "person_id": person_id,
        "committed_effort_pct": 25.0,
    }
    defaults.update(overrides)
    return defaults


def create_expenditure_payload(award_id: str, budget_line_id: str, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "budget_line_id": budget_line_id,
        "expenditure_type": "TRAVEL",
        "amount_cents": 10_000,
        "transaction_date": "2026-03-01T00:00:00Z",
        "is_allocable": True,
        "is_reasonable": True,
        "is_consistent": True,
    }
    defaults.update(overrides)
    return defaults


def create_salary_expenditure_payload(award_id: str, budget_line_id: str, person_id: str,
                                      **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "budget_line_id": budget_line_id,
        "expenditure_type": "SALARY",
        "person_id": person_id,
        "effort_pct": 25.0,
        "period_months": 1,
        "transaction_date": "2026-03-01T00:00:00Z",
        "is_allocable": True,
        "is_reasonable": True,
        "is_consistent": True,
        "cash_disbursed": True,
    }
    defaults.update(overrides)
    return defaults


def create_cost_transfer_payload(source_expenditure_id: str, target_award_id: str,
                                 target_budget_line_id: str, **overrides) -> dict:
    defaults = {
        "source_expenditure_id": source_expenditure_id,
        "target_award_id": target_award_id,
        "target_budget_line_id": target_budget_line_id,
        "justification": "reallocate travel to the correct award",
    }
    defaults.update(overrides)
    return defaults


def create_effort_cycle_payload(**overrides) -> dict:
    defaults = {
        "cycle_code": "2026-H1",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "cycle_months": 6,
    }
    defaults.update(overrides)
    return defaults


def create_subaward_payload(award_id: str, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "subrecipient_name": "Sub U",
        "total_subaward_cents": 1_000_000,
        "risk_rating": "LOW",
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_subaward_invoice_payload(subaward_id: str, **overrides) -> dict:
    defaults = {
        "subaward_id": subaward_id,
        "invoice_number": "INV-1",
        "period_start": "2026-02-01T00:00:00Z",
        "period_end": "2026-03-31T00:00:00Z",
        "current_period_direct_cents": 100_000,
        "current_period_f_and_a_cents": 5_000,
    }
    defaults.update(overrides)
    return defaults


def create_report_requirement_payload(award_id: str, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "report_type": "MILESTONE",
        "due_date": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_drawdown_request_payload(award_id: str, amount_cents: int,
                                    expected_award_version: int, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "amount_cents": amount_cents,
        "expected_award_version": expected_award_version,
    }
    defaults.update(overrides)
    return defaults


def create_receivable_payload(award_id: str, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_modification_request_payload(award_id: str, expected_award_version: int,
                                        **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "mod_type": "NO_COST_EXTENSION",
        "extension_months": 6,
        "justification": "no-cost extension request justification",
        "expected_award_version": expected_award_version,
    }
    defaults.update(overrides)
    # None means "omit this optional field entirely" (e.g. extension_months on
    # a REBUDGET request, rebudget_lines on an NCE request).
    return {k: v for k, v in defaults.items() if v is not None}
