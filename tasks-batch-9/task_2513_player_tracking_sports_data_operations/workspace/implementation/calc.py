"""Domain constants and the six calculation rules (PRD §2.7, §3.2, §3.6–§3.9)."""

from decimal import Decimal
from fractions import Fraction

from util import F, ceil_units, round_half_up, round_half_up_cents, sqrt_decimal

# --- §3.3 collective bargaining -------------------------------------------
CBA_CURRENT_VERSION = "CBA-2026A"

# --- §3.2 calibration accuracy evaluation ---------------------------------
MIN_SAMPLE_COUNT = 5000
MIN_REFERENCE_POINTS = 12
PASS_THRESHOLD_MM = Decimal("90.00")
PROVISIONAL_CEILING_MM = Decimal("140.00")
CERT_VALIDITY_HOURS = 72

# --- §3.6 event tag quality index -----------------------------------------
W_CONFIDENCE = Fraction(1, 2)      # 0.5
W_CORRECTION = Fraction(3, 10)     # 0.3
W_COMPLETENESS = Fraction(1, 5)    # 0.2
APPROVED_WEIGHT = Fraction(1, 1)   # 1.0
REJECTED_WEIGHT = Fraction(1, 4)   # 0.25
EXPECTED_TAGS_PER_GAME = 4
QUALITY_INDEX_FLOOR = Decimal("0.8000")

# --- §3.7 rights allocation ledger ----------------------------------------
LEAGUE_RESERVE_PCT = Fraction(15, 100)   # 0.15
BROADCAST_BUFFER_SECONDS = 300

# --- §3.8 feed session billing --------------------------------------------
ULTRA_LOW_LATENCY_MS = 250
LOW_LATENCY_MS = 1000
TIER_RATE_CENTS_PER_UNIT = {"BRONZE": 40, "SILVER": 30, "GOLD": 22}
TIER_ALLOWED_SCOPES = {
    "BRONZE": ("POSITIONAL",),
    "SILVER": ("POSITIONAL", "EVENT"),
    "GOLD": ("POSITIONAL", "EVENT", "BIOMETRIC"),
}
SLA_CREDIT_PCT = Fraction(1, 4)          # 0.25
SLA_BREACH_SUSPEND_THRESHOLD = 3

# --- §3.9 historical normalization ----------------------------------------
GENERATION_SCALE = {
    "G1": Fraction("1.042"),
    "G2": Fraction("1.017"),
    "G3": Fraction(1, 1),
}
CANONICAL_DRIFT_PCT = {
    "G1": Fraction("-0.6"),
    "G2": Fraction("-0.2"),
    "G3": Fraction(0, 1),
}
MAPPING_VERSION = "MAP-2026.1"

# --- enums ----------------------------------------------------------------
TRACKING_TECHS = ("OPTICAL", "SENSOR_UWB", "HYBRID")
MODALITIES = ("OPTICAL_CAMERA", "UWB_ANCHOR", "LIDAR")
INSTALLATION_STATUSES = ("DEPLOYED", "CALIBRATING", "VALIDATED", "CERTIFIED",
                         "RECALIBRATION_REQUIRED", "RETIRED")
CONSENT_SCOPES = ("BIOMETRIC_TRACKING", "POSITIONAL_ONLY")
CONSENT_STATUSES = ("PENDING", "ACTIVE", "WITHDRAWN", "EXPIRED")
TRACKING_GENERATIONS = ("G1", "G2", "G3")
COLLECTION_STATUSES = ("SCHEDULED", "LIVE", "SUSPENDED_COLLECTION", "COLLECTED",
                       "ARCHIVED")
CERTIFICATION_STATUSES = ("PENDING", "PROVISIONAL", "OFFICIAL", "DISPUTED")
TAG_TYPES = ("SHOT", "PASS", "FOUL", "SUBSTITUTION")
REVIEW_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "UNDER_CORRECTION",
                   "SUPERSEDED")
REASON_CODES = ("WRONG_PLAYER", "WRONG_CLOCK", "WRONG_TYPE", "BIOMETRIC_REMOVAL")
CORRECTION_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED")
RIGHTS_CLASSES = ("BROADCAST_LIVE", "IN_VENUE_DISPLAY", "COMMERCIAL_LICENSE",
                  "LEAGUE_ARCHIVE")
HOLDER_TYPES = ("LEAGUE", "CLUB", "LICENSEE")
SCOPE_MEMBERS = ("POSITIONAL", "EVENT", "BIOMETRIC")
LICENSEE_CLASSES = ("BROADCASTER", "COMMERCIAL_LICENSEE", "DEVELOPER")
TIERS = ("BRONZE", "SILVER", "GOLD")
DELIVERY_MODES = ("REALTIME", "POST_GAME")
SESSION_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATED")
RIGHTS_WINDOW_STATUSES = ("ACTIVE", "REVOKED")
NORMALIZATION_BASES = ("RAW_GENERATION", "CANONICAL_SEASON")
METRIC_CODES = ("TOTAL_DISTANCE_M", "SPRINT_DISTANCE_M")


# ==========================================================================
# calculations.calibration_accuracy_evaluation  (PRD §3.2)
# ==========================================================================

