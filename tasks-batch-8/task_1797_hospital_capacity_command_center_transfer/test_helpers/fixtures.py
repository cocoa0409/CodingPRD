"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: AcceptingPhysician calls are entity-backed by Physician.
Every scenario dict carries per-instance physician headers built from the real
Physician ids via make_accepting_physician_headers(); ownership-gated
consult-response calls never fall back to the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import T_0000
from .factories import (
    create_admission_payload,
    create_bed_payload,
    create_boarding_record_payload,
    create_capacity_forecast_payload,
    create_diversion_payload,
    create_facility_payload,
    create_physician_payload,
    create_transfer_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_accepting_physician_headers,
    make_bed_manager_headers,
    make_coordinator_headers,
)

ADMIN = TEST_USERS["sysadmin_headers"]
BED_MGR = TEST_USERS["bed_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["house_supervisor_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]
ANY_HEADERS = TEST_USERS["coordinator_headers"]  # any authenticated role may read


# ---------------------------------------------------------------------------
# Tier 0: clock and single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=T_0000):
    """Drive the logical clock to an explicit instant. Returns the payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweep():
    """Run one housekeeping sweep; returns the sweep report payload."""
    return validate_success(api_client.run_sweep(ADMIN), 200)


def create_facility(name="Command Center Facility", region="R1"):
    return get_success_data(api_client.create_facility(
        create_facility_payload(name=name, region=region), ADMIN))


def add_bed(facility_id, unit="M-1", label="B1", service="MEDICAL",
            max_acuity="ACUITY_3_MEDICAL_SURGICAL", isolation_capability="NONE",
            **extra):
    payload = create_bed_payload(
        unit=unit, label=label, service=service, max_acuity=max_acuity,
        isolation_capability=isolation_capability, **extra)
    return get_success_data(api_client.create_bed(facility_id, payload, ADMIN))


def add_physician(facility_id, full_name="Dr Test", services=("CARDIAC",),
                  status=None):
    payload = create_physician_payload(full_name=full_name, services=list(services))
    if status is not None:
        payload["status"] = status
    return get_success_data(api_client.create_physician(facility_id, payload, ADMIN))


def create_admission(facility_id, bed_id, patient_ref="P-1",
                     acuity="ACUITY_3_MEDICAL_SURGICAL", isolation_need="NONE",
                     service="MEDICAL"):
    payload = create_admission_payload(
        bed_id, patient_ref=patient_ref, acuity=acuity,
        isolation_need=isolation_need, service=service)
    return get_success_data(api_client.create_admission(facility_id, payload, BED_MGR))


def create_transfer_request(facility_id, patient_ref="PT-1",
                            acuity="ACUITY_3_MEDICAL_SURGICAL",
                            isolation_need="NONE", service="CARDIAC",
                            priority="URGENT", coordinator_id="coord_1",
                            **extra):
    """Create an INTAKE transfer request as a coordinator. Returns the request."""
    payload = create_transfer_request_payload(
        patient_ref=patient_ref, acuity=acuity, isolation_need=isolation_need,
        service=service, priority=priority, **extra)
    headers = make_coordinator_headers(coordinator_id)
    return get_success_data(
        api_client.create_transfer_request(facility_id, payload, headers))


def dispatch_consult(request_id, physician_id, coordinator_id="coord_1"):
    """Dispatch a consult to a physician. Returns the CONSULT_PENDING request."""
    headers = make_coordinator_headers(coordinator_id)
    return get_success_data(api_client.dispatch_consult(
        request_id, {"physician_id": physician_id}, headers))


def respond_consult(request_id, physician_id, decision="ACCEPT",
                    decline_reason=None):
    """Respond to a consult as the consulted (entity-backed) physician."""
    payload = {"decision": decision}
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    headers = make_accepting_physician_headers(physician_id)
    return get_success_data(api_client.consult_response(request_id, payload, headers))


def place_hold(request_id, bed_id=None, ttl_minutes=None, coordinator_id="coord_1"):
    """Place a bed hold for an ACCEPTED request. Returns the BedHold."""
    payload: dict = {}
    if bed_id is not None:
        payload["bed_id"] = bed_id
    if ttl_minutes is not None:
        payload["ttl_minutes"] = ttl_minutes
    headers = make_coordinator_headers(coordinator_id)
    return get_success_data(
        api_client.create_bed_hold(request_id, payload, headers))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_accepted_request(facility_id, physician_id,
                            patient_ref="PT-ACC",
                            acuity="ACUITY_3_MEDICAL_SURGICAL",
                            isolation_need="NONE", service="CARDIAC",
                            priority="URGENT", coordinator_id="coord_1",
                            **extra):
    """Walk a transfer request INTAKE -> CONSULT_PENDING -> ACCEPTED.

    Returns the request in ACCEPTED status.
    """
    tr = create_transfer_request(
        facility_id, patient_ref=patient_ref, acuity=acuity,
        isolation_need=isolation_need, service=service, priority=priority,
        coordinator_id=coordinator_id, **extra)
    dispatch_consult(tr["id"], physician_id, coordinator_id=coordinator_id)
    return respond_consult(tr["id"], physician_id, decision="ACCEPT")


def create_request_with_hold(facility_id, physician_id, bed_id,
                             patient_ref="PT-H", ttl_minutes=None,
                             acuity="ACUITY_1_CRITICAL", isolation_need="NONE",
                             service="CARDIAC", priority="URGENT",
                             coordinator_id="coord_1", **extra):
    """Walk a request through to HOLD_PLACED with an ACTIVE hold on bed_id.

    Returns (request, hold).
    """
    tr = create_accepted_request(
        facility_id, physician_id, patient_ref=patient_ref, acuity=acuity,
        isolation_need=isolation_need, service=service, priority=priority,
        coordinator_id=coordinator_id, **extra)
    hold = place_hold(tr["id"], bed_id=bed_id, ttl_minutes=ttl_minutes,
                      coordinator_id=coordinator_id)
    tr = get_success_data(api_client.get_transfer_request(tr["id"], ANY_HEADERS))
    return tr, hold


# ---------------------------------------------------------------------------
# Tier 2: hierarchy / scenario bundles
# ---------------------------------------------------------------------------

def setup_facility_with_physician(name="Facility", services=("CARDIAC",)):
    """Facility + one ON_CALL physician credentialed for `services`.

    Returns dict with facility, physician, and the physician's entity-backed
    headers under "physician_headers".
    """
    facility = create_facility(name=name)
    physician = add_physician(facility["id"], services=services)
    return {
        "facility": facility,
        "physician": physician,
        "physician_headers": make_accepting_physician_headers(physician["id"]),
    }


def setup_accepted_request_scenario(name="Facility",
                                    bed_service="CARDIAC",
                                    bed_max_acuity="ACUITY_1_CRITICAL",
                                    bed_isolation="AIRBORNE",
                                    bed_unit="C-1",
                                    request_acuity="ACUITY_1_CRITICAL",
                                    request_isolation="NONE",
                                    request_service="CARDIAC",
                                    request_priority="URGENT"):
    """Facility + physician + one bed + one ACCEPTED request.

    Returns dict: facility, physician, bed, request (ACCEPTED).
    """
    bundle = setup_facility_with_physician(name=name,
                                           services=(request_service,))
    facility = bundle["facility"]
    physician = bundle["physician"]
    bed = add_bed(facility["id"], unit=bed_unit, label="B1",
                  service=bed_service, max_acuity=bed_max_acuity,
                  isolation_capability=bed_isolation)
    request = create_accepted_request(
        facility["id"], physician["id"], acuity=request_acuity,
        isolation_need=request_isolation, service=request_service,
        priority=request_priority)
    return {
        "facility": facility,
        "physician": physician,
        "physician_headers": bundle["physician_headers"],
        "bed": bed,
        "request": request,
    }


def setup_hold_placed_scenario(name="Facility", ttl_minutes=None,
                               bed_turnover_minutes=None):
    """Facility + physician + bed + request walked to HOLD_PLACED.

    Returns dict: facility, physician, bed, request (HOLD_PLACED), hold.
    """
    scenario = setup_accepted_request_scenario(name=name)
    bed_extra = {}
    if bed_turnover_minutes is not None:
        bed_extra["turnover_minutes"] = bed_turnover_minutes
    request = scenario["request"]
    hold = place_hold(request["id"], bed_id=scenario["bed"]["id"],
                      ttl_minutes=ttl_minutes)
    request = get_success_data(
        api_client.get_transfer_request(request["id"], ANY_HEADERS))
    scenario["request"] = request
    scenario["hold"] = hold
    return scenario


def setup_ed_boarding_scenario(name="Boarding Facility", ed_unit="ED-1"):
    """Facility + one ED-unit bed + occupying admission + open boarding record.

    Returns dict: facility, ed_bed, admission, boarding_record.
    """
    facility = create_facility(name=name)
    ed_bed = add_bed(facility["id"], unit=ed_unit, label="E1", service="MEDICAL",
                     max_acuity="ACUITY_3_MEDICAL_SURGICAL",
                     isolation_capability="NONE")
    admission = create_admission(facility["id"], ed_bed["id"],
                                 patient_ref="PB-1", service="MEDICAL")
    record = get_success_data(api_client.create_boarding_record(
        facility["id"], create_boarding_record_payload(admission["id"]), COORD))
    return {
        "facility": facility,
        "ed_bed": ed_bed,
        "admission": admission,
        "boarding_record": record,
    }


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------

def walk_request_to_assigned(facility_id, physician_id, bed_id,
                             coordinator_id="coord_1", **request_kwargs):
    """Walk a request INTAKE -> ... -> ASSIGNED; consumes its hold.

    Returns (request_after_assign, hold, assignment).
    """
    request, hold = create_request_with_hold(
        facility_id, physician_id, bed_id, coordinator_id=coordinator_id,
        **request_kwargs)
    assignment = place_assignment(request, hold, coordinator_id=coordinator_id)
    request = get_success_data(
        api_client.get_transfer_request(request["id"], ANY_HEADERS))
    return request, hold, assignment


def place_assignment(request, hold, coordinator_id="coord_1"):
    """Create a PLACED bed assignment against a HOLD_PLACED request, reading
    the request's current version for the OCC field. Returns the assignment."""
    fresh = get_success_data(
        api_client.get_transfer_request(request["id"], ANY_HEADERS))
    payload = {
        "bed_hold_id": hold["id"],
        "expected_transfer_request_version": fresh["version"],
    }
    return get_success_data(api_client.create_bed_assignment(
        request["id"], payload, make_coordinator_headers(coordinator_id)))


