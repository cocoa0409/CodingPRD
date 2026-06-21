"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for setup calls so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion failure mid-test. Every fixture builds its state from scratch using
only PRD-declared endpoints, because the server DB is empty before every test.

Project lifecycle reminder (§3): DRAFT -> ESTIMATING (create estimate) ->
APPROVED (approve estimate) -> SCHEDULED (schedule) -> POURED (complete pour) ->
CURING (begin cure) -> COMPLETED (complete). Approving an estimate, approving a
change order, and releasing a draw all require expected_project_version (§2.7).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_project_payload, create_segment_payload, create_estimate_payload,
    approve_estimate_payload, create_permit_payload, create_material_order_payload,
    start_pour_payload, complete_pour_payload, create_weather_reading_payload,
    create_crew_payload, create_equipment_payload, create_crew_assignment_payload,
    create_change_order_payload, approve_change_order_payload, create_draw_payload,
    release_draw_payload, create_warranty_payload, set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_finance_officer_headers,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]
FIN = TEST_USERS["finance_officer_headers"]
INS = TEST_USERS["inspector_headers"]


# ─── primitives ──────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the server logical UTC clock (§2.10, ProjectManager only)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), PM))


def project_version(project_id: str) -> int:
    return get_success_data(api_client.get_project(project_id, PM))["version"]


def create_project(site_name="Site", client_name="Client") -> dict:
    return get_success_data(api_client.create_project(
        create_project_payload(site_name=site_name, client_name=client_name), EST))


def add_segment(project_id: str, **seg) -> dict:
    return get_success_data(api_client.create_segment(
        project_id, create_segment_payload(**seg), EST))


def create_estimate(project_id: str) -> dict:
    return get_success_data(api_client.create_estimate(
        project_id, create_estimate_payload(), EST))


# ─── Tier 1: State progression on Project ────────────────────────────────────

#: Standard two-segment scope: 600@4 BROOM/REBAR + 240@5 STAMPED/REBAR.
#: estimate_total == 12452.50, provisional_cubic_yards == 13.
COMBO_840_SEGMENTS = [
    dict(label="driveway", area_sqft=600, thickness_in=4, finish_grade="BROOM", reinforcement="REBAR"),
    dict(label="patio", area_sqft=240, thickness_in=5, finish_grade="STAMPED", reinforcement="REBAR"),
]

#: Single 400@4 REBAR slab (no NONE-reinforcement penalty).
SINGLE_400_REBAR = [dict(label="slab", area_sqft=400, thickness_in=4, reinforcement="REBAR")]


def create_estimating_project(segments=None, site_name="Est"):
    """DRAFT project + segments + first estimate -> ESTIMATING.
    Returns (project_dict, estimate_dict)."""
    segments = segments if segments is not None else SINGLE_400_REBAR
    proj = create_project(site_name=site_name)
    for seg in segments:
        add_segment(proj["id"], **seg)
    est = create_estimate(proj["id"])
    proj = get_success_data(api_client.get_project(proj["id"], PM))
    return proj, est


def create_approved_project(segments=None, site_name="Appr"):
    """Project advanced to APPROVED with its estimate approved.
    Returns (project_dict, estimate_dict). The project is refetched post-approval
    so base_contract_amount / contract values are populated."""
    proj, est = create_estimating_project(segments=segments, site_name=site_name)
    pv = project_version(proj["id"])
    get_success_data(api_client.approve_estimate(
        proj["id"], approve_estimate_payload(est["id"], pv), PM))
    proj = get_success_data(api_client.get_project(proj["id"], PM))
    return proj, est


def create_rejected_project(segments=None, site_name="Rej"):
    proj, est = create_estimating_project(segments=segments, site_name=site_name)
    get_success_data(api_client.reject_project(proj["id"], PM))
    proj = get_success_data(api_client.get_project(proj["id"], PM))
    return proj, est


# ─── Tier 2: Resource pools & bookings ───────────────────────────────────────

def create_crew(crew_name="Crew", skill="FLATWORK", headcount=4) -> dict:
    return get_success_data(api_client.create_crew(
        create_crew_payload(crew_name=crew_name, skill=skill, headcount=headcount), PM))


def create_equipment(asset_name="Pump", asset_type="PUMP_TRUCK") -> dict:
    return get_success_data(api_client.create_equipment(
        create_equipment_payload(asset_name=asset_name, asset_type=asset_type), PM))


def book_crew(project_id, crew_id, window_start, window_end, equipment_id=None) -> dict:
    extra = {} if equipment_id is None else {"equipment_id": equipment_id}
    return get_success_data(api_client.create_crew_assignment(
        project_id,
        create_crew_assignment_payload(crew_id, window_start, window_end, **extra),
        PM))


