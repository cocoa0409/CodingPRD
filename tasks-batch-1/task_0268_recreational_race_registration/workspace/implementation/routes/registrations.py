"""Registration endpoints + lifecycle transitions."""
from flask import Blueprint, request

from db import db, new_id
from errors import (err, ERR_NOT_FOUND, ERR_RELATION_MISMATCH, ERR_INVALID_STATE,
                    ERR_REGISTRATION_CLOSED, ERR_NOT_RESOURCE_OWNER,
                    ERR_STALE_DISTANCE_VERSION, ERR_FUNDRAISING_MINIMUM_NOT_MET,
                    ERR_WAVE_FULL, ERR_TARGET_EVENT_INVALID, ERR_INVALID_REQUEST)
from middleware import auth, require_role, get_json, now_dt
from response import object_response
from services.store import (stamp_new, serialize_generic, touch,
                            confirmed_count, charity_confirmed_count,
                            wave_assigned_count, paginate_and_respond)
from services.calculations import (registration_amount_due, registration_refund,
                                   deferral_credit, fundraising_totals,
                                   corral_letter, BIB_START_NUMBER)
from services.validate import (require_str, opt_str, opt_int, opt_enum, require_int,
                               lookup)
from services.waitlist import promote_head

bp = Blueprint("registrations", __name__)

ENTRY_TYPES = {"STANDARD", "CHARITY"}


def _tiers_for_distance(distance_id):
    return [t for t in db.pricing_tiers.values() if t["distance_id"] == distance_id]


def _owner_check(user_id, role, owner_participant_id):
    """Participant-owned mutation: X-User-ID must equal the owning participant."""
    if role == "Participant" and user_id != owner_participant_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting participant is not the resource owner")


# ---------- create ----------

@bp.route("/registrations", methods=["POST"])
def create_registration():
    user_id, role = auth()
    require_role(role, {"Participant"})
    body = get_json()

    # existence of body FKs (path-then-body; here all are body), validated in
    # the documented order: event, distance, wave, participant.
    event_id = require_str(body, "event_id")
    distance_id = require_str(body, "distance_id")
    wave_id = require_str(body, "wave_id")
    participant_id = require_str(body, "participant_id")

    event = db.events.get(event_id)
    if event is None:
        raise err(ERR_NOT_FOUND, "Event not found")
    distance = db.distances.get(distance_id)
    if distance is None:
        raise err(ERR_NOT_FOUND, "Distance not found")
    wave = db.waves.get(wave_id)
    if wave is None:
        raise err(ERR_NOT_FOUND, "Wave not found")
    participant = db.participants.get(participant_id)
    if participant is None:
        raise err(ERR_NOT_FOUND, "Participant not found")

    # ownership: a participant may only create their own registration
    _owner_check(user_id, role, participant_id)

    # body well-formedness
    entry_type = opt_enum(body, "entry_type", ENTRY_TYPES, "STANDARD")
    party_size = opt_int(body, "party_size", default=1, minimum=1)
    promo_code = opt_str(body, "promo_code", default=None)
    qualifying_time = opt_int(body, "qualifying_time_seconds", default=None)

    # relationship consistency (ERR_RELATION_MISMATCH): wave in distance, distance in event
    if wave["distance_id"] != distance_id:
        raise err(ERR_RELATION_MISMATCH, "wave_id does not belong to distance_id")
    if distance["event_id"] != event_id:
        raise err(ERR_RELATION_MISMATCH, "distance_id does not belong to event_id")

    # temporal: event OPEN and within registration window
    if event["status"] != "OPEN":
        raise err(ERR_REGISTRATION_CLOSED, "Event is not open for registration")
    now = now_dt()
    if now < event["_reg_opens_dt"] or now >= event["_reg_closes_dt"]:
        raise err(ERR_REGISTRATION_CLOSED, "Outside the registration window")

    # provisional pricing (reference clock = creation clock). May raise
    # ERR_NO_ACTIVE_PRICING_TIER.
    amount_due, _fee, _disc = registration_amount_due(
        entry_type, party_size, promo_code, _tiers_for_distance(distance_id), now)

    fundraising_minimum = distance["charity_fundraising_minimum_cents"] if entry_type == "CHARITY" else 0

    rid = new_id()
    r = {
        "id": rid,
        "event_id": event_id,
        "distance_id": distance_id,
        "wave_id": wave_id,
        "participant_id": participant_id,
        "entry_type": entry_type,
        "party_size": party_size,
        "promo_code": promo_code,
        "qualifying_time_seconds": qualifying_time,
        "fundraising_minimum_cents": fundraising_minimum,
        "status": "PENDING_PAYMENT",
        "amount_due_cents": amount_due,
        "amount_paid_cents": 0,
        "processing_fee_cents": 0,
        "refund_cents": 0,
        "deferred_to_registration_id": None,
        "deferral_credit_cents": 0,
    }
    stamp_new(r)
    db.registrations[rid] = r
    return object_response(serialize_generic(r), 201)


