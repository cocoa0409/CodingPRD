"""Invoices: provisional generation, issue, settle, dispute, OCC-guarded
adjustments (PRD 3.8)."""

from flask import Blueprint, request

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVOICE_KIND_EXISTS,
    ERR_UNDERPAYMENT, ERR_OVERPAYMENT, ERR_CREDIT_EXCEEDS_OUTSTANDING,
    ERR_STALE_INVOICE_VERSION, ERR_VESSEL_SCOPE,
)
from middleware import authenticate, ANY, scope_call
from response import success_obj, success_list
from util import body_json, raw_body, check_shape, pagination_params, paginate, apply_filters

bp = Blueprint("invoices", __name__, url_prefix="/port-ops")


def _get_invoice_or_404(invoice_id):
    inv = db.get("invoices", invoice_id)
    if inv is None:
        raise ApiError(ERR_NOT_FOUND, 404, "invoice not found")
    return inv


@bp.route("/port-calls/<call_id>/provisional-invoice", methods=["POST"])
def create_provisional(call_id):
    authenticate({"BillingClerk"})
    call = db.get("port_calls", call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    # Priority 8: the call must not be CANCELLED/CLOSED and must hold a
    # CONFIRMED or ACTIVE berth assignment.
    if call["status"] in ("CANCELLED", "CLOSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the call is CANCELLED or CLOSED")
    if not any(a["status"] in ("CONFIRMED", "ACTIVE")
               for a in services.assignments_of_call(call["id"])):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the call holds no CONFIRMED or ACTIVE berth assignment")
    # Priority 16: one PROVISIONAL invoice per call.
    if services.provisional_invoice_of(call["id"]) is not None:
        raise ApiError(ERR_INVOICE_KIND_EXISTS, 409,
                       "a PROVISIONAL invoice already exists for this call")
    dockage, tax, service, gross = services.compute_invoice_fields(call, "PROVISIONAL")
    inv = db.new_entity("invoices", {
        "port_call_id": call["id"],
        "kind": "PROVISIONAL",
        "status": "DRAFT",
        "dockage_fee_cents": dockage,
        "head_tax_cents": tax,
        "service_fee_cents": service,
        "adjustments_total_cents": 0,
        "gross_cents": gross,
        "total_cents": gross,
        "payment_cents": None,
        "dispute_reason": None,
    })
    return success_obj(db.public(inv), code=201)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("invoices")
    if role == "VesselAgent":
        port_call_id = request.args.get("port_call_id")
        if port_call_id is not None:
            call = db.get("port_calls", port_call_id)
            if call is not None and call["vessel_id"] != user_id:
                raise ApiError(ERR_VESSEL_SCOPE, 403,
                               "vessel agent may only read its own vessel's calls")
        items = [
            i for i in items
            if (db.get("port_calls", i["port_call_id"]) or {}).get("vessel_id") == user_id
        ]
    items = apply_filters(items, ["port_call_id", "kind", "status"])
    page, total, has_more = paginate([db.public(i) for i in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    user_id, role = authenticate(ANY)
    inv = _get_invoice_or_404(invoice_id)
    if role == "VesselAgent":
        call = db.get("port_calls", inv["port_call_id"])
        if call is None or call["vessel_id"] != user_id:
            raise ApiError(ERR_VESSEL_SCOPE, 403,
                           "vessel agent may only read its own vessel's calls")
    return success_obj(db.public(inv))


@bp.route("/invoices/<invoice_id>/issue", methods=["POST"])
def issue(invoice_id):
    authenticate({"BillingClerk"})
    inv = _get_invoice_or_404(invoice_id)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "issue requires status DRAFT")
    inv["status"] = "ISSUED"
    db.touch(inv)
    return success_obj(db.public(inv))


@bp.route("/invoices/<invoice_id>/settle", methods=["POST"])
def settle(invoice_id):
    authenticate({"BillingClerk"})
    inv = _get_invoice_or_404(invoice_id)
    body = body_json()
    check_shape(body, {"payment_cents": {"type": "integer", "required": True}})
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "settle requires status ISSUED")
    payment = body["payment_cents"]
    if payment < inv["total_cents"]:
        raise ApiError(ERR_UNDERPAYMENT, 422, "payment_cents is less than total_cents")
    if payment > inv["total_cents"]:
        raise ApiError(ERR_OVERPAYMENT, 422, "payment_cents is greater than total_cents")
    inv["status"] = "SETTLED"
    inv["payment_cents"] = payment
    db.touch(inv)
    return success_obj(db.public(inv))


@bp.route("/invoices/<invoice_id>/dispute", methods=["POST"])
def dispute(invoice_id):
    user_id, role = authenticate({"VesselAgent"})
    inv = _get_invoice_or_404(invoice_id)
    call = db.get("port_calls", inv["port_call_id"])
    scope_call(user_id, role, call)
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": True}})
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "dispute requires status ISSUED")
    inv["status"] = "DISPUTED"
    inv["dispute_reason"] = body["reason"]
    db.touch(inv)
    return success_obj(db.public(inv))


@bp.route("/invoices/<invoice_id>/adjustments", methods=["POST"])
def post_adjustment(invoice_id):
    authenticate({"BillingClerk"})
    inv = _get_invoice_or_404(invoice_id)
    # Priority 5: OCC on the invoice's version.
    raw = raw_body()
    if raw.get("expected_invoice_version") is not None:
        if raw["expected_invoice_version"] != inv["version"]:
            raise ApiError(ERR_STALE_INVOICE_VERSION, 412,
                           "expected_invoice_version does not match the invoice's current version")
    body = body_json()
    check_shape(body, {
        "amount_cents": {"type": "integer", "required": True, "min": 1},
        "reason": {"type": "string", "required": True},
        "expected_invoice_version": {"type": "integer", "required": True},
    })
    if inv["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "adjustments require status ISSUED or DISPUTED")
    # Priority 24: credit ceiling against the current total.
    if body["amount_cents"] > inv["total_cents"]:
        raise ApiError(ERR_CREDIT_EXCEEDS_OUTSTANDING, 422,
                       "adjustment amount_cents exceeds the current total_cents")
    inv["adjustments_total_cents"] += body["amount_cents"]
    inv["total_cents"] = inv["gross_cents"] - inv["adjustments_total_cents"]
    # A posted adjustment resolves a dispute and re-issues at the adjusted total.
    if inv["status"] == "DISPUTED":
        inv["status"] = "ISSUED"
    db.touch(inv)
    return success_obj(db.public(inv), code=201)
