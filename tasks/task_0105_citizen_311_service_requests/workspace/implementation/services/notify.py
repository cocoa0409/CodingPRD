"""StatusNotification synthesis (PRD §3.2 — append-only, immutable)."""
import db


def synthesize(request, from_status, to_status):
    """Create a StatusNotification for the request's citizen.

    channel is copied from the citizen's notify_channel at synthesis time.
    Append-only audit record (id + created_at only).
    """
    citizen = db.citizens.get(request["citizen_id"])
    channel = citizen["notify_channel"] if citizen else "EMAIL"
    rec = {
        "request_id": request["id"],
        "channel": channel,
        "from_status": from_status,
        "to_status": to_status,
        "message": "Request {} moved from {} to {}.".format(request["id"], from_status, to_status),
    }
    db.stamp_audit(rec)
    db.notifications[rec["id"]] = rec
    return rec
