"""FrostEvent endpoints: declare, get, list, activate/complete/cancel.

Completion requires actual_min_temp_c and computes damage_flag; a damaging
completion cascades: the bog+season's APPROVED estimate flips to FLAGGED,
which triggers a MemberQuota recompute (and possibly a posture flip).
"""
from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, ANY_ROLE
from response import ok, created, paginate
from services import quota as quota_service
from services import scheduling
from validation import (get_body, req_string, req_number, req_datetime, req_enum,
                        opt_number)
from validation import to_decimal

bp = Blueprint("frost", __name__)

FROST_STATUSES = {"DECLARED", "ACTIVE", "COMPLETED", "CANCELLED"}
FROST_TRANSITIONS = {
    ("DECLARED", "ACTIVE"),
    ("ACTIVE", "COMPLETED"),
    ("DECLARED", "CANCELLED"),
    ("ACTIVE", "CANCELLED"),
}


def get_event_or_404(event_id):
    event = store.frost_events.get(event_id)
    if event is None:
        raise ApiError("ERR_NOT_FOUND", 404, "FrostEvent not found")
    return event


@bp.post("/coop/frost-events")
def create_event():
    body = get_body()
    bog_id = req_string(body, "bog_id")
    season_id = req_string(body, "season_id")
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    forecast = req_number(body, "forecast_min_temp_c")

    _, role = authenticate()
    require_roles(role, {"FieldOfficer"})

    bog = store.bogs.get(bog_id)
    if bog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Bog not found")
    if season_id not in store.seasons:
        raise ApiError("ERR_NOT_FOUND", 404, "Season not found")

    scheduling.check_window_sanity(window_start, window_end)
    scheduling.check_water_conflict(bog_id, window_start, window_end)

    event = new_common({
        "bog_id": bog_id,
        "season_id": season_id,
        "window_start": window_start,
        "window_end": window_end,
        "forecast_min_temp_c": forecast,
        "actual_min_temp_c": None,
        "damage_flag": False,
        "status": "DECLARED",
    })
    store.frost_events[event["id"]] = event
    return created(event)


@bp.get("/coop/frost-events/<event_id>")
def get_event(event_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_event_or_404(event_id))


@bp.get("/coop/frost-events")
def list_events():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.frost_events.values())
    rows = paginate.filter(rows, "bog_id")
    rows = paginate.filter(rows, "season_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/coop/frost-events/<event_id>/transition")
def transition_event(event_id):
    body = get_body()
    to = req_enum(body, "to", FROST_STATUSES)
    actual = opt_number(body, "actual_min_temp_c")
    if to == "COMPLETED" and actual is None:
        raise ApiError("ERR_VALIDATION", 400,
                       "actual_min_temp_c is required to complete a frost event")

    _, role = authenticate()
    require_roles(role, {"FieldOfficer"})

    event = get_event_or_404(event_id)

    if (event["status"], to) not in FROST_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Frost event transition %s -> %s is not defined"
                       % (event["status"], to))

    if to == "COMPLETED":
        event["actual_min_temp_c"] = actual
        bog = store.bogs.get(event["bog_id"])
        threshold = to_decimal(bog["frost_damage_threshold_c"]) if bog else None
        damage = threshold is not None and to_decimal(actual) <= threshold
        event["damage_flag"] = damage
        event["status"] = "COMPLETED"
        touch(event)
        if damage:
            # Damage cascade: APPROVED estimate for (bog, season) -> FLAGGED,
            # which itself triggers a MemberQuota recompute / posture flip.
            est = quota_service.approved_estimate_for(event["bog_id"], event["season_id"])
            if est is not None:
                est["status"] = "FLAGGED"
                touch(est)
                quota = quota_service.find_quota(est["member_id"], est["season_id"])
                if quota is not None:
                    quota_service.recompute_quota(quota)
    else:
        event["status"] = to
        touch(event)

    return ok(event)
