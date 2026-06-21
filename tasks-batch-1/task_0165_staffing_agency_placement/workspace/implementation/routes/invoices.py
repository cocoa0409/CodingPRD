"""Invoice and InvoiceLineItem routes (PRD 3.8)."""

from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import (
    get_user_context, require_role, get_json_body, parse_pagination, paginate,
)
from response import object_response, array_response
from services import common, serialize, recompute, ownership

bp = Blueprint("invoices", __name__)

INVOICE_TARGETS = {"ISSUED", "PAID", "VOID"}


@bp.route("/staffing/invoices", methods=["POST"])
def create_invoice():
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()

    client_id = common.require_str(body, "client_id")
    common.get_or_404(db.clients, client_id, errors.ERR_CLIENT_NOT_FOUND)

    rec = common.init_mutable({
        "client_id": client_id,
        "subtotal_cents": 0,
        "volume_discount_cents": 0,
        "processing_fee_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
    })
    db.invoices[rec["id"]] = rec
    return object_response(serialize.invoice(rec), 201)


@bp.route("/staffing/invoices", methods=["GET"])
def list_invoices():
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Client"})
    limit, offset = parse_pagination()

    client_filter = request.args.get("client_id")
    status_filter = request.args.get("status")

    rows = list(db.invoices.values())
    if client_filter is not None:
        rows = [r for r in rows if r["client_id"] == client_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if role == "Client":
        rows = [r for r in rows if r["client_id"] == user_id]

    page, total = paginate(rows, limit, offset)
    return array_response([serialize.invoice(r) for r in page], limit, offset, total)


@bp.route("/staffing/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Client"})
    rec = common.get_or_404(db.invoices, iid, errors.ERR_INVOICE_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, rec["client_id"])
    return object_response(serialize.invoice(rec), 200)


@bp.route("/staffing/invoices/<iid>/line-items", methods=["GET"])
def list_line_items(iid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Client"})
    inv = common.get_or_404(db.invoices, iid, errors.ERR_INVOICE_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, inv["client_id"])
    limit, offset = parse_pagination()

    rows = [li for li in db.invoice_line_items.values() if li["invoice_id"] == inv["id"]]
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.invoice_line_item(r) for r in page], limit, offset, total)


@bp.route("/staffing/invoices/<iid>/line-items", methods=["POST"])
def add_line_item(iid):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    inv = common.get_or_404(db.invoices, iid, errors.ERR_INVOICE_NOT_FOUND)
    body = get_json_body()
    timesheet_id = common.require_str(body, "timesheet_id")
    ts = common.get_or_404(db.timesheets, timesheet_id, errors.ERR_TIMESHEET_NOT_FOUND)

    # State (priority 6): timesheet must be APPROVED.
    if ts["status"] != "APPROVED":
        raise ApiError(errors.ERR_TIMESHEET_NOT_APPROVED, 409, "Timesheet is not APPROVED.")

    # Referential (priority 12): timesheet's placement client == invoice client.
    placement = db.placements.get(ts["placement_id"])
    ts_client = placement.get("client_id") if placement else None
    if ts_client != inv["client_id"]:
        raise ApiError(errors.ERR_TIMESHEET_CLIENT_MISMATCH, 409, "Timesheet client mismatch.")

    rec = common.init_immutable({
        "invoice_id": inv["id"],
        "timesheet_id": timesheet_id,
        # line_total_cents copied from the timesheet's bill_cents at this moment.
        "line_total_cents": ts["bill_cents"],
    })
    db.invoice_line_items[rec["id"]] = rec

    # Recompute invoice totals (PRD 3.8 step order).
    recompute.recompute_invoice_totals(inv)

    return object_response(serialize.invoice_line_item(rec), 201)


@bp.route("/staffing/invoices/<iid>", methods=["PATCH"])
def patch_invoice(iid):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    rec = common.get_or_404(db.invoices, iid, errors.ERR_INVOICE_NOT_FOUND)
    body = get_json_body()
    target = common.require_enum(body, "target_status", INVOICE_TARGETS)

    status = rec["status"]
    client = db.clients.get(rec["client_id"])

    if target == "ISSUED":
        if status != "DRAFT":
            raise ApiError(errors.ERR_INVOICE_BAD_STATE, 409, "Invoice is not DRAFT.")
        lines = [li for li in db.invoice_line_items.values() if li["invoice_id"] == rec["id"]]
        if not lines:
            raise ApiError(errors.ERR_INVOICE_EMPTY, 409, "Invoice has no line items.")
        rec["status"] = "ISSUED"
        common.touch(rec)
        # Side effect: each referenced timesheet APPROVED -> INVOICED, invoice_id set.
        for li in lines:
            ts = db.timesheets.get(li["timesheet_id"])
            if ts is not None and ts["status"] == "APPROVED":
                ts["status"] = "INVOICED"
                ts["invoice_id"] = rec["id"]
                common.touch(ts)
        # Side effect: client.outstanding_balance += total (recompute from ISSUED set).
        if client is not None:
            recompute.recompute_outstanding_balance(rec["client_id"])

    elif target == "PAID":
        if status != "ISSUED":
            raise ApiError(errors.ERR_INVOICE_BAD_STATE, 409, "Invoice is not ISSUED.")
        rec["status"] = "PAID"
        common.touch(rec)
        # Side effect: client.outstanding_balance -= total (recompute from ISSUED set).
        if client is not None:
            recompute.recompute_outstanding_balance(rec["client_id"])

    elif target == "VOID":
        if status != "ISSUED":
            raise ApiError(errors.ERR_INVOICE_BAD_STATE, 409, "Invoice is not ISSUED.")
        rec["status"] = "VOID"
        common.touch(rec)
        # Side effect: each referenced timesheet INVOICED -> APPROVED, invoice_id cleared.
        for li in db.invoice_line_items.values():
            if li["invoice_id"] != rec["id"]:
                continue
            ts = db.timesheets.get(li["timesheet_id"])
            if ts is not None and ts["status"] == "INVOICED":
                ts["status"] = "APPROVED"
                ts["invoice_id"] = None
                common.touch(ts)
        # Side effect: client.outstanding_balance -= total (recompute from ISSUED set).
        if client is not None:
            recompute.recompute_outstanding_balance(rec["client_id"])

    return object_response(serialize.invoice(rec), 200)
