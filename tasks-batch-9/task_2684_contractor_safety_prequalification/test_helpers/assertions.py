"""Domain assertions for entity shape, precision regimes and conserved counters."""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

SCORE_TOLERANCE = 0.01
RATE_TOLERANCE = 0.0001


# ---------------------------------------------------------------------------
# Envelope and identity
# ---------------------------------------------------------------------------


def assert_identity_fields(row: Dict[str, Any]) -> None:
    """Every persisted row carries a server-minted UUID and a created_at."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be ISO 8601, got {row.get('created_at')!r}"
    )


def assert_versioned_row(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A row that carries updated_at and version, per Section 2.4."""
    assert_identity_fields(row)
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be ISO 8601, got {row.get('updated_at')!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_immutable_row(row: Dict[str, Any]) -> None:
    """Worker and WorkerQualification expose only id and created_at."""
    assert_identity_fields(row)
    assert "updated_at" not in row, "an immutable row must not expose updated_at"
    assert "version" not in row, "an immutable row must not expose version"


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more


# ---------------------------------------------------------------------------
# Precision regimes
# ---------------------------------------------------------------------------


def assert_score_equals(actual: Any, expected: float) -> None:
    """Scores are two-decimal quantities."""
    assert actual is not None, f"expected score {expected}, got None"
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"expected score {expected}, got {actual}"
    )


def assert_rate_equals(actual: Any, expected: float) -> None:
    """Normalized rates and effective thresholds are four-decimal quantities."""
    assert actual is not None, f"expected rate {expected}, got None"
    assert actual == pytest.approx(expected, abs=RATE_TOLERANCE), (
        f"expected rate {expected}, got {actual}"
    )


def assert_whole_dollars(value: Any) -> None:
    """Insurance figures are whole US dollars."""
    assert isinstance(value, int) or (isinstance(value, float) and float(value).is_integer()), (
        f"expected a whole-dollar figure, got {value!r}"
    )


def assert_exact_int(actual: Any, expected: int) -> None:
    """Citation points are exact integers with no rounding step."""
    assert actual == expected, f"expected exactly {expected}, got {actual!r}"
    assert isinstance(actual, int), f"expected an integer, got {type(actual).__name__}"


def assert_effective_thresholds(
    thresholds: Optional[Dict[str, Any]],
    max_trir: float,
    max_dart_rate: float,
    max_emr: float,
    max_citation_points: float,
    tightening: Optional[float] = None,
    hazard_tier: Optional[int] = None,
) -> None:
    """The resolved yardstick snapshot pinned onto a graded row."""
    assert thresholds is not None, "effective_thresholds must be present once graded"
    assert_rate_equals(thresholds["max_trir"], max_trir)
    assert_rate_equals(thresholds["max_dart_rate"], max_dart_rate)
    assert_rate_equals(thresholds["max_emr"], max_emr)
    assert_rate_equals(thresholds["max_citation_points"], max_citation_points)
    if tightening is not None:
        assert_rate_equals(thresholds["tightening"], tightening)
    if hazard_tier is not None:
        assert thresholds["hazard_tier"] == hazard_tier, (
            f"expected hazard_tier {hazard_tier}, got {thresholds.get('hazard_tier')}"
        )


# ---------------------------------------------------------------------------
# Domain shape assertions
# ---------------------------------------------------------------------------


def assert_prequalification_state(
    row: Dict[str, Any],
    status: Optional[str] = None,
    grade: Optional[Any] = "__unset__",
    deficiency_codes: Optional[List[str]] = None,
    final_composite_score: Any = "__unset__",
    provisional_composite_score: Any = "__unset__",
    statistics_verification_status: Optional[str] = None,
    document_review_status: Optional[str] = None,
    audit_state: Optional[str] = None,
) -> None:
    if status is not None:
        assert row["status"] == status, f"expected status {status}, got {row['status']}"
    if grade != "__unset__":
        assert row["grade"] == grade, f"expected grade {grade!r}, got {row['grade']!r}"
    if deficiency_codes is not None:
        assert row["deficiency_codes"] == deficiency_codes, (
            f"expected deficiency_codes {deficiency_codes}, got {row['deficiency_codes']}"
        )
    if final_composite_score != "__unset__":
        if final_composite_score is None:
            assert row["final_composite_score"] is None, (
                f"expected final_composite_score null, got {row['final_composite_score']}"
            )
        else:
            assert_score_equals(row["final_composite_score"], final_composite_score)
    if provisional_composite_score != "__unset__":
        if provisional_composite_score is None:
            assert row["provisional_composite_score"] is None
        else:
            assert_score_equals(
                row["provisional_composite_score"], provisional_composite_score
            )
    if statistics_verification_status is not None:
        assert row["statistics_verification_status"] == statistics_verification_status
    if document_review_status is not None:
        assert row["document_review_status"] == document_review_status
    if audit_state is not None:
        assert row["audit_state"] == audit_state


def assert_certificate_state(
    row: Dict[str, Any],
    verification_status: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    available_aggregate: Optional[int] = None,
) -> None:
    if verification_status is not None:
        assert row["verification_status"] == verification_status, (
            f"expected verification_status {verification_status}, "
            f"got {row['verification_status']}"
        )
    if lifecycle_status is not None:
        assert row["lifecycle_status"] == lifecycle_status, (
            f"expected lifecycle_status {lifecycle_status}, got {row['lifecycle_status']}"
        )
    if available_aggregate is not None:
        assert row["available_aggregate"] == available_aggregate, (
            f"expected available_aggregate {available_aggregate}, "
            f"got {row['available_aggregate']}"
        )