def calibration_accuracy_evaluation(x_mm, y_mm, z_mm, sample_count,
                                    reference_point_count):
    """Quadratic mean of the three axis errors, then the gate-then-thresholds
    verdict.  The *rounded* composite is what the thresholds compare against."""
    squares = F(x_mm) ** 2 + F(y_mm) ** 2 + F(z_mm) ** 2
    composite = round_half_up(sqrt_decimal(squares / 3), 2)

    if sample_count < MIN_SAMPLE_COUNT or reference_point_count < MIN_REFERENCE_POINTS:
        result = "INVALID"
    elif composite <= PASS_THRESHOLD_MM:
        result = "PASS"
    elif composite <= PROVISIONAL_CEILING_MM:
        result = "PROVISIONAL"
    else:
        result = "FAIL"
    return composite, result


# ==========================================================================
# calculations.venue_data_posture  (PRD §3.1)
# ==========================================================================

def venue_posture_from_counts(certified_count, recalibrating_count,
                              required_certified_installations):
    if certified_count == 0:
        return "UNCERTIFIED"
    if (certified_count >= required_certified_installations
            and recalibrating_count == 0):
        return "CERTIFIED"
    return "RESTRICTED"


# ==========================================================================
# calculations.event_tag_quality_index  (PRD §3.6)
# ==========================================================================

def event_tag_quality_index(scored_confidences, approved_correction_count,
                            rejected_correction_count, accepted_tag_count):
    if len(scored_confidences) == 0:
        # Empty-set short circuit: a game with nothing to score scores nothing.
        return Decimal("0.0000")

    total = Fraction(0)
    for c in scored_confidences:
        total += F(c)
    mean_confidence = total / len(scored_confidences)

    penalty_numerator = (F(approved_correction_count) * APPROVED_WEIGHT
                         + F(rejected_correction_count) * REJECTED_WEIGHT)
    penalty_denominator = F(max(1, accepted_tag_count))
    correction_penalty = min(Fraction(1), penalty_numerator / penalty_denominator)

    completeness = min(Fraction(1),
                       F(accepted_tag_count) / F(EXPECTED_TAGS_PER_GAME))

    value = (W_CONFIDENCE * mean_confidence
             + W_CORRECTION * (Fraction(1) - correction_penalty)
             + W_COMPLETENESS * completeness)
    return round_half_up(value, 4)


# ==========================================================================
# calculations.rights_allocation_ledger  (PRD §3.7)
# ==========================================================================

def league_reserve_minutes(licensable_minutes):
    """Step 1, on the GROSS basis: 15% of licensable_minutes, rounded up."""
    return ceil_units(F(licensable_minutes) * LEAGUE_RESERVE_PCT)


def window_allocated_minutes(start_dt, end_dt):
    """Per-window ceiling of the covered seconds over 60 — never over a sum."""
    seconds = F((end_dt - start_dt).total_seconds())
    return ceil_units(seconds / 60)


# ==========================================================================
# calculations.feed_session_billing  (PRD §3.8)
# ==========================================================================

def latency_multiplier(requested_latency_ms):
    if requested_latency_ms <= ULTRA_LOW_LATENCY_MS:
        return Fraction("1.50")
    if requested_latency_ms <= LOW_LATENCY_MS:
        return Fraction("1.20")
    return Fraction("1.00")


def exact_duration_minutes(start_dt, end_dt):
    """Exact, unrounded (PRD §2.7 'Exact arithmetic')."""
    return F((end_dt - start_dt).total_seconds()) / 60


def reserved_forward(bandwidth_mbps, duration_minutes, multiplier, tier_rate_cents):
    """RESERVED_FORWARD variant: a single ceiling over the whole booked window."""
    units = ceil_units(F(bandwidth_mbps) * F(duration_minutes) * F(multiplier))
    charge = round_half_up_cents(F(units) * F(tier_rate_cents))
    return units, charge


def record_units_charged(bandwidth_mbps, duration_seconds, multiplier):
    """METERED_ACTUAL variant: the ceiling is applied to this record alone."""
    return ceil_units(F(bandwidth_mbps) * (F(duration_seconds) / 60) * F(multiplier))


def settled_charge_cents(metered_units, tier_rate_cents):
    return round_half_up_cents(F(metered_units) * F(tier_rate_cents))


def sla_credit_cents(units_charged, tier_rate_cents):
    return round_half_up_cents(F(units_charged) * F(tier_rate_cents) * SLA_CREDIT_PCT)


# ==========================================================================
# calculations.normalized_tracking_metric  (PRD §3.9)
# ==========================================================================

def normalized_tracking_metric(basis, generation, segment_values):
    scale = GENERATION_SCALE[generation]
    if basis == "RAW_GENERATION":
        drift_pct = Fraction(0)
        # round-then-sum: each segment is rounded before it enters the total
        total = Fraction(0)
        for segment in segment_values:
            total += F(round_half_up(F(segment) * scale, 2))
        normalized = round_half_up(total, 2)
    else:
        drift_pct = CANONICAL_DRIFT_PCT[generation]
        # sum-then-round: full precision throughout, a single terminal rounding
        total = Fraction(0)
        for segment in segment_values:
            total += F(segment)
        normalized = round_half_up(total * scale * (1 + drift_pct / 100), 2)
    return scale, drift_pct, normalized
