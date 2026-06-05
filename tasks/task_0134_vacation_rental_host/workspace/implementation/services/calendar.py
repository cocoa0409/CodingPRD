"""Calendar availability, calendar_version advancement, and channel propagation.

PRD §2.7: whenever an ACTIVE calendar block is created or released on a listing,
the listing's calendar_version advances by 1 and every ChannelConnection on that
listing whose status is CONNECTED or ERROR has pending_sync_count incremented by 1.
DISCONNECTED/SYNCING connections are not bumped. Each mutated record gets its
updated_at refreshed and version incremented.

PRD §3.3: availability test for a half-open [start, end) interval against existing
ACTIVE blocks, honoring the gap_nights turnaround buffer on both sides.
"""
from datetime import timedelta

from db import db
from models import make_entity, touch
from util import date_only


def active_blocks_for_listing(listing_id, exclude_id=None):
    out = []
    for blk in db.calendar_blocks.values():
        if blk["listing_id"] != listing_id:
            continue
        if blk["status"] != "ACTIVE":
            continue
        if exclude_id is not None and blk["id"] == exclude_id:
            continue
        out.append(blk)
    return out


def interval_available(listing, start_dt, end_dt):
    """Return True if [start, end) does not overlap any ACTIVE block and honors the
    gap_nights buffer on both sides (PRD §3.3, validation priority 11).

    Half-open intervals: a checkout day is free for the next arrival. The gap buffer
    requires at least gap_nights nights of clearance between this interval and the
    nearest ACTIVE block on either side.
    """
    gap = listing.get("gap_nights", 0)
    new_start = date_only(start_dt)
    new_end = date_only(end_dt)
    for blk in active_blocks_for_listing(listing["id"]):
        bs = date_only(blk["start_date"])
        be = date_only(blk["end_date"])
        # Direct half-open overlap: [new_start, new_end) intersects [bs, be)
        if new_start < be and bs < new_end:
            return False
        # Gap buffer: require >= gap nights of clearance between the two intervals.
        # If new interval is entirely after the block: clearance = new_start - be.
        # If new interval is entirely before the block: clearance = bs - new_end.
        if new_start >= be:
            clearance = (new_start - be).days
            if clearance < gap:
                return False
        elif new_end <= bs:
            clearance = (bs - new_end).days
            if clearance < gap:
                return False
    return True


def advance_calendar_and_propagate(listing):
    """Advance listing.calendar_version by 1 and bump CONNECTED/ERROR channels
    pending_sync_count by 1 each (PRD §2.7). Updates updated_at/version of the
    listing and each bumped channel."""
    listing["calendar_version"] = listing["calendar_version"] + 1
    touch(listing)
    for conn in db.channel_connections.values():
        if conn["listing_id"] != listing["id"]:
            continue
        if conn["status"] in ("CONNECTED", "ERROR"):
            conn["pending_sync_count"] = conn["pending_sync_count"] + 1
            touch(conn)


def create_active_block(listing, source, start_dt, end_dt):
    """Create an ACTIVE CalendarBlock and run the calendar/channel propagation.

    Returns the new block. Does NOT bump the listing's calendar_version itself —
    that and channel propagation are done by advance_calendar_and_propagate, which
    this calls. Caller is responsible for any additional listing.version bumps
    beyond the one advance_calendar_and_propagate applies.
    """
    block = make_entity({
        "listing_id": listing["id"],
        "source": source,
        "start_date": start_dt,
        "end_date": end_dt,
        "status": "ACTIVE",
    })
    db.calendar_blocks[block["id"]] = block
    advance_calendar_and_propagate(listing)
    return block


def release_block(block, listing):
    """Move an ACTIVE block to RELEASED and run propagation (PRD §3.3, §2.7)."""
    block["status"] = "RELEASED"
    touch(block)
    advance_calendar_and_propagate(listing)
