"""Invoice endpoints (PRD §3.10)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services import calculations
from services.common import (
    new_record,
    optional_str,
    paginate,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.derived import recompute_balance_due_cents
from services.lookup import (
    get_invoice_or_404,
    get_pool_or_404,
    get_visit_or_404,
    get_work_order_or_404,
)

bp = Blueprint("invoices", __name__)


def _serialize_invoice(inv):
    out = serialize(inv)
    out["amount_cents"] = inv["amount_cents"]
    return out


@bp.post("/invoices")
@require_roles("AccountManager")
def create_invoice():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        pool_id = require_str(body, "pool_id")
        visit_id = optional_str(body, "visit_id")
        work_order_id = optional_str(body, "work_order_id")
        # Existence (priority 3) before reference-mismatch (priority 15).
        get_pool_or_404(pool_id)
        if visit_id is not None:
            get_visit_or_404(visit_id)
        if work_order_id is not None:
            get_work_order_or_404(work_order_id)
        # Exactly one of visit_id / work_order_id (priority 15).
        if (visit_id is None) == (work_order_id is None):
            raise err(
                "ERR_INVOICE_REFERENCE_MISMATCH",
                "Invoice must reference exactly one of visit_id or work_order_id",
            )
        rec = new_record(
            {
                "pool_id": pool_id,
                "visit_id": visit_id,
                "work_order_id": work_order_id,
                "amount_cents": 0,
                "status": "DRAFT",
            }
        )
        db.invoices[rec["id"]] = rec
        return success(_serialize_invoice(rec), 201)


@bp.get("/invoices/<inv_id>")
@require_roles("AccountManager", "Customer")
def get_invoice(inv_id):
    with db.lock:
        inv = get_invoice_or_404(inv_id)
        return success(_serialize_invoice(inv), 200)


@bp.get("/invoices")
@require_roles("AccountManager", "Customer")
def list_invoices():
    with db.lock:
        limit, offset = paginate(request.args)
        items = list(db.invoices.values())
        for key in ("pool_id", "visit_id", "work_order_id"):
            val = request.args.get(key)
            if val is not None:
                items = [i for i in items if i.get(key) == val]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([_serialize_invoice(i) for i in page], limit, offset, total)


@bp.post("/invoices/<inv_id>/issue")
@require_roles("AccountManager")
def issue_invoice(inv_id):
    with db.lock:
        inv = get_invoice_or_404(inv_id)
        # State validity (priority 5): invoice DRAFT, referenced work occurred.
        if inv["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Invoice cannot be issued from its current state")
        visit_part = 0
        repair_part = 0
        if inv["visit_id"] is not None:
            visit = db.visits.get(inv["visit_id"])
            if visit is None or visit["status"] != "COMPLETED":
                raise err("ERR_INVALID_STATE", "Referenced visit is not completed")
            visit_part = visit["billed_amount_cents"]
        if inv["work_order_id"] is not None:
            wo = db.work_orders.get(inv["work_order_id"])
            if wo is None or wo["status"] != "RESOLVED":
                raise err("ERR_INVALID_STATE", "Referenced work order is not resolved")
            repair_part = wo["repair_total_cents"]
        amount = calculations.invoice_total(visit_part, repair_part)
        # Nothing-to-bill (priority 14).
        if amount == 0:
            raise err("ERR_NOTHING_TO_BILL", "Invoice would compute to a zero amount")
        inv["status"] = "ISSUED"
        inv["amount_cents"] = amount
        touch(inv)
        recompute_balance_due_cents(db.pools[inv["pool_id"]])
        return success(_serialize_invoice(inv), 200)


@bp.post("/invoices/<inv_id>/pay")
@require_roles("AccountManager")
def pay_invoice(inv_id):
    with db.lock:
        inv = get_invoice_or_404(inv_id)
        if inv["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Invoice cannot be paid from its current state")
        inv["status"] = "PAID"
        touch(inv)
        recompute_balance_due_cents(db.pools[inv["pool_id"]])
        return success(_serialize_invoice(inv), 200)


@bp.post("/invoices/<inv_id>/void")
@require_roles("AccountManager")
def void_invoice(inv_id):
    with db.lock:
        inv = get_invoice_or_404(inv_id)
        prev_status = inv["status"]
        if prev_status not in ("DRAFT", "ISSUED"):
            raise err("ERR_INVALID_STATE", "Invoice cannot be voided from its current state")
        inv["status"] = "VOIDED"
        touch(inv)
        # DRAFT void has no balance effect; ISSUED void recomputes balance.
        if prev_status == "ISSUED":
            recompute_balance_due_cents(db.pools[inv["pool_id"]])
        return success(_serialize_invoice(inv), 200)
