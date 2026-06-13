"""Core domain logic: derived donor fields, eligibility, intervals, inventory
buckets, screening outcome, plasma caps, deferral creation, and cascades.

Every time-sensitive computation reads the owning center's current_utc, never
wall-clock time.
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from timeutil import (
    EPOCH_ISO,
    SECONDS_PER_DAY,
    add_days_iso,
    iso_to_epoch,
    parse_date,
    parse_iso,
)

# ---- constants (from SCAFFOLD calculations) ---------------------------------
WHOLE_INTERVAL_DAYS = 56
PLASMA_INTERVAL_DAYS = 28
PLATELET_INTERVAL_DAYS = 7
INTERVAL_BY_TYPE = {
    "WHOLE": WHOLE_INTERVAL_DAYS,
    "PLASMA": PLASMA_INTERVAL_DAYS,
    "PLATELET": PLATELET_INTERVAL_DAYS,
}

RBC_SHELF_DAYS = 42
PLASMA_SHELF_DAYS = 365
WHOLE_SHELF_DAYS = 35
PLATELET_SHELF_DAYS = 5

UNISEX_HGB_FLOOR = Decimal("12.5")
MIN_WEIGHT_KG = 50
BP_SYS_MIN = 90
BP_SYS_MAX = 180
PULSE_MIN = 50
PULSE_MAX = 100
HEMOGLOBIN_DEFERRAL_DAYS = 90
TRAVEL_DEFERRAL_DAYS = 21
MED_DEFERRAL_DAYS = 14

PER_CAP_LOW = 690
PER_CAP_MID = 825
PER_CAP_HIGH = 880
WEIGHT_BAND_LOW_MAX = 68
WEIGHT_BAND_MID_MAX = 79
ANNUAL_PLASMA_LITERS_CAP = Decimal("2.00")
ROLLING_WINDOW_DAYS = 365

DONATION_COLLECTED_OR_BEYOND = {"COLLECTED", "RELEASABLE", "DISCARDED"}

BLOOD_TYPES = {"O_NEG", "O_POS", "A_NEG", "A_POS", "B_NEG", "B_POS", "AB_NEG", "AB_POS", "UNKNOWN"}
COMPONENTS = {"RBC", "PLASMA", "PLATELET", "WHOLE_BLOOD"}


# ---- center clock -----------------------------------------------------------
def center_now(center):
    return center["current_utc"]


# ---- donor age / eligibility ------------------------------------------------
def _age_years_at(dob_str, current_iso):
    """Whole years between date_of_birth and the center's current_utc."""
    dob = parse_date(dob_str)
    if dob is None:
        return None
    now_dt = parse_iso(current_iso)
    now_date = now_dt.date()
    years = now_date.year - dob.year
    if (now_date.month, now_date.day) < (dob.month, dob.day):
        years -= 1
    return years


def is_underage(donor, center):
    age = _age_years_at(donor.get("date_of_birth"), center["current_utc"])
    if age is None:
        return False
    return age < 18


def active_deferrals_for(donor_id):
    return [d for d in db.deferrals.values()
            if d["donor_id"] == donor_id and d["status"] == "ACTIVE"]


def recompute_eligibility(donor, center):
    """Derive eligibility_status from active deferrals + age. PERM beats TEMP
    beats UNDERAGE beats ELIGIBLE."""
    actives = active_deferrals_for(donor["id"])
    has_perm = any(d["kind"] == "PERMANENT" for d in actives)
    has_temp = any(d["kind"] == "TEMPORARY" for d in actives)
    if has_perm:
        status = "PERM_DEFERRED"
    elif has_temp:
        status = "TEMP_DEFERRED"
    elif is_underage(donor, center):
        status = "UNDERAGE"
    else:
        status = "ELIGIBLE"
    donor["eligibility_status"] = status
    return status


