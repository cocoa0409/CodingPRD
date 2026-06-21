"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""

DEFAULTS = {
    "NOFO_NUMBER": "NOFO-2026-TEST-001",
    "ORG_NAME": "Test Grantee Org",
    "REQUESTED_AMOUNT_CENTS": 30_000_000,
    "FEDERAL_SHARE_PCT": 0.80,
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-12-31T00:00:00Z",
}


def create_application_payload(**overrides) -> dict:
    """POST /applications — required: nofo_number, applicant_org_name,
    requested_amount_cents, period_start_date, period_end_date.
    Optional: federal_share_pct (defaults server-side to 0.80),
    supersedes_application_id (defaults null)."""
    payload = {
        "nofo_number": DEFAULTS["NOFO_NUMBER"],
        "applicant_org_name": DEFAULTS["ORG_NAME"],
        "requested_amount_cents": DEFAULTS["REQUESTED_AMOUNT_CENTS"],
        "federal_share_pct": DEFAULTS["FEDERAL_SHARE_PCT"],
        "period_start_date": DEFAULTS["PERIOD_START"],
        "period_end_date": DEFAULTS["PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def create_indirect_cost_rate_payload(award_id, expected_award_version, **overrides) -> dict:
    """POST /indirect-cost-rates — required: award_id, rate_type, expected_award_version.
    Conditional: negotiated_rate required when rate_type == NEGOTIATED. base_type defaults MTDC."""
    payload = {
        "award_id": award_id,
        "rate_type": "NEGOTIATED",
        "negotiated_rate": 0.30,
        "base_type": "MTDC",
        "expected_award_version": expected_award_version,
    }
    payload.update(overrides)
    return payload


def create_subaward_payload(award_id, **overrides) -> dict:
    """POST /subawards — required: award_id, subrecipient_name, subaward_amount_cents.
    Optional: risk_tier (defaults LOW)."""
    payload = {
        "award_id": award_id,
        "subrecipient_name": "Test Subrecipient",
        "subaward_amount_cents": 2_000_000,
        "risk_tier": "LOW",
    }
    payload.update(overrides)
    return payload


def create_restricted_fund_payload(award_id, **overrides) -> dict:
    """POST /restricted-funds — required: award_id, category, budgeted_cents, priority_order."""
    payload = {
        "award_id": award_id,
        "category": "PERSONNEL",
        "budgeted_cents": 10_000_000,
        "priority_order": 1,
    }
    payload.update(overrides)
    return payload


def create_drawdown_payload(award_id, amount_cents, allocation_plan, **overrides) -> dict:
    """POST /drawdowns — required: award_id, amount_cents, allocation_plan."""
    payload = {
        "award_id": award_id,
        "amount_cents": amount_cents,
        "allocation_plan": allocation_plan,
    }
    payload.update(overrides)
    return payload


def create_financial_report_payload(award_id, **overrides) -> dict:
    """POST /financial-reports — required: award_id, period_label, report_basis, direct_cost_lines.
    Optional: disallowed_cents (defaults 0)."""
    payload = {
        "award_id": award_id,
        "period_label": "FY2026-Q1",
        "report_basis": "INTERIM",
        "direct_cost_lines": [{"category": "PERSONNEL", "amount_cents": 1_000_000}],
    }
    payload.update(overrides)
    return payload


def create_progress_report_payload(award_id, **overrides) -> dict:
    """POST /progress-reports — required: award_id, period_label, milestones_met, milestones_planned."""
    payload = {
        "award_id": award_id,
        "period_label": "FY2026-Q1",
        "milestones_met": 3,
        "milestones_planned": 5,
    }
    payload.update(overrides)
    return payload


def create_single_audit_payload(award_id, **overrides) -> dict:
    """POST /single-audits — required: award_id, fiscal_year, federal_expenditures_cents."""
    payload = {
        "award_id": award_id,
        "fiscal_year": 2026,
        "federal_expenditures_cents": 10_000_000,
    }
    payload.update(overrides)
    return payload


def create_finding_payload(**overrides) -> dict:
    """POST /single-audits/{id}/findings — required: severity. Optional: questioned_cost_cents (defaults 0)."""
    payload = {
        "severity": "MATERIAL_WEAKNESS",
        "questioned_cost_cents": 0,
    }
    payload.update(overrides)
    return payload
