"""Business logic: entity construction, state machines, side effects, computed views."""
from datetime import date, timedelta

import calc
from calc import rhu
from decimal import Decimal
from errors import ApiError
from store import db, new_id, now_iso, base_common, touch


# =====================================================================
# Serialization — return stored dicts as-is (they hold exactly the
# output fields). Copy to avoid callers mutating the store.
# =====================================================================

def serialize(entity):
    return dict(entity)


# =====================================================================
# Lookups (raise ERR_NOT_FOUND) — priority 4
# =====================================================================

def get_or_404(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return ent


# =====================================================================
# Derived aggregates
# =====================================================================

def _confirmed_pax(departure_id):
    return sum(
        b["pax_count"]
        for b in db.bookings.values()
        if b["departure_id"] == departure_id
        and b["reservation_status"] in ("CONFIRMED", "TRAVELED")
    )


def _rooms_committed(departure_id):
    return sum(
        b["rooms_requested"]
        for b in db.bookings.values()
        if b["departure_id"] == departure_id
        and b["reservation_status"] in ("CONFIRMED", "TRAVELED")
    )


def _passengers_of(booking_id):
    return [p for p in db.passengers.values() if p["booking_id"] == booking_id]


def recompute_departure(dep):
    """Recompute confirmed_pax, occupancy_band, and drive the OPEN<->GUARANTEED cycle."""
    changed = False
    cp = _confirmed_pax(dep["id"])
    if dep["confirmed_pax"] != cp:
        dep["confirmed_pax"] = cp
        changed = True
    band = calc.band_for_pax(cp)
    if dep["occupancy_band"] != band:
        dep["occupancy_band"] = band
        changed = True
    if dep["status"] == "OPEN" and cp >= dep["guaranteed_min_pax"]:
        dep["status"] = "GUARANTEED"
        changed = True
    elif dep["status"] == "GUARANTEED" and cp < dep["guaranteed_min_pax"]:
        dep["status"] = "OPEN"
        changed = True
    if changed:
        touch(dep)
    return changed


def recompute_hotel_blocks(departure_id):
    committed = _rooms_committed(departure_id)
    for blk in db.hotel_blocks.values():
        if blk["departure_id"] != departure_id or blk["status"] == "RELEASED":
            continue
        changed = False
        if blk["rooms_committed"] != committed:
            blk["rooms_committed"] = committed
            changed = True
        if blk["status"] == "HELD":
            new_cost = committed * blk["nights"] * blk["rate_per_room_night_cents"]
            if blk["block_cost_cents"] != new_cost:
                blk["block_cost_cents"] = new_cost
                changed = True
        if changed:
            touch(blk)


def recompute_booking_payments(booking):
    paid = sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["booking_id"] == booking["id"] and p["kind"] in ("DEPOSIT", "BALANCE")
    )
    refunded = sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["booking_id"] == booking["id"] and p["kind"] == "REFUND"
    )
    booking["amount_paid_cents"] = paid
    booking["amount_refunded_cents"] = refunded


def _derive_payment_status(booking):
    paid = booking["amount_paid_cents"]
    if paid >= booking["booking_total_cents"]:
        return "PAID_IN_FULL"
    if paid >= booking["deposit_due_cents"]:
        return "DEPOSIT_PAID"
    return "UNPAID"


# =====================================================================
# Creation
# =====================================================================

def create_tour_product(name, duration_days, base_price_per_person_cents, deposit_per_person_cents):
    tp = base_common({
        "name": name,
        "duration_days": duration_days,
        "base_price_per_person_cents": base_price_per_person_cents,
        "deposit_per_person_cents": deposit_per_person_cents,
    })
    db.tour_products[tp["id"]] = tp
    return tp


def create_coach(code, seat_capacity, day_rate_cents):
    c = base_common({
        "code": code,
        "seat_capacity": seat_capacity,
        "day_rate_cents": day_rate_cents,
        "status": "AVAILABLE",
    })
    db.coaches[c["id"]] = c
    return c


def create_driver(name, license_no, day_rate_cents):
    d = base_common({
        "name": name,
        "license_no": license_no,
        "day_rate_cents": day_rate_cents,
        "status": "AVAILABLE",
    })
    db.drivers[d["id"]] = d
    return d


