"""The four-tier escalation ladder and the bed-return conversion (PRD 3.8)."""

from flask import Blueprint

import clock
import derived
import envelope
import ladder
import serializers
import store
from domain import escalations as escalation_service
from domain import episodes as episode_cascades
from routes.common import apply_filter, endpoint
from store import DB

bp = Blueprint("escalations", __name__)

REASONS = ("VITALS_OUT_OF_RANGE", "PATIENT_REQUEST", "TELEMETRY_LOSS", "MEDICATION_FAILURE", "FALL")
ESCALATION_LIST_ROLES = [
    "ProgramAdmin", "AdmittingPhysician", "FieldNurse", "CommunityParamedic",
]
ANSWER_ROLES = ["FieldNurse", "AdmittingPhysician", "CommunityParamedic"]


@endpoint(bp, "/escalation-events", ["POST"],
          ["FieldNurse", "CommunityParamedic", "ProgramAdmin"])
def create_escalation(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["episode_id", "reason", "opened_by_user_id"])
    # rung 4b
    ladder.check_enum(body, "reason", REASONS)
    # rung 4c
    ladder.check_string(body, "opened_by_user_id")
    # rung 5
    episode = ladder.body_episode(body)

    row = escalation_service.open_escalation(episode, body["reason"], body["opened_by_user_id"])
    return envelope.ObjResult(row, serializers.escalation_event, 201)


@endpoint(bp, "/episodes/<episode_id>/escalation-events", ["GET"], ESCALATION_LIST_ROLES)
def list_escalations(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [e for e in DB.escalations.values() if e["episode_id"] == episode_id]
    rows = apply_filter(rows, "status")
    return envelope.ListResult(store.ordered(rows), serializers.escalation_event, limit, offset)


@endpoint(bp, "/escalation-events/<escalation_id>/acknowledge", ["POST"], ANSWER_ROLES)
def acknowledge(caller, escalation_id):
    # rung 3
    escalation = ladder.path_row("escalations", escalation_id)
    # rung 7 -- permitted only from an OPEN tier while the clock is at or
    # before ack_deadline_at.
    ladder.require_state(escalation["status"] in escalation_service.OPEN_STATES)
    deadline = clock.parse_iso(escalation["ack_deadline_at"])
    ladder.require_state(clock.now_dt() <= deadline)

    escalation["status"] = "TIER%d_ACKED" % escalation["current_tier"]
    escalation["acknowledged_by_user_id"] = caller.user_id
    store.touch(escalation)
    return envelope.ObjResult(escalation, serializers.escalation_event, 200)


@endpoint(bp, "/escalation-events/<escalation_id>/promote", ["POST"],
          ["ProgramAdmin", "FieldNurse"])
def promote(caller, escalation_id):
    # rung 3
    escalation = ladder.path_row("escalations", escalation_id)
    # rung 7 -- there is no rung above tier 4
    ladder.require_state(escalation["current_tier"] < 4)
    ladder.require_state(
        escalation["status"] in escalation_service.OPEN_STATES
        or escalation["status"] in escalation_service.ACKED_STATES
    )
    if escalation["status"] in escalation_service.OPEN_STATES:
        deadline = clock.parse_iso(escalation["ack_deadline_at"])
        ladder.require_state(clock.now_dt() > deadline)

    episode = DB.episodes[escalation["episode_id"]]
    escalation_service.promote(escalation, episode)
    return envelope.ObjResult(escalation, serializers.escalation_event, 200)


@endpoint(bp, "/escalation-events/<escalation_id>/resolve", ["POST"], ANSWER_ROLES)
def resolve(caller, escalation_id):
    # rung 3
    escalation = ladder.path_row("escalations", escalation_id)
    # rung 7
    ladder.require_state(escalation["status"] in escalation_service.ACKED_STATES)
    episode = DB.episodes[escalation["episode_id"]]
    escalation_service.resolve(escalation, episode)
    return envelope.ObjResult(escalation, serializers.escalation_event, 200)


@endpoint(bp, "/escalation-events/<escalation_id>/convert-bed-return", ["POST"],
          ["AdmittingPhysician"])
def convert_bed_return(caller, escalation_id):
    # rung 3
    escalation = ladder.path_row("escalations", escalation_id)
    # rung 7 -- three preconditions, all ERR_INVALID_STATE
    ladder.require_state(escalation["status"] in ("TIER3_ACKED", "TIER4_OPEN", "TIER4_ACKED"))
    episode = DB.episodes[escalation["episode_id"]]
    ladder.require_state(episode["status"] == "ESCALATED")
    held = [r for r in derived.episode_reservations(episode["id"]) if r["status"] == "HELD"]
    ladder.require_state(len(held) > 0)

    episode_cascades.convert_to_bed_return(escalation, episode)
    return envelope.ObjResult(escalation, serializers.escalation_event, 200)
