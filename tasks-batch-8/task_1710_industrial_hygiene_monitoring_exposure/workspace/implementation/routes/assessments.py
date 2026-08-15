"""Exposure assessments (PRD section 3.6) and retention archival (3.9)."""

from flask import Blueprint, request

import db
from errors import (
    ERR_ASSESSMENT_ALREADY_OPEN,
    ERR_ASSESSMENT_INVALID_STATE,
    ERR_LEGAL_HOLD_ACTIVE,
    ERR_PLAN_NOT_READY_FOR_ASSESSMENT,
    ERR_RETENTION_NOT_MET,
    ERR_SOD_ASSESSMENT_SIGNER,
    ERR_STALE_VERSION,
    raise_error,
)
from helpers import (
    reject_unknown,
    body, get_or_404, list_response, now_ts, req_bool, req_int, req_string,
    stamp_new, today, touch,
)
from response import success_object
from middleware import ALL_ROLES, require_auth
from serializers import assessment_out
from services import (
    RESAMPLE_INTERVAL_DAYS, add_days, add_years, compute_adjusted_class,
    compute_assessment_stats, working_days_after,
)

bp = Blueprint("assessments", __name__)

IH = ("IndustrialHygienist",)
CIH = ("CIHDirector",)


@bp.route("/ih/exposure-assessments", methods=["POST"])
def create_assessment():
    user_id, _ = require_auth(IH)
    data = body()
    reject_unknown(data, {"sampling_plan_id", "expected_seg_version"})
    # ---- Stage 3: schema (both fields required).
    sampling_plan_id = req_string(data, "sampling_plan_id")
    expected_seg_version = req_int(data, "expected_seg_version")
    # ---- Stage 4: existence.
    plan = get_or_404(db.sampling_plans, sampling_plan_id, "SamplingPlan")
    seg = db.segs[plan["seg_id"]]
    # ---- Stage 5: OCC on the SEG's version (after existence, before state).
    if expected_seg_version != seg["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_seg_version does not match the SEG's current version")
    # ---- Stage 6: the plan must be LAB_COMPLETE.
    if plan["status"] != "LAB_COMPLETE":
        raise_error(ERR_PLAN_NOT_READY_FOR_ASSESSMENT,
                    "Assessment creation requires the plan to be LAB_COMPLETE")
    # ---- Stage 10: at most one open (DRAFT/UNDER_REVIEW) assessment per SEG.
    for a in db.assessments.values():
        if a["seg_id"] == seg["id"] and a["review_status"] in ("DRAFT", "UNDER_REVIEW"):
            raise_error(ERR_ASSESSMENT_ALREADY_OPEN,
                        "An open assessment already exists for the SEG")

    assessment = {
        "seg_id": seg["id"],
        "sampling_plan_id": plan["id"],
        "supersedes_assessment_id": None,
        "n_valid": 0,
        "substitution_rule": None,
        "geo_mean": None,
        "gsd": None,
        "ucl95": None,
        "lcl95": None,
        "exposure_class": None,
        "adjusted_class": None,
        "review_status": "DRAFT",
        "is_current": False,
        "prepared_by_user_id": user_id,
        "signed_by_user_id": None,
        "signed_at": None,
        "retention_until": None,
        "legal_hold": False,
        "_ucl_unrounded": None,
        "_lcl_unrounded": None,
    }
    stamp_new(assessment)
    db.assessments[assessment["id"]] = assessment

    # Supersede the SEG's prior signed-and-current assessment, if any.
    for a in db.assessments.values():
        if (a["id"] != assessment["id"] and a["seg_id"] == seg["id"]
                and a["review_status"] == "SIGNED" and a["is_current"]):
            a["review_status"] = "SUPERSEDED"
            a["is_current"] = False
            touch(a)
            assessment["supersedes_assessment_id"] = a["id"]
            break

    # Statistics and classification are computed at creation and never
    # recomputed afterwards.
    compute_assessment_stats(assessment, plan, seg)

    # Creation itself advances the SEG's version (the reason the OCC exists).
    touch(seg)
    return success_object(assessment_out(assessment), 201)


@bp.route("/ih/exposure-assessments", methods=["GET"])
def list_assessments():
    require_auth(ALL_ROLES)
    items = list(db.assessments.values())
    include_archived = request.args.get("include_archived", "").lower() == "true"
    if not include_archived:
        items = [a for a in items if a["review_status"] != "ARCHIVED"]
    return list_response(items, assessment_out, {
        "seg_id": request.args.get("seg_id"),
        "sampling_plan_id": request.args.get("sampling_plan_id"),
        "supersedes_assessment_id": request.args.get("supersedes_assessment_id"),
    })


