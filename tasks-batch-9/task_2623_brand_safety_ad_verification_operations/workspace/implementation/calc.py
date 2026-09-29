"""Domain constants and every calculation rule (PRD sections 2.5, 2.6, 3.1-3.9)."""

from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------- #
# enumerations                                                                #
# --------------------------------------------------------------------------- #
TIER_FLOOR = "FLOOR"
TIER_HIGH_RISK = "HIGH_RISK"
TIER_MEDIUM_RISK = "MEDIUM_RISK"
TIER_LOW_RISK = "LOW_RISK"
TIER_SAFE = "SAFE"
TIER_UNRATED = "UNRATED"

TIER_RANK = {
    TIER_FLOOR: 0,
    TIER_HIGH_RISK: 1,
    TIER_MEDIUM_RISK: 2,
    TIER_LOW_RISK: 3,
    TIER_SAFE: 4,
}
TIER_SET = set(TIER_RANK)

FORMAT_SET = {"DISPLAY", "LARGE_DISPLAY", "VIDEO"}

CATEGORY_RISK_WEIGHTS = {
    "ADULT": 100,
    "TERRORISM": 100,
    "ILLEGAL_DRUGS": 100,
    "ARMS": 40,
    "CRIME_VIOLENCE": 40,
    "HATE_SPEECH": 40,
    "PIRACY": 40,
    "DEATH_INJURY": 15,
    "TOBACCO_ALCOHOL": 15,
    "GAMBLING": 15,
    "DEBATED_SOCIAL": 15,
    "NEWS_HARD": 5,
    "SPORTS_NEWS": 5,
    "GENERAL": 0,
}
CATEGORY_SET = set(CATEGORY_RISK_WEIGHTS)
CATEGORY_CODES_MAX = 6

STANDARD_FAMILY_SET = {"VIEWABILITY", "IVT", "SUITABILITY"}
ACCREDITATION_LIVE = ("PROVISIONAL", "ACCREDITED")

CLASSIFIER_KIND_CLIENT = {"MODEL", "HUMAN"}
CLASSIFIER_KIND_APPEAL_REMEDY = "APPEAL_REMEDY"

APPEAL_REASON_CODES = {
    "CATEGORY_MISREAD",
    "CONTEXT_IGNORED",
    "STALE_CRAWL",
    "MFA_SIGNAL_WRONG",
}

ENTRY_TYPE_SET = {"PAGE_URL", "DOMAIN", "PUBLISHER", "CATEGORY"}
SPECIFICITY_RANK = {"PAGE_URL": 4, "DOMAIN": 3, "PUBLISHER": 2, "CATEGORY": 1}

IVT_CLASS_TO_FAMILY = {
    "GENERAL_BOT": "GIVT",
    "DATACENTER": "GIVT",
    "SIVT_HIJACKED_DEVICE": "SIVT",
    "SIVT_AD_FARM": "SIVT",
    "SIVT_INCENTIVIZED": "SIVT",
}
IVT_CLASS_SET = set(IVT_CLASS_TO_FAMILY)

REJECT_REASON_CLIENT = {"EVIDENCE_INSUFFICIENT", "BATCH_RESCORED", "DUPLICATE_CLAIM"}
REJECT_REASON_APPEAL_OVERTURNED = "APPEAL_OVERTURNED"

# --------------------------------------------------------------------------- #
# named constants                                                             #
# --------------------------------------------------------------------------- #
MFA_DENSITY_WEIGHT = Decimal("0.4")
MFA_DENSITY_CAP = Decimal("40.00")
MFA_REFRESH_FAST_POINTS = Decimal("25.00")
MFA_REFRESH_MEDIUM_POINTS = Decimal("12.00")
MFA_SOURCED_MAX = Decimal("20.00")
MFA_ORIGINALITY_WEIGHT = Decimal("0.15")
MFA_FLAG_THRESHOLD = Decimal("70.00")

MFA_RISK_MULTIPLIER = Decimal("1.5")
CONFIDENCE_INFLATION = Decimal("1.25")
MODEL_CONFIDENCE_FLOOR = Decimal("0.80")
ROLLUP_WINDOW_DAYS = 30

IVT_CONFIRM_CONFIDENCE_FLOOR = Decimal("0.75")

