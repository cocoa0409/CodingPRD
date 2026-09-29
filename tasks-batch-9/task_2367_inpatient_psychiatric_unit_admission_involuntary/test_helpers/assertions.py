"""Domain assertions for the Inpatient Psychiatric Admission API.

These helpers exist so a test can state a claim once rather than restating the
same envelope, timestamp-shape or derived-counter arithmetic in every case.
Nothing here invents a rule: each helper's docstring names the PRD section whose
sentence it is enforcing.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_errors import CHECK_PRIORITY, ApiErrorId
from .constants import (
    COMPLIANCE_DECIMAL_PLACES,
    OBSERVATION_BILLABLE_STATUSES,
    QUARTER_HOUR_MINUTES,
    expected_effective_available,
    expected_posture,
    parse_instant,
    posture_threshold,
    round_half_up_one_dp,
)

_MILLISECOND_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# Envelope and common fields
# ---------------------------------------------------------------------------


def assert_millisecond_instant(value: Any, label: str = "timestamp") -> None:
    """Timestamps are ISO 8601 UTC with exactly three fractional digits (PRD 2.6)."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert _MILLISECOND_INSTANT.match(value), (
        f"{label} must be ISO 8601 UTC with exactly three fractional digits "
        f"and a trailing Z, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{label} is not a valid instant: {value!r}"


def assert_optional_millisecond_instant(value: Any, label: str = "timestamp") -> None:
    """Allow ``None`` for a not-yet-stamped instant, otherwise check the shape."""
    if value is None:
        return
    assert_millisecond_instant(value, label)


def assert_common_fields(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries id, created_at, updated_at and version (PRD 2.5)."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in record, f"missing common field {field!r} on {record!r}"
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert_millisecond_instant(record["created_at"], "created_at")
    assert_millisecond_instant(record["updated_at"], "updated_at")
    assert isinstance(record["version"], int) and not isinstance(
        record["version"], bool
    ), f"version should be an integer, got {record['version']!r}"
    assert record["version"] >= 1, "version begins at 1 (PRD 2.5)"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_created(response, expected_version: int = 1) -> Dict[str, Any]:
    """A creating operation returns 201 with a fresh resource (PRD 4, 2.5)."""
    data = validate_success(response, 201)
    assert_common_fields(data, expected_version)
    return data


def assert_ok(response) -> Dict[str, Any]:
    """A modifying or reading operation returns 200 (PRD 4)."""
    data = validate_success(response, 200)
    return data


def assert_mutation(response, previous_version: int) -> Dict[str, Any]:
    """A successful mutation returns 200 and advances version by one (PRD 2.5)."""
    data = validate_success(response, 200)
    assert_common_fields(data)
    assert data["version"] == previous_version + 1, (
        "each mutation increases version by exactly one (PRD 2.5): expected "
        f"{previous_version + 1}, got {data['version']}"
    )
    return data


def assert_error(response, error_id: ApiErrorId) -> Dict[str, Any]:
    """Assert the error envelope carries ``error_id`` and its declared status."""
    identifier = error_id.value if isinstance(error_id, ApiErrorId) else error_id
    return validate_error(response, identifier)


def assert_first_failing_check(
    response, expected: ApiErrorId, shadowed: Iterable[ApiErrorId]
) -> Dict[str, Any]:
    """The first failing check terminates the request (PRD 2.9).

    ``shadowed`` names the lower-priority conditions that are also violated by
    the same request; the helper both asserts the reported id and re-checks that
    the priority table really does rank the expected check ahead of them.
    """
    for other in shadowed:
        assert CHECK_PRIORITY[expected] < CHECK_PRIORITY[other], (
            f"{expected.value} is not ranked ahead of {other.value} (PRD 2.9)"
        )
    return assert_error(response, expected)


def assert_page(response, expected_total: Optional[int] = None):
    """Unpack a paginated list envelope and optionally pin its total (PRD 2.3)."""
    items, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}"
        )
    return items, meta


def assert_page_window(
    response, *, limit: int, offset: int, total: int
) -> List[Dict[str, Any]]:
    """The meta block echoes the applied window and derives has_more (PRD 2.3)."""
    items, meta = validate_paginated(response)
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"expected total_count {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is (offset + len(items) < total), (
        "has_more must say whether rows remain beyond this window (PRD 2.3)"
    )
    return items


