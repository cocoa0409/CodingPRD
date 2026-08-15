"""Observations: recording (seven ordered domain checks) and steward review."""
from flask import Blueprint, g, request

from db import db, parse_dt, new_entity, now_iso, now_dt
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    req_number,
    req_datetime,
    get_or_404,
    page_of,
    serialize,
    touch,
)
import services
from routes.cycles import _vendor_scope_for_cycle

bp = Blueprint("observations", __name__)

OBS_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "FieldCollector")


# --------------------------------------------------------------- recording
@bp.post("/participants/<pid>/observations")
@require_roles("FieldCollector")
def record_observation(pid):
    participant = get_or_404(db.participants, pid)
    body = get_body()
    indicator_id = req_str(body, "indicator_id")
    instrument_id = req_str(body, "instrument_id")
    value = req_number(body, "value")
    collected_at = req_datetime(body, "collected_at")

    cycle = services.cycle_of_participant(participant)
    # Domain checks fire in exactly this order (PRD 3.6), each masking later ones.
    # 1. The owning cycle must be ACTIVE.
    if cycle is None or cycle["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Observations can be recorded only while the cycle is ACTIVE."
        )
    # 2. Consent: participant not WITHDRAWN and consent_status CURRENT.
    services.refresh_participant_consent(participant)
    if participant["status"] == "WITHDRAWN" or participant["consent_status"] != "CURRENT":
        raise ApiError(
            "ERR_CONSENT_NOT_CURRENT", 422, "Participant consent is not CURRENT."
        )
    # 3. Instrument must be PUBLISHED.
    instrument = db.instruments.get(instrument_id)
    if instrument is None or instrument["status"] != "PUBLISHED":
        raise ApiError("ERR_INSTRUMENT_NOT_PUBLISHED", 422, "Instrument is not PUBLISHED.")
    # 4. Indicator must be ACTIVE and belong to the cycle's pinned logic model.
    indicator = db.indicators.get(indicator_id)
    if (
        indicator is None
        or indicator["status"] != "ACTIVE"
        or indicator["logic_model_id"] != cycle["pinned_logic_model_id"]
    ):
        raise ApiError(
            "ERR_INDICATOR_NOT_IN_MODEL",
            422,
            "Indicator is not ACTIVE in the cycle's pinned logic model.",
        )
    # 5. A certification must pair the acting collector with the instrument.
    certs = [
        c
        for c in db.certifications.values()
        if c["staff_user_id"] == g.user_id and c["instrument_id"] == instrument_id
    ]
    if not certs:
        raise ApiError(
            "ERR_CERTIFICATION_MISSING",
            422,
            "No training certification pairs this collector with the instrument.",
        )
    cert = max(certs, key=lambda c: c["_seq"])
    services.refresh_certification(cert)
    # 6. The pinned version must still match the instrument line's current
    #    version and the certification must not be STALE.
    if (
        cert["certified_instrument_version"]
        != services.instrument_line_current_version(instrument)
        or cert["status"] == "STALE"
    ):
        raise ApiError(
            "ERR_CERTIFICATION_STALE", 422, "Certification no longer matches the instrument version."
        )
    # 7. The certification must be CERTIFIED with expiry strictly in the future.
    if cert["status"] != "CERTIFIED" or parse_dt(cert["expires_at"]) <= now_dt():
        raise ApiError(
            "ERR_CERTIFICATION_EXPIRED", 422, "Certification is not currently valid."
        )

    recorded_at = now_iso()
    is_late = now_dt() > parse_dt(cycle["cycle_end"])
    ent = new_entity(
        db.observations,
        {
            "participant_id": pid,
            "indicator_id": indicator_id,
            "instrument_id": instrument_id,
            "instrument_version": instrument["instrument_version"],
            "value": value,
            "collected_at": collected_at,
            "recorded_at": recorded_at,
            "collected_by_id": g.user_id,
            "review_status": "PENDING",
            "is_late": is_late,
            "exclusion_reason": None,
        },
    )
    # Creation recomputes total_observation_count and data_completeness_pct
    # (dq recompute is NOT a creation trigger — SCAFFOLD 1.3 dq_score).
    services.recompute_cycle_aggregates(cycle)
    return ok_object(serialize(ent), 201)


