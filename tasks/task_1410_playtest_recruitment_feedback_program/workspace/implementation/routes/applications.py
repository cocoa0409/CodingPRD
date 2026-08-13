"""Screening application endpoints with two-pass fit score."""

from datetime import timedelta

import db
from db import _format_iso
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import get_payload, require_string, stamp_new, touch, optional_string
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_STUDY_NOT_RECRUITING, ERR_PARTICIPANT_NOT_ACTIVE, ERR_DUPLICATE_APPLICATION,
    ERR_NDA_NOT_PUBLISHED, ERR_COHORT_FULL, ERR_FIT_SCORE_BELOW_THRESHOLD,
)
from services.serializers import public
from services.calculations import screening_fit_score, FIT_PASS_THRESHOLD

bp = make_blueprint("applications")

_LIVE_APPLICATION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "ENROLLED")


def _get_application(aid):
    a = db.applications.get(aid)
    if a is None:
        raise_error(ERR_NOT_FOUND, "Application not found")
    return a


def _get_study(sid):
    s = db.studies.get(sid)
    if s is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    return s


def _published_agreement(study_id):
    for a in db.nda_agreements.values():
        if a["study_id"] == study_id and a["status"] == "PUBLISHED":
            return a
    return None


@bp.route("/playtests/applications", methods=["POST"])
def create_application():
    user_id, _role = require_roles("Participant")
    body = get_payload()
    study_id = require_string(body, "study_id")
    study = _get_study(study_id)

    participant = db.participants.get(user_id)
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")

    # State tier: study must be RECRUITING; participant must be ACTIVE
    if study["status"] != "RECRUITING":
        raise_error(ERR_STUDY_NOT_RECRUITING, "Study is not RECRUITING")
    if participant["status"] != "ACTIVE":
        raise_error(ERR_PARTICIPANT_NOT_ACTIVE, "Participant is not ACTIVE")

    # Uniqueness: at most one non-terminal application per (study, participant)
    for a in db.applications.values():
        if (a["study_id"] == study_id and a["participant_id"] == participant["id"]
                and a["status"] in _LIVE_APPLICATION_STATUSES):
            raise_error(ERR_DUPLICATE_APPLICATION,
                        "A non-terminal application already exists for this study and participant")

    fit = screening_fit_score(participant, study, "self_reported")
    rec = {
        "study_id": study_id,
        "participant_id": participant["id"],
        "status": "SUBMITTED",
        "fit_score_provisional": fit,
        "fit_score_final": None,
        "pinned_nda_agreement_id": None,
        "info_request_note": None,
        "decision_reason": None,
    }
    stamp_new(rec)
    db.applications[rec["id"]] = rec
    return success(public(rec, "application"), status=201)


@bp.route("/playtests/applications", methods=["GET"])
def list_applications():
    require_roles("ResearchOpsAdmin", "Researcher", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.applications.values())
    for param in ("study_id", "participant_id", "status", "pinned_nda_agreement_id"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if str(a.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(a, "application") for a in page], status=200, pagination=pagination)


@bp.route("/playtests/applications/<aid>", methods=["GET"])
def get_application(aid):
    require_roles("ResearchOpsAdmin", "Researcher", "Participant")
    a = _get_application(aid)
    return success(public(a, "application"), status=200)


@bp.route("/playtests/applications/<aid>/start-review", methods=["POST"])
def start_review(aid):
    require_roles("Researcher")
    a = _get_application(aid)
    if a["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Application must be SUBMITTED to start review")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success(public(a, "application"), status=200)


@bp.route("/playtests/applications/<aid>/request-info", methods=["POST"])
def request_info(aid):
    require_roles("Researcher")
    a = _get_application(aid)
    body = get_payload()
    note = require_string(body, "info_request_note")
    if a["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Application must be UNDER_REVIEW to request info")
    a["status"] = "INFO_REQUESTED"
    a["info_request_note"] = note
    touch(a)
    return success(public(a, "application"), status=200)


@bp.route("/playtests/applications/<aid>/submit-info", methods=["POST"])
def submit_info(aid):
    user_id, _role = require_roles("Participant")
    a = _get_application(aid)
    if user_id != a["participant_id"]:
        raise_error(ERR_FORBIDDEN, "Only the owning participant may submit info")
    if a["status"] != "INFO_REQUESTED":
        raise_error(ERR_INVALID_STATE, "Application must be INFO_REQUESTED to submit info")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success(public(a, "application"), status=200)


@bp.route("/playtests/applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    require_roles("Researcher")
    a = _get_application(aid)
    if a["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Application must be UNDER_REVIEW to approve")
    study = _get_study(a["study_id"])
    participant = db.participants.get(a["participant_id"])
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")

    # Fixed order of gates (PRD 3.2):
    if study["status"] != "RECRUITING":
        raise_error(ERR_STUDY_NOT_RECRUITING, "Study is not RECRUITING")
    agreement = _published_agreement(study["id"])
    if agreement is None:
        raise_error(ERR_NDA_NOT_PUBLISHED, "No PUBLISHED NDA agreement exists for the study")
    if study["enrolled_count"] >= study["cohort_capacity"]:
        raise_error(ERR_COHORT_FULL, "Cohort capacity reached")
    fit_final = screening_fit_score(participant, study, "verified")
    a["fit_score_final"] = fit_final
    if fit_final < FIT_PASS_THRESHOLD:
        touch(a)
        raise_error(ERR_FIT_SCORE_BELOW_THRESHOLD, "Fit score below threshold")

    a["status"] = "APPROVED"
    a["pinned_nda_agreement_id"] = agreement["id"]
    touch(a)

    # Create the PENDING NDA signature (expires in 7 days)
    expires = db.clock.now() + timedelta(days=7)
    sig = {
        "agreement_id": agreement["id"],
        "participant_id": participant["id"],
        "study_id": study["id"],
        "application_id": a["id"],
        "status": "PENDING",
        "expires_at": _format_iso(expires),
        "signed_at": None,
    }
    stamp_new(sig)
    db.nda_signatures[sig["id"]] = sig
    return success(public(a, "application"), status=200)


@bp.route("/playtests/applications/<aid>/reject", methods=["POST"])
def reject_application(aid):
    require_roles("Researcher")
    a = _get_application(aid)
    body = get_payload()
    reason = require_string(body, "decision_reason")
    if a["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Application must be UNDER_REVIEW to reject")
    a["status"] = "REJECTED"
    a["decision_reason"] = reason
    touch(a)
    return success(public(a, "application"), status=200)


@bp.route("/playtests/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    user_id, _role = require_roles("Participant")
    a = _get_application(aid)
    if user_id != a["participant_id"]:
        raise_error(ERR_FORBIDDEN, "Only the owning participant may withdraw")
    if a["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise_error(ERR_INVALID_STATE, "Application must be SUBMITTED or UNDER_REVIEW to withdraw")
    a["status"] = "WITHDRAWN"
    touch(a)
    return success(public(a, "application"), status=200)
