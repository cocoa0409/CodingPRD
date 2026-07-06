from flask import Blueprint, request as flask_request

from db import db
from errors import err
from middleware import authenticate, require_role
from response import ok, ok_list
from helpers import get_body, paginate, sort_by_created, require_fields

bp = Blueprint("invoices", __name__)


def _recompute_outstanding(client):
    total = 0
    for inv in db.invoices.values():
        if inv["client_id"] == client["id"] and inv["status"] == "ISSUED":
            total += inv["total_cents"]
    client["outstanding_balance_cents"] = total


@bp.post("/interpretation/invoices")
def open_invoice():
    _, role = authenticate()
    require_role(role, {"CoordinatorOps"})
    body = get_body()
    require_fields(body, ["client_id"])
    client = db.clients.get(body["client_id"])
    if client is None:
        raise err("ERR_FK_NOT_FOUND", "client_id not found")

    # gather BILLABLE assignments for this client
    swept_assignments = []
    for a in db.assignments.values():
        if a["billing_status"] != "BILLABLE":
            continue
        req = db.requests.get(a["request_id"])
        if not req or req["client_id"] != client["id"]:
            continue
        swept_assignments.append((a, req))

    if not swept_assignments:
        raise err("ERR_NOTHING_TO_INVOICE", "No billable work for this client")

    line_count = 0
    subtotal = 0
    fees = 0
    swept_requests_for_fee = set()
    for a, req in swept_assignments:
        # session subtotal
        sess = None
        for s in db.sessions.values():
            if s["assignment_id"] == a["id"]:
                sess = s
                break
        if sess is not None:
            line_count += 1
            subtotal += sess["billed_amount_cents"]
        # request fees (cancellation / no-show) swept once per request
        if req["id"] not in swept_requests_for_fee and req.get("cancellation_fee_cents", 0) > 0:
            fees += req["cancellation_fee_cents"]
            swept_requests_for_fee.add(req["id"])
        a["billing_status"] = "INVOICED"
        db.touch(a)

    entity = db.base_fields()
    entity.update({
        "client_id": client["id"],
        "status": "DRAFT",
        "line_count": line_count,
        "subtotal_cents": subtotal,
        "fees_cents": fees,
        "total_cents": subtotal + fees,
    })
    db.invoices[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/invoices/<iid>")
def get_invoice(iid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    inv = db.invoices.get(iid)
    if not inv:
        raise err("ERR_RESOURCE_NOT_FOUND", "Invoice not found")
    return ok(inv)


@bp.get("/interpretation/invoices")
def list_invoices():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    rows = list(db.invoices.values())
    cid = flask_request.args.get("client_id")
    status = flask_request.args.get("status")
    if cid is not None:
        rows = [r for r in rows if r["client_id"] == cid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/interpretation/invoices/<iid>/issue")
def issue_invoice(iid):
    _, role = authenticate()
    require_role(role, {"CoordinatorOps"})
    inv = db.invoices.get(iid)
    if not inv:
        raise err("ERR_RESOURCE_NOT_FOUND", "Invoice not found")
    if inv["status"] != "DRAFT":
        raise err("ERR_INVOICE_NOT_DRAFT", "Invoice is not DRAFT")
    client = db.clients.get(inv["client_id"])
    prospective = client["outstanding_balance_cents"] + inv["total_cents"]
    if prospective > client["credit_limit_cents"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED", "Issuing would exceed credit limit")
    inv["status"] = "ISSUED"
    db.touch(inv)
    _recompute_outstanding(client)
    db.touch(client)
    return ok(inv)


@bp.post("/interpretation/invoices/<iid>/settle")
def settle_invoice(iid):
    _, role = authenticate()
    require_role(role, {"CoordinatorOps"})
    inv = db.invoices.get(iid)
    if not inv:
        raise err("ERR_RESOURCE_NOT_FOUND", "Invoice not found")
    if inv["status"] != "ISSUED":
        raise err("ERR_INVOICE_NOT_ISSUED", "Invoice is not ISSUED")
    inv["status"] = "SETTLED"
    db.touch(inv)
    client = db.clients.get(inv["client_id"])
    if client:
        _recompute_outstanding(client)
        db.touch(client)
    return ok(inv)
