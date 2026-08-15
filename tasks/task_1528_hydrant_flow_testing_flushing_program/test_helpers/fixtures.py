"""Composite setup helpers for the hydrant flow-testing domain (PRD §3).

Every helper builds its preconditions from scratch via the public API — the
test runner restarts the server before every test, so nothing is shared.
Uses get_success_data() internally so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_program_payload,
    create_zone_payload,
    create_private_owner_payload,
    create_hydrant_payload,
    create_inspection_payload,
    record_inspection_payload,
    create_flow_test_payload,
    flow_results_payload,
    create_flush_sequence_payload,
    create_complaint_payload,
    create_outage_payload,
    create_work_order_payload,
    create_part_payload,
    create_iso_snapshot_payload,
)
from .test_users import (
    TEST_USERS,
    make_operator_headers,
    make_supervisor_headers,
    make_liaison_headers,
    make_owner_rep_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]          # X-User-ID op_1
SUP1 = TEST_USERS["supervisor_headers"]       # X-User-ID sup_1
LIAISON = TEST_USERS["liaison_headers"]       # X-User-ID fd_1


# ---------------------------------------------------------------------------
# Tier 1: base hierarchy — program / zone / hydrant
# ---------------------------------------------------------------------------

def create_program(**overrides):
    """Create an OPEN FlushingProgram. Returns the program dict."""
    resp = api_client.create_program(create_program_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_zone(**overrides):
    """Create a PressureZone (default cooldown 60 unless overridden)."""
    resp = api_client.create_zone(create_zone_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_private_owner(**overrides):
    resp = api_client.create_private_owner(create_private_owner_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_hydrant(program_id, zone_id, **overrides):
    """Create an IN_SERVICE hydrant with inspection_tier CURRENT."""
    resp = api_client.create_hydrant(create_hydrant_payload(program_id, zone_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_private_hydrant(program_id, zone_id, owner_id, **overrides):
    """Create a PRIVATE hydrant owned by the given PrivateOwner."""
    overrides["ownership"] = "PRIVATE"
    overrides["private_owner_id"] = owner_id
    return create_hydrant(program_id, zone_id, **overrides)


def setup_program_zone_hydrant(hydrant_overrides=None, zone_overrides=None):
    """Most common setup: OPEN program + zone + one MUNICIPAL hydrant.

    Returns (program, zone, hydrant).
    """
    program = create_program()
    zone = create_zone(**(zone_overrides or {}))
    hydrant = create_hydrant(program["id"], zone["id"], **(hydrant_overrides or {}))
    return program, zone, hydrant


def get_hydrant(hydrant_id, headers=None):
    return get_success_data(api_client.get_hydrant(hydrant_id, headers or ADMIN))


def get_program(program_id, headers=None):
    return get_success_data(api_client.get_program(program_id, headers or ADMIN))


def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.8)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: Inspection lifecycle
# ---------------------------------------------------------------------------

def open_inspection(hydrant_id, headers=None):
    """Open a SCHEDULED inspection, reading the hydrant's live version for OCC.

    Returns the inspection dict.
    """
    hydrant = get_hydrant(hydrant_id)
    resp = api_client.create_inspection(
        create_inspection_payload(hydrant_id, hydrant["version"]),
        headers or OP1,
    )
    return get_success_data(resp)


def record_inspection(inspection_id, headers=None, **overrides):
    """Record findings -> PENDING_VERIFICATION."""
    resp = api_client.record_inspection(
        inspection_id, record_inspection_payload(**overrides), headers or OP1
    )
    return get_success_data(resp)


def create_recorded_inspection(hydrant_id, record_headers=None, **record_overrides):
    """Open + record an inspection. Returns the PENDING_VERIFICATION inspection."""
    inspection = open_inspection(hydrant_id)
    return record_inspection(inspection["id"], headers=record_headers, **record_overrides)


def verify_inspection(inspection_id, decision="VERIFY", headers=None):
    resp = api_client.verify_inspection(inspection_id, {"decision": decision}, headers or SUP1)
    return get_success_data(resp)


def create_verified_inspection(hydrant_id, record_headers=None, performed_date="2026-08-10T00:00:00Z",
                               defects_found=False):
    """Open + record + VERIFY. Returns the VERIFIED inspection."""
    inspection = create_recorded_inspection(
        hydrant_id,
        record_headers=record_headers,
        performed_date=performed_date,
        defects_found=defects_found,
    )
    return verify_inspection(inspection["id"], decision="VERIFY", headers=SUP1)


# ---------------------------------------------------------------------------
# Tier 3: Flow-test lifecycle
# ---------------------------------------------------------------------------

def create_scheduled_flow_test(hydrant_id, window_start="2026-08-02T10:00:00Z",
                               window_end="2026-08-02T11:00:00Z", headers=None):
    resp = api_client.create_flow_test(
        create_flow_test_payload(hydrant_id, window_start=window_start, window_end=window_end),
        headers or OP1,
    )
    return get_success_data(resp)


def submit_flow_results(flow_test_id, headers=None, **overrides):
    """Submit readings (defaults: static 80 / residual 40 / pitot 64). Caller is
    responsible for placing the logical clock inside the window first."""
    resp = api_client.submit_flow_test_results(
        flow_test_id, flow_results_payload(**overrides), headers or OP1
    )
    return get_success_data(resp)


def create_submitted_flow_test(hydrant_id, clock_inside="2026-08-02T10:30:00Z",
                               window_start="2026-08-02T10:00:00Z",
                               window_end="2026-08-02T11:00:00Z", **results_overrides):
    """Schedule a flow test, move the clock inside the window, submit results.
    Returns the RESULTS_SUBMITTED flow test.
    """
    ft = create_scheduled_flow_test(hydrant_id, window_start, window_end)
    if clock_inside is not None:
        set_clock(clock_inside)
    return submit_flow_results(ft["id"], **results_overrides)


def review_flow_test(flow_test_id, decision="APPROVE", headers=None):
    resp = api_client.review_flow_test(flow_test_id, {"decision": decision}, headers or SUP1)
    return get_success_data(resp)


def create_approved_flow_test(hydrant_id, window_start="2026-08-02T10:00:00Z",
                              window_end="2026-08-02T11:00:00Z", **results_overrides):
    """Schedule + submit + APPROVE. Returns the APPROVED flow test."""
    ft = create_submitted_flow_test(
        hydrant_id,
        clock_inside="2026-08-02T10:30:00Z",
        window_start=window_start,
        window_end=window_end,
        **results_overrides,
    )
    return review_flow_test(ft["id"], decision="APPROVE", headers=SUP1)


# ---------------------------------------------------------------------------
# Tier 4: Flush-sequence lifecycle
# ---------------------------------------------------------------------------

def create_planned_sequence(program_id, zone_id, hydrant_id, steps=None, **overrides):
    payload = create_flush_sequence_payload(program_id, zone_id, hydrant_id, **overrides)
    if steps is not None:
        payload["steps"] = steps
    resp = api_client.create_flush_sequence(payload, OP1)
    return get_success_data(resp)


def start_sequence(sequence_id, source_chlorine_residual_mg_L=1.0, headers=None):
    resp = api_client.start_flush_sequence(
        sequence_id, {"source_chlorine_residual_mg_L": source_chlorine_residual_mg_L},
        headers or OP1,
    )
    return get_success_data(resp)


def execute_step(sequence_id, step_index, flow_gpm, duration_minutes, headers=None):
    resp = api_client.execute_flush_step(
        sequence_id,
        {"step_index": step_index, "flow_gpm": flow_gpm, "duration_minutes": duration_minutes},
        headers or OP1,
    )
    return get_success_data(resp)


def create_sequence_in_progress(program_id, zone_id, hydrant_id, steps=None,
                                executed_steps=None, source_residual=1.0, **overrides):
    """Sequence created, started, with the given steps executed.

    executed_steps: list of (step_index, flow_gpm, duration_minutes) tuples.
    Returns the IN_PROGRESS sequence dict (freshly read).
    """
    seq = create_planned_sequence(program_id, zone_id, hydrant_id, steps=steps, **overrides)
    start_sequence(seq["id"], source_residual)
    for step_index, flow_gpm, duration_minutes in (executed_steps or []):
        execute_step(seq["id"], step_index, flow_gpm, duration_minutes)
    return get_success_data(api_client.get_flush_sequence(seq["id"], OP1))


def complete_sequence(sequence_id, final_discharge_residual_mg_L=0.05, headers=None):
    resp = api_client.complete_flush_sequence(
        sequence_id, {"final_discharge_residual_mg_L": final_discharge_residual_mg_L},
        headers or OP1,
    )
    return get_success_data(resp)


def setup_sequence_with_linked_complaint(program, zone, hydrant, category="ODOR",
                                         source_residual=1.0, execute=True):
    """PLANNED sequence + OPEN complaint manually LINKED, then sequence started
    (and its single step executed when execute=True).

    Returns (sequence, complaint).
    """
    seq = create_planned_sequence(program["id"], zone["id"], hydrant["id"])
    complaint = get_success_data(
        api_client.create_complaint(create_complaint_payload(hydrant["id"], category=category), OP1)
    )
    complaint = get_success_data(
        api_client.link_complaint(complaint["id"], {"flush_sequence_id": seq["id"]}, OP1)
    )
    start_sequence(seq["id"], source_residual)
    if execute:
        execute_step(seq["id"], 1, 400, 10)
    seq = get_success_data(api_client.get_flush_sequence(seq["id"], OP1))
    return seq, complaint


# ---------------------------------------------------------------------------
# Tier 5: Complaint lifecycle
# ---------------------------------------------------------------------------

def create_open_complaint(hydrant_id, category="ODOR", headers=None):
    resp = api_client.create_complaint(
        create_complaint_payload(hydrant_id, category=category), headers or OP1
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 6: Outage lifecycle
# ---------------------------------------------------------------------------

def tag_hydrant_out(hydrant_id, reason="LEAK", headers=None):
    """Create an outage -> hydrant OUT_OF_SERVICE, notification PENDING.
    Returns the ACTIVE outage.
    """
    resp = api_client.create_outage(create_outage_payload(hydrant_id, reason=reason), headers or OP1)
    return get_success_data(resp)


def acknowledge_outage(outage_id, headers=None):
    resp = api_client.acknowledge_outage_notification(outage_id, headers or LIAISON)
    return get_success_data(resp)


def close_outage(outage_id, headers=None):
    resp = api_client.close_outage(outage_id, headers or OP1)
    return get_success_data(resp)


def setup_hydrant_out_of_service_acknowledged(program, zone, hydrant):
    """Hydrant tagged out and notification acknowledged (close-ready).
    Returns the ACTIVE, ACKNOWLEDGED outage.
    """
    outage = tag_hydrant_out(hydrant["id"])
    acknowledge_outage(outage["id"])
    return get_success_data(api_client.get_outage(outage["id"], OP1))


# ---------------------------------------------------------------------------
# Tier 7: Work-order lifecycle
# ---------------------------------------------------------------------------

def create_part(**overrides):
    resp = api_client.create_part(create_part_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_part(part_id, headers=None):
    return get_success_data(api_client.get_part(part_id, headers or ADMIN))


def create_draft_work_order(hydrant_id, creator_headers=None, **overrides):
    resp = api_client.create_work_order(
        create_work_order_payload(hydrant_id, **overrides), creator_headers or OP1
    )
    return get_success_data(resp)


def add_part_line(work_order_id, part_id, qty, headers=None):
    resp = api_client.add_work_order_part_line(
        work_order_id, {"part_id": part_id, "qty": qty}, headers or OP1
    )
    return get_success_data(resp)


def get_work_order(work_order_id, headers=None):
    return get_success_data(api_client.get_work_order(work_order_id, headers or ADMIN))


def create_submitted_work_order(hydrant_id, part=None, qty=1, creator_headers=None, **wo_overrides):
    """DRAFT work order with (optionally) one part line, SUBMITTED.
    Returns the work order dict.
    """
    wo = create_draft_work_order(hydrant_id, creator_headers=creator_headers, **wo_overrides)
    if part is not None:
        add_part_line(wo["id"], part["id"], qty)
    resp = api_client.submit_work_order(wo["id"], creator_headers or OP1)
    return get_success_data(resp)


def approve_work_order(work_order_id, approver_headers=None):
    """Approve using the work order's live version for OCC. Returns APPROVED order."""
    wo = get_work_order(work_order_id)
    resp = api_client.approve_work_order(
        work_order_id,
        {"expected_work_order_version": wo["version"]},
        approver_headers or SUP1,
    )
    return get_success_data(resp)