def create_guide(name, day_rate_cents):
    g = base_common({
        "name": name,
        "day_rate_cents": day_rate_cents,
        "status": "AVAILABLE",
    })
    db.guides[g["id"]] = g
    return g


def create_departure(tour_product_id, name, start_date, end_date, guaranteed_min_pax, itinerary_days):
    dep = base_common({
        "tour_product_id": tour_product_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "guaranteed_min_pax": guaranteed_min_pax,
        "itinerary_days": itinerary_days,
        "coach_id": None,
        "driver_id": None,
        "guide_id": None,
        "status": "PLANNING",
        "confirmed_pax": 0,
        "occupancy_band": "SMALL",
        "settlement_net_cents": None,
    })
    db.departures[dep["id"]] = dep
    return dep


def create_hotel_block(departure_id, hotel_name, city, room_count, nights, rate_per_room_night_cents):
    # rooms_committed always equals the sum of rooms_requested over CONFIRMED/
    # TRAVELED bookings on the departure (PRD §2.7/§3.4); for a fresh departure
    # this is 0, matching "a new block begins with rooms_committed of 0".
    committed = _rooms_committed(departure_id)
    blk = base_common({
        "departure_id": departure_id,
        "hotel_name": hotel_name,
        "city": city,
        "room_count": room_count,
        "nights": nights,
        "rate_per_room_night_cents": rate_per_room_night_cents,
        "rooms_committed": committed,
        "status": "HELD",
        "block_cost_cents": committed * nights * rate_per_room_night_cents,
    })
    db.hotel_blocks[blk["id"]] = blk
    return blk


def create_booking(departure_id, lead_name, pax_count, rooms_requested, insurance_opt_in):
    dep = db.departures[departure_id]
    tp = db.tour_products[dep["tour_product_id"]]
    projected = dep["confirmed_pax"] + pax_count
    band = calc.band_for_pax(projected)
    quoted = calc.per_person_price(tp["base_price_per_person_cents"], band)
    base_subtotal = quoted * pax_count
    svc_fee = calc.service_fee(quoted, pax_count)
    ins = calc.insurance_premium(base_subtotal, insurance_opt_in)
    booking_total = base_subtotal + svc_fee + ins
    deposit_due = tp["deposit_per_person_cents"] * pax_count
    booking = base_common({
        "departure_id": departure_id,
        "lead_name": lead_name,
        "pax_count": pax_count,
        "rooms_requested": rooms_requested,
        "insurance_opt_in": insurance_opt_in,
        "reservation_status": "DRAFT",
        "payment_status": "UNPAID",
        "quoted_per_person_cents": quoted,
        "final_per_person_cents": None,
        "base_subtotal_cents": base_subtotal,
        "service_fee_cents": svc_fee,
        "insurance_premium_cents": ins,
        "booking_total_cents": booking_total,
        "deposit_due_cents": deposit_due,
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "penalty_charged_cents": None,
        "cancel_reason": None,
    })
    db.bookings[booking["id"]] = booking
    return booking


def create_passenger(booking_id, full_name, is_lead, roommate_passenger_id):
    p = base_common({
        "booking_id": booking_id,
        "full_name": full_name,
        "is_lead": is_lead,
        "roommate_passenger_id": roommate_passenger_id,
        "seat_no": None,
        "room_no": None,
    })
    db.passengers[p["id"]] = p
    return p


# =====================================================================
# Payments
# =====================================================================

