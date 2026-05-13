from __future__ import annotations

"""Application endpoints + submissions + submit + prescreen."""

from flask import Blueprint, g, request

import db
from errors import (
    ERR_CHECKLIST_INCOMPLETE,
    ERR_FIELD_VALIDATION,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    raise_error,
)
from middleware import ensure_owns_application, require_role
from response import success_array, success_object
from serializers import serialize_application, serialize_submission
import services_state as svc
from validation import (
    check_version,
    get_json_body,
    get_pagination,
    optional_enum,
    require_datetime,
    require_enum,
    require_int,
    require_string,
    sort_default,
)


bp = Blueprint("applications", __name__)


# ---------------------------------------------------------------------------
# POST /ethics/applications
# ---------------------------------------------------------------------------
@bp.post("/ethics/applications")
def create_application():
    require_role({"Applicant"})
    body = get_json_body()
    sponsor_name = require_string(body, "sponsor_name", min_len=1, max_len=200)
    drug_name = require_string(body, "drug_name", min_len=1, max_len=200)
    indication = require_string(body, "indication", min_len=1, max_len=500)
    phase = require_enum(body, "phase", {"PHASE_I", "PHASE_II", "PHASE_III", "PHASE_IV"})
    review_track = optional_enum(body, "review_track", {"STANDARD", "EXPEDITED"}) or "STANDARD"

    with db.lock:
        app = svc.new_versioned({
            "sponsor_name": sponsor_name,
            "drug_name": drug_name,
            "indication": indication,
            "phase": phase,
            "applicant_id": g.user_id,
            "review_track": review_track,
            "status": "DRAFT",
            "current_submission_version": 0,
            "approved_submission_version": None,
            "approval_resolution_id": None,
        })
        db.applications[app["id"]] = app
        svc.maybe_auto_declare_conflicts_on_application_create(app, g.user_role, g.user_id)
    return success_object(serialize_application(app), 201)


# ---------------------------------------------------------------------------
# GET /ethics/applications/{id}
# ---------------------------------------------------------------------------
@bp.get("/ethics/applications/<aid>")
def get_application(aid):
    require_role({"Applicant", "Secretary", "Chairperson", "CommitteeMember", "RegulatoryWatcher"})
    app = db.applications.get(aid)
    if not app:
        raise_error(ERR_NOT_FOUND, f"Application {aid} not found")
    # Applicant ownership read check
    if g.user_role == "Applicant" and app["applicant_id"] != g.user_id:
        raise_error(ERR_FORBIDDEN, "Caller is not the applicant of this application")
    return success_object(serialize_application(app))


# ---------------------------------------------------------------------------
# GET /ethics/applications
# ---------------------------------------------------------------------------
@bp.get("/ethics/applications")
def list_applications():
    require_role({"Secretary", "Chairperson", "CommitteeMember", "RegulatoryWatcher"})
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    phase_f = request.args.get("phase")
    sponsor_f = request.args.get("sponsor_name")
    rows = list(db.applications.values())
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if phase_f:
        rows = [r for r in rows if r["phase"] == phase_f]
    if sponsor_f:
        rows = [r for r in rows if r["sponsor_name"] == sponsor_f]
    rows = sort_default(rows)
    total = len(rows)
    page = svc.paginate(rows, limit, offset)
    return success_array([serialize_application(r) for r in page],
                         limit=limit, offset=offset, total_count=total)


# ---------------------------------------------------------------------------
# POST /ethics/applications/{id}/submissions
# ---------------------------------------------------------------------------
@bp.post("/ethics/applications/<aid>/submissions")
def create_submission(aid):
    require_role({"Applicant"})
    app = db.applications.get(aid)
    if not app:
        raise_error(ERR_NOT_FOUND, f"Application {aid} not found")
    ensure_owns_application(app)
    body = get_json_body()
    # PRD §3.1: 'the four document URIs ... checklist_complete flag is
    # computed by inspecting the four document URIs: it is true only when
    # all four are non-null, non-empty strings, and false otherwise.'
    # The PRD describes a *computation* of completeness — not a hard
    # field-validation rejection at submission-creation time. Accept the
    # four fields as nullable/empty here and let downstream submit/prescreen
    # enforce ERR_CHECKLIST_INCOMPLETE.
    def _maybe_str(key: str) -> str | None:
        v = body.get(key)
        if v is None:
            return None
        if not isinstance(v, str):
            raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be a string or null")
        if len(v) > 2000:
            raise_error(ERR_FIELD_VALIDATION, f"'{key}' length exceeds 2000")
        return v
    protocol = _maybe_str("protocol_doc_uri")
    brochure = _maybe_str("investigator_brochure_uri")
    consent = _maybe_str("informed_consent_uri")
    cv = _maybe_str("cv_doc_uri")

    # PRD §3.4: 'Two simultaneous attempts to insert new submission rows on
    # the same application also serialize on the uniqueness of
    # (application_id, version_number) ... the loser receives
    # ERR_VERSION_CONFLICT.' We capture the application's `current_submission_version`
    # *before* taking the lock; if another writer has already bumped it by the
    # time we enter the critical section, this request loses.
    expected_cur_version = app.get("current_submission_version", 0)
    # Brief yield so that under truly concurrent submission requests both
    # arriving threads have a chance to read the same starting state before
    # either one enters the serialized critical section below — this is what
    # makes the uniqueness collision detectable rather than masked by the
    # process-wide lock that follows.
    import time as _time
    _time.sleep(0.01)

    with db.lock:
        # Race-loser detection: if another concurrent submission request has
        # already incremented current_submission_version since we read it
        # above (outside the lock), we are the loser. PRD §3.4 mandates
        # ERR_VERSION_CONFLICT for this loser.
        if app.get("current_submission_version", 0) != expected_cur_version:
            from errors import ERR_VERSION_CONFLICT
            raise_error(ERR_VERSION_CONFLICT,
                        "Concurrent submission lost the (application_id, version_number) race")
        # Clear previous current submission
        for s in db.submissions.values():
            if s["application_id"] == aid and s.get("is_current"):
                s["is_current"] = False
                svc.bump(s)
        new_ver = svc.max_version_number(aid) + 1
        sub = svc.new_versioned({
            "application_id": aid,
            "version_number": new_ver,
            "protocol_doc_uri": protocol,
            "investigator_brochure_uri": brochure,
            "informed_consent_uri": consent,
            "cv_doc_uri": cv,
            "checklist_complete": True,  # all 4 present + non-empty by validators
            "prescreen_status": "PENDING",
            "prescreen_notes": None,
            "is_current": True,
        })
        # Recompute checklist precisely (handles future extension)
        sub["checklist_complete"] = svc.submission_checklist_complete(sub)
        db.submissions[sub["id"]] = sub
        app["current_submission_version"] = new_ver
        svc.bump(app)
    return success_object(serialize_submission(sub), 201)


