"""Unit-assignment scheduling (vehicle/crew overlap semantics, certification,
window), and run-import uniqueness.

Translates difficulty queue (resource_temporal_overlap) and corner queue
(validations: duplicate run number, invalid window, out-of-service, crew cert).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_agency_org,
    create_patient_with_coverages,
    import_transport,
    import_and_code,
    create_vehicle,
    create_crew,
    create_assignment,
)
from test_helpers import factories as F


# ---------------------------------------------------------------------------
# resource_temporal_overlap / vehicle_closed_interval_plus_turnaround_buffer_conflict
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_vehicle_buffered_interval_conflict(api):
    """PRD §3.2: "the candidate occupies the interval from `window_start_iso` through
    `window_end_iso` plus the vehicle's `turnaround_minutes`, and the request is
    rejected with `ERR_VEHICLE_DOUBLE_BOOKED` (HTTP 409) if that buffered interval
    intersects any existing assignment's buffered interval for the same vehicle".

    Design: Difficulty/resource_temporal_overlap/vehicle_closed_interval_plus_turnaround_buffer_conflict
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    veh = create_vehicle(org, unit_call_sign="Medic-1", turnaround_minutes=30)
    crewA = create_crew(org, "PARAMEDIC", full_name="Crew A")
    crewB = create_crew(org, "PARAMEDIC", full_name="Crew B")
    t1 = import_transport(org, pat["id"], "V1", loaded_miles=5.0, emergency_indicator=True)
    t2 = import_transport(org, pat["id"], "V2", loaded_miles=5.0, emergency_indicator=True)
    create_assignment(org, t1["id"], veh["id"], crewA["id"],
                      "2026-06-09T09:00:00.000Z", "2026-06-09T10:00:00.000Z")
    # second starts 10:20, but the first occupies through 10:00 + 30min buffer = 10:30 -> conflict
    resp = api.create_unit_assignment(
        F.create_unit_assignment_payload(t2["id"], veh["id"], crewB["id"],
                                         "2026-06-09T10:20:00.000Z", "2026-06-09T11:00:00.000Z"),
        org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value)


def test_vehicle_assignment_clear_of_buffer_succeeds(api):
    """PRD §3.2: "the candidate occupies the interval from `window_start_iso` through
    `window_end_iso` plus the vehicle's `turnaround_minutes`, and the request is
    rejected with `ERR_VEHICLE_DOUBLE_BOOKED` (HTTP 409) if that buffered interval
    intersects any existing assignment's buffered interval for the same vehicle, with
    a boundary touch at the buffer edge counting as a conflict."

    Design: Difficulty/resource_temporal_overlap/vehicle_closed_interval_plus_turnaround_buffer_conflict
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    veh = create_vehicle(org, unit_call_sign="Medic-1", turnaround_minutes=30)
    crewA = create_crew(org, "PARAMEDIC", full_name="Crew A")
    crewB = create_crew(org, "PARAMEDIC", full_name="Crew B")
    t1 = import_transport(org, pat["id"], "V3", loaded_miles=5.0, emergency_indicator=True)
    t2 = import_transport(org, pat["id"], "V4", loaded_miles=5.0, emergency_indicator=True)
    create_assignment(org, t1["id"], veh["id"], crewA["id"],
                      "2026-06-09T09:00:00.000Z", "2026-06-09T10:00:00.000Z")
    # second starts 10:31, strictly past the buffered edge (10:00 + 30min = 10:30) -> allowed
    resp = api.create_unit_assignment(
        F.create_unit_assignment_payload(t2["id"], veh["id"], crewB["id"],
                                         "2026-06-09T10:31:00.000Z", "2026-06-09T11:00:00.000Z"),
        org["dispatcher_h"])
    data = validate_success(resp, expected_status=201)
    assert data["vehicle_id"] == veh["id"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap / crew_half_open_interval_back_to_back_allowed
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_crew_back_to_back_assignment_allowed(api):
    """PRD §3.2: "The crew overlap check treats each assignment as occupying a
    half-open interval from `window_start_iso` up to but not including
    `window_end_iso`, with no buffer ... so that a back-to-back assignment whose start
    equals a prior assignment's end is permitted."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_interval_back_to_back_allowed
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    veh1 = create_vehicle(org, unit_call_sign="Medic-1", turnaround_minutes=30)
    veh2 = create_vehicle(org, unit_call_sign="Medic-2", turnaround_minutes=30)
    crew = create_crew(org, "PARAMEDIC", full_name="Solo Crew")
    t1 = import_transport(org, pat["id"], "C1", loaded_miles=5.0, emergency_indicator=True)
    t2 = import_transport(org, pat["id"], "C2", loaded_miles=5.0, emergency_indicator=True)
    create_assignment(org, t1["id"], veh1["id"], crew["id"],
                      "2026-06-09T09:00:00.000Z", "2026-06-09T10:00:00.000Z")
    # second starts exactly when first ends (10:00 == 10:00), different vehicle -> crew back-to-back OK
    resp = api.create_unit_assignment(
        F.create_unit_assignment_payload(t2["id"], veh2["id"], crew["id"],
                                         "2026-06-09T10:00:00.000Z", "2026-06-09T11:00:00.000Z"),
        org["dispatcher_h"])
    data = validate_success(resp, expected_status=201)
    assert data["crew_member_id"] == crew["id"]


