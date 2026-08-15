"""Volunteers, training credits, accreditation lifecycle."""
from flask import Blueprint, g

from auth import authenticate, require_roles
from db import db, Rec, stamp_new, stamp_new_appendonly, bump, now_dt, prog_param
from errors import err_not_found, err_forbidden, err_invalid_state, conflict
from services import ser_volunteer, ser_training_credit, training_hours_24mo
from util import (json_body, success_obj, paginate, v_str, v_int, v_bool,
                  v_enum, v_datetime)

bp = Blueprint("volunteers", __name__)


def _get_volunteer(volunteer_id):
    v = db.volunteers.get(volunteer_id)
    if v is None:
        raise err_not_found("Volunteer not found")
    return v


def _check_self(v):
    if g.user_role == "Volunteer" and v.id != g.user_id:
        raise err_forbidden("Volunteers may only access their own record")


@bp.post("/naturalization/volunteers")
def create_volunteer():
    body = json_body()
    full_name = v_str(body, "full_name")
    email = v_str(body, "email")
    bg = v_bool(body, "background_check_cleared")
    bar = v_str(body, "bar_number", required=False)
    authenticate()
    require_roles("ProgramAdmin")
    v = Rec(full_name=full_name, email=email, background_check_cleared=bg,
            bar_number=bar, accreditation_level="TRAINEE",
            lapsed_from_level=None, accredited_at=None, supervised_hours=0)
    stamp_new(v)
    db.volunteers[v.id] = v
    return success_obj(ser_volunteer(v), 201)


@bp.get("/naturalization/volunteers/<volunteer_id>")
def get_volunteer(volunteer_id):
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Volunteer")
    v = _get_volunteer(volunteer_id)
    _check_self(v)
    return success_obj(ser_volunteer(v))


@bp.post("/naturalization/volunteers/<volunteer_id>/training-credits")
def create_training_credit(volunteer_id):
    body = json_body()
    topic = v_str(body, "topic")
    hours = v_int(body, "hours", minv=1)
    raw, dt = v_datetime(body, "earned_at")
    authenticate()
    require_roles("ProgramAdmin")
    v = _get_volunteer(volunteer_id)
    c = Rec(volunteer_id=v.id, topic=topic, hours=hours,
            earned_at_raw=raw, earned_at_dt=dt)
    stamp_new_appendonly(c)
    db.training[c.id] = c
    return success_obj(ser_training_credit(c), 201)


@bp.get("/naturalization/volunteers/<volunteer_id>/training-credits")
def list_training_credits(volunteer_id):
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Volunteer")
    v = _get_volunteer(volunteer_id)
    _check_self(v)
    recs = [c for c in db.training.values() if c.volunteer_id == v.id]
    return paginate(recs, ser_training_credit)


@bp.post("/naturalization/volunteers/<volunteer_id>/accredit")
def accredit(volunteer_id):
    body = json_body()
    target = v_enum(body, "target_level", ("GENERAL", "LEGAL"))
    authenticate()
    require_roles("ProgramAdmin")
    v = _get_volunteer(volunteer_id)
    if target == "GENERAL":
        if v.accreditation_level != "TRAINEE":
            raise err_invalid_state(
                "Only a TRAINEE volunteer may be accredited to GENERAL")
        if not v.background_check_cleared or \
                training_hours_24mo(v) < prog_param("general_training_hours"):
            raise conflict("ERR_ACCREDITATION_INSUFFICIENT",
                           "Background check or training hours insufficient")
    else:  # LEGAL
        if v.accreditation_level != "GENERAL":
            raise err_invalid_state(
                "Only a GENERAL volunteer may be accredited to LEGAL")
        if not (v.bar_number is not None or
                v.supervised_hours >= prog_param("legal_supervised_hours")):
            raise conflict("ERR_ACCREDITATION_INSUFFICIENT",
                           "Bar number or supervised hours insufficient")
    v.accreditation_level = target
    v.accredited_at = now_dt()
    bump(v)
    return success_obj(ser_volunteer(v))


@bp.post("/naturalization/volunteers/<volunteer_id>/renew")
def renew(volunteer_id):
    json_body()
    authenticate()
    require_roles("ProgramAdmin")
    v = _get_volunteer(volunteer_id)
    if v.accreditation_level != "LAPSED":
        raise err_invalid_state("Only a LAPSED accreditation may be renewed")
    if training_hours_24mo(v) < prog_param("renewal_training_hours"):
        raise conflict("ERR_ACCREDITATION_INSUFFICIENT",
                       "Renewal training hours insufficient")
    v.accreditation_level = v.lapsed_from_level
    v.lapsed_from_level = None
    v.accredited_at = now_dt()
    bump(v)
    return success_obj(ser_volunteer(v))
