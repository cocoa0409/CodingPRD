"""Invoice and InvoiceLine routes (PRD §3.9 billing & settlement)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core

bp = Blueprint("invoices", __name__)


def _referenced_hires(invoice):
    """All distinct hires referenced by HIRE lines of this invoice."""
    hires = []
    seen = set()
    for line in db.invoice_lines.values():
        if line["invoice_id"] != invoice["id"]:
            continue
        if line["kind"] == "HIRE" and line["source_hire_id"]:
            hid = line["source_hire_id"]
            if hid not in seen:
                seen.add(hid)
                h = db.hires.get(hid)
                if h is not None:
                    hires.append(h)
    return hires


# ---------------------------------------------------------------------------
# Invoice (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.route("/invoices", methods=["POST"])
def create_invoice():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10).
    core.resolve_body_fk(body, "account_id", db.accounts)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["account_id"])
    account_id = core.require_str(body, "account_id")

    invoice = core.stamp_new({
        "account_id": account_id,
        "subtotal_cents": 0,
        "credit_cents": 0,
        "total_cents": 0,
        "paid_cents": 0,
        "status": "DRAFT",
    })
    db.invoices[invoice["id"]] = invoice
    return object_response(core.public(invoice), 201)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    invoice = core.require(db.invoices, invoice_id)
    return object_response(core.public(invoice), 200)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.invoices.values())
    for field in ("account_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [i for i in items if i[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# InvoiceLine (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.route("/invoices/<invoice_id>/lines", methods=["POST"])
def add_invoice_line(invoice_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    # Path id checked first (PRD §2.7).
    invoice = core.require(db.invoices, invoice_id)
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10) for any supplied source pointer.
    core.resolve_body_fk(body, "source_hire_id", db.hires)
    core.resolve_body_fk(body, "source_audit_id", db.audits)
    core.resolve_body_fk(body, "source_voucher_id", db.vouchers)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["kind", "amount_cents"])
    kind = core.require_enum(body, "kind", {"HIRE", "LOSS", "REPAIR", "CREDIT"})
    amount_cents = core.require_int(body, "amount_cents", minimum=0)
    source_hire_id = body.get("source_hire_id")
    source_audit_id = body.get("source_audit_id")
    source_voucher_id = body.get("source_voucher_id")

    # Lines attach while the invoice is in draft (PRD §3.9).
    if invoice["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Lines may only be added to a DRAFT invoice")

    line = core.stamp_new({
        "invoice_id": invoice_id,
        "kind": kind,
        "source_hire_id": source_hire_id,
        "source_audit_id": source_audit_id,
        "source_voucher_id": source_voucher_id,
        "amount_cents": amount_cents,
    })
    db.invoice_lines[line["id"]] = line
    return object_response(core.public(line), 201)


@bp.route("/invoices/<invoice_id>/lines", methods=["GET"])
def list_invoice_lines_under_invoice(invoice_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    core.require(db.invoices, invoice_id)
    items = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice_id]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/invoice-lines/<invoice_line_id>", methods=["GET"])
def get_invoice_line(invoice_line_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    line = core.require(db.invoice_lines, invoice_line_id)
    return object_response(core.public(line), 200)


@bp.route("/invoice-lines", methods=["GET"])
def list_invoice_lines():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.invoice_lines.values())
    for field in ("invoice_id", "source_hire_id", "source_audit_id", "source_voucher_id"):
        val = request.args.get(field)
        if val is not None:
            items = [l for l in items if l[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Invoice lifecycle (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.route("/invoices/<invoice_id>/issue", methods=["POST"])
def issue_invoice(invoice_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    invoice = core.require(db.invoices, invoice_id)
    # DRAFT -> ISSUED (PRD §3.9) -> ERR_INVALID_STATE.
    if invoice["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Invoice is not DRAFT")

    lines = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice_id]
    # At least one line (PRD §3.9) -> ERR_INVOICE_EMPTY.
    if len(lines) == 0:
        raise err("ERR_INVOICE_EMPTY", "Invoice has no lines")
    # Every HIRE line's source hire CLOSED (PRD §3.9) -> ERR_HIRE_NOT_CLOSED.
    for line in lines:
        if line["kind"] == "HIRE" and line["source_hire_id"]:
            h = db.hires.get(line["source_hire_id"])
            if h is None or h["lifecycle_status"] != "CLOSED":
                raise err("ERR_HIRE_NOT_CLOSED",
                          "A referenced HIRE line's source hire is not CLOSED")

    # Pin totals: per-line-rounded integers summed (PRD §2.8, §3.9).
    subtotal = sum(l["amount_cents"] for l in lines if l["kind"] in ("HIRE", "LOSS", "REPAIR"))
    credit = sum(l["amount_cents"] for l in lines if l["kind"] == "CREDIT")
    total = max(0, subtotal - credit)
    invoice["subtotal_cents"] = subtotal
    invoice["credit_cents"] = credit
    invoice["total_cents"] = total
    invoice["status"] = "ISSUED"
    core.touch(invoice)

    # Referenced hires UNBILLED -> INVOICED (PRD §3.9).
    for h in _referenced_hires(invoice):
        if h["settlement_status"] == "UNBILLED":
            h["settlement_status"] = "INVOICED"
            core.touch(h)

    # Recompute account outstanding (PRD §3.5/§3.9).
    acc = db.accounts.get(invoice["account_id"])
    if acc is not None:
        core.recompute_account_outstanding(acc)
    return object_response(core.public(invoice), 200)


@bp.route("/invoices/<invoice_id>/record-payment", methods=["POST"])
def record_payment(invoice_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    invoice = core.require(db.invoices, invoice_id)
    body = get_json_body()
    core.require_fields(body, ["amount_cents"])
    amount = core.require_int(body, "amount_cents")
    # amount > 0 (PRD §3.9) -> ERR_INVALID_REQUEST.
    if amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be greater than 0")
    # ISSUED -> PAID (PRD §3.9) -> ERR_INVALID_STATE.
    if invoice["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Invoice is not ISSUED")

    invoice["paid_cents"] += amount
    if invoice["paid_cents"] >= invoice["total_cents"]:
        invoice["status"] = "PAID"
        # Referenced hires INVOICED -> SETTLED (PRD §3.9).
        for h in _referenced_hires(invoice):
            if h["settlement_status"] == "INVOICED":
                h["settlement_status"] = "SETTLED"
                core.touch(h)
    core.touch(invoice)
    acc = db.accounts.get(invoice["account_id"])
    if acc is not None:
        core.recompute_account_outstanding(acc)
    return object_response(core.public(invoice), 200)


@bp.route("/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    invoice = core.require(db.invoices, invoice_id)
    # DRAFT -> VOID (PRD §3.9) -> ERR_INVALID_STATE.
    if invoice["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT invoice can be voided")
    invoice["status"] = "VOID"
    core.touch(invoice)
    return object_response(core.public(invoice), 200)
