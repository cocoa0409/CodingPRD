"""Invoices, payments, reversals (PRD §3.9)."""

from flask import Blueprint, request

from db import (
    current_date,
    logical_now_iso,
    parse_date,
    public,
    sort_by_creation,
    stamp_new,
    stamp_new_payment,
    store,
    touch,
)
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import (
    check_grower_on_invoice,
    check_grower_on_payment,
    get_customer,
    get_invoice,
    get_payment,
)
from services.calculations import drying_charge, find_schedule
from validation import get_body, paginate, req_date, req_int

bp = Blueprint("billing", __name__)

READ_ROLES = {"ElevatorManager", "Grower"}


def _completion_date(run):
    if run["actual_end"] is None:
        return None
    return run["actual_end"][:10]


def _compose_lines(customer_id, period_start, period_end):
    """invoice_composition: per-line integer rounding, then a plain sum."""
    start_d, end_d = parse_date(period_start), parse_date(period_end)
    lots = [l for l in store.lots.values() if l["customer_id"] == customer_id]
    lines = []
    draft_schedule_id = None

    # DRYING: one per distinct lot with >= 1 COMPLETED run completed in period
    for lot in sort_by_creation(lots):
        completed = [
            r for r in store.runs.values()
            if r["lot_id"] == lot["id"] and r["status"] == "COMPLETED"
            and _completion_date(r) is not None
            and start_d <= parse_date(_completion_date(r)) <= end_d
        ]
        if not completed:
            continue
        completed.sort(key=lambda r: (r["actual_end"], r["_seq"]))
        completion = parse_date(_completion_date(completed[0]))
        schedule = find_schedule(lot["commodity"], completion)
        if schedule is None:
            continue
        amount = drying_charge(lot, schedule)["drying_charge_cents"]
        if draft_schedule_id is None:
            draft_schedule_id = schedule["id"]
        lines.append(
            {
                "line_type": "DRYING",
                "ref_id": lot["id"],
                "description": "Drying charge for lot %s" % lot["id"],
                "amount_cents": amount,
            }
        )

    # ENERGY: one per COMPLETED run of the customer's lots completed in period
    for lot in sort_by_creation(lots):
        runs = [
            r for r in store.runs.values()
            if r["lot_id"] == lot["id"] and r["status"] == "COMPLETED"
            and _completion_date(r) is not None
            and start_d <= parse_date(_completion_date(r)) <= end_d
        ]
        runs.sort(key=lambda r: (r["actual_end"], r["_seq"]))
        for run in runs:
            lines.append(
                {
                    "line_type": "ENERGY",
                    "ref_id": run["id"],
                    "description": "Energy pass-through for run %s" % run["id"],
                    "amount_cents": run["energy_charge_cents"] or 0,
                }
            )

    # STORAGE: one per agreement of the customer's lots whose closed_date falls
    # in period; billed only on the first invoice whose period covers the close
    already_billed = set()
    for inv in store.invoices.values():
        if inv["status"] == "VOID":
            continue
        for line in inv["lines"]:
            if line["line_type"] == "STORAGE":
                already_billed.add(line["ref_id"])
    for lot in sort_by_creation(lots):
        agreements = [
            a for a in store.agreements.values()
            if a["lot_id"] == lot["id"] and a["closed_date"] is not None
            and start_d <= parse_date(a["closed_date"]) <= end_d
            and a["id"] not in already_billed
        ]
        agreements.sort(key=lambda a: (a["closed_date"], a["_seq"]))
        for agreement in agreements:
            lines.append(
                {
                    "line_type": "STORAGE",
                    "ref_id": agreement["id"],
                    "description": "Storage accrual for agreement %s" % agreement["id"],
                    "amount_cents": agreement["accrued_storage_cents"],
                }
            )
    return lines, draft_schedule_id


