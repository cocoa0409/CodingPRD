"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_funder_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Funder-{n}",
        "funder_type": "FOUNDATION",
        "contact_email": f"funder{n}@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(funder_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "funder_id": funder_id,
        "award_number": f"AW-{n}",
        "title": f"Grant {n}",
        "award_amount_cents": 100_000_000,
        "start_date": "2026-06-01",
        "end_date": "2027-05-31",
        "reporting_frequency": "QUARTERLY",
    }
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(**overrides) -> dict:
    defaults = {
        "category": "PERSONNEL",
        "budgeted_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(**overrides) -> dict:
    defaults = {
        "fund_type": "UNRESTRICTED",
        "allocated_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "expense_date": "2026-06-20",
        "vendor": f"Vendor-{n}",
        "description": f"Expense {n}",
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(budget_line_id, fund_id, amount_cents, **overrides) -> dict:
    defaults = {
        "budget_line_id": budget_line_id,
        "fund_id": fund_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def outcome_entry(**overrides) -> dict:
    defaults = {
        "metric_name": "people_served",
        "target_value": 100,
        "actual_value": 90,
        "unit": "persons",
    }
    defaults.update(overrides)
    return defaults


def report_edit_payload(**overrides) -> dict:
    defaults = {
        "narrative_draft": "Narrative for the period.",
        "outcome_entries": [outcome_entry()],
    }
    defaults.update(overrides)
    return defaults


def create_variance_explanation_payload(budget_line_id, **overrides) -> dict:
    defaults = {
        "budget_line_id": budget_line_id,
        "explanation_text": "Variance explained by program timing.",
    }
    defaults.update(overrides)
    return defaults


def create_match_contribution_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "contribution_type": "CASH",
        "source_name": f"Donor-{n}",
        "valuation_basis": "ACTUAL_COST",
        "documented_value_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_modification_request_payload(**overrides) -> dict:
    defaults = {
        "request_type": "NO_COST_EXTENSION",
        "justification": "Program delays require more time.",
        "requested_end_date": "2027-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_audit_engagement_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "engagement_type": "SITE_VISIT",
        "auditor_org": f"AudCo-{n}",
        "scheduled_start": "2026-07-01T00:00:00Z",
        "scheduled_end": "2026-07-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(**overrides) -> dict:
    defaults = {
        "severity": "OBSERVATION",
        "description": "Finding description.",
    }
    defaults.update(overrides)
    return defaults
