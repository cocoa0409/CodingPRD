"""Every derived number in the programme (PRD 3.2, 3.3, 3.5, 3.6, 3.8, 3.9).

All arithmetic runs through decimal.Decimal; rounding is half-up to 2 decimal
places once at the end of a calculation, except where PRD 2.6 pins a different
order (settled hours round up; whole-day counts floor; the training-priority
score rounds each contribution before summing).
"""
from decimal import Decimal, ROUND_FLOOR

from util import add_days, add_minutes, ceil_hours, dec, floor_div_days, q2

# ---------------------------------------------------------------- constants

TIER_POINTS = {1: Decimal("100"), 2: Decimal("75"), 3: Decimal("50"), 4: Decimal("25")}
REGIME_POINTS_PER_REGIME = Decimal("40")
REGIME_POINTS_CAP = Decimal("100")
STALENESS_MAX = Decimal("100")
STALENESS_DIVISOR = Decimal("365")

MODE_WEIGHTS = {
    "RISK_DRIVEN": {
        "exposure": Decimal("0.45"),
        "tier": Decimal("0.30"),
        "staleness": Decimal("0.20"),
        "regime": Decimal("0.05"),
    },
    "COMPLIANCE_DRIVEN": {
        "exposure": Decimal("0.20"),
        "tier": Decimal("0.25"),
        "staleness": Decimal("0.15"),
        "regime": Decimal("0.40"),
    },
}

COVERAGE_MIN_PCT = Decimal("60.00")
COVERAGE_EMPTY_INVENTORY = Decimal("100.00")

EXPOSURE_MULTIPLIER = {
    "INTERNAL": Decimal("0.95"),
    "PARTNER": Decimal("1.00"),
    "INTERNET": Decimal("1.15"),
}
TIER_BONUS = {1: Decimal("0.50"), 2: Decimal("0.30"), 3: Decimal("0.10"), 4: Decimal("0.00")}
REGIME_BONUS_PER_REGIME = Decimal("0.20")
REGIME_BONUS_CAP = Decimal("0.60")
SEVERITY_SCORE_CAP = Decimal("10.00")
SEVERITY_BAND_CRITICAL = Decimal("9.00")
SEVERITY_BAND_HIGH = Decimal("7.00")
SEVERITY_BAND_MEDIUM = Decimal("4.00")
SEVERITY_POINTS = {"CRITICAL": 40, "HIGH": 20, "MEDIUM": 8, "LOW": 2}

ACK_DEADLINE_MINUTES = {"INTERNET": 60, "PARTNER": 240, "INTERNAL": 240}

SEVERITY_SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 60, "LOW": 120}
REGIME_SLA_CAP = {"FEDRAMP": 21, "PCI_DSS": 30, "HIPAA": 45, "SOX": 60, "SOC2": 90}
PARTIAL_GRACE_DAYS = 14
MAX_EXTENSIONS = 2

CERT_POINTS = {"OSCP": 45, "GPEN": 35, "CREST": 25, "CISSP": 15}
QUALIFICATION_CAP = 100
LEAD_MIN_SCORE = 60

COOLDOWN_HOURS = {"APPLICATION": 0, "NETWORK": 24, "CLOUD": 12}

ASSURANCE_BASE = Decimal("100.00")
ASSURANCE_DEDUCTION = {
    "CRITICAL": Decimal("25"),
    "HIGH": Decimal("12"),
    "MEDIUM": Decimal("5"),
    "LOW": Decimal("1"),
}
RETEST_CREDIT_PER_CLOSURE = Decimal("5")
RETEST_CREDIT_CAP = Decimal("20")
ASSURANCE_FLOOR = Decimal("0.00")
ASSURANCE_CAP = Decimal("100.00")

TRAINING_SEVERITY_WEIGHT = {
    "CRITICAL": Decimal("5.00"),
    "HIGH": Decimal("3.00"),
    "MEDIUM": Decimal("1.20"),
    "LOW": Decimal("0.40"),
}
RECENCY_WINDOW_DAYS = Decimal("90")
RECENCY_DECAY_SLOPE = Decimal("0.60")
RECENCY_FLOOR = Decimal("0.40")
TRAINING_SCORE_CAP = Decimal("20.00")
MANDATORY_MIN_RECURRENCE = 3
MANDATORY_MIN_SCORE = Decimal("8.00")

ROOT_CAUSE_THEMES = (
    "INPUT_VALIDATION",
    "ACCESS_CONTROL",
    "CRYPTO_MISCONFIG",
    "PATCH_MANAGEMENT",
    "SECRETS_HANDLING",
    "CLOUD_IAM",
)


# ---------------------------------------------------------------- scope scoring

def tier_points(asset):
    return TIER_POINTS[int(asset["criticality_tier"])]


def regime_points(asset):
    return min(
        REGIME_POINTS_PER_REGIME * Decimal(len(asset["compliance_regimes"])), REGIME_POINTS_CAP
    )


def staleness_points(asset, now):
    """Null last_tested_at scores the full 100; otherwise floor(days*100/365) capped."""
    last = asset.get("last_tested_at")
    if last is None:
        return STALENESS_MAX
    days = floor_div_days(now - last)
    raw = (Decimal(days) * Decimal(100) / STALENESS_DIVISOR).to_integral_value(
        rounding=ROUND_FLOOR
    )
    return min(raw, STALENESS_MAX)


