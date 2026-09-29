"""Candidate personas and the channel-preference research behind them."""

from flask import Blueprint, g

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import calc, serialize

bp = Blueprint("personas", __name__)

READ_ROLES = ("BrandProgramLead", "PersonaResearcher", "ComplianceReviewer",
              "MediaBuyer", "CommunityManager", "RecruitingOps")
MIX_METHODS = ("SURVEY_WEIGHTED", "ENGAGEMENT_WEIGHTED")
PERSONA_STATES = ("DRAFT", "IN_REVIEW", "APPROVED", "RETIRED")


def _apply_mix(persona, computed):
    persona["channel_mix"] = computed["channel_mix"]
    persona["mix_confidence_pct"] = computed["mix_confidence_pct"]
    persona["signal_count"] = computed["signal_count"]


@bp.route("/candidate-personas", methods=["POST"])
@require("PersonaResearcher")
def create_persona():
    data = V.body()
    job_family_id = V.field(data, "job_family_id", "string", required=True)
    name = V.field(data, "name", "string", required=True, min_len=1, max_len=120)
    mix_method = V.field(data, "mix_method", "enum", default="SURVEY_WEIGHTED",
                        values=MIX_METHODS)
    research_window_days = V.field(data, "research_window_days", "integer",
                                   default=180, min_value=1)
    family = calc.must_get(db.job_families, job_family_id, "ERR_JOB_FAMILY_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "job_family_id": family["id"],
        "name": name,
        "mix_method": mix_method,
        "research_window_days": research_window_days,
        "state": "DRAFT",
        "channel_mix": [],
        "mix_confidence_pct": 0,
        "signal_count": 0,
        "revision_count": 0,
        "drafted_by_user_id": g.user_id,
        "reviewed_by_user_id": None,
        "last_review_note": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.personas[row["id"]] = row
    return response.ok(serialize.persona(row), 201)


@bp.route("/channel-preference-signals", methods=["POST"])
@require("PersonaResearcher")
def create_signal():
    data = V.body()
    persona_id = V.field(data, "persona_id", "string", required=True)
    channel_id = V.field(data, "channel_id", "string", required=True)
    preference_score = V.field(data, "preference_score", "integer", required=True,
                               min_value=0, max_value=100)
    sample_size = V.field(data, "sample_size", "integer", required=True, min_value=1)
    engagement_events = V.field(data, "engagement_events", "integer",
                                default=0, min_value=0)
    collected_at = V.field(data, "collected_at", "datetime", required=True)

    persona = calc.must_get(db.personas, persona_id, "ERR_PERSONA_NOT_FOUND")
    channel = calc.must_get(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "persona_id": persona["id"],
        "channel_id": channel["id"],
        "preference_score": preference_score,
        "sample_size": sample_size,
        "engagement_events": engagement_events,
        "collected_at": collected_at,
        "created_at": db.wall_now(),
    }
    db.signals[row["id"]] = row
    _apply_mix(persona, calc.persona_channel_mix(persona))
    db.touch(persona)
    return response.ok(serialize.signal(row), 201)


@bp.route("/channel-preference-signals/<signal_id>", methods=["GET"])
@require(*READ_ROLES)
def get_signal(signal_id):
    row = calc.must_get(db.signals, signal_id, "ERR_RECORD_NOT_FOUND")
    return response.ok(serialize.signal(row))


@bp.route("/channel-preference-signals", methods=["GET"])
@require(*READ_ROLES)
def list_signals():
    limit, offset = V.pagination()
    rows = sorted(db.signals.values(),
                  key=lambda r: (r["collected_at"], r["created_at"]))
    persona_id = V.qs("persona_id")
    if persona_id:
        rows = [r for r in rows if r["persona_id"] == persona_id]
    channel_id = V.qs("channel_id")
    if channel_id:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.signal(r) for r in page], meta)