def test_crew_overlapping_interval_rejected(api):
    """PRD §3.2: "the request is rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409) if
    that half-open interval intersects any existing half-open interval for the same
    crew member".

    Design: Difficulty/resource_temporal_overlap/crew_half_open_interval_back_to_back_allowed
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    veh1 = create_vehicle(org, unit_call_sign="Medic-1", turnaround_minutes=30)
    veh2 = create_vehicle(org, unit_call_sign="Medic-2", turnaround_minutes=30)
    crew = create_crew(org, "PARAMEDIC", full_name="Solo Crew")
    t1 = import_transport(org, pat["id"], "C3", loaded_miles=5.0, emergency_indicator=True)
    t2 = import_transport(org, pat["id"], "C4", loaded_miles=5.0, emergency_indicator=True)
    create_assignment(org, t1["id"], veh1["id"], crew["id"],
                      "2026-06-09T09:00:00.000Z", "2026-06-09T10:00:00.000Z")
    # second starts 09:30, inside [09:00, 10:00) -> crew interval intersects
    resp = api.create_unit_assignment(
        F.create_unit_assignment_payload(t2["id"], veh2["id"], crew["id"],
                                         "2026-06-09T09:30:00.000Z", "2026-06-09T10:30:00.000Z"),
        org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)


# ---------------------------------------------------------------------------
# corner / validations  (assignment + import gates)
# ---------------------------------------------------------------------------

def test_invalid_window_rejected(api):
    """PRD §3.2: "The window end must be strictly after the window start; a window
    whose `window_end_iso` is equal to or earlier than its `window_start_iso` is
    rejected with `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/invalid_window_rejected
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    veh = create_vehicle(org, unit_call_sign="Medic-1")
    crew = create_crew(org, "PARAMEDIC")
    t = import_transport(org, pat["id"], "IW1", loaded_miles=10.0, emergency_indicator=True)
    resp = api.create_unit_assignment(
        F.create_unit_assignment_payload(t["id"], veh["id"], crew["id"],
                                         "2026-06-11T09:00:00.000Z", "2026-06-11T09:00:00.000Z"),
        org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_out_of_service_vehicle_rejected(api):
    """PRD §3.2: "The assigned vehicle must be `IN_SERVICE` and the assigned crew
    member must be `ACTIVE`; otherwise the request is rejected with
    `ERR_RESOURCE_OUT_OF_SERVICE` (HTTP 409)."

    Design: Corner/validations/out_of_service_vehicle_rejected
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    veh = create_vehicle(org, unit_call_sign="Medic-9")
    get_success_data(api.vehicle_out_of_service(veh["id"], org["admin_h"]))
    crew = create_crew(org, "PARAMEDIC")
    t = import_transport(org, pat["id"], "OOS1", loaded_miles=10.0, emergency_indicator=True)
    resp = api.create_unit_assignment(
        F.create_unit_assignment_payload(t["id"], veh["id"], crew["id"],
                                         "2026-06-11T09:00:00.000Z", "2026-06-11T10:00:00.000Z"),
        org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_RESOURCE_OUT_OF_SERVICE.value)


def test_crew_cert_insufficient_rejected(api):
    """PRD §3.2: "When the transport has already been coded to a level of service, the
    crew member's certification must cover that level — an `EMT` may serve only `BLS`
    ... a certification that does not cover the coded level is rejected with
    `ERR_CREW_CERT_INSUFFICIENT` (HTTP 409)."

    Design: Corner/validations/crew_cert_insufficient_rejected
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    veh = create_vehicle(org, unit_call_sign="Medic-1")
    crew = create_crew(org, "EMT", full_name="Junior EMT")
    t = import_and_code(org, pat["id"], "CC1", "ALS2", loaded_miles=10.0, emergency_indicator=True)
    resp = api.create_unit_assignment(
        F.create_unit_assignment_payload(t["id"], veh["id"], crew["id"],
                                         "2026-06-11T09:00:00.000Z", "2026-06-11T10:00:00.000Z"),
        org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_CREW_CERT_INSUFFICIENT.value)


def test_duplicate_run_number_rejected(api):
    """PRD §3.3: "The `run_number` must be unique per agency across all transports
    that are not voided; a collision with an existing non-void transport of the same
    agency is rejected with `ERR_DUPLICATE_RUN_NUMBER` (HTTP 409)."

    Design: Corner/validations/duplicate_run_number_rejected
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    import_transport(org, pat["id"], "DUP", loaded_miles=10.0, emergency_indicator=True)
    payload = F.create_transport_payload(org["agency"]["id"], pat["id"], "DUP",
                                         dispatch_iso="2026-06-11T09:00:00.000Z",
                                         loaded_miles=10.0, emergency_indicator=True)
    resp = api.create_transport(payload, org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RUN_NUMBER.value)
