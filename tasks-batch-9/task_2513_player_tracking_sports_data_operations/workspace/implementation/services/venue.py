"""Venue posture derivation and the venue-degradation cascade (PRD §3.1, §3.2)."""

import db
from calc import venue_posture_from_counts
from db import store, touch
from util import sorted_rows


def recompute_venue_census(venue_id):
    """Re-derive the whole census and the posture from scratch (PRD §3.1).

    Returns the resulting ``data_posture``.  The venue row is only touched when
    a field actually moved, so a no-op re-derivation is not a mutation.
    """
    venue = store.venues.get(venue_id)
    if venue is None:
        return None

    installations = db.installations_of_venue(venue_id)
    certified = sum(1 for i in installations if i["status"] == "CERTIFIED")
    recalibrating = sum(1 for i in installations
                        if i["status"] in ("CALIBRATING", "RECALIBRATION_REQUIRED"))
    uncertified = sum(1 for i in installations
                      if i["status"] in ("DEPLOYED", "VALIDATED"))
    retired = sum(1 for i in installations if i["status"] == "RETIRED")
    active = certified + recalibrating + uncertified

    posture = venue_posture_from_counts(
        certified, recalibrating, venue["required_certified_installations"])

    updates = {
        "data_posture": posture,
        "active_installation_count": active,
        "certified_installation_count": certified,
        "recalibrating_installation_count": recalibrating,
        "uncertified_installation_count": uncertified,
        "retired_installation_count": retired,
    }
    changed = any(venue.get(k) != v for k, v in updates.items())
    venue.update(updates)
    if changed:
        touch(venue)
    return posture


def apply_installation_status_change(venue_id):
    """Re-derive the posture and fire the degradation cascade when it leaves
    CERTIFIED (PRD §3.2: flag-drift and retirement share this cascade)."""
    venue = store.venues.get(venue_id)
    posture_before = venue["data_posture"] if venue else None
    posture_after = recompute_venue_census(venue_id)
    if posture_before == "CERTIFIED" and posture_after != "CERTIFIED":
        venue_degradation_cascade(venue_id)
    return posture_after


def venue_degradation_cascade(venue_id):
    """Links 2 and 3 of the venue cascade (PRD §3.2).

    Every LIVE game at the venue moves to SUSPENDED_COLLECTION with a DEGRADED
    quality flag, and every ACTIVE feed session on those games moves to
    SUSPENDED with halt_reason VENUE_DEGRADED.  Quotas are deliberately left
    untouched: the session is paused, not settled.
    """
    suspended_sessions = 0
    for game in sorted_rows(db.games_of_venue(venue_id)):
        if game["collection_status"] != "LIVE":
            continue
        game["collection_status"] = "SUSPENDED_COLLECTION"
        game["data_quality_flag"] = "DEGRADED"
        touch(game)
        for session in sorted_rows(db.sessions_of_game(game["id"])):
            if session["status"] != "ACTIVE":
                continue
            session["status"] = "SUSPENDED"
            session["halt_reason"] = "VENUE_DEGRADED"
            touch(session)
            suspended_sessions += 1
    return suspended_sessions
