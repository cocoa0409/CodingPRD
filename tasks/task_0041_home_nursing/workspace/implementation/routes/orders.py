"""Routes for /orders/* endpoints."""
from flask import Blueprint, g, request

import db
from db import public
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from errors import err
from services import order as order_svc
from services import dispatch as dispatch_svc
from services import service_record as sr_svc
from services import waste as waste_svc
from services import settlement as settle_svc


bp = Blueprint("orders", __name__)


@bp.route("/orders", methods=["POST"])
@require_auth(roles={"Patient"})
def create_order():
    body = get_json_body()
    order, replayed = order_svc.create_order(g.user_id, body)
    return success(public(order), status=201)


@bp.route("/orders", methods=["GET"])
@require_auth(roles={"Patient", "PlatformAdmin", "ComplianceOfficer", "Nurse"})
def list_orders():
    limit, offset = get_pagination()
    status = request.args.get("status")
    rows, total = order_svc.list_orders_scoped(g.user_role, g.user_id, limit, offset, status)
    return success_list([public(r) for r in rows], limit, offset, total)


@bp.route("/orders/<order_id>", methods=["GET"])
@require_auth(roles={"Patient", "PlatformAdmin", "ComplianceOfficer", "Nurse"})
def get_order(order_id):
    o = order_svc.get_order_scoped(order_id, g.user_role, g.user_id)
    return success(public(o))


@bp.route("/orders/<order_id>/eligibility-review", methods=["POST"])
@require_auth(roles={"ComplianceOfficer"})
def eligibility(order_id):
    body = get_json_body()
    o = order_svc.eligibility_review(order_id, body)
    return success(public(o))


@bp.route("/orders/<order_id>/cancel", methods=["POST"])
@require_auth(roles={"Patient"})
def cancel(order_id):
    body = get_json_body()
    o = order_svc.cancel_order(order_id, g.user_id, body)
    return success(public(o))


@bp.route("/orders/<order_id>/confirm-completion", methods=["POST"])
@require_auth(roles={"Patient"})
def confirm(order_id):
    body = get_json_body()
    o = order_svc.confirm_completion(order_id, g.user_id, body)
    return success(public(o))


@bp.route("/orders/<order_id>/refund", methods=["POST"])
@require_auth(roles={"ComplianceOfficer"})
def refund(order_id):
    body = get_json_body()
    s = settle_svc.refund_order(order_id, body)
    return success(public(s))


@bp.route("/orders/<order_id>/dispatches", methods=["GET"])
@require_auth(roles={"Patient", "PlatformAdmin", "ComplianceOfficer"})
def list_disp(order_id):
    o = order_svc.get_order(order_id)
    if g.user_role == "Patient" and o.get("patient_id") != g.user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your order")
    limit, offset = get_pagination()
    rows, total = dispatch_svc.list_dispatches_for_order(order_id, limit, offset)
    return success_list([public(r) for r in rows], limit, offset, total)


# ----- Service record ----- #
@bp.route("/orders/<order_id>/service-record", methods=["POST"])
@require_auth(roles={"Nurse"})
def post_sr(order_id):
    body = get_json_body()
    sr = sr_svc.checkin(order_id, g.user_id, body)
    return success(public(sr), status=201)


@bp.route("/orders/<order_id>/service-record", methods=["PATCH"])
@require_auth(roles={"Nurse"})
def patch_sr(order_id):
    body = get_json_body()
    sr = sr_svc.append_record(order_id, g.user_id, body)
    return success(public(sr))


@bp.route("/orders/<order_id>/service-record/finish", methods=["POST"])
@require_auth(roles={"Nurse"})
def finish_sr(order_id):
    body = get_json_body()
    sr = sr_svc.finish(order_id, g.user_id, body)
    return success(public(sr))


# ----- Waste entries ----- #
@bp.route("/orders/<order_id>/waste-entries", methods=["POST"])
@require_auth(roles={"Nurse"})
def post_waste(order_id):
    body = get_json_body()
    w = waste_svc.register_waste(order_id, g.user_id, body)
    return success(public(w), status=201)


@bp.route("/orders/<order_id>/waste-entries/<waste_id>", methods=["PATCH"])
@require_auth(roles={"Nurse"})
def patch_waste(order_id, waste_id):
    # Ensure order exists first (left-to-right resource validation)
    order_svc.get_order(order_id)
    body = get_json_body()
    w = waste_svc.update_waste(order_id, waste_id, g.user_id, body)
    return success(public(w))


@bp.route("/orders/<order_id>/waste-entries", methods=["GET"])
@require_auth(roles={"Nurse", "PlatformAdmin", "ComplianceOfficer"})
def list_waste(order_id):
    o = order_svc.get_order(order_id)
    if g.user_role == "Nurse":
        # only nurse assigned to this order may list
        sr = None
        for r in db.service_records.values():
            if r.get("order_id") == order_id:
                sr = r
                break
        # Or via accepted dispatch
        accepted = None
        for d in db.dispatches.values():
            if d.get("order_id") == order_id and d.get("status") == "ACCEPTED":
                accepted = d
                break
        is_assigned = (sr and sr.get("nurse_id") == g.user_id) or (accepted and accepted.get("nurse_id") == g.user_id)
        if not is_assigned:
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your order")
    limit, offset = get_pagination()
    rows, total = waste_svc.list_waste_for_order(order_id, limit, offset)
    return success_list([public(r) for r in rows], limit, offset, total)


# ----- Settlement read ----- #
@bp.route("/orders/<order_id>/settlement", methods=["GET"])
@require_auth(roles={"Patient", "PlatformAdmin", "ComplianceOfficer"})
def get_settlement(order_id):
    o = order_svc.get_order(order_id)
    if g.user_role == "Patient" and o.get("patient_id") != g.user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your order")
    s = settle_svc.get_settlement_for_order(order_id)
    if s is None:
        raise err("ERR_INVALID_STATE", "no settlement for this order")
    return success(public(s))
