"""Composite setup helpers.

These encapsulate the multi-step API sequences that put the system into the
specific states the tests assert against. Every helper builds its preconditions
from scratch (the server DB is empty before each test) using only PRD-declared
endpoints, threads entity_backed identities through ownership-gated calls, and
uses get_success_data() so a setup failure surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload, create_staff_payload, create_project_payload,
    create_measurement_payload, create_estimate_payload, create_line_item_payload,
    create_permit_payload, create_material_order_payload, create_crew_payload,
    create_work_schedule_payload, create_progress_draw_payload,
)
from .test_users import (
    make_estimator_headers, make_project_manager_headers,
    make_finance_officer_headers, make_homeowner_client_headers,
)
from .constants import COMMON_DELIVERY_ETA_ISO


# ---------------------------------------------------------------------------
# Tier 0: actor bootstrap
# ---------------------------------------------------------------------------
def bootstrap_actors(with_finance=False, **client_overrides):
    """Register an Estimator, ProjectManager, HomeownerClient (and optionally a
    FinanceOfficer). Returns a dict with ids and ready-to-use role headers.

    Keys: est_id, pm_id, client_id, (fin_id), est_h, pm_h, client_h, (fin_h).
    """
    est = get_success_data(api_client.register_staff(create_staff_payload(role_code="ESTIMATOR")))
    pm = get_success_data(api_client.register_staff(create_staff_payload(role_code="PROJECT_MANAGER")))
    client = get_success_data(api_client.register_client(create_client_payload(**client_overrides)))
    actors = {
        "est_id": est["id"],
        "pm_id": pm["id"],
        "client_id": client["id"],
        "est_h": make_estimator_headers(est["id"]),
        "pm_h": make_project_manager_headers(pm["id"]),
        "client_h": make_homeowner_client_headers(client["id"]),
    }
    if with_finance:
        fin = get_success_data(api_client.register_staff(create_staff_payload(role_code="FINANCE_OFFICER")))
        actors["fin_id"] = fin["id"]
        actors["fin_h"] = make_finance_officer_headers(fin["id"])
    return actors


# ---------------------------------------------------------------------------
# Tier 1: state progression on the Project workflow axis
# ---------------------------------------------------------------------------
def create_draft_project(actors=None, **project_overrides):
    """Create a DRAFT project. Returns (project, actors)."""
    if actors is None:
        actors = bootstrap_actors()
    proj = get_success_data(api_client.create_project(
        create_project_payload(actors["client_id"], actors["pm_id"], **project_overrides),
        actors["pm_h"],
    ))
    return proj, actors


def create_measured_project(actors=None, measurement_overrides=None, **project_overrides):
    """Create a project advanced to workflow_status=MEASURED.
    Returns (project, measurement, actors)."""
    proj, actors = create_draft_project(actors, **project_overrides)
    meas_payload = create_measurement_payload(actors["est_id"], **(measurement_overrides or {}))
    meas = get_success_data(api_client.create_measurement(proj["id"], meas_payload, actors["est_h"]))
    return proj, meas, actors


def create_draft_estimate(actors=None, waste_factor_pct=0.10, measurement_overrides=None, **project_overrides):
    """Create a MEASURED project with a DRAFT estimate (no line items yet).
    Returns (project, measurement, estimate, actors)."""
    proj, meas, actors = create_measured_project(
        actors, measurement_overrides=measurement_overrides, **project_overrides)
    est = get_success_data(api_client.create_estimate(
        create_estimate_payload(proj["id"], meas["id"], waste_factor_pct=waste_factor_pct),
        actors["est_h"],
    ))
    return proj, meas, est, actors


def add_line_item(estimate_id, actors, scope_kind="SIDING", quantity=1000, unit_price_cents=1000):
    """Add a scope line item to an estimate. Returns the line item."""
    return get_success_data(api_client.create_line_item(
        estimate_id,
        create_line_item_payload(scope_kind=scope_kind, quantity=quantity, unit_price_cents=unit_price_cents),
        actors["est_h"],
    ))


def create_baselined_project(actors=None, line_items=None, waste_factor_pct=0.10,
                             measurement_overrides=None, **project_overrides):
    """Create a project promoted to BASELINE (workflow_status=ESTIMATED).

    line_items: list of dicts {scope_kind, quantity, unit_price_cents}; defaults
    to a single SIDING line (qty 1000, unit 1000c -> contract 1190750).
    Returns (project, estimate, line_item_map, actors) where line_item_map maps
    each line's scope_kind (first occurrence) to its created row, plus a list
    'lines' of all created line rows.
    """
    proj, meas, est, actors = create_draft_estimate(
        actors, waste_factor_pct=waste_factor_pct,
        measurement_overrides=measurement_overrides, **project_overrides)
    if line_items is None:
        line_items = [{"scope_kind": "SIDING", "quantity": 1000, "unit_price_cents": 1000}]
    created = []
    line_map = {}
    for li in line_items:
        row = add_line_item(est["id"], actors, **li)
        created.append(row)
        line_map.setdefault(li["scope_kind"], row)
    get_success_data(api_client.baseline_estimate(est["id"], actors["pm_h"]))
    line_map["lines"] = created
    return proj, est, line_map, actors


def THREE_LINE_ESTIMATE():
    """The canonical 3-line estimate used across difficulty instances:
    SIDING 1800@500c (extended 990000 with 0.10 waste), TRIM 300@300c (90000),
    WRAP 1800@80c (144000); subtotal 1224000, tax 100980, total 1324980."""
    return [
        {"scope_kind": "SIDING", "quantity": 1800, "unit_price_cents": 500},
        {"scope_kind": "TRIM", "quantity": 300, "unit_price_cents": 300},
        {"scope_kind": "WRAP", "quantity": 1800, "unit_price_cents": 80},
    ]


# ---------------------------------------------------------------------------
# Tier 1b: compliance axis clearance
# ---------------------------------------------------------------------------
def clear_compliance(project_id, actors, permit_number="P-0001"):
    """File and issue a permit so compliance_status becomes CLEARED (no HOA).
    Returns the issued permit."""
    permit = get_success_data(api_client.create_permit(
        create_permit_payload(project_id), actors["pm_h"]))
    issued = get_success_data(api_client.issue_permit(
        permit["id"], {"permit_number": permit_number}, actors["pm_h"]))
    return issued


# ---------------------------------------------------------------------------
# Tier 2: ORDERED project with a DELIVERED material order, compliance CLEARED
# ---------------------------------------------------------------------------
def setup_ordered_cleared_delivered(actors=None, line_items=None, waste_factor_pct=0.10,
                                   measurement_overrides=None, set_clock=True,
                                   delivery_eta_iso=COMMON_DELIVERY_ETA_ISO,
                                   permit_number="P-0001", **project_overrides):
    """Project at workflow_status=ORDERED, compliance_status=CLEARED, with the
    MaterialOrder DELIVERED. The standard precondition for confirming a work
    window. Returns dict: project, estimate, line_map, material_order, actors.
    """
    proj, est, line_map, actors = create_baselined_project(
        actors=actors, line_items=line_items, waste_factor_pct=waste_factor_pct,
        measurement_overrides=measurement_overrides, **project_overrides)
    clear_compliance(proj["id"], actors, permit_number=permit_number)
    mo = get_success_data(api_client.create_material_order(
        create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
    get_success_data(api_client.confirm_material_order(
        mo["id"], {"delivery_eta_iso": delivery_eta_iso}, actors["pm_h"]))
    if set_clock:
        get_success_data(api_client.set_clock(delivery_eta_iso, actors["pm_h"]))
    get_success_data(api_client.deliver_material_order(mo["id"], actors["pm_h"]))
    return {"project": proj, "estimate": est, "line_map": line_map,
            "material_order": mo, "actors": actors}


def create_crew(actors, name="Test Crew", max_wind_mph=30):
    payload = create_crew_payload(name=name)
    if max_wind_mph is not None:
        payload["max_wind_mph"] = max_wind_mph
    return get_success_data(api_client.create_crew(payload, actors["pm_h"]))


def propose_window(project_id, crew_id, actors, milestone="WRAP_INSTALL",
                  window_start_iso="2026-04-20T08:00:00Z",
                  window_end_iso="2026-04-20T17:00:00Z", forecast_wind_mph=10):
    return get_success_data(api_client.create_work_schedule(
        project_id,
        create_work_schedule_payload(
            crew_id, milestone=milestone, window_start_iso=window_start_iso,
            window_end_iso=window_end_iso, forecast_wind_mph=forecast_wind_mph),
        actors["pm_h"],
    ))


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts to SCHEDULED / IN_PROGRESS / completed windows
# ---------------------------------------------------------------------------
def setup_scheduled_window(actors=None, line_items=None, waste_factor_pct=0.10,
                          measurement_overrides=None, max_wind_mph=30,
                          window_start_iso="2026-04-20T08:00:00Z",
                          window_end_iso="2026-04-20T17:00:00Z",
                          forecast_wind_mph=10, **project_overrides):
    """Project ORDERED/CLEARED/DELIVERED with a crew and one CONFIRMED window
    (project advances to SCHEDULED). Returns dict adding crew, work_schedule."""
    base = setup_ordered_cleared_delivered(
        actors=actors, line_items=line_items, waste_factor_pct=waste_factor_pct,
        measurement_overrides=measurement_overrides, **project_overrides)
    crew = create_crew(base["actors"], name="Crew Sched", max_wind_mph=max_wind_mph)
    ws = propose_window(base["project"]["id"], crew["id"], base["actors"],
                        window_start_iso=window_start_iso, window_end_iso=window_end_iso,
                        forecast_wind_mph=forecast_wind_mph)
    get_success_data(api_client.confirm_work_schedule(ws["id"], base["actors"]["pm_h"]))
    base["crew"] = crew
    base["work_schedule"] = ws
    return base


def setup_completed_window(actors=None, line_items=None, waste_factor_pct=0.10,
                          measurement_overrides=None,
                          window_start_iso="2026-04-20T08:00:00Z",
                          window_end_iso="2026-04-20T17:00:00Z",
                          **project_overrides):
    """Project IN_PROGRESS with one COMPLETED milestone window. The standard
    precondition for requesting and approving a progress draw. Returns dict with
    project, estimate, line_map, material_order, crew, work_schedule, actors."""
    base = setup_scheduled_window(
        actors=actors, line_items=line_items, waste_factor_pct=waste_factor_pct,
        measurement_overrides=measurement_overrides,
        window_start_iso=window_start_iso, window_end_iso=window_end_iso,
        **project_overrides)
    ws = base["work_schedule"]
    a = base["actors"]
    get_success_data(api_client.start_work_schedule(ws["id"], a["pm_h"]))
    get_success_data(api_client.complete_work_schedule(ws["id"], a["pm_h"]))
    return base


def add_completed_window(project_id, crew_id, actors, milestone="SIDING_INSTALL",
                        window_start_iso="2026-04-23T08:00:00Z",
                        window_end_iso="2026-04-23T17:00:00Z", forecast_wind_mph=10,
                        complete=True):
    """Add a second (or further) window to an already-IN_PROGRESS project, confirm
    it, and (optionally) complete it. Returns the work schedule row."""
    ws = propose_window(project_id, crew_id, actors, milestone=milestone,
                        window_start_iso=window_start_iso, window_end_iso=window_end_iso,
                        forecast_wind_mph=forecast_wind_mph)
    get_success_data(api_client.confirm_work_schedule(ws["id"], actors["pm_h"]))
    if complete:
        get_success_data(api_client.complete_work_schedule(ws["id"], actors["pm_h"]))
    return ws


# ---------------------------------------------------------------------------
# Tier 4: progress draws — approved / released
# ---------------------------------------------------------------------------
def request_and_approve_draw(project_id, work_schedule_id, actors, milestone_pct=0.30):
    """Request a draw against a completed window and approve it (PM). Returns the
    approved draw row (with computed gross/retainage/net)."""
    draw = get_success_data(api_client.create_progress_draw(
        project_id, create_progress_draw_payload(work_schedule_id, milestone_pct=milestone_pct),
        actors["pm_h"]))
    approved = get_success_data(api_client.approve_progress_draw(draw["id"], actors["pm_h"]))
    return approved


def current_project_version(project_id, actors, headers=None):
    """Read the project's live version (used for OCC-guarded writes)."""
    h = headers or actors["pm_h"]
    proj = get_success_data(api_client.get_project(project_id, h))
    return proj["version"]


