"""Domain assertions and the arithmetic the PRD mandates.

Money is exact integer cents, so it is compared exactly. Ratios and scores are
rounded half-up — ratios to four decimal places, each weighted score component to
two — and the helpers here reproduce that discipline so a test can state the
expected figure the way the PRD derives it.
"""

from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASE_FEE_CENTS,
    CATEGORY_SURCHARGE_RATE,
    FEE_PER_DECLARED_FEATURE_CENTS,
    LISTING_REFERENCE_PREFIX,
    MINUTES_PER_BENCH_PER_CYCLE,
    PENALTY_BAND_1_RATE_CENTS,
    PENALTY_BAND_1_UNITS,
    PENALTY_BAND_2_RATE_CENTS,
    PENALTY_BAND_2_UNITS,
    PENALTY_BAND_3_RATE_CENTS,
    PENALTY_CAP_CENTS,
    REVIEW_TRACK_MULTIPLIER,
    SECURITY_BASELINE_SURCHARGE_CENTS,
    TIER_DISCOUNT_RATE,
)

# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def as_decimal(value):
    """Coerce a reported figure to Decimal without losing precision."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places):
    """Round half-up to ``places`` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return as_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round a rate-bearing money computation to whole cents, half-up."""
    return int(round_half_up(value, 0))


def ratio(numerator, denominator, when_zero_denominator="0.0000"):
    """A ratio rounded half-up to four decimal places."""
    if denominator == 0:
        return round_half_up(when_zero_denominator, 4)
    return round_half_up(as_decimal(numerator) / as_decimal(denominator), 4)


def weighted_component(weight, component_ratio):
    """One weighted score component, rounded half-up to two decimal places."""
    return round_half_up(as_decimal(weight) * as_decimal(component_ratio), 2)


def score_from_components(pairs):
    """The exact sum of per-component-rounded weighted components."""
    total = Decimal("0")
    for weight, component in pairs:
        total += weighted_component(weight, component)
    return round_half_up(total, 2)


# ---------------------------------------------------------------------------
# Envelope and common fields
# ---------------------------------------------------------------------------


def assert_common_fields(entity, label="resource"):
    """Every resource family carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity.get("id")), (
        "{} id must be a UUID string with no type prefix, got {!r}".format(
            label, entity.get("id")
        )
    )
    assert is_iso8601_timestamp(entity.get("created_at")), (
        "{} created_at must be an ISO 8601 UTC timestamp, got {!r}".format(
            label, entity.get("created_at")
        )
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        "{} updated_at must be an ISO 8601 UTC timestamp, got {!r}".format(
            label, entity.get("updated_at")
        )
    )
    assert isinstance(entity.get("version"), int) and entity["version"] >= 1, (
        "{} version must be an integer starting at 1, got {!r}".format(
            label, entity.get("version")
        )
    )


def assert_freshly_created(entity, label="resource"):
    """At creation ``updated_at`` equals ``created_at`` and ``version`` is 1."""
    assert_common_fields(entity, label)
    assert entity["version"] == 1, (
        "{} version must be 1 at creation, got {}".format(label, entity["version"])
    )
    assert entity["updated_at"] == entity["created_at"], (
        "{} updated_at must equal created_at at creation, got {} vs {}".format(
            label, entity["updated_at"], entity["created_at"]
        )
    )


def assert_version(entity, expected, label="resource"):
    assert entity.get("version") == expected, (
        "{} version must be {}, got {}".format(label, expected, entity.get("version"))
    )


def assert_score(actual, expected, label="score"):
    """Scores are reported with two decimal places."""
    assert actual is not None, "{} must be reported, got None".format(label)
    assert round_half_up(actual, 2) == round_half_up(expected, 2), (
        "{} must be {}, got {!r}".format(label, expected, actual)
    )


def assert_ratio_equals(actual, expected, label="ratio"):
    """Ratios are reported with four decimal places."""
    assert actual is not None, "{} must be reported, got None".format(label)
    assert round_half_up(actual, 4) == round_half_up(expected, 4), (
        "{} must be {}, got {!r}".format(label, expected, actual)
    )


