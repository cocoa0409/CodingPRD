"""Business logic: derived counters, pinned calculations, cascades.

Every mutation bumps version/updated_at on common-fields resources.
BookingPassenger and CruiseCredit carry only id + created_at (PRD section 2.5).
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from util import touch

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------
HOLIDAY_PREMIUM_CENTS = 1500
PEAK_MULT = Decimal("1.25")
SHOULDER_MULT = Decimal("1.10")
OFF_MULT = Decimal("1.00")
HOLIDAY_DATES = {
    date(2026, 7, 4), date(2026, 9, 7), date(2026, 12, 25), date(2026, 12, 31),
}

GRATUITY_PCT = Decimal("0.18")

GALLEY_RESTOCK_REBATE_CENTS = 300
CREDIT_PROCESSING_FEE_CENTS = 450
TIER_1_HOURS = 72
TIER_2_HOURS = 24
TIER_3_HOURS = 6

CHARTER_PRICE_SMALL = 350000
CHARTER_PRICE_MEDIUM = 620000
CHARTER_PRICE_LARGE = 980000
CHARTER_CONVERSION_FEE_PCT = Decimal("0.12")
MAX_QUOTE_ROUNDS = 6
QUOTE_TTL_HOURS = 48

TURNAROUND_MIN = 45


def _round0(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round2(x):
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def season_of(dt):
    if dt.month in (6, 7, 8):
        return "PEAK"
    if dt.month in (5, 9):
        return "SHOULDER"
    return "OFF"


def season_multiplier(season):
    return {"PEAK": PEAK_MULT, "SHOULDER": SHOULDER_MULT, "OFF": OFF_MULT}[season]


def is_holiday_date(dt):
    return dt.date() in HOLIDAY_DATES


def is_minor_dob(dob, depart_at):
    """Age < 21 at the cruise's scheduled departure instant (PRD section 3.3).
    Reads depart_at, never the clock."""
    try:
        ref = date(depart_at.year, dob.month, dob.day)
    except ValueError:  # Feb 29 birthday on a non-leap departure year
        ref = date(depart_at.year, 2, 28)
    if dob > ref:
        ref = date(ref.year - 1, ref.month, ref.day)
    return (ref.year - dob.year) < 21


# ---------------------------------------------------------------------------
# Ticket and bar pricing (pinned rounding order: discount -> seasonal -> holiday)
# ---------------------------------------------------------------------------

def party_discount_pct(party_size):
    if party_size >= 10:
        return Decimal("0.15")
    if party_size >= 6:
        return Decimal("0.10")
    if party_size >= 4:
        return Decimal("0.05")
    return Decimal("0")


def compute_booking_totals(cruise, party_size, bar_package_count):
    menu_tier = db.menu_tiers[cruise["menu_tier_id"]]
    line = Decimal(party_size) * Decimal(menu_tier["base_price_cents"])
    discounted = _round0(line * (Decimal(1) - party_discount_pct(party_size)))
    seasonal = _round0(Decimal(discounted) * season_multiplier(cruise["season"]))
    total = seasonal
    if cruise["is_holiday"]:
        total = seasonal + party_size * HOLIDAY_PREMIUM_CENTS
    gratuity_line = _round0(Decimal(menu_tier["bar_package_price_cents"]) * GRATUITY_PCT)
    per_package = menu_tier["bar_package_price_cents"] + gratuity_line
    bar_total = per_package * bar_package_count
    return total, bar_total


def compute_charter_quote(cruise):
    vessel = db.vessels[cruise["vessel_id"]]
    capacity = vessel["coast_guard_capacity"]
    if capacity <= 49:
        base = CHARTER_PRICE_SMALL
    elif capacity <= 99:
        base = CHARTER_PRICE_MEDIUM
    else:
        base = CHARTER_PRICE_LARGE
    return _round0(Decimal(base) * season_multiplier(cruise["season"]))


# ---------------------------------------------------------------------------
# Derived counters (each recomputation bumps the owning resource's version)
# ---------------------------------------------------------------------------

def recompute_reserved_covers(cruise):
    total = 0
    for b in db.bookings.values():
        if (b["cruise_id"] == cruise["id"]
                and b["booking_status"] in ("RESERVED", "CONFIRMED", "BOARDED")
                and b["payment_status"] in ("PENDING", "PAID", "REFUND_PENDING")):
            total += b["party_size"]
    cruise["reserved_covers"] = total
    touch(cruise)


def recompute_boarded_count(cruise):
    count = 0
    for p in db.passengers.values():
        b = db.bookings.get(p["booking_id"])
        if b is not None and b["cruise_id"] == cruise["id"] and p["boarded_at"] is not None:
            count += 1
    cruise["boarded_count"] = count
    touch(cruise)


def recompute_bar_service(cruise):
    enabled = False
    for a in db.assignments.values():
        if a["cruise_id"] == cruise["id"] and a["status"] == "CONFIRMED":
            sm = db.staff_members.get(a["staff_member_id"])
            expires = sm.get("alcohol_cert_expires_at") if sm else None
            if expires is not None and clock.parse_dt(expires) > clock.now():
                enabled = True
                break
    cruise["bar_service_enabled"] = enabled
    touch(cruise)


def recompute_parking_in_use(dock):
    count = 0
    for p in db.parking_passes.values():
        if p["dock_id"] == dock["id"] and p["status"] in ("RESERVED", "REDEEMED"):
            count += 1
    dock["parking_in_use"] = count
    touch(dock)


def recompute_customer_balance(customer):
    total = 0
    for c in db.credits.values():
        if c["customer_id"] != customer["id"]:
            continue
        if c["credit_status"] == "ISSUED":
            total += c["amount_cents"]
        elif c["credit_status"] == "SETTLED":
            total += c["final_amount_cents"]
    customer["credit_balance_cents"] = total
    touch(customer)


def manifest_for_cruise(cruise_id):
    for m in db.manifests.values():
        if m["cruise_id"] == cruise_id:
            return m
    return None


def refresh_manifest_count(manifest):
    """Only while the manifest is DRAFT (PRD section 2.10); frozen holds a snapshot."""
    if manifest["status"] != "DRAFT":
        return
    count = 0
    for p in db.passengers.values():
        b = db.bookings.get(p["booking_id"])
        if b is not None and b["cruise_id"] == manifest["cruise_id"] and p["boarded_at"] is not None:
            count += 1
    manifest["passenger_count"] = count
    touch(manifest)


# ---------------------------------------------------------------------------
# Weather helpers
# ---------------------------------------------------------------------------

def weather_events_covering(cruise):
    """Weather events whose window covers the cruise's depart_at."""
    depart = clock.parse_dt(cruise["depart_at"])
    out = []
    for e in db.weather_events.values():
        if clock.parse_dt(e["window_start"]) <= depart <= clock.parse_dt(e["window_end"]):
            out.append(e)
    return out


