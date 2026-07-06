"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) internally so a setup failure surfaces as a clear
"Setup failed" rather than a confusing assertion error deep inside a test. Every helper
builds its preconditions from scratch using only PRD-declared endpoints, because the
server database is empty at the start of every test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_pool_project_payload, create_design_plan_payload, create_phase_gate_payload,
    create_inspection_payload, create_subcontractor_payload, create_crew_assignment_payload,
    create_change_order_payload, create_draw_request_payload, create_punch_item_payload,
)
from .test_users import TEST_USERS, make_owner_headers, make_subcontractor_headers

OWNER_USER_ID = "owner-1"

_PHASES = ["EXCAVATION", "STEEL", "PLUMBING", "GUNITE", "PLASTER"]


def _builder():
    return TEST_USERS["builder_headers"]


def _designer():
    return TEST_USERS["designer_headers"]


def _inspector():
    return TEST_USERS["inspector_headers"]


# ─── Building blocks ──────────────────────────────────────────────────────
def create_project(contract_price_cents=500000, owner_user_id=OWNER_USER_ID,
                   pool_gallons=20000, **overrides):
    """Create a NOT_STARTED PoolProject. Returns the project dict."""
    res = api_client.create_pool_project(
        create_pool_project_payload(contract_price_cents=contract_price_cents,
                                    owner_user_id=owner_user_id, pool_gallons=pool_gallons,
                                    **overrides),
        _builder())
    return get_success_data(res)


def create_design_plan(project_id, **overrides):
    """Create the project's DesignPlan in DRAFT. Returns the plan dict."""
    res = api_client.create_design_plan(create_design_plan_payload(project_id, **overrides),
                                        _designer())
    return get_success_data(res)


def _dp_transition(dp_id, action, actor_headers, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.transition_design_plan(dp_id, payload, actor_headers))


def render_and_approve_design(dp_id, owner_user_id=OWNER_USER_ID):
    """DRAFT -> RENDERED_3D -> OWNER_APPROVED."""
    _dp_transition(dp_id, "RENDER", _designer())
    _dp_transition(dp_id, "APPROVE", make_owner_headers(owner_user_id))


def create_permitted_project(contract_price_cents=500000, owner_user_id=OWNER_USER_ID):
    """Create a project and drive its single design through
    RENDER -> APPROVE -> SUBMIT_PERMIT -> ISSUE_PERMIT so design_status == PERMITTED.
    Returns (project, design_plan) — the project re-read after the permit issues.
    """
    project = create_project(contract_price_cents=contract_price_cents, owner_user_id=owner_user_id)
    dp = create_design_plan(project["id"])
    render_and_approve_design(dp["id"], owner_user_id)
    _dp_transition(dp["id"], "SUBMIT_PERMIT", _designer(), jurisdiction="City")
    dp = _dp_transition(dp["id"], "ISSUE_PERMIT", _inspector(), permit_number="P-1")
    project = get_success_data(api_client.get_pool_project(project["id"], _builder()))
    return project, dp


def create_gate(project_id, phase, budget_cents=100000):
    res = api_client.create_phase_gate(create_phase_gate_payload(project_id, phase, budget_cents),
                                       _builder())
    return get_success_data(res)


def start_gate(gate_id):
    return get_success_data(api_client.start_phase_gate(gate_id, _builder()))


def schedule_inspection(project_id, gate_id, scheduled_at="2026-06-01T10:00:00Z",
                        inspector_name="Insp"):
    res = api_client.create_inspection(
        create_inspection_payload(project_id, gate_id, scheduled_at=scheduled_at,
                                  inspector_name=inspector_name),
        _inspector())
    return get_success_data(res)


def record_inspection(inspection_id, outcome):
    return get_success_data(
        api_client.record_inspection(inspection_id, {"outcome": outcome}, _inspector()))


