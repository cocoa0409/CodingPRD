"""Visit scheduling and the two independent axes (PRD 3.3)."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import derived
import envelope
import errors
import ladder
import serializers
import store
from domain import compliance
from errors import fail
from routes.common import apply_filter, endpoint
from store import DB

bp = Blueprint("visits", __name__)

VISIT_TYPES = (
    "RN_IN_PERSON", "PARAMEDIC_IN_PERSON", "PHYSICIAN_IN_PERSON", "PHYSICIAN_TELEHEALTH",
)
CLOSE_OUTCOMES = ("NO_SHOW", "CANCELLED")
VISIT_ACTION_ROLES = ["FieldNurse", "CommunityParamedic", "AdmittingPhysician"]
VISIT_LIST_ROLES = [
    "ProgramAdmin", "AdmittingPhysician", "FieldNurse", "CommunityParamedic",
    "BillingAnalyst", "Patient",
]
OCCUPYING_STATES = ("SCHEDULED", "EN_ROUTE", "COMPLETED")


def _recompute_day(visit):
    """Recompute the compliance record for (episode_id, service_date)."""
    return derived.find_record(visit["episode_id"], visit["service_date"])


@endpoint(bp, "/visits", ["POST"], VISIT_ACTION_ROLES)
def create_visit(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, [
        "episode_id", "visit_type", "staff_user_id", "service_date",
        "scheduled_start_at", "scheduled_end_at", "distance_km",
    ])
    # rung 4b
    ladder.check_enum(body, "visit_type", VISIT_TYPES)
    # rung 4c
    ladder.check_string(body, "staff_user_id")
    start_dt = ladder.check_datetime(body, "scheduled_start_at")
    end_dt = ladder.check_datetime(body, "scheduled_end_at")
    ladder.check_date_string(body, "service_date")
    ladder.check_number_min(body, "distance_km", 0)
    if not (end_dt > start_dt):
        fail(errors.ERR_VALIDATION, "scheduled_end_at must be strictly later than scheduled_start_at.")
    if body["service_date"] != clock.utc_date(start_dt):
        fail(errors.ERR_VALIDATION,
             "service_date must equal the UTC calendar-date portion of scheduled_start_at.")
    # rung 5
    episode = ladder.body_episode(body)
    # rung 8
    ladder.require_episode_active(episode)

    # rung 12 -- the staff turnaround buffer, program-wide, per staff_user_id
    buffer_delta = timedelta(minutes=calc.VISIT_TURNAROUND_BUFFER_MINUTES)
    for other in store.ordered(DB.visits.values()):
        if other["staff_user_id"] != body["staff_user_id"]:
            continue
        if other["scheduling_status"] not in OCCUPYING_STATES:
            continue
        other_start = clock.parse_iso(other["scheduled_start_at"])
        other_end = clock.parse_iso(other["scheduled_end_at"])
        if start_dt >= other_end + buffer_delta:
            continue
        if end_dt <= other_start:
            continue
        fail(errors.ERR_VISIT_OVERLAP)

    visit = store.make_row("visits", {
        "episode_id": episode["id"],
        "visit_type": body["visit_type"],
        "staff_user_id": body["staff_user_id"],
        "service_date": body["service_date"],
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "distance_km": body["distance_km"],
        "scheduling_status": "SCHEDULED",
        "attestation_status": "UNATTESTED",
        "attested_by_user_id": None,
        "travel_payment_usd": calc.ZERO,
    })
    compliance.mint_record(episode, body["service_date"])
    return envelope.ObjResult(visit, serializers.visit, 201)


@endpoint(bp, "/episodes/<episode_id>/visits", ["GET"], VISIT_LIST_ROLES)
def list_episode_visits(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [v for v in DB.visits.values() if v["episode_id"] == episode_id]
    rows = apply_filter(rows, "service_date")
    rows = apply_filter(rows, "scheduling_status")
    return envelope.ListResult(store.ordered(rows), serializers.visit, limit, offset)


@endpoint(bp, "/visits/<visit_id>/depart", ["POST"], VISIT_ACTION_ROLES)
def depart_visit(caller, visit_id):
    # rung 3
    visit = ladder.path_row("visits", visit_id)
    # rung 7
    ladder.require_state(visit["scheduling_status"] == "SCHEDULED")
    # rung 8
    ladder.require_episode_active(DB.episodes[visit["episode_id"]])
    visit["scheduling_status"] = "EN_ROUTE"
    store.touch(visit)
    return envelope.ObjResult(visit, serializers.visit, 200)


@endpoint(bp, "/visits/<visit_id>/complete", ["POST"], VISIT_ACTION_ROLES)
def complete_visit(caller, visit_id):
    # rung 3
    visit = ladder.path_row("visits", visit_id)
    # rung 7
    ladder.require_state(visit["scheduling_status"] == "EN_ROUTE")
    # rung 8
    ladder.require_episode_active(DB.episodes[visit["episode_id"]])
    visit["scheduling_status"] = "COMPLETED"
    visit["travel_payment_usd"] = calc.visit_travel_payment(visit["distance_km"])
    store.touch(visit)
    _recompute_day(visit)
    return envelope.ObjResult(visit, serializers.visit, 200)


@endpoint(bp, "/visits/<visit_id>/close-unperformed", ["POST"], VISIT_ACTION_ROLES)
def close_unperformed(caller, visit_id):
    # rung 3
    visit = ladder.path_row("visits", visit_id)
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["outcome"])
    # rung 4b
    ladder.check_enum(body, "outcome", CLOSE_OUTCOMES)
    # rung 7
    ladder.require_state(visit["scheduling_status"] in ("SCHEDULED", "EN_ROUTE"))
    visit["scheduling_status"] = body["outcome"]
    store.touch(visit)
    _recompute_day(visit)
    return envelope.ObjResult(visit, serializers.visit, 200)


@endpoint(bp, "/visits/<visit_id>/attest", ["POST"], VISIT_ACTION_ROLES)
def attest_visit(caller, visit_id):
    # rung 3
    visit = ladder.path_row("visits", visit_id)
    # rung 7 -- AMENDED is terminal on the attestation axis; a CANCELLED
    # scheduling axis blocks attestation.
    ladder.require_state(visit["attestation_status"] in ("UNATTESTED", "ATTESTED"))
    ladder.require_state(visit["scheduling_status"] != "CANCELLED")

    amending = visit["attestation_status"] == "ATTESTED"
    visit["attestation_status"] = "AMENDED" if amending else "ATTESTED"
    visit["attested_by_user_id"] = caller.user_id
    store.touch(visit)

    record = _recompute_day(visit)
    if amending and record is not None:
        episode = DB.episodes[visit["episode_id"]]
        if episode["status"] != "DISCHARGED":
            compliance.reopen(record)
    return envelope.ObjResult(visit, serializers.visit, 200)


@endpoint(bp, "/compliance-days/<record_id>/finalize", ["POST"],
          ["ProgramAdmin", "AdmittingPhysician"])
def finalize_compliance_day(caller, record_id):
    # rung 3
    record = ladder.path_row("compliance_days", record_id)
    # rung 7
    ladder.require_state(record["status"] == "PENDING")
    compliance.finalize(record)
    return envelope.ObjResult(record, serializers.compliance_day, 200)
