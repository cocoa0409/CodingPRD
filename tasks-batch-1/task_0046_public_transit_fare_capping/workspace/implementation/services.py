"""Business logic: pricing, benefit selection, tap settle/reverse side effects,
and the rider risk score.

All amounts are integer cents. Per-ride percentage products are rounded
half-up at each multiplication (PRD §2.5). Caps accrue chronologically, so the
order in which taps are priced is load-bearing (PRD §1, §3.7).
"""

from datetime import timedelta

from db import db, touch
from clock import clock
import util


# Regulatory Transit FSA monthly maximum (cents). The IRS qualified
# transportation fringe monthly limit; allocated_cents must not exceed it
# (PRD §3.5 / ERR_FSA_CAP_EXCEEDED).
MONTHLY_FSA_CAP_CENTS = 32500

# rider_risk_score weights (SCAFFOLD §1.3 constants / PRD §3.2).
W_REJECT = 15
W_REVERSAL = 8
W_LOWBAL = 20
LOW_BALANCE_FLOOR_CENTS = 500


# ---------------------------------------------------------------------------
# Discount stacking (PRD §3.7 step 1)
# ---------------------------------------------------------------------------

def _has_verified_unexpired_card(rider_id, fday):
    """True if the rider holds a VERIFIED ReducedFareCard whose expires_on is on
    or after the tap's fare day."""
    for card in db.reduced_fare_cards.values():
        if card["rider_id"] != rider_id:
            continue
        if card["status"] != "VERIFIED":
            continue
        exp = util.parse_iso_date(card["expires_on"])
        if exp is not None and exp >= fday:
            return True
    return False


def _active_product_for_zone(zone_code):
    for p in db.fare_products.values():
        if p["zone_code"] == zone_code and p["status"] == "ACTIVE":
            return p
    return None


# ---------------------------------------------------------------------------
# Benefit selector (PRD §3.8 / SCAFFOLD benefit_selector)
# ---------------------------------------------------------------------------

