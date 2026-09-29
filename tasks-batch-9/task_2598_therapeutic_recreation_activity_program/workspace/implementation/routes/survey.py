"""Survey documentation packets and the logical clock (PRD 3.9)."""
from flask import Blueprint

import serializers
from db import date_str, parse_date, store
from errors import ApiError
from helpers import ctx, load, new_entity
from middleware import (
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    authorize,
)
from response import empty_response, object_response
from services import survey as survey_svc
from validation import read_body, validate

bp = Blueprint("survey", __name__)

OPEN_STATUSES = ("OPEN", "COMPILED", "ATTESTED", "AMENDED")

CREATE_SPEC = {
    "window_start": {"type": "date", "required": True},
    "window_end": {"type": "date", "required": True},
}

ATTEST_SPEC = {
    "action": {"type": "enum", "values": ["ATTEST", "AMEND"], "required": True},
    "remediation_note": {"type": "text"},
    "amendment_reason": {"type": "text"},
}

CLOCK_SPEC = {"current_utc": {"type": "datetime", "required": True}}

SCORE_FIELDS = (
    "offered_sessions_targeted",
    "offered_sessions_delivered",
    "base_score",
    "domain_coverage_penalty",
    "refusal_penalty",
    "preliminary_score",
    "provision_score",
)


@bp.post("/survey-packets")
def create_packet():
    authorize(ROLE_COMPLIANCE_OFFICER, ROLE_ACTIVITY_DIRECTOR)
    body = read_body()
    values = validate(body, CREATE_SPEC)
    window_start = values["window_start"]
    window_end = values["window_end"]
    if window_end < window_start:
        raise ApiError("ERR_TIME_WINDOW_INVALID")
    # Rank 24: inclusive windows may touch but never overlap.
    for other in store.packets.values():
        if other["status"] not in OPEN_STATUSES:
            continue
        other_start = parse_date(other["window_start"])
        other_end = parse_date(other["window_end"])
        if window_start <= other_end and other_start <= window_end:
            raise ApiError("ERR_PACKET_WINDOW_OVERLAP")

    packet = new_entity(
        {
            "window_start": date_str(window_start),
            "window_end": date_str(window_end),
            "status": "OPEN",
            "deficiency_flags": [],
            "compiled_by_user_id": None,
            "attested_by_user_id": None,
            "amendment_count": 0,
            "remediation_note": None,
        }
    )
    for name in SCORE_FIELDS:
        packet[name] = None
    store.packets[packet["id"]] = packet
    return object_response(serializers.packet(packet), 201)


@bp.post("/survey-packets/<packet_id>/compile")
def compile_packet(packet_id):
    actor = authorize(ROLE_COMPLIANCE_OFFICER, ROLE_ACTIVITY_DIRECTOR)
    body = read_body()
    packet = load("packet", packet_id)
    validate(body, {})
    # Rank 18: compilation is admitted from OPEN and AMENDED only, and only
    # once the window has closed.
    if packet["status"] not in ("OPEN", "AMENDED"):
        raise ApiError("ERR_PACKET_INVALID_STATE")
    if parse_date(packet["window_end"]) > store.today():
        raise ApiError("ERR_PACKET_INVALID_STATE")

    context = ctx()
    result = survey_svc.compile_packet(store, packet)
    result.pop("cohort_resident_count", None)
    for key, value in result.items():
        packet[key] = value
    packet["compiled_by_user_id"] = actor.user_id
    packet["status"] = "COMPILED"
    context.bump(packet)
    return object_response(serializers.packet(packet), 200)


@bp.post("/survey-packets/<packet_id>/attestation")
def attest_packet(packet_id):
    actor = authorize(ROLE_COMPLIANCE_OFFICER)
    body = read_body()
    packet = load("packet", packet_id)
    # Rank 3: the operator who compiled a packet may never attest it.
    if body.get("action") == "ATTEST" and packet["compiled_by_user_id"] is not None:
        if packet["compiled_by_user_id"] == actor.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    values = validate(body, ATTEST_SPEC)
    action = values["action"]
    context = ctx()

    if action == "ATTEST":
        # Rank 18 then rank 43.
        if packet["status"] != "COMPILED":
            raise ApiError("ERR_PACKET_INVALID_STATE")
        note = values["remediation_note"]
        if packet["deficiency_flags"] and not note:
            raise ApiError("ERR_REMEDIATION_NOTE_REQUIRED")
        packet["status"] = "ATTESTED"
        packet["attested_by_user_id"] = actor.user_id
        packet["remediation_note"] = note
    else:
        if packet["status"] != "ATTESTED":
            raise ApiError("ERR_PACKET_INVALID_STATE")
        packet["status"] = "AMENDED"
        packet["amendment_count"] = packet["amendment_count"] + 1
        packet["attested_by_user_id"] = None

    context.bump(packet)
    return object_response(serializers.packet(packet), 200)


@bp.get("/survey-packets/<packet_id>")
def get_packet(packet_id):
    authorize(ROLE_COMPLIANCE_OFFICER, ROLE_ACTIVITY_DIRECTOR)
    packet = load("packet", packet_id)
    return object_response(serializers.packet(packet), 200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(ROLE_ACTIVITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER)
    body = read_body()
    values = validate(body, CLOCK_SPEC)
    # Rank 23: the logical clock is monotonic.
    if values["current_utc"] < store.clock:
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN")
    store.clock = values["current_utc"]
    return empty_response(200)
