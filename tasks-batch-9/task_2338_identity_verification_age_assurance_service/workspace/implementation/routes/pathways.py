"""Adjudication of inclusion pathways (PRD 3.7)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import response
import schema
import services
import views
from errors import fail
from schema import Field

bp = Blueprint("pathways", __name__)

DECISION_FIELDS = (
    Field("action", "string", required=True, enum=("APPROVE", "DENY")),
)

PENDING_STATES = ("VOUCH_PENDING", "ATTESTATION_PENDING")


@bp.post("/idv/alternative-pathways/<pathway_id>/decision")
def decide_pathway(pathway_id):
    caller = auth.authenticate((auth.INCLUSION_REVIEWER,))
    pathway = db.get(db.PATHWAYS, pathway_id)
    if pathway is None:
        fail("ERR_PATHWAY_NOT_FOUND")
    values = schema.validate(schema.read_body(), DECISION_FIELDS)
    session = db.get(db.SESSIONS, pathway["session_id"])

    if values["action"] == "DENY":
        if pathway["state"] not in PENDING_STATES:
            fail("ERR_PATHWAY_STATE_INVALID")
        pathway["state"] = "DENIED"
        pathway["reviewer_user_id"] = caller.user_id
        pathway["decided_at"] = clock.now()
        db.touch(pathway)
        services.append_event(session, "PATHWAY_DECIDED", caller,
                              "state, reviewer_user_id, decided_at")
        return response.object_response(views.pathway_view(pathway))

    if session is None or session["identity_state"] not in ("IN_PROGRESS", "AWAITING_EVIDENCE"):
        fail("ERR_SESSION_STATE_INVALID")
    if pathway["state"] not in PENDING_STATES:
        fail("ERR_PATHWAY_STATE_INVALID")
    services.require_not_lapsed(session)
    profile = services.select_pathway_profile()
    if profile is None:
        fail("ERR_NO_ELIGIBLE_METHOD")

    quality = (calc.VOUCHING_QUALITY_BPS if pathway["pathway_type"] == "VOUCHING"
               else calc.ATTESTATION_QUALITY_BPS)
    points = calc.contribution_points(profile["assurance_weight"], quality)
    now = clock.now()
    attempt = services.create_attempt(session, profile, "PATHWAY_GRANTED")
    attempt["state"] = "ACCEPTED"
    attempt["evidence_quality_bps"] = quality
    attempt["contribution_points"] = points
    attempt["finalized_at"] = now
    attempt["_has_evidence"] = True

    pathway["state"] = "APPROVED"
    pathway["reviewer_user_id"] = caller.user_id
    pathway["granted_points"] = points
    pathway["decided_at"] = now
    db.touch(pathway)

    if pathway["pathway_type"] == "ATTESTATION":
        session["assurance_ceiling"] = calc.ATTESTATION_CEILING
        db.touch(session)
    services.recompute_provisional(session)
    services.append_event(session, "PATHWAY_DECIDED", caller,
                          "state, reviewer_user_id, granted_points, decided_at")
    return response.object_response(views.pathway_view(pathway))
