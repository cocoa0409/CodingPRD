"""Business logic: computed fields, pricing, settlement, selectors, scans,
cascades, and ops sweeps (SCAFFOLD §1.2/§1.3, PRD §3)."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import domain
from util import rhu_cents

NON_TERMINAL_BOOKING = ("BOOKED", "CHECKED_IN", "OVERSTAY")
NON_TERMINAL_INCIDENT = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING", "REOPENED")
STRIKE_WEIGHTS = {"NO_SHOW": 1, "EVICTION": 2}
TIER_RANK = {"STANDARD": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}
WEEKDAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

RATE_PLAN_DEFAULTS = {
    "tier2_pct": 60,
    "tier3_pct": 80,
    "tier4_pct": 95,
    "mult_low": 0.9,
    "mult_mid": 1.0,
    "mult_high": 1.25,
    "mult_max": 1.5,
    "peak_multiplier": 1.2,
    "peak_days": ["FRI", "SAT"],
}


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def night_interval(d):
    """Night d occupies [d 15:00Z, d+1 11:00Z)."""
    start = datetime.combine(d, time(15, 0), tzinfo=timezone.utc)
    end = datetime.combine(d + timedelta(days=1), time(11, 0), tzinfo=timezone.utc)
    return start, end


def booking_window(b):
    return b["checkin_open_at"], b["checkout_due_at"]


def entry_window(e):
    start = datetime.combine(e["arrival_date"], time(15, 0), tzinfo=timezone.utc)
    end = datetime.combine(e["arrival_date"] + timedelta(days=e["night_count"]),
                           time(11, 0), tzinfo=timezone.utc)
    return start, end


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap."""
    return a_start < b_end and b_start < a_end