# ------------------------------------------------------------------- reads
@bp.get("/observations/<oid>")
@require_roles(*OBS_READ_ROLES, "VendorAnalyst")
def get_observation(oid):
    if g.role == "VendorAnalyst":
        obs = db.observations.get(oid)
        cycle_id = None
        if obs is not None:
            participant = db.participants.get(obs["participant_id"])
            if participant is not None:
                cycle_id = participant["program_cycle_id"]
        # Scope fails closed: an unverifiable target is a scope denial.
        _vendor_scope_for_cycle(cycle_id)
    return ok_object(serialize(get_or_404(db.observations, oid)))


@bp.get("/observations")
@require_roles(*OBS_READ_ROLES)
def list_observations():
    items = list(db.observations.values())
    for param, field in (
        ("participant_id", "participant_id"),
        ("indicator_id", "indicator_id"),
        ("instrument_id", "instrument_id"),
        ("review_status", "review_status"),
    ):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[field] == v]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/cycles/<cid>/observations")
@require_roles(*OBS_READ_ROLES, "VendorAnalyst")
def list_cycle_observations(cid):
    _vendor_scope_for_cycle(cid)
    get_or_404(db.cycles, cid)
    items = services.cycle_observations(cid)
    rs = request.args.get("review_status")
    if rs is not None:
        items = [o for o in items if o["review_status"] == rs]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/participants/<pid>/observations")
@require_roles(*OBS_READ_ROLES)
def list_participant_observations(pid):
    get_or_404(db.participants, pid)
    items = [o for o in db.observations.values() if o["participant_id"] == pid]
    rs = request.args.get("review_status")
    if rs is not None:
        items = [o for o in items if o["review_status"] == rs]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


# ------------------------------------------------------------------ review
def _review_cycle_effects(obs):
    participant = db.participants.get(obs["participant_id"])
    if participant is None:
        return
    cycle = services.cycle_of_participant(participant)
    if cycle is None:
        return
    services.recompute_cycle_aggregates(cycle)
    services.refresh_cycle_dq(cycle)


@bp.post("/observations/<oid>/validate")
@require_roles("DataSteward")
def validate_observation(oid):
    obs = get_or_404(db.observations, oid)
    get_body()
    if obs["review_status"] not in ("PENDING", "FLAGGED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Observation in review_status {obs['review_status']} cannot be validated.",
        )
    # Segregation of duties: the steward must not be the collector.
    if g.user_id == obs["collected_by_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTY", 422, "A steward cannot validate their own collection."
        )
    obs["review_status"] = "VALIDATED"
    touch(db.observations, obs)
    _review_cycle_effects(obs)
    return ok_object(serialize(obs))


@bp.post("/observations/<oid>/flag")
@require_roles("DataSteward")
def flag_observation(oid):
    obs = get_or_404(db.observations, oid)
    body = get_body()
    req_str(body, "reason")
    if obs["review_status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Observation in review_status {obs['review_status']} cannot be flagged.",
        )
    obs["review_status"] = "FLAGGED"
    touch(db.observations, obs)
    # FLAGGED stays in every denominator: cycle counters and completeness are
    # deliberately unchanged by a flag (PRD 3.6).
    return ok_object(serialize(obs))


@bp.post("/observations/<oid>/exclude")
@require_roles("DataSteward")
def exclude_observation(oid):
    obs = get_or_404(db.observations, oid)
    body = get_body()
    reason = req_str(body, "reason")
    if obs["review_status"] not in ("PENDING", "VALIDATED", "FLAGGED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Observation in review_status {obs['review_status']} cannot be excluded.",
        )
    obs["review_status"] = "EXCLUDED"
    obs["exclusion_reason"] = reason
    touch(db.observations, obs)
    _review_cycle_effects(obs)
    return ok_object(serialize(obs))
