from __future__ import annotations

"""RiskIncident routes."""
from flask import Blueprint, request

import db
import errors as E
import response
import serializers as S
from middleware import require_auth
from services import chapter_service as cs
from services import pagination as P
from services import validation as V


bp = Blueprint("risk_incidents", __name__)


def _risk_incident_or_404(rid: str) -> dict:
    if rid not in db.risk_incidents:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"RiskIncident {rid} not found")
    return db.risk_incidents[rid]


@bp.route("/rush/risk-incidents", methods=["POST"])
@require_auth(["RiskOfficer"])
def create_risk_incident():
    body = request.get_json(silent=True) or {}
    chapter_id = V.require_string(body, "chapter_id")
    party_id = V.optional_string(body, "party_id")
    severity = V.require_int(body, "severity_points", min_val=1, max_val=10)
    reason = V.require_string(body, "reason", min_len=1, max_len=200)

    if chapter_id not in db.chapters:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"chapter_id {chapter_id} not found")
    if party_id is not None and party_id not in db.parties:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"party_id {party_id} not found")

    now = db.now_utc()
    rid = db.new_id()
    ri = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "chapter_id": chapter_id,
        "party_id": party_id,
        "severity_points": severity,
        "status": "ACTIVE",
        "reason": reason,
    }
    db.risk_incidents[rid] = ri

    cs.recompute_risk(chapter_id)
    cs.bump_chapter_version(chapter_id)

    return response.success_object(S.risk_incident(ri), status=201)


@bp.route("/rush/risk-incidents/<rid>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RiskOfficer"])
def get_risk_incident(rid):
    ri = _risk_incident_or_404(rid)
    return response.success_object(S.risk_incident(ri))


@bp.route("/rush/risk-incidents/<rid>/dismiss", methods=["POST"])
@require_auth(["RiskOfficer"])
def dismiss_risk_incident(rid):
    ri = _risk_incident_or_404(rid)
    if ri["status"] != "ACTIVE":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"RiskIncident status is {ri['status']}, cannot dismiss",
        )

    ri["status"] = "DISMISSED"
    cs.bump_risk_incident_version(rid)

    cs.recompute_risk(ri["chapter_id"])
    cs.bump_chapter_version(ri["chapter_id"])

    return response.success_object(S.risk_incident(ri))
