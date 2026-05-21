"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape of a single API response data
dict against PRD §3 and §2.4. Child entities DutyPeriod, FlightLeg, and
SickCall carry only id and created_at (PRD §2.4 — "no updated_at field
and no version field").
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DEADHEAD_PAY_RATIO,
    MIN_PAY_CREDIT_FLOOR_MINUTES,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers.
# ---------------------------------------------------------------------------
def _assert_common_fields_mutable(data: Dict[str, Any]) -> None:
    """For entities the PRD §2.4 declares carry id, created_at,
    updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO-8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_common_fields_append_only(data: Dict[str, Any]) -> None:
    """PRD §2.4: "The child entities DutyPeriod, FlightLeg, and SickCall
    carry only id and created_at; they have no updated_at field and no
    version field, and clients must not assume either is present in
    their JSON payloads."
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions.
# ---------------------------------------------------------------------------
def assert_crew_member(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    emp_no = data.get("employee_no", "")
    assert isinstance(emp_no, str) and len(emp_no) == 7 and emp_no[0] == "E" \
        and emp_no[1:].isdigit(), (
        f"PRD §3.1: employee_no pattern ^E\\d{{6}}$; got {emp_no!r}"
    )
    assert data.get("rank") in (
        "CAPTAIN", "FIRST_OFFICER", "PURSER", "FLIGHT_ATTENDANT",
    )
    assert isinstance(data.get("base_airport"), str) and \
        len(data["base_airport"]) == 3
    assert isinstance(data.get("union_seniority_number"), int) and \
        data["union_seniority_number"] > 0
    assert isinstance(data.get("union_local_id"), str) and \
        len(data["union_local_id"]) > 0
    assert data.get("status") in (
        "ACTIVE", "ON_SICK_CALL", "ON_LEAVE", "INACTIVE",
    )
    assert isinstance(data.get("cumulative_duty_minutes_7d"), int) and \
        data["cumulative_duty_minutes_7d"] >= 0
    assert isinstance(data.get("cumulative_block_minutes_30d"), int) and \
        data["cumulative_block_minutes_30d"] >= 0


def assert_pairing(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert isinstance(data.get("pairing_code"), str) and \
        len(data["pairing_code"]) > 0
    assert isinstance(data.get("base_airport"), str) and \
        len(data["base_airport"]) == 3
    assert data.get("status") in (
        "DRAFT", "PUBLISHED", "BIDDING_OPEN", "AWARDED",
        "IN_PROGRESS", "CLOSED", "CANCELLED",
    )
    assert isinstance(data.get("total_block_minutes"), int) and \
        data["total_block_minutes"] >= 0
    assert isinstance(data.get("total_duty_minutes"), int) and \
        data["total_duty_minutes"] >= 0
    assert isinstance(data.get("required_rank_composition"), dict)


def assert_duty_period(data: Dict[str, Any]) -> None:
    _assert_common_fields_append_only(data)
    assert "updated_at" not in data, (
        "PRD §2.4: DutyPeriod has no updated_at field."
    )
    assert "version" not in data, (
        "PRD §2.4: DutyPeriod has no version field."
    )
    assert is_valid_uuid(data.get("pairing_id", ""))
    assert isinstance(data.get("sequence_no"), int) and \
        data["sequence_no"] >= 1
    assert is_iso8601_timestamp(data.get("report_at", ""))
    assert is_iso8601_timestamp(data.get("release_at", ""))
    assert isinstance(data.get("duty_minutes"), int) and \
        data["duty_minutes"] >= 0


def assert_flight_leg(data: Dict[str, Any]) -> None:
    _assert_common_fields_append_only(data)
    assert "updated_at" not in data, (
        "PRD §2.4: FlightLeg has no updated_at field."
    )
    assert "version" not in data, (
        "PRD §2.4: FlightLeg has no version field."
    )
    assert is_valid_uuid(data.get("duty_period_id", ""))
    assert isinstance(data.get("leg_sequence_no"), int) and \
        data["leg_sequence_no"] >= 1
    assert isinstance(data.get("flight_number"), str) and \
        len(data["flight_number"]) > 0
    assert isinstance(data.get("dep_airport"), str) and \
        len(data["dep_airport"]) == 3
    assert isinstance(data.get("arr_airport"), str) and \
        len(data["arr_airport"]) == 3
    assert is_iso8601_timestamp(data.get("dep_at", ""))
    assert is_iso8601_timestamp(data.get("arr_at", ""))
    assert isinstance(data.get("block_minutes"), int) and \
        data["block_minutes"] >= 0
    assert data.get("leg_type") in ("REVENUE", "DEADHEAD")


def assert_bid(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert is_valid_uuid(data.get("pairing_id", ""))
    assert isinstance(data.get("preference_rank"), int) and \
        data["preference_rank"] >= 1
    assert isinstance(data.get("bid_window_id"), str) and \
        len(data["bid_window_id"]) > 0
    assert data.get("status") in (
        "SUBMITTED", "AWARDED", "NOT_AWARDED", "WITHDRAWN",
    )


def assert_assignment(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("pairing_id", ""))
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert data.get("assigned_rank_slot") in (
        "CAPTAIN", "FIRST_OFFICER", "PURSER", "FLIGHT_ATTENDANT",
    )
    assert data.get("source") in (
        "BID_AWARD", "RESERVE_CALLOUT", "TRADE", "ADMIN_OVERRIDE",
    )
    assert data.get("status") in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "RELEASED", "NO_SHOW",
    )
    assert isinstance(data.get("scheduled_block_minutes"), int) and \
        data["scheduled_block_minutes"] >= 0
    assert isinstance(data.get("actual_block_minutes"), int) and \
        data["actual_block_minutes"] >= 0
    assert isinstance(data.get("pay_credit_minutes"), int) and \
        data["pay_credit_minutes"] >= 0


def assert_reserve_pool(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert is_iso8601_timestamp(data.get("reserve_date", ""))
    assert is_iso8601_timestamp(data.get("standby_start_at", ""))
    assert is_iso8601_timestamp(data.get("standby_end_at", ""))
    assert data.get("state") in (
        "AVAILABLE", "CALLED_OUT", "RELEASED", "EXPIRED",
    )


def assert_sick_call(data: Dict[str, Any]) -> None:
    _assert_common_fields_append_only(data)
    assert "updated_at" not in data, (
        "PRD §2.4: SickCall has no updated_at field."
    )
    assert "version" not in data, (
        "PRD §2.4: SickCall has no version field."
    )
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("expected_return_at", ""))


def assert_trade_request(data: Dict[str, Any]) -> None:
    _assert_common_fields_mutable(data)
    assert is_valid_uuid(data.get("initiator_assignment_id", ""))
    assert is_valid_uuid(data.get("counterparty_assignment_id", ""))
    assert is_valid_uuid(data.get("initiator_id", ""))
    assert is_valid_uuid(data.get("counterparty_id", ""))
    assert data.get("state") in (
        "PROPOSED", "COUNTER_PROPOSED", "ACCEPTED", "REJECTED",
        "APPROVED", "EXECUTED", "EXPIRED", "CANCELLED",
    )
    assert isinstance(data.get("revision_count"), int) and \
        data["revision_count"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers / reference computations.
# ---------------------------------------------------------------------------
def expected_pay_credit_actual(revenue_minutes: int,
                                  deadhead_minutes: int) -> int:
    """Reference computation per PRD §3.6.

    "First, revenue minutes are summed ... Second, deadhead minutes are
    summed ... Third, the deadhead credit is derived by multiplying the
    integer deadhead-minute total by the deadhead pay ratio of one half
    and then taking the floor of the product — aggregate first, then
    floor, never floor each leg individually. Fourth, the raw credit is
    the sum of the revenue minutes and the deadhead credit. Fifth,
    pay_credit_minutes is the greater of the raw credit and the
    minimum-pay-credit floor of 240 minutes (four hours)."
    """
    deadhead_credit = math.floor(deadhead_minutes * DEADHEAD_PAY_RATIO)
    raw = int(revenue_minutes) + int(deadhead_credit)
    return max(raw, MIN_PAY_CREDIT_FLOOR_MINUTES)


def expected_pay_credit_scheduled(revenue_minutes: int,
                                     deadhead_minutes: int) -> int:
    """Reference computation per PRD §3.6 scheduled variant.

    "The scheduled variant of the pay-credit calculation treats every
    flight leg currently scheduled in the pairing as if it had flown,
    summing the revenue and deadhead block minutes as above and applying
    the same aggregate-then-floor deadhead arithmetic — but it does not
    apply the 240-minute minimum-pay-credit floor."
    """
    deadhead_credit = math.floor(deadhead_minutes * DEADHEAD_PAY_RATIO)
    return int(revenue_minutes) + int(deadhead_credit)


def assert_version_incremented_by_one(prev: Dict[str, Any],
                                       curr: Dict[str, Any]) -> None:
    """PRD §2.4: "a monotonically increasing integer version that starts
    at 1 and is incremented by exactly 1 on every successful mutation."
    """
    assert curr["version"] == prev["version"] + 1, (
        f"version expected {prev['version'] + 1}, got {curr['version']}"
    )


def assert_block_minutes_conserved_across_trade(
    m1_before: int, m2_before: int,
    m1_after: int, m2_after: int,
) -> None:
    """PRD §3.8: "the SUM of CrewMember.cumulative_block_minutes_30d
    across the two crew members is identical before and after, because
    each minute moves from one ledger to the other with no net loss or
    gain."
    """
    assert m1_before + m2_before == m1_after + m2_after, (
        f"PRD §3.8 conservation: sum_block_30d_both must be unchanged. "
        f"before={m1_before + m2_before}, after={m1_after + m2_after}"
    )


def filter_assignments_by_status(items: Iterable[Dict[str, Any]],
                                    status: str) -> List[Dict[str, Any]]:
    return [a for a in items if a.get("status") == status]


def filter_bids_by_status(items: Iterable[Dict[str, Any]],
                            status: str) -> List[Dict[str, Any]]:
    return [b for b in items if b.get("status") == status]


__all__ = [
    "assert_assignment",
    "assert_bid",
    "assert_block_minutes_conserved_across_trade",
    "assert_crew_member",
    "assert_duty_period",
    "assert_flight_leg",
    "assert_pairing",
    "assert_reserve_pool",
    "assert_sick_call",
    "assert_trade_request",
    "assert_version_incremented_by_one",
    "expected_pay_credit_actual",
    "expected_pay_credit_scheduled",
    "filter_assignments_by_status",
    "filter_bids_by_status",
]