def start_and_pass_gate(project_id, gate_id, scheduled_at="2026-06-01T10:00:00Z"):
    """PENDING -> IN_PROGRESS -> (inspection) -> PASSED. Returns the recorded inspection."""
    start_gate(gate_id)
    ins = schedule_inspection(project_id, gate_id, scheduled_at)
    return record_inspection(ins["id"], "PASS")


def get_project(project_id):
    return get_success_data(api_client.get_pool_project(project_id, _builder()))


def get_project_version(project_id):
    return get_project(project_id)["version"]


def create_subcontractor(company_name="S", trade="GENERAL"):
    return get_success_data(
        api_client.create_subcontractor(create_subcontractor_payload(company_name, trade), _builder()))


def suspend_subcontractor(sub_id):
    return get_success_data(
        api_client.transition_subcontractor(sub_id, {"action": "SUSPEND"}, _builder()))


def book_crew(project_id, sub_id, gate_id, start_at, end_at):
    res = api_client.create_crew_assignment(
        create_crew_assignment_payload(project_id, sub_id, gate_id, start_at, end_at), _builder())
    return get_success_data(res)


def complete_crew(assignment_id, sub_id):
    return get_success_data(
        api_client.transition_crew_assignment(assignment_id, {"action": "COMPLETE"},
                                              make_subcontractor_headers(sub_id)))


def cancel_crew(assignment_id, sub_id):
    return get_success_data(
        api_client.transition_crew_assignment(assignment_id, {"action": "CANCEL"},
                                              make_subcontractor_headers(sub_id)))


def create_draw(project_id, gate_id, requested_cents, expected_version=None):
    if expected_version is None:
        expected_version = get_project_version(project_id)
    res = api_client.create_draw_request(
        create_draw_request_payload(project_id, gate_id, requested_cents, expected_version),
        _builder())
    return get_success_data(res)


def approve_draw(draw_id, owner_user_id=OWNER_USER_ID):
    return get_success_data(
        api_client.transition_draw_request(draw_id, {"action": "APPROVE"},
                                           make_owner_headers(owner_user_id)))


def fund_draw(draw_id):
    return get_success_data(
        api_client.transition_draw_request(draw_id, {"action": "FUND"}, _builder()))


def create_change_order(project_id, category, description, price_delta_cents, phase=None):
    return get_success_data(api_client.create_change_order(
        create_change_order_payload(project_id, category, description, price_delta_cents, phase=phase),
        _builder()))


def approve_change_order(co_id, owner_user_id=OWNER_USER_ID):
    return get_success_data(
        api_client.transition_change_order(co_id, {"action": "APPROVE"},
                                           make_owner_headers(owner_user_id)))


def apply_change_order(co_id):
    return get_success_data(
        api_client.transition_change_order(co_id, {"action": "APPLY"}, _builder()))


def file_punch(project_id, description, severity, actor_headers=None):
    headers = actor_headers if actor_headers is not None else make_owner_headers(OWNER_USER_ID)
    return get_success_data(
        api_client.create_punch_item(create_punch_item_payload(project_id, description, severity),
                                     headers))


# ─── Tier 2/3: shared multi-entity scenarios ──────────────────────────────
def setup_project_with_design(contract_price_cents=500000):
    """A project with a single DRAFT DesignPlan (not rendered/approved)."""
    project = create_project(contract_price_cents=contract_price_cents)
    dp = create_design_plan(project["id"])
    return project, dp


def setup_design_submitted_not_issued(contract_price_cents=500000):
    """Design OWNER_APPROVED and permit SUBMITTED but not yet ISSUED
    (design_status == DESIGN_APPROVED, below PERMITTED)."""
    project = create_project(contract_price_cents=contract_price_cents)
    dp = create_design_plan(project["id"])
    render_and_approve_design(dp["id"])
    dp = _dp_transition(dp["id"], "SUBMIT_PERMIT", _designer(), jurisdiction="City")
    return project, dp


