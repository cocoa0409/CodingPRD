"""PriorAuthorization routes (PRD §3.3)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response
from services import workflow

bp = Blueprint("prior_authorizations", __name__)

READ_ROLES = ["AuthSpecialist", "Pharmacist", "MedicalDirector"]


@bp.route("/prior-authorizations", methods=["POST"])
def create_auth():
    require(["AuthSpecialist"])
    body = helpers.get_body()
    # existence (3) before other body validity (4) per PRD §2.8
    order_id = helpers.as_str(body, "order_id")
    if order_id not in db.infusion_orders:
        raise errors.not_found("Infusion order not found")
    requested_units = helpers.as_int(body, "requested_units")
    if requested_units <= 0:
        raise errors.invalid_request("requested_units must be > 0")

    order = db.infusion_orders[order_id]
    patient = db.patients.get(order["patient_id"])
    payer_plan_id = patient["payer_plan_id"] if patient else None

    auth = stamp_create({
        "order_id": order_id,
        "payer_plan_id": payer_plan_id,
        "requested_units": requested_units,
        "approved_units": 0,
        "status": "SUBMITTED",
    })
    db.prior_authorizations[auth["id"]] = auth
    return object_response(auth, 201)


@bp.route("/prior-authorizations/<id>", methods=["GET"])
def get_auth(id):
    require(READ_ROLES)
    auth = db.prior_authorizations.get(id)
    if auth is None:
        raise errors.not_found("Prior authorization not found")
    return object_response(auth, 200)


@bp.route("/prior-authorizations", methods=["GET"])
def list_auths():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.prior_authorizations.values())
    order_id = request.args.get("order_id")
    payer_plan_id = request.args.get("payer_plan_id")
    if order_id is not None:
        items = [a for a in items if a["order_id"] == order_id]
    if payer_plan_id is not None:
        items = [a for a in items if a["payer_plan_id"] == payer_plan_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/prior-authorizations/<id>/approve", methods=["POST"])
def approve_auth(id):
    require(["AuthSpecialist"])
    auth = db.prior_authorizations.get(id)
    if auth is None:
        raise errors.not_found("Prior authorization not found")
    body = helpers.get_body()
    approved_units = helpers.as_int(body, "approved_units")
    if auth["status"] != "SUBMITTED":
        raise errors.invalid_state("Authorization is not in SUBMITTED state")
    order = db.infusion_orders.get(auth["order_id"])
    if order is None or order["status"] != "PENDING_AUTH":
        raise errors.invalid_state("Order is not in PENDING_AUTH state")

    auth["approved_units"] = approved_units
    auth["status"] = "APPROVED"
    touch(auth)
    # cross-entity cascade: order PENDING_AUTH -> RELEASED
    order["status"] = "RELEASED"
    touch(order)
    return object_response(auth, 200)


@bp.route("/prior-authorizations/<id>/deny", methods=["POST"])
def deny_auth(id):
    require(["AuthSpecialist"])
    auth = db.prior_authorizations.get(id)
    if auth is None:
        raise errors.not_found("Prior authorization not found")
    if auth["status"] != "SUBMITTED":
        raise errors.invalid_state("Authorization is not in SUBMITTED state")

    auth["status"] = "DENIED"
    touch(auth)
    # cross-entity cascade: order PENDING_AUTH -> DISCONTINUED, kits CANCELLED
    order = db.infusion_orders.get(auth["order_id"])
    if order is not None and order["status"] == "PENDING_AUTH":
        order["status"] = "DISCONTINUED"
        order["hold_reason"] = None
        touch(order)
        workflow.cancel_kits_for_order(order)
    return object_response(auth, 200)
