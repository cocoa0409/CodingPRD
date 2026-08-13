"""Workshops and workshop seats."""
from flask import Blueprint, g, request

from auth import authenticate, require_roles, ROLES
from db import db, Rec, stamp_new, bump, now_dt
from errors import (err_not_found, err_forbidden, err_invalid_state,
                    err_stale_version, conflict)
from services import (ser_workshop, ser_seat, check_accreditation,
                      eligible_active_screening)
from util import (json_body, success_obj, paginate, v_str, v_int, v_datetime)

bp = Blueprint("workshops", __name__)


def _get_workshop(workshop_id):
    w = db.workshops.get(workshop_id)
    if w is None:
        raise err_not_found("Workshop not found")
    return w


def _get_seat(seat_id):
    s = db.seats.get(seat_id)
    if s is None:
        raise err_not_found("Workshop seat not found")
    return s


def _recompute_reserved_count(workshop):
    workshop.reserved_count = sum(
        1 for s in db.seats.values()
        if s.workshop_id == workshop.id and s.status in ("RESERVED", "ATTENDED"))


# --------------------------- Workshops ---------------------------

@bp.post("/naturalization/workshops")
def create_workshop():
    body = json_body()
    title = v_str(body, "title")
    supervisor_id = v_str(body, "supervising_volunteer_id")
    assisting_id = v_str(body, "assisting_volunteer_id", required=False)
    raw_start, dt_start = v_datetime(body, "scheduled_start")
    duration_hours = v_int(body, "duration_hours", minv=1)
    capacity = v_int(body, "capacity", minv=1)
    authenticate()
    require_roles("ProgramAdmin")
    supervisor = db.volunteers.get(supervisor_id)
    if supervisor is None:
        raise err_not_found("Supervising volunteer not found")
    if assisting_id is not None and assisting_id not in db.volunteers:
        raise err_not_found("Assisting volunteer not found")
    check_accreditation(supervisor, "LEGAL")
    w = Rec(title=title, supervising_volunteer_id=supervisor_id,
            assisting_volunteer_id=assisting_id,
            scheduled_start_raw=raw_start, scheduled_start_dt=dt_start,
            duration_hours=duration_hours, capacity=capacity,
            reserved_count=0, status="SCHEDULED")
    stamp_new(w)
    db.workshops[w.id] = w
    return success_obj(ser_workshop(w), 201)


@bp.get("/naturalization/workshops")
def list_workshops():
    authenticate()
    require_roles(*ROLES)
    recs = list(db.workshops.values())
    sup = request.args.get("supervising_volunteer_id")
    if sup is not None:
        recs = [w for w in recs if w.supervising_volunteer_id == sup]
    ast = request.args.get("assisting_volunteer_id")
    if ast is not None:
        recs = [w for w in recs if w.assisting_volunteer_id == ast]
    return paginate(recs, ser_workshop)


@bp.get("/naturalization/workshops/<workshop_id>")
def get_workshop(workshop_id):
    authenticate()
    require_roles(*ROLES)
    return success_obj(ser_workshop(_get_workshop(workshop_id)))


@bp.post("/naturalization/workshops/<workshop_id>/complete")
def complete_workshop(workshop_id):
    json_body()
    authenticate()
    require_roles("Volunteer", "ProgramAdmin")
    w = _get_workshop(workshop_id)
    if g.user_role == "Volunteer" and w.supervising_volunteer_id != g.user_id:
        raise err_forbidden("Only the supervising volunteer may complete the workshop")
    if w.status != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED workshop may be completed")
    supervisor = db.volunteers.get(w.supervising_volunteer_id)
    if supervisor is None:
        raise conflict("ERR_ACCREDITATION_INSUFFICIENT",
                       "Supervising volunteer not found")
    check_accreditation(supervisor, "LEGAL")
    if now_dt() < w.scheduled_start_dt:
        raise conflict("ERR_WORKSHOP_NOT_YET_HELD",
                       "Workshop has not yet been held")
    for seat in db.seats.values():
        if seat.workshop_id == w.id and seat.status == "RESERVED":
            seat.status = "ATTENDED"
            bump(seat)
    if w.assisting_volunteer_id:
        assistant = db.volunteers.get(w.assisting_volunteer_id)
        if assistant is not None:
            assistant.supervised_hours += w.duration_hours
            bump(assistant)
    w.status = "COMPLETED"
    bump(w)
    return success_obj(ser_workshop(w))


