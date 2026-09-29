"""Venues and tracking installations (PRD §3.1, §3.2)."""

from datetime import timedelta

from flask import Blueprint

import db
from auth import authenticate
from calc import (CERT_VALIDITY_HOURS, MODALITIES, TRACKING_TECHS,
                  calibration_accuracy_evaluation)
from db import audit_new, audit_new_immutable, new_id, store, touch
from errors import ApiError
from lookups import require_installation, require_venue
from response import array_response, object_response
from services.venue import (apply_installation_status_change,
                            recompute_venue_census)
from util import num, parse_dt, serialize, serialize_many, sorted_rows
from validation import (field, no_body, paginate, pagination, string_filter,
                        validate_body)

bp = Blueprint("venues", __name__)

VENUE_SPEC = {
    "name": field("string"),
    "city": field("string"),
    "tracking_tech": field("enum", values=TRACKING_TECHS),
    "required_certified_installations": field("integer", minimum=1),
    "transport_capacity_mbps": field("number", exclusive_minimum=0),
    "min_achievable_latency_ms": field("integer", minimum=1),
}

INSTALLATION_SPEC = {
    "venue_id": field("string"),
    "rig_label": field("string"),
    "modality": field("enum", values=MODALITIES),
}

CALIBRATION_RUN_SPEC = {
    "axis_rms_x_mm": field("number", minimum=0),
    "axis_rms_y_mm": field("number", minimum=0),
    "axis_rms_z_mm": field("number", minimum=0),
    "sample_count": field("integer", minimum=0),
    "reference_point_count": field("integer", minimum=0),
}


# --------------------------------------------------------------------------
# Venues
# --------------------------------------------------------------------------

@bp.post("/venues")
def create_venue():
    authenticate("LeagueDataOps")
    body = validate_body(VENUE_SPEC)
    venue = {
        "id": new_id(),
        "name": body["name"],
        "city": body["city"],
        "tracking_tech": body["tracking_tech"],
        "required_certified_installations": body["required_certified_installations"],
        "transport_capacity_mbps": body["transport_capacity_mbps"],
        "min_achievable_latency_ms": body["min_achievable_latency_ms"],
        "data_posture": "UNCERTIFIED",
        "active_installation_count": 0,
        "certified_installation_count": 0,
        "recalibrating_installation_count": 0,
        "uncertified_installation_count": 0,
        "retired_installation_count": 0,
    }
    audit_new(venue)
    store.venues[venue["id"]] = venue
    return object_response(serialize(venue), 201)


@bp.get("/venues/<venue_id>")
def get_venue(venue_id):
    authenticate("LeagueDataOps", "CalibrationEngineer")
    venue = require_venue(venue_id)
    return object_response(serialize(venue))


