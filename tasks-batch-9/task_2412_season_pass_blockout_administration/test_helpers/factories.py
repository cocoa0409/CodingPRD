"""Request payload builders.

Each builder supplies the minimal PRD-declared field set with sensible values
and lets a test override any field, including removing one by passing `None`
explicitly through the `drop` argument.
"""

from typing import Any, Dict, List, Optional

from .types import (
    CaseDecision,
    CreditMode,
    GateCode,
    ParkingBenefit,
    PaymentMode,
    PhotoMatch,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


def drop_fields(payload: Dict[str, Any], *fields: str) -> Dict[str, Any]:
    """Return a copy of the payload with the named fields removed."""
    return {key: value for key, value in payload.items() if key not in fields}


# ------------------------------------------------------------- programmes ----


def pass_program_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "season_year": 2026,
            "park_name": "Summit Ridge",
            "early_bird_deadline": "2026-11-15",
        },
        overrides,
    )


def advance_status_payload(target_status: str) -> Dict[str, Any]:
    return {"target_status": target_status}


def billing_run_payload(as_of_date: str) -> Dict[str, Any]:
    return {"as_of_date": as_of_date}


# ------------------------------------------------------------------ tiers ----


def pass_tier_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "name": "BRONZE",
            "tier_rank": 1,
            "base_price_cents": 12000,
            "parking_benefit": ParkingBenefit.NONE.value,
            "in_park_discount_pct": 0.05,
            "reservation_required_on_peak": True,
            "peak_reservation_quota": 2,
        },
        overrides,
    )


def tier_status_payload(target_status: str) -> Dict[str, Any]:
    return {"target_status": target_status}


# -------------------------------------------------------------- park days ----


def park_day_payload(program_id: str, calendar_date: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "calendar_date": calendar_date,
            "capacity_total": 1000,
            "forecast_attendance": 100,
        },
        overrides,
    )


def forecast_payload(forecast_attendance: int) -> Dict[str, Any]:
    return {"forecast_attendance": forecast_attendance}


# ---------------------------------------------------- blockout assignments ----


def blockout_payload(tier_id: str, park_day_id: str, expected_park_day_version: Any) -> Dict[str, Any]:
    return {
        "tier_id": tier_id,
        "park_day_id": park_day_id,
        "expected_park_day_version": expected_park_day_version,
    }


def lift_payload(reason: str) -> Dict[str, Any]:
    return {"reason": reason}


# ------------------------------------------------------------ passholders ----


def passholder_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Ada Holder",
            "email": "ada@example.com",
            "date_of_birth": "1990-04-02",
        },
        overrides,
    )


# ----------------------------------------------------------- season passes ----


def season_pass_payload(
    program_id: str,
    tier_id: str,
    passholder_id: str,
    payment_mode: str = PaymentMode.PAY_IN_FULL.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "tier_id": tier_id,
            "passholder_id": passholder_id,
            "payment_mode": payment_mode,
        },
        overrides,
    )


def process_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"photo_hash": "sha256:aaa", "government_id_last4": "1234"}, overrides)


def payment_plan_payload(
    down_payment_cents: int,
    installment_count: int,
    first_due_date: str,
    expected_season_pass_version: Any,
) -> Dict[str, Any]:
    return {
        "down_payment_cents": down_payment_cents,
        "installment_count": installment_count,
        "first_due_date": first_due_date,
        "expected_season_pass_version": expected_season_pass_version,
    }


def settle_payload(amount_cents: int, paid_at: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if paid_at is not None:
        payload["paid_at"] = paid_at
    return payload


def reinstate_payload(
    cure_amount_cents: int, waive_installment_id: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cure_amount_cents": cure_amount_cents}
    if waive_installment_id is not None:
        payload["waive_installment_id"] = waive_installment_id
    return payload


def renew_payload(
    target_program_id: str,
    target_tier_id: str,
    payment_mode: str = PaymentMode.PAY_IN_FULL.value,
) -> Dict[str, Any]:
    return {
        "target_program_id": target_program_id,
        "target_tier_id": target_tier_id,
        "payment_mode": payment_mode,
    }


# ------------------------------------------------------------ reservations ----


def reservation_payload(
    season_pass_id: str,
    park_day_id: str,
    arrival_window_start: str = "10:00",
    arrival_window_end: str = "13:00",
) -> Dict[str, Any]:
    return {
        "season_pass_id": season_pass_id,
        "park_day_id": park_day_id,
        "arrival_window_start": arrival_window_start,
        "arrival_window_end": arrival_window_end,
    }


# ------------------------------------------------------------------ visits ----


def visit_payload(
    season_pass_id: str,
    park_day_id: str,
    entry_at: str,
    gate_code: str = GateCode.NORTH.value,
    photo_match: Optional[str] = PhotoMatch.MATCH.value,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_pass_id": season_pass_id,
        "park_day_id": park_day_id,
        "entry_at": entry_at,
        "gate_code": gate_code,
    }
    if photo_match is not None:
        payload["photo_match"] = photo_match
    return payload


def close_visit_payload(spend_cents: int) -> Dict[str, Any]:
    return {"spend_cents": spend_cents}


# ----------------------------------------------------------- sharing cases ----


def sharing_case_payload(
    season_pass_id: str, evidence_visit_ids: List[str], note: str = "Photo mismatch"
) -> Dict[str, Any]:
    return {
        "season_pass_id": season_pass_id,
        "evidence_visit_ids": evidence_visit_ids,
        "note": note,
    }


def decide_payload(decision: str = CaseDecision.SUBSTANTIATED.value, rationale: str = "Evidence stands") -> Dict[str, Any]:
    return {"decision": decision, "rationale": rationale}


def appeal_payload(statement: str = "The gate camera was obstructed") -> Dict[str, Any]:
    return {"statement": statement}


# ---------------------------------------------------------- upgrade orders ----


def upgrade_order_payload(
    season_pass_id: str,
    source_tier_id: str,
    target_tier_id: str,
    credit_mode: str = CreditMode.PAID_TO_DATE.value,
) -> Dict[str, Any]:
    return {
        "season_pass_id": season_pass_id,
        "source_tier_id": source_tier_id,
        "target_tier_id": target_tier_id,
        "credit_mode": credit_mode,
    }


def apply_upgrade_payload(payment_amount_cents: int) -> Dict[str, Any]:
    return {"payment_amount_cents": payment_amount_cents}


def reverse_upgrade_payload(reason: str = "Charged in error") -> Dict[str, Any]:
    return {"reason": reason}
