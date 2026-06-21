"""Calculation rules — quote_estimate, final_invoice, linguist_payout, qa_score.

All monetary math uses Decimal with ROUND_HALF_UP. Per-band-then-sum rounding
is pinned (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP
import math

# Band pay factors (PRD §3.3, §3.9, scaffold PAY_FACTOR)
PAY_FACTOR = {
    "no_match": Decimal("1.00"),
    "fuzzy": Decimal("0.65"),
    "reps": Decimal("0.35"),
    "context": Decimal("0.15"),
}

RUSH_MULT = {
    "STANDARD": Decimal("1.00"),
    "EXPRESS": Decimal("1.30"),
    "SAME_DAY": Decimal("1.75"),
}

WORDS_PER_PAGE = 250
CERT_PER_PAGE_CENTS = 500
NOTARY_FLAT_CENTS = 3500

REVISION_SURCHARGE_PCT = Decimal("0.08")
FREE_REVISION_ROUNDS = 1

QA_BONUS_THRESHOLD = Decimal("95")
QA_REWORK_FLOOR = Decimal("80")
QA_BONUS_PCT = Decimal("0.05")
QA_PENALTY_PCT = Decimal("0.10")

# QA scoring constants (PRD §3.10)
CRITICAL_W = 10
MAJOR_W = 5
MINOR_W = 1
QA_PASS_THRESHOLD = Decimal("90.0")


def round_half_up_cents(value):
    """Round a Decimal to the nearest whole cent, half up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def volume_discount_pct(weighted_words):
    """VOLUME_TIER: >= 20000 -> 0.10 ; >= 5000 -> 0.05 ; else 0.00 (>= boundaries)."""
    w = Decimal(weighted_words)
    if w >= Decimal("20000"):
        return Decimal("0.10")
    if w >= Decimal("5000"):
        return Decimal("0.05")
    return Decimal("0.00")


def _bands_from(job, prefix):
    """Return ordered list of (band_key, word_count) using the given field prefix
    ('quoted' or 'actual')."""
    return [
        ("no_match", job["%s_no_match_words" % prefix] or 0),
        ("fuzzy", job["%s_fuzzy_words" % prefix] or 0),
        ("reps", job["%s_reps_words" % prefix] or 0),
        ("context", job["%s_context_words" % prefix] or 0),
    ]


def job_weighted_words(job, prefix):
    """Sum over bands of band_words * PAY_FACTOR[band] (unrounded Decimal)."""
    total = Decimal("0")
    for band, words in _bands_from(job, prefix):
        total += Decimal(words) * PAY_FACTOR[band]
    return total


def job_per_band_subtotal_cents(job, prefix, base_rate):
    """Step 1+2 for a single job: sum of per-band amounts, each rounded then summed."""
    base = Decimal(base_rate)
    subtotal = 0
    for band, words in _bands_from(job, prefix):
        per_band = Decimal(words) * base * PAY_FACTOR[band]
        subtotal += round_half_up_cents(per_band)
    return subtotal


def job_total_source_words(job, prefix):
    """Sum of the four raw band word counts."""
    return sum(words for _band, words in _bands_from(job, prefix))


def page_count(total_source_words):
    """ceil(total_source_words / WORDS_PER_PAGE)."""
    if total_source_words <= 0:
        return 0
    return math.ceil(total_source_words / WORDS_PER_PAGE)


def certification_cents(total_source_words, mode):
    if mode == "NONE":
        return 0
    pages = page_count(total_source_words)
    if mode == "CERTIFIED":
        return pages * CERT_PER_PAGE_CENTS
    if mode == "NOTARIZED":
        return pages * CERT_PER_PAGE_CENTS + NOTARY_FLAT_CENTS
    return 0


# ----------------------------------------------------------------------------
# quote_estimate (PRD §3.3)
# ----------------------------------------------------------------------------
def quote_estimate(jobs, base_rate, rush_tier, certification_mode):
    """Returns quoted_total_cents (int) over QUOTED bands across all jobs."""
    # step 1+2: translation subtotal (round per band, then sum, across all jobs)
    translation_subtotal = 0
    for job in jobs:
        translation_subtotal += job_per_band_subtotal_cents(job, "quoted", base_rate)

    # step 3: weighted words (unrounded) across all jobs
    weighted_words = Decimal("0")
    for job in jobs:
        weighted_words += job_weighted_words(job, "quoted")

    # step 4: volume discount
    pct = volume_discount_pct(weighted_words)
    after_vol = round_half_up_cents(Decimal(translation_subtotal) * (Decimal("1") - pct))

    # step 5: rush
    after_rush = round_half_up_cents(Decimal(after_vol) * RUSH_MULT[rush_tier])

    # step 6: certification
    total_source_words = sum(job_total_source_words(job, "quoted") for job in jobs)
    cert = certification_cents(total_source_words, certification_mode)

    # step 7
    return after_rush + cert


