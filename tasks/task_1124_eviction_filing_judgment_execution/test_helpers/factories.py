"""Payload factories — one per creatable resource, input fields only."""

from .constants import (
    CURE_DAYS,
    DEFENDANT_SURCHARGE_CENTS,
    FILING_FEE_TIERS,
    JURY_FEE_CENTS,
    TEST_DEFAULTS,
    VARIANT_ADJ,
    WRIT_FEE,
)

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_landlord_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"L{n} LLC",
        "contact_email": f"l{n}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(landlord_id, jurisdiction_code="CA", **overrides) -> dict:
    n = _seq()
    defaults = {
        "landlord_id": landlord_id,
        "jurisdiction_code": jurisdiction_code,
        "street_address": TEST_DEFAULTS["STREET_ADDRESS"],
        "unit_label": f"U{n}",
    }
    defaults.update(overrides)
    return defaults


def create_tenancy_payload(unit_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "unit_id": unit_id,
        "tenant_full_name": f"T{n}",
        "monthly_rent_cents": TEST_DEFAULTS["MONTHLY_RENT_CENTS"],
        "lease_start_date": TEST_DEFAULTS["LEASE_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(tenancy_id, case_reason="NONPAYMENT", **overrides) -> dict:
    defaults = {"tenancy_id": tenancy_id, "case_reason": case_reason}
    defaults.update(overrides)
    return defaults


def create_notice_payload(case_version, notice_type="PAY_OR_QUIT", **overrides) -> dict:
    defaults = {
        "notice_type": notice_type,
        "served_on": "2026-05-02",
        "expected_case_version": case_version,
    }
    if notice_type == "PAY_OR_QUIT" and "claimed_rent_owed_cents" not in overrides:
        defaults["claimed_rent_owed_cents"] = TEST_DEFAULTS["CLAIMED_AMOUNT_CENTS"]
    if notice_type == "CURE_OR_QUIT" and "violation_description" not in overrides:
        defaults["violation_description"] = "unauthorized pet"
    defaults.update(overrides)
    return defaults


def create_filing_package_payload(**overrides) -> dict:
    defaults = {
        "claimed_amount_cents": TEST_DEFAULTS["CLAIMED_AMOUNT_CENTS"],
        "defendant_names": [TEST_DEFAULTS["DEFENDANT_NAME"]],
        "jury_demanded": False,
        "efiled": False,
    }
    defaults.update(overrides)
    return defaults


def compute_filing_fee_cents(
    jurisdiction_code,
    claimed_amount_cents,
    defendant_names,
    jury_demanded,
    efiled,
) -> int:
    """PRD 3.3 fee formula: tiered base (<= at ceilings) + per-defendant
    surcharge + jury fee + variant adjustment, floored at zero."""
    base = None
    for ceiling, fee in FILING_FEE_TIERS[jurisdiction_code]:
        if ceiling is None or claimed_amount_cents <= ceiling:
            base = fee
            break
    fee = base + DEFENDANT_SURCHARGE_CENTS * len(defendant_names)
    if jury_demanded:
        fee += JURY_FEE_CENTS
    fee += VARIANT_ADJ["ELECTRONIC" if efiled else "STANDARD"]
    return max(0, fee)


def create_fee_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_review_payload(decision="ACCEPT", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_service_attempt_payload(**overrides) -> dict:
    defaults = {
        "defendant_name": TEST_DEFAULTS["DEFENDANT_NAME"],
        "method": "PERSONAL",
        "result": "SERVED",
        "served_at": "2026-06-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(**overrides) -> dict:
    defaults = {
        "courtroom": TEST_DEFAULTS["COURTROOM"],
        "start_at": "2026-06-15T10:00:00Z",
        "end_at": "2026-06-15T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_answer_payload(**overrides) -> dict:
    defaults = {
        "defense_codes": ["HABITABILITY"],
        "mediation_requested": True,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "mediator_id": TEST_DEFAULTS["MEDIATOR"],
        "session_date": "2026-06-18",
    }
    defaults.update(overrides)
    return defaults


def create_outcome_payload(outcome="FAILED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_judgment_payload(**overrides) -> dict:
    defaults = {
        "possession_granted": True,
        "rent_awarded_cents": 50000,
        "damages_cents": 0,
        "late_fee_cents": 0,
        "court_costs_cents": 0,
        "oldest_unpaid_due_date": "2026-06-20",
    }
    defaults.update(overrides)
    return defaults


def create_writ_payload(jurisdiction_code="CA", **overrides) -> dict:
    defaults = {"writ_fee_paid_cents": WRIT_FEE[jurisdiction_code]}
    defaults.update(overrides)
    return defaults


def create_schedule_lockout_payload(deputy_id=None, **overrides) -> dict:
    defaults = {
        "deputy_id": deputy_id or TEST_DEFAULTS["DEPUTY"],
        "window_start": "2026-06-26T09:00:00Z",
        "window_end": "2026-06-26T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_collection_entry_payload(entry_type="PAYMENT", amount_cents=1000, **overrides) -> dict:
    defaults = {"entry_type": entry_type, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_rental_history_report_payload(report_type="FILING", **overrides) -> dict:
    defaults = {"report_type": report_type}
    defaults.update(overrides)
    return defaults


__all__ = [name for name in dir() if name.startswith(("create_", "compute_"))]
