from flask import Blueprint, request

import store
from auth import ALL_ROLES, NON_BORROWER_ROLES, authenticate, authorize
from errors import (
    ERR_APPLICATION_NOT_COMPLETE,
    ERR_APPLICATION_NOT_FOUND,
    ERR_EVALUATION_NOT_FOUND,
    ERR_STALE_APPLICATION_VERSION,
    raise_err,
)
from services import evaluation_out, run_evaluation, step_out
from util import body_json, get_or_404, list_response, req_int, success_object

bp = Blueprint("evaluations", __name__)


@bp.route("/applications/<rid>/evaluations", methods=["POST"])
def create_evaluation(rid):
    uid, role = authenticate()
    authorize(role, ["Underwriter"])
    body = body_json()
    expected_application_version = req_int(body, "expected_application_version")

    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")

    # OCC (priority 6)
    if expected_application_version != app["version"]:
        raise_err(ERR_STALE_APPLICATION_VERSION,
                  "Application version has advanced")

    # state (priority 7)
    if app["status"] != "COMPLETE_PACKAGE":
        raise_err(ERR_APPLICATION_NOT_COMPLETE,
                  "Application must be COMPLETE_PACKAGE to evaluate")

    ev = run_evaluation(app, uid)
    return success_object(evaluation_out(ev), 201)


@bp.route("/evaluations/<rid>", methods=["GET"])
def get_evaluation(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.evaluations, rid, ERR_EVALUATION_NOT_FOUND, "WaterfallEvaluation")
    return success_object(evaluation_out(rec))


@bp.route("/evaluations", methods=["GET"])
def list_evaluations():
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    records = list(store.evaluations.values())
    application_id = request.args.get("application_id")
    selected_program_id = request.args.get("selected_program_id")
    if application_id is not None:
        records = [r for r in records if r["application_id"] == application_id]
    if selected_program_id is not None:
        records = [r for r in records if r.get("selected_program_id") == selected_program_id]
    return list_response(records, evaluation_out)


@bp.route("/applications/<rid>/evaluations", methods=["GET"])
def list_application_evaluations(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    records = [e for e in store.evaluations.values() if e["application_id"] == app["id"]]
    return list_response(records, evaluation_out)


@bp.route("/evaluations/<rid>/steps", methods=["GET"])
def list_evaluation_steps(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ev = get_or_404(store.evaluations, rid, ERR_EVALUATION_NOT_FOUND, "WaterfallEvaluation")
    records = [s for s in store.steps.values() if s["evaluation_id"] == ev["id"]]
    return list_response(records, step_out)