@bp.route("/candidate-personas/<persona_id>/submit", methods=["POST"])
@require("PersonaResearcher")
def submit_persona(persona_id):
    persona = calc.must_get(db.personas, persona_id, "ERR_PERSONA_NOT_FOUND")
    if persona["state"] != "DRAFT":
        raise ApiError("ERR_PERSONA_NOT_DRAFT", "Persona is not in DRAFT.")
    computed = calc.persona_channel_mix(persona)
    if computed["signal_count"] < 1:
        raise ApiError("ERR_NO_RESEARCH_SIGNALS",
                       "No research signals inside the persona's research window.")
    if computed["mix_confidence_pct"] < 40:
        raise ApiError("ERR_INSUFFICIENT_RESEARCH_CONFIDENCE",
                       "mix_confidence_pct must be at least 40.")
    _apply_mix(persona, computed)
    persona["state"] = "IN_REVIEW"
    db.touch(persona)
    return response.ok(serialize.persona(persona))


@bp.route("/candidate-personas/<persona_id>/review", methods=["POST"])
@require("BrandProgramLead")
def review_persona(persona_id):
    data = V.body()
    decision = V.field(data, "decision", "enum", required=True,
                       values=("APPROVE", "REQUEST_REVISION"))
    review_note = V.field(data, "review_note", "string", nullable=True,
                          min_len=0, max_len=2000)
    persona = calc.must_get(db.personas, persona_id, "ERR_PERSONA_NOT_FOUND")
    if persona["drafted_by_user_id"] is not None and g.user_id == persona["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The persona's drafter may not review it.")
    if persona["state"] != "IN_REVIEW":
        raise ApiError("ERR_PERSONA_NOT_IN_REVIEW", "Persona is not IN_REVIEW.")
    if decision == "APPROVE" and not persona["channel_mix"]:
        raise ApiError("ERR_NO_RESEARCH_SIGNALS",
                       "A persona with an empty channel_mix cannot be approved.")
    persona["reviewed_by_user_id"] = g.user_id
    persona["last_review_note"] = review_note
    if decision == "APPROVE":
        persona["state"] = "APPROVED"
    else:
        persona["state"] = "DRAFT"
        persona["revision_count"] += 1
    db.touch(persona)
    return response.ok(serialize.persona(persona))


@bp.route("/candidate-personas/<persona_id>/retire", methods=["POST"])
@require("PersonaResearcher")
def retire_persona(persona_id):
    persona = calc.must_get(db.personas, persona_id, "ERR_PERSONA_NOT_FOUND")
    if persona["state"] != "APPROVED":
        raise ApiError("ERR_PERSONA_NOT_APPROVED", "Persona is not APPROVED.")
    others = [p for p in db.personas.values()
              if p["job_family_id"] == persona["job_family_id"]
              and p["id"] != persona["id"] and p["state"] == "APPROVED"]
    if not others:
        live = [p for p in db.postings.values()
                if p["job_family_id"] == persona["job_family_id"]
                and p["content_status"] in ("PUBLISHED", "SUSPENDED")]
        if live:
            raise ApiError("ERR_PERSONA_IN_USE",
                           "The family still advertises with published or suspended postings.")
    persona["state"] = "RETIRED"
    db.touch(persona)
    return response.ok(serialize.persona(persona))


@bp.route("/candidate-personas/<persona_id>", methods=["GET"])
@require(*READ_ROLES)
def get_persona(persona_id):
    persona = calc.must_get(db.personas, persona_id, "ERR_PERSONA_NOT_FOUND")
    return response.ok(serialize.persona(persona))


@bp.route("/candidate-personas", methods=["GET"])
@require(*READ_ROLES)
def list_personas():
    limit, offset = V.pagination()
    rows = calc.by_created(db.personas.values())
    job_family_id = V.qs("job_family_id")
    if job_family_id:
        rows = [r for r in rows if r["job_family_id"] == job_family_id]
    state = V.qs("state")
    if state:
        rows = [r for r in rows if r["state"] == state]
    mix_method = V.qs("mix_method")
    if mix_method:
        rows = [r for r in rows if r["mix_method"] == mix_method]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.persona(r) for r in page], meta)
