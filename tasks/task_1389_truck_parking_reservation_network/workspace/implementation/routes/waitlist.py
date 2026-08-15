"""Waitlist entries: join, list, get, accept, withdraw (PRD §3.7)."""
from flask import Blueprint, request

import auth
import db
import domain
import errors
import services
import util

bp = Blueprint("waitlist", __name__)
READ_ROLES = ("Driver", "SiteOperator", "NetworkAdmin")


def _entry_or_404(entry_id):
    e = domain.get("waitlist_entries", entry_id)
    if e is None:
        raise errors.not_found("WaitlistEntry not found")
    return e


def _own_entry(ident, e):
    if e["driver_id"] != ident.user_id:
        raise errors.forbidden("Driver may act only on their own waitlist entries")


@bp.post("/waitlist-entries")
def join_waitlist():
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    body = util.get_body(required=True)
    util.req_fields(body, ["driver_id", "site_id", "arrival_date", "night_count",
                           "stall_class", "payment_mode"])
    driver_id = util.req_str(body, "driver_id")
    site_id = util.req_str(body, "site_id")
    stall_class = util.req_enum(body, "stall_class", ("STANDARD", "OVERSIZED"))
    payment_mode = util.req_enum(body, "payment_mode", ("DRIVER_DIRECT", "FLEET_BILL"))
    fleet_id = body.get("fleet_account_id")
    if payment_mode == "FLEET_BILL":
        if not isinstance(fleet_id, str) or not fleet_id:
            raise errors.validation("fleet_account_id is required for FLEET_BILL")
    elif fleet_id is not None:
        raise errors.validation("fleet_account_id is forbidden for DRIVER_DIRECT")
    night_count_raw = body.get("night_count")
    if night_count_raw is not None and not util.is_int(night_count_raw):
        raise errors.validation("night_count must be an integer")

    if driver_id != ident.user_id:
        raise errors.forbidden("driver_id must equal X-User-ID")
    driver = domain.get("drivers", driver_id)
    if driver is None:
        raise errors.not_found("Driver not found")
    if domain.get("sites", site_id) is None:
        raise errors.not_found("Site not found")
    fleet = None
    if payment_mode == "FLEET_BILL":
        fleet = domain.get("fleet_accounts", fleet_id)
        if fleet is None:
            raise errors.not_found("FleetAccount not found")

    # Priority 8: window discipline (arrival never in the past for entries).
    arrival_raw = body.get("arrival_date")
    arrival = services.parse_date(arrival_raw)
    today = db.clock_now().date()
    if arrival is not None and arrival < today:
        raise errors.window_in_past()
    if util.is_int(night_count_raw) and night_count_raw > 14:
        raise errors.window_too_long()
    if arrival is None:
        raise errors.window_invalid("arrival_date is unparseable")
    if not util.is_int(night_count_raw) or night_count_raw < 1:
        raise errors.window_invalid("night_count must be at least 1")
    night_count = night_count_raw

    # Priority 12: driver standing.
    if services.driver_standing(driver) == "SUSPENDED":
        raise errors.driver_suspended()

    # Priority 13/14: authorization and fleet status at join.
    if payment_mode == "FLEET_BILL":
        if services.active_authorization(driver_id, fleet_id) is None:
            raise errors.driver_not_authorized()
        if fleet["status"] != "ACTIVE":
            raise errors.fleet_suspended()

    # Priority 16: at most one QUEUED/OFFERED entry per (driver, site).
    for e in domain.all_of("waitlist_entries"):
        if (e["driver_id"] == driver_id and e["site_id"] == site_id
                and e["status"] in ("QUEUED", "OFFERED")):
            raise errors.duplicate_waitlist_entry()

    # Join-time fiscal gates (PRD §3.7: credit-checked at join, re-checked at accept).
    if payment_mode == "FLEET_BILL":
        site = domain.get("sites", site_id)
        _, quoted = services.quote_nights(site, driver, "RESERVED", arrival, night_count)
        projected = services.fleet_projected_exposure(fleet_id) + quoted
        if projected > fleet["credit_limit_cents"]:
            raise errors.fleet_credit_exceeded()
        authorization = services.active_authorization(driver_id, fleet_id)
        cap = authorization["spend_cap_per_night_cents"]
        if cap is not None:
            per_night = util.rhu_cents(util.Decimal(quoted) / util.Decimal(night_count))
            if per_night > cap:
                raise errors.spend_cap_exceeded()

    entry = domain.new_entity("waitlist_entries", {
        "site_id": site_id,
        "driver_id": driver_id,
        "arrival_date": arrival,
        "night_count": night_count,
        "stall_class": stall_class,
        "payment_mode": payment_mode,
        "fleet_account_id": fleet_id if payment_mode == "FLEET_BILL" else None,
        "status": "QUEUED",
        "offered_stall_id": None,
        "offer_expires_at": None,
    })
    return util.ok(domain.serialize_waitlist_entry(entry), status=201)