def benefit_selector(rider_id, fday):
    """Select the BenefitAllocation that subsidizes a tap, or None.

    Candidates: rider's ACTIVE allocations whose period_month equals the fare
    day's YYYY-MM and that still have remaining headroom (>0). Rank by remaining
    headroom DESC, tie-break created_at ASC (never id). Empty set -> None.
    """
    month = f"{fday.year:04d}-{fday.month:02d}"
    candidates = []
    for a in db.benefit_allocations.values():
        if a["rider_id"] != rider_id:
            continue
        if a["status"] != "ACTIVE":
            continue
        if a["period_month"] != month:
            continue
        remaining = a["allocated_cents"] - a["consumed_cents"]
        if remaining > 0:
            candidates.append(a)
    if not candidates:
        return None
    candidates.sort(key=lambda a: (-(a["allocated_cents"] - a["consumed_cents"]),
                                    a["created_at"], a["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# Chronological actual pricing (PRD §3.7 / SCAFFOLD compute_tap_charge)
# ---------------------------------------------------------------------------

def _prior_captured_taps_same_rider(rider_id, before_dt, exclude_tap_id):
    """CAPTURED taps for this rider strictly before before_dt (by tapped_at)."""
    out = []
    for t in db.taps.values():
        if t["id"] == exclude_tap_id:
            continue
        if t["rider_id"] != rider_id:
            continue
        if t["status"] != "CAPTURED":
            continue
        t_dt = util.parse_iso_datetime(t["tapped_at"])
        if t_dt is not None and t_dt < before_dt:
            out.append(t)
    return out


def compute_tap_charge(rider, product, fare_week, tapped_at, tap_id=None):
    """Canonical chronological pricing for a tap being settled (PRD §3.7).

    Returns a dict with list_fare_cents, transfer_discount_cents,
    cap_credit_cents, benefit_applied_cents, charge_cents, benefit_allocation_id.
    Reads (does not mutate) the running FareWeek.charged_total_cents and prior
    CAPTURED taps strictly before this tap in time.
    """
    fday = util.fare_day(tapped_at)
    eff = effective_discount_pct_from_product(rider, product, fday)

    # Step 1: per-ride list fare.
    list_fare_cents = util.scale_cents_by_discount(product["base_fare_cents"], eff)

    # Step 2: transfer discount. Most recent CAPTURED tap strictly before this
    # one (tie-break created_at ASC); transfer if gap <= transfer_window_minutes.
    prior = _latest_prior_captured(rider["id"], tapped_at, tap_id)
    transfer_discount_cents = 0
    if prior is not None:
        prior_dt = util.parse_iso_datetime(prior["tapped_at"])
        window = timedelta(minutes=product["transfer_window_minutes"])
        if (tapped_at - prior_dt) <= window:
            transfer_discount_cents = util.pct_of_cents(list_fare_cents, product["transfer_discount_pct"])
    post_transfer = list_fare_cents - transfer_discount_cents

    # Step 3: cap credit (daily then weekly; caps scaled by same eff discount).
    eff_daily_cap = util.scale_cents_by_discount(product["daily_cap_cents"], eff)
    eff_weekly_cap = util.scale_cents_by_discount(product["weekly_cap_cents"], eff)

    day_charged_before = 0
    for t in _prior_captured_taps_same_rider(rider["id"], tapped_at, tap_id):
        t_dt = util.parse_iso_datetime(t["tapped_at"])
        if util.fare_day(t_dt) == fday:
            day_charged_before += t["charge_cents"]
    week_charged_before = fare_week["charged_total_cents"]

    daily_room = max(eff_daily_cap - day_charged_before, 0)
    weekly_room = max(eff_weekly_cap - week_charged_before, 0)
    billable = min(post_transfer, daily_room, weekly_room)
    cap_credit_cents = post_transfer - billable

    # Step 4: benefit (FSA) application, after caps.
    alloc = benefit_selector(rider["id"], fday)
    if alloc is not None:
        benefit_applied_cents = min(billable, alloc["allocated_cents"] - alloc["consumed_cents"])
    else:
        benefit_applied_cents = 0
    charge_cents = billable - benefit_applied_cents

    return {
        "list_fare_cents": list_fare_cents,
        "transfer_discount_cents": transfer_discount_cents,
        "cap_credit_cents": cap_credit_cents,
        "benefit_applied_cents": benefit_applied_cents,
        "charge_cents": charge_cents,
        "benefit_allocation_id": alloc["id"] if alloc is not None else None,
    }


def effective_discount_pct_from_product(rider, product, fday):
    """Same as effective_discount_pct but with the governing product supplied
    explicitly (PRD §3.7 step 1)."""
    eff = 0.0
    if _has_verified_unexpired_card(rider["id"], fday):
        eff = product["reduced_fare_pct"]
    if rider["income_tier"] == "LOW_INCOME":
        eff = max(eff, rider["low_income_discount_pct"])
    return eff


def _latest_prior_captured(rider_id, tapped_at, exclude_tap_id):
    """The rider's most recent CAPTURED tap with tapped_at strictly before the
    given instant; ties broken by created_at ASC (never id) — PRD §3.7 step 2."""
    candidates = _prior_captured_taps_same_rider(rider_id, tapped_at, exclude_tap_id)
    if not candidates:
        return None
    # Most recent => largest tapped_at; tie-break created_at ASC then _seq ASC.
    candidates.sort(key=lambda t: (util.parse_iso_datetime(t["tapped_at"]),
                                   t["created_at"], t["_seq"]))
    # The "most recent prior" is the last by tapped_at. Among equal tapped_at,
    # the spec tie-breaks created_at ASC -> the latest by tapped_at then we want
    # the one chosen by ascending created_at among the max tapped_at group.
    max_dt = util.parse_iso_datetime(candidates[-1]["tapped_at"])
    same = [t for t in candidates if util.parse_iso_datetime(t["tapped_at"]) == max_dt]
    same.sort(key=lambda t: (t["created_at"], t["_seq"]))
    return same[0]


# ---------------------------------------------------------------------------
# Forward-looking quote (PRD §3.9 / variant forward_looking_estimate)
# ---------------------------------------------------------------------------

def compute_quote(rider, product, fare_week, tapped_at):
    """Forward-looking pre-tap estimate (PRD §3.9).

    Same discount, transfer, and weekly-room logic as a real settle, but the
    day's cap is treated by APPENDING the hypothetical tap to today's
    already-captured set regardless of tapped_at.
    """
    fday = util.fare_day(tapped_at)
    eff = effective_discount_pct_from_product(rider, product, fday)

    # Step 1: per-ride list fare.
    list_fare_cents = util.scale_cents_by_discount(product["base_fare_cents"], eff)

    # Step 2: transfer discount (same as chronological_actual).
    prior = _latest_prior_captured(rider["id"], tapped_at, None)
    transfer_discount_cents = 0
    if prior is not None:
        prior_dt = util.parse_iso_datetime(prior["tapped_at"])
        window = timedelta(minutes=product["transfer_window_minutes"])
        if (tapped_at - prior_dt) <= window:
            transfer_discount_cents = util.pct_of_cents(list_fare_cents, product["transfer_discount_pct"])
    post_transfer = list_fare_cents - transfer_discount_cents

    # Step 3 (forward-looking daily cap by append):
    eff_daily_cap = util.scale_cents_by_discount(product["daily_cap_cents"], eff)
    eff_weekly_cap = util.scale_cents_by_discount(product["weekly_cap_cents"], eff)

    day_charged_so_far = 0
    daily_list_total = 0
    for t in db.taps.values():
        if t["rider_id"] != rider["id"] or t["status"] != "CAPTURED":
            continue
        t_dt = util.parse_iso_datetime(t["tapped_at"])
        if t_dt is not None and util.fare_day(t_dt) == fday:
            day_charged_so_far += t["charge_cents"]
            daily_list_total += t["list_fare_cents"]

    daily_marginal = max(min(eff_daily_cap, daily_list_total + list_fare_cents) - day_charged_so_far, 0)

    # Weekly room computed the same way as chronological_actual.
    weekly_room = max(eff_weekly_cap - fare_week["charged_total_cents"], 0)

    # The estimate respects post-transfer, the forward-looking daily marginal,
    # and the weekly room.
    billable = min(post_transfer, daily_marginal, weekly_room)
    cap_credit_cents = post_transfer - billable
    estimated_charge_cents = billable

    return {
        "list_fare_cents": list_fare_cents,
        "transfer_discount_cents": transfer_discount_cents,
        "cap_credit_cents": cap_credit_cents,
        "estimated_charge_cents": estimated_charge_cents,
    }


# ---------------------------------------------------------------------------
# Settle side effects (PRD §3.7) — capture / reject branch
# ---------------------------------------------------------------------------

def apply_capture(tap, funding_source, fare_week, computed):
    """CAPTURED branch side effects (PRD §3.7).

    Debit the funding source, accrue the week, consume + maybe exhaust the
    benefit allocation, refresh updated_at/version on every touched resource.
    """
    tap["list_fare_cents"] = computed["list_fare_cents"]
    tap["transfer_discount_cents"] = computed["transfer_discount_cents"]
    tap["cap_credit_cents"] = computed["cap_credit_cents"]
    tap["benefit_applied_cents"] = computed["benefit_applied_cents"]
    tap["charge_cents"] = computed["charge_cents"]
    tap["benefit_allocation_id"] = computed["benefit_allocation_id"]
    tap["status"] = "CAPTURED"

    funding_source["prepaid_balance_cents"] -= computed["charge_cents"]

    if computed["benefit_applied_cents"] > 0 and computed["benefit_allocation_id"]:
        alloc = db.benefit_allocations.get(computed["benefit_allocation_id"])
        if alloc is not None:
            alloc["consumed_cents"] += computed["benefit_applied_cents"]
            if alloc["consumed_cents"] >= alloc["allocated_cents"]:
                alloc["status"] = "EXHAUSTED"
            touch(alloc)

    fare_week["charged_total_cents"] += computed["charge_cents"]

    touch(tap)
    touch(funding_source)
    touch(fare_week)


def apply_reject(tap, computed):
    """REJECTED branch side effects (PRD §3.7).

    Record charge_cents as the amount that could not be settled; no debit, no
    week or allocation change. Only the tap is mutated.
    """
    tap["list_fare_cents"] = computed["list_fare_cents"]
    tap["transfer_discount_cents"] = computed["transfer_discount_cents"]
    tap["cap_credit_cents"] = computed["cap_credit_cents"]
    # benefit_applied / allocation are not applied on a rejected tap.
    tap["benefit_applied_cents"] = 0
    tap["benefit_allocation_id"] = None
    tap["charge_cents"] = computed["charge_cents"]
    tap["status"] = "REJECTED"
    touch(tap)


# ---------------------------------------------------------------------------
# Reverse side effects (PRD §3.10) — compensating action
# ---------------------------------------------------------------------------

def apply_reverse(tap, funding_source, fare_week):
    """Compensating reversal of a CAPTURED tap (PRD §3.10).

    Credit the funding source, decrement the week, restore + maybe un-exhaust
    the benefit allocation, refresh updated_at/version on every touched
    resource.
    """
    charge = tap["charge_cents"]
    benefit = tap["benefit_applied_cents"]

    funding_source["prepaid_balance_cents"] += charge
    fare_week["charged_total_cents"] -= charge

    if benefit > 0 and tap["benefit_allocation_id"]:
        alloc = db.benefit_allocations.get(tap["benefit_allocation_id"])
        if alloc is not None:
            alloc["consumed_cents"] -= benefit
            if alloc["consumed_cents"] < alloc["allocated_cents"] and alloc["status"] == "EXHAUSTED":
                alloc["status"] = "ACTIVE"
            touch(alloc)

    tap["status"] = "REVERSED"
    touch(tap)
    touch(funding_source)
    touch(fare_week)


# ---------------------------------------------------------------------------
# Rider risk score (PRD §3.2 / SCAFFOLD rider_risk_score)
# ---------------------------------------------------------------------------

def rider_risk_score(rider, mode):
    """Compute the rider's behavioral risk score in [0, 100] (PRD §3.2).

    gross: counts every REJECTED/REVERSED tap ever.
    trailing_week (default): counts only REJECTED/REVERSED taps whose tapped_at
    falls within the 7 days ending at the current clock instant.
    Low-balance flag: rider's default ACTIVE funding source balance < 500.
    """
    now = clock.now()
    window_start = now - timedelta(days=7)

    reject_count = 0
    reversal_count = 0
    for t in db.taps.values():
        if t["rider_id"] != rider["id"]:
            continue
        if t["status"] not in ("REJECTED", "REVERSED"):
            continue
        if mode == "trailing_week":
            t_dt = util.parse_iso_datetime(t["tapped_at"])
            if t_dt is None or not (window_start <= t_dt <= now):
                continue
        if t["status"] == "REJECTED":
            reject_count += 1
        else:
            reversal_count += 1

    low_balance = 0
    default_fs = _default_active_funding_source(rider["id"])
    if default_fs is not None and default_fs["prepaid_balance_cents"] < LOW_BALANCE_FLOOR_CENTS:
        low_balance = 1

    raw = W_REJECT * reject_count + W_REVERSAL * reversal_count + W_LOWBAL * low_balance
    return min(util.round_half_up_cents(raw), 100)


def _default_active_funding_source(rider_id):
    """The rider's default ACTIVE funding source (PRD §3.2 low-balance flag)."""
    for fs in db.funding_sources.values():
        if fs["rider_id"] == rider_id and fs["status"] == "ACTIVE" and fs["is_default"]:
            return fs
    return None
