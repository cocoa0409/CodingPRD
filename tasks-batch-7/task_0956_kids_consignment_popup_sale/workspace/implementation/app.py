"""Kids' Consignment Pop-Up Sale API — Flask entry point."""
import os

from flask import Flask

from core import (
    ApiError, store, auth, require, forbidden, body,
    ok, ok_array, ok_list, err_response,
    parse_dt, fmt_clock, stamp, stamp_light, touch, by_created,
    get_or_404, apply_filters, rhu, tier, volunteer_hours,
    payout_pipeline, provisional_for_consignor, markdown_pct_at,
    serialize_event, serialize_rule, serialize_consignor, serialize_volunteer,
    serialize_slot, serialize_booking, serialize_item, serialize_inspection,
    serialize_shift, serialize_signup, serialize_pass, serialize_txn,
    serialize_line, serialize_settlement,
    NEXT_PHASE, TERMINAL_ITEM_STATUSES,
)

app = Flask(__name__)

EVENT_DT_FIELDS = (
    "intake_start", "intake_end", "presale_start", "presale_end",
    "sale_start", "sale_end", "pickup_deadline",
)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(405)
def _handle_405(e):
    return err_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed."))


@app.errorhandler(Exception)
def _handle_any(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError("ERR_INTERNAL", 500, "Internal server error."))


def _event_or_404(event_id):
    return get_or_404("sale_events", event_id, "ERR_SALE_EVENT_NOT_FOUND", "Sale event")


def _phase_gate(ev, allowed):
    if ev["phase"] not in allowed:
        raise ApiError(
            "ERR_EVENT_PHASE_MISMATCH", 409,
            "Operation not allowed in event phase %s." % ev["phase"],
        )


# ===========================================================================
# Sale events
# ===========================================================================


@app.post("/sale-events")
def create_sale_event():
    uid, role = auth()
    require(role, "EventOrganizer")
    b = body()
    ev = {"name": b.get("name"), "phase": "DRAFT"}
    for f in EVENT_DT_FIELDS:
        ev[f] = b.get(f)
        ev["_" + f] = parse_dt(b.get(f))
    stamp(ev)
    store.sale_events[ev["id"]] = ev
    return ok(serialize_event(ev), 201)


@app.get("/sale-events")
def list_sale_events():
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor", "Volunteer", "Inspector", "Cashier")
    recs = apply_filters(store.sale_events.values(), {"phase": "phase"})
    return ok_list([serialize_event(e) for e in by_created(recs)])