def issue_permit(project_id, permit_number="P-1") -> dict:
    perm = get_success_data(api_client.create_permit(
        project_id, create_permit_payload(permit_number=permit_number), PM))
    perm = get_success_data(api_client.issue_permit(perm["id"], INS))
    return perm


def place_material_order(project_id, mix_type="STANDARD",
                         pour_scheduled_start="2026-07-01T12:00:00Z",
                         pour_duration_hours=4) -> dict:
    return get_success_data(api_client.create_material_order(
        project_id,
        create_material_order_payload(
            mix_type=mix_type,
            pour_scheduled_start=pour_scheduled_start,
            pour_duration_hours=pour_duration_hours),
        PM))


# ─── Tier 3: Full lifecycle shortcuts ────────────────────────────────────────

def create_scheduled_project(segments=None, site_name="Sched",
                             mix_type="STANDARD",
                             pour_scheduled_start="2026-07-01T12:00:00Z",
                             pour_duration_hours=4,
                             window_start="2026-07-01T12:00:00Z",
                             window_end="2026-07-01T18:00:00Z",
                             issue_the_permit=True,
                             clock=None):
    """APPROVED -> SCHEDULED. Issues a permit, places one material order, books
    one crew, then schedules. Returns dict with project/permit/material_order/
    crew/assignment. If issue_the_permit is False the permit is left APPLIED so
    the schedule precondition test can drive its own trigger."""
    if clock is not None:
        set_clock(clock)
    proj, est = create_approved_project(segments=segments, site_name=site_name)
    if issue_the_permit:
        permit = issue_permit(proj["id"])
    else:
        permit = get_success_data(api_client.create_permit(
            proj["id"], create_permit_payload(), PM))
    mo = place_material_order(
        proj["id"], mix_type=mix_type,
        pour_scheduled_start=pour_scheduled_start,
        pour_duration_hours=pour_duration_hours)
    crew = create_crew(crew_name=f"{site_name}-crew")
    assignment = book_crew(proj["id"], crew["id"], window_start, window_end)
    project = get_success_data(api_client.schedule_project(proj["id"], PM))
    return {
        "project": project, "estimate": est, "permit": permit,
        "material_order": mo, "crew": crew, "assignment": assignment,
    }


def create_poured_project(segments=None, site_name="Poured",
                          mix_type="HIGH_EARLY",
                          pour_scheduled_start="2026-06-01T06:00:00Z",
                          pour_duration_hours=4,
                          window_start="2026-06-01T06:00:00Z",
                          window_end="2026-06-01T12:00:00Z",
                          completed_at="2026-06-01T10:00:00Z",
                          clock="2026-06-01T00:00:00Z",
                          issue_warranty=True,
                          force_override=None,
                          weather_reading=None):
    """SCHEDULED -> POURED. Optionally appends a weather reading and issues a
    warranty before scheduling. Starts the pour (optionally force_override) then
    completes it. Returns dict including the poured project and material order."""
    set_clock(clock)
    proj, est = create_approved_project(segments=segments, site_name=site_name)
    permit = issue_permit(proj["id"])
    mo = place_material_order(
        proj["id"], mix_type=mix_type,
        pour_scheduled_start=pour_scheduled_start,
        pour_duration_hours=pour_duration_hours)
    if weather_reading is not None:
        get_success_data(api_client.create_weather_reading(
            mo["id"], create_weather_reading_payload(**weather_reading), PM))
    crew = create_crew(crew_name=f"{site_name}-crew")
    book_crew(proj["id"], crew["id"], window_start, window_end)
    warranty = None
    if issue_warranty:
        warranty = get_success_data(api_client.create_warranty(
            proj["id"], create_warranty_payload(12), PM))
    get_success_data(api_client.schedule_project(proj["id"], PM))
    sp_payload = start_pour_payload() if force_override is None else start_pour_payload(force_override=force_override)
    get_success_data(api_client.start_pour(mo["id"], sp_payload, PM))
    mo = get_success_data(api_client.complete_pour(
        mo["id"], complete_pour_payload(completed_at), PM))
    project = get_success_data(api_client.get_project(proj["id"], PM))
    return {
        "project": project, "estimate": est, "permit": permit,
        "material_order": mo, "warranty": warranty,
    }


def create_curing_project(segments=None, site_name="Cure",
                          mix_type="HIGH_EARLY",
                          pour_scheduled_start="2026-06-01T06:00:00Z",
                          pour_duration_hours=4,
                          window_start="2026-06-01T06:00:00Z",
                          window_end="2026-06-01T12:00:00Z",
                          completed_at="2026-06-01T10:00:00Z",
                          clock="2026-06-01T00:00:00Z",
                          issue_warranty=True):
    """POURED -> CURING. Returns dict including the curing project, material
    order (with its cure_window_end populated), and warranty (or None)."""
    bundle = create_poured_project(
        segments=segments, site_name=site_name, mix_type=mix_type,
        pour_scheduled_start=pour_scheduled_start, pour_duration_hours=pour_duration_hours,
        window_start=window_start, window_end=window_end,
        completed_at=completed_at, clock=clock, issue_warranty=issue_warranty)
    project = get_success_data(api_client.begin_cure(bundle["project"]["id"], PM))
    bundle["project"] = project
    return bundle


