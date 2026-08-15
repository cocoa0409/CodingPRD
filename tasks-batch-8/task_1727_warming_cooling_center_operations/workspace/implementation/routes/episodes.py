"""Episode lifecycle, weather readings, ops sweep, logical clock."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_TRIGGER_NOT_MET,
    ERR_NO_SITES_DESIGNATED, ERR_EPISODE_NOT_ACTIVE, ERR_STALE_VERSION,
    ERR_INVALID_WINDOW, ERR_VALIDATION,
)
from flask import Blueprint, g
from response import respond, respond_list
from services import (
    evaluate_breach, episode_readings, episodes_activations,
    deactivate_episode, resurge_episode, ops_sweep, ser_episode,
    ser_reading,
)
from util import (
    body, req_enum, req_num, req_int, req_dt, req_field, paginate, touch,
    parse_datetime, render_dt,
)

bp = Blueprint("episodes", __name__)

MODES = ("WARMING", "COOLING")
SOURCES = ("NWS", "MANUAL")


def get_episode(episode_id):
    ep = db.store["episodes"].get(episode_id)
    if ep is None:
        raise_err(ERR_NOT_FOUND, f"Episode {episode_id} not found")
    return ep


@bp.route("/episodes", methods=["POST"])
@require_roles("EOCManager")
def create_episode():
    b = body()
    mode = req_enum(b, "mode", MODES)
    threshold_f = req_num(b, "threshold_f")
    shr = req_int(b, "sustained_hours_required", min_value=1)
    scheduled_end_at = req_dt(b, "scheduled_end_at")
    now = clock.now()
    ep = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "mode": mode,
        "threshold_f": threshold_f,
        "sustained_hours_required": shr,
        "scheduled_end_at": scheduled_end_at,
        "status": "STANDBY",
        "trigger_met": False,
        "breach_run_minutes": 0,
        "activated_at": None,
        "activated_by_user_id": None,
        "deactivated_at": None,
        "extension_count": 0,
        "ops_run_index": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["episodes"][ep["id"]] = ep
    return respond(ser_episode(ep), 201)


@bp.route("/episodes/<episode_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_episode(episode_id):
    return respond(ser_episode(get_episode(episode_id)), 200)


@bp.route("/episodes/<episode_id>/weather-readings", methods=["POST"])
@require_roles("EOCManager")
def append_reading(episode_id):
    ep = get_episode(episode_id)
    b = body()
    observed_at = req_dt(b, "observed_at")
    temp_f = req_num(b, "temp_f")
    heat_index_f = req_num(b, "heat_index_f")
    source = b.get("source")
    if source is None:
        source = "MANUAL"
    elif source not in SOURCES:
        raise_err(ERR_VALIDATION, "source must be NWS or MANUAL")
    r = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "episode_id": ep["id"],
        "observed_at": observed_at,
        "temp_f": temp_f,
        "heat_index_f": heat_index_f,
        "source": source,
        "created_at": clock.now(),
    }
    db.store["readings"][r["id"]] = r
    evaluate_breach(ep)
    return respond(ser_reading(r), 201)


@bp.route("/episodes/<episode_id>/weather-readings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_readings(episode_id):
    get_episode(episode_id)
    items = [ser_reading(r) for r in episode_readings(episode_id)]
    page, pagination = paginate(items)
    return respond_list(page, pagination)


@bp.route("/episodes/<episode_id>/evaluate", methods=["POST"])
@require_roles("EOCManager")
def evaluate(episode_id):
    ep = get_episode(episode_id)
    evaluate_breach(ep)
    status = ep["status"]
    if status == "STANDBY":
        if ep["trigger_met"]:
            ep["status"] = "ACTIVATING"
            touch(ep)
    elif status == "ACTIVATING":
        if not ep["trigger_met"]:
            ep["status"] = "STANDBY"
            touch(ep)
    elif status == "DEACTIVATING":
        if ep["trigger_met"]:
            resurge_episode(ep)
    else:  # ACTIVE, DEACTIVATED, CLOSED
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot evaluate an episode in status {status}",
        )
    return respond(ser_episode(ep), 200)


@bp.route("/episodes/<episode_id>/activate", methods=["POST"])
@require_roles("EOCManager")
def activate(episode_id):
    ep = get_episode(episode_id)
    if ep["status"] != "ACTIVATING":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot activate an episode in status {ep['status']}",
        )
    evaluate_breach(ep)
    if not ep["trigger_met"]:
        raise_err(ERR_TRIGGER_NOT_MET, "Trigger is not met")
    designated = any(
        a["status"] in ("OPENING", "OPEN")
        for a in episodes_activations(ep["id"])
    )
    if not designated:
        raise_err(
            ERR_NO_SITES_DESIGNATED,
            "No site activation in OPENING or OPEN for this episode",
        )
    ep["status"] = "ACTIVE"
    if ep["activated_at"] is None:
        ep["activated_at"] = clock.now()
        ep["activated_by_user_id"] = g.user_id
    touch(ep)
    return respond(ser_episode(ep), 200)


@bp.route("/episodes/<episode_id>/extensions", methods=["POST"])
@require_roles("EOCManager")
def extend(episode_id):
    ep = get_episode(episode_id)
    b = body()
    # OCC guard (priority 4) precedes state and payload checks.
    if "expected_episode_version" not in b or b["expected_episode_version"] is None:
        raise_err(ERR_VALIDATION, "Missing required field: expected_episode_version")
    expected = b["expected_episode_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_VALIDATION, "expected_episode_version must be an integer")
    if expected != ep["version"]:
        raise_err(
            ERR_STALE_VERSION,
            f"expected_episode_version {expected} does not match current "
            f"version {ep['version']}",
        )
    if ep["status"] != "ACTIVE":
        raise_err(
            ERR_EPISODE_NOT_ACTIVE,
            f"Extensions require the episode to be ACTIVE (currently "
            f"{ep['status']})",
        )
    new_end = req_dt(b, "new_scheduled_end_at")
    if new_end <= ep["scheduled_end_at"]:
        raise_err(
            ERR_INVALID_WINDOW,
            "new_scheduled_end_at must be strictly after the current "
            "scheduled_end_at",
        )
    ep["scheduled_end_at"] = new_end
    ep["extension_count"] += 1
    touch(ep)
    return respond(ser_episode(ep), 200)


@bp.route("/episodes/<episode_id>/deactivate", methods=["POST"])
@require_roles("EOCManager")
def deactivate(episode_id):
    ep = get_episode(episode_id)
    if ep["status"] != "ACTIVE":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot deactivate an episode in status {ep['status']}",
        )
    deactivate_episode(ep)
    return respond(ser_episode(ep), 200)


@bp.route("/episodes/<episode_id>/run-ops", methods=["POST"])
@require_roles("EOCManager")
def run_ops(episode_id):
    ep = get_episode(episode_id)
    ops_sweep(ep)
    return respond(ser_episode(ep), 200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("EOCManager")
def set_clock():
    b = body()
    to = parse_datetime(req_field(b, "to_iso8601"), "to_iso8601")
    clock.set_current(to)
    return respond({"current_utc": render_dt(clock.now())}, 200)