@bp.route("/ih/exposure-assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    require_auth(ALL_ROLES)
    # Archived assessments remain retrievable directly by id.
    return success_object(assessment_out(get_or_404(db.assessments, aid, "ExposureAssessment")))


@bp.route("/ih/exposure-assessments/<aid>/submit-review", methods=["POST"])
def submit_review(aid):
    require_auth(IH)
    a = get_or_404(db.assessments, aid, "ExposureAssessment")
    if a["review_status"] != "DRAFT":
        raise_error(ERR_ASSESSMENT_INVALID_STATE, "submit-review requires DRAFT")
    a["review_status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(assessment_out(a), 200)


@bp.route("/ih/exposure-assessments/<aid>/reject-review", methods=["POST"])
def reject_review(aid):
    require_auth(CIH)
    a = get_or_404(db.assessments, aid, "ExposureAssessment")
    if a["review_status"] != "UNDER_REVIEW":
        raise_error(ERR_ASSESSMENT_INVALID_STATE, "reject-review requires UNDER_REVIEW")
    a["review_status"] = "DRAFT"
    touch(a)
    return success_object(assessment_out(a), 200)


@bp.route("/ih/exposure-assessments/<aid>/sign", methods=["POST"])
def sign_assessment(aid):
    user_id, _ = require_auth(CIH)
    a = get_or_404(db.assessments, aid, "ExposureAssessment")
    if a["review_status"] != "UNDER_REVIEW":
        raise_error(ERR_ASSESSMENT_INVALID_STATE, "sign requires UNDER_REVIEW")
    if user_id == a["prepared_by_user_id"]:
        raise_error(ERR_SOD_ASSESSMENT_SIGNER,
                    "Assessment signer must differ from its preparer")

    # Pinned evaluation order (PRD 3.6): raw class already fixed at creation;
    # every regulatory consequence keys off the RAW class; only then is the
    # APF-adjusted class derived.
    signed_date = today()
    a["signed_at"] = now_ts()
    a["signed_by_user_id"] = user_id
    seg = db.segs[a["seg_id"]]
    site = db.sites[seg["site_id"]]
    a["retention_until"] = add_years(signed_date, site["retention_years"]).isoformat()
    a["is_current"] = True
    a["review_status"] = "SIGNED"

    seg["current_class"] = a["exposure_class"]
    seg["next_sample_due_date"] = add_days(
        signed_date, RESAMPLE_INTERVAL_DAYS[a["exposure_class"]]).isoformat()
    touch(seg)

    # Notification fan-out: one PENDING notification per current SEG member,
    # due 15 working days after the signed date.
    due = working_days_after(signed_date).isoformat()
    members = [m for m in db.seg_memberships.values() if m["seg_id"] == seg["id"]]
    members.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for m in members:
        notif = {
            "employee_id": m["employee_id"],
            "exposure_assessment_id": a["id"],
            "due_date": due,
            "status": "PENDING",
            "sent_at": None,
            "sent_by_user_id": None,
            "acknowledged_at": None,
        }
        stamp_new(notif)
        db.notifications[notif["id"]] = notif

    # ABOVE_PEL auto-drafts a PROPOSED high-priority engineering control.
    if a["exposure_class"] == "ABOVE_PEL":
        control = {
            "exposure_assessment_id": a["id"],
            "control_type": "ENGINEERING",
            "description": "Auto-created engineering control (ABOVE_PEL classification)",
            "priority": "HIGH",
            "assigned_protection_factor": None,
            "auto_created": True,
            "verification_plan_id": None,
            "implemented_at": None,
            "status": "PROPOSED",
        }
        stamp_new(control)
        db.controls[control["id"]] = control

    # APF adjustment last; never rewrites any raw-class consequence.
    a["adjusted_class"] = compute_adjusted_class(a, seg)
    touch(a)
    return success_object(assessment_out(a), 200)


@bp.route("/ih/exposure-assessments/<aid>", methods=["PUT"])
def update_assessment(aid):
    require_auth(CIH)
    data = body()
    reject_unknown(data, {"legal_hold"})
    legal_hold = req_bool(data, "legal_hold")
    a = get_or_404(db.assessments, aid, "ExposureAssessment")
    a["legal_hold"] = legal_hold
    touch(a)
    return success_object(assessment_out(a), 200)


@bp.route("/ih/exposure-assessments/<aid>/archive", methods=["POST"])
def archive_assessment(aid):
    require_auth(("FirmAdmin",))
    a = get_or_404(db.assessments, aid, "ExposureAssessment")
    if a["review_status"] not in ("SIGNED", "SUPERSEDED"):
        raise_error(ERR_ASSESSMENT_INVALID_STATE,
                    "archive requires SIGNED or SUPERSEDED")
    if a["legal_hold"]:
        raise_error(ERR_LEGAL_HOLD_ACTIVE, "Assessment is under legal hold")
    from datetime import date as _date
    if today() < _date.fromisoformat(a["retention_until"]):
        raise_error(ERR_RETENTION_NOT_MET,
                    "Current date is before the assessment's retention_until")
    a["review_status"] = "ARCHIVED"
    a["is_current"] = False
    touch(a)
    return success_object(assessment_out(a), 200)