def record_payment(booking, kind, amount_cents, method):
    pay = {
        "id": new_id(),
        "created_at": now_iso(),
        "booking_id": booking["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "method": method,
    }
    db.payments[pay["id"]] = pay
    recompute_booking_payments(booking)
    if booking["payment_status"] != "REFUNDED":
        booking["payment_status"] = _derive_payment_status(booking)
    touch(booking)
    return pay


def _create_refund(booking, amount):
    if amount <= 0:
        return
    pay = {
        "id": new_id(),
        "created_at": now_iso(),
        "booking_id": booking["id"],
        "kind": "REFUND",
        "amount_cents": amount,
        "method": None,
    }
    db.payments[pay["id"]] = pay
    recompute_booking_payments(booking)


def _void_issued_vouchers(booking):
    for v in db.vouchers.values():
        if v["booking_id"] == booking["id"] and v["status"] == "ISSUED":
            v["status"] = "VOIDED"
            touch(v)


# =====================================================================
# Booking confirm / cancel
# =====================================================================

def _next_free(used):
    n = 1
    while n in used:
        n += 1
    return n


def confirm_booking(booking):
    dep = db.departures[booking["departure_id"]]
    # State checks (PRD §3.7 order): booking terminal -> from-state -> departure open
    if booking["reservation_status"] in ("CANCELLED", "TRAVELED"):
        raise ApiError("ERR_BOOKING_TERMINAL")
    if booking["reservation_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if dep["status"] not in ("OPEN", "GUARANTEED"):
        raise ApiError("ERR_DEPARTURE_NOT_OPEN")
    # Business constraints
    if dep["coach_id"]:
        coach = db.coaches[dep["coach_id"]]
        if dep["confirmed_pax"] + booking["pax_count"] > coach["seat_capacity"]:
            raise ApiError("ERR_COACH_CAPACITY_EXCEEDED")
    booking_pax = _passengers_of(booking["id"])
    if len(booking_pax) != booking["pax_count"]:
        raise ApiError("ERR_PASSENGER_COUNT_MISMATCH")
    for blk in db.hotel_blocks.values():
        if blk["departure_id"] == dep["id"] and blk["status"] != "RELEASED":
            if blk["rooms_committed"] + booking["rooms_requested"] > blk["room_count"]:
                raise ApiError("ERR_HOTEL_BLOCK_INSUFFICIENT")
    if booking["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise ApiError("ERR_DEPOSIT_UNPAID")

    # ---- side effects ----
    booking["reservation_status"] = "CONFIRMED"

    # seat assignment: lowest free seat numbers on the departure, ascending
    used_seats = {
        p["seat_no"]
        for p in db.passengers.values()
        if p["seat_no"] is not None
        and p["booking_id"] in db.bookings
        and db.bookings[p["booking_id"]]["departure_id"] == dep["id"]
        and db.bookings[p["booking_id"]]["reservation_status"] in ("CONFIRMED", "TRAVELED")
    }
    used_rooms = {
        p["room_no"]
        for p in db.passengers.values()
        if p["room_no"] is not None
        and p["booking_id"] in db.bookings
        and db.bookings[p["booking_id"]]["departure_id"] == dep["id"]
        and db.bookings[p["booking_id"]]["reservation_status"] in ("CONFIRMED", "TRAVELED")
    }
    room_by_passenger = {}
    for p in booking_pax:
        seat = _next_free(used_seats)
        used_seats.add(seat)
        p["seat_no"] = seat
        rm = p.get("roommate_passenger_id")
        if rm and rm in room_by_passenger:
            p["room_no"] = room_by_passenger[rm]
        else:
            room = _next_free(used_rooms)
            used_rooms.add(room)
            p["room_no"] = room
            room_by_passenger[p["id"]] = room
        touch(p)
        # issue one MEAL voucher per passenger
        v = base_common({
            "booking_id": booking["id"],
            "passenger_id": p["id"],
            "kind": "MEAL",
            "face_value_cents": calc.MEAL_VOUCHER_CENTS,
            "status": "ISSUED",
            "redeemed_at": None,
        })
        db.vouchers[v["id"]] = v

    touch(booking)
    recompute_departure(dep)
    recompute_hotel_blocks(dep["id"])
    return booking


def cancel_booking(booking, reason):
    dep = db.departures[booking["departure_id"]]
    if booking["reservation_status"] in ("CANCELLED", "TRAVELED"):
        raise ApiError("ERR_BOOKING_TERMINAL")
    status = booking["reservation_status"]
    if status == "CONFIRMED" and dep["status"] in ("DEPARTED", "SETTLED"):
        raise ApiError("ERR_INVALID_STATE")

    booking["cancel_reason"] = reason

    if status == "DRAFT":
        booking["penalty_charged_cents"] = 0
        if booking["amount_paid_cents"] > 0:
            _create_refund(booking, booking["amount_paid_cents"])
            booking["payment_status"] = "REFUNDED"
        booking["reservation_status"] = "CANCELLED"
        touch(booking)
        return booking

    # CONFIRMED cancel: penalty + refund + unwind
    days_before = (_parse_date(dep["start_date"]) - _clock_date()).days
    pct = calc.penalty_pct(days_before)
    base_penalty = rhu(Decimal(booking["base_subtotal_cents"]) * pct)
    deposit_floor = booking["deposit_due_cents"]
    if booking["insurance_opt_in"]:
        penalty = deposit_floor
    else:
        penalty = max(base_penalty, deposit_floor)
    booking["penalty_charged_cents"] = penalty
    refund_amt = max(0, booking["amount_paid_cents"] - penalty)
    _create_refund(booking, refund_amt)
    booking["payment_status"] = "REFUNDED"
    _void_issued_vouchers(booking)
    for p in _passengers_of(booking["id"]):
        p["seat_no"] = None
        p["room_no"] = None
        touch(p)
    booking["reservation_status"] = "CANCELLED"
    touch(booking)
    recompute_departure(dep)
    recompute_hotel_blocks(dep["id"])
    return booking


# =====================================================================
# Departure lifecycle
# =====================================================================

def _parse_date(s):
    return date.fromisoformat(s)


def _clock_date():
    # clock is an ISO instant; take the date portion (handles trailing Z / offsets)
    s = db.clock
    return date.fromisoformat(s[:10])


def publish_departure(dep):
    if dep["status"] in ("CANCELLED", "SETTLED"):
        raise ApiError("ERR_DEPARTURE_TERMINAL")
    if dep["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE")
    if not dep["itinerary_days"]:
        raise ApiError("ERR_VALIDATION", "Departure requires at least one itinerary day")
    dep["status"] = "OPEN"
    touch(dep)
    return dep


def _release_resource(dep, field, collection):
    rid = dep[field]
    if rid and rid in collection:
        res = collection[rid]
        if res["status"] != "AVAILABLE":
            res["status"] = "AVAILABLE"
            touch(res)


def _dates_overlap(dep_a, dep_b, buffer_days=0, half_open=False):
    s1, e1 = _parse_date(dep_a["start_date"]), _parse_date(dep_a["end_date"])
    s2, e2 = _parse_date(dep_b["start_date"]), _parse_date(dep_b["end_date"])
    if half_open:
        return s1 < e2 and s2 < e1
    buf = timedelta(days=buffer_days)
    return s1 <= (e2 + buf) and s2 <= (e1 + buf)


def assign_resource(dep, resource_kind, resource_id, expected_version):
    # priority 5: departure terminal
    if dep["status"] in ("CANCELLED", "SETTLED"):
        raise ApiError("ERR_DEPARTURE_TERMINAL")

    if resource_kind == "DRIVER":
        # priority 9: DOT hours
        for day in dep["itinerary_days"]:
            hours = day.get("planned_drive_hours", 0) if isinstance(day, dict) else 0
            if hours > calc.DOT_MAX_DRIVE_HOURS_PER_DAY:
                raise ApiError("ERR_DOT_HOURS_EXCEEDED")
        # priority 11: driver overlap (inclusive, no buffer)
        for other in db.departures.values():
            if other["id"] == dep["id"] or other["status"] == "CANCELLED":
                continue
            if other["driver_id"] == resource_id and _dates_overlap(dep, other):
                raise ApiError("ERR_DRIVER_OVERLAP")
    elif resource_kind == "COACH":
        # priority 10: coach overlap with turnaround buffer
        for other in db.departures.values():
            if other["id"] == dep["id"] or other["status"] == "CANCELLED":
                continue
            if other["coach_id"] == resource_id and _dates_overlap(
                dep, other, buffer_days=calc.TURNAROUND_BUFFER_DAYS
            ):
                raise ApiError("ERR_COACH_OVERLAP")
    elif resource_kind == "GUIDE":
        # priority 12: guide overlap (half-open)
        for other in db.departures.values():
            if other["id"] == dep["id"] or other["status"] == "CANCELLED":
                continue
            if other["guide_id"] == resource_id and _dates_overlap(dep, other, half_open=True):
                raise ApiError("ERR_GUIDE_OVERLAP")

    # priority 22 (last): optimistic concurrency
    if expected_version != dep["version"]:
        raise ApiError("ERR_STALE_DEPARTURE_VERSION")

    # apply
    field, collection = {
        "COACH": ("coach_id", db.coaches),
        "DRIVER": ("driver_id", db.drivers),
        "GUIDE": ("guide_id", db.guides),
    }[resource_kind]
    prior = dep[field]
    if prior and prior != resource_id and prior in collection:
        collection[prior]["status"] = "AVAILABLE"
        touch(collection[prior])
    dep[field] = resource_id
    res = collection[resource_id]
    if res["status"] != "ASSIGNED":
        res["status"] = "ASSIGNED"
        touch(res)
    touch(dep)
    return dep


def depart_departure(dep):
    if dep["status"] in ("CANCELLED", "SETTLED"):
        raise ApiError("ERR_DEPARTURE_TERMINAL")
    if dep["status"] != "GUARANTEED":
        raise ApiError("ERR_INVALID_STATE")
    if not (dep["coach_id"] and dep["driver_id"] and dep["guide_id"]):
        raise ApiError("ERR_DEPARTURE_NOT_ASSIGNED")
    dep["status"] = "DEPARTED"
    band = calc.band_for_pax(dep["confirmed_pax"])
    dep["occupancy_band"] = band
    tp = db.tour_products[dep["tour_product_id"]]
    final_pp = calc.per_person_price(tp["base_price_per_person_cents"], band)
    for b in db.bookings.values():
        if b["departure_id"] == dep["id"] and b["reservation_status"] == "CONFIRMED":
            b["reservation_status"] = "TRAVELED"
            b["final_per_person_cents"] = final_pp
            touch(b)
    touch(dep)
    return dep


def settle_departure(dep):
    if dep["status"] in ("CANCELLED", "SETTLED"):
        raise ApiError("ERR_DEPARTURE_TERMINAL")
    if dep["status"] != "DEPARTED":
        raise ApiError("ERR_INVALID_STATE")
    for b in db.bookings.values():
        if b["departure_id"] == dep["id"] and b["reservation_status"] == "TRAVELED":
            if b["amount_paid_cents"] < b["booking_total_cents"]:
                raise ApiError("ERR_BALANCE_UNPAID")
    result = compute_settlement(dep, final=True)
    dep["settlement_net_cents"] = result["net_cents"]
    dep["status"] = "SETTLED"
    _release_resource(dep, "coach_id", db.coaches)
    _release_resource(dep, "driver_id", db.drivers)
    _release_resource(dep, "guide_id", db.guides)
    touch(dep)
    return dep


def cancel_departure(dep, reason):
    if dep["status"] in ("CANCELLED", "SETTLED"):
        raise ApiError("ERR_DEPARTURE_TERMINAL")
    if dep["status"] not in ("OPEN", "GUARANTEED"):
        raise ApiError("ERR_INVALID_STATE")
    for b in list(db.bookings.values()):
        if b["departure_id"] != dep["id"]:
            continue
        if b["reservation_status"] not in ("DRAFT", "CONFIRMED"):
            continue
        b["cancel_reason"] = reason
        b["penalty_charged_cents"] = 0
        if b["amount_paid_cents"] > 0:
            _create_refund(b, b["amount_paid_cents"])
        b["payment_status"] = "REFUNDED"
        _void_issued_vouchers(b)
        for p in _passengers_of(b["id"]):
            p["seat_no"] = None
            p["room_no"] = None
            touch(p)
        b["reservation_status"] = "CANCELLED"
        touch(b)
    # recompute derived counts (all committed rooms/seats released)
    dep["confirmed_pax"] = _confirmed_pax(dep["id"])
    dep["occupancy_band"] = calc.band_for_pax(dep["confirmed_pax"])
    recompute_hotel_blocks(dep["id"])
    _release_resource(dep, "coach_id", db.coaches)
    _release_resource(dep, "driver_id", db.drivers)
    _release_resource(dep, "guide_id", db.guides)
    dep["status"] = "CANCELLED"
    touch(dep)
    return dep


# =====================================================================
# Hotel block transitions
# =====================================================================

def confirm_hotel_block(blk):
    dep = db.departures[blk["departure_id"]]
    if dep["status"] in ("CANCELLED", "SETTLED"):
        raise ApiError("ERR_DEPARTURE_TERMINAL")
    if blk["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE")
    blk["status"] = "CONFIRMED"
    # freeze block_cost at confirmation time
    blk["block_cost_cents"] = blk["rooms_committed"] * blk["nights"] * blk["rate_per_room_night_cents"]
    touch(blk)
    return blk


def release_hotel_block(blk):
    if blk["status"] == "RELEASED":
        raise ApiError("ERR_INVALID_STATE")
    blk["status"] = "RELEASED"
    touch(blk)
    return blk


# =====================================================================
# Voucher
# =====================================================================

def redeem_voucher(v):
    if v["status"] != "ISSUED":
        raise ApiError("ERR_VOUCHER_NOT_ISSUED")
    v["status"] = "REDEEMED"
    v["redeemed_at"] = db.clock
    touch(v)
    return v


# =====================================================================
# Computed views
# =====================================================================

def compute_settlement(dep, final):
    tp = db.tour_products[dep["tour_product_id"]]
    duration = tp["duration_days"]
    crew = 0
    if dep["coach_id"] and dep["coach_id"] in db.coaches:
        crew += db.coaches[dep["coach_id"]]["day_rate_cents"] * duration
    if dep["driver_id"] and dep["driver_id"] in db.drivers:
        crew += db.drivers[dep["driver_id"]]["day_rate_cents"] * duration
    if dep["guide_id"] and dep["guide_id"] in db.guides:
        crew += db.guides[dep["guide_id"]]["day_rate_cents"] * duration
    hotel = sum(
        b["block_cost_cents"]
        for b in db.hotel_blocks.values()
        if b["departure_id"] == dep["id"] and b["status"] == "CONFIRMED"
    )
    bookings = [b for b in db.bookings.values() if b["departure_id"] == dep["id"]]
    vouchers = [
        v
        for v in db.vouchers.values()
        if v["booking_id"] in db.bookings
        and db.bookings[v["booking_id"]]["departure_id"] == dep["id"]
    ]
    if final:
        revenue = sum(
            b["final_per_person_cents"] * b["pax_count"]
            + b["service_fee_cents"]
            + b["insurance_premium_cents"]
            for b in bookings
            if b["reservation_status"] == "TRAVELED"
        )
        voucher_cost = sum(v["face_value_cents"] for v in vouchers if v["status"] == "REDEEMED")
    else:
        revenue = sum(
            b["booking_total_cents"] for b in bookings if b["reservation_status"] == "CONFIRMED"
        )
        voucher_cost = sum(v["face_value_cents"] for v in vouchers if v["status"] == "ISSUED")
    cost = crew + hotel + voucher_cost
    return {"revenue_cents": revenue, "cost_cents": cost, "net_cents": revenue - cost}


def settlement_view(dep):
    if dep["status"] in ("DEPARTED", "SETTLED"):
        variant = "final"
        res = compute_settlement(dep, final=True)
    else:
        variant = "provisional"
        res = compute_settlement(dep, final=False)
    return {"departure_id": dep["id"], "variant": variant, **res}


def manifest_view(dep):
    bookings = [
        b
        for b in db.bookings.values()
        if b["departure_id"] == dep["id"] and b["reservation_status"] in ("CONFIRMED", "TRAVELED")
    ]
    bids = {b["id"] for b in bookings}
    passengers = [p for p in db.passengers.values() if p["booking_id"] in bids]
    vouchers = [v for v in db.vouchers.values() if v["booking_id"] in bids]
    rooming = [
        {
            "passenger_id": p["id"],
            "room_no": p["room_no"],
            "roommate_passenger_id": p.get("roommate_passenger_id"),
        }
        for p in passengers
    ]
    return {
        "departure_id": dep["id"],
        "confirmed_pax": dep["confirmed_pax"],
        "passengers": [serialize(p) for p in passengers],
        "rooming": rooming,
        "vouchers": [serialize(v) for v in vouchers],
    }


# =====================================================================
# List helper
# =====================================================================

def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
