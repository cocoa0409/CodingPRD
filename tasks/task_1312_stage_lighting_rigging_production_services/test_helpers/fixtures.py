"""Composite setup helpers: multi-step arrangements used across the test suite.

Every helper builds its preconditions from scratch via PRD-declared endpoints and
returns parsed response data. Setup calls use the lenient get_success_data so a
broken precondition surfaces as a clear setup failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_venue_payload, create_technician_payload, create_production_payload,
    create_plot_payload, create_rigging_point_payload, create_asset_payload,
    create_pull_list_entry_payload, create_crew_call_payload, create_assignment_payload,
    create_power_plan_payload, create_truck_payload, create_load_schedule_payload,
    create_inspection_payload, create_damage_report_payload, assess_report_payload,
    DEFAULT_PREP_START, DEFAULT_PREP_END,
)
from .test_users import (
    TEST_USERS, make_crew_chief_headers, make_rigging_supervisor_headers,
    make_structural_engineer_headers, make_safety_inspector_headers,
)

PM = TEST_USERS["production_manager_headers"]
WH = TEST_USERS["warehouse_chief_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CLIENT = TEST_USERS["client_contact_headers"]

# Logical-clock instants used across the suite.
CLOCK_LOAD_IN = "2026-09-01T08:00:00Z"        # == default production load_in_at
CLOCK_AFTER_SHOW = "2026-09-02T20:00:00Z"     # > show_at, > default call_end


# ---------------------------------------------------------------- clock ---

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ------------------------------------------------- venues / productions ---

def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), PM))


def create_production(venue_id, **overrides) -> dict:
    return get_success_data(api_client.create_production(create_production_payload(venue_id, **overrides), PM))


def get_production(production_id) -> dict:
    return get_success_data(api_client.get_production(production_id, PM))


def transition_production(production_id, to) -> dict:
    return get_success_data(api_client.transition_production(production_id, {"to": to}, PM))


def setup_planning_production(venue_overrides=None, production_overrides=None) -> dict:
    """Venue + production advanced DRAFT -> PLANNING. Returns a context dict."""
    venue = create_venue(**(venue_overrides or {}))
    production = create_production(venue["id"], **(production_overrides or {}))
    production = transition_production(production["id"], "PLANNING")
    return {"venue": venue, "production": production}


# ----------------------------------------------------- plots and points ---

def create_plot(production, title="Main Rig") -> dict:
    """Create a plot; the OCC token is read off the supplied production dict."""
    payload = create_plot_payload(production["version"], title=title)
    return get_success_data(api_client.create_plot(production["id"], payload, PM))


def get_plot(plot_id) -> dict:
    return get_success_data(api_client.get_plot(plot_id, PM))


def add_rigging_point(plot_id, *, point_label="A1", bay_index=0, hang_type="DEAD_HANG",
                      motor_count=0, deadweight_kg=100, supervisor_id="rig-1") -> dict:
    """Reserve a point, reading the plot's current version for the OCC token."""
    plot = get_plot(plot_id)
    payload = create_rigging_point_payload(
        plot["version"], point_label=point_label, bay_index=bay_index,
        hang_type=hang_type, motor_count=motor_count, deadweight_kg=deadweight_kg,
    )
    return get_success_data(api_client.create_rigging_point(
        plot_id, payload, make_rigging_supervisor_headers(supervisor_id)))


def get_rigging_point(point_id) -> dict:
    return get_success_data(api_client.get_rigging_point(point_id, PM))


def submit_plot(plot_id) -> dict:
    return get_success_data(api_client.transition_plot(plot_id, {"to": "SUBMITTED"}, PM))


def approve_plot(plot_id, engineer_id="eng-1") -> dict:
    return get_success_data(api_client.transition_plot(
        plot_id, {"to": "APPROVED"}, make_structural_engineer_headers(engineer_id)))


def transition_point(point_id, payload, supervisor_id="rig-1") -> dict:
    return get_success_data(api_client.transition_rigging_point(
        point_id, payload, make_rigging_supervisor_headers(supervisor_id)))


def submit_point_for_review(point_id, supervisor_id="rig-1") -> dict:
    return transition_point(point_id, {"to": "UNDER_REVIEW"}, supervisor_id)


def approve_point(point_id, engineer_id="eng-1") -> dict:
    return get_success_data(api_client.transition_rigging_point(
        point_id, {"to": "APPROVED"}, make_structural_engineer_headers(engineer_id)))


def setup_approved_plot_with_point(ctx, **point_kw) -> dict:
    """Plot DRAFT -> SUBMITTED -> APPROVED and its single point -> APPROVED."""
    plot = create_plot(ctx["production"])
    point = add_rigging_point(plot["id"], **point_kw)
    plot = submit_plot(plot["id"])
    plot = approve_plot(plot["id"])
    point = submit_point_for_review(point["id"])
    point = approve_point(point["id"])
    ctx.update(plot=plot, point=point)
    return ctx


