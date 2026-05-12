"""Courier routes."""

from flask import Blueprint, g, request

from db import LOCK
from middleware import require_roles
from response import success_object
from services.courier import (
    blacklist as svc_blacklist,
    create_courier,
    get_courier,
    reinstate as svc_reinstate,
    restrict as svc_restrict,
    serialize_courier,
    serialize_rating,
)


bp = Blueprint("couriers", __name__)


@bp.route("/couriers", methods=["POST"])
@require_roles("OperationsAdmin")
def post_courier():
    with LOCK:
        c = create_courier(request.get_json(silent=True) or {})
        return success_object(serialize_courier(c), 201)


@bp.route("/couriers/<courier_id>", methods=["GET"])
@require_roles("OperationsAdmin", "Courier")
def get_one_courier(courier_id):
    with LOCK:
        # When role=Courier, ownership: caller must be the same id.
        if g.role == "Courier" and g.user_id != courier_id:
            from errors import forbidden
            raise forbidden("Couriers can only read their own record")
        c = get_courier(courier_id)
        return success_object(serialize_courier(c))


@bp.route("/couriers/<courier_id>/rating", methods=["GET"])
@require_roles("OperationsAdmin", "Courier")
def get_rating(courier_id):
    with LOCK:
        if g.role == "Courier" and g.user_id != courier_id:
            from errors import forbidden
            raise forbidden("Couriers can only read their own rating")
        get_courier(courier_id)
        return success_object(serialize_rating(courier_id))


@bp.route("/couriers/<courier_id>/restrict", methods=["POST"])
@require_roles("OperationsAdmin")
def post_restrict(courier_id):
    with LOCK:
        c = svc_restrict(courier_id, request.get_json(silent=True) or {}, "OperationsAdmin", g.user_id)
        return success_object(serialize_courier(c))


@bp.route("/couriers/<courier_id>/blacklist", methods=["POST"])
@require_roles("OperationsAdmin")
def post_blacklist(courier_id):
    with LOCK:
        c = svc_blacklist(courier_id, request.get_json(silent=True) or {}, "OperationsAdmin", g.user_id)
        return success_object(serialize_courier(c))


@bp.route("/couriers/<courier_id>/reinstate", methods=["POST"])
@require_roles("OperationsAdmin")
def post_reinstate(courier_id):
    with LOCK:
        c = svc_reinstate(courier_id, "OperationsAdmin", g.user_id)
        return success_object(serialize_courier(c))
