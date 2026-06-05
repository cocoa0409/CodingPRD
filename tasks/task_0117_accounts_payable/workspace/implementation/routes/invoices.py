"""Invoice endpoints: capture, lines, code/match, submit-approval, reject, and
nested reverse-reachability lists (PRD §3.3, §3.4, §3.5, §2.8)."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_GL_ACCOUNT_NOT_POSTABLE, ERR_DUPLICATE_INVOICE, ERR_EXCEPTION_UNRESOLVED,
    ERR_NO_APPROVAL_ROUTE,
)
from middleware import auth_required, ALL_ROLES, current_user_id
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int, is_str, is_number,
    parse_pagination, paginate, order_by_created,
)
from routes.gl_accounts import find_gl_by_code
from services.calculations import (
    CONFIDENCE_FLOOR, match_variance, match_tolerance_cents, breaches_tolerance,
)
from services.common import new_common_fields, touch
from services.ledger import recompute_invoice_total, recompute_po_matched
from services.audit import append_audit

bp = Blueprint("invoices", __name__)


def _parse_date(value: str):
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 400, "invoice_date must be an ISO 8601 date")


def _add_days_iso(value: str, days: int) -> str:
    """Advance an ISO date by `days`, preserving the original textual format."""
    base = _parse_date(value)
    result = base + timedelta(days=days)
    if "T" in value:
        # Preserve a datetime form (UTC, millisecond precision, 'Z').
        return result.strftime("%Y-%m-%dT%H:%M:%S.") + f"{result.microsecond // 1000:03d}Z"
    return result.strftime("%Y-%m-%d")


def _po_has_posted_receipt(po_id: str) -> bool:
    return any(
        gr["po_id"] == po_id and gr["status"] == "POSTED"
        for gr in db.goods_receipts.values()
    )


def _compute_match_type(po_id) -> str:
    if po_id is None:
        return "NON_PO"
    return "THREE_WAY" if _po_has_posted_receipt(po_id) else "TWO_WAY"


@bp.post("/ap/invoices")
def capture_invoice():
    auth_required({"APClerk", "APManager"})()
    body = get_body()
    require_fields(body, ["vendor_id", "invoice_number", "invoice_date"])

    vendor_id = body["vendor_id"]
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise APIError(ERR_NOT_FOUND, 404, "Vendor not found")

    po_id = body.get("po_id")
    if po_id is not None:
        if po_id not in db.purchase_orders:
            raise APIError(ERR_NOT_FOUND, 404, "Purchase order not found")

    invoice_number = body["invoice_number"]
    if not is_str(invoice_number) or not invoice_number:
        raise APIError(ERR_INVALID_REQUEST, 400, "invoice_number must be a non-empty string")

    invoice_date = body["invoice_date"]
    if not is_str(invoice_date):
        raise APIError(ERR_INVALID_REQUEST, 400, "invoice_date must be a string")
    _parse_date(invoice_date)

    ocr_confidence = body.get("ocr_confidence", 1.0)
    if not is_number(ocr_confidence) or ocr_confidence < 0.0 or ocr_confidence > 1.0:
        raise APIError(ERR_INVALID_REQUEST, 400, "ocr_confidence must be a number in [0.0, 1.0]")

    # Computed at capture: due_date, discount_deadline, match_type (PRD §3.3).
    due_date = _add_days_iso(invoice_date, vendor["net_terms_days"])
    if vendor["early_pay_terms_pct"] and vendor["early_pay_terms_pct"] > 0:
        discount_deadline = _add_days_iso(invoice_date, vendor["early_pay_window_days"])
    else:
        discount_deadline = None
    match_type = _compute_match_type(po_id)

    # Low OCR confidence forces CODING_REVIEW instead of CAPTURED (PRD §3.3).
    status = "CODING_REVIEW" if ocr_confidence < CONFIDENCE_FLOOR else "CAPTURED"

    inv = {
        **new_common_fields(),
        "vendor_id": vendor_id,
        "po_id": po_id,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "ocr_confidence": ocr_confidence,
        "total_amount_cents": 0,
        "match_type": match_type,
        "variance_cents": 0,
        "due_date": due_date,
        "discount_deadline": discount_deadline,
        "coded_by": None,
        "approved_by": None,
        "status": status,
    }
    db.invoices[inv["id"]] = inv
    return ok_object(serialize(inv), http_status=201)


@bp.get("/ap/invoices/<iid>")
def get_invoice(iid):
    auth_required(ALL_ROLES)()
    inv = db.invoices.get(iid)
    if inv is None:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")
    return ok_object(serialize(inv))


@bp.get("/ap/invoices")
def list_invoices():
    auth_required(ALL_ROLES)()
    limit, offset = parse_pagination()
    vendor_id = request.args.get("vendor_id")
    po_id = request.args.get("po_id")
    status = request.args.get("status")
    items = [
        inv for inv in db.invoices.values()
        if (vendor_id is None or inv["vendor_id"] == vendor_id)
        and (po_id is None or inv["po_id"] == po_id)
        and (status is None or inv["status"] == status)
    ]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/ap/invoices/<iid>/lines")
def add_line(iid):
    auth_required({"APClerk"})()
    inv = db.invoices.get(iid)
    if inv is None:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")
    body = get_body()
    require_fields(body, ["gl_account_code", "amount_cents"])

    gl_account_code = body["gl_account_code"]
    if not is_str(gl_account_code):
        raise APIError(ERR_INVALID_REQUEST, 400, "gl_account_code must be a string")

    amount_cents = body["amount_cents"]
    if not is_int(amount_cents) or amount_cents < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "amount_cents must be an integer >= 1")

    description = body.get("description")
    if description is not None and not is_str(description):
        raise APIError(ERR_INVALID_REQUEST, 400, "description must be a string")

    # business_referential: line must code to a postable GLAccount (422).
    gl = find_gl_by_code(gl_account_code)
    if gl is None or not gl["is_postable"]:
        raise APIError(ERR_GL_ACCOUNT_NOT_POSTABLE, 422,
                       "gl_account_code must reference a postable GL account")

    line = {
        **new_common_fields(),
        "invoice_id": iid,
        "gl_account_code": gl_account_code,
        "amount_cents": amount_cents,
        "description": description,
    }
    db.invoice_lines[line["id"]] = line
    recompute_invoice_total(inv)
    return ok_object(serialize(line), http_status=201)


@bp.get("/ap/invoices/<iid>/lines")
def list_lines(iid):
    auth_required(ALL_ROLES)()
    if iid not in db.invoices:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")
    limit, offset = parse_pagination()
    items = [ln for ln in db.invoice_lines.values() if ln["invoice_id"] == iid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


def _invoice_exceptions(iid):
    return [me for me in db.match_exceptions.values() if me["invoice_id"] == iid]


@bp.post("/ap/invoices/<iid>/code")
def code_invoice(iid):
    auth_required({"APClerk"})()
    inv = db.invoices.get(iid)
    if inv is None:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")

    # State: match may run from CAPTURED or CODING_REVIEW only.
    if inv["status"] not in ("CAPTURED", "CODING_REVIEW"):
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not in a codable state")
    prior_status = inv["status"]

    # business: requires >=1 line and total > 0.
    if inv["total_amount_cents"] <= 0:
        raise APIError(ERR_INVALID_STATE, 409, "Invoice has no lines / total is 0")

    # From CAPTURED, ocr_confidence must be at/above the floor.
    if inv["status"] == "CAPTURED" and inv["ocr_confidence"] < CONFIDENCE_FLOOR:
        raise APIError(ERR_INVALID_STATE, 409, "ocr_confidence below the confidence floor")

    # When re-coding from CODING_REVIEW, all exceptions must be non-PENDING (409).
    if inv["status"] == "CODING_REVIEW":
        if any(me["resolution"] == "PENDING" for me in _invoice_exceptions(iid)):
            raise APIError(ERR_EXCEPTION_UNRESOLVED, 409,
                           "All match exceptions must be resolved before coding")

    # Duplicate detection: no other invoice with same vendor_id + invoice_number (409).
    for other in db.invoices.values():
        if other["id"] == iid:
            continue
        if other["vendor_id"] == inv["vendor_id"] and other["invoice_number"] == inv["invoice_number"]:
            raise APIError(ERR_DUPLICATE_INVOICE, 409,
                           "Another invoice exists with the same vendor and invoice number")

    # Compute match_type and variance.
    match_type = _compute_match_type(inv["po_id"])
    inv["match_type"] = match_type
    po = db.purchase_orders.get(inv["po_id"]) if inv["po_id"] else None
    variance = match_variance(match_type, inv["total_amount_cents"], po) if po else 0
    # A WRITTEN_OFF exception absorbs the variance to 0 (PRD §3.4); that zero
    # persists through the revision-loop recompute, which is the documented
    # distinction between write-off and resolve. RESOLVED keeps the original
    # (recomputed) variance.
    if prior_status == "CODING_REVIEW" and any(
        me["resolution"] == "WRITTEN_OFF" for me in _invoice_exceptions(iid)
    ):
        variance = 0
    inv["variance_cents"] = variance
    inv["coded_by"] = current_user_id()

    # Tolerance is only re-tested on the first match out of CAPTURED. Re-coding
    # from CODING_REVIEW (the revision loop, reached only once all exceptions are
    # non-PENDING) advances straight to MATCHED with the variance preserved
    # (PRD §3.4): it does not create a fresh exception.
    if prior_status == "CODING_REVIEW":
        breaches = False
    elif match_type == "NON_PO" or po is None:
        # Nothing to match against — always within tolerance.
        breaches = False
    else:
        tolerance = match_tolerance_cents(po)
        breaches = breaches_tolerance(variance, tolerance)

    if not breaches:
        inv["status"] = "MATCHED"
        touch(inv)
        if po is not None:
            recompute_po_matched(po)
    else:
        # Breach: create a PENDING MatchException and hold in CODING_REVIEW.
        reason = "PRICE_VARIANCE" if match_type == "TWO_WAY" else "QTY_VARIANCE"
        me = {
            **new_common_fields(),
            "invoice_id": iid,
            "reason": reason,
            "variance_cents": variance,
            "resolution": "PENDING",
            "resolved_by": None,
        }
        db.match_exceptions[me["id"]] = me
        inv["status"] = "CODING_REVIEW"
        touch(inv)

    append_audit(iid, "CODED", current_user_id())
    return ok_object(serialize(inv))


@bp.post("/ap/invoices/<iid>/submit-approval")
def submit_approval(iid):
    auth_required({"APClerk"})()
    inv = db.invoices.get(iid)
    if inv is None:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")

    # State: submission only from MATCHED.
    if inv["status"] != "MATCHED":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not in MATCHED state")

    # business: no pending match exceptions (409).
    if any(me["resolution"] == "PENDING" for me in _invoice_exceptions(iid)):
        raise APIError(ERR_EXCEPTION_UNRESOLVED, 409,
                       "All match exceptions must be resolved before submitting for approval")

    # Select the approval tier covering the invoice total [min, max) (PRD §3.5).
    total = inv["total_amount_cents"]
    tier = None
    for r in db.approval_routes.values():
        if r["min_amount_cents"] <= total < r["max_amount_cents"]:
            tier = r
            break
    if tier is None:
        raise APIError(ERR_NO_APPROVAL_ROUTE, 422, "No approval route covers the invoice total")

    for lvl in range(1, tier["required_levels"] + 1):
        step = {
            **new_common_fields(),
            "invoice_id": iid,
            "level": lvl,
            "status": "PENDING",
            "acted_by": None,
        }
        db.approval_steps[step["id"]] = step

    inv["status"] = "PENDING_APPROVAL"
    touch(inv)
    append_audit(iid, "SUBMITTED", current_user_id())
    return ok_object(serialize(inv))


@bp.post("/ap/invoices/<iid>/reject")
def reject_invoice(iid):
    auth_required({"APClerk"})()
    inv = db.invoices.get(iid)
    if inv is None:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")
    # State: reject only from CODING_REVIEW (PRD §3.4).
    if inv["status"] != "CODING_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not in CODING_REVIEW state")
    inv["status"] = "REJECTED"
    touch(inv)
    append_audit(iid, "REJECTED", current_user_id())
    return ok_object(serialize(inv))


@bp.get("/ap/invoices/<iid>/audit-events")
def list_audit_events(iid):
    auth_required(ALL_ROLES)()
    if iid not in db.invoices:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")
    limit, offset = parse_pagination()
    items = [ev for ev in db.audit_events.values() if ev["invoice_id"] == iid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.get("/ap/invoices/<iid>/match-exceptions")
def list_invoice_exceptions(iid):
    auth_required(ALL_ROLES)()
    if iid not in db.invoices:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")
    limit, offset = parse_pagination()
    items = _invoice_exceptions(iid)
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.get("/ap/invoices/<iid>/approval-steps")
def list_invoice_steps(iid):
    auth_required(ALL_ROLES)()
    if iid not in db.invoices:
        raise APIError(ERR_NOT_FOUND, 404, "Invoice not found")
    limit, offset = parse_pagination()
    items = [s for s in db.approval_steps.values() if s["invoice_id"] == iid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
