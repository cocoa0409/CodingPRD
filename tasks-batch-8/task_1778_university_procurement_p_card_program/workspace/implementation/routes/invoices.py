"""Invoice exception resolution and payment (PRD 3.6)."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
)
from errors import (
    ApiError,
    ERR_INVOICE_NOT_RESOLVABLE,
    ERR_INVOICE_NOT_PAYABLE,
    ERR_SELF_RESOLUTION_FORBIDDEN,
)

bp = make_blueprint("invoices")


@bp.get("/invoices")
def list_invoices():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("invoices"), ["vendor_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(i) for i in page], limit, offset, total, has_more)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    authenticate(ROLES)
    invoice = require_fk("invoices", iid)
    return success_obj(db.public(invoice), 200)


@bp.post("/invoices/<iid>/resolve-exception")
def resolve_exception(iid):
    """ACCEPT_VARIANCE re-runs the full three-way match against current POSTED
    receipts and pinned PO prices; REJECT_INVOICE terminates the invoice and
    reopens the PO for a replacement. The resolver may not be the requester of
    the funding requisition."""
    user_id, _ = authenticate(["APClerk"])
    invoice = require_fk("invoices", iid)
    if invoice["status"] != "EXCEPTION":
        raise ApiError(ERR_INVOICE_NOT_RESOLVABLE, 409, "resolve-exception requires EXCEPTION")
    body = body_json()
    check_shape(body, {
        "action": {"type": "enum", "values": ["ACCEPT_VARIANCE", "REJECT_INVOICE"], "required": True},
        "comment": {"type": "string"},
    })
    po = db.get("purchase_orders", invoice["po_id"])
    req = db.get("requisitions", po["requisition_id"]) if po else None
    if req is not None and user_id == req["requester_id"]:
        raise ApiError(ERR_SELF_RESOLUTION_FORBIDDEN, 403, "the resolver may not be the purchase's requester")
    if body["action"] == "ACCEPT_VARIANCE":
        match = svc.run_three_way_match(po, invoice["lines"])
        # Derived fields reflect the re-match either way.
        invoice["total_variance_cents"] = match["total_variance_cents"]
        invoice["total_tolerance_cents"] = match["total_tolerance_cents"]
        invoice["exception_reason"] = match["exception_reason"]
        if match["status"] == "PAYABLE":
            invoice["status"] = "PAYABLE"
            invoice["variance_accepted_by"] = user_id
        # A failed re-match keeps the invoice in EXCEPTION with refreshed reason.
    else:  # REJECT_INVOICE
        invoice["status"] = "REJECTED"
    db.touch(invoice)
    return success_obj(db.public(invoice), 200)


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    """Terminal settlement. On grant POs the charge leaves the computed
    encumbrance and enters spent automatically via the derived ledger."""
    authenticate(["APClerk"])
    invoice = require_fk("invoices", iid)
    if invoice["status"] != "PAYABLE":
        raise ApiError(ERR_INVOICE_NOT_PAYABLE, 409, "pay requires a PAYABLE invoice")
    invoice["status"] = "PAID"
    invoice["paid_at"] = db.logical_ts()
    db.touch(invoice)
    return success_obj(db.public(invoice), 200)
