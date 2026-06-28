"""Distribution endpoints and lifecycle (PRD §3.3)."""

import secrets

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
    @app.route("/distributions", methods=["POST"])
    def create_distribution():
        caller = auth_and_role(["Publisher"])
        data = body()
        show_id = common.require_str(data, "show_id")
        channel = common.require_enum(data, "channel", db.CHANNELS)
        show = ownership.get_show(show_id)
        ownership.assert_publisher_owns_show(caller, show)
        rec = new_common()
        rec.update({
            "show_id": show_id,
            "channel": channel,
            "status": "PENDING",
            "external_ref": None,
        })
        db.db.distributions[rec["id"]] = rec
        return success(serialize.distribution(rec), status=201)

    @app.route("/distributions", methods=["GET"])
    def list_distributions():
        auth_and_role(["PlatformAdmin", "Publisher"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.distributions.values())
        show_id = request.args.get("show_id")
        if show_id:
            items = [d for d in items if d["show_id"] == show_id]
        channel = request.args.get("channel")
        if channel:
            items = [d for d in items if d["channel"] == channel]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.distribution(d) for d in page], limit, offset, total)

    @app.route("/distributions/<did>", methods=["GET"])
    def get_distribution(did):
        auth_and_role(["PlatformAdmin", "Publisher"])
        d = ownership.get_distribution(did)
        return success(serialize.distribution(d), status=200)

    @app.route("/distributions/<did>/approve", methods=["POST"])
    def approve_distribution(did):
        auth_and_role(["PlatformAdmin"])
        d = ownership.get_distribution(did)
        if d["status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a PENDING distribution may be approved")
        # Requires Show ACTIVE and a PUBLIC ENABLED feed (PRD §3.3).
        show = db.db.shows.get(d["show_id"])
        if show is None or show["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Show must be ACTIVE to approve distribution")
        if not _has_public_enabled_feed(d["show_id"]):
            raise errors.err(errors.ERR_INVALID_STATE, "Show must have a PUBLIC ENABLED feed to approve distribution")
        d["status"] = "LIVE"
        d["external_ref"] = "ext_" + secrets.token_hex(8)
        touch(d)
        return success(serialize.distribution(d), status=200)

    @app.route("/distributions/<did>/reject", methods=["POST"])
    def reject_distribution(did):
        auth_and_role(["PlatformAdmin"])
        d = ownership.get_distribution(did)
        if d["status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a PENDING distribution may be rejected")
        d["status"] = "REJECTED"
        touch(d)
        return success(serialize.distribution(d), status=200)

    @app.route("/distributions/<did>/remove", methods=["POST"])
    def remove_distribution(did):
        caller = auth_and_role(["Publisher", "PlatformAdmin"])
        d = ownership.get_distribution(did)
        # Owner-or-admin (PRD §3.3): Publisher must own; PlatformAdmin exempt.
        ownership.assert_publisher_owns_distribution(caller, d)
        if d["status"] not in ("LIVE", "REJECTED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Distribution cannot be removed from its current state")
        d["status"] = "REMOVED"
        touch(d)
        return success(serialize.distribution(d), status=200)


def _has_public_enabled_feed(show_id):
    for f in db.db.feeds.values():
        if f["show_id"] == show_id and f["visibility"] == "PUBLIC" and f["status"] == "ENABLED":
            return True
    return False
