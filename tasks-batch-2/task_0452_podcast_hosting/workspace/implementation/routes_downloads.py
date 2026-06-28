"""DownloadEvent ingestion and IAB analytics (PRD §3.7)."""

from flask import request

import common
import db
import errors
import ownership
import serialize
from common import touch
from db import new_id
from response import success, list_success
from routehelpers import auth_and_role, body
from timeutil import parse_iso, clock_iso_ms


def register(app):
    @app.route("/download-events", methods=["POST"])
    def create_download_event():
        auth_and_role(["PlatformAdmin", "Listener"])
        data = body()
        episode_id = common.require_str(data, "episode_id")
        client_ip_hash = common.require_str(data, "client_ip_hash")
        user_agent = common.require_str(data, "user_agent")
        bytes_served = common.require_int(data, "bytes_served")
        if bytes_served < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "bytes_served must be >= 0")
        event_at = common.require_str(data, "event_at")
        try:
            parse_iso(event_at)
        except ValueError:
            raise errors.err(errors.ERR_INVALID_REQUEST, "event_at must be an ISO 8601 timestamp")
        placement_id = data.get("placement_id")
        access_token = data.get("access_token")
        # Existence: episode, and placement when supplied.
        episode = ownership.get_episode(episode_id)
        placement = None
        if placement_id is not None:
            if not isinstance(placement_id, str):
                raise errors.err(errors.ERR_INVALID_REQUEST, "placement_id must be a string")
            placement = ownership.get_placement(placement_id)
        # Paywall gate (priority 9): private-only show needs a valid ACTIVE
        # subscription access token (PRD §3.7).
        if _is_private_only(episode["show_id"]):
            if not _valid_private_access(episode["show_id"], access_token):
                raise errors.err(errors.ERR_NO_PRIVATE_ACCESS,
                                 "Private episode requires an ACTIVE subscription access token")
        # counted = bytes_served >= IAB minimum (inclusive at threshold).
        counted = bytes_served >= db.IAB_MIN_BYTES
        # created_at records platform time (logical clock, PRD §2.9/§2.4).
        ts = clock_iso_ms()
        rec = {
            "id": new_id(),
            "created_at": ts,
            "episode_id": episode_id,
            "placement_id": placement_id,
            "client_ip_hash": client_ip_hash,
            "user_agent": user_agent,
            "bytes_served": bytes_served,
            "counted": counted,
            "event_at": event_at,
        }
        db.db.download_events[rec["id"]] = rec
        # Only a counted event with a non-null placement credits the placement.
        if counted and placement is not None:
            placement["delivered_impressions"] += 1
            touch(placement)
        return success(serialize.download_event(rec), status=201)

    @app.route("/download-events", methods=["GET"])
    def list_download_events():
        auth_and_role(["PlatformAdmin", "Publisher"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.download_events.values())
        episode_id = request.args.get("episode_id")
        if episode_id:
            items = [d for d in items if d["episode_id"] == episode_id]
        placement_id = request.args.get("placement_id")
        if placement_id:
            items = [d for d in items if d["placement_id"] == placement_id]
        counted = request.args.get("counted")
        if counted is not None and counted != "":
            want = counted.lower() == "true"
            items = [d for d in items if d["counted"] == want]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.download_event(d) for d in page], limit, offset, total)

    @app.route("/download-events/<did>", methods=["GET"])
    def get_download_event(did):
        auth_and_role(["PlatformAdmin", "Publisher"])
        d = ownership.get_download_event(did)
        return success(serialize.download_event(d), status=200)


def _is_private_only(show_id):
    """True iff the show has at least one feed and every feed is PRIVATE (PRD §3.7)."""
    feeds = [f for f in db.db.feeds.values() if f["show_id"] == show_id]
    if not feeds:
        return False
    return all(f["visibility"] == "PRIVATE" for f in feeds)


def _valid_private_access(show_id, access_token):
    if not access_token or not isinstance(access_token, str):
        return False
    for s in db.db.subscriptions.values():
        if (s["show_id"] == show_id and s["status"] == "ACTIVE"
                and s.get("access_token") == access_token):
            return True
    return False
