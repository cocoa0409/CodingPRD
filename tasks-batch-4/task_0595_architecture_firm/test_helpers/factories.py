"""Payload factories — one per entity, request-input fields only."""
from .constants import TEST_DEFAULTS


def create_staff_payload(**overrides) -> dict:
    payload = {
        "full_name": "Pat Manager",
        "title": "PROJECT_MANAGER",
        "billing_rate_cents_per_hour": TEST_DEFAULTS["PM_BILLING_RATE"],
        "cost_rate_cents_per_hour": TEST_DEFAULTS["PM_COST_RATE"],
    }
    payload.update(overrides)
    return payload


def create_architect_payload(**overrides) -> dict:
    payload = {
        "full_name": "Avery Architect",
        "title": "ARCHITECT",
        "billing_rate_cents_per_hour": TEST_DEFAULTS["ARCH_BILLING_RATE"],
        "cost_rate_cents_per_hour": TEST_DEFAULTS["ARCH_COST_RATE"],
    }
    payload.update(overrides)
    return payload


def create_consultant_payload(**overrides) -> dict:
    payload = {
        "name": "Beam & Bolt",
        "discipline": "STRUCTURAL",
        "concurrent_review_capacity": 1,
    }
    payload.update(overrides)
    return payload


def create_project_payload(project_manager_staff_id: str, **overrides) -> dict:
    payload = {
        "project_number": "P-001",
        "name": "Test Project",
        "client_rep_user_id": TEST_DEFAULTS["CLIENT_REP"],
        "project_manager_staff_id": project_manager_staff_id,
        "labor_budget_cents": TEST_DEFAULTS["LABOR_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_contract_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "fee_basis": "PERCENT_OF_CONSTRUCTION",
        "review_clock_basis": "CALENDAR_DAYS",
        "construction_cost_estimate_cents": TEST_DEFAULTS["CONSTRUCTION_COST_CENTS"],
        "fee_rate_bp": TEST_DEFAULTS["FEE_RATE_BP"],
    }
    payload.update(overrides)
    return payload


def create_hourly_contract_payload(project_id: str, not_to_exceed_cents: int, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "fee_basis": "HOURLY",
        "review_clock_basis": "CALENDAR_DAYS",
        "not_to_exceed_cents": not_to_exceed_cents,
    }
    payload.update(overrides)
    return payload


DEFAULT_MILESTONE_DUE = {
    "SD": "2026-08-01T00:00:00Z",
    "DD": "2026-09-01T00:00:00Z",
    "CD": "2026-10-01T00:00:00Z",
    "CA": "2026-12-01T00:00:00Z",
}


def create_phase_payload(project_id: str, phase_code: str, weight_bp: int, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "phase_code": phase_code,
        "weight_bp": weight_bp,
        "milestone_name": f"{phase_code} set",
        "milestone_due_at": DEFAULT_MILESTONE_DUE[phase_code],
    }
    payload.update(overrides)
    return payload


def create_drawing_payload(phase_id: str, **overrides) -> dict:
    payload = {"phase_id": phase_id, "sheet_number": "A-101", "title": "Ground floor plan"}
    payload.update(overrides)
    return payload


def create_time_entry_payload(phase_id: str, staff_member_id: str, **overrides) -> dict:
    payload = {
        "phase_id": phase_id,
        "staff_member_id": staff_member_id,
        "start_utc": "2026-05-04T09:00:00Z",
        "end_utc": "2026-05-04T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_expense_payload(project_id: str, staff_member_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "staff_member_id": staff_member_id,
        "category": "PRINTING",
        "amount_cents": 100_000,
    }
    payload.update(overrides)
    return payload


def create_rfi_payload(project_id: str, **overrides) -> dict:
    payload = {"project_id": project_id, "subject": "Confirm curtain wall mullion spacing"}
    payload.update(overrides)
    return payload


def create_submittal_payload(project_id: str, consultant_firm_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "consultant_firm_id": consultant_firm_id,
        "spec_section": "05 12 00",
    }
    payload.update(overrides)
    return payload


def create_change_order_payload(contract_id: str, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "title": "Additional lobby study",
        "co_type": "ADDITIONAL_SERVICE",
        "fee_delta_cents": 2_000_000,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(contract_id: str, expected_contract_version: int, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "period_end": "2026-06-30T00:00:00Z",
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def create_permit_review_payload(phase_id: str, **overrides) -> dict:
    payload = {
        "phase_id": phase_id,
        "jurisdiction_name": "City of Ashford",
        "permit_type": "BUILDING",
    }
    payload.update(overrides)
    return payload


def create_field_report_payload(project_id: str, staff_member_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "staff_member_id": staff_member_id,
        "visit_date": "2026-05-20T14:00:00Z",
        "weather": "Clear, 18C",
        "observations": "Two hairline cracks in the slab pour.",
        "deficiency_count": 0,
    }
    payload.update(overrides)
    return payload


def state_payload(to_status: str, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return payload
