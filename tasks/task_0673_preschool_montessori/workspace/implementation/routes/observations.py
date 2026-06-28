"""Observation endpoints (PRD §3.12). Observations are immutable: id + created_at only."""
from flask import Blueprint

import errors
from db import db, new_common_fields, parse_iso
from middleware import get_auth, require_role
from response import object_response, array_response
from services.common import (
    get_json_body, require_fields, require_non_empty_string, parse_pagination,
    sort_created_asc, paginate, serialize, serialize_list, str_arg,
)

bp = Blueprint("observations", __name__)

RW_ROLES = {"Registrar", "ComplianceOfficer"}


def _overlaps_closed(a_start, a_end, b_start, b_end):
    # Closed interval: shared endpoints DO conflict -> use <= / >=.
    return a_start <= b_end and b_start <= a_end


@bp.route("/observations", methods=["POST"])
def create_observation():
    _, role = get_auth()
    require_role(role, RW_ROLES)
    body = get_json_body()
    require_fields(body, ["classroom_id", "observer_name", "window_start_at", "window_end_at"])

    classroom_id = body["classroom_id"]
    if not isinstance(classroom_id, str):
        raise errors.invalid_request("classroom_id must be a string.")
    observer_name = require_non_empty_string(body, "observer_name")
    window_start_at = body["window_start_at"]
    window_end_at = body["window_end_at"]
    for val, label in ((window_start_at, "window_start_at"), (window_end_at, "window_end_at")):
        if not isinstance(val, str):
            raise errors.invalid_request(f"{label} must be an ISO 8601 string.")
    try:
        start_dt = parse_iso(window_start_at)
        end_dt = parse_iso(window_end_at)
    except (ValueError, TypeError):
        raise errors.invalid_request("window_start_at/window_end_at must be valid ISO 8601 instants.")

    # Body FK existence (PRD §2.9): classroom.
    if classroom_id not in db.classrooms:
        raise errors.not_found("classroom_id does not exist.")

    # Overlap guard (priority 11) BEFORE interval validity (priority 12) per §2.10.
    for other in db.observations.values():
        if other["classroom_id"] != classroom_id:
            continue
        if _overlaps_closed(start_dt, end_dt, parse_iso(other["window_start_at"]), parse_iso(other["window_end_at"])):
            raise errors.observation_overlap()

    # Interval validity (priority 12): window_end_at > window_start_at.
    if not (end_dt > start_dt):
        raise errors.invalid_interval()

    obs = new_common_fields(versioned=False)
    obs.update({
        "classroom_id": classroom_id,
        "observer_name": observer_name,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    })
    db.observations[obs["id"]] = obs
    return object_response(serialize(obs), 201)


@bp.route("/observations/<obs_id>", methods=["GET"])
def get_observation(obs_id):
    _, role = get_auth()
    require_role(role, RW_ROLES)
    obs = db.observations.get(obs_id)
    if obs is None:
        raise errors.not_found("Observation not found.")
    return object_response(serialize(obs), 200)


@bp.route("/observations", methods=["GET"])
def list_observations():
    _, role = get_auth()
    require_role(role, RW_ROLES)
    limit, offset = parse_pagination()
    classroom_id = str_arg("classroom_id")

    records = list(db.observations.values())
    if classroom_id is not None:
        records = [o for o in records if o["classroom_id"] == classroom_id]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)
