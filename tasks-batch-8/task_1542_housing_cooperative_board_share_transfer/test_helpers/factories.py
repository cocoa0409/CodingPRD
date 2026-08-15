"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COOP_NAME": "Test Cooperative",
    "COOP_ADDRESS": "100 Main Street, New York, NY",
    "MORTGAGE_PRINCIPAL_CENTS": 100000000,
    "MORTGAGE_RATE_BPS": 500,
    "UNIT_LABEL": "1A",
    "SHARES_ALLOCATED": 100,
    "FULL_NAME": "Pat Shareholder",
    "EMAIL": "pat@example.com",
    "FISCAL_YEAR": 2026,
    "ANNUAL_BUDGET_CENTS": 1200000,
    "ALLOCATION_METHOD": "PRO_RATA_SHARES",
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-08-01T00:00:00Z",
    "BUYER_FULL_NAME": "Blair Buyer",
    "BUYER_EMAIL": "blair.buyer@example.com",
    "GROSS_SALE_PRICE_CENTS": 50000000,
    "FINANCING_PERCENT_BPS": 5000,
    "DEBT_TO_INCOME_BPS": 1000,
    "POST_CLOSING_LIQUIDITY_CENTS": 99999999,
    "SUBTENANT_NAME": "Sam Subtenant",
    "SCOPE_DESCRIPTION": "Kitchen renovation",
    "CONTRACTOR_NAME": "Ace Contracting",
    "CONTRACTOR_INSURANCE_CENTS": 200000000,
    "CONTRACTOR_BID_CENTS": 5000000,
    "MEETING_KIND": "ANNUAL",
    "MEETING_SCHEDULED_AT": "2026-08-20T18:00:00Z",
}


def create_cooperative_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["COOP_NAME"],
        "address": DEFAULTS["COOP_ADDRESS"],
        "underlying_mortgage_principal_cents": DEFAULTS["MORTGAGE_PRINCIPAL_CENTS"],
        "underlying_mortgage_rate_bps": DEFAULTS["MORTGAGE_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_label": DEFAULTS["UNIT_LABEL"],
        "shares_allocated": DEFAULTS["SHARES_ALLOCATED"],
    }
    defaults.update(overrides)
    return defaults


def create_shareholder_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_share_ledger_entry_payload(unit_id, shareholder_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "shareholder_id": shareholder_id,
        "shares_held": DEFAULTS["SHARES_ALLOCATED"],
    }
    defaults.update(overrides)
    return defaults


def create_charge_schedule_payload(expected_cooperative_version, **overrides) -> dict:
    defaults = {
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "annual_operating_budget_cents": DEFAULTS["ANNUAL_BUDGET_CENTS"],
        "allocation_method": DEFAULTS["ALLOCATION_METHOD"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
        "expected_cooperative_version": expected_cooperative_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(shareholder_id, amount_cents, **overrides) -> dict:
    defaults = {
        "shareholder_id": shareholder_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_arrears_action_payload(shareholder_id, action_type, **overrides) -> dict:
    defaults = {
        "shareholder_id": shareholder_id,
        "action_type": action_type,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_application_payload(unit_id, seller_shareholder_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "seller_shareholder_id": seller_shareholder_id,
        "buyer_full_name": DEFAULTS["BUYER_FULL_NAME"],
        "buyer_email": DEFAULTS["BUYER_EMAIL"],
        "gross_sale_price_cents": DEFAULTS["GROSS_SALE_PRICE_CENTS"],
        "financing_percent_bps": DEFAULTS["FINANCING_PERCENT_BPS"],
        "debt_to_income_bps": DEFAULTS["DEBT_TO_INCOME_BPS"],
        "post_closing_liquidity_cents": DEFAULTS["POST_CLOSING_LIQUIDITY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_schedule_interview_payload(**overrides) -> dict:
    defaults = {
        "scheduled_at": "2026-08-15T14:00:00Z",
        "panel_member_user_ids": ["bm-panel-1", "bm-panel-2"],
    }
    defaults.update(overrides)
    return defaults


def create_resolution_payload(resolution_kind, subject_entity_kind, subject_entity_id,
                              **overrides) -> dict:
    defaults = {
        "resolution_kind": resolution_kind,
        "subject_entity_kind": subject_entity_kind,
        "subject_entity_id": subject_entity_id,
        "payload_json": {},
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(vote_choice="FOR") -> dict:
    return {"vote_choice": vote_choice}


def create_sublet_payload(unit_id, shareholder_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "shareholder_id": shareholder_id,
        "subtenant_name": DEFAULTS["SUBTENANT_NAME"],
        "sublet_start_date": "2027-01-01T00:00:00Z",
        "sublet_end_date": "2028-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_alteration_payload(unit_id, shareholder_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "shareholder_id": shareholder_id,
        "scope_description": DEFAULTS["SCOPE_DESCRIPTION"],
        "contractor_name": DEFAULTS["CONTRACTOR_NAME"],
        "contractor_insurance_cents": DEFAULTS["CONTRACTOR_INSURANCE_CENTS"],
        "work_window_start": "2026-09-01T00:00:00Z",
        "work_window_end": "2026-10-01T00:00:00Z",
        "contractor_bid_cents": DEFAULTS["CONTRACTOR_BID_CENTS"],
        "involves_wet_over_dry": False,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_payload(**overrides) -> dict:
    defaults = {
        "meeting_kind": DEFAULTS["MEETING_KIND"],
        "scheduled_at": DEFAULTS["MEETING_SCHEDULED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_ballot_payload(shareholder_id, **overrides) -> dict:
    defaults = {
        "shareholder_id": shareholder_id,
        "ballot_kind": "IN_PERSON",
        "candidate_user_ids": ["cand-1"],
    }
    defaults.update(overrides)
    return defaults
