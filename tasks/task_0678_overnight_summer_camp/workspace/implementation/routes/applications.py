"""Applications: intake, deposits, enrollment, withdrawal, balance. PRD §3.4-§3.6."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, recompute, intake, calc
from services.store import base_fields, require, touch, paginate, guardian_owns_camper
from routes.cabins import _gender_band_admits

bp = Blueprint("applications", __name__)


def _camper_of(application):
    return db.campers.get(application["camper_id"])


def _own_application(uid, role, application):
    camper = _camper_of(application)
    if camper is not None:
        guardian_owns_camper(uid, role, camper)


@bp.route("/applications", methods=["POST"])
def create_application():
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    body = get_json_body()

    if "camper_id" not in body or not isinstance(body.get("camper_id"), str):
        raise validate.bad_request("camper_id is required.")
    if "session_id" not in body or not isinstance(body.get("session_id"), str):
        raise validate.bad_request("session_id is required.")

    camper = db.campers.get(body["camper_id"])
    if camper is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Camper not found.")
    guardian_owns_camper(uid, role, camper)
    session = db.sessions.get(body["session_id"])
    if session is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Session not found.")

    a = base_fields()
    a.update({
        "camper_id": camper["id"],
        "session_id": session["id"],
        "cabin_id": None,
        "enroll_status": "DRAFT",
        "payment_status": "UNBILLED",
        "submitted_at_dt": None,
        "offer_expires_at_dt": None,
        "list_tuition_cents": 0,
        "aid_cents": 0,
        "estimated_balance_cents": 0,
        "settled_balance_cents": 0,
        "deposit_paid_cents": 0,
    })
    db.applications[a["id"]] = a
    return response.success(serialize.application(a), 201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    limit, offset = parse_pagination()

    camper_f = request.args.get("camper_id")
    session_f = request.args.get("session_id")
    cabin_f = request.args.get("cabin_id")
    status_f = request.args.get("enroll_status")

    items = list(db.applications.values())
    if role == "Guardian":
        owned = {c["id"] for c in db.campers.values() if c["guardian_user_id"] == uid}
        items = [a for a in items if a["camper_id"] in owned]
    if camper_f is not None:
        items = [a for a in items if a["camper_id"] == camper_f]
    if session_f is not None:
        items = [a for a in items if a["session_id"] == session_f]
    if cabin_f is not None:
        items = [a for a in items if a["cabin_id"] == cabin_f]
    if status_f is not None:
        items = [a for a in items if a["enroll_status"] == status_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.application(a) for a in page], limit, offset, total)


@bp.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    a = require(db.applications, aid)
    _own_application(uid, role, a)
    return response.success(serialize.application(a), 200)


@bp.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    a = require(db.applications, aid)
    _own_application(uid, role, a)

    # State: must be DRAFT.
    if a["enroll_status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is not in DRAFT.")

    session = db.sessions[a["session_id"]]
    camp = db.camps[session["camp_id"]]
    camper = _camper_of(a)

    # ERR_ENROLLMENT_CLOSED evaluated as a state check within the transition.
    if session["status"] != "ENROLLING" or not session["enrollment_open"]:
        raise ApiError(errors.ERR_ENROLLMENT_CLOSED, 409, "Session is not open for enrollment.")
    # Health form at least submitted (PENDING or CLEARED) (ERR_HEALTH_FORM_MISSING, p7-ish).
    if camper["health_status"] not in ("PENDING", "CLEARED"):
        raise ApiError(errors.ERR_HEALTH_FORM_MISSING, 422, "Camper has no submitted health form.")
    # Eligible cabin: gender admitted AND age in band for at least one cabin (p8).
    eligible = any(
        _gender_band_admits(c["gender_band"], camper["gender"])
        and c["min_age"] <= camper["age"] <= c["max_age"]
        for c in db.cabins.values() if c["session_id"] == session["id"]
    )
    if not eligible:
        raise ApiError(errors.ERR_NO_ELIGIBLE_CABIN, 422, "No cabin matches the camper's gender and age.")

    # Side effects: submitted_at, list_tuition snapshot, then route.
    a["submitted_at_dt"] = db.now()
    a["list_tuition_cents"] = calc.compute_list_tuition(session, camper)
    recompute.recompute_application_money(a)

    committed = recompute.session_committed_count(session["id"])
    if committed < session["capacity"]:
        intake.make_offer(a, camp)
    else:
        intake.make_waitlist(a)

    return response.success(serialize.application(a), 200)


@bp.route("/applications/<aid>/pay-deposit", methods=["POST"])
def pay_deposit(aid):
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    a = require(db.applications, aid)
    _own_application(uid, role, a)
    body = get_json_body()

    if a["enroll_status"] != "OFFERED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is not OFFERED.")

    session = db.sessions[a["session_id"]]
    camp = db.camps[session["camp_id"]]

    amount = validate.require_int(body, "amount_cents")

    # Fiscal (p11): deposit amount must match the camp's deposit_cents.
    if amount != camp["deposit_cents"]:
        raise ApiError(errors.ERR_DEPOSIT_AMOUNT_MISMATCH, 422, "Deposit amount does not match.")
    # Offer-not-expired (p12): clock <= offer_expires_at.
    exp = a.get("offer_expires_at_dt")
    if exp is not None and db.now() > exp:
        raise ApiError(errors.ERR_OFFER_EXPIRED, 409, "Offer has expired.")

    # Side effects.
    p = base_fields()
    p.update({
        "application_id": a["id"],
        "kind": "DEPOSIT",
        "amount_cents": amount,
        "status": "APPLIED",
    })
    db.payments[p["id"]] = p

    a["deposit_paid_cents"] = camp["deposit_cents"]
    a["enroll_status"] = "DEPOSIT_PAID"
    a["payment_status"] = "DEPOSIT_SETTLED"
    recompute.recompute_application_money(a)
    touch(a)

    return response.success(serialize.application(a), 200)


@bp.route("/applications/<aid>/enroll", methods=["POST"])
def enroll_application(aid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    a = require(db.applications, aid)

    if a["enroll_status"] != "DEPOSIT_PAID":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is not DEPOSIT_PAID.")

    camper = _camper_of(a)
    session = db.sessions[a["session_id"]]

    # Health cleared (p7).
    if camper["health_status"] != "CLEARED":
        raise ApiError(errors.ERR_HEALTH_NOT_CLEARED, 422, "Camper is not health-cleared.")
    # Bunk assigned (ERR_NO_BUNK_ASSIGNED, 409).
    if not a["cabin_id"]:
        raise ApiError(errors.ERR_NO_BUNK_ASSIGNED, 409, "No bunk assigned.")
    # Target cabin staffable after counting this camper (p8). The camper is
    # already counted in occupied_bunks from DEPOSIT_PAID, so is_staffable as
    # currently computed already reflects this camper.
    cabin = db.cabins[a["cabin_id"]]
    recompute.recompute_cabin_is_staffable(cabin)
    if not cabin["is_staffable"]:
        raise ApiError(errors.ERR_CABIN_UNDERSTAFFED, 422, "Cabin is understaffed.")
    # Session posture not UNDERSTAFFED (p8/temporal).
    recompute.recompute_session_posture(session)
    if session["ratio_posture"] == "UNDERSTAFFED":
        raise ApiError(errors.ERR_SESSION_UNDERSTAFFED, 422, "Session is understaffed.")

    # Side effects. payment axis -> BALANCE_DUE if estimated balance > 0 else
    # PAID_IN_FULL (PRD §3.6).
    a["enroll_status"] = "ENROLLED"
    if calc.compute_estimated_balance(a) > 0:
        a["payment_status"] = "BALANCE_DUE"
    else:
        a["payment_status"] = "PAID_IN_FULL"
    touch(a)
    recompute.recompute_session_posture(session, bump_version=True)

    return response.success(serialize.application(a), 200)


@bp.route("/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    a = require(db.applications, aid)
    _own_application(uid, role, a)

    status = a["enroll_status"]
    if status not in ("OFFERED", "DEPOSIT_PAID", "ENROLLED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application cannot be withdrawn from this state.")

    session = db.sessions[a["session_id"]]

    if status == "ENROLLED" and session["status"] == "RUNNING":
        raise ApiError(errors.ERR_SESSION_RUNNING_NO_WITHDRAW, 409,
                       "Cannot withdraw an enrolled application while the session is running.")

    cabin = db.cabins.get(a["cabin_id"]) if a["cabin_id"] else None

    if status == "OFFERED":
        # Simply free the seat (committed_count is derived).
        a["enroll_status"] = "WITHDRAWN"
        a["offer_expires_at_dt"] = None
        touch(a)
        return response.success(serialize.application(a), 200)

    # DEPOSIT_PAID or ENROLLED: reverse payments, refund, free cabin & activities.
    for p in db.payments.values():
        if p["application_id"] == a["id"] and p["status"] == "APPLIED":
            p["status"] = "REVERSED"
            touch(p)
    a["payment_status"] = "REFUND_DUE"

    if cabin is not None:
        cabin["occupied_bunks"] = max(0, cabin["occupied_bunks"] - 1)
        recompute.recompute_cabin_is_staffable(cabin)
        touch(cabin)
    a["cabin_id"] = None

    # Drop all BOOKED activity enrollments, each freeing a seat.
    for e in db.activity_enrollments.values():
        if e["application_id"] == a["id"] and e["status"] == "BOOKED":
            e["status"] = "DROPPED"
            touch(e)
            offering = db.activity_offerings.get(e["offering_id"])
            if offering is not None:
                offering["seats_taken"] = max(0, offering["seats_taken"] - 1)
                touch(offering)

    a["enroll_status"] = "WITHDRAWN"
    a["offer_expires_at_dt"] = None
    recompute.recompute_application_money(a)
    touch(a)

    recompute.recompute_session_posture(session, bump_version=True)
    return response.success(serialize.application(a), 200)


@bp.route("/applications/<aid>/pay-balance", methods=["POST"])
def pay_balance(aid):
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    a = require(db.applications, aid)
    _own_application(uid, role, a)
    body = get_json_body()

    if a["payment_status"] != "BALANCE_DUE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is not BALANCE_DUE.")

    amount = validate.require_positive_int(body, "amount_cents")

    p = base_fields()
    p.update({
        "application_id": a["id"],
        "kind": "BALANCE",
        "amount_cents": amount,
        "status": "APPLIED",
    })
    db.payments[p["id"]] = p

    # payment axis -> PAID_IN_FULL once the settled balance reaches 0 (PRD §3.6).
    if calc.compute_settled_balance(a) == 0:
        a["payment_status"] = "PAID_IN_FULL"
    touch(a)

    return response.success(serialize.application(a), 200)
