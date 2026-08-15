"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Acme Builders LLC",
    "CONTACT_EMAIL": "ops@acme.example",
    "ENTITY_TYPE": "LLC",
    "COMMITMENT_CENTS": 100_000_000,
    "RATE_BPS": 1200,
    "RESERVE_CENTS": 0,
    "MATURITY_DATE": "2027-12-31",
    "COST_CODE": "SITE",
    "DESCRIPTION": "Site work",
    "LINE_AMOUNT_CENTS": 40_000_000,
    "PERIOD_START": "2026-03-01",
    "PERIOD_END": "2026-03-31",
    "REQUESTED_CENTS": 10_000_000,
    "PARTY_NAME": "Acme GC",
    "DOC_DATE": "2026-03-25",
    "SCHEDULED_DATE": "2026-03-20",
    "COMPLETED_DATE": "2026-03-21",
    "JUSTIFICATION": "Budget rebalance",
    "REASON": "Milestone release",
}


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "entity_type": DEFAULTS["ENTITY_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(borrower_id, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "commitment_amount_cents": DEFAULTS["COMMITMENT_CENTS"],
        "interest_rate_annual_bps": DEFAULTS["RATE_BPS"],
        "interest_reserve_initial_cents": DEFAULTS["RESERVE_CENTS"],
        "maturity_date": DEFAULTS["MATURITY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "cost_code": DEFAULTS["COST_CODE"],
        "description": DEFAULTS["DESCRIPTION"],
        "original_amount_cents": DEFAULTS["LINE_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "period_start_date": DEFAULTS["PERIOD_START"],
        "period_end_date": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_draw_line_item_payload(draw_id, budget_line_id, **overrides) -> dict:
    defaults = {
        "draw_id": draw_id,
        "budget_line_id": budget_line_id,
        "line_type": "WORK_COMPLETED",
        "requested_cents": DEFAULTS["REQUESTED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_draw_document_payload(draw_id, **overrides) -> dict:
    defaults = {
        "draw_id": draw_id,
        "doc_type": "INVOICE",
        "party_name": DEFAULTS["PARTY_NAME"],
        "amount_cents": DEFAULTS["REQUESTED_CENTS"],
        "doc_date": DEFAULTS["DOC_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(**overrides) -> dict:
    defaults = {
        "percent_complete_reported": 50.00,
        "completed_date": DEFAULTS["COMPLETED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def review_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_reallocation_payload(loan_id, from_budget_line_id, to_budget_line_id,
                                expected_loan_version, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "from_budget_line_id": from_budget_line_id,
        "to_budget_line_id": to_budget_line_id,
        "amount_cents": 1_000_000,
        "justification": DEFAULTS["JUSTIFICATION"],
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_retainage_release_payload(loan_id, budget_line_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "budget_line_id": budget_line_id,
        "amount_cents": 500_000,
        "reason": DEFAULTS["REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_conversion_review_payload(loan_id, **overrides) -> dict:
    payload = {"loan_id": loan_id}
    payload.update(overrides)
    return payload


def interest_accrual_payload(period_start_date, period_end_date) -> dict:
    return {
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