def covering_cancellation_event(cruise):
    for e in weather_events_covering(cruise):
        if e["severity"] == "CANCELLATION_REQUIRED" and e["status"] in ("DECLARED", "CANCELLATION_ISSUED"):
            return e
    return None


def hold_covered_cruises(event):
    """On declaration of a CANCELLATION_REQUIRED event: hold covered SCHEDULED cruises."""
    if event["severity"] != "CANCELLATION_REQUIRED":
        return
    ws, we = clock.parse_dt(event["window_start"]), clock.parse_dt(event["window_end"])
    for c in db.cruises.values():
        if c["status"] == "SCHEDULED" and ws <= clock.parse_dt(c["depart_at"]) <= we:
            c["status"] = "WEATHER_HOLD"
            touch(c)


def cruises_cancelled_under(event):
    out = []
    for c in db.cruises.values():
        if c.get("cancelled_by_event_id") == event["id"]:
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# Automatic time-based transitions (evaluated after every clock set)
# ---------------------------------------------------------------------------

def process_auto_transitions():
    """Quote TTL expiry for QUOTED inquiries whose quote instant has lapsed,
    plus bar-service eligibility re-evaluated against the new clock reading
    (PRD 2.4: setting the clock re-evaluates all time-based transitions;
    PRD 3.4: advancing time can silently flip bar_service_enabled)."""
    now = clock.now()
    for inq in db.inquiries.values():
        if inq["status"] == "QUOTED" and inq.get("quoted_at_dt") is not None:
            if now > inq["quoted_at_dt"] + timedelta(hours=QUOTE_TTL_HOURS):
                inq["status"] = "EXPIRED"
                touch(inq)
    for c in db.cruises.values():
        recompute_bar_service(c)


# ---------------------------------------------------------------------------
# Weather credit calculation (provisional and final variants)
# ---------------------------------------------------------------------------

