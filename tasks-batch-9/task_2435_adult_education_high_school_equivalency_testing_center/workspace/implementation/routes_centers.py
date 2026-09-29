"""Testing centres, their rooms and their proctors."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from core import (
    auth,
    body,
    by_created,
    clock,
    created,
    deny_scope,
    effective_proctor_status,
    find_center,
    find_proctor,
    find_room,
    fmt_clock,
    hours_out,
    new_record,
    ok,
    opt_dec,
    opt_int,
    pagination,
    paginate,
    parse_dt,
    proctor_pub,
    pub,
    req_dt,
    req_enum,
    req_int,
    req_str,
    store,
    touch,
)
from errors import ApiError

bp = Blueprint("centers", __name__)

AUTH_DECISIONS = ("GRANT_PROVISIONAL", "GRANT_FULL", "WITHDRAW")
CERT_DECISIONS = ("CERTIFY", "RENEW", "REVOKE")
CENTER_ACTIVE_STATES = ("PROVISIONAL", "FULL_AUTHORIZED")


def guard_center_authorized(center):
    """Band 12: the centre owning the addressed room or session must be live."""
    if center is None:
        raise ApiError("ERR_TESTING_CENTER_NOT_FOUND")
    if center["authorization_status"] == "SUSPENDED":
        raise ApiError("ERR_CENTER_SUSPENDED")
    if center["authorization_status"] not in CENTER_ACTIVE_STATES:
        raise ApiError("ERR_CENTER_NOT_AUTHORIZED")


# --------------------------------------------------------------------------
# testing centres
# --------------------------------------------------------------------------

@bp.post("/testing-centers")
def register_center():
    auth("StateAuthority")
    data = body()
    name = req_str(data, "name")
    state_code = req_str(data, "state_code")
    if len(state_code) != 2 or not state_code.isupper() or not state_code.isalpha():
        raise ApiError("ERR_INVALID_REQUEST")
    center = new_record(store.centers, {
        "name": name,
        "state_code": state_code,
        "authorization_status": "APPLIED",
        "allowed_subtests": [],
        "max_sessions_per_week": 0,
        "authorized_at": None,
        "suspended_reason": None,
    })
    return created(pub(center))


@bp.post("/testing-centers/<center_id>/authorization-decision")
def authorization_decision(center_id):
    auth("StateAuthority")
    center = find_center(center_id)
    data = body()
    decision = req_enum(data, "decision", AUTH_DECISIONS)
    status = center["authorization_status"]

    if decision == "GRANT_PROVISIONAL":
        if status != "APPLIED":
            raise ApiError("ERR_CENTER_DECISION_NOT_ALLOWED")
        center["authorization_status"] = "PROVISIONAL"
        center["allowed_subtests"] = ["MATH", "RLA"]
        center["max_sessions_per_week"] = 2
        center["authorized_at"] = fmt_clock(clock())
    elif decision == "GRANT_FULL":
        if status not in ("APPLIED", "PROVISIONAL"):
            raise ApiError("ERR_CENTER_DECISION_NOT_ALLOWED")
        center["authorization_status"] = "FULL_AUTHORIZED"
        center["allowed_subtests"] = list(calc.SUBTESTS)
        center["max_sessions_per_week"] = 20
        if center["authorized_at"] is None:
            center["authorized_at"] = fmt_clock(clock())
    else:
        if status != "APPLIED":
            raise ApiError("ERR_CENTER_DECISION_NOT_ALLOWED")
        center["authorization_status"] = "WITHDRAWN"
        center["allowed_subtests"] = []

    touch(center)
    return ok(pub(center))


@bp.post("/testing-centers/<center_id>/suspend")
def suspend_center(center_id):
    auth("StateAuthority")
    center = find_center(center_id)
    data = body()
    reason = req_str(data, "suspended_reason")
    if center["authorization_status"] not in CENTER_ACTIVE_STATES:
        raise ApiError("ERR_CENTER_DECISION_NOT_ALLOWED")
    cascades.suspend_center(center, reason)
    return ok(pub(center))


@bp.get("/testing-centers/<center_id>")
def read_center(center_id):
    role, user_id = auth("StateAuthority", "ProgramCoordinator",
                         "CenterAdministrator", "Registrar")
    center = find_center(center_id)
    if role == "CenterAdministrator" and user_id != center["id"]:
        deny_scope()
    return ok(pub(center))


@bp.get("/testing-centers")
def list_centers():
    auth("StateAuthority", "ProgramCoordinator", "Registrar")
    limit, offset = pagination()
    rows = list(store.centers.values())
    for key in ("authorization_status", "state_code"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# testing rooms
# --------------------------------------------------------------------------

@bp.post("/testing-centers/<center_id>/rooms")
def add_room(center_id):
    role, user_id = auth("CenterAdministrator", "StateAuthority")
    center = find_center(center_id)
    if role == "CenterAdministrator" and user_id != center["id"]:
        deny_scope()
    data = body()
    room_code = req_str(data, "room_code")
    seat_capacity = req_int(data, "seat_capacity", minimum=1, maximum=200)
    buffer_minutes = opt_int(data, "turnaround_buffer_minutes", default=45,
                             minimum=0, maximum=120)
    for existing in store.rooms.values():
        if existing["testing_center_id"] == center["id"] and existing["room_code"] == room_code:
            raise ApiError("ERR_INVALID_REQUEST")

    guard_center_authorized(center)

    room = new_record(store.rooms, {
        "testing_center_id": center["id"],
        "room_code": room_code,
        "seat_capacity": seat_capacity,
        "turnaround_buffer_minutes": buffer_minutes,
        "status": "ACTIVE",
        "service_note": None,
    })
    touch(center)
    return created(pub(room))


@bp.post("/testing-rooms/<room_id>/out-of-service")
def room_out_of_service(room_id):
    role, user_id = auth("CenterAdministrator", "StateAuthority")
    room = find_room(room_id)
    if role == "CenterAdministrator" and user_id != room["testing_center_id"]:
        deny_scope()
    data = body()
    note = req_str(data, "service_note")
    if room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_OUT_OF_SERVICE")
    room["status"] = "OUT_OF_SERVICE"
    room["service_note"] = note
    touch(room)
    return ok(pub(room))


@bp.get("/testing-rooms/<room_id>")
def read_room(room_id):
    role, user_id = auth("CenterAdministrator", "StateAuthority", "ProgramCoordinator")
    room = find_room(room_id)
    if role == "CenterAdministrator" and user_id != room["testing_center_id"]:
        deny_scope()
    return ok(pub(room))


@bp.get("/testing-rooms")
def list_rooms():
    auth("CenterAdministrator", "StateAuthority", "ProgramCoordinator")
    limit, offset = pagination()
    rows = list(store.rooms.values())
    for key in ("testing_center_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# proctors
# --------------------------------------------------------------------------

@bp.post("/testing-centers/<center_id>/proctors")
def register_proctor(center_id):
    role, user_id = auth("CenterAdministrator", "StateAuthority")
    center = find_center(center_id)
    if role == "CenterAdministrator" and user_id != center["id"]:
        deny_scope()
    data = body()
    full_name = req_str(data, "full_name")
    cap = opt_dec(data, "daily_hour_cap", default=Decimal("8.00"),
                  exclusive_min=0, maximum=12)
    proctor = new_record(store.proctors, {
        "testing_center_id": center["id"],
        "full_name": full_name,
        "certification_status": "PENDING",
        "certification_expires_at": None,
        "daily_hour_cap": hours_out(cap),
        "assigned_session_count": 0,
        "_certification_expires_at": None,
        "_daily_hour_cap": cap,
    })
    return created(pub(proctor))


@bp.post("/proctors/<proctor_id>/certification-decision")
def certification_decision(proctor_id):
    auth("StateAuthority")
    proctor = find_proctor(proctor_id)
    data = body()
    decision = req_enum(data, "decision", CERT_DECISIONS)
    expires_raw = None
    expires_dt = None
    if decision in ("CERTIFY", "RENEW"):
        expires_raw, expires_dt = req_dt(data, "certification_expires_at")
        if expires_dt <= clock():
            raise ApiError("ERR_INVALID_REQUEST")

    status = effective_proctor_status(proctor)

    if decision == "CERTIFY":
        if status != "PENDING":
            raise ApiError("ERR_PROCTOR_DECISION_NOT_ALLOWED")
        proctor["certification_status"] = "CERTIFIED"
        proctor["certification_expires_at"] = expires_raw
        proctor["_certification_expires_at"] = expires_dt
    elif decision == "RENEW":
        if status != "LAPSED":
            raise ApiError("ERR_PROCTOR_DECISION_NOT_ALLOWED")
        proctor["certification_status"] = "CERTIFIED"
        proctor["certification_expires_at"] = expires_raw
        proctor["_certification_expires_at"] = expires_dt
    else:
        if status not in ("PENDING", "CERTIFIED", "LAPSED"):
            raise ApiError("ERR_PROCTOR_DECISION_NOT_ALLOWED")
        cascades.revoke_proctor(proctor)
        return ok(proctor_pub(proctor))

    touch(proctor)
    return ok(proctor_pub(proctor))


@bp.get("/proctors/<proctor_id>")
def read_proctor(proctor_id):
    role, user_id = auth("CenterAdministrator", "StateAuthority",
                         "ProgramCoordinator", "Proctor")
    proctor = find_proctor(proctor_id)
    if role == "CenterAdministrator" and user_id != proctor["testing_center_id"]:
        deny_scope()
    if role == "Proctor" and user_id != proctor["id"]:
        deny_scope()
    return ok(proctor_pub(proctor))


@bp.get("/proctors")
def list_proctors():
    auth("CenterAdministrator", "StateAuthority", "ProgramCoordinator")
    limit, offset = pagination()
    rows = list(store.proctors.values())
    center_id = request.args.get("testing_center_id")
    if center_id is not None:
        rows = [r for r in rows if r["testing_center_id"] == center_id]
    wanted = request.args.get("certification_status")
    if wanted is not None:
        rows = [r for r in rows if effective_proctor_status(r) == wanted]
    return paginate(by_created(rows), limit, offset, serializer=proctor_pub)