@app.get("/sale-events/<eid>")
def get_sale_event(eid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor", "Volunteer", "Inspector", "Cashier")
    return ok(serialize_event(_event_or_404(eid)))


@app.post("/sale-events/<eid>/advance-phase")
def advance_phase(eid):
    uid, role = auth()
    require(role, "EventOrganizer")
    ev = _event_or_404(eid)
    to_phase = body().get("to_phase")
    nxt = NEXT_PHASE.get(ev["phase"])
    if to_phase != nxt:
        raise ApiError("ERR_EVENT_PHASE_MISMATCH", 409,
                       "Cannot advance from %s to %s." % (ev["phase"], to_phase))
    ck = store.clock

    def _clock_gate(field):
        threshold = ev.get("_" + field)
        if threshold is not None and ck < threshold:
            raise ApiError("ERR_EVENT_PHASE_MISMATCH", 409,
                           "Logical clock has not reached %s." % field)

    if to_phase == "INTAKE_OPEN":
        _clock_gate("intake_start")
    elif to_phase == "INTAKE_CLOSED":
        _clock_gate("intake_end")
    elif to_phase == "PRESALE_DAY":
        _clock_gate("presale_start")
        if any(i["status"] == "DROPPED_OFF" for i in store.items.values()
               if i["sale_event_id"] == eid):
            raise ApiError("ERR_UNINSPECTED_ITEMS_REMAIN", 409,
                           "Items remain in DROPPED_OFF status.")
    elif to_phase == "SALE_ACTIVE":
        _clock_gate("sale_start")
    elif to_phase == "SETTLEMENT":
        _clock_gate("sale_end")
        if any(t["status"] == "OPEN" for t in store.transactions.values()
               if t["sale_event_id"] == eid):
            raise ApiError("ERR_OPEN_TRANSACTIONS_REMAIN", 409,
                           "Transactions remain OPEN.")
    elif to_phase == "CLOSED":
        # Conditional donation cascade runs BEFORE precondition checks.
        for item in by_created([i for i in store.items.values()
                                if i["sale_event_id"] == eid]):
            if item["status"] == "UNSOLD" and item.get("donate_flag"):
                item["status"] = "DONATED"
                touch(item)
            elif item["status"] == "REJECTED":
                item["status"] = "DONATED"
                touch(item)
        if any(i["status"] not in TERMINAL_ITEM_STATUSES
               for i in store.items.values() if i["sale_event_id"] == eid):
            raise ApiError("ERR_ITEMS_NOT_TERMINAL", 409,
                           "Items remain in non-terminal status.")
        if any(s["status"] != "PAID" for s in store.settlements.values()
               if s["sale_event_id"] == eid):
            raise ApiError("ERR_EVENT_PHASE_MISMATCH", 409,
                           "Not all settlements of the event are PAID.")

    # Side effects
    if to_phase == "INTAKE_CLOSED":
        for bk in store.bookings.values():
            slot = store.slots.get(bk["slot_id"])
            if slot is None or slot["sale_event_id"] != eid:
                continue
            if bk["status"] == "BOOKED":
                bk["status"] = "NO_SHOW"
                touch(bk)
            elif bk["status"] == "CHECKED_IN":
                bk["status"] = "COMPLETED"
                touch(bk)
    elif to_phase == "PRESALE_DAY":
        for item in by_created([i for i in store.items.values()
                                if i["sale_event_id"] == eid and i["status"] == "ACCEPTED"]):
            item["status"] = "ON_FLOOR"
            touch(item)
    elif to_phase == "SETTLEMENT":
        for item in by_created([i for i in store.items.values()
                                if i["sale_event_id"] == eid and i["status"] == "ON_FLOOR"]):
            item["status"] = "UNSOLD"
            touch(item)

    ev["phase"] = to_phase
    touch(ev)
    return ok(serialize_event(ev))


@app.post("/sale-events/<eid>/issue-presale-passes")
def issue_presale_passes(eid):
    uid, role = auth()
    require(role, "EventOrganizer")
    ev = _event_or_404(eid)
    _phase_gate(ev, ("INTAKE_CLOSED", "PRESALE_DAY"))

    holders = [("CONSIGNOR", c) for c in store.consignors.values()
               if c["sale_event_id"] == eid]
    holders += [("VOLUNTEER", v) for v in store.volunteers.values()
                if v["sale_event_id"] == eid]
    holders.sort(key=lambda h: (h[1]["created_at"], h[1]["_seq"]))

    def _has_active_pass(kind, holder_id):
        return any(p["sale_event_id"] == eid and p["holder_type"] == kind
                   and p["holder_id"] == holder_id and p["status"] == "ACTIVE"
                   for p in store.passes.values())

    created = []
    for kind, obj in holders:
        if _has_active_pass(kind, obj["id"]):
            continue
        if kind == "CONSIGNOR":
            if obj["status"] != "ACTIVE":
                continue
            eligible = any(
                i["status"] in ("ACCEPTED", "ON_FLOOR", "IN_CART", "SOLD")
                for i in store.items.values() if i["consignor_id"] == obj["id"]
            )
            pct = 0
        else:
            eligible = any(
                s["status"] in ("CHECKED_IN", "COMPLETED")
                for s in store.signups.values() if s["volunteer_id"] == obj["id"]
            )
            completed, _ = volunteer_hours(obj["id"])
            pct = tier(completed)
        if not eligible:
            continue
        p = {
            "sale_event_id": eid,
            "holder_type": kind,
            "holder_id": obj["id"],
            "discount_pct": pct,
            "status": "ACTIVE",
        }
        stamp(p)
        store.passes[p["id"]] = p
        created.append(p)
    return ok_array([serialize_pass(p) for p in created])


@app.post("/sale-events/<eid>/generate-settlements")
def generate_settlements(eid):
    uid, role = auth()
    require(role, "EventOrganizer")
    ev = _event_or_404(eid)
    _phase_gate(ev, ("SALE_ACTIVE", "SETTLEMENT"))
    if any(s["sale_event_id"] == eid and s["status"] in ("FINALIZED", "DISPUTED", "PAID")
           for s in store.settlements.values()):
        raise ApiError("ERR_SETTLEMENTS_LOCKED", 409,
                       "Settlements of this event are locked.")
    expected = body().get("expected_sale_event_version")
    if expected != ev["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_sale_event_version does not match the event version.")

    for sid in [s["id"] for s in store.settlements.values()
                if s["sale_event_id"] == eid and s["status"] == "DRAFT"]:
        del store.settlements[sid]

    created = []
    for cons in by_created([c for c in store.consignors.values()
                            if c["sale_event_id"] == eid]):
        if not any(i["status"] != "TAGGED" for i in store.items.values()
                   if i["consignor_id"] == cons["id"]):
            continue
        g, payout = provisional_for_consignor(cons)
        s = {
            "sale_event_id": eid,
            "consignor_id": cons["id"],
            "status": "DRAFT",
            "provisional_gross_cents": g,
            "provisional_payout_cents": payout,
            "gross_cents": None,
            "split_pct": None,
            "commission_cents": None,
            "payout_before_fee_cents": None,
            "supply_fee_cents": None,
            "rejected_fee_cents": None,
            "adjustment_cents": 0,
            "payout_cents": None,
            "dispute_reason": None,
        }
        stamp(s)
        store.settlements[s["id"]] = s
        created.append(s)
    touch(ev)
    return ok_array([serialize_settlement(s) for s in created])


# ===========================================================================
# Markdown rules
# ===========================================================================


@app.post("/markdown-rules")
def create_markdown_rule():
    uid, role = auth()
    require(role, "EventOrganizer")
    b = body()
    ev = _event_or_404(b.get("sale_event_id"))
    _phase_gate(ev, ("DRAFT", "INTAKE_OPEN", "INTAKE_CLOSED", "PRESALE_DAY"))
    frm = parse_dt(b.get("effective_from"))
    to = parse_dt(b.get("effective_to"))
    if frm is None or to is None or frm >= to:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 409,
                       "effective_from must be strictly before effective_to.")
    for r in store.markdown_rules.values():
        if r["sale_event_id"] != ev["id"]:
            continue
        if r["_from"] < to and frm < r["_to"]:
            raise ApiError("ERR_MARKDOWN_WINDOW_OVERLAP", 409,
                           "Markdown window overlaps an existing rule.")
    rec = {
        "sale_event_id": ev["id"],
        "effective_from": b.get("effective_from"),
        "effective_to": b.get("effective_to"),
        "discount_pct": b.get("discount_pct"),
        "_from": frm,
        "_to": to,
    }
    stamp(rec)
    store.markdown_rules[rec["id"]] = rec
    return ok(serialize_rule(rec), 201)


@app.get("/markdown-rules")
def list_markdown_rules():
    uid, role = auth()
    require(role, "EventOrganizer", "Cashier")
    recs = apply_filters(store.markdown_rules.values(), {"sale_event_id": "sale_event_id"})
    return ok_list([serialize_rule(r) for r in by_created(recs)])


@app.get("/markdown-rules/<rid>")
def get_markdown_rule(rid):
    uid, role = auth()
    require(role, "EventOrganizer", "Cashier")
    return ok(serialize_rule(get_or_404("markdown_rules", rid,
                                        "ERR_MARKDOWN_RULE_NOT_FOUND", "Markdown rule")))


# ===========================================================================
# Consignors
# ===========================================================================


@app.post("/consignors")
def create_consignor():
    uid, role = auth()
    require(role, "Anonymous")
    b = body()
    ev = _event_or_404(b.get("sale_event_id"))
    _phase_gate(ev, ("DRAFT", "INTAKE_OPEN"))
    n = sum(1 for c in store.consignors.values() if c["sale_event_id"] == ev["id"]) + 1
    rec = {
        "sale_event_id": ev["id"],
        "full_name": b.get("full_name"),
        "email": b.get("email"),
        "consignor_code": "C%04d" % n,
        "status": "ACTIVE",
    }
    stamp(rec)
    store.consignors[rec["id"]] = rec
    return ok(serialize_consignor(rec), 201)


