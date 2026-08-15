"""Interviewers and calibration records (PRD §3.6)."""
import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found, err_ownership,
                    err_ref_not_found)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import (bump, filter_params, new_id, next_seq, paginate, req_number,
                  req_string, sort_records)

bp = Blueprint("interviewers", __name__)

READ_ROLES = ["TalentAssessmentAdmin", "Interviewer", "HiringManager", "ComplianceOfficer"]


@bp.post("/talent/interviewers")
def create_interviewer():
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    body = util.get_body()
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    department = req_string(body, "department")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "department": department,
        "committed_minutes_total": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["interviewers"][rec["id"]] = rec
    return success_object(serializers.interviewer(rec), 201)


@bp.get("/talent/interviewers/<iid>")
def get_interviewer(iid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    iv = db.stores["interviewers"].get(iid)
    if iv is None:
        raise err_not_found("Interviewer not found")
    if ctx.role == "Interviewer" and ctx.user_id != iv["id"]:
        raise err_ownership("Interviewer may only read own record")
    core.recompute_interviewer_minutes(iv["id"])
    return success_object(serializers.interviewer(iv))


@bp.post("/talent/interviewers/<iid>/calibrations")
def create_calibration(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    iv = db.stores["interviewers"].get(iid)
    if iv is None:
        raise err_not_found("Interviewer not found")
    body = util.get_body()
    guide_id = body.get("guide_id")
    if not isinstance(guide_id, str):
        raise err_invalid_request("guide_id is required")
    guide = db.stores["guides"].get(guide_id)
    if guide is None:
        raise err_ref_not_found("guide_id does not resolve")
    for rec in db.stores["calibrations"].values():
        if (rec["interviewer_id"] == iid and rec["guide_id"] == guide_id
                and rec["status"] in ("TRAINED", "CALIBRATED")):
            raise api_err("ERR_DUPLICATE_CALIBRATION",
                          "An open calibration record exists for this (interviewer, guide)")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "interviewer_id": iid,
        "guide_id": guide_id,
        "status": "TRAINED",
        "practice_score": None,
        "trained_at": now,
        "certified_at": None,
        "calibration_index": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["calibrations"][rec["id"]] = rec
    return success_object(serializers.calibration(rec), 201)


@bp.get("/talent/calibrations")
def list_calibrations():
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    filters = filter_params(["interviewer_id", "guide_id", "status"])
    if ctx.role == "Interviewer":
        if "interviewer_id" in filters and filters["interviewer_id"] != ctx.user_id:
            raise err_ownership("Interviewer must filter by own interviewer_id")
    recs = []
    for rec in sort_records(list(db.stores["calibrations"].values())):
        if "interviewer_id" in filters and rec["interviewer_id"] != filters["interviewer_id"]:
            continue
        if "guide_id" in filters and rec["guide_id"] != filters["guide_id"]:
            continue
        if "status" in filters and rec["status"] != filters["status"]:
            continue
        if rec["status"] in ("TRAINED", "CALIBRATED"):
            idx = core.compute_calibration_index(rec)
            if idx != rec.get("calibration_index"):
                rec["calibration_index"] = idx
                bump(rec)
        recs.append(serializers.calibration(rec))
    return paginate(recs)


@bp.get("/talent/calibrations/<cid>")
def get_calibration(cid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    rec = db.stores["calibrations"].get(cid)
    if rec is None:
        raise err_not_found("CalibrationRecord not found")
    if ctx.role == "Interviewer" and rec["interviewer_id"] != ctx.user_id:
        raise err_ownership("Interviewer may only read own calibration records")
    if rec["status"] in ("TRAINED", "CALIBRATED"):
        idx = core.compute_calibration_index(rec)
        if idx != rec.get("calibration_index"):
            rec["calibration_index"] = idx
            bump(rec)
    return success_object(serializers.calibration(rec))


@bp.post("/talent/calibrations/<cid>/certify")
def certify_calibration(cid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    rec = db.stores["calibrations"].get(cid)
    if rec is None:
        raise err_not_found("CalibrationRecord not found")
    if rec["status"] != "TRAINED":
        raise api_err("ERR_INVALID_STATE", "Calibration record must be TRAINED to certify")
    guide = db.stores["guides"].get(rec["guide_id"])
    if guide is None or guide["status"] not in ("PILOT", "APPROVED"):
        raise api_err("ERR_GUIDE_NOT_APPROVED",
                      "Guide must be PILOT or APPROVED to certify")
    body = util.get_body()
    practice_score = req_number(body, "practice_score")
    if practice_score < 0.7:
        raise api_err("ERR_PRACTICE_SCORE_BELOW_THRESHOLD",
                      "practice_score must be at least 0.7000")
    rec["practice_score"] = practice_score
    rec["certified_at"] = db.get_now()
    rec["status"] = "CALIBRATED"
    bump(rec)
    return success_object(serializers.calibration(rec))
