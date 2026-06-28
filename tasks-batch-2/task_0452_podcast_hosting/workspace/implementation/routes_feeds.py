"""Feed endpoints and lifecycle (PRD §3.3)."""

from flask import request

import common
import db
import errors
import ownership
import serialize
from common import new_common, touch
from response import success, list_success
from routehelpers import auth_and_role, body


def register(app):
    @app.route("/feeds", methods=["POST"])
    def create_feed():
        caller = auth_and_role(["Publisher"])
        data = body()
        show_id = common.require_str(data, "show_id")
        visibility = common.require_enum(data, "visibility", db.VISIBILITIES)
        show = ownership.get_show(show_id)
        ownership.assert_publisher_owns_show(caller, show)
        rec = new_common()
        rec.update({
            "show_id": show_id,
            "visibility": visibility,
            "status": "ENABLED",
            "token_required": (visibility == "PRIVATE"),
        })
        db.db.feeds[rec["id"]] = rec
        return success(serialize.feed(rec), status=201)

    @app.route("/feeds", methods=["GET"])
    def list_feeds():
        auth_and_role(["PlatformAdmin", "Publisher", "Listener"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.feeds.values())
        show_id = request.args.get("show_id")
        if show_id:
            items = [f for f in items if f["show_id"] == show_id]
        visibility = request.args.get("visibility")
        if visibility:
            items = [f for f in items if f["visibility"] == visibility]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.feed(f) for f in page], limit, offset, total)

    @app.route("/feeds/<fid>", methods=["GET"])
    def get_feed(fid):
        auth_and_role(["PlatformAdmin", "Publisher", "Listener"])
        f = ownership.get_feed(fid)
        return success(serialize.feed(f), status=200)

    @app.route("/feeds/<fid>/disable", methods=["POST"])
    def disable_feed(fid):
        caller = auth_and_role(["Publisher"])
        f = ownership.get_feed(fid)
        ownership.assert_publisher_owns_feed(caller, f)
        if f["status"] != "ENABLED":
            raise errors.err(errors.ERR_INVALID_STATE, "Only an ENABLED feed may be disabled")
        f["status"] = "DISABLED"
        touch(f)
        return success(serialize.feed(f), status=200)

    @app.route("/feeds/<fid>/enable", methods=["POST"])
    def enable_feed(fid):
        caller = auth_and_role(["Publisher"])
        f = ownership.get_feed(fid)
        ownership.assert_publisher_owns_feed(caller, f)
        if f["status"] != "DISABLED":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a DISABLED feed may be enabled")
        # Re-enabling is refused when the show is ARCHIVED (PRD §3.3).
        show = db.db.shows.get(f["show_id"])
        if show is not None and show["status"] == "ARCHIVED":
            raise errors.err(errors.ERR_INVALID_STATE, "Cannot enable a feed on an archived show")
        f["status"] = "ENABLED"
        touch(f)
        return success(serialize.feed(f), status=200)