@app.get("/consignors")
def list_consignors():
    uid, role = auth()
    require(role, "EventOrganizer")
    recs = apply_filters(store.consignors.values(),
                         {"sale_event_id": "sale_event_id", "status": "status"})
    return ok_list([serialize_consignor(c) for c in by_created(recs)])


@app.get("/consignors/<cid>")
def get_consignor(cid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    if role == "Consignor" and cid != uid:
        forbidden("Consignors may only read their own record.")
    return ok(serialize_consignor(get_or_404("consignors", cid,
                                             "ERR_CONSIGNOR_NOT_FOUND", "Consignor")))


@app.post("/consignors/<cid>/withdraw")
def withdraw_consignor(cid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    if role == "Consignor" and cid != uid:
        forbidden("Consignors may only withdraw themselves.")
    cons = get_or_404("consignors", cid, "ERR_CONSIGNOR_NOT_FOUND", "Consignor")
    if cons["status"] == "WITHDRAWN":
        return ok(serialize_consignor(cons))
    if any(i["consignor_id"] == cid for i in store.items.values()):
        raise ApiError("ERR_CONSIGNOR_HAS_ITEMS", 409,
                       "Consignor owns items and cannot withdraw.")
    cons["status"] = "WITHDRAWN"
    touch(cons)
    return ok(serialize_consignor(cons))


# ===========================================================================
# Volunteers
# ===========================================================================


@app.post("/volunteers")
def create_volunteer():
    uid, role = auth()
    require(role, "Anonymous")
    b = body()
    ev = _event_or_404(b.get("sale_event_id"))
    linked = b.get("linked_consignor_id")
    if linked is not None:
        get_or_404("consignors", linked, "ERR_CONSIGNOR_NOT_FOUND", "Consignor")
    _phase_gate(ev, ("DRAFT", "INTAKE_OPEN"))
    rec = {
        "sale_event_id": ev["id"],
        "full_name": b.get("full_name"),
        "email": b.get("email"),
        "linked_consignor_id": linked,
    }
    stamp(rec)
    store.volunteers[rec["id"]] = rec
    return ok(serialize_volunteer(rec), 201)


@app.get("/volunteers")
def list_volunteers():
    uid, role = auth()
    require(role, "EventOrganizer")
    recs = apply_filters(store.volunteers.values(),
                         {"sale_event_id": "sale_event_id",
                          "linked_consignor_id": "linked_consignor_id"})
    return ok_list([serialize_volunteer(v) for v in by_created(recs)])


@app.get("/volunteers/<vid>")
def get_volunteer(vid):
    uid, role = auth()
    require(role, "EventOrganizer", "Volunteer", "Inspector")
    if role in ("Volunteer", "Inspector") and vid != uid:
        forbidden("Volunteers may only read their own record.")
    return ok(serialize_volunteer(get_or_404("volunteers", vid,
                                             "ERR_VOLUNTEER_NOT_FOUND", "Volunteer")))


# ===========================================================================
# Drop-off slots and bookings
# ===========================================================================


@app.post("/drop-off-slots")
def create_slot():
    uid, role = auth()
    require(role, "EventOrganizer")
    b = body()
    ev = _event_or_404(b.get("sale_event_id"))
    _phase_gate(ev, ("DRAFT", "INTAKE_OPEN"))
    start = parse_dt(b.get("start_time"))
    end = parse_dt(b.get("end_time"))
    if start is None or end is None or start >= end:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 409,
                       "start_time must be strictly before end_time.")
    rec = {
        "sale_event_id": ev["id"],
        "start_time": b.get("start_time"),
        "end_time": b.get("end_time"),
        "capacity": b.get("capacity"),
        "_start": start,
        "_end": end,
    }
    stamp(rec)
    store.slots[rec["id"]] = rec
    return ok(serialize_slot(rec), 201)


@app.get("/drop-off-slots")
def list_slots():
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    recs = apply_filters(store.slots.values(), {"sale_event_id": "sale_event_id"})
    return ok_list([serialize_slot(s) for s in by_created(recs)])


@app.get("/drop-off-slots/<sid>")
def get_slot(sid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    return ok(serialize_slot(get_or_404("slots", sid, "ERR_SLOT_NOT_FOUND", "Slot")))


@app.post("/drop-off-bookings")
def create_booking():
    uid, role = auth()
    require(role, "Consignor")
    b = body()
    if b.get("consignor_id") != uid:
        forbidden("Consignors may only book for themselves.")
    slot = get_or_404("slots", b.get("slot_id"), "ERR_SLOT_NOT_FOUND", "Slot")
    cons = get_or_404("consignors", b.get("consignor_id"),
                      "ERR_CONSIGNOR_NOT_FOUND", "Consignor")
    ev = _event_or_404(slot["sale_event_id"])
    _phase_gate(ev, ("DRAFT", "INTAKE_OPEN"))
    from core import slot_booked_count
    if slot_booked_count(slot["id"]) >= (slot.get("capacity") or 0):
        raise ApiError("ERR_SLOT_FULL", 409, "Drop-off slot is full.")
    for bk in store.bookings.values():
        if bk["consignor_id"] != cons["id"] or bk["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        other_slot = store.slots.get(bk["slot_id"])
        if other_slot is not None and other_slot["sale_event_id"] == ev["id"]:
            raise ApiError("ERR_DUPLICATE_ACTIVE_BOOKING", 409,
                           "Consignor already holds an active booking for this event.")
    rec = {"slot_id": slot["id"], "consignor_id": cons["id"], "status": "BOOKED"}
    stamp(rec)
    store.bookings[rec["id"]] = rec
    return ok(serialize_booking(rec), 201)


@app.get("/drop-off-bookings")
def list_bookings():
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    recs = apply_filters(store.bookings.values(),
                         {"slot_id": "slot_id", "consignor_id": "consignor_id",
                          "status": "status"})
    return ok_list([serialize_booking(b) for b in by_created(recs)])


@app.get("/drop-off-bookings/<bid>")
def get_booking(bid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    bk = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND", "Booking")
    if role == "Consignor" and bk["consignor_id"] != uid:
        forbidden("Consignors may only read their own bookings.")
    return ok(serialize_booking(bk))


@app.post("/drop-off-bookings/<bid>/cancel")
def cancel_booking(bid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    bk = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND", "Booking")
    if role == "Consignor" and bk["consignor_id"] != uid:
        forbidden("Consignors may only cancel their own bookings.")
    if bk["status"] != "BOOKED":
        raise ApiError("ERR_BOOKING_WRONG_STATE", 409,
                       "Only a BOOKED booking can be cancelled.")
    bk["status"] = "CANCELLED"
    touch(bk)
    return ok(serialize_booking(bk))


@app.post("/drop-off-bookings/<bid>/check-in")
def check_in_booking(bid):
    uid, role = auth()
    require(role, "EventOrganizer")
    bk = get_or_404("bookings", bid, "ERR_BOOKING_NOT_FOUND", "Booking")
    slot = store.slots.get(bk["slot_id"])
    ev = _event_or_404(slot["sale_event_id"]) if slot else None
    _phase_gate(ev, ("INTAKE_OPEN",))
    if bk["status"] != "BOOKED":
        raise ApiError("ERR_BOOKING_WRONG_STATE", 409,
                       "Only a BOOKED booking can be checked in.")
    bk["status"] = "CHECKED_IN"
    touch(bk)
    return ok(serialize_booking(bk))


# ===========================================================================
# Items and inspection records
# ===========================================================================


@app.post("/items")
def create_item():
    uid, role = auth()
    require(role, "Consignor")
    b = body()
    if b.get("consignor_id") != uid:
        forbidden("Consignors may only tag their own items.")
    cons = get_or_404("consignors", b.get("consignor_id"),
                      "ERR_CONSIGNOR_NOT_FOUND", "Consignor")
    ev = _event_or_404(cons["sale_event_id"])
    _phase_gate(ev, ("DRAFT", "INTAKE_OPEN"))
    price = b.get("price_cents")
    if not isinstance(price, int) or isinstance(price, bool) or price < 200:
        raise ApiError("ERR_PRICE_BELOW_MINIMUM", 400,
                       "price_cents must be at least 200.")
    if price % 50 != 0:
        raise ApiError("ERR_PRICE_INCREMENT_VIOLATION", 400,
                       "price_cents must be a multiple of 50.")
    m = sum(1 for i in store.items.values() if i["consignor_id"] == cons["id"]) + 1
    rec = {
        "consignor_id": cons["id"],
        "sale_event_id": cons["sale_event_id"],
        "title": b.get("title"),
        "category": b.get("category"),
        "size": b.get("size"),
        "price_cents": price,
        "discount_eligible": b.get("discount_eligible", True),
        "donate_flag": b.get("donate_flag", False),
        "barcode": "%s-%04d" % (cons["consignor_code"], m),
        "status": "TAGGED",
        "reject_reason": None,
    }
    stamp(rec)
    store.items[rec["id"]] = rec
    return ok(serialize_item(rec), 201)


@app.get("/items")
def list_items():
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor", "Cashier", "Inspector")
    recs = apply_filters(store.items.values(),
                         {"sale_event_id": "sale_event_id",
                          "consignor_id": "consignor_id",
                          "status": "status", "barcode": "barcode"})
    return ok_list([serialize_item(i) for i in by_created(recs)])


@app.get("/items/<iid>")
def get_item(iid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor", "Cashier", "Inspector")
    item = get_or_404("items", iid, "ERR_ITEM_NOT_FOUND", "Item")
    if role == "Consignor" and item["consignor_id"] != uid:
        forbidden("Consignors may only read their own items.")
    return ok(serialize_item(item))


@app.post("/items/<iid>/drop-off")
def drop_off_item(iid):
    uid, role = auth()
    require(role, "Consignor")
    item = get_or_404("items", iid, "ERR_ITEM_NOT_FOUND", "Item")
    if item["consignor_id"] != uid:
        forbidden("Consignors may only drop off their own items.")
    ev = _event_or_404(item["sale_event_id"])
    _phase_gate(ev, ("INTAKE_OPEN",))
    if item["status"] != "TAGGED":
        raise ApiError("ERR_ITEM_WRONG_STATE", 409,
                       "Only a TAGGED item can be dropped off.")
    ck = store.clock
    if (ev["_intake_start"] is not None and ck < ev["_intake_start"]) or \
            (ev["_intake_end"] is not None and ck >= ev["_intake_end"]):
        raise ApiError("ERR_INTAKE_WINDOW_CLOSED", 409,
                       "Drop-off is outside the intake window.")
    has_booking = False
    for bk in store.bookings.values():
        if bk["consignor_id"] != uid or bk["status"] != "CHECKED_IN":
            continue
        slot = store.slots.get(bk["slot_id"])
        if slot is not None and slot["sale_event_id"] == ev["id"]:
            has_booking = True
            break
    if not has_booking:
        raise ApiError("ERR_NO_CHECKED_IN_BOOKING", 409,
                       "Consignor has no CHECKED_IN booking for this event.")
    item["status"] = "DROPPED_OFF"
    touch(item)
    return ok(serialize_item(item))


@app.post("/items/<iid>/inspect")
def inspect_item(iid):
    uid, role = auth()
    require(role, "Inspector")
    item = get_or_404("items", iid, "ERR_ITEM_NOT_FOUND", "Item")
    ev = _event_or_404(item["sale_event_id"])
    _phase_gate(ev, ("INTAKE_OPEN", "INTAKE_CLOSED"))
    if item["status"] != "DROPPED_OFF":
        raise ApiError("ERR_ITEM_WRONG_STATE", 409,
                       "Only a DROPPED_OFF item can be inspected.")
    volunteer = store.volunteers.get(uid)
    if volunteer is not None and \
            volunteer.get("linked_consignor_id") == item["consignor_id"]:
        raise ApiError("ERR_INSPECTION_SELF_DEALING", 403,
                       "Inspector may not inspect their own consigned items.")
    if ev["_presale_start"] is not None and store.clock >= ev["_presale_start"]:
        raise ApiError("ERR_INSPECTION_DEADLINE_PASSED", 409,
                       "Inspection deadline (presale_start) has passed.")
    b = body()
    outcome = b.get("outcome")
    reasons = b.get("reasons")
    if outcome == "PASS":
        item["status"] = "ACCEPTED"
        record_reasons = None
    elif outcome == "FAIL":
        item["status"] = "REJECTED"
        item["reject_reason"] = reasons
        record_reasons = reasons
    else:
        raise ApiError("ERR_VALIDATION", 400, "outcome must be PASS or FAIL.")
    touch(item)
    rec = {
        "item_id": item["id"],
        "inspector_id": uid,
        "outcome": outcome,
        "reasons": record_reasons,
    }
    stamp_light(rec)
    store.inspection_records[rec["id"]] = rec
    return ok(serialize_item(item))


@app.post("/items/<iid>/pickup")
def pickup_item(iid):
    uid, role = auth()
    require(role, "Consignor")
    item = get_or_404("items", iid, "ERR_ITEM_NOT_FOUND", "Item")
    if item["consignor_id"] != uid:
        forbidden("Consignors may only pick up their own items.")
    ev = _event_or_404(item["sale_event_id"])
    _phase_gate(ev, ("INTAKE_CLOSED", "PRESALE_DAY", "SALE_ACTIVE", "SETTLEMENT"))
    if item["status"] not in ("REJECTED", "UNSOLD"):
        raise ApiError("ERR_ITEM_WRONG_STATE", 409,
                       "Only a REJECTED or UNSOLD item can be picked up.")
    if item["status"] == "UNSOLD":
        if ev["phase"] != "SETTLEMENT":
            raise ApiError("ERR_EVENT_PHASE_MISMATCH", 409,
                           "Unsold pickup requires the SETTLEMENT phase.")
        if ev["_pickup_deadline"] is not None and store.clock > ev["_pickup_deadline"]:
            raise ApiError("ERR_PICKUP_WINDOW_CLOSED", 409,
                           "Pickup deadline has passed.")
    item["status"] = "PICKED_UP"
    touch(item)
    return ok(serialize_item(item))


@app.get("/inspection-records")
def list_inspection_records():
    uid, role = auth()
    require(role, "EventOrganizer", "Inspector")
    recs = apply_filters(store.inspection_records.values(),
                         {"item_id": "item_id", "inspector_id": "inspector_id"})
    return ok_list([serialize_inspection(r) for r in by_created(recs)])


@app.get("/inspection-records/<rid>")
def get_inspection_record(rid):
    uid, role = auth()
    require(role, "EventOrganizer", "Inspector")
    return ok(serialize_inspection(get_or_404(
        "inspection_records", rid, "ERR_INSPECTION_RECORD_NOT_FOUND",
        "Inspection record")))


# ===========================================================================
# Volunteer shifts and signups
# ===========================================================================


@app.post("/volunteer-shifts")
def create_shift():
    uid, role = auth()
    require(role, "EventOrganizer")
    b = body()
    ev = _event_or_404(b.get("sale_event_id"))
    _phase_gate(ev, ("DRAFT", "INTAKE_OPEN", "INTAKE_CLOSED"))
    start = parse_dt(b.get("start_time"))
    end = parse_dt(b.get("end_time"))
    if start is None or end is None or start >= end:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 409,
                       "start_time must be strictly before end_time.")
    rec = {
        "sale_event_id": ev["id"],
        "role_name": b.get("role_name"),
        "start_time": b.get("start_time"),
        "end_time": b.get("end_time"),
        "capacity": b.get("capacity"),
        "_start": start,
        "_end": end,
    }
    stamp(rec)
    store.shifts[rec["id"]] = rec
    return ok(serialize_shift(rec), 201)


@app.get("/volunteer-shifts")
def list_shifts():
    uid, role = auth()
    require(role, "EventOrganizer", "Volunteer", "Inspector")
    recs = apply_filters(store.shifts.values(), {"sale_event_id": "sale_event_id"})
    return ok_list([serialize_shift(s) for s in by_created(recs)])


@app.get("/volunteer-shifts/<sid>")
def get_shift(sid):
    uid, role = auth()
    require(role, "EventOrganizer", "Volunteer", "Inspector")
    return ok(serialize_shift(get_or_404("shifts", sid, "ERR_SHIFT_NOT_FOUND", "Shift")))


@app.post("/shift-signups")
def create_signup():
    uid, role = auth()
    require(role, "Volunteer")
    b = body()
    if b.get("volunteer_id") != uid:
        forbidden("Volunteers may only sign up themselves.")
    shift = get_or_404("shifts", b.get("shift_id"), "ERR_SHIFT_NOT_FOUND", "Shift")
    vol = get_or_404("volunteers", b.get("volunteer_id"),
                     "ERR_VOLUNTEER_NOT_FOUND", "Volunteer")
    ev = _event_or_404(shift["sale_event_id"])
    if ev["phase"] in ("SETTLEMENT", "CLOSED"):
        raise ApiError("ERR_EVENT_PHASE_MISMATCH", 409,
                       "Shift signup is not allowed in phase %s." % ev["phase"])
    for su in store.signups.values():
        if su["volunteer_id"] != vol["id"] or su["status"] not in ("SIGNED_UP", "CHECKED_IN"):
            continue
        other = store.shifts.get(su["shift_id"])
        if other is None:
            continue
        if other["_start"] < shift["_end"] and shift["_start"] < other["_end"]:
            raise ApiError("ERR_SHIFT_OVERLAP", 409,
                           "Signup overlaps an existing signup's shift.")
    from core import shift_signed_up_count
    if shift_signed_up_count(shift["id"]) >= (shift.get("capacity") or 0):
        raise ApiError("ERR_SHIFT_FULL", 409, "Shift is full.")
    rec = {
        "shift_id": shift["id"],
        "volunteer_id": vol["id"],
        "status": "SIGNED_UP",
        "hours_credited": 0,
    }
    stamp(rec)
    store.signups[rec["id"]] = rec
    return ok(serialize_signup(rec), 201)


@app.get("/shift-signups")
def list_signups():
    uid, role = auth()
    require(role, "EventOrganizer", "Volunteer", "Inspector")
    recs = apply_filters(store.signups.values(),
                         {"shift_id": "shift_id", "volunteer_id": "volunteer_id",
                          "status": "status"})
    return ok_list([serialize_signup(s) for s in by_created(recs)])


@app.get("/shift-signups/<sid>")
def get_signup(sid):
    uid, role = auth()
    require(role, "EventOrganizer", "Volunteer", "Inspector")
    su = get_or_404("signups", sid, "ERR_SIGNUP_NOT_FOUND", "Signup")
    if role == "Volunteer" and su["volunteer_id"] != uid:
        forbidden("Volunteers may only read their own signups.")
    return ok(serialize_signup(su))


@app.post("/shift-signups/<sid>/cancel")
def cancel_signup(sid):
    uid, role = auth()
    require(role, "EventOrganizer", "Volunteer")
    su = get_or_404("signups", sid, "ERR_SIGNUP_NOT_FOUND", "Signup")
    if role == "Volunteer" and su["volunteer_id"] != uid:
        forbidden("Volunteers may only cancel their own signups.")
    if su["status"] != "SIGNED_UP":
        raise ApiError("ERR_SIGNUP_WRONG_STATE", 409,
                       "Only a SIGNED_UP signup can be cancelled.")
    su["status"] = "CANCELLED"
    touch(su)
    return ok(serialize_signup(su))


@app.post("/shift-signups/<sid>/check-in")
def check_in_signup(sid):
    uid, role = auth()
    require(role, "EventOrganizer")
    su = get_or_404("signups", sid, "ERR_SIGNUP_NOT_FOUND", "Signup")
    if su["status"] != "SIGNED_UP":
        raise ApiError("ERR_SIGNUP_WRONG_STATE", 409,
                       "Only a SIGNED_UP signup can be checked in.")
    su["status"] = "CHECKED_IN"
    touch(su)
    return ok(serialize_signup(su))


@app.post("/shift-signups/<sid>/check-out")
def check_out_signup(sid):
    uid, role = auth()
    require(role, "EventOrganizer")
    su = get_or_404("signups", sid, "ERR_SIGNUP_NOT_FOUND", "Signup")
    if su["status"] != "CHECKED_IN":
        raise ApiError("ERR_SIGNUP_WRONG_STATE", 409,
                       "Only a CHECKED_IN signup can be checked out.")
    shift = store.shifts.get(su["shift_id"])
    hours = 0.0
    if shift is not None:
        hours = round((shift["_end"] - shift["_start"]).total_seconds() / 3600.0, 2)
    su["hours_credited"] = hours
    su["status"] = "COMPLETED"
    touch(su)
    return ok(serialize_signup(su))


@app.post("/shift-signups/<sid>/mark-no-show")
def mark_no_show_signup(sid):
    uid, role = auth()
    require(role, "EventOrganizer")
    su = get_or_404("signups", sid, "ERR_SIGNUP_NOT_FOUND", "Signup")
    if su["status"] != "SIGNED_UP":
        raise ApiError("ERR_SIGNUP_WRONG_STATE", 409,
                       "Only a SIGNED_UP signup can be marked no-show.")
    shift = store.shifts.get(su["shift_id"])
    if shift is not None and store.clock <= shift["_end"]:
        raise ApiError("ERR_NO_SHOW_TOO_EARLY", 409,
                       "Cannot mark no-show before the shift's end_time.")
    su["status"] = "NO_SHOW"
    touch(su)
    return ok(serialize_signup(su))


# ===========================================================================
# Presale passes
# ===========================================================================


def _pass_ownership(role, uid, p):
    if role == "Consignor":
        if not (p["holder_type"] == "CONSIGNOR" and p["holder_id"] == uid):
            forbidden("Consignors may only read their own passes.")
    elif role == "Volunteer":
        if not (p["holder_type"] == "VOLUNTEER" and p["holder_id"] == uid):
            forbidden("Volunteers may only read their own passes.")


@app.get("/presale-passes")
def list_passes():
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor", "Volunteer", "Cashier")
    recs = apply_filters(store.passes.values(),
                         {"sale_event_id": "sale_event_id",
                          "holder_id": "holder_id", "status": "status"})
    return ok_list([serialize_pass(p) for p in by_created(recs)])


@app.get("/presale-passes/<pid>")
def get_pass(pid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor", "Volunteer", "Cashier")
    p = get_or_404("passes", pid, "ERR_PASS_NOT_FOUND", "Presale pass")
    _pass_ownership(role, uid, p)
    return ok(serialize_pass(p))


@app.post("/presale-passes/<pid>/revoke")
def revoke_pass(pid):
    uid, role = auth()
    require(role, "EventOrganizer")
    p = get_or_404("passes", pid, "ERR_PASS_NOT_FOUND", "Presale pass")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PASS_NOT_ACTIVE", 409, "Presale pass is not ACTIVE.")
    p["status"] = "REVOKED"
    touch(p)
    return ok(serialize_pass(p))


# ===========================================================================
# POS transactions and lines
# ===========================================================================


@app.post("/pos-transactions")
def create_transaction():
    uid, role = auth()
    require(role, "Cashier")
    b = body()
    ev = _event_or_404(b.get("sale_event_id"))
    pass_id = b.get("presale_pass_id")
    p = None
    if pass_id is not None:
        p = get_or_404("passes", pass_id, "ERR_PASS_NOT_FOUND", "Presale pass")
    _phase_gate(ev, ("PRESALE_DAY", "SALE_ACTIVE"))
    if p is not None and p["status"] != "ACTIVE":
        raise ApiError("ERR_PASS_NOT_ACTIVE", 409, "Presale pass is not ACTIVE.")
    if ev["phase"] == "PRESALE_DAY" and p is None:
        raise ApiError("ERR_PRESALE_PASS_REQUIRED", 403,
                       "A valid ACTIVE presale pass is required during PRESALE_DAY.")
    rec = {
        "sale_event_id": ev["id"],
        "cashier_id": uid,
        "presale_pass_id": pass_id,
        "pass_discount_pct": p["discount_pct"] if p is not None else 0,
        "status": "OPEN",
        "tendered_cents": None,
        "change_cents": None,
    }
    stamp(rec)
    store.transactions[rec["id"]] = rec
    return ok(serialize_txn(rec), 201)


@app.get("/pos-transactions")
def list_transactions():
    uid, role = auth()
    require(role, "EventOrganizer", "Cashier")
    recs = apply_filters(store.transactions.values(),
                         {"sale_event_id": "sale_event_id",
                          "presale_pass_id": "presale_pass_id", "status": "status"})
    return ok_list([serialize_txn(t) for t in by_created(recs)])


@app.get("/pos-transactions/<tid>")
def get_transaction(tid):
    uid, role = auth()
    require(role, "EventOrganizer", "Cashier")
    return ok(serialize_txn(get_or_404("transactions", tid,
                                       "ERR_TRANSACTION_NOT_FOUND", "Transaction")))


@app.post("/pos-transactions/<tid>/lines")
def scan_line(tid):
    uid, role = auth()
    require(role, "Cashier")
    txn = get_or_404("transactions", tid, "ERR_TRANSACTION_NOT_FOUND", "Transaction")
    barcode = body().get("barcode")
    item = None
    for i in store.items.values():
        if i["sale_event_id"] == txn["sale_event_id"] and i["barcode"] == barcode:
            item = i
            break
    if item is None:
        raise ApiError("ERR_BARCODE_NOT_FOUND", 404,
                       "Barcode matches no item of the transaction's event.")
    if txn["status"] != "OPEN":
        raise ApiError("ERR_TRANSACTION_NOT_OPEN", 409,
                       "Transaction is not OPEN.")
    if item["status"] != "ON_FLOOR":
        raise ApiError("ERR_ITEM_NOT_ON_FLOOR", 409,
                       "Scanned item is not ON_FLOOR.")
    md_pct = markdown_pct_at(item, store.clock)
    line_price = rhu(item["price_cents"] * (100 - md_pct), 100)
    pass_pct = txn["pass_discount_pct"]
    final_line = rhu(line_price * (100 - pass_pct), 100)
    rec = {
        "transaction_id": txn["id"],
        "item_id": item["id"],
        "barcode": item["barcode"],
        "tag_price_cents": item["price_cents"],
        "markdown_pct_applied": md_pct,
        "line_price_cents": line_price,
        "pass_discount_pct_applied": pass_pct,
        "final_line_cents": final_line,
    }
    stamp_light(rec)
    store.lines[rec["id"]] = rec
    item["status"] = "IN_CART"
    touch(item)
    return ok(serialize_line(rec), 201)


@app.get("/transaction-lines")
def list_lines():
    uid, role = auth()
    require(role, "EventOrganizer", "Cashier")
    recs = apply_filters(store.lines.values(),
                         {"transaction_id": "transaction_id", "item_id": "item_id"})
    return ok_list([serialize_line(l) for l in by_created(recs)])


@app.get("/transaction-lines/<lid>")
def get_line(lid):
    uid, role = auth()
    require(role, "EventOrganizer", "Cashier")
    return ok(serialize_line(get_or_404("lines", lid, "ERR_LINE_NOT_FOUND", "Line")))


@app.delete("/pos-transactions/<tid>/lines/<lid>")
def remove_line(tid, lid):
    uid, role = auth()
    require(role, "Cashier")
    txn = get_or_404("transactions", tid, "ERR_TRANSACTION_NOT_FOUND", "Transaction")
    line = store.lines.get(lid)
    if line is None or line["transaction_id"] != txn["id"]:
        raise ApiError("ERR_LINE_NOT_FOUND", 404, "Line not found: %s" % lid)
    if txn["status"] != "OPEN":
        raise ApiError("ERR_TRANSACTION_NOT_OPEN", 409,
                       "Transaction is not OPEN.")
    data = serialize_line(line)
    item = store.items.get(line["item_id"])
    if item is not None and item["status"] == "IN_CART":
        item["status"] = "ON_FLOOR"
        touch(item)
    del store.lines[lid]
    return ok(data)


@app.post("/pos-transactions/<tid>/checkout")
def checkout(tid):
    uid, role = auth()
    require(role, "Cashier")
    txn = get_or_404("transactions", tid, "ERR_TRANSACTION_NOT_FOUND", "Transaction")
    if txn["status"] != "OPEN":
        raise ApiError("ERR_TRANSACTION_NOT_OPEN", 409,
                       "Transaction is not OPEN.")
    lines = [l for l in store.lines.values() if l["transaction_id"] == txn["id"]]
    if not lines:
        raise ApiError("ERR_EMPTY_TRANSACTION", 409,
                       "Cannot check out a transaction with no lines.")
    total = sum(l["final_line_cents"] for l in lines)
    tendered = body().get("tendered_cents")
    if not isinstance(tendered, int) or isinstance(tendered, bool) or tendered < total:
        raise ApiError("ERR_INSUFFICIENT_TENDER", 402,
                       "tendered_cents is below total_cents.")
    txn["tendered_cents"] = tendered
    txn["change_cents"] = tendered - total
    txn["status"] = "COMPLETED"
    touch(txn)
    for l in lines:
        item = store.items.get(l["item_id"])
        if item is not None and item["status"] == "IN_CART":
            item["status"] = "SOLD"
            touch(item)
    return ok(serialize_txn(txn))


@app.post("/pos-transactions/<tid>/void")
def void_transaction(tid):
    uid, role = auth()
    require(role, "Cashier", "EventOrganizer")
    txn = get_or_404("transactions", tid, "ERR_TRANSACTION_NOT_FOUND", "Transaction")
    if txn["status"] == "COMPLETED" and role == "Cashier":
        forbidden("A cashier may void only OPEN transactions.")
    if txn["status"] == "COMPLETED":
        ev = _event_or_404(txn["sale_event_id"])
        _phase_gate(ev, ("PRESALE_DAY", "SALE_ACTIVE"))
    if txn["status"] == "VOIDED":
        raise ApiError("ERR_TRANSACTION_NOT_OPEN", 409,
                       "Transaction is already VOIDED.")
    if txn["status"] == "OPEN":
        for l in [l for l in store.lines.values() if l["transaction_id"] == txn["id"]]:
            item = store.items.get(l["item_id"])
            if item is not None and item["status"] == "IN_CART":
                item["status"] = "ON_FLOOR"
                touch(item)
            del store.lines[l["id"]]
    else:  # COMPLETED — compensation, lines retained for audit
        for l in [l for l in store.lines.values() if l["transaction_id"] == txn["id"]]:
            item = store.items.get(l["item_id"])
            if item is not None and item["status"] == "SOLD":
                item["status"] = "ON_FLOOR"
                touch(item)
    txn["status"] = "VOIDED"
    touch(txn)
    return ok(serialize_txn(txn))


# ===========================================================================
# Settlements
# ===========================================================================


@app.get("/settlements")
def list_settlements():
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    recs = list(store.settlements.values())
    if role == "Consignor":
        recs = [s for s in recs if s["consignor_id"] == uid]
    recs = apply_filters(recs,
                         {"sale_event_id": "sale_event_id",
                          "consignor_id": "consignor_id", "status": "status"})
    return ok_list([serialize_settlement(s) for s in by_created(recs)])


@app.get("/settlements/<sid>")
def get_settlement(sid):
    uid, role = auth()
    require(role, "EventOrganizer", "Consignor")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    if role == "Consignor" and s["consignor_id"] != uid:
        forbidden("Consignors may only read their own settlements.")
    return ok(serialize_settlement(s))


@app.post("/settlements/<sid>/finalize")
def finalize_settlement(sid):
    uid, role = auth()
    require(role, "EventOrganizer")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    ev = _event_or_404(s["sale_event_id"])
    _phase_gate(ev, ("SETTLEMENT",))
    if s["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_WRONG_STATE", 409,
                       "Only a DRAFT settlement can be finalized.")
    consignor = get_or_404("consignors", s["consignor_id"],
                           "ERR_CONSIGNOR_NOT_FOUND", "Consignor")
    # Persist the last provisional values before freezing.
    g_prov, p_prov = provisional_for_consignor(consignor)
    s["provisional_gross_cents"] = g_prov
    s["provisional_payout_cents"] = p_prov
    gross = 0
    for l in store.lines.values():
        item = store.items.get(l["item_id"])
        if item is None or item["consignor_id"] != consignor["id"]:
            continue
        txn = store.transactions.get(l["transaction_id"])
        if txn is not None and txn["status"] == "COMPLETED":
            gross += l["final_line_cents"]
    result = payout_pipeline(consignor, gross, s["adjustment_cents"])
    s["gross_cents"] = gross
    s["split_pct"] = result["split_pct"]
    s["commission_cents"] = result["commission_cents"]
    s["payout_before_fee_cents"] = result["payout_before_fee_cents"]
    s["supply_fee_cents"] = result["supply_fee_cents"]
    s["rejected_fee_cents"] = result["rejected_fee_cents"]
    s["payout_cents"] = result["payout_cents"]
    s["status"] = "FINALIZED"
    touch(s)
    return ok(serialize_settlement(s))


@app.post("/settlements/<sid>/dispute")
def dispute_settlement(sid):
    uid, role = auth()
    require(role, "Consignor")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    if s["consignor_id"] != uid:
        forbidden("Consignors may only dispute their own settlements.")
    if s["status"] != "FINALIZED":
        raise ApiError("ERR_SETTLEMENT_WRONG_STATE", 409,
                       "Only a FINALIZED settlement can be disputed.")
    s["dispute_reason"] = body().get("reason")
    s["status"] = "DISPUTED"
    touch(s)
    return ok(serialize_settlement(s))


@app.post("/settlements/<sid>/resolve")
def resolve_settlement(sid):
    uid, role = auth()
    require(role, "EventOrganizer")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    if s["status"] != "DISPUTED":
        raise ApiError("ERR_SETTLEMENT_WRONG_STATE", 409,
                       "Only a DISPUTED settlement can be resolved.")
    adjustment = body().get("adjustment_cents", 0)
    if not isinstance(adjustment, int) or isinstance(adjustment, bool):
        adjustment = 0
    s["adjustment_cents"] += adjustment
    # Cycle back to DRAFT; frozen final-variant fields reset to null.
    s["gross_cents"] = None
    s["split_pct"] = None
    s["commission_cents"] = None
    s["payout_before_fee_cents"] = None
    s["supply_fee_cents"] = None
    s["rejected_fee_cents"] = None
    s["payout_cents"] = None
    consignor = store.consignors.get(s["consignor_id"])
    if consignor is not None:
        g_prov, p_prov = provisional_for_consignor(consignor)
        s["provisional_gross_cents"] = g_prov
        s["provisional_payout_cents"] = p_prov
    s["status"] = "DRAFT"
    touch(s)
    return ok(serialize_settlement(s))


@app.post("/settlements/<sid>/mark-paid")
def mark_paid_settlement(sid):
    uid, role = auth()
    require(role, "EventOrganizer")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    if s["status"] != "FINALIZED":
        raise ApiError("ERR_SETTLEMENT_WRONG_STATE", 409,
                       "Only a FINALIZED settlement can be marked paid.")
    if any(i["status"] not in TERMINAL_ITEM_STATUSES
           for i in store.items.values() if i["consignor_id"] == s["consignor_id"]):
        raise ApiError("ERR_ITEMS_NOT_TERMINAL", 409,
                       "Consignor has items not in a terminal status.")
    s["status"] = "PAID"
    touch(s)
    return ok(serialize_settlement(s))


# ===========================================================================
# Test-driving logical clock
# ===========================================================================


@app.post("/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    require(role, "EventOrganizer")
    dt = parse_dt(body().get("to_iso8601"))
    if dt is None:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO8601 UTC instant.")
    store.clock = dt
    return ok({"current_utc": fmt_clock(store.clock)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
