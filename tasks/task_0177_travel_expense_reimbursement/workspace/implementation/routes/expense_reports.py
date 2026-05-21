"""Expense Report endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import (
    err_cross_entity_state,
    err_invalid_state,
    err_not_found,
    err_per_diem_unavailable,
    err_receipt_required,
    err_reference_not_found,
    err_report_already_claimed,
    err_segregation_of_duties,
    err_stale_version,
    err_validation,
)
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_expense_report
from core.store import store
from core.utils import lock
from services import calculations, line_service
from services.clock_service import get_now_iso
from services.timestamps import stamp_create, stamp_update


bp = Blueprint("expense_reports", __name__)


@bp.post("/expense-reports")
@require_roles("TRAVELER")
def create_report():
    body = get_json_body()
    trip_id = body.get("trip_id")
    if not trip_id:
        raise err_validation("trip_id is required.")
    trip = store.trips.get(trip_id)
    if trip is None:
        raise err_reference_not_found(f"trip_id {trip_id} not found.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the traveler may open a report for this trip.")

    with lock():
        rec = {
            "trip_id": trip_id,
            "status": "DRAFT",
            "total_claimed_cents": 0,
            "total_reimbursable_cents": 0,
            "policy_violation_count": 0,
            "reviewer_id": None,
            "submitted_at": None,
            "approved_at": None,
            "reimbursed_at": None,
        }
        stamp_create(rec)
        store.expense_reports[rec["id"]] = rec
    return success_response(serialize_expense_report(rec), status=201)


@bp.get("/expense-reports")
@require_roles("TRAVELER", "FINANCE_REVIEWER", "ADMIN")
def list_reports():
    traveler_id = request.args.get("traveler_id")
    status_f = request.args.get("status")
    trip_id = request.args.get("trip_id")

    items = list(store.expense_reports.values())
    if trip_id:
        items = [r for r in items if r["trip_id"] == trip_id]
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    if traveler_id:
        items = [r for r in items if (store.trips.get(r["trip_id"]) or {}).get("traveler_id") == traveler_id]

    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    page, meta = paginate(items, limit, offset)
    return success_response(
        [serialize_expense_report(r) for r in page],
        response_type="array",
        pagination=meta,
    )


@bp.get("/expense-reports/<rid>")
@require_roles("TRAVELER", "MANAGER", "FINANCE_REVIEWER", "ADMIN")
def get_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    return success_response(serialize_expense_report(rec))


@bp.patch("/expense-reports/<rid>")
@require_roles("TRAVELER")
def patch_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    trip = store.trips.get(rec["trip_id"])
    if trip is None or trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the traveler may edit this report.")
    if rec["status"] not in {"DRAFT", "CHANGES_REQUESTED"}:
        raise err_invalid_state(f"Cannot edit report in status {rec['status']}.")

    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if body["version"] != rec["version"]:
            raise err_stale_version(
                f"version mismatch: client={body['version']}, server={rec['version']}."
            )

    with lock():
        if rec["status"] == "CHANGES_REQUESTED":
            rec["status"] = "DRAFT"
            rec["reviewer_id"] = None
        stamp_update(rec)
    return success_response(serialize_expense_report(rec))


@bp.post("/expense-reports/<rid>/submit")
@require_roles("TRAVELER")
def submit_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    if rec["status"] != "DRAFT":
        raise err_invalid_state(f"Report status is {rec['status']}, not DRAFT.")
    trip = store.trips.get(rec["trip_id"])
    if trip is None:
        raise err_reference_not_found("Parent trip not found.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the traveler may submit this report.")
    if trip["status"] not in {"APPROVED", "COMPLETED"}:
        raise err_cross_entity_state(f"Trip status is {trip['status']}, not APPROVED/COMPLETED.")

    lines = store.lines_for_report(rid)
    active = [ln for ln in lines if ln.get("line_status") == "ACTIVE"]
    if not active:
        raise err_invalid_state("Report has no ACTIVE lines.")

    for ln in active:
        if ln.get("category") in {"LODGING", "RENTAL_CAR", "FLIGHT"}:
            if not ln.get("receipt_id"):
                raise err_receipt_required(
                    f"Line {ln['id']} (category {ln['category']}) requires a receipt."
                )
            if ln.get("ocr_status") not in {"OCR_VERIFIED", "OCR_MISMATCH", "OCR_WAIVED"}:
                raise err_invalid_state(
                    f"Line {ln['id']} ocr_status is {ln.get('ocr_status')}; must be verified/mismatch/waived."
                )

    with lock():
        rec["status"] = "SUBMITTED"
        rec["submitted_at"] = get_now_iso()
        line_service.rollup_report(rec)
        stamp_update(rec)
    return success_response(serialize_expense_report(rec))


@bp.post("/expense-reports/<rid>/claim")
@require_roles("FINANCE_REVIEWER")
def claim_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    with lock():
        if rec["status"] != "SUBMITTED":
            # If already claimed, signal already-claimed; otherwise invalid state
            if rec.get("reviewer_id") and rec["status"] == "IN_REVIEW":
                raise err_report_already_claimed(
                    f"Report already claimed by {rec['reviewer_id']}."
                )
            raise err_invalid_state(f"Report status is {rec['status']}, not SUBMITTED.")
        rec["status"] = "IN_REVIEW"
        rec["reviewer_id"] = current_user_id()
        stamp_update(rec)
    return success_response(serialize_expense_report(rec))


@bp.post("/expense-reports/<rid>/approve")
@require_roles("FINANCE_REVIEWER")
def approve_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    if rec["status"] != "IN_REVIEW":
        raise err_invalid_state(f"Report status is {rec['status']}, not IN_REVIEW.")
    trip = store.trips.get(rec["trip_id"])
    if trip is None:
        raise err_reference_not_found("Parent trip not found.")
    if current_user_id() == trip["traveler_id"]:
        raise err_segregation_of_duties("Approver cannot be the trip's traveler.")
    if rec.get("reviewer_id") != current_user_id():
        raise err_invalid_state("Only the claiming reviewer may approve.")

    # Every OUT_OF_POLICY line must have a FINAL_APPROVED OOP approval
    lines = store.lines_for_report(rid)
    for ln in lines:
        if ln.get("policy_status") == "OUT_OF_POLICY":
            ok = False
            for app in store.oop_for_line(ln["id"]):
                if app.get("chain_level") == "FINAL_APPROVED":
                    ok = True
                    break
            if not ok:
                raise err_invalid_state(
                    f"Line {ln['id']} OUT_OF_POLICY without FINAL_APPROVED OOP."
                )

    with lock():
        # Replay FINAL variant of meal & flight & lodging calculations
        # against the trip's pinned per-diem rate (PRD §3.7, §3.8, §3.11).
        # PRD §3.11: "the chronological variant fires at report approval
        # and replays the variance against `Trip.pinned_per_diem_rate_id`"
        # — the replay produces both an updated reimbursable amount AND
        # an updated policy_status when the two variants diverge.
        # OOP_APPROVED / OOP_DENIED outcomes from the OOP chain are
        # honored and not overwritten by the replay.
        terminal_oop_states = {"OOP_APPROVED", "OOP_DENIED"}
        for ln in lines:
            if ln.get("line_status") == "VOIDED":
                continue
            cat = ln.get("category")
            old_reimb = int(ln.get("amount_reimbursable_cents") or 0)
            current_policy = ln.get("policy_status")
            if cat == "MEAL":
                amount, policy, _cap = calculations.compute_meal_reimbursement(ln, trip, variant="final")
                if current_policy == "OOP_APPROVED":
                    ln["amount_reimbursable_cents"] = int(ln.get("amount_claimed_cents") or 0)
                elif current_policy == "OOP_DENIED":
                    ln["amount_reimbursable_cents"] = amount
                elif ln.get("meal_was_provided"):
                    ln["amount_reimbursable_cents"] = 0
                    ln["policy_status"] = "IN_POLICY"
                else:
                    ln["amount_reimbursable_cents"] = amount
                    ln["policy_status"] = policy
            elif cat == "FLIGHT":
                amount, policy, _llf = calculations.compute_flight_reimbursement(ln, trip, variant="final")
                if current_policy == "OOP_APPROVED":
                    ln["amount_reimbursable_cents"] = int(ln.get("amount_claimed_cents") or 0)
                elif current_policy == "OOP_DENIED":
                    ln["amount_reimbursable_cents"] = amount
                else:
                    ln["amount_reimbursable_cents"] = amount
                    ln["policy_status"] = policy
            elif cat == "LODGING":
                amount, policy = calculations.compute_lodging_reimbursement(ln, trip, variant="final")
                if current_policy == "OOP_APPROVED":
                    ln["amount_reimbursable_cents"] = int(ln.get("amount_claimed_cents") or 0)
                elif current_policy == "OOP_DENIED":
                    ln["amount_reimbursable_cents"] = amount
                else:
                    ln["amount_reimbursable_cents"] = amount
                    ln["policy_status"] = policy
            new_reimb = int(ln.get("amount_reimbursable_cents") or 0)
            if new_reimb != old_reimb or ln.get("policy_status") != current_policy:
                # If the line is tied to a virtual card, adjust authorization
                if ln.get("virtual_card_id"):
                    delta = new_reimb - old_reimb
                    if delta != 0:
                        line_service.authorize_card_delta(ln["virtual_card_id"], delta)
                stamp_update(ln)

        rec["status"] = "APPROVED"
        rec["approved_at"] = get_now_iso()
        line_service.rollup_report(rec)
        stamp_update(rec)
    return success_response(serialize_expense_report(rec))


@bp.post("/expense-reports/<rid>/reject")
@require_roles("FINANCE_REVIEWER")
def reject_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    if rec["status"] != "IN_REVIEW":
        raise err_invalid_state(f"Report status is {rec['status']}, not IN_REVIEW.")
    if rec.get("reviewer_id") != current_user_id():
        raise err_invalid_state("Only the claiming reviewer may reject.")

    with lock():
        rec["status"] = "REJECTED"
        stamp_update(rec)
        for ln in store.lines_for_report(rid):
            if ln.get("line_status") == "ACTIVE":
                ln["line_status"] = "VOIDED"
                # Cascade hop 2: deauthorize card
                if ln.get("virtual_card_id"):
                    card = store.virtual_cards.get(ln["virtual_card_id"])
                    if card is not None:
                        new_auth = int(card.get("authorized_amount_cents") or 0) - int(ln.get("amount_reimbursable_cents") or 0)
                        if new_auth < 0:
                            new_auth = 0
                        card["authorized_amount_cents"] = new_auth
                        stamp_update(card)
                stamp_update(ln)
                # Cascade hop 3: bound OOP approvals -> DENIED
                for app in store.oop_for_line(ln["id"]):
                    if app["chain_level"] not in {"DENIED", "FINAL_APPROVED"}:
                        app["chain_level"] = "DENIED"
                        stamp_update(app)
        line_service.rollup_report(rec)
    return success_response(serialize_expense_report(rec))


@bp.post("/expense-reports/<rid>/request-changes")
@require_roles("FINANCE_REVIEWER")
def request_changes_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    if rec["status"] != "IN_REVIEW":
        raise err_invalid_state(f"Report status is {rec['status']}, not IN_REVIEW.")
    if rec.get("reviewer_id") != current_user_id():
        raise err_invalid_state("Only the claiming reviewer may request changes.")

    with lock():
        rec["status"] = "CHANGES_REQUESTED"
        stamp_update(rec)
    return success_response(serialize_expense_report(rec))


@bp.post("/expense-reports/<rid>/disburse")
@require_roles("FINANCE_REVIEWER")
def disburse_report(rid):
    rec = store.expense_reports.get(rid)
    if rec is None:
        raise err_not_found(f"ExpenseReport {rid} not found.")
    if rec["status"] != "APPROVED":
        raise err_invalid_state(f"Report status is {rec['status']}, not APPROVED.")
    if not rec.get("approved_at"):
        raise err_invalid_state("approved_at is null.")
    trip = store.trips.get(rec["trip_id"])
    if trip is None:
        raise err_reference_not_found("Parent trip not found.")
    if current_user_id() == trip["traveler_id"]:
        raise err_segregation_of_duties("Disburser cannot be the traveler.")

    with lock():
        rec["status"] = "REIMBURSED"
        rec["reimbursed_at"] = get_now_iso()
        for ln in store.lines_for_report(rid):
            if ln.get("line_status") == "ACTIVE":
                ln["line_status"] = "REIMBURSED"
                stamp_update(ln)
        stamp_update(rec)
    return success_response(serialize_expense_report(rec))
