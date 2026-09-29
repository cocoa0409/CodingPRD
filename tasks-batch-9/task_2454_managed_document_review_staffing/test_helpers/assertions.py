"""Domain assertions and money helpers.

The money helpers reproduce the PRD's arithmetic exactly — round half up, and
for per-document pricing the rate is rounded to whole cents before it is
multiplied by the document count — so a test can express an expectation as a
formula rather than as an opaque literal when that reads better.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

import pytest

from .constants import (
    ACCURACY_WEIGHT,
    COMPLEXITY_TIER_MULTIPLIER,
    HOURLY_INCREMENT_MINUTES,
    LANGUAGE_PREMIUM_PER_LANGUAGE,
    LANGUAGE_WEIGHT,
    PACE_NORMALISATION_CAP,
    PACE_WEIGHT,
    PASS_TYPE_MULTIPLIER,
    PRIVILEGE_VALIDATION_FLOOR,
    QC_MIN_SAMPLE_DOCS,
    QC_SURCHARGE_FACTOR,
    STRIKE_PENALTY_CAP,
    STRIKE_PENALTY_WEIGHT,
    SUBJECT_WEIGHT,
    VOLUME_DISCOUNT_BAND_HIGH_FLOOR,
    VOLUME_DISCOUNT_BAND_LOW_CEILING,
    VOLUME_DISCOUNT_PCT_HIGH,
    VOLUME_DISCOUNT_PCT_LOW,
    VOLUME_DISCOUNT_PCT_MID,
)

# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def round_half_up(value, places: int = 0):
    """Round half up to ``places`` decimal places, as all money and rates do."""
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


# ---------------------------------------------------------------------------
# Rates and commitments
# ---------------------------------------------------------------------------


def contract_rate_cents(per_document_rate_cents: int, complexity_tier: str) -> int:
    """The contract rate: base rate times tier multiplier, rounded half up.

    Deliberately excludes any reviewer-specific language premium, because the
    forward-looking spend basis prices work whose reviewer is not yet known.
    """
    product = (
        Decimal(per_document_rate_cents)
        * COMPLEXITY_TIER_MULTIPLIER[complexity_tier]
    )
    return round_half_up(product)


def premium_language_count(
    reviewer_languages: list[str], required_languages: list[str]
) -> int:
    """Languages common to both lists, with English excluded.

    English attracts no premium, so it is removed from the intersection before
    the remaining languages are counted.
    """
    shared = set(reviewer_languages) & set(required_languages)
    shared.discard("EN")
    return len(shared)


def effective_per_document_cents(
    per_document_rate_cents: int,
    complexity_tier: str,
    premium_languages: int,
    pass_type: str,
) -> int:
    """The pinned per-document rate for an assignment.

    The whole product is formed first and only then rounded half up to whole
    cents; the rounded rate is what is later multiplied by the document count.
    ``premium_languages`` counts the shared languages after English has been
    removed, because English attracts no premium.
    """
    factor = (
        Decimal(1) + LANGUAGE_PREMIUM_PER_LANGUAGE * Decimal(premium_languages)
    )
    product = (
        Decimal(per_document_rate_cents)
        * COMPLEXITY_TIER_MULTIPLIER[complexity_tier]
        * factor
        * PASS_TYPE_MULTIPLIER[pass_type]
    )
    return round_half_up(product)


def hourly_commitment_cents(
    hourly_rate_cents: int, document_count: int, min_pace_dph: int
) -> int:
    """The hourly commitment sizing: rate times documents over the pace floor."""
    product = (
        Decimal(hourly_rate_cents) * Decimal(document_count) / Decimal(min_pace_dph)
    )
    return round_half_up(product)


def billable_minutes(minutes_logged: int) -> int:
    """Minutes rounded up to the next whole six-minute increment."""
    blocks = math.ceil(minutes_logged / HOURLY_INCREMENT_MINUTES)
    return blocks * HOURLY_INCREMENT_MINUTES


def hourly_billable_cents(hourly_rate_cents: int, minutes_logged: int) -> int:
    """Hourly billing from six-minute blocks."""
    minutes = billable_minutes(minutes_logged)
    product = Decimal(hourly_rate_cents) * Decimal(minutes) / Decimal(60)
    return round_half_up(product)


# ---------------------------------------------------------------------------
# Quality control sizing
# ---------------------------------------------------------------------------


def qc_sample_target_size(document_count: int, qc_sample_pct: float) -> int:
    """The greater of ten and the batch size times the sampling percentage."""
    scaled = math.ceil(Decimal(document_count) * Decimal(str(qc_sample_pct)))
    return max(QC_MIN_SAMPLE_DOCS, scaled)


def privilege_validation_quota(entry_count: int, privilege_sample_pct: float) -> int:
    """The greater of two and the entry population times the sampling share."""
    scaled = math.ceil(Decimal(entry_count) * Decimal(str(privilege_sample_pct)))
    return max(PRIVILEGE_VALIDATION_FLOOR, scaled)


def discrepancy_rate(
    coding_error_count: int, privilege_error_count: int, sampled_document_count: int
) -> float:
    """Errors over the frozen sample size, carried to four decimal places."""
    total = Decimal(coding_error_count + privilege_error_count)
    return round_half_up(total / Decimal(sampled_document_count), 4)


# ---------------------------------------------------------------------------
# Invoice waterfall
# ---------------------------------------------------------------------------


def qc_surcharge_cents(gross_billable_cents: int, qc_sample_pct: float) -> int:
    product = (
        Decimal(gross_billable_cents)
        * Decimal(str(qc_sample_pct))
        * QC_SURCHARGE_FACTOR
    )
    return round_half_up(product)


def volume_discount_pct(provisional_total_cents: int) -> Decimal:
    """The band is selected from the provisional total and nothing else."""
    if provisional_total_cents < VOLUME_DISCOUNT_BAND_LOW_CEILING:
        return VOLUME_DISCOUNT_PCT_LOW
    if provisional_total_cents < VOLUME_DISCOUNT_BAND_HIGH_FLOOR:
        return VOLUME_DISCOUNT_PCT_MID
    return VOLUME_DISCOUNT_PCT_HIGH


def invoice_waterfall(gross_billable_cents: int, qc_sample_pct: float) -> dict:
    """The four pinned steps, each consuming the previous step's output."""
    surcharge = qc_surcharge_cents(gross_billable_cents, qc_sample_pct)
    provisional = gross_billable_cents + surcharge
    pct = volume_discount_pct(provisional)
    discount = round_half_up(Decimal(provisional) * pct)
    return {
        "gross_billable_cents": gross_billable_cents,
        "qc_surcharge_cents": surcharge,
        "provisional_total_cents": provisional,
        "volume_discount_pct": float(pct),
        "volume_discount_cents": discount,
        "invoice_total_cents": provisional - discount,
    }


