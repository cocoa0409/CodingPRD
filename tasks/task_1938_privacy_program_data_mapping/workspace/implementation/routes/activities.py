"""Processing activities, purposes, and privacy impact assessments."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import STAFF_ROLES, get_body, require_roles
from response import list_response, success
from serialize import ser_activity, ser_assessment, ser_purpose
from services.core import (base_entity, create_assessment, created_asc,
                           has_open_assessment, maybe_resume_activity,
                           select_current_published_notice,
                           suspend_transfers_for_activity,
                           reinstate_transfers_for_activity, touch)
from services.risk import (LEGAL_BASES, NOTICE_SCOPES, PIA_RISK_THRESHOLD,
                           PURPOSE_TYPES, comprehensive_score, screening_score)
from utils import add_days

bp = Blueprint("activities", __name__)


# --- ProcessingActivity ----------------------------------------------------------

@bp.post("/privacy/processing-activities")
def create_activity():
    require_roles("DataSteward")
    body = get_body()
    element_ids = body.get("data_element_ids")
    vendor_id = body.get("vendor_id")
    if isinstance(element_ids, list):
        for eid in element_ids:
            if isinstance(eid, str) and eid not in db.data_elements:
                raise ApiError("ERR_NOT_FOUND", "linked data element not found")
    if (vendor_id is not None and isinstance(vendor_id, str)
            and vendor_id not in db.vendors):
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    if isinstance(element_ids, list):
        for eid in element_ids:
            element = db.data_elements.get(eid)
            if element is not None and element["status"] != "ACTIVE":
                raise ApiError("ERR_ELEMENT_RETIRED",
                               "linked data element is RETIRED")
    activity_name = body.get("activity_name")
    business_unit = body.get("business_unit")
    notice_scope = body.get("notice_scope")
    if not isinstance(activity_name, str) or not activity_name:
        raise ApiError("ERR_INVALID_REQUEST", "activity_name is required")
    if not isinstance(business_unit, str) or not business_unit:
        raise ApiError("ERR_INVALID_REQUEST", "business_unit is required")
    if notice_scope not in NOTICE_SCOPES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid notice_scope")
    if (not isinstance(element_ids, list)
            or any(not isinstance(eid, str) for eid in element_ids)):
        raise ApiError("ERR_INVALID_REQUEST",
                       "data_element_ids must be a list of strings")
    if vendor_id is not None and not isinstance(vendor_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "vendor_id must be a string")
    activity = base_entity()
    activity.update({
        "activity_name": activity_name,
        "business_unit": business_unit,
        "notice_scope": notice_scope,
        "data_element_ids": list(element_ids),
        "vendor_id": vendor_id,
        "risk_score": 0,
        "pia_required": False,
        "status": "DRAFT",
    })
    activity["risk_score"] = screening_score(activity)
    activity["pia_required"] = activity["risk_score"] >= PIA_RISK_THRESHOLD
    db.activities[activity["id"]] = activity
    if activity["pia_required"]:
        create_assessment(activity, "RISK_THRESHOLD")
    return success(ser_activity(activity), 201)


@bp.get("/privacy/processing-activities")
def list_activities():
    require_roles(*STAFF_ROLES)
    items = created_asc(list(db.activities.values()))
    status = request.args.get("status")
    vendor_id = request.args.get("vendor_id")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if vendor_id is not None:
        items = [a for a in items if a["vendor_id"] == vendor_id]
    return list_response(items, ser_activity)


@bp.get("/privacy/processing-activities/<activity_id>")
def get_activity(activity_id):
    require_roles(*STAFF_ROLES)
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    return success(ser_activity(activity), 200)


@bp.post("/privacy/processing-activities/<activity_id>/activate")
def activate_activity(activity_id):
    require_roles("DataSteward")
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    if activity["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a DRAFT activity can be activated")
    if activity["pia_required"]:
        approved = any(a["activity_id"] == activity_id and a["status"] == "APPROVED"
                       for a in db.assessments.values())
        if not approved:
            raise ApiError("ERR_PIA_NOT_APPROVED",
                           "pia_required activity needs an APPROVED assessment")
    has_documented = any(p["activity_id"] == activity_id and p["status"] == "DOCUMENTED"
                         for p in db.purposes.values())
    if not has_documented:
        raise ApiError("ERR_NO_DOCUMENTED_PURPOSE",
                       "activation needs at least one DOCUMENTED purpose")
    activity["status"] = "ACTIVE"
    touch(activity)
    return success(ser_activity(activity), 200)


@bp.post("/privacy/processing-activities/<activity_id>/resume")
def resume_activity(activity_id):
    require_roles("DataSteward")
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    if activity["status"] != "COMPLIANCE_HOLD":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a COMPLIANCE_HOLD activity can be resumed")
    has_stale = any(p["activity_id"] == activity_id and p["status"] == "CONSENT_STALE"
                    for p in db.purposes.values())
    if has_stale:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "activity has purposes in CONSENT_STALE")
    if has_open_assessment(activity_id):
        raise ApiError("ERR_PIA_NOT_APPROVED",
                       "an open assessment exists for this activity")
    activity["status"] = "ACTIVE"
    touch(activity)
    reinstate_transfers_for_activity(activity_id)
    return success(ser_activity(activity), 200)


@bp.post("/privacy/processing-activities/<activity_id>/retire")
def retire_activity(activity_id):
    require_roles("DataSteward")
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    if activity["status"] not in ("ACTIVE", "COMPLIANCE_HOLD"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an ACTIVE or COMPLIANCE_HOLD activity can be retired")
    activity["status"] = "RETIRED"
    touch(activity)
    suspend_transfers_for_activity(activity_id)
    return success(ser_activity(activity), 200)


# --- Purpose ----------------------------------------------------------------------

@bp.post("/privacy/processing-activities/<activity_id>/purposes")
def create_purpose(activity_id):
    require_roles("DataSteward")
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    body = get_body()
    retention_policy_id = body.get("retention_policy_id")
    if (isinstance(retention_policy_id, str)
            and retention_policy_id not in db.retention_policies):
        raise ApiError("ERR_NOT_FOUND", "retention policy not found")
    if activity["status"] == "RETIRED":
        raise ApiError("ERR_ACTIVITY_RETIRED",
                       "cannot create a purpose on a RETIRED activity")
    legal_basis = body.get("legal_basis")
    pinned_notice_id = None
    if legal_basis == "CONSENT":
        notice = select_current_published_notice(activity["notice_scope"])
        if notice is None:
            raise ApiError("ERR_NO_PUBLISHED_NOTICE",
                           "no PUBLISHED notice in the activity's notice_scope")
        pinned_notice_id = notice["id"]
    purpose_type = body.get("purpose_type")
    if purpose_type not in PURPOSE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid purpose_type")
    if legal_basis not in LEGAL_BASES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid legal_basis")
    if not isinstance(retention_policy_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "retention_policy_id is required")
    policy = db.retention_policies[retention_policy_id]
    purpose = base_entity()
    purpose.update({
        "activity_id": activity_id,
        "purpose_type": purpose_type,
        "legal_basis": legal_basis,
        "retention_policy_id": retention_policy_id,
        "pinned_notice_id": pinned_notice_id,
        "retention_expires_at": add_days(purpose["created_at"],
                                         policy["duration_days"]),
        "status": "DOCUMENTED",
    })
    db.purposes[purpose["id"]] = purpose
    return success(ser_purpose(purpose), 201)


@bp.get("/privacy/processing-activities/<activity_id>/purposes")
def list_activity_purposes(activity_id):
    require_roles(*STAFF_ROLES)
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    items = created_asc([p for p in db.purposes.values()
                         if p["activity_id"] == activity_id])
    return list_response(items, ser_purpose)


@bp.get("/privacy/purposes/<purpose_id>")
def get_purpose(purpose_id):
    require_roles(*STAFF_ROLES)
    purpose = db.purposes.get(purpose_id)
    if purpose is None:
        raise ApiError("ERR_NOT_FOUND", "purpose not found")
    return success(ser_purpose(purpose), 200)


@bp.get("/privacy/purposes")
def list_purposes():
    require_roles(*STAFF_ROLES)
    items = created_asc(list(db.purposes.values()))
    activity_id = request.args.get("activity_id")
    retention_policy_id = request.args.get("retention_policy_id")
    pinned_notice_id = request.args.get("pinned_notice_id")
    if activity_id is not None:
        items = [p for p in items if p["activity_id"] == activity_id]
    if retention_policy_id is not None:
        items = [p for p in items if p["retention_policy_id"] == retention_policy_id]
    if pinned_notice_id is not None:
        items = [p for p in items if p["pinned_notice_id"] == pinned_notice_id]
    return list_response(items, ser_purpose)


@bp.post("/privacy/purposes/<purpose_id>/relink")
def relink_purpose(purpose_id):
    require_roles("DataSteward")
    purpose = db.purposes.get(purpose_id)
    if purpose is None:
        raise ApiError("ERR_NOT_FOUND", "purpose not found")
    if purpose["status"] != "CONSENT_STALE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a CONSENT_STALE purpose can be relinked")
    activity = db.activities.get(purpose["activity_id"])
    notice = select_current_published_notice(activity["notice_scope"])
    if notice is None:
        raise ApiError("ERR_NO_PUBLISHED_NOTICE",
                       "no PUBLISHED notice in the activity's notice_scope")
    purpose["status"] = "DOCUMENTED"
    purpose["pinned_notice_id"] = notice["id"]
    touch(purpose)
    maybe_resume_activity(activity)
    return success(ser_purpose(purpose), 200)


@bp.post("/privacy/purposes/<purpose_id>/retire")
def retire_purpose(purpose_id):
    require_roles("DataSteward")
    purpose = db.purposes.get(purpose_id)
    if purpose is None:
        raise ApiError("ERR_NOT_FOUND", "purpose not found")
    if purpose["status"] not in ("DOCUMENTED", "CONSENT_STALE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a DOCUMENTED or CONSENT_STALE purpose can be retired")
    purpose["status"] = "RETIRED"
    touch(purpose)
    return success(ser_purpose(purpose), 200)


# --- PrivacyImpactAssessment -----------------------------------------------------

@bp.post("/privacy/processing-activities/<activity_id>/assessments")
def create_assessment_manual(activity_id):
    require_roles("DataSteward")
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    if activity["status"] == "RETIRED":
        raise ApiError("ERR_ACTIVITY_RETIRED",
                       "cannot create an assessment on a RETIRED activity")
    if has_open_assessment(activity_id):
        raise ApiError("ERR_OPEN_ASSESSMENT_EXISTS",
                       "an open assessment already exists for this activity")
    assessment = create_assessment(activity, "MANUAL")
    return success(ser_assessment(assessment), 201)


@bp.get("/privacy/processing-activities/<activity_id>/assessments")
def list_activity_assessments(activity_id):
    require_roles(*STAFF_ROLES)
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_NOT_FOUND", "processing activity not found")
    items = created_asc([a for a in db.assessments.values()
                         if a["activity_id"] == activity_id])
    return list_response(items, ser_assessment)


@bp.get("/privacy/assessments/<assessment_id>")
def get_assessment(assessment_id):
    require_roles(*STAFF_ROLES)
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        raise ApiError("ERR_NOT_FOUND", "assessment not found")
    return success(ser_assessment(assessment), 200)


@bp.post("/privacy/assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    uid, _ = require_roles("BusinessOwner")
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        raise ApiError("ERR_NOT_FOUND", "assessment not found")
    if assessment["status"] not in ("TRIGGERED", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "assessment must be TRIGGERED or CHANGES_REQUESTED")
    assessment["status"] = "IN_REVIEW"
    assessment["submitted_by_user_id"] = uid
    touch(assessment)
    return success(ser_assessment(assessment), 200)


def _review_guard(assessment_id, uid):
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        raise ApiError("ERR_NOT_FOUND", "assessment not found")
    if assessment["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "assessment must be IN_REVIEW")
    if uid == assessment["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "reviewer must differ from the most recent submitter")
    return assessment


@bp.post("/privacy/assessments/<assessment_id>/approve")
def approve_assessment(assessment_id):
    uid, _ = require_roles("LegalCounsel")
    assessment = _review_guard(assessment_id, uid)
    activity = db.activities.get(assessment["activity_id"])
    assessment["final_score"] = comprehensive_score(activity)
    assessment["status"] = "APPROVED"
    touch(assessment)
    maybe_resume_activity(activity)
    return success(ser_assessment(assessment), 200)


@bp.post("/privacy/assessments/<assessment_id>/request-changes")
def request_changes_assessment(assessment_id):
    uid, _ = require_roles("LegalCounsel")
    assessment = _review_guard(assessment_id, uid)
    assessment["status"] = "CHANGES_REQUESTED"
    touch(assessment)
    return success(ser_assessment(assessment), 200)


@bp.post("/privacy/assessments/<assessment_id>/reject")
def reject_assessment(assessment_id):
    uid, _ = require_roles("LegalCounsel")
    assessment = _review_guard(assessment_id, uid)
    assessment["status"] = "REJECTED"
    touch(assessment)
    return success(ser_assessment(assessment), 200)
