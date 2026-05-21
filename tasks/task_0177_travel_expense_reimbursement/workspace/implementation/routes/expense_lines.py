"""Expense Line endpoints."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import (
    err_card_limit_exceeded,
    err_card_trip_mismatch,
    err_category_field_missing,
    err_cross_entity_state,
    err_expense_outside_trip_window,
    err_invalid_state,
    err_not_found,
    err_receipt_already_used,
    err_receipt_required,
    err_reference_not_found,
    err_segregation_of_duties,
    err_stale_version,
    err_validation,
)
from core.serializers import serialize_expense_line
from core.store import store
from core.utils import is_int, is_number, lock, parse_iso
from services import line_service
from services.timestamps import stamp_create, stamp_update


bp = Blueprint("expense_lines", __name__)


_VALID_CATEGORIES = {"FLIGHT", "LODGING", "RENTAL_CAR", "MEAL", "MILEAGE", "OTHER"}


def _validate_create_body(body):
    for f in ("category", "expense_date"):
        if body.get(f) is None or body.get(f) == "":
            raise err_validation(f"{f} is required.")
    if body["category"] not in _VALID_CATEGORIES:
        raise err_validation(f"category must be one of {sorted(_VALID_CATEGORIES)}.")
    try:
        parse_iso(body["expense_date"])
    except ValueError as exc:
        raise err_validation(str(exc))


def _check_category_fields_on_create(body):
    cat = body["category"]
    if cat == "MILEAGE":
        if body.get("miles_driven") is None:
            raise err_category_field_missing("miles_driven is required for MILEAGE.")
        if not is_number(body["miles_driven"]):
            raise err_validation("miles_driven must be a number.")
        if "amount_claimed_cents" in body and body["amount_claimed_cents"] is not None:
            raise err_validation("amount_claimed_cents must be omitted for MILEAGE.")
    else:
        if body.get("amount_claimed_cents") is None:
            raise err_validation("amount_claimed_cents is required.")
        if not is_int(body["amount_claimed_cents"]) or body["amount_claimed_cents"] < 0:
            raise err_validation("amount_claimed_cents must be a non-negative integer.")

    if cat == "RENTAL_CAR":
        if body.get("rental_days") is None:
            raise err_category_field_missing("rental_days is required for RENTAL_CAR.")
        if not is_int(body["rental_days"]) or body["rental_days"] < 1:
            raise err_validation("rental_days must be an integer >= 1.")
    if cat == "MEAL":
        if body.get("meal_type") is None:
            raise err_category_field_missing("meal_type is required for MEAL.")
        if body["meal_type"] not in {"BREAKFAST", "LUNCH", "DINNER", "INCIDENTAL"}:
            raise err_validation("Invalid meal_type.")
        if not body.get("meal_was_provided"):
            if body.get("per_diem_method") is None:
                raise err_category_field_missing("per_diem_method is required for MEAL (unless meal_was_provided).")
    if cat == "LODGING":
        if body.get("per_diem_method") is None:
            raise err_category_field_missing("per_diem_method is required for LODGING.")
    method = body.get("per_diem_method")
    if method is not None and method not in {"ACTUAL", "PER_DIEM"}:
        raise err_validation("per_diem_method must be ACTUAL or PER_DIEM.")


@bp.post("/expense-reports/<rid>/lines")
@require_roles("TRAVELER")
def create_line(rid):
    report = store.expense_reports.get(rid)
    if report is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    trip = store.trips.get(report["trip_id"])
    if trip is None:
        raise err_reference_not_found("Parent trip not found.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the traveler may add lines to this report.")

    if report["status"] not in {"DRAFT", "CHANGES_REQUESTED"}:
        raise err_invalid_state(f"Report status is {report['status']}, cannot add line.")

    body = get_json_body()
    _validate_create_body(body)

    # Validate FK references first (REFERENCE_NOT_FOUND)
    receipt_id = body.get("receipt_id")
    if receipt_id:
        if store.receipts.get(receipt_id) is None:
            raise err_reference_not_found(f"receipt_id {receipt_id} not found.")
    card_id = body.get("virtual_card_id")
    if card_id:
        card = store.virtual_cards.get(card_id)
        if card is None:
            raise err_reference_not_found(f"virtual_card_id {card_id} not found.")

    # Card-trip mismatch (priority 9, before expense-window check priority 10)
    if card_id:
        card = store.virtual_cards.get(card_id)
        if card["trip_id"] != trip["id"]:
            raise err_card_trip_mismatch(
                f"virtual_card.trip_id={card['trip_id']} != report.trip_id={trip['id']}."
            )

    # Expense window (priority 10)
    expense_date = body["expense_date"]
    ed = parse_iso(expense_date)
    s = parse_iso(trip["start_date"])
    e = parse_iso(trip["end_date"])
    if ed.date() < s.date() or ed.date() > e.date():
        raise err_expense_outside_trip_window(
            f"expense_date {expense_date} outside [{trip['start_date']}, {trip['end_date']}]."
        )

    # Category field validation (priority 13)
    _check_category_fields_on_create(body)

    # Receipt requirement (priority 12) — after the category check is settled
    cat = body["category"]
    if cat == "MILEAGE":
        amount_claimed = 0  # will be computed
    else:
        amount_claimed = int(body["amount_claimed_cents"])

    if cat in {"LODGING", "RENTAL_CAR", "FLIGHT"} or amount_claimed > 7500:
        if not receipt_id:
            raise err_receipt_required(
                f"Receipt required for category={cat} or amount>{7500}."
            )

    with lock():
        if report["status"] == "CHANGES_REQUESTED":
            report["status"] = "DRAFT"
            report["reviewer_id"] = None
            stamp_update(report)

        line = {
            "report_id": rid,
            "category": cat,
            "expense_date": expense_date,
            "amount_claimed_cents": amount_claimed if cat != "MILEAGE" else 0,
            "amount_reimbursable_cents": 0,
            "policy_status": "PENDING_EVAL",
            "ocr_status": "NO_RECEIPT",
            "line_status": "ACTIVE",
            "receipt_id": receipt_id,
            "miles_driven": body.get("miles_driven"),
            "rental_days": body.get("rental_days"),
            "meal_type": body.get("meal_type"),
            "meal_was_provided": bool(body.get("meal_was_provided", False)),
            "per_diem_method": body.get("per_diem_method"),
            "cdw_purchased": bool(body.get("cdw_purchased", False)),
            "virtual_card_id": card_id,
        }
        stamp_create(line)

        # Run category calculation (sets amount_reimbursable_cents and policy_status)
        line_service.compute_line_amounts(line, trip, variant="provisional")

        # Card authorization
        if card_id:
            line_service.authorize_card_delta(card_id, int(line["amount_reimbursable_cents"]))

        store.expense_lines[line["id"]] = line

        # If a receipt_id was passed at create-time, treat it as already attached
        # by binding the receipt to this line and running the OCR resolution.
        if receipt_id:
            receipt = store.receipts.get(receipt_id)
            if receipt and receipt.get("used_by_line_id") is None:
                receipt["used_by_line_id"] = line["id"]
                line_service.resolve_ocr_status(line, receipt)
            elif receipt and receipt.get("used_by_line_id") != line["id"]:
                raise err_receipt_already_used(
                    f"Receipt {receipt_id} already bound."
                )

        line_service.rollup_report(report)
        stamp_update(report)

    return success_response(serialize_expense_line(line), status=201)


@bp.get("/expense-lines/<lid>")
@require_roles("TRAVELER", "MANAGER", "FINANCE_REVIEWER", "ADMIN")
def get_line(lid):
    line = store.expense_lines.get(lid)
    if line is None:
        raise err_not_found(f"ExpenseLine {lid} not found.")
    return success_response(serialize_expense_line(line))


@bp.patch("/expense-lines/<lid>")
@require_roles("TRAVELER")
def patch_line(lid):
    line = store.expense_lines.get(lid)
    if line is None:
        raise err_not_found(f"ExpenseLine {lid} not found.")
    report = store.expense_reports.get(line["report_id"])
    if report is None:
        raise err_reference_not_found("Parent report not found.")
    trip = store.trips.get(report["trip_id"])
    if trip is None:
        raise err_reference_not_found("Parent trip not found.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the traveler may edit lines.")

    if report["status"] not in {"DRAFT", "CHANGES_REQUESTED"}:
        raise err_invalid_state(f"Report status is {report['status']}, cannot edit line.")

    body = get_json_body()

    if "version" in body and body["version"] is not None:
        if body["version"] != line["version"]:
            raise err_stale_version(
                f"version mismatch: client={body['version']}, server={line['version']}."
            )

    # Validate possible FK reference
    if "virtual_card_id" in body and body["virtual_card_id"]:
        card = store.virtual_cards.get(body["virtual_card_id"])
        if card is None:
            raise err_reference_not_found(f"virtual_card_id {body['virtual_card_id']} not found.")
        if card["trip_id"] != trip["id"]:
            raise err_card_trip_mismatch(
                f"virtual_card.trip_id={card['trip_id']} != report.trip_id={trip['id']}."
            )

    with lock():
        if report["status"] == "CHANGES_REQUESTED":
            report["status"] = "DRAFT"
            report["reviewer_id"] = None
            stamp_update(report)

        old_card_id = line.get("virtual_card_id")
        old_reimb = int(line.get("amount_reimbursable_cents") or 0)

        for field in ("amount_claimed_cents", "miles_driven", "rental_days",
                      "meal_type", "meal_was_provided", "per_diem_method",
                      "cdw_purchased", "virtual_card_id"):
            if field in body:
                if field == "amount_claimed_cents":
                    if body[field] is not None:
                        if not is_int(body[field]) or body[field] < 0:
                            raise err_validation("amount_claimed_cents must be a non-negative integer.")
                line[field] = body[field]

        # MILEAGE: claimed is server-computed
        if line["category"] == "MILEAGE" and line.get("miles_driven") is None:
            raise err_category_field_missing("miles_driven is required for MILEAGE.")

        # Recompute
        line_service.compute_line_amounts(line, trip, variant="provisional")
        new_reimb = int(line.get("amount_reimbursable_cents") or 0)

        # Reconcile card authorizations
        new_card_id = line.get("virtual_card_id")
        if old_card_id and old_card_id == new_card_id:
            delta = new_reimb - old_reimb
            if delta != 0:
                line_service.authorize_card_delta(new_card_id, delta)
        else:
            if old_card_id:
                line_service.authorize_card_delta(old_card_id, -old_reimb)
            if new_card_id:
                line_service.authorize_card_delta(new_card_id, new_reimb)

        stamp_update(line)
        line_service.rollup_report(report)
        stamp_update(report)

    return success_response(serialize_expense_line(line))


@bp.post("/expense-lines/<lid>/attach-receipt")
@require_roles("TRAVELER")
def attach_receipt(lid):
    line = store.expense_lines.get(lid)
    if line is None:
        raise err_not_found(f"ExpenseLine {lid} not found.")
    report = store.expense_reports.get(line["report_id"])
    if report is None:
        raise err_reference_not_found("Parent report not found.")
    trip = store.trips.get(report["trip_id"])
    if trip is None or trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the traveler may attach receipts.")

    body = get_json_body()
    receipt_id = body.get("receipt_id")
    if not receipt_id:
        raise err_validation("receipt_id is required.")
    receipt = store.receipts.get(receipt_id)
    if receipt is None:
        raise err_reference_not_found(f"receipt_id {receipt_id} not found.")

    if line.get("ocr_status") != "NO_RECEIPT":
        raise err_invalid_state(f"Line ocr_status is {line.get('ocr_status')}, not NO_RECEIPT.")

    with lock():
        if receipt.get("used_by_line_id"):
            raise err_receipt_already_used(
                f"Receipt {receipt_id} already bound to line {receipt['used_by_line_id']}."
            )
        receipt["used_by_line_id"] = line["id"]
        line["receipt_id"] = receipt_id
        line_service.resolve_ocr_status(line, receipt)
        stamp_update(line)
    return success_response(serialize_expense_line(line))


@bp.post("/expense-lines/<lid>/waive-ocr")
@require_roles("FINANCE_REVIEWER")
def waive_ocr(lid):
    line = store.expense_lines.get(lid)
    if line is None:
        raise err_not_found(f"ExpenseLine {lid} not found.")
    report = store.expense_reports.get(line["report_id"])
    if report is None:
        raise err_reference_not_found("Parent report not found.")
    if report["status"] != "IN_REVIEW":
        raise err_cross_entity_state(f"Report status is {report['status']}, not IN_REVIEW.")
    if line.get("ocr_status") != "OCR_MISMATCH":
        raise err_invalid_state(f"Line ocr_status is {line.get('ocr_status')}, not OCR_MISMATCH.")

    with lock():
        line["ocr_status"] = "OCR_WAIVED"
        stamp_update(line)
    return success_response(serialize_expense_line(line))
