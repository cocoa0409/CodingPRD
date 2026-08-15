"""Ration endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_RATION_NOT_FOUND, ERR_INVALID_REQUEST, raise_err
from serializers import ration_out, ration_assignment_out, feed_call_out
from util import body_json, get_or_404, list_response, new_record, \
    req_str, req_int, success_object

bp = Blueprint("rations", __name__)


@bp.route("/feedlot/rations", methods=["POST"])
def create_ration():
    _, role = authenticate()
    authorize(role, ["FeedManager"])
    body = body_json()
    ration_name = req_str(body, "ration_name")
    step_level = req_int(body, "step_level")
    cost_per_ton_cents = req_int(body, "cost_per_ton_cents")

    if step_level < 1:
        raise_err(ERR_INVALID_REQUEST, "step_level must be >= 1")
    if cost_per_ton_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "cost_per_ton_cents must be > 0")

    rec = new_record()
    rec.update({
        "ration_name": ration_name,
        "step_level": step_level,
        "cost_per_ton_cents": cost_per_ton_cents,
    })
    store.rations[rec["id"]] = rec
    return success_object(ration_out(rec), 201)


@bp.route("/feedlot/rations", methods=["GET"])
def list_rations():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(list(store.rations.values()), ration_out)


@bp.route("/feedlot/rations/<ration_id>", methods=["GET"])
def get_ration(ration_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.rations, ration_id, ERR_RATION_NOT_FOUND, "Ration")
    return success_object(ration_out(rec))


@bp.route("/feedlot/rations/<ration_id>/ration-assignments", methods=["GET"])
def list_ration_assignments(ration_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.rations, ration_id, ERR_RATION_NOT_FOUND, "Ration")
    ras = [ra for ra in store.ration_assignments.values() if ra["ration_id"] == ration_id]
    return list_response(ras, ration_assignment_out)


@bp.route("/feedlot/rations/<ration_id>/feed-calls", methods=["GET"])
def list_ration_feed_calls(ration_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.rations, ration_id, ERR_RATION_NOT_FOUND, "Ration")
    calls = [fc for fc in store.feed_calls.values() if fc["ration_id"] == ration_id]
    return list_response(calls, feed_call_out)
