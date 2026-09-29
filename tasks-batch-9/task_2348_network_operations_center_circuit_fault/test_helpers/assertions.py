"""Domain assertions for the network-operations contract.

These wrap the generic structural helpers with the precision rules of PRD
Section 2.9 and the derived-field vocabulary of PRD Section 3, so tests can
state an expectation once instead of repeating field-by-field comparisons.
"""

from typing import Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)
from prd_bench_local_runner.testing import validate_success as _validate_success_envelope


def validate_success(response, expected_status: int = 200) -> dict:
    """Validate the success envelope and return the whole body.

    The generic framework helper returns only `data`; every call site in this
    suite reads the full envelope (`["data"]`, `["meta"]`, `["response_type"]`),
    so this wrapper runs the same structural checks and hands back `response.json()`.
    """
    _validate_success_envelope(response, expected_status)
    return response.json()

# Precision tolerances taken from PRD Section 2.9.
MINUTE_TOLERANCE = 0.005  # minutes are carried to two decimal places
AVAILABILITY_TOLERANCE = 0.0005  # availability percentages to three places
RATIO_TOLERANCE = 0.00005  # credit ratios to four places
SCORE_TOLERANCE = 0.005  # scores to two decimal places
PERCENT_TOLERANCE = 0.005  # utilisation compared at two decimal places


# ---------------------------------------------------------------------------
# Identity, timestamps and versioning (PRD 2.5)
# ---------------------------------------------------------------------------
def assert_identity_block(record: dict, label: str = "record") -> None:
    """Every record carries a UUID `id` and an ISO 8601 `created_at`."""
    assert is_valid_uuid(record.get("id", "")), (
        f"{label}.id must be a UUID, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant, "
        f"got {record.get('created_at')!r}"
    )


def assert_versioned_record(
    record: dict, expected_version: Optional[int] = None, label: str = "record"
) -> None:
    """A mutable record also carries `updated_at` and an integer `version`."""
    assert_identity_block(record, label)
    assert is_iso8601_timestamp(record.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 instant, "
        f"got {record.get('updated_at')!r}"
    )
    version = record.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version must be an integer, got {version!r}"
    )
    if expected_version is not None:
        assert version == expected_version, (
            f"{label}.version should be {expected_version}, got {version}"
        )


def assert_append_only_record(record: dict, label: str = "record") -> None:
    """Append-only records carry only `id` and `created_at`, never a version."""
    assert_identity_block(record, label)
    assert "version" not in record, (
        f"{label} is append-only and must not expose a version field"
    )
    assert "updated_at" not in record, (
        f"{label} is append-only and must not expose an updated_at field"
    )


def assert_instant(actual: Optional[str], expected: str, label: str) -> None:
    """An instant must match exactly, with three fractional-second digits."""
    assert actual == expected, f"{label} should be {expected}, got {actual!r}"


def assert_millisecond_precision(value: str, label: str) -> None:
    """PRD 2.5 renders instants with exactly three fractional-second digits."""
    assert is_iso8601_timestamp(value), f"{label} is not an ISO 8601 instant: {value!r}"
    assert "." in value and len(value.split(".")[1].rstrip("Z")) == 3, (
        f"{label} must carry exactly three fractional-second digits, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Precision helpers (PRD 2.9)
# ---------------------------------------------------------------------------
def assert_minutes(actual, expected: float, label: str) -> None:
    """Minute quantities are carried to two decimal places."""
    assert actual == pytest.approx(expected, abs=MINUTE_TOLERANCE), (
        f"{label} should be {expected:.2f} minutes, got {actual!r}"
    )


def assert_availability_pct(actual, expected: float, label: str) -> None:
    """Availability percentages are carried to three decimal places."""
    assert actual == pytest.approx(expected, abs=AVAILABILITY_TOLERANCE), (
        f"{label} should be {expected:.3f}, got {actual!r}"
    )


def assert_credit_ratio(actual, expected: float, label: str = "credit_ratio") -> None:
    """Credit ratios are carried to four decimal places."""
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label} should be {expected:.4f}, got {actual!r}"
    )


def assert_score(actual, expected: float, label: str = "net_performance_score") -> None:
    """Scores are carried to two decimal places and floored at zero."""
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{label} should be {expected:.2f}, got {actual!r}"
    )
    assert actual >= 0.0, f"{label} must never fall below 0.00, got {actual!r}"


def assert_utilization_pct(actual, expected: float) -> None:
    """Utilisation is compared at two decimal places."""
    assert actual == pytest.approx(expected, abs=PERCENT_TOLERANCE), (
        f"utilization_pct should be {expected:.2f}, got {actual!r}"
    )


