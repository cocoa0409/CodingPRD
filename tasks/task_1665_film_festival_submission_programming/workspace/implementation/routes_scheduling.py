"""Routes: venues and screening slots (the screening grid)."""

from datetime import timedelta

from flask import Blueprint, request

import domain as D
from errors import (err409, err_invalid_state, err_not_found, err_phase,
                    err_referential, err_stale_version)
from store import DB
from util import (auth, created_key, get_body, get_or_404, ok, paginate,
                  require_role, v_arr, v_dt, v_enum, v_int, v_str)

bp = Blueprint("scheduling", __name__)

VENUE_READ = ["FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "PROGRAM_CHAIR",
              "SCHEDULING_OPS"]
SLOT_READ = ["FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "PROGRAM_CHAIR",
             "SCHEDULING_OPS", "FILMMAKER"]
OPS = ["SCHEDULING_OPS"]

POST_LIVE_PHASES = ("FESTIVAL_LIVE", "AWARDS_NIGHT", "CLOSED")


# -------------------------------------------------------------------- venues
@bp.post("/festival/venues")
def create_venue():
    body = get_body()
    edition_id = v_str(body, "edition_id")
    name = v_str(body, "name")
    seat_capacity = v_int(body, "seat_capacity")
    formats_supported = v_arr(body, "formats_supported", item_enum=D.FORMATS)
    turnover = v_int(body, "turnover_minutes", required=False)
    if turnover is None:
        turnover = 30
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN"])
    edition = DB.editions.get(edition_id)
    if edition is None:
        raise err_referential("Edition not found")
    if edition["status"] in POST_LIVE_PHASES:
        raise err_phase("Venue creation is forbidden once the festival is live")
    rec = D.new_rec({
        "edition_id": edition_id, "name": name, "seat_capacity": seat_capacity,
        "formats_supported": list(formats_supported),
        "turnover_minutes": turnover,
    })
    DB.venues[rec["id"]] = rec
    return ok(D.ser_venue(rec), 201)


@bp.get("/festival/venues/<vid>")
def get_venue(vid):
    uid, role = auth()
    require_role(role, VENUE_READ)
    rec = get_or_404(DB.venues, vid)
    return ok(D.ser_venue(rec))


@bp.get("/festival/venues")
def list_venues():
    uid, role = auth()
    require_role(role, VENUE_READ)
    items = list(DB.venues.values())
    edition_id = request.args.get("edition_id")
    if edition_id is not None:
        items = [v for v in items if v["edition_id"] == edition_id]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_venue(v) for v in page], pagination=meta)


# -------------------------------------------------------------- slot helpers
def _slot_conflicts(venue, start_at, end_at):
    """Turnover-buffered half-open interval arithmetic (§3.8): a candidate
    [s,e) conflicts with an existing occupied [s2,e2) unless the candidate's
    end plus the buffer is at or before the existing start, or the existing
    end plus the buffer is at or before the candidate's start. Exactly the
    buffer between them does not conflict. CANCELLED slots drop out."""
    buf = timedelta(minutes=venue["turnover_minutes"])
    for slot in DB.slots.values():
        if slot["venue_id"] != venue["id"]:
            continue
        if slot["status"] not in ("OPEN", "HELD", "CONFIRMED", "PLAYED"):
            continue
        s2, e2 = slot["start_at"], slot["end_at"]
        if end_at + buf <= s2 or e2 + buf <= start_at:
            continue
        return True
    return False


def _entry_slots(entry_id):
    return [s for s in DB.slots.values() if s["slate_entry_id"] == entry_id]


# --------------------------------------------------------------------- slots
@bp.post("/festival/screening-slots")
def create_slot():
    body = get_body()
    venue_id = v_str(body, "venue_id")
    slot_type = v_enum(body, "slot_type", D.SLOT_TYPES)
    start_at = v_dt(body, "start_at")
    end_at = v_dt(body, "end_at")
    if end_at <= start_at:
        from errors import err_validation
        raise err_validation("end_at must be later than start_at")
    expected_venue_version = v_int(body, "expected_venue_version")
    uid, role = auth()
    require_role(role, OPS)
    venue = DB.venues.get(venue_id)
    if venue is None:
        raise err_referential("Venue not found")
    edition = DB.editions.get(venue["edition_id"])
    if edition is not None and (
            start_at < edition["festival_start_at"]
            or end_at > edition["festival_end_at"]):
        raise err409("ERR_SLOT_OUTSIDE_FESTIVAL_WINDOW",
                     "Slot must sit inside the festival window")
    if _slot_conflicts(venue, start_at, end_at):
        raise err409("ERR_VENUE_OVERLAP",
                     "Slot conflicts with an occupied slot on this venue")
    if expected_venue_version != venue["version"]:
        raise err_stale_version()
    rec = D.new_rec({
        "venue_id": venue_id, "slate_entry_id": None, "slot_type": slot_type,
        "start_at": start_at, "end_at": end_at, "status": "OPEN",
    })
    DB.slots[rec["id"]] = rec
    D.touch(venue)
    return ok(D.ser_slot(rec), 201)


