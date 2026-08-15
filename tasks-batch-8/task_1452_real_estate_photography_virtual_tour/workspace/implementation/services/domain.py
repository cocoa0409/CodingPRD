"""Domain service: state transitions, cascades, and clock-driven sweeps."""

from datetime import timedelta

from db import store
from timeutil import new_id, iso_now_ms, now_dt, day_key
from services.calculations import (
    DRONE_KINDS,
    compute_scheduled_end,
    recompute_committed_minutes,
)


PRE_SHOOT_STATES = {"DRAFT", "AWAITING_READINESS", "READY", "ASSIGNED", "AUTHORIZATION_PENDING", "CONFIRMED"}
CANCELLABLE_STATES = {"DRAFT", "AWAITING_READINESS", "READY", "ASSIGNED", "AUTHORIZATION_PENDING", "CONFIRMED"}
RESCHEDULABLE_STATES = {"ASSIGNED", "AUTHORIZATION_PENDING", "CONFIRMED"}
OPEN_COMMITTED_STATES = {"ASSIGNED", "AUTHORIZATION_PENDING", "CONFIRMED"}
SHOOT_OR_LATER_STATES = {"SHOT", "IN_EDIT", "DELIVERED", "REVISION_REQUESTED", "ACCEPTED",
                         "CANCELLED_BY_CLIENT", "CANCELLED_WEATHER", "EXPIRED"}

DEFAULT_CHECKLIST_KEYS = ["DECLUTTER_MAIN", "UTILITIES_ON", "PETS_SECURED", "ACCESS_CODES", "EXTERIOR_CLEAR"]


def touch(entity):
    entity["updated_at"] = iso_now_ms()
    entity["version"] = entity.get("version", 0) + 1


def get_booking(booking_id):
    return store.bookings.get(booking_id)


def active_drone_addons(booking):
    return [a for a in store.addons.values()
            if a["booking_id"] == booking["id"] and a["state"] == "ACTIVE" and a["kind"] in DRONE_KINDS]


def has_active_drone(booking):
    return len(active_drone_addons(booking)) > 0


def pending_or_rejected_auths(booking_id):
    return [a for a in store.airspace_authorizations.values()
            if a["booking_id"] == booking_id and a["state"] in ("PENDING", "REJECTED")]


def pending_auths(booking_id):
    return [a for a in store.airspace_authorizations.values()
            if a["booking_id"] == booking_id and a["state"] == "PENDING"]


def approved_auths(booking_id):
    return [a for a in store.airspace_authorizations.values()
            if a["booking_id"] == booking_id and a["state"] == "APPROVED"]


def create_authorization(booking, addon, attempt_number):
    now = now_dt()
    auth = {
        "id": new_id(),
        "booking_id": booking["id"],
        "addon_id": addon["id"],
        "window_start_utc": booking["scheduled_start_utc"],
        "window_end_utc": booking["scheduled_end_utc"],
        "state": "PENDING",
        "attempt_number": attempt_number,
        "decided_at_utc": None,
        "created_at": iso_now_ms(),
        "updated_at": iso_now_ms(),
        "version": 1,
    }
    store.airspace_authorizations[auth["id"]] = auth
    return auth


def maybe_advance_to_confirmed(booking):
    """AUTHORIZATION_PENDING (or ASSIGNED with a drone history whose auth
    resolved) -> CONFIRMED when no unresolved drone auth remains.

    PRD §3.5: "when every authorization on the booking is `APPROVED` and none
    remains `PENDING` or unresolved-`REJECTED`, the booking advances
    automatically to `CONFIRMED`". Also covers the §3.5 cap-exhaustion path:
    "if the rejected authorization had already reached `attempt_number` 3,
    the covered drone add-on moves to `REFUSED`, and if no drone add-on
    remains `ACTIVE` on the booking, the booking returns to `CONFIRMED`
    without it." """
    if booking["state"] not in ("AUTHORIZATION_PENDING", "ASSIGNED"):
        return
    # Only drone-history bookings participate; a plain ASSIGNED booking with
    # no authorizations at all must not be auto-advanced by this helper.
    has_any_auth = any(a["booking_id"] == booking["id"]
                       for a in store.airspace_authorizations.values())
    if not has_any_auth:
        return
    # Any PENDING or REJECTED-unresolved auth keeps it waiting
    unresolved = [a for a in store.airspace_authorizations.values()
                  if a["booking_id"] == booking["id"] and a["state"] in ("PENDING", "REJECTED")]
    # But: REJECTED auths whose addon got REFUSED are no longer "unresolved" — the addon is dead.
    active_drone_ids = {a["id"] for a in active_drone_addons(booking)}
    truly_unresolved = [a for a in unresolved if a["addon_id"] in active_drone_ids]
    if not truly_unresolved:
        booking["state"] = "CONFIRMED"
        touch(booking)


