"""The calculation rules (PRD 2.8 and section 3).

All money is whole integer cents and every non-integer intermediate is rounded
HALF UP -- a value exactly at the half boundary rounds away from zero, upward.
Where a calculation rounds more than once the ORDER of rounding is part of the
specification and is not interchangeable with an equivalent-looking alternative.
"""

from decimal import Decimal, ROUND_HALF_UP

import clock
from store import DB, ordered
import derive

# ---- global constants (SCAFFOLD global_constants) --------------------------
STRAY_HOLD_STRAY_IDENTIFIABLE_DAYS = 7
STRAY_HOLD_STRAY_UNIDENTIFIABLE_DAYS = 3
STRAY_HOLD_OWNER_SURRENDER_DAYS = 0
STRAY_HOLD_CONFISCATE_DAYS = 10
STRAY_HOLD_TRANSFER_IN_DAYS = 1
STRAY_HOLD_RETURN_DAYS = 0

HOME_CHECK_VALID_DAYS = 180

CVI_WINDOW_DAYS_DOG = 30
CVI_WINDOW_DAYS_CAT = 15
CVI_WINDOW_DAYS_OTHER = 10
RABIES_MIN_AGE_WEEKS = 12

FOSTER_SLOT_COST_INDIVIDUAL = 1
FOSTER_SLOT_COST_NURSING_UNIT = 2

CRATE_UNITS_SMALL = 1
CRATE_UNITS_MEDIUM = 2
CRATE_UNITS_LARGE = 3
CRATE_UNITS_LITTER_GROUPED = 2
DRIVER_TURNAROUND_BUFFER_MINUTES = 60

BASE_RECLAIM_FEE_CENTS = 4500
IMPOUND_TIER1_MAX_DAYS = 3
IMPOUND_TIER2_MAX_DAYS = 7
IMPOUND_TIER1_PER_DAY_CENTS = 1500
IMPOUND_TIER2_PER_DAY_CENTS = 2500
IMPOUND_TIER3_PER_DAY_CENTS = 4000
REPEAT_OFFENSE_MULTIPLIER_NONE = 1.0
REPEAT_OFFENSE_MULTIPLIER_SECOND = 1.5
REPEAT_OFFENSE_MULTIPLIER_THIRD_PLUS = 2.0
RECLAIM_WAIVER_TOTAL_THRESHOLD_CENTS = 20000
RECLAIM_HARDSHIP_WAIVER_CENTS = 2000

ADOPTION_BASE_FEE_DOG_CENTS = 25000
ADOPTION_BASE_FEE_CAT_CENTS = 12500
ADOPTION_BASE_FEE_OTHER_CENTS = 6000
SENIOR_WAIVER_AGE_MONTHS = 84
SENIOR_WAIVER_PCT = Decimal("0.60")
LONG_STAY_WAIVER_DAYS = 120
LONG_STAY_WAIVER_PCT = Decimal("0.50")

ALTERATION_MIN_AGE_WEEKS = 16
ALTERATION_DEPOSIT_FLAT_CENTS = 15000
ALTERATION_DEPOSIT_PER_WEEK_CENTS = 1200
ALTERATION_DEPOSIT_SCALED_FLOOR_CENTS = 6000
ALTERATION_DEPOSIT_SCALED_CAP_CENTS = 18000

RETURN_WINDOW_FULL_DAYS = 14
RETURN_WINDOW_PARTIAL_DAYS = 30
RETURN_REFUND_PCT_FULL = Decimal("1.00")
RETURN_REFUND_PCT_PARTIAL = Decimal("0.50")
RETURN_REFUND_PCT_NONE = Decimal("0.00")

MEDICAL_ADMIN_OVERHEAD_PCT = Decimal("0.08")
MAX_ADOPTION_APPLICATION_ATTEMPTS = 3
LIVE_RELEASE_RATE_PRECISION_DP = 4