def create_approved_work_order(hydrant_id, part=None, qty=1, **wo_overrides):
    """DRAFT -> line -> SUBMITTED -> APPROVED. Returns the APPROVED order."""
    wo = create_submitted_work_order(hydrant_id, part=part, qty=qty, **wo_overrides)
    return approve_work_order(wo["id"], approver_headers=SUP1)


# ---------------------------------------------------------------------------
# Tier 8: Complaint cluster / ISO composite scenarios
# ---------------------------------------------------------------------------

def setup_complaint_cluster(program, zone, hydrant, count=3):
    """Log `count` DISCOLORED_WATER complaints at the current clock; the third
    triggers the auto-sequence cluster (PRD §3.5). Returns list of complaints."""
    complaints = []
    for _ in range(count):
        complaints.append(create_open_complaint(hydrant["id"], category="DISCOLORED_WATER"))
    return complaints


def setup_hydrant_with_two_flow_results(program, zone, hydrant):
    """Hydrant with FT1 APPROVED (80/40/64 -> Q20 1671) and FT2 left
    RESULTS_SUBMITTED (90/50/49 -> Q20 1589). Provisional 1589, approved 1671.

    Returns (ft1, ft2).
    """
    ft1 = create_approved_flow_test(
        hydrant["id"],
        window_start="2026-08-02T10:00:00Z",
        window_end="2026-08-02T11:00:00Z",
        static_psi=80, residual_psi=40, pitot_psi=64,
    )
    ft2 = create_submitted_flow_test(
        hydrant["id"],
        clock_inside="2026-08-03T10:30:00Z",
        window_start="2026-08-03T10:00:00Z",
        window_end="2026-08-03T11:00:00Z",
        static_psi=90, residual_psi=50, pitot_psi=49,
    )
    return ft1, ft2


