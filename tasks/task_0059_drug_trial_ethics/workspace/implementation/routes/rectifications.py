from __future__ import annotations

"""Rectification endpoints."""

from flask import Blueprint, g

import db
from clock import iso, now, parse_iso
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RECTIFICATION_EXPIRED,
    raise_error,
)
from middleware import ensure_owns_application, require_role
from response import success_object
from serializers import serialize_rectification
import services_state as svc
from validation import (
    check_version,
    get_json_body,
    require_string,
)


bp = Blueprint("rectifications", __name__)


# ---------------------------------------------------------------------------
# GET /ethics/rectifications/{id}
# ---------------------------------------------------------------------------
@bp.get("/ethics/rectifications/<rid>")
def get_rectification(rid):
    require_role({"Secretary", "Chairperson", "CommitteeMember", "Applicant"})
    r = db.rectifications.get(rid)
    if not r:
        raise_error(ERR_NOT_FOUND, f"Rectification {rid} not found")
    if g.user_role == "Applicant":
        app = db.applications.get(r["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            raise_error(ERR_FORBIDDEN, "Applicant may not read this rectification")
    return success_object(serialize_rectification(r))


# ---------------------------------------------------------------------------
# POST /ethics/rectifications/{id}/respond
# ---------------------------------------------------------------------------
@bp.post("/ethics/rectifications/<rid>/respond")
def respond_rectification(rid):
    require_role({"Applicant"})
    r = db.rectifications.get(rid)
    if not r:
        raise_error(ERR_NOT_FOUND, f"Rectification {rid} not found")
    app = db.applications.get(r["application_id"])
    if not app:
        raise_error(ERR_NOT_FOUND, "Parent application not found")
    ensure_owns_application(app)

    body = get_json_body()
    resp_uri = require_string(body, "applicant_response_uri", min_len=1, max_len=2000)

    with db.lock:
        # Ownership-then-state: check state first per priority order
        if r["status"] != "OPEN":
            # Special case: if EXPIRED, return ERR_RECTIFICATION_EXPIRED per scaffold
            if r["status"] == "EXPIRED":
                raise_error(ERR_RECTIFICATION_EXPIRED,
                            "Rectification has expired")
            raise_error(ERR_INVALID_STATE,
                        f"Rectification is in '{r['status']}' (must be OPEN)")
        # Temporal check (priority 11)
        due = parse_iso(r["due_at"])
        if now() >= due:
            # Atomic sweep-style flip on race
            r["status"] = "EXPIRED"
            svc.bump(r)
            svc.write_audit(g.user_role, g.user_id, "REVIEW_DECISION",
                            "Rectification", r["id"],
                            {"event": "RECTIFICATION_EXPIRED",
                             "application_id": r["application_id"]})
            raise_error(ERR_RECTIFICATION_EXPIRED,
                        "Rectification deadline has passed")
        check_version(body, r)

        r["applicant_response_uri"] = resp_uri
        r["responded_at"] = iso()
        r["status"] = "RESPONDED"
        svc.bump(r)
    return success_object(serialize_rectification(r))
