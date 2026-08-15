"""Payload factories — one per creatable resource, input fields only."""
from .constants import TEST_DEFAULTS


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["DEPARTMENT_NAME"],
        "college_name": TEST_DEFAULTS["COLLEGE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_inventor_payload(department_id, **overrides) -> dict:
    defaults = {
        "full_name": "Ada Lovelace",
        "email": "ada@uni.edu",
        "department_id": department_id,
        "appointment_type": "FACULTY",
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(**overrides) -> dict:
    defaults = {
        "title": "Tensor Compiler",
        "description": "Novel compiler",
        "funding_source": "NON_FEDERAL",
    }
    defaults.update(overrides)
    return defaults


def add_roster_entry_payload(inventor_id, share_bp=10000, **overrides) -> dict:
    defaults = {"inventor_id": inventor_id, "share_bp": share_bp}
    defaults.update(overrides)
    return defaults


def finalize_payload(expected_disclosure_version) -> dict:
    return {"expected_disclosure_version": expected_disclosure_version}


def assessment_payload(patentability_rating="HIGH", market_rating="HIGH",
                       **overrides) -> dict:
    defaults = {
        "patentability_rating": patentability_rating,
        "market_rating": market_rating,
    }
    defaults.update(overrides)
    return defaults


def decision_payload(decision="PURSUE_PATENT", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def dispute_payload(reason="Share allocation contested", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(adjusted_shares, resolution_notes="Resolved",
                            **overrides) -> dict:
    defaults = {
        "resolution_notes": resolution_notes,
        "adjusted_shares": adjusted_shares,
    }
    defaults.update(overrides)
    return defaults


def create_patent_application_payload(**overrides) -> dict:
    defaults = {
        "docket_number": "DKT-1",
        "application_type": "PROVISIONAL",
        "filed_date": "2026-02-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cost_payload(amount_cents, cost_type="ATTORNEY_FEE",
                        incurred_date="2026-03-01T00:00:00Z", **overrides) -> dict:
    defaults = {
        "cost_type": cost_type,
        "amount_cents": amount_cents,
        "incurred_date": incurred_date,
    }
    defaults.update(overrides)
    return defaults


def create_startup_payload(**overrides) -> dict:
    defaults = {
        "name": "SpinCo",
        "founded_date": "2026-02-01T00:00:00Z",
        "equity_model": "FIXED",
    }
    defaults.update(overrides)
    return defaults


def create_coi_plan_payload(inventor_id, **overrides) -> dict:
    defaults = {
        "inventor_id": inventor_id,
        "coverage_start": TEST_DEFAULTS["COI_COVERAGE_START"],
        "coverage_end": TEST_DEFAULTS["COI_COVERAGE_END"],
        "management_plan_text": "Recusal plan",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "licensee_name": "Acme Corp",
        "exclusivity": "NON_EXCLUSIVE",
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
        "expiration_date": TEST_DEFAULTS["EXPIRATION_DATE"],
        "royalty_rate_bp": TEST_DEFAULTS["ROYALTY_RATE_BP"],
        "minimum_annual_royalty_cents": 0,
        "upfront_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def execute_license_payload(expected_license_version) -> dict:
    return {"expected_license_version": expected_license_version}


def create_milestone_payload(due_date="2026-06-01T00:00:00Z", **overrides) -> dict:
    defaults = {
        "description": "First sale",
        "due_date": due_date,
        "amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_report_payload(reported_sales_cents, **overrides) -> dict:
    defaults = {
        "period_start": TEST_DEFAULTS["REPORT_PERIOD_START"],
        "period_end": TEST_DEFAULTS["REPORT_PERIOD_END"],
        "reported_sales_cents": reported_sales_cents,
    }
    defaults.update(overrides)
    return defaults


def approve_distribution_payload(expected_distribution_version) -> dict:
    return {"expected_distribution_version": expected_distribution_version}


def create_compliance_report_payload(report_type="INITIAL_DISCLOSURE",
                                     **overrides) -> dict:
    defaults = {"report_type": report_type}
    defaults.update(overrides)
    return defaults


def agency_response_payload(outcome="ACCEPTED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