ADMIN_FEE_TIER_BREAK_CENTS = 500000
ADMIN_FEE_RATE_STANDARD = Decimal("0.15")
ADMIN_FEE_RATE_HIGH_VOLUME = Decimal("0.10")

QUALITY_IVT_WEIGHT = Decimal("2.0")
QUALITY_VIEWABILITY_TARGET = Decimal("0.70")
QUALITY_VIEW_WEIGHT = Decimal("1.5")
QUALITY_MFA_PENALTY = Decimal("5")
QUALITY_QUARANTINE_PENALTY = Decimal("3")
QUALITY_OVERTURN_CREDIT = Decimal("10")

BATCH_WINDOW_BUFFER_SECONDS = 60
APPEAL_FILING_WINDOW_DAYS = 14
CLAIM_FILING_WINDOW_DAYS = 30
APPEAL_MAX_ROUNDS = 3
AUDIT_MAX_FINDING_RATE = Decimal("0.05")
PUBLISHER_QUARANTINE_LIMIT = 3
PUBLISHER_MFA_LIMIT = 3

# methodology threshold defaults (PRD section 3.2)
METHODOLOGY_DEFAULTS = {
    "display_in_view_seconds": Decimal("1.0"),
    "video_in_view_seconds": Decimal("2.0"),
    "display_pixel_pct": Decimal("0.5"),
    "large_display_pixel_pct": Decimal("0.3"),
    "video_pixel_pct": Decimal("0.5"),
    "coverage_rate_floor": Decimal("0.7"),
    "ivt_rate_ceiling": Decimal("0.02"),
}


# --------------------------------------------------------------------------- #
# decimal helpers                                                             #
# --------------------------------------------------------------------------- #
def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def rhu(value, places):
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def round2(value):
    return rhu(value, 2)


def round4(value):
    return rhu(value, 4)


