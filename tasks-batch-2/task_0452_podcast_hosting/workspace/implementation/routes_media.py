"""MediaAsset endpoints; drives the episode media axis (PRD §3.2)."""

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
    @app.route("/media-assets", methods=["POST"])
    def create_media():
        caller = auth_and_role(["Publisher"])
        data = body()
        episode_id = common.require_str(data, "episode_id")
        source_filename = common.require_str(data, "source_filename")
        source_duration_ms = common.require_int(data, "source_duration_ms")
        if source_duration_ms <= 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "source_duration_ms must be > 0")
        episode = ownership.get_episode(episode_id)
        ownership.assert_publisher_owns_episode(caller, episode)
        rec = new_common()
        rec.update({
            "episode_id": episode_id,
            "source_filename": source_filename,
            "source_duration_ms": source_duration_ms,
            "status": "UPLOADED",
            "transcode_attempts": 0,
            "output_duration_ms": 0,
        })
        db.db.media_assets[rec["id"]] = rec
        # Episode media_status NONE -> PENDING (PRD §3.2).
        episode["media_status"] = "PENDING"
        touch(episode)
        return success(serialize.media_asset(rec), status=201)

    @app.route("/media-assets", methods=["GET"])
    def list_media():
        auth_and_role(["PlatformAdmin", "Publisher"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.media_assets.values())
        episode_id = request.args.get("episode_id")
        if episode_id:
            items = [m for m in items if m["episode_id"] == episode_id]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.media_asset(m) for m in page], limit, offset, total)

    @app.route("/media-assets/<mid>", methods=["GET"])
    def get_media(mid):
        auth_and_role(["PlatformAdmin", "Publisher"])
        m = ownership.get_media_asset(mid)
        return success(serialize.media_asset(m), status=200)

    @app.route("/media-assets/<mid>/transcode-start", methods=["POST"])
    def transcode_start(mid):
        auth_and_role(["PlatformAdmin"])
        m = ownership.get_media_asset(mid)
        # State: UPLOADED -> TRANSCODING, or FAILED -> TRANSCODING (retry).
        if m["status"] == "UPLOADED":
            pass
        elif m["status"] == "FAILED":
            # Retry only while attempts below the max (PRD §3.2).
            if m["transcode_attempts"] >= db.MAX_TRANSCODE_ATTEMPTS:
                raise errors.err(errors.ERR_INVALID_STATE, "Maximum transcode attempts reached")
        else:
            raise errors.err(errors.ERR_INVALID_STATE, "Transcode cannot start from the current state")
        m["status"] = "TRANSCODING"
        m["transcode_attempts"] += 1
        touch(m)
        episode = db.db.episodes.get(m["episode_id"])
        if episode is not None:
            episode["media_status"] = "PROCESSING"
            touch(episode)
        return success(serialize.media_asset(m), status=200)

    @app.route("/media-assets/<mid>/transcode-result", methods=["POST"])
    def transcode_result(mid):
        auth_and_role(["PlatformAdmin"])
        m = ownership.get_media_asset(mid)
        # State: only from TRANSCODING.
        if m["status"] != "TRANSCODING":
            raise errors.err(errors.ERR_INVALID_STATE, "Transcode result requires a TRANSCODING asset")
        data = body()
        outcome = common.require_str(data, "outcome")
        if outcome not in ("SUCCESS", "FAILURE"):
            raise errors.err(errors.ERR_INVALID_REQUEST, "outcome must be SUCCESS or FAILURE")
        episode = db.db.episodes.get(m["episode_id"])
        if outcome == "SUCCESS":
            output_duration_ms = common.require_int(data, "output_duration_ms")
            if output_duration_ms <= 0:
                raise errors.err(errors.ERR_INVALID_REQUEST, "output_duration_ms must be > 0")
            m["status"] = "READY"
            m["output_duration_ms"] = output_duration_ms
            touch(m)
            if episode is not None:
                episode["media_status"] = "READY"
                episode["duration_ms"] = output_duration_ms
                touch(episode)
        else:
            m["status"] = "FAILED"
            touch(m)
            if episode is not None:
                # media_status -> FAILED only at the max attempt; else stays PROCESSING.
                if m["transcode_attempts"] >= db.MAX_TRANSCODE_ATTEMPTS:
                    episode["media_status"] = "FAILED"
                else:
                    episode["media_status"] = "PROCESSING"
                touch(episode)
        return success(serialize.media_asset(m), status=200)
