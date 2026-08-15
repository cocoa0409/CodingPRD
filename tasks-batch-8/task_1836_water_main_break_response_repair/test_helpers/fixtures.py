"""Composite setup helpers for the water-main-break domain.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup step failed" error.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    complete_work_order_payload,
    confirm_break_report_payload,
    create_boil_water_advisory_payload,
    create_break_report_payload,
    create_crew_payload,
    create_damage_claim_payload,
    create_isolation_event_payload,
    create_pipe_segment_payload,
    create_pressure_anomaly_payload,
    create_traffic_permit_payload,
    create_valve_payload,
    create_water_quality_test_payload,
    create_work_order_payload,
    dispatch_work_order_payload,
    schedule_restoration_job_payload,
)
from .test_users import TEST_USERS, make_crew_lead_headers

# Header shortcuts (module-level so fixtures read cleanly)
DISPATCHER = TEST_USERS["dispatcher_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SYSTEM = TEST_USERS["system_headers"]
WQ1 = TEST_USERS["wq_officer_headers"]
WQ2 = TEST_USERS["wq_officer_2_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_segment(segment_ref="MAIN-8-OAK", material="DUCTILE_IRON",
                   diameter_inches=8, install_year=1978, **extra):
    """Create a PipeSegment. Returns the created entity dict."""
    payload = create_pipe_segment_payload(
        segment_ref=segment_ref, material=material,
        diameter_inches=diameter_inches, install_year=install_year, **extra
    )
    return get_success_data(api_client.create_pipe_segment(payload, ENGINEER), 201)


def create_valve(segment_id, valve_code, coverage_zone="Z1", customers_served=100):
    """Create a Valve on a segment. Returns the created entity dict."""
    payload = create_valve_payload(
        valve_code=valve_code, pipe_segment_id=segment_id,
        coverage_zone=coverage_zone, customers_served=customers_served,
    )
    return get_success_data(api_client.create_valve(payload, ENGINEER), 201)


def create_crew(crew_name="Crew Alpha", crew_size=3, equipment_class="LIGHT",
                hourly_rate_cents=6000):
    """Create a Crew. Returns the created entity dict."""
    payload = create_crew_payload(
        crew_name=crew_name, crew_size=crew_size,
        equipment_class=equipment_class, hourly_rate_cents=hourly_rate_cents,
    )
    return get_success_data(api_client.create_crew(payload, DISPATCHER), 201)


def create_break(location_description="12 Oak St", source="CUSTOMER_CALL"):
    """File a BreakReport (born REPORTED). Returns the created entity dict."""
    payload = create_break_report_payload(
        location_description=location_description, source=source
    )
    return get_success_data(api_client.create_break_report(payload, DISPATCHER), 201)


def confirm_break(break_id, segment_id, break_type="CIRCUMFERENTIAL",
                  severity="MEDIUM"):
    """Confirm a REPORTED break against a segment. Returns the updated break."""
    payload = confirm_break_report_payload(
        pipe_segment_id=segment_id, break_type=break_type, severity=severity
    )
    return get_success_data(
        api_client.confirm_break_report(break_id, payload, DISPATCHER), 200
    )


def create_anomaly(segment_id, anomaly_type="PRESSURE_DROP",
                   observed_at="2026-08-01T00:00:00Z", magnitude_pct=45):
    """Post a pressure/flow anomaly. Returns the created entity dict."""
    payload = create_pressure_anomaly_payload(
        pipe_segment_id=segment_id, anomaly_type=anomaly_type,
        observed_at=observed_at, magnitude_pct=magnitude_pct,
    )
    return get_success_data(api_client.create_pressure_anomaly(payload, SYSTEM), 201)


def create_isolation_plan(break_id, valve_ids, expected_break_report_version):
    """Create a PLANNED IsolationEvent (OCC-guarded). Returns the plan."""
    payload = create_isolation_event_payload(
        break_report_id=break_id, valve_ids=valve_ids,
        expected_break_report_version=expected_break_report_version,
    )
    return get_success_data(api_client.create_isolation_event(payload, DISPATCHER), 201)


def execute_isolation(isolation_id):
    """Execute a PLANNED isolation. Returns the updated IsolationEvent."""
    return get_success_data(
        api_client.execute_isolation_event(isolation_id, DISPATCHER), 200
    )


def get_break(break_id):
    return get_success_data(api_client.get_break_report(break_id, DISPATCHER), 200)


def get_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, DISPATCHER), 200)


def get_crew(crew_id):
    return get_success_data(api_client.get_crew(crew_id, DISPATCHER), 200)


def get_advisory(advisory_id):
    return get_success_data(
        api_client.get_boil_water_advisory(advisory_id, DISPATCHER), 200
    )


def get_restoration_job(job_id):
    return get_success_data(api_client.get_restoration_job(job_id, DISPATCHER), 200)


def list_break_isolations(break_id):
    data, _meta = _list(api_client.list_break_isolation_events(break_id, DISPATCHER))
    return data


def list_break_advisories(break_id):
    data, _meta = _list(api_client.list_break_advisories(break_id, DISPATCHER))
    return data


def list_segment_valves(segment_id):
    data, _meta = _list(api_client.list_segment_valves(segment_id, DISPATCHER))
    return data


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, SYSTEM), 200)


def run_ops():
    return get_success_data(api_client.run_ops_checkpoint(SYSTEM), 200)


# ---------------------------------------------------------------------------
# Tier 2: hierarchy builders — segment + valves (+ crew)
# ---------------------------------------------------------------------------

def setup_segment_with_valves(segment_ref="MAIN-8-OAK", diameter_inches=8,
                              material="DUCTILE_IRON", install_year=1978,
                              valve_specs: Optional[List[dict]] = None):
    """Create a segment plus N valves.

    valve_specs: list of dicts with keys valve_code/coverage_zone/customers_served.
    Defaults to a single valve V-1/Z1/100.
    Returns (segment, valves list).
    """
    seg = create_segment(
        segment_ref=segment_ref, material=material,
        diameter_inches=diameter_inches, install_year=install_year,
    )
    specs = valve_specs or [
        {"valve_code": "V-1", "coverage_zone": "Z1", "customers_served": 100},
    ]
    valves = [create_valve(seg["id"], **spec) for spec in specs]
    return seg, valves


def setup_confirmed_break(segment_ref="MAIN-8-OAK", diameter_inches=8,
                          material="DUCTILE_IRON", install_year=1978,
                          valve_specs=None,
                          break_type="CIRCUMFERENTIAL", severity="MEDIUM",
                          location_description="12 Oak St",
                          source="CUSTOMER_CALL"):
    """Segment + valve(s) + filed & confirmed break.

    Returns dict with keys: segment, valves, break.
    """
    seg, valves = setup_segment_with_valves(
        segment_ref=segment_ref, diameter_inches=diameter_inches,
        material=material, install_year=install_year, valve_specs=valve_specs,
    )
    br = create_break(location_description=location_description, source=source)
    br = confirm_break(br["id"], seg["id"], break_type=break_type, severity=severity)
    return {"segment": seg, "valves": valves, "break": br}


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — isolation / work-order progression
# ---------------------------------------------------------------------------

def isolate_break(break_id, valve_ids):
    """Create + execute an isolation plan for a CONFIRMED/REPAIRED break.

    Reads the break's current version first so the OCC check passes.
    Returns the executed IsolationEvent.
    """
    current = get_break(break_id)
    plan = create_isolation_plan(break_id, valve_ids, current["version"])
    return execute_isolation(plan["id"])


def setup_isolated_break(**kwargs):
    """setup_confirmed_break + executed isolation over all its valves.

    Returns dict with keys: segment, valves, break (refreshed), isolation.
    """
    ctx = setup_confirmed_break(**kwargs)
    iso = isolate_break(ctx["break"]["id"], [v["id"] for v in ctx["valves"]])
    ctx["isolation"] = iso
    ctx["break"] = get_break(ctx["break"]["id"])
    return ctx


def setup_dispatched_work_order(crew_name="Crew Alpha", crew_rate=6000,
                                crew_class=None, crew_size=3,
                                est_pipe_length_ft=4, **kwargs):
    """Isolated break + crew + work order dispatched to that crew.

    crew_class defaults to the class sufficient for the computed requirement
    (HEAVY when required, else LIGHT) — pass explicitly to test class rules.
    Returns dict with keys: segment, valves, break, isolation, crew, work_order.
    """
    ctx = setup_isolated_break(**kwargs)
    cls = crew_class or "LIGHT"
    crew = create_crew(crew_name=crew_name, crew_size=crew_size,
                       equipment_class=cls, hourly_rate_cents=crew_rate)
    wo = get_success_data(
        api_client.create_work_order(
            create_work_order_payload(
                break_report_id=ctx["break"]["id"],
                est_pipe_length_ft=est_pipe_length_ft,
            ),
            DISPATCHER,
        ),
        201,
    )
    wo = get_success_data(
        api_client.dispatch_work_order(
            wo["id"], dispatch_work_order_payload(crew_id=crew["id"]), DISPATCHER
        ),
        200,
    )
    ctx.update({"crew": crew, "work_order": wo})
    return ctx


def setup_on_site_work_order(**kwargs):
    """Dispatched work order + CrewLead arrival (break moves to IN_REPAIR).

    Returns dict with keys: segment, valves, break, isolation, crew, work_order.
    """
    ctx = setup_dispatched_work_order(**kwargs)
    wo = get_success_data(
        api_client.arrive_work_order(
            ctx["work_order"]["id"], make_crew_lead_headers(ctx["crew"]["id"])
        ),
        200,
    )
    ctx["work_order"] = wo
    ctx["break"] = get_break(ctx["break"]["id"])
    return ctx


def complete_work_order(work_order_id, crew_id, actual_pipe_length_ft=4,
                        labor_hours=1, materials_used=None):
    """Complete an ON_SITE work order as its owning CrewLead. Returns updated WO."""
    payload = complete_work_order_payload(
        actual_pipe_length_ft=actual_pipe_length_ft, labor_hours=labor_hours,
        materials_used=materials_used if materials_used is not None else [],
    )
    return get_success_data(
        api_client.complete_work_order(
            work_order_id, payload, make_crew_lead_headers(crew_id)
        ),
        200,
    )


def setup_repaired_break(materials_used=None, labor_hours=1,
                         actual_pipe_length_ft=4, **kwargs):
    """Full path through REPAIR_COMPLETE: break is REPAIRED, isolation RESTORED,
    a PENDING RestorationJob exists against the completed work order.

    Returns dict with keys: segment, valves, break, isolation, crew,
    work_order (REPAIR_COMPLETE), restoration_job.
    """
    ctx = setup_on_site_work_order(**kwargs)
    wo = complete_work_order(
        ctx["work_order"]["id"], ctx["crew"]["id"],
        actual_pipe_length_ft=actual_pipe_length_ft,
        labor_hours=labor_hours, materials_used=materials_used,
    )
    ctx["work_order"] = wo
    ctx["break"] = get_break(ctx["break"]["id"])
    ctx["restoration_job"] = find_restoration_job_for_work_order(wo["id"])
    return ctx


def find_restoration_job_for_work_order(work_order_id):
    """Locate the auto-created PENDING restoration job for a work order."""
    data, _meta = _list(
        api_client.list_restoration_jobs(
            DISPATCHER, params={"work_order_id": work_order_id}
        )
    )
    assert len(data) == 1, f"expected exactly 1 restoration job for {work_order_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 4: permit + restoration
# ---------------------------------------------------------------------------

def create_approved_permit(break_id, street_block="OAK-100-BLK",
                           valid_from="2026-08-10T00:00:00Z",
                           valid_to="2026-08-12T00:00:00Z",
                           control_plan="LANE_CLOSURE"):
    """Create + approve a traffic permit. Returns the APPROVED permit."""
    payload = create_traffic_permit_payload(
        break_report_id=break_id, street_block=street_block,
        valid_from=valid_from, valid_to=valid_to, control_plan=control_plan,
    )
    perm = get_success_data(api_client.create_traffic_permit(payload, DISPATCHER), 201)
    return get_success_data(api_client.approve_traffic_permit(perm["id"], ENGINEER), 200)


def schedule_and_complete_restoration(job_id, permit_id, patch_cost_cents=10000,
                                      scheduled_start="2026-08-10T08:00:00Z",
                                      scheduled_end="2026-08-10T16:00:00Z"):
    """Schedule then complete a restoration job. Returns the COMPLETED job."""
    payload = schedule_restoration_job_payload(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        traffic_permit_id=permit_id,
    )
    get_success_data(api_client.schedule_restoration_job(job_id, payload, DISPATCHER), 200)
    return get_success_data(
        api_client.complete_restoration_job(
            job_id, {"patch_cost_cents": patch_cost_cents}, DISPATCHER
        ),
        200,
    )


def setup_restored_break(permit_block="OAK-100-BLK", patch_cost_cents=10000,
                         valid_from="2026-08-10T00:00:00Z",
                         valid_to="2026-08-12T00:00:00Z",
                         scheduled_start="2026-08-10T08:00:00Z",
                         scheduled_end="2026-08-10T16:00:00Z",
                         **kwargs):
    """Repaired break + approved permit + scheduled + completed restoration.
    The break is RESTORED once all its restoration jobs complete.

    Returns the repaired-break context plus permit and completed job.
    """
    ctx = setup_repaired_break(**kwargs)
    perm = create_approved_permit(
        ctx["break"]["id"], street_block=permit_block,
        valid_from=valid_from, valid_to=valid_to,
    )
    rj = schedule_and_complete_restoration(
        ctx["restoration_job"]["id"], perm["id"], patch_cost_cents=patch_cost_cents,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    ctx["permit"] = perm
    ctx["restoration_job"] = rj
    ctx["break"] = get_break(ctx["break"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: advisory helpers
# ---------------------------------------------------------------------------

def issue_manual_advisory(break_id, officer_headers=None):
    """Manually issue a boil-water advisory. Returns the ISSUED advisory."""
    headers = officer_headers or WQ1
    payload = create_boil_water_advisory_payload(break_report_id=break_id)
    return get_success_data(
        api_client.create_boil_water_advisory(payload, headers), 201
    )


def record_sample(advisory_id, sampled_at, chlorine_residual_mg_l=0.30,
                  coliform_result="PASS", officer_headers=None):
    """Record a water-quality test. Returns the created test."""
    headers = officer_headers or WQ1
    payload = create_water_quality_test_payload(
        advisory_id=advisory_id, sampled_at=sampled_at,
        chlorine_residual_mg_l=chlorine_residual_mg_l,
        coliform_result=coliform_result,
    )
    return get_success_data(api_client.create_water_quality_test(payload, headers), 201)


def setup_advisory_with_passes(num_passes=2, break_kwargs=None):
    """Confirmed break + manual advisory (wq_officer_1) + num_passes PASS samples
    spaced 24h apart starting 2026-08-02T00:00:00Z.

    Returns dict with keys: segment, break, advisory.
    """
    bk = break_kwargs or {}
    ctx = setup_confirmed_break(**bk)
    adv = issue_manual_advisory(ctx["break"]["id"], WQ1)
    for i in range(num_passes):
        day = 2 + i
        record_sample(adv["id"], f"2026-08-{day:02d}T00:00:00Z")
    ctx["advisory"] = get_advisory(adv["id"])
    return ctx


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------

def create_claim(break_id, claimant_name="J. Homeowner", claimed_amount_cents=100000):
    payload = create_damage_claim_payload(
        break_report_id=break_id, claimant_name=claimant_name,
        claimed_amount_cents=claimed_amount_cents,
    )
    return get_success_data(api_client.create_damage_claim(payload, DISPATCHER), 201)


def approve_claim(claim_id, approved_amount_cents):
    return get_success_data(
        api_client.approve_damage_claim(
            claim_id, {"approved_amount_cents": approved_amount_cents}, ADJUSTER
        ),
        200,
    )
