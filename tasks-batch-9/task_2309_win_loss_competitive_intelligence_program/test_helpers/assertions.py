"""
Domain assertion helpers.

Numeric fields arrive as JSON numbers, so every monetary or ratio comparison is
routed through the PRD's own precision: monetary fields are compared at two
decimal places and ratio/score fields at four, which is exactly the precision at
which the PRD pins them.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .constants import money, ratio


# ---------------------------------------------------------------------------
# Numeric equality at the declared precision
# ---------------------------------------------------------------------------


def assert_money(actual: Any, expected: Any, label: str = "amount") -> None:
    """Compare a 2-decimal monetary field."""
    assert actual is not None, f"{label} was null, expected {expected}"
    assert money(actual) == money(expected), (
        f"{label}: expected {money(expected)}, got {money(actual)}"
    )


def assert_ratio(actual: Any, expected: Any, label: str = "ratio") -> None:
    """Compare a 4-decimal ratio or score field."""
    assert actual is not None, f"{label} was null, expected {expected}"
    assert ratio(actual) == ratio(expected), (
        f"{label}: expected {ratio(expected)}, got {ratio(actual)}"
    )


def assert_null(actual: Any, label: str = "field") -> None:
    assert actual is None, f"{label}: expected null, got {actual!r}"


def assert_not_null(actual: Any, label: str = "field") -> None:
    assert actual is not None, f"{label}: expected a value, got null"


def assert_field(entity: Dict[str, Any], field: str, expected: Any) -> None:
    """Exact equality on a non-numeric field, with the field named in the message."""
    assert field in entity, f"missing field {field!r} in {sorted(entity)}"
    assert entity[field] == expected, (
        f"{field}: expected {expected!r}, got {entity[field]!r}"
    )


def assert_fields(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    for field, value in expected.items():
        assert_field(entity, field, value)


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource but a recorded interview answer carries all four of these."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"missing common field {field!r} in {sorted(entity)}"
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version: expected {expected_version}, got {entity['version']}"
        )


def assert_response_common_fields(entity: Dict[str, Any]) -> None:
    """A recorded interview answer carries only `id` and `created_at`."""
    for field in ("id", "created_at"):
        assert field in entity, f"missing field {field!r} in {sorted(entity)}"
    assert "updated_at" not in entity, "an interview response must not carry updated_at"
    assert "version" not in entity, "an interview response must not carry version"


def assert_version_incremented(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"version: expected {before['version'] + by}, got {after['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version changed from {before['version']} to {after['version']}"
    )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Both envelopes carry a `meta` with a request id and a timestamp."""
    assert "meta" in body, f"missing meta in {sorted(body)}"
    meta = body["meta"]
    assert "api_request_id" in meta, "meta must carry api_request_id"
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must be prefixed with req_, got {meta['api_request_id']!r}"
    )
    assert "api_request_timestamp" in meta, "meta must carry api_request_timestamp"


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"paginated meta must carry {field!r}, got {sorted(meta)}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more: expected {expected_has_more}, got {meta['has_more']}"
        )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def assert_id_order(items: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Assert the exact sequence of identifiers, order included."""
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), (
        f"order: expected {list(expected_ids)}, got {actual}"
    )


def assert_ascending(values: Iterable[Any], label: str = "values") -> None:
    seq = list(values)
    assert seq == sorted(seq), f"{label} not ascending: {seq}"


def assert_descending(values: Iterable[Any], label: str = "values") -> None:
    seq = list(values)
    assert seq == sorted(seq, reverse=True), f"{label} not descending: {seq}"


def assert_contains_id(items: Sequence[Dict[str, Any]], entity_id: str) -> None:
    ids = [item["id"] for item in items]
    assert entity_id in ids, f"expected {entity_id} among {ids}"


def assert_excludes_id(items: Sequence[Dict[str, Any]], entity_id: str) -> None:
    ids = [item["id"] for item in items]
    assert entity_id not in ids, f"did not expect {entity_id} among {ids}"


# ---------------------------------------------------------------------------
# Ledger and posture
# ---------------------------------------------------------------------------


def assert_ledger(
    program: Dict[str, Any],
    committed_usd: Any,
    paid_usd: Any,
    posture: Optional[str] = None,
) -> None:
    assert_money(program["incentive_committed_usd"], committed_usd, "incentive_committed_usd")
    assert_money(program["incentive_paid_usd"], paid_usd, "incentive_paid_usd")
    if posture is not None:
        assert_field(program, "posture", posture)


def assert_analyst_workload(
    analyst: Dict[str, Any], open_interview_count: int, committed_minutes: int
) -> None:
    assert_field(analyst, "open_interview_count", open_interview_count)
    assert_field(analyst, "committed_minutes", committed_minutes)


def assert_frame_conservation(frame: Dict[str, Any]) -> None:
    """Each stratum's quota always equals its selected count plus its open slots.

    A frame still in `DRAFT` is exempt: its open slots are not materialised until it
    is sealed, so every counter is legitimately 0 while the quotas are not.
    """
    if frame.get("status") == "DRAFT":
        return
    for stratum, quota, selected, open_slots in (
        ("WON", "quota_won", "selected_won_count", "open_won_slots"),
        ("LOST", "quota_lost", "selected_lost_count", "open_lost_slots"),
        (
            "NO_DECISION",
            "quota_no_decision",
            "selected_no_decision_count",
            "open_no_decision_slots",
        ),
    ):
        assert frame[quota] == frame[selected] + frame[open_slots], (
            f"{stratum} conservation broken: quota {frame[quota]} != "
            f"selected {frame[selected]} + open {frame[open_slots]}"
        )


def assert_frame_slots(
    frame: Dict[str, Any],
    selected_won: Optional[int] = None,
    open_won: Optional[int] = None,
    selected_lost: Optional[int] = None,
    open_lost: Optional[int] = None,
    selected_no_decision: Optional[int] = None,
    open_no_decision: Optional[int] = None,
    coverage: Any = None,
) -> None:
    pairs = (
        ("selected_won_count", selected_won),
        ("open_won_slots", open_won),
        ("selected_lost_count", selected_lost),
        ("open_lost_slots", open_lost),
        ("selected_no_decision_count", selected_no_decision),
        ("open_no_decision_slots", open_no_decision),
    )
    for field, expected in pairs:
        if expected is not None:
            assert_field(frame, field, expected)
    if coverage is not None:
        assert_ratio(frame["coverage_ratio"], coverage, "coverage_ratio")
    assert_frame_conservation(frame)


# ---------------------------------------------------------------------------
# Battlecards
# ---------------------------------------------------------------------------


def assert_risk_indices(card: Dict[str, Any], pre: Any, final: Any) -> None:
    assert_money(card["risk_index_pre"], pre, "risk_index_pre")
    assert_money(card["risk_index_final"], final, "risk_index_final")


def assert_claim_counters(
    card: Dict[str, Any],
    approved: Optional[int] = None,
    conditional: Optional[int] = None,
    rejected: Optional[int] = None,
    corroborated: Optional[int] = None,
) -> None:
    for field, expected in (
        ("approved_claim_count", approved),
        ("conditional_claim_count", conditional),
        ("rejected_claim_count", rejected),
        ("corroborated_claim_count", corroborated),
    ):
        if expected is not None:
            assert_field(card, field, expected)


def assert_adoption(
    card: Dict[str, Any],
    assigned_count: Optional[int] = None,
    trained_count: Optional[int] = None,
    adoption_rate: Any = None,
) -> None:
    if assigned_count is not None:
        assert_field(card, "assigned_count", assigned_count)
    if trained_count is not None:
        assert_field(card, "trained_count", trained_count)
    if adoption_rate is not None:
        assert_ratio(card["adoption_rate"], adoption_rate, "adoption_rate")


def assert_substantiation(
    claim: Dict[str, Any], score: Any, level: str, risk: str
) -> None:
    assert_money(claim["substantiation_score"], score, "substantiation_score")
    assert_field(claim, "substantiation_level", level)
    assert_field(claim, "risk_class", risk)


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------


def assert_deal_dimensions(
    deal: Dict[str, Any],
    research_status: Optional[str] = None,
    attribution_status: Optional[str] = None,
    interview_coverage_count: Optional[int] = None,
) -> None:
    """The two status dimensions on a deal row are independent and both observable."""
    if research_status is not None:
        assert_field(deal, "research_status", research_status)
    if attribution_status is not None:
        assert_field(deal, "attribution_status", attribution_status)
    if interview_coverage_count is not None:
        assert_field(deal, "interview_coverage_count", interview_coverage_count)


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


def find_segment(trends: Dict[str, Any], segment: str) -> Dict[str, Any]:
    for entry in trends["segments"]:
        if entry["segment"] == segment:
            return entry
    raise AssertionError(
        f"segment {segment!r} absent from {[s['segment'] for s in trends['segments']]}"
    )


def assert_segment_absent(trends: Dict[str, Any], segment: str) -> None:
    present = [s["segment"] for s in trends["segments"]]
    assert segment not in present, f"segment {segment!r} should be omitted, got {present}"


def assert_trend_row(row: Dict[str, Any], code: str, weighted_total: Any, share: Any) -> None:
    assert_field(row, "root_reason_code", code)
    assert_money(row["weighted_total"], weighted_total, f"weighted_total[{code}]")
    assert_ratio(row["share"], share, f"share[{code}]")


def decimal_of(value: Any) -> Decimal:
    return Decimal(str(value))


def sorted_codes(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["root_reason_code"] for row in rows]
