"""Terminals: create/list/get, run-ops checkpoint, screening-requirement read."""

from flask import Blueprint, request

import db
import services
from errors import ApiError, ERR_VALIDATION, ERR_NOT_FOUND
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, pagination_params, paginate

bp = Blueprint("terminals", __name__, url_prefix="/port-ops")

ANY_AUTH = ANY


@bp.route("/terminals", methods=["POST"])
def create_terminal():
    authenticate({"PortAuthorityAdmin"})
    body = body_json()
    check_shape(body, {
        "name": {"type": "string", "required": True},
        "max_apron_slots": {"type": "integer", "required": True, "min": 1},
        "taxi_dispatch_capacity_per_window": {"type": "integer", "required": True, "min": 1},
    })
    term = db.new_entity("terminals", {
        "name": body["name"],
        "max_apron_slots": body["max_apron_slots"],
        "taxi_dispatch_capacity_per_window": body["taxi_dispatch_capacity_per_window"],
        "ops_run_index": 0,
    })
    return success_obj(services.serialize_terminal(term), code=201)


@bp.route("/terminals", methods=["GET"])
def list_terminals():
    authenticate(ANY_AUTH)
    limit, offset = pagination_params()
    items = [services.serialize_terminal(t) for t in db.all_of("terminals")]
    page, total, has_more = paginate(items, limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/terminals/<term_id>", methods=["GET"])
def get_terminal(term_id):
    authenticate(ANY_AUTH)
    term = db.get("terminals", term_id)
    if term is None:
        raise ApiError(ERR_NOT_FOUND, 404, "terminal not found")
    return success_obj(services.serialize_terminal(term))


@bp.route("/terminals/<term_id>/run-ops", methods=["POST"])
def run_ops(term_id):
    authenticate({"PortAuthorityAdmin"})
    term = db.get("terminals", term_id)
    if term is None:
        raise ApiError(ERR_NOT_FOUND, 404, "terminal not found")
    services.run_ops_sweep(term)
    return success_obj(services.serialize_terminal(term))


@bp.route("/terminals/<term_id>/screening-requirement", methods=["GET"])
def screening_requirement(term_id):
    authenticate({"PortAuthorityAdmin", "Harbormaster", "TerminalOperator"})
    term = db.get("terminals", term_id)
    if term is None:
        raise ApiError(ERR_NOT_FOUND, 404, "terminal not found")
    port_call_id = request.args.get("port_call_id")
    if port_call_id is None or not str(port_call_id).strip():
        raise ApiError(ERR_VALIDATION, 400, "port_call_id query parameter is required")
    call = db.get("port_calls", port_call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    mode = request.args.get("mode", "PROJECTION")
    if mode not in ("PROJECTION", "ACTUAL"):
        raise ApiError(ERR_VALIDATION, 400, "mode must be PROJECTION or ACTUAL")
    result = services.screening_requirement(term, call, mode)
    return success_obj(result)
