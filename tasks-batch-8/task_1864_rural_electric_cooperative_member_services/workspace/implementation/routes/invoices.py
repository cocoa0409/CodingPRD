"""Invoice endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, require_member_ownership, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import invoice as inv_svc
from db import store

bp = Blueprint("invoices", __name__)


@bp.route("/coop/invoices", methods=["POST"])
def create_invoice():
    uid, role = get_context()
    require_roles(["BillingClerk"])
    body = get_json_body()
    result = inv_svc.create_invoice(body)
    return created(result)


@bp.route("/coop/invoices/<inv_id>", methods=["GET"])
def get_invoice(inv_id):
    uid, role = get_context()
    require_roles(["BillingClerk", "MemberServicesRep", "Member"])
    result = inv_svc.get_invoice(inv_id)
    if role == "Member":
        loc = store.service_locations.get(result["service_location_id"])
        if loc:
            require_member_ownership(loc.get("member_id"))
    return ok(result)


@bp.route("/coop/invoices", methods=["GET"])
def list_invoices():
    uid, role = get_context()
    require_roles(["BillingClerk", "MemberServicesRep"])
    service_location_id = request.args.get("service_location_id")
    status = request.args.get("status")
    rows = inv_svc.list_invoices(service_location_id, status)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/invoices/<inv_id>/finalize", methods=["POST"])
def finalize_invoice(inv_id):
    uid, role = get_context()
    require_roles(["BillingClerk"])
    result = inv_svc.finalize_invoice(inv_id)
    return ok(result)


@bp.route("/coop/invoices/<inv_id>/pay", methods=["POST"])
def pay_invoice(inv_id):
    uid, role = get_context()
    require_roles(["BillingClerk"])
    result = inv_svc.pay_invoice(inv_id)
    return ok(result)


@bp.route("/coop/invoices/<inv_id>/write-off", methods=["POST"])
def write_off_invoice(inv_id):
    uid, role = get_context()
    require_roles(["BillingClerk"])
    result = inv_svc.write_off_invoice(inv_id)
    return ok(result)


@bp.route("/coop/invoices/<inv_id>/void", methods=["POST"])
def void_invoice(inv_id):
    uid, role = get_context()
    require_roles(["BillingClerk"])
    result = inv_svc.void_invoice(inv_id)
    return ok(result)
