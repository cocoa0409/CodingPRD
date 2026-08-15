"""Invoice endpoints: per-project listing, fetch, issue, mark_paid."""
from flask import Blueprint, request

import errors
from db import DB, clock_now
from middleware import auth
from response import ok, ok_list
from services import invoice_json, lazy_read_tick, paginate, sorted_rows, touch

bp = Blueprint("invoices", __name__)

READ_ROLES = ["CastingDirector", "Client", "Agent", "Talent"]


def _get_invoice(iid):
    inv = DB["invoices"].get(iid)
    if inv is None:
        raise errors.not_found("Invoice not found")
    return inv


@bp.get("/projects/<pid>/invoices")
def list_project_invoices(pid):
    auth(READ_ROLES)
    lazy_read_tick()
    if DB["projects"].get(pid) is None:
        raise errors.not_found("Project not found")
    rows = [i for i in sorted_rows("invoices") if i["project_id"] == pid]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([invoice_json(i) for i in page], total, limit, offset)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    auth(READ_ROLES)
    lazy_read_tick()
    return ok(invoice_json(_get_invoice(iid)))


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    auth(["Agent"])
    inv = _get_invoice(iid)
    if inv["status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING invoice can be issued")
    inv["status"] = "ISSUED"
    inv["issued_at"] = clock_now()
    touch(inv)
    return ok(invoice_json(inv))


@bp.post("/invoices/<iid>/mark_paid")
def mark_paid(iid):
    auth(["Agent"])
    inv = _get_invoice(iid)
    if inv["status"] != "ISSUED":
        raise errors.invalid_state("Only an ISSUED invoice can be marked paid")
    inv["status"] = "PAID"
    touch(inv)
    return ok(invoice_json(inv))
