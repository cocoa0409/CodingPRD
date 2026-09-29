"""Domain assertions and pure reference calculators.

Two kinds of helper live here. The ``assert_*`` functions check shape rules the
PRD states once and applies everywhere — the common-property quartet, the
immutable trio that must omit `updated_at` and `version`, the cascade version
discipline, and the two system-wide invariants. The ``expected_*`` functions are
pure re-implementations of PRD formulas, written to follow the PRD's pinned
evaluation and rounding order exactly, so a test can assert a computed field
against an independently derived figure instead of a hand-copied literal.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from test_helpers.constants import (
    BASE_PLATFORM_FEE_CENTS,
    COMPLETENESS_WEIGHT,
    DUPLICATE_WEIGHT,
    GRADE_A_FLOOR,
    GRADE_B_FLOOR,
    GRADE_C_FLOOR,
    PENALTY_POINTS_BY_GRADE,
    QUALITY_MULTIPLIER_BY_GRADE,
    REJECTION_WEIGHT,
    TIER_1_RATE_CENTS,
    TIER_1_UNIT_CAP,
    TIER_2_CUMULATIVE_CAP,
    TIER_2_RATE_CENTS,
    TIER_2_UNIT_SPAN,
    TIER_3_RATE_CENTS,
    TIMELINESS_STEP_60_MAX_SECONDS,
    TIMELINESS_STEP_85_MAX_SECONDS,
    TIMELINESS_STEP_100_MAX_SECONDS,
    TIMELINESS_WEIGHT,
)

# ----------------------------------------------------------------------
# Rounding
# ----------------------------------------------------------------------

def round_half_up(value: float, places: int) -> float:
    """Round half up to `places` decimals, the only rounding mode the PRD uses."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_to_int(value: float) -> int:
    """Round half up to a whole cent."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------
# Common resource properties
# ----------------------------------------------------------------------

FULL_QUARTET_ENTITIES = (
    "Participant",
    "ConformanceTest",
    "ConsentPolicy",
    "MatchThresholdConfig",
    "PatientRecord",
    "IdentityCluster",
    "MatchLink",
    "ConsentDirective",
    "BreakGlassAccess",
    "NotificationSubscription",
    "DataFeed",
    "ParticipationInvoice",
)

IMMUTABLE_ENTITIES = ("RecordLocatorQuery", "AccessAuditEntry", "FeedQualitySample")


def assert_uuid_id(entity: Dict[str, Any]) -> None:
    """`id` is a UUID with no type prefix of any kind."""
    assert "id" in entity, f"entity is missing id: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"


def assert_created_at(entity: Dict[str, Any]) -> None:
    """`created_at` is ISO 8601 UTC with exactly three fractional digits."""
    assert "created_at" in entity, f"entity is missing created_at: {entity}"
    created_at = entity["created_at"]
    assert is_iso8601_timestamp(created_at), f"created_at is not ISO 8601: {created_at!r}"
    assert created_at.endswith("Z"), f"created_at is not UTC-suffixed: {created_at!r}"
    fractional = created_at[:-1].split(".")
    assert len(fractional) == 2 and len(fractional[1]) == 3, (
        f"created_at must carry exactly three fractional digits: {created_at!r}"
    )


def assert_full_quartet(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """The addressed entity carries id, created_at, updated_at and version."""
    assert_uuid_id(entity)
    assert_created_at(entity)
    assert "updated_at" in entity, f"entity is missing updated_at: {sorted(entity)}"
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not ISO 8601: {entity['updated_at']!r}"
    )
    assert "version" in entity, f"entity is missing version: {sorted(entity)}"
    assert isinstance(entity["version"], int), f"version must be an integer: {entity['version']!r}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_shape(entity: Dict[str, Any]) -> None:
    """An immutable family carries only id and created_at: both other keys are absent."""
    assert_uuid_id(entity)
    assert_created_at(entity)
    assert "updated_at" not in entity, (
        f"updated_at must be absent from an immutable resource: {sorted(entity)}"
    )
    assert "version" not in entity, (
        f"version must be absent from an immutable resource: {sorted(entity)}"
    )


def assert_version_bumped_by_one(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Every mutation, including one a cascade caused, bumps version by exactly 1."""
    assert after["version"] == before["version"] + 1, (
        f"version moved {before['version']} -> {after['version']}, expected +1"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A row a request did not mutate keeps its version."""
    assert after["version"] == before["version"], (
        f"version moved {before['version']} -> {after['version']}, expected no change"
    )


def assert_updated_at_advanced_to(entity: Dict[str, Any], clock: str) -> None:
    """`updated_at` is refreshed to the logical clock on every mutation."""
    assert entity["updated_at"].startswith(clock[:19]), (
        f"updated_at {entity['updated_at']!r} was not refreshed to the clock {clock!r}"
    )


# ----------------------------------------------------------------------
# Ordering
# ----------------------------------------------------------------------

def assert_ascending_created_at(rows: Sequence[Dict[str, Any]]) -> None:
    """List reads are returned in ascending `created_at` order."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in ascending created_at order: {stamps}"


def assert_id_order(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """The rows appear in exactly this order, by id."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"expected id order {list(expected_ids)}, got {actual}"


# ----------------------------------------------------------------------
# System-wide invariants
# ----------------------------------------------------------------------

def assert_membership_invariant(
    clusters: Iterable[Dict[str, Any]], records: Iterable[Dict[str, Any]]
) -> None:
    """SUM(member_record_count) over ACTIVE clusters equals COUNT(CLUSTERED records)."""
    counted = sum(
        cluster["member_record_count"] for cluster in clusters if cluster["status"] == "ACTIVE"
    )
    clustered = sum(1 for record in records if record["match_state"] == "CLUSTERED")
    assert counted == clustered, (
        f"membership conservation broken: ACTIVE clusters count {counted} members "
        f"but {clustered} records are CLUSTERED"
    )


def assert_outstanding_balance_invariant(
    participant: Dict[str, Any], invoices: Iterable[Dict[str, Any]]
) -> None:
    """outstanding_balance_cents equals SUM(total_cents) over ISSUED and DELINQUENT."""
    expected = sum(
        invoice["total_cents"]
        for invoice in invoices
        if invoice["status"] in ("ISSUED", "DELINQUENT")
    )
    assert participant["outstanding_balance_cents"] == expected, (
        f"outstanding_balance_cents is {participant['outstanding_balance_cents']} "
        f"but the ISSUED/DELINQUENT invoices sum to {expected}"
    )


# ----------------------------------------------------------------------
# Reference calculators: identity matching
# ----------------------------------------------------------------------

FUZZY_FIELDS = ("family_name", "given_name", "postal_code", "phone_digits")
SCORED_FIELDS = (
    "family_name",
    "given_name",
    "birth_date",
    "ssn_last4",
    "postal_code",
    "phone_digits",
)


def _normalize(field: str, value: Optional[str]) -> Optional[str]:
    """Text is trimmed and lowercased; digit-bearing values keep only digits."""
    if value is None:
        return None
    if field in ("ssn_last4", "phone_digits"):
        return "".join(character for character in str(value) if character.isdigit())
    return str(value).strip().lower()


def field_agreement(
    field: str, left: Optional[str], right: Optional[str], partial_credit_factor: float
) -> float:
    """One of three values: 0, 1, or the partial credit factor for a fuzzy field."""
    left_normalized = _normalize(field, left)
    right_normalized = _normalize(field, right)
    if left_normalized is None or right_normalized is None:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    if field in FUZZY_FIELDS and left_normalized[:3] == right_normalized[:3]:
        return float(partial_credit_factor)
    return 0.0


def expected_probabilistic_score(
    agreements: Dict[str, float], weights: Dict[str, float]
) -> float:
    """Weighted total, rounded; then the birth-date cap, then the floor, then rounded."""
    raw = sum(weights[f"weight_{field}"] * agreements[field] for field in SCORED_FIELDS)
    score = round_half_up(raw, 4)
    if agreements["birth_date"] == 0:
        score = min(score, 0.6000)
    if agreements["ssn_last4"] == 1 and agreements["family_name"] == 1:
        score = max(score, 0.8000)
    return round_half_up(score, 4)


def expected_deterministic_score(agreements: Dict[str, float]) -> float:
    """Exactly 1.0000 when either conjunction of exact matches holds, else 0.0000."""
    if agreements["ssn_last4"] == 1 and agreements["birth_date"] == 1:
        return 1.0000
    if all(
        agreements[field] == 1
        for field in ("family_name", "given_name", "birth_date", "postal_code")
    ):
        return 1.0000
    return 0.0000


def expected_completeness_score(record_payload: Dict[str, Any]) -> int:
    """The count of non-null values among the six counted demographic fields."""
    return sum(
        1
        for field in (
            "given_name",
            "family_name",
            "birth_date",
            "ssn_last4",
            "postal_code",
            "phone_digits",
        )
        if record_payload.get(field) is not None
    )


# ----------------------------------------------------------------------
# Reference calculators: conformance results
# ----------------------------------------------------------------------

def expected_pass_rate(assertions_passed: int, assertions_total: int) -> float:
    """assertions_passed divided by assertions_total, rounded to four places."""
    return round_half_up(assertions_passed / assertions_total, 4)


# ----------------------------------------------------------------------
# Reference calculators: feed quality and the scorecard
# ----------------------------------------------------------------------

def expected_reject_rate(messages_rejected: int, messages_received: int) -> float:
    """Rejected over max(1, received), rounded to four places."""
    return round_half_up(messages_rejected / max(1, messages_received), 4)


def expected_timeliness_component(average_p95_seconds: float) -> int:
    """A step function on the average p95 lag, not a ratio."""
    if average_p95_seconds <= TIMELINESS_STEP_100_MAX_SECONDS:
        return 100
    if average_p95_seconds <= TIMELINESS_STEP_85_MAX_SECONDS:
        return 85
    if average_p95_seconds <= TIMELINESS_STEP_60_MAX_SECONDS:
        return 60
    return 30


def grade_for(score: float) -> str:
    """The four bands: A at 92 or above, B at 84, C at 70, D below that."""
    if score >= GRADE_A_FLOOR:
        return "A"
    if score >= GRADE_B_FLOOR:
        return "B"
    if score >= GRADE_C_FLOOR:
        return "C"
    return "D"


def expected_scorecard(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The whole scorecard for an already-windowed, already-truncated sample set.

    Follows the PRD's pinned order: provisional grade from the base score, penalty
    from the provisional grade alone, quality score after the deduction, final
    grade from the quality score.
    """
    if not samples:
        return {
            "samples_counted": 0,
            "completeness_component": 0,
            "rejection_component": 0,
            "duplicate_component": 0,
            "timeliness_component": 0,
            "average_p95_seconds": 0,
            "base_quality_score": 0,
            "provisional_grade": "UNGRADED",
            "penalty_points": 0,
            "quality_score": None,
            "grade": "UNGRADED",
        }
    received = sum(sample["messages_received"] for sample in samples)
    denominator = max(1, received)
    completeness = 100 * (
        1 - sum(sample["required_fields_missing_count"] for sample in samples) / denominator
    )
    rejection = 100 * (
        1 - sum(sample["messages_rejected"] for sample in samples) / denominator
    )
    duplicate = 100 * (1 - sum(sample["duplicate_count"] for sample in samples) / denominator)
    average_p95 = round_half_up(
        sum(sample["timeliness_p95_seconds"] for sample in samples) / len(samples), 2
    )
    timeliness = expected_timeliness_component(average_p95)
    base = round_half_up(
        COMPLETENESS_WEIGHT * completeness
        + REJECTION_WEIGHT * rejection
        + DUPLICATE_WEIGHT * duplicate
        + TIMELINESS_WEIGHT * timeliness,
        2,
    )
    provisional = grade_for(base)
    penalty = PENALTY_POINTS_BY_GRADE[provisional]
    quality_score = round_half_up(base - penalty, 2)
    return {
        "samples_counted": len(samples),
        "completeness_component": completeness,
        "rejection_component": rejection,
        "duplicate_component": duplicate,
        "timeliness_component": timeliness,
        "average_p95_seconds": average_p95,
        "base_quality_score": base,
        "provisional_grade": provisional,
        "penalty_points": penalty,
        "quality_score": quality_score,
        "grade": grade_for(quality_score),
    }


# ----------------------------------------------------------------------
# Reference calculators: the participation fee
# ----------------------------------------------------------------------

def expected_tier_quantities(billable_volume: int) -> Dict[str, int]:
    """The ladder: 24,750 then 75,000 more to a cumulative 99,750, then the rest."""
    tier_one = min(billable_volume, TIER_1_UNIT_CAP)
    tier_two = max(0, min(TIER_2_UNIT_SPAN, billable_volume - TIER_1_UNIT_CAP))
    tier_three = max(0, billable_volume - TIER_2_CUMULATIVE_CAP)
    return {"TIER_1": tier_one, "TIER_2": tier_two, "TIER_3": tier_three}


def expected_tier_charge_breakdown(billable_volume: int) -> Dict[str, int]:
    """Each tier charge is rounded to a whole cent individually, before any sum."""
    quantities = expected_tier_quantities(billable_volume)
    return {
        "TIER_1": round_half_up_to_int(quantities["TIER_1"] * TIER_1_RATE_CENTS),
        "TIER_2": round_half_up_to_int(quantities["TIER_2"] * TIER_2_RATE_CENTS),
        "TIER_3": round_half_up_to_int(quantities["TIER_3"] * TIER_3_RATE_CENTS),
    }


def expected_volume_fee_cents(billable_volume: int) -> int:
    """The sum of the three individually rounded tier charges."""
    return sum(expected_tier_charge_breakdown(billable_volume).values())


def expected_fee_tier(billable_volume: int) -> str:
    """TIER_3 when tier three is non-empty, else TIER_2, else TIER_1."""
    quantities = expected_tier_quantities(billable_volume)
    if quantities["TIER_3"] > 0:
        return "TIER_3"
    if quantities["TIER_2"] > 0:
        return "TIER_2"
    return "TIER_1"


def expected_total_cents(billable_volume: int, quality_multiplier: float) -> int:
    """Base plus volume fee, multiplied, then rounded to a whole cent exactly once."""
    subtotal = BASE_PLATFORM_FEE_CENTS + expected_volume_fee_cents(billable_volume)
    return round_half_up_to_int(subtotal * quality_multiplier)


def expected_provisional_volume(declared_annual_patient_volume: int) -> int:
    """The declared annual volume divided by twelve and rounded up to a whole unit."""
    return math.ceil(declared_annual_patient_volume / 12)


def multiplier_for_grade(grade: str) -> float:
    """A 0.95, B 1.00, C 1.08, D 1.20, UNGRADED 1.00."""
    return QUALITY_MULTIPLIER_BY_GRADE[grade]