# ---- donor donation-derived fields ------------------------------------------
def donor_collected_donations(donor_id):
    """This donor's donations that ever reached COLLECTED-or-beyond."""
    return [d for d in db.donations.values()
            if d["donor_id"] == donor_id and d["status"] in DONATION_COLLECTED_OR_BEYOND]


def recompute_donor_donation_fields(donor):
    donor_id = donor["id"]
    collected = donor_collected_donations(donor_id)
    donor["lifetime_collected_count"] = len(collected)
    if collected:
        # most recent by collected_at DESC then created_at DESC
        best = sorted(
            collected,
            key=lambda d: (d.get("collected_at", ""), d.get("created_at", "")),
            reverse=True,
        )[0]
        donor["last_qualifying_donation_id"] = best["id"]
    else:
        donor["last_qualifying_donation_id"] = None


def open_appointment_for(donor_id):
    opens = [a for a in db.appointments.values()
             if a["donor_id"] == donor_id and a["status"] in ("SCHEDULED", "CHECKED_IN")]
    return opens[0] if opens else None


def recompute_pending_donation_type(donor):
    appt = open_appointment_for(donor["id"])
    donor["pending_donation_type"] = appt["donation_type"] if appt else "NONE"


def recompute_donor(donor, center, bump=True):
    """Recompute all derived donor fields and bump version/timestamp."""
    recompute_donor_donation_fields(donor)
    recompute_pending_donation_type(donor)
    recompute_eligibility(donor, center)
    if bump:
        db.touch(donor)


def donor_view(donor):
    """Return a donor snapshot with eligibility/interval fields recomputed
    against the current clock (read path). Does NOT bump version."""
    center = db.centers.get(donor["center_id"])
    if center is not None:
        recompute_donor_donation_fields(donor)
        recompute_pending_donation_type(donor)
        recompute_eligibility(donor, center)
    return donor


# ---- inter-donation interval (FINAL variant, authoritative at check-in) -----
def final_next_eligible_epoch(donor, donation_type):
    """Epoch seconds of the FINAL next-eligible instant for a donation_type."""
    last_id = donor.get("last_qualifying_donation_id")
    if last_id and last_id in db.donations:
        base_iso = db.donations[last_id]["collected_at"]
    else:
        base_iso = EPOCH_ISO
    interval = INTERVAL_BY_TYPE[donation_type]
    return iso_to_epoch(base_iso) + interval * SECONDS_PER_DAY


def interval_elapsed(donor, donation_type, center):
    now_epoch = iso_to_epoch(center["current_utc"])
    return now_epoch >= final_next_eligible_epoch(donor, donation_type)