def parse_date(value):
    """Parse YYYY-MM-DD into a date, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Derived driver state (PRD §3.3)
# --------------------------------------------------------------------------
def strikes_90d(driver):
    now = db.clock_now()
    cutoff = now - timedelta(days=90)
    return sum(STRIKE_WEIGHTS[e["kind"]] for e in driver["strike_events"]
               if e["at"] >= cutoff)


def driver_standing(driver):
    s = strikes_90d(driver)
    if s >= 3:
        return "SUSPENDED"
    if s == 2:
        return "PROBATION"
    return "GOOD"


def settled_nights_90d(driver_id):
    now = db.clock_now()
    cutoff = now - timedelta(days=90)
    total = 0
    for b in domain.all_of("bookings"):
        if (b["driver_id"] == driver_id and b["billing_status"] == "PAID"
                and b["checked_out_at"] is not None
                and b["checked_out_at"] >= cutoff):
            total += b["night_count"]
    return total


def loyalty_tier(settled_nights):
    if settled_nights >= 60:
        return "PLATINUM"
    if settled_nights >= 30:
        return "GOLD"
    if settled_nights >= 12:
        return "SILVER"
    return "STANDARD"


def loyalty_pct_for_tier(tier):
    return {"PLATINUM": 15, "GOLD": 10, "SILVER": 5}.get(tier, 0)


def driver_computed(driver):
    s = strikes_90d(driver)
    standing = "SUSPENDED" if s >= 3 else ("PROBATION" if s == 2 else "GOOD")
    nights = settled_nights_90d(driver["id"])
    return {
        "strikes_90d": s,
        "standing": standing,
        "settled_nights_90d": nights,
        "loyalty_tier": loyalty_tier(nights),
    }


# --------------------------------------------------------------------------
# Fleet derived state (PRD §3.9)
# --------------------------------------------------------------------------
def fleet_balance(fleet_id):
    total = 0
    for inv in domain.all_of("invoices"):
        if inv["fleet_account_id"] == fleet_id and inv["status"] != "WRITTEN_OFF":
            total += inv["net_cents"] - inv["paid_cents"]
    return total


def fleet_projected_exposure(fleet_id):
    """Balance + UNBILLED FLEET_BILL bookings (final where set, else quoted)."""
    total = fleet_balance(fleet_id)
    for b in domain.all_of("bookings"):
        if (b["fleet_account_id"] == fleet_id and b["payment_mode"] == "FLEET_BILL"
                and b["billing_status"] == "UNBILLED"):
            total += b["final_total_cents"] if b["final_total_cents"] is not None \
                else b["quoted_total_cents"]
    return total


def active_authorization(driver_id, fleet_id):
    for a in domain.all_of("driver_authorizations"):
        if (a["driver_id"] == driver_id and a["fleet_account_id"] == fleet_id
                and a["status"] == "ACTIVE"):
            return a
    return None


# --------------------------------------------------------------------------
# Site posture (derived, never stored — PRD §3.8)
# --------------------------------------------------------------------------
def site_posture(site_id):
    nonterm = [i for i in domain.all_of("incidents")
               if i["site_id"] == site_id and i["status"] in NON_TERMINAL_INCIDENT]
    if any(i["severity"] == "CRITICAL" for i in nonterm):
        return "ESCALATED"
    if sum(1 for i in nonterm if i["category"] == "LIGHTING") >= 3:
        return "DEGRADED"
    return "NORMAL"


# --------------------------------------------------------------------------
# Dynamic nightly pricing (PRD §3.2)
# --------------------------------------------------------------------------
def active_rate_plan(site_id):
    for p in domain.all_of("rate_plans"):
        if p["site_id"] == site_id and p["status"] == "ACTIVE":
            return p
    return None


def occupancy_counts(site_id, d, exclude_booking_id=None):
    stalls = [s for s in domain.all_of("stalls")
              if s["site_id"] == site_id and s["is_reservable"] and s["status"] == "ACTIVE"]
    n_start, n_end = night_interval(d)
    occupied = 0
    for s in stalls:
        for b in domain.all_of("bookings"):
            if (b["stall_id"] == s["id"] and b["status"] in NON_TERMINAL_BOOKING
                    and b["id"] != exclude_booking_id
                    and overlaps(b["checkin_open_at"], b["checkout_due_at"],
                                 n_start, n_end)):
                occupied += 1
                break
    return occupied, len(stalls)


def nightly_rate(site, plan, d):
    occupied, denom = occupancy_counts(site["id"], d)
    # Exact-ratio comparison: occupied/denom*100 vs tier pct (no floor division).
    if denom == 0 or occupied * 100 < plan["tier2_pct"] * denom:
        occ_mult = plan["mult_low"]
    elif occupied * 100 < plan["tier3_pct"] * denom:
        occ_mult = plan["mult_mid"]
    elif occupied * 100 < plan["tier4_pct"] * denom:
        occ_mult = plan["mult_high"]
    else:
        occ_mult = plan["mult_max"]
    if site_posture(site["id"]) == "DEGRADED":
        occ_mult = min(occ_mult, 1.0)
    peak_mult = plan["peak_multiplier"] \
        if WEEKDAY_CODES[d.weekday()] in plan["peak_days"] else 1.0
    rate = Decimal(site["base_nightly_rate_cents"]) * Decimal(str(occ_mult)) \
        * Decimal(str(peak_mult))
    return rhu_cents(rate)


def quote_nights(site, driver, booking_kind, arrival, night_count):
    """Pin per-night rates and compute the provisional quote (PRD §3.4)."""
    plan = active_rate_plan(site["id"])
    rates = []
    for i in range(night_count):
        d = arrival + timedelta(days=i)
        if booking_kind == "WALK_IN":
            rate = site["base_nightly_rate_cents"]
        else:
            rate = nightly_rate(site, plan, d)
        rates.append({"date": d, "rate_cents": rate})
    subtotal = sum(r["rate_cents"] for r in rates)
    if booking_kind == "WALK_IN":
        pct = 0
    else:
        tier = loyalty_tier(settled_nights_90d(driver["id"]))
        pct = loyalty_pct_for_tier(tier)
    discount = rhu_cents(Decimal(subtotal * pct) / Decimal(100))
    return rates, subtotal - discount


# --------------------------------------------------------------------------
# Stall selectors (PRD §3.2, §3.7)
# --------------------------------------------------------------------------
def stall_free_of_bookings(stall_id, window, exclude_booking_id=None):
    w_start, w_end = window
    for b in domain.all_of("bookings"):
        if (b["stall_id"] == stall_id and b["status"] in NON_TERMINAL_BOOKING
                and b["id"] != exclude_booking_id
                and overlaps(b["checkin_open_at"], b["checkout_due_at"],
                             w_start, w_end)):
            return False
    return True


def stall_free_of_offers(stall_id, window):
    w_start, w_end = window
    for e in domain.all_of("waitlist_entries"):
        if (e["status"] == "OFFERED" and e["offered_stall_id"] == stall_id):
            e_start, e_end = entry_window(e)
            if overlaps(e_start, e_end, w_start, w_end):
                return False
    return True


def eligible_stalls(site_id, is_reservable, stall_class, window,
                    exclude_stall_id=None, respect_offers=False):
    out = []
    for s in domain.all_of("stalls"):
        if s["site_id"] != site_id or s["status"] != "ACTIVE":
            continue
        if s["is_reservable"] != is_reservable or s["stall_class"] != stall_class:
            continue
        if exclude_stall_id and s["id"] == exclude_stall_id:
            continue
        if not stall_free_of_bookings(s["id"], window):
            continue
        if respect_offers and not stall_free_of_offers(s["id"], window):
            continue
        out.append(s)
    # smallest stall_number, lexicographic ascending
    out.sort(key=lambda s: s["stall_number"])
    return out


def driver_has_conflict(driver_id, window, exclude_booking_id=None):
    w_start, w_end = window
    for b in domain.all_of("bookings"):
        if (b["driver_id"] == driver_id and b["status"] in NON_TERMINAL_BOOKING
                and b["id"] != exclude_booking_id
                and overlaps(b["checkin_open_at"], b["checkout_due_at"],
                             w_start, w_end)):
            return True
    return False


# --------------------------------------------------------------------------
# Waitlist offer scan (PRD §3.7) — one offer per released stall
# --------------------------------------------------------------------------
def waitlist_scan(site_id, freed_stall_id):
    stall = domain.get("stalls", freed_stall_id)
    if stall is None or stall["status"] != "ACTIVE" or not stall["is_reservable"]:
        return
    candidates = []
    for e in domain.all_of("waitlist_entries"):
        if e["site_id"] != site_id or e["status"] != "QUEUED":
            continue
        if e["stall_class"] != stall["stall_class"]:
            continue
        driver = domain.get("drivers", e["driver_id"])
        if driver is None or driver_standing(driver) == "SUSPENDED":
            continue
        window = entry_window(e)
        if not stall_free_of_bookings(stall["id"], window):
            continue
        if not stall_free_of_offers(stall["id"], window):
            continue
        tier = loyalty_tier(settled_nights_90d(e["driver_id"]))
        candidates.append((e, tier))
    if not candidates:
        return
    # loyalty tier DESC, then created_at ASC (stable: insertion order on ties)
    candidates.sort(key=lambda c: (-TIER_RANK[c[1]], c[0]["created_at"], c[0]["_seq"]))
    winner = candidates[0][0]
    winner["status"] = "OFFERED"
    winner["offered_stall_id"] = stall["id"]
    winner["offer_expires_at"] = db.clock_now() + timedelta(minutes=30)
    domain.touch(winner)


# --------------------------------------------------------------------------
# Booking lifecycle helpers (PRD §3.5)
# --------------------------------------------------------------------------
def system_cancel_booking(b):
    """System cancellations never charge: fee 0, final 0, billing WAIVED."""
    b["status"] = "CANCELLED"
    b["fee_cents"] = 0
    b["final_total_cents"] = 0
    b["billing_status"] = "WAIVED"
    b["settled_at"] = db.clock_now()
    domain.touch(b)
    waitlist_scan(b["site_id"], b["stall_id"])


def driver_suspension_cascade(driver):
    """The moment a driver crosses into SUSPENDED: cancel future BOOKED stays."""
    if driver_standing(driver) != "SUSPENDED":
        return
    now = db.clock_now()
    future = [b for b in domain.all_of("bookings")
              if b["driver_id"] == driver["id"] and b["status"] == "BOOKED"
              and b["checkin_open_at"] > now]
    for b in sorted(future, key=lambda x: (x["created_at"], x["_seq"])):
        system_cancel_booking(b)


def append_strike(driver, kind, booking_id):
    driver["strike_events"].append(
        {"at": db.clock_now(), "kind": kind, "booking_id": booking_id})
    domain.touch(driver)
    driver_suspension_cascade(driver)


def loyalty_earn(booking):
    driver = domain.get("drivers", booking["driver_id"])
    if driver is not None:
        driver["loyalty_points_balance"] += 10 * booking["night_count"]
        domain.touch(driver)


def loyalty_clawback(booking):
    driver = domain.get("drivers", booking["driver_id"])
    if driver is not None:
        driver["loyalty_points_balance"] -= 10 * booking["night_count"]
        domain.touch(driver)


def overstay_penalty(b, site):
    now = db.clock_now()
    grace_end = b["checkout_due_at"] + timedelta(minutes=site["overstay_grace_minutes"])
    minutes_past = int((now - grace_end).total_seconds() // 60)
    if minutes_past < 0:
        minutes_past = 0
    billable_hours = (minutes_past + 59) // 60  # each STARTED hour bills
    last_rate = b["per_night_rates"][-1]["rate_cents"]
    hourly = rhu_cents(Decimal(15) * Decimal(last_rate) / Decimal(200))
    return billable_hours * hourly


def settle_booking(b, site, charge_overstay_fee):
    """Final settlement, pinned order (PRD §3.5, booking_settlement calc)."""
    subtotal = sum(r["rate_cents"] for r in b["per_night_rates"])
    b["parking_subtotal_cents"] = subtotal
    if b["booking_kind"] == "WALK_IN":
        pct = 0
    else:
        pct = loyalty_pct_for_tier(loyalty_tier(settled_nights_90d(b["driver_id"])))
    b["discount_cents"] = rhu_cents(Decimal(subtotal * pct) / Decimal(100))
    parking_net = subtotal - b["discount_cents"]

    lines = [l for l in domain.all_of("booking_amenities")
             if l["booking_id"] == b["id"] and l["status"] in ("RESERVED", "FULFILLED")]
    a_sub = sum(l["unit_price_cents"] * l["quantity"] * b["night_count"] for l in lines)
    codes = set()
    for l in lines:
        product = domain.get("amenity_products", l["amenity_product_id"])
        if product is not None:
            codes.add(product["code"])
    if len(codes) >= 2 and b["booking_kind"] != "WALK_IN":
        a_disc = rhu_cents(Decimal(a_sub * 10) / Decimal(100))
    else:
        a_disc = 0
    b["amenity_net_cents"] = a_sub - a_disc

    b["fee_cents"] = overstay_penalty(b, site) if charge_overstay_fee else 0
    b["final_total_cents"] = parking_net + b["amenity_net_cents"] + b["fee_cents"]
    b["settled_at"] = db.clock_now()


# --------------------------------------------------------------------------
# Fleet cascades (PRD §3.9)
# --------------------------------------------------------------------------
def auth_suspension_cascade(auth):
    """Cascade variant of auth suspension: cancel future fleet-billed bookings."""
    now = db.clock_now()
    bookings = [b for b in domain.all_of("bookings")
                if b["driver_id"] == auth["driver_id"]
                and b["payment_mode"] == "FLEET_BILL"
                and b["fleet_account_id"] == auth["fleet_account_id"]
                and b["status"] == "BOOKED"
                and b["checkin_open_at"] > now]
    for b in sorted(bookings, key=lambda x: (x["created_at"], x["_seq"])):
        system_cancel_booking(b)


def fleet_overdue_cascade(fleet):
    if fleet["status"] != "ACTIVE":
        return
    fleet["status"] = "SUSPENDED"
    fleet["auto_suspended"] = True
    domain.touch(fleet)
    auths = [a for a in domain.all_of("driver_authorizations")
             if a["fleet_account_id"] == fleet["id"] and a["status"] == "ACTIVE"]
    for a in sorted(auths, key=lambda x: (x["created_at"], x["_seq"])):
        a["status"] = "SUSPENDED"
        a["auto_suspended"] = True
        domain.touch(a)
        auth_suspension_cascade(a)


def fleet_reactivation_check(fleet):
    """Reactivate when suspended automatically and no blocking invoice remains."""
    if fleet["status"] != "SUSPENDED" or not fleet["auto_suspended"]:
        return
    today = db.clock_now().date()
    for inv in domain.all_of("invoices"):
        if inv["fleet_account_id"] != fleet["id"]:
            continue
        if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE", "DISPUTED"):
            continue
        outstanding = inv["paid_cents"] < inv["net_cents"]
        past_due = today > inv["due_date"]
        if outstanding or past_due:
            return
    fleet["status"] = "ACTIVE"
    fleet["auto_suspended"] = False
    domain.touch(fleet)
    auths = [a for a in domain.all_of("driver_authorizations")
             if a["fleet_account_id"] == fleet["id"]
             and a["status"] == "SUSPENDED" and a["auto_suspended"]]
    for a in sorted(auths, key=lambda x: (x["created_at"], x["_seq"])):
        a["status"] = "ACTIVE"
        a["auto_suspended"] = False
        domain.touch(a)


# --------------------------------------------------------------------------
# Site ops-run (PRD §3.8) — pinned sweep order
# --------------------------------------------------------------------------
def site_ops_run(site):
    now = db.clock_now()
    site_id = site["id"]

    # 1. No-show sweep
    bookings = [b for b in domain.all_of("bookings")
                if b["site_id"] == site_id and b["status"] == "BOOKED"]
    for b in sorted(bookings, key=lambda x: (x["created_at"], x["_seq"])):
        deadline = b["checkin_open_at"] + timedelta(
            minutes=site["no_show_grace_minutes"])
        if now > deadline:  # strict: at exactly the boundary still check-in-able
            b["status"] = "NO_SHOW"
            b["fee_cents"] = b["per_night_rates"][0]["rate_cents"]
            b["final_total_cents"] = b["fee_cents"]
            b["settled_at"] = now
            domain.touch(b)
            waitlist_scan(site_id, b["stall_id"])
            driver = domain.get("drivers", b["driver_id"])
            if driver is not None:
                append_strike(driver, "NO_SHOW", b["id"])

    # 2. Overstay marking
    bookings = [b for b in domain.all_of("bookings")
                if b["site_id"] == site_id and b["status"] == "CHECKED_IN"]
    for b in sorted(bookings, key=lambda x: (x["created_at"], x["_seq"])):
        deadline = b["checkout_due_at"] + timedelta(
            minutes=site["overstay_grace_minutes"])
        if now > deadline:
            b["status"] = "OVERSTAY"
            b["overstayed_at"] = now
            domain.touch(b)

    # 3. Overstay escalation (auto-incident past grace + 4 hours)
    bookings = [b for b in domain.all_of("bookings")
                if b["site_id"] == site_id and b["status"] == "OVERSTAY"
                and not b["incident_escalated"]]
    for b in sorted(bookings, key=lambda x: (x["created_at"], x["_seq"])):
        deadline = b["checkout_due_at"] + timedelta(
            minutes=site["overstay_grace_minutes"]) + timedelta(hours=4)
        if now > deadline:
            domain.new_entity("incidents", {
                "site_id": site_id,
                "reporter_driver_id": None,
                "booking_id": b["id"],
                "category": "SECURITY",
                "severity": "HIGH",
                "description": "Auto-escalated overstay",
                "status": "OPEN",
                "acknowledged_by_user_id": None,
                "resolved_by_user_id": None,
                "resolved_at": None,
                "reopened_count": 0,
            })
            b["incident_escalated"] = True
            domain.touch(b)

    # 4. Waitlist offer expiry + re-offer
    entries = [e for e in domain.all_of("waitlist_entries")
               if e["site_id"] == site_id and e["status"] == "OFFERED"]
    for e in sorted(entries, key=lambda x: (x["created_at"], x["_seq"])):
        if now > e["offer_expires_at"]:  # strict: inclusive boundary on accept
            stalled = e["offered_stall_id"]
            e["status"] = "EXPIRED"
            domain.touch(e)
            waitlist_scan(site_id, stalled)

    # 5. Posture recompute — derived on read, so nothing to store.

    site["ops_run_index"] += 1
    domain.touch(site)


# --------------------------------------------------------------------------
# Fleet ops-run (PRD §3.9)
# --------------------------------------------------------------------------
def fleet_ops_run(fleet):
    now = db.clock_now()
    today = now.date()
    invoices = [i for i in domain.all_of("invoices")
                if i["fleet_account_id"] == fleet["id"]
                and i["status"] in ("ISSUED", "PARTIALLY_PAID")]
    for inv in sorted(invoices, key=lambda x: (x["created_at"], x["_seq"])):
        if today > inv["due_date"]:  # clock past due_date end-of-day UTC
            inv["status"] = "OVERDUE"
            domain.touch(inv)
    has_overdue = any(
        i["fleet_account_id"] == fleet["id"] and i["status"] == "OVERDUE"
        for i in domain.all_of("invoices"))
    if has_overdue:
        fleet_overdue_cascade(fleet)
    else:
        fleet_reactivation_check(fleet)
