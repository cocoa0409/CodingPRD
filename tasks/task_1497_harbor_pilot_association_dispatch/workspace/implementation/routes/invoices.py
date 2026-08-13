"""Invoices: list/detail/finalize (with the incident hold)."""
from flask import Blueprint, request

from db import DB, now, touch
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import invoice_view
from util import pagination_args, paginate

bp = Blueprint("invoices", __name__)


def _get_invoice(iid):
    inv = DB["invoices"].get(iid)
    if inv is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Invoice does not exist")
    return inv


@bp.get("/pilotage/invoices")
def list_invoices():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    items = list(DB["invoices"].values())
    assignment_id = request.args.get("assignment_id")
    status = request.args.get("status")
    if assignment_id is not None:
        items = [i for i in items if i["assignment_id"] == assignment_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([invoice_view(i) for i in page], total, limit, offset)


@bp.get("/pilotage/invoices/<iid>")
def get_invoice(iid):
    auth(ANY_ROLE)
    return ok(invoice_view(_get_invoice(iid)))


@bp.post("/pilotage/invoices/<iid>/finalize")
def finalize_invoice(iid):
    auth(["FinanceOfficer"])
    invoice = _get_invoice(iid)
    if invoice["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Invoice cannot be finalized from {invoice['status']}",
        )
    # Incident hold: any REPORTED or UNDER_REVIEW incident on the same
    # assignment blocks finalization (priority 12).
    for inc in DB["incidents"].values():
        if inc["assignment_id"] == invoice["assignment_id"] and inc["status"] in (
            "REPORTED",
            "UNDER_REVIEW",
        ):
            raise ApiError(
                "ERR_INCIDENT_HOLD_ACTIVE",
                422,
                "An open incident on the assignment blocks finalization",
            )
    invoice["status"] = "FINALIZED"
    invoice["finalized_at"] = now()
    touch(invoice)
    return ok(invoice_view(invoice))
