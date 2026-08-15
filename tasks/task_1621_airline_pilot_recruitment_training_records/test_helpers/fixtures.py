"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors.

Identity threading: CheckAirman calls are entity-backed by Instructor and
Pilot calls are entity-backed by Applicant; identity-gated calls always use
make_check_airman_headers(instructor["id"]) / make_pilot_headers(applicant["id"]),
never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLASS_START_CLOCK,
    DEFAULT_CLASS_DATE,
    DEFAULT_MEDICAL_ISSUED_AT,
)
from .factories import (
    create_applicant_payload,
    create_bid_payload,
    create_bid_period_payload,
    create_checkride_payload,
    create_enrollment_payload,
    create_equipment_payload,
    create_flight_activity_payload,
    create_instructor_payload,
    create_medical_certificate_payload,
    create_qualification_payload,
    create_records_request_payload,
    create_simulator_slot_payload,
    create_training_class_payload,
    create_training_event_payload,
)
from .test_users import TEST_USERS, make_check_airman_headers

REC = TEST_USERS["recruiter_headers"]
TC = TEST_USERS["training_coordinator_headers"]
CS = TEST_USERS["crew_scheduler_headers"]
SA = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Logical clock and daily scan
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, SA))


def run_daily_scan() -> dict:
    return get_success_data(api_client.run_daily_scan(SA))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def make_equipment(code=None, sim_rate=45000, ioe_hours=10,
                   landings_required=3) -> dict:
    overrides = {"simulator_cost_per_hour_cents": sim_rate,
                 "ioe_hours_required": ioe_hours}
    if code is not None:
        overrides["code"] = code
        overrides["name"] = f"Fleet {code}"
    if landings_required is not None:
        overrides["landings_required_90d"] = landings_required
    return get_success_data(
        api_client.create_equipment(create_equipment_payload(**overrides), TC))


def make_applicant(email, license_number, full_name="Test Applicant",
                   hours=2000) -> dict:
    """Create an applicant in SCREENING."""
    return get_success_data(api_client.create_applicant(
        create_applicant_payload(full_name=full_name, email=email,
                                 license_number=license_number,
                                 total_flight_hours=hours), REC))


def make_instructor(full_name, instructor_type, daily_max=8) -> dict:
    return get_success_data(api_client.create_instructor(
        create_instructor_payload(full_name=full_name,
                                  instructor_type=instructor_type,
                                  daily_max_sessions=daily_max), TC))


def make_simulator_slot(equipment_id, start_at, end_at) -> dict:
    return get_success_data(api_client.create_simulator_slot(
        create_simulator_slot_payload(equipment_id, start_at, end_at), TC))


# ---------------------------------------------------------------------------
# Tier 2: applicant screening pipeline
# ---------------------------------------------------------------------------

def make_records_request(applicant_id, request_type="PRIA") -> dict:
    return get_success_data(api_client.create_records_request(
        create_records_request_payload(applicant_id, request_type), REC))


def drive_records_request_to_verified(request_id) -> dict:
    """DRAFT -> SENT -> RECEIVED -> VERIFIED. Returns the verified request."""
    get_success_data(api_client.send_records_request(request_id, REC))
    get_success_data(api_client.receive_records_request(
        request_id, {"outcome": "RECEIVED"}, REC))
    return get_success_data(api_client.verify_records_request(request_id, REC))


def issue_first_class_medical(applicant_id, issued_at=DEFAULT_MEDICAL_ISSUED_AT,
                              age=30) -> dict:
    return get_success_data(api_client.create_medical_certificate(
        create_medical_certificate_payload(
            applicant_id, cert_class="FIRST", issued_at=issued_at,
            pilot_age_at_issue=age), CS))


def make_cleared_applicant(email, license_number, full_name="Test Applicant",
                           hours=2000, age=30,
                           medical_issued_at=DEFAULT_MEDICAL_ISSUED_AT) -> dict:
    """Full screening chain: create -> advance -> PRIA request verified ->
    VALID FIRST-class medical -> clear. Returns the CLEARED applicant."""
    ap = make_applicant(email, license_number, full_name=full_name, hours=hours)
    get_success_data(api_client.advance_screening(ap["id"], REC))
    rr = make_records_request(ap["id"], "PRIA")
    drive_records_request_to_verified(rr["id"])
    issue_first_class_medical(ap["id"], issued_at=medical_issued_at, age=age)
    return get_success_data(api_client.clear_applicant(ap["id"], REC))


# ---------------------------------------------------------------------------
# Tier 2: classes and enrollments
# ---------------------------------------------------------------------------

def make_training_class(equipment_id, class_date=DEFAULT_CLASS_DATE,
                        seat_capacity=10, attrition=0.20) -> dict:
    """Create a class (SCHEDULED)."""
    return get_success_data(api_client.create_training_class(
        create_training_class_payload(
            equipment_id, class_date=class_date, seat_capacity=seat_capacity,
            base_attrition_rate=attrition), TC))


