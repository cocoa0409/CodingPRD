"""Payload factories — one per creatable resource, input fields only (PRD §4)."""

from .constants import STD_RATE, STD_TERM


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_term_payload(**overrides) -> dict:
    defaults = dict(STD_TERM)
    defaults.update(overrides)
    return defaults


def create_tuition_rate_payload(term_id: str = "PLACEHOLDER-TERM", **overrides) -> dict:
    defaults = dict(STD_RATE)
    defaults["term_id"] = term_id
    defaults.update(overrides)
    return defaults


def create_student_payload(
    full_name: str = "Test Student",
    external_ref: str = "S-TEST",
    residency_status: str = "IN_STATE",
    level: str = "UNDERGRADUATE",
    **overrides,
) -> dict:
    defaults = {
        "full_name": full_name,
        "external_ref": external_ref,
        "residency_status": residency_status,
        "level": level,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(
    student_id: str,
    term_id: str,
    credit_hours: int = 12,
    effective_date: str = "2026-08-25",
    **overrides,
) -> dict:
    defaults = {
        "student_id": student_id,
        "term_id": term_id,
        "credit_hours": credit_hours,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(
    account_id: str,
    amount_cents: int = 50000,
    method: str = "CARD",
    **overrides,
) -> dict:
    defaults = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(
    account_id: str,
    kind: str = "WAIVER",
    awarded_cents: int = 50000,
    **overrides,
) -> dict:
    defaults = {
        "account_id": account_id,
        "kind": kind,
        "awarded_cents": awarded_cents,
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_agreement_payload(
    student_id: str,
    term_id: str,
    sponsor_name: str = "SponsorCo",
    cap_cents: int = 1000000,
    covers_tuition: bool = True,
    covers_fees: bool = True,
    billing_basis: str = "GROSS",
    start_date: str = "2026-08-01",
    end_date: str = "2026-12-31",
    **overrides,
) -> dict:
    defaults = {
        "sponsor_name": sponsor_name,
        "student_id": student_id,
        "term_id": term_id,
        "cap_cents": cap_cents,
        "covers_tuition": covers_tuition,
        "covers_fees": covers_fees,
        "billing_basis": billing_basis,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_invoice_payload(agreement_id: str, **overrides) -> dict:
    defaults = {"agreement_id": agreement_id}
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(
    account_id: str,
    installment_count: int = 2,
    first_due_date: str = "2026-09-01",
    expected_account_version: int = 1,
    **overrides,
) -> dict:
    defaults = {
        "account_id": account_id,
        "installment_count": installment_count,
        "first_due_date": first_due_date,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(
    account_id: str,
    hold_type: str = "REGISTRATION",
    reason: str = "Advising stop",
    **overrides,
) -> dict:
    defaults = {
        "account_id": account_id,
        "hold_type": hold_type,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_tax_form_payload(student_id: str, tax_year: int = 2026, **overrides) -> dict:
    defaults = {"student_id": student_id, "tax_year": tax_year}
    defaults.update(overrides)
    return defaults
