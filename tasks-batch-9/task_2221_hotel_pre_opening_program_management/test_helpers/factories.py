"""Request payload builders.

Each factory returns a complete, valid payload for one endpoint and accepts
``**overrides`` so a test can perturb exactly the field under examination.
Passing ``None`` as an override value drops the key from the payload, which is
how tests exercise omitted-optional and missing-required behaviour.
"""

from typing import Any, Dict, Optional

# ─── Canonical scenario values ────────────────────────────────────────────────

DEFAULT_CONSTRUCTION_START = "2026-09-01"
DEFAULT_TARGET_OPENING = "2027-05-01"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is None."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Programs ─────────────────────────────────────────────────────────────────

def program_payload(**overrides: Any) -> Dict[str, Any]:
    """A complete program create payload, omitting the four tuning inputs."""
    return _merge(
        {
            "property_name": "Cobalt Bay Hotel",
            "brand_code": "CBH",
            "room_count": 120,
            "construction_start_date": DEFAULT_CONSTRUCTION_START,
            "target_opening_date": DEFAULT_TARGET_OPENING,
            "storage_capacity_pallets": 40,
            "relocation_rate_cents": 25000,
            "guarantee_penalty_cents": 150000,
            "room_night_ceiling": 200,
            "contingency_liability_cap_cents": 50000000,
        },
        overrides,
    )


def soft_opening_payload(soft_opening_date: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"soft_opening_date": soft_opening_date}, overrides)


# ─── Milestones and dependencies ──────────────────────────────────────────────

def milestone_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "code": "CONSTRUCTION_COMPLETE",
            "name": "Construction complete",
            "duration_days": 90,
            "planned_start_date": DEFAULT_CONSTRUCTION_START,
        },
        overrides,
    )


def dependency_payload(
    predecessor_milestone_id: str,
    successor_milestone_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "predecessor_milestone_id": predecessor_milestone_id,
            "successor_milestone_id": successor_milestone_id,
            "dependency_type": "FINISH_START",
            "lag_days": 0,
        },
        overrides,
    )


# ─── Permit applications ──────────────────────────────────────────────────────

def permit_payload(
    program_id: str, gating_milestone_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "gating_milestone_id": gating_milestone_id,
            "permit_type": "FOOD_SERVICE",
            "review_days": 21,
        },
        overrides,
    )


def permit_review_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """``decision`` is ISSUE, DEFICIENCY or DENY; a deficiency carries a reason."""
    base: Dict[str, Any] = {"decision": decision}
    if decision == "DEFICIENCY":
        base["deficiency_reason"] = "Grease interceptor undersized"
    return _merge(base, overrides)


# ─── System implementations and test runs ─────────────────────────────────────

def system_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"program_id": program_id, "system_type": "PMS", "is_required": True},
        overrides,
    )


def test_run_payload(
    executed_at: str, cases_total: int, cases_passed: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "executed_at": executed_at,
            "cases_total": cases_total,
            "cases_passed": cases_passed,
            "blocker_count": 0,
        },
        overrides,
    )


# ─── Hiring ───────────────────────────────────────────────────────────────────

def hiring_plan_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "department": "ROOMS",
            "headcount_target": 1,
            "wave_start_date": "2026-09-10",
        },
        overrides,
    )


def hire_payload(
    hiring_plan_id: str,
    orientation_session_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "hiring_plan_id": hiring_plan_id,
        "full_name": "Ana Reyes",
        "hourly_rate_cents": 2500,
        "scheduled_hours_per_day": 8,
        "start_date": "2026-09-15",
    }
    if orientation_session_id is not None:
        base["orientation_session_id"] = orientation_session_id
    return _merge(base, overrides)


def hire_response_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """``decision`` is ACCEPT, DECLINE or WITHDRAW."""
    return _merge({"decision": decision}, overrides)


def assign_orientation_payload(orientation_session_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"orientation_session_id": orientation_session_id}, overrides)


# ─── Training sessions ────────────────────────────────────────────────────────

def training_session_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "title": "Rooms orientation",
            "training_room_code": "TR-1",
            "starts_at": "2026-09-14T09:00:00Z",
            "ends_at": "2026-09-14T12:00:00Z",
            "capacity": 10,
            "department": "ROOMS",
        },
        overrides,
    )


# ─── Budget lines and OS&E orders ─────────────────────────────────────────────

def budget_line_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "category": "SETUP",
            "authorized_cents": 1000000,
        },
        overrides,
    )


def ose_order_payload(
    program_id: str,
    budget_line_id: str,
    expected_budget_line_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "budget_line_id": budget_line_id,
            "description": "Banquet chairs",
            "amount_cents": 300000,
            "pallet_count": 4,
            "delivery_window_start": "2026-10-01",
            "delivery_window_end": "2026-10-10",
            "expected_budget_line_version": expected_budget_line_version,
        },
        overrides,
    )


def receive_payload(stored_bay_code: str = "BAY-01", **overrides: Any) -> Dict[str, Any]:
    return _merge({"stored_bay_code": stored_bay_code}, overrides)


# ─── Reservation blocks ───────────────────────────────────────────────────────

def reservation_block_payload(
    program_id: str, expected_program_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "account_name": "Coastal Rowing Club",
            "arrival_date": "2026-12-01",
            "night_count": 4,
            "room_count": 19,
            "rate_cents": 20000,
            "expected_program_version": expected_program_version,
        },
        overrides,
    )


def resolve_contingency_payload(resolution: str, **overrides: Any) -> Dict[str, Any]:
    """``resolution`` is RELOCATE or CANCEL."""
    return _merge({"resolution": resolution}, overrides)


# ─── Punch-list items ─────────────────────────────────────────────────────────

def punch_item_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "description": "Lobby millwork gap",
            "severity": "MAJOR",
        },
        overrides,
    )


def punch_verify_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """``decision`` is VERIFY or REJECT."""
    return _merge({"decision": decision}, overrides)


def reopen_payload(reason: str = "Gap reappeared after settling", **overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)
