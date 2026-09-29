"""Composite setup helpers for the fastener plant.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only — the database is empty at the start of each test. Setup calls go through
``get_success_data`` so a broken precondition surfaces as an explicit
"Setup step failed" rather than as a confusing assertion later.

Layering, from the bottom up:

* single-call wrappers (``register_part_spec``, ``mount_tool``, ...)
* short sequences (``create_verified_heat``, ``create_released_wire_lot``,
  ``run_secondary_op``, ``run_heat_treat``, ``plate_and_bake``, ...)
* whole-route composites (``setup_master_data``, ``setup_headed_lot``,
  ``setup_secondary_done_lot``, ``setup_baked_lot``, ``setup_tested_lot``,
  ``setup_certified_lot``, ``setup_sealed_pack``, ``setup_shipped_pack``)

Whole-route composites return a plain dict keyed by role name ("spec", "heat",
"wire", "tool", "furnace", "lot", ...) so a test can reach any intermediate
record without re-fetching it.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    complete_heading_payload,
    create_certification_document_payload,
    create_furnace_payload,
    create_heading_tool_payload,
    create_heat_treat_run_payload,
    create_lot_test_payload,
    create_pack_unit_payload,
    create_part_spec_payload,
    create_plating_run_payload,
    create_production_lot_payload,
    create_steel_heat_payload,
    create_unplated_part_spec_payload,
    create_wire_lot_payload,
    heat_treat_results_payload,
    lot_test_results_payload,
    queue_secondary_operation_payload,
    start_bake_payload,
    verify_mill_cert_payload,
)
from .test_users import (
    TEST_USERS,
    make_clerk_headers,
    make_inspector_headers,
    make_manager_headers,
)

ENGINEER = TEST_USERS["engineer_headers"]
HEAT_TREAT = TEST_USERS["heat_treat_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(instant: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical plant clock to ``instant``."""
    return get_success_data(api_client.set_clock(instant, headers or ENGINEER))


# ---------------------------------------------------------------------------
# Master data — single-call wrappers
# ---------------------------------------------------------------------------
def register_part_spec(headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_part_spec(
            create_part_spec_payload(**overrides), headers or ENGINEER
        )
    )


def register_unplated_part_spec(
    headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_part_spec(
            create_unplated_part_spec_payload(**overrides), headers or ENGINEER
        )
    )


def revise_part_spec(
    part_spec_id: str, headers: Optional[Dict[str, str]] = None, **fields
) -> Dict[str, Any]:
    return get_success_data(
        api_client.revise_part_spec(part_spec_id, fields, headers or ENGINEER)
    )


def register_steel_heat(headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_steel_heat(
            create_steel_heat_payload(**overrides), headers or INSPECTOR
        )
    )


def verify_heat(
    steel_heat_id: str,
    inspector_user_id: str = "insp-1",
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_mill_cert(
            steel_heat_id,
            verify_mill_cert_payload(**overrides),
            make_inspector_headers(inspector_user_id),
        )
    )


def create_verified_heat(
    inspector_user_id: str = "insp-1", **overrides
) -> Dict[str, Any]:
    """Register a steel heat and take it PENDING -> VERIFIED."""
    heat = register_steel_heat(**overrides)
    verify_heat(
        heat["id"],
        inspector_user_id=inspector_user_id,
        mill_cert_serial=heat["mill_cert_serial"],
    )
    return get_success_data(api_client.get_steel_heat(heat["id"], INSPECTOR))


def flag_heat_counterfeit(
    steel_heat_id: str, reason: str = "SERIAL_NOT_ON_MILL_REGISTER"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.flag_counterfeit(steel_heat_id, {"reason": reason}, MANAGER)
    )


def register_wire_lot(
    steel_heat_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_wire_lot(
            create_wire_lot_payload(steel_heat_id, **overrides), headers or ENGINEER
        )
    )


def release_wire_lot(wire_lot_id: str, inspector_user_id: str = "insp-1") -> Dict[str, Any]:
    return get_success_data(
        api_client.release_wire_lot(
            wire_lot_id, make_inspector_headers(inspector_user_id)
        )
    )


def create_released_wire_lot(steel_heat_id: str, **overrides) -> Dict[str, Any]:
    """Record a drawn wire lot and take it DRAWN -> RELEASED."""
    wire = register_wire_lot(steel_heat_id, **overrides)
    return release_wire_lot(wire["id"])