def complete_assignment(assignment_id, completer_id="bm_1"):
    """Complete a PLACED assignment as a BedManager with a distinct user id."""
    return get_success_data(api_client.complete_bed_assignment(
        assignment_id, make_bed_manager_headers(completer_id)))


def walk_request_to_completed(facility_id, physician_id, bed_id,
                              coordinator_id="coord_1", completer_id="bm_1",
                              **request_kwargs):
    """Walk a request through the full pipeline to terminal COMPLETED.

    Returns (request, hold, assignment).
    """
    request, hold, assignment = walk_request_to_assigned(
        facility_id, physician_id, bed_id, coordinator_id=coordinator_id,
        **request_kwargs)
    complete_assignment(assignment["id"], completer_id=completer_id)
    request = get_success_data(
        api_client.get_transfer_request(request["id"], ANY_HEADERS))
    return request, hold, assignment


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# ---------------------------------------------------------------------------

def place_holds_for_n_requests(facility_id, physician_id, bed_ids,
                               coordinator_id="coord_1", patient_prefix="PQ"):
    """Create N ACCEPTED requests and place one hold for each on the matching
    bed. Returns (requests, holds). Used to fill the facility hold quota."""
    requests = []
    holds = []
    for i, bed_id in enumerate(bed_ids, start=1):
        tr, hold = create_request_with_hold(
            facility_id, physician_id, bed_id,
            patient_ref=f"{patient_prefix}{i}", coordinator_id=coordinator_id)
        requests.append(tr)
        holds.append(hold)
    return requests, holds


# ---------------------------------------------------------------------------
# Tier 5: forecast / finalization helpers
# ---------------------------------------------------------------------------

def create_forecast(facility_id, horizon_hours=4):
    return get_success_data(api_client.create_capacity_forecast(
        facility_id, create_capacity_forecast_payload(horizon_hours=horizon_hours),
        PLANNER))


def publish_forecast(forecast_id):
    return get_success_data(api_client.publish_capacity_forecast(
        forecast_id, PLANNER))


def declare_diversion(facility_id, level="FULL", service=None,
                      starts_at="2026-08-01T00:00:00Z",
                      ends_at="2026-08-01T02:00:00Z", supervisor_id="hs_1"):
    payload = create_diversion_payload(level=level, starts_at=starts_at,
                                       ends_at=ends_at)
    if service is not None:
        payload["service"] = service
    from .test_users import make_house_supervisor_headers
    return get_success_data(api_client.create_diversion(
        facility_id, payload, make_house_supervisor_headers(supervisor_id)))
