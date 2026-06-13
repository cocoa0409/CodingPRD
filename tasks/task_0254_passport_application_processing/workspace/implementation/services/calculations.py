"""Calculation rules (scaffold §1.3 / PRD §3.5-3.8).

All monetary amounts are integer cents; a single combination at the very end.
The verification risk score is the only fractional arithmetic — 2 dp, round-half-up.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import db

# ---- fee constants (integer cents) -------------------------------------------
BOOK_ADULT_CENTS = 13000
BOOK_MINOR_CENTS = 10000
CARD_ADULT_CENTS = 3000
CARD_MINOR_CENTS = 1500
BUNDLE_DISCOUNT_CENTS = 1000
EXECUTION_FEE_CENTS = 3500
EXPEDITE_FEE_CENTS = 6000
URGENT_SURCHARGE_CENTS = 6000
ONE_DAY_DELIVERY_CENTS = 2136

# ---- risk score weights ------------------------------------------------------
W_IDENTITY = Decimal("0.40")
W_CITIZENSHIP = Decimal("0.35")
W_PHOTO = Decimal("0.25")
REVIEW_HOLD_THRESHOLD = Decimal("50")

# ---- SLA -----------------------------------------------------------------------
ROUTINE_DAYS = 42
EXPEDITE_DAYS = 21


# ---- date helpers ------------------------------------------------------------
def parse_iso_to_date(iso: str) -> date:
    """Extract the calendar date from an ISO 8601 instant or date string."""
    s = iso
    # Tolerate trailing 'Z'
    if s.endswith("Z"):
        s = s[:-1]
    # date-only
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return date.fromisoformat(s)
    # full datetime
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        # last resort: take first 10 chars
        return date.fromisoformat(s[:10])


# =============================================================================
# fee_assessment
# =============================================================================
def compute_fee_components(application: dict, one_day_delivery: bool) -> dict:
    is_minor = application["applicant_is_minor"]
    product_type = application["product_type"]
    service_level = application["service_level"]

    book_cents = BOOK_MINOR_CENTS if is_minor else BOOK_ADULT_CENTS
    card_cents = CARD_MINOR_CENTS if is_minor else CARD_ADULT_CENTS

    if product_type == "BOOK":
        base = book_cents
    elif product_type == "CARD":
        base = card_cents
    else:  # BOOK_AND_CARD
        base = book_cents + card_cents - BUNDLE_DISCOUNT_CENTS

    execution = EXECUTION_FEE_CENTS if application["requires_execution"] else 0
    expedite = EXPEDITE_FEE_CENTS if service_level == "EXPEDITE" else 0
    urgent = URGENT_SURCHARGE_CENTS if application["urgent_travel"] else 0
    delivery = ONE_DAY_DELIVERY_CENTS if one_day_delivery else 0

    total = base + execution + expedite + urgent + delivery
    return {
        "base_fee_cents": base,
        "execution_fee_cents": execution,
        "expedite_fee_cents": expedite,
        "urgent_surcharge_cents": urgent,
        "one_day_delivery_cents": delivery,
        "total_due_cents": total,
    }


# =============================================================================
# verification_risk_score (FINAL or PROVISIONAL)
# =============================================================================
def _factor_quality_final(docs: list, category: str) -> int:
    """Highest declared_quality among ACCEPTED docs of this category, else 0."""
    accepted = [
        d["declared_quality"]
        for d in docs
        if d["doc_category"] == category and d["verification_status"] == "ACCEPTED"
    ]
    return max(accepted) if accepted else 0


def _round2(value: Decimal) -> float:
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def compute_risk_score_for_applicant(applicant_id: str) -> float:
    """FINAL variant across ALL applications owned by the applicant.

    Only ACCEPTED docs contribute their declared_quality. Photo factor is 100
    if any photo on any of the applicant's applications has validation_result
    PASS, else 0.
    """
    app_ids = [
        a["id"] for a in db.applications.values() if a["applicant_id"] == applicant_id
    ]
    docs = [d for d in db.supporting_documents.values() if d["application_id"] in app_ids]
    photos = [p for p in db.photos.values() if p["application_id"] in app_ids]

    q_identity = _factor_quality_final(docs, "IDENTITY")
    q_citizen = _factor_quality_final(docs, "CITIZENSHIP")
    photo_quality = 100 if any(p["validation_result"] == "PASS" for p in photos) else 0

    quality = (
        W_IDENTITY * Decimal(q_identity)
        + W_CITIZENSHIP * Decimal(q_citizen)
        + W_PHOTO * Decimal(photo_quality)
    )
    risk = Decimal(100) - quality
    return _round2(risk)


def compute_risk_score_provisional(application: dict) -> float:
    """PROVISIONAL variant at submission: no document is verified yet, so both
    document factors are 0; only the PASS photo on this application contributes.

    Computed for the owning applicant but at submission no doc is ACCEPTED, so
    it equals 100 - 25*(photo PASS?) at the applicant level too. We evaluate
    over the applicant's full set to remain consistent (still 0 for docs since
    none are accepted) and to capture an existing PASS photo on any of the
    applicant's applications.
    """
    return compute_risk_score_for_applicant(application["applicant_id"])


# =============================================================================
# processing_sla_target
# =============================================================================
def _days_for(service_level: str) -> int:
    return EXPEDITE_DAYS if service_level == "EXPEDITE" else ROUTINE_DAYS


def forward_looking_target(application: dict) -> str | None:
    """effective_start = date(submitted_at); null if not submitted."""
    submitted_at = application.get("submitted_at")
    if not submitted_at:
        return None
    start = parse_iso_to_date(submitted_at)
    target = start + timedelta(days=_days_for(application["service_level"]))
    return target.isoformat()


def chronological_target(application: dict) -> str | None:
    """effective_start = date(verification_completed_at); null until verified."""
    vc = application.get("verification_completed_at")
    if not vc:
        return None
    start = parse_iso_to_date(vc)
    target = start + timedelta(days=_days_for(application["service_level"]))
    return target.isoformat()


# =============================================================================
# photo_validation
# =============================================================================
MIN_DIMENSION_PX = 600
RATIO_MIN = 0.98
RATIO_MAX = 1.02
HEAD_FRACTION_MIN = 0.50
HEAD_FRACTION_MAX = 0.69


def validate_photo(width_px: int, height_px: int, head_height_fraction: float, background_is_white: bool):
    reasons = []
    if not (MIN_DIMENSION_PX <= width_px and MIN_DIMENSION_PX <= height_px):
        reasons.append("DIMENSION_TOO_SMALL")
    ratio = width_px / height_px
    if not (RATIO_MIN <= ratio <= RATIO_MAX):
        reasons.append("NOT_SQUARE")
    if not (HEAD_FRACTION_MIN <= head_height_fraction <= HEAD_FRACTION_MAX):
        reasons.append("HEAD_OUT_OF_RANGE")
    if not background_is_white:
        reasons.append("BACKGROUND_NOT_WHITE")
    result = "PASS" if not reasons else "FAIL"
    return result, reasons