def assert_created_at_ascending(items: Sequence[Dict[str, Any]]) -> None:
    """List results are sorted by ``created_at`` ascending (PRD 2.3)."""
    stamps = [parse_instant(item["created_at"]) for item in items]
    assert stamps == sorted(stamps), "results must be sorted created_at ascending"


def assert_ids(items: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Assert a listing returned exactly these ids, in this order."""
    assert [item["id"] for item in items] == list(expected_ids)


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_clinician(record: Dict[str, Any]) -> None:
    """A clinician exposes its roster credential and booked docket (PRD 3.1)."""
    assert_common_fields(record)
    for field in ("full_name", "staff_role", "license_number", "booked_docket_minutes"):
        assert field in record, f"clinician missing {field!r}"
    assert isinstance(record["booked_docket_minutes"], int)
    assert record["booked_docket_minutes"] >= 0


def assert_unit(record: Dict[str, Any]) -> None:
    """A unit exposes its five derived counters and its posture (PRD 3.1)."""
    assert_common_fields(record)
    for field in (
        "name",
        "gender_mixing_policy",
        "seclusion_room_count",
        "licensed_placement_bed_count",
        "raw_available_bed_count",
        "posture",
        "effective_available_bed_count",
        "occupied_bed_count",
        "active_seclusion_count",
        "open_rights_violation_count",
    ):
        assert field in record, f"unit missing {field!r}"


def assert_bed(record: Dict[str, Any]) -> None:
    """A bed exposes its location, type and status (PRD 3.1)."""
    assert_common_fields(record)
    for field in ("unit_id", "room_number", "wing_code", "bed_label", "bed_type", "status"):
        assert field in record, f"bed missing {field!r}"


def assert_patient(record: Dict[str, Any]) -> None:
    """A patient exposes derived minor status and active hold count (PRD 3.2)."""
    assert_common_fields(record)
    for field in (
        "mrn",
        "legal_name",
        "age_years",
        "gender_care_category",
        "is_minor",
        "active_hold_count",
    ):
        assert field in record, f"patient missing {field!r}"
    assert isinstance(record["is_minor"], bool)


def assert_evaluation(record: Dict[str, Any]) -> None:
    """An evaluation exposes its four derived clinical figures (PRD 3.2)."""
    assert_common_fields(record)
    for field in (
        "patient_id",
        "evaluating_clinician_id",
        "evaluation_started_at",
        "prior_admission_count_30d",
        "acuity_score",
        "acuity_tier",
        "recommended_status",
        "status",
        "signed_at",
    ):
        assert field in record, f"evaluation missing {field!r}"
    assert_millisecond_instant(record["evaluation_started_at"], "evaluation_started_at")
    assert_optional_millisecond_instant(record["signed_at"], "signed_at")


def assert_hold(record: Dict[str, Any]) -> None:
    """A hold exposes its four computed instants (PRD 3.3)."""
    assert_common_fields(record)
    for field in (
        "patient_id",
        "evaluation_id",
        "hold_type",
        "statutory_hours",
        "clock_started_at",
        "certification_deadline_at",
        "release_deadline_at",
        "petition_filing_deadline_at",
        "status",
    ):
        assert field in record, f"hold missing {field!r}"
    for field in (
        "clock_started_at",
        "certification_deadline_at",
        "release_deadline_at",
        "petition_filing_deadline_at",
    ):
        assert_millisecond_instant(record[field], field)
    assert_optional_millisecond_instant(record.get("certified_at"), "certified_at")


def assert_petition(record: Dict[str, Any]) -> None:
    """A petition exposes its continuance tally (PRD 3.4)."""
    assert_common_fields(record)
    for field in (
        "hold_id",
        "petitioning_clinician_id",
        "requested_hold_type",
        "petition_grounds",
        "filed_at",
        "continuance_count",
        "status",
    ):
        assert field in record, f"petition missing {field!r}"
    assert_millisecond_instant(record["filed_at"], "filed_at")


def assert_hearing(record: Dict[str, Any]) -> None:
    """A hearing exposes its computed end instant, status and outcome (PRD 3.4)."""
    assert_common_fields(record)
    for field in (
        "petition_id",
        "advocate_clinician_id",
        "scheduled_start_at",
        "duration_minutes",
        "scheduled_end_at",
        "status",
        "outcome",
        "findings_note",
    ):
        assert field in record, f"hearing missing {field!r}"
    assert_millisecond_instant(record["scheduled_start_at"], "scheduled_start_at")
    assert_millisecond_instant(record["scheduled_end_at"], "scheduled_end_at")


def assert_admission(record: Dict[str, Any]) -> None:
    """An admission exposes both of its independent axes (PRD 3.5)."""
    assert_common_fields(record)
    for field in (
        "patient_id",
        "evaluation_id",
        "unit_id",
        "bed_id",
        "admitting_clinician_id",
        "legal_status",
        "placement_status",
        "acuity_tier",
        "admitted_at",
        "safety_search_status",
        "discharge_plan_status",
        "observation_staff_quarter_hours",
        "rights_violation_flag",
    ):
        assert field in record, f"admission missing {field!r}"
    assert_millisecond_instant(record["admitted_at"], "admitted_at")
    assert_optional_millisecond_instant(record.get("placed_at"), "placed_at")
    assert_optional_millisecond_instant(record.get("discharged_at"), "discharged_at")


def assert_restraint(record: Dict[str, Any]) -> None:
    """A restraint episode exposes its schedule and compliance figures (PRD 3.6)."""
    assert_common_fields(record)
    for field in (
        "admission_id",
        "ordered_by_clinician_id",
        "intervention_type",
        "ordered_duration_minutes",
        "clinical_justification",
        "started_at",
        "authorized_until_at",
        "face_to_face_deadline_at",
        "monitoring_interval_minutes",
        "monitoring_check_log",
        "status",
    ):
        assert field in record, f"restraint missing {field!r}"
    assert_millisecond_instant(record["started_at"], "started_at")
    assert_millisecond_instant(record["authorized_until_at"], "authorized_until_at")
    assert_millisecond_instant(
        record["face_to_face_deadline_at"], "face_to_face_deadline_at"
    )
    assert isinstance(record["monitoring_check_log"], list)


def assert_capacity_determination(record: Dict[str, Any]) -> None:
    """A determination exposes its three surrogate fields and status (PRD 3.7)."""
    assert_common_fields(record)
    for field in (
        "admission_id",
        "determined_by_clinician_id",
        "capacity_present",
        "surrogate_name",
        "surrogate_relationship",
        "surrogate_authority_scope",
        "determined_at",
        "status",
    ):
        assert field in record, f"capacity determination missing {field!r}"
    assert_millisecond_instant(record["determined_at"], "determined_at")


def assert_medication_consent(record: Dict[str, Any]) -> None:
    """A consent exposes its basis and expiry (PRD 3.7)."""
    assert_common_fields(record)
    for field in (
        "admission_id",
        "capacity_determination_id",
        "prescribing_clinician_id",
        "medication_name",
        "consent_basis",
        "expires_at",
        "status",
    ):
        assert field in record, f"medication consent missing {field!r}"
    assert_optional_millisecond_instant(record["expires_at"], "expires_at")


def assert_discharge_request(record: Dict[str, Any]) -> None:
    """A discharge request exposes its response deadline and decision (PRD 3.8)."""
    assert_common_fields(record)
    for field in (
        "admission_id",
        "recorded_by_clinician_id",
        "requested_by",
        "requested_at",
        "response_deadline_at",
        "decision",
        "status",
    ):
        assert field in record, f"discharge request missing {field!r}"
    assert_millisecond_instant(record["requested_at"], "requested_at")
    assert_millisecond_instant(record["response_deadline_at"], "response_deadline_at")


def assert_sweep_counts(data: Dict[str, Any]) -> None:
    """The sweep reports its four counters (PRD 2.4)."""
    for field in (
        "expired_hold_count",
        "expired_restraint_count",
        "expired_discharge_request_count",
        "expired_consent_count",
    ):
        assert field in data, f"sweep response missing {field!r}"
        assert isinstance(data[field], int), f"{field} should be an integer"


# ---------------------------------------------------------------------------
# Derived-quantity assertions
# ---------------------------------------------------------------------------


def assert_unit_availability(
    unit: Dict[str, Any],
    *,
    licensed: int,
    raw_available: int,
    occupied: Optional[int] = None,
) -> None:
    """Re-derive the whole availability chain of PRD 3.1 from the two tallies."""
    assert unit["licensed_placement_bed_count"] == licensed, (
        f"expected licensed_placement_bed_count {licensed}, "
        f"got {unit['licensed_placement_bed_count']}"
    )
    assert unit["raw_available_bed_count"] == raw_available, (
        f"expected raw_available_bed_count {raw_available}, "
        f"got {unit['raw_available_bed_count']}"
    )
    assert unit["posture"] == expected_posture(licensed, raw_available), (
        f"posture should be {expected_posture(licensed, raw_available)} for "
        f"licensed={licensed} raw={raw_available}, got {unit['posture']}"
    )
    assert unit["effective_available_bed_count"] == expected_effective_available(
        licensed, raw_available
    ), (
        "effective_available_bed_count should be "
        f"{expected_effective_available(licensed, raw_available)}, "
        f"got {unit['effective_available_bed_count']}"
    )
    if occupied is not None:
        assert unit["occupied_bed_count"] == occupied, (
            f"expected occupied_bed_count {occupied}, got {unit['occupied_bed_count']}"
        )


def assert_posture_threshold(licensed: int, expected: int) -> None:
    """The restricted threshold is ``max(1, floor(licensed / 5))`` (PRD 3.1)."""
    assert posture_threshold(licensed) == expected


def assert_compliance_pct(actual: Any, expected: float, label: str) -> None:
    """A compliance percentage carries one decimal place, halves up (PRD 2.6)."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"expected {label} of {expected}, got {actual}"
    )
    rendered = f"{float(actual):.{COMPLIANCE_DECIMAL_PLACES}f}"
    assert float(rendered) == pytest.approx(float(actual), abs=0.001), (
        f"{label} should carry a single decimal place, got {actual}"
    )


