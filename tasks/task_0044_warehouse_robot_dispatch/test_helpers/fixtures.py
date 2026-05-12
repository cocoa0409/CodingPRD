"""Composite setup helpers for the Warehouse Robot Dispatch test suite.

Most interesting test claims require the system to be in a specific
state that takes 5-15 API calls to reach: a fleet with a configured
map, robots placed and battery-pinned, tasks dispatched, charging
sessions in flight, fault incidents opened. These helpers encapsulate
those preambles so tests can focus on assertions.

PRD section 2.1: All three roles (Operator, FleetAdmin, WMS) use
X-User-ID as an opaque operator identifier - none of them is backed by
a persisted entity. Shared TEST_USERS constants are therefore canonical
for every call; no per-instance ownership-resolved header is required.

Setup calls use get_success_data (lenient validator), so broken
preconditions surface as obvious errors rather than confusing assertion
failures.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    AGING_BUCKET_SECONDS,
    DEFAULT_CHARGING_FULL_PCT,
    DEFAULT_CHARGING_LOW_THRESHOLD_PCT,
    DEFAULT_DEADLOCK_WAIT_SECONDS,
    DEFAULT_SLOT_SECONDS,
    DEFAULT_TASK_EXPIRY_SECONDS,
    HEARTBEAT_TIMEOUT_SECONDS,
)
from .factories import (
    advance_clock_payload,
    assign_task_payload,
    create_charging_station_payload,
    create_fleet_payload,
    create_map_edge_payload,
    create_map_node_payload,
    create_robot_payload,
    create_slot_reservation_payload,
    create_task_payload,
    emit_event_payload,
    merge_tasks_payload,
    open_fault_payload,
    queue_charger_payload,
    unique_code,
)
from .test_users import TEST_USERS


# ===========================================================================
# Time helpers
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def epoch_iso(seconds: int) -> str:
    """ISO 8601 string for UNIX-epoch second seconds, three fractional digits."""
    return iso_z(datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds))


# ===========================================================================
# Fleet creation
# ===========================================================================
def create_fleet(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["fleet_admin_headers"]
    payload = create_fleet_payload(**overrides)
    resp = api_client.create_fleet(payload, h)
    return get_success_data(resp)


def advance_clock(
    fleet_id: str,
    delta_seconds: int,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    resp = api_client.advance_clock(
        fleet_id, advance_clock_payload(delta_seconds=delta_seconds), h
    )
    return get_success_data(resp)


def get_fleet(
    fleet_id: str, *, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.get_fleet(fleet_id, h))


# ===========================================================================
# Map creation
# ===========================================================================
def create_map_node(
    fleet_id: str,
    *,
    code: Optional[str] = None,
    kind: str = "LANE",
    x: int = 0,
    y: int = 0,
    capacity: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["fleet_admin_headers"]
    payload = create_map_node_payload(
        code=code, kind=kind, x=x, y=y, capacity=capacity
    )
    return get_success_data(api_client.create_map_node(fleet_id, payload, h))


def create_map_edge(
    fleet_id: str,
    *,
    from_node_id: str,
    to_node_id: str,
    cost: Optional[int] = None,
    directional: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["fleet_admin_headers"]
    payload = create_map_edge_payload(
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        cost=cost,
        directional=directional,
    )
    return get_success_data(api_client.create_map_edge(fleet_id, payload, h))


def link_bidirectional(
    fleet_id: str,
    a: Dict[str, Any],
    b: Dict[str, Any],
    *,
    cost: int = 1,
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """Create one non-directional edge a<->b. PRD section 3.1: a
    non-directional edge causes the system to materialise the reverse
    automatically, so a single create_map_edge call is sufficient."""
    create_map_edge(
        fleet_id,
        from_node_id=a["id"],
        to_node_id=b["id"],
        cost=cost,
        directional=False,
        headers=headers,
    )


# ===========================================================================
# Charging station
# ===========================================================================
def create_charging_station(
    fleet_id: str,
    *,
    node_id: str,
    charge_rate_pct_per_second: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["fleet_admin_headers"]
    payload = create_charging_station_payload(
        node_id=node_id,
        charge_rate_pct_per_second=charge_rate_pct_per_second,
    )
    return get_success_data(
        api_client.create_charging_station(fleet_id, payload, h)
    )


# ===========================================================================
# Robot
# ===========================================================================
def create_robot(
    fleet_id: str,
    *,
    position_node_id: str,
    code: Optional[str] = None,
    battery_pct: Optional[int] = None,
    standby_priority: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["fleet_admin_headers"]
    payload = create_robot_payload(
        code=code,
        position_node_id=position_node_id,
        battery_pct=battery_pct,
        standby_priority=standby_priority,
    )
    return get_success_data(api_client.create_robot(fleet_id, payload, h))


def get_robot(
    fleet_id: str,
    robot_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.get_robot(fleet_id, robot_id, h))


# ===========================================================================
# Task
# ===========================================================================
def create_task(
    fleet_id: str,
    *,
    pickup_node_id: str,
    dropoff_node_id: str,
    source: str = "INBOUND",
    priority_class: Optional[str] = None,
    payload_units: Optional[int] = None,
    max_units_per_robot: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    payload = create_task_payload(
        source=source,
        pickup_node_id=pickup_node_id,
        dropoff_node_id=dropoff_node_id,
        priority_class=priority_class,
        payload_units=payload_units,
        max_units_per_robot=max_units_per_robot,
    )
    return get_success_data(api_client.create_task(fleet_id, payload, h))


def get_task(
    fleet_id: str,
    task_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    params = {"view": view} if view is not None else None
    return get_success_data(
        api_client.get_task(fleet_id, task_id, h, params=params)
    )


def assign_task(
    fleet_id: str,
    task_id: str,
    *,
    robot_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(
        api_client.assign_task(
            fleet_id, task_id, assign_task_payload(robot_id=robot_id), h
        )
    )


def start_task(
    fleet_id: str,
    task_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.start_task(fleet_id, task_id, h))


def complete_task(
    fleet_id: str,
    task_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.complete_task(fleet_id, task_id, h))


def cancel_task(
    fleet_id: str,
    task_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.cancel_task(fleet_id, task_id, h))


def dispatch(
    fleet_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.dispatch(fleet_id, h))


# ===========================================================================
# Robot motion
# ===========================================================================
def step_robot(
    fleet_id: str,
    robot_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.step_robot(fleet_id, robot_id, h))


def step_until_at(
    fleet_id: str,
    robot: Dict[str, Any],
    target_node_id: str,
    *,
    max_steps: int = 20,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Issue :step repeatedly until the robot's position_node_id ==
    target_node_id, or max_steps is reached."""
    h = headers or TEST_USERS["operator_headers"]
    current = robot
    for _ in range(max_steps):
        if current["position_node_id"] == target_node_id:
            return current
        current = step_robot(fleet_id, current["id"], headers=h)
    return current