# ------------------------------------------------------------- power plans ---

def create_power_plan(production_id, **overrides) -> dict:
    return get_success_data(api_client.create_power_plan(
        production_id, create_power_plan_payload(**overrides), PM))


def get_power_plan(plan_id) -> dict:
    return get_success_data(api_client.get_power_plan(plan_id, PM))


def submit_power_plan(plan_id) -> dict:
    return get_success_data(api_client.transition_power_plan(plan_id, {"to": "SUBMITTED"}, PM))


def approve_power_plan(plan_id, inspector_id="si-1") -> dict:
    return get_success_data(api_client.transition_power_plan(
        plan_id, {"to": "APPROVED"}, make_safety_inspector_headers(inspector_id)))


def setup_approved_power_plan(ctx, **plan_kw) -> dict:
    plan = create_power_plan(ctx["production"]["id"], **plan_kw)
    plan = submit_power_plan(plan["id"])
    plan = approve_power_plan(plan["id"])
    ctx["power_plan"] = plan
    return ctx


# ------------------------------------------ assets / pull list / trucks ---

def create_asset(**overrides) -> dict:
    return get_success_data(api_client.create_asset(create_asset_payload(**overrides), WH))


def get_asset(asset_id) -> dict:
    return get_success_data(api_client.get_asset(asset_id, WH))


def transition_asset(asset_id, to) -> dict:
    return get_success_data(api_client.transition_asset(asset_id, {"to": to}, WH))


def create_pull_list_entry(production_id, asset_id) -> dict:
    return get_success_data(api_client.create_pull_list_entry(
        production_id, create_pull_list_entry_payload(asset_id), WH))


def get_pull_list_entry(entry_id) -> dict:
    return get_success_data(api_client.get_pull_list_entry(entry_id, WH))


def transition_entry(entry_id, payload) -> dict:
    return get_success_data(api_client.transition_pull_list_entry(entry_id, payload, WH))


def reserve_entry(entry_id) -> dict:
    return transition_entry(entry_id, {"to": "RESERVED"})


def prep_entry(entry_id, prep_window_start=DEFAULT_PREP_START, prep_window_end=DEFAULT_PREP_END) -> dict:
    return transition_entry(entry_id, {
        "to": "PREPPED",
        "prep_window_start": prep_window_start,
        "prep_window_end": prep_window_end,
    })


def checkout_entry(entry_id, load_schedule_id) -> dict:
    return transition_entry(entry_id, {"to": "OUT", "load_schedule_id": load_schedule_id})


def return_entry(entry_id) -> dict:
    return transition_entry(entry_id, {"to": "RETURNED"})


def cancel_entry(entry_id) -> dict:
    return transition_entry(entry_id, {"to": "CANCELLED"})


def create_truck(**overrides) -> dict:
    return get_success_data(api_client.create_truck(create_truck_payload(**overrides), WH))


def create_load_schedule(production_id, truck_id, **overrides) -> dict:
    return get_success_data(api_client.create_load_schedule(
        production_id, create_load_schedule_payload(truck_id, **overrides), PM))


def get_load_schedule(schedule_id) -> dict:
    return get_success_data(api_client.get_load_schedule(schedule_id, PM))


def transition_schedule(schedule_id, to) -> dict:
    return get_success_data(api_client.transition_load_schedule(schedule_id, {"to": to}, PM))


def setup_prepped_entry(ctx, asset_overrides=None) -> dict:
    """Add one asset with its pull entry driven REQUESTED -> PREPPED."""
    asset = create_asset(**(asset_overrides or {}))
    entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])
    entry = reserve_entry(entry["id"])
    entry = prep_entry(entry["id"])
    ctx.update(asset=asset, entry=entry)
    return ctx


def setup_confirmed_load_in_schedule(ctx, truck_overrides=None, **schedule_kw) -> dict:
    """Truck + LOAD_IN schedule PLANNED -> CONFIRMED (production still PLANNING)."""
    truck = create_truck(**(truck_overrides or {}))
    schedule = create_load_schedule(ctx["production"]["id"], truck["id"], **schedule_kw)
    schedule = transition_schedule(schedule["id"], "CONFIRMED")
    ctx.update(truck=truck, schedule=schedule)
    return ctx


# -------------------------------------------------------- crew and labor ---

def create_technician(**overrides) -> dict:
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), PM))


def create_crew_call(production_id, **overrides) -> dict:
    return get_success_data(api_client.create_crew_call(
        production_id, create_crew_call_payload(**overrides), PM))


def get_crew_call(call_id) -> dict:
    return get_success_data(api_client.get_crew_call(call_id, PM))


