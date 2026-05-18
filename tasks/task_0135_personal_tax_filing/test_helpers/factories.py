"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.5: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp / date helpers — PRD §2.4 ISO 8601 UTC with three fractional
# digits. PRD §2.9 virtual clock advances by ISO 8601 instant.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_instant_utc(year: int, month: int, day: int, hour: int = 0,
                    minute: int = 0, second: int = 0) -> str:
    """Build a deterministic ISO 8601 UTC instant with .000Z millis."""
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            tzinfo=timezone.utc))


def iso_date(d: date) -> str:
    """PRD §3.1: 'YYYY-MM-DD form'."""
    return d.isoformat()


def date_offset(d: date, *, days: int) -> date:
    return d + timedelta(days=days)


def parse_iso(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(
        string.ascii_uppercase + string.digits, k=length,
    ))


def random_ssn_last4() -> str:
    return f"{random.randint(1000, 9999)}"


def random_ein() -> str:
    return f"{random.randint(10, 99)}-{random.randint(1_000_000, 9_999_999)}"


# ---------------------------------------------------------------------------
# Optimistic concurrency version helper — PRD §2.6
# ---------------------------------------------------------------------------
def version_body(version: Optional[int] = None,
                 **extra: Any) -> Dict[str, Any]:
    """Build a PATCH body that includes 'version' when supplied."""
    body: Dict[str, Any] = dict(extra)
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Taxpayer payloads — PRD §3.1
# ---------------------------------------------------------------------------
def filing_address(
    *,
    street: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> Dict[str, str]:
    """PRD §3.1 filing_address: street, city, state, zip."""
    return {
        "street": street or TEST_DEFAULTS["STREET"],
        "city": city or TEST_DEFAULTS["CITY"],
        "state": state or TEST_DEFAULTS["STATE"],
        "zip": zip_code or TEST_DEFAULTS["ZIP"],
    }


def create_taxpayer_payload(
    *,
    ssn_last4: Optional[str] = None,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    address: Optional[Dict[str, str]] = None,
    is_blind: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /taxpayers — PRD §3.1."""
    payload: Dict[str, Any] = {
        "ssn_last4": ssn_last4 or random_ssn_last4(),
        "full_name": full_name or (
            f"{TEST_DEFAULTS['FULL_NAME']} {random_suffix(4)}"
        ),
        "date_of_birth": (
            date_of_birth or TEST_DEFAULTS["DATE_OF_BIRTH"]
        ),
        "filing_address": address or filing_address(),
    }
    if is_blind is not None:
        payload["is_blind"] = is_blind
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TaxReturn payloads — PRD §3.1
# ---------------------------------------------------------------------------
def create_tax_return_payload(
    *,
    taxpayer_id: str,
    tax_year: Optional[int] = None,
    filing_status: Optional[str] = None,
    dependents_count: Optional[int] = None,
    qualifying_children_under_17: Optional[int] = None,
    deduction_method: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns — PRD §3.1."""
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "tax_year": (
            tax_year if tax_year is not None
            else TEST_DEFAULTS["TAX_YEAR"]
        ),
        "filing_status": (
            filing_status or TEST_DEFAULTS["FILING_STATUS"]
        ),
    }
    if dependents_count is not None:
        payload["dependents_count"] = dependents_count
    if qualifying_children_under_17 is not None:
        payload["qualifying_children_under_17"] = (
            qualifying_children_under_17
        )
    if deduction_method is not None:
        payload["deduction_method"] = deduction_method
    payload.update(overrides)
    return payload


def patch_tax_return_payload(
    *,
    filing_status: Optional[str] = None,
    dependents_count: Optional[int] = None,
    qualifying_children_under_17: Optional[int] = None,
    deduction_method: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /tax-returns/{id} — PRD §4 mutable inputs."""
    payload: Dict[str, Any] = {}
    if filing_status is not None:
        payload["filing_status"] = filing_status
    if dependents_count is not None:
        payload["dependents_count"] = dependents_count
    if qualifying_children_under_17 is not None:
        payload["qualifying_children_under_17"] = (
            qualifying_children_under_17
        )
    if deduction_method is not None:
        payload["deduction_method"] = deduction_method
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IncomeDocument payloads — PRD §3.2
# ---------------------------------------------------------------------------
def create_w2_payload(
    *,
    wages_cents: int = 0,
    federal_withholding_cents: int = 0,
    payer_ein: Optional[str] = None,
    payer_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/income-documents (W2) — PRD §3.2."""
    payload: Dict[str, Any] = {
        "doc_type": "W2",
        "payer_ein": payer_ein or random_ein(),
        "payer_name": payer_name or TEST_DEFAULTS["PAYER_NAME"],
        "wages_cents": wages_cents,
        "federal_withholding_cents": federal_withholding_cents,
    }
    payload.update(overrides)
    return payload


def create_1099_nec_payload(
    *,
    nonemployee_comp_cents: int = 0,
    federal_withholding_cents: int = 0,
    payer_ein: Optional[str] = None,
    payer_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/income-documents (1099_NEC) — PRD §3.2."""
    payload: Dict[str, Any] = {
        "doc_type": "1099_NEC",
        "payer_ein": payer_ein or random_ein(),
        "payer_name": payer_name or TEST_DEFAULTS["PAYER_NAME"],
        "nonemployee_comp_cents": nonemployee_comp_cents,
        "federal_withholding_cents": federal_withholding_cents,
    }
    payload.update(overrides)
    return payload


def create_1099_int_payload(
    *,
    interest_income_cents: int = 0,
    federal_withholding_cents: int = 0,
    payer_ein: Optional[str] = None,
    payer_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/income-documents (1099_INT) — PRD §3.2."""
    payload: Dict[str, Any] = {
        "doc_type": "1099_INT",
        "payer_ein": payer_ein or random_ein(),
        "payer_name": payer_name or TEST_DEFAULTS["PAYER_NAME"],
        "interest_income_cents": interest_income_cents,
        "federal_withholding_cents": federal_withholding_cents,
    }
    payload.update(overrides)
    return payload


def create_1099_div_payload(
    *,
    ordinary_dividends_cents: int = 0,
    qualified_dividends_cents: int = 0,
    federal_withholding_cents: int = 0,
    payer_ein: Optional[str] = None,
    payer_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/income-documents (1099_DIV) — PRD §3.2."""
    payload: Dict[str, Any] = {
        "doc_type": "1099_DIV",
        "payer_ein": payer_ein or random_ein(),
        "payer_name": payer_name or TEST_DEFAULTS["PAYER_NAME"],
        "ordinary_dividends_cents": ordinary_dividends_cents,
        "qualified_dividends_cents": qualified_dividends_cents,
        "federal_withholding_cents": federal_withholding_cents,
    }
    payload.update(overrides)
    return payload


def create_1099_b_payload(
    *,
    proceeds_cents: int = 0,
    cost_basis_cents: int = 0,
    holding_period: str = "SHORT_TERM",
    federal_withholding_cents: int = 0,
    payer_ein: Optional[str] = None,
    payer_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/income-documents (1099_B) — PRD §3.2."""
    payload: Dict[str, Any] = {
        "doc_type": "1099_B",
        "payer_ein": payer_ein or random_ein(),
        "payer_name": payer_name or TEST_DEFAULTS["PAYER_NAME"],
        "proceeds_cents": proceeds_cents,
        "cost_basis_cents": cost_basis_cents,
        "holding_period": holding_period,
        "federal_withholding_cents": federal_withholding_cents,
    }
    payload.update(overrides)
    return payload


def patch_income_document_payload(
    *,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /income-documents/{id} — PRD §3.2."""
    payload: Dict[str, Any] = dict(overrides)
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# Schedule payloads — PRD §3.3
# ---------------------------------------------------------------------------
def create_schedule_a_payload(
    *,
    itemized_medical_cents: int = 0,
    itemized_salt_cents: int = 0,
    itemized_mortgage_interest_cents: int = 0,
    itemized_charity_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/schedules (A) — PRD §3.3."""
    payload: Dict[str, Any] = {
        "schedule_type": "A",
        "itemized_medical_cents": itemized_medical_cents,
        "itemized_salt_cents": itemized_salt_cents,
        "itemized_mortgage_interest_cents": (
            itemized_mortgage_interest_cents
        ),
        "itemized_charity_cents": itemized_charity_cents,
    }
    payload.update(overrides)
    return payload


def create_schedule_b_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /tax-returns/{id}/schedules (B) — PRD §3.3 (computed-only)."""
    payload: Dict[str, Any] = {"schedule_type": "B"}
    payload.update(overrides)
    return payload


def create_schedule_c_payload(
    *,
    schedule_c_gross_receipts_cents: int = 0,
    schedule_c_expenses_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/schedules (C) — PRD §3.3."""
    payload: Dict[str, Any] = {
        "schedule_type": "C",
        "schedule_c_gross_receipts_cents": (
            schedule_c_gross_receipts_cents
        ),
        "schedule_c_expenses_cents": schedule_c_expenses_cents,
    }
    payload.update(overrides)
    return payload


def create_schedule_d_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /tax-returns/{id}/schedules (D) — PRD §3.3 (computed-only)."""
    payload: Dict[str, Any] = {"schedule_type": "D"}
    payload.update(overrides)
    return payload


def create_schedule_e_payload(
    *,
    schedule_e_rental_income_cents: int = 0,
    schedule_e_rental_expenses_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/schedules (E) — PRD §3.3."""
    payload: Dict[str, Any] = {
        "schedule_type": "E",
        "schedule_e_rental_income_cents": schedule_e_rental_income_cents,
        "schedule_e_rental_expenses_cents": (
            schedule_e_rental_expenses_cents
        ),
    }
    payload.update(overrides)
    return payload


def patch_schedule_payload(
    *,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /schedules/{id} — PRD §3.3."""
    payload: Dict[str, Any] = dict(overrides)
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# TaxCredit payloads — PRD §3.4
# ---------------------------------------------------------------------------
def create_credit_payload(
    *,
    credit_type: str,
    requested_amount_cents: int,
    aotc_student_count: Optional[int] = None,
    aotc_qualified_expenses_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns/{id}/credits — PRD §3.4."""
    payload: Dict[str, Any] = {
        "credit_type": credit_type,
        "requested_amount_cents": requested_amount_cents,
    }
    if aotc_student_count is not None:
        payload["aotc_student_count"] = aotc_student_count
    if aotc_qualified_expenses_cents is not None:
        payload["aotc_qualified_expenses_cents"] = (
            aotc_qualified_expenses_cents
        )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Amendment payloads — PRD §3.9
# ---------------------------------------------------------------------------
def create_amendment_payload(
    *,
    original_return_id: str,
    reason_summary: str,
    restated_filing_status: Optional[str] = None,
    restated_dependents_count: Optional[int] = None,
    restated_qualifying_children_under_17: Optional[int] = None,
    restated_deduction_method: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /amendments — PRD §3.9."""
    payload: Dict[str, Any] = {
        "original_return_id": original_return_id,
        "reason_summary": reason_summary,
    }
    if restated_filing_status is not None:
        payload["restated_filing_status"] = restated_filing_status
    if restated_dependents_count is not None:
        payload["restated_dependents_count"] = restated_dependents_count
    if restated_qualifying_children_under_17 is not None:
        payload["restated_qualifying_children_under_17"] = (
            restated_qualifying_children_under_17
        )
    if restated_deduction_method is not None:
        payload["restated_deduction_method"] = restated_deduction_method
    payload.update(overrides)
    return payload


def decide_filing_payload(
    *,
    outcome: str,
    rejection_code: Optional[str] = None,
    rejection_message: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /efilings/{id}/decide — PRD §3.8."""
    payload: Dict[str, Any] = {"outcome": outcome}
    if rejection_code is not None:
        payload["rejection_code"] = rejection_code
    if rejection_message is not None:
        payload["rejection_message"] = rejection_message
    return payload


def decide_amendment_payload(
    *,
    outcome: str,
    rejection_message: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /amendments/{id}/decide — PRD §3.9."""
    payload: Dict[str, Any] = {"outcome": outcome}
    if rejection_message is not None:
        payload["rejection_message"] = rejection_message
    return payload


# ---------------------------------------------------------------------------
# EstimatedTaxPayment payloads — PRD §3.10
# ---------------------------------------------------------------------------
def create_estimated_payment_payload(
    *,
    taxpayer_id: str,
    tax_year: int,
    quarter: str,
    amount_cents: int,
    scheduled_pay_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /estimated-payments — PRD §3.10."""
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "tax_year": tax_year,
        "quarter": quarter,
        "amount_cents": amount_cents,
        "scheduled_pay_date": scheduled_pay_date,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compliance lock payload — PRD §3.11
# ---------------------------------------------------------------------------
def compliance_lock_payload(*, reason: Optional[str] = None) -> Dict[str, Any]:
    """POST /taxpayers/{id}/compliance-lock — PRD §3.11."""
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ---------------------------------------------------------------------------
# Virtual clock payload — PRD §2.9
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to_iso_timestamp: str) -> Dict[str, Any]:
    """POST /_clock/advance — PRD §2.9 supplies a future ISO 8601 instant."""
    return {"to_iso_timestamp": to_iso_timestamp}


__all__ = [
    # date / time helpers
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "iso_date",
    "date_offset",
    "parse_iso",
    # random helpers
    "random_suffix",
    "random_ssn_last4",
    "random_ein",
    # OCC helper
    "version_body",
    # Taxpayer payloads
    "filing_address",
    "create_taxpayer_payload",
    # TaxReturn payloads
    "create_tax_return_payload",
    "patch_tax_return_payload",
    # IncomeDocument payloads
    "create_w2_payload",
    "create_1099_nec_payload",
    "create_1099_int_payload",
    "create_1099_div_payload",
    "create_1099_b_payload",
    "patch_income_document_payload",
    # Schedule payloads
    "create_schedule_a_payload",
    "create_schedule_b_payload",
    "create_schedule_c_payload",
    "create_schedule_d_payload",
    "create_schedule_e_payload",
    "patch_schedule_payload",
    # Credit payloads
    "create_credit_payload",
    # Amendment / decision payloads
    "create_amendment_payload",
    "decide_filing_payload",
    "decide_amendment_payload",
    # EstimatedTaxPayment payload
    "create_estimated_payment_payload",
    # Compliance lock payload
    "compliance_lock_payload",
    # Clock payload
    "clock_advance_payload",
]