def open_class(class_id) -> dict:
    return get_success_data(api_client.open_training_class(class_id, TC))


def make_open_class(equipment_id, class_date=DEFAULT_CLASS_DATE,
                    seat_capacity=10, attrition=0.20) -> dict:
    cls = make_training_class(equipment_id, class_date=class_date,
                              seat_capacity=seat_capacity, attrition=attrition)
    return open_class(cls["id"])


def get_class(class_id) -> dict:
    return get_success_data(api_client.get_training_class(class_id, TC))


def get_class_version(class_id) -> int:
    return get_class(class_id)["version"]


def enroll(class_id, applicant_id, headers=TC):
    """Create an enrollment against the class, reading the current class
    version first so the OCC field is fresh. Returns the TENTATIVE
    enrollment."""
    version = get_class_version(class_id)
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(applicant_id, class_id, version), headers))


def confirm_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.confirm_enrollment(enrollment_id, TC))


def get_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, TC))


def start_class(class_id) -> dict:
    return get_success_data(api_client.start_training_class(class_id, TC))


def start_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.start_enrollment(enrollment_id, TC))


# ---------------------------------------------------------------------------
# Tier 3: full training-pipeline lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_in_progress_enrollment(eq_kwargs=None, ap_kwargs=None,
                                 cls_kwargs=None, class_start_clock=CLASS_START_CLOCK):
    """Cleared applicant + OPEN class + CONFIRMED enrollment, then the clock
    advances to the class date and both class and enrollment start.

    Returns ctx dict: equipment, applicant, training_class, enrollment
    (enrollment IN_PROGRESS at phase GROUND_SCHOOL).
    """
    eq = make_equipment(**(eq_kwargs or {}))
    ap = make_cleared_applicant(**(ap_kwargs or {
        "email": "crew@example.com", "license_number": "LIC-CREW-1"}))
    cls = make_open_class(eq["id"], **(cls_kwargs or {}))
    en = enroll(cls["id"], ap["id"])
    confirm_enrollment(en["id"])
    set_clock(class_start_clock)
    start_class(cls["id"])
    en = start_enrollment(en["id"])
    return {
        "equipment": eq,
        "applicant": get_success_data(api_client.get_applicant(ap["id"], REC)),
        "training_class": get_class(cls["id"]),
        "enrollment": en,
    }


def schedule_event(enrollment_id, instructor_id, phase, event_type,
                   start, end, slot_id=None, headers=TC) -> dict:
    return get_success_data(api_client.create_training_event(
        create_training_event_payload(
            enrollment_id, instructor_id, phase, event_type, start, end,
            simulator_slot_id=slot_id), headers))


def complete_event_at(event_id, score, clock, headers=TC) -> dict:
    """Advance the logical clock to the event's start, then complete it."""
    set_clock(clock)
    return get_success_data(
        api_client.complete_training_event(event_id, {"score": score}, headers))


def pass_milestone(enrollment_id, instructor_id, phase, start, end, score=88,
                   slot_id=None) -> dict:
    """Schedule a MILESTONE event and complete it with a passing score."""
    ev = schedule_event(enrollment_id, instructor_id, phase, "MILESTONE",
                        start, end, slot_id=slot_id)
    return complete_event_at(ev["id"], score, start)


def advance_enrollment_ground_to_simulator(ctx, instructor_id,
                                           start="2026-08-10T10:00:00Z",
                                           end="2026-08-10T12:00:00Z",
                                           score=88) -> dict:
    """Pass a GROUND_SCHOOL milestone so the enrollment's phase advances to
    SIMULATOR. Returns the completed milestone event."""
    ev = pass_milestone(ctx["enrollment"]["id"], instructor_id,
                        "GROUND_SCHOOL", start, end, score=score)
    ctx["enrollment"] = get_enrollment(ctx["enrollment"]["id"])
    return ev


def advance_enrollment_simulator_to_checkride(ctx, instructor_id,
                                              slot_start="2026-08-11T08:00:00Z",
                                              slot_end="2026-08-11T18:00:00Z",
                                              start="2026-08-11T09:00:00Z",
                                              end="2026-08-11T11:00:00Z",
                                              score=86) -> dict:
    """Pass a SIMULATOR milestone (inside a fresh slot) so the phase advances
    to CHECKRIDE. Stores the slot on ctx and returns the event."""
    slot = make_simulator_slot(ctx["equipment"]["id"], slot_start, slot_end)
    ctx["slot"] = slot
    ev = pass_milestone(ctx["enrollment"]["id"], instructor_id, "SIMULATOR",
                        start, end, score=score, slot_id=slot["id"])
    ctx["enrollment"] = get_enrollment(ctx["enrollment"]["id"])
    return ev


