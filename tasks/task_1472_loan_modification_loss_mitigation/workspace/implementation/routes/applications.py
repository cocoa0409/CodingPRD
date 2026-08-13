from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize, check_borrower_ownership
from errors import ERR_APPLICATION_NOT_FOUND, ERR_APPLICATION_STATE_INVALID, raise_err
from services import (
    application_out,
    loan_of_application,
    notice_out,
    withdraw_application,
)
from util import bump, get_or_404, list_response, success_object

bp = Blueprint("applications", __name__)

WITHDRAWABLE_STATES = {
    "SUBMITTED", "ACKNOWLEDGED", "COMPLETE_PACKAGE",
    "EVALUATED_OFFER", "EVALUATED_DENIAL", "APPEAL_REVIEW",
}


@bp.route("/applications/<rid>", methods=["GET"])
def get_application(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    return success_object(application_out(rec))


@bp.route("/applications", methods=["GET"])
def list_applications():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.applications.values())
    loan_id = request.args.get("loan_id")
    status = request.args.get("status")
    active_evaluation_id = request.args.get("active_evaluation_id")
    superseded_by = request.args.get("superseded_by_application_id")
    if loan_id is not None:
        records = [r for r in records if r["loan_id"] == loan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if active_evaluation_id is not None:
        records = [r for r in records if r.get("active_evaluation_id") == active_evaluation_id]
    if superseded_by is not None:
        records = [r for r in records if r.get("superseded_by_application_id") == superseded_by]
    return list_response(records, application_out)


@bp.route("/applications/<rid>/acknowledge", methods=["POST"])
def acknowledge_application(rid):
    _, role = authenticate()
    authorize(role, ["LossMitAgent"])
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    if app["status"] != "SUBMITTED":
        raise_err(ERR_APPLICATION_STATE_INVALID,
                  "Application must be SUBMITTED to acknowledge")
    app["status"] = "ACKNOWLEDGED"
    app["acknowledged_at"] = clock.now()
    bump(app)
    return success_object(application_out(app))


@bp.route("/applications/<rid>/withdraw", methods=["POST"])
def withdraw_application_route(rid):
    uid, role = authenticate()
    authorize(role, ["Borrower"])
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    check_borrower_ownership(uid, loan_of_application(app))
    if app["status"] not in WITHDRAWABLE_STATES:
        raise_err(ERR_APPLICATION_STATE_INVALID,
                  "Application in %s cannot be withdrawn" % app["status"])
    withdraw_application(app)
    return success_object(application_out(app))


@bp.route("/applications/<rid>/denial-notices", methods=["GET"])
def list_application_denial_notices(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    records = [n for n in store.notices.values() if n["application_id"] == app["id"]]
    return list_response(records, notice_out)
