"""Domain assertions for the live animal travel contract.

These helpers only restate promises the PRD already makes, so a failure message
always points at a specific PRD rule rather than at a bare dictionary diff.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_versioned_resource_shape(resource: Dict[str, Any]) -> None:
    """A versioned resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id must be a UUID, got {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert is_iso8601_timestamp(resource["updated_at"]), resource["updated_at"]
    assert isinstance(resource["version"], int)
    assert resource["version"] >= 1


def assert_append_only_event_shape(resource: Dict[str, Any]) -> None:
    """A welfare check carries only id and created_at of the common fields.

    PRD §2.4: "It has **no** `updated_at` field and **no** `version` field, and
    it is never updated after it is written."
    """
    assert is_valid_uuid(resource["id"]), f"id must be a UUID, got {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert "updated_at" not in resource, "a welfare check must not expose updated_at"
    assert "version" not in resource, "a welfare check must not expose version"


def assert_initial_version(resource: Dict[str, Any]) -> None:
    """PRD §2.4: version "starts at 1 on creation"."""
    assert resource["version"] == 1, f"expected version 1, got {resource['version']}"


def assert_version_is(resource: Dict[str, Any], expected: int) -> None:
    assert resource["version"] == expected, (
        f"expected version {expected}, got {resource['version']}"
    )


# ---------------------------------------------------------------------------
# Envelope (PRD §2.2)
# ---------------------------------------------------------------------------


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta


# ---------------------------------------------------------------------------
# Money (PRD §2.8, §3.8)
# ---------------------------------------------------------------------------


def assert_money_fields_are_integers(reservation: Dict[str, Any]) -> None:
    """PRD §2.8 names the money fields that are integers in minor units."""
    for field in (
        "irops_fee_total",
        "subtotal_amount",
        "loyalty_discount_amount",
        "refunded_amount",
        "net_payable_amount",
    ):
        assert isinstance(reservation[field], int) and not isinstance(
            reservation[field], bool
        ), f"{field} must be an integer number of minor units, got {reservation[field]!r}"


def assert_charge_identity(source: Dict[str, Any]) -> None:
    """PRD §3.8: "`subtotal_amount` equals `net_payable_amount` plus
    `loyalty_discount_amount` plus `refunded_amount`"."""
    assert source["subtotal_amount"] == (
        source["net_payable_amount"]
        + source["loyalty_discount_amount"]
        + source["refunded_amount"]
    ), (
        f"identity broken: subtotal={source['subtotal_amount']} "
        f"net={source['net_payable_amount']} "
        f"discount={source['loyalty_discount_amount']} "
        f"refunded={source['refunded_amount']}"
    )


def assert_reservation_money(
    reservation: Dict[str, Any],
    *,
    irops_fee_total: Optional[int] = None,
    subtotal_amount: Optional[int] = None,
    loyalty_tier_pct: Optional[float] = None,
    loyalty_discount_amount: Optional[int] = None,
    refunded_amount: Optional[int] = None,
    net_payable_amount: Optional[int] = None,
) -> None:
    expectations = {
        "irops_fee_total": irops_fee_total,
        "subtotal_amount": subtotal_amount,
        "loyalty_tier_pct": loyalty_tier_pct,
        "loyalty_discount_amount": loyalty_discount_amount,
        "refunded_amount": refunded_amount,
        "net_payable_amount": net_payable_amount,
    }
    for field, expected in expectations.items():
        if expected is None:
            continue
        actual = reservation[field]
        if field == "loyalty_tier_pct":
            assert abs(float(actual) - float(expected)) < 1e-9, (
                f"{field}: expected {expected}, got {actual}"
            )
        else:
            assert actual == expected, f"{field}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# State dimensions (PRD §3.4)
# ---------------------------------------------------------------------------


def assert_reservation_state(
    reservation: Dict[str, Any],
    *,
    booking_status: Optional[str] = None,
    compliance_status: Optional[str] = None,
) -> None:
    """PRD §3.4 tracks two independent dimensions on a reservation."""
    if booking_status is not None:
        assert reservation["booking_status"] == booking_status, (
            f"booking_status: expected {booking_status}, "
            f"got {reservation['booking_status']}"
        )
    if compliance_status is not None:
        assert reservation["compliance_status"] == compliance_status, (
            f"compliance_status: expected {compliance_status}, "
            f"got {reservation['compliance_status']}"
        )


def assert_animal_state(
    animal: Dict[str, Any],
    *,
    status: Optional[str] = None,
    container_compliance_state: Optional[str] = None,
    deficiency_codes: Optional[Sequence[str]] = None,
    chargeable_weight_kg: Optional[float] = None,
) -> None:
    if status is not None:
        assert animal["status"] == status, (
            f"animal status: expected {status}, got {animal['status']}"
        )
    if container_compliance_state is not None:
        assert animal["container_compliance_state"] == container_compliance_state, (
            f"container_compliance_state: expected {container_compliance_state}, "
            f"got {animal['container_compliance_state']}"
        )
    if deficiency_codes is not None:
        assert animal["deficiency_codes"] == list(deficiency_codes), (
            f"deficiency_codes: expected {list(deficiency_codes)}, "
            f"got {animal['deficiency_codes']}"
        )
    if chargeable_weight_kg is not None:
        assert animal["chargeable_weight_kg"] == chargeable_weight_kg, (
            f"chargeable_weight_kg: expected {chargeable_weight_kg}, "
            f"got {animal['chargeable_weight_kg']}"
        )


def assert_flight_leg_state(
    leg: Dict[str, Any],
    *,
    status: Optional[str] = None,
    posture: Optional[str] = None,
    governing_embargo_rule_id: Optional[str] = ...,  # type: ignore[assignment]
    booked_cabin_count: Optional[int] = None,
    booked_checked_count: Optional[int] = None,
    booked_cargo_count: Optional[int] = None,
    block_minutes: Optional[int] = None,
) -> None:
    if status is not None:
        assert leg["status"] == status, (
            f"leg status: expected {status}, got {leg['status']}"
        )
    if posture is not None:
        assert leg["posture"] == posture, (
            f"leg posture: expected {posture}, got {leg['posture']}"
        )
    if governing_embargo_rule_id is not ...:
        assert leg["governing_embargo_rule_id"] == governing_embargo_rule_id, (
            f"governing_embargo_rule_id: expected {governing_embargo_rule_id}, "
            f"got {leg['governing_embargo_rule_id']}"
        )
    for field, expected in (
        ("booked_cabin_count", booked_cabin_count),
        ("booked_checked_count", booked_checked_count),
        ("booked_cargo_count", booked_cargo_count),
        ("block_minutes", block_minutes),
    ):
        if expected is not None:
            assert leg[field] == expected, (
                f"{field}: expected {expected}, got {leg[field]}"
            )


def assert_segment_state(
    segment: Dict[str, Any],
    *,
    status: Optional[str] = None,
    segment_fee_amount: Optional[int] = None,
    fee_variant: Optional[str] = None,
    connection_minutes: Optional[int] = ...,  # type: ignore[assignment]
    required_welfare_check_count: Optional[int] = None,
    completed_welfare_check_count: Optional[int] = None,
) -> None:
    if status is not None:
        assert segment["status"] == status, (
            f"segment status: expected {status}, got {segment['status']}"
        )
    if segment_fee_amount is not None:
        assert segment["segment_fee_amount"] == segment_fee_amount, (
            f"segment_fee_amount: expected {segment_fee_amount}, "
            f"got {segment['segment_fee_amount']}"
        )
    if fee_variant is not None:
        assert segment["fee_variant"] == fee_variant, (
            f"fee_variant: expected {fee_variant}, got {segment['fee_variant']}"
        )
    if connection_minutes is not ...:
        assert segment["connection_minutes"] == connection_minutes, (
            f"connection_minutes: expected {connection_minutes}, "
            f"got {segment['connection_minutes']}"
        )
    for field, expected in (
        ("required_welfare_check_count", required_welfare_check_count),
        ("completed_welfare_check_count", completed_welfare_check_count),
    ):
        if expected is not None:
            assert segment[field] == expected, (
                f"{field}: expected {expected}, got {segment[field]}"
            )


def assert_incident_state(
    incident: Dict[str, Any],
    *,
    status: Optional[str] = None,
    preliminary_severity_score: Optional[int] = None,
    adjudicated_severity_score: Optional[int] = ...,  # type: ignore[assignment]
    disclosure_required: Optional[bool] = None,
    disclosure_deadline_utc: Optional[str] = ...,  # type: ignore[assignment]
    disclosure_on_time: Optional[bool] = ...,  # type: ignore[assignment]
) -> None:
    if status is not None:
        assert incident["status"] == status, (
            f"incident status: expected {status}, got {incident['status']}"
        )
    if preliminary_severity_score is not None:
        assert incident["preliminary_severity_score"] == preliminary_severity_score, (
            f"preliminary_severity_score: expected {preliminary_severity_score}, "
            f"got {incident['preliminary_severity_score']}"
        )
    if adjudicated_severity_score is not ...:
        assert incident["adjudicated_severity_score"] == adjudicated_severity_score, (
            f"adjudicated_severity_score: expected {adjudicated_severity_score}, "
            f"got {incident['adjudicated_severity_score']}"
        )
    if disclosure_required is not None:
        assert incident["disclosure_required"] is disclosure_required, (
            f"disclosure_required: expected {disclosure_required}, "
            f"got {incident['disclosure_required']}"
        )
    if disclosure_deadline_utc is not ...:
        assert incident["disclosure_deadline_utc"] == disclosure_deadline_utc, (
            f"disclosure_deadline_utc: expected {disclosure_deadline_utc}, "
            f"got {incident['disclosure_deadline_utc']}"
        )
    if disclosure_on_time is not ...:
        assert incident["disclosure_on_time"] is disclosure_on_time, (
            f"disclosure_on_time: expected {disclosure_on_time}, "
            f"got {incident['disclosure_on_time']}"
        )


def assert_station_bays(station: Dict[str, Any], reserved_bay_count: int) -> None:
    assert station["reserved_bay_count"] == reserved_bay_count, (
        f"reserved_bay_count: expected {reserved_bay_count}, "
        f"got {station['reserved_bay_count']}"
    )


def assert_ids_equal(actual: Any, expected: Any, label: str = "id") -> None:
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


__all__ = [
    "assert_versioned_resource_shape",
    "assert_append_only_event_shape",
    "assert_initial_version",
    "assert_version_is",
    "assert_envelope_meta",
    "assert_money_fields_are_integers",
    "assert_charge_identity",
    "assert_reservation_money",
    "assert_reservation_state",
    "assert_animal_state",
    "assert_flight_leg_state",
    "assert_segment_state",
    "assert_incident_state",
    "assert_station_bays",
    "assert_ids_equal",
    "ids_of",
]
