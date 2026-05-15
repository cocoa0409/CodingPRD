"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup
failures produce clear "Setup failed" errors instead of confusing
assertion failures.

All fixtures honor PRD §2.1 identity rules:

- Housekeeper headers are minted per-Housekeeper via
  make_housekeeper_headers(housekeeper["id"]) — never the shared
  TEST_USERS["housekeeper_headers"] fallback, which would fail every
  ownership check (accept/start/submit/self-shift-toggle) because
  X-User-ID would never equal any real Housekeeper.id.

- Supervisor / FrontDesk / Engineer / SystemIntegration are opaque per
  PRD §2.1 — shared TEST_USERS constants are canonical.

Test isolation: PRD §3.3 scopes auto-dispatch to housekeepers whose
``assigned_zone`` equals the room's ``zone_code``. Because the
underlying server keeps DB state across tests, using a single shared
zone (e.g. ``FLOOR_12_NORTH``) lets housekeepers created in earlier
tests leak into the candidate pool for later tests, causing
ASSIGNED-vs-PENDING confusion or auto-dispatch picking the "wrong"
housekeeper. To stay PRD-faithful while being deterministic, each
setup helper that does not receive an explicit ``zone_code`` mints a
fresh random zone via :func:`unique_zone`; tests that want to share
a zone can still pass one explicitly.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    EARLY_CHECK_IN_WINDOW_HOURS,
    MINIBAR_DISPUTE_WINDOW_HOURS,
    TEST_DEFAULTS,
)


def unique_zone(prefix: str = "ZONE") -> str:
    """Generate a fresh, unique zone code so each test's dispatch pool
    is isolated from prior tests' housekeepers. PRD §3.1 only requires
    that ``zone_code`` is a string identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:10].upper()}"


def unique_code(base: str) -> str:
    """Append a short uuid to a caller-supplied employee_code-style
    base, preserving lexicographic ordering of the *base* while keeping
    the final string globally unique. Used so that tests asserting
    "HK-AAA-001 < HK-ZZZ-999" stay comparable across re-runs."""
    return f"{base}-{uuid.uuid4().hex[:6]}"
from .factories import (
    clock_advance_payload,
    create_cleaning_task_payload,
    create_housekeeper_payload,
    create_linen_movement_payload,
    create_linen_type_payload,
    create_maintenance_ticket_payload,
    create_minibar_consumption_payload,
    create_minibar_item_payload,
    create_room_payload,
    dispatch_maintenance_ticket_payload,
    dispute_minibar_payload,
    engineering_update_payload,
    inspect_cleaning_task_payload,
    investigate_minibar_payload,
    laundry_return_payload,
    pms_sync_payload,
    resolve_minibar_payload,
    toggle_shift_payload,
)
from .test_users import (
    TEST_USERS,
    make_housekeeper_headers,
)


# ===========================================================================
# Tier 1: State Progression — single-entity walk to a target state
# ===========================================================================
def create_room(
    zone_code: Optional[str] = None,
    room_type: str = "STANDARD",
    vip_flag: bool = False,
    pms_occupancy: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Room with sensible defaults. Returns the Room dict.

    PRD §3.1: 'A front-desk agent creates a Room by supplying its
    room_number, a zone_code ..., and a room_type drawn from STANDARD,
    SUITE, or PRESIDENTIAL.'
    """
    payload = create_room_payload(
        zone_code=zone_code or unique_zone(),
        room_type=room_type,
        vip_flag=vip_flag,
        **overrides,
    )
    if pms_occupancy is not None:
        payload["pms_occupancy"] = pms_occupancy
    res = api_client.create_room(payload, TEST_USERS["frontdesk_headers"])
    return get_success_data(res)


