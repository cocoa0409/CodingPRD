"""Sampled inspection deployments and the field encounters recorded under them."""

from flask import Blueprint

import calc
import cascade
import serial
from core import (ApiError, authorize, base_record, body, db, lookup, opt_dt,
                  opt_str, ordered, page, pagination, query_filter, req_dt,
                  req_enum, req_int, req_str, respond_object, touch)

bp = Blueprint("deployments", __name__)

DEPLOYMENT_READ_ROLES = ("EnforcementPlanner", "EquityAnalyst", "FareInspector")
ENCOUNTER_READ_ROLES = ("EnforcementPlanner", "EquityAnalyst", "FareInspector",
                        "HearingOfficer", "AppealsBoardMember")


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _overlaps_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------

@bp.post("/inspection-deployments")
def plan_deployment():
    authorize("EnforcementPlanner")
    payload = body()
    line_id = req_str(payload, "line_id", min_len=1)
    zone_id = req_str(payload, "zone_id", min_len=1)
    window_start = req_dt(payload, "window_start", error_id="ERR_INVALID_TIME_WINDOW")
    window_end = req_dt(payload, "window_end", error_id="ERR_INVALID_TIME_WINDOW")
    planned_inspector_count = req_int(payload, "planned_inspector_count",
                                     minimum=1, maximum=20)
    sampling_method = req_enum(payload, "sampling_method", calc.SAMPLING_METHODS)
    target_sample_size = req_int(payload, "target_sample_size", minimum=1)

    if window_end <= window_start:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "window_end must be strictly later than window_start.")
    if (window_end - window_start).total_seconds() % 60 != 0:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "The deployment window must span a whole number of minutes.")

    line = lookup(db.lines, line_id, "ERR_LINE_NOT_FOUND")
    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")

    enforceable = False
    for row in db.assignments.values():
        if (row["zone_id"] == zone["id"] and row["line_id"] == line["id"]
                and row["effective_from"] <= window_start):
            enforceable = True
            break
    if not enforceable:
        raise ApiError("ERR_LINE_NOT_ASSIGNED_TO_ZONE",
                       "This line is not enforceable inside the zone at window_start.")

    for other in db.deployments.values():
        if other["line_id"] != line["id"]:
            continue
        if other["status"] not in ("PLANNED", "ACTIVE", "CLOSED"):
            continue
        if _overlaps_half_open(window_start, window_end,
                               other["window_start"], other["window_end"]):
            raise ApiError("ERR_DEPLOYMENT_WINDOW_OVERLAP",
                           "Another live deployment on this line shares the window.")

    intersecting = 0
    for other in db.deployments.values():
        if other["zone_id"] != zone["id"]:
            continue
        if other["status"] not in ("PLANNED", "ACTIVE", "CLOSED"):
            continue
        if _overlaps_closed(window_start, window_end,
                            other["window_start"], other["window_end"]):
            intersecting += 1
    if intersecting >= zone["max_concurrent_deployments"]:
        raise ApiError("ERR_ZONE_DEPLOYMENT_CAPACITY",
                       "The zone's concurrent-deployment cap is already reached.")

    deployment = base_record()
    deployment.update({
        "line_id": line["id"],
        "zone_id": zone["id"],
        "window_start": window_start,
        "window_end": window_end,
        "planned_inspector_count": planned_inspector_count,
        "sampling_method": sampling_method,
        "target_sample_size": target_sample_size,
        "achieved_sample_count": 0,
        "voided_encounter_count": 0,
        "sample_adequacy_ratio": calc.rhu4(0, target_sample_size),
        "measured_evasion_rate_bps": None,
        "resolved_evasion_rate_bps": None,
        "enforcement_cost_cents": None,
        "status": "PLANNED",
        "void_reason": None,
    })
    db.deployments[deployment["id"]] = deployment
    return respond_object(serial.deployment_out(deployment), 201)


