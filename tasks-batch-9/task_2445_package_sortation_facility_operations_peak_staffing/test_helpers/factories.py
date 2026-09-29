"""Request-payload builders.

Each builder returns a valid body for one creating or modifying operation, with
defaults chosen so the request succeeds against a bare facility. Keyword
overrides replace any field; passing `OMIT` as a value drops the field
altogether, which is how a test provokes a missing-required-field rejection.

Identifiers that must be unique inside their scope (`code`, `trailer_code`) get
a short random suffix so two rows created in the same test never collide.
"""

import uuid

# Sentinel meaning "leave this field out of the body entirely".
OMIT = object()

# The logical clock's startup value; every default window is placed around it so
# that a freshly booted server evaluates the window as current.
CLOCK_START = "2026-08-01T00:00:00Z"


def _apply(payload: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def unique_suffix(length: int = 6) -> str:
    """A short uppercase token for building unique codes."""
    return uuid.uuid4().hex[:length].upper()


def unique_center_code() -> str:
    """A center `code` inside the 3 to 10 character bound."""
    return f"SC{unique_suffix(6)}"


def unique_trailer_code() -> str:
    return f"TRL-{unique_suffix(8)}"


def unique_lane_code() -> str:
    return f"LN-{unique_suffix(6)}"


# ─── SortCenter (PRD §3.1) ────────────────────────────

def sort_center_payload(**overrides) -> dict:
    """A center on the mid throughput tier (automation 70) with a 10-body bench."""
    payload = {
        "code": unique_center_code(),
        "name": "Test Sort Center",
        "automation_utilization_pct": 70.00,
        "flex_pool_total": 10,
    }
    return _apply(payload, overrides)


def sort_center_patch_payload(automation_utilization_pct: float) -> dict:
    return {"automation_utilization_pct": automation_utilization_pct}


# ─── DockDoor (PRD §3.1) ──────────────────────────────

def dock_door_payload(**overrides) -> dict:
    """An inbound door numbered 1; `turnaround_buffer_min` is left to its default."""
    payload = {
        "door_number": 1,
        "kind": "INBOUND",
    }
    return _apply(payload, overrides)


def dock_door_patch_payload(**overrides) -> dict:
    payload = {}
    return _apply(payload, overrides)


# ─── SortChute (PRD §3.1) ─────────────────────────────

def sort_chute_payload(**overrides) -> dict:
    """A chute numbered 1 rated at 1,200 packages per hour."""
    payload = {
        "chute_number": 1,
        "throughput_pph": 1200,
    }
    return _apply(payload, overrides)


# ─── DestinationLane (PRD §3.1) ───────────────────────

def destination_lane_payload(**overrides) -> dict:
    payload = {
        "lane_code": unique_lane_code(),
        "region": "WEST",
        "service_class": "GROUND",
        "forecast_hourly_volume": 100,
    }
    return _apply(payload, overrides)


def destination_lane_patch_payload(**overrides) -> dict:
    payload = {}
    return _apply(payload, overrides)


# ─── ChuteAssignment (PRD §3.2) ───────────────────────

def chute_assignment_payload(
    chute_id: str, destination_lane_id: str, expected_chute_version: int, **overrides
) -> dict:
    """A day-long mapping whose window contains the clock's startup instant."""
    payload = {
        "chute_id": chute_id,
        "destination_lane_id": destination_lane_id,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-02T00:00:00Z",
        "expected_chute_version": expected_chute_version,
    }
    return _apply(payload, overrides)


# ─── TrailerAppointment (PRD §3.3) ────────────────────

def trailer_appointment_payload(
    sort_center_id: str, door_id: str, **overrides
) -> dict:
    payload = {
        "sort_center_id": sort_center_id,
        "door_id": door_id,
        "trailer_code": unique_trailer_code(),
        "window_start": "2026-08-01T06:00:00Z",
        "window_end": "2026-08-01T08:00:00Z",
        "priority_class": "STANDARD",
        "manifest_package_count": 1000,
    }
    return _apply(payload, overrides)


def jam_hold_payload(chute_id: str, **overrides) -> dict:
    payload = {
        "chute_id": chute_id,
        "jam_reason": "Belt jam on the induction line",
    }
    return _apply(payload, overrides)


def resume_unload_payload(chute_id: str, **overrides) -> dict:
    payload = {"chute_id": chute_id}
    return _apply(payload, overrides)


# ─── ShiftPlan (PRD §3.4, §3.5, §3.9) ─────────────────

def shift_plan_payload(**overrides) -> dict:
    """An eight-hour shift starting at the clock's startup instant."""
    payload = {
        "shift_date": "2026-08-01",
        "shift_window_start": "2026-08-01T00:00:00Z",
        "shift_window_end": "2026-08-01T08:00:00Z",
        "forecast_volume": 4000,
        "planned_core_headcount": 4,
        "planned_seasonal_headcount": 0,
        "labor_budget_cents": 1000000,
    }
    return _apply(payload, overrides)


def approve_payload(expected_center_version: int, **overrides) -> dict:
    payload = {"expected_center_version": expected_center_version}
    return _apply(payload, overrides)


def reject_payload(**overrides) -> dict:
    payload = {"rejection_reason": "Budget review requested"}
    return _apply(payload, overrides)


def revise_payload(**overrides) -> dict:
    payload = {}
    return _apply(payload, overrides)


def close_plan_payload(expected_center_version: int, **overrides) -> dict:
    payload = {"expected_center_version": expected_center_version}
    return _apply(payload, overrides)


# ─── Worker (PRD §3.6) ────────────────────────────────

def worker_payload(**overrides) -> dict:
    """A core hire whose hire date is one month before the clock's startup."""
    payload = {
        "full_name": "Test Associate",
        "hire_class": "CORE",
        "hire_date": "2026-07-01",
    }
    return _apply(payload, overrides)


def onboarding_event_payload(event_type: str, **overrides) -> dict:
    payload = {"event_type": event_type}
    return _apply(payload, overrides)


# ─── StaffAssignment (PRD §3.7) ───────────────────────

def staff_assignment_payload(
    shift_plan_id: str, worker_id: str, line_chute_id: str, **overrides
) -> dict:
    payload = {
        "shift_plan_id": shift_plan_id,
        "worker_id": worker_id,
        "line_chute_id": line_chute_id,
        "role_on_line": "PRIMARY_SORTER",
    }
    return _apply(payload, overrides)


# ─── OutboundLoad (PRD §3.8) ──────────────────────────

def outbound_load_payload(
    sort_center_id: str, door_id: str, destination_lane_id: str, **overrides
) -> dict:
    payload = {
        "sort_center_id": sort_center_id,
        "door_id": door_id,
        "destination_lane_id": destination_lane_id,
        "trailer_code": unique_trailer_code(),
        "trailer_cube_cuft": 1000.00,
        "dispatch_cut_time": "2026-08-02T00:00:00Z",
    }
    return _apply(payload, overrides)


def scan_packages_payload(**overrides) -> dict:
    """Every size-class count is optional and defaults to 0 server-side."""
    payload = {}
    return _apply(payload, overrides)


def seal_payload(**overrides) -> dict:
    payload = {"seal_code": f"SEAL-{unique_suffix(6)}"}
    return _apply(payload, overrides)


# ─── PackageException (PRD §3.8) ──────────────────────

def package_exception_payload(sort_center_id: str, **overrides) -> dict:
    payload = {
        "sort_center_id": sort_center_id,
        "exception_type": "DAMAGED",
        "package_count": 10,
    }
    return _apply(payload, overrides)


def resolve_exception_payload(resolution: str, **overrides) -> dict:
    payload = {"resolution": resolution}
    return _apply(payload, overrides)


# ─── InjuryReport (PRD §3.9) ──────────────────────────

def injury_report_payload(sort_center_id: str, worker_id: str, **overrides) -> dict:
    payload = {
        "sort_center_id": sort_center_id,
        "worker_id": worker_id,
        "severity": "FIRST_AID",
        "body_part": "HAND",
        "occurred_at": CLOCK_START,
    }
    return _apply(payload, overrides)


def close_injury_payload(lost_time_days: int = 0, **overrides) -> dict:
    payload = {"lost_time_days": lost_time_days}
    return _apply(payload, overrides)
