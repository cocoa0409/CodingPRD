"""Append-only telemetry gaps (PRD 3.4)."""

from flask import Blueprint

import clock
import envelope
import errors
import ladder
import serializers
import store
from domain import compliance
from errors import fail
from routes.common import endpoint
from store import DB

bp = Blueprint("monitoring", __name__)

LAPSE_CAUSES = ("DEVICE_OFFLINE", "CONNECTIVITY_LOSS", "PATIENT_REMOVED", "UNKNOWN")


@endpoint(bp, "/monitoring-lapses", ["POST"], ["ProgramAdmin", "FieldNurse"])
def create_lapse(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["episode_id", "gap_start_at", "gap_end_at"])
    # rung 4b
    ladder.check_enum(body, "cause", LAPSE_CAUSES)
    # rung 4c
    start_dt = ladder.check_datetime(body, "gap_start_at")
    end_dt = ladder.check_datetime(body, "gap_end_at")
    if not (end_dt > start_dt):
        fail(errors.ERR_VALIDATION, "gap_end_at must be strictly later than gap_start_at.")
    # rung 5
    episode = ladder.body_episode(body)
    # rung 8
    ladder.require_episode_active(episode)

    row = store.make_row("lapses", {
        "episode_id": episode["id"],
        "gap_start_at": body["gap_start_at"],
        "gap_end_at": body["gap_end_at"],
        "cause": body.get("cause") or "UNKNOWN",
        "_gap_start_dt": start_dt,
        "_gap_end_dt": end_dt,
    }, audited=False)
    compliance.mint_record(episode, clock.utc_date(start_dt))
    return envelope.ObjResult(row, serializers.monitoring_lapse, 201)


@endpoint(bp, "/episodes/<episode_id>/monitoring-lapses", ["GET"],
          ["ProgramAdmin", "AdmittingPhysician", "FieldNurse"])
def list_lapses(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [l for l in DB.lapses.values() if l["episode_id"] == episode_id]
    return envelope.ListResult(store.ordered(rows), serializers.monitoring_lapse, limit, offset)