def setup_owner_approved_design(contract_price_cents=500000):
    """Design OWNER_APPROVED with permit_status NONE (revisable)."""
    project = create_project(contract_price_cents=contract_price_cents)
    dp = create_design_plan(project["id"])
    render_and_approve_design(dp["id"])
    dp = get_success_data(api_client.get_design_plan(dp["id"], _builder()))
    return project, dp


def setup_permitted_project_with_gate(budget_cents=100000, phase="EXCAVATION",
                                      contract_price_cents=500000):
    """Permitted project + one PENDING gate."""
    project, _ = create_permitted_project(contract_price_cents=contract_price_cents)
    gate = create_gate(project["id"], phase, budget_cents)
    return project, gate


def setup_permitted_project_two_gates_pending(contract_price_cents=500000):
    """Permitted project + EXCAVATION and STEEL gates, both PENDING."""
    project, _ = create_permitted_project(contract_price_cents=contract_price_cents)
    pg_excavation = create_gate(project["id"], "EXCAVATION", 100000)
    pg_steel = create_gate(project["id"], "STEEL", 100000)
    return project, pg_excavation, pg_steel


def setup_permitted_project_gate_and_sub(trade="EXCAVATOR", contract_price_cents=500000):
    """Permitted project + one PENDING gate + one ACTIVE subcontractor."""
    project, gate = setup_permitted_project_with_gate(contract_price_cents=contract_price_cents)
    sub = create_subcontractor("S", trade)
    return project, gate, sub


def setup_permitted_project_with_started_gate(budget_cents=100000, contract_price_cents=500000):
    """Permitted project + one gate IN_PROGRESS."""
    project, gate = setup_permitted_project_with_gate(budget_cents=budget_cents,
                                                      contract_price_cents=contract_price_cents)
    start_gate(gate["id"])
    return project, gate


def setup_gate_inspection_pending(budget_cents=100000, contract_price_cents=500000):
    """Permitted project + one gate driven to INSPECTION_PENDING (started, inspection scheduled).
    Returns (project, gate, inspection)."""
    project, gate = setup_permitted_project_with_started_gate(
        budget_cents=budget_cents, contract_price_cents=contract_price_cents)
    inspection = schedule_inspection(project["id"], gate["id"])
    return project, gate, inspection


def setup_gate_passed_via_inspection(budget_cents=100000, contract_price_cents=500000):
    """Permitted project + one gate PASSED, plus its terminal PASSED inspection."""
    project, gate = setup_permitted_project_with_started_gate(
        budget_cents=budget_cents, contract_price_cents=contract_price_cents)
    ins = schedule_inspection(project["id"], gate["id"])
    record_inspection(ins["id"], "PASS")
    return project, gate, ins


# ─── Difficulty-instance composites (queue A) ─────────────────────────────
def setup_provisional_final_divergence():
    """Draw created while gate IN_PROGRESS (provisional 50000), APPROVED; gate then PASSED.
    Returns (project, gate, draw) ready for the FUND trigger."""
    project, gate = setup_permitted_project_with_started_gate(budget_cents=100000,
                                                              contract_price_cents=500000)
    draw = create_draw(project["id"], gate["id"], 100000)   # provisional snapshot at IN_PROGRESS
    approve_draw(draw["id"])
    ins = schedule_inspection(project["id"], gate["id"])
    record_inspection(ins["id"], "PASS")                    # gate now PASSED
    return project, gate, draw


