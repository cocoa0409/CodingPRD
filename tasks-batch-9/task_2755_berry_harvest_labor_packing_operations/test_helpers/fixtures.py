"""
Composite setup helpers for the Berry Harvest Ops API test suite.

The harness restarts the service before every individual test, so each test
starts against an empty database and must build the whole state it needs. The
helpers here walk the season in the order PRD section 3 describes it: ground
and water first, then people, then the harvest windows that bring the two
together, then the pay those windows generate, then the fruit they produce,
and finally the buyers that fruit was promised to.

Every helper drives the public API only — no fixture reaches behind the
service — and uses ``get_success_data`` so that a broken setup step fails with
the API's own error identifier rather than with an opaque KeyError.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as u
from .api_client import ApiClient

# ═══════════════════════════════════════════════════════════════════════════
# Tier 0 — the logical clock
# ═══════════════════════════════════════════════════════════════════════════


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """
    Move the logical UTC clock (PRD 2.5).

    "A `HarvestManager` moves the clock by supplying a `current_utc` instant
    to the clock-setting capability described in §4; the response echoes the
    instant now in force as `current_utc`."
    """
    return get_success_data(api.set_clock(current_utc, u.HARVEST_MANAGER))


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1 — state progression: blocks and the water register
# ═══════════════════════════════════════════════════════════════════════════


def register_block(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one production block (PRD 3.1)."""
    return get_success_data(
        api.create_block(f.block_payload(**overrides), u.HARVEST_MANAGER), 201
    )


