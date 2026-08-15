"""Invoice intake, tiered approval, rejection, resubmission, cancellation."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_VENDOR_BLOCKED,
    ERR_VENDOR_NOT_ACTIVE,
    ERR_NO_APPROVAL_RULE,
    ERR_DUPLICATE_INVOICE_NUMBER,
    ERR_SOD_INVOICE_SUBMITTER_CANNOT_APPROVE,
    ERR_SOD_SAME_APPROVER_TWO_TIERS,
    ERR_APPROVAL_TIER_OUT_OF_ORDER,
    raise_err,
)
from middleware import (
    require_auth,
    require_role,
    require_tier_role,
    get_body,
    req_str,
    req_int,
    opt_str,
    opt_int,
    get_or_404,
    paginate,
    parse_iso_date,
)
from response import ok, ok_list

bp = Blueprint("invoices", __name__)

INTAKE_ROLES = ["APClerk", "APSupervisor", "APManager"]
APPROVER_ROLES = ["APSupervisor", "APManager", "Controller"]
INVOICE_EDITABLE_STATUSES = ("RECEIVED", "REJECTED")


def _invoice_number_taken(vendor_id, invoice_number, exclude_id=None):
    for inv in db.invoices.values():
        if inv["vendor_id"] != vendor_id:
            continue
        if inv["status"] == "CANCELLED":
            continue
        if exclude_id is not None and inv["id"] == exclude_id:
            continue
        if inv["invoice_number"] == invoice_number:
            return True
    return False


def _parse_tier(body):
    tier = body.get("tier")
    if tier is None or not isinstance(tier, int) or isinstance(tier, bool) or tier not in (1, 2, 3):
        raise_err(ERR_INVALID_REQUEST, "Field 'tier' is required and must be one of 1, 2, 3.")
    return tier


def _approvals_this_round(invoice):
    return [a for a in db.invoice_approvals.values()
            if a["invoice_id"] == invoice["id"] and a["round_no"] == invoice["approval_round"]]


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    ctx = require_auth()
    require_role(ctx, INTAKE_ROLES)
    body = get_body()
    vendor_id = req_str(body, "vendor_id")
    invoice_number = req_str(body, "invoice_number")
    amount_cents = req_int(body, "amount_cents")
    if amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be strictly positive.")
    cost_center = req_str(body, "cost_center")
    received_date = opt_str(body, "received_date")
    if received_date is None:
        received_date = db.today().isoformat()
    else:
        parse_iso_date(received_date, "received_date")

    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] == "BLOCKED":
        raise_err(ERR_VENDOR_BLOCKED, "Vendor is BLOCKED.")
    if vendor["status"] != "ACTIVE":
        raise_err(ERR_VENDOR_NOT_ACTIVE,
                  "Vendor in status %s cannot receive invoices." % vendor["status"])
    if _invoice_number_taken(vendor_id, invoice_number):
        raise_err(ERR_DUPLICATE_INVOICE_NUMBER,
                  "invoice_number '%s' already exists for this vendor." % invoice_number)

    invoice = db.stamp_new({
        "id": db.new_id(),
        "vendor_id": vendor_id,
        "invoice_number": invoice_number,
        "amount_cents": amount_cents,
        "cost_center": cost_center,
        "received_date": received_date,
        "status": "RECEIVED",
        "pre_hold_status": None,
        "required_tier": None,
        "approval_round": 0,
        "submitted_by_user_id": None,
        "provisional_discount_cents": None,
    })
    db.invoices[invoice["id"]] = invoice
    return ok(invoice, status=201)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    require_auth()
    items = list(db.invoices.values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [i for i in items if i["vendor_id"] == vendor_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    cost_center = request.args.get("cost_center")
    if cost_center is not None:
        items = [i for i in items if i["cost_center"] == cost_center]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    require_auth()
    return ok(get_or_404(db.invoices, invoice_id, "Invoice"))


@bp.route("/invoices/<invoice_id>", methods=["PATCH"])
def patch_invoice(invoice_id):
    ctx = require_auth()
    require_role(ctx, INTAKE_ROLES)
    body = get_body()
    updates = {}
    if "amount_cents" in body:
        amount = body["amount_cents"]
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer.")
        if amount <= 0:
            raise_err(ERR_INVALID_REQUEST, "amount_cents must be strictly positive.")
        updates["amount_cents"] = amount
    if "cost_center" in body:
        updates["cost_center"] = req_str(body, "cost_center")
    if "invoice_number" in body:
        updates["invoice_number"] = req_str(body, "invoice_number")
    invoice = get_or_404(db.invoices, invoice_id, "Invoice")
    if invoice["status"] not in INVOICE_EDITABLE_STATUSES:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Invoice in status %s cannot be edited." % invoice["status"])
    if "invoice_number" in updates and _invoice_number_taken(
        invoice["vendor_id"], updates["invoice_number"], exclude_id=invoice["id"]
    ):
        raise_err(ERR_DUPLICATE_INVOICE_NUMBER,
                  "invoice_number '%s' already exists for this vendor." % updates["invoice_number"])
    for field, value in updates.items():
        invoice[field] = value
    db.touch(invoice)
    return ok(invoice)


def _submit_invoice(ctx, invoice, from_status):
    if invoice["status"] != from_status:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Invoice in status %s cannot transition from %s." % (invoice["status"], from_status))
    vendor = db.vendors.get(invoice["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE":
        raise_err(ERR_VENDOR_NOT_ACTIVE, "Vendor must be ACTIVE.")
    required_tier = svc.route_invoice_tier(vendor, invoice)
    if required_tier is None:
        raise_err(ERR_NO_APPROVAL_RULE,
                  "No ACTIVE approval matrix rule covers this invoice's amount and cost center.")
    invoice["approval_round"] += 1
    invoice["submitted_by_user_id"] = ctx.user_id
    invoice["required_tier"] = required_tier
    invoice["status"] = "PENDING_APPROVAL"
    db.touch(invoice)


@bp.route("/invoices/<invoice_id>/submit", methods=["POST"])
def submit_invoice(invoice_id):
    ctx = require_auth()
    require_role(ctx, INTAKE_ROLES)
    invoice = get_or_404(db.invoices, invoice_id, "Invoice")
    _submit_invoice(ctx, invoice, "RECEIVED")
    return ok(invoice)


@bp.route("/invoices/<invoice_id>/resubmit", methods=["POST"])
def resubmit_invoice(invoice_id):
    ctx = require_auth()
    require_role(ctx, INTAKE_ROLES)
    invoice = get_or_404(db.invoices, invoice_id, "Invoice")
    _submit_invoice(ctx, invoice, "REJECTED")
    return ok(invoice)


def _tier_gate(ctx, body, invoice, enforce_sod):
    """Shared approve/reject guard chain; returns the presented tier."""
    # role-for-tier check runs in the auth phase (priority 2), before body/shape
    # validation; tier is read leniently here for that purpose.
    raw = request.get_json(silent=True)
    hinted = raw.get("tier") if isinstance(raw, dict) else None
    if isinstance(hinted, int) and not isinstance(hinted, bool) and hinted in (1, 2, 3):
        require_tier_role(ctx, hinted)
    tier = _parse_tier(body)
    require_tier_role(ctx, tier)
    if invoice["status"] != "PENDING_APPROVAL":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Invoice in status %s cannot be approved or rejected." % invoice["status"])
    approved_count = len(_approvals_this_round(invoice))
    if tier <= approved_count:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Tier %s has already been approved in the current round." % tier)
    if enforce_sod:
        if ctx.user_id == invoice["submitted_by_user_id"]:
            raise_err(ERR_SOD_INVOICE_SUBMITTER_CANNOT_APPROVE,
                      "The current round's submitter may not approve it (SoD-2).")
        for a in _approvals_this_round(invoice):
            if a["approver_user_id"] == ctx.user_id:
                raise_err(ERR_SOD_SAME_APPROVER_TWO_TIERS,
                          "One operator may approve at most one tier per round (SoD-5).")
    if tier != approved_count + 1:
        raise_err(ERR_APPROVAL_TIER_OUT_OF_ORDER,
                  "Tier %s skips ahead of the next pending tier %s." % (tier, approved_count + 1))
    return tier


@bp.route("/invoices/<invoice_id>/approve", methods=["POST"])
def approve_invoice(invoice_id):
    ctx = require_auth()
    require_role(ctx, APPROVER_ROLES)
    body = get_body()
    invoice = get_or_404(db.invoices, invoice_id, "Invoice")
    tier = _tier_gate(ctx, body, invoice, enforce_sod=True)

    approval = db.stamp_new({
        "id": db.new_id(),
        "invoice_id": invoice["id"],
        "round_no": invoice["approval_round"],
        "tier": tier,
        "approver_user_id": ctx.user_id,
        "approver_role": ctx.role,
    })
    db.invoice_approvals[approval["id"]] = approval
    if tier == invoice["required_tier"]:
        # final tier: APPROVED + provisional discount snapshot (logical date at approval)
        vendor = db.vendors.get(invoice["vendor_id"])
        invoice["provisional_discount_cents"] = svc.compute_discount_cents(
            invoice, vendor, db.today()) if vendor is not None else 0
        invoice["status"] = "APPROVED"
    db.touch(invoice)
    return ok(invoice)


@bp.route("/invoices/<invoice_id>/reject", methods=["POST"])
def reject_invoice(invoice_id):
    ctx = require_auth()
    require_role(ctx, APPROVER_ROLES)
    body = get_body()
    req_str(body, "reason")
    invoice = get_or_404(db.invoices, invoice_id, "Invoice")
    _tier_gate(ctx, body, invoice, enforce_sod=False)
    invoice["status"] = "REJECTED"
    db.touch(invoice)
    svc.audit_status_change("Invoice", invoice["id"], "PENDING_APPROVAL", "REJECTED", ctx)
    return ok(invoice)


@bp.route("/invoices/<invoice_id>/cancel", methods=["POST"])
def cancel_invoice(invoice_id):
    ctx = require_auth()
    require_role(ctx, ["APClerk"])
    if request.data:
        get_body()  # optional body with optional reason; must parse as an object if present
    invoice = get_or_404(db.invoices, invoice_id, "Invoice")
    if invoice["status"] not in ("RECEIVED", "PENDING_APPROVAL", "REJECTED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Invoice in status %s cannot be cancelled." % invoice["status"])
    invoice["status"] = "CANCELLED"
    db.touch(invoice)
    return ok(invoice)


@bp.route("/invoices/<invoice_id>/approvals", methods=["GET"])
def list_invoice_approvals(invoice_id):
    require_auth()
    get_or_404(db.invoices, invoice_id, "Invoice")
    items = [a for a in db.invoice_approvals.values() if a["invoice_id"] == invoice_id]
    round_no = request.args.get("round_no")
    if round_no is not None:
        try:
            round_no = int(round_no)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'round_no' must be an integer.")
        items = [a for a in items if a["round_no"] == round_no]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)
