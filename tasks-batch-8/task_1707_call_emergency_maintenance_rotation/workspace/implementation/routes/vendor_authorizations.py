"""VendorAuthorization endpoints."""

import math

from flask import Blueprint, request

from db import store, clock
from errors import (
    ApiError,
    ERR_CALL_TICKET_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
    ERR_VENDOR_AUTHORIZATION_NOT_FOUND,
    ERR_VENDOR_AUTHORIZATION_INVALID_STATE,
    ERR_REFERENTIAL_MISMATCH,
    ERR_VENDOR_SUSPENDED,
    ERR_SELF_AUTHORIZATION_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VENDOR_MISMATCH,
    ERR_VENDOR_LIMIT_EXCEEDED,
    ERR_ROLE_AUTH_LIMIT_EXCEEDED,
    ERR_INCIDENT_VENDOR_CAP_EXCEEDED,
    ERR_INVOICE_EXCEEDS_AUTHORIZATION,
    ERR_INVALID_REQUEST,
)
from helpers import (
    body,
    req_int,
    new_id,
    serialize_vendor_authorization,
    touch,
    pagination_params,
)
from middleware import get_actor, require_role, require_supervisor_capable
from response import success_object, success_list
from services.calculations import (
    invoice_settlement,
    TECH_SELF_AUTH_CAP_CENTS,
    SUPERVISOR_AUTH_CAP_CENTS,
    INCIDENT_VENDOR_CAP_CENTS,
)

bp = Blueprint("vendor_authorizations", __name__)

READ_ROLES = {
    "PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor", "Vendor",
}


@bp.route("/v1/call-tickets/<callTicketId>/vendor-authorizations", methods=["POST"])
def propose_authorization(callTicketId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    ticket = store.call_tickets.get(callTicketId)
    if ticket is None:
        raise ApiError(ERR_CALL_TICKET_NOT_FOUND, "Call ticket not found", 404)
    data = body()
    work_order_id = data.get("work_order_id")
    if not isinstance(work_order_id, str) or not work_order_id:
        raise ApiError(ERR_INVALID_REQUEST, "work_order_id is required", 400)
    vendor_id = data.get("vendor_id")
    if not isinstance(vendor_id, str) or not vendor_id:
        raise ApiError(ERR_INVALID_REQUEST, "vendor_id is required", 400)
    amount_cents = req_int(data, "amount_cents", minimum=1)
    # Body FK existence
    wo = store.work_orders.get(work_order_id)
    if wo is None:
        raise ApiError(ERR_WORK_ORDER_NOT_FOUND, "Work order not found", 404)
    vendor = store.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError(ERR_VENDOR_NOT_FOUND, "Vendor not found", 404)
    # Referential (priority 7): work order must belong to the ticket
    if wo["call_ticket_id"] != ticket["id"]:
        raise ApiError(ERR_REFERENTIAL_MISMATCH, "Work order does not belong to this ticket", 422)
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_SUSPENDED, "Vendor is suspended", 409)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "call_ticket_id": ticket["id"],
        "work_order_id": work_order_id,
        "vendor_id": vendor_id,
        "amount_cents": amount_cents,
        "requested_by_technician_id": actor.user_id,
        "authorized_by_technician_id": None,
        "status": "PROPOSED",
        "invoice_subtotal_cents": None,
        "invoice_markup_cents": None,
        "invoice_total_cents": None,
        "_seq": store.next_seq(),
    }
    store.vendor_authorizations[rec["id"]] = rec
    return success_object(serialize_vendor_authorization(rec), 201)


@bp.route("/v1/vendor-authorizations", methods=["GET"])
def list_authorizations():
    actor = get_actor()
    require_role(actor, READ_ROLES)
    limit, offset = pagination_params()
    items = list(store.vendor_authorizations.values())
    for key in (
        "call_ticket_id",
        "work_order_id",
        "vendor_id",
        "requested_by_technician_id",
        "authorized_by_technician_id",
        "status",
    ):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a[key] == v]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_vendor_authorization(a) for a in page], limit, offset, total)


