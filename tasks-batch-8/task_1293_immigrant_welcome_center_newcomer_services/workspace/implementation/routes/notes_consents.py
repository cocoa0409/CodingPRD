"""Case notes (sensitivity/clearance/redaction) and consents."""
from flask import Blueprint, request

import db
import services
from auth import require, get_or_404, staff_clearance
from envelope import ok, ok_list, paginate
from errors import ApiError, bad_request, forbidden, invalid_state
from util import body_json, req_str, req_enum, req_present, opt_datetime

bp = Blueprint("notes_consents", __name__)

SENSITIVITY_LEVEL = {"STANDARD": 1, "CONFIDENTIAL": 2, "SEALED": 3}
CONSENT_SCOPES = {"REFERRAL_SHARE", "ACCOMPANIMENT", "DATA_REPORTING"}


# ---------------------------------------------------------------------------
# Case notes
# ---------------------------------------------------------------------------

def _can_read(note, user_id):
    """Clearance-or-authorship rule, applied per note."""
    if note["author_id"] == user_id:
        return True
    clearance = staff_clearance(user_id)
    if clearance is None:
        return False
    return clearance >= SENSITIVITY_LEVEL[note["sensitivity"]]


def _note_view(note, user_id):
    out = db.pub(note)
    if note["redaction_status"] == "REDACTED":
        out["body"] = None
    return out


@bp.route("/case-notes", methods=["POST"])
def create_note():
    user_id, role = require("IntakeSpecialist", "CaseManager", "CenterAdmin")
    data = body_json()

    # rung 3: body-referenced ids
    case_id = data.get("case_id")
    case = None
    if case_id is not None:
        if not isinstance(case_id, str):
            raise bad_request("case_id must be a string")
        case = get_or_404("cases", case_id, "case")

    # rung 4: CLOSED cases reject child-service writes
    if case is not None and case["service_status"] == "CLOSED":
        raise invalid_state("case is CLOSED")

    # rung 5: SEALED posture blocks note creation by non-CenterAdmin
    if (case is not None and case["privacy_posture"] == "SEALED"
            and role != "CenterAdmin"):
        raise ApiError("ERR_PRIVACY_SEALED", 409,
                       "case is SEALED; notes are CenterAdmin-only")

    # rung 5: sensitivity may not exceed the author's clearance
    sensitivity = data.get("sensitivity")
    if isinstance(sensitivity, str) and sensitivity in SENSITIVITY_LEVEL:
        clearance = staff_clearance(user_id)
        if clearance is None:
            raise forbidden("author is not a known staff member")
        if SENSITIVITY_LEVEL[sensitivity] > clearance:
            raise ApiError("ERR_CLEARANCE_INSUFFICIENT", 403,
                           "note sensitivity exceeds author clearance")

    # rung 7: structural
    req_present(data, "case_id")
    sensitivity = req_enum(data, "sensitivity", set(SENSITIVITY_LEVEL))
    body = req_present(data, "body")
    if not isinstance(body, str):
        raise bad_request("body must be a string")
    if len(body) < 1 or len(body) > 10000:
        raise ApiError("ERR_NOTE_TOO_LONG", 422,
                       "note body must be 1..10000 characters")

    note = db.new_entity("notes", {
        "case_id": case_id,
        "author_id": user_id,
        "body": body,
        "sensitivity": sensitivity,
        "redaction_status": "VISIBLE",
    })
    return ok(db.pub(note), status=201)


@bp.route("/case-notes/<note_id>", methods=["GET"])
def get_note(note_id):
    user_id, _ = require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    note = get_or_404("notes", note_id, "case note")
    if not _can_read(note, user_id):
        raise forbidden("insufficient clearance to read this note")
    return ok(_note_view(note, user_id))


@bp.route("/case-notes", methods=["GET"])
def list_notes():
    user_id, _ = require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("notes")
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [n for n in items if n["case_id"] == case_id]
    author_id = request.args.get("author_id")
    if author_id is not None:
        items = [n for n in items if n["author_id"] == author_id]
    # clearance-or-authorship applied row by row
    items = [n for n in items if _can_read(n, user_id)]
    page, meta = paginate(items)
    return ok_list([_note_view(n, user_id) for n in page], meta)


@bp.route("/case-notes/<note_id>/redact", methods=["POST"])
def redact_note(note_id):
    require("CenterAdmin")
    note = get_or_404("notes", note_id, "case note")
    data = body_json()
    reason = data.get("reason")
    if not isinstance(reason, str):
        raise bad_request("reason is required")
    if note["redaction_status"] != "VISIBLE":
        raise invalid_state("note is already REDACTED")
    note["redaction_status"] = "REDACTED"
    db.touch(note)
    return ok(_note_view(note, user_id=None))


# ---------------------------------------------------------------------------
# Consents
# ---------------------------------------------------------------------------

@bp.route("/consents", methods=["POST"])
def create_consent():
    require("IntakeSpecialist", "CaseManager", "CenterAdmin")
    data = body_json()

    client_id = data.get("client_id")
    client = None
    if client_id is not None:
        if not isinstance(client_id, str):
            raise bad_request("client_id must be a string")
        client = get_or_404("clients", client_id, "client")

    # rung 7: structural
    req_present(data, "client_id")
    scope = req_enum(data, "scope", CONSENT_SCOPES)
    expires_at = opt_datetime(data, "expires_at", None)

    # rung 9: EXITED clients may not receive new consents
    if client["status"] == "EXITED":
        raise ApiError("ERR_CLIENT_EXITED", 409,
                       "client has exited services")

    consent = db.new_entity("consents", {
        "client_id": client_id,
        "scope": scope,
        "status": "GRANTED",
        "expires_at": expires_at,
        "revoked_reason": None,
    })
    if scope == "DATA_REPORTING":
        services.recompute_reportable(client_id)
    return ok(db.pub(consent), status=201)


@bp.route("/consents/<consent_id>", methods=["GET"])
def get_consent(consent_id):
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "Client")
    consent = get_or_404("consents", consent_id, "consent")
    if role == "Client" and consent["client_id"] != user_id:
        raise forbidden("clients may read only their own consents")
    return ok(db.pub(consent))


@bp.route("/consents", methods=["GET"])
def list_consents():
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "Client")
    items = db.all_of("consents")
    if role == "Client":
        items = [c for c in items if c["client_id"] == user_id]
    for param in ("client_id", "scope", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if str(c.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(c) for c in page], meta)


@bp.route("/consents/<consent_id>/revoke", methods=["POST"])
def revoke_consent(consent_id):
    user_id, role = require("CaseManager", "CenterAdmin", "Client")
    consent = get_or_404("consents", consent_id, "consent")
    if role == "Client" and consent["client_id"] != user_id:
        raise forbidden("clients may revoke only their own consents")
    if consent["status"] != "GRANTED":
        raise invalid_state("consent is not GRANTED")
    data = body_json()
    reason = data.get("revoked_reason")
    if reason is not None and not isinstance(reason, str):
        raise bad_request("revoked_reason must be a string")
    consent["status"] = "REVOKED"
    consent["revoked_reason"] = reason
    db.touch(consent)
    services.recompute_reportable(consent["client_id"])
    if consent["scope"] == "REFERRAL_SHARE":
        services.referral_share_cascade(consent["client_id"])
    return ok(db.pub(consent))
