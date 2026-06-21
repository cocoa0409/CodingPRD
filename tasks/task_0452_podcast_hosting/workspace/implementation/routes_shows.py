"""Show endpoints and lifecycle (PRD §3.1, §2.6 cascade)."""

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


def register(app):
    @app.route("/shows", methods=["POST"])
    def create_show():
        caller = auth_and_role(["Publisher"])
        data = body()
        publisher_id = common.require_str(data, "publisher_id")
        title = common.require_str(data, "title")
        category = common.require_enum(data, "category", db.CATEGORIES)
        monetization = common.optional_bool(data, "monetization_enabled", False)
        # Ownership (priority 3): the acting Publisher must be creating under
        # their own id, before existence is resolved.
        if publisher_id != caller.user_id:
            raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Publisher may only create shows under their own id")
        # Existence (priority 4).
        ownership.get_publisher(publisher_id)
        rec = new_common()
        rec.update({
            "publisher_id": publisher_id,
            "title": title,
            "category": category,
            "status": "DRAFT",
            "monetization_enabled": monetization,
            "episode_count": 0,
        })
        db.db.shows[rec["id"]] = rec
        return success(serialize.show(rec), status=201)

    @app.route("/shows", methods=["GET"])
    def list_shows():
        auth_and_role(["PlatformAdmin", "Publisher", "Listener"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.shows.values())
        pub = request.args.get("publisher_id")
        if pub:
            items = [s for s in items if s["publisher_id"] == pub]
        status = request.args.get("status")
        if status:
            items = [s for s in items if s["status"] == status]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.show(s) for s in page], limit, offset, total)

    @app.route("/shows/<sid>", methods=["GET"])
    def get_show(sid):
        auth_and_role(["PlatformAdmin", "Publisher", "Listener"])
        show = ownership.get_show(sid)
        return success(serialize.show(show), status=200)

    @app.route("/shows/<sid>/activate", methods=["POST"])
    def activate_show(sid):
        caller = auth_and_role(["Publisher", "PlatformAdmin"])
        show = ownership.get_show(sid)
        # Ownership: Publisher must own; PlatformAdmin exempt.
        ownership.assert_publisher_owns_show(caller, show)
        # State: DRAFT/SUSPENDED -> ACTIVE.
        if show["status"] not in ("DRAFT", "SUSPENDED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Show cannot be activated from its current state")
        show["status"] = "ACTIVE"
        touch(show)
        return success(serialize.show(show), status=200)

    @app.route("/shows/<sid>/suspend", methods=["POST"])
    def suspend_show(sid):
        auth_and_role(["PlatformAdmin"])
        show = ownership.get_show(sid)
        if show["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE show may be suspended")
        show["status"] = "SUSPENDED"
        touch(show)
        # Three-level cascade (PRD §3.1).
        lifecycle.suspend_show_cascade(show)
        recompute.recompute_show_episode_count(show)
        return success(serialize.show(show), status=200)

    @app.route("/shows/<sid>/archive", methods=["POST"])
    def archive_show(sid):
        caller = auth_and_role(["Publisher"])
        show = ownership.get_show(sid)
        ownership.assert_publisher_owns_show(caller, show)
        # State: archival valid from DRAFT or ACTIVE; from SUSPENDED -> INVALID_STATE.
        if show["status"] not in ("DRAFT", "ACTIVE"):
            raise errors.err(errors.ERR_INVALID_STATE, "Show cannot be archived from its current state")
        # From ACTIVE, refuse if any episode is still PUBLISHED.
        if show["status"] == "ACTIVE":
            for e in db.db.episodes.values():
                if e["show_id"] == show["id"] and e["publish_status"] == "PUBLISHED":
                    raise errors.err(errors.ERR_SHOW_HAS_PUBLISHED_EPISODES,
                                     "Show has published episodes; unpublish them first")
        show["status"] = "ARCHIVED"
        touch(show)
        lifecycle.archive_show_disable_feeds(show)
        return success(serialize.show(show), status=200)
