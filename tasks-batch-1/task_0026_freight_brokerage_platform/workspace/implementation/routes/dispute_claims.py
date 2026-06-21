"""DisputeClaim endpoints (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_DISPUTE_AMOUNT_EXCEEDS_OPEN,
    ERR_RESOLUTION_AMOUNT_INVALID,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_enum,
    require_int_or_str_int,
    lookup_path_or_404,
    lookup_fk_or_422,
)
from services.calculations import (
    compute_invoice_total,
    recompute_shipper_open_ar,
)


bp = Blueprint("dispute_claims", __name__)


CLAIM_TYPES = {"OVERCHARGE", "DAMAGED_GOODS", "LATE_DELIVERY", "MISSING_POD"}
RESOLUTION_KINDS = {"UPHELD", "PARTIAL", "DENIED"}


def _shipper_id_for_invoice(invoice):
    load = db.loads.get(invoice.get("load_id"))
    if load is None:
        return None
    q = db.quote_requests.get(load.get("quote_request_id"))
    return q.get("shipper_id") if q else None


@bp.post("/freight/dispute-claims")
def open_dispute():
    require_auth(["Shipper"])()
    body = get_json_body()
    require_fields(body, ["invoice_id", "claim_type", "claimed_amount_cents"])
    invoice = lookup_fk_or_422(db.invoices, body["invoice_id"], "Invoice")

    # Shipper ownership: invoice's shipper must equal X-User-ID.
    if _shipper_id_for_invoice(invoice) != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only dispute own invoices")

    require_enum(body["claim_type"], CLAIM_TYPES, "claim_type")
    amount = require_int_or_str_int(body["claimed_amount_cents"], "claimed_amount_cents")
    if amount <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "claimed_amount_cents must be > 0")

    # priority 5: state
    if invoice.get("status") not in {"ISSUED", "PARTIALLY_PAID"}:
        raise APIError(ERR_INVALID_STATE, 409, "Invoice not eligible for dispute")
    # priority 15: amount bound
    remaining = int(invoice["total_cents"]) - int(invoice.get("amount_paid_cents", 0))
    if amount > remaining:
        raise APIError(ERR_DISPUTE_AMOUNT_EXCEEDS_OPEN, 422, "Claimed amount exceeds open balance")

    prior_status = invoice["status"]
    claim = {
        "invoice_id": invoice["id"],
        "claim_type": body["claim_type"],
        "claimed_amount_cents": amount,
        "resolution_amount_cents": None,
        "resolution_kind": None,
        "status": "OPEN",
        # Remember the invoice's prior status so withdrawal can revert.
        "_prior_invoice_status": prior_status,
    }
    db.stamp_common(claim)
    db.dispute_claims[claim["id"]] = claim

    invoice["status"] = "DISPUTED"
    db.bump(invoice)

    # Shipper open AR conservation: DISPUTED still contributes per §2.9.
    sid = _shipper_id_for_invoice(invoice)
    if sid:
        recompute_shipper_open_ar(sid)

    # Strip internal _prior_invoice_status from response.
    response = {k: v for k, v in claim.items() if not k.startswith("_")}
    return ok_object(response, 201)


def _claim_visible_to(claim, role: str, uid: str) -> bool:
    if role == "BrokerOps":
        return True
    if role == "Shipper":
        invoice = db.invoices.get(claim.get("invoice_id"))
        return invoice is not None and _shipper_id_for_invoice(invoice) == uid
    return False


def _strip_internal(claim):
    return {k: v for k, v in claim.items() if not k.startswith("_")}


@bp.get("/freight/dispute-claims/<did>")
def get_dispute(did: str):
    require_auth(["BrokerOps", "Shipper"])()
    claim = lookup_path_or_404(db.dispute_claims, did, "DisputeClaim")
    if not _claim_visible_to(claim, current_role(), current_user_id()):
        raise APIError(ERR_UNAUTHORIZED, 403, "Not permitted to view this dispute claim")
    return ok_object(_strip_internal(claim), 200)


@bp.get("/freight/dispute-claims")
def list_disputes():
    require_auth(["BrokerOps", "Shipper"])()
    limit, offset = paginate_params(request.args)
    invoice_filter = request.args.get("invoice_id")
    status_filter = request.args.get("status")
    items = list(db.dispute_claims.values())
    role = current_role()
    uid = current_user_id()
    if role == "Shipper":
        items = [c for c in items if _claim_visible_to(c, role, uid)]
    if invoice_filter:
        items = [c for c in items if c.get("invoice_id") == invoice_filter]
    if status_filter:
        items = [c for c in items if c.get("status") == status_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    payload = [_strip_internal(c) for c in page]
    return ok_array(payload, limit, offset, total, 200)


@bp.post("/freight/dispute-claims/<did>/resolve")
def resolve_dispute(did: str):
    require_auth(["BrokerOps"])()
    claim = lookup_path_or_404(db.dispute_claims, did, "DisputeClaim")
    body = get_json_body()
    require_fields(body, ["resolution_kind", "resolution_amount_cents"])
    require_enum(body["resolution_kind"], RESOLUTION_KINDS, "resolution_kind")
    amount = require_int_or_str_int(body["resolution_amount_cents"], "resolution_amount_cents")
    kind = body["resolution_kind"]

    if claim.get("status") != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "DisputeClaim must be OPEN to resolve")

    invoice = db.invoices.get(claim["invoice_id"])
    if invoice is None:
        raise APIError(ERR_INVALID_STATE, 409, "Invoice missing")
    remaining = int(invoice["total_cents"]) - int(invoice.get("amount_paid_cents", 0))

    # priority 16: resolution_amount bound by resolution_kind
    if kind == "DENIED":
        if amount != 0:
            raise APIError(ERR_RESOLUTION_AMOUNT_INVALID, 422, "DENIED must have resolution_amount_cents == 0")
    elif kind == "UPHELD":
        if amount != remaining:
            raise APIError(ERR_RESOLUTION_AMOUNT_INVALID, 422, "UPHELD must equal open balance")
    elif kind == "PARTIAL":
        if not (0 < amount < remaining):
            raise APIError(ERR_RESOLUTION_AMOUNT_INVALID, 422, "PARTIAL must be > 0 and < open balance")

    claim["status"] = "RESOLVED"
    claim["resolution_kind"] = kind
    claim["resolution_amount_cents"] = amount
    db.bump(claim)

    if kind == "DENIED":
        # Rewind: ISSUED if paid == 0 else PARTIALLY_PAID
        if int(invoice.get("amount_paid_cents", 0)) == 0:
            invoice["status"] = "ISSUED"
        else:
            invoice["status"] = "PARTIALLY_PAID"
        db.bump(invoice)
    elif kind == "PARTIAL":
        # Rerun invoice_total_cents with the new PARTIAL credit term.
        load = db.loads.get(invoice["load_id"])
        new_total = compute_invoice_total(load, invoice["id"])
        invoice["total_cents"] = new_total
        if int(invoice.get("amount_paid_cents", 0)) == 0:
            invoice["status"] = "ISSUED"
        else:
            invoice["status"] = "PARTIALLY_PAID"
        db.bump(invoice)
    elif kind == "UPHELD":
        invoice["status"] = "WRITTEN_OFF"
        db.bump(invoice)
        # Cascade hop 2: Load -> CLOSED
        load = db.loads.get(invoice["load_id"])
        if load is not None and load.get("status") in {"INVOICED", "DELIVERED", "IN_TRANSIT", "AWARDED"}:
            load["status"] = "CLOSED"
            db.bump(load)
        # Cascade hop 3: FactoringRequest -> RECOURSE when factored
        if invoice.get("factored"):
            for fr in db.factoring_requests.values():
                if fr.get("invoice_id") == invoice["id"] and fr.get("status") == "ADVANCED":
                    fr["status"] = "RECOURSE"
                    db.bump(fr)

    # Conservation: recompute shipper open AR.
    sid = _shipper_id_for_invoice(invoice)
    if sid:
        recompute_shipper_open_ar(sid)

    return ok_object(_strip_internal(claim), 200)


@bp.post("/freight/dispute-claims/<did>/withdraw")
def withdraw_dispute(did: str):
    require_auth(["Shipper"])()
    claim = lookup_path_or_404(db.dispute_claims, did, "DisputeClaim")
    invoice = db.invoices.get(claim.get("invoice_id"))
    if invoice is None:
        raise APIError(ERR_INVALID_STATE, 409, "Invoice missing")
    # Ownership: must own the underlying invoice's shipper.
    if _shipper_id_for_invoice(invoice) != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only withdraw own disputes")
    if claim.get("status") != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "DisputeClaim must be OPEN to withdraw")

    claim["status"] = "WITHDRAWN"
    db.bump(claim)

    # Revert invoice to its pre-DISPUTED status.
    prior = claim.get("_prior_invoice_status")
    if not prior:
        prior = "ISSUED" if int(invoice.get("amount_paid_cents", 0)) == 0 else "PARTIALLY_PAID"
    invoice["status"] = prior
    db.bump(invoice)

    sid = _shipper_id_for_invoice(invoice)
    if sid:
        recompute_shipper_open_ar(sid)

    return ok_object(_strip_internal(claim), 200)
