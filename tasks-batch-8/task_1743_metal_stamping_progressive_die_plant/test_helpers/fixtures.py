"""Composite setup helpers for the stamping-plant API (PRD §3 workflows).

Every test starts against an empty database, so these helpers build the full
precondition chain — customer, part, die, pairing, approved strip layout,
approved PPAP, press, completed changeover, approved coil, released order —
using only PRD-declared endpoints. All helpers use get_success_data() so a
setup failure surfaces as a clear "Setup failed" error.

Segregation-of-duties threading (PRD §3.5, §3.9): PPAP submissions are created
by the ProcessEngineer identity and dispositioned by a *different*
QualityEngineer identity; layered audits are scheduled by one QualityEngineer
identity and recorded by another.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_process_engineer_headers,
    make_qe_dispositioner_headers,
    make_qe_reviewer_headers,
)

ADMIN = TEST_USERS["plant_admin_headers"]
ENGINEER = TEST_USERS["process_engineer_headers"]
TOOLROOM = TEST_USERS["toolroom_manager_headers"]
SETUP = TEST_USERS["setup_lead_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["press_operator_headers"]
QE = TEST_USERS["quality_engineer_headers"]
CLERK = TEST_USERS["shipping_clerk_headers"]
ANALYST = TEST_USERS["cost_analyst_headers"]


# ---------------------------------------------------------------------------
# Clock and atomic creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = C.DEFAULT_CLOCK_ISO):
    """Advance the server's logical UTC clock (PRD §2.4)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    get_success_data(resp)