def setup_enrollment_at_checkride_phase(eq_kwargs=None, ap_kwargs=None,
                                        cls_kwargs=None,
                                        instructor_name="Kit Air",
                                        instructor_type="CHECK_AIRMAN"):
    """Enrollment IN_PROGRESS at phase CHECKRIDE. The returned ctx carries
    `instructor` — the instructor who taught the milestones (and is therefore
    ineligible to examine this enrollment under segregation of duties)."""
    ctx = setup_in_progress_enrollment(eq_kwargs=eq_kwargs, ap_kwargs=ap_kwargs,
                                       cls_kwargs=cls_kwargs)
    instructor = make_instructor(instructor_name, instructor_type)
    ctx["instructor"] = instructor
    advance_enrollment_ground_to_simulator(ctx, instructor["id"])
    advance_enrollment_simulator_to_checkride(ctx, instructor["id"])
    return ctx


def make_checkride(enrollment_id, check_airman_id,
                   scheduled_at="2026-08-12T09:00:00Z",
                   ride_type="PRACTICAL") -> dict:
    return get_success_data(api_client.create_checkride(
        create_checkride_payload(enrollment_id, check_airman_id, scheduled_at,
                                 ride_type=ride_type), TC))


def record_checkride(checkride_id, outcome, airman_id) -> dict:
    """Record an outcome as the assigned check airman (identity-gated)."""
    return get_success_data(api_client.record_checkride_outcome(
        checkride_id, {"outcome": outcome}, make_check_airman_headers(airman_id)))


def get_checkride(checkride_id) -> dict:
    return get_success_data(api_client.get_checkride(checkride_id, TC))


def setup_enrollment_at_ioe_phase(eq_kwargs=None, ap_kwargs=None,
                                  cls_kwargs=None):
    """Enrollment IN_PROGRESS at phase IOE via a passed PRACTICAL checkride.
    ctx carries `instructor` (taught the milestones) and `examiner` (clean
    check airman who passed the ride)."""
    ctx = setup_enrollment_at_checkride_phase(eq_kwargs=eq_kwargs,
                                              ap_kwargs=ap_kwargs,
                                              cls_kwargs=cls_kwargs)
    examiner = make_instructor("Sam Ride", "CHECK_AIRMAN")
    ctx["examiner"] = examiner
    ck = make_checkride(ctx["enrollment"]["id"], examiner["id"])
    set_clock("2026-08-12T09:00:00Z")
    record_checkride(ck["id"], "PASS", examiner["id"])
    ctx["checkride"] = get_success_data(api_client.get_checkride(ck["id"], TC))
    ctx["enrollment"] = get_enrollment(ctx["enrollment"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: qualifications, currency, and flight activity
# ---------------------------------------------------------------------------

def make_qualification(applicant_id, equipment_id) -> dict:
    return get_success_data(api_client.create_qualification(
        create_qualification_payload(applicant_id, equipment_id), CS))


def get_qualification(qualification_id) -> dict:
    return get_success_data(api_client.get_qualification(qualification_id, CS))


def log_flight_activity(qualification_id, activity_date, landings, hours=2.0,
                        activity_type="REVENUE") -> dict:
    return get_success_data(api_client.create_flight_activity(
        create_flight_activity_payload(qualification_id, activity_date,
                                       landings, hours, activity_type), CS))


# ---------------------------------------------------------------------------
# Tier 4: ledger and footprint reads
# ---------------------------------------------------------------------------

def list_ledger_entries(headers=CS, **params) -> list:
    data, _meta = validate_paginated(api_client.list_cost_ledger(
        headers, params=params or None))
    return data


def get_applicant(applicant_id) -> dict:
    return get_success_data(api_client.get_applicant(applicant_id, REC))


def get_footprint(applicant_id, variant=None) -> dict:
    return get_success_data(
        api_client.get_training_footprint(applicant_id, CS, variant=variant))


# ---------------------------------------------------------------------------
# Tier 4: bid periods and bids
# ---------------------------------------------------------------------------

def make_bid_period(equipment_id, opens_at="2026-07-01T00:00:00Z",
                    closes_at="2026-08-20T00:00:00Z", seats_available=1) -> dict:
    return get_success_data(api_client.create_bid_period(
        create_bid_period_payload(equipment_id, opens_at=opens_at,
                                  closes_at=closes_at,
                                  seats_available=seats_available), CS))


def make_open_bid_period(equipment_id, opens_at="2026-07-01T00:00:00Z",
                         closes_at="2026-08-20T00:00:00Z", seats_available=1,
                         open_clock=None) -> dict:
    """Create a bid period and open it; sets the clock into the window first
    when open_clock is supplied."""
    bp = make_bid_period(equipment_id, opens_at=opens_at, closes_at=closes_at,
                         seats_available=seats_available)
    if open_clock is not None:
        set_clock(open_clock)
    return get_success_data(api_client.open_bid_period(bp["id"], CS))


def submit_bid(bid_period_id, applicant_id, preference_rank=1, headers=CS) -> dict:
    return get_success_data(api_client.create_bid(
        create_bid_payload(bid_period_id, applicant_id, preference_rank),
        headers))


def get_bid(bid_id) -> dict:
    return get_success_data(api_client.get_bid(bid_id, CS))
