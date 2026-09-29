"""The nine calculation rules of the PRD (§2.7, §3.5, §3.4, §3.7, §3.8, §2.9)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import db

# ---- pinned constants ------------------------------------------------------
DISCOUNT_MONTHLY_CAP_CENTS = 3000
PROMO_DISCLOSURE_MONTHS = 12
POSTURE_FREEZE_UPHELD_COUNT = 3
PHASE_MONTH_SECONDS = 2592000
LATENCY_TOLERANCE_MS = 5
RELIABILITY_WINDOW_DAYS = 30
SEVERE_RATIO = Decimal("0.50")
MODERATE_RATIO = Decimal("0.25")
CREDIT_WINDOW_DAYS = 30
CREDIT_FLOOR_CENTS = 500
FLAT_TIER_CENTS = {"NONE": 0, "MINOR": 1000, "MODERATE": 2500, "SEVERE": 5000}
REMEDIATION_AUDIT_THRESHOLD = 2
SUBSTANTIATION_MIN_MARGIN = Decimal("0.80")
PROBE_COOLDOWN_MINUTES = 60
NOTICE_MIN_DAYS = 30
COMPLAINT_SLA_DAYS = 30
REOPEN_WINDOW_DAYS = 30
MAX_REOPENS = 2

MONTHLY_PHASE_CATEGORIES = ("MONTHLY_RECURRING", "GOVERNMENT_TAX")


# ---- rounding --------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round half up to a whole number of cents."""
    return int(round_half_up(value, 0))


def to_number(value, places):
    """Emit a Decimal as a JSON number at the pinned precision."""
    if value is None:
        return None
    return float(round_half_up(value, places))


def nearest_rank(sorted_values, fraction):
    """1-based rank ceil(fraction * n), returned as a 0-based index."""
    count = len(sorted_values)
    rank = (dec(fraction) * count).to_integral_value(rounding=ROUND_CEILING)
    index = int(rank) - 1
    if index < 0:
        index = 0
    if index > count - 1:
        index = count - 1
    return index


