"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty DB) before every
test. All helpers use get_success_data() (lenient) so setup failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.

Identity note: every role's X-User-ID is opaque (PRD §2.1); there is no
ownership-gating, so the shared TEST_USERS headers are used throughout.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
GATE_CTRL = TEST_USERS["gate_controller_headers"]
RAMP = TEST_USERS["ramp_agent_headers"]
SLOT = TEST_USERS["slot_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — registry primitives
# ---------------------------------------------------------------------------
def register_gate(code="A12", terminal="T1", max_wingspan_m=80, buffer_minutes=10, **extra):
    payload = {"code": code, "terminal": terminal, "max_wingspan_m": max_wingspan_m,
               "buffer_minutes": buffer_minutes}
    payload.update(extra)
    return get_success_data(api_client.create_gate(payload, OPS))


def register_remote_stand(code="R5", max_wingspan_m=80, capacity=1, **extra):
    payload = {"code": code, "max_wingspan_m": max_wingspan_m, "capacity": capacity}
    payload.update(extra)
    return get_success_data(api_client.create_remote_stand(payload, OPS))


def register_cute_unit(label="CUTE-3", terminal="T1", **extra):
    payload = {"label": label, "terminal": terminal}
    payload.update(extra)
    return get_success_data(api_client.create_cute_unit(payload, OPS))


def register_ground_equipment(asset_tag="GPU-07", equipment_type="GPU", turnaround_minutes=0, **extra):
    payload = {"asset_tag": asset_tag, "equipment_type": equipment_type,
               "turnaround_minutes": turnaround_minutes}
    payload.update(extra)
    return get_success_data(api_client.create_ground_equipment(payload, OPS))


def create_flight(flight_no="AA482", aircraft_wingspan_m=60,
                  sched_arrival_utc="2026-06-10T08:00:00Z",
                  sched_departure_utc="2026-06-10T10:00:00Z",
                  min_turn_minutes=45, **extra):
    payload = {"flight_no": flight_no, "aircraft_wingspan_m": aircraft_wingspan_m,
               "sched_arrival_utc": sched_arrival_utc,
               "sched_departure_utc": sched_departure_utc,
               "min_turn_minutes": min_turn_minutes}
    payload.update(extra)
    return get_success_data(api_client.create_flight(payload, OPS))


def activate_flight(flight_id):
    return get_success_data(api_client.activate_flight(flight_id, OPS))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


# ---------------------------------------------------------------------------
# Tier 1/2 — gate assignment creation (GATE / REMOTE)
# ---------------------------------------------------------------------------
def create_gate_assignment(flight_id, gate_id, start_utc, end_utc, expected_gate_version):
    """Create a GATE-stand assignment (PLANNED). Returns the assignment."""
    payload = {"flight_id": flight_id, "stand_type": "GATE", "gate_id": gate_id,
               "start_utc": start_utc, "end_utc": end_utc,
               "expected_gate_version": expected_gate_version}
    return get_success_data(api_client.create_gate_assignment(payload, GATE_CTRL))


def create_remote_assignment(flight_id, remote_stand_id, start_utc, end_utc):
    """Create a REMOTE-stand assignment (PLANNED). Returns the assignment."""
    payload = {"flight_id": flight_id, "stand_type": "REMOTE",
               "remote_stand_id": remote_stand_id,
               "start_utc": start_utc, "end_utc": end_utc}
    return get_success_data(api_client.create_gate_assignment(payload, GATE_CTRL))


def current_gate_version(gate_id):
    return get_success_data(api_client.get_gate(gate_id, GATE_CTRL))["version"]


# ---------------------------------------------------------------------------
# Tier 2/3 — composite scenarios reused across difficulty + corner translations
# ---------------------------------------------------------------------------
def setup_gate_and_flight(gate_kwargs=None, flight_kwargs=None):
    """Register one gate + one flight. Returns (gate, flight)."""
    gate = register_gate(**(gate_kwargs or {}))
    flight = create_flight(**(flight_kwargs or {}))
    return gate, flight


def setup_planned_gate_assignment(gate_kwargs=None, flight_kwargs=None,
                                  start_utc="2026-06-10T08:00:00Z",
                                  end_utc="2026-06-10T10:00:00Z"):
    """Gate + flight + one PLANNED GATE assignment. Returns (gate, flight, assignment)."""
    gate, flight = setup_gate_and_flight(gate_kwargs, flight_kwargs)
    assignment = create_gate_assignment(flight["id"], gate["id"], start_utc, end_utc,
                                        gate["version"])
    return gate, flight, assignment


def setup_occupied_gate_assignment(gate_kwargs=None, flight_kwargs=None,
                                   start_utc="2026-06-10T08:00:00Z",
                                   end_utc="2026-06-10T12:00:00Z", activate=False):
    """Gate + flight + PLANNED->OCCUPIED assignment. Returns (gate, flight, assignment)."""
    gate, flight = setup_gate_and_flight(gate_kwargs, flight_kwargs)
    if activate:
        activate_flight(flight["id"])
    assignment = create_gate_assignment(flight["id"], gate["id"], start_utc, end_utc,
                                        gate["version"])
    get_success_data(api_client.occupy_gate_assignment(assignment["id"], RAMP))
    return gate, flight, assignment


def setup_towed_assignment(gate_kwargs=None, flight_kwargs=None,
                           remote_kwargs=None,
                           start_utc="2026-06-10T08:00:00Z",
                           end_utc="2026-06-10T12:00:00Z"):
    """Gate + remote stand + flight; assignment occupied at gate then towed to the
    remote stand (status TOWED_AWAY). Returns (gate, remote, flight, assignment)."""
    gate, flight, assignment = setup_occupied_gate_assignment(
        gate_kwargs, flight_kwargs, start_utc, end_utc)
    remote = register_remote_stand(**(remote_kwargs or {}))
    get_success_data(api_client.tow_gate_assignment(
        assignment["id"], {"target_remote_stand_id": remote["id"]}, GATE_CTRL))
    return gate, remote, flight, assignment


# ---------------------------------------------------------------------------
# Tier 3 — slot permit lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_slot_permit(flight_id, movement_type="ARRIVAL",
                       slot_time_utc="2026-06-10T12:00:00Z", tolerance_minutes=15):
    payload = {"flight_id": flight_id, "movement_type": movement_type,
               "slot_time_utc": slot_time_utc, "tolerance_minutes": tolerance_minutes}
    return get_success_data(api_client.create_slot_permit(payload, SLOT))


