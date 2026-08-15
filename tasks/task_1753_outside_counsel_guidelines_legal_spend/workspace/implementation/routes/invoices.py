"""Invoice, InvoiceLineItem, and Appeal endpoints."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER
from services import invoice_service as svc

bp = Blueprint("invoices", __name__)

VALID_REJECTION_REASONS = {
    "BLOCK_BILLING", "RATE_EXCEEDS_APPROVED", "UNAPPROVED_TIMEKEEPER",
    "STAFFING_RATIO", "OVER_BUDGET",
}


# ---------------------------------------------------------------------------
# Invoice create (with auto-review rule engine) / read / pay / void
# ---------------------------------------------------------------------------

@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices", methods=["POST"])
def create_invoice(deptId, matterId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    dept, matter = helpers.resolve_matter(deptId, matterId)
    body = helpers.get_body()
    helpers.require_fields(body, ["invoice_number", "billing_period_start", "billing_period_end"])

    firm_id = matter.get("panel_firm_id")
    firm = db.panel_firms.get(firm_id)

    # Priority 4 (state): matter must be ENGAGED.
    if matter.get("engagement_status") != "ENGAGED":
        raise errors.invalid_state()
    # Firm must be ACTIVE.
    if firm is None or firm.get("status") != "ACTIVE":
        raise errors.firm_not_active()
    # Acting firm must match the matter's engaged firm.
    if user_id != firm_id:
        raise errors.firm_mismatch()
    # Referential integrity: every line's timekeeper must belong to the firm.
    line_items_in = body.get("line_items") or []
    if not isinstance(line_items_in, list):
        raise errors.referential_integrity("line_items must be an array")
    for li in line_items_in:
        if not isinstance(li, dict):
            raise errors.referential_integrity("each line item must be an object")
        tk = db.timekeepers.get(li.get("timekeeper_id"))
        if tk is None or tk.get("panel_firm_id") != firm_id:
            raise errors.referential_integrity("line item timekeeper does not belong to the engaged firm")
    # Uniqueness: invoice_number unique per firm.
    for inv in db.invoices.values():
        if inv.get("panel_firm_id") == firm_id and inv.get("invoice_number") == body["invoice_number"]:
            raise errors.duplicate_invoice_number()
    # Temporal: billing_period_end > billing_period_start.
    bp_start = db.parse_iso(body.get("billing_period_start"))
    bp_end = db.parse_iso(body.get("billing_period_end"))
    if bp_start is None or bp_end is None or bp_end <= bp_start:
        raise errors.invalid_temporal()
    # Priority 9 fiscal/OCC: expected_matter_version vs current matter version.
    expected = body.get("expected_matter_version")
    if expected is not None:
        try:
            expected_i = int(expected)
        except (TypeError, ValueError):
            raise errors.stale_version()
        if expected_i != int(matter.get("version", 1)):
            raise errors.stale_version()

    # Create the invoice (SUBMITTED) and persist line items.
    inv = db.base_resource({
        "matter_id": matterId,
        "panel_firm_id": firm_id,
        "invoice_number": body["invoice_number"],
        "billing_period_start": body["billing_period_start"],
        "billing_period_end": body["billing_period_end"],
        "status": "SUBMITTED",
        "submitted_total_cents": 0,
        "approved_total_cents": 0,
        "final_payable_cents": 0,
    })
    db.invoices[inv["id"]] = inv

    year = bp_start.year
    lines = []
    submitted_total = 0
    for li in line_items_in:
        amount = svc.compute_line_amount_cents(li.get("hours", 0), li.get("rate_cents", 0))
        line = db.base_resource({
            "invoice_id": inv["id"],
            "timekeeper_id": li.get("timekeeper_id"),
            "utbms_task_code": li.get("utbms_task_code"),
            "narrative": li.get("narrative"),
            "hours": li.get("hours"),
            "rate_cents": int(li.get("rate_cents", 0)),
            "amount_cents": amount,
            "review_status": "PENDING",
            "adjusted_amount_cents": None,
            "rejection_reason_code": None,
        })
        db.invoice_line_items[line["id"]] = line
        lines.append(line)
        submitted_total += amount
    inv["submitted_total_cents"] = submitted_total

    # Auto-transition SUBMITTED -> UNDER_REVIEW, then run the rule engine.
    inv["status"] = "UNDER_REVIEW"
    for line in lines:
        svc.rule_engine_line(line, firm_id, year)

    # Fiscal budget gate (priority 9, line-level): any APPROVED line whose
    # approval would push billed_to_date over budget -> OVER_BUDGET rejection.
    budget = int(matter.get("budget_cents", 0))
    booked_now = int(matter.get("billed_to_date_cents", 0))
    running = booked_now
    for line in lines:
        if line.get("review_status") != "APPROVED":
            continue
        if running + int(line.get("amount_cents", 0)) > budget:
            line["review_status"] = "REJECTED"
            line["rejection_reason_code"] = svc.OVER_BUDGET
        else:
            running += int(line.get("amount_cents", 0))

    # Derive aggregate status and book spend / consume accruals.
    svc.finalize_invoice_state(inv, matter, "UNDER_REVIEW")

    # Invoice creation advances the matter's version (spend-cache side effect).
    db.touch(matter)
    svc.refresh_forecast(matterId)

    return resp.success_object(resp.public(inv), 201)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>", methods=["GET"])
def get_invoice(deptId, matterId, invoiceId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, inv = helpers.resolve_invoice(deptId, matterId, invoiceId)
    return resp.success_object(resp.public(inv))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices", methods=["GET"])
def list_invoices(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_matter(deptId, matterId)
    limit, offset = resp.parse_pagination(request.args)
    records = [i for i in db.invoices.values() if i.get("matter_id") == matterId]
    records = helpers.apply_filters(records, request.args, ["status"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/pay", methods=["POST"])
def pay_invoice(deptId, matterId, invoiceId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter, inv = helpers.resolve_invoice(deptId, matterId, invoiceId)
    if inv.get("status") not in ("APPROVED", "PARTIALLY_APPROVED"):
        raise errors.invalid_state()
    if inv.get("status") == "PARTIALLY_APPROVED":
        # Refused while any appeal on any of this invoice's lines is open.
        line_ids = {l["id"] for l in db.invoice_line_items.values() if l.get("invoice_id") == invoiceId}
        for a in db.appeals.values():
            if a.get("invoice_line_item_id") in line_ids and a.get("status") in ("SUBMITTED", "UNDER_REVIEW"):
                raise errors.open_appeals()
    # Freeze final payable at the then-current approved total.
    inv["status"] = "PAID"
    inv["final_payable_cents"] = int(inv.get("approved_total_cents", 0))
    db.touch(inv)
    return resp.success_object(resp.public(inv))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/void", methods=["POST"])
def void_invoice(deptId, matterId, invoiceId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, matter, inv = helpers.resolve_invoice(deptId, matterId, invoiceId)
    if inv.get("status") != "REJECTED":
        raise errors.invalid_state()
    if user_id != inv.get("panel_firm_id"):
        raise errors.firm_mismatch()
    inv["status"] = "VOID"
    db.touch(inv)
    return resp.success_object(resp.public(inv))


# ---------------------------------------------------------------------------
# InvoiceLineItem reads + manual review actions
# ---------------------------------------------------------------------------

@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>", methods=["GET"])
def get_line_item(deptId, matterId, invoiceId, lineId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, _, line = helpers.resolve_line_item(deptId, matterId, invoiceId, lineId)
    return resp.success_object(resp.public(line))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items", methods=["GET"])
def list_line_items(deptId, matterId, invoiceId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_invoice(deptId, matterId, invoiceId)
    limit, offset = resp.parse_pagination(request.args)
    records = [l for l in db.invoice_line_items.values() if l.get("invoice_id") == invoiceId]
    records = helpers.apply_filters(records, request.args, ["review_status"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


def _after_line_action(inv, matter, old_inv_status, line, old_line_status):
    """Recompute totals, re-derive status, handle compensating debit on
    post-approval rejection, refresh forecast, and touch the invoice."""
    new_line_status = line.get("review_status")
    if (
        old_inv_status in ("APPROVED", "PARTIALLY_APPROVED")
        and old_line_status in ("APPROVED", "ADJUSTED_APPROVED")
        and new_line_status == "REJECTED"
    ):
        # Compensating debit: matter billed_to_date decreases by the line's
        # prior contribution.
        prior = (
            int(line.get("adjusted_amount_cents") or 0)
            if old_line_status == "ADJUSTED_APPROVED"
            else int(line.get("amount_cents", 0))
        )
        matter["billed_to_date_cents"] = int(matter.get("billed_to_date_cents", 0)) - prior
    svc.finalize_invoice_state(inv, matter, old_inv_status)
    svc.refresh_forecast(matter["id"])
    db.touch(line)
    db.touch(inv)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/approve", methods=["POST"])
def approve_line(deptId, matterId, invoiceId, lineId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter, inv, line = helpers.resolve_line_item(deptId, matterId, invoiceId, lineId)
    if line.get("review_status") != "PENDING":
        raise errors.invalid_state()
    old_inv_status = inv.get("status")
    old_line_status = line.get("review_status")
    line["review_status"] = "APPROVED"
    line["rejection_reason_code"] = None
    _after_line_action(inv, matter, old_inv_status, line, old_line_status)
    return resp.success_object(resp.public(line))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/adjust", methods=["POST"])
def adjust_line(deptId, matterId, invoiceId, lineId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter, inv, line = helpers.resolve_line_item(deptId, matterId, invoiceId, lineId)
    if line.get("review_status") != "PENDING":
        raise errors.invalid_state()
    body = helpers.get_body()
    helpers.require_fields(body, ["adjusted_amount_cents"])
    try:
        adjusted = int(body["adjusted_amount_cents"])
    except (TypeError, ValueError):
        raise errors.invalid_adjustment()
    if adjusted < 0 or adjusted >= int(line.get("amount_cents", 0)):
        raise errors.invalid_adjustment()
    old_inv_status = inv.get("status")
    old_line_status = line.get("review_status")
    line["review_status"] = "ADJUSTED_APPROVED"
    line["adjusted_amount_cents"] = adjusted
    line["rejection_reason_code"] = None
    _after_line_action(inv, matter, old_inv_status, line, old_line_status)
    return resp.success_object(resp.public(line))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/reject", methods=["POST"])
def reject_line(deptId, matterId, invoiceId, lineId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter, inv, line = helpers.resolve_line_item(deptId, matterId, invoiceId, lineId)
    body = helpers.get_body()
    reason = body.get("rejection_reason_code")
    if reason is not None and reason not in VALID_REJECTION_REASONS:
        raise errors.ApiError(errors.ERR_REFERENTIAL_INTEGRITY, "invalid rejection_reason_code", 422)
    current = line.get("review_status")
    inv_status = inv.get("status")
    if current == "PENDING":
        pass
    elif current in ("APPROVED", "ADJUSTED_APPROVED") and inv_status in ("APPROVED", "PARTIALLY_APPROVED"):
        # Post-approval correction path.
        pass
    else:
        raise errors.invalid_state()
    old_inv_status = inv_status
    old_line_status = current
    line["review_status"] = "REJECTED"
    line["rejection_reason_code"] = reason
    _after_line_action(inv, matter, old_inv_status, line, old_line_status)
    return resp.success_object(resp.public(line))


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/appeals", methods=["POST"])
def create_appeal(deptId, matterId, invoiceId, lineId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, matter, inv, line = helpers.resolve_line_item(deptId, matterId, invoiceId, lineId)
    if line.get("review_status") != "REJECTED":
        raise errors.invalid_state()
    if user_id != inv.get("panel_firm_id"):
        raise errors.firm_mismatch()
    body = helpers.get_body()
    helpers.require_fields(body, ["rationale"])
    rec = db.base_resource({
        "invoice_line_item_id": lineId,
        "rationale": body["rationale"],
        "status": "SUBMITTED",
        "resolution_note": None,
    })
    db.appeals[rec["id"]] = rec
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/appeals/<appealId>", methods=["GET"])
def get_appeal(deptId, matterId, invoiceId, lineId, appealId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, _, _, appeal = helpers.resolve_appeal(deptId, matterId, invoiceId, lineId, appealId)
    return resp.success_object(resp.public(appeal))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/appeals", methods=["GET"])
def list_appeals(deptId, matterId, invoiceId, lineId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_line_item(deptId, matterId, invoiceId, lineId)
    limit, offset = resp.parse_pagination(request.args)
    records = [a for a in db.appeals.values() if a.get("invoice_line_item_id") == lineId]
    records = helpers.apply_filters(records, request.args, ["status"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/appeals/<appealId>/claim", methods=["POST"])
def claim_appeal(deptId, matterId, invoiceId, lineId, appealId):
    require_auth([ROLE_LEGAL_OPS])
    _, _, _, _, appeal = helpers.resolve_appeal(deptId, matterId, invoiceId, lineId, appealId)
    if appeal.get("status") != "SUBMITTED":
        raise errors.invalid_state()
    appeal["status"] = "UNDER_REVIEW"
    db.touch(appeal)
    return resp.success_object(resp.public(appeal))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/appeals/<appealId>/grant", methods=["POST"])
def grant_appeal(deptId, matterId, invoiceId, lineId, appealId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter, inv, line, appeal = helpers.resolve_appeal(deptId, matterId, invoiceId, lineId, appealId)
    if appeal.get("status") != "UNDER_REVIEW":
        raise errors.invalid_state()
    body = helpers.get_body()
    appeal["status"] = "GRANTED"
    if body.get("resolution_note") is not None:
        appeal["resolution_note"] = body["resolution_note"]
    db.touch(appeal)
    # Cascade hop 1: line REJECTED -> REINSTATED, reason cleared.
    if line.get("review_status") == "REJECTED":
        line["review_status"] = "REINSTATED"
        line["rejection_reason_code"] = None
        db.touch(line)
    # Cascade hop 2: invoice totals recomputed (line included again).
    old_inv_status = inv.get("status")
    svc.finalize_invoice_state(inv, matter, old_inv_status)
    # Cascade hop 3: matter billed_to_date increases by the line's amount as a
    # compensating credit on top of whatever was already booked.
    matter["billed_to_date_cents"] = int(matter.get("billed_to_date_cents", 0)) + int(line.get("amount_cents", 0))
    svc.refresh_forecast(matter["id"])
    db.touch(inv)
    return resp.success_object(resp.public(appeal))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/invoices/<invoiceId>/line-items/<lineId>/appeals/<appealId>/deny", methods=["POST"])
def deny_appeal(deptId, matterId, invoiceId, lineId, appealId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter, inv, line, appeal = helpers.resolve_appeal(deptId, matterId, invoiceId, lineId, appealId)
    if appeal.get("status") != "UNDER_REVIEW":
        raise errors.invalid_state()
    body = helpers.get_body()
    appeal["status"] = "DENIED"
    if body.get("resolution_note") is not None:
        appeal["resolution_note"] = body["resolution_note"]
    db.touch(appeal)
    # Cascade hop 1: line REJECTED -> UPHELD.
    if line.get("review_status") == "REJECTED":
        line["review_status"] = "UPHELD"
        db.touch(line)
    # Cascade hop 2: invoice totals recomputed (no amount change; status flip).
    svc.finalize_invoice_state(inv, matter, inv.get("status"))
    db.touch(inv)
    return resp.success_object(resp.public(appeal))
