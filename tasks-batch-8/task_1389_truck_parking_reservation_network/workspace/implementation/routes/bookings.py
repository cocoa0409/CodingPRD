"""Bookings and booking amenity lines (PRD §3.4, §3.5, §3.6)."""
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, request

import auth
import db
import domain
import errors
import services
import util

bp = Blueprint("bookings", __name__)
READ_ROLES = ("Driver", "FleetManager", "SiteOperator", "NetworkAdmin")
LINE_ROLES = ("Driver", "SiteOperator", "NetworkAdmin")


def _booking_or_404(booking_id):
    b = domain.get("bookings", booking_id)
    if b is None:
        raise errors.not_found("Booking not found")
    return b


def _own_booking(ident, b):
    if b["driver_id"] != ident.user_id:
        raise errors.forbidden("Driver may act only on their own bookings")


def _validate_window_fields(kind, arrival_raw, night_count):
    """Priority 8, listed order: past/today, too-long, invalid."""
    arrival = services.parse_date(arrival_raw)
    today = db.clock_now().date()
    if arrival is not None:
        if kind == "RESERVED" and arrival < today:
            raise errors.window_in_past()
        if kind == "WALK_IN" and arrival != today:
            raise errors.walkin_not_today()
    if isinstance(night_count, int) and not isinstance(night_count, bool) \
            and night_count > 14:
        raise errors.window_too_long()
    if arrival is None:
        raise errors.window_invalid("arrival_date is unparseable")
    if not isinstance(night_count, int) or isinstance(night_count, bool) \
            or night_count < 1:
        raise errors.window_invalid("night_count must be at least 1")
    return arrival


