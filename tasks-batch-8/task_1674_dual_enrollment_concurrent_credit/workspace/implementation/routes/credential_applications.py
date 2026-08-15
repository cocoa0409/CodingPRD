"""CredentialApplication endpoints (PRD 3.3).

State machine: SUBMITTED -> UNDER_REVIEW -> APPROVED | DENIED | NEEDS_REVISION,
NEEDS_REVISION -> SUBMITTED. Review ownership (reviewed_by) and segregation of
duties (a reviewer never decides on their own application) are priority-3 auth
checks.
"""
from flask import Blueprint

from errors import (
    raise_error,
    ERR_CREDENTIAL_APPLICATION_INVALID_STATE,
    ERR_CREDENTIAL_SELF_APPROVAL,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, public, touch
from validate import get_body, opt_str, req_str, require_body_ref, require_path_resource

bp = Blueprint("credential_applications", __name__)


@bp.post("/credential-applications")
def create_credential_application():
    caller = authorized(["Instructor"])
    body = get_body()
    # Priority 3: entity-backed ownership — the applicant is the caller.
    raw_instructor = body.get("instructor_id")
    if isinstance(raw_instructor, str) and raw_instructor != caller.user_id:
        raise_error(
            ERR_NOT_RESOURCE_OWNER,
            "instructor_id must equal the acting Instructor's X-User-ID",
        )
    instructor_id = req_str(body, "instructor_id")
    course_id = req_str(body, "course_id")
    qualification_summary = req_str(body, "qualification_summary")
    # Priority 5: body FKs in declared input order.
    require_body_ref("instructors", instructor_id, "instructor_id")
    require_body_ref("courses", course_id, "course_id")
    rec = new_record(
        "credential_applications",
        {
            "instructor_id": instructor_id,
            "course_id": course_id,
            "qualification_summary": qualification_summary,
            "status": "SUBMITTED",
            "reviewed_by": None,
            "decision_reason": None,
        },
    )
    return success_object(public(rec), status=201)


@bp.get("/credential-applications")
def list_credential_applications():
    return list_response(
        "credential_applications",
        {
            "instructor_id": arg("instructor_id"),
            "course_id": arg("course_id"),
            "status": arg("status"),
        },
    )


@bp.get("/credential-applications/<rid>")
def get_credential_application(rid):
    return get_one("credential_applications", rid)


@bp.post("/credential-applications/<rid>/begin-review")
def begin_review(rid):
    caller = authorized(["CredentialReviewer"])
    app = require_path_resource("credential_applications", rid)
    if app["status"] != "SUBMITTED":
        raise_error(
            ERR_CREDENTIAL_APPLICATION_INVALID_STATE,
            "only a SUBMITTED application can be claimed for review",
        )
    app["status"] = "UNDER_REVIEW"
    app["reviewed_by"] = caller.user_id  # claim review ownership
    touch(app)
    return success_object(public(app))


def _decision(rid, new_status, record_reason):
    """UNDER_REVIEW decision calls: approve / deny / request-revision.

    Priority 3 ownership (caller == reviewed_by), then priority 3 segregation
    of duties (caller != instructor_id), then priority 6 state."""
    caller = authorized(["CredentialReviewer"])
    app = require_path_resource("credential_applications", rid)
    if app["reviewed_by"] != caller.user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER, "only the review owner may decide")
    if app["instructor_id"] == caller.user_id:
        raise_error(
            ERR_CREDENTIAL_SELF_APPROVAL,
            "a reviewer may not decide on their own credential application",
        )
    if app["status"] != "UNDER_REVIEW":
        raise_error(
            ERR_CREDENTIAL_APPLICATION_INVALID_STATE,
            "application is not UNDER_REVIEW",
        )
    if record_reason:
        reason = opt_str(get_body(), "decision_reason")
        if reason is not None:
            app["decision_reason"] = reason
    app["status"] = new_status
    touch(app)
    return success_object(public(app))


@bp.post("/credential-applications/<rid>/approve")
def approve(rid):
    return _decision(rid, "APPROVED", record_reason=True)


@bp.post("/credential-applications/<rid>/deny")
def deny(rid):
    return _decision(rid, "DENIED", record_reason=True)


@bp.post("/credential-applications/<rid>/request-revision")
def request_revision(rid):
    return _decision(rid, "NEEDS_REVISION", record_reason=True)


@bp.post("/credential-applications/<rid>/resubmit")
def resubmit(rid):
    caller = authorized(["Instructor"])
    app = require_path_resource("credential_applications", rid)
    # Priority 3: the applicant only.
    if app["instructor_id"] != caller.user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER, "only the applicant may resubmit")
    if app["status"] != "NEEDS_REVISION":
        raise_error(
            ERR_CREDENTIAL_APPLICATION_INVALID_STATE,
            "only a NEEDS_REVISION application can be resubmitted",
        )
    app["status"] = "SUBMITTED"
    app["reviewed_by"] = None  # review ownership released
    touch(app)
    return success_object(public(app))