def release_draw(project_id, draw_id, actors, finance_headers=None):
    """Release an APPROVED draw as the FinanceOfficer, using the current project
    version. Returns the released draw row."""
    fin_h = finance_headers or actors["fin_h"]
    v = current_project_version(project_id, actors, headers=fin_h)
    return get_success_data(api_client.release_progress_draw(
        draw_id, {"expected_project_version": v}, fin_h))


def setup_approved_draw(actors=None, line_items=None, waste_factor_pct=0.10,
                       measurement_overrides=None, milestone_pct=0.30,
                       **project_overrides):
    """Full setup: project IN_PROGRESS, one COMPLETED window, one APPROVED draw.
    Requires a FinanceOfficer in actors (bootstrapped if actors is None).
    Returns dict with project, estimate, line_map, crew, work_schedule, draw,
    actors."""
    if actors is None:
        actors = bootstrap_actors(with_finance=True)
    base = setup_completed_window(
        actors=actors, line_items=line_items, waste_factor_pct=waste_factor_pct,
        measurement_overrides=measurement_overrides, **project_overrides)
    draw = request_and_approve_draw(base["project"]["id"], base["work_schedule"]["id"],
                                    base["actors"], milestone_pct=milestone_pct)
    base["draw"] = draw
    return base


def setup_released_draw(actors=None, line_items=None, waste_factor_pct=0.10,
                       measurement_overrides=None, milestone_pct=0.30,
                       **project_overrides):
    """Full setup: project IN_PROGRESS with one COMPLETED window and one RELEASED
    draw (PM approves, FinanceOfficer releases). Returns the same dict as
    setup_approved_draw with the draw in RELEASED state."""
    base = setup_approved_draw(
        actors=actors, line_items=line_items, waste_factor_pct=waste_factor_pct,
        measurement_overrides=measurement_overrides, milestone_pct=milestone_pct,
        **project_overrides)
    release_draw(base["project"]["id"], base["draw"]["id"], base["actors"])
    base["draw"] = get_success_data(
        api_client.get_progress_draw(base["draw"]["id"], base["actors"]["pm_h"]))
    return base


# ---------------------------------------------------------------------------
# Tier 5: change-order helpers
# ---------------------------------------------------------------------------
def create_dual_signed_change_order(project_id, target_line_item_id, actors, delta_cents=20000):
    """Submit a change order and collect both PM and client sign-offs (status
    stays SUBMITTED). Returns the change order row."""
    from .factories import create_change_order_payload
    co = get_success_data(api_client.create_change_order(
        create_change_order_payload(project_id, target_line_item_id, delta_cents=delta_cents),
        actors["pm_h"]))
    get_success_data(api_client.sign_change_order(co["id"], actors["pm_h"]))
    get_success_data(api_client.sign_change_order(co["id"], actors["client_h"]))
    return co


def approve_change_order(project_id, co_id, actors):
    """Approve a dual-signed change order using the live project version."""
    v = current_project_version(project_id, actors)
    return get_success_data(api_client.approve_change_order(
        co_id, {"expected_project_version": v}, actors["pm_h"]))