@bp.post("/bookings")
def create_booking():
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    body = util.get_body(required=True)
    util.req_fields(body, ["driver_id", "site_id", "booking_kind", "arrival_date",
                           "night_count", "payment_mode"])
    driver_id = util.req_str(body, "driver_id")
    site_id = util.req_str(body, "site_id")
    kind = util.req_enum(body, "booking_kind", ("RESERVED", "WALK_IN"))
    payment_mode = util.req_enum(body, "payment_mode", ("DRIVER_DIRECT", "FLEET_BILL"))
    stall_class = util.opt_enum(body, "stall_class", ("STANDARD", "OVERSIZED"),
                                "STANDARD")
    stall_id = body.get("stall_id")
    if stall_id is not None and not isinstance(stall_id, str):
        raise errors.validation("stall_id must be a string")
    fleet_id = body.get("fleet_account_id")
    if payment_mode == "FLEET_BILL":
        if not isinstance(fleet_id, str) or not fleet_id:
            raise errors.validation("fleet_account_id is required for FLEET_BILL")
    elif fleet_id is not None:
        raise errors.validation("fleet_account_id is forbidden for DRIVER_DIRECT")
    night_count_raw = body.get("night_count")
    if night_count_raw is not None and not util.is_int(night_count_raw):
        raise errors.validation("night_count must be an integer")

    # Priority 2: ownership. Priority 3: referenced entities exist.
    if driver_id != ident.user_id:
        raise errors.forbidden("driver_id must equal X-User-ID")
    driver = domain.get("drivers", driver_id)
    if driver is None:
        raise errors.not_found("Driver not found")
    site = domain.get("sites", site_id)
    if site is None:
        raise errors.not_found("Site not found")
    fleet = None
    if payment_mode == "FLEET_BILL":
        fleet = domain.get("fleet_accounts", fleet_id)
        if fleet is None:
            raise errors.not_found("FleetAccount not found")

    # Priority 7: site posture safety gate.
    if services.site_posture(site_id) == "ESCALATED":
        raise errors.site_escalated()

    # Priority 8: window discipline.
    arrival = _validate_window_fields(kind, body.get("arrival_date"), night_count_raw)
    night_count = night_count_raw
    checkin_open = datetime.combine(arrival, time(15, 0), tzinfo=timezone.utc)
    checkout_due = datetime.combine(arrival + timedelta(days=night_count),
                                    time(11, 0), tzinfo=timezone.utc)
    window = (checkin_open, checkout_due)

    # Priority 10: interval conflicts — requested stall, then driver.
    stall = None
    if stall_id is not None:
        candidate = domain.get("stalls", stall_id)
        if candidate is not None and candidate["site_id"] == site_id:
            if not services.stall_free_of_bookings(stall_id, window):
                raise errors.stall_window_conflict()
            stall = candidate
    if services.driver_has_conflict(driver_id, window):
        raise errors.driver_window_conflict()

    # Priority 12: driver standing.
    if services.driver_standing(driver) == "SUSPENDED":
        raise errors.driver_suspended()

    # Priority 13/14 are evaluated inside _check_fleet_gates after quoting,
    # but authorization/fleet existence order matters: run 13/14 now.
    if payment_mode == "FLEET_BILL":
        if services.active_authorization(driver_id, fleet_id) is None:
            raise errors.driver_not_authorized()
        if fleet["status"] != "ACTIVE":
            raise errors.fleet_suspended()

    # Priority 15: explicit stall referential fit.
    if stall_id is not None:
        if stall is None:
            raise errors.stall_not_reservable("stall_id is foreign to the site")
        if stall["status"] != "ACTIVE":
            raise errors.stall_not_reservable("stall is OUT_OF_SERVICE")
        if stall["is_reservable"] != (kind == "RESERVED"):
            raise errors.stall_not_reservable("stall pool mismatch")
        if stall["stall_class"] != stall_class:
            raise errors.stall_not_reservable("stall class mismatch")

    # Priority 16: pool capacity via the assignment selector.
    if stall is None:
        eligible = services.eligible_stalls(site_id, kind == "RESERVED",
                                            stall_class, window)
        if not eligible:
            raise errors.site_capacity_full()
        stall = eligible[0]

    # Quote: per-night rates pinned; provisional total at creation-time tier.
    rates, quoted = services.quote_nights(site, driver, kind, arrival, night_count)

    # Priorities 19/20: fiscal gates against the provisional quote.
    if payment_mode == "FLEET_BILL":
        projected = services.fleet_projected_exposure(fleet_id) + quoted
        if projected > fleet["credit_limit_cents"]:
            raise errors.fleet_credit_exceeded()
        authorization = services.active_authorization(driver_id, fleet_id)
        cap = authorization["spend_cap_per_night_cents"]
        if cap is not None:
            per_night = util.rhu_cents(util.Decimal(quoted) / util.Decimal(night_count))
            if per_night > cap:
                raise errors.spend_cap_exceeded()

    booking = domain.new_entity("bookings", {
        "driver_id": driver_id,
        "site_id": site_id,
        "stall_id": stall["id"],
        "waitlist_entry_id": None,
        "booking_kind": kind,
        "payment_mode": payment_mode,
        "fleet_account_id": fleet_id if payment_mode == "FLEET_BILL" else None,
        "arrival_date": arrival,
        "night_count": night_count,
        "checkin_open_at": checkin_open,
        "checkout_due_at": checkout_due,
        "checked_in_at": db.clock_now() if kind == "WALK_IN" else None,
        "checked_out_at": None,
        "overstayed_at": None,
        "status": "CHECKED_IN" if kind == "WALK_IN" else "BOOKED",
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
    return util.ok(domain.serialize_booking(booking), status=201)


@bp.get("/bookings")
def list_bookings():
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    items = list(domain.all_of("bookings"))
    if ident.role == "Driver":
        items = [b for b in items if b["driver_id"] == ident.user_id]
    elif ident.role == "FleetManager":
        items = [b for b in items if b["fleet_account_id"] == ident.user_id]
    for field in ("driver_id", "site_id", "stall_id", "waitlist_entry_id",
                  "fleet_account_id", "status", "billing_status"):
        value = request.args.get(field)
        if value is not None:
            items = [b for b in items if b[field] == value]
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_booking(b) for b in page], pagination=pg)


