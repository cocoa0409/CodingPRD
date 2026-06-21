"""Monthly invoicing: generate (rollup), issue (lock), pay (wallet debit)."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import get_identity, require_roles, get_json_body, parse_pagination
from response import success, paginated
from services.common import (
    stamp_new, touch, public, find_member, get_or_404, sorted_by_creation,
    paginate, require_fields, parse_dt,
)
from services.calculations import invoice_totals

bp = Blueprint("invoices", __name__)


def _load_member_invoice(member_id, invoice_id):
    find_member(member_id)
    invoice = get_or_404(db.invoices, invoice_id)
    if invoice["member_id"] != member_id:
        raise ApiError("ERR_NOT_FOUND")
    return invoice


@bp.post("/members/<member_id>/invoices")
def create_invoice(member_id):
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    body = get_json_body()
    with LOCK:
        find_member(member_id)
        require_fields(body, ["period_start_utc", "period_end_utc"])
        start_dt = parse_dt(body["period_start_utc"])
        end_dt = parse_dt(body["period_end_utc"])
        if start_dt is None or end_dt is None:
            raise ApiError("ERR_INVALID_REQUEST")
        if not (end_dt > start_dt):
            raise ApiError("ERR_INVALID_INTERVAL")

        # booking_subtotal: COMPLETED bookings whose end_utc in [start, end).
        booking_subtotal = 0
        for b in db.bookings.values():
            if b["member_id"] != member_id or b["status"] != "COMPLETED":
                continue
            end = parse_dt(b["end_utc"])
            if end is not None and start_dt <= end < end_dt:
                booking_subtotal += b["fee_cents"]

        # storage_subtotal: ACTIVE assignments at generation time.
        storage_subtotal = 0
        for a in db.storage_assignments.values():
            if a["member_id"] == member_id and a["status"] == "ACTIVE":
                storage_subtotal += a["monthly_fee_cents"]

        # production_subtotal: COMPLETED batches whose completion in [start, end).
        production_subtotal = 0
        for p in db.production_batches.values():
            if p["member_id"] != member_id or p["status"] != "COMPLETED":
                continue
            done = parse_dt(p.get("_completed_at")) if p.get("_completed_at") else None
            if done is not None and start_dt <= done < end_dt:
                production_subtotal += p["production_fee_cents"] or 0

        totals = invoice_totals(booking_subtotal, storage_subtotal, production_subtotal)

        invoice = {
            "member_id": member_id,
            "period_start_utc": body["period_start_utc"],
            "period_end_utc": body["period_end_utc"],
            "booking_subtotal_cents": booking_subtotal,
            "storage_subtotal_cents": storage_subtotal,
            "production_subtotal_cents": production_subtotal,
            "subtotal_cents": totals["subtotal_cents"],
            "loyalty_discount_cents": totals["loyalty_discount_cents"],
            "platform_fee_cents": totals["platform_fee_cents"],
            "total_cents": totals["total_cents"],
            "status": "DRAFT",
        }
        stamp_new(invoice)
        db.invoices[invoice["id"]] = invoice
        return success(public(invoice), 201)


@bp.get("/members/<member_id>/invoices")
def list_member_invoices(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        find_member(member_id)
        records = [i for i in db.invoices.values() if i["member_id"] == member_id]
        records = sorted_by_creation(records)
        if status:
            records = [i for i in records if i["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/members/<member_id>/invoices/<invoice_id>")
def get_member_invoice(member_id, invoice_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        invoice = _load_member_invoice(member_id, invoice_id)
        return success(public(invoice))


@bp.post("/members/<member_id>/invoices/<invoice_id>/issue")
def issue_invoice(member_id, invoice_id):
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    with LOCK:
        invoice = _load_member_invoice(member_id, invoice_id)
        if invoice["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        invoice["status"] = "ISSUED"
        touch(invoice)
        return success(public(invoice))


@bp.post("/members/<member_id>/invoices/<invoice_id>/pay")
def pay_invoice(member_id, invoice_id):
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    with LOCK:
        invoice = _load_member_invoice(member_id, invoice_id)
        if invoice["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE")
        member = db.members[member_id]
        total = invoice["total_cents"]
        if member["wallet_balance_cents"] < total:
            raise ApiError("ERR_INSUFFICIENT_WALLET")
        member["wallet_balance_cents"] -= total
        member["lifetime_charged_cents"] += total
        touch(member)
        invoice["status"] = "PAID"
        touch(invoice)
        return success(public(invoice))