# ---------------------------------------------------------------------------
# Auto-assignment score
# ---------------------------------------------------------------------------


def selector_score(
    accuracy_score: float,
    pace_dph: float,
    min_pace_dph: int,
    matched_language_count: int,
    required_language_count: int,
    matched_subject_count: int,
    required_subject_count: int,
    scorecard_strikes: int,
) -> float:
    """The weighted selector score used to rank an eligible reviewer."""
    pace_component = min(
        Decimal(str(pace_dph)) / Decimal(min_pace_dph), PACE_NORMALISATION_CAP
    ) / PACE_NORMALISATION_CAP
    language_component = (
        Decimal(matched_language_count) / Decimal(required_language_count)
        if required_language_count
        else Decimal(1)
    )
    subject_component = (
        Decimal(matched_subject_count) / Decimal(required_subject_count)
        if required_subject_count
        else Decimal(1)
    )
    strike_component = min(Decimal(scorecard_strikes), Decimal(STRIKE_PENALTY_CAP))
    total = (
        ACCURACY_WEIGHT * Decimal(str(accuracy_score))
        + PACE_WEIGHT * pace_component
        + LANGUAGE_WEIGHT * language_component
        + SUBJECT_WEIGHT * subject_component
        - STRIKE_PENALTY_WEIGHT * strike_component
    )
    return round_half_up(total, 4)


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------


def assert_status(entity: dict, expected: str, field: str = "status") -> None:
    actual = entity.get(field)
    assert actual == expected, (
        f"expected {field} {expected!r} but the row reports {actual!r}"
    )


def assert_money(actual, expected: int, label: str = "amount") -> None:
    """Whole integer cents; no fractional cents are ever stored or returned."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a whole number of cents, got {actual!r}"
    )
    assert actual == expected, f"expected {label} {expected} but got {actual}"


def assert_rate_4dp(actual, expected: float, label: str = "rate") -> None:
    """Accuracy, discrepancy and score values are carried to four places."""
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"expected {label} {expected} but got {actual}"
    )


def assert_pace_2dp(actual, expected: float, label: str = "pace_dph") -> None:
    """Documents-per-hour pace is carried to two places."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"expected {label} {expected} but got {actual}"
    )


def assert_stream_row_has_no_version(row: dict, label: str = "stream row") -> None:
    """Append-only stream rows carry only an identifier and a creation stamp."""
    assert "version" not in row, f"{label} must not carry a version field"
    assert "updated_at" not in row, f"{label} must not carry an updated_at field"


def assert_ledger_entries(
    rows: list[dict], expected: list[tuple[str, int]]
) -> None:
    """Assert the ledger rows, in creation order, match (entry_type, amount)."""
    actual = [(r.get("entry_type"), r.get("amount_cents")) for r in rows]
    assert actual == expected, (
        f"expected ledger movements {expected} in created_at order but got {actual}"
    )


def assert_ledger_movements(
    rows: list[dict], expected: list[tuple[str, int]]
) -> None:
    """Assert the exact population of (entry_type, amount) movements.

    A single settlement writes its actual row and the reversal of its own
    commitment together, so the population is pinned while the relative order of
    those two rows within the settlement is not.
    """
    actual = sorted((r.get("entry_type"), r.get("amount_cents")) for r in rows)
    assert actual == sorted(expected), (
        f"expected the ledger to hold exactly {sorted(expected)} but it holds {actual}"
    )


def assert_ledger_sums_to(rows: list[dict], expected: int) -> None:
    total = sum(r.get("amount_cents", 0) for r in rows)
    assert total == expected, (
        f"expected the ledger replay to total {expected} but it totals {total}"
    )


def assert_scorecard_events(
    rows: list[dict], expected: list[tuple[str, int]]
) -> None:
    """Assert the scorecard rows, in creation order, match (event_type, delta)."""
    actual = [(r.get("event_type"), r.get("strike_delta")) for r in rows]
    assert actual == expected, (
        f"expected scorecard stream {expected} in created_at order but got {actual}"
    )


def assert_created_at_ascending(rows: list[dict]) -> None:
    stamps = [r.get("created_at") for r in rows]
    assert stamps == sorted(stamps), (
        f"rows must be returned in created_at ascending order, got {stamps}"
    )


def assert_ids_equal(rows: list[dict], expected_ids: list[str]) -> None:
    actual = [r.get("id") for r in rows]
    assert actual == expected_ids, (
        f"expected rows {expected_ids} in this order but got {actual}"
    )


def ids_of(rows: list[dict]) -> list[str]:
    return [r.get("id") for r in rows]