@bp.get("/bookings/<booking_id>")
def get_booking(booking_id):
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    b = domain.get("bookings", booking_id)
    if b is None:
        raise errors.not_found("Booking not found")
    if ident.role == "Driver" and b["driver_id"] != ident.user_id:
        raise errors.forbidden()
    if ident.role == "FleetManager" and b["fleet_account_id"] != ident.user_id:
        raise errors.forbidden()
    return util.ok(domain.serialize_booking(b))


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    b = _booking_or_404(booking_id)
    _own_booking(ident, b)
    if b["status"] != "BOOKED":
        raise errors.invalid_state("Only BOOKED bookings may be cancelled")
    site = domain.get("sites", b["site_id"])
    free_before = b["checkin_open_at"] - timedelta(
        hours=site["cancellation_free_window_hours"])
    now = db.clock_now()
    if now <= free_before:  # inclusive boundary
        b["fee_cents"] = 0
        b["billing_status"] = "WAIVED"
        b["status"] = "CANCELLED"
        b["settled_at"] = now
    else:
        b["fee_cents"] = util.rhu_cents(
            util.Decimal(b["per_night_rates"][0]["rate_cents"]) / util.Decimal(2))
        b["final_total_cents"] = b["fee_cents"]
        b["status"] = "CANCELLED"
        b["settled_at"] = now
    domain.touch(b)
    services.waitlist_scan(b["site_id"], b["stall_id"])
    return util.ok(domain.serialize_booking(b))