def assert_cents(actual, expected, label="amount"):
    """Money is an integer number of cents and is compared exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "{} must be an integer number of cents, got {!r}".format(label, actual)
    )
    assert actual == expected, "{} must be {} cents, got {}".format(
        label, expected, actual
    )


def assert_listing_reference(value, ordinal):
    """``LST-`` plus a six-digit zero-padded ordinal."""
    expected = "{}{:06d}".format(LISTING_REFERENCE_PREFIX, ordinal)
    assert value == expected, "listing_reference must be {}, got {!r}".format(
        expected, value
    )


# ---------------------------------------------------------------------------
# Fee arithmetic
# ---------------------------------------------------------------------------


def expected_certification_fee(
    device_type, declared_feature_count, security_baseline_level, tier, review_track
):
    """The pinned certification fee: subtotal, then discount-and-round, then
    multiplier-and-round."""
    subtotal = (
        BASE_FEE_CENTS[device_type]
        + FEE_PER_DECLARED_FEATURE_CENTS * declared_feature_count
        + SECURITY_BASELINE_SURCHARGE_CENTS[security_baseline_level]
    )
    discounted = round_cents(
        as_decimal(subtotal) * (Decimal("1") - as_decimal(TIER_DISCOUNT_RATE[tier]))
    )
    return round_cents(
        as_decimal(discounted) * as_decimal(REVIEW_TRACK_MULTIPLIER[review_track])
    )


# ---------------------------------------------------------------------------
# Penalty arithmetic
# ---------------------------------------------------------------------------


def expected_penalty(claimed_impact_units, category):
    """The marginally-tiered assessment: subtotal, surcharge and capped total."""
    units = int(claimed_impact_units)
    band_one = min(units, PENALTY_BAND_1_UNITS)
    band_two = min(max(units - PENALTY_BAND_1_UNITS, 0), PENALTY_BAND_2_UNITS)
    band_three = max(units - PENALTY_BAND_1_UNITS - PENALTY_BAND_2_UNITS, 0)
    subtotal = (
        band_one * PENALTY_BAND_1_RATE_CENTS
        + band_two * PENALTY_BAND_2_RATE_CENTS
        + band_three * PENALTY_BAND_3_RATE_CENTS
    )
    surcharge = round_cents(
        as_decimal(subtotal) * as_decimal(CATEGORY_SURCHARGE_RATE[category])
    )
    total = min(subtotal + surcharge, PENALTY_CAP_CENTS)
    return subtotal, surcharge, total


def assert_penalty(case, claimed_impact_units, category):
    """The three penalty figures, with subtotal and surcharge stored uncapped."""
    subtotal, surcharge, total = expected_penalty(claimed_impact_units, category)
    assert_cents(case.get("assessment_subtotal_cents"), subtotal, "assessment_subtotal_cents")
    assert_cents(case.get("surcharge_cents"), surcharge, "surcharge_cents")
    assert_cents(case.get("penalty_total_cents"), total, "penalty_total_cents")


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def assert_credit_ledger_invariant(member_or_ledger, balance_field=None):
    """``credits_purchased_cents`` equals balance plus consumed plus escrowed."""
    row = member_or_ledger
    field = balance_field or (
        "balance_cents" if "balance_cents" in row else "credit_balance_cents"
    )
    purchased = row["credits_purchased_cents"]
    consumed = row["credits_consumed_cents"]
    escrowed = row["escrowed_credit_cents"]
    balance = row[field]
    assert purchased == balance + consumed + escrowed, (
        "credits_purchased_cents {} must equal {} + {} + {} = {}".format(
            purchased, balance, consumed, escrowed, balance + consumed + escrowed
        )
    )


def assert_reserved_bench_minutes(laboratory, expected):
    assert laboratory.get("reserved_bench_minutes") == expected, (
        "reserved_bench_minutes must be {}, got {}".format(
            expected, laboratory.get("reserved_bench_minutes")
        )
    )


def capacity_ceiling(bench_capacity):
    """Each bench is budgeted 600 minutes per cycle."""
    return bench_capacity * MINUTES_PER_BENCH_PER_CYCLE


def assert_states(entity, **expected):
    """Assert several fields of one row in a single readable failure."""
    for field, value in expected.items():
        assert entity.get(field) == value, (
            "{} must be {!r}, got {!r}".format(field, value, entity.get(field))
        )
