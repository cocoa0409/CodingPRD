"""Invoice routes: issue (compute pricing), read, void."""

from flask import Blueprint

from db import DB, new_id, LOCK
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
    ERR_INVOICE_INELIGIBLE_TASKS, ERR_DEPOSIT_OVERDRAW, raise_error,
)
from middleware import auth_required
from response import success_response
from services.common import get_json_body, require_fields
from services.serializers import serialize_invoice
from services.time_util import now_iso
from services.calculations import compute_line_item, compute_invoice_totals
from services.state import touch

bp = Blueprint("invoices", __name__)


def _final_record_abnormal_for_task(task_id):
    """Return whether the latest non-superseded SUBMITTED record on this task
    has abnormal_flag == true. Used for refund computation."""
    recs = [r for r in DB["records"].values()
            if r.get("task_id") == task_id and r.get("status") == "SUBMITTED"]
    if not recs:
        return False
    recs.sort(key=lambda r: r["created_at"])
    return bool(recs[-1].get("abnormal_flag"))


@bp.post("/clients/<cid>/invoices")
@auth_required(["LabManager"])
def issue_invoice(cid):
    client = DB["clients"].get(cid)
    if client is None:
        raise_error(ERR_NOT_FOUND, "Client not found")
    body = get_json_body()
    require_fields(body, ["task_ids"])
    task_ids = body["task_ids"]
    if not isinstance(task_ids, list) or not task_ids:
        raise_error(ERR_VALIDATION, "task_ids must be a non-empty list")
    # Validate each task: must belong to this client, must be COMPLETED, must
    # not appear in any prior invoice's line_items.
    invoiced_ids = set()
    for inv in DB["invoices"].values():
        if inv.get("status") in ("ISSUED", "PAID"):
            for li in inv.get("line_items", []):
                invoiced_ids.add(li["task_id"])

    tasks = []
    for tid in task_ids:
        # Existence check (404 per priority 5 — but invoice eligibility is
        # priority 18; the scaffold ordering puts NOT_FOUND first).
        t = DB["tasks"].get(tid)
        if t is None:
            raise_error(ERR_NOT_FOUND, f"Task {tid} not found")
        sample = DB["samples"].get(t["sample_id"])
        if sample is None or sample["client_id"] != cid:
            raise_error(ERR_INVOICE_INELIGIBLE_TASKS, "Task does not belong to client")
        if t.get("status") != "COMPLETED":
            raise_error(ERR_INVOICE_INELIGIBLE_TASKS, "Task is not COMPLETED")
        if tid in invoiced_ids:
            raise_error(ERR_INVOICE_INELIGIBLE_TASKS, "Task already invoiced")
        tasks.append(t)

    with LOCK:
        line_items = []
        for t in tasks:
            line_items.append(compute_line_item(t, _final_record_abnormal_for_task(t["id"])))
        totals = compute_invoice_totals(
            line_items,
            client_contract_id=client.get("contract_id"),
            client_deposit_balance=client.get("deposit_balance_cents", 0),
        )
        if totals["deposit_applied_cents"] > client.get("deposit_balance_cents", 0):
            raise_error(ERR_DEPOSIT_OVERDRAW, "Computed deposit exceeds available")
        now = now_iso()
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "client_id": cid,
            "line_items": line_items,
            **totals,
            "status": "ISSUED",
            "paid_at": None,
        }
        DB["invoices"][row["id"]] = row
        # Side effects on client
        client["deposit_balance_cents"] = client.get("deposit_balance_cents", 0) - totals["deposit_applied_cents"]
        client["outstanding_balance_cents"] = client.get("outstanding_balance_cents", 0) + totals["total_due_cents"]
        touch(client)
    return success_response(serialize_invoice(row), 201)


@bp.post("/invoices/<iid>/void")
@auth_required(["LabManager"])
def void_invoice(iid):
    row = DB["invoices"].get(iid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Invoice not found")
    if row.get("status") != "ISSUED":
        raise_error(ERR_INVALID_STATE, "Only ISSUED invoices may be voided")
    with LOCK:
        # If any associated report has been ISSUED or ARCHIVED, voiding is rejected
        for li in row.get("line_items", []):
            for r in DB["reports"].values():
                if r.get("task_id") == li["task_id"] and r.get("status") in ("ISSUED", "ARCHIVED"):
                    raise_error(ERR_INVALID_STATE,
                                "Cannot void invoice: associated report already issued/archived")
        row["status"] = "VOIDED"
        touch(row)
        client = DB["clients"].get(row["client_id"])
        if client is not None:
            client["outstanding_balance_cents"] = client.get("outstanding_balance_cents", 0) - row.get("total_due_cents", 0)
            client["deposit_balance_cents"] = client.get("deposit_balance_cents", 0) + row.get("deposit_applied_cents", 0)
            touch(client)
    return success_response(serialize_invoice(row), 200)


@bp.get("/invoices/<iid>")
@auth_required(["LabManager", "LabClerk"])
def read_invoice(iid):
    row = DB["invoices"].get(iid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Invoice not found")
    return success_response(serialize_invoice(row), 200)
