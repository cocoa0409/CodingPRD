"""Synchronous, immediate cascades.  Every downstream consequence is applied
before the triggering write returns; each affected row's version and updated_at
move, and a credited parent's version increments once per cascade."""
from core import db, now, touch
from logic import (
    item_live_asset_count, post_session_cost_allocation, return_days_late,
    session_bookings, session_items, style_items, style_required_item_count,
    vendor_strike,
)


# --------------------------------------------------------------------------
# Style content-axis helpers (compound state; never set by an operator)
# --------------------------------------------------------------------------
def style_of_item(item):
    return db.styles.get(item["style_id"])


def all_required_captured(style_id):
    required = [i for i in style_items(style_id)
                if i["required"] and i["item_state"] != "WAIVED"]
    if not required:
        return False
    return all(i["item_state"] == "CAPTURED" for i in required)


def all_required_delivered(style_id):
    required = [i for i in style_items(style_id)
                if i["required"] and i["item_state"] != "WAIVED"]
    if not required:
        return False
    for item in required:
        delivered = [a for a in db.assets.values()
                     if a["shot_list_item_id"] == item["id"]
                     and a["asset_state"] == "DELIVERED"]
        if not delivered:
            return False
    return True


def matched_samples_in_building(style_id):
    return [s for s in db.samples.values()
            if s.get("matched_style_id") == style_id
            and s["match_state"] == "MATCHED"
            and s["custody_state"] in ("IN_STUDIO", "ON_SET")]


# --------------------------------------------------------------------------
# Sample -> LOST : depth-4 block cascade (PRD 3.3)
# --------------------------------------------------------------------------
def cascade_sample_lost(sample):
    # L1 -- the vendor pays for it.
    vendor = db.vendors.get(sample["vendor_id"])
    if vendor is not None:
        vendor_strike(vendor)
        touch(vendor)

    style_id = sample.get("matched_style_id")
    if not style_id:
        return
    style = db.styles.get(style_id)
    if style is None:
        return

    # L2 -- caused by L1's custody change.
    if matched_samples_in_building(style_id):
        return
    if style["content_state"] not in ("NOT_STARTED", "SAMPLE_READY", "SCHEDULED"):
        return
    style["content_state"] = "BLOCKED"
    touch(style)

    # L3 -- caused by L2's block.
    affected_sessions = []
    for item in style_items(style_id):
        if item["item_state"] in ("PLANNED", "ASSIGNED"):
            was_assigned_to = item["session_id"] if item["item_state"] == "ASSIGNED" else None
            item["item_state"] = "BLOCKED"
            touch(item)
            if was_assigned_to and was_assigned_to not in affected_sessions:
                affected_sessions.append(was_assigned_to)

    # L4 -- caused by L3: a session stripped of every required assigned or
    # captured item auto-unlocks.
    for session_id in affected_sessions:
        session = db.sessions.get(session_id)
        if session is None:
            continue
        remaining = [i for i in session_items(session_id)
                     if i["required"] and i["item_state"] in ("ASSIGNED", "CAPTURED")]
        if remaining:
            continue
        if session["session_state"] == "LOCKED":
            session["session_state"] = "BOOKED"
            touch(session)


# --------------------------------------------------------------------------
# ShootSession -> CANCELLED (PRD 3.4)
# --------------------------------------------------------------------------
def cascade_session_cancelled(session):
    session["session_state"] = "CANCELLED"
    touch(session)

    # L2 / L3 -- crew released, minute ledger reversed.
    for booking in session_bookings(session["id"]):
        if booking["booking_state"] not in ("HELD", "CONFIRMED"):
            continue
        booking["booking_state"] = "CANCELLED"
        touch(booking)
        talent = db.talents.get(booking["talent_id"])
        if talent is not None:
            touch(talent)

    # Assignments return to the backlog.
    for item in session_items(session["id"]):
        if item["item_state"] == "ASSIGNED":
            item["item_state"] = "PLANNED"
            item["session_id"] = None
            touch(item)


# --------------------------------------------------------------------------
# ShootSession -> WRAPPED (PRD 3.7)
# --------------------------------------------------------------------------
def cascade_session_wrapped(session):
    session["session_state"] = "WRAPPED"
    session["wrapped_at"] = now()
    session["actual_minutes"] = int(
        (session["wrapped_at"] - session["started_at"]).total_seconds() // 60
    ) if session["started_at"] else 0
    touch(session)

    for booking in session_bookings(session["id"]):
        if booking["booking_state"] == "CONFIRMED":
            booking["booking_state"] = "RELEASED"
            touch(booking)

    post_session_cost_allocation(session)


# --------------------------------------------------------------------------
# Asset ingest -> item capture -> style SHOT (PRD 3.6 / 3.7)
# --------------------------------------------------------------------------
def cascade_asset_ingested(item):
    live = item_live_asset_count(item["id"])
    became_captured = False
    if live == 1 and item["item_state"] == "ASSIGNED":
        item["item_state"] = "CAPTURED"
        became_captured = True
    touch(item)

    if not became_captured:
        return
    style = style_of_item(item)
    if style is None:
        return
    if style["content_state"] == "SCHEDULED" and all_required_captured(style["id"]):
        style["content_state"] = "SHOT"
        touch(style)


# --------------------------------------------------------------------------
# Asset -> REJECTED : capture revoked (PRD 3.8)
# --------------------------------------------------------------------------
def cascade_asset_rejected(item):
    live = item_live_asset_count(item["id"])
    reverted = False
    if live == 0 and item["item_state"] == "CAPTURED":
        item["item_state"] = "ASSIGNED"
        reverted = True
    touch(item)

    if not reverted:
        return
    style = style_of_item(item)
    if style is None:
        return
    if style["content_state"] == "SHOT":
        style["content_state"] = "SCHEDULED"
        touch(style)


# --------------------------------------------------------------------------
# Asset -> DELIVERED : depth-4 delivery cascade (PRD 3.9)
# --------------------------------------------------------------------------
def cascade_asset_delivered(asset, item, style):
    # L2 -- the style's delivered ledger moves (recount-backed) once.
    if style is None:
        return
    touch(style)

    # L3 -- caused by that delivery covering the last outstanding shot.
    if style["content_state"] == "IN_POST" and all_required_delivered(style["id"]):
        style["content_state"] = "DELIVERED"
        # L4 -- caused by the style reaching DELIVERED.
        for sample in db.samples.values():
            if sample.get("matched_style_id") != style["id"]:
                continue
            if sample["custody_state"] in ("IN_STUDIO", "ON_SET"):
                sample["custody_state"] = "RETURN_PENDING"
                touch(sample)