def setup_reliability_projected_vs_realized():
    """One sub with two COMPLETED assignments: gate A passed on attempt 1, gate B passed
    only after rework (attempt 2). Returns the subcontractor dict."""
    project, _ = create_permitted_project(contract_price_cents=500000)
    sub = create_subcontractor("S", "GENERAL")
    pg1 = create_gate(project["id"], "EXCAVATION", 100000)
    pg2 = create_gate(project["id"], "STEEL", 100000)

    start_gate(pg1["id"])
    a1 = book_crew(project["id"], sub["id"], pg1["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    complete_crew(a1["id"], sub["id"])
    ins1 = schedule_inspection(project["id"], pg1["id"], "2026-06-01T17:00:00Z")
    record_inspection(ins1["id"], "PASS")                   # pg1 PASSED, attempts 1

    start_gate(pg2["id"])
    a2 = book_crew(project["id"], sub["id"], pg2["id"], "2026-06-02T08:00:00Z", "2026-06-02T16:00:00Z")
    complete_crew(a2["id"], sub["id"])
    ins2 = schedule_inspection(project["id"], pg2["id"], "2026-06-02T17:00:00Z")
    record_inspection(ins2["id"], "FAIL")                   # pg2 FAILED, attempts 1, posture STOP_WORK
    start_gate(pg2["id"])                                   # rework (own-failure exempt) -> IN_PROGRESS
    ins3 = schedule_inspection(project["id"], pg2["id"], "2026-06-03T17:00:00Z")
    record_inspection(ins3["id"], "PASS")                   # pg2 PASSED, attempts 2

    return get_success_data(api_client.get_subcontractor(sub["id"], _builder()))


def setup_retainage_two_draws():
    """Two gates budget 12345 each, both PASSED; first draw FUNDED, second draw APPROVED
    and awaiting the FUND trigger. Returns (project, draw1, draw2)."""
    project, _ = create_permitted_project(contract_price_cents=500000)
    pg1 = create_gate(project["id"], "EXCAVATION", 12345)
    pg2 = create_gate(project["id"], "STEEL", 12345)

    start_and_pass_gate(project["id"], pg1["id"], "2026-06-01T10:00:00Z")
    dr1 = create_draw(project["id"], pg1["id"], 12345)
    approve_draw(dr1["id"])
    fund_draw(dr1["id"])

    start_and_pass_gate(project["id"], pg2["id"], "2026-06-02T10:00:00Z")
    dr2 = create_draw(project["id"], pg2["id"], 12345)
    approve_draw(dr2["id"])
    return project, dr1, dr2


def setup_change_order_tiered():
    """CO1 (+600000) APPLIED at tier 0%, CO2 (+400000) APPROVED and awaiting APPLY.
    Returns (project, co1, co2)."""
    project = create_project(contract_price_cents=1000000)
    co1 = create_change_order(project["id"], "SCOPE", "spa add", 600000)
    approve_change_order(co1["id"])
    apply_change_order(co1["id"])
    co2 = create_change_order(project["id"], "HEATER", "heater upgrade", 400000)
    approve_change_order(co2["id"])
    return project, co1, co2


def setup_change_order_applied(contract_price_cents=1000000, price_delta_cents=600000,
                               category="WATER_FEATURE"):
    """A single change order APPLIED. Returns (project, change_order) ready for REVERSE."""
    project = create_project(contract_price_cents=contract_price_cents)
    co = create_change_order(project["id"], category, "waterfall", price_delta_cents)
    approve_change_order(co["id"])
    co = apply_change_order(co["id"])
    return project, co


def setup_proposed_change_order(price_delta_cents=50000, category="PUMP"):
    """A project with one PROPOSED (never approved) change order."""
    project = create_project(contract_price_cents=1000000)
    co = create_change_order(project["id"], category, "vs pump", price_delta_cents)
    return project, co


def setup_passed_gate_draw_requested(contract_price_cents=50000, budget_cents=100000,
                                     requested_cents=100000):
    """Gate PASSED; a draw left in REQUESTED (never approved). Returns (project, gate, draw)."""
    project, gate = setup_permitted_project_with_gate(budget_cents=budget_cents,
                                                      contract_price_cents=contract_price_cents)
    start_and_pass_gate(project["id"], gate["id"])
    draw = create_draw(project["id"], gate["id"], requested_cents)
    return project, gate, draw


def setup_approved_draw_gate_in_progress(budget_cents=100000, contract_price_cents=500000,
                                         requested_cents=100000):
    """Gate IN_PROGRESS (not passed); a draw APPROVED and awaiting FUND. Returns (project, gate, draw)."""
    project, gate = setup_permitted_project_with_started_gate(
        budget_cents=budget_cents, contract_price_cents=contract_price_cents)
    draw = create_draw(project["id"], gate["id"], requested_cents)
    approve_draw(draw["id"])
    return project, gate, draw


def setup_approved_draw_at_boundary(contract_price_cents=90000, budget_cents=100000,
                                    requested_cents=100000):
    """Gate PASSED; a draw APPROVED and awaiting FUND. Contract price controls the money
    boundary (net 90000 vs remaining). Returns (project, gate, draw)."""
    project, gate = setup_permitted_project_with_gate(budget_cents=budget_cents,
                                                      contract_price_cents=contract_price_cents)
    start_and_pass_gate(project["id"], gate["id"])
    draw = create_draw(project["id"], gate["id"], requested_cents)
    approve_draw(draw["id"])
    return project, gate, draw


def setup_failed_gate_with_crew():
    """Gate started, sub S booked [08:00,16:00), inspection recorded FAIL so the gate is
    FAILED and posture is STOP_WORK. Returns (project, sub, gate, assignment)."""
    project, _ = create_permitted_project(contract_price_cents=500000)
    sub = create_subcontractor("S", "GENERAL")
    gate = create_gate(project["id"], "EXCAVATION", 100000)
    start_gate(gate["id"])
    a1 = book_crew(project["id"], sub["id"], gate["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    ins = schedule_inspection(project["id"], gate["id"], "2026-06-01T10:00:00Z")
    record_inspection(ins["id"], "FAIL")
    return project, sub, gate, a1


def setup_permitted_project_with_suspended_sub():
    """Permitted project + PENDING gate + a SUSPENDED sub. Returns (project, gate, sub)."""
    project, gate = setup_permitted_project_with_gate(contract_price_cents=500000)
    sub = create_subcontractor("S", "EXCAVATOR")
    suspend_subcontractor(sub["id"])
    return project, gate, sub


def setup_sub_booked_two_projects():
    """One sub booked on project A [08:00,16:00); project B ready for an overlapping booking
    on a DIFFERENT site. Returns (project_a, project_b, gate_a, gate_b, sub, assignment_a)."""
    project_a, _ = create_permitted_project(contract_price_cents=500000, owner_user_id="owner-1")
    gate_a = create_gate(project_a["id"], "EXCAVATION", 100000)
    project_b, _ = create_permitted_project(contract_price_cents=500000, owner_user_id="owner-2")
    gate_b = create_gate(project_b["id"], "EXCAVATION", 100000)
    sub = create_subcontractor("S", "EXCAVATOR")
    a1 = book_crew(project_a["id"], sub["id"], gate_a["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    return project_a, project_b, gate_a, gate_b, sub, a1


def setup_gunite_crew_booked():
    """A GUNITE crew booked [06-10 08:00,16:00) on the site, plus a PLASTER gate and a
    distinct plaster sub ready for a cure-buffer test. Returns
    (project, gunite_gate, plaster_gate, gunite_sub, plaster_sub, gunite_assignment)."""
    project, _ = create_permitted_project(contract_price_cents=500000)
    pg_gunite = create_gate(project["id"], "GUNITE", 100000)
    pg_plaster = create_gate(project["id"], "PLASTER", 100000)
    sub_gunite = create_subcontractor("GuniteCo", "GUNITE")
    sub_plaster = create_subcontractor("PlasterCo", "PLASTER")
    ag = book_crew(project["id"], sub_gunite["id"], pg_gunite["id"],
                   "2026-06-10T08:00:00Z", "2026-06-10T16:00:00Z")
    return project, pg_gunite, pg_plaster, sub_gunite, sub_plaster, ag


def setup_crew_booked_8h():
    """A single 8-hour crew booking. Returns (project, gate, sub, assignment)."""
    project, gate = setup_permitted_project_with_gate(contract_price_cents=500000)
    sub = create_subcontractor("S", "EXCAVATOR")
    a1 = book_crew(project["id"], sub["id"], gate["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    return project, gate, sub, a1


def setup_two_subs_one_booked():
    """Two subs S1 and S2; S1 booked [08:00,16:00) on the site's gate. Returns
    (project, gate, sub1, sub2, assignment1) for a site-occupancy test."""
    project, gate = setup_permitted_project_with_gate(contract_price_cents=500000)
    s1 = create_subcontractor("S1", "EXCAVATOR")
    s2 = create_subcontractor("S2", "GENERAL")
    a1 = book_crew(project["id"], s1["id"], gate["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    return project, gate, s1, s2, a1


def setup_started_gate_two_subs_one_booked():
    """Gate IN_PROGRESS, subs S1 and S2, crew booked for S1. Returns
    (project, gate, sub1, sub2, assignment1) for an ownership-denial test."""
    project, gate = setup_permitted_project_with_started_gate(contract_price_cents=500000)
    s1 = create_subcontractor("S1", "EXCAVATOR")
    s2 = create_subcontractor("S2", "GENERAL")
    a1 = book_crew(project["id"], s1["id"], gate["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    return project, gate, s1, s2, a1


def setup_crew_booked_on_pending_gate():
    """Crew booked against a PENDING gate (never started). Returns (project, gate, sub, assignment)."""
    project, gate = setup_permitted_project_with_gate(contract_price_cents=500000)
    sub = create_subcontractor("S", "EXCAVATOR")
    a1 = book_crew(project["id"], sub["id"], gate["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    return project, gate, sub, a1


def setup_permitted_project_with_major_punch():
    """Permitted project + PENDING gate + one OPEN MAJOR punch item (posture HOLD).
    Returns (project, gate, punch)."""
    project, gate = setup_permitted_project_with_gate(contract_price_cents=500000)
    punch = file_punch(project["id"], "deck crack", "MAJOR", _inspector())
    return project, gate, punch


def setup_plaster_pending_all_passed_with_funded_draw():
    """Five gates: EXCAVATION..GUNITE PASSED (with a FUNDED draw on EXCAVATION), PLASTER
    started and its inspection SCHEDULED (gate INSPECTION_PENDING). Returns
    (project, gates_by_phase, excavation_draw, plaster_inspection)."""
    project, _ = create_permitted_project(contract_price_cents=2000000)
    gates = {ph: create_gate(project["id"], ph, 100000) for ph in _PHASES}

    start_and_pass_gate(project["id"], gates["EXCAVATION"]["id"], "2026-06-01T10:00:00Z")
    dr = create_draw(project["id"], gates["EXCAVATION"]["id"], 100000)
    approve_draw(dr["id"])
    fund_draw(dr["id"])

    start_and_pass_gate(project["id"], gates["STEEL"]["id"], "2026-06-02T10:00:00Z")
    start_and_pass_gate(project["id"], gates["PLUMBING"]["id"], "2026-06-03T10:00:00Z")
    start_and_pass_gate(project["id"], gates["GUNITE"]["id"], "2026-06-04T10:00:00Z")

    start_gate(gates["PLASTER"]["id"])
    ins = schedule_inspection(project["id"], gates["PLASTER"]["id"], "2026-06-05T10:00:00Z")
    dr = get_success_data(api_client.get_draw_request(dr["id"], _builder()))
    return project, gates, dr, ins


def setup_oriented_project_with_open_punch(severity="MINOR"):
    """A project driven fully to ORIENTED with one OPEN punch item still on file.
    Returns (project, punch)."""
    project, _ = create_permitted_project(contract_price_cents=1000000)
    gates = [create_gate(project["id"], ph, 10000) for ph in _PHASES]
    for i, g in enumerate(gates):
        start_and_pass_gate(project["id"], g["id"], f"2026-06-0{i + 1}T10:00:00Z")
    get_success_data(api_client.transition_pool_project(project["id"], {"action": "ORIENT"}, _builder()))
    punch = file_punch(project["id"], "coping chip", severity, make_owner_headers(OWNER_USER_ID))
    return project, punch
