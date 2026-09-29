"""Site controls: proposal, coverage exclusivity, O&M certification, retirement."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import endpoint
from routes.common import apply_filter, fetch, require_owner
from services import derive
from services.constants import (
    CONTROL_CLASS,
    CONTROL_COVERAGE_BUFFER_DAYS,
    CONTROL_CONDITION,
    CONTROL_STATUS,
    CONTROL_TYPES,
)
from services.serialize import dump_control

bp = Blueprint("controls", __name__)

READ_ROLES = ["EnvironmentalConsultant", "StateAgencyReviewer", "Redeveloper",
              "Insurer", "Lender"]
ACTIVE_STATUSES = ("PROPOSED", "APPROVED", "OPERATING", "IMPAIRED")


@bp.post("/site-controls")
@endpoint(["EnvironmentalConsultant"])
def create_control():
    body = V.json_body()
    site_id = V.id_field(body, "site_id", True)
    plan_id = V.id_field(body, "remedial_action_plan_id", True)
    control_type = V.enum_field(body, "control_type", CONTROL_TYPES, True)
    sub_area_code = V.string_field(body, "sub_area_code", True, 1, 32)
    coverage_from = V.date_field(body, "coverage_from", True)
    coverage_to = V.date_field(body, "coverage_to", True)
    interval = V.int_field(body, "inspection_interval_days", True, 30, 730)
    if coverage_to < coverage_from:
        V.fail("Field coverage_to must be on or after coverage_from.")

    site = fetch("sites", site_id)
    plan = fetch("remedial_action_plans", plan_id)
    derive.assert_not_frozen(site)

    control_class = derive.control_class_for(control_type)
    if control_class == "ENGINEERING":
        buffer = CONTROL_COVERAGE_BUFFER_DAYS
        for other in derive.controls_of_site(site["id"]):
            if (other["sub_area_code"] != sub_area_code
                    or other["control_class"] != "ENGINEERING"
                    or other["status"] not in ACTIVE_STATUSES):
                continue
            other_from = db.parse_date(other["coverage_from"])
            other_to = db.parse_date(other["coverage_to"])
            if (coverage_from <= db.add_days(other_to, buffer)
                    and other_from <= db.add_days(coverage_to, buffer)):
                raise ApiError(
                    "ERR_CONTROL_COVERAGE_CONFLICT",
                    "Sub-area %s is already covered by control %s within the "
                    "30-day changeover buffer." % (sub_area_code, other["id"]))

    if plan["site_id"] != site["id"]:
        raise ApiError("ERR_PLAN_SITE_MISMATCH",
                       "The named plan belongs to a different parcel.")

    row = db.insert("site_controls", {
        "site_id": site["id"],
        "remedial_action_plan_id": plan["id"],
        "control_type": control_type,
        "control_class": control_class,
        "sub_area_code": sub_area_code,
        "coverage_from": coverage_from.isoformat(),
        "coverage_to": coverage_to.isoformat(),
        "inspection_interval_days": interval,
        "status": "PROPOSED",
        "last_certified_on": None,
        "next_certification_due_on": db.add_days(coverage_from,
                                                interval).isoformat(),
        "impaired_since": None,
        "impairment_count": 0,
    })
    return response.created(dump_control(row))


@bp.get("/site-controls")
@endpoint(READ_ROLES)
def list_controls():
    rows = db.ordered(db.all_rows("site_controls"))
    rows = apply_filter(rows, "site_id", V.query_string("site_id"))
    rows = apply_filter(rows, "remedial_action_plan_id",
                        V.query_string("remedial_action_plan_id"))
    rows = apply_filter(rows, "sub_area_code", V.query_string("sub_area_code"))
    rows = apply_filter(rows, "status", V.query_enum("status", CONTROL_STATUS))
    rows = apply_filter(rows, "control_class",
                        V.query_enum("control_class", CONTROL_CLASS))
    return response.list_response(rows, dump_control)


@bp.get("/site-controls/<control_id>")
@endpoint(READ_ROLES)
def get_control(control_id):
    return response.object_response(dump_control(fetch("site_controls", control_id)))


@bp.post("/site-controls/<control_id>/operation-certification")
@endpoint(["Redeveloper"])
def operation_certification(control_id):
    body = V.json_body()
    condition = V.enum_field(body, "condition", CONTROL_CONDITION, True)
    certification_date = V.date_field(body, "certification_date", True)

    control = fetch("site_controls", control_id)
    site = db.get("sites", control["site_id"])
    if site is not None:
        require_owner(site)
        if condition == "PASS":
            derive.assert_not_frozen(site)

    if control["status"] in ("PROPOSED", "DECOMMISSIONED"):
        raise ApiError("ERR_INVALID_CONTROL_STATE",
                       "A %s control may not be certified." % control["status"])
    if condition == "FAIL" and control["status"] != "OPERATING":
        raise ApiError("ERR_INVALID_CONTROL_STATE",
                       "Only an OPERATING control may fail a certification.")

    if condition == "PASS":
        if (certification_date < db.parse_date(control["coverage_from"])
                or certification_date > db.parse_date(control["coverage_to"])):
            raise ApiError("ERR_CERTIFICATION_OUTSIDE_COVERAGE",
                           "The certification date falls outside the control's "
                           "coverage interval.")
        was_impaired = control["status"] == "IMPAIRED"
        control["status"] = "OPERATING"
        control["last_certified_on"] = certification_date.isoformat()
        control["next_certification_due_on"] = db.add_days(
            certification_date, int(control["inspection_interval_days"])).isoformat()
        if was_impaired:
            control["impaired_since"] = None
        db.touch(control)

        plan = db.get("remedial_action_plans", control["remedial_action_plan_id"])
        enrollment = (db.get("vcp_enrollments", plan["vcp_enrollment_id"])
                      if plan is not None else None)
        if enrollment is not None and enrollment["status"] == "REMEDY_APPROVED":
            enrollment["status"] = "IMPLEMENTATION"
            db.touch(enrollment)
        if site is not None and was_impaired:
            changed, _ = derive.recompute_posture(site)
            if changed:
                db.touch(site)
        return response.object_response(dump_control(control))

    derive.impair_control(control, site, revoke_letters=False)
    return response.object_response(dump_control(control))


@bp.post("/site-controls/<control_id>/decommission")
@endpoint(["StateAgencyReviewer"])
def decommission_control(control_id):
    body = V.json_body()
    V.string_field(body, "decommission_note", False, 1, 400)

    control = fetch("site_controls", control_id)
    site = db.get("sites", control["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if control["status"] != "OPERATING":
        raise ApiError("ERR_INVALID_CONTROL_STATE",
                       "Only an OPERATING control may be decommissioned.")

    for goal in derive.goals_of_site(control["site_id"]):
        if (goal.get("control_credit_type") == control["control_type"]
                and goal["attainment_status"] != "ATTAINED"):
            raise ApiError("ERR_CONTROL_STILL_REQUIRED",
                           "Cleanup goal %s still credits this control."
                           % goal["id"])
    for letter in derive.letters_of_site(control["site_id"]):
        if (letter["status"] == "ACCEPTED_BY_LENDER"
                and letter["requested_scope"] == "RESTRICTED_WITH_CONTROLS"):
            raise ApiError("ERR_CONTROL_STILL_REQUIRED",
                           "A lender is relying on closure that depends on this "
                           "control.")

    control["status"] = "DECOMMISSIONED"
    db.touch(control)
    return response.object_response(dump_control(control))
