"""Invoice and dispute endpoints (PRD 3.3, 3.4)."""

from flask import Blueprint

from db import base_row, db, public, sorted_rows, touch
from middleware import (BUYER_ADMIN, BUYER_TREASURY, PLATFORM_OPS, SUPPLIER,
                        authenticate, get_dispute, get_invoice, scope_dispute,
                        scope_invoice)
from response import ok, ok_list
from services import flows
from services import guards as g
from services import recompute as rc
from validation import (bad, body, filter_arg, opt_str, paginate, pagination,
                        req_enum, req_int, req_str)

bp = Blueprint("invoices", __name__)

READ_ROLES = (BUYER_ADMIN, BUYER_TREASURY, SUPPLIER, PLATFORM_OPS)
CLIENT_REASON_CODES = ("SHORT_SHIPMENT", "PRICE_VARIANCE", "GOODS_REJECTED")
ALL_REASON_CODES = ("BUYER_FILE_SUPPRESSION",) + CLIENT_REASON_CODES


def _visible_invoices(ctx):
    rows = []
    for invoice in db.invoices.values():
        if ctx.role == SUPPLIER and invoice["supplier_id"] != ctx.uid:
            continue
        if ctx.is_buyer:
            program = db.programs.get(invoice["program_id"])
            if program is None or program["buyer_id"] != ctx.uid:
                continue
        rows.append(invoice)
    return sorted_rows(rows)


@bp.get("/invoices")
def list_invoices():
    ctx = authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = _visible_invoices(ctx)
    file_id = filter_arg("file_id")
    program_id = filter_arg("program_id")
    supplier_id = filter_arg("supplier_id")
    status = filter_arg("status")
    if file_id is not None:
        rows = [r for r in rows if r["file_id"] == file_id]
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


@bp.get("/invoices/<invoice_id>")
def read_invoice(invoice_id):
    ctx = authenticate(READ_ROLES)
    invoice = get_invoice(invoice_id)
    scope_invoice(ctx, invoice)
    return ok(public(invoice))


@bp.get("/invoices/<invoice_id>/lines")
def list_invoice_lines(invoice_id):
    ctx = authenticate(READ_ROLES)
    limit, offset = pagination()
    invoice = get_invoice(invoice_id)
    scope_invoice(ctx, invoice)
    rows = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice["id"]]
    rows.sort(key=lambda l: (l["line_no"], l["created_at"], l["_seq"]))
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


@bp.get("/invoices/<invoice_id>/disputes")
def list_invoice_disputes(invoice_id):
    ctx = authenticate(READ_ROLES)
    limit, offset = pagination()
    invoice = get_invoice(invoice_id)
    scope_invoice(ctx, invoice)
    rows = rc.invoice_disputes(invoice["id"])
    status = filter_arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


@bp.post("/invoices/<invoice_id>/disputes")
def raise_dispute(invoice_id):
    ctx = authenticate((BUYER_ADMIN, PLATFORM_OPS))
    b = body()
    reason_code = req_enum(b, "reason_code", CLIENT_REASON_CODES)
    disputed_amount_cents = req_int(b, "disputed_amount_cents", 1)
    resolution_note = opt_str(b, "resolution_note", 1, 2000)
    invoice = get_invoice(invoice_id)
    scope_invoice(ctx, invoice)
    if disputed_amount_cents > invoice["face_amount_cents"]:
        bad(detail="disputed_amount_cents may not exceed the invoice face amount.")
    if invoice["status"] not in ("ELIGIBLE", "OFFERED", "AWARDED"):
        g.invalid_state("The invoice cannot be disputed from its current state.")
    if invoice["dispute_suppressed"]:
        g.invalid_state("The invoice is already suppressed.")

    dispute = base_row()
    dispute.update(
        {
            "invoice_id": invoice["id"],
            "reason_code": reason_code,
            "disputed_amount_cents": disputed_amount_cents,
            "status": "OPEN",
            "resolution_note": resolution_note,
        }
    )
    db.disputes[dispute["id"]] = dispute

    invoice["dispute_suppressed"] = True
    invoice["status"] = "SUPPRESSED"
    touch(invoice)
    flows.suppress_invoice(invoice)
    program = rc.program_of_invoice(invoice)
    if program is not None:
        rc.recompute_program_adoption(program)
    return ok(public(dispute), 201)


@bp.post("/disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    ctx = authenticate((BUYER_ADMIN, PLATFORM_OPS))
    b = body()
    resolution = req_enum(b, "resolution", ("WITHDRAWN", "REJECTED", "UPHELD"))
    resolution_note = opt_str(b, "resolution_note", 1, 2000)
    dispute = get_dispute(dispute_id)
    scope_dispute(ctx, dispute)
    g.require_dispute_not_terminal(dispute)
    if dispute["status"] != "OPEN":
        g.invalid_state("Only an OPEN dispute can be resolved.")

    if resolution == "WITHDRAWN":
        dispute["status"] = "WITHDRAWN"
    elif resolution == "REJECTED":
        dispute["status"] = "RESOLVED_REJECTED"
    else:
        dispute["status"] = "RESOLVED_UPHELD"
    if resolution_note is not None:
        dispute["resolution_note"] = resolution_note
    touch(dispute)

    invoice = db.invoices.get(dispute["invoice_id"])
    if invoice is None:
        return ok(public(dispute))

    if resolution == "UPHELD":
        if invoice["status"] == "SUPPRESSED":
            invoice["status"] = "MATURED"
            touch(invoice)
    else:
        remaining_open = [
            d for d in rc.invoice_disputes(invoice["id"]) if d["status"] == "OPEN"
        ]
        if not remaining_open:
            invoice["dispute_suppressed"] = False
            if invoice["status"] == "SUPPRESSED":
                invoice["status"] = "ELIGIBLE"
            touch(invoice)
    program = rc.program_of_invoice(invoice)
    if program is not None:
        rc.recompute_program_adoption(program)
    return ok(public(dispute))