def setup_iso_scenario():
    """Program with H1 (municipal, flow-approved + inspection-verified),
    H2 (municipal, flow-approved only), H3 (municipal, neither), and
    H4 (private, flow-approved + inspection-verified by its owner rep).

    Clock ends at 2026-08-02T10:30:00Z. Returns dict of the built entities.
    """
    program = create_program()
    zone = create_zone()
    owner = create_private_owner()
    h1 = create_hydrant(program["id"], zone["id"], hydrant_number="H-1")
    h2 = create_hydrant(program["id"], zone["id"], hydrant_number="H-2")
    h3 = create_hydrant(program["id"], zone["id"], hydrant_number="H-3")
    h4 = create_private_hydrant(program["id"], zone["id"], owner["id"], hydrant_number="H-4")

    # Flow tests: H1, H2, H4 each get an APPROVED result in the same window.
    for h in (h1, h2, h4):
        ft = create_scheduled_flow_test(h["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        set_clock("2026-08-02T10:30:00Z")
        submit_flow_results(ft["id"], static_psi=80, residual_psi=40, pitot_psi=64)
        review_flow_test(ft["id"], decision="APPROVE", headers=SUP1)

    # Verified inspections: H1 by the field operator, H4 by its owner rep.
    in1 = open_inspection(h1["id"])
    record_inspection(in1["id"], headers=OP1, performed_date="2026-07-15T00:00:00Z",
                      defects_found=False)
    verify_inspection(in1["id"], decision="VERIFY", headers=SUP1)

    in4 = open_inspection(h4["id"])
    record_inspection(in4["id"], headers=make_owner_rep_headers(owner["id"]),
                      performed_date="2026-07-15T00:00:00Z", defects_found=False)
    verify_inspection(in4["id"], decision="VERIFY", headers=SUP1)

    return {
        "program": program,
        "zone": zone,
        "owner": owner,
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "h4": h4,
    }


def create_and_publish_snapshot(program_id, weighting_profile="MUNICIPAL_ONLY"):
    """Create a DRAFT snapshot for the program and publish it. Returns the
    PUBLISHED snapshot."""
    snap = get_success_data(
        api_client.create_iso_snapshot(
            program_id, create_iso_snapshot_payload(weighting_profile=weighting_profile), ADMIN
        )
    )
    return get_success_data(api_client.publish_iso_snapshot(snap["id"], ADMIN))