@bp.post("/invoices")
def create_invoice():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    body = get_body()
    # priority 4: body FK existence
    if body.get("customer_id") is not None:
        get_customer(body["customer_id"])
    # priority 5: shape
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise_err("ERR_INVALID_REQUEST", "Field customer_id is required")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if parse_date(period_start) > parse_date(period_end):
        raise_err("ERR_INVALID_REQUEST", "period_start must be on or before period_end")
    lines, draft_schedule_id = _compose_lines(customer_id, period_start, period_end)
    # priority 12: billable content
    if not lines:
        raise_err("ERR_NO_BILLABLE_ACTIVITY", "Invoice composition produced zero lines")
    total = sum(line["amount_cents"] for line in lines)
    rec = stamp_new(
        {
            "customer_id": customer_id,
            "period_start": period_start,
            "period_end": period_end,
            "lines": lines,
            "total_cents": total,
            "amount_due_cents": total,
            "schedule_id": None,
            "pinned_schedule_version": None,
            "issued_at": None,
            "status": "DRAFT",
            "_draft_schedule_id": draft_schedule_id,
        }
    )
    store.invoices[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/invoices")
def list_invoices():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = list(store.invoices.values())
    if ctx["role"] == "Grower":
        records = [i for i in records if i["customer_id"] == ctx["user_id"]]
    for field in ("customer_id", "schedule_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/invoices/<iid>")
def get_one_invoice(iid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_invoice(iid)
    check_grower_on_invoice(ctx, rec)
    return success(public(rec))


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_invoice(iid)
    body = get_body()
    # priority 5: shape
    pinned = req_int(body, "pinned_schedule_version")
    # priority 6: state
    if rec["status"] == "VOID":
        raise_err("ERR_ALREADY_TERMINAL", "Invoice is in a terminal state")
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT invoice may be issued")
    # priority 7: tariff pin against the schedule used at draft creation
    schedule_id = rec.get("_draft_schedule_id")
    if schedule_id is not None:
        schedule = store.schedules.get(schedule_id)
        if schedule is not None and schedule["version"] != pinned:
            raise_err("ERR_STALE_SCHEDULE_VERSION", "pinned_schedule_version does not match the schedule's current version")
    rec["schedule_id"] = schedule_id
    rec["pinned_schedule_version"] = pinned
    rec["issued_at"] = logical_now_iso()
    rec["amount_due_cents"] = rec["total_cents"]
    rec["status"] = "ISSUED"
    touch(rec)
    return success(public(rec))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_invoice(iid)
    if rec["status"] == "VOID":
        raise_err("ERR_ALREADY_TERMINAL", "Invoice is in a terminal state")
    if rec["status"] == "ISSUED" and rec["amount_due_cents"] != rec["total_cents"]:
        raise_err("ERR_INVALID_STATE", "ISSUED invoice has unreversed payments applied")
    if rec["status"] not in ("DRAFT", "ISSUED"):
        raise_err("ERR_INVALID_STATE", "Only a DRAFT or fully-unpaid ISSUED invoice may be voided")
    rec["status"] = "VOID"
    touch(rec)
    return success(public(rec))


@bp.post("/invoices/<iid>/payments")
def post_payment(iid):
    ctx = get_ctx()
    require_roles(ctx, {"Grower", "ElevatorManager"})
    rec = get_invoice(iid)
    check_grower_on_invoice(ctx, rec)
    body = get_body()
    # priority 5: shape
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise_err("ERR_INVALID_REQUEST", "amount_cents must be positive")
    expected_version = req_int(body, "expected_invoice_version")
    # priority 6: payments land only on ISSUED invoices
    if rec["status"] == "VOID":
        raise_err("ERR_ALREADY_TERMINAL", "Invoice is in a terminal state")
    if rec["status"] == "DRAFT":
        raise_err("ERR_INVOICE_NOT_ISSUED", "Payment attempted on a DRAFT invoice")
    # priority 7: OCC on the invoice version
    if rec["version"] != expected_version:
        raise_err("ERR_STALE_INVOICE_VERSION", "expected_invoice_version does not match current Invoice.version")
    # priority 12: prepaid draws first; cash may not exceed the remaining due
    customer = store.customers.get(rec["customer_id"])
    prepaid_available = customer["prepaid_balance_cents"] if customer is not None else 0
    prepaid_drawn = min(prepaid_available, rec["amount_due_cents"])
    if amount > rec["amount_due_cents"] - prepaid_drawn:
        raise_err("ERR_PAYMENT_EXCEEDS_DUE", "Cash portion exceeds amount_due after the prepaid draw")
    payment = stamp_new_payment(
        {
            "invoice_id": rec["id"],
            "amount_cents": amount,
            "applied_from_prepaid_cents": prepaid_drawn,
            "applied_from_cash_cents": amount,
            "direction": "APPLICATION",
            "reversal_of_payment_id": None,
        }
    )
    store.payments[payment["id"]] = payment
    rec["amount_due_cents"] -= prepaid_drawn + amount
    if customer is not None and prepaid_drawn > 0:
        customer["prepaid_balance_cents"] -= prepaid_drawn
        touch(customer)
    if rec["amount_due_cents"] == 0:
        rec["status"] = "PAID"
    touch(rec)
    return success(public(payment), code=201)


@bp.get("/invoices/<iid>/payments")
def list_invoice_payments(iid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_invoice(iid)
    check_grower_on_invoice(ctx, rec)
    records = [p for p in store.payments.values() if p["invoice_id"] == rec["id"]]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/payments")
def list_payments():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = list(store.payments.values())
    if ctx["role"] == "Grower":
        records = [
            p for p in records
            if store.invoices.get(p["invoice_id"]) is not None
            and store.invoices[p["invoice_id"]]["customer_id"] == ctx["user_id"]
        ]
    for field in ("invoice_id", "reversal_of_payment_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/payments/<pid>")
def get_one_payment(pid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_payment(pid)
    check_grower_on_payment(ctx, rec)
    return success(public(rec))


@bp.post("/payments/<pid>/reverse")
def reverse_payment(pid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_payment(pid)
    # priority 10: only a not-yet-reversed APPLICATION may be reversed
    if rec["direction"] != "APPLICATION" or rec["id"] in store.reversed_payment_ids:
        raise_err("ERR_PAYMENT_NOT_REVERSIBLE", "Reverse attempted on a REVERSAL record or an already-reversed APPLICATION")
    invoice = store.invoices.get(rec["invoice_id"])
    reversal = stamp_new_payment(
        {
            "invoice_id": rec["invoice_id"],
            "amount_cents": rec["amount_cents"],
            "applied_from_prepaid_cents": rec["applied_from_prepaid_cents"],
            "applied_from_cash_cents": rec["applied_from_cash_cents"],
            "direction": "REVERSAL",
            "reversal_of_payment_id": rec["id"],
        }
    )
    store.payments[reversal["id"]] = reversal
    store.reversed_payment_ids.add(rec["id"])
    if invoice is not None:
        invoice["amount_due_cents"] += rec["applied_from_prepaid_cents"] + rec["applied_from_cash_cents"]
        if invoice["status"] == "PAID" and invoice["amount_due_cents"] > 0:
            invoice["status"] = "ISSUED"
        touch(invoice)
    customer = store.customers.get(invoice["customer_id"]) if invoice is not None else None
    if customer is not None and rec["applied_from_prepaid_cents"] > 0:
        customer["prepaid_balance_cents"] += rec["applied_from_prepaid_cents"]
        touch(customer)
    return success(public(reversal), code=201)
