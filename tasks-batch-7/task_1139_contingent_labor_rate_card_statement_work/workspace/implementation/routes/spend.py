from flask import Blueprint, request

from db import store
from envelope import ok, ok_list
from errors import ERR_NOT_FOUND, raise_err
from security import require_roles
from validators import apply_filters, paginate
import serializers

bp = Blueprint("spend", __name__)

READ_ROLES = ("ProgramAdmin", "FinanceAnalyst")


@bp.get("/v1/spend-ledger-entries")
def list_ledger_entries():
    require_roles(*READ_ROLES)
    filters = {
        "supplier_id": request.args.get("supplier_id"),
        "engagement_id": request.args.get("engagement_id"),
        "timesheet_id": request.args.get("timesheet_id"),
        "milestone_id": request.args.get("milestone_id"),
        "invoice_id": request.args.get("invoice_id"),
        "entry_type": request.args.get("entry_type"),
    }
    records = apply_filters(list(store.ledger.values()), filters)
    page, total, limit, offset = paginate(records, serializers.ledger_entry)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/spend-ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    require_roles(*READ_ROLES)
    e = store.ledger.get(entry_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, f"Spend ledger entry {entry_id} not found.")
    return ok(serializers.ledger_entry(e))


@bp.get("/v1/spend/summary")
def spend_summary():
    require_roles(*READ_ROLES)
    supplier_id = request.args.get("supplier_id")

    total_committed = 0
    for e in store.ledger.values():
        if supplier_id is not None and e["supplier_id"] != supplier_id:
            continue
        total_committed += e["delta_cents"]

    total_invoiced = 0
    total_paid = 0
    savings = 0
    for inv in store.invoices.values():
        if supplier_id is not None and inv["supplier_id"] != supplier_id:
            continue
        if inv["status"] in ("FINALIZED", "PAID"):
            total_invoiced += inv["total_cents"]
            savings += inv["consolidation_savings_cents"]
        if inv["status"] == "PAID":
            total_paid += inv["total_cents"]

    open_violations = 0
    for a in store.audits.values():
        if supplier_id is not None and a["supplier_id"] != supplier_id:
            continue
        if a["status"] in ("OPEN", "ACKNOWLEDGED"):
            open_violations += 1

    return ok(
        {
            "total_committed_cents": total_committed,
            "total_invoiced_cents": total_invoiced,
            "total_paid_cents": total_paid,
            "consolidation_savings_cents": savings,
            "open_violations_count": open_violations,
        }
    )
