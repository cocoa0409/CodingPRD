"""Agencies, bank officers, compliance reviewers, logical clock."""
from flask import Blueprint

import calc
from db import db, new_id, next_seq, now
from errors import (ApiError, ERR_DUPLICATE_KEY)
from middleware import auth, require_role
from response import ok_obj
from serializers import ser_agency, ser_officer, ser_reviewer
from util import (bool_filter, enum_filter, fmt_dt, get_or_404, list_page,
                  opt_bool, payload, req_enum, req_int, req_str, parse_dt)

bp = Blueprint("admin", __name__)

JURISDICTIONS = ["FEDERAL", "STATE", "FOREIGN"]
CERT_LEVELS = ["L1", "L2", "L3"]
ALL_ROLES = ("PlatformAdmin", "RegulatoryAffairsManager", "RemediationOwner",
             "ComplianceReviewer", "BoardReporter")


# ------------------------------------------------------------- agencies
@bp.post("/regulatory-exams/agencies")
def create_agency():
    auth_pair = auth()
    require_role(auth_pair[1], "PlatformAdmin")
    p = payload()
    # Uniqueness (priority 11) precedes request-shape (priority 14).
    code = p.get("agency_code")
    if isinstance(code, str):
        for a in db.agencies.values():
            if a["agency_code"] == code:
                raise ApiError(ERR_DUPLICATE_KEY, 409, "agency_code already exists")
    code = req_str(p, "agency_code")
    if len(code) > 20:
        raise ApiError("ERR_INVALID_REQUEST", 400, "agency_code must be 1-20 chars")
    name = req_str(p, "agency_name")
    jur = req_enum(p, "jurisdiction", JURISDICTIONS)
    thr = req_int(p, "escalation_threshold_days", 1, 730)
    mult = req_int(p, "repeat_finding_multiplier_bp", 10000, 40000)
    active = opt_bool(p, "active", True)
    rec = {"id": new_id(), "agency_code": code, "agency_name": name,
           "jurisdiction": jur, "escalation_threshold_days": thr,
           "repeat_finding_multiplier_bp": mult, "active": active,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.agencies[rec["id"]] = rec
    return ok_obj(ser_agency(rec), 201)


@bp.get("/regulatory-exams/agencies")
def list_agencies():
    auth()
    jur = enum_filter("jurisdiction", JURISDICTIONS)
    act = bool_filter("active")
    rows = [a for a in db.agencies.values()
            if (jur is None or a["jurisdiction"] == jur)
            and (act is None or a["active"] == act)]
    return list_page(rows, ser_agency)


@bp.get("/regulatory-exams/agencies/<rid>")
def get_agency(rid):
    auth()
    return ok_obj(ser_agency(get_or_404(db.agencies, rid)))


# ------------------------------------------------------------- officers
@bp.post("/regulatory-exams/officers")
def create_officer():
    auth_pair = auth()
    require_role(auth_pair[1], "PlatformAdmin")
    p = payload()
    name = req_str(p, "full_name")
    email = req_str(p, "email")
    title = req_str(p, "officer_role_title")
    active = opt_bool(p, "active", True)
    for o in db.officers.values():
        if o["email"] == email:
            raise ApiError(ERR_DUPLICATE_KEY, 409, "email already registered")
    rec = {"id": new_id(), "full_name": name, "email": email,
           "officer_role_title": title, "active": active,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.officers[rec["id"]] = rec
    return ok_obj(ser_officer(rec), 201)


@bp.get("/regulatory-exams/officers")
def list_officers():
    auth()
    act = bool_filter("active")
    rows = [o for o in db.officers.values() if act is None or o["active"] == act]
    return list_page(rows, ser_officer)


@bp.get("/regulatory-exams/officers/<rid>")
def get_officer(rid):
    auth()
    return ok_obj(ser_officer(get_or_404(db.officers, rid)))


# ------------------------------------------------------------- reviewers
@bp.post("/regulatory-exams/reviewers")
def create_reviewer():
    auth_pair = auth()
    require_role(auth_pair[1], "PlatformAdmin")
    p = payload()
    name = req_str(p, "full_name")
    email = req_str(p, "email")
    cert = req_enum(p, "certification_level", CERT_LEVELS)
    active = opt_bool(p, "active", True)
    for r in db.reviewers.values():
        if r["email"] == email:
            raise ApiError(ERR_DUPLICATE_KEY, 409, "email already registered")
    rec = {"id": new_id(), "full_name": name, "email": email,
           "certification_level": cert, "active": active,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.reviewers[rec["id"]] = rec
    return ok_obj(ser_reviewer(rec), 201)


@bp.get("/regulatory-exams/reviewers")
def list_reviewers():
    auth()
    cert = enum_filter("certification_level", CERT_LEVELS)
    act = bool_filter("active")
    rows = [r for r in db.reviewers.values()
            if (cert is None or r["certification_level"] == cert)
            and (act is None or r["active"] == act)]
    return list_page(rows, ser_reviewer)


@bp.get("/regulatory-exams/reviewers/<rid>")
def get_reviewer(rid):
    auth()
    return ok_obj(ser_reviewer(get_or_404(db.reviewers, rid)))


# ------------------------------------------------------- logical clock
@bp.post("/regulatory-exams/_clock/set_current_utc")
def set_clock():
    auth_pair = auth()
    require_role(auth_pair[1], "PlatformAdmin")
    p = payload()
    to = parse_dt(p.get("to_iso8601"))
    if to is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing or invalid to_iso8601")
    calc.process_clock(to)
    return ok_obj({"current_utc": fmt_dt(db.clock)})
