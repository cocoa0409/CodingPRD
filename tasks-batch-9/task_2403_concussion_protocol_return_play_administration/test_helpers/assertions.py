"""
Domain assertion helpers for the Concussion Protocol & Return-to-Play API.

These build on the generic structural assertions supplied by the shared testing
framework and add the checks this contract keeps repeating: the four
system-managed properties, the three independent case dimensions, the club
compliance ledger identity, the roster-exemption slot conservation identity and
the escalation-tier / posture band derivations.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_valid_uuid,
)

from .constants import (
    CLUB_POSTURE_BANDS,
    ESCALATION_TIER_BANDS,
    STAGE_NAMES,
)


# ─── Common system-managed properties ────────────────────────────────────────

def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every row of every resource type carries id, created_at, updated_at, version."""
    assert is_valid_uuid(row.get("id", "")), f"id is not a raw UUID: {row.get('id')!r}"
    assert_timestamp_format(row["created_at"])
    assert_timestamp_format(row["updated_at"])
    assert isinstance(row.get("version"), int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_millisecond_timestamp(value: str) -> None:
    """Timestamps are ISO 8601 UTC with three fractional digits."""
    assert_timestamp_format(value)
    assert value.endswith("Z"), f"timestamp must be UTC with a Z suffix: {value!r}"
    assert len(value) == len("2026-09-13T18:19:00.000Z"), (
        f"timestamp must carry three fractional digits: {value!r}"
    )


def assert_instant(actual: Optional[str], expected: str) -> None:
    """Assert a stamped instant equals the expected millisecond-precision value."""
    assert actual == expected, f"Expected instant {expected}, got {actual!r}"


def assert_null(row: Dict[str, Any], *field_names: str) -> None:
    for field_name in field_names:
        assert row.get(field_name, None) is None, (
            f"Expected {field_name} to be null, got {row.get(field_name)!r}"
        )


# ─── Club compliance posture ─────────────────────────────────────────────────

def expected_escalation_tier(compliance_score: int) -> str:
    """TIER_0 at 90 and above, TIER_1 for 75..89, TIER_2 for 60..74, TIER_3 below 60."""
    for tier, low, high in ESCALATION_TIER_BANDS:
        if low is not None and high is None and compliance_score >= low:
            return tier
        if low is not None and high is not None and low <= compliance_score <= high:
            return tier
        if low is None and high is not None and compliance_score <= high:
            return tier
    raise AssertionError(f"no escalation tier band matches {compliance_score}")


def expected_club_posture(compliance_score: int) -> str:
    """ACTIVE at 90 and above, PROBATION for 70..89, SANCTIONED below 70."""
    for posture, low, high in CLUB_POSTURE_BANDS:
        if low is not None and high is None and compliance_score >= low:
            return posture
        if low is not None and high is not None and low <= compliance_score <= high:
            return posture
        if low is None and high is not None and compliance_score <= high:
            return posture
    raise AssertionError(f"no club posture band matches {compliance_score}")


def assert_club_posture(
    club: Dict[str, Any],
    compliance_score: int,
    escalation_tier: Optional[str] = None,
    status: Optional[str] = None,
    outstanding_fine_cents: Optional[int] = None,
    open_violation_count: Optional[int] = None,
    adjudicated_compliance_score: Optional[int] = None,
) -> None:
    """Assert the club's compliance posture, deriving tier and status when omitted."""
    assert club["compliance_score"] == compliance_score, (
        f"Expected compliance_score {compliance_score}, got {club['compliance_score']}"
    )
    tier = escalation_tier or expected_escalation_tier(compliance_score)
    posture = status or expected_club_posture(compliance_score)
    assert club["escalation_tier"] == tier, (
        f"Expected escalation_tier {tier}, got {club['escalation_tier']}"
    )
    assert club["status"] == posture, f"Expected status {posture}, got {club['status']}"
    if outstanding_fine_cents is not None:
        assert club["outstanding_fine_cents"] == outstanding_fine_cents, (
            f"Expected outstanding_fine_cents {outstanding_fine_cents}, "
            f"got {club['outstanding_fine_cents']}"
        )
    if open_violation_count is not None:
        assert club["open_violation_count"] == open_violation_count, (
            f"Expected open_violation_count {open_violation_count}, "
            f"got {club['open_violation_count']}"
        )
    if adjudicated_compliance_score is not None:
        assert club["adjudicated_compliance_score"] == adjudicated_compliance_score, (
            f"Expected adjudicated_compliance_score {adjudicated_compliance_score}, "
            f"got {club['adjudicated_compliance_score']}"
        )


def assert_fine_ledger_reconciles(club: Dict[str, Any], audits: List[Dict[str, Any]]) -> None:
    """
    outstanding_fine_cents equals the sum of assessed_fine_cents over the club's
    audits in FINDINGS_ISSUED, CLUB_RESPONDED or CLOSED_UPHELD.
    """
    counted = [
        a
        for a in audits
        if a["status"] in ("FINDINGS_ISSUED", "CLUB_RESPONDED", "CLOSED_UPHELD")
    ]
    total = sum(a["assessed_fine_cents"] for a in counted)
    assert club["outstanding_fine_cents"] == total, (
        f"Ledger drift: club carries {club['outstanding_fine_cents']} but counted audits "
        f"sum to {total}"
    )


def assert_exemption_slots_conserved(club: Dict[str, Any]) -> None:
    """exemption_slots_used + exemption_slots_available always equals exemption_slots_total."""
    used = club["exemption_slots_used"]
    available = club["exemption_slots_available"]
    total = club["exemption_slots_total"]
    assert used + available == total, (
        f"Slot pool not conserved: used {used} + available {available} != total {total}"
    )


def assert_exemption_slots(
    club: Dict[str, Any], used: int, available: int, total: Optional[int] = None
) -> None:
    assert club["exemption_slots_used"] == used, (
        f"Expected exemption_slots_used {used}, got {club['exemption_slots_used']}"
    )
    assert club["exemption_slots_available"] == available, (
        f"Expected exemption_slots_available {available}, got {club['exemption_slots_available']}"
    )
    if total is not None:
        assert club["exemption_slots_total"] == total
    assert_exemption_slots_conserved(club)


# ─── Concussion case dimensions ──────────────────────────────────────────────

def assert_case_dimensions(
    case: Dict[str, Any],
    case_status: Optional[str] = None,
    monitoring_status: Optional[str] = None,
    roster_exemption_status: Optional[str] = None,
) -> None:
    """The case carries three independent state dimensions on one row."""
    if case_status is not None:
        assert case["case_status"] == case_status, (
            f"Expected case_status {case_status}, got {case['case_status']}"
        )
    if monitoring_status is not None:
        assert case["monitoring_status"] == monitoring_status, (
            f"Expected monitoring_status {monitoring_status}, got {case['monitoring_status']}"
        )
    if roster_exemption_status is not None:
        assert case["roster_exemption_status"] == roster_exemption_status, (
            f"Expected roster_exemption_status {roster_exemption_status}, "
            f"got {case['roster_exemption_status']}"
        )


def assert_case_progress(
    case: Dict[str, Any],
    rtp_stage: Optional[int] = None,
    recurrence_count: Optional[int] = None,
    severity_index: Optional[int] = None,
    earliest_return_at: Any = "__unset__",
) -> None:
    if rtp_stage is not None:
        assert case["rtp_stage"] == rtp_stage, (
            f"Expected rtp_stage {rtp_stage}, got {case['rtp_stage']}"
        )
    if recurrence_count is not None:
        assert case["recurrence_count"] == recurrence_count, (
            f"Expected recurrence_count {recurrence_count}, got {case['recurrence_count']}"
        )
    if severity_index is not None:
        assert case["severity_index"] == severity_index, (
            f"Expected severity_index {severity_index}, got {case['severity_index']}"
        )
    if earliest_return_at != "__unset__":
        assert case["earliest_return_at"] == earliest_return_at, (
            f"Expected earliest_return_at {earliest_return_at!r}, "
            f"got {case['earliest_return_at']!r}"
        )


# ─── Return steps ────────────────────────────────────────────────────────────

def assert_return_step(
    step: Dict[str, Any],
    stage_index: Optional[int] = None,
    status: Optional[str] = None,
    attempt_index: Optional[int] = None,
    started_at: Optional[str] = None,
    min_start_at: Optional[str] = None,
    dwell_complete_at: Optional[str] = None,
) -> None:
    if stage_index is not None:
        assert step["stage_index"] == stage_index
        assert step["stage_name"] == STAGE_NAMES[stage_index], (
            f"Expected stage_name {STAGE_NAMES[stage_index]}, got {step['stage_name']}"
        )
    if status is not None:
        assert step["status"] == status, f"Expected step status {status}, got {step['status']}"
    if attempt_index is not None:
        assert step["attempt_index"] == attempt_index
    if started_at is not None:
        assert_instant(step["started_at"], started_at)
    if min_start_at is not None:
        assert_instant(step["min_start_at"], min_start_at)
    if dwell_complete_at is not None:
        assert_instant(step["dwell_complete_at"], dwell_complete_at)


# ─── Pagination ──────────────────────────────────────────────────────────────

def assert_page_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more {has_more}, got {meta['has_more']}"
        )


def assert_ids_equal(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert a listing returned exactly these ids, in this order."""
    actual = [r["id"] for r in rows]
    assert actual == expected_ids, f"Expected ids {expected_ids}, got {actual}"


def assert_sorted_by_created_at(rows: List[Dict[str, Any]]) -> None:
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"Rows are not ascending by created_at: {stamps}"


def assert_only_ids(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert a listing returned exactly this set of ids, order-insensitively."""
    actual = sorted(r["id"] for r in rows)
    assert actual == sorted(expected_ids), (
        f"Expected id set {sorted(expected_ids)}, got {actual}"
    )


# ─── Error envelope ──────────────────────────────────────────────────────────

def assert_error_envelope(response: Any) -> Dict[str, Any]:
    """A refused request carries meta, response_type 'error' and data.error_id/message."""
    body = response.json()
    assert set(body.keys()) >= {"meta", "response_type", "data"}, (
        f"Error envelope is missing top-level keys: {sorted(body.keys())}"
    )
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    error = body["data"]
    assert set(error.keys()) == {"error_id", "message"}, (
        f"Error data must carry exactly error_id and message, got {sorted(error.keys())}"
    )
    assert error["message"].strip()
    return error
