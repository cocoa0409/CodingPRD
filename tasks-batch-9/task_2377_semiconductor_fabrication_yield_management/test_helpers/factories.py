"""Request-payload builders.

Each builder returns a dict containing only fields the PRD declares as
client-supplied input, with defaults that satisfy every declared constraint.
Pass ``**overrides`` to bend one field; pass ``None`` explicitly through
``drop=[...]`` to omit a field entirely and exercise a default or a
shape failure.
"""

from typing import Any, Dict, Iterable, List, Optional

from .constants import (
    DEFAULT_PARTICLE_LIMIT,
    DEFAULT_PM_INTERVAL_HOURS,
    DEFAULT_PURGE_BUFFER_HOURS,
)


def _finish(payload: Dict[str, Any], drop: Optional[Iterable[str]], overrides: Dict[str, Any]):
    for key in drop or ():
        payload.pop(key, None)
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Process flows and steps (PRD §3.1)
# --------------------------------------------------------------------------


def process_flow_payload(
    flow_code: str = "FLOW-A",
    product_family: str = "LOGIC_N5",
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {"flow_code": flow_code, "product_family": product_family}, drop, overrides
    )


def process_step_payload(
    recipe_id: str,
    step_seq: int = 10,
    step_name: str = "LITHO-1",
    standard_hours: float = 2.0,
    metrology_required: Optional[bool] = None,
    rework_target_step_id: Optional[str] = None,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recipe_id": recipe_id,
        "step_seq": step_seq,
        "step_name": step_name,
        "standard_hours": standard_hours,
    }
    if metrology_required is not None:
        payload["metrology_required"] = metrology_required
    if rework_target_step_id is not None:
        payload["rework_target_step_id"] = rework_target_step_id
    return _finish(payload, drop, overrides)


# --------------------------------------------------------------------------
# Recipes and change notices (PRD §3.2)
# --------------------------------------------------------------------------


def recipe_payload(
    recipe_code: str = "LITHO-100",
    tool_type: str = "LITHO",
    target_value: float = 50.0,
    qual_expiry_days: Optional[int] = 100,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recipe_code": recipe_code,
        "tool_type": tool_type,
        "target_value": target_value,
    }
    if qual_expiry_days is not None:
        payload["qual_expiry_days"] = qual_expiry_days
    return _finish(payload, drop, overrides)


def change_request_payload(
    change_class: str = "MINOR",
    proposed_target: float = 50.5,
    justification: str = "Process window centring",
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "change_class": change_class,
            "proposed_target": proposed_target,
            "justification": justification,
        },
        drop,
        overrides,
    )


