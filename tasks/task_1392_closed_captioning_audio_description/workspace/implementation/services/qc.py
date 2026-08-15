"""caption_accuracy (PRD §3.4): weighted error scoring in exact decimal
arithmetic with a single final ROUND_HALF_UP to two decimal places."""
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, ERR_VALIDATION
from util import is_int

WEIGHT_MINOR = 1
WEIGHT_MAJOR = 3
WEIGHT_CRITICAL = 10

THRESHOLD_PCT = {
    "FCC_BROADCAST": Decimal("99.00"),
    "SECTION_508": Decimal("98.50"),
    "INTERNAL": Decimal("95.00"),
}

REVIEW_MODES = {"FULL_REVIEW", "SAMPLED_REVIEW"}


def min_sampled_words(total_words):
    """ceil(total_words * 0.20) in exact integer arithmetic."""
    return -(-total_words // 5)


def validate_review_shape(data):
    review_mode = data.get("review_mode")
    if review_mode not in REVIEW_MODES:
        raise ApiError(ERR_VALIDATION, 400, "Field 'review_mode' must be FULL_REVIEW or SAMPLED_REVIEW")
    total_words = data.get("total_words")
    if not is_int(total_words) or total_words <= 0:
        raise ApiError(ERR_VALIDATION, 400, "Field 'total_words' must be an integer > 0")
    counts = {}
    for field in ("minor_errors", "major_errors", "critical_errors"):
        v = data.get(field)
        if not is_int(v) or v < 0:
            raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be an integer >= 0")
        counts[field] = v
    sampled_words = data.get("sampled_words")
    if review_mode == "SAMPLED_REVIEW":
        if not is_int(sampled_words):
            raise ApiError(ERR_VALIDATION, 400, "Field 'sampled_words' is required for SAMPLED_REVIEW")
        if sampled_words < min_sampled_words(total_words):
            raise ApiError(
                ERR_VALIDATION,
                400,
                "Field 'sampled_words' must be >= ceil(total_words * 0.20)",
            )
    elif sampled_words is not None and not is_int(sampled_words):
        raise ApiError(ERR_VALIDATION, 400, "Field 'sampled_words' must be an integer")
    return review_mode, total_words, sampled_words, counts


def compute_accuracy(review_mode, total_words, sampled_words, counts):
    weighted = (
        counts["minor_errors"] * WEIGHT_MINOR
        + counts["major_errors"] * WEIGHT_MAJOR
        + counts["critical_errors"] * WEIGHT_CRITICAL
    )
    denominator = total_words if review_mode == "FULL_REVIEW" else sampled_words
    # Exact decimal arithmetic; one rounding step at the very end.
    accuracy = (Decimal(1) - Decimal(weighted) / Decimal(denominator)) * Decimal(100)
    accuracy = accuracy.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return weighted, accuracy


def outcome_for(accuracy_pct, compliance_standard):
    threshold = THRESHOLD_PCT[compliance_standard]
    # Inclusive comparison: accuracy_pct >= threshold_pct passes.
    return threshold, ("PASS" if accuracy_pct >= threshold else "FAIL")
