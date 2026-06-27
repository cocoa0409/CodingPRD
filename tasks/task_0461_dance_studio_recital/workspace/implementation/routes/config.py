"""Term / Room / Instructor routes (PRD 3.1, 3.2)."""
from flask import Blueprint

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (lookup, parse_date, require_fields, require_int,
                     require_str, optional_int)
from middleware import authenticate, get_json
from response import success
from views import public

bp = Blueprint("config", __name__)


# --------------------------------------------------------------------------
# Terms
# --------------------------------------------------------------------------
@bp.route("/terms", methods=["POST"])
def create_term():
    authenticate({"StudioAdmin"})
    body = get_json()
    require_fields(body, ["name", "start_date", "end_date", "age_cutoff_date",
                          "monthly_billing_day"])
    name = require_str(body, "name")
    start = parse_date(body, "start_date")
    end = parse_date(body, "end_date")
    cutoff = parse_date(body, "age_cutoff_date")
    billing_day = require_int(body, "monthly_billing_day", lo=1, hi=28)
    if not (end > start):
        raise err("ERR_INVALID_REQUEST", "end_date must be strictly after start_date.")
    if not (start <= cutoff <= end):
        raise err("ERR_INVALID_REQUEST", "age_cutoff_date must be within the term window.")
    term = {
        "id": new_id(),
        "name": name,
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "age_cutoff_date": body["age_cutoff_date"],
        "monthly_billing_day": billing_day,
        "status": "DRAFT",
        **common_fields(),
    }
    db.terms[term["id"]] = term
    return success(public(term), status=201)


@bp.route("/terms/<tid>", methods=["GET"])
def get_term(tid):
    authenticate({"StudioAdmin", "Parent", "Instructor"})
    term = lookup(db.terms, tid)
    return success(public(term), status=200)


@bp.route("/terms/<tid>/open", methods=["POST"])
def open_term(tid):
    authenticate({"StudioAdmin"})
    term = lookup(db.terms, tid)
    if term["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Term is not DRAFT.")
    sections = [s for s in db.sections.values() if s["term_id"] == term["id"]]
    scheduled = [s for s in sections if s["status"] == "SCHEDULED"]
    if not scheduled:
        raise err("ERR_INVALID_STATE", "Term has no SCHEDULED section.")
    start = parse_date(term, "start_date")
    end = parse_date(term, "end_date")
    cutoff = parse_date(term, "age_cutoff_date")
    if not (start <= cutoff <= end):
        raise err("ERR_INVALID_STATE", "age_cutoff_date is outside the term window.")
    term["status"] = "OPEN"
    touch(term)
    for s in scheduled:
        s["status"] = "OPEN"
        touch(s)
    return success(public(term), status=200)


@bp.route("/terms/<tid>/close", methods=["POST"])
def close_term(tid):
    authenticate({"StudioAdmin"})
    term = lookup(db.terms, tid)
    if term["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Term is not OPEN.")
    term_invoices = [i for i in db.invoices.values() if i["term_id"] == term["id"]]
    if any(i["status"] not in {"PAID", "VOID"} for i in term_invoices):
        raise err("ERR_INVALID_STATE", "Not all term invoices are PAID or VOID.")
    term["status"] = "CLOSED"
    touch(term)
    # Each BILLING_ACTIVE enrollment under this term -> BILLING_ENDED.
    section_ids = {s["id"] for s in db.sections.values() if s["term_id"] == term["id"]}
    for e in db.enrollments.values():
        if e["section_id"] in section_ids and e["billing_status"] == "BILLING_ACTIVE":
            e["billing_status"] = "BILLING_ENDED"
            touch(e)
    return success(public(term), status=200)


# --------------------------------------------------------------------------
# Rooms
# --------------------------------------------------------------------------
@bp.route("/rooms", methods=["POST"])
def create_room():
    authenticate({"StudioAdmin"})
    body = get_json()
    require_fields(body, ["name", "capacity"])
    name = require_str(body, "name")
    capacity = require_int(body, "capacity", lo=1)
    buffer = optional_int(body, "turnover_buffer_minutes", default=0, lo=0)
    room = {
        "id": new_id(),
        "name": name,
        "capacity": capacity,
        "turnover_buffer_minutes": buffer,
        **common_fields(),
    }
    db.rooms[room["id"]] = room
    return success(public(room), status=201)


@bp.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    authenticate({"StudioAdmin", "Instructor"})
    room = lookup(db.rooms, rid)
    return success(public(room), status=200)


# --------------------------------------------------------------------------
# Instructors
# --------------------------------------------------------------------------
@bp.route("/instructors", methods=["POST"])
def create_instructor():
    authenticate({"StudioAdmin"})
    body = get_json()
    require_fields(body, ["full_name", "email"])
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    norm = email.strip().lower()
    if any(i["email"].strip().lower() == norm for i in db.instructors.values()):
        raise err("ERR_INVALID_REQUEST", "Instructor email already in use.")
    max_weekly = optional_int(body, "max_weekly_sessions", default=30, lo=1)
    inst = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "max_weekly_sessions": max_weekly,
        **common_fields(),
    }
    db.instructors[inst["id"]] = inst
    return success(public(inst), status=201)


@bp.route("/instructors/<iid>", methods=["GET"])
def get_instructor(iid):
    authenticate({"StudioAdmin", "Instructor"})
    inst = lookup(db.instructors, iid)
    return success(public(inst), status=200)
