"""Ghost-strike recomputation for DirectoryListing (§3.5)."""

import db
import helpers

GHOST_STRIKE_THRESHOLD = 3


def recompute_ghost_strikes(listing):
    """Replay this listing's RECORDED probes chronologically (recorded_at ASC,
    tie-break created_at ASC); PASS resets the running count, FAIL increments.
    If the recomputed count >= threshold and the listing is LISTED, transition
    the listing to UNDER_REVIEW."""
    probes = [
        p for p in db.probes.values()
        if p["listing_id"] == listing["id"] and p["status"] == "RECORDED"
    ]
    probes.sort(key=lambda p: (p["recorded_at"] or "", p["created_at"]))
    running = 0
    for p in probes:
        if p["result"] == "PASS":
            running = 0
        elif p["result"] == "FAIL":
            running += 1
    listing["ghost_strike_count"] = running
    if running >= GHOST_STRIKE_THRESHOLD and listing["status"] == "LISTED":
        listing["status"] = "UNDER_REVIEW"
        helpers.touch(listing)
