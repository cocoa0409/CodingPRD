"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. Computed and
system-managed fields (status, trust_balance_cents, screening outputs, etc.)
are never sent.
"""

DEFAULTS = {
    "MANAGEMENT_FEE_PCT": 0.08,
    "MARKET_RENT_CENTS": 200000,
    "MONTHLY_RENT_CENTS": 200000,
    "ANNUAL_INCOME_CENTS": 12000000,
    "CREDIT_SCORE": 700,
    "REQUESTED_RENT_CENTS": 200000,
}

_email_counter = [0]


def _unique_email(prefix: str) -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Acme Holdings",
        "email": _unique_email("owner"),
        "management_fee_pct": DEFAULTS["MANAGEMENT_FEE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "name": "Maple Court",
        "state_code": "TX",
        "address": "1 Maple St",
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "label": "Apt 1A",
        "market_rent_cents": DEFAULTS["MARKET_RENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Pat Renter",
        "email": _unique_email("applicant"),
        "unit_id": unit_id,
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
        "credit_score": DEFAULTS["CREDIT_SCORE"],
        "requested_rent_cents": DEFAULTS["REQUESTED_RENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(unit_id: str, applicant_id: str = None, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "start_date": "2026-06-01",
        "end_date": "2027-06-01",
        "monthly_rent_cents": DEFAULTS["MONTHLY_RENT_CENTS"],
    }
    if applicant_id is not None:
        defaults["applicant_id"] = applicant_id
    defaults.update(overrides)
    return defaults


def create_rent_charge_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "period_label": "2026-06",
        "due_date": "2026-06-01",
        "amount_cents": DEFAULTS["MONTHLY_RENT_CENTS"],
        "charge_type": "RENT",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(lease_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "amount_cents": amount_cents,
        "received_date": "2026-06-10",
    }
    defaults.update(overrides)
    return defaults


def create_security_deposit_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "collected_cents": 200000,
        "collected_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "category": "PLUMBING",
        "description": "Leak under sink",
    }
    defaults.update(overrides)
    return defaults


def create_eviction_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "reason": "NONPAYMENT",
        "notice_date": "2026-06-10",
    }
    defaults.update(overrides)
    return defaults


def create_owner_statement_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "period_label": "2026-06",
        "basis": "CASH",
    }
    defaults.update(overrides)
    return defaults


def create_turnover_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "opened_date": "2026-07-02",
        "target_ready_date": "2026-07-20",
    }
    defaults.update(overrides)
    return defaults
