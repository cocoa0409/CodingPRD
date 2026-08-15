"""Calculation rules per SCAFFOLD §1.3 / PRD §2.6, §3.3, §3.9.

Precision rules (PRD §2.6):
- rental_fee_quote / rental_fee_settlement: round EACH component half-up to
  whole cents individually, then sum the rounded components.
- deposit_hold_rule: sum tiered components first, round half-up exactly once.
- cross_rental_settlement: round half-up once.
- damage_charge_rule: whole cents, no rounding.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
import math

from db import store
from util import day_count


def _round_half_up(value):
    """Round a Decimal to whole cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Cartage zones (PRD §3.3)
REGION_WEST = {"LAX", "SFO", "SEA", "PDX"}
REGION_NORTHEAST = {"NYC", "BOS", "PHI", "DC"}
REGION_MIDSOUTH = {"NASH", "ATL", "MEM"}
REGIONS = [REGION_WEST, REGION_NORTHEAST, REGION_MIDSOUTH]

INSURANCE_RISK_THRESHOLD = 50
INSURANCE_SURCHARGE_PCT = Decimal("0.08")
LATE_MULTIPLIER = Decimal("1.5")

MIN_CONDITION_SCORE = 40
MAX_RENTAL_DAYS_SINCE_SERVICE = 30
TRANSIT_BUFFER_DAYS = 1


def zone_multiplier(origin_city_code, dest_city_code):
    """1.00 same city; 1.10 both in one region; 1.25 cross-region."""
    if origin_city_code == dest_city_code:
        return Decimal("1.00")
    for region in REGIONS:
        if origin_city_code in region and dest_city_code in region:
            return Decimal("1.10")
    return Decimal("1.25")


def rental_fee_quote(base_rate_cents, days, origin_city_code, dest_city_code, risk_score):
    """Forward-looking provisional fee (PRD §3.3). Per-component rounding."""
    base = base_rate_cents * days
    mult = zone_multiplier(origin_city_code, dest_city_code)
    cartage = _round_half_up(Decimal(base) * (mult - Decimal("1.0")))
    if risk_score >= INSURANCE_RISK_THRESHOLD:
        insurance = _round_half_up(Decimal(base) * INSURANCE_SURCHARGE_PCT)
    else:
        insurance = 0
    return base + cartage + insurance


def rental_fee_settlement(base_rate_cents, days, origin_city_code, dest_city_code,
                          risk_score, end_date, checked_in_at, was_shorted):
    """Chronological final fee (PRD §3.9).

    - late fee: each started 24h block past end_date until check-in adds 1 day
      at 150% of base_rate; the inflated day rate is rounded half-up once, then
      multiplied by the block count.
    - insurance uses settle-time risk_score.
    - shortage credit subtracts the entire base when the line was shorted.
    - floor at 0 applied last.
    """
    base = base_rate_cents * days
    late_blocks = 0
    if checked_in_at is not None and checked_in_at > end_date:
        delta_seconds = (checked_in_at - end_date).total_seconds()
        late_blocks = int(math.ceil(delta_seconds / 86400.0))
    late_day_rate = _round_half_up(Decimal(base_rate_cents) * LATE_MULTIPLIER)
    late_fee = late_blocks * late_day_rate
    mult = zone_multiplier(origin_city_code, dest_city_code)
    cartage = _round_half_up(Decimal(base) * (mult - Decimal("1.0")))
    if risk_score >= INSURANCE_RISK_THRESHOLD:
        insurance = _round_half_up(Decimal(base) * INSURANCE_SURCHARGE_PCT)
    else:
        insurance = 0
    shortage_credit = base if was_shorted else 0
    total = base + cartage + insurance + late_fee - shortage_credit
    return max(0, total)


def deposit_hold_rule(replacement_value_cents, deposit_waived):
    """Tiered deposit hold (PRD §2.7/§3.3). Sum tiers first, round half-up once."""
    if deposit_waived:
        return 0
    rv = replacement_value_cents
    tier1 = Decimal("0.20") * Decimal(min(rv, 200_000))
    tier2 = Decimal("0.15") * Decimal(min(max(rv - 200_000, 0), 300_000))
    tier3 = Decimal("0.10") * Decimal(max(rv - 500_000, 0))
    return _round_half_up(tier1 + tier2 + tier3)


def damage_charge_rule(assessed_severity, repair_estimate_cents, replacement_value_cents,
                       linked_deposit_held_cents):
    """Damage charge (PRD §3.7). Whole cents, no rounding.

    Returns (charge_cents, overage_cents): overage is the portion strictly
    exceeding the linked reservation's deposit_held_cents.
    """
    if assessed_severity == "TOTAL_LOSS":
        charge = replacement_value_cents
    else:
        charge = repair_estimate_cents
    overage = max(0, charge - linked_deposit_held_cents)
    return charge, overage


def cross_rental_settlement(vendor_rate_cents_per_day, days, commission_bps):
    """Commission owed by the vendor (PRD §3.8). Rounded half-up once."""
    vendor_revenue = vendor_rate_cents_per_day * days
    return _round_half_up(Decimal(vendor_revenue) * Decimal(commission_bps) / Decimal(10_000))


def maintenance_cycle_gate(rental_days_since_service, condition_score, reservation_days):
    """Decide AVAILABLE vs MAINTENANCE at check-in (PRD §2.8, §3.6).

    Returns (force_maintenance, opened_reason or None). Boundary: projected
    days == 30 forces MAINTENANCE; condition_score == 40 does not.
    """
    projected = rental_days_since_service + reservation_days
    if projected >= MAX_RENTAL_DAYS_SINCE_SERVICE:
        return True, "SCHEDULED_CYCLE"
    if condition_score < MIN_CONDITION_SCORE:
        return True, "CONDITION_THRESHOLD"
    return False, None


