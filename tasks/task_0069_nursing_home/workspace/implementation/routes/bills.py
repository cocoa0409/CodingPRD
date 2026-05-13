"""Bill endpoints."""
from flask import request

from clock import iso_now, parse_date
from db import LOCK, get_db
from errors import APIError
from helpers import (new_entity, paginate, parse_pagination, require_body,
                     require_enum, require_field, touch)
from middleware import require_roles
from response import list_success, success
from services import billing as billing_svc
from services import elder as elder_svc


BILLING_MODES = {"PACKAGE", "A_LA_CARTE"}


def _serialize(b):
    return dict(b)


def register(app):

    @app.post("/elders/<eid>/bills")
    @require_roles("Finance")
    def create_bill(user_id, role, eid):
        body = require_body()
        cycle_start_date = require_field(body, "cycle_start_date", str)
        cycle_end_date = require_field(body, "cycle_end_date", str)
        billing_mode = require_enum(body, "billing_mode", BILLING_MODES)
        try:
            cs = parse_date(cycle_start_date)
            ce = parse_date(cycle_end_date)
        except Exception:
            raise APIError("ERR_VALIDATION", "cycle dates must be YYYY-MM-DD", 422)
        if ce < cs:
            raise APIError("ERR_VALIDATION", "cycle_end_date >= cycle_start_date", 422)
        if cs.month != ce.month or cs.year != ce.year:
            raise APIError("ERR_VALIDATION", "cycle must be within same calendar month", 422)
        # Optional medical_line_items, actual_meal_count carried on bill for finalize.
        medical_lines = body.get("medical_line_items") or []
        actual_meal_count = body.get("actual_meal_count") or 0
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            b = new_entity({
                "elder_id": eid,
                "cycle_start_date": cycle_start_date,
                "cycle_end_date": cycle_end_date,
                "billing_mode": billing_mode,
                "line_items": [],
                "subtotal_cents": 0,
                "government_subsidy_cents": 0,
                "insurance_offset_cents": 0,
                "deposit_applied_cents": 0,
                "amount_due_cents": 0,
                "status": "DRAFT",
                "finalized_at": None,
                "paid_at": None,
                "external_payment_ref": None,
                "_medical_line_items": medical_lines,
                "_actual_meal_count": actual_meal_count,
            })
            db.bills[b["id"]] = b
            return success(_serialize(b), status=201)

    @app.post("/bills/<bid>/finalize")
    @require_roles("Finance")
    def finalize_bill(user_id, role, bid):
        body = require_body()
        with LOCK:
            db = get_db()
            b = db.bills.get(bid)
            if b is None:
                raise APIError("ERR_NOT_FOUND", f"Bill {bid} not found", 404)
            if b["status"] != "DRAFT":
                raise APIError("ERR_INVALID_STATE",
                               f"Bill is {b['status']}, expected DRAFT", 409)
            elder = db.elders.get(b["elder_id"])
            if elder is None:
                raise APIError("ERR_INVALID_STATE", "Elder missing", 409)
            # Allow body to override medical_line_items and actual_meal_count
            medical_lines = body.get("medical_line_items")
            actual_meal_count = body.get("actual_meal_count")
            if medical_lines is None:
                medical_lines = b.get("_medical_line_items") or []
            if actual_meal_count is None:
                actual_meal_count = b.get("_actual_meal_count") or 0
            billing_svc.finalize_bill(b, elder, medical_lines, actual_meal_count)
            touch(b)
            elder_svc.recompute_outstanding_balance(elder["id"])
            return success(_serialize(b))

    @app.post("/bills/<bid>/pay")
    @require_roles("Family", "Finance")
    def pay_bill(user_id, role, bid):
        body = require_body()
        external_payment_ref = require_field(body, "external_payment_ref", str)
        with LOCK:
            db = get_db()
            b = db.bills.get(bid)
            if b is None:
                raise APIError("ERR_NOT_FOUND", f"Bill {bid} not found", 404)
            # Duplicate-ref handling
            existing_bill_id = db.bill_external_payment_refs.get(external_payment_ref)
            if existing_bill_id is not None:
                if existing_bill_id == bid:
                    # Idempotent replay — return current bill state without re-applying
                    return success(_serialize(b))
                else:
                    raise APIError("ERR_DUPLICATE_PAYMENT",
                                   "external_payment_ref already used on a different bill", 409)
            if b["status"] != "FINALIZED":
                raise APIError("ERR_BILL_NOT_FINALIZED",
                               f"Bill is {b['status']}, not FINALIZED", 409)
            b["status"] = "PAID"
            b["paid_at"] = iso_now()
            b["external_payment_ref"] = external_payment_ref
            db.bill_external_payment_refs[external_payment_ref] = bid
            touch(b)
            elder_svc.recompute_outstanding_balance(b["elder_id"])
            return success(_serialize(b))

    @app.post("/bills/<bid>/adjust")
    @require_roles("Finance")
    def adjust_bill(user_id, role, bid):
        body = require_body()
        adjustment_reason = require_field(body, "adjustment_reason", str)
        override = require_field(body, "override_amount_due_cents", int)
        if override < 0:
            raise APIError("ERR_VALIDATION", "override_amount_due_cents must be >= 0", 422)
        with LOCK:
            db = get_db()
            b = db.bills.get(bid)
            if b is None:
                raise APIError("ERR_NOT_FOUND", f"Bill {bid} not found", 404)
            if b["status"] != "FINALIZED":
                raise APIError("ERR_INVALID_STATE",
                               f"Bill is {b['status']}, expected FINALIZED", 409)
            b["status"] = "ADJUSTED"
            b["adjustment_reason"] = adjustment_reason
            b["amount_due_cents"] = override
            touch(b)
            elder_svc.recompute_outstanding_balance(b["elder_id"])
            return success(_serialize(b))

    @app.post("/bills/<bid>/refund")
    @require_roles("Finance")
    def refund_bill(user_id, role, bid):
        body = require_body()
        refund_amount = require_field(body, "refund_amount_cents", int)
        reason = require_field(body, "reason", str)
        if refund_amount < 0:
            raise APIError("ERR_VALIDATION", "refund_amount_cents must be >= 0", 422)
        with LOCK:
            db = get_db()
            b = db.bills.get(bid)
            if b is None:
                raise APIError("ERR_NOT_FOUND", f"Bill {bid} not found", 404)
            if b["status"] != "PAID":
                raise APIError("ERR_INVALID_STATE",
                               f"Bill is {b['status']}, expected PAID", 409)
            deposit_applied = int(b.get("deposit_applied_cents", 0))
            # "amount paid externally" = subtotal - subsidy - insurance - deposit_applied
            remaining_after_deposit = max(
                0,
                int(b.get("subtotal_cents", 0))
                - int(b.get("government_subsidy_cents", 0))
                - int(b.get("insurance_offset_cents", 0))
                - deposit_applied
            )
            ceiling = deposit_applied + remaining_after_deposit
            if refund_amount > ceiling:
                raise APIError("ERR_REFUND_OVER_LIMIT",
                               f"Refund {refund_amount} exceeds ceiling {ceiling}", 422)
            elder = get_db().elders.get(b["elder_id"])
            if elder is not None:
                refund_to_deposit = min(refund_amount, deposit_applied)
                elder["deposit_balance_cents"] = int(elder.get("deposit_balance_cents", 0)) + refund_to_deposit
                touch(elder)
            b["status"] = "REFUNDED"
            b["refund_amount_cents"] = refund_amount
            b["refund_reason"] = reason
            touch(b)
            elder_svc.recompute_outstanding_balance(b["elder_id"])
            return success(_serialize(b))

    @app.get("/elders/<eid>/bills")
    @require_roles("Finance", "Family", "Admin")
    def list_elder_bills(user_id, role, eid):
        limit, offset = parse_pagination()
        status_f = request.args.get("status")
        db = get_db()
        if db.elders.get(eid) is None:
            raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
        items = [b for b in db.bills.values() if b["elder_id"] == eid]
        if status_f:
            items = [b for b in items if b["status"] == status_f]
        items.sort(key=lambda b: b["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize(b) for b in page], limit, offset, total)

    @app.get("/bills/<bid>")
    @require_roles("Finance", "Family", "Admin")
    def get_bill(user_id, role, bid):
        db = get_db()
        b = db.bills.get(bid)
        if b is None:
            raise APIError("ERR_NOT_FOUND", f"Bill {bid} not found", 404)
        return success(_serialize(b))
