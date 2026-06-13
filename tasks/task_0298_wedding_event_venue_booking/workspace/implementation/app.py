"""Wedding & Event Venue Booking API — Flask entry point.

In-memory store; starts empty on every boot (no seeding). All routes register
here; business logic lives in services.py.
"""
import os

from flask import Flask, request

from db import store, new_id
from errors import ApiError, err
from response import success, list_response, error_response
from serializers import (
    venue_out, space_out, package_out, client_out, coordinator_out, booking_out,
    hold_out, milestone_out, payment_out, vendor_out, guarantee_out,
    walkthrough_out, reschedule_out,
)
import services as svc
from datetime import timedelta

from common import (
    authenticate, require_role, get_body, require_fields, require_string,
    require_enum, require_int, require_number, parse_datetime, parse_date,
    parse_pagination, paginate, stamp_create, touch, clock_now, clock_date,
    dt_to_iso,
)

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed"), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_INVALID_REQUEST", str(e)), 422


# ===========================================================================
# Lookup helpers (existence: priority 4 path / priority 5 body FK)
# ===========================================================================
def get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def ref_or_404(coll, _id, allow_archived=False):
    rec = coll.get(_id)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found")
    if not allow_archived and rec.get("status") == "ARCHIVED":
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource is archived")
    return rec


def sorted_by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


# Ownership (priority 3) -----------------------------------------------------
def check_booking_owner(booking, user_id, role):
    """Client must own the booking; Coordinator must belong to booking's venue."""
    if role == "Client":
        if booking["client_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this booking")
    elif role == "Coordinator":
        coord = store.coordinators.get(user_id)
        if coord is None or coord["venue_id"] != booking["venue_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Coordinator does not belong to this booking's venue")


# ===========================================================================
# §3.1 Venues / inventory
# ===========================================================================
@app.route("/venues", methods=["POST"])
def create_venue():
    _, role = authenticate()
    require_role(role, {"VenueAdmin"})
    body = get_body()
    require_fields(body, ["name"])
    name = require_string(body, "name", 1, 120)

    timezone_v = body.get("timezone", "America/New_York")
    if "timezone" in body and not isinstance(timezone_v, str):
        raise err("ERR_INVALID_REQUEST", "timezone must be a string")
    tier = body.get("cancellation_tier", "STANDARD")
    if tier not in ("STANDARD", "STRICT", "FLEXIBLE"):
        raise err("ERR_INVALID_REQUEST", "cancellation_tier invalid")
    fm = body.get("force_majeure_fee_pct", 0.0)
    if "force_majeure_fee_pct" in body:
        fm = require_number(body, "force_majeure_fee_pct", 0.0, 0.25)

    v = {
        "id": new_id(), "name": name, "timezone": timezone_v,
        "cancellation_tier": tier, "force_majeure_fee_pct": fm, "status": "ACTIVE",
    }
    stamp_create(v)
    store.venues[v["id"]] = v
    return success(venue_out(v), status=201)


@app.route("/venues/<vid>", methods=["GET"])
def get_venue(vid):
    authenticate()
    v = get_or_404(store.venues, vid)
    return success(venue_out(v))


@app.route("/venues/<vid>/archive", methods=["POST"])
def archive_venue(vid):
    _, role = authenticate()
    require_role(role, {"VenueAdmin"})
    v = get_or_404(store.venues, vid)
    v["status"] = "ARCHIVED"
    touch(v)
    return success(venue_out(v))


@app.route("/venues/<vid>/spaces", methods=["POST"])
def create_space(vid):
    _, role = authenticate()
    require_role(role, {"VenueAdmin"})
    v = get_or_404(store.venues, vid)
    body = get_body()
    require_fields(body, ["name", "space_kind", "max_capacity", "base_rental_cents"])
    name = require_string(body, "name", 1, 120)
    kind = require_enum(body, "space_kind", {"CEREMONY", "RECEPTION", "DUAL"})
    cap = require_int(body, "max_capacity", 1)
    rental = require_int(body, "base_rental_cents", 0)
    buf = 0
    if "turnover_buffer_minutes" in body and body["turnover_buffer_minutes"] is not None:
        buf = require_int(body, "turnover_buffer_minutes", 0)

    s = {
        "id": new_id(), "venue_id": v["id"], "name": name, "space_kind": kind,
        "max_capacity": cap, "base_rental_cents": rental,
        "turnover_buffer_minutes": buf, "status": "ACTIVE",
    }
    stamp_create(s)
    store.spaces[s["id"]] = s
    return success(space_out(s), status=201)


@app.route("/venues/<vid>/spaces", methods=["GET"])
def list_spaces(vid):
    authenticate()
    get_or_404(store.venues, vid)
    limit, offset = parse_pagination()
    items = sorted_by_created([s for s in store.spaces.values() if s["venue_id"] == vid])
    page, total = paginate(items, limit, offset)
    return list_response([space_out(s) for s in page], limit, offset, total)


@app.route("/venues/<vid>/packages", methods=["POST"])
def create_package(vid):
    _, role = authenticate()
    require_role(role, {"VenueAdmin"})
    v = get_or_404(store.venues, vid)
    body = get_body()
    require_fields(body, ["tier", "per_head_cents", "fb_minimum_cents"])
    tier = require_enum(body, "tier", {"SILVER", "GOLD", "PLATINUM"})
    per_head = require_int(body, "per_head_cents", 0)
    fb_min = require_int(body, "fb_minimum_cents", 0)
    svc_pct = 0.22
    if "service_charge_pct" in body and body["service_charge_pct"] is not None:
        svc_pct = require_number(body, "service_charge_pct", 0.0, 0.50)
    tax_pct = 0.08
    if "tax_pct" in body and body["tax_pct"] is not None:
        tax_pct = require_number(body, "tax_pct", 0.0, 0.30)

    p = {
        "id": new_id(), "venue_id": v["id"], "tier": tier,
        "per_head_cents": per_head, "fb_minimum_cents": fb_min,
        "service_charge_pct": svc_pct, "tax_pct": tax_pct, "status": "ACTIVE",
    }
    stamp_create(p)
    store.packages[p["id"]] = p
    return success(package_out(p), status=201)


