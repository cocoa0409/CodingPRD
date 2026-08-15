"""Logical clock + expiry sweep endpoints (test-driving surface)."""

import db
from db import _parse_iso
from middleware import require_roles
from response import success
from routes import make_blueprint
from util import get_payload, require_field
from errors import raise_error, ERR_INVALID_REQUEST
from services.cascade import write_exposure
from util import touch

bp = make_blueprint("system_ops")


@bp.route("/playtests/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("ResearchOpsAdmin")
    body = get_payload()
    to_iso8601 = require_field(body, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a string")
    try:
        db.clock.set(to_iso8601)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    return success({"now_iso8601": db.clock.now_iso()}, status=200)


@bp.route("/playtests/_sweeps/run-expiry", methods=["POST"])
def run_expiry():
    require_roles("ResearchOpsAdmin")
    now = db.clock.now()
    signatures_expired = 0
    keys_expired = 0

    # PENDING signatures with expires_at <= now -> EXPIRED (boundary: equality expires)
    for sig in list(db.nda_signatures.values()):
        if sig["status"] == "PENDING" and _parse_iso(sig["expires_at"]) <= now:
            sig["status"] = "EXPIRED"
            touch(sig)
            signatures_expired += 1

    # ISSUED keys with expires_at <= now -> EXPIRED + journal record + decrement
    for key in list(db.access_keys.values()):
        if key["status"] == "ISSUED" and _parse_iso(key["expires_at"]) <= now:
            key["status"] = "EXPIRED"
            touch(key)
            build = db.builds.get(key["build_id"])
            if build is not None:
                build["keys_active_count"] = max(0, build.get("keys_active_count", 0) - 1)
                touch(build)
                study_id = build["study_id"]
            else:
                study_id = None
            write_exposure(key["participant_id"], key["build_id"], study_id, "KEY_EXPIRED")
            keys_expired += 1

    return success({"signatures_expired": signatures_expired, "keys_expired": keys_expired}, status=200)
