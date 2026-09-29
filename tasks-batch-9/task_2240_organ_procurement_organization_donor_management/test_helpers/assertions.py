"""Domain assertion helpers and reference implementations of the derived values.

The reference calculators here reproduce the arithmetic the PRD narrates, so a
test can assert an expected figure without hard-coding the same sum twice.  They
follow the specification exactly: whole-minute truncation downward, half-up
rounding to two decimal places, and inclusive thresholds at the stated floor.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ABSOLUTE_MARKERS,
    BASE_PREP_MINUTES,
    CRASH_PREP_MINUTES,
    EXPEDITED_PREP_MINUTES,
    EXPEDITED_TIER_FLOOR,
    FACTOR_WEIGHTS,
    IMPUTATION_FRACTION,
    NOK_RANK,
    PRESSOR_PENALTY_CAP,
    PRESSOR_PENALTY_PER_AGENT,
    RELIABILITY_MULTIPLIER,
    RISK_TIER_THRESHOLD,
    SCORE_CAP,
    SODIUM_NORMAL_HIGH,
    SODIUM_NORMAL_LOW,
    STANDARD_PREP_MINUTES,
    STANDARD_TIER_FLOOR,
    VARIANT_INTERVIEW_BASED,
    VARIANT_RECORDS_ONLY,
)

WEIGHT_OF = {name: Decimal(str(weight)) for name, weight in FACTOR_WEIGHTS}
CANONICAL_ORDER = [name for name, _ in FACTOR_WEIGHTS]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating both ``Z`` and an offset."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def whole_minutes_between(start: str, end: str) -> int:
    """Whole minutes from ``start`` to ``end``, discarding the fraction downward."""
    seconds = (parse_instant(end) - parse_instant(start)).total_seconds()
    return int(seconds // 60)


def shift_minutes(instant: str, minutes: int) -> str:
    """Return ``instant`` moved by ``minutes``, rendered back as a ``Z`` instant."""
    moved = parse_instant(instant) + timedelta(minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two instants by value, ignoring fractional-digit rendering."""
    if left is None or right is None:
        return left is right
    return parse_instant(left) == parse_instant(right)


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    assert actual is not None, "expected an instant, found null"
    assert instants_equal(actual, expected), f"expected {expected}, found {actual}"


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up_2dp(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def assert_two_decimal_value(actual: Any, expected: float) -> None:
    """A ratio or score is carried to exactly two decimal places."""
    assert actual is not None, "expected a numeric value, found null"
    assert float(actual) == pytest.approx(expected, abs=0.005), (
        f"expected {expected:.2f}, found {actual}"
    )


# ---------------------------------------------------------------------------
# Identity shape
# ---------------------------------------------------------------------------
def assert_managed_identity(resource: Dict[str, Any]) -> None:
    """A managed aggregate carries the full quartet of identity fields."""
    assert is_valid_uuid(resource["id"]), f"id is not a bare UUID: {resource['id']}"
    assert is_iso8601_timestamp(resource["created_at"])
    assert is_iso8601_timestamp(resource["updated_at"])
    assert isinstance(resource["version"], int) and resource["version"] >= 1


def assert_append_only_identity(record: Dict[str, Any]) -> None:
    """An append-only record carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"])
    assert "updated_at" not in record, "updated_at must be absent, not null"
    assert "version" not in record, "version must be absent, not null"


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """An error body reports only ``error_id`` and ``message`` inside ``data``."""
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "an error envelope's meta carries only the request id and timestamp"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


# ---------------------------------------------------------------------------
# Behavioral risk score
# ---------------------------------------------------------------------------
def expected_risk_score(
    risk_factors: Sequence[str],
    informant_reliability: str,
    unresolved_factors: Sequence[str] = (),
) -> Decimal:
    """Reproduce the scoring: round each contribution first, then add them."""
    multiplier = Decimal(str(RELIABILITY_MULTIPLIER[informant_reliability]))
    records_only = informant_reliability == "MEDICAL_RECORD_ONLY"

    total = Decimal("0.00")
    for name in CANONICAL_ORDER:
        if name in set(risk_factors):
            total += round_half_up_2dp(WEIGHT_OF[name] * multiplier)
    if records_only:
        for name in CANONICAL_ORDER:
            if name in set(unresolved_factors):
                contribution = (
                    WEIGHT_OF[name] * Decimal(str(IMPUTATION_FRACTION)) * multiplier
                )
                total += round_half_up_2dp(contribution)

    capped = min(total, Decimal(str(SCORE_CAP)))
    return round_half_up_2dp(capped)


def expected_risk_tier(score: Decimal) -> str:
    return "INCREASED_RISK" if score >= Decimal(str(RISK_TIER_THRESHOLD)) else "STANDARD"


def expected_risk_variant(informant_reliability: str) -> str:
    return (
        VARIANT_RECORDS_ONLY
        if informant_reliability == "MEDICAL_RECORD_ONLY"
        else VARIANT_INTERVIEW_BASED
    )


# ---------------------------------------------------------------------------
# Viability index
# ---------------------------------------------------------------------------
def expected_viability_index(
    map_mmhg: int,
    pao2_fio2_ratio: int,
    sodium: int,
    urine_output_ml_per_kg_hr: float,
    pressor_count: int,
    cardiac_arrest: bool = False,
) -> int:
    """The four-step index: oxygenation, haemodynamics, metabolic, then clamp."""
    if cardiac_arrest:
        return 0

    if pao2_fio2_ratio >= 300:
        oxygenation = 40
    elif pao2_fio2_ratio >= 200:
        oxygenation = 30
    elif pao2_fio2_ratio >= 100:
        oxygenation = 15
    else:
        oxygenation = 0

    if map_mmhg >= 70:
        base = 35
    elif map_mmhg >= 60:
        base = 25
    elif map_mmhg >= 50:
        base = 10
    else:
        base = 0
    penalty = min(PRESSOR_PENALTY_CAP, PRESSOR_PENALTY_PER_AGENT * pressor_count)
    haemodynamic = max(0, base - penalty)

    metabolic = 15 if SODIUM_NORMAL_LOW <= sodium <= SODIUM_NORMAL_HIGH else 5
    if urine_output_ml_per_kg_hr >= 1.0:
        metabolic += 10
    elif urine_output_ml_per_kg_hr >= 0.5:
        metabolic += 5

    return max(0, min(100, oxygenation + haemodynamic + metabolic))


def expected_dmg_bundle_met(
    map_mmhg: int,
    pao2_fio2_ratio: int,
    sodium: int,
    urine_output_ml_per_kg_hr: float,
    pressor_count: int,
) -> bool:
    """All five bounds must hold simultaneously."""
    return (
        map_mmhg >= 60
        and pao2_fio2_ratio >= 300
        and SODIUM_NORMAL_LOW <= sodium <= SODIUM_NORMAL_HIGH
        and urine_output_ml_per_kg_hr >= 0.5
        and pressor_count <= 1
    )


def expected_physiologic_status(index: int, cardiac_arrest: bool = False) -> str:
    if cardiac_arrest:
        return "LOST"
    if index >= 70:
        return "OPTIMIZED"
    if index >= 40:
        return "STABILIZING"
    return "DECOMPENSATING"


# ---------------------------------------------------------------------------
# Cold ischemic projection
# ---------------------------------------------------------------------------
def expected_cold_ischemic_projection(
    cit_limit_minutes: int,
    cross_clamp_at: str,
    transport_depart_at: str,
    transport_arrive_at: str,
) -> Dict[str, int]:
    """The pinned single pass: provisional margin selects the prep tier once."""
    elapsed = whole_minutes_between(cross_clamp_at, transport_depart_at)
    transit = whole_minutes_between(transport_depart_at, transport_arrive_at)
    provisional = cit_limit_minutes - elapsed - transit - BASE_PREP_MINUTES
    if provisional >= STANDARD_TIER_FLOOR:
        prep = STANDARD_PREP_MINUTES
    elif provisional >= EXPEDITED_TIER_FLOOR:
        prep = EXPEDITED_PREP_MINUTES
    else:
        prep = CRASH_PREP_MINUTES
    projected = elapsed + transit + prep
    return {
        "elapsed_minutes": elapsed,
        "transit_minutes": transit,
        "provisional_margin_minutes": provisional,
        "implant_prep_minutes": prep,
        "projected_cold_ischemic_minutes": projected,
        "projected_cit_margin_minutes": cit_limit_minutes - projected,
    }


# ---------------------------------------------------------------------------
# Serology
# ---------------------------------------------------------------------------
def expected_absolute_contraindication_marker(
    marker: str, result: str, nat_confirmed: bool
) -> bool:
    """All three conditions must hold together."""
    return marker in ABSOLUTE_MARKERS and result == "POSITIVE" and nat_confirmed


# ---------------------------------------------------------------------------
# Next of kin
# ---------------------------------------------------------------------------
def expected_nok_rank(relationship: str) -> int:
    return NOK_RANK[relationship]


# ---------------------------------------------------------------------------
# Conserved quantities
# ---------------------------------------------------------------------------
def assert_slot_conservation(run: Dict[str, Any]) -> None:
    """For each match run, pending plus free always equals the primary slots."""
    assert run["pending_offer_count"] + run["slots_free"] == run["primary_offer_slots"], (
        "pending_offer_count + slots_free must equal primary_offer_slots, found "
        f"{run['pending_offer_count']} + {run['slots_free']} != "
        f"{run['primary_offer_slots']}"
    )


def assert_team_ledger(
    team: Dict[str, Any], booked_or_minutes: int, scheduled_operation_count: int
) -> None:
    """The OR-minutes ledger and the scheduled count must both reconcile."""
    assert team["booked_or_minutes"] == booked_or_minutes, (
        f"expected booked_or_minutes {booked_or_minutes}, "
        f"found {team['booked_or_minutes']}"
    )
    assert team["scheduled_operation_count"] == scheduled_operation_count, (
        f"expected scheduled_operation_count {scheduled_operation_count}, "
        f"found {team['scheduled_operation_count']}"
    )


def assert_case_dimensions(
    case: Dict[str, Any],
    physiologic_status: Optional[str] = None,
    allocation_status: Optional[str] = None,
    case_posture: Optional[str] = None,
    closed_reason: Any = "__unset__",
) -> None:
    """Assert any subset of the two dimensions plus the derived posture."""
    if physiologic_status is not None:
        assert case["physiologic_status"] == physiologic_status
    if allocation_status is not None:
        assert case["allocation_status"] == allocation_status
    if case_posture is not None:
        assert case["case_posture"] == case_posture
    if closed_reason != "__unset__":
        assert case["closed_reason"] == closed_reason


def assert_organ_state(
    organ: Dict[str, Any],
    status: Optional[str] = None,
    viability_hold: Optional[bool] = None,
    accepted_offer_id: Any = "__unset__",
    nontransplantable_reason: Any = "__unset__",
) -> None:
    if status is not None:
        assert organ["status"] == status
    if viability_hold is not None:
        assert organ["viability_hold"] is viability_hold
    if accepted_offer_id != "__unset__":
        assert organ["accepted_offer_id"] == accepted_offer_id
    if nontransplantable_reason != "__unset__":
        assert organ["nontransplantable_reason"] == nontransplantable_reason


def assert_offer_state(
    offer: Dict[str, Any],
    status: Optional[str] = None,
    bypass_reason: Any = "__unset__",
    decline_reason: Any = "__unset__",
) -> None:
    if status is not None:
        assert offer["status"] == status
    if bypass_reason != "__unset__":
        assert offer["bypass_reason"] == bypass_reason
    if decline_reason != "__unset__":
        assert offer["decline_reason"] == decline_reason


def offers_by_position(offers: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Offer listings arrive ordered by sequence position ascending."""
    return sorted(offers, key=lambda o: o["sequence_position"])


def find_offer(offers: Iterable[Dict[str, Any]], sequence_position: int) -> Dict[str, Any]:
    for offer in offers:
        if offer["sequence_position"] == sequence_position:
            return offer
    raise AssertionError(f"no offer at sequence position {sequence_position}")
