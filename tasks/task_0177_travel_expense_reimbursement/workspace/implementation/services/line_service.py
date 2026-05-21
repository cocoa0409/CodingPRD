"""Expense line creation/edit, category-specific calculations, OCR resolution."""
from __future__ import annotations

from typing import Optional

from core.errors import (
    err_card_limit_exceeded,
    err_card_trip_mismatch,
    err_category_field_missing,
    err_cross_entity_state,
    err_expense_outside_trip_window,
    err_invalid_state,
    err_receipt_already_used,
    err_receipt_required,
    err_reference_not_found,
    err_validation,
)
from core.store import store
from core.utils import is_int, is_number, new_id, parse_iso
from services import calculations
from services.timestamps import stamp_create, stamp_update


_RECEIPT_REQUIRED_CATEGORIES = {"LODGING", "RENTAL_CAR", "FLIGHT"}
_RECEIPT_AMOUNT_THRESHOLD_CENTS = 7500


def _ensure_category(category):
    valid = {"FLIGHT", "LODGING", "RENTAL_CAR", "MEAL", "MILEAGE", "OTHER"}
    if category not in valid:
        raise err_validation(f"Unknown category: {category}")


def _check_category_fields(payload: dict):
    cat = payload.get("category")
    if cat == "MILEAGE":
        if payload.get("miles_driven") is None:
            raise err_category_field_missing("miles_driven is required for MILEAGE.")
        if not is_number(payload["miles_driven"]):
            raise err_validation("miles_driven must be a number.")
    elif cat == "RENTAL_CAR":
        if payload.get("rental_days") is None:
            raise err_category_field_missing("rental_days is required for RENTAL_CAR.")
        if not is_int(payload["rental_days"]) or payload["rental_days"] < 1:
            raise err_validation("rental_days must be an integer >= 1.")
    elif cat == "MEAL":
        if payload.get("meal_type") is None:
            raise err_category_field_missing("meal_type is required for MEAL.")
        if payload["meal_type"] not in {"BREAKFAST", "LUNCH", "DINNER", "INCIDENTAL"}:
            raise err_validation("meal_type must be a valid enum.")
        if not payload.get("meal_was_provided"):
            if payload.get("per_diem_method") is None:
                raise err_category_field_missing("per_diem_method is required for MEAL (unless meal_was_provided).")
    elif cat == "LODGING":
        if payload.get("per_diem_method") is None:
            raise err_category_field_missing("per_diem_method is required for LODGING.")

    method = payload.get("per_diem_method")
    if method is not None and method not in {"ACTUAL", "PER_DIEM"}:
        raise err_validation("per_diem_method must be ACTUAL or PER_DIEM.")


def _enforce_receipt_requirement(line: dict):
    cat = line["category"]
    amount = int(line.get("amount_claimed_cents") or 0)
    if cat in _RECEIPT_REQUIRED_CATEGORIES or amount > _RECEIPT_AMOUNT_THRESHOLD_CENTS:
        if not line.get("receipt_id"):
            raise err_receipt_required(
                f"Receipt required for category={cat} or amount>{_RECEIPT_AMOUNT_THRESHOLD_CENTS}."
            )


def _validate_trip_window(trip: dict, expense_date: str):
    ed = parse_iso(expense_date)
    if ed is None:
        raise err_validation("expense_date must be a valid ISO 8601 datetime.")
    start = parse_iso(trip["start_date"])
    end = parse_iso(trip["end_date"])
    # Inclusive on both ends (UTC midnight)
    if ed.date() < start.date() or ed.date() > end.date():
        raise err_expense_outside_trip_window(
            f"expense_date {expense_date} outside [{trip['start_date']}, {trip['end_date']}]."
        )


def _validate_card(line: dict, trip: dict):
    card_id = line.get("virtual_card_id")
    if not card_id:
        return
    card = store.virtual_cards.get(card_id)
    if card is None:
        raise err_reference_not_found(f"virtual_card_id {card_id} not found.")
    if card["trip_id"] != trip["id"]:
        raise err_card_trip_mismatch(
            f"virtual_card.trip_id={card['trip_id']} != report.trip_id={trip['id']}."
        )


def _validate_receipt(line: dict):
    rid = line.get("receipt_id")
    if not rid:
        return
    receipt = store.receipts.get(rid)
    if receipt is None:
        raise err_reference_not_found(f"receipt_id {rid} not found.")


