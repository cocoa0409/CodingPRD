"""Payload factories — one per entity, input fields only."""

import itertools

_counter = itertools.count(1)


def unique_email(prefix: str = "sub") -> str:
    """Emails are unique across subscribers (PRD §3.1)."""
    return f"{prefix}-{next(_counter)}@example.com"


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "ULTIMATE",
        "monthly_fee_cents": 3499,
        "insurance_limit_cents": 500000,
        "max_family_members": 4,
        "child_monitoring_included": True,
        "bureau_scope": "TRI",
        "min_specialist_tier": "TIER1",
    }
    defaults.update(overrides)
    return defaults


def enroll_subscriber_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Subscriber",
        "date_of_birth": "1990-01-01",
        "ssn_last4": "1234",
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_family_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Dependent",
        "date_of_birth": "2015-05-05",
        "ssn_last4": "4321",
        "relationship": "ADULT",
    }
    defaults.update(overrides)
    return defaults


def create_specialist_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Specialist",
        "tier": "TIER2",
        "max_caseload": 3,
        "max_concurrent_engagements": 1,
    }
    defaults.update(overrides)
    return defaults


def create_alert_payload(subscriber_id: str, **overrides) -> dict:
    defaults = {
        "subscriber_id": subscriber_id,
        "alert_type": "DARK_WEB",
        "severity": "LOW",
        "source_detail": "credentials seen in breach dump",
    }
    defaults.update(overrides)
    return defaults


def create_wallet_item_payload(**overrides) -> dict:
    defaults = {"item_type": "CREDIT_CARD", "issuer": "Test Bank", "last4": "9876"}
    defaults.update(overrides)
    return defaults


def create_thaw_window_payload(window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "window_start": window_start,
        "window_end": window_end,
        "purpose": "MORTGAGE_APPLICATION",
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(
    specialist_id: str,
    case_id: str,
    window_start: str,
    window_end: str,
    expected_specialist_version: int,
    **overrides,
) -> dict:
    defaults = {
        "specialist_id": specialist_id,
        "case_id": case_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_specialist_version": expected_specialist_version,
    }
    defaults.update(overrides)
    return defaults


def expense(category: str, amount_cents: int, documented: bool = True) -> dict:
    """One line item of an InsuranceClaim.expenses array (PRD §3.7)."""
    return {"category": category, "amount_cents": amount_cents, "documented": documented}


def create_claim_payload(
    case_id: str, expected_case_version: int, expenses: list, **overrides
) -> dict:
    defaults = {
        "case_id": case_id,
        "expected_case_version": expected_case_version,
        "expenses": expenses,
    }
    defaults.update(overrides)
    return defaults


# The six-line expense array used by the dual-variant and rounding scenarios.
SIX_LINE_EXPENSES = [
    expense("LEGAL_FEES", 120000, True),
    expense("LOST_WAGES", 333333, True),
    expense("TRAVEL", 4501, True),
    expense("TRAVEL", 4501, True),
    expense("CHILDCARE", 30001, False),
    expense("NOTARY", 2501, True),
]