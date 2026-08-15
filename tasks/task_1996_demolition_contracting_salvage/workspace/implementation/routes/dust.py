"""DustNoiseLog endpoints: append-only monitoring events with exposure-score
computation and the exceedance stoppage cascade."""

import uuid
from decimal import Decimal

from flask import Blueprint

from db import store, now, next_seq, touch
from errors import err, ERR_INVALID_STATE, ERR_VALIDATION
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_dust_log
from services import (get_project, children, project_inspections, wind_factor,
                      RAW_CAP, DUST_EXCEEDANCE_THRESHOLD, PROJECT_ACTIVE_PHASES)
from util import req_enum, req_number, round1

bp = Blueprint("dust", __name__)

READING_TYPES = ("PM25", "PM10", "NOISE_DB")
DUST_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "EnvironmentalMonitor")


@bp.post("/demolition/projects/<pid>/dust-noise-logs")
@require_roles("EnvironmentalMonitor")
def create_dust_log(pid):
    b = body()
    reading_type = req_enum(b, "reading_type", READING_TYPES)
    measured_value = req_number(b, "measured_value")
    if measured_value < 0:
        raise err(ERR_VALIDATION, "measured_value must be >= 0")
    wind_speed = req_number(b, "wind_speed_mph")
    if wind_speed < 0:
        raise err(ERR_VALIDATION, "wind_speed_mph must be >= 0")
    duration = req_number(b, "duration_hours")
    if duration <= 0:
        raise err(ERR_VALIDATION, "duration_hours must be > 0")

    project = get_project(pid)
    if project["status"] not in PROJECT_ACTIVE_PHASES:
        raise err(ERR_INVALID_STATE, "monitoring events require an active project phase")

    raw = measured_value * wind_factor(wind_speed) * duration
    score = round1(min(raw, RAW_CAP) / Decimal("10"))
    is_exceedance = score >= DUST_EXCEEDANCE_THRESHOLD

    current = now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": current,
        "_seq": next_seq(),
        "project_id": project["id"],
        "reading_type": reading_type,
        "measured_value": measured_value,
        "wind_speed_mph": wind_speed,
        "duration_hours": duration,
        "exposure_score": score,
        "is_exceedance": is_exceedance,
        "recorded_at": current,
    }
    store.dust_logs[rec["id"]] = rec

    project["cumulative_exposure_score"] += score
    if is_exceedance:
        project["work_posture"] = "STOPPED"
        for insp in project_inspections(project["id"]):
            if insp["status"] == "SCHEDULED":
                insp["status"] = "CANCELLED"
                touch(insp)
    touch(project)
    return success(ser_dust_log(rec), status=201)


@bp.get("/demolition/projects/<pid>/dust-noise-logs")
@require_roles(*DUST_READ_ROLES)
def list_dust_logs(pid):
    project = get_project(pid)
    return list_response(children(store.dust_logs, "project_id", project["id"]), ser_dust_log)
