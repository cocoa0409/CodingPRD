"""Integrated pest management: scouting rounds and biological-control releases."""
from datetime import timedelta

from flask import Blueprint, g, request

import calc
import const
import fields
from authz import (ALL_ROLES, IPM_COORDINATOR, IPM_SCOUT, body, guard)
from envelope import created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, terminal, to_status_enum, transition
from money import D, q0
from store import base_record, db, ordered, touch

bp = Blueprint("ipm", __name__)


# ------------------------------------------------------------ ScoutingObservation


@bp.post("/scouting-observations")
@guard([IPM_SCOUT], actor=True)
def create_observation():
    payload = body()
    # priority 4
    zone_id = fields.string(payload, "zone_id")
    crop_cycle_id = fields.string(payload, "crop_cycle_id")
    observed_at = fields.timestamp(payload, "observed_at")
    pest_code = fields.enum_slot(payload, "pest_code")
    plants_inspected = fields.integer(payload, "plants_inspected", lo=1)
    pest_count = fields.number(payload, "pest_count_per_plant", lo=0)
    # priority 5
    fields.enum_value(pest_code, "pest_code", const.PEST_CODES)
    # priority 7
    zone = fetch("zones", zone_id)
    cycle = fetch("crop_cycles", crop_cycle_id)
    # priority 38
    if cycle["zone_id"] != zone_id:
        raise ApiError("ERR_CROP_CYCLE_ZONE_MISMATCH")

    threshold, status, required = calc.pest_threshold(pest_code, pest_count)
    record = base_record(with_common=False)
    record.update({
        "zone_id": zone_id,
        "crop_cycle_id": crop_cycle_id,
        "observed_by_worker_id": g.user_id,
        "observed_at": observed_at,
        "pest_code": pest_code,
        "plants_inspected": plants_inspected,
        "pest_count_per_plant": pest_count,
        "action_threshold": threshold,
        "threshold_status": status,
        "release_required": required,
    })
    db["scouting_observations"][record["id"]] = record

    if required:
        # hop 1 - the alert counter drives the posture derivation
        zone["open_pest_alert_count"] = zone["open_pest_alert_count"] + 1
        if zone["open_pest_alert_count"] == const.PEST_ALERT_LOCK_COUNT:
            # hops 2 and 3 - harvest crews stand down, budget is repaid
            calc.cascade_ipm_lock(zone)
        calc.refresh_zone(zone, force=True)
    return created(public(record))


@bp.get("/scouting-observations")
@guard(ALL_ROLES)
def list_observations():
    rows = ordered("scouting_observations")
    rows = filter_equals(rows, "zone_id", request.args.get("zone_id"))
    rows = filter_equals(rows, "crop_cycle_id", request.args.get("crop_cycle_id"))
    rows = filter_equals(
        rows, "observed_by_worker_id", request.args.get("observed_by_worker_id")
    )
    rows = filter_equals(rows, "threshold_status", request.args.get("threshold_status"))
    return paginated(rows, public)


@bp.get("/scouting-observations/<observation_id>")
@guard(ALL_ROLES)
def get_observation(observation_id):
    return ok(public(fetch("scouting_observations", observation_id)))


# ------------------------------------------------------------ BioControlRelease

ALLOWED = {
    "REQUESTED": ("REJECTED", "CANCELLED"),
    "APPROVED": ("REQUESTED", "CANCELLED"),
}

SUBROLES = {
    "REQUESTED": (IPM_COORDINATOR,),
    "REJECTED": (IPM_COORDINATOR,),
    "CANCELLED": (IPM_SCOUT,),
}


def _observation_of(release):
    return db["scouting_observations"].get(release["observation_id"])