@bp.post("/naturalization/workshops/<workshop_id>/reverse-completion")
def reverse_completion(workshop_id):
    json_body()
    authenticate()
    require_roles("ProgramAdmin")
    w = _get_workshop(workshop_id)
    if w.status != "COMPLETED":
        raise err_invalid_state("Only a COMPLETED workshop may be reversed")
    seat_ids = {s.id for s in db.seats.values() if s.workshop_id == w.id}
    for p in db.packets.values():
        if p.workshop_seat_id in seat_ids:
            raise conflict("ERR_COMPLETION_LOCKED",
                           "A packet already references one of this workshop's seats")
    for seat in db.seats.values():
        if seat.workshop_id == w.id and seat.status == "ATTENDED":
            seat.status = "REVERSED"
            bump(seat)
    if w.assisting_volunteer_id:
        assistant = db.volunteers.get(w.assisting_volunteer_id)
        if assistant is not None:
            assistant.supervised_hours -= w.duration_hours
            bump(assistant)
    w.status = "COMPLETION_REVERSED"
    bump(w)
    return success_obj(ser_workshop(w))


@bp.post("/naturalization/workshops/<workshop_id>/cancel")
def cancel_workshop(workshop_id):
    json_body()
    authenticate()
    require_roles("ProgramAdmin")
    w = _get_workshop(workshop_id)
    if w.status != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED workshop may be cancelled")
    for seat in db.seats.values():
        if seat.workshop_id == w.id and seat.status == "RESERVED":
            seat.status = "CANCELLED"
            bump(seat)
    _recompute_reserved_count(w)
    w.status = "CANCELLED"
    bump(w)
    return success_obj(ser_workshop(w))


# --------------------------- Workshop seats ---------------------------

@bp.post("/naturalization/workshops/<workshop_id>/seats")
def reserve_seat(workshop_id):
    body = json_body()
    applicant_id = v_str(body, "applicant_id")
    expected_version = v_int(body, "expected_workshop_version")
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    w = _get_workshop(workshop_id)
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise err_not_found("Applicant not found")
    if g.user_role == "Applicant" and applicant_id != g.user_id:
        raise err_forbidden("Applicants may only reserve seats for themselves")
    eligible_active_screening(applicant)
    if w.reserved_count >= w.capacity:
        raise conflict("ERR_WORKSHOP_FULL", "Workshop is at capacity")
    if expected_version != w.version:
        raise err_stale_version()
    seat = Rec(workshop_id=w.id, applicant_id=applicant.id, status="RESERVED")
    stamp_new(seat)
    db.seats[seat.id] = seat
    w.reserved_count += 1
    bump(w)
    return success_obj(ser_seat(seat), 201)


@bp.get("/naturalization/workshops/<workshop_id>/seats")
def list_workshop_seats(workshop_id):
    authenticate()
    require_roles(*ROLES)
    w = _get_workshop(workshop_id)
    recs = [s for s in db.seats.values() if s.workshop_id == w.id]
    if g.user_role == "Applicant":
        recs = [s for s in recs if s.applicant_id == g.user_id]
    return paginate(recs, ser_seat)


@bp.get("/naturalization/workshop-seats")
def list_seats():
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    recs = list(db.seats.values())
    if g.user_role == "Applicant":
        recs = [s for s in recs if s.applicant_id == g.user_id]
    applicant_id = request.args.get("applicant_id")
    if applicant_id is not None:
        recs = [s for s in recs if s.applicant_id == applicant_id]
    workshop_id = request.args.get("workshop_id")
    if workshop_id is not None:
        recs = [s for s in recs if s.workshop_id == workshop_id]
    status = request.args.get("status")
    if status is not None:
        recs = [s for s in recs if s.status == status]
    return paginate(recs, ser_seat)


@bp.get("/naturalization/workshop-seats/<seat_id>")
def get_seat(seat_id):
    authenticate()
    require_roles(*ROLES)
    seat = _get_seat(seat_id)
    if g.user_role == "Applicant" and seat.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only read their own seats")
    return success_obj(ser_seat(seat))


@bp.post("/naturalization/workshop-seats/<seat_id>/cancel")
def cancel_seat(seat_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    seat = _get_seat(seat_id)
    if g.user_role == "Applicant" and seat.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only cancel their own seats")
    if seat.status != "RESERVED":
        raise err_invalid_state("Only a RESERVED seat may be cancelled")
    seat.status = "CANCELLED"
    bump(seat)
    w = db.workshops.get(seat.workshop_id)
    if w is not None:
        w.reserved_count -= 1
        bump(w)
    return success_obj(ser_seat(seat))
