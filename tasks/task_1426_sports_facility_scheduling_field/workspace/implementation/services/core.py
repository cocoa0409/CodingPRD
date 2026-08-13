"""Core domain services: lookups, derived counters, scoring, fee quotes,
allocation run, rain-out cascade, deposit waterfall, and closeouts."""

from datetime import timedelta

import errors
import util
import clock
from util import (
    PRIME_START_MINUTE, LIGHTS_BUFFER_MINUTES, BLOCK_MINUTES,
    REFUND_AUTO_APPROVE_MAX_CENTS, half_open_overlap, prime_hours,
    week_monday, ceil_div, slot_datetime,
)
from db import store
from decimal import Decimal, ROUND_HALF_UP


# Scoring constants (scaffold §1.3 allocation_priority_score)
LOYALTY_CAP = 12
LOYALTY_PER_SEASON = 3
STRIKE_PENALTY_POINTS = 12
UTIL_BONUS_HIGH = 10
UTIL_BONUS_LOW = 5

CLASS_BASE = {"RESIDENT": 80, "NONRESIDENT": 45, "COMMERCIAL": 25}
TYPE_MOD = {
    "YOUTH_LEAGUE": 15,
    "SCHOOL": 12,
    "ADULT_LEAGUE": 6,
    "CORPORATE": 0,
    "TOURNAMENT_OPERATOR": -5,
}
EVENT_MOD = {
    "LEAGUE_GAME": 8,
    "LEAGUE_PRACTICE": 4,
    "SPECIAL_EVENT": 0,
    "TOURNAMENT": -10,
}

# Cancellation tiers (scaffold §1.3 cancellation_penalty)
TIER_FREE_HOURS = 168
TIER_LOW_HOURS = 48
TIER_MID_HOURS = 24
TIER_LOW_PCT = 15
TIER_MID_PCT = 30
TIER_HIGH_PCT = 50

RESCHEDULE_HARD_CAP = 2
RESCHEDULE_HORIZON_DAYS = 10


# ---------------------------------------------------------------------------
# Lookups (priority 5: path existence, dedicated 404s)
# ---------------------------------------------------------------------------

def get_organization(oid):
    ent = store.organizations.get(oid)
    if ent is None:
        raise errors.ApiError(errors.ERR_ORGANIZATION_NOT_FOUND,
                              f"Organization not found: {oid}", 404)
    return ent


def get_facility(fid):
    ent = store.facilities.get(fid)
    if ent is None:
        raise errors.ApiError(errors.ERR_FACILITY_NOT_FOUND,
                              f"Facility not found: {fid}", 404)
    return ent


def get_fee_schedule(sid):
    ent = store.fee_schedules.get(sid)
    if ent is None:
        raise errors.ApiError(errors.ERR_FEE_SCHEDULE_NOT_FOUND,
                              f"FeeSchedule not found: {sid}", 404)
    return ent


def get_window(wid):
    ent = store.allocation_windows.get(wid)
    if ent is None:
        raise errors.ApiError(errors.ERR_WINDOW_NOT_FOUND,
                              f"AllocationWindow not found: {wid}", 404)
    return ent


def get_application(aid):
    ent = store.permit_applications.get(aid)
    if ent is None:
        raise errors.ApiError(errors.ERR_APPLICATION_NOT_FOUND,
                              f"PermitApplication not found: {aid}", 404)
    return ent


def get_permit(pid):
    ent = store.permits.get(pid)
    if ent is None:
        raise errors.ApiError(errors.ERR_PERMIT_NOT_FOUND,
                              f"Permit not found: {pid}", 404)
    return ent


def get_closure(cid):
    ent = store.field_closures.get(cid)
    if ent is None:
        raise errors.ApiError(errors.ERR_CLOSURE_NOT_FOUND,
                              f"FieldClosure not found: {cid}", 404)
    return ent


def get_invoice(iid):
    ent = store.invoices.get(iid)
    if ent is None:
        raise errors.ApiError(errors.ERR_INVOICE_NOT_FOUND,
                              f"Invoice not found: {iid}", 404)
    return ent