def request_revision_payload(
    reviewer_comment: str = "Add split-lot data",
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish({"reviewer_comment": reviewer_comment}, drop, overrides)


def approve_payload(
    expected_recipe_version: int,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {"expected_recipe_version": expected_recipe_version}, drop, overrides
    )


# --------------------------------------------------------------------------
# Equipment and chambers (PRD §3.3)
# --------------------------------------------------------------------------


def equipment_payload(
    equipment_code: str = "LITHO-1",
    tool_type: str = "LITHO",
    pm_interval_hours: Optional[float] = DEFAULT_PM_INTERVAL_HOURS,
    purge_buffer_hours: Optional[float] = DEFAULT_PURGE_BUFFER_HOURS,
    hours_since_pm: Optional[float] = 0.0,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "equipment_code": equipment_code,
        "tool_type": tool_type,
    }
    if pm_interval_hours is not None:
        payload["pm_interval_hours"] = pm_interval_hours
    if purge_buffer_hours is not None:
        payload["purge_buffer_hours"] = purge_buffer_hours
    if hours_since_pm is not None:
        payload["hours_since_pm"] = hours_since_pm
    return _finish(payload, drop, overrides)


def chamber_payload(
    equipment_id: str,
    qualified_recipe_id: str,
    chamber_code: str = "CH_L1",
    particle_limit: Optional[float] = DEFAULT_PARTICLE_LIMIT,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "equipment_id": equipment_id,
        "qualified_recipe_id": qualified_recipe_id,
        "chamber_code": chamber_code,
    }
    if particle_limit is not None:
        payload["particle_limit"] = particle_limit
    return _finish(payload, drop, overrides)


def qualification_run_payload(
    qual_result: str = "PASS",
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish({"qual_result": qual_result}, drop, overrides)


def particle_reading_payload(
    particle_reading: float,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish({"particle_reading": particle_reading}, drop, overrides)


def pm_start_payload(
    pm_reason: str = "Scheduled preventive maintenance",
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish({"pm_reason": pm_reason}, drop, overrides)


# --------------------------------------------------------------------------
# Operators (PRD §3.6)
# --------------------------------------------------------------------------


def operator_payload(
    badge_id: str = "OP-001",
    full_name: str = "Ada Fabrizio",
    certified_tool_types: Optional[List[str]] = None,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "badge_id": badge_id,
            "full_name": full_name,
            "certified_tool_types": list(
                certified_tool_types
                if certified_tool_types is not None
                else ["LITHO", "ETCH", "CMP"]
            ),
        },
        drop,
        overrides,
    )


def gown_patch(gown_state: str = "GOWNED") -> Dict[str, Any]:
    return {"gown_state": gown_state}


def cert_patch(cert_status: str) -> Dict[str, Any]:
    return {"cert_status": cert_status}


# --------------------------------------------------------------------------
# Wafer start plans (PRD §3.4)
# --------------------------------------------------------------------------


def plan_payload(
    flow_id: str,
    product_family: str = "LOGIC_N5",
    week_start_date: str = "2026-08-03T00:00:00Z",
    planned_wafer_starts: int = 10,
    capacity_budget_hours: float = 100.0,
    cycle_time_target_days: float = 30.0,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "flow_id": flow_id,
            "product_family": product_family,
            "week_start_date": week_start_date,
            "planned_wafer_starts": planned_wafer_starts,
            "capacity_budget_hours": capacity_budget_hours,
            "cycle_time_target_days": cycle_time_target_days,
        },
        drop,
        overrides,
    )


# --------------------------------------------------------------------------
# Lots (PRD §3.5, §3.8)
# --------------------------------------------------------------------------


def lot_payload(
    plan_id: str,
    flow_id: str,
    lot_number: str = "LOT-001",
    wafer_count: int = 3,
    priority_class: Optional[str] = None,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "flow_id": flow_id,
        "lot_number": lot_number,
        "wafer_count": wafer_count,
    }
    if priority_class is not None:
        payload["priority_class"] = priority_class
    return _finish(payload, drop, overrides)


def release_lot_payload(
    expected_plan_version: int,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish({"expected_plan_version": expected_plan_version}, drop, overrides)


def split_payload(
    expected_lot_version: int,
    split_wafer_count: int,
    lot_number: str = "LOT-001-S1",
    priority_class: Optional[str] = None,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_lot_version": expected_lot_version,
        "split_wafer_count": split_wafer_count,
        "lot_number": lot_number,
    }
    if priority_class is not None:
        payload["priority_class"] = priority_class
    return _finish(payload, drop, overrides)


# --------------------------------------------------------------------------
# Step runs (PRD §3.6)
# --------------------------------------------------------------------------


def step_run_payload(
    lot_id: str,
    step_id: str,
    operator_id: str,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {"lot_id": lot_id, "step_id": step_id, "operator_id": operator_id},
        drop,
        overrides,
    )


def abort_payload(
    abort_reason: str = "Chamber excursion",
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish({"abort_reason": abort_reason}, drop, overrides)


# --------------------------------------------------------------------------
# SPC charts and metrology (PRD §3.7)
# --------------------------------------------------------------------------


def spc_chart_payload(
    step_id: str,
    param_name: str = "ETCH_DEPTH",
    target: float = 100.0,
    sigma: float = 2.0,
    usl: float = 110.0,
    lsl: float = 90.0,
    ucl: float = 106.0,
    lcl: float = 94.0,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "step_id": step_id,
            "param_name": param_name,
            "target": target,
            "sigma": sigma,
            "usl": usl,
            "lsl": lsl,
            "ucl": ucl,
            "lcl": lcl,
        },
        drop,
        overrides,
    )


def measurement_payload(
    step_run_id: str,
    spc_chart_id: str,
    measured_value: float,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "step_run_id": step_run_id,
            "spc_chart_id": spc_chart_id,
            "measured_value": measured_value,
        },
        drop,
        overrides,
    )


# --------------------------------------------------------------------------
# Excursion handling (PRD §3.8)
# --------------------------------------------------------------------------


def contain_payload(
    containment_scope: str,
    chamber_id: Optional[str] = None,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"containment_scope": containment_scope}
    if chamber_id is not None:
        payload["chamber_id"] = chamber_id
    return _finish(payload, drop, overrides)


def disposition_payload(
    disposition: str,
    root_cause_note: str = "Chamber drift confirmed by cross-section",
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {"disposition": disposition, "root_cause_note": root_cause_note},
        drop,
        overrides,
    )


# --------------------------------------------------------------------------
# Die sort (PRD §3.9)
# --------------------------------------------------------------------------


def wafer_result(
    wafer_slot: int,
    tested_die: int,
    good_die: int,
    edge_ring_fails: int = 0,
    center_cluster_fails: int = 0,
    scratch_line_fails: int = 0,
    parametric_shift_fails: int = 0,
) -> Dict[str, Any]:
    """One element of ``wafer_results``.

    The four failure counts must sum to exactly ``tested_die - good_die`` for
    the set to be accepted, so callers that want a rejection deliberately
    unbalance them.
    """
    return {
        "wafer_slot": wafer_slot,
        "tested_die": tested_die,
        "good_die": good_die,
        "edge_ring_fails": edge_ring_fails,
        "center_cluster_fails": center_cluster_fails,
        "scratch_line_fails": scratch_line_fails,
        "parametric_shift_fails": parametric_shift_fails,
    }


def die_sort_payload(
    lot_id: str,
    wafer_results: List[Dict[str, Any]],
    gross_die_per_wafer: int = 100,
    baseline_yield: float = 0.92,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "lot_id": lot_id,
            "gross_die_per_wafer": gross_die_per_wafer,
            "baseline_yield": baseline_yield,
            "wafer_results": wafer_results,
        },
        drop,
        overrides,
    )


def bin_payload(
    premium_target_die: int,
    standard_target_die: int,
    drop: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "premium_target_die": premium_target_die,
            "standard_target_die": standard_target_die,
        },
        drop,
        overrides,
    )
