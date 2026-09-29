"""Valuation runs (PRD section 3.8)."""
from flask import Blueprint, request

from authz import (FIDUCIARY, READ_ROLES_NO_PLATFORM, authenticate,
                   require_action_role, require_fiduciary_estate, require_role)
from clock import CLOCK, parse_date
from db import DB
from errors import ApiError
from response import public, single
from routes.common import paged
from services import lookup, valuation
from services import estate as estate_svc
from validation import parse_body, v_enum, v_int, v_text, validate

bp = Blueprint("valuations", __name__)

BASES = ("DATE_OF_DEATH", "ALTERNATE")
TOTAL_SHARE_BP = 10000
RUN_ACTION_OWNERS = {"FINALIZE": FIDUCIARY}


@bp.route("/estates/<estate_id>/valuation-runs", methods=["POST"])
def create_run(estate_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request), required={
        "basis": v_enum(BASES),
        "expected_estate_version": v_int(0),
    })

    estate = lookup.get_estate(estate_id)
    require_fiduciary_estate(user_id, role, estate_id)
    if body["expected_estate_version"] != estate["version"]:
        raise ApiError("ERR_STALE_ESTATE_VERSION")
    estate_svc.require_open(estate)

    if estate_svc.finalized_run(estate_id) is not None:
        raise ApiError("ERR_VALUATION_ALREADY_FINALIZED")

    basis = body["basis"]
    if basis == "ALTERNATE":
        if CLOCK.today() < parse_date(estate["alternate_valuation_date"]):
            raise ApiError("ERR_ALTERNATE_DATE_NOT_REACHED")

    total_bp = sum(d["share_bp"] for d in lookup.estate_designations(estate_id))
    if total_bp != TOTAL_SHARE_BP:
        raise ApiError("ERR_SHARE_TOTAL_INVALID")

    run = valuation.execute_run(estate, basis)
    return single(public(run), 201)


@bp.route("/valuation-runs/<run_id>", methods=["GET"])
def read_run(run_id):
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    return single(public(lookup.get_run(run_id)), 200)


@bp.route("/valuation-runs", methods=["GET"])
def list_runs():
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    return paged(DB.runs.values(), request.args, {
        "estate_id": "estate_id",
        "basis": "basis",
        "status": "status",
    })


@bp.route("/valuation-runs/<run_id>/transitions", methods=["POST"])
def run_transition(run_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request),
                    required={"action": v_enum(("FINALIZE",))},
                    optional={"finalization_note": v_text()})
    action = body["action"]
    require_action_role(role, action, RUN_ACTION_OWNERS)

    run = lookup.get_run(run_id)
    estate = lookup.get_estate(run["estate_id"])
    require_fiduciary_estate(user_id, role, run["estate_id"])
    estate_svc.require_open(estate)

    if run["status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_RUN_STATE")

    valuation.finalize_run(run, estate, body.get("finalization_note"))
    return single(public(run), 200)
