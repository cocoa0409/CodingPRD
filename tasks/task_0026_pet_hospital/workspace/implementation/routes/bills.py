"""Bills (PRD §3.9)."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from clock import now_utc
from errors import err
from middleware import authenticate, require_roles
from response import success_object
from services.bill_calc import (
    aggregate_lines_from_visit_children,
    gross_after_discount,
    recompute_final,
    recompute_provisional,
)
from services.common import bump, init_full
from validators import require_int, require_str

bp = Blueprint("bills", __name__)


@bp.before_request
def _auth():
    authenticate()


VALID_PACKAGES = {"DENTAL_PKG", "SURGERY_PKG"}


@bp.post("/bills")
def create_bill():
    require_roles("Cashier")
    payload = request.get_json(silent=True) or {}
    visit_id = payload.get("visit_id")
    if not isinstance(visit_id, str):
        raise err("ERR_VALIDATION_FAILED", "visit_id required")
    pkg = payload.get("package_code")
    if pkg is not None and pkg not in VALID_PACKAGES:
        raise err("ERR_VALIDATION_FAILED", "package_code unknown")
    insurance_estimate = payload.get("insurance_estimate_cents", 0)
    if isinstance(insurance_estimate, bool) or not isinstance(insurance_estimate, int) \
            or insurance_estimate < 0:
        raise err("ERR_VALIDATION_FAILED", "insurance_estimate_cents must be int >= 0")
    with db.GLOBAL_LOCK:
        v = db.visits.get(visit_id)
        if not v:
            raise err("ERR_REFERENCE_NOT_FOUND", "visit_id not found")
        if db.bill_for_visit(visit_id):
            raise err("ERR_INVALID_STATE", "Bill already exists for this visit")
        b = {
            "visit_id": visit_id,
            "line_items": [],
            "package_code": pkg,
            "deposit_applied_cents": 0,
            "insurance_estimate_cents": int(insurance_estimate),
            "insurance_actual_cents": 0,
            "provisional_total_cents": 0,
            "final_total_cents": 0,
            "paid_amount_cents": 0,
            "refund_amount_cents": 0,
            "invoice_no": None,
            "status": "DRAFT",
        }
        init_full(b)
        db.bills[b["id"]] = b
        return success_object(bill_view(b), status=201)


@bp.post("/bills/<bill_id>/recompute")
def recompute_bill(bill_id):
    require_roles("Cashier")
    with db.GLOBAL_LOCK:
        b = db.bills.get(bill_id)
        if not b:
            raise err("ERR_NOT_FOUND", f"Bill {bill_id} not found")
        # PRD §3.9: "The line items contributing to the bill are aggregated
        # from the visit's children with statuses pinned exactly: only
        # finalized treatment records contribute CONSULT lines, only
        # finalized lab reports contribute LAB lines, only dispensed
        # prescriptions contribute DRUG lines, and only discharged
        # hospitalizations contribute HOSPITAL_DAY lines."
        aggregate_lines_from_visit_children(b)
        recompute_provisional(b)
        bump(b)
        return success_object(bill_view(b))


@bp.post("/bills/<bill_id>/issue")
def issue_bill(bill_id):
    require_roles("Cashier")
    with db.GLOBAL_LOCK:
        b = db.bills.get(bill_id)
        if not b:
            raise err("ERR_NOT_FOUND", f"Bill {bill_id} not found")
        if b["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Issue requires DRAFT")
        v = db.visits.get(b["visit_id"]) or {}
        if v.get("status") not in {"CONSULT_DONE", "HOSPITALIZED"}:
            raise err("ERR_INVALID_STATE", "Visit must be CONSULT_DONE or HOSPITALIZED")
        # PRD §3.9: re-aggregate children before issue so all finalized/
        # dispensed/discharged children are reflected in line_items.
        aggregate_lines_from_visit_children(b)
        # Apply deposit: min(deposit_balance, gross_after_discount).
        gad = gross_after_discount(b)
        pet = db.pets.get(v.get("pet_id")) or {}
        owner = db.owners.get(pet.get("owner_id")) or {}
        deposit_avail = int(owner.get("deposit_balance_cents", 0))
        applied = min(deposit_avail, gad)
        b["deposit_applied_cents"] = applied
        if owner:
            owner["deposit_balance_cents"] = deposit_avail - applied
            bump(owner)
        # Recompute provisional with the deposit locked in.
        recompute_provisional(b)
        b["status"] = "ISSUED"
        bump(b)
        return success_object(bill_view(b))


@bp.post("/bills/<bill_id>/issue-invoice")
def issue_invoice(bill_id):
    require_roles("Cashier")
    with db.GLOBAL_LOCK:
        b = db.bills.get(bill_id)
        if not b:
            raise err("ERR_NOT_FOUND", f"Bill {bill_id} not found")
        if b["status"] != "PAID":
            raise err("ERR_INVALID_STATE", "issue-invoice requires PAID")
        # invoice_no = INV-YYYYMMDD-{seq6}
        d = now_utc().strftime("%Y%m%d")
        seq = db.invoice_seq_per_day.get(d, 0) + 1
        db.invoice_seq_per_day[d] = seq
        b["invoice_no"] = f"INV-{d}-{seq:06d}"
        b["status"] = "INVOICED"
        bump(b)
        return success_object(bill_view(b))


@bp.post("/bills/<bill_id>/refund")
def refund_bill(bill_id):
    require_roles("Cashier")
    payload = request.get_json(silent=True) or {}
    amount = payload.get("amount_cents")
    reason = payload.get("reason")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise err("ERR_VALIDATION_FAILED", "amount_cents must be positive int")
    if not isinstance(reason, str) or not reason:
        raise err("ERR_VALIDATION_FAILED", "reason required")
    with db.GLOBAL_LOCK:
        b = db.bills.get(bill_id)
        if not b:
            raise err("ERR_NOT_FOUND", f"Bill {bill_id} not found")
        if b["status"] not in {"PAID", "INVOICED"}:
            raise err("ERR_INVALID_STATE", "refund requires PAID or INVOICED")
        if int(b["refund_amount_cents"]) + amount > int(b["paid_amount_cents"]):
            raise err("ERR_REFUND_EXCEEDS_PAID", "refund exceeds paid amount")
        b["status"] = "REFUND_PENDING"
        bump(b)
        return success_object(bill_view(b))


@bp.post("/bills/<bill_id>/cancel")
def cancel_bill(bill_id):
    require_roles("Cashier")
    with db.GLOBAL_LOCK:
        b = db.bills.get(bill_id)
        if not b:
            raise err("ERR_NOT_FOUND", f"Bill {bill_id} not found")
        if b["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Only DRAFT bills can be cancelled")
        v = db.visits.get(b["visit_id"]) or {}
        if v.get("status") != "CANCELLED":
            raise err("ERR_INVALID_STATE", "Visit must be CANCELLED to cancel bill")
        # Restore deposit if any was applied.
        applied = int(b.get("deposit_applied_cents", 0))
        if applied:
            pet = db.pets.get(v.get("pet_id")) or {}
            owner = db.owners.get(pet.get("owner_id")) or {}
            if owner:
                owner["deposit_balance_cents"] = int(owner.get("deposit_balance_cents", 0)) + applied
                bump(owner)
        b["status"] = "CANCELLED"
        bump(b)
        return success_object(bill_view(b))


def bill_view(b):
    return {
        "id": b["id"],
        "visit_id": b["visit_id"],
        "line_items": list(b.get("line_items", [])),
        "package_code": b.get("package_code"),
        "deposit_applied_cents": int(b.get("deposit_applied_cents", 0)),
        "insurance_estimate_cents": int(b.get("insurance_estimate_cents", 0)),
        "insurance_actual_cents": int(b.get("insurance_actual_cents", 0)),
        "provisional_total_cents": int(b.get("provisional_total_cents", 0)),
        "final_total_cents": int(b.get("final_total_cents", 0)),
        "paid_amount_cents": int(b.get("paid_amount_cents", 0)),
        "refund_amount_cents": int(b.get("refund_amount_cents", 0)),
        "invoice_no": b.get("invoice_no"),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }
