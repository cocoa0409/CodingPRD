import db
from services.overlap import parse_dt, has_overlap
from services.audit import create_audit_log
from services.cost import compute_cost_cents


def promote_waitlist(room_id, freed_start, freed_end, actor_id, actor_role):
    """Try to promote one waitlist entry after a slot is freed.

    Finds WAITING entries for the same room whose time window is fully contained
    in the freed slot. Sorted by position ascending (FIFO). Promotes the first
    eligible entry.
    """
    room = db.rooms.get(room_id)
    if not room or room["status"] != "ACTIVE":
        return

    freed_st = parse_dt(freed_start)
    freed_et = parse_dt(freed_end)

    candidates = []
    for w in db.waitlist.values():
        if w["room_id"] != room_id:
            continue
        if w["status"] != "WAITING":
            continue
        w_st = parse_dt(w["start_time"])
        w_et = parse_dt(w["end_time"])
        # Must be fully contained in freed slot
        if w_st >= freed_st and w_et <= freed_et:
            candidates.append(w)

    candidates.sort(key=lambda x: x["position"])

    for candidate in candidates:
        if candidate["attendee_count"] > room["capacity"]:
            continue
        # Check overlap with remaining CONFIRMED/CHECKED_IN bookings
        if has_overlap(room_id, candidate["start_time"], candidate["end_time"]):
            continue

        # Promote this entry
        old_status = candidate["status"]
        candidate["status"] = "PROMOTED"
        candidate["updated_at"] = db.now_iso()
        candidate["version"] += 1

        create_audit_log(
            actor_id="system",
            actor_role="system",
            action="waitlist.promoted",
            resource_type="Waitlist",
            resource_id=candidate["id"],
            details={"before": {"status": old_status}, "after": {"status": "PROMOTED"}},
        )

        # Create a new TENTATIVE booking from waitlist entry
        booking_id = db.gen_id()
        now = db.now_iso()
        booking = {
            "id": booking_id,
            "room_id": room_id,
            "organizer_id": candidate["requester_id"],
            "title": candidate["title"],
            "start_time": candidate["start_time"],
            "end_time": candidate["end_time"],
            "attendee_count": candidate["attendee_count"],
            "status": "TENTATIVE",
            "series_id": None,
            "cost_cents": None,
            "rejection_reason": None,
            "checked_in_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.bookings[booking_id] = booking

        create_audit_log(
            actor_id="system",
            actor_role="system",
            action="booking.created",
            resource_type="Booking",
            resource_id=booking_id,
            details={"after": dict(booking)},
        )

        # Auto-confirm for STANDARD, PENDING_APPROVAL for PREMIUM
        if room["tier"] == "STANDARD":
            if not has_overlap(room_id, booking["start_time"], booking["end_time"], exclude_booking_id=booking_id):
                st = parse_dt(booking["start_time"])
                et = parse_dt(booking["end_time"])
                cost = compute_cost_cents(room, st, et)
                booking["status"] = "CONFIRMED"
                booking["cost_cents"] = cost
                booking["updated_at"] = db.now_iso()
                booking["version"] += 1
                create_audit_log(
                    actor_id="system",
                    actor_role="system",
                    action="booking.confirmed",
                    resource_type="Booking",
                    resource_id=booking_id,
                    details={"before": {"status": "TENTATIVE"}, "after": {"status": "CONFIRMED", "cost_cents": cost}},
                )
        else:
            booking["status"] = "PENDING_APPROVAL"
            booking["updated_at"] = db.now_iso()
            booking["version"] += 1
            create_audit_log(
                actor_id="system",
                actor_role="system",
                action="booking.pending_approval",
                resource_type="Booking",
                resource_id=booking_id,
                details={"before": {"status": "TENTATIVE"}, "after": {"status": "PENDING_APPROVAL"}},
            )

        # Re-position remaining waitlist entries for same room
        _reposition_waitlist(room_id)
        return  # Only one promotion per event

    return


def _reposition_waitlist(room_id):
    """Re-assign position numbers for all WAITING entries on a room,
    preserving their original order."""
    waiting = [w for w in db.waitlist.values()
               if w["room_id"] == room_id and w["status"] == "WAITING"]
    waiting.sort(key=lambda x: x["position"])
    for i, w in enumerate(waiting, 1):
        if w["position"] != i:
            w["position"] = i
            w["updated_at"] = db.now_iso()
            w["version"] += 1


def reposition_waitlist(room_id):
    _reposition_waitlist(room_id)