def round_half_up(value):
    """Round a Decimal to whole cents, half away from zero (upward)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_dp(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# =====================================================================
#  Intake, the stray hold clock and the owner reclaim (PRD 3.2)
# =====================================================================

def stray_hold_days(intake_type, identifiable_at_intake):
    if intake_type == "STRAY":
        return (STRAY_HOLD_STRAY_IDENTIFIABLE_DAYS if identifiable_at_intake
                else STRAY_HOLD_STRAY_UNIDENTIFIABLE_DAYS)
    if intake_type == "OWNER_SURRENDER":
        return STRAY_HOLD_OWNER_SURRENDER_DAYS
    if intake_type == "CONFISCATE":
        return STRAY_HOLD_CONFISCATE_DAYS
    if intake_type == "TRANSFER_IN":
        return STRAY_HOLD_TRANSFER_IN_DAYS
    return STRAY_HOLD_RETURN_DAYS


def impound_billable_days(record):
    """Dual variant selected by IntakeRecord.impound_billing_basis."""
    start = clock.parse(record["intake_datetime"])
    now = clock.now()
    if record["impound_billing_basis"] == "CALENDAR_DAY":
        days = (now.date() - start.date()).days + 1
    else:  # OVERNIGHT
        days = clock.elapsed_days(now, start)
    return max(1, days)


def impound_tiered_subtotal(days):
    """Marginal tiers, not an average rate."""
    t1 = min(days, IMPOUND_TIER1_MAX_DAYS)
    t2 = min(max(days - IMPOUND_TIER1_MAX_DAYS, 0), IMPOUND_TIER2_MAX_DAYS - IMPOUND_TIER1_MAX_DAYS)
    t3 = max(days - IMPOUND_TIER2_MAX_DAYS, 0)
    return (t1 * IMPOUND_TIER1_PER_DAY_CENTS
            + t2 * IMPOUND_TIER2_PER_DAY_CENTS
            + t3 * IMPOUND_TIER3_PER_DAY_CENTS)


def repeat_offense_multiplier(history_count):
    if history_count == 0:
        return REPEAT_OFFENSE_MULTIPLIER_NONE
    if history_count == 1:
        return REPEAT_OFFENSE_MULTIPLIER_SECOND
    return REPEAT_OFFENSE_MULTIPLIER_THIRD_PLUS


def reclaim_total(subtotal_cents, multiplier, hardship_certified):
    """PRD 2.8/3.2: the multiplier acts on the impound subtotal ALONE and the
    product is rounded BEFORE the flat base reclaim fee is added -- never the
    other way round, and never with the base fee inside the multiplication.
    The waiver test then reads the PRE-waiver total, never the final figure."""
    step1 = round_half_up(Decimal(subtotal_cents) * Decimal(str(multiplier)))
    step2 = BASE_RECLAIM_FEE_CENTS + step1                       # pre-waiver total
    waiver = (RECLAIM_HARDSHIP_WAIVER_CENTS
              if (step2 >= RECLAIM_WAIVER_TOTAL_THRESHOLD_CENTS and hardship_certified)
              else 0)
    return step1, step2, waiver, max(0, step2 - waiver)


# =====================================================================
#  Adoption money (PRD 3.8)
# =====================================================================

def adoption_base_fee(species):
    if species == "DOG":
        return ADOPTION_BASE_FEE_DOG_CENTS
    if species == "CAT":
        return ADOPTION_BASE_FEE_CAT_CENTS
    return ADOPTION_BASE_FEE_OTHER_CENTS


def adoption_waiver_selection(animal):
    """Waivers never stack; when both qualify only the strictly larger is used."""
    senior_ok = derive.age_months(animal) >= SENIOR_WAIVER_AGE_MONTHS
    long_stay_ok = derive.length_of_stay_days(animal) >= LONG_STAY_WAIVER_DAYS
    if senior_ok and long_stay_ok:
        return ("SENIOR", SENIOR_WAIVER_PCT) if SENIOR_WAIVER_PCT > LONG_STAY_WAIVER_PCT \
            else ("LONG_STAY", LONG_STAY_WAIVER_PCT)
    if senior_ok:
        return "SENIOR", SENIOR_WAIVER_PCT
    if long_stay_ok:
        return "LONG_STAY", LONG_STAY_WAIVER_PCT
    return "NONE", Decimal("0")


def adoption_sponsorship_pool(animal_id):
    """Eligible contributions ranked by three keys applied in sequence:
    rows designated to this animal first, then created_at ascending, then
    donor_reference ascending lexicographically.  Entity ids never participate."""
    eligible = []
    for c in DB.all("Contribution"):
        if c["status"] not in ("RECEIVED", "PARTIALLY_APPLIED"):
            continue
        if derive.available_cents(c) <= 0:
            continue
        if c["designated_animal_id"] == animal_id or c["designated_program"] == "ADOPTION_FEE_ASSISTANCE":
            eligible.append(c)
    eligible.sort(key=lambda c: (0 if c["designated_animal_id"] == animal_id else 1,
                                 c["_created_dt"],
                                 c["donor_reference"]))
    total = sum(derive.available_cents(c) for c in eligible)
    return eligible, total


def adoption_fee_waterfall(base_fee_cents, waiver_pct, available_credit_cents, order):
    """Dual variant selected by Adoption.credit_application_order.  Exactly one
    rounding occurs on either branch and the three components always sum back
    to base_fee_cents."""
    if order == "CREDIT_FIRST":
        sponsorship = min(base_fee_cents, available_credit_cents)
        remaining = base_fee_cents - sponsorship
        waiver = round_half_up(Decimal(remaining) * waiver_pct)
        charged = remaining - waiver
    else:  # WAIVER_FIRST
        waiver = round_half_up(Decimal(base_fee_cents) * waiver_pct)
        after_waiver = base_fee_cents - waiver
        sponsorship = min(after_waiver, available_credit_cents)
        charged = after_waiver - sponsorship
    residual = available_credit_cents - sponsorship
    return sponsorship, waiver, charged, residual


def alteration_deposit(animal, deposit_basis):
    """Dual variant selected by Adoption.deposit_basis."""
    if deposit_basis == "FLAT":
        return ALTERATION_DEPOSIT_FLAT_CENTS
    raw = (ALTERATION_MIN_AGE_WEEKS - derive.age_weeks(animal)) * ALTERATION_DEPOSIT_PER_WEEK_CENTS
    return min(max(raw, ALTERATION_DEPOSIT_SCALED_FLOOR_CENTS), ALTERATION_DEPOSIT_SCALED_CAP_CENTS)


def return_refund_pct(elapsed):
    if elapsed <= RETURN_WINDOW_FULL_DAYS:
        return RETURN_REFUND_PCT_FULL
    if elapsed <= RETURN_WINDOW_PARTIAL_DAYS:
        return RETURN_REFUND_PCT_PARTIAL
    return RETURN_REFUND_PCT_NONE


def allocate_restoration(lines, total):
    """Split `total` restored cents across the sponsorship draw lines.

    # Adjudication of friction 9: Reading A -- the restoration is spread
    # PROPORTIONALLY across each drawn contribution, in proportion to what each
    # one supplied.  The PRD says the total restored and every conservation
    # identity are identical under both readings, so nothing is stranded either
    # way; Reading A is chosen because it is the reading the rest of the
    # specification already assumes -- the refund_basis field is described as
    # restoring "a proportional share of applied sponsorship credit".
    # Remainder handling: every line but the last takes its rounded
    # proportional share and the last line absorbs the residue, so the parts
    # sum back to `total` exactly.
    """
    supplied = sum(amount for _, amount in lines)
    if supplied <= 0 or total <= 0:
        return [(cid, 0) for cid, _ in lines]
    out = []
    allocated = 0
    for index, (cid, amount) in enumerate(lines):
        if index == len(lines) - 1:
            share = total - allocated
        else:
            share = round_half_up(Decimal(total) * Decimal(amount) / Decimal(supplied))
            share = min(share, amount, total - allocated)
        allocated += share
        out.append((cid, share))
    return out


# =====================================================================
#  Foster capacity (PRD 3.4)
# =====================================================================

def foster_slot_consumption(count_basis):
    return FOSTER_SLOT_COST_INDIVIDUAL if count_basis == "INDIVIDUAL" else FOSTER_SLOT_COST_NURSING_UNIT


def foster_headcount_consumption(count_basis, litter_id):
    """Deliberately NOT proportional to slot_consumption."""
    if count_basis == "INDIVIDUAL":
        return 1
    return 1 + derive.litter_member_count(litter_id) if litter_id else 1


def species_bucket(species):
    """A DOG consumes dog slots; a CAT and an OTHER both consume cat slots."""
    return "dog" if species == "DOG" else "cat"


def recompute_home(home):
    """Recompute a home's counters from scratch; only ACTIVE placements count.

    Returns True when capacity_status flipped, so the caller can honour PRD 3.4:
    "each flip in either direction increments the home's version by one".
    """
    dog = cat = heads = 0
    for p in DB.where("FosterPlacement", foster_home_id=home["id"], status="ACTIVE"):
        a = DB.get("Animal", p["animal_id"])
        if a is not None and species_bucket(a["species"]) == "dog":
            dog += p["slot_consumption"]
        else:
            cat += p["slot_consumption"]
        heads += p["headcount_consumption"]
    home["consumed_dog_slots"] = dog
    home["consumed_cat_slots"] = cat
    home["consumed_headcount"] = heads
    dog_free = home["dog_slot_capacity"] - dog
    cat_free = home["cat_slot_capacity"] - cat
    head_free = home["max_headcount"] - heads
    status = "OPEN" if ((dog_free > 0 or cat_free > 0) and head_free > 0) else "FULL"
    flipped = status != home["capacity_status"]
    home["capacity_status"] = status
    return flipped


# =====================================================================
#  Transport (PRD 3.6)
# =====================================================================

MANIFEST_OCCUPYING = ("ASSIGNED", "LOADED", "DELIVERED")


def per_animal_crate_units(size_class):
    if size_class == "SMALL":
        return CRATE_UNITS_SMALL
    if size_class == "MEDIUM":
        return CRATE_UNITS_MEDIUM
    return CRATE_UNITS_LARGE


def litter_transport_units(animal, leg_id):
    """Dual variant selected by the animal's litter posture."""
    litter_id = animal.get("litter_id")
    litter = DB.get("Litter", litter_id) if litter_id else None
    if litter is None or litter["transport_basis"] == "SPLIT_APPROVED":
        return per_animal_crate_units(animal["size_class"]), False
    for entry in DB.where("ManifestEntry", transport_leg_id=leg_id):
        if entry["status"] not in MANIFEST_OCCUPYING:
            continue
        other = DB.get("Animal", entry["animal_id"])
        if other is not None and other.get("litter_id") == litter_id:
            return 0, False
    return CRATE_UNITS_LITTER_GROUPED, True


