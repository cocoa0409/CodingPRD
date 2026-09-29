"""Domain assertions derived from the PRD's cross-cutting rules.

These wrap the repeated shape checks (PRD §2.5 common properties, §2.8
precision, §2.3 pagination meta) so individual tests can stay focused on the
behaviour they are pinning down.
"""

import re
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ACUITY_MAX,
    ACUITY_MIN,
    LEVEL_ORDINAL,
    OUTCOME_ORDINAL,
    OVERTRIAGE_POINTS_PER_ORDINAL,
    UNDERTRIAGE_POINTS_PER_ORDINAL,
)

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z$")


def canonical_instant(value: str) -> str:
    """Strip a fractional-second component so two instants compare by value.

    PRD §2.2 fixes the wire format as "ISO 8601 UTC strings ending in `Z`";
    the fractional part is not part of the instant being asserted.
    """
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"not an ISO 8601 UTC instant: {value!r}"
    return match.group(1) + "Z"


def assert_instant(actual: Optional[str], expected: str, label: str = "timestamp"):
    """Compare two UTC instants ignoring sub-second width."""
    assert actual is not None, f"{label} was null, expected {expected}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label} was {actual}, expected {expected}"
    )


def assert_timestamp(value: Any, label: str = "timestamp"):
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label} is not an ISO 8601 UTC timestamp: {value!r}"
    )


# ── PRD §2.5 common resource properties ────────────────────────────────────
def assert_common_fields(entity: Dict[str, Any], versioned: bool = True):
    """Every resource carries `id` and `created_at`; the ten mutable ones also
    carry `updated_at` and `version` (PRD §2.5)."""
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert_timestamp(entity.get("created_at"), "created_at")
    if versioned:
        assert_timestamp(entity.get("updated_at"), "updated_at")
        assert isinstance(entity.get("version"), int), "version must be an integer"
        assert entity["version"] >= 1, "version starts at 1"
    else:
        assert_immutable_record(entity)


def assert_immutable_record(entity: Dict[str, Any]):
    """PRD §2.5: the immutable resources "have no `updated_at` field and no
    `version` field at all"."""
    assert "updated_at" not in entity, (
        f"immutable record must not expose updated_at: {entity.get('updated_at')!r}"
    )
    assert "version" not in entity, (
        f"immutable record must not expose version: {entity.get('version')!r}"
    )


def assert_version_is(entity: Dict[str, Any], expected: int, label: str = "version"):
    assert entity.get("version") == expected, (
        f"{label} was {entity.get('version')}, expected {expected}"
    )


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any]):
    """PRD §2.5: "`version` starts at 1 and increases by exactly one on every
    accepted mutation"."""
    assert after["version"] > before["version"], (
        f"version did not advance: {before['version']} -> {after['version']}"
    )


# ── PRD §2.8 precision ─────────────────────────────────────────────────────
def assert_cents(value: Any, expected: int, label: str = "amount"):
    """Money is carried in integer cents (PRD §2.8)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"{label} was {value} cents, expected {expected}"


def assert_percentage(value: Any, expected: float, label: str = "percentage"):
    """Percentages are "rounded half up to one decimal place" (PRD §2.8)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert value == pytest.approx(expected, abs=0.01), (
        f"{label} was {value}, expected {expected}"
    )