def setup_confirmed_slot_permit(flight_kwargs=None, movement_type="ARRIVAL",
                                slot_time_utc="2026-06-10T12:00:00Z",
                                tolerance_minutes=15):
    """Flight + a CONFIRMED slot permit. Returns (flight, permit)."""
    flight = create_flight(**(flight_kwargs or {}))
    permit = create_slot_permit(flight["id"], movement_type, slot_time_utc, tolerance_minutes)
    permit = get_success_data(api_client.confirm_slot_permit(permit["id"], SLOT))
    return flight, permit


# ---------------------------------------------------------------------------
# Tier 3 — allocation lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_cute_allocation(flight_id, cute_unit_id, start_utc, end_utc):
    payload = {"flight_id": flight_id, "cute_unit_id": cute_unit_id,
               "start_utc": start_utc, "end_utc": end_utc}
    return get_success_data(api_client.create_cute_allocation(payload, RAMP))


def create_gse_allocation(flight_id, equipment_id, start_utc, end_utc):
    payload = {"flight_id": flight_id, "equipment_id": equipment_id,
               "start_utc": start_utc, "end_utc": end_utc}
    return get_success_data(api_client.create_gse_allocation(payload, RAMP))


# ---------------------------------------------------------------------------
# Tier 5 — full IROPS-ready composite (active flight occupying a gate, with a
# confirmed slot permit and a held GSE allocation). Reused by both IROPS depth
# instances. The caller decides cancel vs divert.
# ---------------------------------------------------------------------------
def setup_active_flight_full_commitments(with_gse=True):
    """
    Active flight occupying Gate G1 (OCCUPIED assignment), one CONFIRMED
    SlotPermit, and (optionally) one HELD GseAllocation.
    Returns dict with keys: gate, flight, assignment, permit, gse, equipment.
    """
    gate = register_gate(code="E1", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    flight = create_flight(flight_no="AF5", aircraft_wingspan_m=60,
                           sched_arrival_utc="2026-06-10T08:00:00Z",
                           sched_departure_utc="2026-06-10T10:00:00Z",
                           min_turn_minutes=45)
    activate_flight(flight["id"])
    assignment = create_gate_assignment(flight["id"], gate["id"],
                                        "2026-06-10T08:00:00Z", "2026-06-10T10:00:00Z",
                                        gate["version"])
    get_success_data(api_client.occupy_gate_assignment(assignment["id"], RAMP))
    permit = create_slot_permit(flight["id"], "ARRIVAL", "2026-06-10T08:00:00Z", 15)
    permit = get_success_data(api_client.confirm_slot_permit(permit["id"], SLOT))
    equipment = None
    gse = None
    if with_gse:
        equipment = register_ground_equipment(asset_tag="GPU-1", equipment_type="GPU",
                                               turnaround_minutes=0)
        gse = create_gse_allocation(flight["id"], equipment["id"],
                                    "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    return {"gate": gate, "flight": flight, "assignment": assignment,
            "permit": permit, "gse": gse, "equipment": equipment}