@bp.get("/festival/screening-slots/<sid>")
def get_slot(sid):
    uid, role = auth()
    require_role(role, SLOT_READ)
    rec = get_or_404(DB.slots, sid)
    return ok(D.ser_slot(rec))


@bp.get("/festival/screening-slots")
def list_slots():
    uid, role = auth()
    require_role(role, SLOT_READ)
    items = list(DB.slots.values())
    venue_id = request.args.get("venue_id")
    slate_entry_id = request.args.get("slate_entry_id")
    slot_type = request.args.get("slot_type")
    status = request.args.get("status")
    if venue_id is not None:
        items = [s for s in items if s["venue_id"] == venue_id]
    if slate_entry_id is not None:
        items = [s for s in items if s["slate_entry_id"] == slate_entry_id]
    if slot_type is not None:
        items = [s for s in items if s["slot_type"] == slot_type]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_slot(s) for s in page], pagination=meta)


@bp.post("/festival/screening-slots/<sid>/hold")
def hold_slot(sid):
    body = get_body()
    slate_entry_id = v_str(body, "slate_entry_id")
    uid, role = auth()
    require_role(role, OPS)
    slot = get_or_404(DB.slots, sid)
    if slot["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN slot may be held")
    entry = DB.entries.get(slate_entry_id)
    # The entry must be confirmed into the program: CONFIRMED, or PROGRAMMED
    # (the CONFIRMED<->PROGRAMMED pair is a slot-occupancy cycle, so a film
    # holding one confirmed slot is PROGRAMMED yet must still accept further
    # holds up to its licensed screening count).
    if entry is not None and entry["status"] not in ("CONFIRMED", "PROGRAMMED"):
        raise err409("ERR_ENTRY_NOT_CONFIRMED",
                     "The slate entry is not CONFIRMED")
    sub = DB.submissions.get(entry["submission_id"]) if entry else None
    agreement = (D.agreement_for_submission(entry["submission_id"])
                 if entry else None)
    if entry is not None and entry["status"] in ("CONFIRMED", "PROGRAMMED"):
        if agreement is None or agreement["status"] not in ("SIGNED", "ACTIVE"):
            raise err409("ERR_AGREEMENT_NOT_SIGNED",
                         "The exhibition agreement is not SIGNED or ACTIVE")
    venue = DB.venues.get(slot["venue_id"])
    edition = DB.editions.get(venue["edition_id"]) if venue else None
    if edition is None or edition["status"] != "SCHEDULING":
        raise err_phase("Slot holds are allowed only during SCHEDULING")
    if entry is None:
        raise err_referential("Slate entry not found")
    # Premiere-before-public ordering (temporal window rule).
    if slot["slot_type"] in ("PUBLIC", "PRESS_INDUSTRY"):
        has_earlier_premiere = any(
            s["slot_type"] == "PREMIERE"
            and s["status"] in ("HELD", "CONFIRMED", "PLAYED")
            and s["start_at"] < slot["start_at"]
            for s in _entry_slots(entry["id"]))
        if not has_earlier_premiere:
            raise err409("ERR_PREMIERE_WINDOW_VIOLATION",
                         "No earlier PREMIERE slot exists for this entry")
    if sub is not None and sub["edition_id"] != edition["id"]:
        raise err_referential("Entry belongs to another edition")
    if slot["slot_type"] == "PREMIERE":
        if any(s["slot_type"] == "PREMIERE"
               and s["status"] in ("HELD", "CONFIRMED", "PLAYED")
               for s in _entry_slots(entry["id"])):
            raise err409("ERR_PREMIERE_SLOT_EXISTS",
                         "This entry already has a PREMIERE slot")
    if sub is not None:
        duration = slot["end_at"] - slot["start_at"]
        needed = timedelta(minutes=sub["runtime_minutes"] + D.QA_MINUTES)
        if duration < needed:
            raise err409("ERR_SLOT_TOO_SHORT",
                         "Slot is shorter than runtime plus 15 minutes QA")
        if sub["format"] not in venue["formats_supported"]:
            raise err409("ERR_FORMAT_UNSUPPORTED",
                         "The venue does not support this exhibition format")
    slot["status"] = "HELD"
    slot["slate_entry_id"] = entry["id"]
    entry["_ever_held"] = True
    D.touch(slot)
    return ok(D.ser_slot(slot))


