"""Domain assertions for the Poultry Hatchery & Breeder Flock API.

Two families live here: per-entity shape assertions that check the common audit
surface of PRD 2.5 alongside a record's own required fields, and invariant
checkers for the two exact counting equalities of PRD 2.10.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BOX_SIZE,
    DEGREE_HOUR_TOL,
    FACTOR_TOL,
    ONE_DP_TOL,
    PCT_TOL,
)
from .types import (
    AssignmentStatus,
    ChickBatchStatus,
    ItemStatus,
)

# ---------------------------------------------------------------------------
# Instant comparisons (PRD 2.5)
# ---------------------------------------------------------------------------

#: An ISO 8601 UTC instant, with or without fractional seconds.
_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _parse_instant(value: str) -> Optional[datetime]:
    """Parse an ISO 8601 UTC instant, or return ``None`` if it is not one."""
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def instants_equal(got: Any, want: Any) -> bool:
    """Two ISO 8601 UTC instants denote the same moment.

    PRD 2.5 renders server timestamps with three fractional digits, so an
    instant written in a test as ``2026-08-01T18:00:00Z`` legitimately comes
    back as ``2026-08-01T18:00:00.000Z``; both spellings denote the same
    instant and both are accepted.
    """
    left, right = _parse_instant(got), _parse_instant(want)
    if left is None or right is None:
        return False
    return left == right


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """An instant field equals ``expected``, ignoring fractional-digit spelling."""
    assert instants_equal(actual, expected), (
        f"{label}: expected the instant {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Scale-aware numeric comparisons (PRD 2.6)
# ---------------------------------------------------------------------------


def assert_one_dp(actual: Any, expected: float, label: str = "value") -> None:
    """One-decimal-place quantity (production_rate_pct, photoperiod, feed)."""
    assert actual == pytest.approx(expected, abs=ONE_DP_TOL), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Two-decimal-place quantity (percentages, ages, deviations, scores)."""
    assert actual == pytest.approx(expected, abs=PCT_TOL), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_three_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Three-decimal-place quantity (degree-hours)."""
    assert actual == pytest.approx(expected, abs=DEGREE_HOUR_TOL), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Four-decimal-place quantity (the two factors and weighted_age_days)."""
    assert actual == pytest.approx(expected, abs=FACTOR_TOL), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common audit surface (PRD 2.5)
# ---------------------------------------------------------------------------


def assert_common_fields(record: Dict[str, Any], entity: str = "record") -> None:
    """Every record but the environment reading carries id/created_at/updated_at/version."""
    assert is_valid_uuid(record.get("id")), f"{entity}.id is not a UUID: {record.get('id')}"
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"{entity}.created_at is not an ISO 8601 timestamp: {record.get('created_at')}"
    )
    assert is_iso8601_timestamp(record.get("updated_at")), (
        f"{entity}.updated_at is not an ISO 8601 timestamp: {record.get('updated_at')}"
    )
    assert isinstance(record.get("version"), int), (
        f"{entity}.version is not an integer: {record.get('version')}"
    )
    assert record["version"] >= 1, f"{entity}.version must start at 1"


def assert_freshly_created(record: Dict[str, Any], entity: str = "record") -> None:
    """A brand new record is at version 1 with created_at equal to updated_at."""
    assert_common_fields(record, entity)
    assert record["version"] == 1, f"{entity}.version on creation must be 1"
    assert record["created_at"] == record["updated_at"], (
        f"{entity}.created_at and updated_at must match on creation"
    )


def assert_stamped_at(
    record: Dict[str, Any],
    field: str,
    instant: str,
    entity: str = "record",
) -> None:
    """A server-stamped audit instant equals the logical clock reading.

    PRD 2.5 renders ``created_at`` and ``updated_at`` with three fractional
    digits, so an instant written as ``2026-08-01T12:00:00Z`` may legitimately
    come back as ``2026-08-01T12:00:00.000Z``; both spellings denote the same
    instant and both are accepted here.
    """
    value = record.get(field)
    assert isinstance(value, str), (
        f"{entity}.{field} must be an ISO 8601 instant, got {value!r}"
    )
    trimmed = instant[:-1] if instant.endswith("Z") else instant
    assert value == instant or value.startswith(trimmed), (
        f"{entity}.{field}: expected the logical clock instant {instant}, got {value}"
    )


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """The error envelope of PRD 2.2: response_type error plus a readable message."""
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')}"
    )
    data = body.get("data") or {}
    assert data.get("error_id"), "error body must carry an error_id"
    assert isinstance(data.get("message"), str) and data["message"].strip(), (
        "error body must carry a non-empty human-readable message"
    )
    meta = body.get("meta") or {}
    assert str(meta.get("api_request_id", "")).startswith("req_"), (
        "meta.api_request_id must start with req_"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        "meta.api_request_timestamp must be an ISO 8601 timestamp"
    )