def assert_whole_minutes(value: Any, expected: int, label: str = "minutes"):
    """Minutes are "always whole numbers" (PRD §2.8)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a whole number of minutes, got {value!r}"
    )
    assert value == expected, f"{label} was {value}, expected {expected}"


# ── PRD §2.5 / §3.5 acuity ─────────────────────────────────────────────────
def assert_acuity_in_range(score: Any):
    """PRD §3.5 clamps the acuity score "into the range 0 to 100 inclusive"."""
    assert isinstance(score, int), f"acuity_score must be an integer, got {score!r}"
    assert ACUITY_MIN <= score <= ACUITY_MAX, (
        f"acuity_score {score} is outside 0..100"
    )


def assert_assessment_math(
    assessment: Dict[str, Any],
    age_years_used: int,
    age_modifier_points: int,
    pregnancy_modifier_points: int,
    red_flag_points: int,
    acuity_score: int,
):
    """Pin every published intermediate of the acuity formula (PRD §3.5)."""
    assert assessment["age_years_used"] == age_years_used, (
        f"age_years_used was {assessment['age_years_used']}, "
        f"expected {age_years_used}"
    )
    assert assessment["age_modifier_points"] == age_modifier_points, (
        f"age_modifier_points was {assessment['age_modifier_points']}, "
        f"expected {age_modifier_points}"
    )
    assert assessment["pregnancy_modifier_points"] == pregnancy_modifier_points, (
        f"pregnancy_modifier_points was "
        f"{assessment['pregnancy_modifier_points']}, "
        f"expected {pregnancy_modifier_points}"
    )
    assert assessment["red_flag_points"] == red_flag_points, (
        f"red_flag_points was {assessment['red_flag_points']}, "
        f"expected {red_flag_points}"
    )
    assert_acuity_in_range(assessment["acuity_score"])
    assert assessment["acuity_score"] == acuity_score, (
        f"acuity_score was {assessment['acuity_score']}, expected {acuity_score}"
    )


# ── PRD §3.10 variance ─────────────────────────────────────────────────────
def expected_variance(reported_outcome: str, final_level: str):
    """Reproduce the variance classification of PRD §3.10 from its inputs."""
    outcome_ordinal = OUTCOME_ORDINAL[reported_outcome]
    level_ordinal = LEVEL_ORDINAL[final_level]
    gap = outcome_ordinal - level_ordinal
    if gap == 0:
        return "CONCORDANT", 0
    if gap > 0:
        return "UNDERTRIAGE", gap * UNDERTRIAGE_POINTS_PER_ORDINAL
    return "OVERTRIAGE", -gap * OVERTRIAGE_POINTS_PER_ORDINAL


def assert_variance(
    record: Dict[str, Any],
    outcome_ordinal: int,
    disposition_level_ordinal: int,
    variance_class: str,
    variance_severity_points: int,
):
    assert record["outcome_ordinal"] == outcome_ordinal, (
        f"outcome_ordinal was {record['outcome_ordinal']}, "
        f"expected {outcome_ordinal}"
    )
    assert record["disposition_level_ordinal"] == disposition_level_ordinal, (
        f"disposition_level_ordinal was {record['disposition_level_ordinal']}, "
        f"expected {disposition_level_ordinal}"
    )
    assert record["variance_class"] == variance_class, (
        f"variance_class was {record['variance_class']}, expected {variance_class}"
    )
    assert record["variance_severity_points"] == variance_severity_points, (
        f"variance_severity_points was {record['variance_severity_points']}, "
        f"expected {variance_severity_points}"
    )


# ── PRD §2.9 counters ──────────────────────────────────────────────────────
def assert_counters(entity: Dict[str, Any], **expected: int):
    """Assert several conserved counters at once (PRD §2.9)."""
    for field, value in expected.items():
        assert entity.get(field) == value, (
            f"{field} was {entity.get(field)}, expected {value}"
        )


def assert_nurse_load(nurse: Dict[str, Any], active: int, high_risk: int, eligibility: str):
    assert_counters(
        nurse,
        active_call_load=active,
        pending_high_risk_count=high_risk,
    )
    assert nurse["intake_eligibility"] == eligibility, (
        f"intake_eligibility was {nurse['intake_eligibility']}, "
        f"expected {eligibility}"
    )


# ── PRD §2.3 listings ──────────────────────────────────────────────────────
def assert_total_count(meta: Dict[str, Any], expected: int):
    assert meta["total_count"] == expected, (
        f"total_count was {meta['total_count']}, expected {expected}"
    )


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str]):
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"row order was {actual}, expected {expected_ids}"


def assert_field_values(rows: List[Dict[str, Any]], field: str, expected: List[Any]):
    actual = [row.get(field) for row in rows]
    assert actual == expected, f"{field} sequence was {actual}, expected {expected}"


# ── PRD §2.2 envelope ──────────────────────────────────────────────────────
def assert_error_envelope(response, expected_error_id: str):
    """PRD §2.2: an error body carries `response_type` "error" and a `data`
    object holding `error_id` and `message`, with a `meta` object that
    "contains only `api_request_id` and `api_request_timestamp`"."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"response_type was {body.get('response_type')!r}, expected 'error'"
    )
    data = body.get("data") or {}
    assert data.get("error_id") == expected_error_id, (
        f"error_id was {data.get('error_id')}, expected {expected_error_id}"
    )
    assert isinstance(data.get("message"), str) and data["message"], (
        "error message must be a non-empty human-readable string"
    )
    meta = body.get("meta") or {}
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta carried {sorted(meta.keys())}, expected only "
        "api_request_id and api_request_timestamp"
    )
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )


def assert_success_envelope(response, response_type: str = "object"):
    """PRD §2.2: a success body carries `meta`, `response_type` and `data`,
    where `api_request_id` "starts with `req_`"."""
    body = response.json()
    assert body.get("response_type") == response_type, (
        f"response_type was {body.get('response_type')!r}, "
        f"expected {response_type!r}"
    )
    assert "data" in body, f"success body has no data field: {body}"
    meta = body.get("meta") or {}
    assert str(meta.get("api_request_id", "")).startswith("req_"), (
        f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    )
    assert_timestamp(meta.get("api_request_timestamp"), "api_request_timestamp")
    return body["data"]