@bp.post("/festival/screening-slots/<sid>/confirm")
def confirm_slot(sid):
    get_body()
    uid, role = auth()
    require_role(role, OPS)
    slot = get_or_404(DB.slots, sid)
    if slot["status"] != "HELD":
        raise err_invalid_state("Only a HELD slot may be confirmed")
    entry = DB.entries.get(slot["slate_entry_id"])
    agreement = (D.agreement_for_submission(entry["submission_id"])
                 if entry else None)
    if agreement is not None and (
            agreement["used_screening_count"] + 1
            > agreement["licensed_screening_count"]):
        raise err409("ERR_LICENSED_COUNT_EXCEEDED",
                     "The licensed screening count would be exceeded")
    slot["status"] = "CONFIRMED"
    D.touch(slot)
    if agreement is not None:
        agreement["used_screening_count"] += 1
        if agreement["status"] == "SIGNED":
            agreement["status"] = "ACTIVE"
        D.touch(agreement)
    if entry is not None:
        occupied = [s for s in _entry_slots(entry["id"])
                    if s["status"] in ("CONFIRMED", "PLAYED")]
        if len(occupied) >= 1 and entry["status"] == "CONFIRMED":
            entry["status"] = "PROGRAMMED"
            D.touch(entry)
            sub = DB.submissions.get(entry["submission_id"])
            if sub is not None and sub["status"] == "CONFIRMED":
                sub["status"] = "PROGRAMMED"
                D.touch(sub)
    return ok(D.ser_slot(slot))


@bp.post("/festival/screening-slots/<sid>/release")
def release_slot(sid):
    get_body()
    uid, role = auth()
    require_role(role, OPS)
    slot = get_or_404(DB.slots, sid)
    if slot["status"] != "HELD":
        raise err_invalid_state("Only a HELD slot may be released")
    slot["status"] = "OPEN"
    slot["slate_entry_id"] = None
    D.touch(slot)
    return ok(D.ser_slot(slot))


@bp.post("/festival/screening-slots/<sid>/cancel")
def cancel_slot(sid):
    get_body()
    uid, role = auth()
    require_role(role, OPS)
    slot = get_or_404(DB.slots, sid)
    if slot["status"] != "CONFIRMED":
        raise err_invalid_state("Only a CONFIRMED slot may be cancelled")
    slot["status"] = "CANCELLED"
    D.touch(slot)
    entry = DB.entries.get(slot["slate_entry_id"])
    agreement = (D.agreement_for_submission(entry["submission_id"])
                 if entry else None)
    if agreement is not None:
        agreement["used_screening_count"] -= 1
        D.touch(agreement)
    if entry is not None:
        remaining = [s for s in _entry_slots(entry["id"])
                     if s["status"] in ("CONFIRMED", "PLAYED")]
        if not remaining and entry["status"] == "PROGRAMMED":
            entry["status"] = "CONFIRMED"
            D.touch(entry)
            sub = DB.submissions.get(entry["submission_id"])
            if sub is not None and sub["status"] == "PROGRAMMED":
                sub["status"] = "CONFIRMED"
                D.touch(sub)
    return ok(D.ser_slot(slot))


@bp.post("/festival/screening-slots/<sid>/mark-played")
def mark_played(sid):
    get_body()
    uid, role = auth()
    require_role(role, OPS)
    slot = get_or_404(DB.slots, sid)
    if slot["status"] != "CONFIRMED":
        raise err_invalid_state("Only a CONFIRMED slot may be marked played")
    venue = DB.venues.get(slot["venue_id"])
    edition = DB.editions.get(venue["edition_id"]) if venue else None
    if edition is None or edition["status"] != "FESTIVAL_LIVE":
        raise err_phase("Slots may be marked played only during FESTIVAL_LIVE")
    slot["status"] = "PLAYED"
    D.touch(slot)
    return ok(D.ser_slot(slot))