def create_completed_project(segments=None, site_name="Done",
                             mix_type="HIGH_EARLY",
                             completed_at="2026-06-01T10:00:00Z",
                             clock_pour="2026-06-01T00:00:00Z",
                             clock_complete="2026-06-05T00:00:00Z",
                             window_start="2026-06-01T06:00:00Z",
                             window_end="2026-06-01T12:00:00Z"):
    """CURING -> COMPLETED. Advances the clock past cure_window_end then
    completes. Returns dict with completed project, warranty, assignment id."""
    set_clock(clock_pour)
    proj, est = create_approved_project(segments=segments, site_name=site_name)
    permit = issue_permit(proj["id"])
    mo = place_material_order(
        proj["id"], mix_type=mix_type,
        pour_scheduled_start=window_start, pour_duration_hours=4)
    crew = create_crew(crew_name=f"{site_name}-crew")
    assignment = book_crew(proj["id"], crew["id"], window_start, window_end)
    warranty = get_success_data(api_client.create_warranty(
        proj["id"], create_warranty_payload(12), PM))
    get_success_data(api_client.schedule_project(proj["id"], PM))
    get_success_data(api_client.start_pour(mo["id"], start_pour_payload(), PM))
    get_success_data(api_client.complete_pour(mo["id"], complete_pour_payload(completed_at), PM))
    get_success_data(api_client.begin_cure(proj["id"], PM))
    set_clock(clock_complete)
    project = get_success_data(api_client.complete_project(proj["id"], PM))
    return {
        "project": project, "estimate": est, "permit": permit,
        "material_order": mo, "warranty": warranty,
        "crew": crew, "assignment": assignment,
    }


# ─── Tier 4: Change orders & draws on an APPROVED project ─────────────────────

def submit_change_order(project_id, description, delta_amount, fin_user_id, **extra) -> dict:
    """Submit a change order as the FinanceOfficer carrying `fin_user_id`
    (recorded as submitted_by_user_id)."""
    headers = make_finance_officer_headers(fin_user_id)
    return get_success_data(api_client.create_change_order(
        project_id, create_change_order_payload(description, delta_amount, **extra), headers))


def review_change_order(change_order_id, fin_user_id) -> dict:
    headers = make_finance_officer_headers(fin_user_id)
    return get_success_data(api_client.start_review_change_order(change_order_id, headers))


def approve_change_order(project_id, change_order_id, fin_user_id) -> dict:
    """start-review (if needed elsewhere) is the caller's job. Approves with a
    fresh expected_project_version read immediately before the approve."""
    headers = make_finance_officer_headers(fin_user_id)
    pv = project_version(project_id)
    return get_success_data(api_client.approve_change_order(
        change_order_id, approve_change_order_payload(pv), headers))


def submit_review_approve_change_order(project_id, description, delta_amount, fin_user_id, **extra) -> dict:
    """Full submit -> start-review -> approve for one change order. Returns the
    APPROVED change order."""
    co = submit_change_order(project_id, description, delta_amount, fin_user_id, **extra)
    review_change_order(co["id"], fin_user_id)
    return approve_change_order(project_id, co["id"], fin_user_id)


def request_draw(project_id, draw_type, amount, fin_user_id) -> dict:
    headers = make_finance_officer_headers(fin_user_id)
    return get_success_data(api_client.create_draw(
        project_id, create_draw_payload(draw_type, amount), headers))


def release_draw(project_id, draw_id, fin_user_id) -> dict:
    """Reads a fresh expected_project_version immediately before release."""
    headers = make_finance_officer_headers(fin_user_id)
    pv = project_version(project_id)
    return get_success_data(api_client.release_draw(
        draw_id, release_draw_payload(pv), headers))


def request_and_release_draw(project_id, draw_type, amount, fin_user_id) -> dict:
    draw = request_draw(project_id, draw_type, amount, fin_user_id)
    return release_draw(project_id, draw["id"], fin_user_id)


# ─── Tier 5: Completed project + active warranty (for defect-claim tests) ─────

def create_completed_project_with_active_warranty(segments=None, site_name="Warr"):
    """COMPLETED project that still has an ACTIVE warranty (it is not voided by
    completion). Returns (project_dict, warranty_dict)."""
    segs = segments if segments is not None else SINGLE_400_REBAR
    bundle = create_completed_project(segments=segs, site_name=site_name)
    return bundle["project"], bundle["warranty"]
