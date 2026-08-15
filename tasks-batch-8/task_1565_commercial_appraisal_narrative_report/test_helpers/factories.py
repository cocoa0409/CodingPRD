"""Payload factories — one per entity, input fields only (PRD §3).

Defaults follow the canonical fixtures used across the workflows: a STANDARD
tier OFFICE engagement of 30,000 sf for FINANCING with a 30-day turnaround,
and a full-year 2025 operating statement.
"""

DEFAULTS = {
    "CLIENT_NAME": "Apex Bank",
    "CLIENT_TYPE": "LENDER",
    "AUTHOR_NAME": "Ann Author",
    "REVIEWER_NAME": "Rob Reviewer",
    "SIGNER_NAME": "Mary Mai",
    "DESIGNATION": "CERTIFIED_GENERAL",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLIENT_NAME"],
        "client_type": DEFAULTS["CLIENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_appraiser_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["AUTHOR_NAME"],
        "designation": DEFAULTS["DESIGNATION"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(client_id: str, author_appraiser_id: str,
                              reviewer_appraiser_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "author_appraiser_id": author_appraiser_id,
        "reviewer_appraiser_id": reviewer_appraiser_id,
        "property_address": "100 Main St",
        "property_type": "OFFICE",
        "building_sf": 30000,
        "intended_use": "FINANCING",
        "intended_users": [DEFAULTS["CLIENT_NAME"]],
        "requested_turnaround_days": 30,
        "planned_approach_count": 1,
        "fee_schedule": "TIERED",
        "is_contingent_fee": False,
    }
    defaults.update(overrides)
    return defaults


def create_data_submission_payload(**overrides) -> dict:
    defaults = {
        "submission_type": "OPERATING_STATEMENT",
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-12-31T00:00:00Z",
        "scheduled_gross_rent_cents": 12000000,
        "vacancy_loss_cents": 600000,
        "expense_reimbursements_cents": 300000,
        "operating_expenses_cents": 4000000,
    }
    defaults.update(overrides)
    return defaults


def create_approach_payload(**overrides) -> dict:
    defaults = {
        "approach_type": "INCOME",
        "weight_pct": 100.00,
    }
    defaults.update(overrides)
    return defaults


def create_comparable_payload(**overrides) -> dict:
    defaults = {
        "address": "200 Oak Ave",
        "sale_date": "2026-03-01T00:00:00Z",
        "sale_price_cents": 10000000,
        "noi_at_sale_cents": 650000,
        "size_sf": 5000,
        "adjustment_pct": 0,
        "selected_for_support": True,
    }
    defaults.update(overrides)
    return defaults


def create_revision_request_payload(**overrides) -> dict:
    defaults = {
        "category": "CLARIFICATION",
        "requested_change": "Clarify the zoning paragraph",
    }
    defaults.update(overrides)
    return defaults