@bp.get("/venues/<venue_id>/installations")
def list_venue_installations(venue_id):
    authenticate("LeagueDataOps", "CalibrationEngineer")
    require_venue(venue_id)
    limit, offset = pagination()
    status = string_filter("status")
    rows = db.installations_of_venue(venue_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


# --------------------------------------------------------------------------
# Installations
# --------------------------------------------------------------------------

@bp.post("/installations")
def create_installation():
    authenticate("LeagueDataOps")
    body = validate_body(INSTALLATION_SPEC)
    require_venue(body["venue_id"])
    installation = {
        "id": new_id(),
        "venue_id": body["venue_id"],
        "rig_label": body["rig_label"],
        "modality": body["modality"],
        "status": "DEPLOYED",
        "latest_run_result": None,
        "latest_run_composite_rms_mm": None,
        "latest_run_recorded_at_utc": None,
        "latest_run_engineer_user_id": None,
        "certified_at_utc": None,
        "certified_by_user_id": None,
        "calibration_run_count": 0,
        "drift_flag_count": 0,
    }
    audit_new(installation)
    store.installations[installation["id"]] = installation
    recompute_venue_census(installation["venue_id"])
    return object_response(serialize(installation), 201)


@bp.get("/installations/<installation_id>")
def get_installation(installation_id):
    authenticate("LeagueDataOps", "CalibrationEngineer")
    installation = require_installation(installation_id)
    return object_response(serialize(installation))


@bp.post("/installations/<installation_id>/calibration-runs")
def create_calibration_run(installation_id):
    principal = authenticate("CalibrationEngineer")
    installation = require_installation(installation_id)
    body = validate_body(CALIBRATION_RUN_SPEC)

    # rank 10: installation lifecycle
    if installation["status"] not in ("DEPLOYED", "CALIBRATING",
                                     "RECALIBRATION_REQUIRED"):
        raise ApiError("ERR_INVALID_INSTALLATION_STATE",
                       "A calibration run may only be recorded while the rig is "
                       "DEPLOYED, CALIBRATING or RECALIBRATION_REQUIRED.")

    composite, result = calibration_accuracy_evaluation(
        body["axis_rms_x_mm"], body["axis_rms_y_mm"], body["axis_rms_z_mm"],
        body["sample_count"], body["reference_point_count"])

    run = {
        "id": new_id(),
        "installation_id": installation["id"],
        "recorded_by_user_id": principal.user_id,
        "recorded_at_utc": store.clock_raw,
        "axis_rms_x_mm": body["axis_rms_x_mm"],
        "axis_rms_y_mm": body["axis_rms_y_mm"],
        "axis_rms_z_mm": body["axis_rms_z_mm"],
        "sample_count": body["sample_count"],
        "reference_point_count": body["reference_point_count"],
        "composite_rms_mm": num(composite),
        "result": result,
    }
    audit_new_immutable(run)
    store.calibration_runs[run["id"]] = run

    # The recording always moves the rig into CALIBRATING.
    installation["status"] = "CALIBRATING"
    installation["calibration_run_count"] = installation["calibration_run_count"] + 1
    _refresh_latest_run_mirrors(installation)
    touch(installation)
    recompute_venue_census(installation["venue_id"])

    # Immediately afterwards, and without any further call, a PASS auto-validates.
    if result == "PASS":
        installation["status"] = "VALIDATED"
        touch(installation)
        recompute_venue_census(installation["venue_id"])

    return object_response(serialize(run), 201)


def _refresh_latest_run_mirrors(installation):
    """Mirror the run with the greatest recorded_at_utc (created_at ASC tie-break,
    last written wins)."""
    runs = db.runs_of_installation(installation["id"])
    if not runs:
        installation["latest_run_result"] = None
        installation["latest_run_composite_rms_mm"] = None
        installation["latest_run_recorded_at_utc"] = None
        installation["latest_run_engineer_user_id"] = None
        return
    runs.sort(key=lambda r: (parse_dt(r["recorded_at_utc"]),
                             r.get("created_at") or "",
                             r.get("_seq", 0)))
    latest = runs[-1]
    installation["latest_run_result"] = latest["result"]
    installation["latest_run_composite_rms_mm"] = latest["composite_rms_mm"]
    installation["latest_run_recorded_at_utc"] = latest["recorded_at_utc"]
    installation["latest_run_engineer_user_id"] = latest["recorded_by_user_id"]


@bp.get("/installations/<installation_id>/calibration-runs")
def list_calibration_runs(installation_id):
    authenticate("LeagueDataOps", "CalibrationEngineer")
    require_installation(installation_id)
    limit, offset = pagination()
    # PRD §2.3: the one deliberate exception — newest first.
    rows = sorted_rows(db.runs_of_installation(installation_id), descending=True)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


@bp.post("/installations/<installation_id>/certify")
def certify_installation(installation_id):
    principal = authenticate("LeagueDataOps")
    installation = require_installation(installation_id)
    no_body()

    # rank 7: segregation of duties
    if (installation["latest_run_engineer_user_id"] is not None
            and principal.user_id == installation["latest_run_engineer_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The operator who recorded the run may not certify the rig.")

    # rank 9: the accuracy claim sits deliberately ahead of the lifecycle gate.
    if installation["latest_run_result"] != "PASS":
        raise ApiError("ERR_CALIBRATION_NOT_PASSING",
                       "The rig's latest calibration run did not pass.")

    # rank 10: lifecycle
    if installation["status"] != "VALIDATED":
        raise ApiError("ERR_INVALID_INSTALLATION_STATE",
                       "Only a VALIDATED rig may be certified.")

    # rank 26: calibration freshness
    recorded_at = parse_dt(installation["latest_run_recorded_at_utc"])
    if recorded_at is None or (store.clock - recorded_at) > timedelta(
            hours=CERT_VALIDITY_HOURS):
        raise ApiError("ERR_CALIBRATION_EXPIRED",
                       "The latest passing run is older than %d hours."
                       % CERT_VALIDITY_HOURS)

    installation["status"] = "CERTIFIED"
    installation["certified_at_utc"] = store.clock_raw
    installation["certified_by_user_id"] = principal.user_id
    touch(installation)
    recompute_venue_census(installation["venue_id"])
    return object_response(serialize(installation))


@bp.post("/installations/<installation_id>/flag-drift")
def flag_drift(installation_id):
    authenticate("CalibrationEngineer")
    installation = require_installation(installation_id)
    no_body()

    if installation["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_INSTALLATION_STATE",
                       "Only a CERTIFIED rig may be flagged for drift.")

    installation["status"] = "RECALIBRATION_REQUIRED"
    installation["drift_flag_count"] = installation["drift_flag_count"] + 1
    touch(installation)
    apply_installation_status_change(installation["venue_id"])
    return object_response(serialize(installation))


@bp.post("/installations/<installation_id>/retire")
def retire_installation(installation_id):
    authenticate("LeagueDataOps")
    installation = require_installation(installation_id)
    no_body()

    if installation["status"] not in ("CERTIFIED", "RECALIBRATION_REQUIRED"):
        raise ApiError("ERR_INVALID_INSTALLATION_STATE",
                       "Only a CERTIFIED or RECALIBRATION_REQUIRED rig may be "
                       "retired.")

    installation["status"] = "RETIRED"
    touch(installation)
    apply_installation_status_change(installation["venue_id"])
    return object_response(serialize(installation))