def assert_whole_cents(value, label: str) -> None:
    """Money is carried in whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a whole number of cents, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Carrier ledgers (PRD 2.10, 3.1, 3.6)
# ---------------------------------------------------------------------------
def assert_carrier_ledger(
    carrier: dict,
    exposure_cents: Optional[int] = None,
    committed_mbps: Optional[int] = None,
    watchlist_state: Optional[str] = None,
    chronic_circuit_count: Optional[int] = None,
) -> None:
    if exposure_cents is not None:
        assert carrier["open_credit_exposure_cents"] == exposure_cents, (
            f"open_credit_exposure_cents should be {exposure_cents}, "
            f"got {carrier['open_credit_exposure_cents']}"
        )
    if committed_mbps is not None:
        assert carrier["committed_upgrade_mbps"] == committed_mbps, (
            f"committed_upgrade_mbps should be {committed_mbps}, "
            f"got {carrier['committed_upgrade_mbps']}"
        )
    if watchlist_state is not None:
        assert carrier["watchlist_state"] == watchlist_state, (
            f"watchlist_state should be {watchlist_state}, "
            f"got {carrier['watchlist_state']}"
        )
    if chronic_circuit_count is not None:
        assert carrier["chronic_circuit_count"] == chronic_circuit_count, (
            f"chronic_circuit_count should be {chronic_circuit_count}, "
            f"got {carrier['chronic_circuit_count']}"
        )


# ---------------------------------------------------------------------------
# Circuit posture dimensions (PRD 3.1, 3.2, 3.8)
# ---------------------------------------------------------------------------
def assert_circuit_posture(
    circuit: dict,
    monitoring_state: Optional[str] = None,
    operational_state: Optional[str] = None,
    chronic_state: Optional[str] = None,
    capacity_state: Optional[str] = None,
    consecutive_high_readings: Optional[int] = None,
    spof_flag: Optional[bool] = None,
    fault_count_period: Optional[int] = None,
    bandwidth_mbps: Optional[int] = None,
) -> None:
    checks = {
        "monitoring_state": monitoring_state,
        "operational_state": operational_state,
        "chronic_state": chronic_state,
        "capacity_state": capacity_state,
        "consecutive_high_readings": consecutive_high_readings,
        "spof_flag": spof_flag,
        "fault_count_period": fault_count_period,
        "bandwidth_mbps": bandwidth_mbps,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert circuit[field] == expected, (
                f"circuit.{field} should be {expected!r}, got {circuit[field]!r}"
            )


# ---------------------------------------------------------------------------
# Path posture (PRD 3.2)
# ---------------------------------------------------------------------------
def assert_path_posture(
    path: dict,
    posture: Optional[str] = None,
    active_leg_count: Optional[int] = None,
    healthy_leg_count: Optional[int] = None,
    monitored_segment_count: Optional[int] = None,
) -> None:
    checks = {
        "posture": posture,
        "active_leg_count": active_leg_count,
        "healthy_leg_count": healthy_leg_count,
        "monitored_segment_count": monitored_segment_count,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert path[field] == expected, (
                f"path.{field} should be {expected!r}, got {path[field]!r}"
            )


# ---------------------------------------------------------------------------
# Incident classification (PRD 3.4)
# ---------------------------------------------------------------------------
def assert_incident_classification(
    incident: dict,
    severity: Optional[str] = None,
    impact_score: Optional[int] = None,
    response_state: Optional[str] = None,
    escalation_state: Optional[str] = None,
    alarm_count: Optional[int] = None,
    reopen_count: Optional[int] = None,
) -> None:
    checks = {
        "severity": severity,
        "impact_score": impact_score,
        "response_state": response_state,
        "escalation_state": escalation_state,
        "alarm_count": alarm_count,
        "reopen_count": reopen_count,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert incident[field] == expected, (
                f"incident.{field} should be {expected!r}, got {incident[field]!r}"
            )


# ---------------------------------------------------------------------------
# Upgrade order costing (PRD 3.8)
# ---------------------------------------------------------------------------
def assert_upgrade_cost(
    order: dict,
    delta_mbps: Optional[int] = None,
    subtotal_cents: Optional[int] = None,
    expedite_fee_cents: Optional[int] = None,
    total_cost_cents: Optional[int] = None,
) -> None:
    checks = {
        "delta_mbps": delta_mbps,
        "subtotal_cents": subtotal_cents,
        "expedite_fee_cents": expedite_fee_cents,
        "total_cost_cents": total_cost_cents,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert order[field] == expected, (
                f"order.{field} should be {expected}, got {order[field]}"
            )
    for field in ("subtotal_cents", "expedite_fee_cents", "total_cost_cents"):
        if field in order and order[field] is not None:
            assert_whole_cents(order[field], f"order.{field}")


# ---------------------------------------------------------------------------
# Credit arithmetic (PRD 3.6)
# ---------------------------------------------------------------------------
def assert_credit_arithmetic(
    claim: dict,
    basis: Optional[str] = None,
    sla_target_minutes: Optional[int] = None,
    breach_minutes: Optional[float] = None,
    breach_hours: Optional[int] = None,
    credit_amount_cents: Optional[int] = None,
) -> None:
    if basis is not None:
        assert claim["basis"] == basis, (
            f"claim.basis should be {basis}, got {claim['basis']}"
        )
    if sla_target_minutes is not None:
        assert claim["sla_target_minutes"] == sla_target_minutes, (
            f"claim.sla_target_minutes should be {sla_target_minutes}, "
            f"got {claim['sla_target_minutes']}"
        )
    if breach_minutes is not None:
        assert_minutes(claim["breach_minutes"], breach_minutes, "claim.breach_minutes")
    if breach_hours is not None:
        assert claim["breach_hours"] == breach_hours, (
            f"claim.breach_hours should be {breach_hours}, "
            f"got {claim['breach_hours']}"
        )
    if credit_amount_cents is not None:
        assert claim["credit_amount_cents"] == credit_amount_cents, (
            f"claim.credit_amount_cents should be {credit_amount_cents}, "
            f"got {claim['credit_amount_cents']}"
        )
        assert_whole_cents(claim["credit_amount_cents"], "claim.credit_amount_cents")


# ---------------------------------------------------------------------------
# Restoration clocks (PRD 3.5)
# ---------------------------------------------------------------------------
def assert_restoration_clocks(
    ticket: dict,
    carrier_clock: Optional[float] = None,
    noc_clock: Optional[float] = None,
    excluded_minutes: Optional[float] = None,
) -> None:
    if carrier_clock is not None:
        assert_minutes(
            ticket["restoration_minutes_carrier_clock"],
            carrier_clock,
            "ticket.restoration_minutes_carrier_clock",
        )
    if noc_clock is not None:
        assert_minutes(
            ticket["restoration_minutes_noc_clock"],
            noc_clock,
            "ticket.restoration_minutes_noc_clock",
        )
    if excluded_minutes is not None:
        assert_minutes(
            ticket["excluded_minutes"], excluded_minutes, "ticket.excluded_minutes"
        )


# ---------------------------------------------------------------------------
# Envelope shape (PRD 2.2, 2.3)
# ---------------------------------------------------------------------------
def assert_object_envelope(response) -> dict:
    """A single-record success body: `response_type` is exactly `object`."""
    body = response.json()
    assert body["response_type"] == "object", (
        f"single-record reads must report response_type 'object', "
        f"got {body.get('response_type')!r}"
    )
    return body["data"]


def assert_array_envelope(response) -> list:
    """A collection success body: `response_type` is exactly `array`."""
    body = response.json()
    assert body["response_type"] == "array", (
        f"collection reads must report response_type 'array', "
        f"got {body.get('response_type')!r}"
    )
    assert isinstance(body["data"], list), "collection data must be a list"
    return body["data"]


def assert_error_envelope(response) -> dict:
    """An error body: `response_type` error, `data` limited to the failure pair."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"failures must report response_type 'error', "
        f"got {body.get('response_type')!r}"
    )
    data = body["data"]
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data must carry exactly error_id and message, got {sorted(data)}"
    )
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only the request id and timestamp, got {sorted(meta)}"
    )
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"], (
        "error meta.api_request_id must be a non-empty string"
    )
    return data


def assert_request_id_shape(meta: dict) -> None:
    """`meta.api_request_id` is prefixed `req_` (PRD 2.2)."""
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )


def assert_page(
    meta: dict,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    checks = {
        "total_count": total_count,
        "has_more": has_more,
        "limit": limit,
        "offset": offset,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert meta[field] == expected, (
                f"meta.{field} should be {expected!r}, got {meta[field]!r}"
            )


def assert_ascending_by_created_at(rows: list) -> None:
    """Collections are ordered by ascending `created_at` (PRD 2.3)."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"rows must be ordered by ascending created_at, got {stamps}"
    )


def assert_distinct_ids(rows: list) -> None:
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), f"page contains duplicate ids: {ids}"
