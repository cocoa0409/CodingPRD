"""Composite setup helpers.

Every helper builds preconditions from scratch via the public API (each test
runs against a freshly restarted server with an empty database). Setup calls
use get_success_data() so a broken precondition surfaces as a clear
"Setup failed" error naming the step.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_assignment_payload,
    create_course_payload,
    create_credential_payload,
    create_drug_test_payload,
    create_join_booking_payload,
    create_manning_slot_payload,
    create_mariner_payload,
    create_medical_certificate_payload,
    create_rotation_plan_payload,
    create_sea_service_record_payload,
    create_union_hall_payload,
    create_union_registration_payload,
    create_vessel_payload,
    record_drug_result_payload,
    travel_leg_payload,
)
from .test_users import (
    TEST_USERS,
    make_mariner_headers,
    make_union_dispatcher_headers,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
CREWING = TEST_USERS["crewing_headers"]
CAPTAIN = TEST_USERS["port_captain_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_mariner(**overrides) -> dict:
    resp = api_client.create_mariner(create_mariner_payload(**overrides), ADMIN)
    return get_success_data(resp)


def issue_medical_certificate(mariner_id, *, officer_headers=None, **overrides) -> dict:
    resp = api_client.create_medical_certificate(
        mariner_id, create_medical_certificate_payload(**overrides),
        officer_headers or OFFICER)
    return get_success_data(resp)


def issue_credential(mariner_id, *, officer_headers=None, **overrides) -> dict:
    resp = api_client.create_credential(
        mariner_id, create_credential_payload(**overrides),
        officer_headers or OFFICER)
    return get_success_data(resp)


def schedule_drug_test(mariner_id, *, officer_headers=None, **overrides) -> dict:
    resp = api_client.create_drug_test(
        mariner_id, create_drug_test_payload(**overrides),
        officer_headers or OFFICER)
    return get_success_data(resp)


def record_drug_result(mariner_id, test_id, *, officer_headers=None,
                       **overrides) -> dict:
    resp = api_client.record_drug_test_result(
        mariner_id, test_id, record_drug_result_payload(**overrides),
        officer_headers or OFFICER)
    return get_success_data(resp)


def record_negative_drug_test(mariner_id, *, officer_headers=None,
                              collected_date=C.STD_DRUG_COLLECTED,
                              test_type="PRE_EMPLOYMENT") -> dict:
    """Schedule a drug test and record a NEGATIVE result. Returns the record."""
    test = schedule_drug_test(
        mariner_id, officer_headers=officer_headers, test_type=test_type,
        scheduled_date=collected_date)
    return record_drug_result(
        mariner_id, test["id"], officer_headers=officer_headers,
        result="NEGATIVE", collected_date=collected_date)


def create_activated_mariner(*, medical_expiry=C.STD_MEDICAL_EXPIRY,
                             credential_expiry=C.STD_CREDENTIAL_EXPIRY,
                             endorsement_code="DECK_AB",
                             drug_collected=C.STD_DRUG_COLLECTED,
                             **mariner_overrides) -> dict:
    """Mariner + VALID medical + VALID credential + NEGATIVE drug test,
    then activated. Returns the activated Mariner."""
    mariner = create_mariner(**mariner_overrides)
    issue_medical_certificate(mariner["id"], expiry_date=medical_expiry)
    issue_credential(
        mariner["id"], endorsement_code=endorsement_code,
        expiry_date=credential_expiry)
    record_negative_drug_test(mariner["id"], collected_date=drug_collected)
    resp = api_client.activate_mariner(mariner["id"], ADMIN)
    return get_success_data(resp)


def create_vessel(**overrides) -> dict:
    resp = api_client.create_vessel(create_vessel_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_manning_slot(vessel_id, **overrides) -> dict:
    resp = api_client.create_manning_slot(
        vessel_id, create_manning_slot_payload(**overrides), CAPTAIN)
    return get_success_data(resp)


def activate_vessel(vessel_id) -> dict:
    return get_success_data(api_client.activate_vessel(vessel_id, ADMIN))


def get_vessel(vessel_id) -> dict:
    return get_success_data(api_client.get_vessel(vessel_id, ADMIN))


def create_rotation_plan(vessel_id, *, vessel_version=None, **overrides) -> dict:
    """Create a rotation plan. Fetches the vessel's current version for the
    OCC guard when not supplied."""
    if vessel_version is None:
        vessel_version = get_vessel(vessel_id)["version"]
    resp = api_client.create_rotation_plan(
        vessel_id,
        create_rotation_plan_payload(vessel_version, **overrides),
        CREWING)
    return get_success_data(resp)


def setup_active_vessel_with_slot(*, slot_overrides=None, plan_overrides=None,
                                  with_rotation_plan=True,
                                  vessel_overrides=None) -> dict:
    """Vessel + one manning slot + ACTIVE (+ default rotation plan).
    Returns {"vessel": ..., "slot": ..., "plan": ...|None}."""
    vessel = create_vessel(**(vessel_overrides or {}))
    slot = create_manning_slot(vessel["id"], **(slot_overrides or {}))
    vessel = activate_vessel(vessel["id"])
    plan = None
    if with_rotation_plan:
        plan = create_rotation_plan(vessel["id"], **(plan_overrides or {}))
    return {"vessel": vessel, "slot": slot, "plan": plan}


def setup_crewing_scenario(*, mariner_overrides=None, slot_overrides=None,
                           plan_overrides=None) -> dict:
    """Activated CLEAR mariner + ACTIVE vessel + one slot + ACTIVE rotation
    plan. Returns {"mariner": ..., "vessel": ..., "slot": ..., "plan": ...}."""
    mariner = create_activated_mariner(**(mariner_overrides or {}))
    env = setup_active_vessel_with_slot(
        slot_overrides=slot_overrides, plan_overrides=plan_overrides)
    return {"mariner": mariner, **env}


# ---------------------------------------------------------------------------
# Tier 2: assignments
# ---------------------------------------------------------------------------

def propose_assignment(mariner_id, slot_id, *, headers=None, **overrides) -> dict:
    resp = api_client.create_assignment(
        create_assignment_payload(mariner_id, slot_id, **overrides),
        headers or CREWING)
    return get_success_data(resp)


def confirm_assignment(assignment_id, *, headers=None) -> dict:
    return get_success_data(
        api_client.confirm_assignment(assignment_id, headers or CREWING))


def setup_confirmed_assignment(*, sign_on=C.STD_SIGN_ON,
                               relief=C.STD_PLANNED_RELIEF,
                               local_join=True, scenario=None,
                               assignment_overrides=None) -> dict:
    """Crewing scenario + one CONFIRMED assignment.
    Returns {"mariner","vessel","slot","plan","assignment"}."""
    ctx = scenario or setup_crewing_scenario()
    payload_overrides = {
        "sign_on_date": sign_on, "planned_relief_date": relief,
        "local_join": local_join,
    }
    payload_overrides.update(assignment_overrides or {})
    assignment = propose_assignment(ctx["mariner"]["id"], ctx["slot"]["id"],
                                    **payload_overrides)
    assignment = confirm_assignment(assignment["id"])
    return {**ctx, "assignment": assignment}


def setup_onboard_assignment(*, sign_on=C.STD_SIGN_ON,
                             relief=C.STD_PLANNED_RELIEF,
                             local_join=True, scenario=None) -> dict:
    """CONFIRMED assignment signed on at the sign_on instant (clock advanced).
    Returns {"mariner","vessel","slot","plan","assignment"} with the
    assignment in ONBOARD."""
    ctx = setup_confirmed_assignment(
        sign_on=sign_on, relief=relief, local_join=local_join,
        scenario=scenario)
    set_clock(sign_on)
    assignment = get_success_data(
        api_client.sign_on_assignment(ctx["assignment"]["id"], CREWING))
    return {**ctx, "assignment": assignment}


def setup_relief_pair(*, relief_sign_on="2026-11-08T00:00:00Z",
                      relief_end="2027-02-08T00:00:00Z") -> dict:
    """M1 ONBOARD on the slot; M2 CONFIRMED incoming relief on the same slot
    (2-day handover within the default 3-day allowance, local join).
    Returns {"outgoing","incoming","vessel","slot","plan","m1","m2"}."""
    ctx = setup_onboard_assignment()
    m2 = create_activated_mariner()
    incoming = propose_assignment(
        m2["id"], ctx["slot"]["id"],
        sign_on_date=relief_sign_on, planned_relief_date=relief_end,
        local_join=True, relief_of_assignment_id=ctx["assignment"]["id"])
    incoming = confirm_assignment(incoming["id"])
    return {
        "outgoing": ctx["assignment"], "incoming": incoming,
        "vessel": ctx["vessel"], "slot": ctx["slot"], "plan": ctx["plan"],
        "m1": ctx["mariner"], "m2": m2,
    }


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: travel bookings
# ---------------------------------------------------------------------------

def create_join_booking(assignment_id, *, legs=None, payer="VESSEL_OWNER") -> dict:
    resp = api_client.create_travel_booking(
        assignment_id, create_join_booking_payload(legs=legs, payer=payer),
        CREWING)
    return get_success_data(resp)


def book_and_ticket(assignment_id, booking_id) -> dict:
    get_success_data(
        api_client.book_travel_booking(assignment_id, booking_id, CREWING))
    return get_success_data(
        api_client.ticket_travel_booking(assignment_id, booking_id, CREWING))


def create_ticketed_join_booking(assignment_id, *, legs=None,
                                 payer="VESSEL_OWNER") -> dict:
    booking = create_join_booking(assignment_id, legs=legs, payer=payer)
    return book_and_ticket(assignment_id, booking["id"])


def list_bookings(assignment_id, **params) -> list:
    resp = api_client.list_travel_bookings(assignment_id, CREWING,
                                           params=params or None)
    return get_success_data(resp)


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, CREWING))


# ---------------------------------------------------------------------------
# Tier 4: training courses, enrollments, budgets
# ---------------------------------------------------------------------------

def create_course(**overrides) -> dict:
    resp = api_client.create_course(create_course_payload(**overrides), ADMIN)
    return get_success_data(resp)


def request_enrollment(course_id, mariner_id) -> dict:
    resp = api_client.request_enrollment(
        course_id, make_mariner_headers(mariner_id))
    return get_success_data(resp)


def approve_enrollment(enrollment_id, *, approver_id="cm-100") -> dict:
    from .test_users import make_crewing_headers
    resp = api_client.approve_enrollment(
        enrollment_id, make_crewing_headers(approver_id))
    return get_success_data(resp)


def enroll_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.enroll_enrollment(enrollment_id, ADMIN))


def setup_enrolled_enrollment(*, course_overrides=None, mariner_overrides=None,
                              approver_id="cm-100") -> dict:
    """Activated mariner + course + enrollment walked to ENROLLED.
    Returns {"mariner","course","enrollment"}."""
    mariner = create_activated_mariner(**(mariner_overrides or {}))
    course = create_course(**(course_overrides or {}))
    enrollment = request_enrollment(course["id"], mariner["id"])
    enrollment = approve_enrollment(enrollment["id"], approver_id=approver_id)
    enrollment = enroll_enrollment(enrollment["id"])
    return {"mariner": mariner, "course": course, "enrollment": enrollment}


def get_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, ADMIN))


def get_course(course_id) -> dict:
    return get_success_data(api_client.get_course(course_id, ADMIN))


def budget_rows(mariner_id) -> list:
    return get_success_data(api_client.list_training_budgets(mariner_id, ADMIN))


def first_budget_row(mariner_id) -> dict:
    rows = budget_rows(mariner_id)
    assert len(rows) == 1, f"expected exactly one budget row, got {len(rows)}"
    return rows[0]


def get_mariner(mariner_id) -> dict:
    return get_success_data(api_client.get_mariner(mariner_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 5: union halls and registrations
# ---------------------------------------------------------------------------

def create_union_hall(**overrides) -> dict:
    resp = api_client.create_union_hall(create_union_hall_payload(**overrides),
                                        ADMIN)
    return get_success_data(resp)


def register_union_mariner(hall_id, mariner_id, **overrides) -> dict:
    resp = api_client.create_union_registration(
        hall_id, create_union_registration_payload(mariner_id, **overrides),
        make_union_dispatcher_headers(hall_id))
    return get_success_data(resp)


def setup_union_mariner(*, seniority_date="2026-01-01T00:00:00Z") -> dict:
    """Union hall + activated UNION_HALL mariner + REGISTERED registration.
    Returns {"hall","mariner","registration"}."""
    hall = create_union_hall()
    mariner = create_activated_mariner(hire_channel="UNION_HALL")
    registration = register_union_mariner(
        hall["id"], mariner["id"], seniority_date=seniority_date)
    return {"hall": hall, "mariner": mariner, "registration": registration}


# ---------------------------------------------------------------------------
# Sea service
# ---------------------------------------------------------------------------

def create_sea_record(mariner_id, vessel_id, *, recorder_headers=None,
                      **overrides) -> dict:
    resp = api_client.create_sea_service_record(
        mariner_id, create_sea_service_record_payload(vessel_id, **overrides),
        recorder_headers or make_mariner_headers(mariner_id))
    return get_success_data(resp)


def submit_sea_record(mariner_id, record_id, *, headers=None) -> dict:
    resp = api_client.submit_sea_service_record(
        mariner_id, record_id, headers or make_mariner_headers(mariner_id))
    return get_success_data(resp)


def verify_sea_record(mariner_id, record_id, *, officer_headers=None) -> dict:
    resp = api_client.verify_sea_service_record(
        mariner_id, record_id, officer_headers or OFFICER)
    return get_success_data(resp)


def create_verified_sea_record(mariner_id, vessel_id, **overrides) -> dict:
    record = create_sea_record(mariner_id, vessel_id, **overrides)
    submit_sea_record(mariner_id, record["id"])
    return verify_sea_record(mariner_id, record["id"])
