"""Episode endpoints: create, get, list, PUBLISH / FINALIZE_MEASUREMENT,
episode-scoped download listing."""

from flask import Blueprint, request

import db
from errors import (
    err_not_found,
    err_invalid,
    err_conflict,
    ERR_EPISODE_NOT_PUBLISHED,
    ERR_EPISODE_NOT_DUE,
    ERR_MEASUREMENT_WINDOW_OPEN,
)
from helpers import (
    body_of,
    new_id,
    now_timestamp,
    require_string,
    require_timestamp,
    optional_int,
    parse_dt,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response, serialize
from services import Changes, recompute_show, finalize_episode
from datetime import timedelta

bp = Blueprint("episodes", __name__)


def get_episode_or_404(episode_id):
    episode = db.episodes.get(episode_id)
    if episode is None:
        raise err_not_found(f"Episode '{episode_id}' not found")
    return episode


@bp.route("/adnet/episodes", methods=["POST"])
def create_episode():
    require_roles({"AdOps"})
    body = body_of(request)
    show_id = body.get("show_id")
    if isinstance(show_id, str) and show_id not in db.shows:
        raise err_not_found(f"Show '{show_id}' not found")

    show_id = require_string(body, "show_id")
    title = require_string(body, "title")
    publish_at = require_timestamp(body, "publish_at")
    measurement_window_days = optional_int(
        body, "measurement_window_days", default=30, minimum=1, maximum=90
    )
    slot_capacity = optional_int(body, "slot_capacity", default=2, minimum=1, maximum=5)

    ts = now_timestamp()
    episode = {
        "id": new_id(),
        "show_id": show_id,
        "title": title,
        "publish_at": publish_at,
        "measurement_window_days": measurement_window_days,
        "slot_capacity": slot_capacity,
        "status": "SCHEDULED",
        "provisional_download_count": 0,
        "measured_download_count": 0,
        "slots_in_use": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.episodes[episode["id"]] = episode
    ch = Changes()
    show = db.shows.get(show_id)
    if show is not None:
        recompute_show(show, ch)
    ch.commit()
    return success_object(serialize(episode), 201)


@bp.route("/adnet/episodes/<episode_id>", methods=["GET"])
def get_episode(episode_id):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_episode_or_404(episode_id)))


@bp.route("/adnet/episodes", methods=["GET"])
def list_episodes():
    require_roles(ALL_ROLES)
    items = list(db.episodes.values())
    show_id = request.args.get("show_id")
    status = request.args.get("status")
    if show_id is not None:
        items = [e for e in items if e["show_id"] == show_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response(items, request.args)


@bp.route("/adnet/episodes/<episode_id>/transition", methods=["POST"])
def transition_episode(episode_id):
    require_roles({"AdOps"})
    episode = get_episode_or_404(episode_id)
    body = body_of(request)
    action = body.get("action")
    if action not in ("PUBLISH", "FINALIZE_MEASUREMENT"):
        raise err_invalid("Field 'action' must be one of PUBLISH, FINALIZE_MEASUREMENT")

    now = db.current_dt()
    publish_at = parse_dt(episode["publish_at"])

    if action == "PUBLISH":
        if episode["status"] != "SCHEDULED":
            raise err_conflict(
                ERR_EPISODE_NOT_PUBLISHED,
                f"Episode is {episode['status']}; PUBLISH requires SCHEDULED",
            )
        if now < publish_at:
            raise err_conflict(
                ERR_EPISODE_NOT_DUE, "Episode publish_at has not been reached by the clock"
            )
        ch = Changes()
        ch.update(episode, status="PUBLISHED")
        show = db.shows.get(episode["show_id"])
        if show is not None:
            recompute_show(show, ch)
        ch.commit()
        return success_object(serialize(episode))

    # FINALIZE_MEASUREMENT
    if episode["status"] != "PUBLISHED":
        raise err_conflict(
            ERR_EPISODE_NOT_PUBLISHED,
            f"Episode is {episode['status']}; FINALIZE_MEASUREMENT requires PUBLISHED",
        )
    window_close = publish_at + timedelta(days=episode["measurement_window_days"])
    if not (now > window_close):
        raise err_conflict(
            ERR_MEASUREMENT_WINDOW_OPEN,
            "Measurement window is still open (clock must be strictly past publish_at + measurement_window_days)",
        )
    ch = Changes()
    finalize_episode(episode, ch)
    ch.commit()
    return success_object(serialize(episode))


@bp.route("/adnet/episodes/<episode_id>/downloads", methods=["GET"])
def list_episode_downloads(episode_id):
    require_roles({"AdOps", "Finance"})
    episode = get_episode_or_404(episode_id)
    items = [d for d in db.downloads.values() if d["episode_id"] == episode["id"]]
    return list_response(items, request.args)