# -----------------------------------------------------------------------------
# Calculation dispatch
# -----------------------------------------------------------------------------
def compute_line_amounts(line: dict, trip: dict, variant: str = "provisional"):
    """Compute amount_reimbursable_cents and policy_status hints for a line."""
    cat = line["category"]
    if cat == "MILEAGE":
        amount = calculations.compute_mileage_reimbursement(line)
        line["amount_claimed_cents"] = amount
        line["amount_reimbursable_cents"] = amount
        line["policy_status"] = "IN_POLICY"
        return
    if cat == "MEAL":
        amount, policy, _cap = calculations.compute_meal_reimbursement(line, trip, variant)
        line["amount_reimbursable_cents"] = amount
        if line.get("meal_was_provided"):
            line["policy_status"] = "IN_POLICY"
        else:
            line["policy_status"] = policy
        return
    if cat == "RENTAL_CAR":
        amount, policy = calculations.compute_rental_reimbursement(line, trip)
        line["amount_reimbursable_cents"] = amount
        line["policy_status"] = policy
        return
    if cat == "FLIGHT":
        amount, policy, _llf = calculations.compute_flight_reimbursement(line, trip, variant)
        line["amount_reimbursable_cents"] = amount
        line["policy_status"] = policy
        return
    if cat == "LODGING":
        amount, policy = calculations.compute_lodging_reimbursement(line, trip, variant)
        line["amount_reimbursable_cents"] = amount
        line["policy_status"] = policy
        return
    # OTHER
    amount, policy = calculations.compute_other_reimbursement(line)
    line["amount_reimbursable_cents"] = amount
    line["policy_status"] = policy


# -----------------------------------------------------------------------------
# Card authorization
# -----------------------------------------------------------------------------
def authorize_card_delta(card_id: Optional[str], delta_cents: int):
    """Adjust a card's authorized_amount_cents and enforce credit limit.

    `delta_cents` may be positive (add charges) or negative (deauthorize).
    """
    if not card_id:
        return
    card = store.virtual_cards.get(card_id)
    if card is None:
        return
    new_amount = int(card.get("authorized_amount_cents") or 0) + delta_cents
    if new_amount < 0:
        new_amount = 0
    if delta_cents > 0 and new_amount > int(card["credit_limit_cents"]):
        raise err_card_limit_exceeded(
            f"Authorization {new_amount} exceeds credit_limit_cents {card['credit_limit_cents']}."
        )
    card["authorized_amount_cents"] = new_amount
    stamp_update(card)


# -----------------------------------------------------------------------------
# Report rollups
# -----------------------------------------------------------------------------
def rollup_report(report: dict):
    """Recompute total_claimed_cents, total_reimbursable_cents, policy_violation_count."""
    lines = store.lines_for_report(report["id"])
    total_claim = 0
    total_reimb = 0
    violation_count = 0
    for ln in lines:
        if ln.get("line_status") != "VOIDED":
            total_claim += int(ln.get("amount_claimed_cents") or 0)
            total_reimb += int(ln.get("amount_reimbursable_cents") or 0)
        if ln.get("policy_status") == "OUT_OF_POLICY":
            violation_count += 1
    report["total_claimed_cents"] = total_claim
    report["total_reimbursable_cents"] = total_reimb
    report["policy_violation_count"] = violation_count


# -----------------------------------------------------------------------------
# OCR resolution (system-driven on attach)
# -----------------------------------------------------------------------------
def resolve_ocr_status(line: dict, receipt: dict):
    """Run the OCR matching rule and update ocr_status accordingly.

    Mutates `line` in-place. Caller is responsible for stamp_update.
    """
    line["ocr_status"] = "PENDING_OCR"
    merchant_total = int(receipt.get("merchant_total_cents") or 0)
    claimed = int(line.get("amount_claimed_cents") or 0)
    confidence = float(receipt.get("ocr_confidence") or 0)

    matches = merchant_total == claimed and confidence >= 0.80

    if matches:
        line["ocr_status"] = "OCR_VERIFIED"
        return

    # Mismatch — but check meal carve-out
    if line.get("category") == "MEAL":
        diff = abs(merchant_total - claimed)
        if diff <= 200 and confidence >= 0.60:
            line["ocr_status"] = "OCR_WAIVED"
            return

    line["ocr_status"] = "OCR_MISMATCH"