def create_customer(**overrides) -> dict:
    resp = api_client.create_customer(factories.create_customer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_part(customer_id: str, **overrides) -> dict:
    resp = api_client.create_part(
        factories.create_part_payload(customer_id, **overrides), ENGINEER
    )
    return get_success_data(resp)


def create_die(**overrides) -> dict:
    resp = api_client.create_die(factories.create_die_payload(**overrides), TOOLROOM)
    return get_success_data(resp)


def create_press(**overrides) -> dict:
    resp = api_client.create_press(factories.create_press_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_assignment(part_id: str, die_id: str) -> dict:
    resp = api_client.create_part_die_assignment(
        factories.create_part_die_assignment_payload(part_id, die_id), ENGINEER
    )
    return get_success_data(resp)


def create_coil(**overrides) -> dict:
    resp = api_client.create_steel_coil(
        factories.create_steel_coil_payload(**overrides), CLERK
    )
    return get_success_data(resp)


def approve_coil(coil_id: str) -> dict:
    resp = api_client.approve_steel_coil(coil_id, make_qe_reviewer_headers())
    return get_success_data(resp)


def create_approved_coil(**overrides) -> dict:
    coil = create_coil(**overrides)
    return approve_coil(coil["id"])


def get_coil(coil_id: str) -> dict:
    return get_success_data(api_client.get_steel_coil(coil_id, OPERATOR))


def get_die(die_id: str) -> dict:
    return get_success_data(api_client.get_die(die_id, TOOLROOM))


def get_press(press_id: str) -> dict:
    return get_success_data(api_client.get_press(press_id, ADMIN))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_production_order(order_id, PLANNER))


def get_run(run_id: str) -> dict:
    return get_success_data(api_client.get_production_run(run_id, OPERATOR))


def get_part_fresh(part_id: str) -> dict:
    return get_success_data(api_client.get_part(part_id, ENGINEER))


# ---------------------------------------------------------------------------
# Strip layout approval (OCC: expected_part_version, PRD §2.8 / §3.2)
# ---------------------------------------------------------------------------

def create_layout(part_id: str, **overrides) -> dict:
    resp = api_client.create_strip_layout(
        factories.create_strip_layout_payload(part_id, **overrides), ENGINEER
    )
    return get_success_data(resp)


def create_and_approve_layout(
    part_id: str, gross_weight_per_part_kg: float = C.DEFAULT_GROSS_WEIGHT_PER_PART_KG,
    **overrides,
) -> dict:
    """Create a layout and approve it against the part's current version."""
    layout = create_layout(part_id, gross_weight_per_part_kg=gross_weight_per_part_kg, **overrides)
    part = get_part_fresh(part_id)
    resp = api_client.approve_strip_layout(
        layout["id"], {"expected_part_version": part["version"]}, ENGINEER
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# PPAP lifecycle (PRD §3.5) — creator and approver are distinct users
# ---------------------------------------------------------------------------

def create_ppap_submission(part_id: str, level: int = 1, control_plan_attached: bool = False) -> dict:
    resp = api_client.create_ppap_submission(
        factories.create_ppap_submission_payload(
            part_id, level=level, control_plan_attached=control_plan_attached
        ),
        make_process_engineer_headers(C.PE_CREATOR_USER_ID),
    )
    return get_success_data(resp)


def begin_ppap_review(submission_id: str) -> dict:
    resp = api_client.begin_ppap_review(submission_id, make_qe_reviewer_headers())
    return get_success_data(resp)


def approve_ppap(submission_id: str) -> dict:
    resp = api_client.approve_ppap_submission(submission_id, make_qe_dispositioner_headers())
    return get_success_data(resp)


def reject_ppap(submission_id: str, reason: str = "Control plan gaps") -> dict:
    resp = api_client.reject_ppap_submission(
        submission_id, {"rejection_reason": reason}, make_qe_dispositioner_headers()
    )
    return get_success_data(resp)


def create_and_approve_ppap(part_id: str, level: int = 1) -> dict:
    sub = create_ppap_submission(part_id, level=level, control_plan_attached=(level >= 2))
    begin_ppap_review(sub["id"])
    return approve_ppap(sub["id"])


# ---------------------------------------------------------------------------
# Tier-1 composite: part fully cleared for release
# ---------------------------------------------------------------------------

def setup_part_ready(
    part_overrides: dict | None = None,
    die_overrides: dict | None = None,
    customer_overrides: dict | None = None,
    gross_weight_per_part_kg: float = C.DEFAULT_GROSS_WEIGHT_PER_PART_KG,
    ppap_level: int = 1,
    approve_ppap_flag: bool = True,
    approve_layout_flag: bool = True,
) -> dict:
    """Customer + part + die + part–die assignment (+ approved layout, + approved PPAP).

    Returns a context dict with keys: customer, part, die, assignment, layout, ppap.
    """
    customer = create_customer(**(customer_overrides or {}))
    part = create_part(customer["id"], **(part_overrides or {}))
    die = create_die(**(die_overrides or {}))
    assignment = create_assignment(part["id"], die["id"])
    layout = None
    if approve_layout_flag:
        layout = create_and_approve_layout(part["id"], gross_weight_per_part_kg)
    ppap = None
    if approve_ppap_flag:
        level = (part_overrides or {}).get("ppap_required_level", ppap_level)
        ppap = create_and_approve_ppap(part["id"], level=level)
    return {
        "customer": customer,
        "part": part,
        "die": die,
        "assignment": assignment,
        "layout": layout,
        "ppap": ppap,
    }


# ---------------------------------------------------------------------------
# Orders (PRD §3.5) — release carries expected_order_version
# ---------------------------------------------------------------------------

def create_order(part_id: str, **overrides) -> dict:
    resp = api_client.create_production_order(
        factories.create_production_order_payload(part_id, **overrides), PLANNER
    )
    return get_success_data(resp)


def release_order(order_id: str) -> dict:
    order = get_order(order_id)
    resp = api_client.release_production_order(
        order_id, {"expected_order_version": order["version"]}, PLANNER
    )
    return get_success_data(resp)


def create_and_release_order(part_id: str, **overrides) -> dict:
    order = create_order(part_id, **overrides)
    return release_order(order["id"])


# ---------------------------------------------------------------------------
# Changeovers (PRD §3.6): plan -> start -> complete installs the die
# ---------------------------------------------------------------------------

def install_die_on_press(
    press_id: str,
    die_id: str,
    planned_start: str = C.CHANGEOVER_START,
    planned_end: str = C.CHANGEOVER_END,
    smed_target_minutes: int = 40,
    from_die_id: str | None = None,
) -> dict:
    """Plan, start, and complete a changeover; afterwards the press is IDLE and
    the incoming die is ASSIGNED (PRD §3.6)."""
    payload = factories.create_die_change_event_payload(
        press_id,
        die_id,
        planned_start=planned_start,
        planned_end=planned_end,
        smed_target_minutes=smed_target_minutes,
    )
    if from_die_id is not None:
        payload["from_die_id"] = from_die_id
    event = get_success_data(api_client.create_die_change_event(payload, SETUP))
    get_success_data(api_client.start_die_change_event(event["id"], SETUP))
    return get_success_data(api_client.complete_die_change_event(event["id"], SETUP))


# ---------------------------------------------------------------------------
# Tier-2 composite: everything needed to schedule and start a run
# ---------------------------------------------------------------------------

def setup_runnable(
    quantity_ordered: int = 100,
    coil_weight_kg: float = 1000,
    heat_lot_number: str | None = None,
    part_overrides: dict | None = None,
    die_overrides: dict | None = None,
    customer_overrides: dict | None = None,
    order_overrides: dict | None = None,
    gross_weight_per_part_kg: float = C.DEFAULT_GROSS_WEIGHT_PER_PART_KG,
    changeover_start: str = C.CHANGEOVER_START,
    changeover_end: str = C.CHANGEOVER_END,
    smed_target_minutes: int = 40,
    coil_overrides: dict | None = None,
    set_clock_first: bool = True,
) -> dict:
    """Part-ready chain + released order + press with the die installed +
    approved coil. Ready for production-run scheduling.

    The default quantities keep the coil-sufficiency estimate satisfied under
    every reading of PRD §3.7 (quantity_ordered * steel_content_kg <= coil).
    """
    if set_clock_first:
        set_clock()
    ctx = setup_part_ready(
        part_overrides=part_overrides,
        die_overrides=die_overrides,
        customer_overrides=customer_overrides,
        gross_weight_per_part_kg=gross_weight_per_part_kg,
    )
    ctx["order"] = create_and_release_order(
        ctx["part"]["id"], quantity_ordered=quantity_ordered, **(order_overrides or {})
    )
    ctx["press"] = create_press()
    ctx["changeover"] = install_die_on_press(
        ctx["press"]["id"], ctx["die"]["id"],
        planned_start=changeover_start, planned_end=changeover_end,
        smed_target_minutes=smed_target_minutes,
    )
    coil_kwargs = {"received_weight_kg": coil_weight_kg}
    if heat_lot_number is not None:
        coil_kwargs["heat_lot_number"] = heat_lot_number
    coil_kwargs.update(coil_overrides or {})
    ctx["coil"] = create_approved_coil(**coil_kwargs)
    return ctx


# ---------------------------------------------------------------------------
# Runs (PRD §3.7)
# ---------------------------------------------------------------------------

def schedule_run(
    ctx: dict,
    scheduled_start: str = C.RUN_WINDOW_START,
    scheduled_end: str = C.RUN_WINDOW_END,
    coil_id: str | None = None,
    die_id: str | None = None,
    press_id: str | None = None,
    order_id: str | None = None,
) -> dict:
    payload = factories.create_production_run_payload(
        order_id or ctx["order"]["id"],
        press_id or ctx["press"]["id"],
        die_id or ctx["die"]["id"],
        coil_id or ctx["coil"]["id"],
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    resp = api_client.create_production_run(payload, PLANNER)
    return get_success_data(resp)


def start_run(run_id: str) -> dict:
    return get_success_data(api_client.start_production_run(run_id, OPERATOR))


def complete_run(run_id: str, shots_recorded: int, coil_id: str) -> dict:
    """Complete a run, threading the coil's current version (PRD §2.8)."""
    coil = get_coil(coil_id)
    resp = api_client.complete_production_run(
        run_id,
        {"shots_recorded": shots_recorded, "expected_coil_version": coil["version"]},
        OPERATOR,
    )
    return get_success_data(resp)


def add_reject_event(run_id: str, quantity: int, station_number: int = 1,
                     sensor_code: str = "MISFEED",
                     sensed_at: str = "2026-08-01T08:30:00Z") -> dict:
    resp = api_client.create_reject_event(
        run_id,
        factories.create_reject_event_payload(
            station_number=station_number, sensor_code=sensor_code,
            quantity=quantity, sensed_at=sensed_at,
        ),
        OPERATOR,
    )
    return get_success_data(resp)


def setup_running_run(
    run_start: str = C.RUN_WINDOW_START,
    run_end: str = C.RUN_WINDOW_END,
    **runnable_kwargs,
) -> dict:
    """Full chain through a RUNNING production run. Context gains key: run."""
    ctx = setup_runnable(**runnable_kwargs)
    ctx["run"] = schedule_run(ctx, run_start, run_end)
    ctx["run"] = start_run(ctx["run"]["id"])
    return ctx


def setup_completed_run(
    shots_recorded: int = 100,
    run_start: str = C.RUN_WINDOW_START,
    run_end: str = C.RUN_WINDOW_END,
    **runnable_kwargs,
) -> dict:
    """Full chain through a COMPLETED run. Context gains keys: run, coil_after."""
    ctx = setup_running_run(run_start=run_start, run_end=run_end, **runnable_kwargs)
    ctx["run"] = complete_run(ctx["run"]["id"], shots_recorded, ctx["coil"]["id"])
    ctx["coil_after"] = get_coil(ctx["coil"]["id"])
    return ctx


def setup_completed_order(shots_recorded: int = 100, quantity_ordered: int = 100,
                          **runnable_kwargs) -> dict:
    """Full chain through a COMPLETED production order (one run covering the
    ordered quantity). Ready for close-out (PRD §3.10)."""
    ctx = setup_completed_run(
        shots_recorded=shots_recorded, quantity_ordered=quantity_ordered, **runnable_kwargs
    )
    get_success_data(api_client.complete_production_order(ctx["order"]["id"], PLANNER))
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Index publications (PRD §3.1)
# ---------------------------------------------------------------------------

def publish_index(value_usd_per_ton: float, index_code: str = "CRU_HRC",
                  published_at: str = C.DEFAULT_CLOCK_ISO) -> dict:
    resp = api_client.create_index_publication(
        factories.create_index_publication_payload(
            index_code=index_code, published_at=published_at,
            value_usd_per_ton=value_usd_per_ton,
        ),
        ADMIN,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Layered audits (PRD §3.9) — scheduler and recorder are distinct users
# ---------------------------------------------------------------------------

def create_audit(press_id: str, audit_tier: int = 1,
                 scheduled_date: str = "2026-08-10T00:00:00Z") -> dict:
    resp = api_client.create_layered_audit(
        factories.create_layered_audit_payload(
            press_id, audit_tier=audit_tier, scheduled_date=scheduled_date
        ),
        make_qe_reviewer_headers(),
    )
    return get_success_data(resp)


def record_audit(audit_id: str, result: str, findings_count: int) -> dict:
    resp = api_client.record_layered_audit(
        audit_id, {"result": result, "findings_count": findings_count},
        make_qe_dispositioner_headers(),
    )
    return get_success_data(resp)


def record_tier3_fail(press_id: str, findings_count: int = 2,
                      scheduled_date: str = "2026-08-01T09:00:00Z") -> dict:
    """Schedule and FAIL a tier-3 audit on a press, detonating the heat-lot
    quarantine cascade (PRD §3.9)."""
    audit = create_audit(press_id, audit_tier=3, scheduled_date=scheduled_date)
    return record_audit(audit["id"], "FAIL", findings_count)
