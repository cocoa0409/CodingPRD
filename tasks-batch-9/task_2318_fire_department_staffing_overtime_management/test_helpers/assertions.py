"""Domain assertion helpers.

Shape checkers for each entity plus the derived-state invariants the PRD states
about staffing, the encumbrance ledger and the FLSA work period.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    FLSA_MAX_PERIOD_HOURS,
    FLSA_THRESHOLD_HOURS,
    LEAVE_FLOOR_SLACK,
    WATCH_BAND_BP,
    WITHIN_BAND_BP,
)


# ---------------------------------------------------------------------------
# Common properties
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Every resource carries id, created_at, updated_at and an integer version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be ISO-8601, got {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be ISO-8601, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"


def _require(entity: Dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"missing fields {missing} in {sorted(entity)}"


# ---------------------------------------------------------------------------
# Per-entity shape checks
# ---------------------------------------------------------------------------
def assert_station(station: Dict[str, Any]) -> None:
    assert_common_fields(station)
    _require(
        station,
        "name",
        "battalion_code",
        "minimum_staffing_floor",
        "fiscal_ot_budget_cents",
        "fiscal_period_start_date",
        "fiscal_period_end_date",
        "ot_committed_cents",
        "ot_actual_cents",
        "budget_posture",
    )
    assert station["budget_posture"] in ("WITHIN", "WATCH", "OVER")
    assert station["ot_committed_cents"] >= 0
    assert station["ot_actual_cents"] >= 0


def assert_apparatus(apparatus: Dict[str, Any]) -> None:
    assert_common_fields(apparatus)
    _require(
        apparatus,
        "station_id",
        "unit_designation",
        "apparatus_type",
        "minimum_crew_size",
        "required_certifications",
        "closure_priority",
        "closure_exempt",
        "status",
    )
    assert 1 <= apparatus["minimum_crew_size"] <= 8
    assert isinstance(apparatus["required_certifications"], list)
    assert len(apparatus["required_certifications"]) <= apparatus["minimum_crew_size"]
    assert apparatus["status"] in ("IN_SERVICE", "OUT_OF_SERVICE")
    assert isinstance(apparatus["closure_exempt"], bool)


def assert_firefighter(firefighter: Dict[str, Any]) -> None:
    assert_common_fields(firefighter)
    _require(
        firefighter,
        "station_id",
        "acting_supervisor_id",
        "full_name",
        "rank",
        "platoon",
        "seniority_rank",
        "kelly_day_cycle_position",
        "certifications",
        "hourly_rate_cents",
        "employment_status",
        "roster_standing",
        "voluntary_ot_hours_charged",
        "mandatory_holdover_count",
        "callback_count",
        "ot_pass_count",
        "pending_offer_count",
    )
    assert firefighter["platoon"] in ("A", "B", "C", "D")
    assert firefighter["rank"] in ("FIREFIGHTER", "ENGINEER", "LIEUTENANT", "CAPTAIN")
    assert 1 <= firefighter["kelly_day_cycle_position"] <= 8
    assert firefighter["seniority_rank"] >= 1
    assert firefighter["hourly_rate_cents"] >= 1
    assert firefighter["employment_status"] in ("ACTIVE", "INJURY_LEAVE", "SEPARATED")
    assert firefighter["roster_standing"] in ("AVAILABLE", "PASSED", "UNAVAILABLE")


def assert_hiring_roster(roster: Dict[str, Any]) -> None:
    assert_common_fields(roster)
    _require(roster, "station_id", "roster_type", "certification_scope", "dispatch_count")
    assert roster["roster_type"] in (
        "VOLUNTARY_OT",
        "MANDATORY_HOLDOVER",
        "CALLBACK",
    )
    assert roster["certification_scope"] in (
        "NONE",
        "PARAMEDIC",
        "HAZMAT_TECH",
        "TECHNICAL_RESCUE",
    )


def assert_duty_shift(shift: Dict[str, Any]) -> None:
    assert_common_fields(shift)
    _require(
        shift,
        "station_id",
        "shift_date",
        "platoon",
        "status",
        "required_staffing",
        "assigned_headcount",
        "certification_gap_count",
        "staffing_gap",
        "leave_floor_headcount",
        "staffing_posture",
        "closed_apparatus_ids",
        "open_vacancy_count",
        "ops_run_index",
    )
    assert shift["status"] in ("DRAFT", "HIRING", "STAFFED", "COMPLETED")
    assert shift["staffing_posture"] in ("FULLY_STAFFED", "SHORT", "CRITICAL")
    assert isinstance(shift["closed_apparatus_ids"], list)


def assert_shift_assignment(assignment: Dict[str, Any]) -> None:
    assert_common_fields(assignment)
    _require(
        assignment,
        "duty_shift_id",
        "firefighter_id",
        "apparatus_id",
        "source_offer_id",
        "relieved_by_leave_request_id",
        "assignment_type",
        "seat_certification",
        "scheduled_hours",
        "actual_hours",
        "projected_premium_cents",
        "status",
    )
    assert assignment["assignment_type"] in (
        "REGULAR",
        "KELLY_RELIEF",
        "OVERTIME",
        "HOLDOVER",
        "CALLBACK",
        "TRADE",
    )
    assert assignment["status"] in ("SCHEDULED", "WORKED", "RELIEVED", "CANCELLED")
    assert 0 < assignment["scheduled_hours"] <= 24


def assert_leave_request(leave: Dict[str, Any]) -> None:
    assert_common_fields(leave)
    _require(
        leave,
        "firefighter_id",
        "duty_shift_id",
        "leave_type",
        "requested_hours",
        "status",
        "decision_order_index",
        "denial_reason",
        "backfill_vacancy_id",
    )
    assert leave["leave_type"] in (
        "INJURY",
        "SICK",
        "KELLY_DAY",
        "BEREAVEMENT",
        "VACATION",
    )
    assert leave["status"] in ("QUEUED", "APPROVED", "DENIED", "REVOKED")
    assert leave["denial_reason"] in (None, "STAFFING_FLOOR")


def assert_trade_request(trade: Dict[str, Any]) -> None:
    assert_common_fields(trade)
    _require(
        trade,
        "requesting_firefighter_id",
        "counterparty_firefighter_id",
        "duty_shift_id",
        "traded_assignment_id",
        "status",
        "revision_count",
        "decided_by_user_id",
    )
    assert trade["status"] in ("PROPOSED", "COUNTERSIGNED", "APPROVED", "REJECTED")
    assert trade["revision_count"] >= 0


def assert_vacancy(vacancy: Dict[str, Any]) -> None:
    assert_common_fields(vacancy)
    _require(
        vacancy,
        "duty_shift_id",
        "apparatus_id",
        "filled_by_assignment_id",
        "driver",
        "driver_source_id",
        "required_certification",
        "seat_index",
        "status",
    )
    assert vacancy["driver"] in ("VACANT_POSITION", "LEAVE", "INJURY")
    assert vacancy["status"] in (
        "OPEN",
        "OFFERING",
        "FILLED",
        "CLOSED_BY_COMPANY_CLOSURE",
        "CANCELLED",
    )


def assert_overtime_offer(offer: Dict[str, Any]) -> None:
    assert_common_fields(offer)
    _require(
        offer,
        "vacancy_id",
        "firefighter_id",
        "roster_id",
        "hiring_mode",
        "offer_hours",
        "projected_cost_cents",
        "expires_at",
        "status",
    )
    assert offer["hiring_mode"] in ("VOLUNTARY", "MANDATORY_HOLDOVER", "CALLBACK")
    assert offer["status"] in (
        "OFFERED",
        "ACCEPTED",
        "DECLINED",
        "EXPIRED",
        "RESCINDED",
        "MANDATED",
    )
    assert offer["projected_cost_cents"] >= 0
    assert is_iso8601_timestamp(offer["expires_at"])


def assert_work_period(period: Dict[str, Any]) -> None:
    assert_common_fields(period)
    _require(
        period,
        "firefighter_id",
        "period_start_date",
        "period_end_date",
        "flsa_threshold_hours",
        "adjusted_scheduled_hours",
        "adjusted_worked_hours",
        "scheduled_hours",
        "worked_hours",
        "leave_hours",
        "projected_flsa_overtime_hours",
        "final_flsa_overtime_hours",
        "flsa_premium_cents",
        "status",
    )
    assert period["flsa_threshold_hours"] == FLSA_THRESHOLD_HOURS
    assert period["status"] in ("OPEN", "CLOSED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_staffing_counters(
    shift: Dict[str, Any],
    required_staffing: int,
    assigned_headcount: int,
    staffing_gap: int,
    open_vacancy_count: int,
    certification_gap_count: Optional[int] = None,
    staffing_posture: Optional[str] = None,
) -> None:
    """Check the derived staffing block of a duty shift in one call."""
    assert shift["required_staffing"] == required_staffing, (
        f"required_staffing {shift['required_staffing']} != {required_staffing}"
    )
    assert shift["assigned_headcount"] == assigned_headcount, (
        f"assigned_headcount {shift['assigned_headcount']} != {assigned_headcount}"
    )
    assert shift["staffing_gap"] == staffing_gap, (
        f"staffing_gap {shift['staffing_gap']} != {staffing_gap}"
    )
    assert shift["open_vacancy_count"] == open_vacancy_count, (
        f"open_vacancy_count {shift['open_vacancy_count']} != {open_vacancy_count}"
    )
    if certification_gap_count is not None:
        assert shift["certification_gap_count"] == certification_gap_count, (
            f"certification_gap_count {shift['certification_gap_count']} "
            f"!= {certification_gap_count}"
        )
    if staffing_posture is not None:
        assert shift["staffing_posture"] == staffing_posture, (
            f"staffing_posture {shift['staffing_posture']} != {staffing_posture}"
        )


def expected_leave_floor_headcount(
    minimum_staffing_floor: int, required_staffing: int
) -> int:
    """The larger of the contractual floor and required_staffing less the slack."""
    return max(minimum_staffing_floor, required_staffing - LEAVE_FLOOR_SLACK)


def assert_leave_floor_headcount(
    shift: Dict[str, Any], minimum_staffing_floor: int
) -> None:
    """Check the shift's leave floor against the station's contractual floor."""
    expected = expected_leave_floor_headcount(
        minimum_staffing_floor, shift["required_staffing"]
    )
    assert shift["leave_floor_headcount"] == expected, (
        f"leave_floor_headcount {shift['leave_floor_headcount']} != {expected}"
    )


def assert_budget_posture_band(station: Dict[str, Any]) -> None:
    """Recompute the posture band from the ledger and the budget."""
    budget = station["fiscal_ot_budget_cents"]
    committed = station["ot_committed_cents"] + station["ot_actual_cents"]
    if budget == 0:
        return
    basis_points = round(committed * 10000 / budget)
    if basis_points <= WITHIN_BAND_BP:
        expected = "WITHIN"
    elif basis_points <= WATCH_BAND_BP:
        expected = "WATCH"
    else:
        expected = "OVER"
    assert station["budget_posture"] == expected, (
        f"{basis_points} basis points should be {expected}, "
        f"got {station['budget_posture']}"
    )


def assert_no_flsa_overtime_below_threshold(period: Dict[str, Any]) -> None:
    """No projected overtime until the adjusted scheduled basis passes 204 hours."""
    if period["adjusted_scheduled_hours"] <= FLSA_THRESHOLD_HOURS:
        assert period["projected_flsa_overtime_hours"] == 0
        assert period["flsa_premium_cents"] == 0


def assert_within_flsa_cap(period: Dict[str, Any]) -> None:
    assert period["adjusted_scheduled_hours"] <= FLSA_MAX_PERIOD_HOURS


def round_half_up(value: float) -> int:
    """The PRD's rounding discipline: half away from zero, to a whole cent."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