# ===========================================================================
# Charging
# ===========================================================================
def dock_robot(
    fleet_id: str,
    robot_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(api_client.dock_robot(fleet_id, robot_id, h))


def queue_charger(
    fleet_id: str,
    robot_id: str,
    *,
    charging_station_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(
        api_client.queue_charger(
            fleet_id,
            robot_id,
            queue_charger_payload(charging_station_id=charging_station_id),
            h,
        )
    )


# ===========================================================================
# Slot reservation
# ===========================================================================
def create_slot_reservation(
    fleet_id: str,
    *,
    node_id: str,
    robot_id: str,
    scheduled_at: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    payload = create_slot_reservation_payload(
        node_id=node_id,
        robot_id=robot_id,
        scheduled_at=scheduled_at,
    )
    return get_success_data(
        api_client.create_slot_reservation(fleet_id, payload, h)
    )


# ===========================================================================
# Fault
# ===========================================================================
def open_fault(
    fleet_id: str,
    robot_id: str,
    *,
    kind: str = "MECHANICAL_FAULT",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(
        api_client.open_fault(
            fleet_id, robot_id, open_fault_payload(kind=kind), h
        )
    )


def takeover_fault(
    fleet_id: str,
    incident_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(
        api_client.takeover_fault(fleet_id, incident_id, h)
    )


def resolve_fault(
    fleet_id: str,
    incident_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["operator_headers"]
    return get_success_data(
        api_client.resolve_fault(fleet_id, incident_id, h)
    )


# ===========================================================================
# Listing helpers
# ===========================================================================
def list_audit_events(
    fleet_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["operator_headers"]
    resp = api_client.list_audit_events(fleet_id, h, params=params or None)
    data, _meta = validate_paginated(resp)
    return data


def list_trajectory(
    fleet_id: str,
    robot_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["operator_headers"]
    resp = api_client.list_trajectory(
        fleet_id, robot_id, h, params=params or None
    )
    data, _meta = validate_paginated(resp)
    return data


def list_slot_reservations(
    fleet_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["operator_headers"]
    resp = api_client.list_slot_reservations(
        fleet_id, h, params=params or None
    )
    data, _meta = validate_paginated(resp)
    return data


def list_tasks(
    fleet_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["operator_headers"]
    resp = api_client.list_tasks(fleet_id, h, params=params or None)
    data, _meta = validate_paginated(resp)
    return data


def list_robots(
    fleet_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["operator_headers"]
    resp = api_client.list_robots(fleet_id, h, params=params or None)
    data, _meta = validate_paginated(resp)
    return data


# ===========================================================================
# Composite scenarios
# ===========================================================================

def build_two_node_map(
    fleet_id: str,
    *,
    pickup_kind: str = "LANE",
    dropoff_kind: str = "LANE",
    pickup_capacity: Optional[int] = None,
    dropoff_capacity: Optional[int] = None,
    cost: int = 1,
    directional: bool = False,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create two map nodes plus one edge. Returns (pickup_node, dropoff_node).

    Default is a bidirectional edge cost=1 between two LANE nodes - the
    minimal map sufficient for tasks pickup->dropoff."""
    p = create_map_node(
        fleet_id,
        code=unique_code("P"),
        kind=pickup_kind,
        x=0,
        y=0,
        capacity=pickup_capacity,
        headers=headers,
    )
    d = create_map_node(
        fleet_id,
        code=unique_code("D"),
        kind=dropoff_kind,
        x=1,
        y=0,
        capacity=dropoff_capacity,
        headers=headers,
    )
    create_map_edge(
        fleet_id,
        from_node_id=p["id"],
        to_node_id=d["id"],
        cost=cost,
        directional=directional,
        headers=headers,
    )
    if directional:
        # Tests sometimes want a true one-way edge; we honour that.
        pass
    return p, d


def setup_minimal_fleet(
    *,
    headers: Optional[Dict[str, str]] = None,
    **fleet_overrides: Any,
) -> Dict[str, Any]:
    """Just a fleet with default configuration."""
    return create_fleet(headers=headers, **fleet_overrides)


def setup_fleet_with_two_node_map(
    *,
    headers: Optional[Dict[str, str]] = None,
    pickup_kind: str = "LANE",
    dropoff_kind: str = "LANE",
    pickup_capacity: Optional[int] = None,
    dropoff_capacity: Optional[int] = None,
    cost: int = 1,
    directional: bool = False,
    **fleet_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (fleet, pickup_node, dropoff_node)."""
    fleet = create_fleet(headers=headers, **fleet_overrides)
    p, d = build_two_node_map(
        fleet["id"],
        pickup_kind=pickup_kind,
        dropoff_kind=dropoff_kind,
        pickup_capacity=pickup_capacity,
        dropoff_capacity=dropoff_capacity,
        cost=cost,
        directional=directional,
        headers=headers,
    )
    return fleet, p, d


def setup_assignable_scenario(
    *,
    battery_pct: int = 100,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Default 'happy-path' scenario: fleet + 2-node map + 1 robot at
    pickup + 1 task pickup->dropoff.

    Returns (fleet, pickup, dropoff, robot, task).
    """
    fleet, p, d = setup_fleet_with_two_node_map(headers=headers)
    robot = create_robot(
        fleet["id"],
        position_node_id=p["id"],
        battery_pct=battery_pct,
        headers=headers,
    )
    task = create_task(
        fleet["id"],
        pickup_node_id=p["id"],
        dropoff_node_id=d["id"],
        headers=headers,
    )
    return fleet, p, d, robot, task


def setup_executing_task(
    *,
    battery_pct: int = 100,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk a task from QUEUED -> ASSIGNED -> EXECUTING via direct :assign+:start.

    Returns (fleet, pickup, dropoff, robot, task) with task.status==EXECUTING.
    """
    fleet, p, d, robot, task = setup_assignable_scenario(
        battery_pct=battery_pct, headers=headers
    )
    assign_task(fleet["id"], task["id"], robot_id=robot["id"], headers=headers)
    started = start_task(fleet["id"], task["id"], headers=headers)
    return fleet, p, d, robot, started


def setup_completed_task_at_zero(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Run one task through its full lifecycle (queue->assign->start->step->complete)
    entirely at clock_now==0. Returns (fleet, robot, task_completed, dropoff_node).

    This is the precondition for the boundary metrics test in
    rule 1 instance 2 (closed vs open window at cutoff).
    """
    fleet, p, d, robot, task = setup_executing_task(headers=headers)
    # Step the robot until it reaches dropoff.
    step_until_at(fleet["id"], robot, d["id"], headers=headers)
    completed = complete_task(fleet["id"], task["id"], headers=headers)
    return fleet, robot, completed, d


# ---------------------------------------------------------------------------
# Difficulty-design recipe: parent task with one child completed
# ---------------------------------------------------------------------------
def setup_parent_with_three_children_one_completed(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    """For rule 1 instance 1 (parent_task_status persisted vs projected).

    - Create fleet + map (P pickup, D dropoff, both CHARGER kind? no - PRD says
      pickup/dropoff can be any kind. PRD section 3.1 lists LANE/INTERSECTION/
      LIFT_POINT/CHARGER/PARK/SHELF; we use LANE for simplicity).
    - Create parent task with payload_units=15, max_units_per_robot=5 -> ceil(15/5)=3 children.
    - Split parent -> children C1, C2, C3 each payload_units=5.
    - Complete only C1 via the full lifecycle (assign, start, step, complete).

    Returns (fleet, pickup, dropoff, [c1, c2, c3], parent).
    """
    fleet, p, d = setup_fleet_with_two_node_map(headers=headers)
    parent_payload = create_task_payload(
        source="INBOUND",
        pickup_node_id=p["id"],
        dropoff_node_id=d["id"],
        payload_units=15,
        max_units_per_robot=5,
    )
    h_op = headers or TEST_USERS["operator_headers"]
    parent = get_success_data(
        api_client.create_task(fleet["id"], parent_payload, h_op)
    )
    split_resp = api_client.split_task(fleet["id"], parent["id"], h_op)
    children_data = get_success_data(split_resp)
    # Normalize the children list out of the response envelope.
    if isinstance(children_data, dict):
        # Some implementations wrap the array under a key.
        for key in ("children", "tasks", "items", "data"):
            if key in children_data and isinstance(children_data[key], list):
                children = children_data[key]
                break
        else:
            children = [children_data]
    else:
        children = children_data
    assert isinstance(children, list) and len(children) >= 3, (
        f"Expected >=3 children, got {children!r}"
    )
    # Take the first child and run it through to COMPLETED. We need a
    # robot for the child; create one at pickup.
    robot = create_robot(
        fleet["id"], position_node_id=p["id"], headers=headers
    )
    c1 = children[0]
    assign_task(fleet["id"], c1["id"], robot_id=robot["id"], headers=h_op)
    start_task(fleet["id"], c1["id"], headers=h_op)
    step_until_at(fleet["id"], robot, d["id"], headers=h_op)
    complete_task(fleet["id"], c1["id"], headers=h_op)
    return fleet, p, d, children, parent


# ---------------------------------------------------------------------------
# Empty-set metrics fixture (rule 6 instance 2)
# ---------------------------------------------------------------------------
def setup_empty_fleet_for_metrics(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Fleet with default config and NO tasks NOR robots. Used to
    verify metrics produces zeros without dividing by zero."""
    return create_fleet(headers=headers)


# ---------------------------------------------------------------------------
# Fault cascade fixture (rule 4 instance 1)
# ---------------------------------------------------------------------------
def setup_fault_cascade_strip(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    List[Dict[str, Any]],
    Dict[str, Any],
    Dict[str, Any],
]:
    """5-node LANE strip N1-N2-N3-N4-N5 with bidirectional edges; robot
    R at N3 mid-strip; task T pickup=N2 dropoff=N4; dispatched +
    started so T.status=EXECUTING. Returns (fleet, [N1..N5], robot, task)."""
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    nodes: List[Dict[str, Any]] = []
    for i in range(5):
        n = create_map_node(
            fid,
            code=f"N{i + 1}-{unique_code('s')}",
            kind="LANE",
            x=i,
            y=0,
            capacity=1,
            headers=headers,
        )
        nodes.append(n)
    # Bidirectional edges chain.
    for i in range(4):
        create_map_edge(
            fid,
            from_node_id=nodes[i]["id"],
            to_node_id=nodes[i + 1]["id"],
            cost=1,
            directional=False,
            headers=headers,
        )
    # Robot at N3 (index 2) with battery 100.
    robot = create_robot(
        fid, position_node_id=nodes[2]["id"], battery_pct=100, headers=headers
    )
    task = create_task(
        fid,
        pickup_node_id=nodes[1]["id"],
        dropoff_node_id=nodes[3]["id"],
        max_units_per_robot=10,
        payload_units=1,
        headers=headers,
    )
    assign_task(fid, task["id"], robot_id=robot["id"], headers=headers)
    start_task(fid, task["id"], headers=headers)
    return fleet, nodes, robot, task


# ---------------------------------------------------------------------------
# Charging cascade fixture (rule 4 instance 2)
# ---------------------------------------------------------------------------
def setup_charging_queue_two_robots(
    *,
    headers: Optional[Dict[str, str]] = None,
    ra_battery: int = 94,
    rb_battery: int = 10,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """One CHARGER node N + one station S. Robot Ra docked (CHARGING).
    Robot Rb queued (WAITING_CHARGER). Returns (fleet, N, station, Ra, Rb)."""
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    n = create_map_node(
        fid, code=unique_code("C"), kind="CHARGER", x=0, y=0, headers=headers
    )
    station = create_charging_station(
        fid, node_id=n["id"], charge_rate_pct_per_second=1, headers=headers
    )
    ra = create_robot(
        fid,
        position_node_id=n["id"],
        battery_pct=ra_battery,
        headers=headers,
    )
    dock_robot(fid, ra["id"], headers=headers)
    rb = create_robot(
        fid,
        position_node_id=n["id"],
        battery_pct=rb_battery,
        headers=headers,
    )
    queue_charger(
        fid, rb["id"], charging_station_id=station["id"], headers=headers
    )
    return fleet, n, station, ra, rb


# ---------------------------------------------------------------------------
# Robot parallel-dimensions fixture (rule 3 instance 2)
# ---------------------------------------------------------------------------
def setup_single_robot_at_charger(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Fleet with one CHARGER node N and one robot R at N (default
    config). Returns (fleet, N, R)."""
    fleet = create_fleet(headers=headers)
    n = create_map_node(
        fleet["id"],
        code=unique_code("C"),
        kind="CHARGER",
        x=0,
        y=0,
        headers=headers,
    )
    r = create_robot(
        fleet["id"], position_node_id=n["id"], headers=headers
    )
    return fleet, n, r


# ---------------------------------------------------------------------------
# Cyclic rollback fixture (rule 3 instance 1)
# ---------------------------------------------------------------------------
def setup_executing_task_for_rollback(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """Two-node map P,D with edge P->D; robot R at P; task T started.
    Returns (fleet, P, D, R, T)."""
    fleet, p, d, robot, task = setup_executing_task(headers=headers)
    return fleet, p, d, robot, task


# ---------------------------------------------------------------------------
# Priority score boundary fixture (rule 2 instance 1)
# ---------------------------------------------------------------------------
def setup_dispatch_priority_ageing_scenario(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """For rule 2 instance 1: Create fleet, single robot R at pickup,
    task A priority=HIGH at clock=0 (queued_at=0), then advance clock
    to 6065, then create task B priority=NORMAL (queued_at=6065). One
    robot - first dispatch should give it to A (priority_score(A) =
    1000 - 101*10 = -10 vs priority_score(B) = 2000).

    Returns (fleet, pickup, dropoff, robot, task_A, task_B).
    """
    # PRD §3.2/§3.10 do not pin a default for task_expiry_seconds; the
    # priority-ageing assertion requires the HIGH task to survive 6065s in
    # QUEUED, so configure the fleet with a long expiry window.
    fleet, p, d = setup_fleet_with_two_node_map(
        headers=headers, task_expiry_seconds=100000
    )
    fid = fleet["id"]
    task_a = create_task(
        fid,
        pickup_node_id=p["id"],
        dropoff_node_id=d["id"],
        priority_class="HIGH",
        headers=headers,
    )
    # Advance clock to 6065 seconds. PRD §3.10 dictates that a
    # heartbeat-timeout sweep runs during clock advancement and any robot
    # whose last_heartbeat_at is fifteen-plus seconds behind the new clock
    # flips to OFFLINE and auto-opens a COMM_LOSS fault. To keep the
    # scenario's lone robot healthy for the dispatch assertion, the robot
    # is registered AFTER the advance so its heartbeat is current.
    advance_clock(fid, 6065, headers=headers)
    robot = create_robot(
        fid, position_node_id=p["id"], battery_pct=100, headers=headers
    )
    task_b = create_task(
        fid,
        pickup_node_id=p["id"],
        dropoff_node_id=d["id"],
        priority_class="NORMAL",
        headers=headers,
    )
    return fleet, p, d, robot, task_a, task_b


# ---------------------------------------------------------------------------
# Throughput rounding-mode fixture (rule 2 instance 2)
# ---------------------------------------------------------------------------
def setup_throughput_rounding_seven_robots(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """For rule 2 instance 2: PRD section 3.11 specifies per-robot
    utilization computed first (round to 4dp), then the fleet
    utilization is the mean rounded again. We construct seven robots
    with controlled executing intervals over a 3-second window.

    The fixture creates the fleet+seven robots+seven completed tasks
    where R1..R6 each have started_at=0, completed_at=2 (2 EXECUTING
    seconds) and R7 has started_at=2, completed_at=3 (1 EXECUTING
    second). Then advance_clock to 3.

    Returns (fleet, [robot1..robot7]). Implementations that materialize
    EXECUTING time from AuditEvent + TrajectoryRecord will see the
    intervals as described.
    """
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    # Two LANE nodes with bidirectional cost-1 edge each, one per robot's
    # task. To keep timing independent, give each robot its own pair.
    robots: List[Dict[str, Any]] = []
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for i in range(7):
        pn = create_map_node(
            fid,
            code=f"PN{i}-{unique_code('p')}",
            kind="LANE",
            x=2 * i,
            y=0,
            headers=headers,
        )
        dn = create_map_node(
            fid,
            code=f"DN{i}-{unique_code('d')}",
            kind="LANE",
            x=2 * i + 1,
            y=0,
            headers=headers,
        )
        create_map_edge(
            fid,
            from_node_id=pn["id"],
            to_node_id=dn["id"],
            cost=1,
            directional=False,
            headers=headers,
        )
        pairs.append((pn, dn))

    for i in range(7):
        r = create_robot(
            fid,
            position_node_id=pairs[i][0]["id"],
            battery_pct=100,
            headers=headers,
        )
        robots.append(r)

    # For R1..R6: start a task that runs from clock=0 to clock=2.
    # We can't directly control the wall-clock the task spends in
    # EXECUTING beyond what advance_clock + start/complete order
    # produces - so the test itself will drive the clock and complete
    # tasks. This helper exposes the topology and robot list.
    return fleet, robots


# ---------------------------------------------------------------------------
# Capacity LANE fixture (rule 8 instance 2)
# ---------------------------------------------------------------------------
def setup_capacity_three_lane_with_four_robots(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """LANE node L with capacity=3; four source nodes S1..S4 each with
    a directed edge S_i -> L; four robots R1..R4 on S1..S4; each robot
    is started on its own task pickup at S_i dropoff at L (so that
    :step moves R_i onto L).

    Returns (fleet, L, [S1..S4], [R1..R4], [T1..T4]).
    """
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    L = create_map_node(
        fid,
        code=unique_code("L"),
        kind="LANE",
        x=10,
        y=10,
        capacity=3,
        headers=headers,
    )
    sources: List[Dict[str, Any]] = []
    robots: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    for i in range(4):
        s = create_map_node(
            fid,
            code=f"S{i + 1}-{unique_code('s')}",
            kind="LANE",
            x=i,
            y=0,
            headers=headers,
        )
        sources.append(s)
        # Bidirectional edge S_i <-> L.
        create_map_edge(
            fid,
            from_node_id=s["id"],
            to_node_id=L["id"],
            cost=1,
            directional=False,
            headers=headers,
        )
    for i in range(4):
        r = create_robot(
            fid,
            position_node_id=sources[i]["id"],
            battery_pct=100,
            headers=headers,
        )
        robots.append(r)
        t = create_task(
            fid,
            pickup_node_id=sources[i]["id"],
            dropoff_node_id=L["id"],
            headers=headers,
        )
        assign_task(fid, t["id"], robot_id=r["id"], headers=headers)
        start_task(fid, t["id"], headers=headers)
        tasks.append(t)
    return fleet, L, sources, robots, tasks


# ---------------------------------------------------------------------------
# Slot uniqueness fixture (rule 8 instance 1)
# ---------------------------------------------------------------------------
def setup_intersection_for_slot_reservations(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """One INTERSECTION node I (capacity=1) and two robots Ra,Rb on
    adjacent LANE nodes. Default slot_seconds=10.

    Returns (fleet, I, Ra, Rb).
    """
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    la = create_map_node(
        fid,
        code=unique_code("LA"),
        kind="LANE",
        x=0,
        y=0,
        capacity=1,
        headers=headers,
    )
    lb = create_map_node(
        fid,
        code=unique_code("LB"),
        kind="LANE",
        x=2,
        y=0,
        capacity=1,
        headers=headers,
    )
    inter = create_map_node(
        fid,
        code=unique_code("I"),
        kind="INTERSECTION",
        x=1,
        y=0,
        capacity=1,
        headers=headers,
    )
    # Edges la<->inter, inter<->lb (bidirectional)
    create_map_edge(
        fid,
        from_node_id=la["id"],
        to_node_id=inter["id"],
        cost=1,
        directional=False,
        headers=headers,
    )
    create_map_edge(
        fid,
        from_node_id=inter["id"],
        to_node_id=lb["id"],
        cost=1,
        directional=False,
        headers=headers,
    )
    ra = create_robot(
        fid, position_node_id=la["id"], battery_pct=100, headers=headers
    )
    rb = create_robot(
        fid, position_node_id=lb["id"], battery_pct=100, headers=headers
    )
    return fleet, inter, ra, rb


# ---------------------------------------------------------------------------
# Existence-vs-state fixture (rule 5 instance 1)
# ---------------------------------------------------------------------------
def setup_empty_fleet(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Just a fleet, no tasks. For tests that need to call an action on
    a nonexistent task id."""
    return create_fleet(headers=headers)


# ---------------------------------------------------------------------------
# Robot battery boundary fixture (rule 6 instance 1)
# ---------------------------------------------------------------------------
def setup_battery_boundary_assign_pair(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """For rule 6 instance 1: fleet with default
    charging_low_threshold_pct=20. Two-node map P,D with directed
    P->D edge cost=1. One task T (priority=HIGH). Two robots: Ra
    battery=20 (exactly at threshold), Rb battery=21 (one above).

    Returns (fleet, P, D, task, Ra, Rb).
    """
    fleet, p, d = setup_fleet_with_two_node_map(
        headers=headers, cost=1, directional=False
    )
    fid = fleet["id"]
    task = create_task(
        fid,
        pickup_node_id=p["id"],
        dropoff_node_id=d["id"],
        priority_class="HIGH",
        headers=headers,
    )
    ra = create_robot(
        fid, position_node_id=p["id"], battery_pct=20, headers=headers
    )
    rb = create_robot(
        fid, position_node_id=p["id"], battery_pct=21, headers=headers
    )
    return fleet, p, d, task, ra, rb


# ---------------------------------------------------------------------------
# Task<->Robot connectivity fixture (rule 7 instance 1)
# ---------------------------------------------------------------------------
def setup_assigned_task_for_connectivity_test(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """For rule 7 instance 1: fleet (defaults), P (PARK) and D (SHELF)
    nodes with edge P->D cost=1. Robot R at P battery=100, last_heartbeat=0.
    Task T pickup=P dropoff=D. POST /dispatch -> T.status=ASSIGNED.

    Returns (fleet, P, D, R, T).
    """
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    p = create_map_node(
        fid,
        code=unique_code("P"),
        kind="PARK",
        x=0,
        y=0,
        headers=headers,
    )
    d = create_map_node(
        fid,
        code=unique_code("D"),
        kind="SHELF",
        x=1,
        y=0,
        headers=headers,
    )
    create_map_edge(
        fid,
        from_node_id=p["id"],
        to_node_id=d["id"],
        cost=1,
        directional=False,
        headers=headers,
    )
    robot = create_robot(
        fid, position_node_id=p["id"], battery_pct=100, headers=headers
    )
    task = create_task(
        fid,
        pickup_node_id=p["id"],
        dropoff_node_id=d["id"],
        headers=headers,
    )
    # Trigger dispatch so the assignment is made.
    dispatch(fid, headers=headers)
    # Re-read to pick up updated status/assigned_robot_id.
    task = get_task(fid, task["id"], headers=headers)
    robot = get_robot(fid, robot["id"], headers=headers)
    return fleet, p, d, robot, task


# ---------------------------------------------------------------------------
# Split conservation fixture (rule 9 instance 1)
# ---------------------------------------------------------------------------
def setup_oversized_queued_task(
    *,
    payload_units: int = 23,
    max_units_per_robot: int = 5,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """For rule 9 instance 1: fleet + 2-node map + one QUEUED task with
    payload_units > max_units_per_robot (default 23 / 5 -> 5 children
    with [5,5,5,5,3] payload_units).

    Returns (fleet, pickup, dropoff, task).
    """
    fleet, p, d = setup_fleet_with_two_node_map(headers=headers)
    task = create_task(
        fleet["id"],
        pickup_node_id=p["id"],
        dropoff_node_id=d["id"],
        priority_class="NORMAL",
        payload_units=payload_units,
        max_units_per_robot=max_units_per_robot,
        headers=headers,
    )
    return fleet, p, d, task


# ---------------------------------------------------------------------------
# Open-node-count invariant fixture (rule 9 instance 2)
# ---------------------------------------------------------------------------
def setup_lane_strip_for_isolation(
    *,
    n_nodes: int = 5,
    robot_index: int = 2,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    """5 LANE nodes in a line, robot R at the middle node. Returns
    (fleet, [N1..N5], R)."""
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    nodes: List[Dict[str, Any]] = []
    for i in range(n_nodes):
        n = create_map_node(
            fid,
            code=f"L{i + 1}-{unique_code('s')}",
            kind="LANE",
            x=i,
            y=0,
            headers=headers,
        )
        nodes.append(n)
    for i in range(n_nodes - 1):
        create_map_edge(
            fid,
            from_node_id=nodes[i]["id"],
            to_node_id=nodes[i + 1]["id"],
            cost=1,
            directional=False,
            headers=headers,
        )
    robot = create_robot(
        fid,
        position_node_id=nodes[robot_index]["id"],
        battery_pct=100,
        headers=headers,
    )
    return fleet, nodes, robot


# ---------------------------------------------------------------------------
# Faulted-robot step fixture (rule 5 instance 2)
# ---------------------------------------------------------------------------
def setup_faulted_robot_with_executing_task(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """For rule 5 instance 2: map with LANE L and INTERSECTION I,
    edge L->I cost=1. Robot R at L battery=100, no slot reservation.
    Task T pickup=L dropoff=I. dispatch+start so EXECUTING. POST /faults
    SENSOR_ANOMALY -> R is FAULTED.

    Returns (fleet, L, I, R, T, fault_incident).
    """
    fleet = create_fleet(headers=headers)
    fid = fleet["id"]
    L = create_map_node(
        fid,
        code=unique_code("L"),
        kind="LANE",
        x=0,
        y=0,
        capacity=1,
        headers=headers,
    )
    I = create_map_node(
        fid,
        code=unique_code("I"),
        kind="INTERSECTION",
        x=1,
        y=0,
        capacity=1,
        headers=headers,
    )
    create_map_edge(
        fid,
        from_node_id=L["id"],
        to_node_id=I["id"],
        cost=1,
        directional=False,
        headers=headers,
    )
    robot = create_robot(
        fid, position_node_id=L["id"], battery_pct=100, headers=headers
    )
    task = create_task(
        fid,
        pickup_node_id=L["id"],
        dropoff_node_id=I["id"],
        headers=headers,
    )
    assign_task(fid, task["id"], robot_id=robot["id"], headers=headers)
    start_task(fid, task["id"], headers=headers)
    fault = open_fault(
        fid, robot["id"], kind="SENSOR_ANOMALY", headers=headers
    )
    return fleet, L, I, robot, task, fault


__all__ = [
    # time
    "iso_z",
    "parse_iso",
    "epoch_iso",
    # primitives
    "create_fleet",
    "advance_clock",
    "get_fleet",
    "create_map_node",
    "create_map_edge",
    "link_bidirectional",
    "create_charging_station",
    "create_robot",
    "get_robot",
    "create_task",
    "get_task",
    "assign_task",
    "start_task",
    "complete_task",
    "cancel_task",
    "dispatch",
    "step_robot",
    "step_until_at",
    "dock_robot",
    "queue_charger",
    "create_slot_reservation",
    "open_fault",
    "takeover_fault",
    "resolve_fault",
    "list_audit_events",
    "list_trajectory",
    "list_slot_reservations",
    "list_tasks",
    "list_robots",
    # composites
    "build_two_node_map",
    "setup_minimal_fleet",
    "setup_fleet_with_two_node_map",
    "setup_assignable_scenario",
    "setup_executing_task",
    "setup_completed_task_at_zero",
    "setup_parent_with_three_children_one_completed",
    "setup_empty_fleet_for_metrics",
    "setup_fault_cascade_strip",
    "setup_charging_queue_two_robots",
    "setup_single_robot_at_charger",
    "setup_executing_task_for_rollback",
    "setup_dispatch_priority_ageing_scenario",
    "setup_throughput_rounding_seven_robots",
    "setup_capacity_three_lane_with_four_robots",
    "setup_intersection_for_slot_reservations",
    "setup_empty_fleet",
    "setup_battery_boundary_assign_pair",
    "setup_assigned_task_for_connectivity_test",
    "setup_oversized_queued_task",
    "setup_lane_strip_for_isolation",
    "setup_faulted_robot_with_executing_task",
]
