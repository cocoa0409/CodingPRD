"""Payload factories — one per endpoint that accepts a request body.

Each factory emits the JSON body shape PRD declares for the endpoint
(PRD §3 narratives + §4 endpoint table). Tests pass overrides for the
values they want to control. Only PRD-declared input fields are
emitted; computed and system-derived fields are intentionally omitted.

PRD §2.6: monetary amounts are integer cents.
PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def parse_iso(iso_ts: str) -> datetime:
    """Accept both 'Z' and '+00:00' suffixes."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def date_only_iso(year: int, month: int, day: int) -> str:
    return iso_utc(datetime(year, month, day, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Uniqueness helpers — every test independently isolated.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{random_suffix(8)}@example.com"


def unique_city(prefix: str = "City") -> str:
    return f"{prefix}{random_suffix(6)}"


# ---------------------------------------------------------------------------
# Employee — POST /employees (PRD §3.12)
# Required input: full_name, email, role, cost_center, home_address_state.
# manager_id required for TRAVELER, must be null for ADMIN.
# ---------------------------------------------------------------------------
def create_employee_payload(
    *,
    role: str,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    manager_id: Optional[str] = None,
    cost_center: Optional[str] = None,
    home_address_state: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Test {role.title()} {random_suffix(4)}",
        "email": email or unique_email(role.lower()),
        "role": role,
        "cost_center": cost_center or str(TEST_DEFAULTS["DEFAULT_COST_CENTER"]),
        "home_address_state":
            home_address_state or str(TEST_DEFAULTS["DEFAULT_HOME_STATE"]),
    }
    # PRD §3.12: manager_id required for TRAVELER, must be null for ADMIN.
    if role == "TRAVELER":
        payload["manager_id"] = manager_id  # caller passes the manager id
    elif role == "ADMIN":
        payload["manager_id"] = None
    else:
        # MANAGER, FINANCE_REVIEWER, OOP_APPROVER — manager_id is optional;
        # leave it out unless explicitly supplied.
        if manager_id is not None:
            payload["manager_id"] = manager_id
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# PerDiemRate — POST /per-diem-rates (PRD §3.12)
# ---------------------------------------------------------------------------
def create_per_diem_rate_payload(
    *,
    city: Optional[str] = None,
    state: Optional[str] = None,
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    lodging_cap_cents: Optional[int] = None,
    mie_cap_cents: Optional[int] = None,
    is_high_cost_locality: Optional[bool] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "city": city or str(TEST_DEFAULTS["TRIP_DESTINATION_CITY"]),
        "state": state or str(TEST_DEFAULTS["TRIP_DESTINATION_STATE"]),
        "effective_from":
            effective_from or str(TEST_DEFAULTS["RATE_EFFECTIVE_FROM"]),
        "effective_to":
            effective_to or str(TEST_DEFAULTS["RATE_EFFECTIVE_TO"]),
        "lodging_cap_cents":
            lodging_cap_cents
            if lodging_cap_cents is not None
            else int(TEST_DEFAULTS["RATE_LODGING_CAP_CENTS"]),
        "mie_cap_cents":
            mie_cap_cents
            if mie_cap_cents is not None
            else int(TEST_DEFAULTS["RATE_MIE_CAP_CENTS"]),
        "is_high_cost_locality":
            bool(is_high_cost_locality)
            if is_high_cost_locality is not None
            else False,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Trip — POST /trips (PRD §3.1)
# Required input: traveler_id, purpose, origin_city, origin_state,
# destination_city, destination_state, start_date, end_date.
# ---------------------------------------------------------------------------
def create_trip_payload(
    *,
    traveler_id: str,
    purpose: Optional[str] = None,
    origin_city: Optional[str] = None,
    origin_state: Optional[str] = None,
    destination_city: Optional[str] = None,
    destination_state: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "traveler_id": traveler_id,
        "purpose": purpose or str(TEST_DEFAULTS["DEFAULT_TRIP_PURPOSE"]),
        "origin_city": origin_city or str(TEST_DEFAULTS["TRIP_ORIGIN_CITY"]),
        "origin_state":
            origin_state or str(TEST_DEFAULTS["TRIP_ORIGIN_STATE"]),
        "destination_city":
            destination_city or str(TEST_DEFAULTS["TRIP_DESTINATION_CITY"]),
        "destination_state":
            destination_state or str(TEST_DEFAULTS["TRIP_DESTINATION_STATE"]),
        "start_date":
            start_date or str(TEST_DEFAULTS["TRIP_START_DATE"]),
        "end_date":
            end_date or str(TEST_DEFAULTS["TRIP_END_DATE"]),
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def update_trip_payload(
    *,
    version: Optional[int] = None,
    purpose: Optional[str] = None,
    origin_city: Optional[str] = None,
    origin_state: Optional[str] = None,
    destination_city: Optional[str] = None,
    destination_state: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """PATCH /trips/{id} — partial body, OCC via version (PRD §2.4)."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if purpose is not None:
        payload["purpose"] = purpose
    if origin_city is not None:
        payload["origin_city"] = origin_city
    if origin_state is not None:
        payload["origin_state"] = origin_state
    if destination_city is not None:
        payload["destination_city"] = destination_city
    if destination_state is not None:
        payload["destination_state"] = destination_state
    if start_date is not None:
        payload["start_date"] = start_date
    if end_date is not None:
        payload["end_date"] = end_date
    return payload


# ---------------------------------------------------------------------------
# VirtualCard — POST /virtual-cards (PRD §3.2)
# Required input: trip_id, credit_limit_cents.
# ---------------------------------------------------------------------------
def create_virtual_card_payload(
    *,
    trip_id: str,
    credit_limit_cents: int,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "trip_id": trip_id,
        "credit_limit_cents": credit_limit_cents,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def lock_virtual_card_payload(*, locked_reason: str) -> Dict[str, Any]:
    return {"locked_reason": locked_reason}


# ---------------------------------------------------------------------------
# ExpenseReport — POST /expense-reports (PRD §3.3)
# Required input: trip_id.
# ---------------------------------------------------------------------------
def create_expense_report_payload(
    *,
    trip_id: str,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"trip_id": trip_id}
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def update_expense_report_payload(
    *, version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# ExpenseLine — POST /expense-reports/{report_id}/lines (PRD §3.3)
# Required input: category, expense_date.
# Conditional inputs (per-category) handled by helpers below.
# ---------------------------------------------------------------------------
def _base_line_payload(
    category: str,
    expense_date: str,
    amount_claimed_cents: Optional[int],
    receipt_id: Optional[str],
    virtual_card_id: Optional[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category": category,
        "expense_date": expense_date,
    }
    if amount_claimed_cents is not None:
        payload["amount_claimed_cents"] = amount_claimed_cents
    if receipt_id is not None:
        payload["receipt_id"] = receipt_id
    if virtual_card_id is not None:
        payload["virtual_card_id"] = virtual_card_id
    return payload


def create_flight_line_payload(
    *,
    expense_date: str,
    amount_claimed_cents: int,
    receipt_id: Optional[str] = None,
    virtual_card_id: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _base_line_payload(
        "FLIGHT", expense_date, amount_claimed_cents,
        receipt_id, virtual_card_id,
    )
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def create_lodging_line_payload(
    *,
    expense_date: str,
    amount_claimed_cents: int,
    per_diem_method: str,
    receipt_id: Optional[str] = None,
    virtual_card_id: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _base_line_payload(
        "LODGING", expense_date, amount_claimed_cents,
        receipt_id, virtual_card_id,
    )
    payload["per_diem_method"] = per_diem_method
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def create_rental_car_line_payload(
    *,
    expense_date: str,
    amount_claimed_cents: int,
    rental_days: int,
    cdw_purchased: bool = False,
    receipt_id: Optional[str] = None,
    virtual_card_id: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _base_line_payload(
        "RENTAL_CAR", expense_date, amount_claimed_cents,
        receipt_id, virtual_card_id,
    )
    payload["rental_days"] = rental_days
    payload["cdw_purchased"] = bool(cdw_purchased)
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def create_meal_line_payload(
    *,
    expense_date: str,
    meal_type: str,
    amount_claimed_cents: Optional[int] = None,
    meal_was_provided: bool = False,
    per_diem_method: Optional[str] = None,
    receipt_id: Optional[str] = None,
    virtual_card_id: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """PRD §3.3: meal_type required when category==MEAL;
    per_diem_method required for MEAL when meal_was_provided=false.
    """
    payload = _base_line_payload(
        "MEAL", expense_date, amount_claimed_cents,
        receipt_id, virtual_card_id,
    )
    payload["meal_type"] = meal_type
    payload["meal_was_provided"] = bool(meal_was_provided)
    if per_diem_method is not None:
        payload["per_diem_method"] = per_diem_method
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def create_mileage_line_payload(
    *,
    expense_date: str,
    miles_driven: float,
    receipt_id: Optional[str] = None,
    virtual_card_id: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'for `MILEAGE`, `amount_claimed_cents` must be omitted
    on create and the server computes it from `miles_driven`.'"""
    payload = _base_line_payload(
        "MILEAGE", expense_date, None,
        receipt_id, virtual_card_id,
    )
    payload["miles_driven"] = miles_driven
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def create_other_line_payload(
    *,
    expense_date: str,
    amount_claimed_cents: int,
    receipt_id: Optional[str] = None,
    virtual_card_id: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _base_line_payload(
        "OTHER", expense_date, amount_claimed_cents,
        receipt_id, virtual_card_id,
    )
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def update_expense_line_payload(
    *,
    version: Optional[int] = None,
    amount_claimed_cents: Optional[int] = None,
    miles_driven: Optional[float] = None,
    rental_days: Optional[int] = None,
    meal_type: Optional[str] = None,
    meal_was_provided: Optional[bool] = None,
    per_diem_method: Optional[str] = None,
    cdw_purchased: Optional[bool] = None,
    virtual_card_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if amount_claimed_cents is not None:
        payload["amount_claimed_cents"] = amount_claimed_cents
    if miles_driven is not None:
        payload["miles_driven"] = miles_driven
    if rental_days is not None:
        payload["rental_days"] = rental_days
    if meal_type is not None:
        payload["meal_type"] = meal_type
    if meal_was_provided is not None:
        payload["meal_was_provided"] = bool(meal_was_provided)
    if per_diem_method is not None:
        payload["per_diem_method"] = per_diem_method
    if cdw_purchased is not None:
        payload["cdw_purchased"] = bool(cdw_purchased)
    if virtual_card_id is not None:
        payload["virtual_card_id"] = virtual_card_id
    return payload


# ---------------------------------------------------------------------------
# Receipt — POST /receipts (PRD §3.4)
# ---------------------------------------------------------------------------
def create_receipt_payload(
    *,
    merchant_total_cents: int,
    ocr_extracted_date: str,
    ocr_confidence: float = 0.95,
    merchant_name: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "merchant_name":
            merchant_name or f"Merchant {random_suffix(6)}",
        "merchant_total_cents": merchant_total_cents,
        "ocr_extracted_date": ocr_extracted_date,
        "ocr_confidence": ocr_confidence,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def attach_receipt_payload(*, receipt_id: str) -> Dict[str, Any]:
    return {"receipt_id": receipt_id}


# ---------------------------------------------------------------------------
# OutOfPolicyApproval — POST /oop-approvals (PRD §3.5)
# ---------------------------------------------------------------------------
def create_oop_approval_payload(
    *,
    expense_line_id: str,
    justification: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expense_line_id": expense_line_id,
        "justification":
            justification
            or "Out-of-policy justification with sufficient length.",
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Clock — POST /_clock/advance (PRD §3.12)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to_iso: str) -> Dict[str, Any]:
    return {"to": to_iso}


__all__ = [
    # Time helpers
    "iso_utc", "utcnow", "parse_iso", "add_days", "date_only_iso",
    # Uniqueness
    "random_suffix", "unique_email", "unique_city",
    # Employee
    "create_employee_payload",
    # PerDiemRate
    "create_per_diem_rate_payload",
    # Trip
    "create_trip_payload", "update_trip_payload",
    # VirtualCard
    "create_virtual_card_payload", "lock_virtual_card_payload",
    # ExpenseReport
    "create_expense_report_payload", "update_expense_report_payload",
    # ExpenseLine — per category
    "create_flight_line_payload",
    "create_lodging_line_payload",
    "create_rental_car_line_payload",
    "create_meal_line_payload",
    "create_mileage_line_payload",
    "create_other_line_payload",
    "update_expense_line_payload",
    # Receipt
    "create_receipt_payload", "attach_receipt_payload",
    # OOP approval
    "create_oop_approval_payload",
    # Clock
    "clock_advance_payload",
]
