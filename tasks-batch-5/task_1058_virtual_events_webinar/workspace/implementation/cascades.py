"""Multi-link cascades that run to completion inside the triggering request."""

import calc
import db
from db import S


def _event_of(row):
    return S.events.get(row.get("event_id"))


# ------------------------------------------------------------ seat inventory


def release_seat(registration):
    """Give a held seat back: sold_count -1, registered_count -1, availability."""
    ticket_type = S.ticket_types.get(registration.get("ticket_type_id"))
    event = S.events.get(registration.get("event_id"))
    if ticket_type is not None:
        ticket_type["sold_count"] = max(0, int(ticket_type.get("sold_count", 0)) - 1)
        calc.recompute_availability(ticket_type)
        db.touch(ticket_type)
    if event is not None:
        event["registered_count"] = max(0, int(event.get("registered_count", 0)) - 1)
    return ticket_type


def take_seat(registration):
    ticket_type = S.ticket_types.get(registration.get("ticket_type_id"))
    event = S.events.get(registration.get("event_id"))
    if ticket_type is not None:
        ticket_type["sold_count"] = int(ticket_type.get("sold_count", 0)) + 1
        calc.recompute_availability(ticket_type)
        db.touch(ticket_type)
    if event is not None:
        event["registered_count"] = int(event.get("registered_count", 0)) + 1
    return ticket_type


def promote_waitlist(ticket_type, event):
    """CASCADE-B link 3: promote the earliest-created WAITLISTED registration."""
    if ticket_type is None or ticket_type.get("availability_status") != "AVAILABLE":
        return None
    candidates = [
        r for r in S.registrations.values()
        if r.get("ticket_type_id") == ticket_type["id"]
        and r.get("attendance_status") == "WAITLISTED"
    ]
    if not candidates:
        return None
    promoted = db.sort_rows(candidates)[0]
    promoted["attendance_status"] = "REGISTERED"
    promoted["amount_due_cents"] = calc.price_provisional(promoted, ticket_type, event)
    take_seat(promoted)
    db.touch(promoted)
    return promoted


def cancel_pending_match_requests(registration):
    for mr in S.match_requests.values():
        if mr.get("state") != "PENDING":
            continue
        if registration["id"] in (
            mr.get("requester_registration_id"),
            mr.get("target_registration_id"),
        ):
            mr["state"] = "CANCELLED"
            db.touch(mr)


# ------------------------------------------------------------- media chain


def retract_recordings_of_broadcast(broadcast, event):
    """Every recording of an aborted broadcast is retracted."""
    for rec in db.sort_rows(list(S.recordings.values())):
        if rec.get("broadcast_id") != broadcast["id"]:
            continue
        if rec.get("state") not in ("PENDING", "PROCESSING", "READY", "PUBLISHED"):
            continue
        was_published = rec.get("state") == "PUBLISHED"
        rec["state"] = "RETRACTED"
        db.touch(rec)
        if was_published and event is not None:
            event["published_recording_count"] = max(
                0, int(event.get("published_recording_count", 0)) - 1
            )


def abort_broadcast(broadcast, event):
    broadcast["state"] = "ABORTED"
    db.touch(broadcast)
    retract_recordings_of_broadcast(broadcast, event)


def release_session_speakers(session):
    """Every INVITED or ACCEPTED junction row of a cancelled session is RELEASED."""
    for ss in db.sort_rows(list(S.session_speakers.values())):
        if ss.get("session_id") != session["id"]:
            continue
        state = ss.get("state")
        if state not in ("INVITED", "ACCEPTED"):
            continue
        ss["state"] = "RELEASED"
        db.touch(ss)
        if state == "ACCEPTED":
            speaker = S.speakers.get(ss.get("speaker_id"))
            if speaker is not None:
                speaker["accepted_session_count"] = max(
                    0, int(speaker.get("accepted_session_count", 0)) - 1
                )
                recompute_engagement(speaker)
                db.touch(speaker)
            session["accepted_speaker_count"] = max(
                0, int(session.get("accepted_speaker_count", 0)) - 1
            )


def recompute_engagement(speaker):
    speaker["engagement_status"] = (
        "ENGAGED" if int(speaker.get("accepted_session_count", 0)) >= 1 else "UNASSIGNED"
    )
    return speaker["engagement_status"]


def cancel_session(session, event):
    """Session cancellation: track slot release, speaker release, broadcast abort."""
    prior = session.get("state")
    session["state"] = "CANCELLED"
    if prior in ("SCHEDULED", "LIVE"):
        track = S.tracks.get(session.get("track_id"))
        if track is not None:
            track["scheduled_session_count"] = max(
                0, int(track.get("scheduled_session_count", 0)) - 1
            )
            db.touch(track)
    release_session_speakers(session)
    for bc in db.sort_rows(list(S.broadcasts.values())):
        if bc.get("session_id") != session["id"]:
            continue
        if bc.get("state") in ("SCHEDULED", "PREVIEW", "LIVE"):
            abort_broadcast(bc, event)
    db.touch(session)


def cancel_event_cascade(event):
    """CASCADE-A: sessions -> broadcasts -> recordings."""
    for session in db.sort_rows(list(S.sessions.values())):
        if session.get("event_id") != event["id"]:
            continue
        if session.get("state") in ("DRAFT", "SCHEDULED", "LIVE"):
            cancel_session(session, event)