def get_payment(pid):
    ent = store.payments.get(pid)
    if ent is None:
        raise errors.ApiError(errors.ERR_PAYMENT_NOT_FOUND,
                              f"Payment not found: {pid}", 404)
    return ent


def get_strike(sid):
    ent = store.strike_records.get(sid)
    if ent is None:
        raise errors.ApiError(errors.ERR_STRIKE_NOT_FOUND,
                              f"StrikeRecord not found: {sid}", 404)
    return ent


def get_ledger(lid):
    ent = store.usage_ledgers.get(lid)
    if ent is None:
        raise errors.ApiError("ERR_LEDGER_NOT_FOUND",
                              f"UsageLedger not found: {lid}", 404)
    return ent


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal/rational to whole cents, ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Derived counters (PRD 2.10)
# ---------------------------------------------------------------------------

def active_strike_count(org_id):
    return sum(1 for s in store.strike_records.values()
               if s["organization_id"] == org_id and s["status"] == "ACTIVE")


def recompute_org_strikes(org):
    org["no_show_strikes_active"] = active_strike_count(org["id"])


def recompute_facility_weekly_prime(facility):
    """weekly_prime_hours_used = prime load of the facility's permits in
    {RESERVED, CONFIRMED} for the Mon-Sun week containing the logical clock date."""
    today = clock.now().date()
    monday = week_monday(today)
    sunday = monday + timedelta(days=6)
    total = 0
    for p in store.permits.values():
        if p["facility_id"] != facility["id"]:
            continue
        if p["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        pd = util.parse_date(p["permit_date"], "permit_date")
        if monday <= pd <= sunday:
            total += prime_hours(p["start_minute"], p["end_minute"])
    facility["weekly_prime_hours_used"] = total


def weekly_load_for(facility_id, slot_date):
    """Prime load for the week containing slot_date (cap check basis)."""
    monday = week_monday(slot_date)
    sunday = monday + timedelta(days=6)
    total = 0
    for p in store.permits.values():
        if p["facility_id"] != facility_id:
            continue
        if p["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        pd = util.parse_date(p["permit_date"], "permit_date")
        if monday <= pd <= sunday:
            total += prime_hours(p["start_minute"], p["end_minute"])
    return total


def find_ledger(org_id, season_code):
    for l in store.usage_ledgers.values():
        if l["organization_id"] == org_id and l["season_code"] == season_code:
            return l
    return None


def get_or_create_ledger(org_id, season_code):
    l = find_ledger(org_id, season_code)
    if l is None:
        l = util.new_entity({
            "organization_id": org_id,
            "season_code": season_code,
            "awarded_prime_hours": 0,
            "awarded_nonprime_hours": 0,
            "attended_hours": 0,
            "no_show_count": 0,
        })
        store.usage_ledgers[l["id"]] = l
    return l


def ledger_release(org_id, season_code, permit):
    """Release a slot's awarded hours from the season ledger."""
    l = find_ledger(org_id, season_code)
    if l is None:
        return
    dur_h = (permit["end_minute"] - permit["start_minute"]) // 60
    ph = prime_hours(permit["start_minute"], permit["end_minute"])
    l["awarded_prime_hours"] -= ph
    l["awarded_nonprime_hours"] -= (dur_h - ph)
    util.touch(l)


def ledger_readd(org_id, season_code, permit):
    l = get_or_create_ledger(org_id, season_code)
    dur_h = (permit["end_minute"] - permit["start_minute"]) // 60
    ph = prime_hours(permit["start_minute"], permit["end_minute"])
    l["awarded_prime_hours"] += ph
    l["awarded_nonprime_hours"] += (dur_h - ph)
    util.touch(l)


def find_invoice_for_permit(permit_id):
    for inv in store.invoices.values():
        if inv["permit_id"] == permit_id:
            return inv
    return None


def recompute_invoice_totals(inv):
    inv["balance_due_cents"] = inv["total_cents"] - (inv["paid_cents"] - inv["refunded_cents"])


def maybe_settle_refunded(inv):
    """Auto-transition to REFUNDED when cleared refunds fully cover net paid
    and the invoice total is 0 (PRD 3.8)."""
    if inv["status"] in ("PAID", "PARTIALLY_PAID"):
        if inv["paid_cents"] > 0 and inv["refunded_cents"] == inv["paid_cents"] and inv["total_cents"] == 0:
            inv["status"] = "REFUNDED"
            util.touch(inv)
            return True
    return False


def apply_payment_status(inv):
    """Advance invoice status after a cleared payment (PRD 3.8)."""
    if inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
        if inv["balance_due_cents"] == 0 and inv["paid_cents"] > 0:
            inv["status"] = "PAID"
        elif inv["paid_cents"] > 0:
            inv["status"] = "PARTIALLY_PAID"


# ---------------------------------------------------------------------------
# Standing re-evaluation (PRD 3.1)
# ---------------------------------------------------------------------------

def reevaluate_standing(org):
    """System standing transitions from the active strike count.

    SUSPENDED stays SUSPENDED no matter how far the count falls (only an
    explicit reinstate lifts it). Returns nothing; mutates org in place."""
    count = org["no_show_strikes_active"]
    if org["standing"] == "SUSPENDED":
        return
    if count >= 3:
        org["standing"] = "SUSPENDED"
        util.touch(org)
        suspension_cascade(org)
    elif count == 2:
        if org["standing"] != "PROBATION":
            org["standing"] = "PROBATION"
            util.touch(org)
    else:  # count < 2
        if org["standing"] == "PROBATION":
            org["standing"] = "GOOD"
            util.touch(org)


def suspension_cascade(org):
    """PRD 3.1: on SUSPENDED, revoke RESERVED/CONFIRMED permits with
    permit_date >= current logical date under ORG_FAULT, and deny all
    WAITLISTED applications of the org."""
    today = clock.now().date()
    for p in sorted(store.permits.values(), key=util.sort_key):
        if p["organization_id"] != org["id"]:
            continue
        if p["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        pd = util.parse_date(p["permit_date"], "permit_date")
        if pd < today:
            continue
        _revoke_permit(p, fault="ORG_FAULT", run_promotion=True)

    for a in sorted(store.permit_applications.values(), key=util.sort_key):
        if a["organization_id"] == org["id"] and a["status"] == "WAITLISTED":
            a["status"] = "DENIED"
            a["decision_note"] = "ORG_SUSPENDED"
            util.touch(a)


# ---------------------------------------------------------------------------
# Priority scoring (PRD 3.5)
# ---------------------------------------------------------------------------

def compute_score(org, event_type, current_season_code):
    base = CLASS_BASE[org["classification"]]
    type_mod = TYPE_MOD[org["org_type"]]
    loyalty = min(LOYALTY_CAP, LOYALTY_PER_SEASON * org["prior_seasons_active"])

    # Utilization bonus: most recent prior-season ledger with any awarded history.
    util_bonus = 0
    priors = [l for l in store.usage_ledgers.values()
              if l["organization_id"] == org["id"] and l["season_code"] != current_season_code]
    priors.sort(key=lambda l: l["season_code"], reverse=True)
    for l in priors:
        total = l["awarded_prime_hours"] + l["awarded_nonprime_hours"] + l["attended_hours"]
        if total > 0:
            attended = l["attended_hours"]
            if attended * 100 >= 80 * total:
                util_bonus = UTIL_BONUS_HIGH
            elif attended * 100 >= 60 * total:
                util_bonus = UTIL_BONUS_LOW
            break

    strike_penalty = STRIKE_PENALTY_POINTS * org["no_show_strikes_active"]
    event_mod = EVENT_MOD[event_type]
    return max(0, base + type_mod + loyalty + util_bonus - strike_penalty + event_mod)


# ---------------------------------------------------------------------------
# Fee quote (PRD 3.6 provisional variant)
# ---------------------------------------------------------------------------

def quote_fees(schedule, classification, event_type, duration_min, lights_minutes_quoted):
    """Provisional quote. Returns (field_fee, lights_fee, surcharge, total, deposit)."""
    if event_type == "TOURNAMENT" and duration_min >= schedule["tournament_day_min_minutes"]:
        raw_field = Decimal(schedule["tournament_day_cents"])
        hourly_rate = None
    else:
        if classification == "RESIDENT":
            hourly_rate = schedule["hourly_resident_cents"]
        elif classification == "NONRESIDENT":
            hourly_rate = schedule["hourly_nonresident_cents"]
        else:
            hourly_rate = schedule["hourly_commercial_cents"]
        raw_field = (Decimal(duration_min) * Decimal(hourly_rate)) / Decimal(60)
    field_fee = round_half_up_cents(raw_field)

    blocks = ceil_div(lights_minutes_quoted, BLOCK_MINUTES)
    lights_fee = blocks * schedule["lights_block_cents"]

    if classification == "NONRESIDENT":
        surcharge_pct = schedule["nonresident_surcharge_pct"]
    elif classification == "COMMERCIAL":
        surcharge_pct = schedule["commercial_surcharge_pct"]
    else:
        surcharge_pct = 0
    surcharge = round_half_up_cents(Decimal(field_fee) * Decimal(surcharge_pct) / Decimal(100))

    total = field_fee + lights_fee + surcharge
    pct_floor = round_half_up_cents(Decimal(total) * Decimal(schedule["deposit_pct"]) / Decimal(100))
    deposit = min(total, max(schedule["min_deposit_cents"], pct_floor))
    return field_fee, lights_fee, surcharge, total, deposit, hourly_rate


# ---------------------------------------------------------------------------
# Slot / lights / cap checks
# ---------------------------------------------------------------------------

def slot_conflicts(facility_id, date_str, start_minute, end_minute, exclude_permit_id=None):
    """Any RESERVED/CONFIRMED permit on facility+date overlapping [start, end)."""
    for p in store.permits.values():
        if p["facility_id"] != facility_id or p["permit_date"] != date_str:
            continue
        if p["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        if exclude_permit_id is not None and p["id"] == exclude_permit_id:
            continue
        if half_open_overlap(start_minute, end_minute, p["start_minute"], p["end_minute"]):
            return True
    return False


def lights_conflict_or_cap(facility, date_str, start_minute, end_minute, exclude_permit_id=None):
    """True when the candidate lights window breaches the 30-minute buffer or
    the nightly block cap."""
    cand_blocks = ceil_div(end_minute - start_minute, BLOCK_MINUTES)
    used_blocks = 0
    for p in store.permits.values():
        if p["facility_id"] != facility["id"] or p["permit_date"] != date_str:
            continue
        if p["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        if not p["lights_approved"]:
            continue
        if exclude_permit_id is not None and p["id"] == exclude_permit_id:
            continue
        s, e = p["start_minute"], p["end_minute"]
        # Buffer rule: conflict iff gap < 30 minutes in either order.
        if half_open_overlap(start_minute, end_minute, s, e):
            return True
        if e <= start_minute and (start_minute - e) < LIGHTS_BUFFER_MINUTES:
            return True
        if end_minute <= s and (s - end_minute) < LIGHTS_BUFFER_MINUTES:
            return True
        used_blocks += ceil_div(p["lights_minutes_quoted"], BLOCK_MINUTES)
    if used_blocks + cand_blocks > facility["nightly_light_block_cap"]:
        return True
    return False


def tournament_day_count(org_id, season_code):
    """Count of TOURNAMENT event days held by org's RESERVED/CONFIRMED permits
    in the season (permits are tied to a season through their window)."""
    count = 0
    for p in store.permits.values():
        if p["organization_id"] != org_id:
            continue
        if p["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        if p["event_type"] != "TOURNAMENT":
            continue
        if p.get("season_code") != season_code:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Award fan-out (PRD 3.5)
# ---------------------------------------------------------------------------

def award_application(app, window, schedule):
    """Create Permit(RESERVED) + Invoice(DRAFT), update ledger + facility counters."""
    org = get_organization(app["organization_id"])
    facility = get_facility(app["facility_id"])
    start = app["start_minute"]
    end = app["end_minute"]
    duration = end - start

    lights_approved = False
    lights_minutes = 0
    if app["wants_lights"] and facility["has_lights"]:
        if not lights_conflict_or_cap(facility, app["event_date"], start, end):
            lights_approved = True
            lights_minutes = duration

    field_fee, lights_fee, surcharge, total, deposit, _rate = quote_fees(
        schedule, org["classification"], app["event_type"], duration, lights_minutes)

    permit = util.new_entity({
        "application_id": app["id"],
        "organization_id": org["id"],
        "facility_id": facility["id"],
        "fee_schedule_id": schedule["id"],
        "original_permit_id": None,
        "permit_date": app["event_date"],
        "start_minute": start,
        "end_minute": end,
        "event_type": app["event_type"],
        "lights_approved": lights_approved,
        "lights_minutes_quoted": lights_minutes,
        "status": "RESERVED",
        "quoted_field_fee_cents": field_fee,
        "quoted_lights_fee_cents": lights_fee,
        "quoted_surcharge_cents": surcharge,
        "quoted_total_cents": total,
        "deposit_required_cents": deposit,
        "final_total_cents": None,
        "attendance_minutes": None,
        "rain_reschedule_count": 0,
        "season_code": window["season_code"],
    })
    store.permits[permit["id"]] = permit

    invoice = util.new_entity({
        "permit_id": permit["id"],
        "organization_id": org["id"],
        "status": "DRAFT",
        "field_fee_cents": field_fee,
        "lights_fee_cents": lights_fee,
        "surcharge_cents": surcharge,
        "credit_cents": 0,
        "adjustment_cents": 0,
        "penalty_cents": 0,
        "total_cents": total,
        "deposit_cents": deposit,
        "paid_cents": 0,
        "refunded_cents": 0,
        "balance_due_cents": total,
        "deposit_penalty_applied_cents": 0,
        "deposit_balance_applied_cents": 0,
        "deposit_refunded_cents": 0,
    })
    store.invoices[invoice["id"]] = invoice

    ledger_readd(org["id"], window["season_code"], permit)
    recompute_facility_weekly_prime(facility)

    app["status"] = "AWARDED"
    util.touch(app)
    return permit


# ---------------------------------------------------------------------------
# Allocation run (PRD 3.5)
# ---------------------------------------------------------------------------

def run_allocation(window):
    schedule = None
    for s in store.fee_schedules.values():
        if s["status"] == "PUBLISHED":
            schedule = s
            break
    if schedule is None:
        raise errors.ApiError(errors.ERR_INVALID_SCHEDULE_STATE,
                              "No PUBLISHED fee schedule exists", 409)

    candidates = [a for a in store.permit_applications.values()
                  if a["window_id"] == window["id"] and a["status"] == "UNDER_REVIEW"]
    # Final scores frozen at run time.
    for a in candidates:
        org = get_organization(a["organization_id"])
        a["final_score"] = compute_score(org, a["event_type"], window["season_code"])
    candidates.sort(key=lambda a: (-a["final_score"], util.sort_key(a)))

    awarded_this_run = []
    for a in candidates:
        org = get_organization(a["organization_id"])
        facility = get_facility(a["facility_id"])

        if org["standing"] == "SUSPENDED":
            a["status"] = "DENIED"
            a["decision_note"] = "ORG_SUSPENDED"
            util.touch(a)
            continue

        # Slot conflict vs already-awarded-this-run or existing RESERVED/CONFIRMED permits.
        conflict = False
        for p in awarded_this_run:
            if (p["facility_id"] == a["facility_id"] and p["permit_date"] == a["event_date"]
                    and half_open_overlap(a["start_minute"], a["end_minute"],
                                          p["start_minute"], p["end_minute"])):
                conflict = True
                break
        if not conflict:
            conflict = slot_conflicts(a["facility_id"], a["event_date"],
                                      a["start_minute"], a["end_minute"])
        if conflict:
            a["status"] = "WAITLISTED"
            a["decision_note"] = "SLOT_CONFLICT"
            util.touch(a)
            continue

        # Prime cap (inclusive boundary).
        ph = prime_hours(a["start_minute"], a["end_minute"])
        ledger = find_ledger(org["id"], window["season_code"])
        current_prime = ledger["awarded_prime_hours"] if ledger else 0
        if current_prime + ph > window["prime_cap_hours_per_org"]:
            a["status"] = "WAITLISTED"
            a["decision_note"] = "PRIME_CAP"
            util.touch(a)
            continue

        # Turf-rest weekly cap (inclusive boundary) against the candidate slot's week.
        slot_date = util.parse_date(a["event_date"], "event_date")
        if weekly_load_for(facility["id"], slot_date) + ph > facility["weekly_prime_hour_cap"]:
            a["status"] = "WAITLISTED"
            a["decision_note"] = "TURF_REST_CAP"
            util.touch(a)
            continue

        # Tournament-day cap (inclusive boundary).
        if a["event_type"] == "TOURNAMENT":
            if tournament_day_count(org["id"], window["season_code"]) + 1 > window["max_tournament_days_per_org"]:
                a["status"] = "WAITLISTED"
                a["decision_note"] = "TOURNAMENT_CAP"
                util.touch(a)
                continue

        permit = award_application(a, window, schedule)
        awarded_this_run.append(permit)


def waitlist_promotion(window_id, facility_id, event_date):
    """Promote the first fitting WAITLISTED application for the freed slot."""
    schedule = None
    for s in store.fee_schedules.values():
        if s["status"] == "PUBLISHED":
            schedule = s
            break
    if schedule is None:
        return
    window = store.allocation_windows.get(window_id)
    if window is None:
        return

    pool = [a for a in store.permit_applications.values()
            if a["window_id"] == window_id and a["status"] == "WAITLISTED"
            and a["facility_id"] == facility_id and a["event_date"] == event_date]
    pool.sort(key=lambda a: (-(a["final_score"] if a["final_score"] is not None else 0),
                             util.sort_key(a)))
    for a in pool:
        org = get_organization(a["organization_id"])
        if org["standing"] == "SUSPENDED":
            continue
        facility = get_facility(a["facility_id"])
        if slot_conflicts(a["facility_id"], a["event_date"], a["start_minute"], a["end_minute"]):
            continue
        ph = prime_hours(a["start_minute"], a["end_minute"])
        ledger = find_ledger(org["id"], window["season_code"])
        current_prime = ledger["awarded_prime_hours"] if ledger else 0
        if current_prime + ph > window["prime_cap_hours_per_org"]:
            continue
        slot_date = util.parse_date(a["event_date"], "event_date")
        if weekly_load_for(facility["id"], slot_date) + ph > facility["weekly_prime_hour_cap"]:
            continue
        if a["event_type"] == "TOURNAMENT":
            if tournament_day_count(org["id"], window["season_code"]) + 1 > window["max_tournament_days_per_org"]:
                continue
        award_application(a, window, schedule)
        return


# ---------------------------------------------------------------------------
# Deposit waterfall (PRD 3.8)
# ---------------------------------------------------------------------------

def run_deposit_waterfall(inv, initiated_by):
    """Drain the held deposit through penalty -> balance -> refund buckets.

    Money conservation: deposit_held == bucket1 + bucket2 + bucket3.
    Creates a REFUND Payment when bucket3 > 0 (PENDING_APPROVAL over threshold).
    Returns the created Payment or None."""
    deposit_held = min(inv["paid_cents"] - inv["refunded_cents"], inv["deposit_cents"])
    if deposit_held < 0:
        deposit_held = 0
    b1 = min(deposit_held, inv["penalty_cents"])
    b2 = min(deposit_held - b1, max(0, inv["total_cents"] - inv["penalty_cents"]))
    b3 = deposit_held - b1 - b2
    inv["deposit_penalty_applied_cents"] = b1
    inv["deposit_balance_applied_cents"] = b2
    inv["deposit_refunded_cents"] = b3

    payment = None
    if b3 > 0:
        status = "CLEARED" if b3 <= REFUND_AUTO_APPROVE_MAX_CENTS else "PENDING_APPROVAL"
        payment = util.new_entity({
            "invoice_id": inv["id"],
            "organization_id": inv["organization_id"],
            "kind": "REFUND",
            "amount_cents": b3,
            "method": None,
            "status": status,
            "initiated_by": initiated_by,
            "approved_by": None,
        })
        store.payments[payment["id"]] = payment
        if status == "CLEARED":
            inv["refunded_cents"] += b3
    recompute_invoice_totals(inv)
    maybe_settle_refunded(inv)
    util.touch(inv)
    return payment


# ---------------------------------------------------------------------------
# Permit closeouts (cancel / revoke) and rain-out cascade
# ---------------------------------------------------------------------------

def _release_slot_resources(permit):
    """Release ledger hours and recompute the facility weekly counter."""
    ledger_release(permit["organization_id"], permit.get("season_code", ""), permit)
    facility = store.facilities.get(permit["facility_id"])
    if facility is not None:
        recompute_facility_weekly_prime(facility)


def _window_for_permit(permit):
    app = store.permit_applications.get(permit["application_id"])
    if app is not None:
        return store.allocation_windows.get(app["window_id"])
    return None


def cancel_permit(permit, initiated_by):
    """Cancel from RESERVED / CONFIRMED / RAINED_OUT per PRD 3.7-3.8."""
    inv = find_invoice_for_permit(permit["id"])
    if permit["status"] == "RESERVED":
        penalty = 0
    elif permit["status"] == "RAINED_OUT":
        penalty = 0
    else:  # CONFIRMED — notice-tier penalty against the pre-cancel quoted total
        start_dt = slot_datetime(util.parse_date(permit["permit_date"], "permit_date"),
                                 permit["start_minute"])
        delta_seconds = (start_dt - clock.now()).total_seconds()
        notice_hours = int(delta_seconds // 3600)  # whole hours, floor
        if notice_hours >= TIER_FREE_HOURS:
            tier_pct = 0
        elif notice_hours >= TIER_LOW_HOURS:
            tier_pct = TIER_LOW_PCT
        elif notice_hours >= TIER_MID_HOURS:
            tier_pct = TIER_MID_PCT
        else:
            tier_pct = TIER_HIGH_PCT
        penalty = round_half_up_cents(
            Decimal(permit["quoted_total_cents"]) * Decimal(tier_pct) / Decimal(100))

    # PINNED order: penalty against pre-cancel total; invoice.total REPLACED by
    # penalty; then the waterfall runs.
    inv["penalty_cents"] = penalty
    inv["total_cents"] = penalty
    run_deposit_waterfall(inv, initiated_by)

    permit["status"] = "CANCELLED"
    util.touch(permit)
    _release_slot_resources(permit)

    window = _window_for_permit(permit)
    if window is not None:
        waitlist_promotion(window["id"], permit["facility_id"], permit["permit_date"])


def _revoke_permit(permit, fault, run_promotion=True):
    """Revocation under ORG_FAULT (deposit forfeited) or ADMIN_DISCRETION (full refund)."""
    inv = find_invoice_for_permit(permit["id"])
    if fault == "ORG_FAULT":
        penalty = inv["deposit_cents"]
    else:  # ADMIN_DISCRETION
        penalty = 0
    inv["penalty_cents"] = penalty
    inv["total_cents"] = penalty
    run_deposit_waterfall(inv, initiated_by="system")

    permit["status"] = "REVOKED"
    util.touch(permit)
    _release_slot_resources(permit)

    if run_promotion:
        window = _window_for_permit(permit)
        if window is not None:
            waitlist_promotion(window["id"], permit["facility_id"], permit["permit_date"])


def revoke_permit(permit, fault):
    _revoke_permit(permit, fault, run_promotion=True)


def rain_out_permit(permit):
    """Closure cascade: RESERVED/CONFIRMED -> RAINED_OUT with full invoice credit."""
    inv = find_invoice_for_permit(permit["id"])
    permit["status"] = "RAINED_OUT"
    util.touch(permit)

    inv["credit_cents"] = inv["field_fee_cents"] + inv["lights_fee_cents"] + inv["surcharge_cents"]
    inv["total_cents"] = (inv["field_fee_cents"] + inv["lights_fee_cents"]
                          + inv["surcharge_cents"] + inv["adjustment_cents"]
                          - inv["credit_cents"])
    recompute_invoice_totals(inv)
    util.touch(inv)

    _release_slot_resources(permit)


def closure_intersects_permit(closure, permit):
    """Half-open intersection of a closure with a permit slot on facility+date."""
    if closure["facility_id"] != permit["facility_id"]:
        return False
    if closure["closure_date"] != permit["permit_date"]:
        return False
    if closure["start_minute"] is None or closure["end_minute"] is None:
        return True  # full-day closure
    return half_open_overlap(closure["start_minute"], closure["end_minute"],
                             permit["start_minute"], permit["end_minute"])
