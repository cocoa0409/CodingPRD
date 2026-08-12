"""POST /api/_clock/set_current_utc — advance the logical clock and run sweeps."""

from datetime import datetime, timezone, date, timedelta

from flask import Blueprint, request

import db
from db import (
    title_search_store, lien_release_store, lien_store, trust_agreement_store,
    escrow_file_store, touch, get_logical_now, set_logical_now, format_ts,
)
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.escrow import recompute_posture, try_bubble_cleared, try_bubble_funded

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_roles(["EscrowManager"])

    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601 or not isinstance(to_iso8601, str):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required.", 400)

    # Parse the ISO 8601 datetime
    try:
        # Handle Z suffix
        clean = to_iso8601.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 datetime.", 400)

    set_logical_now(dt)
    new_date = dt.date()

    # Collect affected escrow file IDs for posture recompute
    affected_files = set()

    # Sweep 1: TitleSearch COMPLETED -> STALE when the effective_at instant lies
    # strictly more than 30 days in the past (instant-granularity per PRD §2.4).
    for ts in title_search_store.values():
        if ts["status"] == "COMPLETED" and ts.get("effective_at"):
            eff = datetime.fromisoformat(ts["effective_at"].replace("Z", "+00:00"))
            threshold = eff + timedelta(days=30)
            if dt > threshold:
                ts["status"] = "STALE"
                touch(ts)
                affected_files.add(ts["escrow_file_id"])

    # Sweep 2: LienRelease QUOTED -> QUOTE_EXPIRED when date > good_through_date
    for lr in lien_release_store.values():
        if lr["status"] == "QUOTED" and lr.get("good_through_date"):
            gtd = date.fromisoformat(lr["good_through_date"])
            if new_date > gtd:
                lr["status"] = "QUOTE_EXPIRED"
                touch(lr)
                # Check if lien should return to DISCOVERED
                lien = lien_store.get(lr["lien_id"])
                if lien:
                    affected_files.add(lien["escrow_file_id"])
                    _check_lien_orphaned(lien)

    # Sweep 3: TrustAgreement ACCEPTED -> EXPIRED when date > expiry_date
    for ta in trust_agreement_store.values():
        if ta["status"] == "ACCEPTED" and ta.get("expiry_date"):
            exp = date.fromisoformat(ta["expiry_date"])
            if new_date > exp:
                ta["status"] = "EXPIRED"
                touch(ta)
                # Find all escrow files for this aircraft with requires_trust
                for ef in escrow_file_store.values():
                    if ef["aircraft_id"] == ta["aircraft_id"] and ef.get("requires_trust"):
                        affected_files.add(ef["id"])

    # Recompute posture on all affected files
    for file_id in affected_files:
        ef = escrow_file_store.get(file_id)
        if ef:
            recompute_posture(ef)
            touch(ef)
            try_bubble_cleared(ef)
            try_bubble_funded(ef)

    return success_object({"current_utc": format_ts(dt)})


def _check_lien_orphaned(lien: dict):
    """If RELEASE_PENDING lien has no active release, return to DISCOVERED."""
    if lien["status"] != "RELEASE_PENDING":
        return
    has_active = any(
        r["lien_id"] == lien["id"]
        and r["status"] in ("REQUESTED", "QUOTED", "RELEASE_RECEIVED", "FILED")
        for r in lien_release_store.values()
    )
    if not has_active:
        lien["status"] = "DISCOVERED"
        touch(lien)
