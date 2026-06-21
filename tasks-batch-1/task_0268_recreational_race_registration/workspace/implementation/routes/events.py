"""Event endpoints + lifecycle transitions and event-cancel cascade."""
from flask import Blueprint, request

from db import db, new_id
from errors import (err, ERR_INVALID_STATE, ERR_REGISTRATION_CLOSED)
from middleware import auth, require_role, get_json, parse_iso, now_dt
from response import object_response
from services.store import stamp_new, serialize_generic, touch
from services.calculations import registration_refund
from services.validate import require_str, lookup

bp = Blueprint("events", __name__)


@bp.route("/events", methods=["POST"])
def create_event():
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    body = get_json()
    name = require_str(body, "name")
    race_date = require_str(body, "race_date_utc")
    reg_opens = require_str(body, "registration_opens_utc")
    reg_closes = require_str(body, "registration_closes_utc")
    race_date_dt = parse_iso(race_date)
    reg_opens_dt = parse_iso(reg_opens)
    reg_closes_dt = parse_iso(reg_closes)

    eid = new_id()
    e = {
        "id": eid,
        "name": name,
        "race_date_utc": race_date,
        "registration_opens_utc": reg_opens,
        "registration_closes_utc": reg_closes,
        "status": "DRAFT",
        "_race_date_dt": race_date_dt,
        "_reg_opens_dt": reg_opens_dt,
        "_reg_closes_dt": reg_closes_dt,
    }
    stamp_new(e)
    db.events[eid] = e
    return object_response(serialize_generic(e), 201)


@bp.route("/events/<event_id>", methods=["GET"])
def get_event(event_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    e = lookup(db.events, event_id, "Event")
    return object_response(serialize_generic(e), 200)


@bp.route("/events/<event_id>/open", methods=["POST"])
def open_event(event_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    e = lookup(db.events, event_id, "Event")
    # state: must be DRAFT
    if e["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Event must be DRAFT to open")
    # precondition: >=1 distance with >=1 wave and >=1 pricing tier
    has_ready_distance = False
    for d in db.distances.values():
        if d["event_id"] != event_id:
            continue
        has_wave = any(w["distance_id"] == d["id"] for w in db.waves.values())
        has_tier = any(t["distance_id"] == d["id"] for t in db.pricing_tiers.values())
        if has_wave and has_tier:
            has_ready_distance = True
            break
    if not has_ready_distance:
        raise err(ERR_INVALID_STATE,
                  "Event needs at least one distance with a wave and a pricing tier")
    # temporal: now >= registration_opens_utc
    if now_dt() < e["_reg_opens_dt"]:
        raise err(ERR_REGISTRATION_CLOSED, "Cannot open before registration_opens_utc")
    e["status"] = "OPEN"
    touch(e)
    return object_response(serialize_generic(e), 200)


@bp.route("/events/<event_id>/close", methods=["POST"])
def close_event(event_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    e = lookup(db.events, event_id, "Event")
    if e["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Event must be OPEN to close")
    e["status"] = "CLOSED"
    touch(e)
    return object_response(serialize_generic(e), 200)


@bp.route("/events/<event_id>/post-results", methods=["POST"])
def post_results(event_id):
    user_id, role = auth()
    require_role(role, {"TimingOfficial"})
    e = lookup(db.events, event_id, "Event")
    if e["status"] != "CLOSED":
        raise err(ERR_INVALID_STATE, "Event must be CLOSED to post results")
    if now_dt() < e["_race_date_dt"]:
        raise err(ERR_REGISTRATION_CLOSED, "Cannot post results before race_date_utc")
    e["status"] = "RESULTS_POSTED"
    touch(e)
    return object_response(serialize_generic(e), 200)


@bp.route("/events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    e = lookup(db.events, event_id, "Event")
    if e["status"] == "RESULTS_POSTED" or e["status"] == "CANCELLED":
        raise err(ERR_INVALID_STATE, "Event cannot be cancelled from its current status")

    # gather distances of this event
    dist_ids = {d["id"] for d in db.distances.values() if d["event_id"] == event_id}

    # CASCADE: cancel every non-terminal registration on every distance.
    # Organizer-initiated => full refund of amount_paid (incl. processing fee).
    reg_terminal = {"CANCELLED", "TRANSFERRED", "DEFERRED", "FINISHED"}
    touched_distances = set()
    touched_waves = set()
    for r in db.registrations.values():
        if r["distance_id"] not in dist_ids:
            continue
        if r["status"] in reg_terminal:
            continue
        prev = r["status"]
        refund = registration_refund(prev, r["amount_paid_cents"], r["processing_fee_cents"], True)
        r["refund_cents"] = refund
        # if it had a bib, delete it and free the wave slot
        if prev == "BIB_ASSIGNED":
            for bid, b in list(db.bib_assignments.items()):
                if b["registration_id"] == r["id"]:
                    wave = db.waves.get(b["wave_id"])
                    del db.bib_assignments[bid]
                    if wave is not None:
                        touched_waves.add(wave["id"])
        r["status"] = "CANCELLED"
        touch(r)
        if prev in ("CONFIRMED", "BIB_ASSIGNED"):
            touched_distances.add(r["distance_id"])
        # any PROPOSED transfer on this registration -> CANCELLED
        for tr in db.transfer_requests.values():
            if tr["registration_id"] == r["id"] and tr["status"] == "PROPOSED":
                tr["status"] = "CANCELLED"
                touch(tr)

    # CASCADE: every QUEUED or OFFERED waitlist entry -> WITHDRAWN
    for w in db.waitlist_entries.values():
        if w["distance_id"] in dist_ids and w["status"] in ("QUEUED", "OFFERED"):
            w["status"] = "WITHDRAWN"
            touch(w)

    # bump versions of affected distances/waves (confirmed_count recompute)
    for did in touched_distances:
        d = db.distances.get(did)
        if d is not None:
            touch(d)
    for wid in touched_waves:
        wv = db.waves.get(wid)
        if wv is not None:
            touch(wv)

    e["status"] = "CANCELLED"
    touch(e)
    return object_response(serialize_generic(e), 200)
