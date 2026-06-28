"""Financial-aid awards and adjudication. PRD §3.7."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, recompute, calc
from services.store import base_fields, require, touch, paginate, guardian_owns_camper

bp = Blueprint("financial_aid", __name__)

AID_KINDS = {"NEED_GRANT", "MERIT_SCHOLARSHIP"}


def _application_owner_camper(application):
    return db.campers.get(application["camper_id"])


@bp.route("/financial-aid", methods=["POST"])
def request_aid():
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    body = get_json_body()

    if "application_id" not in body or not isinstance(body.get("application_id"), str):
        raise validate.bad_request("application_id is required.")
    application = db.applications.get(body["application_id"])
    if application is None:
        # FK target must resolve (ERR_REFERENTIAL_MISMATCH, PRD §3.7).
        raise ApiError(errors.ERR_REFERENTIAL_MISMATCH, 409, "Application does not resolve.")
    camper = _application_owner_camper(application)
    if camper is not None:
        guardian_owns_camper(uid, role, camper)

    kind = validate.require_enum(body, "kind", AID_KINDS)
    amount = validate.require_positive_int(body, "amount_cents")

    a = base_fields()
    a.update({
        "application_id": application["id"],
        "kind": kind,
        "amount_cents": amount,
        "status": "REQUESTED",
    })
    db.financial_aid_awards[a["id"]] = a

    # Application balances are derived live at serialize time (PRD §3.5); a new
    # REQUESTED award is immediately reflected by the optimistic estimated
    # balance with no application mutation required (the scaffold's POST
    # /financial-aid side effects do not bump the application version).
    return response.success(serialize.financial_aid_award(a), 201)


@bp.route("/financial-aid", methods=["GET"])
def list_aid():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    limit, offset = parse_pagination()

    app_f = request.args.get("application_id")
    status_f = request.args.get("status")

    items = list(db.financial_aid_awards.values())
    if role == "Guardian":
        owned_apps = set()
        owned_campers = {c["id"] for c in db.campers.values() if c["guardian_user_id"] == uid}
        for ap in db.applications.values():
            if ap["camper_id"] in owned_campers:
                owned_apps.add(ap["id"])
        items = [a for a in items if a["application_id"] in owned_apps]
    if app_f is not None:
        items = [a for a in items if a["application_id"] == app_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.financial_aid_award(a) for a in page], limit, offset, total)


@bp.route("/financial-aid/<aid>", methods=["GET"])
def get_aid(aid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    a = require(db.financial_aid_awards, aid)
    if role == "Guardian":
        application = db.applications.get(a["application_id"])
        if application is not None:
            camper = _application_owner_camper(application)
            if camper is not None:
                guardian_owns_camper(uid, role, camper)
    return response.success(serialize.financial_aid_award(a), 200)


@bp.route("/financial-aid/<aid>/approve", methods=["POST"])
def approve_aid(aid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    a = require(db.financial_aid_awards, aid)
    body = get_json_body()

    application = db.applications.get(a["application_id"])
    if application is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Application not found.")

    # State: award must be REQUESTED.
    if a["status"] != "REQUESTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Award is not REQUESTED.")
    # Application must not be WITHDRAWN (ERR_INVALID_STATE).
    if application["enroll_status"] == "WITHDRAWN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is withdrawn.")

    # Fiscal ceiling (p11): amount + existing approved aid <= list_tuition.
    existing_approved = calc.compute_aid_total(application)
    if existing_approved + a["amount_cents"] > application["list_tuition_cents"]:
        raise ApiError(errors.ERR_AID_EXCEEDS_TUITION, 422, "Aid would exceed list tuition.")

    # OCC (p13): expected_application_version must match.
    if "expected_application_version" not in body or body.get("expected_application_version") is None:
        raise validate.bad_request("expected_application_version is required.")
    expected = body.get("expected_application_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise validate.bad_request("expected_application_version must be an integer.")
    if expected != application["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "Application version is stale.")

    a["status"] = "APPROVED"
    touch(a)
    recompute.recompute_application_money(application)
    touch(application)  # increments Application.version by 1

    return response.success(serialize.financial_aid_award(a), 200)


@bp.route("/financial-aid/<aid>/deny", methods=["POST"])
def deny_aid(aid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    a = require(db.financial_aid_awards, aid)

    if a["status"] != "REQUESTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Award is not REQUESTED.")

    a["status"] = "DENIED"
    touch(a)
    return response.success(serialize.financial_aid_award(a), 200)


@bp.route("/financial-aid/<aid>/revoke", methods=["POST"])
def revoke_aid(aid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    a = require(db.financial_aid_awards, aid)

    if a["status"] != "APPROVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Award is not APPROVED.")

    application = db.applications.get(a["application_id"])
    if application is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Application not found.")

    # Permitted only when payment axis is not PAID_IN_FULL (ERR_INVALID_STATE).
    if application["payment_status"] == "PAID_IN_FULL":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Cannot revoke aid on a paid-in-full application.")

    a["status"] = "REVOKED"
    touch(a)
    recompute.recompute_application_money(application)
    # Per PRD §3.7 the payment axis would revert PAID_IN_FULL -> BALANCE_DUE if
    # the resulting balance is now positive; revocation is only permitted when
    # the axis is NOT PAID_IN_FULL (checked above), so this branch is reached
    # only when the gate is already satisfied and never changes a paid-in-full
    # application. We retain the spec's intent without mutating other axes.
    touch(application)

    return response.success(serialize.financial_aid_award(a), 200)
