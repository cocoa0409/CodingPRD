"""Invoice endpoints: TM vs LUMP_SUM variants, retainage, NTE cap, append-only records."""
from flask import Blueprint

import db
from errors import (ApiError, ERR_FINAL_INVOICE_EXISTS, ERR_INVALID_STATE,
                    ERR_NO_BILLABLE_WORK, ERR_NTE_EXCEEDED, ERR_VALIDATION)
from helpers import project_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import invoice_json
from util import D, new_id, now_iso, round_half_up_int
from validators import get_body, pagination, req_date, req_enum, req_num, req_str

bp = Blueprint("invoices", __name__)


@bp.post("/v1/invoices")
@require_roles("ProjectManager")
def create_invoice():
    body = get_body()
    # existence (priority 3)
    pid = body.get("project_id")
    project = project_or_404(pid) if isinstance(pid, str) else None
    # state gate (priority 5): invoice kind vs project phase
    kind_raw = body.get("kind")
    if project is not None and kind_raw in ("PROGRESS", "FINAL"):
        ws = project["work_status"]
        if kind_raw == "PROGRESS" and ws not in ("MOBILIZED", "INSTALLING", "COMMISSIONING"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "PROGRESS invoices require MOBILIZED, INSTALLING or COMMISSIONING")
        if kind_raw == "FINAL" and ws != "COMPLETED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "FINAL invoices require the project to be COMPLETED")
    # schema (priority 7)
    req_str(body, "project_id")
    kind = req_enum(body, "kind", ("PROGRESS", "FINAL"))
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if period_end < period_start:
        raise ApiError(ERR_VALIDATION, 400, "'period_end': must be >= period_start")
    mode = project["billing_mode"]
    if mode == "LUMP_SUM":
        pct_raw, pct_d = req_num(body, "progress_pct", ge=0, le=100)
    else:
        if "progress_pct" in body and body["progress_pct"] is not None:
            raise ApiError(ERR_VALIDATION, 400,
                           "'progress_pct': forbidden for TM projects")
        pct_raw, pct_d = None, None

    prior_invoices = sorted_items(i for i in db.invoices.values()
                                  if i["project_id"] == project["id"])
    prior_gross = sum(i["gross_cents"] for i in prior_invoices)

    labor_rows, lift_rows = [], []
    if mode == "TM":
        labor_rows = sorted_items(
            e for e in db.labor_entries.values()
            if e["project_id"] == project["id"] and e["status"] == "APPROVED"
            and period_start <= e["_work_date"] <= period_end)
        lift_rows = sorted_items(
            l for l in db.lift_permits.values()
            if l["project_id"] == project["id"] and l["status"] == "EXECUTED"
            and period_start <= l["_starts_dt"].date() <= period_end)
        gross = (sum(e["total_cost_cents"] for e in labor_rows)
                 + sum(l["equipment_charge_cents"] for l in lift_rows))
    else:
        # LUMP_SUM: cumulative target minus previously invoiced gross
        target = round_half_up_int(D(project["contract_amount_cents"]) * pct_d / D(100))
        gross = target - prior_gross

    # fiscal rules (priorities 26-28)
    if mode == "TM" and prior_gross + gross > project["contract_amount_cents"]:
        raise ApiError(ERR_NTE_EXCEEDED, 409,
                       "invoice would exceed the contract not-to-exceed cap")
    if kind == "FINAL" and any(i["kind"] == "FINAL" for i in prior_invoices):
        raise ApiError(ERR_FINAL_INVOICE_EXISTS, 409,
                       "a FINAL invoice already exists for the project")
    if kind == "PROGRESS" and gross <= 0:
        raise ApiError(ERR_NO_BILLABLE_WORK, 409,
                       "PROGRESS invoice has no positive billable content")

    # shared retainage tail: rounded half-up once on the summed gross
    retainage = round_half_up_int(D(gross) * D(project["retainage_pct"]))
    released = (sum(i["retainage_cents"] for i in prior_invoices)
                if kind == "FINAL" else 0)
    amount = gross - retainage + released

    inv = {
        "id": new_id(),
        "created_at": now_iso(),
        "project_id": project["id"],
        "kind": kind,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "progress_pct": pct_raw,
        "billing_mode_snapshot": mode,
        "gross_cents": gross,
        "retainage_cents": retainage,
        "retainage_released_cents": released,
        "amount_cents": amount,
        "labor_entry_ids": [e["id"] for e in labor_rows] if mode == "TM" else [],
        "lift_permit_ids": [l["id"] for l in lift_rows] if mode == "TM" else [],
        "_seq": db.next_seq(),
    }
    db.invoices[inv["id"]] = inv
    # TM: swept labor entries transition APPROVED -> INVOICED (terminal)
    for e in labor_rows:
        e["status"] = "INVOICED"
        touch(e)
    # rollup re-evaluation (invoiced_cents) mutates the project
    touch(project)
    return success(invoice_json(inv), 201)


@bp.get("/v1/projects/<pid>/invoices")
@require_roles(*ROLES)
def list_invoices(pid):
    project_or_404(pid)
    limit, offset = pagination()
    items = sorted_items(i for i in db.invoices.values() if i["project_id"] == pid)
    total = len(items)
    return success_list([invoice_json(i) for i in items[offset:offset + limit]],
                        limit, offset, total)