# ----------------------------------------------------------------------------
# final_invoice (PRD §3.8)
# ----------------------------------------------------------------------------
def final_invoice(jobs, base_rate, rush_tier, certification_mode):
    """Returns dict with the six computed amount fields and total_cents.

    `jobs` are the DELIVERED jobs; uses ACTUAL bands.
    """
    # step 1: translation subtotal over actual bands (per-band rounded, then summed)
    translation_subtotal_cents = 0
    per_job_subtotal = {}
    for job in jobs:
        sub = job_per_band_subtotal_cents(job, "actual", base_rate)
        per_job_subtotal[job["id"]] = sub
        translation_subtotal_cents += sub

    # step 2: weighted words over actual bands; volume discount
    weighted_words = Decimal("0")
    for job in jobs:
        weighted_words += job_weighted_words(job, "actual")
    pct = volume_discount_pct(weighted_words)
    after_vol = round_half_up_cents(
        Decimal(translation_subtotal_cents) * (Decimal("1") - pct))
    volume_discount_cents = translation_subtotal_cents - after_vol

    # step 3: rush surcharge
    rush_total = round_half_up_cents(Decimal(after_vol) * RUSH_MULT[rush_tier])
    rush_surcharge_cents = rush_total - after_vol

    # step 4: revision surcharge (sum over jobs)
    revision_surcharge_cents = 0
    for job in jobs:
        chargeable = max(0, (job.get("revision_rounds") or 0) - FREE_REVISION_ROUNDS)
        if chargeable > 0:
            surcharge = round_half_up_cents(
                Decimal(per_job_subtotal[job["id"]])
                * REVISION_SURCHARGE_PCT
                * Decimal(chargeable))
            revision_surcharge_cents += surcharge

    # step 5: certification from actual total source words
    total_source_words = sum(job_total_source_words(job, "actual") for job in jobs)
    cert_cents = certification_cents(total_source_words, certification_mode)

    # step 6: total
    total_cents = after_vol + rush_surcharge_cents + revision_surcharge_cents + cert_cents

    return {
        "translation_subtotal_cents": translation_subtotal_cents,
        "volume_discount_cents": volume_discount_cents,
        "rush_surcharge_cents": rush_surcharge_cents,
        "revision_surcharge_cents": revision_surcharge_cents,
        "certification_cents": cert_cents,
        "total_cents": total_cents,
    }


# ----------------------------------------------------------------------------
# linguist_payout (PRD §3.9)
# ----------------------------------------------------------------------------
def linguist_payout_provisional(job, linguist_rate):
    """Base over QUOTED bands, no quality adjustment."""
    weighted = job_weighted_words(job, "quoted")
    return round_half_up_cents(weighted * Decimal(linguist_rate))


def linguist_payout_final(job, linguist_rate, latest_qa_score):
    """Base over ACTUAL bands plus a quality adjustment keyed on latest_qa_score."""
    weighted = job_weighted_words(job, "actual")
    base = round_half_up_cents(weighted * Decimal(linguist_rate))
    adj = 0
    if latest_qa_score is not None:
        score = Decimal(str(latest_qa_score))
        if score >= QA_BONUS_THRESHOLD:
            adj = round_half_up_cents(Decimal(base) * QA_BONUS_PCT)
        elif score < QA_REWORK_FLOOR:
            adj = -round_half_up_cents(Decimal(base) * QA_PENALTY_PCT)
        else:
            adj = 0
    return base + adj


# ----------------------------------------------------------------------------
# qa_score (PRD §3.10)
# ----------------------------------------------------------------------------
def qa_score(critical_count, major_count, minor_count, scored_word_count):
    """Returns (score: float one decimal place, outcome: 'PASS'|'FAIL')."""
    weighted_errors = (Decimal(critical_count) * CRITICAL_W
                       + Decimal(major_count) * MAJOR_W
                       + Decimal(minor_count) * MINOR_W)
    penalty = weighted_errors / Decimal(scored_word_count) * Decimal("1000")
    raw = Decimal("100") - penalty
    score = raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if score < 0:
        score = Decimal("0.0")
    outcome = "PASS" if score >= QA_PASS_THRESHOLD else "FAIL"
    return float(score), outcome