def expected_grid_compliance(satisfied: int, required: int) -> float:
    """Reproduce ``grid_compliance_pct`` of PRD 3.6."""
    if required == 0:
        return 100.0
    return round_half_up_one_dp(100.0 * satisfied / required)


def expected_raw_compliance(logged: int, required: int) -> float:
    """Reproduce ``raw_compliance_pct`` of PRD 3.6."""
    if required == 0:
        return 100.0
    return round_half_up_one_dp(100.0 * min(required, logged) / required)


def assert_monitoring_compliance(
    episode: Dict[str, Any],
    *,
    required: int,
    grid_satisfied: int,
    logged: int,
) -> None:
    """Pin both compliance percentages from the same episode (PRD 3.6)."""
    assert episode["required_check_count"] == required, (
        f"expected required_check_count {required}, "
        f"got {episode['required_check_count']}"
    )
    assert episode["grid_satisfied_slot_count"] == grid_satisfied, (
        f"expected grid_satisfied_slot_count {grid_satisfied}, "
        f"got {episode['grid_satisfied_slot_count']}"
    )
    assert_compliance_pct(
        episode["grid_compliance_pct"],
        expected_grid_compliance(grid_satisfied, required),
        "grid_compliance_pct",
    )
    assert_compliance_pct(
        episode["raw_compliance_pct"],
        expected_raw_compliance(logged, required),
        "raw_compliance_pct",
    )


