"""Patient care reports and the QA cascade (PRD §3.9, C8)."""

from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    ERR_DUPLICATE_PCR, ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_MISSION_NOT_COMPLETED, ERR_PCR_WINDOW_EXPIRED, ERR_SELF_REVIEW_FORBIDDEN,
    ERR_STALE_VERSION, db, fail, get_body, list_response, must_exist,
    next_seq, now_dt, now_iso, ok_object, require_roles, stamp_new, touch,
    v_enum, v_int, v_str,
)
from serialize import ser_pcr

bp = Blueprint("pcr", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

PCR_STATUSES = {"DRAFT", "SUBMITTED", "QA_APPROVED", "QA_FLAGGED", "AMENDED"}
QA_OUTCOMES = {"APPROVED", "FLAGGED"}


@bp.route("/air-ambulance/patient-care-reports", methods=["POST"])
def create_pcr():
    user_id, role = require_roles("FlightCrew")
    body = get_body()
    # FlightCrew ownership (priority 2) precedes body-FK existence (priority 3)
    if body.get("author_crew_id") is not None and body.get("author_crew_id") != user_id:
        fail(ERR_FORBIDDEN, 403, "author_crew_id must equal X-User-ID")
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    if body.get("author_crew_id") is not None:
        must_exist(db.crew_members, body["author_crew_id"], "CrewMember")
    mission_id = v_str(body, "mission_id")
    author_id = v_str(body, "author_crew_id")
    vitals = v_str(body, "vitals_summary")
    interventions = v_str(body, "interventions_summary")
    meds = v_str(body, "meds_summary")
    if any(p["mission_id"] == mission_id for p in db.patient_care_reports.values()):
        fail(ERR_DUPLICATE_PCR, 409,
             "A patient care report already exists for this mission")
    rec = stamp_new({
        "mission_id": mission_id,
        "author_crew_id": author_id,
        "vitals_summary": vitals,
        "interventions_summary": interventions,
        "meds_summary": meds,
        "last_review_points": 0,
        "submitted_at": None,
        "status": "DRAFT",
    })
    db.patient_care_reports[rec["id"]] = rec
    return ok_object(ser_pcr(rec), 201)


@bp.route("/air-ambulance/patient-care-reports/<rid>", methods=["GET"])
def get_pcr(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.patient_care_reports, rid, "PatientCareReport")
    return ok_object(ser_pcr(rec))


@bp.route("/air-ambulance/patient-care-reports", methods=["GET"])
def list_pcrs():
    require_roles(*ALL_ROLES)
    return list_response(
        db.patient_care_reports.values(), ser_pcr,
        {"mission_id": "mission_id", "author_crew_id": "author_crew_id",
         "status": "status"},
    )


@bp.route("/air-ambulance/patient-care-reports/<rid>/submit", methods=["POST"])
def submit_pcr(rid):
    user_id, role = require_roles("FlightCrew")
    rec = must_exist(db.patient_care_reports, rid, "PatientCareReport")
    if rec["author_crew_id"] != user_id:
        fail(ERR_FORBIDDEN, 403, "Only the author may submit the record")
    get_body()
    if rec["status"] not in {"DRAFT", "AMENDED"}:
        fail(ERR_INVALID_STATE, 409,
             "PatientCareReport status %s cannot be submitted" % rec["status"])
    mission = db.missions.get(rec["mission_id"])
    if mission is None or mission["status"] != "COMPLETED":
        fail(ERR_MISSION_NOT_COMPLETED, 409, "Owning mission is not COMPLETED")
    completed = mission.get("_completed_dt")
    if completed is None or now_dt() > completed + timedelta(hours=24):
        fail(ERR_PCR_WINDOW_EXPIRED, 422,
             "Submission is later than 24h after mission completion")
    rec["submitted_at"] = now_iso()
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok_object(ser_pcr(rec))


@bp.route("/air-ambulance/patient-care-reports/<rid>/qa-review", methods=["POST"])
def qa_review(rid):
    user_id, role = require_roles("QaReviewer")
    rec = must_exist(db.patient_care_reports, rid, "PatientCareReport")
    # segregation of duties: the reviewer may never review their own record
    if rec["author_crew_id"] == user_id:
        fail(ERR_SELF_REVIEW_FORBIDDEN, 403,
             "A QaReviewer may not review a record they authored")
    body = get_body()
    outcome = v_enum(body, "outcome", QA_OUTCOMES)
    points = v_int(body, "deficiency_points", minimum=0)
    if rec["status"] != "SUBMITTED":
        fail(ERR_INVALID_STATE, 409,
             "PatientCareReport status %s cannot be reviewed" % rec["status"])
    rec["last_review_points"] = points
    if outcome == "APPROVED":
        rec["status"] = "QA_APPROVED"
        touch(rec)
        return ok_object(ser_pcr(rec))
    # FLAGGED: record the review event, then run the C8 cascade
    rec["status"] = "QA_FLAGGED"
    touch(rec)
    db.qa_review_events.append({
        "pcr_id": rec["id"],
        "author_crew_id": rec["author_crew_id"],
        "points": points,
        "created_dt": now_dt(),
        "seq": next_seq(),
    })
    author = db.crew_members.get(rec["author_crew_id"])
    if author is not None:
        # hop 1: rolling tally mutates the member
        touch(author)
        # hop 2: crossing the threshold pulls the member from duty
        if (author["status"] == "ACTIVE"
                and calc.deficiency_points_90d(author["id"]) >= calc.REMEDIATION_THRESHOLD):
            author["status"] = "REMEDIATION_HOLD"
            touch(author)
            # hop 3: release the member's ASSIGNED assignments on PLANNING missions
            for a in db.crew_assignments.values():
                if a["crew_member_id"] == author["id"] and a["status"] == "ASSIGNED":
                    mission = db.missions.get(a["mission_id"])
                    if mission is not None and mission["status"] == "PLANNING":
                        a["status"] = "RELEASED"
                        touch(a)
    return ok_object(ser_pcr(rec))


@bp.route("/air-ambulance/patient-care-reports/<rid>/amend", methods=["POST"])
def amend_pcr(rid):
    user_id, role = require_roles("FlightCrew")
    rec = must_exist(db.patient_care_reports, rid, "PatientCareReport")
    if rec["author_crew_id"] != user_id:
        fail(ERR_FORBIDDEN, 403, "Only the author may amend the record")
    body = get_body()
    expected = v_int(body, "expected_patient_care_report_version")
    narratives = {}
    for field in ("vitals_summary", "interventions_summary", "meds_summary"):
        if body.get(field) is not None:
            narratives[field] = v_str(body, field)
    if rec["status"] not in {"QA_FLAGGED", "AMENDED"}:
        fail(ERR_INVALID_STATE, 409,
             "PatientCareReport status %s cannot be amended" % rec["status"])
    # OCC at the tail of the business-rule ladder
    if expected != rec["version"]:
        fail(ERR_STALE_VERSION, 412,
             "expected_patient_care_report_version does not match the current version")
    for field, value in narratives.items():
        rec[field] = value
    rec["status"] = "AMENDED"
    touch(rec)
    return ok_object(ser_pcr(rec))
