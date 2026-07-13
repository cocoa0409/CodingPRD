"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints and uses
get_success_data() (lenient) so setup failures surface as clear "Setup failed" errors.
The test harness restarts the server (empty DB, logical clock reset to 2026-03-01T00:00:00Z)
before every test, so these helpers never assume carried-over state.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .constants import COVERING_SHIFT_START, COVERING_SHIFT_END

COMMANDER = TEST_USERS["commander_headers"]
SHELTER = TEST_USERS["shelter_headers"]
TRAFFIC = TEST_USERS["traffic_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
PIO = TEST_USERS["pio_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-step creators / transitions (return the resource data dict)
# ---------------------------------------------------------------------------
def create_incident(name="Ridge Fire", jurisdiction="Butte County",
                    hazard_type="WILDFIRE", ipaws_daily_slot_budget=None):
    payload = {"name": name, "jurisdiction": jurisdiction, "hazard_type": hazard_type}
    if ipaws_daily_slot_budget is not None:
        payload["ipaws_daily_slot_budget"] = ipaws_daily_slot_budget
    return get_success_data(api_client.create_incident(payload, COMMANDER))


def set_incident_phase(incident_id, to_phase):
    return get_success_data(
        api_client.set_incident_phase(incident_id, {"to_phase": to_phase}, COMMANDER)
    )


def create_active_incident(**overrides):
    inc = create_incident(**overrides)
    return set_incident_phase(inc["id"], "ACTIVE")


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, COMMANDER))


def create_zone(incident_id, **overrides):
    payload = {
        "incident_id": incident_id,
        "name": "Zone-1",
        "geofence_wkt": "POLYGON((0 0,0 1,1 1,1 0,0 0))",
        "residential_population": 100,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_zone(payload, COMMANDER))


def order_zone(zone_id, level):
    return get_success_data(
        api_client.set_zone_order(zone_id, {"level": level}, COMMANDER)
    )


def create_shelter(incident_id, physical_capacity=10, ada_reserved_pct=None,
                   power_backup=True, name="North HS"):
    payload = {
        "incident_id": incident_id,
        "name": name,
        "physical_capacity": physical_capacity,
        "power_backup": power_backup,
    }
    if ada_reserved_pct is not None:
        payload["ada_reserved_pct"] = ada_reserved_pct
    return get_success_data(api_client.create_shelter(payload, SHELTER))


