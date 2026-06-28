"""Therapist routes: onboarding, licensing, activation/deactivation, matches list."""
from flask import Blueprint, request

from db import db, common_create_fields, touch
from clock import clock, parse_iso
from errors import err, ERR_INVALID_STATE
from middleware import get_auth, require_role
from lookup import get_or_404, paginate, check_therapist_owner
from validate import (
    require_body, require_string, require_enum, optional_int, require_datetime,
    require_string_array_subset, STATE_CODES, SPECIALTIES,
)
from services.domain import recompute_license_status, recompute_all_licenses
import serialize
from response import success, list_success

bp = Blueprint("therapists", __name__)


@bp.route("/therapists", methods=["POST"])
def create_therapist():
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    data = require_body(request.get_json(silent=True))
    full_name = require_string(data, "full_name")
    specialties = require_string_array_subset(data, "specialties", SPECIALTIES)
    max_caseload = optional_int(data, "max_active_caseload", default=30, minimum=1)
    therapist = {
        **common_create_fields(),
        "full_name": full_name,
        "status": "ONBOARDING",
        "max_active_caseload": max_caseload,
        "active_caseload": 0,
        "specialties": specialties,
    }
    db.therapists[therapist["id"]] = therapist
    return success(serialize.therapist_out(therapist), status=201)


@bp.route("/therapists/<tid>", methods=["GET"])
def get_therapist(tid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin", "BillingAdmin"})
    therapist = get_or_404(db.therapists, tid)
    return success(serialize.therapist_out(therapist))


@bp.route("/therapists", methods=["GET"])
def list_therapists():
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin", "BillingAdmin"})
    status = request.args.get("status")
    state_code = request.args.get("state_code")
    items = list(db.therapists.values())
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if state_code is not None:
        covered = set()
        recompute_all_licenses()
        for lic in db.licenses.values():
            if lic["state_code"] == state_code and lic["status"] == "VALID":
                covered.add(lic["therapist_id"])
        items = [t for t in items if t["id"] in covered]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.therapist_out(t) for t in page], lim, off, total)


@bp.route("/therapists/<tid>/licenses", methods=["POST"])
def add_license(tid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    therapist = get_or_404(db.therapists, tid)
    data = require_body(request.get_json(silent=True))
    state_code = require_enum(data, "state_code", STATE_CODES)
    expires_on = require_datetime(data, "expires_on")
    status = "VALID" if expires_on > clock.now() else "EXPIRED"
    lic = {
        **common_create_fields(),
        "therapist_id": tid,
        "state_code": state_code,
        "expires_on": data["expires_on"],
        "status": status,
    }
    db.licenses[lic["id"]] = lic
    return success(serialize.license_out(lic), status=201)


@bp.route("/therapists/<tid>/licenses", methods=["GET"])
def list_licenses(tid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin", "BillingAdmin"})
    get_or_404(db.therapists, tid)
    state_code = request.args.get("state_code")
    items = [l for l in db.licenses.values() if l["therapist_id"] == tid]
    for l in items:
        recompute_license_status(l)
    if state_code is not None:
        items = [l for l in items if l["state_code"] == state_code]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.license_out(l) for l in page], lim, off, total)


@bp.route("/therapists/<tid>/activate", methods=["POST"])
def activate_therapist(tid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    therapist = get_or_404(db.therapists, tid)
    if therapist["status"] != "ONBOARDING":
        raise err(ERR_INVALID_STATE, "Therapist not in ONBOARDING")
    # require >= 1 VALID license
    has_valid = False
    for l in db.licenses.values():
        if l["therapist_id"] == tid:
            recompute_license_status(l)
            if l["status"] == "VALID":
                has_valid = True
                break
    if not has_valid:
        raise err(ERR_INVALID_STATE, "Therapist has no VALID license")
    therapist["status"] = "ACCEPTING"
    touch(therapist)
    return success(serialize.therapist_out(therapist))


@bp.route("/therapists/<tid>/deactivate", methods=["POST"])
def deactivate_therapist(tid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    therapist = get_or_404(db.therapists, tid)
    if therapist["status"] not in ("ACCEPTING", "FULL", "ONBOARDING"):
        raise err(ERR_INVALID_STATE, "Therapist cannot be deactivated from current state")
    active_matches = [m for m in db.matches.values()
                      if m["therapist_id"] == tid and m["status"] == "ACTIVE"]
    if active_matches:
        raise err(ERR_INVALID_STATE, "Therapist has ACTIVE matches")
    therapist["status"] = "INACTIVE"
    touch(therapist)
    return success(serialize.therapist_out(therapist))


@bp.route("/therapists/<tid>/matches", methods=["GET"])
def list_therapist_matches(tid):
    user_id, role = get_auth()
    require_role(role, {"Therapist", "ClinicalAdmin"})
    get_or_404(db.therapists, tid)
    check_therapist_owner(role, user_id, tid)
    status = request.args.get("status")
    items = [m for m in db.matches.values()
             if m["therapist_id"] == tid and (status is None or m["status"] == status)]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.match_out(m) for m in page], lim, off, total)