def create_housekeeper(
    assigned_zone: Optional[str] = None,
    employee_code: Optional[str] = None,
    on_shift: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Housekeeper, optionally toggling them on shift.

    PRD §3.6: 'A supervisor creates a Housekeeper by supplying
    employee_code, display_name, and assigned_zone; ... shift_status
    defaults to OFF_SHIFT.'
    """
    payload = create_housekeeper_payload(
        assigned_zone=assigned_zone or unique_zone(),
        **overrides,
    )
    if employee_code is not None:
        payload["employee_code"] = employee_code
    res = api_client.create_housekeeper(
        payload, TEST_USERS["supervisor_headers"],
    )
    hk = get_success_data(res)
    if on_shift:
        shift_res = api_client.toggle_housekeeper_shift(
            hk["id"],
            toggle_shift_payload("ON_SHIFT"),
            TEST_USERS["supervisor_headers"],
        )
        hk = get_success_data(shift_res)
    return hk


def create_housekeeper_on_shift(
    assigned_zone: Optional[str] = None,
    employee_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Shortcut: housekeeper rostered ON_SHIFT in the given zone."""
    return create_housekeeper(
        assigned_zone=assigned_zone,
        employee_code=employee_code,
        on_shift=True,
        **overrides,
    )


def create_minibar_item(
    unit_price_cents: int = 500,
    par_level: int = 10,
    replenishment_threshold: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a MinibarItem (ACTIVE)."""
    payload = create_minibar_item_payload(
        unit_price_cents=unit_price_cents,
        par_level=par_level,
        replenishment_threshold=replenishment_threshold,
        **overrides,
    )
    res = api_client.create_minibar_item(
        payload, TEST_USERS["supervisor_headers"],
    )
    return get_success_data(res)


def create_archived_minibar_item(**overrides: Any) -> Dict[str, Any]:
    """Create then archive a MinibarItem."""
    item = create_minibar_item(**overrides)
    res = api_client.archive_minibar_item(
        item["id"], TEST_USERS["supervisor_headers"],
    )
    return get_success_data(res)


def create_linen_type(
    replacement_policy: str = "PER_STAY",
    scheduled_interval_days: Optional[int] = None,
    replacement_cost_cents: int = 2_000,
    par_per_room: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a LinenType."""
    payload = create_linen_type_payload(
        replacement_policy=replacement_policy,
        scheduled_interval_days=scheduled_interval_days,
        replacement_cost_cents=replacement_cost_cents,
        par_per_room=par_per_room,
        **overrides,
    )
    res = api_client.create_linen_type(
        payload, TEST_USERS["supervisor_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2: Entity Hierarchy — pre-built room + housekeeper + task
# ===========================================================================
def setup_room_and_housekeeper(
    *,
    zone_code: Optional[str] = None,
    room_type: str = "STANDARD",
    vip_flag: bool = False,
    pms_occupancy: Optional[str] = None,
    hk_on_shift: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Active Room + Housekeeper rostered in the same zone (defaults
    on-shift). Returns (room, housekeeper).
    """
    zone = zone_code or unique_zone()
    room = create_room(
        zone_code=zone,
        room_type=room_type,
        vip_flag=vip_flag,
        pms_occupancy=pms_occupancy,
    )
    hk = create_housekeeper(
        assigned_zone=zone,
        on_shift=hk_on_shift,
    )
    return room, hk


def create_cleaning_task(
    room_id: str,
    task_source: str = "SCHEDULED",
    expedite_flag: Optional[bool] = None,
    early_check_in_at: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a CleaningTask via POST /cleaning-tasks. Caller picks
    actor headers; FrontDesk and Supervisor are both authorized by PRD
    §4 for this endpoint."""
    payload = create_cleaning_task_payload(
        room_id=room_id,
        task_source=task_source,
        expedite_flag=expedite_flag,
        early_check_in_at=early_check_in_at,
        **overrides,
    )
    res = api_client.create_cleaning_task(
        payload, actor_headers or TEST_USERS["supervisor_headers"],
    )
    return get_success_data(res)


def setup_room_hk_task(
    *,
    room_type: str = "STANDARD",
    vip_flag: bool = False,
    task_source: str = "SCHEDULED",
    expedite_flag: Optional[bool] = None,
    early_check_in_at: Optional[str] = None,
    pms_occupancy: Optional[str] = None,
    zone_code: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Room + on-shift Housekeeper in same zone + CleaningTask. Because
    the housekeeper is on shift, the task should auto-dispatch to
    ASSIGNED (PRD §3.3). Returns (room, housekeeper, task).
    """
    room, hk = setup_room_and_housekeeper(
        zone_code=zone_code,
        room_type=room_type,
        vip_flag=vip_flag,
        pms_occupancy=pms_occupancy,
        hk_on_shift=True,
    )
    task = create_cleaning_task(
        room_id=room["id"],
        task_source=task_source,
        expedite_flag=expedite_flag,
        early_check_in_at=early_check_in_at,
    )
    return room, hk, task


# ===========================================================================
# Tier 3: Full lifecycle shortcuts — drive a task / consumption /
# movement / ticket through to a target state.
# ===========================================================================
def accept_task(task_id: str, housekeeper_id: str) -> Dict[str, Any]:
    """PRD §3.3: 'when X-User-ID does not match assigned_housekeeper_id,
    the request is rejected with ERR_NOT_TASK_ASSIGNEE.' Mint
    per-Housekeeper headers."""
    res = api_client.accept_cleaning_task(
        task_id, make_housekeeper_headers(housekeeper_id),
    )
    return get_success_data(res)


def start_task(task_id: str, housekeeper_id: str) -> Dict[str, Any]:
    res = api_client.start_cleaning_task(
        task_id, make_housekeeper_headers(housekeeper_id),
    )
    return get_success_data(res)


def submit_task(task_id: str, housekeeper_id: str) -> Dict[str, Any]:
    res = api_client.submit_cleaning_task(
        task_id, make_housekeeper_headers(housekeeper_id),
    )
    return get_success_data(res)


def inspect_task(
    task_id: str,
    outcome: str,
    checklist_items: Optional[List[Dict[str, Any]]] = None,
    notes: Optional[str] = None,
    supervisor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    res = api_client.inspect_cleaning_task(
        task_id,
        inspect_cleaning_task_payload(
            outcome=outcome,
            checklist_items=checklist_items,
            notes=notes,
        ),
        supervisor_headers or TEST_USERS["supervisor_headers"],
    )
    return get_success_data(res)


def drive_task_to_state(
    task: Dict[str, Any],
    housekeeper_id: str,
    target: str,
    *,
    clock_advance_minutes_between_start_submit: Optional[int] = None,
) -> Dict[str, Any]:
    """Walk a CleaningTask from its current status to `target`.

    Valid targets: ASSIGNED, ACCEPTED, IN_PROGRESS, SUBMITTED,
    COMPLETED, CANCELLED (PASS-COMPLETED only — cancel-by-inspect needs
    a separate fail call).
    """
    sequence = ["ASSIGNED", "ACCEPTED", "IN_PROGRESS", "SUBMITTED",
                "COMPLETED"]
    if target not in sequence:
        raise ValueError(f"drive_task_to_state: target {target!r}")
    current_status = task["status"]
    if current_status == "PENDING":
        # Not auto-dispatched: caller likely set up a no-eligible-hk
        # scenario. Manual dispatch:
        res = api_client.dispatch_cleaning_task(
            task["id"], TEST_USERS["supervisor_headers"],
        )
        task = get_success_data(res)
    # accept / start / submit
    if sequence.index(target) >= sequence.index("ACCEPTED"):
        task = accept_task(task["id"], housekeeper_id)
    if sequence.index(target) >= sequence.index("IN_PROGRESS"):
        task = start_task(task["id"], housekeeper_id)
    if (
        clock_advance_minutes_between_start_submit is not None
        and clock_advance_minutes_between_start_submit > 0
    ):
        # Advance the test clock so actual_minutes ≈ requested gap.
        adv = api_client.clock_advance(
            clock_advance_payload(
                clock_advance_minutes_between_start_submit,
            ),
            TEST_USERS["system_integration_headers"],
        )
        get_success_data(adv)
    if sequence.index(target) >= sequence.index("SUBMITTED"):
        task = submit_task(task["id"], housekeeper_id)
    if sequence.index(target) >= sequence.index("COMPLETED"):
        inspect_task(task["id"], outcome="PASS")
        # Re-read task — inspect endpoint returns InspectionRecord,
        # not the updated CleaningTask.
        res = api_client.get_cleaning_task(
            task["id"], TEST_USERS["supervisor_headers"],
        )
        task = get_success_data(res)
    return task


def setup_task_in_state(
    *,
    target: str,
    room_type: str = "STANDARD",
    vip_flag: bool = False,
    task_source: str = "SCHEDULED",
    expedite_flag: Optional[bool] = None,
    pms_occupancy: Optional[str] = None,
    clock_advance_minutes_between_start_submit: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build (room, housekeeper, task) with the task driven to `target`."""
    room, hk, task = setup_room_hk_task(
        room_type=room_type,
        vip_flag=vip_flag,
        task_source=task_source,
        expedite_flag=expedite_flag,
        pms_occupancy=pms_occupancy,
    )
    task = drive_task_to_state(
        task,
        hk["id"],
        target,
        clock_advance_minutes_between_start_submit=(
            clock_advance_minutes_between_start_submit
        ),
    )
    return room, hk, task


# ---------------------------------------------------------------------------
# Maintenance lifecycle helpers
# ---------------------------------------------------------------------------
def create_maintenance_ticket(
    room_id: str,
    reporter_housekeeper_id: str,
    severity: str = "MEDIUM",
    category: str = "PLUMBING",
    description: str = "issue",
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_maintenance_ticket_payload(
        room_id=room_id,
        reporter_housekeeper_id=reporter_housekeeper_id,
        severity=severity,
        category=category,
        description=description,
    )
    res = api_client.create_maintenance_ticket(
        payload, actor_headers or TEST_USERS["supervisor_headers"],
    )
    return get_success_data(res)


def dispatch_ticket(
    ticket_id: str,
    engineering_assignee: str = "eng-default",
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    res = api_client.dispatch_maintenance_ticket(
        ticket_id,
        dispatch_maintenance_ticket_payload(engineering_assignee),
        actor_headers or TEST_USERS["supervisor_headers"],
    )
    return get_success_data(res)


def drive_ticket_through_repair(ticket_id: str) -> Dict[str, Any]:
    """Walk DISPATCHED → IN_REPAIR → REPAIR_COMPLETED via the inbound
    engineering-update channel (PRD §3.7)."""
    sys_hdr = TEST_USERS["system_integration_headers"]
    res = api_client.engineering_update_event(
        engineering_update_payload(ticket_id, "IN_REPAIR"), sys_hdr,
    )
    get_success_data(res)
    res = api_client.engineering_update_event(
        engineering_update_payload(ticket_id, "REPAIR_COMPLETED"), sys_hdr,
    )
    return get_success_data(res)


def setup_room_isolated_by_ticket(
    *,
    severity: str = "CRITICAL",
    pms_occupancy: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a Room held OUT_OF_ORDER by a dispatched HIGH/CRITICAL
    ticket. Returns (room, reporter_housekeeper, ticket).
    """
    room, hk = setup_room_and_housekeeper(
        pms_occupancy=pms_occupancy, hk_on_shift=True,
    )
    ticket = create_maintenance_ticket(
        room_id=room["id"],
        reporter_housekeeper_id=hk["id"],
        severity=severity,
    )
    ticket = dispatch_ticket(ticket["id"])
    return room, hk, ticket


# ---------------------------------------------------------------------------
# Minibar consumption lifecycle helpers
# ---------------------------------------------------------------------------
def create_minibar_consumption(
    room_id: str,
    line_items: List[Dict[str, Any]],
    source_type: str = "GUEST_SELF_REPORT",
    cleaning_task_id: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_minibar_consumption_payload(
        room_id=room_id,
        source_type=source_type,
        line_items=line_items,
        cleaning_task_id=cleaning_task_id,
    )
    res = api_client.create_minibar_consumption(
        payload, actor_headers or TEST_USERS["frontdesk_headers"],
    )
    return get_success_data(res)


def post_consumption(consumption_id: str) -> Dict[str, Any]:
    res = api_client.post_minibar_consumption(
        consumption_id, TEST_USERS["frontdesk_headers"],
    )
    return get_success_data(res)


def drive_consumption_to_state(
    consumption: Dict[str, Any],
    target: str,
    *,
    dispute_note: str = "guest dispute",
    finding_note: str = "supervisor finding",
    keep_charge: Optional[bool] = None,
) -> Dict[str, Any]:
    """Walk a MinibarConsumption from PENDING toward `target`.

    target ∈ {POSTED, DISPUTED, INVESTIGATED, RESOLVED, WAIVED}.
    For RESOLVED/WAIVED, pass keep_charge explicitly.
    """
    current = consumption
    # Steps are state-conditional so callers may invoke this fixture
    # from any intermediate state (e.g., post then drive to WAIVED).
    if (target in {"POSTED", "DISPUTED", "INVESTIGATED", "RESOLVED",
                   "WAIVED"}
            and current["status"] == "PENDING"):
        current = post_consumption(current["id"])
    if (target in {"DISPUTED", "INVESTIGATED", "RESOLVED", "WAIVED"}
            and current["status"] == "POSTED"):
        res = api_client.dispute_minibar_consumption(
            current["id"],
            dispute_minibar_payload(dispute_note),
            TEST_USERS["frontdesk_headers"],
        )
        current = get_success_data(res)
    if (target in {"INVESTIGATED", "RESOLVED", "WAIVED"}
            and current["status"] == "DISPUTED"):
        res = api_client.investigate_minibar_consumption(
            current["id"],
            investigate_minibar_payload(finding_note),
            TEST_USERS["supervisor_headers"],
        )
        current = get_success_data(res)
    if (target in {"RESOLVED", "WAIVED"}
            and current["status"] == "INVESTIGATED"):
        if keep_charge is None:
            keep_charge = (target == "RESOLVED")
        res = api_client.resolve_minibar_consumption(
            current["id"],
            resolve_minibar_payload(keep_charge),
            TEST_USERS["supervisor_headers"],
        )
        current = get_success_data(res)
    return current


def setup_consumption_in_state(
    *,
    target: str,
    unit_price_cents: int = 25,
    line_count: int = 2,
    quantity_each: int = 1,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """(room, items, consumption-at-target).

    Default: two items at 25¢ each, one of each line — exercises the
    sum-then-round invariant in PRD §3.11.
    """
    room = create_room()
    items: List[Dict[str, Any]] = []
    line_items: List[Dict[str, Any]] = []
    for _ in range(line_count):
        item = create_minibar_item(
            unit_price_cents=unit_price_cents,
            par_level=10,
            replenishment_threshold=2,
        )
        items.append(item)
        line_items.append({
            "minibar_item_id": item["id"], "quantity": quantity_each,
        })
    consumption = create_minibar_consumption(
        room_id=room["id"],
        line_items=line_items,
        source_type="GUEST_SELF_REPORT",
    )
    if target != "PENDING":
        consumption = drive_consumption_to_state(consumption, target)
    return room, items, consumption


# ---------------------------------------------------------------------------
# Linen movement lifecycle helpers
# ---------------------------------------------------------------------------
def create_linen_movement(
    room_id: str,
    linen_type_id: str,
    collected_quantity: int = 1,
    cleaning_task_id: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §4: POST /linen-movements is exclusive to Housekeeper. The
    caller must pass headers for an actual Housekeeper.id; default uses
    a freshly-minted housekeeper inside the helper if no actor supplied.
    """
    if actor_headers is None:
        hk = create_housekeeper_on_shift()
        actor_headers = make_housekeeper_headers(hk["id"])
    payload = create_linen_movement_payload(
        room_id=room_id,
        linen_type_id=linen_type_id,
        collected_quantity=collected_quantity,
        cleaning_task_id=cleaning_task_id,
    )
    res = api_client.create_linen_movement(payload, actor_headers)
    return get_success_data(res)


def handover_linen(
    movement_id: str,
    housekeeper_id: str,
) -> Dict[str, Any]:
    """PRD §4: POST /linen-movements/{id}/handover-laundry is exclusive
    to Housekeeper. Mint per-housekeeper headers."""
    res = api_client.handover_laundry(
        movement_id, make_housekeeper_headers(housekeeper_id),
    )
    return get_success_data(res)


def setup_linen_movement_at_handover(
    *,
    replacement_policy: str = "PER_STAY",
    scheduled_interval_days: Optional[int] = None,
    collected_quantity: int = 10,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
          Dict[str, Any]]:
    """Build (room, housekeeper, linen_type, movement-at-SENT_TO_LAUNDRY).
    """
    room = create_room()
    hk = create_housekeeper_on_shift()
    lt = create_linen_type(
        replacement_policy=replacement_policy,
        scheduled_interval_days=scheduled_interval_days,
    )
    movement = create_linen_movement(
        room_id=room["id"],
        linen_type_id=lt["id"],
        collected_quantity=collected_quantity,
        actor_headers=make_housekeeper_headers(hk["id"]),
    )
    movement = handover_linen(movement["id"], hk["id"])
    return room, hk, lt, movement


def advance_clock(minutes: int) -> Dict[str, Any]:
    """Wrap POST /_clock/advance (PRD §2.11)."""
    res = api_client.clock_advance(
        clock_advance_payload(minutes),
        TEST_USERS["system_integration_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4: Threshold / boundary targeting — set up exact preconditions
# for boundary tests (PRD §3.5, §3.11, §3.12).
# ===========================================================================
def _server_now_iso() -> str:
    """Query the server's logical clock by advancing it 0 minutes.
    PRD §2.11: 'The response contains a now field naming the new
    logical clock value.' Using server-time keeps early_check_in_at
    in-window even after other tests have advanced the clock."""
    res = api_client.clock_advance(
        {"minutes": 0},
        TEST_USERS["system_integration_headers"],
    )
    data = get_success_data(res)
    return data["now"]


def _parse_iso(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def now_plus_seconds_iso(seconds: int) -> str:
    """ISO 8601 UTC anchored to the server's logical clock plus
    ``seconds``. PRD §2.11 lets the test clock advance independently
    of wall time, so anchoring to the server clock guarantees the
    moment stays in-window regardless of prior advances."""
    base = _parse_iso(_server_now_iso())
    t = base + timedelta(seconds=seconds)
    return _format_iso(t)


def early_check_in_within_window_iso(hours_ahead: float = 1.0) -> str:
    """early_check_in_at within the EARLY_CHECK_IN_WINDOW_HOURS=4
    window. PRD §3.5: 'when the early-check-in moment is in the future
    and no further off than the four-hour window'."""
    assert 0 < hours_ahead < EARLY_CHECK_IN_WINDOW_HOURS
    return now_plus_seconds_iso(int(hours_ahead * 3600))


def setup_high_priority_task_inputs(
    *,
    vip_flag: bool,
    expedite_flag: bool,
    early_check_in: bool,
    task_source: str = "SCHEDULED",
    room_type: str = "STANDARD",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a task whose four priority inputs are precisely those
    requested. Returns (room, housekeeper, task).
    """
    room, hk = setup_room_and_housekeeper(
        room_type=room_type, vip_flag=vip_flag,
    )
    eci_iso = (
        early_check_in_within_window_iso(1.0) if early_check_in else None
    )
    task = create_cleaning_task(
        room_id=room["id"],
        task_source=task_source,
        expedite_flag=expedite_flag,
        early_check_in_at=eci_iso,
    )
    return room, hk, task


def setup_consumption_two_25c_items() -> Tuple[Dict[str, Any],
                                               List[Dict[str, Any]],
                                               Dict[str, Any]]:
    """Builds the canonical sum-then-round scenario:
    Item_X (25¢), Item_Y (25¢), one quantity of each → gross=50, tax=5,
    posted=55. PRD §3.11: 'tax_cents as the gross amount multiplied by
    the minibar tax rate of 0.10 and rounded half-up to a whole cent on
    that single product (per-line tax-then-sum is incorrect because
    each line's tax would be rounded independently).'
    """
    return setup_consumption_in_state(
        target="PENDING", unit_price_cents=25, line_count=2,
        quantity_each=1,
    )


# ---------------------------------------------------------------------------
# Audit log lookups
# ---------------------------------------------------------------------------
def list_audit_entries_for_subject(
    subject_id: str,
    action_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read audit log entries filtered by subject_id (and optionally
    action_type). PRD §3.13."""
    params: Dict[str, Any] = {"subject_id": subject_id, "limit": 100}
    if action_type is not None:
        params["action_type"] = action_type
    res = api_client.list_audit_logs(
        TEST_USERS["supervisor_headers"], params=params,
    )
    # paginated envelope; data is the list
    body = res.json()
    return body.get("data", [])


def list_room_status_events(room_id: str) -> List[Dict[str, Any]]:
    res = api_client.list_room_status_events(
        room_id, TEST_USERS["supervisor_headers"],
        params={"limit": 100},
    )
    body = res.json()
    return body.get("data", [])


__all__ = [
    # Tier 1
    "create_room",
    "create_housekeeper",
    "create_housekeeper_on_shift",
    "create_minibar_item",
    "create_archived_minibar_item",
    "create_linen_type",
    # Tier 2
    "setup_room_and_housekeeper",
    "create_cleaning_task",
    "setup_room_hk_task",
    # Tier 3
    "accept_task",
    "start_task",
    "submit_task",
    "inspect_task",
    "drive_task_to_state",
    "setup_task_in_state",
    "create_maintenance_ticket",
    "dispatch_ticket",
    "drive_ticket_through_repair",
    "setup_room_isolated_by_ticket",
    "create_minibar_consumption",
    "post_consumption",
    "drive_consumption_to_state",
    "setup_consumption_in_state",
    "create_linen_movement",
    "handover_linen",
    "setup_linen_movement_at_handover",
    "advance_clock",
    # Tier 4
    "now_plus_seconds_iso",
    "early_check_in_within_window_iso",
    "setup_high_priority_task_inputs",
    "setup_consumption_two_25c_items",
    # Lookups
    "list_audit_entries_for_subject",
    "list_room_status_events",
]
