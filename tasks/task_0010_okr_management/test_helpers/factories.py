"""Payload factories — one per entity, input fields only.

PRD-faithful schemas only. Required vs optional follows PRD §3.
"""
import uuid


# --- Department (PRD §3.2) ---

def create_department_payload(**overrides) -> dict:
    """code, name required; parent_department_id optional (default null)."""
    suffix = uuid.uuid4().hex[:6]
    defaults = {
        "code": f"D{suffix.upper()}",
        "name": f"Department {suffix}",
    }
    defaults.update(overrides)
    return defaults


# --- User (PRD §2.1) ---

def create_user_payload(**overrides) -> dict:
    """email, full_name, department_id, role_type required; manager_id optional."""
    suffix = uuid.uuid4().hex[:8]
    defaults = {
        "email": f"user-{suffix}@example.com",
        "full_name": f"User {suffix}",
        "role_type": "EMPLOYEE",
    }
    defaults.update(overrides)
    return defaults


# --- Cycle (PRD §3.1) ---

# Monotonic counter so that successive calls to create_cycle_payload() produce
# non-overlapping [start_date, end_date) intervals, preventing ERR_CYCLE_OVERLAP
# in tests that share a session-scoped server. Each cycle is one calendar
# quarter; we walk forward through years and quarters as the counter increments.
_CYCLE_COUNTER = [0]
_CYCLE_BASE_YEAR = 2030


def _next_cycle_window():
    n = _CYCLE_COUNTER[0]
    _CYCLE_COUNTER[0] += 1
    year = _CYCLE_BASE_YEAR + (n // 4)
    quarter = (n % 4) + 1
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 3
    if end_month > 12:
        end_year = year + 1
        end_month = 1
    else:
        end_year = year
    start_date = f"{year:04d}-{start_month:02d}-01T00:00:00.000Z"
    end_date = f"{end_year:04d}-{end_month:02d}-01T00:00:00.000Z"
    return year, quarter, start_date, end_date


def create_cycle_payload(**overrides) -> dict:
    """cycle_code, year, quarter, start_date, end_date required."""
    suffix = uuid.uuid4().hex[:4].upper()
    year, quarter, start_date, end_date = _next_cycle_window()
    defaults = {
        "cycle_code": f"{year:04d}-Q{quarter}-{suffix}",
        "year": year,
        "quarter": quarter,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


# --- Objective (PRD §3.2) ---

def create_objective_payload(**overrides) -> dict:
    """cycle_id, level, owner_user_id, title, weight required.
    department_id required for DEPARTMENT/TEAM/INDIVIDUAL.
    description, confidential, parent_objective_id optional.
    """
    suffix = uuid.uuid4().hex[:6]
    defaults = {
        "title": f"Objective {suffix}",
        "level": "INDIVIDUAL",
        "weight": 1.0,
    }
    defaults.update(overrides)
    return defaults


# --- KeyResult (PRD §3.3) ---

def create_kr_payload(**overrides) -> dict:
    """title, measurement_type, weight required.
    For NUMERIC/PERCENTAGE: start_value, target_value required, milestones empty.
    For MILESTONE: milestones required, start/target/current null.
    """
    suffix = uuid.uuid4().hex[:6]
    defaults = {
        "title": f"KR {suffix}",
        "measurement_type": "NUMERIC",
        "start_value": 0,
        "target_value": 100,
        "weight": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_numeric_kr_payload(start_value=0, target_value=100, weight=1.0, **overrides) -> dict:
    return create_kr_payload(
        measurement_type="NUMERIC",
        start_value=start_value,
        target_value=target_value,
        weight=weight,
        **overrides,
    )


def create_percentage_kr_payload(start_value=0.0, target_value=1.0, weight=1.0, **overrides) -> dict:
    return create_kr_payload(
        measurement_type="PERCENTAGE",
        start_value=start_value,
        target_value=target_value,
        weight=weight,
        **overrides,
    )


def create_milestone_kr_payload(milestones=None, weight=1.0, **overrides) -> dict:
    if milestones is None:
        milestones = [
            {"label": "a", "completed": False},
            {"label": "b", "completed": False},
        ]
    payload = {
        "title": overrides.pop("title", f"KR {uuid.uuid4().hex[:6]}"),
        "measurement_type": "MILESTONE",
        "milestones": milestones,
        "weight": weight,
    }
    payload.update(overrides)
    return payload


# --- Progress (PRD §3.3) ---

def create_value_change_payload(new_value, comment=None) -> dict:
    p = {"update_type": "VALUE_CHANGE", "new_value": new_value}
    if comment is not None:
        p["comment"] = comment
    return p


def create_milestone_toggle_payload(milestone_index, milestone_completed, comment=None) -> dict:
    p = {
        "update_type": "MILESTONE_TOGGLE",
        "milestone_index": milestone_index,
        "milestone_completed": milestone_completed,
    }
    if comment is not None:
        p["comment"] = comment
    return p


# --- AlignmentLink (PRD §3.5) ---

def create_alignment_link_payload(upstream_objective_id, downstream_objective_id, dependency_type="SUPPORTS") -> dict:
    return {
        "upstream_objective_id": upstream_objective_id,
        "downstream_objective_id": downstream_objective_id,
        "dependency_type": dependency_type,
    }


def create_reject_link_payload(rejection_reason="out of scope") -> dict:
    return {"rejection_reason": rejection_reason}


# --- CoOwnership (PRD §3.6) ---

def create_co_owner_payload(co_owner_user_id, contribution_weight=0.3) -> dict:
    return {
        "co_owner_user_id": co_owner_user_id,
        "contribution_weight": contribution_weight,
    }


# --- AccessGrant (PRD §3.8) ---

def create_access_grant_payload(user_id) -> dict:
    return {"user_id": user_id}


# --- Reviews (PRD §3.7) ---

def self_submit_payload(self_score) -> dict:
    return {"self_score": self_score}


def manager_submit_payload(manager_score) -> dict:
    return {"manager_score": manager_score}


def calibrate_payload(calibration_score) -> dict:
    return {"calibration_score": calibration_score}


# --- ExternalEvent (PRD §3.9) ---

def create_external_event_payload(source_system="HR", external_event_id=None, event_type="EMPLOYEE_TRANSFERRED", payload=None) -> dict:
    if external_event_id is None:
        external_event_id = f"evt-{uuid.uuid4().hex[:8]}"
    if payload is None:
        payload = {}
    return {
        "source_system": source_system,
        "external_event_id": external_event_id,
        "event_type": event_type,
        "payload": payload,
    }