def transition_crew_call(call_id, to) -> dict:
    return get_success_data(api_client.transition_crew_call(call_id, {"to": to}, PM))


def create_assignment(call_id, technician_id) -> dict:
    return get_success_data(api_client.create_crew_assignment(
        call_id, create_assignment_payload(technician_id), PM))


def get_crew_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_crew_assignment(assignment_id, PM))


def confirm_assignment(assignment_id, technician_id) -> dict:
    """CrewChief self-confirm: X-User-ID is the technician's own id (PRD §2.1)."""
    return get_success_data(api_client.transition_crew_assignment(
        assignment_id, {"to": "CONFIRMED"}, make_crew_chief_headers(technician_id)))


def report_hours_worked(assignment_id, technician_id, worked_hours) -> dict:
    """CrewChief self-reports hours on their own assignment."""
    return get_success_data(api_client.transition_crew_assignment(
        assignment_id, {"to": "WORKED", "worked_hours": worked_hours},
        make_crew_chief_headers(technician_id)))


def confirm_crew_call(call_id) -> dict:
    return transition_crew_call(call_id, "CONFIRMED")


def setup_confirmed_crew_call(ctx, technician_overrides=None, **call_kw) -> dict:
    """Crew call DRAFT -> PUBLISHED with one assignment self-confirmed, call CONFIRMED."""
    technician = create_technician(**(technician_overrides or {}))
    call = create_crew_call(ctx["production"]["id"], **call_kw)
    call = transition_crew_call(call["id"], "PUBLISHED")
    assignment = create_assignment(call["id"], technician["id"])
    assignment = confirm_assignment(assignment["id"], technician["id"])
    call = confirm_crew_call(call["id"])
    ctx.update(technician=technician, crew_call=call, assignment=assignment)
    return ctx


# ------------------------------------------------------------ inspections ---

def create_inspection(production_id, inspection_type) -> dict:
    return get_success_data(api_client.create_inspection(
        production_id, create_inspection_payload(inspection_type), PM))


def transition_inspection(inspection_id, payload, headers) -> dict:
    return get_success_data(api_client.transition_inspection(inspection_id, payload, headers))


def begin_inspection(inspection_id, inspector_id="si-1") -> dict:
    return transition_inspection(inspection_id, {"to": "IN_PROGRESS"},
                                 make_safety_inspector_headers(inspector_id))


def pass_inspection(inspection_id, inspector_id="si-1") -> dict:
    return transition_inspection(inspection_id, {"to": "PASSED"},
                                 make_safety_inspector_headers(inspector_id))


def pass_inspection_type(production_id, inspection_type, inspector_id="si-1") -> dict:
    """Schedule -> begin -> pass one inspection of the given type."""
    inspection = create_inspection(production_id, inspection_type)
    inspection = begin_inspection(inspection["id"], inspector_id)
    return pass_inspection(inspection["id"], inspector_id)


def certify_show(ctx, inspector_id="si-1") -> dict:
    """Pass RIGGING + ELECTRICAL + FINAL; production fires LOAD_IN -> SHOW_READY."""
    pid = ctx["production"]["id"]
    ctx["rigging_inspection"] = pass_inspection_type(pid, "RIGGING", inspector_id)
    ctx["electrical_inspection"] = pass_inspection_type(pid, "ELECTRICAL", inspector_id)
    ctx["final_inspection"] = pass_inspection_type(pid, "FINAL", inspector_id)
    ctx["production"] = get_production(pid)
    return ctx


# -------------------------------------------------------- damage reports ---

def file_damage_report(production_id, pull_list_entry_id, report_type="DAMAGE") -> dict:
    return get_success_data(api_client.create_damage_report(
        production_id, create_damage_report_payload(pull_list_entry_id, report_type), WH))


def get_damage_report(report_id) -> dict:
    return get_success_data(api_client.get_damage_report(report_id, WH))


def assess_report(report_id, valuation_method="DEPRECIATED", repair_quote_cents=None) -> dict:
    payload = assess_report_payload(valuation_method)
    if repair_quote_cents is not None:
        payload["repair_quote_cents"] = repair_quote_cents
    return get_success_data(api_client.assess_damage_report(report_id, payload, WH))


def charge_report(report_id) -> dict:
    return get_success_data(api_client.transition_damage_report(report_id, {"to": "CHARGED"}, WH))


def waive_report(report_id) -> dict:
    return get_success_data(api_client.transition_damage_report(report_id, {"to": "WAIVED"}, PM))


# -------------------------------------------------------------- settlement ---

def create_settlement(production_id) -> dict:
    return get_success_data(api_client.create_settlement(production_id, PM))


def get_settlement(settlement_id) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, PM))


