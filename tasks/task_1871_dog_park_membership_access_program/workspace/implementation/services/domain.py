"""Business logic: derived fields, fee calculations, strikes, cascades,
and the nightly service-run epoch. All temporal rules read the logical clock.
"""
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import store
from helpers import (
    now_dt, now_iso, today, minute_of_day,
    parse_date, parse_term_end, term_end_string,
)

# --- fee / scoring constants (SCAFFOLD §1.3) -------------------------------
BASE_ANNUAL_FEE_CENTS = 12000
ADDITIONAL_DOG_FEE_CENTS = 3000
DAYS_IN_YEAR = 365
EARLY_BIRD_DISCOUNT = Decimal("0.10")
REINSTATEMENT_FEE_CENTS = 2500

GUEST_WEEKDAY_FEE_CENTS = 1500
GUEST_WEEKEND_MULTIPLIER = Decimal("1.5")
GUEST_MONTHLY_LIMIT = 2

SEVERITY_POINTS = {"MINOR": 10, "MAJOR": 20, "SEVERE": 30}
PROVISIONAL_WEIGHT = Decimal("0.5")
SUSPENSION_THRESHOLD = 30

FILL_PER_VISIT_PCT = 25
FILL_THRESHOLD_PCT = 80


def round_half_up_int(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Entity plumbing
# --------------------------------------------------------------------------

def new_entity(collection, fields):
    """Mint a resource with common system fields; store and return it."""
    entity = dict(fields)
    entity["id"] = str(uuid.uuid4())
    entity["created_at"] = now_iso()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    entity["_created_dt"] = now_dt()
    collection[entity["id"]] = entity
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version by one."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def public(entity):
    """Strip internal keys (prefixed '_') for serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# Derived member fields
# --------------------------------------------------------------------------

def verified_dog_count(member_id):
    return sum(
        1 for d in store.dogs.values()
        if d["member_id"] == member_id and d["verification_status"] == "VERIFIED"
    )


def pending_points(member_id):
    return sum(
        SEVERITY_POINTS[r["severity"]]
        for r in store.incidents.values()
        if r["subject_member_id"] == member_id
        and r["status"] in ("FILED", "UNDER_REVIEW")
    )


def provisional_score(member):
    """strike_points + round_half_up(0.5 * pending); advisory, never suspends."""
    return member["strike_points"] + round_half_up_int(
        Decimal(pending_points(member["id"])) * PROVISIONAL_WEIGHT
    )


def guest_usage(member_id):
    """Passes created in the logical clock's current calendar month whose
    status is ISSUED, REDEEMED, or EXPIRED (VOID excluded)."""
    now = now_dt()
    count = 0
    for p in store.guest_passes.values():
        if p["sponsor_member_id"] != member_id or p["status"] == "VOID":
            continue
        created = p["_created_dt"]
        if created.year == now.year and created.month == now.month:
            count += 1
    return count


def member_view(member):
    out = public(member)
    out["provisional_strike_score"] = provisional_score(member)
    out["guest_passes_used_this_month"] = guest_usage(member["id"])
    return out


# --------------------------------------------------------------------------
# Area occupancy / effective capacity
# --------------------------------------------------------------------------

def occupancy(area_id):
    return sum(
        1 for v in store.visits.values()
        if v["area_id"] == area_id and v["status"] == "OPEN"
    )


def effective_capacity(area):
    for c in store.closures.values():
        if c["area_id"] == area["id"] and c["status"] == "ACTIVE":
            return 0
    minute = minute_of_day()
    for w in area["peak_windows"]:
        if w["start_minute"] <= minute < w["end_minute"]:
            return min(area["capacity"], area["peak_capacity"])
    return area["capacity"]


def area_view(area):
    out = public(area)
    out["current_occupancy"] = occupancy(area["id"])
    out["effective_capacity"] = effective_capacity(area)
    return out


# --------------------------------------------------------------------------
# Fees
# --------------------------------------------------------------------------

def initial_membership_fee(member_id, purchase_date):
    """Prorated: each line rounded half-up to whole cents first, then summed."""
    dec31 = date(purchase_date.year, 12, 31)
    days_remaining = (dec31 - purchase_date).days + 1  # both ends inclusive
    base_line = round_half_up_int(
        Decimal(BASE_ANNUAL_FEE_CENTS * days_remaining) / Decimal(DAYS_IN_YEAR))
    extra_dogs = max(0, verified_dog_count(member_id) - 1)
    dog_line = round_half_up_int(
        Decimal(ADDITIONAL_DOG_FEE_CENTS * extra_dogs * days_remaining)
        / Decimal(DAYS_IN_YEAR))
    return base_line + dog_line


def early_renewal_fee(member_id):
    """10% off each line; per-line round half-up, then sum."""
    base_line = round_half_up_int(
        Decimal(BASE_ANNUAL_FEE_CENTS) * (Decimal(1) - EARLY_BIRD_DISCOUNT))
    extra_dogs = max(0, verified_dog_count(member_id) - 1)
    dog_line = round_half_up_int(
        Decimal(ADDITIONAL_DOG_FEE_CENTS * extra_dogs)
        * (Decimal(1) - EARLY_BIRD_DISCOUNT))
    return base_line + dog_line


def lapsed_renewal_fee(member_id):
    """Full undiscounted year lines + flat reinstatement; no proration."""
    extra_dogs = max(0, verified_dog_count(member_id) - 1)
    return (BASE_ANNUAL_FEE_CENTS
            + ADDITIONAL_DOG_FEE_CENTS * extra_dogs
            + REINSTATEMENT_FEE_CENTS)


def guest_pass_fee(valid_on_date):
    """Weekend (Sat/Sun UTC): round_half_up(1500 * 1.5) = 2250; else 1500."""
    if valid_on_date.weekday() >= 5:
        return round_half_up_int(
            Decimal(GUEST_WEEKDAY_FEE_CENTS) * GUEST_WEEKEND_MULTIPLIER)
    return GUEST_WEEKDAY_FEE_CENTS


# --------------------------------------------------------------------------
# Suspension cascade (CONFIRMED incident reaching the strike threshold)
# --------------------------------------------------------------------------

def suspend_member(member):
    """Member ACTIVE -> SUSPENDED with the full atomic cascade. Assumes the
    caller will touch the member once for this request's combined mutation."""
    member["status"] = "SUSPENDED"
    for ms in list(store.memberships.values()):
        if ms["member_id"] == member["id"] and ms["status"] == "ACTIVE":
            ms["status"] = "SUSPENDED"
            touch(ms)
    for v in list(store.visits.values()):
        if v["member_id"] == member["id"] and v["status"] == "OPEN":
            v["status"] = "FORCE_CLOSED"
            v["close_reason"] = "MEMBER_SUSPENDED"
            v["checked_out_at"] = now_iso()
            touch(v)
    for p in list(store.guest_passes.values()):
        if p["sponsor_member_id"] == member["id"] and p["status"] == "ISSUED":
            p["status"] = "VOID"
            touch(p)


# --------------------------------------------------------------------------
# Nightly service-run epoch — six cascades in pinned order (PRD §3.8)
# --------------------------------------------------------------------------

def nightly_run():
    now = now_dt()
    run_date = today()
    tallies = {
        "visits_force_closed": 0,
        "memberships_expired": 0,
        "members_lapsed": 0,
        "guest_passes_expired": 0,
        "closures_activated": 0,
        "closures_completed": 0,
        "dogs_expired": 0,
        "stations_flagged": 0,
    }

    # 1. Force-close every OPEN visit (NIGHTLY_SWEEP).
    for v in list(store.visits.values()):
        if v["status"] == "OPEN":
            v["status"] = "FORCE_CLOSED"
            v["close_reason"] = "NIGHTLY_SWEEP"
            v["checked_out_at"] = now_iso()
            touch(v)
            tallies["visits_force_closed"] += 1

    # 2. Expire memberships whose term_end is before the run time; lapse
    #    members whose prior membership status was ACTIVE.
    for ms in list(store.memberships.values()):
        if ms["status"] in ("ACTIVE", "SUSPENDED") \
                and parse_term_end(ms["term_end"]) < now:
            prior = ms["status"]
            ms["status"] = "EXPIRED"
            touch(ms)
            tallies["memberships_expired"] += 1
            if prior == "ACTIVE":
                member = store.members.get(ms["member_id"])
                if member is not None and member["status"] == "ACTIVE":
                    member["status"] = "LAPSED"
                    touch(member)
                    tallies["members_lapsed"] += 1

    # 3. Expire ISSUED guest passes with valid_on before the run date.
    for p in list(store.guest_passes.values()):
        if p["status"] == "ISSUED":
            valid = parse_date(p["valid_on"])
            if valid is not None and valid < run_date:
                p["status"] = "EXPIRED"
                touch(p)
                tallies["guest_passes_expired"] += 1

    # 4. Advance closure windows.
    for c in list(store.closures.values()):
        if c["status"] == "SCHEDULED" \
                and c["_starts_dt"] <= now < c["_ends_dt"]:
            c["status"] = "ACTIVE"
            touch(c)
            tallies["closures_activated"] += 1
        elif c["status"] == "ACTIVE" and now >= c["_ends_dt"]:
            c["status"] = "COMPLETED"
            touch(c)
            tallies["closures_completed"] += 1

    # 5. Accumulate waste-station fill (+25 per area visit since the previous
    #    run, or since station creation when no run has occurred; all visit
    #    statuses counted; capped at 100) and flag NEEDS_SERVICE at >= 80.
    for s in list(store.waste_stations.values()):
        # "checked_in_at after the previous service-run time (or station
        # creation time if no prior run)". Compared as a (logical time,
        # insertion order) watermark so visits made at the same logical
        # instant as the baseline are ordered deterministically.
        if store.last_service_run_at is not None:
            baseline = (store.last_service_run_at, store.last_service_run_seq)
        else:
            baseline = (s["_created_dt"], s["_seq"])
        new_visits = sum(
            1 for v in store.visits.values()
            if v["area_id"] == s["area_id"]
            and (v["_checked_in_dt"], v["_seq"]) > baseline
        )
        changed = False
        if new_visits > 0:
            s["fill_pct"] = min(100, s["fill_pct"] + FILL_PER_VISIT_PCT * new_visits)
            changed = True
        if s["fill_pct"] >= FILL_THRESHOLD_PCT and s["status"] == "OK":
            s["status"] = "NEEDS_SERVICE"
            tallies["stations_flagged"] += 1
            changed = True
        if changed:
            touch(s)

    # 6. Sweep VERIFIED dogs whose vaccination expired before the run date.
    for d in list(store.dogs.values()):
        if d["verification_status"] == "VERIFIED":
            expires = parse_date(d["vaccination_expires_on"])
            if expires is not None and expires < run_date:
                d["verification_status"] = "EXPIRED"
                touch(d)
                tallies["dogs_expired"] += 1

    store.last_service_run_at = now
    store.last_service_run_seq = store.seq
    return tallies