def create_staff_shift(shelter_id, staffed_beds=20, start_utc=COVERING_SHIFT_START,
                       end_utc=COVERING_SHIFT_END, role_label="GENERAL"):
    payload = {
        "shelter_id": shelter_id,
        "role_label": role_label,
        "staffed_beds": staffed_beds,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    return get_success_data(api_client.create_staff_shift(payload, SHELTER))


def set_shelter_status(shelter_id, state):
    return get_success_data(
        api_client.set_shelter_status(shelter_id, {"state": state}, SHELTER)
    )


def create_registrant(zone_id, party_size=2, functional_needs=None,
                      household_name="Alvarez", transport_required=None):
    payload = {"zone_id": zone_id, "household_name": household_name, "party_size": party_size}
    if functional_needs is not None:
        payload["functional_needs"] = functional_needs
    if transport_required is not None:
        payload["transport_required"] = transport_required
    return get_success_data(api_client.create_registrant(payload, REGISTRAR))


def create_assignment(registrant_id, shelter_id, expected_registrant_version):
    payload = {
        "registrant_id": registrant_id,
        "shelter_id": shelter_id,
        "expected_registrant_version": expected_registrant_version,
    }
    return get_success_data(api_client.create_shelter_assignment(payload, SHELTER))


def assignment_action(assignment_id, action):
    return get_success_data(
        api_client.set_shelter_assignment_status(assignment_id, {"action": action}, SHELTER)
    )


def create_route(incident_id, throughput_vph=1200, name="US-101 N", corridor_label="US-101"):
    payload = {
        "incident_id": incident_id,
        "name": name,
        "corridor_label": corridor_label,
        "throughput_vph": throughput_vph,
    }
    return get_success_data(api_client.create_route(payload, TRAFFIC))


def set_route_status(route_id, state):
    return get_success_data(
        api_client.set_route_status(route_id, {"state": state}, TRAFFIC)
    )


def create_contraflow(route_id, segment_key="SEG-A", direction="INBOUND_REVERSED",
                      window_start_utc="2026-03-01T10:00:00Z",
                      window_end_utc="2026-03-01T12:00:00Z"):
    payload = {
        "route_id": route_id,
        "segment_key": segment_key,
        "direction": direction,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    return get_success_data(api_client.create_contraflow_segment(payload, TRAFFIC))


def create_credential(zone_id, registrant_id, credential_type="RESIDENT",
                      valid_from_utc="2026-02-01T00:00:00Z",
                      valid_until_utc="2026-12-01T00:00:00Z"):
    payload = {
        "zone_id": zone_id,
        "registrant_id": registrant_id,
        "credential_type": credential_type,
        "valid_from_utc": valid_from_utc,
        "valid_until_utc": valid_until_utc,
    }
    return get_success_data(api_client.create_access_credential(payload, REGISTRAR))


def create_alert(zone_id, channels, severity="WARNING", message="Evacuate now"):
    payload = {"zone_id": zone_id, "message": message, "severity": severity, "channels": channels}
    return get_success_data(api_client.create_alert(payload, PIO))


def set_alert_status(alert_id, state):
    return get_success_data(
        api_client.set_alert_status(alert_id, {"state": state}, PIO)
    )


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenarios
# ---------------------------------------------------------------------------
def setup_active_incident_with_zone(order_level="VOLUNTARY", **zone_overrides):
    """Active incident + one zone driven to `order_level`. Returns (incident, zone)."""
    inc = create_active_incident()
    zone = create_zone(inc["id"], **zone_overrides)
    if order_level != "NONE":
        zone = order_zone(zone["id"], order_level)
    return inc, zone


def setup_checkin_scenario(order_level="MANDATORY", physical_capacity=5, staffed_beds=5,
                           ada_reserved_pct=0, power_backup=True, party_size=2,
                           functional_needs=None, open_shelter=True, close_shelter=False):
    """Build a shelter + a RESERVED assignment ready for a CHECK_IN attempt.

    Returns a dict with keys: incident, zone, shelter, registrant, assignment.
    - open_shelter=False leaves the shelter STANDBY.
    - close_shelter=True closes the shelter from STANDBY *after* the reservation
      exists (STANDBY -> CLOSED does not cancel RESERVED assignments).
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    order_zone(zone["id"], order_level)
    shelter = create_shelter(inc["id"], physical_capacity=physical_capacity,
                             ada_reserved_pct=ada_reserved_pct, power_backup=power_backup)
    if staffed_beds > 0:
        create_staff_shift(shelter["id"], staffed_beds=staffed_beds)
    if open_shelter:
        shelter = set_shelter_status(shelter["id"], "OPEN")
    reg = create_registrant(zone["id"], party_size=party_size, functional_needs=functional_needs)
    asg = create_assignment(reg["id"], shelter["id"], reg["version"])
    if close_shelter:
        shelter = set_shelter_status(shelter["id"], "CLOSED")
    return {"incident": inc, "zone": zone, "shelter": shelter,
            "registrant": reg, "assignment": asg}


def setup_open_shelter(order_level="MANDATORY", physical_capacity=5, staffed_beds=5,
                       ada_reserved_pct=0, power_backup=True):
    """Active incident + ordered zone + an OPEN, staffed shelter (no reservation yet).
    Returns (incident, zone, shelter)."""
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    order_zone(zone["id"], order_level)
    shelter = create_shelter(inc["id"], physical_capacity=physical_capacity,
                             ada_reserved_pct=ada_reserved_pct, power_backup=power_backup)
    create_staff_shift(shelter["id"], staffed_beds=staffed_beds)
    shelter = set_shelter_status(shelter["id"], "OPEN")
    return inc, zone, shelter


def reserve_and_check_in(shelter_id, zone_id, party_size, functional_needs=None):
    """Create a registrant, reserve on the shelter, and CHECK_IN. Returns (registrant, assignment)."""
    reg = create_registrant(zone_id, party_size=party_size, functional_needs=functional_needs)
    asg = create_assignment(reg["id"], shelter_id, reg["version"])
    asg = assignment_action(asg["id"], "CHECK_IN")
    return reg, asg


def setup_route_open_with_contraflow(segment_key="SEG-A",
                                     window_start_utc="2026-03-01T10:00:00Z",
                                     window_end_utc="2026-03-01T12:00:00Z"):
    """Active incident + OPEN route + one SCHEDULED contraflow segment.
    Returns (incident, route, segment)."""
    inc = create_active_incident()
    route = create_route(inc["id"])
    route = set_route_status(route["id"], "OPEN")
    seg = create_contraflow(route["id"], segment_key=segment_key,
                            window_start_utc=window_start_utc, window_end_utc=window_end_utc)
    return inc, route, seg