def _segregation(release):
    """Priority 17 - the scout who filed the observation may not decide it."""
    observation = _observation_of(release)
    if observation is None:
        return
    if g.user_id == observation["observed_by_worker_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


@bp.post("/bio-control-releases")
@guard([IPM_SCOUT], actor=True)
def create_release():
    payload = body()
    zone_id = fields.string(payload, "zone_id")
    observation_id = fields.string(payload, "observation_id")
    agent_code = fields.enum_slot(payload, "agent_code")
    planned_count = fields.integer(payload, "planned_release_count", lo=100)
    planned_date = fields.day(payload, "planned_release_date")
    fields.enum_value(agent_code, "agent_code", const.AGENT_CODES)
    # priority 7 - declared input order: zone_id then observation_id
    fetch("zones", zone_id)
    observation = fetch("scouting_observations", observation_id)
    # priority 37 - threshold first, only then the compartment match
    if not observation["release_required"]:
        raise ApiError("ERR_OBSERVATION_BELOW_THRESHOLD")
    if observation["zone_id"] != zone_id:
        raise ApiError("ERR_OBSERVATION_ZONE_MISMATCH")

    record = base_record()
    record.update({
        "zone_id": zone_id,
        "observation_id": observation_id,
        "agent_code": agent_code,
        "planned_release_count": planned_count,
        "planned_release_date": planned_date,
        "requested_by_worker_id": g.user_id,
        "decided_by_worker_id": None,
        "approved_release_count": None,
        "decision_reason": None,
        "revision_count": 0,
        "status": "REQUESTED",
        "released_at": None,
        "actual_release_count": None,
        "reentry_hours": None,
    })
    db["bio_control_releases"][record["id"]] = record
    return created(public(record))


@bp.get("/bio-control-releases")
@guard(ALL_ROLES)
def list_releases():
    rows = ordered("bio_control_releases")
    rows = filter_equals(rows, "zone_id", request.args.get("zone_id"))
    rows = filter_equals(rows, "observation_id", request.args.get("observation_id"))
    rows = filter_equals(
        rows, "requested_by_worker_id", request.args.get("requested_by_worker_id")
    )
    rows = filter_equals(
        rows, "decided_by_worker_id", request.args.get("decided_by_worker_id")
    )
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/bio-control-releases/<release_id>")
@guard(ALL_ROLES)
def get_release(release_id):
    return ok(public(fetch("bio_control_releases", release_id)))


@bp.post("/bio-control-releases/<release_id>/approve")
@guard([IPM_COORDINATOR], actor=True)
def approve_release(release_id):
    payload = body()
    revised = fields.integer(payload, "revised_release_count", required=False)
    reason = fields.string(payload, "decision_reason", required=False)
    release = fetch("bio_control_releases", release_id)
    terminal(release["status"], const.RELEASE_TERMINAL)
    transition({"REQUESTED": ("APPROVED",)}, release["status"], "APPROVED")
    _segregation(release)

    release["approved_release_count"] = (
        revised if revised is not None else release["planned_release_count"]
    )
    if reason is not None:
        release["decision_reason"] = reason
    release["decided_by_worker_id"] = g.user_id
    release["status"] = "APPROVED"
    touch(release)
    return ok(public(release))


@bp.post("/bio-control-releases/<release_id>/transitions")
@guard([IPM_SCOUT, IPM_COORDINATOR], subroles=SUBROLES)
def transition_release(release_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    reason = fields.string(payload, "decision_reason", required=False)
    to_status_enum(target, const.RELEASE_STATUSES)
    release = fetch("bio_control_releases", release_id)
    terminal(release["status"], const.RELEASE_TERMINAL)
    transition(ALLOWED, release["status"], target)
    if target == "REJECTED" and reason is None:
        raise ApiError("ERR_DECISION_REASON_REQUIRED")
    _segregation(release)

    if target == "REQUESTED":
        # priority 25 - the revision loop is closed once the cap is reached
        if release["revision_count"] >= const.MAX_RELEASE_REVISIONS:
            raise ApiError("ERR_MAX_REVISIONS_EXCEEDED")
        release["revision_count"] = release["revision_count"] + 1
        release["approved_release_count"] = None
        release["decided_by_worker_id"] = None
        release["status"] = "REQUESTED"
        if reason is not None:
            release["decision_reason"] = reason
    elif target == "REJECTED":
        # The alert counter is untouched: refusing to treat does not clear the pest.
        release["decision_reason"] = reason
        release["decided_by_worker_id"] = g.user_id
        release["status"] = "REJECTED"
    else:  # CANCELLED - approved_release_count is retained for audit
        if reason is not None:
            release["decision_reason"] = reason
        release["decided_by_worker_id"] = g.user_id
        release["status"] = "CANCELLED"
    touch(release)
    return ok(public(release))


@bp.post("/bio-control-releases/<release_id>/execute")
@guard([IPM_SCOUT], actor=True)
def execute_release(release_id):
    payload = body()
    released_at = fields.timestamp(payload, "released_at")
    actual_count = fields.integer(payload, "actual_release_count", lo=0)
    release = fetch("bio_control_releases", release_id)
    terminal(release["status"], const.RELEASE_TERMINAL)
    transition({"APPROVED": ("RELEASED",)}, release["status"], "RELEASED")
    # priority 26 - closed interval, each bound rounded to whole agents
    approved = D(release["approved_release_count"] or 0)
    tolerance = const.RELEASE_COUNT_TOLERANCE_PCT / D(100)
    low = q0(approved * (D(1) - tolerance))
    high = q0(approved * (D(1) + tolerance))
    if not (low <= D(actual_count) <= high):
        raise ApiError("ERR_RELEASE_COUNT_OUT_OF_TOLERANCE")
    observation = _observation_of(release)
    if observation is not None and released_at < observation["observed_at"]:
        raise ApiError("ERR_RELEASE_BEFORE_OBSERVATION")

    hours = const.AGENT_REENTRY_HOURS[release["agent_code"]]
    release["released_at"] = released_at
    release["actual_release_count"] = actual_count
    release["reentry_hours"] = hours
    release["status"] = "RELEASED"
    touch(release)

    zone = db["zones"].get(release["zone_id"])
    if zone is not None:
        count = zone["open_pest_alert_count"] - 1
        zone["open_pest_alert_count"] = count if count > 0 else 0
        # The freshly set re-entry interval holds the posture at LOCKED even
        # though the alert counter just fell, possibly to zero.
        zone["reentry_clear_at"] = released_at + timedelta(hours=hours)
        calc.refresh_zone(zone, force=True)
    return ok(public(release))