# Damage severity weights for the artist risk score (PRD §3.1)
RISK_WEIGHTS = {"COSMETIC": 2, "MINOR": 5, "MAJOR": 12, "TOTAL_LOSS": 30}
RISK_ELIGIBLE_STATUSES = {"ASSESSED", "CHARGED", "DISPUTED", "PAID"}
RECENCY_WINDOW_DAYS = 90
RECENCY_MULT = 2
RISK_CAP = 100

# Condition-score impact per damage assessment (PRD §3.7)
CONDITION_IMPACT = {"COSMETIC": 5, "MINOR": 15, "MAJOR": 35, "TOTAL_LOSS": 100}


def artist_risk_score(artist_id):
    """Recompute from scratch (PRD §3.1). Claims of the artist's reservations
    in {ASSESSED, CHARGED, DISPUTED, PAID} assessed within trailing 365 days.
    Weight doubled when assessment is no more than 90 days old.
    """
    from db import store as _store
    now = _store.current_utc
    # Collect reservation ids belonging to this artist's tours
    artist_tour_ids = {t["id"] for t in _store.tours.values() if t.get("artist_id") == artist_id}
    artist_res_ids = {r["id"] for r in _store.reservation_lines.values()
                      if r.get("tour_id") in artist_tour_ids}
    raw = 0
    for claim in _store.damage_claims.values():
        if claim.get("reservation_line_id") not in artist_res_ids:
            continue
        if claim.get("status") not in RISK_ELIGIBLE_STATUSES:
            continue
        assessed_at = claim.get("assessed_at_dt")
        if assessed_at is None:
            continue
        age_days = (now - assessed_at).total_seconds() / 86400.0
        if age_days < 0:
            # Assessment in the future relative to logical clock: still within window
            age_days = 0
        if age_days > 365:
            continue
        weight = RISK_WEIGHTS.get(claim.get("assessed_severity"), 0)
        mult = RECENCY_MULT if age_days <= RECENCY_WINDOW_DAYS else 1
        raw += weight * mult
    return min(RISK_CAP, max(0, raw))


def gear_availability_window(gear_model_id, window_start, window_end, stop_city_code,
                             exclude_reservation_id=None):
    """Pick the GearUnit to source for a rider line (SCAFFOLD gear_availability_window).

    Candidate must: match model, not be out of service (MAINTENANCE /
    QUARANTINED / RETIRED are excluded), condition >= 40,
    rental_days_since_service < 30, and have no conflicting SOURCED/DISPATCHED/
    DELIVERED reservation overlapping the half-open window (a unit committed to
    a non-overlapping reservation remains a candidate — windows that merely
    touch do not conflict, PRD §2.5/§3.3). Units whose home_city_code != stop
    city use an effective window starting 1 day earlier.
    Ranking: same-city first, then fewest rental_days_since_service, then
    earliest created_at. Tie-break on created_at, never id.

    Returns (best_unit_or_None, saw_unserviceable_flag).
    """
    candidates = []
    saw_unserviceable = False
    for unit in store.gear_units.values():
        if unit.get("gear_model_id") != gear_model_id:
            continue
        # Units out of service (maintenance / quarantine / retirement) are
        # never candidates. Units merely committed to other reservations stay
        # in the pool: the half-open window-overlap clause below (PRD §3.3) is
        # what excludes them — windows that merely touch do not conflict.
        if unit.get("status") in {"MAINTENANCE", "QUARANTINED", "RETIRED"}:
            continue
        if unit.get("condition_score", 100) < MIN_CONDITION_SCORE or \
                unit.get("rental_days_since_service", 0) >= MAX_RENTAL_DAYS_SINCE_SERVICE:
            saw_unserviceable = True
            continue
        # Effective window with transit buffer for cross-city units
        same_city = unit.get("home_city_code") == stop_city_code
        eff_start = window_start if same_city else window_start - timedelta(days=TRANSIT_BUFFER_DAYS)
        # Conflict check: reservations in occupied statuses overlapping [eff_start, window_end)
        conflict = False
        for r in store.reservation_lines.values():
            if r.get("gear_unit_id") != unit["id"]:
                continue
            if exclude_reservation_id is not None and r["id"] == exclude_reservation_id:
                continue
            if r.get("status") not in {"SOURCED", "DISPATCHED", "DELIVERED"}:
                continue
            r_start = r["_start_dt"]
            r_end = r["_end_dt"]
            # half-open overlap; adjacent end==start does NOT overlap
            if r_start < window_end and r_end > eff_start:
                conflict = True
                break
        if conflict:
            continue
        candidates.append((unit, same_city))
    if not candidates:
        return None, saw_unserviceable
    # Ranking: same-city DESC, rental_days ASC, created_at ASC (never id)
    candidates.sort(key=lambda t: (
        0 if t[1] else 1,
        t[0].get("rental_days_since_service", 0),
        t[0]["created_at"],
    ))
    return candidates[0][0], saw_unserviceable


def approved_vendor_covers_city(city_code):
    """Whether any APPROVED partner vendor covers the given city."""
    for v in store.partner_vendors.values():
        if v.get("status") == "APPROVED" and city_code in (v.get("city_codes") or []):
            return True
    return False