def round_cents(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def num2(value):
    """Serialise a 2-decimal score as a JSON number."""
    if value is None:
        return None
    return float(round2(value))


def num4(value):
    """Serialise a 4-decimal rate as a JSON number."""
    if value is None:
        return None
    return float(round4(value))


def plain(value):
    if value is None:
        return None
    return float(D(value))


def tier_rank(tier):
    return TIER_RANK.get(tier)


def worse_than(tier, floor_tier):
    """True when tier is strictly worse than floor_tier, UNRATED always worse."""
    if tier == TIER_UNRATED or tier is None:
        return True
    if floor_tier not in TIER_RANK:
        return False
    return TIER_RANK[tier] < TIER_RANK[floor_tier]


# --------------------------------------------------------------------------- #
# mfa_score  (PRD section 3.3)                                                        #
# --------------------------------------------------------------------------- #
def mfa_score(ad_density_ratio, refresh_seconds, sourced_traffic_pct, originality_score):
    density_points = min(
        MFA_DENSITY_CAP,
        round2(D(ad_density_ratio) * Decimal(100) * MFA_DENSITY_WEIGHT),
    )
    seconds = int(refresh_seconds)
    if 0 < seconds <= 15:
        refresh_points = MFA_REFRESH_FAST_POINTS
    elif 15 < seconds <= 30:
        refresh_points = MFA_REFRESH_MEDIUM_POINTS
    else:
        refresh_points = Decimal("0.00")
    sourced_points = round2(D(sourced_traffic_pct) * MFA_SOURCED_MAX)
    originality_points = round2((Decimal(100) - D(originality_score)) * MFA_ORIGINALITY_WEIGHT)
    total = round2(density_points + refresh_points + sourced_points + originality_points)
    return total, total >= MFA_FLAG_THRESHOLD


# --------------------------------------------------------------------------- #
# page_suitability_tier  (PRD section 3.3)                                            #
# --------------------------------------------------------------------------- #
def base_risk_points(category_codes):
    total = Decimal(0)
    for code in category_codes or []:
        total += Decimal(CATEGORY_RISK_WEIGHTS.get(code, 0))
    return total


def risk_scoring(category_codes, mfa_flag, classifier_kind, model_confidence):
    base = base_risk_points(category_codes)
    mfa_multiplier = MFA_RISK_MULTIPLIER if mfa_flag else Decimal(1)
    if classifier_kind == "MODEL" and D(model_confidence) < MODEL_CONFIDENCE_FLOOR:
        confidence_multiplier = CONFIDENCE_INFLATION
    else:
        confidence_multiplier = Decimal(1)
    adjusted = round2(base * mfa_multiplier * confidence_multiplier)
    return base, adjusted, tier_from_points(adjusted)


def tier_from_points(adjusted):
    points = D(adjusted)
    if points >= Decimal("100.00"):
        return TIER_FLOOR
    if points >= Decimal("40.00"):
        return TIER_HIGH_RISK
    if points >= Decimal("15.00"):
        return TIER_MEDIUM_RISK
    if points >= Decimal("5.00"):
        return TIER_LOW_RISK
    return TIER_SAFE


# --------------------------------------------------------------------------- #
# viewability_and_coverage  (PRD section 3.7)                                         #
# --------------------------------------------------------------------------- #
def required_thresholds(fmt, methodology):
    if fmt == "VIDEO":
        seconds = D(methodology["video_in_view_seconds"])
        pixel = D(methodology["video_pixel_pct"])
    elif fmt == "LARGE_DISPLAY":
        seconds = D(methodology["display_in_view_seconds"])
        pixel = D(methodology["large_display_pixel_pct"])
    else:
        seconds = D(methodology["display_in_view_seconds"])
        pixel = D(methodology["display_pixel_pct"])
    return seconds, pixel


def viewability_and_coverage(batch, methodology):
    required_seconds, required_pixel = required_thresholds(batch["format"], methodology)
    measured = int(batch["measured_impressions"])
    measurable = int(batch["measurable_impressions"])
    in_view = int(batch["in_view_impressions"])
    if D(batch["avg_in_view_seconds"]) >= required_seconds and D(
        batch["avg_in_view_pixel_pct"]
    ) >= required_pixel:
        qualified = in_view
    else:
        qualified = 0
    unmeasurable = measured - measurable
    non_viewable = measurable - qualified
    coverage_rate = round4(Decimal(measurable) / Decimal(measured)) if measured > 0 else Decimal("0.0000")
    if measurable > 0:
        viewability_rate = round4(Decimal(qualified) / Decimal(measurable))
    else:
        viewability_rate = Decimal("0.0000")
    return {
        "qualified_in_view_impressions": qualified,
        "unmeasurable_impressions": unmeasurable,
        "non_viewable_impressions": non_viewable,
        "coverage_rate": coverage_rate,
        "viewability_rate": viewability_rate,
    }


# --------------------------------------------------------------------------- #
# ivt_dedup_rate  (PRD section 3.8)                                                   #
# --------------------------------------------------------------------------- #
def ivt_dedup(measured_impressions, confirmed_findings):
    givt = [
        int(f["flagged_impressions"])
        for f in confirmed_findings
        if f["ivt_family"] == "GIVT"
    ]
    sivt = [
        int(f["flagged_impressions"])
        for f in confirmed_findings
        if f["ivt_family"] == "SIVT"
    ]
    givt_component = max(givt) if givt else 0
    sivt_component = max(sivt) if sivt else 0
    measured = int(measured_impressions)
    ivt_impressions = min(givt_component + sivt_component, measured)
    if measured > 0:
        ivt_rate = round4(Decimal(ivt_impressions) / Decimal(measured))
    else:
        ivt_rate = Decimal("0.0000")
    return {
        "ivt_impressions": ivt_impressions,
        "ivt_rate": ivt_rate,
        "sophistication_flag": sivt_component > 0,
        "net_billable_impressions": measured - ivt_impressions,
    }


# --------------------------------------------------------------------------- #
# campaign_coverage_status  (PRD section 3.7)                                         #
# --------------------------------------------------------------------------- #
def coverage_status(campaign):
    measured = int(campaign["certified_measured_impressions"])
    if measured == 0:
        return "UNKNOWN"
    measurable = int(campaign["certified_measurable_impressions"])
    ratio = round4(Decimal(measurable) / Decimal(measured))
    target = D(campaign["target_coverage_rate"])
    return "ON_TARGET" if ratio >= target else "BELOW_TARGET"


# --------------------------------------------------------------------------- #
# claim_impression_basis / credit money  (PRD section 3.9)                            #
# --------------------------------------------------------------------------- #
def batch_is_defective(batch, methodology):
    if batch.get("suitability_breach_flag"):
        return True
    if int(batch.get("ivt_impressions") or 0) > 0:
        return True
    coverage_rate = batch.get("coverage_rate")
    if coverage_rate is not None and methodology is not None:
        if D(coverage_rate) < D(methodology["coverage_rate_floor"]):
            return True
    if batch.get("sophistication_flag"):
        return True
    if batch.get("scoring_status") == "DECERTIFIED":
        return True
    return False


def gross_basis_impressions(batch):
    return int(batch["measured_impressions"])


def net_basis_impressions(batch):
    measured = int(batch["measured_impressions"])
    if batch.get("suitability_breach_flag"):
        return measured
    ivt = int(batch.get("ivt_impressions") or 0)
    measurable = int(batch.get("measurable_impressions") or 0)
    qualified = int(batch.get("qualified_in_view_impressions") or 0)
    shortfall = measurable - qualified
    if shortfall < 0:
        shortfall = 0
    return min(measured, ivt + shortfall)


def credit_cents(basis_impressions, cpm_cents):
    """Per-batch money: round to whole cents BEFORE summation."""
    return round_cents(Decimal(int(basis_impressions)) * Decimal(int(cpm_cents)) / Decimal(1000))


def admin_fee(gross_credit_cents):
    if gross_credit_cents >= ADMIN_FEE_TIER_BREAK_CENTS:
        rate = ADMIN_FEE_RATE_HIGH_VOLUME
    else:
        rate = ADMIN_FEE_RATE_STANDARD
    fee = round_cents(Decimal(int(gross_credit_cents)) * rate)
    return rate, fee, int(gross_credit_cents) - fee


# --------------------------------------------------------------------------- #
# publisher_quality_index  (PRD section 3.1)                                          #
# --------------------------------------------------------------------------- #
def quality_index(publisher, adjudicated_batches):
    sum_measured = sum(int(b["measured_impressions"]) for b in adjudicated_batches)
    sum_ivt = sum(int(b.get("ivt_impressions") or 0) for b in adjudicated_batches)
    sum_measurable = sum(int(b.get("measurable_impressions") or 0) for b in adjudicated_batches)
    sum_qualified = sum(
        int(b.get("qualified_in_view_impressions") or 0) for b in adjudicated_batches
    )
    ivt_rate_avg = (
        round4(Decimal(sum_ivt) / Decimal(sum_measured)) if sum_measured > 0 else Decimal("0.0000")
    )
    viewability_rate_avg = (
        round4(Decimal(sum_qualified) / Decimal(sum_measurable))
        if sum_measurable > 0
        else Decimal("0.0000")
    )
    decided = int(publisher["decided_appeal_count"])
    overturned = int(publisher["overturned_appeal_count"])
    overturn_rate = (
        round4(Decimal(overturned) / Decimal(decided)) if decided > 0 else Decimal("0.0000")
    )
    ivt_penalty = ivt_rate_avg * Decimal(100) * QUALITY_IVT_WEIGHT
    if sum_measurable == 0:
        viewability_penalty = Decimal("0.00")
    else:
        shortfall = QUALITY_VIEWABILITY_TARGET - viewability_rate_avg
        if shortfall < 0:
            shortfall = Decimal(0)
        viewability_penalty = shortfall * Decimal(100) * QUALITY_VIEW_WEIGHT
    raw = (
        Decimal(100)
        - ivt_penalty
        - viewability_penalty
        - (Decimal(int(publisher["mfa_page_count"])) * QUALITY_MFA_PENALTY)
        - (Decimal(int(publisher["quarantined_batch_count"])) * QUALITY_QUARANTINE_PENALTY)
        + (overturn_rate * QUALITY_OVERTURN_CREDIT)
    )
    clamped = min(Decimal(100), max(Decimal(0), raw))
    index = round2(clamped)
    if index >= Decimal("85.00"):
        band = "PREFERRED"
    elif index >= Decimal("60.00"):
        band = "STANDARD"
    elif index >= Decimal("40.00"):
        band = "WATCHLIST"
    else:
        band = "SUSPENDED_QUALITY"
    return {
        "sum_measured": sum_measured,
        "ivt_rate_avg": ivt_rate_avg,
        "viewability_rate_avg": viewability_rate_avg,
        "overturn_rate": overturn_rate,
        "quality_index": index,
        "tier_band": band,
    }