def register_heading_tool(
    headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_heading_tool(
            create_heading_tool_payload(**overrides), headers or ENGINEER
        )
    )


def mount_tool(heading_tool_id: str, press_code: str = "PRESS-3") -> Dict[str, Any]:
    return get_success_data(
        api_client.mount_heading_tool(
            heading_tool_id, {"press_code": press_code}, ENGINEER
        )
    )


def condemn_tool(heading_tool_id: str, reason: str = "CHIPPED_STATION_3") -> Dict[str, Any]:
    return get_success_data(
        api_client.condemn_heading_tool(heading_tool_id, {"reason": reason}, ENGINEER)
    )


def regrind_tool(heading_tool_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.regrind_heading_tool(heading_tool_id, ENGINEER))


def create_mounted_tool(press_code: str = "PRESS-3", **overrides) -> Dict[str, Any]:
    """Register a fresh die set and mount it, opening a life cycle."""
    tool = register_heading_tool(**overrides)
    return mount_tool(tool["id"], press_code)


def register_furnace(headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_furnace(
            create_furnace_payload(**overrides), headers or ENGINEER
        )
    )


# ---------------------------------------------------------------------------
# Fresh reads (version threading for the two optimistic-concurrency writes)
# ---------------------------------------------------------------------------
def read_wire_lot(wire_lot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_wire_lot(wire_lot_id, ENGINEER))


def read_lot(production_lot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_production_lot(production_lot_id, ENGINEER))


def read_tool(heading_tool_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_heading_tool(heading_tool_id, ENGINEER))


def read_furnace(furnace_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_furnace(furnace_id, ENGINEER))


def read_heat(steel_heat_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_steel_heat(steel_heat_id, ENGINEER))


def read_part_spec(part_spec_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_part_spec(part_spec_id, ENGINEER))


def read_heat_treat_run(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_heat_treat_run(run_id, ENGINEER))


def read_certificate(cert_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_certification_document(cert_id, ENGINEER))


def read_pack_unit(pack_unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pack_unit(pack_unit_id, ENGINEER))


def wire_lot_version(wire_lot_id: str) -> int:
    """The wire lot ``version`` a lot-opening client must echo back."""
    return read_wire_lot(wire_lot_id)["version"]


def lot_version(production_lot_id: str) -> int:
    """The production lot ``version`` a certificate-drafting client must echo back."""
    return read_lot(production_lot_id)["version"]


# ---------------------------------------------------------------------------
# Production lot lifecycle
# ---------------------------------------------------------------------------
def open_production_lot(
    part_spec_id: str,
    wire_lot_id: str,
    heading_tool_id: str,
    expected_wire_lot_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Open a lot, reading the wire lot's live ``version`` unless one is given."""
    if expected_wire_lot_version is None:
        expected_wire_lot_version = wire_lot_version(wire_lot_id)
    payload = create_production_lot_payload(
        part_spec_id, wire_lot_id, heading_tool_id, expected_wire_lot_version, **overrides
    )
    return get_success_data(
        api_client.create_production_lot(payload, headers or ENGINEER)
    )


def report_heading(
    production_lot_id: str, headed_count: int, heading_scrap_count: int
) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_heading(
            production_lot_id,
            complete_heading_payload(
                headed_count=headed_count, heading_scrap_count=heading_scrap_count
            ),
            ENGINEER,
        )
    )


def abort_heading(production_lot_id: str, reason: str = "PRESS_DOWN") -> Dict[str, Any]:
    return get_success_data(
        api_client.abort_heading(production_lot_id, {"reason": reason}, ENGINEER)
    )


def place_hold(production_lot_id: str, reason: str = "CUSTOMER_QUERY") -> Dict[str, Any]:
    return get_success_data(
        api_client.hold_production_lot(production_lot_id, {"reason": reason}, INSPECTOR)
    )