def assert_grant_state(
    row: Dict[str, Any],
    status: Optional[str] = None,
    revocation_reason: Any = "__unset__",
    revoked_at: Any = "__unset__",
    qualification_snapshot: Optional[List[str]] = None,
) -> None:
    if status is not None:
        assert row["status"] == status, f"expected grant status {status}, got {row['status']}"
    if revocation_reason != "__unset__":
        assert row["revocation_reason"] == revocation_reason, (
            f"expected revocation_reason {revocation_reason!r}, "
            f"got {row['revocation_reason']!r}"
        )
    if revoked_at != "__unset__":
        assert row["revoked_at"] == revoked_at, (
            f"expected revoked_at {revoked_at!r}, got {row['revoked_at']!r}"
        )
    if qualification_snapshot is not None:
        assert row["qualification_snapshot"] == qualification_snapshot, (
            f"expected qualification_snapshot {qualification_snapshot}, "
            f"got {row['qualification_snapshot']}"
        )


def assert_site_posture(
    row: Dict[str, Any],
    granted_worker_count: Optional[int] = None,
    access_gate_status: Optional[str] = None,
) -> None:
    if granted_worker_count is not None:
        assert row["granted_worker_count"] == granted_worker_count, (
            f"expected granted_worker_count {granted_worker_count}, "
            f"got {row['granted_worker_count']}"
        )
    if access_gate_status is not None:
        assert row["access_gate_status"] == access_gate_status, (
            f"expected access_gate_status {access_gate_status}, "
            f"got {row['access_gate_status']}"
        )


def assert_contractor_posture(
    row: Dict[str, Any],
    status: Optional[str] = None,
    base_hazard_tier: Optional[int] = None,
    incident_review_flag: Optional[bool] = None,
    open_severe_incident_count: Optional[int] = None,
    open_deficiency_count: Optional[int] = None,
    verified_coverage_types: Optional[List[str]] = None,
) -> None:
    if status is not None:
        assert row["status"] == status
    if base_hazard_tier is not None:
        assert row["base_hazard_tier"] == base_hazard_tier, (
            f"expected base_hazard_tier {base_hazard_tier}, got {row['base_hazard_tier']}"
        )
    if incident_review_flag is not None:
        assert row["incident_review_flag"] is incident_review_flag, (
            f"expected incident_review_flag {incident_review_flag}, "
            f"got {row['incident_review_flag']}"
        )
    if open_severe_incident_count is not None:
        assert row["open_severe_incident_count"] == open_severe_incident_count, (
            f"expected open_severe_incident_count {open_severe_incident_count}, "
            f"got {row['open_severe_incident_count']}"
        )
    if open_deficiency_count is not None:
        assert row["open_deficiency_count"] == open_deficiency_count, (
            f"expected open_deficiency_count {open_deficiency_count}, "
            f"got {row['open_deficiency_count']}"
        )
    if verified_coverage_types is not None:
        assert row["verified_coverage_types"] == verified_coverage_types, (
            f"expected verified_coverage_types {verified_coverage_types}, "
            f"got {row['verified_coverage_types']}"
        )


# ---------------------------------------------------------------------------
# Conserved-counter reconciliation
# ---------------------------------------------------------------------------


def reconcile_granted_worker_count(api, headers: dict, site_id: str) -> int:
    """Return the defining query for a site's granted_worker_count and check it."""
    site = validate_success(api.get_site(site_id, headers))
    rows, meta = validate_paginated(
        api.list_grants(headers, {"site_id": site_id, "status": "GRANTED"})
    )
    assert site["granted_worker_count"] == meta["total_count"], (
        f"granted_worker_count {site['granted_worker_count']} drifted from the "
        f"{meta['total_count']} GRANTED rows on the site"
    )
    return site["granted_worker_count"]


def reconcile_open_deficiency_count(api, headers: dict, contractor_id: str) -> int:
    """Return the defining query for a contractor's open_deficiency_count and check it."""
    contractor = validate_success(api.get_contractor(contractor_id, headers))
    rows, _meta = validate_paginated(
        api.list_prequalifications(
            headers, {"contractor_id": contractor_id, "status": "CONDITIONAL", "limit": 100}
        )
    )
    expected = sum(len(row["deficiency_codes"]) for row in rows)
    assert contractor["open_deficiency_count"] == expected, (
        f"open_deficiency_count {contractor['open_deficiency_count']} drifted from the "
        f"{expected} codes carried by CONDITIONAL rows"
    )
    return contractor["open_deficiency_count"]


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Compare two instants at second granularity, per Section 2.5."""
    assert actual is not None, f"expected instant {expected}, got None"
    got = parse_instant(actual).replace(microsecond=0)
    want = parse_instant(expected).replace(microsecond=0)
    assert got == want, f"expected instant {expected}, got {actual}"


def assert_instant_is_none(actual: Any, field: str = "instant") -> None:
    assert actual is None, f"expected {field} to be null, got {actual!r}"