def recompute_leg(leg):
    """Conservation identity 5 -- BUMPED and STRANDED entries are excluded."""
    crates = 0
    weight = Decimal("0")
    for entry in DB.where("ManifestEntry", transport_leg_id=leg["id"]):
        if entry["status"] not in MANIFEST_OCCUPYING:
            continue
        crates += entry["crate_units"]
        a = DB.get("Animal", entry["animal_id"])
        if a is not None:
            weight += Decimal(str(a["weight_lb"]))
    leg["used_crate_units"] = crates
    leg["used_weight_lb"] = float(round_dp(weight, 2))
    return leg


def leg_species_compatible(leg, candidate):
    """DELIVERED entries are excluded from this particular test even though they
    still count toward crate and weight."""
    manifest = []
    for entry in ordered(DB.where("ManifestEntry", transport_leg_id=leg["id"])):
        if entry["status"] not in ("ASSIGNED", "LOADED"):
            continue
        a = DB.get("Animal", entry["animal_id"])
        if a is not None:
            manifest.append(a)
    manifest.append(candidate)
    policy = leg["species_policy"]
    if policy == "DOGS_ONLY":
        return all(a["species"] == "DOG" for a in manifest)
    if policy == "CATS_ONLY":
        return all(a["species"] == "CAT" for a in manifest)
    if policy == "MIXED_SEGREGATED":
        for a in manifest:
            if a["temperament"] != "REACTIVE":
                continue
            for b in manifest:
                if b is a:
                    continue
                if b["species"] != a["species"]:
                    return False
        return True
    return sum(1 for a in manifest if a["temperament"] == "REACTIVE") < 2