def transition_settlement(settlement_id, payload, headers=PM) -> dict:
    return get_success_data(api_client.transition_settlement(settlement_id, payload, headers))


# ------------------------------------------- full-lifecycle composites ---

def setup_full_planning_surface(*, venue_overrides=None, production_overrides=None,
                                asset_specs=None, with_entry=True, with_crew_call=True,
                                with_load_out_schedule=False, truck_overrides=None) -> dict:
    """Everything the readiness posture reads, built while the production is PLANNING:
    approved plot with one approved point, approved house power plan, one PREPPED
    pull entry per asset spec, a CONFIRMED LOAD_IN dock schedule, and a CONFIRMED
    crew call. Stops before the READY_FOR_LOADIN transition."""
    ctx = setup_planning_production(venue_overrides=venue_overrides,
                                    production_overrides=production_overrides)
    setup_approved_plot_with_point(ctx)
    setup_approved_power_plan(ctx)
    ctx["assets"] = []
    ctx["entries"] = []
    if with_entry:
        specs = asset_specs or [None]
        for spec in specs:
            asset = create_asset(**(spec or {}))
            entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])
            entry = reserve_entry(entry["id"])
            entry = prep_entry(entry["id"])
            ctx["assets"].append(asset)
            ctx["entries"].append(entry)
        ctx["asset"] = ctx["assets"][0]
        ctx["entry"] = ctx["entries"][0]
    setup_confirmed_load_in_schedule(ctx, truck_overrides=truck_overrides)
    if with_load_out_schedule:
        truck_out = create_truck(plate_no="T-OUT", capacity_kg=10000)
        schedule_out = create_load_schedule(
            ctx["production"]["id"], truck_out["id"],
            direction="LOAD_OUT", dock_door_index=1,
            window_start="2026-09-03T10:00:00Z", window_end="2026-09-03T14:00:00Z")
        schedule_out = transition_schedule(schedule_out["id"], "CONFIRMED")
        ctx.update(truck_out=truck_out, schedule_out=schedule_out)
    if with_crew_call:
        setup_confirmed_crew_call(ctx)
    return ctx


def setup_ready_production(**kwargs) -> dict:
    """Full planning surface + READY_FOR_LOADIN (posture READY)."""
    ctx = setup_full_planning_surface(**kwargs)
    ctx["production"] = transition_production(ctx["production"]["id"], "READY_FOR_LOADIN")
    return ctx


def setup_load_in_production(*, checkout=True, **kwargs) -> dict:
    """READY_FOR_LOADIN, clock advanced to load_in_at, production LOAD_IN,
    LOAD_IN schedule AUTHORIZED, and every PREPPED entry checked OUT onto it."""
    ctx = setup_ready_production(**kwargs)
    set_clock(ctx["production"]["load_in_at"])
    ctx["production"] = transition_production(ctx["production"]["id"], "LOAD_IN")
    ctx["schedule"] = transition_schedule(ctx["schedule"]["id"], "AUTHORIZED")
    if checkout:
        ctx["entries"] = [checkout_entry(e["id"], ctx["schedule"]["id"]) for e in ctx["entries"]]
        if ctx["entries"]:
            ctx["entry"] = ctx["entries"][0]
    return ctx


def setup_closed_production_with_assessed_damage(*, report_type="DAMAGE",
                                                 valuation_method="DEPRECIATED",
                                                 repair_quote_cents=None,
                                                 worked_hours=8.00) -> dict:
    """Full end-to-end chain: LOAD_IN with the entry OUT, a damage report ASSESSED
    (entry billed at the assessment clock, same-day = 1 day), all inspections
    PASSED, show completed, crew call COMPLETED (8.00h), LOAD_OUT, schedule
    COMPLETE, production CLOSED. The damage report is left ASSESSED."""
    ctx = setup_load_in_production()
    report = file_damage_report(ctx["production"]["id"], ctx["entry"]["id"], report_type)
    report = assess_report(report["id"], valuation_method,
                           repair_quote_cents=repair_quote_cents)
    ctx["report"] = report
    ctx["entry"] = get_pull_list_entry(ctx["entry"]["id"])
    certify_show(ctx)
    set_clock(CLOCK_AFTER_SHOW)
    ctx["production"] = transition_production(ctx["production"]["id"], "SHOW_COMPLETE")
    ctx["assignment"] = report_hours_worked(ctx["assignment"]["id"],
                                            ctx["technician"]["id"], worked_hours)
    ctx["crew_call"] = transition_crew_call(ctx["crew_call"]["id"], "COMPLETED")
    ctx["production"] = transition_production(ctx["production"]["id"], "LOAD_OUT")
    ctx["schedule"] = transition_schedule(ctx["schedule"]["id"], "COMPLETE")
    ctx["production"] = transition_production(ctx["production"]["id"], "CLOSED")
    return ctx
