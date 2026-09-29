"""Sites, acquisition, cleanup goals and the site-scoped collection reads."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import ALL_ROLES, actor_id, actor_role, endpoint
from routes.common import apply_filter, fetch, party_or_404, require_owner, \
    require_party_type
from services import derive
from services.constants import (
    CLEANUP_POSTURE,
    CONTROL_TYPES,
    ENROLLMENT_STATUS,
    AWARD_STATUS,
    GOAL_BASIS,
    INTENDED_REUSE,
    MEDIA,
)
from services.serialize import (
    dump_award,
    dump_enrollment,
    dump_goal,
    dump_protection,
    dump_site,
)

bp = Blueprint("sites", __name__)

READ_ROLES = ["Redeveloper", "EnvironmentalConsultant", "StateAgencyReviewer",
              "Insurer", "Lender"]


@bp.post("/sites")
@endpoint(["Redeveloper"])
def create_site():
    body = V.json_body()
    owner_party_id = V.id_field(body, "owner_party_id", True)
    site_name = V.string_field(body, "site_name", True, 1, 160)
    county_code = V.string_field(body, "county_code", True, 1, 16)
    acreage = V.number_field(body, "acreage", True, gt=0, max_dp=2)
    intended_reuse = V.enum_field(body, "intended_reuse", INTENDED_REUSE, True)
    planned = V.date_field(body, "planned_acquisition_date", True)
    committed = V.bool_field(body, "institutional_control_committed",
                             False, default=False)

    owner = party_or_404(owner_party_id)
    require_owner({"owner_party_id": owner_party_id, "id": "new"})
    require_party_type(owner, "REDEVELOPER")

    row = db.insert("sites", {
        "owner_party_id": owner_party_id,
        "site_name": site_name,
        "county_code": county_code,
        "acreage": acreage,
        "intended_reuse": intended_reuse,
        "institutional_control_committed": committed,
        "planned_acquisition_date": planned.isoformat(),
        "acquisition_status": "UNDER_CONTRACT",
        "acquisition_date": None,
        "delineation_status": "NONE",
        "cleanup_posture": "OPEN",
        "impaired_control_count": 0,
    })
    return response.created(dump_site(row))


@bp.get("/sites")
@endpoint(ALL_ROLES)
def list_sites():
    rows = db.ordered(db.all_rows("sites"))
    rows = apply_filter(rows, "owner_party_id", V.query_string("owner_party_id"))
    rows = apply_filter(rows, "cleanup_posture",
                        V.query_enum("cleanup_posture", CLEANUP_POSTURE))
    return response.list_response(rows, dump_site)


@bp.get("/sites/<site_id>")
@endpoint(ALL_ROLES)
def get_site(site_id):
    return response.object_response(dump_site(fetch("sites", site_id)))


@bp.post("/sites/<site_id>/acquisition")
@endpoint(["Redeveloper"])
def record_acquisition(site_id):
    body = V.json_body()
    acquisition_date = V.date_field(body, "acquisition_date", True)
    site = fetch("sites", site_id)
    require_owner(site)
    derive.assert_not_frozen(site)
    if site["acquisition_status"] == "ACQUIRED":
        raise ApiError("ERR_SITE_ALREADY_ACQUIRED",
                       "Parcel %s is already ACQUIRED." % site["id"])
    site["acquisition_status"] = "ACQUIRED"
    site["acquisition_date"] = acquisition_date.isoformat()
    db.touch(site)

    protection = derive.protection_for_site(site["id"])
    if protection is not None:
        derive.recompute_protection(protection, site)
        db.touch(protection)
    return response.object_response(dump_site(site))


@bp.get("/sites/<site_id>/funding-assembly")
@endpoint(["Redeveloper", "StateAgencyReviewer", "Lender", "Insurer"])
def funding_assembly(site_id):
    site = fetch("sites", site_id)
    return response.object_response(derive.compute_assembly(site))


# ------------------------------------------------------------- cleanup goals


@bp.post("/sites/<site_id>/cleanup-goals")
@endpoint(["EnvironmentalConsultant", "Redeveloper"])
def create_cleanup_goal(site_id):
    body = V.json_body()
    contaminant_code = V.string_field(body, "contaminant_code", True, 1, 24)
    media = V.enum_field(body, "media", MEDIA, True)
    screening = V.number_field(body, "screening_level_ugl", True, gt=0)
    basis = V.enum_field(body, "basis", GOAL_BASIS, True)
    credit = V.enum_field(body, "control_credit_type", CONTROL_TYPES, False)
    if basis == "RESTRICTED" and credit is None:
        V.fail("Field control_credit_type is required when basis is RESTRICTED.")
    if basis == "UNRESTRICTED" and credit is not None:
        V.fail("Field control_credit_type must be absent when basis is UNRESTRICTED.")

    site = fetch("sites", site_id)
    if actor_role() == "Redeveloper":
        require_owner(site)
    derive.assert_not_frozen(site)

    existing = None
    for goal in derive.goals_of_site(site["id"]):
        if goal["contaminant_code"] == contaminant_code and goal["media"] == media:
            existing = goal
            break

    if existing is None:
        row = db.insert("cleanup_goals", {
            "site_id": site["id"],
            "contaminant_code": contaminant_code,
            "media": media,
            "screening_level_ugl": screening,
            "basis": basis,
            "control_credit_type": credit,
            "contaminant_count_in_media": 0,
            "goal_ugl": 0,
            "cumulative_cap_applied": False,
            "attainment_status": "NOT_ATTAINED",
            "compliant_streak": 0,
        })
        derive.recompute_goal(row, site)
        derive.replay_attainment(row)
    else:
        row = existing
        row["screening_level_ugl"] = screening
        row["basis"] = basis
        row["control_credit_type"] = credit
        derive.recompute_goal(row, site)
        derive.replay_attainment(row)
        db.touch(row)
    return response.created(dump_goal(row))


@bp.get("/sites/<site_id>/cleanup-goals")
@endpoint(READ_ROLES)
def list_cleanup_goals(site_id):
    site = fetch("sites", site_id)
    rows = derive.goals_of_site(site["id"])
    rows = apply_filter(rows, "media", V.query_enum("media", MEDIA))
    rows = apply_filter(rows, "basis", V.query_enum("basis", GOAL_BASIS))
    return response.list_response(rows, dump_goal)


@bp.get("/cleanup-goals/<goal_id>")
@endpoint(READ_ROLES)
def get_cleanup_goal(goal_id):
    return response.object_response(dump_goal(fetch("cleanup_goals", goal_id)))


# ------------------------------------------------- site-scoped collections


@bp.get("/sites/<site_id>/liability-protections")
@endpoint(READ_ROLES)
def list_site_protections(site_id):
    site = fetch("sites", site_id)
    protection = derive.protection_for_site(site["id"])
    rows = [protection] if protection is not None else []
    return response.list_response(rows, dump_protection)


@bp.get("/sites/<site_id>/vcp-enrollments")
@endpoint(READ_ROLES)
def list_site_enrollments(site_id):
    site = fetch("sites", site_id)
    rows = db.ordered([e for e in db.all_rows("vcp_enrollments")
                       if e["site_id"] == site["id"]])
    rows = apply_filter(rows, "status", V.query_enum("status", ENROLLMENT_STATUS))
    return response.list_response(rows, dump_enrollment)


@bp.get("/sites/<site_id>/funding-awards")
@endpoint(["Redeveloper", "StateAgencyReviewer", "Lender"])
def list_site_awards(site_id):
    site = fetch("sites", site_id)
    rows = derive.awards_of_site(site["id"])
    rows = apply_filter(rows, "status", V.query_enum("status", AWARD_STATUS))
    return response.list_response(rows, dump_award)
