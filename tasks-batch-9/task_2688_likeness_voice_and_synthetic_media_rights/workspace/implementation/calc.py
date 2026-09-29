"""Every calculation the PRD pins, implemented exactly as written."""

from decimal import Decimal

from core import (
    add_days, add_years, at_midnight, db, dec, now, round_half_up, round_up,
    whole_months,
)

# ------------------------------------------------------------------- constants

BREADTH_STEP = Decimal("0.15")
SHORT_TERM_MONTHS = 12
MID_TERM_MONTHS = 36
DURATION_SHORT = Decimal("1.00")
DURATION_MID = Decimal("1.25")
DURATION_LONG = Decimal("1.60")
EXCLUSIVE_FACTOR = Decimal("1.35")
NON_EXCLUSIVE_FACTOR = Decimal("1.00")

MEDIA_TYPES = ("ADVERTISING", "FEATURE_FILM", "EPISODIC", "VIDEO_GAME", "SOCIAL")
MEDIA_FLOOR_RANK = {
    "ADVERTISING": 5,
    "FEATURE_FILM": 4,
    "EPISODIC": 3,
    "VIDEO_GAME": 2,
    "SOCIAL": 1,
}
MEDIA_MULTIPLIER = {
    "ADVERTISING": Decimal("1.50"),
    "FEATURE_FILM": Decimal("1.30"),
    "EPISODIC": Decimal("1.15"),
    "VIDEO_GAME": Decimal("1.10"),
    "SOCIAL": Decimal("1.00"),
}
REACH_TIER_1 = 1000000
REACH_TIER_2 = 10000000
REACH_FACTOR_1 = Decimal("1.00")
REACH_FACTOR_2 = Decimal("1.40")
REACH_FACTOR_3 = Decimal("1.90")
TERRITORY_STEP = Decimal("0.10")

PURGE_EXECUTION_GRACE_DAYS = 7
REVIEW_WINDOW_DAYS = 7
MAX_REVISION_ROUNDS = 3
MIN_CONSENT_TERM_DAYS = 30
MAX_OVERLAPPING_LICENSES = 2

SURCHARGE_RATE_ADVERTISING = Decimal("0.0175")
SURCHARGE_RATE_ENTERTAINMENT = Decimal("0.0125")

WEIGHT_CONFIDENCE = Decimal("0.60")
WEIGHT_REACH = Decimal("0.25")
WEIGHT_POSTURE = Decimal("0.15")
REACH_SATURATION = Decimal("10000000")
MANDATORY_TAKEDOWN_THRESHOLD = Decimal("0.7500")
ESCALATION_FLOOR = Decimal("0.5000")
POSTURE_FACTOR = {
    "FROZEN": Decimal("1.0"),
    "RESTRICTED": Decimal("0.6"),
    "CLEAR": Decimal("0.3"),
}
UNION_FLOOR_RATIO = Decimal("0.5")

DISCLOSURE_RANK = {
    "METADATA_ONLY": 1,
    "END_CARD": 2,
    "PRE_ROLL": 3,
    "PERSISTENT_BUG": 4,
}

CHANNELS = ("ADVERTISING", "ENTERTAINMENT")
UNION_CODES = ("SAG_AFTRA", "AFM")


# --------------------------------------------------------- reference data lookup

def profile_for(state_code):
    for row in db.state_law_profiles.values():
        if row["state_code"] == state_code:
            return row
    return None


def governing_media_type(permitted):
    return max(permitted, key=lambda m: MEDIA_FLOOR_RANK[m])


def select_union_row(union_code, media_type, reference_dt):
    """Deterministic union row selection (PRD 2.7)."""
    if not union_code:
        return None
    candidates = [
        row for row in db.union_minimum_schedules.values()
        if row["union_code"] == union_code
        and row["media_type"] == media_type
        and row["effective_from"] <= reference_dt
    ]
    if not candidates:
        return None
    best = max(row["effective_from"] for row in candidates)
    tied = [row for row in candidates if row["effective_from"] == best]
    tied.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return tied[0]


def initial_floor(grant):
    """(row, floor_cents).  row is None when no lookup happens."""
    union_code = grant.get("union_code_snapshot")
    if not union_code:
        return None, 0
    media = governing_media_type(grant["permitted_media_types"])
    row = select_union_row(union_code, media, grant["effective_from"])
    if row is None:
        return None, None
    return row, int(row["minimum_initial_cents"])


