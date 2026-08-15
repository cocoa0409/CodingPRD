"""Composite setup helpers (PRD §3 workflows).

Every test starts against a fresh server, so each fixture builds its own
preconditions from scratch via PRD-declared endpoints. All helpers use the
lenient get_success_data() so a setup failure surfaces as a clear error.

Canonical logical timeline used by the fixtures: clock starts at
2026-08-01T00:00:00Z (PRD §2.4); calls are triaged and dispatched at that
instant; the clock is then advanced for arrival and later steps.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import T1_THRESHOLDS
from .factories import (
    create_territory_payload,
    create_technician_payload,
    create_shift_payload,
    create_crew_payload,
    create_emergency_call_payload,
)
from .test_users import TEST_USERS, make_technician_headers, make_supervisor_headers

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]

SHIFT_START = "2026-08-01T00:00:00Z"
SHIFT_END = "2026-08-01T12:00:00Z"
DAY2 = "2026-08-02T00:00:00Z"


def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_territory(name="T1", **overrides):
    payload = create_territory_payload(name=name, **overrides)
    return get_success_data(api_client.create_territory(payload, ADMIN))


def create_technician(territory_id, full_name="Tech One", badge_number="B001",
                      hourly_rate_cents=6000):
    payload = create_technician_payload(
        full_name=full_name, badge_number=badge_number,
        home_territory_id=territory_id, hourly_rate_cents=hourly_rate_cents)
    return get_success_data(api_client.create_technician(payload, ADMIN))


def add_shift(technician_id, shift_start=SHIFT_START, shift_end=SHIFT_END,
              headers=None):
    payload = create_shift_payload(shift_start=shift_start, shift_end=shift_end)
    return get_success_data(api_client.create_shift(technician_id, payload,
                                                    headers or SUPERVISOR))


def create_crew(territory_id, crew_code="C1", hourly_rate_cents=6000):
    payload = create_crew_payload(crew_code=crew_code, territory_id=territory_id,
                                  hourly_rate_cents=hourly_rate_cents)
    return get_success_data(api_client.create_repair_crew(payload, ADMIN))


def setup_territory(**overrides):
    """Tier 1: just a territory. Returns territory dict."""
    set_clock("2026-08-01T00:00:00Z")
    return create_territory(**overrides)


def setup_territory_technician(shift_start=SHIFT_START, shift_end=SHIFT_END,
                               territory_overrides=None, tech_name="Tech One",
                               badge="B001"):
    """Tier 2: territory + one on-shift technician. Returns (territory, tech)."""
    terr = setup_territory(**(territory_overrides or {}))
    tech = create_technician(terr["id"], full_name=tech_name, badge_number=badge)
    add_shift(tech["id"], shift_start, shift_end)
    return terr, tech


def setup_territory_technician_crew(shift_start=SHIFT_START, shift_end=SHIFT_END,
                                    territory_overrides=None):
    """Tier 2: territory + on-shift technician + crew. Returns (terr, tech, crew)."""
    terr, tech = setup_territory_technician(shift_start, shift_end,
                                            territory_overrides)
    crew = create_crew(terr["id"])
    return terr, tech, crew


def intake_call(territory_id, address_line="1 Main St", city="Springfield",
                caller_name="Caller", caller_phone="555-0100",
                location_context="INSIDE_STRUCTURE", occupancy_type=None,
                odor_reported=True, symptoms_reported=False, hissing_reported=False,
                headers=None):
    """Intake one emergency call. Returns the created call record."""
    payload = create_emergency_call_payload(
        caller_name=caller_name, caller_phone=caller_phone,
        address_line=address_line, city=city, territory_id=territory_id,
        location_context=location_context,
        odor_reported=odor_reported, symptoms_reported=symptoms_reported,
        hissing_reported=hissing_reported)
    if occupancy_type is not None:
        payload["occupancy_type"] = occupancy_type
    return get_success_data(api_client.create_emergency_call(
        payload, headers or DISPATCHER))


def setup_new_incident(territory_id, **call_kwargs):
    """One PRIMARY call -> NEW incident. Returns (call, incident)."""
    call = intake_call(territory_id, **call_kwargs)
    incident = get_success_data(api_client.get_incident(call["incident_id"], SUPERVISOR))
    return call, incident


def triage(incident_id, priority="P2", headers=None):
    return get_success_data(api_client.triage_incident(
        incident_id, {"priority": priority}, headers or DISPATCHER))


def dispatch(incident_id, technician_id, headers=None):
    return get_success_data(api_client.create_dispatch(
        incident_id, {"technician_id": technician_id}, headers or DISPATCHER))


def arrive(dispatch_id, technician_id):
    return get_success_data(api_client.arrive_dispatch(
        dispatch_id, make_technician_headers(technician_id)))


def clear(dispatch_id, technician_id):
    return get_success_data(api_client.clear_dispatch(
        dispatch_id, make_technician_headers(technician_id)))


def record_reading(incident_id, technician_id, pct_lel=1.0, co_ppm=0,
                   reading_context="INSIDE"):
    return get_success_data(api_client.create_reading(
        incident_id,
        {"pct_lel": pct_lel, "co_ppm": co_ppm, "reading_context": reading_context},
        make_technician_headers(technician_id)))


def record_action(incident_id, technician_id, action_type="VENTILATE", notes=None):
    payload = {"action_type": action_type}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_make_safe_action(
        incident_id, payload, make_technician_headers(technician_id)))


def complete_make_safe(incident_id, technician_id, leak_confirmed=False,
                       no_make_safe_required=True):
    return get_success_data(api_client.complete_make_safe(
        incident_id,
        {"leak_confirmed": leak_confirmed,
         "no_make_safe_required": no_make_safe_required},
        make_technician_headers(technician_id)))


def setup_triaged_incident(territory_id, priority="P2", **call_kwargs):
    """Tier 3: incident triaged. Returns (call, incident)."""
    call, _inc = setup_new_incident(territory_id, **call_kwargs)
    incident = triage(call["incident_id"], priority)
    return call, incident


def setup_dispatched_incident(territory_id, technician_id, priority="P2",
                              **call_kwargs):
    """Tier 3: incident TRIAGED -> DISPATCHED with the given technician EN_ROUTE.
    Returns (call, incident, dispatch)."""
    call, _inc = setup_triaged_incident(territory_id, priority, **call_kwargs)
    disp = dispatch(call["incident_id"], technician_id)
    incident = get_success_data(api_client.get_incident(call["incident_id"], SUPERVISOR))
    return call, incident, disp


def setup_on_scene_incident(territory_id, technician_id, priority="P2",
                            arrive_at="2026-08-01T00:20:00Z", **call_kwargs):
    """Tier 3: incident driven to ON_SCENE (technician arrived).
    Returns (call, incident, dispatch)."""
    call, _inc, disp = setup_dispatched_incident(
        territory_id, technician_id, priority, **call_kwargs)
    if arrive_at is not None:
        set_clock(arrive_at)
    arrive(disp["id"], technician_id)
    incident = get_success_data(api_client.get_incident(call["incident_id"], SUPERVISOR))
    return call, incident, disp


def setup_monitoring_incident(territory_id, technician_id, priority="P2",
                              leak_confirmed=False, pct_lel=0.5, co_ppm=0,
                              reading_context="INSIDE", with_action=False,
                              arrive_at="2026-08-01T00:20:00Z", **call_kwargs):
    """Tier 5: incident in MONITORING (make-safe completed, odor gate satisfied).
    Returns (call, incident, dispatch)."""
    call, _inc, disp = setup_on_scene_incident(
        territory_id, technician_id, priority, arrive_at, **call_kwargs)
    inc_id = call["incident_id"]
    record_reading(inc_id, technician_id, pct_lel=pct_lel, co_ppm=co_ppm,
                   reading_context=reading_context)
    if with_action:
        record_action(inc_id, technician_id, "VENTILATE")
    complete_make_safe(inc_id, technician_id, leak_confirmed=leak_confirmed,
                       no_make_safe_required=True)
    incident = get_success_data(api_client.get_incident(inc_id, SUPERVISOR))
    return call, incident, disp


def setup_closed_incident(territory_id, technician_id, priority="P2",
                          leak_confirmed=False, arrive_at="2026-08-01T00:20:00Z",
                          close_at=None, **call_kwargs):
    """Tier 5: incident driven fully to CLOSED. Returns (call, incident, dispatch)."""
    call, _inc, disp = setup_monitoring_incident(
        territory_id, technician_id, priority, leak_confirmed=leak_confirmed,
        arrive_at=arrive_at, **call_kwargs)
    clear(disp["id"], technician_id)
    if close_at is not None:
        set_clock(close_at)
    get_success_data(api_client.close_incident(call["incident_id"], SUPERVISOR))
    incident = get_success_data(api_client.get_incident(call["incident_id"], SUPERVISOR))
    return call, incident, disp


def draft_determination(incident_id, responsibility="OUTSIDE_COMPANY",
                        basis="BARHOLE_SURVEY", drafter="sup-1"):
    """Draft a determination with a fresh OCC version read (PRD §2.8)."""
    inc = get_success_data(api_client.get_incident(incident_id, SUPERVISOR))
    return get_success_data(api_client.create_determination(
        incident_id,
        {"responsibility": responsibility, "basis": basis,
         "expected_incident_version": inc["version"]},
        make_supervisor_headers(drafter)))


def finalize_determination(determination_id, finalizer="sup-2"):
    return get_success_data(api_client.finalize_determination(
        determination_id, make_supervisor_headers(finalizer)))


def draft_and_finalize_determination(incident_id, responsibility="OUTSIDE_COMPANY",
                                     basis="BARHOLE_SURVEY",
                                     drafter="sup-1", finalizer="sup-2"):
    det = draft_determination(incident_id, responsibility, basis, drafter)
    return finalize_determination(det["id"], finalizer)


def setup_incident_with_auto_work_order(territory_id, technician_id,
                                        priority="P2",
                                        responsibility="OUTSIDE_COMPANY",
                                        **call_kwargs):
    """Tier 5: leak-confirmed MONITORING incident + FINAL determination, which
    auto-creates an OPEN work order (PRD §3.7). Returns
    (call, incident, dispatch, work_order)."""
    call, _inc, disp = setup_monitoring_incident(
        territory_id, technician_id, priority, leak_confirmed=True,
        **call_kwargs)
    inc_id = call["incident_id"]
    draft_and_finalize_determination(inc_id, responsibility)
    work_orders, _meta = _list_work_orders(inc_id)
    incident = get_success_data(api_client.get_incident(inc_id, SUPERVISOR))
    return call, incident, disp, work_orders[0]


def _list_work_orders(incident_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_work_orders(incident_id, SUPERVISOR)
    return validate_paginated(resp)


def list_work_orders(incident_id):
    return _list_work_orders(incident_id)[0]


def get_incident(incident_id):
    return get_success_data(api_client.get_incident(incident_id, SUPERVISOR))


def get_technician(technician_id):
    return get_success_data(api_client.get_technician(technician_id, SUPERVISOR))


def get_territory(territory_id):
    return get_success_data(api_client.get_territory(territory_id, SUPERVISOR))


def get_work_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, SUPERVISOR))


def get_report(report_id):
    return get_success_data(api_client.get_report(report_id, SUPERVISOR))


def create_report(territory_id, period_start="2026-08-01T00:00:00Z",
                  period_end="2026-08-02T00:00:00Z"):
    return get_success_data(api_client.create_report(
        {"territory_id": territory_id, "period_start": period_start,
         "period_end": period_end}, SUPERVISOR))