def release_hold(production_lot_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    payload = {} if note is None else {"note": note}
    return get_success_data(
        api_client.release_hold(production_lot_id, payload, MANAGER)
    )


# ---------------------------------------------------------------------------
# Secondary operations
# ---------------------------------------------------------------------------
def queue_op(
    production_lot_id: str,
    op_type: str = "THREAD_ROLL",
    sequence_no: int = 1,
    machine_code: str = "TR-1",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.queue_secondary_operation(
            production_lot_id,
            queue_secondary_operation_payload(
                op_type=op_type, sequence_no=sequence_no, machine_code=machine_code
            ),
            ENGINEER,
        )
    )


def complete_op(secondary_operation_id: str, pieces_out: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_secondary_operation(
            secondary_operation_id, {"pieces_out": pieces_out}, ENGINEER
        )
    )


def run_secondary_op(
    production_lot_id: str,
    op_type: str = "THREAD_ROLL",
    sequence_no: int = 1,
    pieces_out: Optional[int] = None,
    machine_code: str = "TR-1",
) -> Dict[str, Any]:
    """Queue one operation and close it. With ``pieces_out`` omitted nothing is scrapped."""
    op = queue_op(production_lot_id, op_type, sequence_no, machine_code)
    if pieces_out is None:
        pieces_out = op["pieces_in"]
    return complete_op(op["id"], pieces_out)


# ---------------------------------------------------------------------------
# Heat treatment
# ---------------------------------------------------------------------------
def book_heat_treat(
    production_lot_id: str,
    furnace_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_heat_treat_run(
            create_heat_treat_run_payload(production_lot_id, furnace_id, **overrides),
            headers or HEAT_TREAT,
        )
    )


def start_heat_treat(heat_treat_run_id: str, at: Optional[str] = None) -> Dict[str, Any]:
    if at is not None:
        set_clock(at, HEAT_TREAT)
    return get_success_data(
        api_client.start_heat_treat_run(heat_treat_run_id, HEAT_TREAT)
    )


def record_heat_treat_results(
    heat_treat_run_id: str,
    at: Optional[str] = None,
    inspector_user_id: str = "insp-1",
    **overrides,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(at, HEAT_TREAT)
    return get_success_data(
        api_client.record_heat_treat_results(
            heat_treat_run_id,
            heat_treat_results_payload(**overrides),
            make_inspector_headers(inspector_user_id),
        )
    )


def run_heat_treat(
    production_lot_id: str,
    furnace_id: str,
    start_at: str = "2026-09-01T19:00:00Z",
    results_at: str = "2026-09-01T22:00:00Z",
    core_hardness_hv: float = 330.0,
    surface_decarb_depth_mm: float = 0.020,
    **booking_overrides,
) -> Dict[str, Any]:
    """Book a furnace window, start the run inside it and record its results.

    Returns the COMPLETED run. Defaults land a PASS for the reference part spec.
    """
    run = book_heat_treat(production_lot_id, furnace_id, **booking_overrides)
    start_heat_treat(run["id"], at=start_at)
    return record_heat_treat_results(
        run["id"],
        at=results_at,
        core_hardness_hv=core_hardness_hv,
        surface_decarb_depth_mm=surface_decarb_depth_mm,
    )


# ---------------------------------------------------------------------------
# Plating and the relief bake
# ---------------------------------------------------------------------------
def schedule_plating(
    production_lot_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_plating_run(
            create_plating_run_payload(production_lot_id, **overrides),
            headers or HEAT_TREAT,
        )
    )


def complete_plating(plating_run_id: str, at: Optional[str] = None) -> Dict[str, Any]:
    if at is not None:
        set_clock(at, HEAT_TREAT)
    return get_success_data(api_client.complete_plating(plating_run_id, HEAT_TREAT))


def start_bake(
    plating_run_id: str, at: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    if at is not None:
        set_clock(at, HEAT_TREAT)
    return get_success_data(
        api_client.start_bake(plating_run_id, start_bake_payload(**overrides), HEAT_TREAT)
    )


def complete_bake(plating_run_id: str, at: Optional[str] = None) -> Dict[str, Any]:
    if at is not None:
        set_clock(at, HEAT_TREAT)
    return get_success_data(api_client.complete_bake(plating_run_id, HEAT_TREAT))


def plate_and_bake(
    production_lot_id: str,
    plated_at: Optional[str] = None,
    bake_started_at: Optional[str] = None,
    bake_completed_at: Optional[str] = None,
    bake_temp_c: float = 210.0,
    bake_duration_min: int = 240,
) -> Dict[str, Any]:
    """Schedule plating, complete it, run the relief bake and close it.

    The three instants drive the logical clock, which is what fixes
    ``bake_delay_hours`` and the elapsed-soak check. Returns the BAKE_COMPLETE run.
    """
    run = schedule_plating(production_lot_id)
    complete_plating(run["id"], at=plated_at)
    start_bake(
        run["id"],
        at=bake_started_at,
        bake_temp_c=bake_temp_c,
        bake_duration_min=bake_duration_min,
    )
    return complete_bake(run["id"], at=bake_completed_at)


def plate_without_bake(
    production_lot_id: str,
    plated_at: Optional[str] = None,
    bake_completed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Plate a part whose ``he_bake_required`` is false and close the run directly."""
    run = schedule_plating(production_lot_id)
    complete_plating(run["id"], at=plated_at)
    return complete_bake(run["id"], at=bake_completed_at)


# ---------------------------------------------------------------------------
# Destructive lot tests
# ---------------------------------------------------------------------------
def open_lot_test(
    production_lot_id: str, inspector_user_id: str = "insp-1"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_lot_test(
            create_lot_test_payload(production_lot_id),
            make_inspector_headers(inspector_user_id),
        )
    )


def record_lot_test_results(
    lot_test_id: str, inspector_user_id: str = "insp-1", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_lot_test_results(
            lot_test_id,
            lot_test_results_payload(**overrides),
            make_inspector_headers(inspector_user_id),
        )
    )


def run_lot_test(
    production_lot_id: str,
    inspector_user_id: str = "insp-1",
    proof_load_failures: int = 0,
    tensile_failures: int = 0,
    min_measured_core_hardness_hv: float = 330.0,
) -> Dict[str, Any]:
    """Open a destructive test and record its results. Returns the closed test."""
    test = open_lot_test(production_lot_id, inspector_user_id)
    return record_lot_test_results(
        test["id"],
        inspector_user_id=inspector_user_id,
        proof_load_failures=proof_load_failures,
        tensile_failures=tensile_failures,
        min_measured_core_hardness_hv=min_measured_core_hardness_hv,
    )


# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------
def draft_certificate(
    production_lot_id: str,
    lot_test_id: str,
    cert_serial: str = "COC-2026-0001",
    expected_production_lot_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draft a certificate, reading the lot's live ``version`` unless one is given."""
    if expected_production_lot_version is None:
        expected_production_lot_version = lot_version(production_lot_id)
    payload = create_certification_document_payload(
        production_lot_id,
        lot_test_id,
        expected_production_lot_version,
        cert_serial=cert_serial,
    )
    return get_success_data(
        api_client.create_certification_document(payload, headers or INSPECTOR)
    )


def issue_certificate(cert_id: str, manager_user_id: str = "qm-1") -> Dict[str, Any]:
    return get_success_data(
        api_client.issue_certification_document(
            cert_id, make_manager_headers(manager_user_id)
        )
    )


def revoke_certificate(
    cert_id: str, reason: str = "CUSTOMER_COMPLAINT", manager_user_id: str = "qm-1"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.revoke_certification_document(
            cert_id, {"reason": reason}, make_manager_headers(manager_user_id)
        )
    )


def reissue_certificate(
    cert_id: str, cert_serial: str = "COC-2026-0002", manager_user_id: str = "qm-1"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.reissue_certification_document(
            cert_id, {"cert_serial": cert_serial}, make_manager_headers(manager_user_id)
        )
    )


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------
def open_pack(
    production_lot_id: str,
    certification_document_id: str,
    clerk_user_id: str = "ship-1",
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pack_unit(
            create_pack_unit_payload(
                production_lot_id, certification_document_id, **overrides
            ),
            make_clerk_headers(clerk_user_id),
        )
    )


def seal_pack(pack_unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.seal_pack_unit(pack_unit_id, CLERK))


def reopen_pack(pack_unit_id: str, reason: str = "RECOUNT") -> Dict[str, Any]:
    return get_success_data(
        api_client.reopen_pack_unit(pack_unit_id, {"reason": reason}, CLERK)
    )


def ship_pack(pack_unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.ship_pack_unit(pack_unit_id, CLERK))


# ---------------------------------------------------------------------------
# Whole-route composites
# ---------------------------------------------------------------------------
def setup_master_data(
    clock: Optional[str] = "2026-09-01T06:00:00Z",
    spec_overrides: Optional[Dict[str, Any]] = None,
    heat_overrides: Optional[Dict[str, Any]] = None,
    wire_overrides: Optional[Dict[str, Any]] = None,
    tool_overrides: Optional[Dict[str, Any]] = None,
    furnace_overrides: Optional[Dict[str, Any]] = None,
    unplated: bool = False,
    press_code: str = "PRESS-3",
    release_wire: bool = True,
    mount: bool = True,
) -> Dict[str, Any]:
    """Part spec + VERIFIED heat + RELEASED wire lot + MOUNTED die set + furnace.

    This is the preamble every production route needs. ``unplated=True`` swaps in
    a ``plating_spec`` of ``NONE`` part so the lot can be tested straight from
    ``HEAT_TREATED``.
    """
    if clock is not None:
        set_clock(clock)
    maker = register_unplated_part_spec if unplated else register_part_spec
    spec = maker(**(spec_overrides or {}))
    heat = create_verified_heat(**(heat_overrides or {}))
    wire = register_wire_lot(heat["id"], **(wire_overrides or {}))
    if release_wire:
        wire = release_wire_lot(wire["id"])
    tool = register_heading_tool(**(tool_overrides or {}))
    if mount:
        tool = mount_tool(tool["id"], press_code)
    furnace = register_furnace(**(furnace_overrides or {}))
    return {
        "spec": spec,
        "heat": heat,
        "wire": wire,
        "tool": tool,
        "furnace": furnace,
        "press_code": press_code,
    }


def setup_lot_in_setup(
    planned_pieces: int = 5000, env: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Master data plus one production lot in ``SETUP`` / ``IN_PROCESS``."""
    lot_overrides = kwargs.pop("lot_overrides", {}) or {}
    env = env or setup_master_data(**kwargs)
    lot = open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        planned_pieces=planned_pieces,
        **lot_overrides,
    )
    env["lot"] = lot
    return env


def setup_headed_lot(
    planned_pieces: int = 5000,
    headed_count: int = 4900,
    heading_scrap_count: int = 60,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A lot reported through heading: ``process_state`` ``HEADED``."""
    env = setup_lot_in_setup(planned_pieces=planned_pieces, env=env, **kwargs)
    env["lot"] = report_heading(env["lot"]["id"], headed_count, heading_scrap_count)
    return env


def setup_secondary_done_lot(
    planned_pieces: int = 5000,
    headed_count: int = 4900,
    heading_scrap_count: int = 60,
    ops: Optional[List[Dict[str, Any]]] = None,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A lot whose required secondary operations are all ``DONE``.

    ``ops`` is a list of ``{"op_type", "sequence_no", "pieces_out", "machine_code"}``
    dicts; the default runs a single ``THREAD_ROLL`` yielding 4850 pieces.
    """
    env = setup_headed_lot(
        planned_pieces=planned_pieces,
        headed_count=headed_count,
        heading_scrap_count=heading_scrap_count,
        env=env,
        **kwargs,
    )
    if ops is None:
        ops = [
            {
                "op_type": "THREAD_ROLL",
                "sequence_no": 1,
                "pieces_out": 4850,
                "machine_code": "TR-1",
            }
        ]
    env["operations"] = []
    for spec in ops:
        env["operations"].append(
            run_secondary_op(
                env["lot"]["id"],
                op_type=spec.get("op_type", "THREAD_ROLL"),
                sequence_no=spec.get("sequence_no", 1),
                pieces_out=spec.get("pieces_out"),
                machine_code=spec.get("machine_code", "TR-1"),
            )
        )
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_heat_treated_lot(
    core_hardness_hv: float = 330.0,
    surface_decarb_depth_mm: float = 0.020,
    start_at: str = "2026-09-01T19:00:00Z",
    results_at: str = "2026-09-01T22:00:00Z",
    booking_overrides: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A lot that came out of the furnace with a PASS: ``HEAT_TREATED``."""
    env = setup_secondary_done_lot(env=env, **kwargs)
    env["heat_treat_run"] = run_heat_treat(
        env["lot"]["id"],
        env["furnace"]["id"],
        start_at=start_at,
        results_at=results_at,
        core_hardness_hv=core_hardness_hv,
        surface_decarb_depth_mm=surface_decarb_depth_mm,
        **(booking_overrides or {}),
    )
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_baked_lot(
    plated_at: str = "2026-09-02T02:00:00Z",
    bake_started_at: str = "2026-09-02T04:00:00Z",
    bake_completed_at: str = "2026-09-02T10:00:00Z",
    bake_temp_c: float = 210.0,
    bake_duration_min: int = 240,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A plated lot whose relief bake has closed: ``BAKED`` with a pre-test score."""
    env = setup_heat_treated_lot(env=env, **kwargs)
    env["plating_run"] = plate_and_bake(
        env["lot"]["id"],
        plated_at=plated_at,
        bake_started_at=bake_started_at,
        bake_completed_at=bake_completed_at,
        bake_temp_c=bake_temp_c,
        bake_duration_min=bake_duration_min,
    )
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_tested_lot(
    proof_load_failures: int = 0,
    tensile_failures: int = 0,
    min_measured_core_hardness_hv: float = 330.0,
    inspector_user_id: str = "insp-1",
    unplated: bool = False,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A lot with a closed destructive test.

    With ``unplated=True`` the route stops at ``HEAT_TREATED`` and the test is
    opened straight from there, which is the unplated entry gate; otherwise the
    lot goes through plating and the relief bake to ``BAKED`` first.
    """
    if unplated:
        env = setup_heat_treated_lot(env=env, unplated=True, **kwargs)
    else:
        env = setup_baked_lot(env=env, **kwargs)
    env["lot_test"] = run_lot_test(
        env["lot"]["id"],
        inspector_user_id=inspector_user_id,
        proof_load_failures=proof_load_failures,
        tensile_failures=tensile_failures,
        min_measured_core_hardness_hv=min_measured_core_hardness_hv,
    )
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_drafted_certificate(
    cert_serial: str = "COC-2026-0001",
    drafter_headers: Optional[Dict[str, str]] = None,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A lot in ``TESTED`` with a ``DRAFT`` certificate citing its accepted test."""
    env = setup_tested_lot(env=env, **kwargs)
    env["certificate"] = draft_certificate(
        env["lot"]["id"],
        env["lot_test"]["id"],
        cert_serial=cert_serial,
        headers=drafter_headers,
    )
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_certified_lot(
    manager_user_id: str = "qm-1",
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A lot in ``CERTIFIED`` behind an ``ISSUED`` certificate."""
    env = setup_drafted_certificate(env=env, **kwargs)
    env["certificate"] = issue_certificate(
        env["certificate"]["id"], manager_user_id=manager_user_id
    )
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_open_pack(
    label_serial: str = "PK-2026-0001",
    pack_overrides: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A certified lot with one pack unit still ``OPEN``."""
    env = setup_certified_lot(env=env, **kwargs)
    env["pack"] = open_pack(
        env["lot"]["id"],
        env["certificate"]["id"],
        label_serial=label_serial,
        **(pack_overrides or {}),
    )
    return env


def setup_sealed_pack(
    env: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """A certified lot with one ``SEALED`` pack unit; the lot is ``PACKED``."""
    env = setup_open_pack(env=env, **kwargs)
    env["pack"] = seal_pack(env["pack"]["id"])
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_shipped_pack(
    env: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """A certified lot with its only pack unit ``SHIPPED``; the lot is ``SHIPPED``."""
    env = setup_sealed_pack(env=env, **kwargs)
    env["pack"] = ship_pack(env["pack"]["id"])
    env["lot"] = read_lot(env["lot"]["id"])
    return env


def setup_tool_with_one_closed_cycle(
    rated_life_pieces: int = 40000,
    cycle_pieces: int = 12000,
    press_code: str = "PRESS-3",
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A die set with exactly one closed cycle of ``cycle_pieces`` and one regrind.

    Reached the only way the API allows: mount, head a burn-in lot for exactly
    ``cycle_pieces``, condemn the set early, regrind it (which appends the cycle
    and recomputes both life budgets), then mount it again. The returned env's
    "tool" therefore carries a non-null ``observed_avg_cycle_pieces``, which is
    what makes the conservative budget bite for an aerospace part.
    """
    env = env or setup_master_data(
        tool_overrides={"rated_life_pieces": rated_life_pieces},
        press_code=press_code,
        **kwargs,
    )
    burn_in = open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=press_code,
        lot_code="L-BURNIN",
        planned_pieces=cycle_pieces,
    )
    report_heading(burn_in["id"], cycle_pieces - 100, 100)
    condemn_tool(env["tool"]["id"])
    regrind_tool(env["tool"]["id"])
    env["tool"] = mount_tool(env["tool"]["id"], press_code)
    env["burn_in_lot"] = read_lot(burn_in["id"])
    return env