def read_block(api: ApiClient, block_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one block including its derived water and food-safety fields."""
    return get_success_data(
        api.get_block(block_id, headers or u.HARVEST_MANAGER), 200
    )


def record_water_sample(
    api: ApiClient,
    block_id: str,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record one agricultural-water sample (PRD 3.1 "The rolling water series")."""
    return get_success_data(
        api.create_water_test(
            f.water_test_payload(block_id, **overrides),
            headers or u.FOOD_SAFETY_OFFICER,
        ),
        201,
    )


def block_with_provisional_water(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """
    A block carrying one passing sample.

    PRD 3.1: "if fewer than three samples are in the window, the status is
    `PROVISIONAL`", and PRD 3.1 "Posture is derived": "if `water_status` is
    `PROVISIONAL` or `COMPLIANT`, the posture is `CLEARED`". This is the
    cheapest block that a harvest window may be opened against.
    """
    block = register_block(api, **overrides)
    record_water_sample(api, block["id"], generic_ecoli_mpn=40)
    return read_block(api, block["id"])


def block_with_compliant_water(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """
    A block carrying three passing samples, so its `water_status` is COMPLIANT.

    PRD 3.7 requires exactly this for a shipment: "The `water_status` of the
    lot's traceability block must be exactly `COMPLIANT` — not `PROVISIONAL`,
    not `FAILED`, not `NON_COMPLIANT`".
    """
    block = register_block(api, **overrides)
    for sample_date, mpn in (
        ("2026-07-18", 40),
        ("2026-07-19", 50),
        ("2026-07-20", 60),
    ):
        record_water_sample(
            api, block["id"], sample_date=sample_date, generic_ecoli_mpn=mpn
        )
    return read_block(api, block["id"])


def quarantine_block(
    api: ApiClient,
    block_id: str,
    reason_code: str = "ADJACENT_LIVESTOCK",
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Impose a manual food-safety hold, firing the four-level cascade (PRD 3.1)."""
    return get_success_data(
        api.quarantine_block(
            block_id,
            f.quarantine_payload(quarantine_reason_code=reason_code),
            headers or u.FOOD_SAFETY_OFFICER,
        ),
        200,
    )


def clear_block(
    api: ApiClient, block_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Lift the manual hold (PRD 3.1 "Clearing a hold").

    The clearing officer must differ from `quarantined_by_user_id`, so the
    default header here is the *second* food safety officer.
    """
    return get_success_data(
        api.clear_block(block_id, headers or u.FOOD_SAFETY_OFFICER_2), 200
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — entity hierarchy: crews, pickers and the support plan
# ═══════════════════════════════════════════════════════════════════════════


def recruit_crew(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Recruit a harvest crew; it starts at `RECRUITING` (PRD 3.2)."""
    return get_success_data(
        api.create_crew(f.crew_payload(**overrides), u.HARVEST_MANAGER), 201
    )


def read_crew(api: ApiClient, crew_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one crew including its wage ledger."""
    return get_success_data(api.get_crew(crew_id, headers or u.HARVEST_MANAGER), 200)


def register_picker(
    api: ApiClient, crew_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """
    Register a worker onto a crew (PRD 3.2 "Registering pickers").

    The default `hygiene_training_on` of 2026-06-01 expires 365 days later, so
    the training is valid both at the start-up clock and on a 2026-08 work
    date.
    """
    return get_success_data(
        api.create_picker(
            f.picker_payload(crew_id, **overrides), headers or u.HARVEST_MANAGER
        ),
        201,
    )


def read_picker(
    api: ApiClient, picker_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one picker including lifetime productivity."""
    return get_success_data(
        api.get_picker(picker_id, headers or u.HARVEST_MANAGER), 200
    )


def record_support_plan(
    api: ApiClient, crew_id: str, head_count: int = 1, **overrides: Any
) -> Dict[str, Any]:
    """Record housing and transportation in one call (PRD 3.2)."""
    return get_success_data(
        api.record_support_plan(
            crew_id, f.support_plan_payload(head_count, **overrides), u.HARVEST_MANAGER
        ),
        200,
    )


def certify_crew(api: ApiClient, crew_id: str) -> Dict[str, Any]:
    """Certify a `STAFFED` crew, moving it `STAFFED → CERTIFIED` (PRD 3.2)."""
    return get_success_data(api.certify_crew(crew_id, u.HARVEST_MANAGER), 200)


def certified_crew(
    api: ApiClient,
    picker_count: int = 1,
    planned_head_count: Optional[int] = None,
    supervisor_user_id: str = u.SUP_1,
    labor_program: str = "DOMESTIC",
    hygiene_training_on: str = "2026-06-01",
    support_plan: Optional[Dict[str, Any]] = None,
    **crew_overrides: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    A crew all the way to `CERTIFIED`, with its pickers registered.

    Walks the whole chain of PRD 3.2: recruit, register pickers (which moves
    `RECRUITING → STAFFED` on the first one), record a support plan that
    satisfies the labor program, then certify. Returns the re-read crew and
    the list of pickers in registration order.
    """
    head_count = planned_head_count if planned_head_count is not None else picker_count
    crew = recruit_crew(
        api,
        labor_program=labor_program,
        supervisor_user_id=supervisor_user_id,
        planned_head_count=head_count,
        **crew_overrides,
    )
    pickers = [
        register_picker(api, crew["id"], hygiene_training_on=hygiene_training_on)
        for _ in range(picker_count)
    ]
    record_support_plan(api, crew["id"], head_count, **(support_plan or {}))
    certify_crew(api, crew["id"])
    return read_crew(api, crew["id"]), pickers


def release_crew(api: ApiClient, crew_id: str) -> Dict[str, Any]:
    """Release the crew at the end of its contract (PRD 3.2 "Release")."""
    return get_success_data(api.release_crew(crew_id, u.HARVEST_MANAGER), 200)


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — harvest windows
# ═══════════════════════════════════════════════════════════════════════════


def plan_window(
    api: ApiClient, block_id: str, crew_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Plan a harvest window; it starts at `PLANNED` (PRD 3.3)."""
    return get_success_data(
        api.create_harvest_window(
            f.harvest_window_payload(block_id, crew_id, **overrides),
            u.HARVEST_MANAGER,
        ),
        201,
    )


def read_window(
    api: ApiClient, window_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one harvest window including its staffing requirement."""
    return get_success_data(
        api.get_harvest_window(window_id, headers or u.HARVEST_MANAGER), 200
    )


def confirm_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    """Confirm the window `PLANNED → CONFIRMED` (PRD 3.3)."""
    return get_success_data(
        api.confirm_harvest_window(window_id, u.HARVEST_MANAGER), 200
    )


def open_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    """Open the window `CONFIRMED → OPEN` (PRD 3.3 "Opening")."""
    return get_success_data(api.open_harvest_window(window_id, u.HARVEST_MANAGER), 200)


def close_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    """Close the window `OPEN → CLOSED` (PRD 3.3 "Closing")."""
    return get_success_data(api.close_harvest_window(window_id, u.HARVEST_MANAGER), 200)


def resume_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    """Resume a `SUSPENDED` window back to `CONFIRMED` (PRD 3.3)."""
    return get_success_data(
        api.resume_harvest_window(window_id, u.HARVEST_MANAGER), 200
    )


def cancel_window(
    api: ApiClient, window_id: str, reason_code: str = "WEATHER"
) -> Dict[str, Any]:
    """Cancel a window, freeing the block re-entry slot immediately (PRD 3.3)."""
    return get_success_data(
        api.cancel_harvest_window(
            window_id, f.cancel_window_payload(cancel_reason_code=reason_code),
            u.HARVEST_MANAGER,
        ),
        200,
    )


def confirmed_window(
    api: ApiClient, block_id: str, crew_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A window carried from `PLANNED` through `CONFIRMED`."""
    window = plan_window(api, block_id, crew_id, **overrides)
    return confirm_window(api, window["id"])


def opened_window(
    api: ApiClient, block_id: str, crew_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A window carried all the way to `OPEN`."""
    window = plan_window(api, block_id, crew_id, **overrides)
    confirm_window(api, window["id"])
    return open_window(api, window["id"])


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — pick sessions and the wage guarantee
# ═══════════════════════════════════════════════════════════════════════════


def supervisor_headers(supervisor_user_id: str = u.SUP_1) -> Dict[str, str]:
    """
    Headers for the operator named as a crew's `supervisor_user_id`.

    PRD 2.1: the server "compares a `CrewSupervisor` caller's `X-User-ID`
    against the `supervisor_user_id` value that was supplied when the crew was
    recruited".
    """
    return u.headers_with_role(supervisor_user_id, u.ROLE_CREW_SUPERVISOR)


def open_session(
    api: ApiClient,
    window_id: str,
    picker_id: str,
    supervisor_user_id: str = u.SUP_1,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a picker's day on an `OPEN` window (PRD 3.4)."""
    return get_success_data(
        api.create_pick_session(
            f.pick_session_payload(window_id, picker_id, **overrides),
            supervisor_headers(supervisor_user_id),
        ),
        201,
    )


def read_session(
    api: ApiClient, session_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one pick session including its piece-rate and guarantee figures."""
    return get_success_data(
        api.get_pick_session(session_id, headers or u.HARVEST_MANAGER), 200
    )


def tally_session(
    api: ApiClient,
    session_id: str,
    supervisor_user_id: str = u.SUP_1,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record the row-pack tally and price the session (PRD 3.4)."""
    return get_success_data(
        api.tally_pick_session(
            session_id,
            f.tally_payload(**overrides),
            supervisor_headers(supervisor_user_id),
        ),
        200,
    )


def approve_session(
    api: ApiClient, session_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Approve a tallied session `TALLIED → APPROVED` (PRD 3.4 "Approval").

    The approver must differ from `tallied_by_user_id`, so the default clerk
    here is never the default supervisor.
    """
    return get_success_data(
        api.approve_pick_session(session_id, headers or u.PAYROLL_CLERK), 200
    )


def dispute_session(
    api: ApiClient,
    session_id: str,
    reason_code: str = "PICKER_CONTESTS_COUNT",
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Dispute a tally from `TALLIED` or `APPROVED` (PRD 3.4 "Disputes")."""
    return get_success_data(
        api.dispute_pick_session(
            session_id,
            f.dispute_payload(dispute_reason_code=reason_code),
            headers or u.CREW_SUPERVISOR,
        ),
        200,
    )


def tallied_session(
    api: ApiClient,
    window_id: str,
    picker_id: str,
    supervisor_user_id: str = u.SUP_1,
    work_date: str = "2026-08-03",
    hours_worked: float = 3.00,
    clamshells_filled: int = 20,
    culled_clamshells: int = 0,
) -> Dict[str, Any]:
    """A session opened and tallied in one step."""
    session = open_session(
        api, window_id, picker_id, supervisor_user_id, work_date=work_date
    )
    return tally_session(
        api,
        session["id"],
        supervisor_user_id,
        hours_worked=hours_worked,
        clamshells_filled=clamshells_filled,
        culled_clamshells=culled_clamshells,
    )


def approved_session(
    api: ApiClient,
    window_id: str,
    picker_id: str,
    supervisor_user_id: str = u.SUP_1,
    approver_headers: Optional[Dict] = None,
    work_date: str = "2026-08-03",
    hours_worked: float = 3.00,
    clamshells_filled: int = 20,
    culled_clamshells: int = 0,
) -> Dict[str, Any]:
    """A session carried from `OPEN` through `TALLIED` to `APPROVED`."""
    session = tallied_session(
        api,
        window_id,
        picker_id,
        supervisor_user_id,
        work_date=work_date,
        hours_worked=hours_worked,
        clamshells_filled=clamshells_filled,
        culled_clamshells=culled_clamshells,
    )
    return approve_session(api, session["id"], approver_headers)


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — payroll runs
# ═══════════════════════════════════════════════════════════════════════════


def open_payroll_run(api: ApiClient, crew_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a draft pay period for a crew (PRD 3.5)."""
    return get_success_data(
        api.create_payroll_run(f.payroll_run_payload(crew_id, **overrides), u.PAYROLL_CLERK),
        201,
    )


def read_payroll_run(
    api: ApiClient, run_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one payroll run including its period-averaged settlement figures."""
    return get_success_data(
        api.get_payroll_run(run_id, headers or u.PAYROLL_CLERK), 200
    )


def lock_payroll_run(
    api: ApiClient, run_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Freeze the bound session set `DRAFT → LOCKED` (PRD 3.5)."""
    return get_success_data(
        api.lock_payroll_run(run_id, headers or u.PAYROLL_CLERK), 200
    )


def settle_payroll_run(
    api: ApiClient, run_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Settle the locked period `LOCKED → SETTLED` (PRD 3.5).

    "the settling `X-User-ID` must differ from `locked_by_user_id`", so the
    default settler is the second clerk.
    """
    return get_success_data(
        api.settle_payroll_run(run_id, headers or u.PAYROLL_CLERK_2), 200
    )


def locked_payroll_run(
    api: ApiClient,
    crew_id: str,
    locker_headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A pay period opened and locked in one step."""
    run = open_payroll_run(api, crew_id, **overrides)
    return lock_payroll_run(api, run["id"], locker_headers)


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — cooling tunnels, fruit lots and the cold chain
# ═══════════════════════════════════════════════════════════════════════════


def register_tunnel(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a forced-air cooling tunnel; `committed_slots` starts 0 (PRD 3.6)."""
    return get_success_data(
        api.create_cooling_tunnel(
            f.cooling_tunnel_payload(**overrides), u.PACKHOUSE_OPERATOR
        ),
        201,
    )


def read_tunnel(
    api: ApiClient, tunnel_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one tunnel; "Its `version` is the concurrency token" (PRD 4)."""
    return get_success_data(
        api.get_cooling_tunnel(tunnel_id, headers or u.PACKHOUSE_OPERATOR), 200
    )


def tunnel_version(api: ApiClient, tunnel_id: str) -> int:
    """
    Re-read a tunnel's current `version` for the start-cooling guard.

    PRD 2.8: "A caller that re-reads the tunnel and resubmits with the current
    `version` succeeds whenever room genuinely remains."
    """
    return int(read_tunnel(api, tunnel_id)["version"])


def pack_lot(
    api: ApiClient, window_id: str, block_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Record a field-packed lot; it starts `PACKED`/`UNCOMMITTED` (PRD 3.6)."""
    return get_success_data(
        api.create_fruit_lot(
            f.fruit_lot_payload(window_id, block_id, **overrides),
            u.PACKHOUSE_OPERATOR,
        ),
        201,
    )


def read_lot(
    api: ApiClient, lot_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one fruit lot with both of its state dimensions."""
    return get_success_data(
        api.get_fruit_lot(lot_id, headers or u.PACKHOUSE_OPERATOR), 200
    )


def start_cooling(
    api: ApiClient,
    lot_id: str,
    tunnel_id: str,
    expected_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Push a lot into a tunnel `PACKED → COOLING` (PRD 3.6).

    When ``expected_version`` is omitted the tunnel is re-read first, which is
    the discipline PRD 2.8 prescribes for the concurrency guard.
    """
    version = (
        expected_version
        if expected_version is not None
        else tunnel_version(api, tunnel_id)
    )
    return get_success_data(
        api.start_cooling(
            lot_id,
            f.start_cooling_payload(tunnel_id, version, **overrides),
            u.PACKHOUSE_OPERATOR,
        ),
        200,
    )


def complete_cooling(api: ApiClient, lot_id: str, **overrides: Any) -> Dict[str, Any]:
    """Complete a cooling run `COOLING → COOLED`, releasing slots (PRD 3.6)."""
    return get_success_data(
        api.complete_cooling(
            lot_id, f.complete_cooling_payload(**overrides), u.PACKHOUSE_OPERATOR
        ),
        200,
    )


def repack_lot(
    api: ApiClient,
    lot_id: str,
    output_clamshell_count: int,
    cull_clamshell_count: int,
    optical_reject_clamshell_count: int,
    output_grade: str = "B",
) -> Dict[str, Any]:
    """
    Run a cooled lot across the optical sorter (PRD 3.6 "The repack line").

    "A repack **returns the newly created child lot**, not the source, with
    status 201", so the returned dict is the child.
    """
    return get_success_data(
        api.repack_fruit_lot(
            lot_id,
            f.repack_payload(
                output_clamshell_count,
                cull_clamshell_count,
                optical_reject_clamshell_count,
                output_grade,
            ),
            u.PACKHOUSE_OPERATOR,
        ),
        201,
    )


def reject_lot(
    api: ApiClient,
    lot_id: str,
    reason_code: str = "MOLD",
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Reject a lot on quality or food-safety grounds (PRD 3.6)."""
    return get_success_data(
        api.reject_fruit_lot(
            lot_id,
            f.reject_lot_payload(reject_reason_code=reason_code),
            headers or u.PACKHOUSE_OPERATOR,
        ),
        200,
    )


def cooled_lot(
    api: ApiClient,
    window_id: str,
    block_id: str,
    tunnel_id: str,
    cool_start_at: str = "2026-08-03T13:00:00Z",
    planned_cool_end_at: str = "2026-08-03T17:00:00Z",
    cool_complete_at: str = "2026-08-03T17:00:00Z",
    exit_pulp_temp_f: float = 34.0,
    entry_pulp_temp_f: float = 62.0,
    pallet_slots: int = 1,
    **lot_overrides: Any,
) -> Dict[str, Any]:
    """
    A lot packed, cooled and completed, so it sits at `COOLED`/`UNCOMMITTED`.

    PRD 3.7 requires exactly this before a line may ship: "The lot's
    `cold_chain_status` must be exactly `COOLED`".
    """
    lot = pack_lot(api, window_id, block_id, **lot_overrides)
    start_cooling(
        api,
        lot["id"],
        tunnel_id,
        cool_start_at=cool_start_at,
        planned_cool_end_at=planned_cool_end_at,
        entry_pulp_temp_f=entry_pulp_temp_f,
        pallet_slots=pallet_slots,
    )
    return complete_cooling(
        api,
        lot["id"],
        cool_complete_at=cool_complete_at,
        exit_pulp_temp_f=exit_pulp_temp_f,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — buyer programs, allocation and shipping
# ═══════════════════════════════════════════════════════════════════════════


def open_commitment(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a buyer program commitment; it starts `OPEN` (PRD 3.7)."""
    return get_success_data(
        api.create_buyer_commitment(
            f.buyer_commitment_payload(**overrides), u.SALES_MANAGER
        ),
        201,
    )


def read_commitment(
    api: ApiClient, commitment_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one buyer commitment; its `version` is the allocation token."""
    return get_success_data(
        api.get_buyer_commitment(commitment_id, headers or u.SALES_MANAGER), 200
    )


def commitment_version(api: ApiClient, commitment_id: str) -> int:
    """
    Re-read a commitment's current `version` for the allocation guard.

    PRD 2.8: "Re-reading the commitment and resubmitting succeeds while
    `open_lbs` still covers the request."
    """
    return int(read_commitment(api, commitment_id)["version"])


def allocate(
    api: ApiClient,
    lot_id: str,
    commitment_id: str,
    allocated_lbs: float,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Pledge pounds from a lot to a commitment, creating a `RESERVED` line.

    The commitment is re-read for its current `version` unless the caller
    supplies one deliberately, because "Every accepted allocation, release,
    ship and cascaded release mutates `committed_lbs` or `shipped_lbs` and
    advances the commitment's `version`" (PRD 2.8).
    """
    version = (
        expected_version
        if expected_version is not None
        else commitment_version(api, commitment_id)
    )
    return get_success_data(
        api.create_lot_allocation(
            f.lot_allocation_payload(lot_id, commitment_id, allocated_lbs, version),
            u.SALES_MANAGER,
        ),
        201,
    )


def read_allocation(
    api: ApiClient, allocation_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Read one allocation line including its settled money figures."""
    return get_success_data(
        api.get_lot_allocation(allocation_id, headers or u.SALES_MANAGER), 200
    )


def ship_allocation(
    api: ApiClient, allocation_id: str, shipped_at: str = "2026-08-05T09:00:00Z"
) -> Dict[str, Any]:
    """Ship an allocation line `RESERVED → SHIPPED` (PRD 3.7)."""
    return get_success_data(
        api.ship_lot_allocation(
            allocation_id, f.ship_payload(shipped_at), u.SALES_MANAGER
        ),
        200,
    )


def release_allocation(
    api: ApiClient, allocation_id: str, reason_code: str = "BUYER_CANCELLED"
) -> Dict[str, Any]:
    """Release a `RESERVED` line back to inventory (PRD 3.7)."""
    return get_success_data(
        api.release_lot_allocation(
            allocation_id,
            f.release_payload(release_reason_code=reason_code),
            u.SALES_MANAGER,
        ),
        200,
    )


def settle_commitment(api: ApiClient, commitment_id: str) -> Dict[str, Any]:
    """Settle a buyer program after its delivery window has passed (PRD 3.7)."""
    return get_success_data(
        api.settle_buyer_commitment(commitment_id, u.SALES_MANAGER), 200
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3 — full lifecycle shortcuts
# ═══════════════════════════════════════════════════════════════════════════


def harvest_ready(
    api: ApiClient,
    block_name: Optional[str] = None,
    variety: str = "STRAWBERRY",
    picker_count: int = 1,
    planned_head_count: Optional[int] = None,
    supervisor_user_id: str = u.SUP_1,
    labor_program: str = "DOMESTIC",
    hygiene_training_on: str = "2026-06-01",
    support_plan: Optional[Dict[str, Any]] = None,
    block_overrides: Optional[Dict[str, Any]] = None,
    crew_overrides: Optional[Dict[str, Any]] = None,
    **window_overrides: Any,
) -> Dict[str, Any]:
    """
    Everything needed to record a pick session or pack a lot: a `CLEARED`
    block, a `CERTIFIED` crew with pickers, and an `OPEN` harvest window.

    The block is sampled once so that its posture is `CLEARED`, which PRD 3.3
    requires for opening: "The block's `food_safety_posture` must be exactly
    `CLEARED`". Returns a dict of ``block``, ``crew``, ``pickers`` and
    ``window`` — every entity as read back after the window opened.
    """
    block_kwargs = dict(block_overrides or {})
    if block_name is not None:
        block_kwargs["name"] = block_name
    block = block_with_provisional_water(api, variety=variety, **block_kwargs)
    crew, pickers = certified_crew(
        api,
        picker_count=picker_count,
        planned_head_count=planned_head_count,
        supervisor_user_id=supervisor_user_id,
        labor_program=labor_program,
        hygiene_training_on=hygiene_training_on,
        support_plan=support_plan,
        **(crew_overrides or {}),
    )
    window = opened_window(api, block["id"], crew["id"], **window_overrides)
    return {
        "block": read_block(api, block["id"]),
        "crew": read_crew(api, crew["id"]),
        "pickers": pickers,
        "picker": pickers[0] if pickers else None,
        "window": window,
    }


def packing_ready(
    api: ApiClient,
    tunnel_slot_capacity: int = 4,
    tunnel_name: Optional[str] = None,
    target_pulp_temp_f: float = 34.0,
    **harvest_kwargs: Any,
) -> Dict[str, Any]:
    """
    ``harvest_ready`` plus a registered cooling tunnel.

    PRD 3.6 calls tunnels "a capacity register that lots book against"; they
    have no lifecycle, so registering one is all the setup the cold chain
    needs.
    """
    setup = harvest_ready(api, **harvest_kwargs)
    tunnel_kwargs: Dict[str, Any] = {
        "slot_capacity": tunnel_slot_capacity,
        "target_pulp_temp_f": target_pulp_temp_f,
    }
    if tunnel_name is not None:
        tunnel_kwargs["name"] = tunnel_name
    setup["tunnel"] = register_tunnel(api, **tunnel_kwargs)
    return setup


def shipping_ready(
    api: ApiClient,
    allocated_lbs: float = 50.00,
    clamshell_count: int = 50,
    commitment_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
    block_name: Optional[str] = None,
    variety: str = "STRAWBERRY",
    **harvest_kwargs: Any,
) -> Dict[str, Any]:
    """
    A shippable line: a water-`COMPLIANT` block, a `COOLED` lot and an `OPEN`
    buyer program with one `RESERVED` allocation drawn on the lot.

    The block carries three passing samples rather than one, because PRD 3.7
    demands the traceability block be "exactly `COMPLIANT`" on a ship, and
    PRD 3.1 only reaches `COMPLIANT` once at least three samples are in the
    rolling window.
    """
    block_kwargs: Dict[str, Any] = {}
    if block_name is not None:
        block_kwargs["name"] = block_name
    block = block_with_compliant_water(api, variety=variety, **block_kwargs)
    crew, pickers = certified_crew(api, **harvest_kwargs)
    window = opened_window(api, block["id"], crew["id"])
    tunnel = register_tunnel(api, slot_capacity=4)
    lot = cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        variety=variety,
        clamshell_count=clamshell_count,
        **(lot_overrides or {}),
    )
    commitment = open_commitment(api, variety=variety, **(commitment_overrides or {}))
    allocation = allocate(api, lot["id"], commitment["id"], allocated_lbs)
    return {
        "block": read_block(api, block["id"]),
        "crew": crew,
        "pickers": pickers,
        "window": window,
        "tunnel": tunnel,
        "lot": read_lot(api, lot["id"]),
        "commitment": read_commitment(api, commitment["id"]),
        "allocation": allocation,
    }


def payroll_ready(
    api: ApiClient,
    hours_worked: float = 3.00,
    clamshells_filled: int = 20,
    culled_clamshells: int = 0,
    period_start_date: str = "2026-08-03",
    period_end_date: str = "2026-08-03",
    **harvest_kwargs: Any,
) -> Dict[str, Any]:
    """
    ``harvest_ready`` plus one `APPROVED` session and a `DRAFT` payroll run.

    PRD 3.5 binds only sessions "whose status is `APPROVED`, whose `work_date`
    lies inside the inclusive period, and whose `payroll_run_id` is still
    empty", so a lock over this setup binds exactly the one session.
    """
    setup = harvest_ready(api, **harvest_kwargs)
    session = approved_session(
        api,
        setup["window"]["id"],
        setup["picker"]["id"],
        supervisor_user_id=setup["crew"]["supervisor_user_id"],
        hours_worked=hours_worked,
        clamshells_filled=clamshells_filled,
        culled_clamshells=culled_clamshells,
    )
    setup["session"] = session
    setup["run"] = open_payroll_run(
        api,
        setup["crew"]["id"],
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    return setup


# ═══════════════════════════════════════════════════════════════════════════
# Tier 4 — accumulation and threshold targeting
# ═══════════════════════════════════════════════════════════════════════════


def water_series(
    api: ApiClient, block_id: str, samples: List[Tuple[str, int]]
) -> List[Dict[str, Any]]:
    """
    Record a whole water series in one call, in the order supplied.

    PRD 3.1 orders the rolling window "by `sample_date` ascending and, within a
    shared date, by `created_at` ascending", so the insertion order of a
    same-date pair is itself significant.
    """
    return [
        record_water_sample(
            api, block_id, sample_date=sample_date, generic_ecoli_mpn=mpn
        )
        for sample_date, mpn in samples
    ]


def two_same_day_windows(
    api: ApiClient,
    block_a_id: str,
    block_b_id: str,
    crew_id: str,
    start_a: str = "2026-08-03T06:00:00Z",
    end_a: str = "2026-08-03T14:00:00Z",
    start_b: str = "2026-08-04T06:00:00Z",
    end_b: str = "2026-08-04T14:00:00Z",
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Two `OPEN` windows on different blocks, one per calendar date.

    PRD 3.3 forbids a multi-day window — "`end_at` ... must fall on the same
    calendar date" — and PRD 3.3 makes adjacency on one block a re-entry
    conflict, so spanning two work dates needs two blocks.
    """
    window_a = opened_window(
        api, block_a_id, crew_id, start_at=start_a, end_at=end_a, **overrides
    )
    window_b = opened_window(
        api, block_b_id, crew_id, start_at=start_b, end_at=end_b, **overrides
    )
    return window_a, window_b


def lots_on_block(
    api: ApiClient,
    window_id: str,
    block_id: str,
    specs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Pack a series of lots against one window, in the order supplied.

    PRD 3.6 numbers `traceability_code` from "the number of lots that already
    share the same `block_id`, `pick_date` and `grade`, counted in `created_at`
    ascending order", so insertion order determines the sequence family.
    """
    return [pack_lot(api, window_id, block_id, **spec) for spec in specs]


# ═══════════════════════════════════════════════════════════════════════════
# Tier 5 — list-read helpers (the only discovery channels of PRD 2.11)
# ═══════════════════════════════════════════════════════════════════════════


def list_sessions(
    api: ApiClient, headers: Optional[Dict] = None, **params: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The pick-session list — the only channel for cascade-touched sessions."""
    response = api.list_pick_sessions(headers or u.HARVEST_MANAGER, params or None)
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]


def list_lots(
    api: ApiClient, headers: Optional[Dict] = None, **params: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The fruit-lot list — the only channel for a repack child lot."""
    response = api.list_fruit_lots(headers or u.PACKHOUSE_OPERATOR, params or None)
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]


def list_allocations(
    api: ApiClient, headers: Optional[Dict] = None, **params: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The allocation list — the only channel for cascade-released lines."""
    response = api.list_lot_allocations(headers or u.SALES_MANAGER, params or None)
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]


def list_windows(
    api: ApiClient, headers: Optional[Dict] = None, **params: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The harvest-window list, filterable by block, crew or status."""
    response = api.list_harvest_windows(headers or u.HARVEST_MANAGER, params or None)
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]