def per_use_floor(grant, media_type):
    union_code = grant.get("union_code_snapshot")
    if not union_code:
        return None, 0
    row = select_union_row(union_code, media_type, grant["effective_from"])
    if row is None:
        return None, None
    return row, int(row["minimum_per_use_cents"])


# ------------------------------------------------------ initial creation payment

def breadth_factor(permitted):
    return Decimal("1.00") + BREADTH_STEP * (len(permitted) - 1)


def duration_factor(grant):
    months = whole_months(grant["effective_from"], grant["effective_until"])
    if months <= SHORT_TERM_MONTHS:
        return DURATION_SHORT
    if months <= MID_TERM_MONTHS:
        return DURATION_MID
    return DURATION_LONG


def exclusivity_factor(grant):
    return EXCLUSIVE_FACTOR if grant["exclusivity"] == "EXCLUSIVE" else NON_EXCLUSIVE_FACTOR


def initial_creation_compensation(grant, floor_cents):
    """Returns (scaled, initial_compensation_cents, union_topup_cents)."""
    raw = (
        dec(grant["initial_creation_fee_cents"])
        * breadth_factor(grant["permitted_media_types"])
        * duration_factor(grant)
        * exclusivity_factor(grant)
    )
    scaled = int(round_half_up(raw))
    floor_cents = int(floor_cents or 0)
    initial = max(scaled, floor_cents)
    topup = max(0, floor_cents - scaled)
    return scaled, initial, topup


# --------------------------------------------------------------- per-use royalty

def reach_factor(reach):
    reach = int(reach)
    if reach <= REACH_TIER_1:
        return REACH_FACTOR_1
    if reach <= REACH_TIER_2:
        return REACH_FACTOR_2
    return REACH_FACTOR_3


def territory_factor(codes):
    return Decimal("1.00") + TERRITORY_STEP * (len(codes) - 1)


def per_use_compensation(grant, media_type, reach, territory_codes, floor_cents):
    raw = (
        dec(grant["per_use_base_fee_cents"])
        * reach_factor(reach)
        * MEDIA_MULTIPLIER[media_type]
        * territory_factor(territory_codes)
    )
    scaled = int(round_half_up(raw))
    return max(scaled, int(floor_cents or 0))


# -------------------------------------------------------------- post-mortem term

def postmortem_rights_expiry(date_of_death, profile):
    if date_of_death is None or profile is None:
        return None
    years = int(profile["postmortem_rights_years"])
    if years == 0:
        return None
    return at_midnight(add_years(at_midnight(date_of_death), years))


# ---------------------------------------------------------- retention deadlines

def biometric_retention_deadline(asset_created_at, grant, profile):
    statutory = add_days(asset_created_at, profile["biometric_retention_max_days"])
    consent_end = grant.get("effective_end_actual") or grant["effective_until"]
    contractual = add_days(consent_end, profile["deletion_grace_days"])
    return min(statutory, contractual)


def purge_due_from(retention_until):
    return add_days(retention_until, PURGE_EXECUTION_GRACE_DAYS)


def license_removal_deadline(profile):
    return add_days(now(), profile["removal_window_days"])


# ---------------------------------------------------------------- license total

def license_total_cost(subtotal, disclosure_required, channel):
    subtotal = int(subtotal)
    if not disclosure_required:
        rate = Decimal("0")
    elif channel == "ADVERTISING":
        rate = SURCHARGE_RATE_ADVERTISING
    else:
        rate = SURCHARGE_RATE_ENTERTAINMENT
    surcharge = int(round_up(dec(subtotal) * rate))
    return surcharge, subtotal + surcharge


# --------------------------------------------------------------- severity score

def infringement_severity_score(match_confidence, view_count, posture_before):
    reach_term = dec(view_count) / REACH_SATURATION
    if reach_term > Decimal("1.0"):
        reach_term = Decimal("1.0")
    total = (
        WEIGHT_CONFIDENCE * dec(match_confidence)
        + WEIGHT_REACH * reach_term
        + WEIGHT_POSTURE * POSTURE_FACTOR[posture_before]
    )
    return round_half_up(total, 4)


def use_state_enforceability(talent, detected_profile):
    """Returns (use_state_rights_until, enforceable_under_use_state)."""
    years = int(detected_profile["postmortem_rights_years"])
    death = talent.get("date_of_death")
    if years == 0 or death is None:
        rights_until = None
    else:
        rights_until = at_midnight(add_years(at_midnight(death), years))
    if talent["life_status"] == "LIVING":
        return rights_until, True
    enforceable = rights_until is not None and rights_until >= now()
    return rights_until, enforceable
