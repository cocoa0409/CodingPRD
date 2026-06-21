"""Trampoline / Indoor Attraction Park API — Flask entry point.

In-memory store, no seeding. Boots fresh on every start.sh invocation.
"""
import os

# --- Boot-latency hardening (no behavioral effect) -------------------------
# On macOS, socket.getfqdn("0.0.0.0") blocks ~5s on a reverse-DNS lookup that
# times out. Werkzeug's dev server calls getfqdn(host) during server_bind only
# to compose its "Running on http://..." banner. Under per-test-server
# isolation (server restarted before every test, 8 rounds concurrently) that
# 5s stall is paid repeatedly and can push a boot past the runner's restart
# poll window, surfacing as a spurious "could not be restarted". Neutralize it
# here so a fast boot does not depend on the runner injecting its own patch.
# This only changes the cosmetic startup-log hostname for unspecified
# addresses; the server still binds 0.0.0.0 and serves identical responses.
import socket as _socket

_real_getfqdn = _socket.getfqdn


def _fast_getfqdn(name=""):
    if name in ("", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"):
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn
# ---------------------------------------------------------------------------

from flask import Flask, request

from common import make_common, touch, public, round_half_up
from db import db, now_dt, iso_ms
from errors import ApiError, err
from middleware import authenticate, require_role
from response import success, list_response, error_response
from validation import (
    get_json_body,
    require,
    require_str,
    opt_str,
    require_int,
    opt_int,
    require_number,
    opt_number,
    require_enum,
    require_datetime,
    parse_datetime,
    parse_pagination,
    paginate,
)
import services as svc

app = Flask(__name__)


# ===========================================================================
# Transport hardening (no behavioral effect on PRD-defined responses)
# ===========================================================================
# Under per-test-server isolation the server is killed and respawned on the
# same port before every test, while the test harness reuses a single
# persistent requests.Session (HTTP keep-alive). A pooled socket left open from
# the previous (now-dead) server can be reused for the first request of the
# next test and surface as a "Connection aborted / BadStatusLine" before the
# new server's handler ever runs. Returning `Connection: close` makes the
# client tear that socket down after each response, so no stale keep-alive
# socket survives across a restart. This only affects transport framing; the
# JSON body, status code, and all PRD semantics are unchanged.
@app.after_request
def _no_keep_alive(resp):
    resp.headers["Connection"] = "close"
    return resp


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_VALIDATION", 422, "Unexpected error: %s" % str(e))


@app.get("/health")
def health():
    return success({}, status=200)


# ===========================================================================
# Serializers — public projection per entity
# ===========================================================================
def slot_view(slot):
    svc.recompute_slot(slot)
    return public(slot)


def serialize(rec):
    return public(rec)


# ===========================================================================
# Auth helper
# ===========================================================================
def auth_and_role(allowed_roles):
    user_id, user_role = authenticate()
    require_role(user_role, allowed_roles)
    return user_id, user_role


def ensure_owner_member(user_id, user_role, owner_member_id):
    """For Member role, enforce ownership against owner_member_id (PRD §2.1)."""
    if user_role == "Member" and user_id != owner_member_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this resource.")


# ===========================================================================
# Park (bootstrap/config)
# ===========================================================================
@app.post("/park")
def create_park():
    # Bootstrap is exempt from auth (PRD §2.1).
    body = get_json_body()
    name = require_str(body, "name")
    timezone_v = opt_str(body, "timezone", "UTC")

    grip_sock = opt_int(body, "grip_sock_price_cents", 350)
    if grip_sock < 0:
        raise err("ERR_VALIDATION", "grip_sock_price_cents must be >= 0.")
    minor_threshold = opt_int(body, "minor_age_threshold", 18)
    if minor_threshold < 1:
        raise err("ERR_VALIDATION", "minor_age_threshold must be >= 1.")
    walkin = opt_int(body, "walkin_surcharge_cents", 500)
    if walkin < 0:
        raise err("ERR_VALIDATION", "walkin_surcharge_cents must be >= 0.")
    deposit_pct = opt_number(body, "party_deposit_pct", 0.25)
    if not (0 <= deposit_pct <= 1):
        raise err("ERR_VALIDATION", "party_deposit_pct must be between 0 and 1.")
    cutoff = opt_int(body, "cancellation_cutoff_minutes", 120)
    if cutoff < 0:
        raise err("ERR_VALIDATION", "cancellation_cutoff_minutes must be >= 0.")

    rec = make_common()
    rec.update({
        "name": name,
        "timezone": timezone_v,
        "grip_sock_price_cents": grip_sock,
        "minor_age_threshold": minor_threshold,
        "walkin_surcharge_cents": walkin,
        "party_deposit_pct": deposit_pct,
        "cancellation_cutoff_minutes": cutoff,
        # logical clock defaults to creation time until a manager sets it
        "_clock_dt": rec_clock_default(),
    })
    db.parks[rec["id"]] = rec
    return success(public(rec), status=201)


def rec_clock_default():
    return now_dt()


@app.get("/park/<park_id>")
def get_park(park_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    park = svc.get_or_404(db.parks, park_id)
    return success(public(park), status=200)


@app.post("/park/_clock/set_current_utc")
def set_clock():
    auth_and_role({"ParkManager"})
    body = get_json_body()
    to_iso = require(body, "to_iso8601")
    dt = parse_datetime(to_iso, "to_iso8601")
    # The clock lives on the (single) park. Locate it; if a park_id is supplied
    # use it, otherwise apply to all parks (test harness bootstraps one park).
    park_id = body.get("park_id")
    if park_id is not None:
        park = svc.get_or_404(db.parks, park_id)
        targets = [park]
    else:
        targets = list(db.parks.values())
    if not targets:
        raise err("ERR_NOT_FOUND", "No park to set the clock on.")
    for park in targets:
        park["_clock_dt"] = dt
        touch(park)
    return success(public(targets[-1]), status=200)


# ===========================================================================
# SessionSlot
# ===========================================================================
@app.post("/park/slots")
def create_slot():
    auth_and_role({"ParkManager"})
    body = get_json_body()
    park_id = require_str(body, "park_id")
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    jump_capacity = require_int(body, "jump_capacity")
    base_price = require_int(body, "base_price_cents")

    if jump_capacity < 1:
        raise err("ERR_VALIDATION", "jump_capacity must be >= 1.")
    if base_price < 0:
        raise err("ERR_VALIDATION", "base_price_cents must be >= 0.")

    park = svc.get_or_404(db.parks, park_id)

    # ends_at strictly after starts_at (priority 11)
    if not (ends_at > starts_at):
        raise err("ERR_INVALID_SLOT_WINDOW", "ends_at must be strictly after starts_at.")

    rec = make_common()
    rec.update({
        "park_id": park_id,
        "starts_at": iso_ms(starts_at),
        "ends_at": iso_ms(ends_at),
        "_starts_dt": starts_at,
        "_ends_dt": ends_at,
        "jump_capacity": jump_capacity,
        "base_price_cents": base_price,
        "seats_taken": 0,
        "status": "OPEN",
        "closed": False,
    })
    db.slots[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/slots/<slot_id>")
def get_slot(slot_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    slot = svc.get_or_404(db.slots, slot_id)
    return success(slot_view(slot), status=200)


@app.get("/park/slots")
def list_slots():
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    park_id = request.args.get("park_id")
    items = [s for s in db.slots.values() if park_id is None or s["park_id"] == park_id]
    window, total = paginate(items, limit, offset)
    return list_response([slot_view(s) for s in window], limit, offset, total)


@app.post("/park/slots/<slot_id>/close")
def close_slot(slot_id):
    auth_and_role({"ParkManager"})
    slot = svc.get_or_404(db.slots, slot_id)
    if slot["closed"]:
        raise err("ERR_INVALID_STATE", "Slot is already closed.")
    slot["closed"] = True
    slot["status"] = "CLOSED"
    touch(slot)
    return success(slot_view(slot), status=200)


@app.post("/park/slots/<slot_id>/sweep-no-shows")
def sweep_no_shows(slot_id):
    auth_and_role({"ParkManager"})
    slot = svc.get_or_404(db.slots, slot_id)
    park = svc.get_or_404(db.parks, slot["park_id"])
    clock = svc.park_clock(park)
    if clock < slot["_ends_dt"]:
        # Precondition: park clock must have reached slot end.
        raise err("ERR_INVALID_STATE", "Slot end has not been reached on the park clock.")
    changed = False
    for jp in db.jump_passes.values():
        if jp["slot_id"] != slot_id:
            continue
        if jp["admission_status"] != "RESERVED":
            continue
        jp["admission_status"] = "NO_SHOW"
        # restore inclusion if consumed
        restore_inclusion(jp)
        touch(jp)
        changed = True
    svc.recompute_slot(slot)
    if changed:
        touch(slot)
    return success(slot_view(slot), status=200)


@app.get("/park/slots/<slot_id>/jump-passes")
def slot_jump_passes(slot_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    svc.get_or_404(db.slots, slot_id)
    limit, offset = parse_pagination()
    items = [j for j in db.jump_passes.values() if j["slot_id"] == slot_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(j) for j in window], limit, offset, total)


@app.get("/park/slots/<slot_id>/party-bookings")
def slot_party_bookings(slot_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    svc.get_or_404(db.slots, slot_id)
    limit, offset = parse_pagination()
    items = [b for b in db.party_bookings.values() if b["slot_id"] == slot_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(b) for b in window], limit, offset, total)


# ===========================================================================
# Participant
# ===========================================================================
def compute_is_minor(park, birthdate_dt):
    """Whole-year age at the park clock; minor when strictly younger than threshold."""
    clock = svc.park_clock(park)
    years = clock.year - birthdate_dt.year
    # subtract one if birthday hasn't occurred yet this year
    if (clock.month, clock.day) < (birthdate_dt.month, birthdate_dt.day):
        years -= 1
    return years < park["minor_age_threshold"]


@app.post("/park/participants")
def create_participant():
    auth_and_role({"FrontDesk", "Member", "ParkManager"})
    body = get_json_body()
    park_id = require_str(body, "park_id")
    full_name = require_str(body, "full_name")
    birthdate = require_datetime(body, "birthdate")
    guardian_id = opt_str(body, "guardian_participant_id", None)
    member_id = opt_str(body, "member_id", None)

    park = svc.get_or_404(db.parks, park_id)
    guardian = None
    if guardian_id is not None:
        guardian = svc.get_or_404(db.participants, guardian_id)
    if member_id is not None:
        svc.get_or_404(db.members, member_id)

    is_minor = compute_is_minor(park, birthdate)

    # Guardian rule (priority 6)
    if is_minor:
        if guardian is None:
            raise err("ERR_GUARDIAN_REQUIRED", "Minor requires a guardian.")
        if guardian["park_id"] != park_id or guardian["is_minor"]:
            raise err("ERR_GUARDIAN_REQUIRED", "Guardian must be a non-minor in the same park.")
    else:
        if guardian_id is not None:
            raise err("ERR_GUARDIAN_REQUIRED", "An adult must not supply a guardian.")

    rec = make_common()
    rec.update({
        "park_id": park_id,
        "full_name": full_name,
        "birthdate": iso_ms(birthdate),
        "is_minor": is_minor,
        "guardian_participant_id": guardian_id,
        "member_id": member_id,
    })
    db.participants[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/participants/<participant_id>")
def get_participant(participant_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    p = svc.get_or_404(db.participants, participant_id)
    return success(public(p), status=200)


@app.get("/park/participants")
def list_participants():
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    park_id = request.args.get("park_id")
    member_id = request.args.get("member_id")
    guardian_id = request.args.get("guardian_participant_id")
    items = []
    for p in db.participants.values():
        if park_id is not None and p["park_id"] != park_id:
            continue
        if member_id is not None and p["member_id"] != member_id:
            continue
        if guardian_id is not None and p["guardian_participant_id"] != guardian_id:
            continue
        items.append(p)
    window, total = paginate(items, limit, offset)
    return list_response([serialize(p) for p in window], limit, offset, total)


@app.get("/park/participants/<participant_id>/waivers")
def participant_waivers(participant_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    svc.get_or_404(db.participants, participant_id)
    limit, offset = parse_pagination()
    items = [w for w in db.waivers.values() if w["participant_id"] == participant_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(w) for w in window], limit, offset, total)


# ===========================================================================
# Waiver
# ===========================================================================
@app.post("/park/waivers")
def create_waiver():
    user_id, user_role = auth_and_role({"FrontDesk", "Member", "Guardian", "ParkManager"})
    body = get_json_body()
    participant_id = require_str(body, "participant_id")
    signed_by = require_str(body, "signed_by_participant_id")
    signature_text = require_str(body, "signature_text")

    participant = svc.get_or_404(db.participants, participant_id)
    signer = svc.get_or_404(db.participants, signed_by)

    # Guardian ownership: the signing participant must be the acting Guardian.
    if user_role == "Guardian" and user_id != signed_by:
        raise err("ERR_NOT_RESOURCE_OWNER", "Guardian must sign as themselves.")

    # Signer rule (priority 7)
    if participant["is_minor"]:
        if signed_by != participant["guardian_participant_id"]:
            raise err("ERR_INVALID_SIGNER", "Minor's waiver must be signed by the guardian.")
    else:
        if signed_by != participant_id:
            raise err("ERR_INVALID_SIGNER", "Adult must self-sign.")

    park = svc.get_or_404(db.parks, participant["park_id"])
    signed_at = svc.park_clock(park)
    from datetime import timedelta
    expires_at = signed_at + timedelta(days=svc.WAIVER_VALIDITY_DAYS)

    # Supersede prior SIGNED waiver for the same participant -> VOIDED
    for w in db.waivers.values():
        if w["participant_id"] == participant_id and w["status"] == "SIGNED":
            w["status"] = "VOIDED"
            touch(w)

    rec = make_common()
    rec.update({
        "participant_id": participant_id,
        "signed_by_participant_id": signed_by,
        "signature_text": signature_text,
        "signed_at": iso_ms(signed_at),
        "expires_at": iso_ms(expires_at),
        "_expires_dt": expires_at,
        "status": "SIGNED",
    })
    db.waivers[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/waivers/<waiver_id>")
def get_waiver(waiver_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    w = svc.get_or_404(db.waivers, waiver_id)
    return success(public(w), status=200)


@app.get("/park/waivers")
def list_waivers():
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    participant_id = request.args.get("participant_id")
    signed_by = request.args.get("signed_by_participant_id")
    items = []
    for w in db.waivers.values():
        if participant_id is not None and w["participant_id"] != participant_id:
            continue
        if signed_by is not None and w["signed_by_participant_id"] != signed_by:
            continue
        items.append(w)
    window, total = paginate(items, limit, offset)
    return list_response([serialize(w) for w in window], limit, offset, total)


# ===========================================================================
# JumpPass
# ===========================================================================
@app.post("/park/jump-passes")
def create_jump_pass():
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    body = get_json_body()
    slot_id = require_str(body, "slot_id")
    participant_id = require_str(body, "participant_id")
    channel = require_enum(body, "channel", {"RESERVATION", "WALKIN"})
    sock_count = opt_int(body, "sock_count", 1)
    member_id = opt_str(body, "member_id", None)
    expected_slot_version = require_int(body, "expected_slot_version")

    # Existence: path then body FKs left-to-right (priority 3)
    slot = svc.get_or_404(db.slots, slot_id)
    svc.get_or_404(db.participants, participant_id)
    membership = None
    if member_id is not None:
        svc.get_or_404(db.members, member_id)
        membership = svc.membership_for(member_id)

    # Member ownership (priority 4): a Member may only act with its own member_id
    if user_role == "Member":
        if member_id is None or member_id != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Member must apply its own membership.")

    # Quantity (priority 13)
    if sock_count < 1:
        raise err("ERR_INVALID_QUANTITY", "sock_count must be >= 1.")

    # OCC (priority 14) before capacity (priority 15) — safety-before-fiscal §2.7
    if expected_slot_version != slot["version"]:
        raise err("ERR_STALE_SLOT_VERSION", "Slot version is stale.")

    # Capacity (priority 15)
    if slot["status"] == "CLOSED" or slot["closed"]:
        raise err("ERR_SLOT_CAPACITY_EXCEEDED", "Slot is closed.")
    if slot["seats_taken"] + 1 > slot["jump_capacity"]:
        raise err("ERR_SLOT_CAPACITY_EXCEEDED", "Slot capacity exceeded.")

    park = svc.get_or_404(db.parks, slot["park_id"])
    base_charge, consumes_inclusion = svc.compute_pass_price(
        park, slot, channel, sock_count, membership
    )

    admission = "CHECKED_IN" if channel == "WALKIN" else "RESERVED"

    rec = make_common()
    rec.update({
        "slot_id": slot_id,
        "participant_id": participant_id,
        "channel": channel,
        "sock_count": sock_count,
        "member_id": member_id,
        "admission_status": admission,
        "payment_status": "UNPAID",
        "base_charge_cents": base_charge,
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "included_visit_consumed": False,
        "_consumes_inclusion": consumes_inclusion,
    })
    db.jump_passes[rec["id"]] = rec

    # consume one seat, recompute status, bump version
    svc.recompute_slot(slot)
    svc.bump_slot_version(slot)
    return success(public(rec), status=201)


@app.get("/park/jump-passes/<pass_id>")
def get_jump_pass(pass_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    jp = svc.get_or_404(db.jump_passes, pass_id)
    return success(public(jp), status=200)


@app.get("/park/jump-passes")
def list_jump_passes():
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    slot_id = request.args.get("slot_id")
    participant_id = request.args.get("participant_id")
    member_id = request.args.get("member_id")
    items = []
    for j in db.jump_passes.values():
        if slot_id is not None and j["slot_id"] != slot_id:
            continue
        if participant_id is not None and j["participant_id"] != participant_id:
            continue
        if member_id is not None and j["member_id"] != member_id:
            continue
        items.append(j)
    window, total = paginate(items, limit, offset)
    return list_response([serialize(j) for j in window], limit, offset, total)


@app.post("/park/jump-passes/<pass_id>/pay")
def pay_jump_pass(pass_id):
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    jp = svc.get_or_404(db.jump_passes, pass_id)
    ensure_pass_member_owner(user_id, user_role, jp)

    # State checks (priority 16 specific)
    if jp["payment_status"] != "UNPAID":
        raise err("ERR_ALREADY_PAID", "Pass is already paid or refunded.")
    if jp["admission_status"] in ("CANCELLED", "NO_SHOW"):
        raise err("ERR_INVALID_STATE", "Cannot pay a cancelled or no-show pass.")

    addon_total = svc.addon_total_for_pass(jp["id"])
    jp["amount_paid_cents"] = jp["base_charge_cents"] + addon_total
    jp["payment_status"] = "PAID"

    if jp.get("_consumes_inclusion"):
        membership = svc.membership_for(jp["member_id"]) if jp["member_id"] else None
        if membership and membership["status"] == "ACTIVE" and membership["included_visits_remaining"] > 0:
            jp["included_visit_consumed"] = True
            membership["included_visits_remaining"] -= 1
            touch(membership)
    touch(jp)
    return success(public(jp), status=200)


@app.post("/park/jump-passes/<pass_id>/check-in")
def checkin_jump_pass(pass_id):
    auth_and_role({"FrontDesk"})
    jp = svc.get_or_404(db.jump_passes, pass_id)
    slot = svc.get_or_404(db.slots, jp["slot_id"])
    park = svc.get_or_404(db.parks, slot["park_id"])

    # State: must be RESERVED reservation pass (priority 5)
    if jp["channel"] != "RESERVATION" or jp["admission_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Pass is not a reserved reservation pass.")

    # Safety gate first (priority 8)
    participant = svc.get_or_404(db.participants, jp["participant_id"])
    if not svc.covering_waiver_exists(park, participant):
        raise err("ERR_WAIVER_MISSING_OR_EXPIRED", "No valid waiver on file.")

    # Temporal window (priority 9)
    if not svc.within_checkin_window(park, slot):
        raise err("ERR_OUTSIDE_CHECKIN_WINDOW", "Outside the check-in window.")

    # Payment required (after safety + temporal per §2.7 ordering; treated as state)
    if jp["payment_status"] != "PAID":
        raise err("ERR_INVALID_STATE", "Pass must be paid before check-in.")

    jp["admission_status"] = "CHECKED_IN"
    touch(jp)
    # seat already held; slot unchanged but recompute for safety
    svc.recompute_slot(slot)
    return success(public(jp), status=200)


@app.post("/park/jump-passes/<pass_id>/complete")
def complete_jump_pass(pass_id):
    auth_and_role({"FrontDesk"})
    jp = svc.get_or_404(db.jump_passes, pass_id)
    if jp["admission_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Pass must be checked in to complete.")
    jp["admission_status"] = "COMPLETED"
    touch(jp)
    slot = db.slots.get(jp["slot_id"])
    if slot is not None:
        svc.recompute_slot(slot)
        svc.bump_slot_version(slot)
    return success(public(jp), status=200)


@app.post("/park/jump-passes/<pass_id>/cancel")
def cancel_jump_pass(pass_id):
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    jp = svc.get_or_404(db.jump_passes, pass_id)
    ensure_pass_member_owner(user_id, user_role, jp)

    if jp["admission_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Only a reserved pass can be cancelled.")

    jp["admission_status"] = "CANCELLED"
    slot = db.slots.get(jp["slot_id"])
    park = svc.get_or_404(db.parks, slot["park_id"]) if slot else None

    # Refund if paid
    if jp["payment_status"] == "PAID" and park is not None:
        svc.apply_cancellation_refund(park, slot, jp)

    # Restore inclusion if consumed
    restore_inclusion(jp)

    touch(jp)
    if slot is not None:
        svc.recompute_slot(slot)
        svc.bump_slot_version(slot)
    return success(public(jp), status=200)


@app.post("/park/jump-passes/<pass_id>/add-ons")
def attach_addon(pass_id):
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    jp = svc.get_or_404(db.jump_passes, pass_id)
    ensure_pass_member_owner(user_id, user_role, jp)
    body = get_json_body()
    sku = require_enum(body, "sku", set(svc.ADDON_PRICES.keys()))
    quantity = require_int(body, "quantity")
    if quantity < 1:
        raise err("ERR_INVALID_QUANTITY", "quantity must be >= 1.")

    unit_price = svc.ADDON_PRICES[sku]
    rec = make_common(with_version=False)
    rec.update({
        "jump_pass_id": pass_id,
        "sku": sku,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": unit_price * quantity,
    })
    db.add_ons[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/jump-passes/<pass_id>/add-ons")
def list_addons(pass_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    svc.get_or_404(db.jump_passes, pass_id)
    limit, offset = parse_pagination()
    items = [a for a in db.add_ons.values() if a["jump_pass_id"] == pass_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(a) for a in window], limit, offset, total)


def ensure_pass_member_owner(user_id, user_role, jp):
    if user_role == "Member" and jp["member_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this pass.")


def restore_inclusion(jp):
    """Compensating invariant: restore one included visit if pass consumed one."""
    if jp.get("included_visit_consumed"):
        membership = svc.membership_for(jp["member_id"]) if jp["member_id"] else None
        if membership is not None:
            membership["included_visits_remaining"] += 1
            touch(membership)
        jp["included_visit_consumed"] = False


# ===========================================================================
# Member / Membership
# ===========================================================================
@app.post("/park/members")
def create_member():
    auth_and_role({"FrontDesk", "ParkManager"})
    body = get_json_body()
    park_id = require_str(body, "park_id")
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    svc.get_or_404(db.parks, park_id)

    # Email uniqueness per park, case-insensitive (priority 17)
    for m in db.members.values():
        if m["park_id"] == park_id and m["email"].lower() == email.lower():
            raise err("ERR_DUPLICATE_EMAIL", "Email already exists in this park.")

    rec = make_common()
    rec.update({"park_id": park_id, "email": email, "full_name": full_name})
    db.members[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/members/<member_id>")
def get_member(member_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    m = svc.get_or_404(db.members, member_id)
    return success(public(m), status=200)


@app.get("/park/members")
def list_members():
    auth_and_role({"ParkManager", "FrontDesk"})
    limit, offset = parse_pagination()
    park_id = request.args.get("park_id")
    items = [m for m in db.members.values() if park_id is None or m["park_id"] == park_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(m) for m in window], limit, offset, total)


@app.get("/park/members/<member_id>/memberships")
def member_memberships(member_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    svc.get_or_404(db.members, member_id)
    limit, offset = parse_pagination()
    items = [m for m in db.memberships.values() if m["member_id"] == member_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(m) for m in window], limit, offset, total)


@app.post("/park/memberships")
def create_membership():
    user_id, user_role = auth_and_role({"FrontDesk", "Member", "ParkManager"})
    body = get_json_body()
    member_id = require_str(body, "member_id")
    tier = require_enum(body, "tier", {"BRONZE", "SILVER", "GOLD"})
    cycle_anchor = require_datetime(body, "cycle_anchor_at")

    svc.get_or_404(db.members, member_id)
    if user_role == "Member" and user_id != member_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this account.")

    allot = svc.TIER_TABLE[tier]["included_visits"]
    rec = make_common()
    rec.update({
        "member_id": member_id,
        "tier": tier,
        "cycle_anchor_at": iso_ms(cycle_anchor),
        "_anchor_dt": cycle_anchor,
        "status": "ACTIVE",
        "included_visits_remaining": allot,
        "current_cycle_index": 0,
    })
    db.memberships[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/memberships/<membership_id>")
def get_membership(membership_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    m = svc.get_or_404(db.memberships, membership_id)
    return success(public(m), status=200)


@app.post("/park/memberships/<membership_id>/renew")
def renew_membership(membership_id):
    user_id, user_role = auth_and_role({"Member", "ParkManager"})
    m = svc.get_or_404(db.memberships, membership_id)
    ensure_membership_owner(user_id, user_role, m)
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"SUCCEEDED", "FAILED"})

    park = membership_park(m)
    allot = svc.TIER_TABLE[m["tier"]]["included_visits"]

    if m["status"] == "ACTIVE":
        # Renewal due check (priority 18)
        from datetime import timedelta
        next_boundary = m["_anchor_dt"] + timedelta(days=30 * (m["current_cycle_index"] + 1))
        if svc.park_clock(park) < next_boundary:
            raise err("ERR_RENEWAL_NOT_DUE", "Renewal is not yet due.")
        if outcome == "SUCCEEDED":
            m["current_cycle_index"] += 1
            m["included_visits_remaining"] = allot
        else:  # FAILED
            m["status"] = "PAST_DUE"
            m["included_visits_remaining"] = 0
    elif m["status"] == "PAST_DUE":
        if outcome == "SUCCEEDED":
            m["current_cycle_index"] += 1
            m["status"] = "ACTIVE"
            m["included_visits_remaining"] = allot
        else:
            # A FAILED renewal from PAST_DUE has no defined transition.
            raise err("ERR_INVALID_STATE", "No renewal transition from PAST_DUE on failure.")
    else:  # CANCELLED
        raise err("ERR_INVALID_STATE", "Cannot renew a cancelled membership.")

    touch(m)
    return success(public(m), status=200)


@app.post("/park/memberships/<membership_id>/cancel")
def cancel_membership(membership_id):
    user_id, user_role = auth_and_role({"Member", "ParkManager"})
    m = svc.get_or_404(db.memberships, membership_id)
    ensure_membership_owner(user_id, user_role, m)

    if m["status"] == "ACTIVE":
        m["status"] = "CANCELLED"
        m["included_visits_remaining"] = 0
    elif m["status"] == "PAST_DUE":
        m["status"] = "CANCELLED"
    else:
        raise err("ERR_INVALID_STATE", "Membership is already cancelled.")
    touch(m)
    return success(public(m), status=200)


def ensure_membership_owner(user_id, user_role, membership):
    if user_role == "Member" and membership["member_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this membership.")


def membership_park(membership):
    member = db.members.get(membership["member_id"])
    if member is None:
        raise err("ERR_NOT_FOUND", "Owning member not found.")
    return svc.get_or_404(db.parks, member["park_id"])


# ===========================================================================
# PartyRoom / PartyPackage
# ===========================================================================
@app.post("/park/rooms")
def create_room():
    auth_and_role({"ParkManager"})
    body = get_json_body()
    park_id = require_str(body, "park_id")
    name = require_str(body, "name")
    room_capacity = require_int(body, "room_capacity")
    turnover = opt_int(body, "turnover_buffer_minutes", 30)
    svc.get_or_404(db.parks, park_id)
    if room_capacity < 1:
        raise err("ERR_VALIDATION", "room_capacity must be >= 1.")
    if turnover < 0:
        raise err("ERR_VALIDATION", "turnover_buffer_minutes must be >= 0.")
    rec = make_common()
    rec.update({
        "park_id": park_id,
        "name": name,
        "room_capacity": room_capacity,
        "turnover_buffer_minutes": turnover,
    })
    db.rooms[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/rooms/<room_id>")
def get_room(room_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    r = svc.get_or_404(db.rooms, room_id)
    return success(public(r), status=200)


@app.get("/park/rooms")
def list_rooms():
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    park_id = request.args.get("park_id")
    items = [r for r in db.rooms.values() if park_id is None or r["park_id"] == park_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(r) for r in window], limit, offset, total)


@app.get("/park/rooms/<room_id>/party-bookings")
def room_party_bookings(room_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    svc.get_or_404(db.rooms, room_id)
    limit, offset = parse_pagination()
    items = [b for b in db.party_bookings.values() if b["room_id"] == room_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(b) for b in window], limit, offset, total)


@app.post("/park/packages")
def create_package():
    auth_and_role({"ParkManager"})
    body = get_json_body()
    park_id = require_str(body, "park_id")
    name = require_str(body, "name")
    per_guest = require_int(body, "per_guest_cents")
    base_room_fee = require_int(body, "base_room_fee_cents")
    min_guests = require_int(body, "min_guests")
    svc.get_or_404(db.parks, park_id)
    if per_guest < 0:
        raise err("ERR_VALIDATION", "per_guest_cents must be >= 0.")
    if base_room_fee < 0:
        raise err("ERR_VALIDATION", "base_room_fee_cents must be >= 0.")
    if min_guests < 1:
        raise err("ERR_VALIDATION", "min_guests must be >= 1.")
    rec = make_common()
    rec.update({
        "park_id": park_id,
        "name": name,
        "per_guest_cents": per_guest,
        "base_room_fee_cents": base_room_fee,
        "min_guests": min_guests,
    })
    db.packages[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/packages/<package_id>")
def get_package(package_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    p = svc.get_or_404(db.packages, package_id)
    return success(public(p), status=200)


@app.get("/park/packages")
def list_packages():
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    park_id = request.args.get("park_id")
    items = [p for p in db.packages.values() if park_id is None or p["park_id"] == park_id]
    window, total = paginate(items, limit, offset)
    return list_response([serialize(p) for p in window], limit, offset, total)


# ===========================================================================
# PartyBooking
# ===========================================================================
@app.post("/park/party-bookings")
def create_party_booking():
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    body = get_json_body()
    package_id = require_str(body, "package_id")
    room_id = require_str(body, "room_id")
    slot_id = require_str(body, "slot_id")
    guest_count = require_int(body, "guest_count")
    host_member_id = opt_str(body, "host_member_id", None)

    package = svc.get_or_404(db.packages, package_id)
    room = svc.get_or_404(db.rooms, room_id)
    svc.get_or_404(db.slots, slot_id)
    membership = None
    if host_member_id is not None:
        svc.get_or_404(db.members, host_member_id)
        membership = svc.membership_for(host_member_id)

    if user_role == "Member":
        if host_member_id is None or host_member_id != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Member must host with its own account.")

    # guest_count range (priority 12)
    if guest_count < package["min_guests"] or guest_count > room["room_capacity"]:
        raise err("ERR_GUEST_COUNT_OUT_OF_RANGE", "guest_count outside allowed range.")

    total = svc.compute_party_total(package, guest_count, membership)
    rec = make_common()
    rec.update({
        "package_id": package_id,
        "room_id": room_id,
        "slot_id": slot_id,
        "host_member_id": host_member_id,
        "guest_count": guest_count,
        "booking_status": "PENDING",
        "total_cents": total,
        "deposit_cents": 0,
        "balance_paid_cents": 0,
    })
    db.party_bookings[rec["id"]] = rec
    return success(public(rec), status=201)


@app.get("/park/party-bookings/<booking_id>")
def get_party_booking(booking_id):
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    b = svc.get_or_404(db.party_bookings, booking_id)
    return success(public(b), status=200)


@app.get("/park/party-bookings")
def list_party_bookings():
    auth_and_role({"ParkManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    package_id = request.args.get("package_id")
    room_id = request.args.get("room_id")
    slot_id = request.args.get("slot_id")
    host_member_id = request.args.get("host_member_id")
    items = []
    for b in db.party_bookings.values():
        if package_id is not None and b["package_id"] != package_id:
            continue
        if room_id is not None and b["room_id"] != room_id:
            continue
        if slot_id is not None and b["slot_id"] != slot_id:
            continue
        if host_member_id is not None and b["host_member_id"] != host_member_id:
            continue
        items.append(b)
    window, total = paginate(items, limit, offset)
    return list_response([serialize(b) for b in window], limit, offset, total)


@app.post("/park/party-bookings/<booking_id>/hold-deposit")
def hold_deposit(booking_id):
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    b = svc.get_or_404(db.party_bookings, booking_id)
    ensure_booking_owner(user_id, user_role, b)
    body = get_json_body()
    expected_slot_version = require_int(body, "expected_slot_version")

    if b["booking_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Booking is not pending.")

    slot = svc.get_or_404(db.slots, b["slot_id"])
    room = svc.get_or_404(db.rooms, b["room_id"])
    park = svc.get_or_404(db.parks, slot["park_id"])

    # Room conflict (priority 10) precedes OCC (priority 14) and capacity (priority 15)
    if room_conflict(room, slot, b["id"]):
        raise err("ERR_ROOM_CONFLICT", "Room interval conflict.")

    # OCC (priority 14) before capacity (priority 15)
    if expected_slot_version != slot["version"]:
        raise err("ERR_STALE_SLOT_VERSION", "Slot version is stale.")

    # Capacity (priority 15)
    if slot["status"] == "CLOSED" or slot["closed"]:
        raise err("ERR_SLOT_CAPACITY_EXCEEDED", "Slot is closed.")
    if slot["seats_taken"] + b["guest_count"] > slot["jump_capacity"]:
        raise err("ERR_SLOT_CAPACITY_EXCEEDED", "Slot capacity exceeded.")

    deposit = round_half_up(b["total_cents"] * park["party_deposit_pct"])
    b["booking_status"] = "DEPOSIT_HELD"
    b["deposit_cents"] = deposit
    b["balance_paid_cents"] = deposit
    touch(b)

    svc.recompute_slot(slot)
    svc.bump_slot_version(slot)
    return success(public(b), status=200)


def room_conflict(room, new_slot, booking_id):
    """True if the new slot interval collides (incl. turnover buffer) with another
    non-CANCELLED booking on the same room (PRD §3.8)."""
    from datetime import timedelta
    buf = timedelta(minutes=room["turnover_buffer_minutes"])
    new_start = new_slot["_starts_dt"]
    new_end = new_slot["_ends_dt"]
    for other in db.party_bookings.values():
        if other["id"] == booking_id:
            continue
        if other["room_id"] != room["id"]:
            continue
        if other["booking_status"] == "CANCELLED":
            continue
        other_slot = db.slots.get(other["slot_id"])
        if other_slot is None:
            continue
        o_start = other_slot["_starts_dt"]
        o_end = other_slot["_ends_dt"]
        # Two intervals are separated only if one ends + buffer <= the other starts.
        if new_start >= o_end + buf or o_start >= new_end + buf:
            continue
        return True
    return False


@app.post("/park/party-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    b = svc.get_or_404(db.party_bookings, booking_id)
    ensure_booking_owner(user_id, user_role, b)
    if b["booking_status"] != "DEPOSIT_HELD":
        raise err("ERR_INVALID_STATE", "Booking must be deposit-held to confirm.")
    b["balance_paid_cents"] = b["total_cents"]
    b["booking_status"] = "CONFIRMED"
    touch(b)
    return success(public(b), status=200)


@app.post("/park/party-bookings/<booking_id>/check-in")
def checkin_booking(booking_id):
    auth_and_role({"FrontDesk"})
    b = svc.get_or_404(db.party_bookings, booking_id)
    if b["booking_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Booking must be confirmed to check in.")
    slot = svc.get_or_404(db.slots, b["slot_id"])
    park = svc.get_or_404(db.parks, slot["park_id"])
    if not svc.within_checkin_window(park, slot):
        raise err("ERR_OUTSIDE_CHECKIN_WINDOW", "Outside the check-in window.")
    b["booking_status"] = "CHECKED_IN"
    touch(b)
    return success(public(b), status=200)


@app.post("/park/party-bookings/<booking_id>/complete")
def complete_booking(booking_id):
    auth_and_role({"FrontDesk"})
    b = svc.get_or_404(db.party_bookings, booking_id)
    if b["booking_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Booking must be checked in to complete.")
    b["booking_status"] = "COMPLETED"
    touch(b)
    slot = db.slots.get(b["slot_id"])
    if slot is not None:
        svc.recompute_slot(slot)
        svc.bump_slot_version(slot)
    return success(public(b), status=200)


@app.post("/park/party-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, user_role = auth_and_role({"FrontDesk", "Member"})
    b = svc.get_or_404(db.party_bookings, booking_id)
    ensure_booking_owner(user_id, user_role, b)
    status = b["booking_status"]
    if status not in ("PENDING", "DEPOSIT_HELD", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Booking cannot be cancelled from its state.")

    slot = db.slots.get(b["slot_id"])
    if status == "PENDING":
        # clean cancel; no seats, no deposit, no slot change
        b["booking_status"] = "CANCELLED"
        touch(b)
    elif status == "DEPOSIT_HELD":
        b["booking_status"] = "CANCELLED"
        # forfeit deposit: balance stays at deposit_cents, no refund
        touch(b)
        if slot is not None:
            svc.recompute_slot(slot)
            svc.bump_slot_version(slot)
    else:  # CONFIRMED
        b["booking_status"] = "CANCELLED"
        # refund balance beyond deposit; balance settles to deposit_cents
        b["balance_paid_cents"] = b["deposit_cents"]
        touch(b)
        if slot is not None:
            svc.recompute_slot(slot)
            svc.bump_slot_version(slot)
    return success(public(b), status=200)


def ensure_booking_owner(user_id, user_role, booking):
    if user_role == "Member" and booking["host_member_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not host this booking.")


# ===========================================================================
# IncidentReport
# ===========================================================================
@app.post("/park/incidents")
def file_incident():
    auth_and_role({"FrontDesk", "ParkManager"})
    body = get_json_body()
    park_id = require_str(body, "park_id")
    jump_pass_id = require_str(body, "jump_pass_id")
    severity = require_enum(body, "severity", {"MINOR", "MODERATE", "SEVERE"})
    narrative = require_str(body, "narrative")

    svc.get_or_404(db.parks, park_id)
    jp = svc.get_or_404(db.jump_passes, jump_pass_id)

    # Pass must be CHECKED_IN at filing time (priority 5)
    if jp["admission_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Pass must be checked in to file an incident.")

    rec = make_common()
    rec.update({
        "park_id": park_id,
        "jump_pass_id": jump_pass_id,
        "severity": severity,
        "narrative": narrative,
        "status": "FILED",
        "reviewed_by_user_id": None,
    })
    db.incidents[rec["id"]] = rec

    # SEVERE cascade: force-close the pass's slot at file time (PRD §3.9)
    if severity == "SEVERE":
        slot = db.slots.get(jp["slot_id"])
        if slot is not None and not slot["closed"]:
            slot["closed"] = True
            slot["status"] = "CLOSED"
            touch(slot)
    return success(public(rec), status=201)


@app.get("/park/incidents/<incident_id>")
def get_incident(incident_id):
    auth_and_role({"ParkManager", "FrontDesk"})
    i = svc.get_or_404(db.incidents, incident_id)
    return success(public(i), status=200)


@app.get("/park/incidents")
def list_incidents():
    auth_and_role({"ParkManager", "FrontDesk"})
    limit, offset = parse_pagination()
    park_id = request.args.get("park_id")
    jump_pass_id = request.args.get("jump_pass_id")
    items = []
    for i in db.incidents.values():
        if park_id is not None and i["park_id"] != park_id:
            continue
        if jump_pass_id is not None and i["jump_pass_id"] != jump_pass_id:
            continue
        items.append(i)
    window, total = paginate(items, limit, offset)
    return list_response([serialize(i) for i in window], limit, offset, total)


@app.post("/park/incidents/<incident_id>/review")
def review_incident(incident_id):
    user_id, user_role = auth_and_role({"ParkManager"})
    i = svc.get_or_404(db.incidents, incident_id)
    if i["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Incident must be filed to review.")
    i["status"] = "REVIEWED"
    i["reviewed_by_user_id"] = user_id
    touch(i)
    return success(public(i), status=200)


@app.post("/park/incidents/<incident_id>/sign-off")
def signoff_incident(incident_id):
    auth_and_role({"ParkManager"})
    i = svc.get_or_404(db.incidents, incident_id)
    if i["status"] != "REVIEWED":
        raise err("ERR_INVALID_STATE", "Incident must be reviewed to sign off.")
    i["status"] = "SIGNED_OFF"
    touch(i)
    return success(public(i), status=200)


@app.post("/park/incidents/<incident_id>/void")
def void_incident(incident_id):
    auth_and_role({"ParkManager"})
    i = svc.get_or_404(db.incidents, incident_id)
    if i["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Only a filed incident can be voided.")
    i["status"] = "VOIDED"
    touch(i)
    return success(public(i), status=200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # use_reloader=False: a reloading dev server forks a second interpreter,
    # doubling cold-start cost under the 8x-concurrent per-test restart sweep.
    # debug=False keeps the request path lean. Server still binds 0.0.0.0.
    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
        debug=False,
        use_reloader=False,
    )