@app.route("/venues/<vid>/packages", methods=["GET"])
def list_packages(vid):
    authenticate()
    get_or_404(store.venues, vid)
    limit, offset = parse_pagination()
    items = sorted_by_created([p for p in store.packages.values() if p["venue_id"] == vid])
    page, total = paginate(items, limit, offset)
    return list_response([package_out(p) for p in page], limit, offset, total)


@app.route("/venues/<vid>/coordinators", methods=["POST"])
def create_coordinator(vid):
    _, role = authenticate()
    require_role(role, {"VenueAdmin"})
    v = get_or_404(store.venues, vid)
    body = get_body()
    require_fields(body, ["full_name"])
    full_name = require_string(body, "full_name", 1, 120)
    cap = 8
    if "active_booking_cap" in body and body["active_booking_cap"] is not None:
        cap = require_int(body, "active_booking_cap", 1)

    c = {
        "id": new_id(), "venue_id": v["id"], "full_name": full_name,
        "active_booking_cap": cap, "assigned_active_count": 0,
    }
    stamp_create(c)
    store.coordinators[c["id"]] = c
    return success(coordinator_out(c), status=201)


@app.route("/venues/<vid>/coordinators", methods=["GET"])
def list_coordinators(vid):
    authenticate()
    get_or_404(store.venues, vid)
    limit, offset = parse_pagination()
    items = sorted_by_created([c for c in store.coordinators.values() if c["venue_id"] == vid])
    page, total = paginate(items, limit, offset)
    return list_response([coordinator_out(c) for c in page], limit, offset, total)


@app.route("/coordinators/<cid>", methods=["GET"])
def get_coordinator(cid):
    _, role = authenticate()
    require_role(role, {"VenueAdmin", "Coordinator", "FinanceOfficer"})
    c = get_or_404(store.coordinators, cid)
    c["assigned_active_count"] = svc.coordinator_active_count(cid)
    return success(coordinator_out(c))