@bp.post("/bookings/<booking_id>/check-in")
def check_in(booking_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    b = _booking_or_404(booking_id)
    _own_booking(ident, b)
    if b["status"] != "BOOKED":
        raise errors.invalid_state("Check-in is only possible from BOOKED")
    site = domain.get("sites", b["site_id"])
    now = db.clock_now()
    if now < b["checkin_open_at"]:
        raise errors.checkin_not_open()
    deadline = b["checkin_open_at"] + timedelta(minutes=site["no_show_grace_minutes"])
    if now > deadline:  # late boundary inclusive
        raise errors.checkin_grace_elapsed()
    stall = domain.get("stalls", b["stall_id"])
    if stall is None or stall["status"] != "ACTIVE":
        raise errors.stall_out_of_service()
    b["status"] = "CHECKED_IN"
    b["checked_in_at"] = now
    domain.touch(b)
    return util.ok(domain.serialize_booking(b))


@bp.post("/bookings/<booking_id>/check-out")
def check_out(booking_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver", "SiteOperator"))
    b = _booking_or_404(booking_id)
    body = util.get_body()
    force = util.opt_bool(body, "force", False)

    if ident.role == "SiteOperator":
        if not force:
            raise errors.forbidden("SiteOperator may only force check-out")
        if b["status"] != "OVERSTAY":
            raise errors.invalid_state("Eviction requires an OVERSTAY booking")
    else:
        if force:
            raise errors.forbidden("Drivers may not force check-out")
        _own_booking(ident, b)
        if b["status"] not in ("CHECKED_IN", "OVERSTAY"):
            raise errors.invalid_state("Check-out requires CHECKED_IN or OVERSTAY")

    site = domain.get("sites", b["site_id"])
    was_overstay = b["status"] == "OVERSTAY"
    b["checked_out_at"] = db.clock_now()
    services.settle_booking(b, site, charge_overstay_fee=was_overstay)
    b["status"] = "EVICTED" if (ident.role == "SiteOperator" and force) else "CHECKED_OUT"
    domain.touch(b)
    services.waitlist_scan(b["site_id"], b["stall_id"])
    if b["status"] == "EVICTED":
        driver = domain.get("drivers", b["driver_id"])
        if driver is not None:
            services.append_strike(driver, "EVICTION", b["id"])
    return util.ok(domain.serialize_booking(b))


@bp.post("/bookings/<booking_id>/extend")
def extend_booking(booking_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    b = _booking_or_404(booking_id)
    _own_booking(ident, b)
    body = util.get_body(required=True)
    util.req_fields(body, ["added_nights", "expected_booking_version"])
    added = util.req_int(body, "added_nights")
    if added < 1:
        raise errors.validation("added_nights must be at least 1")
    expected = util.req_int(body, "expected_booking_version")
    if b["status"] != "BOOKED":
        raise errors.invalid_state("Only BOOKED bookings may be extended")
    if expected != b["version"]:
        raise errors.stale_version()
    if b["night_count"] + added > 14:
        raise errors.extension_conflict("Extension would exceed 14 nights")

    site = domain.get("sites", b["site_id"])
    driver = domain.get("drivers", b["driver_id"])
    old_due = b["checkout_due_at"]
    new_due = old_due + timedelta(days=added)
    # The extension window must be free on the booking's own stall.
    if not services.stall_free_of_bookings(b["stall_id"], (old_due, new_due),
                                           exclude_booking_id=b["id"]):
        raise errors.extension_conflict()

    plan = services.active_rate_plan(b["site_id"])
    first_new_date = b["arrival_date"] + timedelta(days=b["night_count"])
    for i in range(added):
        d = first_new_date + timedelta(days=i)
        b["per_night_rates"].append(
            {"date": d, "rate_cents": services.nightly_rate(site, plan, d)})
    b["night_count"] += added
    b["checkout_due_at"] = new_due
    # Quote recomputed over all pinned nights at the current loyalty tier.
    subtotal = sum(r["rate_cents"] for r in b["per_night_rates"])
    if b["booking_kind"] == "WALK_IN":
        pct = 0
    else:
        pct = services.loyalty_pct_for_tier(
            services.loyalty_tier(services.settled_nights_90d(b["driver_id"])))
    discount = util.rhu_cents(util.Decimal(subtotal * pct) / util.Decimal(100))
    b["quoted_total_cents"] = subtotal - discount
    domain.touch(b)
    return util.ok(domain.serialize_booking(b))


@bp.post("/bookings/<booking_id>/payments")
def pay_booking(booking_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    b = _booking_or_404(booking_id)
    _own_booking(ident, b)
    body = util.get_body(required=True)
    util.req_fields(body, ["amount_cents"])
    amount = util.req_int(body, "amount_cents")
    if amount <= 0:
        raise errors.validation("amount_cents must be positive")
    if (b["payment_mode"] != "DRIVER_DIRECT" or b["final_total_cents"] is None
            or b["billing_status"] in ("PAID", "WAIVED")):
        raise errors.payment_not_due()
    remaining = b["final_total_cents"] - b["paid_cents"]
    if amount > remaining:
        raise errors.overpayment()
    if amount == remaining:
        b["paid_cents"] = b["final_total_cents"]
        b["billing_status"] = "PAID"
        domain.touch(b)
        services.loyalty_earn(b)
    else:
        b["paid_cents"] += amount
        b["billing_status"] = "PARTIALLY_PAID"
        domain.touch(b)
    return util.ok(domain.serialize_booking(b), status=201)


# --------------------------------------------------------------------------
# Booking amenity lines (PRD §3.6)
# --------------------------------------------------------------------------
def _line_or_404(line_id):
    line = domain.get("booking_amenities", line_id)
    if line is None:
        raise errors.not_found("BookingAmenity not found")
    return line


def _visible_line(ident, line):
    if ident.role == "Driver":
        booking = domain.get("bookings", line["booking_id"])
        if booking is None or booking["driver_id"] != ident.user_id:
            raise errors.forbidden()


@bp.post("/bookings/<booking_id>/amenities")
def add_amenity(booking_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    b = _booking_or_404(booking_id)
    _own_booking(ident, b)
    body = util.get_body(required=True)
    util.req_fields(body, ["amenity_product_id"])
    product_id = util.req_str(body, "amenity_product_id")
    quantity = util.opt_int(body, "quantity", 1)
    if quantity < 1:
        raise errors.validation("quantity must be at least 1")
    if b["status"] not in ("BOOKED", "CHECKED_IN"):
        raise errors.invalid_state("Amenities may be added only while BOOKED or CHECKED_IN")
    product = domain.get("amenity_products", product_id)
    if product is None or product["site_id"] != b["site_id"] \
            or product["status"] != "ACTIVE":
        raise errors.stall_not_reservable("Amenity product is foreign or discontinued")

    # Nightly capacity check across the booking's whole span (== allowed).
    capacity = product["nightly_capacity"]
    if capacity is not None:
        for i in range(b["night_count"]):
            d = b["arrival_date"] + timedelta(days=i)
            consumed = 0
            for line in domain.all_of("booking_amenities"):
                if (line["amenity_product_id"] != product_id
                        or line["status"] not in ("RESERVED", "FULFILLED")):
                    continue
                other = domain.get("bookings", line["booking_id"])
                if other is None or other["status"] in ("CANCELLED", "NO_SHOW"):
                    continue
                if other["arrival_date"] <= d < other["arrival_date"] + timedelta(
                        days=other["night_count"]):
                    consumed += line["quantity"]
            if consumed + quantity > capacity:
                raise errors.amenity_capacity_exceeded()

    line = domain.new_entity("booking_amenities", {
        "booking_id": b["id"],
        "amenity_product_id": product_id,
        "quantity": quantity,
        "unit_price_cents": product["price_cents"],
        "status": "RESERVED",
    })
    return util.ok(domain.serialize_booking_amenity(line), status=201)


@bp.get("/booking-amenities")
def list_amenities():
    ident = auth.identity()
    auth.require_roles(ident, LINE_ROLES)
    items = list(domain.all_of("booking_amenities"))
    if ident.role == "Driver":
        own = {b["id"] for b in domain.all_of("bookings")
               if b["driver_id"] == ident.user_id}
        items = [l for l in items if l["booking_id"] in own]
    for field in ("booking_id", "amenity_product_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [l for l in items if l[field] == value]
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_booking_amenity(l) for l in page], pagination=pg)


@bp.get("/booking-amenities/<line_id>")
def get_amenity(line_id):
    ident = auth.identity()
    auth.require_roles(ident, LINE_ROLES)
    line = domain.get("booking_amenities", line_id)
    if line is None:
        raise errors.not_found("BookingAmenity not found")
    _visible_line(ident, line)
    return util.ok(domain.serialize_booking_amenity(line))


@bp.patch("/booking-amenities/<line_id>")
def fulfill_amenity(line_id):
    ident = auth.identity()
    auth.require_roles(ident, ("SiteOperator",))
    line = _line_or_404(line_id)
    body = util.get_body(required=True)
    util.req_fields(body, ["status"])
    target = util.req_enum(body, "status", ("RESERVED", "FULFILLED", "CANCELLED"))
    if line["status"] != "RESERVED" or target != "FULFILLED":
        raise errors.invalid_state("Only a RESERVED line may be fulfilled")
    booking = domain.get("bookings", line["booking_id"])
    if booking is None or booking["status"] not in ("CHECKED_IN", "OVERSTAY"):
        raise errors.invalid_state("Booking must be CHECKED_IN or OVERSTAY to fulfill")
    line["status"] = "FULFILLED"
    domain.touch(line)
    return util.ok(domain.serialize_booking_amenity(line))


@bp.delete("/booking-amenities/<line_id>")
def cancel_amenity(line_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    line = domain.get("booking_amenities", line_id)
    if line is None:
        raise errors.not_found("BookingAmenity not found")
    _visible_line(ident, line)
    booking = domain.get("bookings", line["booking_id"])
    if line["status"] != "RESERVED":
        raise errors.invalid_state("Only a RESERVED line may be cancelled")
    if booking is None or booking["status"] not in ("BOOKED", "CHECKED_IN"):
        raise errors.invalid_state("Booking must be BOOKED or CHECKED_IN to cancel a line")
    line["status"] = "CANCELLED"
    domain.touch(line)
    return util.ok(domain.serialize_booking_amenity(line))