def cvi_window_days(species):
    if species == "DOG":
        return CVI_WINDOW_DAYS_DOG
    if species == "CAT":
        return CVI_WINDOW_DAYS_CAT
    return CVI_WINDOW_DAYS_OTHER


def governing_certificate(animal_id, destination_state):
    """The row with the greatest issued_at, tie-broken by the greatest created_at."""
    matches = [c for c in DB.all("HealthCertificate")
               if c["animal_id"] == animal_id and c["destination_state"] == destination_state]
    if not matches:
        return None
    matches.sort(key=lambda c: (clock.parse(c["issued_at"]), c["_created_dt"], c["id"]))
    return matches[-1]


def rabies_eligible(animal):
    vaccinated = animal.get("rabies_vaccinated_at")
    if not vaccinated:
        return False
    days = clock.elapsed_days(clock.parse(vaccinated), clock.parse(animal["date_of_birth"]))
    return (days // 7) >= RABIES_MIN_AGE_WEEKS


def driver_interval_conflict(driver_person_id, depart_raw, arrive_raw):
    """Exclusive occupancy with an asymmetric turnaround buffer appended to the
    END of each EXISTING leg only, never to its start and never to the candidate.
    Half-open intervals: a.start < b.end AND b.start < a.end."""
    from datetime import timedelta
    cand_start = clock.parse(depart_raw)
    cand_end = clock.parse(arrive_raw)
    buffer_delta = timedelta(minutes=DRIVER_TURNAROUND_BUFFER_MINUTES)
    for leg in DB.all("TransportLeg"):
        if leg["driver_person_id"] != driver_person_id:
            continue
        if leg["status"] not in ("SCHEDULED", "DEPARTED"):
            continue
        occ_start = clock.parse(leg["scheduled_depart_at"])
        occ_end = clock.parse(leg["scheduled_arrive_at"]) + buffer_delta
        if cand_start < occ_end and occ_start < cand_end:
            return True
    return False


# =====================================================================
#  Medical funding (PRD 3.5)
# =====================================================================

def medical_eligible_pool(record, named_ids=None):
    """Draw order is fully pinned: created_at ASC, then amount_cents DESC among
    rows created at the same instant, then donor_reference ASC as a last resort."""
    if named_ids is not None:
        rows = [DB.get("Contribution", cid) for cid in named_ids]
        rows = [r for r in rows if r is not None]
    else:
        rows = DB.all("Contribution")
    eligible = []
    for c in rows:
        if c["status"] not in ("RECEIVED", "PARTIALLY_APPLIED"):
            continue
        if derive.available_cents(c) <= 0:
            continue
        if not (c["restriction_category"] == record["expense_category"]
                or c["restriction_category"] == "UNRESTRICTED"):
            continue
        if c["designated_animal_id"] is not None and c["designated_animal_id"] != record["animal_id"]:
            continue
        eligible.append(c)
    eligible.sort(key=lambda c: (c["_created_dt"], -c["amount_cents"], c["donor_reference"]))
    return eligible


def medical_admin_overhead(line_cents):
    """Overhead is rounded PER DRAW LINE and only then summed; summing the lines
    first and rounding once produces a different total and is incorrect."""
    return round_half_up(Decimal(line_cents) * MEDICAL_ADMIN_OVERHEAD_PCT)
