"""Composite setup helpers — multi-step scenario builders used by tests.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the test runner restarts the server between tests).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_aircraft_payload,
    create_firefighter_payload,
    create_incident_payload,
    create_incident_report_payload,
    create_mutual_aid_agreement_payload,
    create_out_of_service_event_payload,
    create_profile_payload,
    create_readiness_check_payload,
    create_response_drill_payload,
    create_training_record_payload,
    create_vehicle_payload,
)
from .test_users import (
    TEST_USERS,
    make_airport_manager_headers,
    make_arff_chief_headers,
    make_safety_officer_headers,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]
SO = TEST_USERS["safety_officer_headers"]
FAA = TEST_USERS["faa_inspector_headers"]

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
TRAINING_DATE_CURRENT = "2026-04-15"


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, AM)
    return get_success_data(resp)


def reset_clock():
    return set_clock(DEFAULT_CLOCK)


def create_profile(airport_code="KDEMO", certificated_index="C"):
    resp = api_client.create_profile(
        create_profile_payload(
            airport_code=airport_code, certificated_index=certificated_index,
        ),
        AM,
    )
    return get_success_data(resp)


def create_aircraft(model_name="B737-900", length_ft=138.2,
                    avg_daily_departures=6.0, in_scheduled_service=True):
    resp = api_client.create_aircraft(
        create_aircraft_payload(
            model_name=model_name,
            length_ft=length_ft,
            avg_daily_departures=avg_daily_departures,
            in_scheduled_service=in_scheduled_service,
        ),
        AM,
    )
    return get_success_data(resp)


def create_vehicle(call_sign, water_capacity_gal=2000, dry_chem_capacity_lb=500):
    resp = api_client.create_vehicle(
        create_vehicle_payload(
            call_sign=call_sign,
            water_capacity_gal=water_capacity_gal,
            dry_chem_capacity_lb=dry_chem_capacity_lb,
        ),
        AC,
    )
    return get_success_data(resp)


def record_readiness_check(vehicle_id, water_available_gal=2000,
                           dry_chem_available_lb=500, discharge_system_ok=True):
    resp = api_client.create_readiness_check(
        create_readiness_check_payload(
            vehicle_id,
            water_available_gal=water_available_gal,
            dry_chem_available_lb=dry_chem_available_lb,
            discharge_system_ok=discharge_system_ok,
        ),
        AC,
    )
    return get_success_data(resp)


def create_firefighter(employee_no, full_name="FF"):
    resp = api_client.create_firefighter(
        create_firefighter_payload(employee_no=employee_no, full_name=full_name),
        AC,
    )
    return get_success_data(resp)


def record_training(firefighter_id, completed_on=TRAINING_DATE_CURRENT,
                    drill_type="AIRCRAFT", result="PASS"):
    resp = api_client.create_training_record(
        create_training_record_payload(
            firefighter_id,
            completed_on=completed_on,
            drill_type=drill_type,
            result=result,
        ),
        AC,
    )
    return get_success_data(resp)


def setup_compliant_index_c_airport(clock=DEFAULT_CLOCK,
                                    training_date=TRAINING_DATE_CURRENT,
                                    num_firefighters=4):
    """Build a fully compliant index-C airport:
    - profile certificated C
    - one qualifying band-C aircraft (B737-900, 138.2 ft, 6.0 dep/day)
    - two vehicles rated 2000 gal / 500 lb, each measured at full capacity
    - N ACTIVE firefighters all trained (PASS) at training_date

    Returns dict with profile, aircraft, vehicles, firefighters ids/entities.
    """
    set_clock(clock)
    profile = create_profile(airport_code="KDEMO", certificated_index="C")
    aircraft = create_aircraft()
    v1 = create_vehicle("RED-1", 2000, 500)
    v2 = create_vehicle("RED-2", 2000, 500)
    record_readiness_check(v1["id"], 2000, 500, True)
    record_readiness_check(v2["id"], 2000, 500, True)
    firefighters = []
    for i in range(1, num_firefighters + 1):
        ff = create_firefighter(f"FF-{100 + i}", f"FF {i}")
        drill_type = "AIRCRAFT" if i <= 2 else "STRUCTURAL"
        record_training(ff["id"], completed_on=training_date,
                        drill_type=drill_type, result="PASS")
        firefighters.append(ff)
    return {
        "profile": profile,
        "aircraft": aircraft,
        "veh1": v1,
        "veh2": v2,
        "firefighters": firefighters,
    }


def setup_profile_only(airport_code="KDEMO", certificated_index="C",
                       clock=DEFAULT_CLOCK):
    """Just a profile (and optionally a clock set). Returns profile."""
    if clock is not None:
        set_clock(clock)
    return create_profile(airport_code=airport_code,
                          certificated_index=certificated_index)


def create_controlled_incident(alert_level="ALERT_1", location="Taxiway A"):
    """Create an incident and drive REPORTED -> RESPONDING -> CONTROLLED.
    Assumes effective_index is sufficient for the chosen alert level.
    Returns the incident dict after control.
    """
    resp = api_client.create_incident(
        create_incident_payload(alert_level=alert_level, location=location), AC,
    )
    inc = get_success_data(resp)
    api_client.respond_incident(inc["id"], AC)
    resp = api_client.control_incident(inc["id"], AC)
    return get_success_data(resp)


def create_draft_report(incident_id, narrative=None, agent_expenditure_lines=None,
                        author_user_id="user-so-1"):
    payload_kwargs = {}
    if narrative is not None:
        payload_kwargs["narrative"] = narrative
    if agent_expenditure_lines is not None:
        payload_kwargs["agent_expenditure_lines"] = agent_expenditure_lines
    payload = create_incident_report_payload(**payload_kwargs)
    headers = make_safety_officer_headers(author_user_id)
    resp = api_client.create_incident_report(incident_id, payload, headers)
    return get_success_data(resp)


def create_submitted_report(incident_id, narrative=None,
                            author_user_id="user-so-1"):
    report = create_draft_report(incident_id, narrative=narrative,
                                 author_user_id=author_user_id)
    headers = make_safety_officer_headers(author_user_id)
    api_client.submit_incident_report(report["id"], headers)
    return report


def create_accepted_report(incident_id, narrative=None,
                           author_user_id="user-so-1",
                           reviewer_user_id="user-am-1"):
    report = create_submitted_report(incident_id, narrative=narrative,
                                     author_user_id=author_user_id)
    headers = make_airport_manager_headers(reviewer_user_id)
    api_client.accept_incident_report(report["id"], headers)
    return report


def create_active_agreement(partner_airport_code="KCTY", max_alert_level="ALERT_2",
                            start_date="2026-01-01", end_date="2026-12-31"):
    resp = api_client.create_mutual_aid_agreement(
        create_mutual_aid_agreement_payload(
            partner_airport_code=partner_airport_code,
            max_alert_level=max_alert_level,
            start_date=start_date,
            end_date=end_date,
        ),
        AM,
    )
    ag = get_success_data(resp)
    api_client.activate_mutual_aid_agreement(ag["id"], AM)
    resp = api_client.get_mutual_aid_agreement(ag["id"], AM)
    return get_success_data(resp)


def create_certified_drill(runway="09L",
                           window_start="2026-05-02T10:00:00Z",
                           window_end="2026-05-02T11:00:00Z",
                           execute_clock="2026-05-02T10:30:00Z",
                           first_vehicle_arrival_seconds=120,
                           all_vehicles_arrival_seconds=200):
    """Create a drill, advance clock into the window, execute with passing
    times, and certify it. Returns the CERTIFIED drill."""
    resp = api_client.create_response_drill(
        create_response_drill_payload(
            runway_designator=runway,
            scheduled_start=window_start,
            scheduled_end=window_end,
        ),
        AC,
    )
    drill = get_success_data(resp)
    set_clock(execute_clock)
    api_client.execute_response_drill(
        drill["id"],
        {
            "first_vehicle_arrival_seconds": first_vehicle_arrival_seconds,
            "all_vehicles_arrival_seconds": all_vehicles_arrival_seconds,
        },
        AC,
    )
    resp = api_client.certify_response_drill(drill["id"], AC)
    return get_success_data(resp)


def get_profile():
    resp = api_client.get_profile(AC)
    return get_success_data(resp)


def get_readiness(role_headers=None):
    resp = api_client.get_readiness(role_headers or AC)
    return get_success_data(resp)


def get_notifications(params=None):
    resp = api_client.list_index_downgrade_notifications(AC, params=params)
    return get_success_data(resp)


def get_firefighter(firefighter_id):
    resp = api_client.get_firefighter(firefighter_id, AC)
    return get_success_data(resp)


def get_vehicle(vehicle_id):
    resp = api_client.get_vehicle(vehicle_id, AC)
    return get_success_data(resp)


def open_oos_event(vehicle_id, reason="Foam pump failure"):
    resp = api_client.create_out_of_service_event(
        vehicle_id, create_out_of_service_event_payload(reason=reason), AC,
    )
    return get_success_data(resp)


def restore_oos_event(event_id):
    resp = api_client.restore_out_of_service_event(event_id, AC)
    return get_success_data(resp)