@bp.route("/registrations/<registration_id>", methods=["GET"])
def get_registration(registration_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    r = lookup(db.registrations, registration_id, "Registration")
    return object_response(serialize_generic(r), 200)


@bp.route("/registrations", methods=["GET"])
def list_registrations():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    items = list(db.registrations.values())
    for f in ("event_id", "distance_id", "wave_id", "participant_id",
              "deferred_to_registration_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    return paginate_and_respond("registration", items, request.args)


# ---------- confirm-payment ----------

@bp.route("/registrations/<registration_id>/confirm-payment", methods=["POST"])
def confirm_payment(registration_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    r = lookup(db.registrations, registration_id, "Registration")
    _owner_check(user_id, role, r["participant_id"])

    body = get_json()
    expected_version = require_int(body, "expected_distance_version")

    # state: only from PENDING_PAYMENT
    if r["status"] != "PENDING_PAYMENT":
        raise err(ERR_INVALID_STATE, "Registration must be PENDING_PAYMENT to confirm payment")

    event = db.events.get(r["event_id"])
    if event is None or event["status"] != "OPEN":
        raise err(ERR_REGISTRATION_CLOSED, "Owning event is not OPEN")

    distance = db.distances.get(r["distance_id"])
    if distance is None:
        raise err(ERR_NOT_FOUND, "Distance not found")

    # OCC version check
    if expected_version != distance["version"]:
        raise err(ERR_STALE_DISTANCE_VERSION, "expected_distance_version is stale")

    now = now_dt()
    cc = confirmed_count(distance["id"])
    is_charity = r["entry_type"] == "CHARITY"
    cap_full = cc >= distance["capacity_total"]
    charity_full = is_charity and (charity_confirmed_count(distance["id"]) >= distance["charity_capacity"])

    if cap_full or charity_full:
        # route to WAITLISTED; create QUEUED WaitlistEntry; no charge captured
        r["status"] = "WAITLISTED"
        touch(r)
        wlid = new_id()
        wl = {
            "id": wlid,
            "distance_id": distance["id"],
            "registration_id": r["id"],
            "participant_id": r["participant_id"],
            "status": "QUEUED",
            "offer_expires_utc": None,
            "_offer_expires_dt": None,
        }
        stamp_new(wl)
        db.waitlist_entries[wlid] = wl
        return object_response(serialize_generic(r), 200)

    # capacity available -> CONFIRMED, capture final charge (confirm-time clock)
    amount, fee, _disc = registration_amount_due(
        r["entry_type"], r["party_size"], r["promo_code"],
        _tiers_for_distance(distance["id"]), now)
    r["amount_paid_cents"] = amount
    r["processing_fee_cents"] = fee
    r["status"] = "CONFIRMED"
    touch(r)
    touch(distance)  # confirmed_count changed -> bump Distance.version
    return object_response(serialize_generic(r), 200)


# ---------- cancel ----------

@bp.route("/registrations/<registration_id>/cancel", methods=["POST"])
def cancel_registration(registration_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    r = lookup(db.registrations, registration_id, "Registration")
    _owner_check(user_id, role, r["participant_id"])

    if r["status"] not in ("PENDING_PAYMENT", "CONFIRMED", "BIB_ASSIGNED", "WAITLISTED"):
        raise err(ERR_INVALID_STATE, "Registration cannot be cancelled from its current status")

    prev = r["status"]
    refund = registration_refund(prev, r["amount_paid_cents"], r["processing_fee_cents"], False)
    r["refund_cents"] = refund

    distance = db.distances.get(r["distance_id"])

    # delete bib + free wave slot if BIB_ASSIGNED
    if prev == "BIB_ASSIGNED":
        for bid, b in list(db.bib_assignments.items()):
            if b["registration_id"] == r["id"]:
                wave = db.waves.get(b["wave_id"])
                del db.bib_assignments[bid]
                if wave is not None:
                    touch(wave)

    # cancel any PROPOSED transfer on this registration
    for tr in db.transfer_requests.values():
        if tr["registration_id"] == r["id"] and tr["status"] == "PROPOSED":
            tr["status"] = "CANCELLED"
            touch(tr)

    r["status"] = "CANCELLED"
    touch(r)

    # if a confirmed slot was released, bump distance version and promote head
    if prev in ("CONFIRMED", "BIB_ASSIGNED") and distance is not None:
        touch(distance)
        promote_head(distance["id"])

    return object_response(serialize_generic(r), 200)


# ---------- assign-bib ----------

@bp.route("/registrations/<registration_id>/assign-bib", methods=["POST"])
def assign_bib(registration_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    r = lookup(db.registrations, registration_id, "Registration")

    if r["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Registration must be CONFIRMED to assign a bib")

    # CHARITY fundraising gate (settled total >= fundraising_minimum_cents)
    if r["entry_type"] == "CHARITY":
        pledges = [p for p in db.fundraising_pledges.values() if p["registration_id"] == r["id"]]
        _prov, settled = fundraising_totals(pledges)
        if settled < r["fundraising_minimum_cents"]:
            raise err(ERR_FUNDRAISING_MINIMUM_NOT_MET,
                      "Settled fundraising below the required minimum")

    wave = db.waves.get(r["wave_id"])
    if wave is None:
        raise err(ERR_NOT_FOUND, "Wave not found")
    if wave_assigned_count(wave["id"]) >= wave["wave_capacity"]:
        raise err(ERR_WAVE_FULL, "Wave is full")

    distance_id = r["distance_id"]

    bid = new_id()
    b = {
        "id": bid,
        "registration_id": r["id"],
        "distance_id": distance_id,
        "wave_id": wave["id"],
        "bib_number": None,
        "corral": None,
    }
    stamp_new(b)
    db.bib_assignments[bid] = b

    # corral: rank all bib assignments in the wave (including this new one) by
    # qualifying_time ASC (null last), created_at ASC tie-break (never id).
    _assign_corral(b, wave)
    # bib_number: next sequential within the distance, in created_at ASC order
    _assign_bib_numbers(distance_id)

    r["status"] = "BIB_ASSIGNED"
    touch(r)
    touch(wave)  # assigned_count changed -> bump Wave.version

    return object_response(serialize_generic(b), 201)


def _assign_corral(new_bib, wave):
    in_wave = [b for b in db.bib_assignments.values() if b["wave_id"] == wave["id"]]
    # rank key: qualifying_time of the linked registration (None -> +inf), then created_at, then seq
    def sort_key(b):
        reg = db.registrations.get(b["registration_id"])
        qt = reg.get("qualifying_time_seconds") if reg else None
        qt_key = (1, 0) if qt is None else (0, qt)  # None sorts last
        return (qt_key, b["_created_dt"], b["_seq"])
    in_wave.sort(key=sort_key)
    corral_cap = wave["corral_capacity"]
    for rank, b in enumerate(in_wave):
        idx = rank // corral_cap
        b["corral"] = corral_letter(idx)


def _assign_bib_numbers(distance_id):
    in_dist = [b for b in db.bib_assignments.values() if b["distance_id"] == distance_id]
    in_dist.sort(key=lambda b: (b["_created_dt"], b["_seq"]))
    num = BIB_START_NUMBER
    for b in in_dist:
        b["bib_number"] = num
        num += 1


# ---------- defer ----------

@bp.route("/registrations/<registration_id>/defer", methods=["POST"])
def defer_registration(registration_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    r = lookup(db.registrations, registration_id, "Registration")
    _owner_check(user_id, role, r["participant_id"])

    body = get_json()
    target_event_id = require_str(body, "target_event_id")
    target_event = db.events.get(target_event_id)
    if target_event is None:
        raise err(ERR_NOT_FOUND, "Target event not found")

    if r["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Registration must be CONFIRMED to defer")

    source_distance = db.distances.get(r["distance_id"])
    # target event must be DRAFT/OPEN, differ from source, and have a matching-label distance
    if (target_event["status"] not in ("DRAFT", "OPEN")
            or target_event_id == r["event_id"]):
        raise err(ERR_TARGET_EVENT_INVALID, "Target event is not a valid deferral target")
    target_distance = None
    for d in db.distances.values():
        if d["event_id"] == target_event_id and d["label"] == source_distance["label"]:
            target_distance = d
            break
    if target_distance is None:
        raise err(ERR_TARGET_EVENT_INVALID, "Target event has no matching distance label")

    # deferral credit
    credit = deferral_credit(r["amount_paid_cents"], r["processing_fee_cents"])
    r["deferral_credit_cents"] = credit

    # create new PENDING_PAYMENT registration on target distance
    new_rid = new_id()
    # pick any wave on the target distance for the requested wave_id reference
    target_wave = None
    for w in db.waves.values():
        if w["distance_id"] == target_distance["id"]:
            target_wave = w
            break
    new_reg = {
        "id": new_rid,
        "event_id": target_event_id,
        "distance_id": target_distance["id"],
        "wave_id": target_wave["id"] if target_wave else r["wave_id"],
        "participant_id": r["participant_id"],
        "entry_type": r["entry_type"],
        "party_size": r["party_size"],
        "promo_code": r["promo_code"],
        "qualifying_time_seconds": r["qualifying_time_seconds"],
        "fundraising_minimum_cents": (target_distance["charity_fundraising_minimum_cents"]
                                      if r["entry_type"] == "CHARITY" else 0),
        "status": "PENDING_PAYMENT",
        "amount_due_cents": 0,
        "amount_paid_cents": 0,
        "processing_fee_cents": 0,
        "refund_cents": 0,
        "deferred_to_registration_id": None,
        "deferral_credit_cents": 0,
    }
    stamp_new(new_reg)
    db.registrations[new_rid] = new_reg

    r["deferred_to_registration_id"] = new_rid
    r["status"] = "DEFERRED"
    touch(r)

    # original distance frees a slot: bump version + promote head waitlist
    if source_distance is not None:
        touch(source_distance)
        promote_head(source_distance["id"])

    return object_response(serialize_generic(r), 200)


# ---------- finish ----------

@bp.route("/registrations/<registration_id>/finish", methods=["POST"])
def finish_registration(registration_id):
    user_id, role = auth()
    require_role(role, {"TimingOfficial"})
    r = lookup(db.registrations, registration_id, "Registration")

    if r["status"] != "BIB_ASSIGNED":
        raise err(ERR_INVALID_STATE, "Registration must be BIB_ASSIGNED to finish")

    event = db.events.get(r["event_id"])
    if event is None or event["status"] not in ("CLOSED", "RESULTS_POSTED"):
        raise err(ERR_INVALID_STATE, "Owning event must be CLOSED or RESULTS_POSTED")

    has_official = any(res["registration_id"] == r["id"] and res["status"] == "OFFICIAL"
                       for res in db.result_records.values())
    if not has_official:
        raise err(ERR_INVALID_STATE, "An OFFICIAL result record is required to finish")

    r["status"] = "FINISHED"
    touch(r)
    return object_response(serialize_generic(r), 200)


# ---------- FK sub-list reads ----------

@bp.route("/registrations/<registration_id>/bib-assignments", methods=["GET"])
def list_reg_bibs(registration_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    lookup(db.registrations, registration_id, "Registration")
    items = [b for b in db.bib_assignments.values() if b["registration_id"] == registration_id]
    return paginate_and_respond("bib", items, request.args)


@bp.route("/registrations/<registration_id>/fundraising-pledges", methods=["GET"])
def list_reg_pledges(registration_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    lookup(db.registrations, registration_id, "Registration")
    items = [p for p in db.fundraising_pledges.values() if p["registration_id"] == registration_id]
    return paginate_and_respond("pledge", items, request.args)


@bp.route("/registrations/<registration_id>/packet-pickups", methods=["GET"])
def list_reg_pickups(registration_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    lookup(db.registrations, registration_id, "Registration")
    items = [p for p in db.packet_pickups.values() if p["registration_id"] == registration_id]
    return paginate_and_respond("pickup", items, request.args)


@bp.route("/registrations/<registration_id>/results", methods=["GET"])
def list_reg_results(registration_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    lookup(db.registrations, registration_id, "Registration")
    items = [res for res in db.result_records.values() if res["registration_id"] == registration_id]
    return paginate_and_respond("result", items, request.args)


@bp.route("/registrations/<registration_id>/transfer-requests", methods=["GET"])
def list_reg_transfers(registration_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    lookup(db.registrations, registration_id, "Registration")
    items = [tr for tr in db.transfer_requests.values() if tr["registration_id"] == registration_id]
    status = request.args.get("status")
    if status is not None:
        items = [tr for tr in items if tr["status"] == status]
    return paginate_and_respond("transfer", items, request.args)