# ===========================================================================
# §3.1 Clients
# ===========================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    _, role = authenticate()
    require_role(role, {"VenueAdmin", "Client"})
    body = get_body()
    require_fields(body, ["full_name", "email"])
    full_name = require_string(body, "full_name", 1, 120)
    email = require_string(body, "email", 1)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise err("ERR_INVALID_REQUEST", "email is not a valid address")
    for existing in store.clients.values():
        if existing["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already registered")

    c = {"id": new_id(), "full_name": full_name, "email": email}
    stamp_create(c)
    store.clients[c["id"]] = c
    return success(client_out(c), status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = authenticate()
    require_role(role, {"VenueAdmin", "Client", "Coordinator"})
    c = get_or_404(store.clients, cid)
    return success(client_out(c))


# ===========================================================================
# §3.2 Bookings
# ===========================================================================
def _validate_block_window(cs, ce, rs, re_):
    if not (cs < ce <= rs < re_):
        raise err("ERR_INVALID_TIME_WINDOW", "Block times out of order")


@app.route("/bookings", methods=["POST"])
def create_booking():
    user_id, role = authenticate()
    require_role(role, {"Client", "Coordinator"})
    body = get_body()
    require_fields(body, [
        "client_id", "venue_id", "package_id", "event_date",
        "ceremony_start", "ceremony_end", "reception_start", "reception_end",
        "expected_guest_count",
    ])

    # priority 5: body FK existence (non-archived)
    client = ref_or_404(store.clients, body["client_id"], allow_archived=True)
    venue = ref_or_404(store.venues, body["venue_id"])
    package = ref_or_404(store.packages, body["package_id"])
    if package["venue_id"] != venue["id"]:
        raise err("ERR_REFERENCE_NOT_FOUND", "package does not belong to venue")

    # ownership: a Client may only create their own booking
    if role == "Client" and body["client_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Client may only create their own booking")

    # priority 6: shape
    expected_guests = require_int(body, "expected_guest_count", 1)
    event_date = parse_date(body["event_date"], "event_date")
    cs = parse_datetime(body["ceremony_start"], "ceremony_start")
    ce = parse_datetime(body["ceremony_end"], "ceremony_end")
    rs = parse_datetime(body["reception_start"], "reception_start")
    re_ = parse_datetime(body["reception_end"], "reception_end")

    # priority 7: time window + future event_date
    _validate_block_window(cs, ce, rs, re_)
    if event_date <= clock_date():
        raise err("ERR_INVALID_TIME_WINDOW", "event_date must be strictly in the future")

    b = {
        "id": new_id(), "client_id": client["id"], "venue_id": venue["id"],
        "package_id": package["id"], "coordinator_id": None,
        "event_date": body["event_date"],
        "ceremony_start": body["ceremony_start"], "ceremony_end": body["ceremony_end"],
        "reception_start": body["reception_start"], "reception_end": body["reception_end"],
        "expected_guest_count": expected_guests,
        "booking_status": "INQUIRY", "payment_status": "UNPAID",
        "hold_expires_at": None, "amount_paid_cents": 0,
        "event_charge_cents": 0, "balance_due_cents": 0, "cancelled_reason": None,
    }
    stamp_create(b)
    store.bookings[b["id"]] = b
    return success(booking_out(b), status=201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    authenticate()
    b = get_or_404(store.bookings, bid)
    return success(booking_out(b))


@app.route("/bookings", methods=["GET"])
def list_bookings():
    _, role = authenticate()
    require_role(role, {"VenueAdmin", "Coordinator", "FinanceOfficer"})
    limit, offset = parse_pagination()
    items = list(store.bookings.values())
    for key in ("client_id", "venue_id", "package_id", "coordinator_id", "booking_status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b[key] == val]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([booking_out(b) for b in page], limit, offset, total)


@app.route("/bookings/<bid>/assign-coordinator", methods=["POST"])
def assign_coordinator(bid):
    user_id, role = authenticate()
    require_role(role, {"VenueAdmin", "Coordinator"})
    b = get_or_404(store.bookings, bid)
    if role == "Coordinator":
        check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, ["coordinator_id"])
    coord = ref_or_404(store.coordinators, body["coordinator_id"], allow_archived=True)
    if coord["venue_id"] != b["venue_id"]:
        raise err("ERR_REFERENCE_NOT_FOUND", "coordinator does not belong to booking's venue")

    # capacity check (priority 14): would this push above active_booking_cap?
    if b["coordinator_id"] != coord["id"]:
        prospective = svc.coordinator_active_count(coord["id"])
        if b["booking_status"] not in svc.BOOKING_TERMINAL:
            prospective += 1
        if prospective > coord["active_booking_cap"]:
            raise err("ERR_COORDINATOR_AT_CAPACITY", "coordinator at capacity")

    old_coord = b["coordinator_id"]
    b["coordinator_id"] = coord["id"]
    touch(b)
    svc.refresh_coordinator_count(coord["id"])
    if old_coord and old_coord != coord["id"]:
        svc.refresh_coordinator_count(old_coord)
    return success(booking_out(b))


# ===========================================================================
# §3.3 Space holds
# ===========================================================================
@app.route("/bookings/<bid>/holds", methods=["POST"])
def create_hold(bid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, ["space_id", "block_role", "expected_booking_version"])
    # body FK existence (priority 5)
    space = ref_or_404(store.spaces, body["space_id"])
    block_role = require_enum(body, "block_role", {"CEREMONY", "RECEPTION"})
    expected_v = require_int(body, "expected_booking_version", 0)

    # priority 9: OCC
    if expected_v != b["version"]:
        raise err("ERR_STALE_BOOKING_VERSION", "expected_booking_version mismatch")

    # priority 11: space-kind compatibility
    if block_role == "CEREMONY" and space["space_kind"] not in ("CEREMONY", "DUAL"):
        raise err("ERR_SPACE_KIND_MISMATCH", "block_role incompatible with space_kind")
    if block_role == "RECEPTION" and space["space_kind"] not in ("RECEPTION", "DUAL"):
        raise err("ERR_SPACE_KIND_MISMATCH", "block_role incompatible with space_kind")

    # copy occupation times from the matching block
    if block_role == "CEREMONY":
        occ_start, occ_end = b["ceremony_start"], b["ceremony_end"]
    else:
        occ_start, occ_end = b["reception_start"], b["reception_end"]

    # priority 12: space-date overlap (with turnover buffer), against OTHER bookings
    if svc.space_conflict(
        space["id"],
        parse_datetime(occ_start, "occupy_start"),
        parse_datetime(occ_end, "occupy_end"),
        exclude_booking_id=b["id"],
    ):
        raise err("ERR_SPACE_DOUBLE_BOOKED", "space double-booked")

    h = {
        "id": new_id(), "booking_id": b["id"], "space_id": space["id"],
        "block_role": block_role, "occupy_start": occ_start, "occupy_end": occ_end,
        "hold_status": "HELD",
    }
    stamp_create(h)
    store.space_holds[h["id"]] = h
    touch(b)  # hold creation bumps the booking version
    return success(hold_out(h), status=201)


@app.route("/bookings/<bid>/holds", methods=["GET"])
def list_booking_holds(bid):
    authenticate()
    get_or_404(store.bookings, bid)
    limit, offset = parse_pagination()
    items = sorted_by_created([h for h in store.space_holds.values() if h["booking_id"] == bid])
    page, total = paginate(items, limit, offset)
    return list_response([hold_out(h) for h in page], limit, offset, total)


@app.route("/holds", methods=["GET"])
def list_holds():
    _, role = authenticate()
    require_role(role, {"VenueAdmin", "Coordinator", "FinanceOfficer"})
    limit, offset = parse_pagination()
    items = list(store.space_holds.values())
    for key in ("space_id", "booking_id", "hold_status"):
        val = request.args.get(key)
        if val is not None:
            items = [h for h in items if h[key] == val]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([hold_out(h) for h in page], limit, offset, total)


@app.route("/holds/<hid>", methods=["GET"])
def get_hold(hid):
    authenticate()
    h = get_or_404(store.space_holds, hid)
    return success(hold_out(h))


@app.route("/bookings/<bid>/holds/<hold_id>", methods=["DELETE"])
def release_hold(bid, hold_id):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    b = get_or_404(store.bookings, bid)  # path validated left-to-right
    h = get_or_404(store.space_holds, hold_id)
    if h["booking_id"] != bid:
        raise err("ERR_NOT_FOUND", "hold not found under this booking")
    check_booking_owner(b, user_id, role)
    if h["hold_status"] != "HELD":
        raise err("ERR_INVALID_STATE", "only a HELD hold may be released")
    h["hold_status"] = "RELEASED"
    touch(h)
    return success(hold_out(h))


# ===========================================================================
# §3.3 / §3.4 / §3.7 / §3.9 Booking lifecycle transitions
# ===========================================================================
@app.route("/bookings/<bid>/place-hold", methods=["POST"])
def place_hold(bid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)

    if b["booking_status"] != "INQUIRY":
        raise err("ERR_INVALID_STATE", "place-hold requires INQUIRY")
    venue = store.venues[b["venue_id"]]
    package = store.packages[b["package_id"]]
    if venue["status"] != "ACTIVE" or package["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "venue and package must be ACTIVE")

    holds = [h for h in store.space_holds.values()
             if h["booking_id"] == bid and h["hold_status"] == "HELD"]
    has_ceremony = any(h["block_role"] == "CEREMONY" for h in holds)
    has_reception = any(h["block_role"] == "RECEPTION" for h in holds)
    if not (has_ceremony and has_reception):
        raise err("ERR_INVALID_STATE", "both CEREMONY and RECEPTION holds required")

    b["booking_status"] = "HELD"
    b["hold_expires_at"] = dt_to_iso(clock_now() + timedelta(hours=svc.HOLD_DURATION_HOURS))
    touch(b)
    return success(booking_out(b))


@app.route("/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)

    # priority 8: state
    if b["booking_status"] != "HELD":
        raise err("ERR_INVALID_STATE", "confirm requires HELD")
    if b["coordinator_id"] is None:
        raise err("ERR_INVALID_STATE", "a coordinator must be assigned")
    if b["hold_expires_at"] is not None:
        if clock_now() >= parse_datetime(b["hold_expires_at"], "hold_expires_at"):
            raise err("ERR_INVALID_STATE", "soft hold has lapsed")

    # priority 17: deposit settled
    if b["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise err("ERR_DEPOSIT_NOT_SETTLED", "deposit milestone not settled")

    # cascade: commit holds
    for h in store.space_holds.values():
        if h["booking_id"] == bid and h["hold_status"] == "HELD":
            h["hold_status"] = "COMMITTED"
            touch(h)
    b["hold_expires_at"] = None
    b["booking_status"] = "CONFIRMED"
    b["event_charge_cents"] = svc.provisional_event_charge(b)
    svc.build_milestones(b)
    touch(b)
    svc.settle_and_status(b)
    return success(booking_out(b))


@app.route("/bookings/<bid>/guarantee", methods=["POST"])
def guarantee_booking(bid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, ["guaranteed_count"])
    guaranteed_count = require_int(body, "guaranteed_count", 1)

    # priority 8: state
    if b["booking_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "guarantee requires CONFIRMED")

    # priority 10: capacity (reception space seated max)
    _check_capacity(b, guaranteed_count)

    # priority 15: vendor COI
    for v in store.vendors.values():
        if v["booking_id"] == bid and v["coi_required"] and v["vendor_status"] != "CLEARED":
            raise err("ERR_VENDOR_COI_MISSING", "required-COI vendor not cleared")

    # priority 16: guarantee deadline
    deadline = svc.guarantee_deadline_for(b["event_date"])
    if clock_date().isoformat() > deadline:
        raise err("ERR_GUARANTEE_DEADLINE_PASSED", "guarantee deadline passed")

    # precondition: no DEPOSIT milestone may still be OPEN
    for m in store.milestones.values():
        if m["booking_id"] == bid and m["kind"] == "DEPOSIT" and m["milestone_status"] == "OPEN":
            raise err("ERR_DEPOSIT_NOT_SETTLED", "deposit milestone still open")

    # create guarantee + switch to final charge
    g = {
        "id": new_id(), "booking_id": bid, "guaranteed_count": guaranteed_count,
        "guarantee_deadline": deadline, "locked_at": svc.now_iso(),
    }
    stamp_create(g)
    store.guarantees[g["id"]] = g

    b["event_charge_cents"] = svc.final_event_charge(b, guaranteed_count)
    b["booking_status"] = "GUARANTEED"
    svc.recompute_milestone_amounts(b)
    touch(b)
    svc.settle_and_status(b)
    return success(booking_out(b))


@app.route("/bookings/<bid>/guarantee", methods=["GET"])
def get_guarantee(bid):
    authenticate()
    get_or_404(store.bookings, bid)
    items = sorted_by_created([g for g in store.guarantees.values() if g["booking_id"] == bid])
    return success([guarantee_out(g) for g in items], response_type="array")


@app.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)

    if b["booking_status"] != "GUARANTEED":
        raise err("ERR_INVALID_STATE", "complete requires GUARANTEED")
    if clock_date() <= parse_date(b["event_date"], "event_date"):
        raise err("ERR_INVALID_STATE", "event has not yet occurred")
    if b["payment_status"] != "PAID_IN_FULL":
        raise err("ERR_BALANCE_OUTSTANDING", "outstanding balance at completion")

    # cascade: cancel scheduled walkthroughs
    for w in store.walkthroughs.values():
        if w["booking_id"] == bid and w["walkthrough_status"] == "SCHEDULED":
            w["walkthrough_status"] = "CANCELLED"
            touch(w)
    b["booking_status"] = "COMPLETED"
    touch(b)
    svc.refresh_coordinator_count(b["coordinator_id"])
    return success(booking_out(b))


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, role = authenticate()
    require_role(role, {"Client", "Coordinator"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)

    status = b["booking_status"]
    if status not in ("INQUIRY", "HELD", "CONFIRMED", "GUARANTEED"):
        raise err("ERR_INVALID_STATE", "booking not in a cancellable state")

    if status == "INQUIRY":
        b["cancelled_reason"] = "CLIENT_CANCEL"
        b["booking_status"] = "CANCELLED"
        touch(b)
        svc.refresh_coordinator_count(b["coordinator_id"])
        return success(booking_out(b))

    if status == "HELD":
        for h in store.space_holds.values():
            if h["booking_id"] == bid and h["hold_status"] == "HELD":
                h["hold_status"] = "RELEASED"
                touch(h)
        b["cancelled_reason"] = "CLIENT_CANCEL"
        b["hold_expires_at"] = None
        b["booking_status"] = "CANCELLED"
        touch(b)
        svc.refresh_coordinator_count(b["coordinator_id"])
        return success(booking_out(b))

    # CONFIRMED or GUARANTEED: release holds, waive milestones, refund.
    for h in store.space_holds.values():
        if h["booking_id"] == bid and h["hold_status"] in ("HELD", "COMMITTED"):
            h["hold_status"] = "RELEASED"
            touch(h)
    # Waive every milestone that is not already WAIVED (the booking is being
    # cancelled, so none of the schedule remains collectible).
    for m in store.milestones.values():
        if m["booking_id"] == bid and m["milestone_status"] != "WAIVED":
            m["milestone_status"] = "WAIVED"
            m["amount_allocated_cents"] = 0
            touch(m)

    refund = svc.cancellation_refund_amount(b, status)
    b["cancelled_reason"] = "CLIENT_CANCEL"
    b["booking_status"] = "CANCELLED"
    touch(b)
    if refund > 0:
        svc.post_outbound_payment(b, refund)
    # All milestones are WAIVED now; do not re-run the waterfall. Just reconcile
    # the derived money fields and the payment_status axis.
    svc.recompute_money(b)
    svc.recompute_payment_status(b)
    svc.refresh_coordinator_count(b["coordinator_id"])
    return success(booking_out(b))


@app.route("/bookings/<bid>/expire-hold", methods=["POST"])
def expire_hold(bid):
    user_id, role = authenticate()
    require_role(role, {"VenueAdmin", "Coordinator"})
    b = get_or_404(store.bookings, bid)
    if role == "Coordinator":
        check_booking_owner(b, user_id, role)

    if b["booking_status"] != "HELD":
        raise err("ERR_INVALID_STATE", "expire-hold requires HELD")

    # sweep makes no change if the hold has not yet lapsed
    if b["hold_expires_at"] is None or clock_now() < parse_datetime(b["hold_expires_at"], "hold_expires_at"):
        return success(booking_out(b))

    for h in store.space_holds.values():
        if h["booking_id"] == bid and h["hold_status"] == "HELD":
            h["hold_status"] = "RELEASED"
            touch(h)
    b["cancelled_reason"] = "NONPAYMENT"
    b["hold_expires_at"] = None
    b["booking_status"] = "CANCELLED"
    touch(b)
    svc.refresh_coordinator_count(b["coordinator_id"])
    return success(booking_out(b))


def _check_capacity(booking, count):
    """Guest count must not exceed the seated max_capacity of the reception space."""
    reception_space = None
    for h in store.space_holds.values():
        if h["booking_id"] == booking["id"] and h["block_role"] == "RECEPTION" \
                and h["hold_status"] in ("HELD", "COMMITTED"):
            reception_space = store.spaces.get(h["space_id"])
            break
    if reception_space is not None and count > reception_space["max_capacity"]:
        raise err("ERR_CAPACITY_EXCEEDED", "guest count exceeds reception capacity")


# ===========================================================================
# §3.5 Payments & milestones
# ===========================================================================
@app.route("/bookings/<bid>/milestones", methods=["GET"])
def list_milestones(bid):
    authenticate()
    get_or_404(store.bookings, bid)
    limit, offset = parse_pagination()
    items = sorted_by_created([m for m in store.milestones.values() if m["booking_id"] == bid])
    page, total = paginate(items, limit, offset)
    return list_response([milestone_out(m) for m in page], limit, offset, total)


@app.route("/bookings/<bid>/payments", methods=["POST"])
def post_payment(bid):
    _, role = authenticate()
    require_role(role, {"FinanceOfficer"})
    b = get_or_404(store.bookings, bid)
    body = get_body()
    require_fields(body, ["direction", "amount_cents", "method"])
    direction = require_enum(body, "direction", {"INBOUND", "OUTBOUND"})
    amount = require_int(body, "amount_cents", 1)
    method = require_enum(body, "method", {"CARD", "ACH", "CHECK", "WIRE"})

    # priority 19: INBOUND may not exceed current balance_due_cents.
    # The contracted ceiling only exists once event_charge_cents is set (at confirm);
    # before that the deposit is paid against a not-yet-computed charge, so the
    # overpayment ceiling does not bind.
    if direction == "INBOUND":
        svc.recompute_money(b)
        if b["event_charge_cents"] > 0 and amount > b["balance_due_cents"]:
            raise err("ERR_OVERPAYMENT", "payment exceeds balance due")

    p = {
        "id": new_id(), "booking_id": bid, "direction": direction,
        "amount_cents": amount, "method": method, "status": "POSTED",
        "posted_at": svc.now_iso(),
    }
    p["created_at"] = svc.now_iso()
    p["_seq"] = store.next_seq()
    store.payments[p["id"]] = p

    svc.settle_and_status(b)
    return success(payment_out(p), status=201)


@app.route("/bookings/<bid>/payments", methods=["GET"])
def list_payments(bid):
    authenticate()
    get_or_404(store.bookings, bid)
    limit, offset = parse_pagination()
    items = sorted_by_created([p for p in store.payments.values() if p["booking_id"] == bid])
    page, total = paginate(items, limit, offset)
    return list_response([payment_out(p) for p in page], limit, offset, total)


# ===========================================================================
# §3.6 Vendors & COI
# ===========================================================================
def _coi_required_for(vendor_role, venue):
    """Whether a COI is required for this vendor_role at this venue.
    Default policy: required for all roles (scaffold default true)."""
    return True


@app.route("/bookings/<bid>/vendors", methods=["POST"])
def add_vendor(bid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator", "Client"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, ["company_name", "vendor_role"])
    company = require_string(body, "company_name", 1, 120)
    vendor_role = require_enum(
        body, "vendor_role",
        {"CATERING", "FLORAL", "PHOTOGRAPHY", "MUSIC", "RENTAL", "OTHER"},
    )
    venue = store.venues[b["venue_id"]]
    v = {
        "id": new_id(), "booking_id": bid, "company_name": company,
        "vendor_role": vendor_role, "coi_required": _coi_required_for(vendor_role, venue),
        "coi_on_file": False, "coi_expires_on": None, "vendor_status": "PENDING",
    }
    stamp_create(v)
    store.vendors[v["id"]] = v
    return success(vendor_out(v), status=201)


@app.route("/bookings/<bid>/vendors", methods=["GET"])
def list_vendors(bid):
    authenticate()
    get_or_404(store.bookings, bid)
    limit, offset = parse_pagination()
    items = sorted_by_created([v for v in store.vendors.values() if v["booking_id"] == bid])
    page, total = paginate(items, limit, offset)
    return list_response([vendor_out(v) for v in page], limit, offset, total)


@app.route("/vendors/<vid>/coi", methods=["POST"])
def upload_coi(vid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    v = get_or_404(store.vendors, vid)
    b = store.bookings[v["booking_id"]]
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, ["coi_expires_on"])
    expires = parse_date(body["coi_expires_on"], "coi_expires_on")
    event_date = parse_date(b["event_date"], "event_date")

    if v["vendor_status"] == "REJECTED":
        raise err("ERR_INVALID_STATE", "cannot upload COI for a rejected vendor")

    if expires < event_date:
        # an upload that expires before the event:
        #  - from PENDING is rejected outright
        #  - from CLEARED bounces back to PENDING
        if v["vendor_status"] == "CLEARED":
            v["coi_on_file"] = False
            v["coi_expires_on"] = body["coi_expires_on"]
            v["vendor_status"] = "PENDING"
            touch(v)
            return success(vendor_out(v))
        raise err("ERR_COI_EXPIRES_BEFORE_EVENT", "COI expires before event date")

    # valid COI -> CLEARED
    v["coi_on_file"] = True
    v["coi_expires_on"] = body["coi_expires_on"]
    v["vendor_status"] = "CLEARED"
    touch(v)
    return success(vendor_out(v))


@app.route("/vendors/<vid>/reject", methods=["POST"])
def reject_vendor(vid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    v = get_or_404(store.vendors, vid)
    b = store.bookings[v["booking_id"]]
    check_booking_owner(b, user_id, role)
    if v["vendor_status"] not in ("PENDING", "CLEARED"):
        raise err("ERR_INVALID_STATE", "vendor not in a rejectable state")
    v["vendor_status"] = "REJECTED"
    touch(v)
    return success(vendor_out(v))


# ===========================================================================
# §3.8 Walkthroughs
# ===========================================================================
@app.route("/bookings/<bid>/walkthroughs", methods=["POST"])
def schedule_walkthrough(bid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, ["scheduled_start", "scheduled_end"])
    start = parse_datetime(body["scheduled_start"], "scheduled_start")
    end = parse_datetime(body["scheduled_end"], "scheduled_end")

    # priority 7: time window ordering
    if not (start < end):
        raise err("ERR_INVALID_TIME_WINDOW", "scheduled_end must be after scheduled_start")

    # priority 21: must be strictly before event_date
    event_date = parse_date(b["event_date"], "event_date")
    if start.date() >= event_date:
        raise err("ERR_WALKTHROUGH_AFTER_EVENT", "walkthrough must be before event_date")

    # priority 13: no overlap with another SCHEDULED walkthrough on the same coordinator
    coord_id = b["coordinator_id"]
    if coord_id is not None:
        for w in store.walkthroughs.values():
            if w["walkthrough_status"] != "SCHEDULED":
                continue
            ob = store.bookings.get(w["booking_id"])
            if ob is None or ob["coordinator_id"] != coord_id:
                continue
            ws = parse_datetime(w["scheduled_start"], "scheduled_start")
            we = parse_datetime(w["scheduled_end"], "scheduled_end")
            # plain half-open overlap, no buffer (adjacent allowed)
            if start < we and ws < end:
                raise err("ERR_WALKTHROUGH_CONFLICT", "walkthrough overlaps another on this coordinator")

    w = {
        "id": new_id(), "booking_id": bid,
        "scheduled_start": body["scheduled_start"], "scheduled_end": body["scheduled_end"],
        "walkthrough_status": "SCHEDULED",
    }
    stamp_create(w)
    store.walkthroughs[w["id"]] = w
    return success(walkthrough_out(w), status=201)


@app.route("/bookings/<bid>/walkthroughs", methods=["GET"])
def list_walkthroughs(bid):
    authenticate()
    get_or_404(store.bookings, bid)
    limit, offset = parse_pagination()
    items = sorted_by_created([w for w in store.walkthroughs.values() if w["booking_id"] == bid])
    page, total = paginate(items, limit, offset)
    return list_response([walkthrough_out(w) for w in page], limit, offset, total)


# ===========================================================================
# §3.10 Reschedule requests
# ===========================================================================
@app.route("/bookings/<bid>/reschedule-requests", methods=["POST"])
def propose_reschedule(bid):
    user_id, role = authenticate()
    require_role(role, {"Client"})
    b = get_or_404(store.bookings, bid)
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, [
        "reason_kind", "proposed_event_date", "proposed_ceremony_start",
        "proposed_ceremony_end", "proposed_reception_start", "proposed_reception_end",
    ])
    reason = require_enum(body, "reason_kind", {"CLIENT_REQUEST", "FORCE_MAJEURE"})
    parse_date(body["proposed_event_date"], "proposed_event_date")
    cs = parse_datetime(body["proposed_ceremony_start"], "proposed_ceremony_start")
    ce = parse_datetime(body["proposed_ceremony_end"], "proposed_ceremony_end")
    rs = parse_datetime(body["proposed_reception_start"], "proposed_reception_start")
    re_ = parse_datetime(body["proposed_reception_end"], "proposed_reception_end")

    supersedes = body.get("supersedes_request_id")
    superseded_req = None
    if supersedes is not None:
        superseded_req = store.reschedule_requests.get(supersedes)
        if superseded_req is None or superseded_req["booking_id"] != bid:
            raise err("ERR_REFERENCE_NOT_FOUND", "supersedes_request_id not found")

    # priority 7: time window ordering
    _validate_block_window(cs, ce, rs, re_)

    # priority 20: only one active (PROPOSED/COUNTERED) request unless superseding
    active = [
        r for r in store.reschedule_requests.values()
        if r["booking_id"] == bid and r["request_status"] in ("PROPOSED", "COUNTERED")
    ]
    if supersedes is None:
        if active:
            raise err("ERR_RESCHEDULE_IN_PROGRESS", "an active reschedule already exists")
    else:
        # superseding: the superseded request must be COUNTERED
        if superseded_req["request_status"] != "COUNTERED":
            raise err("ERR_INVALID_STATE", "superseded request is not COUNTERED")
        # any other active request besides the superseded one blocks
        others = [r for r in active if r["id"] != supersedes]
        if others:
            raise err("ERR_RESCHEDULE_IN_PROGRESS", "another active reschedule exists")

    r = {
        "id": new_id(), "booking_id": bid, "supersedes_request_id": supersedes,
        "reason_kind": reason,
        "proposed_event_date": body["proposed_event_date"],
        "proposed_ceremony_start": body["proposed_ceremony_start"],
        "proposed_ceremony_end": body["proposed_ceremony_end"],
        "proposed_reception_start": body["proposed_reception_start"],
        "proposed_reception_end": body["proposed_reception_end"],
        "request_status": "PROPOSED",
    }
    stamp_create(r)
    store.reschedule_requests[r["id"]] = r

    if superseded_req is not None:
        superseded_req["request_status"] = "WITHDRAWN"
        touch(superseded_req)

    return success(reschedule_out(r), status=201)


@app.route("/bookings/<bid>/reschedule-requests", methods=["GET"])
def list_booking_reschedules(bid):
    authenticate()
    get_or_404(store.bookings, bid)
    limit, offset = parse_pagination()
    items = [r for r in store.reschedule_requests.values() if r["booking_id"] == bid]
    rs_filter = request.args.get("request_status")
    if rs_filter is not None:
        items = [r for r in items if r["request_status"] == rs_filter]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([reschedule_out(r) for r in page], limit, offset, total)


@app.route("/reschedule-requests", methods=["GET"])
def list_reschedules():
    authenticate()
    limit, offset = parse_pagination()
    items = list(store.reschedule_requests.values())
    for key in ("booking_id", "supersedes_request_id", "request_status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([reschedule_out(r) for r in page], limit, offset, total)


@app.route("/reschedule-requests/<rid>", methods=["GET"])
def get_reschedule(rid):
    authenticate()
    r = get_or_404(store.reschedule_requests, rid)
    return success(reschedule_out(r))


@app.route("/reschedule-requests/<rid>/counter", methods=["POST"])
def counter_reschedule(rid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    r = get_or_404(store.reschedule_requests, rid)
    b = store.bookings[r["booking_id"]]
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, [
        "proposed_event_date", "proposed_ceremony_start", "proposed_ceremony_end",
        "proposed_reception_start", "proposed_reception_end",
    ])
    parse_date(body["proposed_event_date"], "proposed_event_date")
    cs = parse_datetime(body["proposed_ceremony_start"], "proposed_ceremony_start")
    ce = parse_datetime(body["proposed_ceremony_end"], "proposed_ceremony_end")
    rs = parse_datetime(body["proposed_reception_start"], "proposed_reception_start")
    re_ = parse_datetime(body["proposed_reception_end"], "proposed_reception_end")
    _validate_block_window(cs, ce, rs, re_)

    if r["request_status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "counter requires PROPOSED")
    if b["booking_status"] not in ("CONFIRMED", "GUARANTEED"):
        raise err("ERR_INVALID_STATE", "booking must be CONFIRMED or GUARANTEED")

    r["proposed_event_date"] = body["proposed_event_date"]
    r["proposed_ceremony_start"] = body["proposed_ceremony_start"]
    r["proposed_ceremony_end"] = body["proposed_ceremony_end"]
    r["proposed_reception_start"] = body["proposed_reception_start"]
    r["proposed_reception_end"] = body["proposed_reception_end"]
    r["request_status"] = "COUNTERED"
    touch(r)
    return success(reschedule_out(r))


@app.route("/reschedule-requests/<rid>/approve", methods=["POST"])
def approve_reschedule(rid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator", "Client"})
    r = get_or_404(store.reschedule_requests, rid)
    b = store.bookings[r["booking_id"]]
    check_booking_owner(b, user_id, role)
    body = get_body()
    require_fields(body, ["expected_booking_version"])
    expected_v = require_int(body, "expected_booking_version", 0)

    # Coordinator approves PROPOSED; Client approves COUNTERED
    if role == "Coordinator":
        if r["request_status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "coordinator approves a PROPOSED request")
    else:  # Client
        if r["request_status"] != "COUNTERED":
            raise err("ERR_INVALID_STATE", "client approves a COUNTERED request")

    if expected_v != b["version"]:
        raise err("ERR_STALE_BOOKING_VERSION", "expected_booking_version mismatch")

    # no other PROPOSED/COUNTERED request for this booking
    others = [
        x for x in store.reschedule_requests.values()
        if x["booking_id"] == b["id"] and x["id"] != rid
        and x["request_status"] in ("PROPOSED", "COUNTERED")
    ]
    if others:
        raise err("ERR_RESCHEDULE_IN_PROGRESS", "another active reschedule exists")

    new_event_date = r["proposed_event_date"]
    new_cs = r["proposed_ceremony_start"]
    new_ce = r["proposed_ceremony_end"]
    new_rs = r["proposed_reception_start"]
    new_re = r["proposed_reception_end"]

    # capacity re-check against reception space
    eff_count = b["expected_guest_count"]
    g = _booking_guarantee(b["id"])
    if g is not None:
        eff_count = g["guaranteed_count"]
    _check_capacity(b, eff_count)

    # space-date overlap check against the target spaces (excluding this booking's holds)
    committed = [
        h for h in store.space_holds.values()
        if h["booking_id"] == b["id"] and h["hold_status"] == "COMMITTED"
    ]
    for h in committed:
        if h["block_role"] == "CEREMONY":
            os_, oe_ = new_cs, new_ce
        else:
            os_, oe_ = new_rs, new_re
        if svc.space_conflict(
            h["space_id"],
            parse_datetime(os_, "occupy_start"),
            parse_datetime(oe_, "occupy_end"),
            exclude_booking_id=b["id"],
        ):
            raise err("ERR_SPACE_DOUBLE_BOOKED", "space double-booked at new interval")

    # rewrite booking block times
    b["event_date"] = new_event_date
    b["ceremony_start"] = new_cs
    b["ceremony_end"] = new_ce
    b["reception_start"] = new_rs
    b["reception_end"] = new_re

    # re-create committed holds at the new interval
    for h in committed:
        h["hold_status"] = "RELEASED"
        touch(h)
        if h["block_role"] == "CEREMONY":
            os_, oe_ = new_cs, new_ce
        else:
            os_, oe_ = new_rs, new_re
        nh = {
            "id": new_id(), "booking_id": b["id"], "space_id": h["space_id"],
            "block_role": h["block_role"], "occupy_start": os_, "occupy_end": oe_,
            "hold_status": "COMMITTED",
        }
        stamp_create(nh)
        store.space_holds[nh["id"]] = nh

    # re-derive guarantee deadline
    if g is not None:
        g["guarantee_deadline"] = svc.guarantee_deadline_for(new_event_date)
        touch(g)

    # revalidate vendors: COI now before new event_date bounces CLEARED -> PENDING
    new_ed = parse_date(new_event_date, "event_date")
    for v in store.vendors.values():
        if v["booking_id"] != b["id"]:
            continue
        if v["vendor_status"] == "CLEARED" and v["coi_expires_on"] is not None:
            if parse_date(v["coi_expires_on"], "coi_expires_on") < new_ed:
                v["coi_on_file"] = False
                v["vendor_status"] = "PENDING"
                touch(v)

    # FORCE_MAJEURE money handling
    if r["reason_kind"] == "FORCE_MAJEURE":
        venue = store.venues[b["venue_id"]]
        svc.recompute_money(b)
        paid = b["amount_paid_cents"]
        overpayment = paid - b["event_charge_cents"]
        if overpayment > 0:
            svc.post_outbound_payment(b, overpayment)

    r["request_status"] = "APPROVED"
    touch(r)
    touch(b)
    svc.settle_and_status(b)
    return success(reschedule_out(r))


@app.route("/reschedule-requests/<rid>/decline", methods=["POST"])
def decline_reschedule(rid):
    user_id, role = authenticate()
    require_role(role, {"Coordinator"})
    r = get_or_404(store.reschedule_requests, rid)
    b = store.bookings[r["booking_id"]]
    check_booking_owner(b, user_id, role)
    if r["request_status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "decline requires PROPOSED")
    r["request_status"] = "DECLINED"
    touch(r)
    return success(reschedule_out(r))


@app.route("/reschedule-requests/<rid>/withdraw", methods=["POST"])
def withdraw_reschedule(rid):
    user_id, role = authenticate()
    require_role(role, {"Client"})
    r = get_or_404(store.reschedule_requests, rid)
    b = store.bookings[r["booking_id"]]
    check_booking_owner(b, user_id, role)
    if r["request_status"] not in ("PROPOSED", "COUNTERED"):
        raise err("ERR_INVALID_STATE", "withdraw requires PROPOSED or COUNTERED")
    r["request_status"] = "WITHDRAWN"
    touch(r)
    return success(reschedule_out(r))


def _booking_guarantee(booking_id):
    for g in store.guarantees.values():
        if g["booking_id"] == booking_id:
            return g
    return None


# ===========================================================================
# Test-driving clock
# ===========================================================================
@app.route("/_clock/set", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"VenueAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    store.clock = parse_datetime(body["to_iso8601"], "to_iso8601")
    return success({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