@bp.get("/waitlist-entries")
def list_waitlist():
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    items = list(domain.all_of("waitlist_entries"))
    if ident.role == "Driver":
        items = [e for e in items if e["driver_id"] == ident.user_id]
    for field in ("driver_id", "site_id", "fleet_account_id", "offered_stall_id",
                  "status"):
        value = request.args.get(field)
        if value is not None:
            items = [e for e in items if e[field] == value]
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_waitlist_entry(e) for e in page], pagination=pg)


@bp.get("/waitlist-entries/<entry_id>")
def get_waitlist_entry(entry_id):
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    e = _entry_or_404(entry_id)
    if ident.role == "Driver":
        _own_entry(ident, e)
    return util.ok(domain.serialize_waitlist_entry(e))


@bp.post("/waitlist-entries/<entry_id>/accept")
def accept_waitlist_entry(entry_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    e = _entry_or_404(entry_id)
    _own_entry(ident, e)
    driver = domain.get("drivers", e["driver_id"])
    site = domain.get("sites", e["site_id"])

    if e["status"] != "OFFERED":
        raise errors.invalid_state("Only an OFFERED entry may be accepted")
    # Priority 7 safety gate, then the offer-expiry timing check.
    if services.site_posture(e["site_id"]) == "ESCALATED":
        raise errors.site_escalated()
    now = db.clock_now()
    if now > e["offer_expires_at"]:  # accept boundary inclusive
        raise errors.offer_expired()

    window = services.entry_window(e)
    # Priority 10: interval conflicts re-checked against the pinned stall.
    if not services.stall_free_of_bookings(e["offered_stall_id"], window):
        raise errors.stall_window_conflict()
    if services.driver_has_conflict(e["driver_id"], window):
        raise errors.driver_window_conflict()

    # Priority 12: standing; 13/14/19/20: fleet gates re-run on a fresh quote.
    if services.driver_standing(driver) == "SUSPENDED":
        raise errors.driver_suspended()

    rates, quoted = services.quote_nights(site, driver, "RESERVED",
                                          e["arrival_date"], e["night_count"])
    fleet = None
    if e["payment_mode"] == "FLEET_BILL":
        fleet = domain.get("fleet_accounts", e["fleet_account_id"])
        authorization = services.active_authorization(e["driver_id"],
                                                      e["fleet_account_id"])
        if authorization is None:
            raise errors.driver_not_authorized()
        if fleet is None or fleet["status"] != "ACTIVE":
            raise errors.fleet_suspended()
        projected = services.fleet_projected_exposure(e["fleet_account_id"]) + quoted
        if projected > fleet["credit_limit_cents"]:
            raise errors.fleet_credit_exceeded()
        cap = authorization["spend_cap_per_night_cents"]
        if cap is not None:
            per_night = util.rhu_cents(
                util.Decimal(quoted) / util.Decimal(e["night_count"]))
            if per_night > cap:
                raise errors.spend_cap_exceeded()

    checkin_open, checkout_due = window
    booking = domain.new_entity("bookings", {
        "driver_id": e["driver_id"],
        "site_id": e["site_id"],
        "stall_id": e["offered_stall_id"],
        "waitlist_entry_id": e["id"],
        "booking_kind": "RESERVED",
        "payment_mode": e["payment_mode"],
        "fleet_account_id": e["fleet_account_id"],
        "arrival_date": e["arrival_date"],
        "night_count": e["night_count"],
        "checkin_open_at": checkin_open,
        "checkout_due_at": checkout_due,
        "checked_in_at": None,
        "checked_out_at": None,
        "overstayed_at": None,
        "status": "BOOKED",
        "billing_status": "UNBILLED",
        "per_night_rates": rates,
        "quoted_total_cents": quoted,
        "parking_subtotal_cents": 0,
        "amenity_net_cents": 0,
        "discount_cents": 0,
        "fee_cents": 0,
        "final_total_cents": None,
        "paid_cents": 0,
        "incident_escalated": False,
        "settled_at": None,
    })
    e["status"] = "PROMOTED"
    domain.touch(e)
    return util.ok(domain.serialize_waitlist_entry(e))


@bp.post("/waitlist-entries/<entry_id>/withdraw")
def withdraw_waitlist_entry(entry_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    e = _entry_or_404(entry_id)
    _own_entry(ident, e)
    if e["status"] != "QUEUED":
        raise errors.invalid_state("Only a QUEUED entry may be withdrawn")
    e["status"] = "WITHDRAWN"
    domain.touch(e)
    return util.ok(domain.serialize_waitlist_entry(e))