def median(values):
    ordered_values = sorted(values)
    count = len(ordered_values)
    if count % 2 == 1:
        return ordered_values[(count - 1) // 2]
    return (ordered_values[count // 2 - 1] + ordered_values[count // 2]) / Decimal(2)


def percentile(values, fraction):
    ordered_values = sorted(values)
    return ordered_values[nearest_rank(ordered_values, fraction)]


# ---------------------------------------------------------------------------
# calculations.label_monthly_itemization + discount_program_benefit
# + first_year_total_disclosure  (PRD §3.5)
# ---------------------------------------------------------------------------

def plan_fee_lines(plan_id):
    return db.ordered([f for f in db.store.fee_line_items.values()
                       if f["plan_id"] == plan_id])


def compute_label_figures(plan, discount_program_applied):
    """The whole priced face of a label: itemisation, discount, first-year."""
    fee_lines = plan_fee_lines(plan["id"])

    phases = []
    if plan["intro_price_cents"] is not None:
        phases.append(("INTRO", plan["intro_price_cents"]))
    phases.append(("POST_PROMO", plan["monthly_price_cents"]))

    itemization = []
    totals = {"INTRO": None, "POST_PROMO": None}

    for phase, base in phases:
        total = base
        for line in fee_lines:
            if line["label_category"] not in MONTHLY_PHASE_CATEGORIES:
                continue
            applies = line["applies_during"]
            eligible = (
                applies == "ALWAYS"
                or (phase == "INTRO" and applies == "INTRO_ONLY")
                or (phase == "POST_PROMO" and applies == "POST_PROMO_ONLY")
            )
            if not eligible:
                continue
            if line["basis"] == "FIXED":
                amount = line["amount_cents"]
            else:
                # Round each percentage line to whole cents here (round-then-sum).
                amount = round_cents(dec(line["rate_pct"]) * dec(base))
            itemization.append({
                "fee_code": line["fee_code"],
                "label_category": line["label_category"],
                "phase": phase,
                "amount_cents": amount,
            })
            total += amount
        totals[phase] = total

    one_time_total = 0
    for line in fee_lines:
        if line["label_category"] != "ONE_TIME":
            continue
        amount = line["amount_cents"]
        itemization.append({
            "fee_code": line["fee_code"],
            "label_category": line["label_category"],
            "phase": ONE_TIME_PHASE,
            "amount_cents": amount,
        })
        one_time_total += amount

    # ---- discount benefit derived from the GROSS totals --------------------
    if discount_program_applied:
        benefit_intro = (min(DISCOUNT_MONTHLY_CAP_CENTS, totals["INTRO"])
                         if totals["INTRO"] is not None else 0)
        benefit_post = min(DISCOUNT_MONTHLY_CAP_CENTS, totals["POST_PROMO"])
    else:
        benefit_intro = 0
        benefit_post = 0

    net_intro = (totals["INTRO"] - benefit_intro
                 if totals["INTRO"] is not None else None)
    net_post = totals["POST_PROMO"] - benefit_post

    # ---- first-year disclosure, both variants -----------------------------
    if plan["intro_price_cents"] is not None:
        intro_months = min(plan["intro_term_months"], PROMO_DISCLOSURE_MONTHS)
    else:
        intro_months = 0
    intro_component = (net_intro or 0) * intro_months
    promo_weighted = (
        one_time_total
        + intro_component
        + net_post * (PROMO_DISCLOSURE_MONTHS - intro_months)
    )
    post_promo_annualised = one_time_total + net_post * PROMO_DISCLOSURE_MONTHS

    return {
        "fee_itemization": itemization,
        "monthly_total_intro_cents": totals["INTRO"],
        "monthly_total_post_promo_cents": totals["POST_PROMO"],
        "discount_program_benefit_intro_cents": benefit_intro,
        "discount_program_benefit_post_promo_cents": benefit_post,
        "net_monthly_intro_cents": net_intro,
        "net_monthly_post_promo_cents": net_post,
        "one_time_fee_total_cents": one_time_total,
        "first_year_total_promo_weighted_cents": promo_weighted,
        "first_year_total_post_promo_cents": post_promo_annualised,
        "etf_disclosure_cents": plan["early_termination_fee_cents"],
        "data_allowance_gb_snapshot": plan["data_allowance_gb"],
        "overage_rate_cents_per_gb_snapshot": plan["overage_rate_cents_per_gb"],
    }


ONE_TIME_PHASE = "ONE_TIME"


# ---------------------------------------------------------------------------
# calculations.typical_speed_metrics  (PRD §3.4)
# ---------------------------------------------------------------------------

def eligible_runs(plan_id, methodology_doc_id):
    rows = [r for r in db.store.test_runs.values()
            if r["plan_id"] == plan_id
            and r["methodology_doc_id"] == methodology_doc_id
            and r["status"] == "INCLUDED"]
    return db.ordered(rows)


def typical_speed_metrics(plan, runs, metric_variant, snapshot):
    """Returns the computed metric dict, or None when the pool is empty."""
    all_samples = []
    for run in runs:
        all_samples.extend(run["samples"])
    if not all_samples:
        return None

    if metric_variant == "PEAK_HOUR_MEDIAN":
        start_hour = snapshot["peak_hours_start_utc_hour"]
        end_hour = snapshot["peak_hours_end_utc_hour"]
        pool = []
        for sample in all_samples:
            moment = db.parse_iso(sample["observed_at"])
            hour = moment.hour
            if start_hour <= hour < end_hour:
                pool.append(sample)
    else:
        pool = list(all_samples)

    if not pool:
        return None

    downloads = [dec(s["download_mbps"]) for s in pool]
    uploads = [dec(s["upload_mbps"]) for s in pool]
    latencies = [dec(s["latency_ms"]) for s in pool]

    if metric_variant == "PEAK_HOUR_MEDIAN":
        typical_download = median(downloads)
        typical_upload = median(uploads)
    else:
        typical_download = percentile(downloads, "0.20")
        typical_upload = percentile(uploads, "0.20")

    typical_latency = percentile(latencies, "0.95")

    typical_download = round_half_up(typical_download, 2)
    typical_upload = round_half_up(typical_upload, 2)
    typical_latency_ms = int(round_half_up(typical_latency, 0))

    download_margin = round_half_up(
        typical_download / dec(plan["advertised_download_mbps"]), 4)
    upload_margin = round_half_up(
        typical_upload / dec(plan["advertised_upload_mbps"]), 4)

    return {
        "pooled_sample_count": len(pool),
        "typical_download_mbps": float(typical_download),
        "typical_upload_mbps": float(typical_upload),
        "typical_latency_ms": typical_latency_ms,
        "download_margin_pct": float(download_margin),
        "upload_margin_pct": float(upload_margin),
    }


# ---------------------------------------------------------------------------
# calculations.plan_label_posture  (PRD §2.9)
# ---------------------------------------------------------------------------

def published_label(plan_id):
    for label in db.ordered(db.store.label_versions.values()):
        if label["plan_id"] == plan_id and label["publication_state"] == "PUBLISHED":
            return label
    return None


def recompute_plan_posture(plan):
    published = published_label(plan["id"])
    if plan["upheld_complaint_count"] >= POSTURE_FREEZE_UPHELD_COUNT:
        posture = "FROZEN"
    elif published is not None and published["substantiation_status"] == "UNSUBSTANTIATED":
        posture = "FROZEN"
    elif published is None:
        posture = "RESTRICTED"
    elif plan["price_disclosure_drift"]:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    plan["label_posture"] = posture
    return posture


# ---------------------------------------------------------------------------
# calculations.effective_label_selection  (PRD §3.7)
# ---------------------------------------------------------------------------

def select_effective_label(plan_id):
    clock = db.now()
    candidates = []
    for label in db.store.label_versions.values():
        if label["plan_id"] != plan_id:
            continue
        if label["publication_state"] != "PUBLISHED":
            continue
        effective_from = db.dt_of(label, "effective_from")
        if effective_from is None or effective_from > clock:
            continue
        effective_until = db.dt_of(label, "effective_until")
        if effective_until is not None and not clock < effective_until:
            continue
        candidates.append(label)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (-r["version_seq"], r["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# calculations.account_pricing_phase  (PRD §3.7)
# ---------------------------------------------------------------------------

def account_pricing_phase(account):
    plan = db.store.service_plans.get(account["plan_id"])
    if plan is None or plan["intro_price_cents"] is None:
        return "POST_PROMO"
    start = db.dt_of(account, "service_start_date")
    if start is None:
        return "POST_PROMO"
    elapsed_months = db.elapsed_30day_months(start, db.now())
    if elapsed_months < plan["intro_term_months"]:
        return "INTRO"
    return "POST_PROMO"


# ---------------------------------------------------------------------------
# calculations.complaint_shortfall_assessment  (PRD §3.8)
# ---------------------------------------------------------------------------

def complaint_shortfall_assessment(complaint, label):
    allegation = complaint["allegation_type"]
    if allegation == "SPEED_SHORTFALL":
        claimed = dec(label["typical_download_mbps"])
        observed = dec(complaint["measured_download_mbps"])
        gap = claimed - observed
        if gap < 0:
            gap = Decimal(0)
        ratio = round_half_up(gap / claimed, 4)
    elif allegation == "LATENCY_SHORTFALL":
        claimed_latency = dec(label["typical_latency_ms"])
        allowed = claimed_latency + LATENCY_TOLERANCE_MS
        excess = dec(complaint["measured_latency_ms"]) - allowed
        if excess < 0:
            excess = Decimal(0)
        ratio = excess / claimed_latency
        if ratio > 1:
            ratio = Decimal(1)
        ratio = round_half_up(ratio, 4)
    elif allegation == "RELIABILITY_OUTAGE":
        ratio = dec(complaint["affected_days"]) / dec(RELIABILITY_WINDOW_DAYS)
        if ratio > 1:
            ratio = Decimal(1)
        ratio = round_half_up(ratio, 4)
    else:  # FEE_MISMATCH
        ratio = round_half_up(Decimal(0), 4)

    if ratio < 0:
        ratio = Decimal("0.0000")

    if ratio >= SEVERE_RATIO:
        severity = "SEVERE"
    elif ratio >= MODERATE_RATIO:
        severity = "MODERATE"
    elif ratio > 0:
        severity = "MINOR"
    else:
        severity = "NONE"
    return float(ratio), severity


# ---------------------------------------------------------------------------
# calculations.remediation_credit_amount  (PRD §3.8)
# ---------------------------------------------------------------------------

def remediation_credit_amount(complaint, label, account):
    phase = account_pricing_phase(account)
    if phase == "INTRO":
        base = label["net_monthly_intro_cents"]
        if base is None:
            base = label["net_monthly_post_promo_cents"]
    else:
        base = label["net_monthly_post_promo_cents"]
    if base is None:
        base = 0

    if complaint["severity"] == "NONE":
        return 0

    if complaint["credit_basis"] == "PRORATA_DAYS":
        days = min(complaint["affected_days"], CREDIT_WINDOW_DAYS)
        raw = (dec(base) * dec(complaint["shortfall_ratio"]) * dec(days)
               / dec(CREDIT_WINDOW_DAYS))
    else:  # FLAT_SEVERITY_TIER
        raw = dec(FLAT_TIER_CENTS[complaint["severity"]])

    amount = round_cents(raw)
    if amount < CREDIT_FLOOR_CENTS:
        amount = CREDIT_FLOOR_CENTS
    if amount > base:
        amount = base
    return amount


# ---------------------------------------------------------------------------
# calculations.etf_disclosure_amount  (PRD §3.7)
# ---------------------------------------------------------------------------

def etf_disclosure_amount(account, source_plan):
    policy = source_plan["etf_proration_policy"]
    if policy == "NONE":
        return 0
    if policy == "FULL":
        return source_plan["early_termination_fee_cents"]
    start = db.dt_of(account, "service_start_date")
    elapsed_months = db.elapsed_30day_months(start, db.now()) if start else 0
    remaining = source_plan["intro_term_months"] - elapsed_months
    if remaining < 0:
        remaining = 0
    denominator = source_plan["intro_term_months"]
    if denominator < 1:
        denominator = 1
    return round_cents(
        dec(source_plan["early_termination_fee_cents"]) * dec(remaining)
        / dec(denominator))