def _get_auth_or_404(auth_id):
    rec = store.vendor_authorizations.get(auth_id)
    if rec is None:
        raise ApiError(ERR_VENDOR_AUTHORIZATION_NOT_FOUND, "Vendor authorization not found", 404)
    return rec


@bp.route("/v1/vendor-authorizations/<vendorAuthorizationId>", methods=["GET"])
def get_authorization(vendorAuthorizationId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = _get_auth_or_404(vendorAuthorizationId)
    return success_object(serialize_vendor_authorization(rec))


@bp.route("/v1/vendor-authorizations/<vendorAuthorizationId>/authorize", methods=["POST"])
def authorize_authorization(vendorAuthorizationId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    rec = _get_auth_or_404(vendorAuthorizationId)
    # State (priority 5)
    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_VENDOR_AUTHORIZATION_INVALID_STATE, "Authorization is not PROPOSED", 409)
    # SoD before fiscal caps (priority 2 scoping, evaluated after state here per
    # PRD §3.6: "The authorization must be PROPOSED... The segregation-of-duties
    # check comes before any fiscal cap")
    if actor.is_technician_backed and actor.user_id == rec["requested_by_technician_id"]:
        if rec["amount_cents"] > TECH_SELF_AUTH_CAP_CENTS:
            raise ApiError(
                ERR_SELF_AUTHORIZATION_FORBIDDEN,
                "Self-authorization above the technician cap is forbidden",
                403,
            )
    vendor = store.vendors.get(rec["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_SUSPENDED, "Vendor is suspended", 409)
    # Fiscal caps (priority 10) in pinned order, equality allowed
    if rec["amount_cents"] > vendor["per_incident_limit_cents"]:
        raise ApiError(ERR_VENDOR_LIMIT_EXCEEDED, "Amount exceeds vendor per-incident limit", 402)
    if actor.role == "OnCallTechnician":
        role_cap = TECH_SELF_AUTH_CAP_CENTS
    elif actor.role == "MaintenanceSupervisor":
        role_cap = SUPERVISOR_AUTH_CAP_CENTS
    else:
        role_cap = None  # PropertyAdmin unlimited
    if role_cap is not None and rec["amount_cents"] > role_cap:
        raise ApiError(ERR_ROLE_AUTH_LIMIT_EXCEEDED, "Amount exceeds the acting role's cap", 402)
    committed = 0
    for a in store.vendor_authorizations.values():
        if (
            a["call_ticket_id"] == rec["call_ticket_id"]
            and a["id"] != rec["id"]
            and a["status"] in ("AUTHORIZED", "INVOICED", "PAID")
        ):
            committed += a["amount_cents"]
    if committed + rec["amount_cents"] > INCIDENT_VENDOR_CAP_CENTS:
        raise ApiError(ERR_INCIDENT_VENDOR_CAP_EXCEEDED, "Incident vendor cap exceeded", 402)
    rec["authorized_by_technician_id"] = actor.user_id if actor.is_technician_backed else None
    rec["status"] = "AUTHORIZED"
    touch(rec)
    # Linked work order OPEN -> ASSIGNED (vendor engagement; technician stays null)
    wo = store.work_orders.get(rec["work_order_id"])
    if wo is not None and wo["status"] == "OPEN":
        wo["status"] = "ASSIGNED"
        touch(wo)
    return success_object(serialize_vendor_authorization(rec))


@bp.route("/v1/vendor-authorizations/<vendorAuthorizationId>/reject", methods=["POST"])
def reject_authorization(vendorAuthorizationId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    rec = _get_auth_or_404(vendorAuthorizationId)
    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_VENDOR_AUTHORIZATION_INVALID_STATE, "Authorization is not PROPOSED", 409)
    if actor.user_id == rec["requested_by_technician_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Requester cannot reject their own proposal", 403)
    rec["status"] = "REJECTED"
    touch(rec)
    return success_object(serialize_vendor_authorization(rec))


@bp.route("/v1/vendor-authorizations/<vendorAuthorizationId>/void", methods=["POST"])
def void_authorization(vendorAuthorizationId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    rec = _get_auth_or_404(vendorAuthorizationId)
    if rec["status"] != "AUTHORIZED":
        raise ApiError(ERR_VENDOR_AUTHORIZATION_INVALID_STATE, "Authorization is not AUTHORIZED", 409)
    rec["status"] = "VOIDED"
    touch(rec)
    # Compensation: release work order ASSIGNED -> OPEN when no sibling
    # authorization on the same work order remains in {AUTHORIZED, INVOICED}
    wo = store.work_orders.get(rec["work_order_id"])
    if wo is not None and wo["status"] == "ASSIGNED":
        sibling_engaged = False
        for a in store.vendor_authorizations.values():
            if (
                a["work_order_id"] == wo["id"]
                and a["id"] != rec["id"]
                and a["status"] in ("AUTHORIZED", "INVOICED")
            ):
                sibling_engaged = True
                break
        if not sibling_engaged:
            wo["status"] = "OPEN"
            touch(wo)
    return success_object(serialize_vendor_authorization(rec))


@bp.route("/v1/vendor-authorizations/<vendorAuthorizationId>/invoice", methods=["POST"])
def invoice_authorization(vendorAuthorizationId):
    actor = get_actor()
    require_role(actor, {"Vendor"})
    rec = _get_auth_or_404(vendorAuthorizationId)
    data = body()
    lines = data.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array", 400)
    parsed_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError(ERR_INVALID_REQUEST, "each line must be an object", 400)
        description = line.get("description")
        if not isinstance(description, str) or not description:
            raise ApiError(ERR_INVALID_REQUEST, "line description is required", 400)
        quantity = line.get("quantity")
        # PRD §3.6 pins per-line rounding of quantity x unit_cost_cents, which
        # is only meaningful when fractional quantities are accepted; quantity
        # is a positive number, not necessarily an integer.
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, (int, float))
            or not math.isfinite(quantity)
            or quantity <= 0
        ):
            raise ApiError(ERR_INVALID_REQUEST, "line quantity must be a positive number", 400)
        unit_cost = line.get("unit_cost_cents")
        if isinstance(unit_cost, bool) or not isinstance(unit_cost, int) or unit_cost < 0:
            raise ApiError(ERR_INVALID_REQUEST, "line unit_cost_cents must be a non-negative integer", 400)
        parsed_lines.append({"description": description, "quantity": quantity, "unit_cost_cents": unit_cost})
    markup_bp = data.get("overhead_markup_bp")
    if isinstance(markup_bp, bool) or not isinstance(markup_bp, int) or markup_bp < 0:
        raise ApiError(ERR_INVALID_REQUEST, "overhead_markup_bp must be a non-negative integer", 400)
    # State (priority 5)
    if rec["status"] != "AUTHORIZED":
        raise ApiError(ERR_VENDOR_AUTHORIZATION_INVALID_STATE, "Authorization is not AUTHORIZED", 409)
    # Vendor self-check
    if actor.user_id != rec["vendor_id"]:
        raise ApiError(ERR_VENDOR_MISMATCH, "X-User-ID does not match the authorization's vendor", 403)
    subtotal, markup, total, ceiling = invoice_settlement(
        parsed_lines, markup_bp, rec["amount_cents"]
    )
    if total > ceiling:
        raise ApiError(ERR_INVOICE_EXCEEDS_AUTHORIZATION, "Invoice exceeds the overage ceiling", 409)
    rec["invoice_subtotal_cents"] = subtotal
    rec["invoice_markup_cents"] = markup
    rec["invoice_total_cents"] = total
    rec["status"] = "INVOICED"
    touch(rec)
    return success_object(serialize_vendor_authorization(rec))


@bp.route("/v1/vendor-authorizations/<vendorAuthorizationId>/mark-paid", methods=["POST"])
def mark_paid_authorization(vendorAuthorizationId):
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    rec = _get_auth_or_404(vendorAuthorizationId)
    if rec["status"] != "INVOICED":
        raise ApiError(ERR_VENDOR_AUTHORIZATION_INVALID_STATE, "Authorization is not INVOICED", 409)
    rec["status"] = "PAID"
    touch(rec)
    return success_object(serialize_vendor_authorization(rec))