def assert_object_envelope(body: Dict[str, Any]) -> None:
    """The single-resource success envelope of PRD 2.2."""
    assert body.get("response_type") == "object", (
        f"expected response_type 'object', got {body.get('response_type')}"
    )
    meta = body.get("meta") or {}
    assert str(meta.get("api_request_id", "")).startswith("req_"), (
        "meta.api_request_id must start with req_"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        "meta.api_request_timestamp must be an ISO 8601 timestamp"
    )


def assert_array_envelope(body: Dict[str, Any]) -> None:
    """The list success envelope of PRD 2.2 and 2.3."""
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')}"
    )
    meta = body.get("meta") or {}
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list meta must carry {key}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_flock_program(program: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(program, "FlockProgram")
    for field in ("code", "breed", "stimulation_week", "lighting_steps", "feed_steps", "retired"):
        assert field in program, f"FlockProgram must expose {field}"
    _match(program, expected, "FlockProgram")


def assert_incubation_profile(profile: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(profile, "IncubationProfile")
    for field in ("code", "breed", "transfer_hours", "total_hours", "stages", "retired"):
        assert field in profile, f"IncubationProfile must expose {field}"
    _match(profile, expected, "IncubationProfile")


def assert_incubation_unit(unit: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(unit, "IncubationUnit")
    for field in (
        "code",
        "unit_type",
        "capacity_eggs",
        "sanitation_status",
        "occupancy_status",
    ):
        assert field in unit, f"IncubationUnit must expose {field}"
    _match(unit, expected, "IncubationUnit")


def assert_breeder_flock(flock: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(flock, "BreederFlock")
    for field in (
        "code",
        "program_id",
        "breed",
        "house_code",
        "hatch_date",
        "placed_at",
        "hen_count",
        "status",
        "age_weeks",
        "settable_forecast",
        "corrective_action_count",
        "late_pull_count",
    ):
        assert field in flock, f"BreederFlock must expose {field}"
    _match(flock, expected, "BreederFlock")


def assert_forecast_chain(
    flock: Dict[str, Any],
    age_weeks: Optional[int] = None,
    photoperiod_hours: Optional[float] = None,
    feed_grams_per_hen_day: Optional[float] = None,
    production_rate_pct: Optional[float] = None,
    lighting_factor: Optional[float] = None,
    nutrition_factor: Optional[float] = None,
    settable_forecast: Optional[int] = None,
) -> None:
    """Check the seven fields of the forecast chain at their declared scales."""
    if age_weeks is not None:
        assert flock["age_weeks"] == age_weeks, (
            f"age_weeks: expected {age_weeks}, got {flock['age_weeks']}"
        )
    if photoperiod_hours is not None:
        assert_one_dp(flock["photoperiod_hours"], photoperiod_hours, "photoperiod_hours")
    if feed_grams_per_hen_day is not None:
        assert_one_dp(
            flock["feed_grams_per_hen_day"],
            feed_grams_per_hen_day,
            "feed_grams_per_hen_day",
        )
    if production_rate_pct is not None:
        assert_one_dp(flock["production_rate_pct"], production_rate_pct, "production_rate_pct")
    if lighting_factor is not None:
        assert_four_dp(flock["lighting_factor"], lighting_factor, "lighting_factor")
    if nutrition_factor is not None:
        assert_four_dp(flock["nutrition_factor"], nutrition_factor, "nutrition_factor")
    if settable_forecast is not None:
        assert flock["settable_forecast"] == settable_forecast, (
            f"settable_forecast: expected {settable_forecast}, got {flock['settable_forecast']}"
        )


def assert_egg_lot(lot: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(lot, "EggLot")
    for field in (
        "flock_id",
        "collected_at",
        "collected_count",
        "settable_count",
        "eggs_remaining",
        "sanitation_cycle_count",
        "effective_age_days",
        "status",
    ):
        assert field in lot, f"EggLot must expose {field}"
    _match(lot, expected, "EggLot")


def assert_setter_load(load: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(load, "SetterLoad")
    for field in (
        "unit_id",
        "profile_id",
        "planned_set_at",
        "status",
        "environment_status",
        "total_eggs_set",
        "deviation_degree_hours",
    ):
        assert field in load, f"SetterLoad must expose {field}"
    _match(load, expected, "SetterLoad")


def assert_hatch_window(
    record: Dict[str, Any],
    planned_pull_at: str,
    pull_window_start_at: str,
    pull_window_end_at: str,
) -> None:
    """The nominal pull instant and the symmetric six-hour window around it."""
    assert_instant(record["planned_pull_at"], planned_pull_at, "planned_pull_at")
    assert_instant(
        record["pull_window_start_at"], pull_window_start_at, "pull_window_start_at"
    )
    assert_instant(record["pull_window_end_at"], pull_window_end_at, "pull_window_end_at")


def assert_setter_load_item(item: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(item, "SetterLoadItem")
    for field in (
        "setter_load_id",
        "egg_lot_id",
        "eggs_taken",
        "effective_age_days_at_set",
        "item_status",
    ):
        assert field in item, f"SetterLoadItem must expose {field}"
    _match(item, expected, "SetterLoadItem")


#: The complete field surface of an append-only probe sample (PRD 2.5, 3.5).
ENVIRONMENT_READING_FIELDS = {
    "id",
    "created_at",
    "setter_load_id",
    "recorded_at",
    "temp_c",
    "humidity_pct",
    "elapsed_hours",
    "target_temp_c",
    "abs_deviation_c",
    "segment_degree_hours",
}


def assert_environment_reading(reading: Dict[str, Any], **expected: Any) -> None:
    """An environment reading carries only ``id`` and ``created_at`` of the audit
    surface: no ``updated_at`` and no ``version`` at all."""
    assert is_valid_uuid(reading.get("id")), "EnvironmentReading.id is not a UUID"
    assert is_iso8601_timestamp(reading.get("created_at")), (
        "EnvironmentReading.created_at is not an ISO 8601 timestamp"
    )
    assert "updated_at" not in reading, (
        "EnvironmentReading must not carry updated_at"
    )
    assert "version" not in reading, "EnvironmentReading must not carry version"
    for field in ENVIRONMENT_READING_FIELDS:
        assert field in reading, f"EnvironmentReading must expose {field}"
    _match(reading, expected, "EnvironmentReading")


def assert_hatcher_load(load: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(load, "HatcherLoad")
    for field in (
        "setter_load_id",
        "unit_id",
        "status",
        "transferred_at",
        "eggs_transferred",
        "planned_pull_at",
        "pull_window_start_at",
        "pull_window_end_at",
        "inherited_degree_hours",
        "quality_flag",
    ):
        assert field in load, f"HatcherLoad must expose {field}"
    _match(load, expected, "HatcherLoad")


def assert_chick_batch(batch: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(batch, "ChickBatch")
    for field in (
        "hatcher_load_id",
        "primary_flock_id",
        "breed",
        "hatched_count",
        "quality_score_provisional",
        "status",
    ):
        assert field in batch, f"ChickBatch must expose {field}"
    _match(batch, expected, "ChickBatch")


def assert_grower_farm(farm: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(farm, "GrowerFarm")
    for field in ("code", "operator_user_id", "capacity_chicks", "biosecurity_status"):
        assert field in farm, f"GrowerFarm must expose {field}"
    _match(farm, expected, "GrowerFarm")


def assert_placement_order(order: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(order, "GrowerPlacementOrder")
    for field in (
        "farm_id",
        "requested_breed",
        "requested_placement_date",
        "requested_chicks",
        "allocated_chicks",
        "remaining_need",
        "status",
    ):
        assert field in order, f"GrowerPlacementOrder must expose {field}"
    assert order["remaining_need"] == order["requested_chicks"] - order["allocated_chicks"], (
        "remaining_need is always requested_chicks less allocated_chicks"
    )
    _match(order, expected, "GrowerPlacementOrder")


def assert_delivery_assignment(assignment: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(assignment, "DeliveryAssignment")
    for field in (
        "chick_batch_id",
        "placement_order_id",
        "chicks_assigned",
        "boxes_assigned",
        "scheduled_delivery_date",
        "status",
    ):
        assert field in assignment, f"DeliveryAssignment must expose {field}"
    assert assignment["chicks_assigned"] == assignment["boxes_assigned"] * BOX_SIZE, (
        "boxes_assigned is chicks_assigned divided by the standard box of 100"
    )
    _match(assignment, expected, "DeliveryAssignment")


def assert_lab_test(test: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(test, "LabTest")
    for field in ("subject_type", "subject_id", "test_code", "collected_at", "status"):
        assert field in test, f"LabTest must expose {field}"
    _match(test, expected, "LabTest")


def assert_corrective_action(action: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(action, "CorrectiveAction")
    for field in (
        "flock_id",
        "trigger_reason",
        "status",
        "verification_round",
        "opened_at",
        "opened_by_user_id",
    ):
        assert field in action, f"CorrectiveAction must expose {field}"
    _match(action, expected, "CorrectiveAction")


# ---------------------------------------------------------------------------
# Conservation invariants (PRD 2.10)
# ---------------------------------------------------------------------------


def assert_egg_conservation(lot: Dict[str, Any], draws: Iterable[Dict[str, Any]]) -> None:
    """settable_count equals eggs_remaining plus the ACTIVE draws' eggs_taken."""
    active = [d for d in draws if d["item_status"] == ItemStatus.ACTIVE.value]
    taken = sum(d["eggs_taken"] for d in active)
    assert lot["settable_count"] == lot["eggs_remaining"] + taken, (
        "egg conservation broken: settable_count "
        f"{lot['settable_count']} != eggs_remaining {lot['eggs_remaining']} "
        f"+ active draws {taken}"
    )


def assert_chick_conservation(
    batch: Dict[str, Any], assignments: Iterable[Dict[str, Any]]
) -> None:
    """saleable_count equals unassigned_chicks plus ASSIGNED/DELIVERED grants."""
    live = [
        a
        for a in assignments
        if a["status"]
        in (AssignmentStatus.ASSIGNED.value, AssignmentStatus.DELIVERED.value)
    ]
    assigned = sum(a["chicks_assigned"] for a in live)
    assert batch["saleable_count"] == batch["unassigned_chicks"] + assigned, (
        "chick conservation broken: saleable_count "
        f"{batch['saleable_count']} != unassigned_chicks "
        f"{batch['unassigned_chicks']} + live assignments {assigned}"
    )


def assert_order_allocation_consistent(
    order: Dict[str, Any], assignments: Iterable[Dict[str, Any]]
) -> None:
    """allocated_chicks is the sum of live grants against this order (PRD 3.8)."""
    live = [
        a
        for a in assignments
        if a["placement_order_id"] == order["id"]
        and a["status"]
        in (AssignmentStatus.ASSIGNED.value, AssignmentStatus.DELIVERED.value)
    ]
    assigned = sum(a["chicks_assigned"] for a in live)
    assert order["allocated_chicks"] == assigned, (
        f"allocated_chicks {order['allocated_chicks']} != live grants {assigned}"
    )


def assert_boxed_batch_pool(batch: Dict[str, Any]) -> None:
    """A freshly boxed batch has its whole saleable pool unassigned (PRD 3.7)."""
    assert batch["status"] == ChickBatchStatus.BOXED.value
    assert batch["unassigned_chicks"] == batch["saleable_count"], (
        "unassigned_chicks is initialised to saleable_count at boxing"
    )
    expected_boxes = -(-batch["saleable_count"] // BOX_SIZE)
    assert batch["box_count"] == expected_boxes, (
        f"box_count: expected ceil(saleable/100) = {expected_boxes}, "
        f"got {batch['box_count']}"
    )


def assert_cull_resolution(batch: Dict[str, Any]) -> None:
    """cull_count is sexing culls plus vaccine culls; saleable is the remainder."""
    assert batch["cull_count"] == batch["sexing_cull_count"] + batch["vaccine_cull_count"], (
        "cull_count is sexing_cull_count plus vaccine_cull_count"
    )
    assert batch["saleable_count"] == batch["hatched_count"] - batch["cull_count"], (
        "saleable_count is hatched_count less cull_count"
    )


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------


def assert_ordered_by(rows: List[Dict[str, Any]], field: str) -> None:
    """Rows are returned in ascending order of ``field``."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows are not ascending by {field}: {values}"


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert [row["id"] for row in rows] == expected_ids, (
        f"expected ids {expected_ids}, got {[row['id'] for row in rows]}"
    )


def _match(record: Dict[str, Any], expected: Dict[str, Any], entity: str) -> None:
    """Compare every supplied keyword against the record, scale-aware for floats."""
    for field, want in expected.items():
        assert field in record, f"{entity} must expose {field}"
        got = record[field]
        if isinstance(want, float) and got is not None:
            assert got == pytest.approx(want, abs=PCT_TOL), (
                f"{entity}.{field}: expected {want}, got {got}"
            )
        elif got != want and _parse_instant(want) is not None:
            # PRD 2.5 renders instants with three fractional digits.
            assert instants_equal(got, want), (
                f"{entity}.{field}: expected the instant {want}, got {got}"
            )
        else:
            assert got == want, f"{entity}.{field}: expected {want}, got {got}"
