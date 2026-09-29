"""AccreditationAudit scheduling, reads and progressions."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("audits", __name__)

SCOPES = ("FULL", "ANIMAL_CARE_ONLY", "LIFE_SUPPORT_ONLY")
STATUSES = ("SCHEDULED", "IN_PROGRESS", "PASSED", "CONDITIONAL", "FAILED", "CANCELLED")
ACTIONS = ("START", "CLOSE", "REOPEN", "CANCEL")
LEGAL_ACTIONS = {
    "SCHEDULED": ("START", "CANCEL"),
    "IN_PROGRESS": ("CLOSE",),
    "CONDITIONAL": ("REOPEN",),
}

AUDIT_COMPUTED = (
    "status", "readiness_score", "domain_subscores", "blocking_finding_count",
    "opened_by_user_id", "closed_by_user_id", "started_at", "closed_at", "determination_note",
)
PROGRESSION_COMPUTED = tuple(f for f in AUDIT_COMPUTED if f != "determination_note")


@bp.route("/aquarium/accreditation-audits", methods=["POST"])
def create_audit():
    M.authenticate({M.DIRECTOR})
    body = M.json_body()
    V.reject_computed(body, AUDIT_COMPUTED)
    audit_code = V.as_str(body, "audit_code", required=True)
    scope = V.as_enum(body, "scope", SCOPES, required=True)
    scheduled_for = V.as_dt(body, "scheduled_for", required=True)

    for row in db.db.accreditation_audits.values():
        if row["audit_code"] == audit_code:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = db.new_row()
    row.update({
        "audit_code": audit_code,
        "scope": scope,
        "scheduled_for": scheduled_for,
        "status": "SCHEDULED",
        "readiness_score": None,
        "domain_subscores": None,
        "blocking_finding_count": 0,
        "opened_by_user_id": None,
        "closed_by_user_id": None,
        "started_at": None,
        "closed_at": None,
        "determination_note": None,
    })
    db.insert("accreditation_audits", row)
    return response.object_response(S.accreditation_audit(row), 201)


@bp.route("/aquarium/accreditation-audits", methods=["GET"])
def list_audits():
    M.authenticate(M.NON_LIAISON)
    status = M.enum_param("status", STATUSES)
    scope = M.enum_param("scope", SCOPES)
    limit, offset = M.pagination()

    def keep(row):
        if status is not None and row["status"] != status:
            return False
        if scope is not None and row["scope"] != scope:
            return False
        return True

    rows = db.ordered("accreditation_audits", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.accreditation_audit(r) for r in page], limit, offset, total)


@bp.route("/aquarium/accreditation-audits/<row_id>", methods=["GET"])
def get_audit(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("accreditation_audits", row_id)
    return response.object_response(S.accreditation_audit(row))


@bp.route("/aquarium/accreditation-audits/<row_id>/progressions", methods=["POST"])
def progress_audit(row_id):
    user_id, _role = M.authenticate({M.DIRECTOR})
    audit = M.fetch("accreditation_audits", row_id)
    body = M.json_body()
    V.reject_computed(body, PROGRESSION_COMPUTED)
    action = V.as_enum(body, "action", ACTIONS, required=True)
    note = V.as_str(body, "determination_note")

    if audit["status"] in ("PASSED", "FAILED", "CANCELLED"):
        raise ApiError("ERR_ENTITY_TERMINAL")
    if action not in LEGAL_ACTIONS.get(audit["status"], ()):
        raise ApiError("ERR_INVALID_ACTION")

    if action == "CLOSE" and user_id == audit["opened_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION")
    if action == "START" and db.db.clock < audit["scheduled_for"]:
        raise ApiError("ERR_AUDIT_NOT_DUE")

    if action in ("START", "REOPEN"):
        engine.rescore_audit_specimens()
        engine.score_audit(audit)
        audit["status"] = "IN_PROGRESS"
        audit["opened_by_user_id"] = user_id
        audit["started_at"] = db.db.clock
        audit["closed_by_user_id"] = None
        audit["closed_at"] = None
        db.touch(audit)
    elif action == "CANCEL":
        audit["status"] = "CANCELLED"
        db.touch(audit)
    else:
        audit["status"] = calc.audit_determination(
            audit["readiness_score"], int(audit["blocking_finding_count"]))
        audit["closed_by_user_id"] = user_id
        audit["closed_at"] = db.db.clock
        audit["determination_note"] = note
        db.touch(audit)

    return response.object_response(S.accreditation_audit(audit))
