"""Business logic: calculations (scaffold §1.3), cascades, and clock sweeps.

All money math uses Decimal with ROUND_HALF_UP. Rounding order is pinned:
rental lines are rounded per line then summed; tune quotes round once after
both multipliers; DIN rounds to the nearest 0.25 step after clamping.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import db, now, now_iso, parse_date, parse_dt, touch


def rhu(x):
    """Round-half-up to whole cents (integer)."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def full_years(dob, on):
    """Full years between a birth date and a later date."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


# ---------------------------------------------------------------------------
# fitment_din
# ---------------------------------------------------------------------------

def compute_din(cust, on_date=None):
    on_date = on_date or now().date()
    base = (Decimal("0.5")
            + Decimal(str(cust["weight_kg"])) * Decimal("0.06")
            + Decimal(str(cust["height_cm"])) * Decimal("0.005"))
    type_adj = {"TYPE_1": Decimal("-0.5"), "TYPE_2": Decimal("0"),
                "TYPE_3": Decimal("0.75")}[cust["skier_type"]]
    age = full_years(parse_date(cust["date_of_birth"]), on_date)
    if age < 10:
        age_adj = Decimal("-0.75")
    elif age <= 49:
        age_adj = Decimal("0")
    else:
        age_adj = Decimal("-0.5")
    sole_adj = (Decimal(cust["boot_sole_mm"]) - Decimal(285)) * Decimal("0.01")
    raw = base + type_adj + age_adj + sole_adj
    raw = max(Decimal("0.75"), min(Decimal("12.0"), raw))
    steps = (raw / Decimal("0.25")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(steps * Decimal("0.25"))


# ---------------------------------------------------------------------------
# rental_charge
# ---------------------------------------------------------------------------

def rental_discount(planned_days):
    if planned_days >= 14:
        return Decimal("0.20")
    if planned_days >= 7:
        return Decimal("0.10")
    return Decimal("0")


def planned_days_of(res):
    return (parse_date(res["end_date"]) - parse_date(res["start_date"])).days + 1


def items_of(reservation_id):
    return sorted(
        (i for i in db.reservation_items.values() if i["reservation_id"] == reservation_id),
        key=lambda i: i["_seq"],
    )


def recompute_quote(res):
    """Provisional variant: per-line round then sum, over ASSIGNED items."""
    total = 0
    for it in items_of(res["id"]):
        if it["status"] == "ASSIGNED":
            total += rhu(Decimal(it["planned_days"]) * Decimal(it["daily_rate_cents"])
                         * (Decimal(1) - rental_discount(it["planned_days"])))
    res["quoted_total_cents"] = total
    res["deposit_minimum_cents"] = rhu(Decimal("0.20") * Decimal(total))


# ---------------------------------------------------------------------------
# Occupancy windows + assignment / release / waitlist promotion
# ---------------------------------------------------------------------------

def occupancy_conflict(unit_id, start_date, end_date, exclude_item_id=None):
    """Closed date windows with a mandatory 1 free day between windows."""
    s = parse_date(start_date) if isinstance(start_date, str) else start_date
    e = parse_date(end_date) if isinstance(end_date, str) else end_date
    for it in db.reservation_items.values():
        if it["equipment_item_id"] != unit_id or it["status"] != "ASSIGNED":
            continue
        if exclude_item_id and it["id"] == exclude_item_id:
            continue
        r = db.reservations[it["reservation_id"]]
        s2 = parse_date(r["start_date"])
        e2 = parse_date(r["end_date"])
        # OK only if the new window starts at least 2 dates after the existing
        # window ends, or the existing window starts at least 2 dates after
        # the new window ends.
        if s > e2 + timedelta(days=1) or s2 > e + timedelta(days=1):
            continue
        return True
    return False


def assign_item(item, unit, din):
    """QUEUED -> ASSIGNED with snapshots; unit AVAILABLE -> RESERVED."""
    item["status"] = "ASSIGNED"
    item["equipment_item_id"] = unit["id"]
    item["daily_rate_cents"] = unit["base_daily_rate_cents"]
    item["din_setting"] = din
    item["assigned_at"] = now_iso()
    touch(item)
    unit["status"] = "RESERVED"
    touch(unit)
    res = db.reservations[item["reservation_id"]]
    recompute_quote(res)
    touch(res)


def unit_eligible(unit, item, res, din):
    if unit["gear_type"] != item["gear_type_requested"]:
        return False
    if unit["tier"] != item["tier_requested"]:
        return False
    if not (unit["din_min"] <= din <= unit["din_max"]):
        return False
    if occupancy_conflict(unit["id"], res["start_date"], res["end_date"],
                          exclude_item_id=item["id"]):
        return False
    return True


def try_promote(unit):
    """Waitlist promotion: oldest-created compatible QUEUED line gets the unit."""
    candidates = sorted(
        (i for i in db.reservation_items.values() if i["status"] == "QUEUED"),
        key=lambda i: (i["created_at"], i["_seq"]),
    )
    for item in candidates:
        res = db.reservations[item["reservation_id"]]
        if res["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
            continue
        cust = db.customers[res["customer_id"]]
        din = compute_din(cust)
        if not unit_eligible(unit, item, res, din):
            continue
        assign_item(item, unit, din)
        return True
    return False


def release_item(item):
    """ASSIGNED -> RELEASED; free the unit when no assigned window remains,
    then run waitlist promotion on the freed unit."""
    unit = db.equipment_items.get(item["equipment_item_id"])
    item["status"] = "RELEASED"
    touch(item)
    res = db.reservations[item["reservation_id"]]
    recompute_quote(res)
    touch(res)
    if unit is None or unit["status"] != "RESERVED":
        return
    still_assigned = any(
        i["equipment_item_id"] == unit["id"] and i["status"] == "ASSIGNED"
        for i in db.reservation_items.values()
    )
    if not still_assigned:
        unit["status"] = "AVAILABLE"
        touch(unit)
        try_promote(unit)


# ---------------------------------------------------------------------------
# customer_standing (+ BARRED -> lease suspension cascade)
# ---------------------------------------------------------------------------

def recompute_standing(customer_id):
    cust = db.customers.get(customer_id)
    if cust is None:
        return
    unpaid = []
    for a in db.damage_assessments.values():
        if a["status"] != "INVOICED":
            continue
        res = db.reservations.get(a["reservation_id"])
        if res is not None and res["customer_id"] == customer_id:
            unpaid.append(a)
    if any(a["severity"] == "TOTAL_LOSS" for a in unpaid):
        new = "BARRED"
    elif unpaid or cust["late_return_count"] >= 3:
        new = "WATCH"
    else:
        new = "GOOD_STANDING"
    if new != cust["standing"]:
        cust["standing"] = new
        touch(cust)
    if new == "BARRED":
        for lease in db.season_leases.values():
            if lease["junior_customer_id"] == customer_id and lease["status"] == "ACTIVE":
                lease["status"] = "SUSPENDED"
                touch(lease)


# ---------------------------------------------------------------------------
# tune_quote + turnaround_scheduling
# ---------------------------------------------------------------------------

SERVICE_PRICE_CENTS = {"WAX": 2500, "EDGE_TUNE": 3000, "BASE_GRIND": 4500,
                       "BINDING_ADJUST": 2000}
SERVICE_LABOR_MINUTES = {"WAX": 45, "EDGE_TUNE": 60, "BASE_GRIND": 90,
                         "BINDING_ADJUST": 30}


def labor_minutes(services):
    return sum(SERVICE_LABOR_MINUTES[s] for s in services)


def tune_quote(ticket):
    subtotal = sum(SERVICE_PRICE_CENTS[s] for s in ticket["services"])
    subtotal += ticket["parts_surcharge_cents"]
    rush_mult = Decimal("1.5") if ticket["rush"] else Decimal("1")
    junior = any(
        l["junior_customer_id"] == ticket["customer_id"]
        and l["status"] in ("ACTIVE", "SUSPENDED")
        for l in db.season_leases.values()
    )
    junior_mult = Decimal("0.8") if junior else Decimal("1")
    price = rhu(Decimal(subtotal) * rush_mult * junior_mult)
    return price, junior


def capacity_for_date(d):
    key = d.isoformat() if not isinstance(d, str) else d
    for c in db.shop_day_capacity.values():
        if c["service_date"] == key:
            return c
    return None


# ---------------------------------------------------------------------------
# damage_charge
# ---------------------------------------------------------------------------

SEVERITY_PCT = {"COSMETIC": Decimal("0.10"), "MINOR": Decimal("0.25"),
                "MAJOR": Decimal("0.50"), "TOTAL_LOSS": Decimal("1.00")}


def damage_charge_cents(unit, severity):
    blocks = unit["accrued_rental_days"] // 30
    factor = max(Decimal("0.30"), Decimal(1) - Decimal("0.02") * blocks)
    depreciated = rhu(Decimal(unit["purchase_price_cents"]) * factor)
    severity_amt = SEVERITY_PCT[severity] * Decimal(unit["purchase_price_cents"])
    return rhu(min(severity_amt, Decimal(depreciated)))


# ---------------------------------------------------------------------------
# season_lease_buyout
# ---------------------------------------------------------------------------

def lease_buyouts(lease, unit):
    season_days = (parse_date(lease["season_end_date"])
                   - parse_date(lease["season_start_date"])).days
    activated_date = parse_dt(lease["activated_at"]).date()
    elapsed = (now().date() - activated_date).days
    elapsed = max(0, min(elapsed, season_days))
    price = Decimal(unit["purchase_price_cents"])
    sl_factor = max(Decimal("0.40"),
                    Decimal(1) - Decimal("0.5") * Decimal(elapsed) / Decimal(season_days))
    usage_factor = max(Decimal("0.40"),
                       Decimal(1) - Decimal("0.01") * Decimal(elapsed))
    straight = rhu(price * sl_factor)
    usage = rhu(price * usage_factor)
    return straight, usage, elapsed


# ---------------------------------------------------------------------------
# demo_upgrade_pricing helpers
# ---------------------------------------------------------------------------

def eligible_demo_credits(customer_id):
    credits = [
        c for c in db.demo_credits.values()
        if c["customer_id"] == customer_id
        and c["status"] == "ACTIVE"
        and parse_dt(c["expires_at"]) > now()
    ]
    return sorted(credits, key=lambda c: (c["created_at"], c["_seq"]))


# ---------------------------------------------------------------------------
# pickup_window_posture + clock sweeps
# ---------------------------------------------------------------------------

def window_end_dt(w):
    t = datetime.strptime(w["end_time"], "%H:%M").time()
    return datetime.combine(parse_date(w["service_date"]), t, tzinfo=timezone.utc)


def refresh_window(w):
    """Derived posture: CLOSED once now >= window end (BOOKED -> NO_SHOW),
    FULL when booked_count >= van_capacity, else OPEN. Touches only on change."""
    booked = sum(
        1 for b in db.pickup_bookings.values()
        if b["pickup_window_id"] == w["id"] and b["status"] == "BOOKED"
    )
    if now() >= window_end_dt(w):
        if w["posture"] != "CLOSED":
            for b in db.pickup_bookings.values():
                if b["pickup_window_id"] == w["id"] and b["status"] == "BOOKED":
                    b["status"] = "NO_SHOW"
                    touch(b)
            w["booked_count"] = 0
            w["posture"] = "CLOSED"
            touch(w)
        elif w["booked_count"] != booked:
            w["booked_count"] = booked
            touch(w)
    else:
        new_posture = "FULL" if booked >= w["van_capacity"] else "OPEN"
        if new_posture != w["posture"] or booked != w["booked_count"]:
            w["posture"] = new_posture
            w["booked_count"] = booked
            touch(w)


def run_sweeps():
    """Clock-driven system transitions: overdue reservations, credit expiry,
    window closure/no-shows. Runs on clock-set and lazily before each read."""
    today = now().date()
    for res in db.reservations.values():
        if (res["fulfillment_status"] == "ACTIVE"
                and today > parse_date(res["end_date"])):
            res["fulfillment_status"] = "OVERDUE"
            touch(res)
    for c in db.demo_credits.values():
        if c["status"] == "ACTIVE" and now() >= parse_dt(c["expires_at"]):
            c["status"] = "EXPIRED"
            touch(c)
    for w in db.pickup_windows.values():
        refresh_window(w)