def scope_priority_score(asset, mode, now):
    weights = MODE_WEIGHTS[mode]
    total = (
        weights["exposure"] * dec(asset["exposure_score"])
        + weights["tier"] * tier_points(asset)
        + weights["staleness"] * staleness_points(asset, now)
        + weights["regime"] * regime_points(asset)
    )
    return q2(total)


def coverage_score(assets, numerator_asset_ids):
    """100 * distinct tier-1/2 assets covered / tier-1/2 inventory; 100.00 if empty."""
    denominator = 0
    for asset in assets:
        if int(asset["criticality_tier"]) in (1, 2):
            denominator += 1
    if denominator == 0:
        return COVERAGE_EMPTY_INVENTORY
    numerator = len(numerator_asset_ids)
    return q2(Decimal(100) * Decimal(numerator) / Decimal(denominator))


# ---------------------------------------------------------------- severity

def severity_score(base_score, exposure_class, asset):
    """Multiplier applies to the technical base score alone; bonuses are additive."""
    total = dec(base_score) * EXPOSURE_MULTIPLIER[exposure_class]
    total = total + TIER_BONUS[int(asset["criticality_tier"])]
    total = total + min(
        REGIME_BONUS_PER_REGIME * Decimal(len(asset["compliance_regimes"])), REGIME_BONUS_CAP
    )
    if total > SEVERITY_SCORE_CAP:
        total = SEVERITY_SCORE_CAP
    return q2(total)


def severity_band(score):
    if score >= SEVERITY_BAND_CRITICAL:
        return "CRITICAL"
    if score >= SEVERITY_BAND_HIGH:
        return "HIGH"
    if score >= SEVERITY_BAND_MEDIUM:
        return "MEDIUM"
    return "LOW"


def ack_deadline(raised_at, exposure_class):
    return add_minutes(raised_at, ACK_DEADLINE_MINUTES[exposure_class])


# ---------------------------------------------------------------- remediation

def sla_days(band, regimes):
    default = SEVERITY_SLA_DAYS[band]
    if not regimes:
        return default
    strictest = min(REGIME_SLA_CAP[regime] for regime in regimes)
    return min(default, strictest)


def due_at(created_instant, days):
    return add_days(created_instant, days)


def days_late(verified_at, due_instant):
    days = floor_div_days(verified_at - due_instant)
    return max(0, days)


def is_overdue(remediation, now):
    if remediation["status"] in ("VALIDATED", "CLOSED"):
        return False
    return now > remediation["due_at"]


# ---------------------------------------------------------------- hours

def settled_hours(assignment, revoked_at):
    """Provisioned grants settle the hours actually held, capped at the reservation."""
    baseline = max(assignment["interval_start"], assignment["provisioned_at"])
    effective_end = min(revoked_at, assignment["interval_end"])
    hours = ceil_hours(effective_end - baseline)
    requested = dec(assignment["requested_hours"])
    return min(dec(hours), requested)


# ---------------------------------------------------------------- testers

def qualification_score(certifications):
    total = sum(CERT_POINTS[cert] for cert in certifications)
    return min(total, QUALIFICATION_CAP)


def cooldown_hours(asset):
    return COOLDOWN_HOURS[asset["asset_class"]]


# ---------------------------------------------------------------- assurance

def assurance_score(findings, variant):
    """PROVISIONAL: everything but DUPLICATE, no credit.  FINAL: also drops CLOSED
    findings from the deduction set and adds a capped retest credit."""
    total = ASSURANCE_BASE
    closed = 0
    for finding in findings:
        status = finding["status"]
        if status == "DUPLICATE":
            continue
        if status == "CLOSED":
            closed += 1
            if variant == "FINAL":
                continue
        total = total - ASSURANCE_DEDUCTION[finding["severity_band"]]
    if variant == "FINAL":
        total = total + min(RETEST_CREDIT_PER_CLOSURE * Decimal(closed), RETEST_CREDIT_CAP)
        if total > ASSURANCE_CAP:
            total = ASSURANCE_CAP
    if total < ASSURANCE_FLOOR:
        total = ASSURANCE_FLOOR
    return q2(total)


# ---------------------------------------------------------------- trend analysis

def recency_multiplier(discovered_at, generated_at):
    days = floor_div_days(generated_at - discovered_at)
    value = Decimal(1) - (Decimal(days) / RECENCY_WINDOW_DAYS) * RECENCY_DECAY_SLOPE
    if value < RECENCY_FLOOR:
        value = RECENCY_FLOOR
    return value


def training_priority_score(findings, generated_at):
    """Each contribution rounds to 2dp BEFORE summing; the sum is capped then rounded."""
    total = Decimal("0")
    for finding in findings:
        weight = TRAINING_SEVERITY_WEIGHT[finding["severity_band"]]
        total = total + q2(weight * recency_multiplier(finding["discovered_at"], generated_at))
    if total > TRAINING_SCORE_CAP:
        total = TRAINING_SCORE_CAP
    return q2(total)


def urgency_band(recurrence_count, score):
    if recurrence_count >= MANDATORY_MIN_RECURRENCE and score >= MANDATORY_MIN_SCORE:
        return "MANDATORY"
    return "RECOMMENDED"
