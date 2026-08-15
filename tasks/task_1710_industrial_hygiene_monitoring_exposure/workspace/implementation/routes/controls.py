"""Control recommendations (PRD section 3.7)."""

from flask import Blueprint, request

import db
from errors import (
    ERR_ASSESSMENT_NOT_SIGNED,
    ERR_CONTROL_INVALID_STATE,
    ERR_FIT_TEST_MISSING_FOR_PPE,
    ERR_INVALID_REQUEST,
    ERR_VERIFICATION_NOT_CLEAN,
    raise_error,
)
from helpers import (
    reject_unknown,
    body, get_or_404, list_response, now_ts, opt_number, req_enum, req_string,
    stamp_new, today, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import control_out
from services import (
    VERIFICATION_DUE_DAYS, add_days, spawn_verification_plan,
)

bp = Blueprint("controls", __name__)

IH = ("IndustrialHygienist",)
SSM = ("SiteSafetyManager",)
CIH = ("CIHDirector",)

CONTROL_TYPES = ("ENGINEERING", "ADMINISTRATIVE", "PPE_RESPIRATOR")
PRIORITIES = ("HIGH", "MEDIUM", "LOW")


@bp.route("/ih/control-recommendations", methods=["POST"])
def create_control():
    require_auth(IH)
    data = body()
    reject_unknown(data, {"exposure_assessment_id", "control_type", "description", "priority", "assigned_protection_factor"})
    exposure_assessment_id = req_string(data, "exposure_assessment_id")
    control_type = req_enum(data, "control_type", CONTROL_TYPES)
    description = req_string(data, "description")
    priority = req_enum(data, "priority", PRIORITIES)
    apf = opt_number(data, "assigned_protection_factor")
    if control_type == "PPE_RESPIRATOR":
        if apf is None:
            raise_error(ERR_INVALID_REQUEST,
                        "assigned_protection_factor is required for PPE_RESPIRATOR")
        if apf <= 1:
            raise_error(ERR_INVALID_REQUEST, "assigned_protection_factor must be > 1")
    elif apf is not None:
        raise_error(ERR_INVALID_REQUEST,
                    "assigned_protection_factor is forbidden unless control_type is PPE_RESPIRATOR")
    get_or_404(db.assessments, exposure_assessment_id, "ExposureAssessment")
    control = {
        "exposure_assessment_id": exposure_assessment_id,
        "control_type": control_type,
        "description": description,
        "priority": priority,
        "assigned_protection_factor": apf if control_type == "PPE_RESPIRATOR" else None,
        "auto_created": False,
        "verification_plan_id": None,
        "implemented_at": None,
        "status": "PROPOSED",
    }
    stamp_new(control)
    db.controls[control["id"]] = control
    return success_object(control_out(control), 201)


@bp.route("/ih/control-recommendations", methods=["GET"])
def list_controls():
    require_auth(ALL_ROLES)
    return list_response(list(db.controls.values()), control_out, {
        "exposure_assessment_id": request.args.get("exposure_assessment_id"),
        "verification_plan_id": request.args.get("verification_plan_id"),
    })


@bp.route("/ih/control-recommendations/<cid>", methods=["GET"])
def get_control(cid):
    require_auth(ALL_ROLES)
    return success_object(control_out(get_or_404(db.controls, cid, "ControlRecommendation")))


@bp.route("/ih/control-recommendations/<cid>/accept", methods=["POST"])
def accept_control(cid):
    require_auth(SSM)
    control = get_or_404(db.controls, cid, "ControlRecommendation")
    if control["status"] != "PROPOSED":
        raise_error(ERR_CONTROL_INVALID_STATE, "accept requires PROPOSED")
    if control["control_type"] == "PPE_RESPIRATOR":
        # Every current member of the parent SEG must hold a current PASSED
        # fit test AND a current CLEARED medical clearance.
        assessment = db.assessments[control["exposure_assessment_id"]]
        seg_id = assessment["seg_id"]
        now_date = today()
        member_ids = [m["employee_id"] for m in db.seg_memberships.values()
                      if m["seg_id"] == seg_id]
        for emp_id in member_ids:
            fit_ok = any(
                ft["employee_id"] == emp_id and ft["status"] == "PASSED"
                and ft["expiry_date"] is not None
                and now_date <= _d(ft["expiry_date"])
                for ft in db.fit_tests.values())
            clearance_ok = any(
                c["employee_id"] == emp_id and c["status"] == "CLEARED"
                and c["expiry_date"] is not None
                and now_date <= _d(c["expiry_date"])
                for c in db.medical_clearances.values())
            if not (fit_ok and clearance_ok):
                raise_error(ERR_FIT_TEST_MISSING_FOR_PPE,
                            "A SEG member lacks a current PASSED fit test or "
                            "current CLEARED medical clearance")
    control["status"] = "ACCEPTED"
    touch(control)
    return success_object(control_out(control), 200)


def _d(s):
    from datetime import date as _date
    return _date.fromisoformat(s)


@bp.route("/ih/control-recommendations/<cid>/reject", methods=["POST"])
def reject_control(cid):
    require_auth(SSM)
    control = get_or_404(db.controls, cid, "ControlRecommendation")
    if control["status"] != "PROPOSED":
        raise_error(ERR_CONTROL_INVALID_STATE, "reject requires PROPOSED")
    control["status"] = "REJECTED"
    touch(control)
    return success_object(control_out(control), 200)


@bp.route("/ih/control-recommendations/<cid>/implement", methods=["POST"])
def implement_control(cid):
    user_id, _ = require_auth(SSM)
    control = get_or_404(db.controls, cid, "ControlRecommendation")
    if control["status"] != "ACCEPTED":
        raise_error(ERR_CONTROL_INVALID_STATE, "implement requires ACCEPTED")
    assessment = db.assessments[control["exposure_assessment_id"]]
    if assessment["review_status"] != "SIGNED":
        raise_error(ERR_ASSESSMENT_NOT_SIGNED,
                    "Control implement requires the parent assessment to be SIGNED")
    control["implemented_at"] = now_ts()
    # Auto-create the verification sampling plan (cascade hop 2).
    plan = spawn_verification_plan(assessment["seg_id"], user_id)
    control["verification_plan_id"] = plan["id"]
    # Pull the SEG's next_sample_due_date forward to now + 14 days (cascade 3).
    seg = db.segs[assessment["seg_id"]]
    candidate = add_days(today(), VERIFICATION_DUE_DAYS).isoformat()
    if seg["next_sample_due_date"] is None or candidate < seg["next_sample_due_date"]:
        seg["next_sample_due_date"] = candidate
    touch(seg)
    control["status"] = "IMPLEMENTED"
    touch(control)
    return success_object(control_out(control), 200)


@bp.route("/ih/control-recommendations/<cid>/verify", methods=["POST"])
def verify_control(cid):
    require_auth(CIH)
    control = get_or_404(db.controls, cid, "ControlRecommendation")
    if control["status"] != "IMPLEMENTED":
        raise_error(ERR_CONTROL_INVALID_STATE, "verify requires IMPLEMENTED")
    plan_id = control["verification_plan_id"]
    clean = any(
        a["sampling_plan_id"] == plan_id
        and a["is_current"]
        and a["review_status"] == "SIGNED"
        and a["exposure_class"] in ("BELOW_ACTION", "BELOW_PEL_MONITOR")
        for a in db.assessments.values())
    if not clean:
        raise_error(ERR_VERIFICATION_NOT_CLEAN,
                    "Verification plan lacks a current SIGNED assessment with a "
                    "BELOW_ACTION or BELOW_PEL_MONITOR class")
    control["status"] = "VERIFIED"
    touch(control)
    return success_object(control_out(control), 200)