@bp.post("/inspection-deployments/<deployment_id>/activate")
def activate_deployment(deployment_id):
    authorize("EnforcementPlanner")
    deployment = lookup(db.deployments, deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    if deployment["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_DEPLOYMENT_STATE",
                       "Deployment is %s; only PLANNED may be activated."
                       % deployment["status"])
    zone = db.zones[deployment["zone_id"]]
    if zone["designation_status"] != "DESIGNATED":
        raise ApiError("ERR_ZONE_NOT_DESIGNATED",
                       "The governing zone is %s, not DESIGNATED."
                       % zone["designation_status"])
    if db.now() < deployment["window_start"]:
        raise ApiError("ERR_INVALID_DEPLOYMENT_STATE",
                       "The deployment window has not begun yet.")
    deployment["status"] = "ACTIVE"
    touch(deployment)
    return respond_object(serial.deployment_out(deployment))


@bp.post("/inspection-deployments/<deployment_id>/close")
def close_deployment(deployment_id):
    authorize("EnforcementPlanner")
    deployment = lookup(db.deployments, deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    if deployment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_DEPLOYMENT_STATE",
                       "Deployment is %s; only ACTIVE may be closed." % deployment["status"])
    encounters = calc.deployment_encounters(deployment["id"])
    if any(e["outcome"] == "PENDING" for e in encounters):
        raise ApiError("ERR_OPEN_ENCOUNTERS_REMAIN",
                       "The deployment still holds PENDING encounters.")
    calc.refresh_deployment_counters(deployment)
    if deployment["sample_adequacy_ratio"] < calc.SAMPLE_ADEQUACY_MIN:
        raise ApiError("ERR_SAMPLE_SIZE_INADEQUATE",
                       "sample_adequacy_ratio is below 0.8000.")
    measured, resolved = calc.evasion_rates(deployment)
    zone = db.zones[deployment["zone_id"]]
    deployment["measured_evasion_rate_bps"] = measured
    deployment["resolved_evasion_rate_bps"] = resolved
    deployment["enforcement_cost_cents"] = calc.enforcement_cost_cents(deployment, zone)
    deployment["status"] = "CLOSED"
    touch(deployment)
    return respond_object(serial.deployment_out(deployment))


@bp.post("/inspection-deployments/<deployment_id>/void")
def void_deployment_route(deployment_id):
    authorize("EnforcementPlanner")
    deployment = lookup(db.deployments, deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    if deployment["status"] not in ("PLANNED", "ACTIVE"):
        raise ApiError("ERR_INVALID_DEPLOYMENT_STATE",
                       "Deployment is %s; only PLANNED or ACTIVE may be voided."
                       % deployment["status"])
    cascade.void_deployment(deployment, "PLANNER_CANCELLED")
    return respond_object(serial.deployment_out(deployment))


@bp.get("/inspection-deployments/<deployment_id>")
def get_deployment(deployment_id):
    authorize(*DEPLOYMENT_READ_ROLES)
    deployment = lookup(db.deployments, deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    return respond_object(serial.deployment_out(deployment))


@bp.get("/inspection-deployments")
def list_deployments():
    authorize(*DEPLOYMENT_READ_ROLES)
    limit, offset = pagination()
    line_id = query_filter("line_id")
    zone_id = query_filter("zone_id")
    status = query_filter("status")
    rows = [d for d in db.deployments.values()
            if (line_id is None or d["line_id"] == line_id)
            and (zone_id is None or d["zone_id"] == zone_id)
            and (status is None or d["status"] == status)]
    return page(ordered(rows), limit, offset, serial.deployment_out)


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------

@bp.post("/inspection-encounters")
def record_encounter():
    actor = authorize("FareInspector")
    payload = body()
    deployment_id = req_str(payload, "deployment_id", min_len=1)
    inspector_id = req_str(payload, "inspector_id", min_len=1)
    rider_id = opt_str(payload, "rider_id")
    occurred_at = req_dt(payload, "occurred_at")
    fare_media_type = req_enum(payload, "fare_media_type", calc.FARE_MEDIA_TYPES)
    media_reference = opt_str(payload, "media_reference")
    media_validated_at = opt_dt(payload, "media_validated_at")
    media_expires_at = opt_dt(payload, "media_expires_at")
    media_zone_code = opt_str(payload, "media_zone_code")
    identity_capture_method = req_enum(payload, "identity_capture_method",
                                       calc.IDENTITY_METHODS)

    deployment = lookup(db.deployments, deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    inspector = lookup(db.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    rider = None
    if rider_id is not None:
        rider = lookup(db.riders, rider_id, "ERR_RIDER_NOT_FOUND")

    if actor.user_id != inspector["id"]:
        raise ApiError("ERR_INSPECTOR_NOT_ON_ENCOUNTER",
                       "X-User-ID must equal the encounter's inspector_id.")
    if deployment["status"] != "ACTIVE":
        raise ApiError("ERR_DEPLOYMENT_NOT_ACTIVE",
                       "Deployment is %s, not ACTIVE." % deployment["status"])
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_SUSPENDED", "The inspector is SUSPENDED.")
    if not inspector["certification_expiry"] > occurred_at:
        raise ApiError("ERR_INSPECTOR_CERT_EXPIRED",
                       "The inspector's certification had lapsed at occurred_at.")
    if not (deployment["window_start"] <= occurred_at < deployment["window_end"]):
        raise ApiError("ERR_ENCOUNTER_OUTSIDE_WINDOW",
                       "occurred_at falls outside the deployment window.")
    if occurred_at > db.now():
        raise ApiError("ERR_ENCOUNTER_OUTSIDE_WINDOW",
                       "occurred_at may not be later than the logical clock.")

    zone = db.zones[deployment["zone_id"]]
    verdict = calc.encounter_validation_result(
        fare_media_type, media_validated_at, media_expires_at, media_zone_code,
        occurred_at, zone["zone_code"])

    encounter = base_record()
    encounter.update({
        "deployment_id": deployment["id"],
        "inspector_id": inspector["id"],
        "rider_id": rider["id"] if rider is not None else None,
        "occurred_at": occurred_at,
        "fare_media_type": fare_media_type,
        "media_reference": media_reference,
        "media_validated_at": media_validated_at,
        "media_expires_at": media_expires_at,
        "media_zone_code": media_zone_code,
        "identity_capture_method": identity_capture_method,
        "validation_result": verdict,
        "outcome": "PENDING",
    })
    db.encounters[encounter["id"]] = encounter
    calc.refresh_deployment_counters(deployment)
    return respond_object(serial.encounter_out(encounter), 201)


@bp.post("/inspection-encounters/<encounter_id>/resolve")
def resolve_encounter(encounter_id):
    actor = authorize("FareInspector")
    payload = body()
    disposition = req_enum(payload, "disposition", calc.RESOLVE_DISPOSITIONS)

    encounter = lookup(db.encounters, encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    if actor.user_id != encounter["inspector_id"]:
        raise ApiError("ERR_INSPECTOR_NOT_ON_ENCOUNTER",
                       "X-User-ID must equal the encounter's inspector_id.")
    if encounter["outcome"] != "PENDING":
        raise ApiError("ERR_ENCOUNTER_NOT_PENDING",
                       "Encounter is %s, not PENDING." % encounter["outcome"])

    if disposition == "COMPLIANT":
        if encounter["validation_result"] != "VALID":
            raise ApiError("ERR_DISPOSITION_NOT_SUPPORTED",
                           "A COMPLIANT disposition requires a VALID fare-media verdict.")
    elif disposition == "WARNING_ISSUED":
        if encounter["validation_result"] not in calc.NONCOMPLIANT_RESULTS:
            raise ApiError("ERR_DISPOSITION_NOT_SUPPORTED",
                           "A warning requires a non-compliant fare-media verdict.")
        if encounter["rider_id"] is None:
            raise ApiError("ERR_DISPOSITION_NOT_SUPPORTED",
                           "A warning must be attributable to an identified rider.")
    else:
        if encounter["identity_capture_method"] != "REFUSED":
            raise ApiError("ERR_DISPOSITION_NOT_SUPPORTED",
                           "UNRESOLVED_IDENTITY requires identity_capture_method REFUSED.")

    encounter["outcome"] = disposition
    touch(encounter)
    return respond_object(serial.encounter_out(encounter))


@bp.get("/inspection-encounters/<encounter_id>")
def get_encounter(encounter_id):
    authorize(*ENCOUNTER_READ_ROLES)
    encounter = lookup(db.encounters, encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    return respond_object(serial.encounter_out(encounter))


@bp.get("/inspection-encounters")
def list_encounters():
    authorize(*ENCOUNTER_READ_ROLES)
    limit, offset = pagination()
    deployment_id = query_filter("deployment_id")
    inspector_id = query_filter("inspector_id")
    rider_id = query_filter("rider_id")
    outcome = query_filter("outcome")
    rows = [e for e in db.encounters.values()
            if (deployment_id is None or e["deployment_id"] == deployment_id)
            and (inspector_id is None or e["inspector_id"] == inspector_id)
            and (rider_id is None or e["rider_id"] == rider_id)
            and (outcome is None or e["outcome"] == outcome)]
    return page(ordered(rows), limit, offset, serial.encounter_out)