def _hours_notice(cruise):
    delta = clock.parse_dt(cruise["depart_at"]) - clock.now()
    return int(delta.total_seconds() // 3600)


def _credit_pct(hours_notice):
    if hours_notice >= TIER_1_HOURS:
        return Decimal("1.00")
    if hours_notice >= TIER_2_HOURS:
        return Decimal("0.75")
    if hours_notice >= TIER_3_HOURS:
        return Decimal("0.50")
    return Decimal("0.25")


def compute_provisional_credit(cruise, booking):
    return _round0(Decimal(booking["booking_total_cents"]) * _credit_pct(_hours_notice(cruise)))


def compute_final_credit(cruise, booking, order_was_placed, provisional_covers):
    base = _round0(Decimal(booking["booking_total_cents"]) * _credit_pct(_hours_notice(cruise)))
    if order_was_placed:
        base += GALLEY_RESTOCK_REBATE_CENTS * provisional_covers
    return base - CREDIT_PROCESSING_FEE_CENTS


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def weather_cancel_cascade(cruise):
    """Six-part atomic cascade per PRD section 3.8."""
    now_z = clock.to_z(clock.now())

    affected = []
    for b in db.bookings.values():
        # Bookings already cancelled by their customers are untouched (PRD 3.8);
        # an unpaid customer-cancelled booking still stands at PENDING, so the
        # payment filter alone would wrongly sweep it.
        if (b["cruise_id"] == cruise["id"]
                and b["payment_status"] in ("PENDING", "PAID")
                and b["booking_status"] != "CANCELLED"):
            affected.append(b)

    event = covering_cancellation_event(cruise)

    # 1-2. bookings -> CANCELLED/REFUND_PENDING + provisional CruiseCredit per booking
    for b in affected:
        b["payment_status"] = "REFUND_PENDING"
        b["booking_status"] = "CANCELLED"
        b["cancelled_by_event_id"] = event["id"]
        touch(b)
        db.insert(db.credits, {
            "id": db.new_id(),
            "created_at": now_z,
            "customer_id": b["customer_id"],
            "booking_id": b["id"],
            "amount_cents": compute_provisional_credit(cruise, b),
            "final_amount_cents": None,
            "credit_status": "ISSUED",
        })

    # 3. provision order: DRAFT/PLACED -> CANCELLED; rebate when it stood at PLACED
    for o in db.provision_orders.values():
        if o["cruise_id"] == cruise["id"] and o["status"] in ("DRAFT", "PLACED"):
            if o["status"] == "PLACED":
                o["restocking_rebate_cents"] = GALLEY_RESTOCK_REBATE_CENTS * o["provisional_covers"]
                o["was_placed_at_cancel"] = True
            o["status"] = "CANCELLED"
            touch(o)

    # 4. driving weather event -> CANCELLATION_ISSUED (first cancel beneath it)
    if event["status"] == "DECLARED":
        event["status"] = "CANCELLATION_ISSUED"
        touch(event)

    # 5. RESERVED parking passes -> RELEASED, dock parking_in_use decremented
    affected_docks = {}
    for p in db.parking_passes.values():
        if p["cruise_id"] == cruise["id"] and p["status"] == "RESERVED":
            p["status"] = "RELEASED"
            touch(p)
            dock = db.docks.get(p["dock_id"])
            if dock is not None:
                affected_docks[dock["id"]] = dock

    # 6. staff assignments ASSIGNED/CONFIRMED -> RELEASED
    for a in db.assignments.values():
        if a["cruise_id"] == cruise["id"] and a["status"] in ("ASSIGNED", "CONFIRMED"):
            a["status"] = "RELEASED"
            touch(a)

    cruise["status"] = "CANCELLED"
    cruise["cancelled_by_event_id"] = event["id"]
    touch(cruise)

    for dock in affected_docks.values():
        recompute_parking_in_use(dock)
    recompute_bar_service(cruise)
    recompute_reserved_covers(cruise)
    for cid in {b["customer_id"] for b in affected}:
        cust = db.customers.get(cid)
        if cust is not None:
            recompute_customer_balance(cust)


def depart_cascade(cruise):
    """Departure side effects: no-shows stranded, RESERVED passes expired."""
    now_z = clock.to_z(clock.now())
    for b in db.bookings.values():
        if (b["cruise_id"] == cruise["id"]
                and b["payment_status"] == "PAID"
                and b["booking_status"] == "CONFIRMED"):
            pax = [p for p in db.passengers.values() if p["booking_id"] == b["id"]]
            if all(p["boarded_at"] is None for p in pax):
                b["booking_status"] = "NO_SHOW"
                touch(b)
    affected_docks = {}
    for p in db.parking_passes.values():
        if p["cruise_id"] == cruise["id"] and p["status"] == "RESERVED":
            p["status"] = "EXPIRED"
            touch(p)
            dock = db.docks.get(p["dock_id"])
            if dock is not None:
                affected_docks[dock["id"]] = dock
    cruise["status"] = "UNDERWAY"
    touch(cruise)
    for dock in affected_docks.values():
        recompute_parking_in_use(dock)
    recompute_reserved_covers(cruise)
    cruise["departed_at"] = now_z
    touch(cruise)


def complete_cascade(cruise):
    """Completion: manifest FILED, provision order SETTLED with final covers,
    CONFIRMED bookings with zero boarded passengers -> NO_SHOW."""
    manifest = manifest_for_cruise(cruise["id"])
    if manifest is not None and manifest["status"] == "FROZEN":
        manifest["status"] = "FILED"
        touch(manifest)

    boarded = 0
    for p in db.passengers.values():
        b = db.bookings.get(p["booking_id"])
        if b is not None and b["cruise_id"] == cruise["id"] and p["boarded_at"] is not None:
            boarded += 1
    crew = sum(1 for a in db.assignments.values()
               if a["cruise_id"] == cruise["id"] and a["status"] == "CONFIRMED")

    for o in db.provision_orders.values():
        if o["cruise_id"] == cruise["id"] and o["status"] in ("PLACED", "RECEIVED"):
            o["status"] = "SETTLED"
            o["final_covers"] = boarded + crew
            touch(o)

    for b in db.bookings.values():
        if b["cruise_id"] == cruise["id"] and b["booking_status"] == "CONFIRMED":
            pax = [p for p in db.passengers.values() if p["booking_id"] == b["id"]]
            if all(p["boarded_at"] is None for p in pax):
                b["booking_status"] = "NO_SHOW"
                touch(b)

    cruise["status"] = "COMPLETED"
    touch(cruise)
    recompute_reserved_covers(cruise)


def settle_credits_cascade(event):
    """Settle every REFUND_PENDING booking of cruises cancelled under this event."""
    cruises = cruises_cancelled_under(event)
    affected_customers = set()
    for c in cruises:
        order_placed = False
        provisional_covers = 0
        for o in db.provision_orders.values():
            if o["cruise_id"] == c["id"] and o.get("was_placed_at_cancel"):
                order_placed = True
                provisional_covers = o["provisional_covers"]
                break
        for b in db.bookings.values():
            if b["cruise_id"] != c["id"] or b["payment_status"] != "REFUND_PENDING":
                continue
            final_amount = compute_final_credit(c, b, order_placed, provisional_covers)
            for cr in db.credits.values():
                if cr["booking_id"] == b["id"] and cr["credit_status"] == "ISSUED":
                    cr["final_amount_cents"] = final_amount
                    cr["credit_status"] = "SETTLED"
            b["payment_status"] = "CREDITED"
            touch(b)
            affected_customers.add(b["customer_id"])
    event["status"] = "CREDITS_SETTLED"
    touch(event)
    for cid in affected_customers:
        cust = db.customers.get(cid)
        if cust is not None:
            recompute_customer_balance(cust)
    for c in cruises:
        recompute_reserved_covers(c)


def charter_convert_cascade(inquiry, cruise):
    """Charter conversion per PRD section 3.9."""
    now_z = clock.to_z(clock.now())
    vessel = db.vessels[cruise["vessel_id"]]
    customer_id = inquiry["customer_id"]

    charter_booking = {
        "id": db.new_id(),
        "created_at": now_z,
        "updated_at": now_z,
        "version": 1,
        "cruise_id": cruise["id"],
        "customer_id": customer_id,
        "party_size": vessel["coast_guard_capacity"],
        "booking_total_cents": inquiry["quoted_total_cents"],
        "bar_package_count": 0,
        "bar_package_total_cents": 0,
        "payment_status": "PAID",
        "booking_status": "CONFIRMED",
        "is_charter_booking": True,
    }
    db.insert(db.bookings, charter_booking)
    cruise["charter_booking_id"] = charter_booking["id"]

    converted_customers = set()
    for b in db.bookings.values():
        if (b["cruise_id"] == cruise["id"] and b["id"] != charter_booking["id"]
                and b["booking_status"] in ("RESERVED", "CONFIRMED")):
            b["booking_status"] = "CONVERTED_TO_CHARTER"
            if b["payment_status"] == "PAID":
                b["payment_status"] = "CREDITED"
                amount = _round0(Decimal(b["booking_total_cents"]) * (Decimal(1) - CHARTER_CONVERSION_FEE_PCT))
                db.insert(db.credits, {
                    "id": db.new_id(),
                    "created_at": now_z,
                    "customer_id": b["customer_id"],
                    "booking_id": b["id"],
                    "amount_cents": amount,
                    "final_amount_cents": None,
                    "credit_status": "ISSUED",
                })
                converted_customers.add(b["customer_id"])
            touch(b)

    inquiry["status"] = "CONVERTED"
    touch(inquiry)
    touch(cruise)
    recompute_reserved_covers(cruise)
    for cid in converted_customers:
        cust = db.customers.get(cid)
        if cust is not None:
            recompute_customer_balance(cust)
