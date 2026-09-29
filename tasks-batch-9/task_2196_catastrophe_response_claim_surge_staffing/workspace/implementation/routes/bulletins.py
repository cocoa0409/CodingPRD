"""RegulatoryBulletin endpoints and lifecycle."""
from flask import Blueprint, request

import derive
import store
import sync
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing
from store import clock_now, touch

bp = Blueprint("bulletins", __name__)

BULLETIN_TYPES = ("CANCELLATION_MORATORIUM", "CLAIM_DEADLINE_EXTENSION",
                  "ADVANCE_PAYMENT_MANDATE", "ADJUSTER_LICENSE_WAIVER")


@bp.post("/regulatory-bulletins")
def create_bulletin():
    begin()
    # Position 4 - the body event reference resolves before schema work.
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")

    number = validate.req_string(payload, "bulletin_number")
    jurisdiction = validate.req_state(payload, "jurisdiction_state")
    bulletin_type = validate.req_enum(payload, "bulletin_type", BULLETIN_TYPES)
    effective_from = validate.req_datetime(payload, "effective_from")
    effective_to = validate.req_datetime(payload, "effective_to")
    pct = validate.opt_number(payload, "mandated_advance_pct", minimum=0, maximum=1,
                              default=store.dec("0.0"))
    days = validate.opt_int(payload, "deadline_extension_days", minimum=0,
                            maximum=365, default=0)
    # Position 16 - interval well-formedness.
    validate.interval(effective_from, effective_to,
                      "effective_to must be strictly later than effective_from.")
    # Position 31 - uniqueness of (event_id, bulletin_number).
    for other in store.bulletins.values():
        if other["event_id"] == event["id"] and other["bulletin_number"] == number:
            fail("ERR_BULLETIN_NUMBER_TAKEN")

    rec = store.base_record()
    rec.update({
        "event_id": event["id"],
        "bulletin_number": number,
        "jurisdiction_state": jurisdiction,
        "bulletin_type": bulletin_type,
        "status": "DRAFT",
        "effective_from": effective_from,
        "effective_to": effective_to,
        "mandated_advance_pct": pct,
        "deadline_extension_days": days,
        "activated_at_utc": None,
    })
    store.bulletins[rec["id"]] = rec
    return created(derive.bulletin_out(rec))


@bp.get("/regulatory-bulletins")
def list_bulletins():
    begin()
    rows = list(store.bulletins.values())
    for param, field in (("event_id", "event_id"),
                         ("bulletin_type", "bulletin_type"),
                         ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.bulletin_out)


@bp.get("/regulatory-bulletins/<bulletin_id>")
def read_bulletin(bulletin_id):
    begin()
    return ok(derive.bulletin_out(validate.bulletin(bulletin_id)))


@bp.post("/regulatory-bulletins/<bulletin_id>/activate")
def activate_bulletin(bulletin_id):
    begin()
    rec = validate.bulletin(bulletin_id)
    if rec["status"] != "DRAFT":
        fail("ERR_BULLETIN_NOT_DRAFT")
    event = store.events.get(rec["event_id"])
    if event is None or event["status"] not in ("DECLARED", "SURGE_ACTIVE"):
        fail("ERR_EVENT_NOT_DECLARED")
    # Position 30 - jurisdiction must match the parent event.
    if rec["jurisdiction_state"] != event["jurisdiction_state"]:
        fail("ERR_JURISDICTION_MISMATCH")

    rec["status"] = "EFFECTIVE"
    rec["activated_at_utc"] = clock_now()
    touch(rec)
    if rec["bulletin_type"] == "CLAIM_DEADLINE_EXTENSION":
        sync.recompute_event_deadlines(event["id"])
    if rec["bulletin_type"] == "CANCELLATION_MORATORIUM":
        touch(event)
    return ok(derive.bulletin_out(rec))


@bp.post("/regulatory-bulletins/<bulletin_id>/withdraw")
def withdraw_bulletin(bulletin_id):
    begin()
    rec = validate.bulletin(bulletin_id)
    if rec["status"] not in ("DRAFT", "EFFECTIVE"):
        fail("ERR_BULLETIN_NOT_WITHDRAWABLE")
    was_effective = rec["status"] == "EFFECTIVE"
    rec["status"] = "WITHDRAWN"
    touch(rec)
    if was_effective:
        sync.recompute_event_deadlines(rec["event_id"])
    return ok(derive.bulletin_out(rec))