def cascade_cancel_booking(booking):
    """Release cascade shared by cancel and weather-cancellation."""
    # Non-terminal addons -> CANCELLED
    for a in store.addons.values():
        if a["booking_id"] == booking["id"] and a["state"] in ("PENDING", "ACTIVE"):
            a["state"] = "CANCELLED"
            touch(a)
    # All non-terminal authorizations -> CANCELLED
    for auth in store.airspace_authorizations.values():
        if auth["booking_id"] == booking["id"] and auth["state"] in ("PENDING", "REJECTED", "APPROVED"):
            auth["state"] = "CANCELLED"
            touch(auth)
    # Release photographer minutes
    release_assignment(booking)


def release_assignment(booking):
    """Clear assigned photographer, recompute their committed minutes, bump photographer."""
    pid = booking.get("assigned_photographer_id")
    if not pid:
        return
    booking["assigned_photographer_id"] = None
    p = store.photographers.get(pid)
    if p:
        recompute_committed_minutes(p)
        touch(p)


def refresh_readiness(booking, item_was_unchecked=False):
    """Re-evaluate readiness aggregate after a checklist patch.

    - complete + state==AWAITING_READINESS -> READY (auto-advance)
    - a required item flipped checked->unchecked while AWAITING_READINESS or READY -> DRAFT
      (regression; quote stays locked)

    The regression only fires on an actual true->false flip of a required item, not on
    every patch that happens to leave the aggregate incomplete.
    """
    items = [it for it in store.checklist_items.values() if it["booking_id"] == booking["id"]]
    required = [it for it in items if it["required"]]
    complete = all(it["checked"] for it in required) if required else False
    if complete and booking["state"] == "AWAITING_READINESS":
        booking["state"] = "READY"
        touch(booking)
    elif item_was_unchecked and booking["state"] in ("AWAITING_READINESS", "READY"):
        booking["state"] = "DRAFT"
        touch(booking)


def sweep_clock():
    """Apply clock-driven transitions. Called after every clock set and on reads.

    - DRAFT/AWAITING_READINESS/READY bookings with now >= scheduled_start_utc -> EXPIRED
    - APPROVED authorizations with now >= window_end_utc and booking not yet SHOT -> EXPIRED
    - OPEN revisions whose revision_window_closes_utc <= now -> REJECTED_LATE
    """
    now = now_dt()
    for b in store.bookings.values():
        if b["state"] in ("DRAFT", "AWAITING_READINESS", "READY") and b["scheduled_start_utc"] <= now:
            b["state"] = "EXPIRED"
            touch(b)
    for auth in store.airspace_authorizations.values():
        if auth["state"] == "APPROVED" and auth["window_end_utc"] is not None and auth["window_end_utc"] <= now:
            b = store.bookings.get(auth["booking_id"])
            if b and b["state"] in OPEN_COMMITTED_STATES:
                auth["state"] = "EXPIRED"
                touch(auth)
    for r in store.revisions.values():
        if r["state"] == "OPEN":
            b = store.bookings.get(r["booking_id"])
            if b and b.get("revision_window_closes_utc") and b["revision_window_closes_utc"] <= now:
                r["state"] = "REJECTED_LATE"
                touch(r)


def spawn_default_checklist(booking):
    for key in DEFAULT_CHECKLIST_KEYS:
        item = {
            "id": new_id(),
            "booking_id": booking["id"],
            "item_key": key,
            "required": True,
            "checked": False,
            "checked_at_utc": None,
            "created_at": iso_now_ms(),
            "updated_at": iso_now_ms(),
            "version": 1,
        }
        store.checklist_items[item["id"]] = item


def recompute_booking_window(booking):
    booking["scheduled_end_utc"] = compute_scheduled_end(booking)
