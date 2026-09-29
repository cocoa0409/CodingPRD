"""Sites, the director assignment and the site-scoped reads (PRD 3.2, 3.9)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("sites", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")
NON_OPERATOR = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor")

DIRECTOR_ROLE_TITLES = ("PHYSICIAN", "DOCTORAL_SCIENTIST", "MIDLEVEL_PRACTITIONER")
BASES = ("AS_OF_ACTUAL", "PRE_SURVEY_PROJECTED")


@route(bp, "/sites", ["POST"], ["ProgramAdmin"])
def create_site(user_id, role):
    payload = valid.body()
    name = valid.req_str(payload, "name")
    department_code = valid.req_str(payload, "department_code")
    scope = valid.req_enum(payload, "complexity_scope", ("WAIVED", "MODERATE"))
    if any(s["department_code"] == department_code
           for s in db.data["sites"].values()):
        raise errors.invalid_request("department_code must be unique.")

    row = db.insert("sites", {
        "name": name,
        "department_code": department_code,
        "complexity_scope": scope,
        "lab_director_operator_id": None,
        "oversight_posture": "OPEN",
        "manual_entry_blocked": False,
        "open_deficiency_weight": 0.0,
        "held_result_count": 0,
        "total_operator_count": 0,
        "locked_out_operator_count": 0,
        "lapsed_or_locked_operator_count": 0,
        "pt_unsuccessful_count": 0,
        "site_qc_compliance_index": 100.00,
        "inspection_readiness_score": 100.00,
        "scope_creep_flag": False,
        "last_oversight_run_at": None,
    })
    return response.object_response(serializers.dump("sites", row), 201)


@route(bp, "/sites/<site_id>", ["GET"], ALL_ROLES)
def read_site(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    derive.recompute_site(site, refresh_device_rates=True)
    return response.object_response(serializers.dump("sites", site))


@route(bp, "/sites", ["GET"], ALL_ROLES)
def list_sites(user_id, role):
    limit, offset = valid.pagination()
    director = valid.arg("lab_director_operator_id")
    posture = valid.arg("oversight_posture")
    items = [s for s in db.rows("sites")
             if (director is None or s["lab_director_operator_id"] == director)
             and (posture is None or s["oversight_posture"] == posture)]
    return response.list_response(
        serializers.dump_many("sites", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/sites/<site_id>/director", ["PATCH"], ["ProgramAdmin"])
def assign_director(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    payload = valid.body()
    # Rank 11 — operator existence.
    nominee = valid.resolve_body("operators", payload, "lab_director_operator_id")
    # Rank 60.
    if nominee["site_id"] != site["id"]:
        raise errors.ApiError("ERR_CROSS_SITE_REFERENCE", 422)
    # Rank 64.
    if (nominee["role_title"] not in DIRECTOR_ROLE_TITLES
            or nominee["competency_status"] not in ("PROVISIONAL", "COMPETENT")):
        raise errors.ApiError("ERR_DIRECTOR_NOT_QUALIFIED", 422)

    site["lab_director_operator_id"] = nominee["id"]
    db.touch(site)
    return response.object_response(serializers.dump("sites", site))


@route(bp, "/sites/<site_id>/readiness", ["GET"], NON_OPERATOR)
def read_readiness(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    basis = valid.arg("basis") or "AS_OF_ACTUAL"
    if basis not in BASES:
        raise errors.invalid_request(
            "'basis' must be AS_OF_ACTUAL or PRE_SURVEY_PROJECTED.")
    # The read re-evaluates against the clock and always persists AS_OF_ACTUAL.
    derive.recompute_site(site, refresh_device_rates=True)
    breakdown = calc.readiness(site, basis)
    breakdown["computed_at"] = clock.now_iso()
    return response.object_response(breakdown)


@route(bp, "/sites/<site_id>/operators", ["GET"], NON_OPERATOR)
def list_site_operators(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    limit, offset = valid.pagination()
    items = [o for o in db.rows("operators") if o["site_id"] == site["id"]]
    return response.list_response(
        serializers.dump_many("operators", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/sites/<site_id>/devices", ["GET"], ALL_ROLES)
def list_site_devices(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    limit, offset = valid.pagination()
    items = [d for d in db.rows("devices") if d["site_id"] == site["id"]]
    return response.list_response(
        serializers.dump_many("devices", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/sites/<site_id>/storage-units", ["GET"], ALL_ROLES)
def list_site_storage_units(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    limit, offset = valid.pagination()
    items = [u for u in db.rows("storage_units") if u["site_id"] == site["id"]]
    return response.list_response(
        serializers.dump_many("storage_units", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/sites/<site_id>/inspections", ["GET"], NON_OPERATOR)
def list_site_inspections(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    limit, offset = valid.pagination()
    status = valid.arg("status")
    items = [i for i in db.rows("inspections")
             if i["site_id"] == site["id"]
             and (status is None or i["status"] == status)]
    return response.list_response(
        serializers.dump_many("inspections", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/sites/<site_id>/pt-enrollments", ["GET"], NON_OPERATOR)
def list_site_enrollments(user_id, role, site_id):
    site = valid.resolve("sites", site_id)
    limit, offset = valid.pagination()
    items = [e for e in db.rows("enrollments") if e["site_id"] == site["id"]]
    return response.list_response(
        serializers.dump_many("enrollments", valid.page(items, limit, offset)),
        limit, offset, len(items))