# ---- screening outcome ------------------------------------------------------
def compute_screening_outcome(hemoglobin, weight, systolic, pulse, travel, medication):
    """Return (outcome, failure_reason) per the fixed five-check order."""
    hgb = Decimal(str(hemoglobin)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if hgb < UNISEX_HGB_FLOOR:
        return "FAIL", "HEMOGLOBIN_LOW"
    if weight < MIN_WEIGHT_KG:
        return "FAIL", "UNDERWEIGHT"
    if not (BP_SYS_MIN <= systolic <= BP_SYS_MAX and PULSE_MIN <= pulse <= PULSE_MAX):
        return "FAIL", "VITALS_OUT_OF_RANGE"
    if travel:
        return "FAIL", "TRAVEL_RISK"
    if medication:
        return "FAIL", "MEDICATION"
    return "PASS", "NONE"


# ---- deferral creation (shared by manual + auto-raise cascades) -------------
def create_deferral(donor, center, category, kind, reason, duration_days=None,
                    source_reaction_id=None):
    """Create a Deferral row, recompute donor eligibility. Returns the deferral."""
    starts_at = center["current_utc"]
    if kind == "TEMPORARY":
        expires_at = add_days_iso(starts_at, duration_days)
    else:
        expires_at = None
    deferral = {
        "donor_id": donor["id"],
        "center_id": donor["center_id"],
        "category": category,
        "kind": kind,
        "reason": reason,
        "starts_at": starts_at,
        "expires_at": expires_at,
        "duration_days": duration_days if kind == "TEMPORARY" else None,
        "status": "ACTIVE",
        "source_reaction_id": source_reaction_id,
    }
    db.stamp_new(deferral)
    db.deferrals[deferral["id"]] = deferral
    recompute_donor(donor, center)
    return deferral


# ---- inventory buckets ------------------------------------------------------
def recount_bucket(bucket):
    """Live recount of available/reserved counts over BloodUnit rows."""
    center_id = bucket["center_id"]
    blood_type = bucket["blood_type"]
    component = bucket["component"]
    available = 0
    reserved = 0
    for unit in db.blood_units.values():
        if (unit["center_id"] == center_id
                and unit["blood_type"] == blood_type
                and unit["component"] == component):
            if unit["status"] == "AVAILABLE":
                available += 1
            elif unit["status"] == "RESERVED":
                reserved += 1
    return available, reserved


def bucket_view(bucket):
    """Reflect the live recount on read (counts are an invariant)."""
    available, reserved = recount_bucket(bucket)
    bucket["available_count"] = available
    bucket["reserved_count"] = reserved
    return bucket


def find_bucket(center_id, blood_type, component):
    for b in db.inventory_buckets.values():
        if (b["center_id"] == center_id
                and b["blood_type"] == blood_type
                and b["component"] == component):
            return b
    return None


def adjust_bucket(center_id, blood_type, component, available_delta=0, reserved_delta=0):
    """Apply an incremental delta to the matching bucket, if one exists, and
    bump its version/timestamp. Buckets are optional rows; if none exists the
    counts are still derivable on demand from unit rows."""
    bucket = find_bucket(center_id, blood_type, component)
    if bucket is None:
        return
    bucket["available_count"] = bucket.get("available_count", 0) + available_delta
    bucket["reserved_count"] = bucket.get("reserved_count", 0) + reserved_delta
    db.touch(bucket)


# ---- unit shelf-life --------------------------------------------------------
def collection_anchored_expiry(component, collected_at):
    if component == "RBC":
        days = RBC_SHELF_DAYS
    elif component == "PLASMA":
        days = PLASMA_SHELF_DAYS
    elif component == "WHOLE_BLOOD":
        days = WHOLE_SHELF_DAYS
    else:
        return None
    return add_days_iso(collected_at, days)


def release_anchored_expiry(released_at):
    return add_days_iso(released_at, PLATELET_SHELF_DAYS)


# ---- plasma volume caps -----------------------------------------------------
def plasma_band_cap(weight_kg):
    if weight_kg < MIN_WEIGHT_KG:
        # below-band weight has no defined cap; treat as the lowest band cap so
        # a too-large volume is still rejected. (Underweight is screened earlier.)
        return PER_CAP_LOW
    if weight_kg < WEIGHT_BAND_LOW_MAX:
        return PER_CAP_LOW
    if weight_kg < WEIGHT_BAND_MID_MAX:
        return PER_CAP_MID
    return PER_CAP_HIGH


def _liters_round(volume_ml):
    return (Decimal(str(volume_ml)) / Decimal("1000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def rolling_annual_plasma_liters(donor_id, center, incoming_volume_ml):
    """Sum of per-collection rounded liters for prior in-window PLASMA donations
    plus the in-flight collection. Round-per-collection-THEN-sum."""
    window_start = iso_to_epoch(center["current_utc"]) - ROLLING_WINDOW_DAYS * SECONDS_PER_DAY
    total = Decimal("0.00")
    for d in db.donations.values():
        if (d["donor_id"] == donor_id
                and d["donation_type"] == "PLASMA"
                and d["status"] in ("COLLECTED", "RELEASABLE")
                and d.get("collected_at")
                and iso_to_epoch(d["collected_at"]) >= window_start):
            total += _liters_round(d["volume_ml"])
    total += _liters_round(incoming_volume_ml)
    return total
