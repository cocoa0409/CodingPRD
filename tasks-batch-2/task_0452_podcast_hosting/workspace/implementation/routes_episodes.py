"""Episode endpoints, publish axis, and DELETE (PRD §3.2)."""

from flask import request

import common
import db
import errors
import lifecycle
import ownership
import recompute
import serialize
from common import new_common, touch
from response import success, list_success
from routehelpers import auth_and_role, body
from timeutil import parse_iso


def register(app):
    @app.route("/episodes", methods=["POST"])
    def create_episode():
        caller = auth_and_role(["Publisher"])
        data = body()
        show_id = common.require_str(data, "show_id")
        title = common.require_str(data, "title")
        total_ad_slots = common.require_int(data, "total_ad_slots")
        if total_ad_slots < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "total_ad_slots must be >= 0")
        offered = common.require_field(data, "offered_positions")
        if not isinstance(offered, list) or any(p not in db.POSITIONS for p in offered):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offered_positions must be a subset of the position enum")
        # Existence + ownership of the parent show.
        show = ownership.get_show(show_id)
        ownership.assert_publisher_owns_show(caller, show)
        rec = new_common()
        rec.update({
            "show_id": show_id,
            "title": title,
            "duration_ms": 0,
            "total_ad_slots": total_ad_slots,
            "offered_positions": offered,
            "media_status": "NONE",
            "publish_status": "DRAFT",
            "scheduled_publish_at": None,
            "filled_slots": 0,
            "available_slots": total_ad_slots,
            "fill_rate": 0.0,
        })
        db.db.episodes[rec["id"]] = rec
        recompute.recompute_show_episode_count(show)
        return success(serialize.episode(rec), status=201)

    @app.route("/episodes", methods=["GET"])
    def list_episodes():
        auth_and_role(["PlatformAdmin", "Publisher", "Listener"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.episodes.values())
        show_id = request.args.get("show_id")
        if show_id:
            items = [e for e in items if e["show_id"] == show_id]
        ps = request.args.get("publish_status")
        if ps:
            items = [e for e in items if e["publish_status"] == ps]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.episode(e) for e in page], limit, offset, total)

    @app.route("/episodes/<eid>", methods=["GET"])
    def get_episode(eid):
        auth_and_role(["PlatformAdmin", "Publisher", "Listener", "Advertiser"])
        ep = ownership.get_episode(eid)
        return success(serialize.episode(ep), status=200)

    @app.route("/episodes/<eid>/schedule", methods=["POST"])
    def schedule_episode(eid):
        caller = auth_and_role(["Publisher"])
        ep = ownership.get_episode(eid)
        ownership.assert_publisher_owns_episode(caller, ep)
        # State: DRAFT -> SCHEDULED.
        if ep["publish_status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "Episode can only be scheduled from DRAFT")
        data = body()
        sched = common.require_str(data, "scheduled_publish_at")
        try:
            sched_dt = parse_iso(sched)
        except ValueError:
            raise errors.err(errors.ERR_INVALID_REQUEST, "scheduled_publish_at must be an ISO 8601 timestamp")
        # Business: must be strictly after the current logical clock.
        if sched_dt <= parse_iso(db.db.clock):
            raise errors.err(errors.ERR_SCHEDULE_IN_PAST, "scheduled_publish_at must be after the current clock")
        ep["publish_status"] = "SCHEDULED"
        ep["scheduled_publish_at"] = sched
        touch(ep)
        return success(serialize.episode(ep), status=200)

    @app.route("/episodes/<eid>/publish", methods=["POST"])
    def publish_episode(eid):
        caller = auth_and_role(["Publisher"])
        ep = ownership.get_episode(eid)
        ownership.assert_publisher_owns_episode(caller, ep)
        # State: from DRAFT/SCHEDULED/UNPUBLISHED, with show ACTIVE + media READY.
        if ep["publish_status"] not in ("DRAFT", "SCHEDULED", "UNPUBLISHED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Episode cannot be published from its current state")
        show = db.db.shows.get(ep["show_id"])
        if show is None or show["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Show must be ACTIVE to publish")
        if ep["media_status"] != "READY":
            raise errors.err(errors.ERR_INVALID_STATE, "Episode media must be READY to publish")
        ep["publish_status"] = "PUBLISHED"
        touch(ep)
        recompute.recompute_show_episode_count(show)
        return success(serialize.episode(ep), status=200)

    @app.route("/episodes/<eid>/unpublish", methods=["POST"])
    def unpublish_episode(eid):
        caller = auth_and_role(["Publisher"])
        ep = ownership.get_episode(eid)
        ownership.assert_publisher_owns_episode(caller, ep)
        if ep["publish_status"] != "PUBLISHED":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a PUBLISHED episode may be unpublished")
        ep["publish_status"] = "UNPUBLISHED"
        touch(ep)
        # Cancel PROPOSED/INSERTED placements, release reserves, recompute fill.
        lifecycle.unpublish_episode_cascade(ep)
        return success(serialize.episode(ep), status=200)

    @app.route("/episodes/<eid>", methods=["DELETE"])
    def delete_episode(eid):
        caller = auth_and_role(["Publisher"])
        ep = ownership.get_episode(eid)
        ownership.assert_publisher_owns_episode(caller, ep)
        if ep["publish_status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT episode may be deleted")
        ep["publish_status"] = "DELETED"
        touch(ep)
        show = db.db.shows.get(ep["show_id"])
        if show is not None:
            recompute.recompute_show_episode_count(show)
        return success(serialize.episode(ep), status=200)