def expected_quarter_hours(actual_durations: Iterable[int]) -> int:
    """Ceil each episode to quarter hours before summing (PRD 3.6)."""
    return sum(
        -(-duration // QUARTER_HOUR_MINUTES) for duration in actual_durations
    )


def assert_observation_quarter_hours(
    admission: Dict[str, Any], actual_durations: Iterable[int]
) -> None:
    """The staffing total ceilings per episode, then sums (PRD 3.6)."""
    durations = list(actual_durations)
    expected = expected_quarter_hours(durations)
    assert admission["observation_staff_quarter_hours"] == expected, (
        f"expected observation_staff_quarter_hours {expected} from per-episode "
        f"ceilings of {durations}, got {admission['observation_staff_quarter_hours']}"
    )


def assert_docket_minutes(clinician: Dict[str, Any], expected: int) -> None:
    """``booked_docket_minutes`` sums the advocate's scheduled hearings (PRD 3.1)."""
    assert clinician["booked_docket_minutes"] == expected, (
        f"expected booked_docket_minutes {expected}, "
        f"got {clinician['booked_docket_minutes']}"
    )


def assert_axes(
    admission: Dict[str, Any], *, legal_status: str, placement_status: str
) -> None:
    """Pin both admission axes at once, since they evolve independently (PRD 3.5)."""
    assert admission["legal_status"] == legal_status, (
        f"expected legal_status {legal_status}, got {admission['legal_status']}"
    )
    assert admission["placement_status"] == placement_status, (
        f"expected placement_status {placement_status}, "
        f"got {admission['placement_status']}"
    )


def assert_billable_status(status: str) -> None:
    """Only closed episodes contribute observation quarter hours (PRD 3.6)."""
    assert status in OBSERVATION_BILLABLE_STATUSES, (
        f"{status} does not contribute observation staffing (PRD 3.6)"
    )