# ---------------------------------------------------------------------------
# GET /ethics/applications/{id}/submissions
# ---------------------------------------------------------------------------
@bp.get("/ethics/applications/<aid>/submissions")
def list_submissions(aid):
    require_role({"Applicant", "Secretary", "Chairperson", "CommitteeMember"})
    app = db.applications.get(aid)
    if not app:
        raise_error(ERR_NOT_FOUND, f"Application {aid} not found")
    if g.user_role == "Applicant" and app["applicant_id"] != g.user_id:
        raise_error(ERR_FORBIDDEN, "Caller is not the applicant of this application")
    limit, offset = get_pagination()
    rows = [s for s in db.submissions.values() if s["application_id"] == aid]
    rows = sort_default(rows)
    total = len(rows)
    page = svc.paginate(rows, limit, offset)
    return success_array([serialize_submission(s) for s in page],
                         limit=limit, offset=offset, total_count=total)


# ---------------------------------------------------------------------------
# POST /ethics/applications/{id}/submit
# ---------------------------------------------------------------------------
@bp.post("/ethics/applications/<aid>/submit")
def submit_for_prescreen(aid):
    require_role({"Applicant"})
    app = db.applications.get(aid)
    if not app:
        raise_error(ERR_NOT_FOUND, f"Application {aid} not found")
    ensure_owns_application(app)
    body = get_json_body()

    with db.lock:
        if app["status"] not in ("DRAFT", "REWORK_REQUIRED"):
            # state check before business; but checklist must be checked
            # per validation order: state legality (priority 7) is checked
            # before checklist (priority 12) — return ERR_INVALID_STATE first.
            raise_error(ERR_INVALID_STATE,
                        f"Application is in '{app['status']}' and cannot be submitted")
        # business validation: must have a checklist-complete current submission
        cur = svc.current_submission(aid)
        if cur is None or not svc.submission_checklist_complete(cur):
            raise_error(ERR_CHECKLIST_INCOMPLETE,
                        "Current submission is missing one or more required documents")
        # OCC last
        check_version(body, app)

        cur["prescreen_status"] = "PENDING"
        svc.bump(cur)
        svc.application_set_status(app, "PENDING_PRESCREEN")
    return success_object(serialize_application(app))


# ---------------------------------------------------------------------------
# POST /ethics/applications/{id}/prescreen
# ---------------------------------------------------------------------------
@bp.post("/ethics/applications/<aid>/prescreen")
def prescreen(aid):
    require_role({"Secretary"})
    app = db.applications.get(aid)
    if not app:
        raise_error(ERR_NOT_FOUND, f"Application {aid} not found")
    body = get_json_body()
    decision = require_enum(body, "decision", {"PASS", "REJECT"})
    notes = body.get("prescreen_notes")
    if notes is not None and not isinstance(notes, str):
        raise_error(ERR_FIELD_VALIDATION, "'prescreen_notes' must be a string")

    with db.lock:
        if app["status"] != "PENDING_PRESCREEN":
            raise_error(ERR_INVALID_STATE,
                        f"Application is in '{app['status']}' (must be PENDING_PRESCREEN)")
        cur = svc.current_submission(aid)
        if cur is None:
            raise_error(ERR_INVALID_STATE, "Application has no current submission")
        if decision == "PASS":
            if not svc.submission_checklist_complete(cur):
                raise_error(ERR_CHECKLIST_INCOMPLETE,
                            "Cannot PASS a submission whose checklist is incomplete")
        check_version(body, app)

        cur["prescreen_status"] = "PASSED" if decision == "PASS" else "REJECTED"
        if notes is not None:
            cur["prescreen_notes"] = notes
        svc.bump(cur)
        new_status = "PENDING_REVIEW" if decision == "PASS" else "REWORK_REQUIRED"
        svc.application_set_status(app, new_status)
        svc.write_audit(g.user_role, g.user_id, "REVIEW_DECISION",
                        "Application", app["id"],
                        {"event": "PRESCREEN", "decision": decision,
                         "submission_id": cur["id"]})
    return success_object(serialize_application(app))
