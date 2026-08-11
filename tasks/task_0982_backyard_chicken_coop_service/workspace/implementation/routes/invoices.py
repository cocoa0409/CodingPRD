"""Invoice and InvoiceLine endpoints (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

from db import new_id, now, serialize, stamp_new, stamp_new_config, store, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, body, require_owner, require_role
from response import list_response, ok
from services.pricing import DUE_DAYS, TAX_RATE, invoice_total_composition
from util import dec, is_int, midnight, req_dt, req_str, rhu

bp = Blueprint("invoices", __name__)


def get_invoice(iid):
    inv = store.invoices.get(iid)
    if inv is None:
        fail("ERR_INVOICE_NOT_FOUND", f"Invoice {iid} does not exist")
    return inv


def _in_period(d, period_start, period_end):
    """Half-open period membership at date granularity."""
    return period_start.date() <= d < period_end.date()


def _add_line(invoice_id, source_type, source_id, description, amount_cents):
    line = stamp_new_config({
        "id": new_id(),
        "invoice_id": invoice_id,
        "source_type": source_type,
        "source_id": source_id,
        "description": description,
        "amount_cents": amount_cents,
    })
    store.lines[line["id"]] = line
    return line


@bp.route("/coopcare/invoices", methods=["POST"])
def generate_invoice():
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    data = body()
    household_id = data.get("household_id")
    if not isinstance(household_id, str) or not household_id.strip():
        fail("ERR_INVALID_REQUEST", "household_id is required")
    h = store.households.get(household_id)
    if h is None:
        fail("ERR_HOUSEHOLD_NOT_FOUND", f"Household {household_id} does not exist")
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    if period_end <= period_start:
        fail("ERR_INVALID_TIME_RANGE", "period_end must be strictly after period_start")
    # Temporal: no overlapping non-VOID invoice period for this household.
    for inv in store.invoices.values():
        if inv["household_id"] != household_id or inv["status"] == "VOID":
            continue
        if period_start < inv["period_end"] and period_end > inv["period_start"]:
            fail("ERR_INVOICE_PERIOD_OVERLAP", "period overlaps an existing non-VOID invoice of this household")
    # Billing sweep over the household's unbilled sources.
    sweep = []  # (source_type, source_obj, description, amount_cents)
    for v in store.visits.values():
        if (
            v["household_id"] == household_id
            and v["coverage"] == "BILLABLE"
            and v["status"] == "COMPLETED"
            and v["billed_invoice_id"] is None
            and _in_period(v["scheduled_start"].date(), period_start, period_end)
        ):
            sweep.append(("VISIT", v, f"Service visit {v['visit_type']}", v["final_price_cents"]))
    for e in store.engagements.values():
        if (
            e["household_id"] == household_id
            and e["status"] == "COMPLETED"
            and e["billed_invoice_id"] is None
            and _in_period(e["settled_at"].date(), period_start, period_end)
        ):
            sweep.append(("SITTING", e, "Sitting engagement settlement", e["final_price_cents"]))
    for o in store.orders.values():
        if (
            o["household_id"] == household_id
            and o["status"] in ("PLACED", "FULFILLED")
            and o["billed_invoice_id"] is None
            and _in_period(o["placed_at"].date(), period_start, period_end)
        ):
            sweep.append(("ORDER", o, "Supply order", o["total_cents"]))
    for s in store.subscriptions.values():
        if (
            s["household_id"] == household_id
            and s["status"] in ("ACTIVE", "PAUSED")
            and _in_period(s["current_period_start"].date(), period_start, period_end)
        ):
            plan = store.plans[s["plan_id"]]
            sweep.append(("SUBSCRIPTION_FEE", s, f"Subscription fee ({plan['plan_code']})", plan["monthly_fee_cents"]))
            break  # at most one non-CANCELLED subscription per household
    for e in store.engagements.values():
        if (
            e["household_id"] == household_id
            and e["status"] == "CANCELLED"
            and e["cancellation_fee_cents"] > 0
            and e["billed_invoice_id"] is None
            and _in_period(e["cancelled_at"].date(), period_start, period_end)
        ):
            sweep.append(("CANCELLATION_FEE", e, "Sitting cancellation fee", e["cancellation_fee_cents"]))
    if not sweep:
        fail("ERR_INVOICE_EMPTY", "the sweep found no billable sources for this period")
    inv = stamp_new({
        "id": new_id(),
        "household_id": household_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "subtotal_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "credit_applied_cents": 0,
        "amount_due_cents": 0,
        "due_date": None,
        "issued_at": None,
    })
    store.invoices[inv["id"]] = inv
    for source_type, source, description, amount in sweep:
        _add_line(inv["id"], source_type, source["id"], description, amount)
    inv["subtotal_cents"], inv["tax_cents"], inv["total_cents"] = invoice_total_composition(inv)
    inv["amount_due_cents"] = inv["total_cents"]  # credit_applied starts at 0
    touch(inv)
    # Stamp every swept source; SUBSCRIPTION_FEE sources carry no billed_invoice_id field.
    for source_type, source, _desc, _amt in sweep:
        if source_type in ("VISIT", "SITTING", "ORDER", "CANCELLATION_FEE"):
            source["billed_invoice_id"] = inv["id"]
            touch(source)
    return ok(serialize(inv), 201)


@bp.route("/coopcare/invoices", methods=["GET"])
def list_invoices():
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    filters = []
    for key in ("household_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters.append((key, v))
    return list_response(store.invoices.values(), filters)


@bp.route("/coopcare/invoices/<iid>", methods=["GET"])
def read_invoice(iid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_invoice(iid)), 200)


@bp.route("/coopcare/invoices/<iid>/lines", methods=["GET"])
def list_invoice_lines(iid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    inv = get_invoice(iid)
    lines = [l for l in store.lines.values() if l["invoice_id"] == inv["id"]]
    return list_response(lines, [])


@bp.route("/coopcare/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    inv = get_invoice(iid)
    if inv["status"] != "DRAFT":
        fail("ERR_INVOICE_NOT_DRAFT", "issue requires invoice status DRAFT")
    h = store.households[inv["household_id"]]
    credit = min(h["wallet_credit_cents"], inv["total_cents"])
    h["wallet_credit_cents"] -= credit
    touch(h)
    inv["credit_applied_cents"] = credit
    inv["amount_due_cents"] = inv["total_cents"] - credit
    inv["due_date"] = midnight(now() + timedelta(days=DUE_DAYS))
    inv["issued_at"] = now()
    inv["status"] = "ISSUED"
    touch(inv)
    return ok(serialize(inv), 200)


@bp.route("/coopcare/invoices/<iid>/mark-paid", methods=["POST"])
def mark_paid(iid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    inv = get_invoice(iid)
    if inv["status"] != "ISSUED":
        fail("ERR_INVOICE_NOT_ISSUED", "mark-paid requires invoice status ISSUED")
    inv["status"] = "PAID"
    touch(inv)
    return ok(serialize(inv), 200)


@bp.route("/coopcare/invoices/<iid>/dispute", methods=["POST"])
def dispute(iid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    inv = get_invoice(iid)
    require_owner(uid, role, inv["household_id"])
    if inv["status"] != "ISSUED":
        fail("ERR_INVOICE_NOT_ISSUED", "dispute requires invoice status ISSUED")
    inv["status"] = "DISPUTED"
    touch(inv)
    return ok(serialize(inv), 200)


@bp.route("/coopcare/invoices/<iid>/resolve-dispute", methods=["POST"])
def resolve_dispute(iid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    inv = get_invoice(iid)
    data = body()
    adjustment = data.get("adjustment_amount_cents")
    if not is_int(adjustment):
        fail("ERR_INVALID_REQUEST", "adjustment_amount_cents is required and must be an integer")
    reason = req_str(data, "reason")
    if inv["status"] != "DISPUTED":
        fail("ERR_INVOICE_NOT_DISPUTED", "resolve-dispute requires invoice status DISPUTED")
    new_subtotal = inv["subtotal_cents"] + adjustment
    new_tax = rhu(dec(new_subtotal) * TAX_RATE)
    new_total = new_subtotal + new_tax
    if adjustment == 0 or new_total < 0:
        fail("ERR_INVALID_ADJUSTMENT", "adjustment must be nonzero and keep the invoice total non-negative")
    _add_line(inv["id"], "ADJUSTMENT", "ADJUSTMENT", f"Dispute adjustment: {reason}", adjustment)
    inv["subtotal_cents"] = new_subtotal
    inv["tax_cents"] = new_tax
    inv["total_cents"] = new_total
    # credit_applied_cents stays frozen at whatever was applied at issue time.
    inv["amount_due_cents"] = new_total - inv["credit_applied_cents"]
    inv["status"] = "ISSUED"
    touch(inv)
    return ok(serialize(inv), 200)


@bp.route("/coopcare/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    inv = get_invoice(iid)
    if inv["status"] != "ISSUED":
        fail("ERR_INVOICE_NOT_ISSUED", "void requires invoice status ISSUED")
    h = store.households[inv["household_id"]]
    h["wallet_credit_cents"] += inv["credit_applied_cents"]  # exact refund
    touch(h)
    inv["amount_due_cents"] = inv["total_cents"]
    inv["credit_applied_cents"] = 0
    inv["status"] = "VOID"
    touch(inv)
    # Release every swept source so it becomes billable again.
    for line in store.lines.values():
        if line["invoice_id"] != inv["id"]:
            continue
        st, sid = line["source_type"], line["source_id"]
        target = None
        if st == "VISIT":
            target = store.visits.get(sid)
        elif st in ("SITTING", "CANCELLATION_FEE"):
            target = store.engagements.get(sid)
        elif st == "ORDER":
            target = store.orders.get(sid)
        if target is not None and target.get("billed_invoice_id") == inv["id"]:
            target["billed_invoice_id"] = None
            touch(target)
    return ok(serialize(inv), 200)
