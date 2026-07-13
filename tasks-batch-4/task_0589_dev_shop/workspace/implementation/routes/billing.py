"""Invoices — PRD §3.8. Every amount is computed server-side."""
from flask import Blueprint, g, request

from core import (auth, clock, created, err, fk, get_body, invalid, must_get, ok, ok_list,
                  pagination, paginate, parse_date, r2, req_enum, req_int, req_number,
                  req_str, scope_client, store, touch, D)
import services as S

bp = Blueprint("billing", __name__)

KINDS = {"MILESTONE", "TIME_AND_MATERIALS", "RETAINER"}


@bp.post("/invoices")
def create_invoice():
    auth("FinanceOfficer")
    b = get_body()
    eng = fk(b, "engagement_id", "engagement")
    if eng is None:
        invalid("engagement_id is required.")
    milestone = fk(b, "milestone_id", "milestone", required=False)
    retainer = fk(b, "retainer_id", "retainer", required=False)
    kind = req_enum(b, "kind", KINDS)
    expected = req_int(b, "expected_engagement_version")
    period_start = parse_date(b["period_start"], "period_start") if b.get("period_start") else None
    period_end = parse_date(b["period_end"], "period_end") if b.get("period_end") else None

    if expected != eng["version"]:
        err("ERR_STALE_ENGAGEMENT_VERSION", "The engagement has moved on since you read it.")

    if milestone is not None and milestone["engagement_id"] != eng["id"]:
        err("ERR_MILESTONE_ENGAGEMENT_MISMATCH",
            "The milestone belongs to a different engagement.")

    if kind == "MILESTONE":
        if eng["billing_model"] != "FIXED" or milestone is None:
            err("ERR_INVOICE_KIND_MISMATCH",
                "A MILESTONE invoice needs a FIXED engagement and a milestone_id.")
    elif kind == "TIME_AND_MATERIALS":
        if (eng["billing_model"] != "TIME_AND_MATERIALS"
                or period_start is None or period_end is None):
            err("ERR_INVOICE_KIND_MISMATCH",
                "A TIME_AND_MATERIALS invoice needs a T&M engagement and a period.")
    else:  # RETAINER
        if (retainer is None or retainer["engagement_id"] != eng["id"]
                or period_start is None or period_end is None):
            err("ERR_INVOICE_KIND_MISMATCH",
                "A RETAINER invoice needs a retainer of this engagement and a period.")

    if milestone is not None and kind == "MILESTONE":
        for inv in store.invoices.values():
            if (inv["milestone_id"] == milestone["id"]
                    and inv["status"] in ("DRAFT", "ISSUED", "PAID")):
                err("ERR_DUPLICATE_MILESTONE_INVOICE",
                    "This milestone already carries a live invoice.")

    inv = S.create_invoice_row(
        eng, kind,
        milestone=milestone if kind == "MILESTONE" else None,
        retainer=retainer if kind == "RETAINER" else None,
        period_start=period_start, period_end=period_end,
    )
    touch(eng)
    return created(S.ser_invoice(inv))


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    auth()
    inv = must_get("invoice", iid)
    scope_client(store.engagements[inv["engagement_id"]]["client_id"])
    return ok(S.ser_invoice(inv))


@bp.get("/invoices")
def list_invoices():
    auth()
    limit, offset = pagination()
    rows = list(store.invoices.values())
    if g.role == "ClientContact":
        rows = [i for i in rows
                if store.engagements[i["engagement_id"]]["client_id"] == g.user_id]
    for key in ("engagement_id", "milestone_id", "retainer_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [i for i in rows if i[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_invoice(i) for i in page], limit, offset, total)


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    auth("FinanceOfficer")
    inv = must_get("invoice", iid)
    eng = store.engagements[inv["engagement_id"]]
    if inv["status"] != "DRAFT":
        err("ERR_INVALID_TRANSITION", "Only a DRAFT invoice may be issued.")
    milestone = store.milestones.get(inv["milestone_id"]) if inv["milestone_id"] else None
    if inv["kind"] == "MILESTONE" and (milestone is None or milestone["status"] != "COMPLETED"):
        err("ERR_MILESTONE_NOT_COMPLETED", "The milestone has not reached COMPLETED.")
    if not inv["lines"]:
        err("ERR_INVOICE_NO_LINES", "An invoice with no lines cannot be issued.")

    inv["status"] = "ISSUED"
    inv["issued_at"] = clock.now
    touch(inv)
    if inv["kind"] == "MILESTONE" and milestone is not None:
        milestone["status"] = "BILLED"
        touch(milestone)
    S.recompute_money_ledger(eng)
    touch(eng)
    return ok(S.ser_invoice(inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    auth("FinanceOfficer")
    inv = must_get("invoice", iid)
    b = get_body()
    paid_amount = req_number(b, "paid_amount")
    if inv["status"] != "ISSUED":
        err("ERR_INVALID_TRANSITION", "Only an ISSUED invoice may be paid.")
    if D(paid_amount) != inv["total"]:
        err("ERR_PAYMENT_AMOUNT_MISMATCH", "paid_amount must equal the invoice total exactly.")
    inv["status"] = "PAID"
    inv["paid_at"] = clock.now
    touch(inv)
    return ok(S.ser_invoice(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    auth("FinanceOfficer")
    inv = must_get("invoice", iid)
    b = get_body()
    req_str(b, "reason")
    if inv["status"] not in ("DRAFT", "ISSUED"):
        err("ERR_INVALID_TRANSITION", "Only a DRAFT or ISSUED invoice may be voided.")
    was_issued = inv["status"] == "ISSUED"
    eng = store.engagements[inv["engagement_id"]]
    inv["status"] = "VOID"
    touch(inv)
    if was_issued:
        if inv["kind"] == "MILESTONE" and inv["milestone_id"]:
            milestone = store.milestones.get(inv["milestone_id"])
            if milestone is not None and milestone["status"] == "BILLED":
                milestone["status"] = "COMPLETED"
                touch(milestone)
        S.recompute_money_ledger(eng)
        touch(eng)
    return ok(S.ser_invoice(inv))
