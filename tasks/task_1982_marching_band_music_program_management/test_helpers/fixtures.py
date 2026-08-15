"""Composite setup helpers.

Each helper builds a multi-step precondition through PRD-declared endpoints so
tests can focus on assertions. Setup calls use get_success_data() so failures
surface as clear "Setup failed" errors. Every test starts against an empty
database with the logical clock at the PRD §2.6 startup default of
2026-08-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    advance_program_payload,
    challenge_payload,
    cleaning_batch_item_payload,
    close_fundraiser_payload,
    complete_maintenance_payload,
    create_arrangement_payload,
    create_audition_entry_payload,
    create_audition_payload,
    create_cleaning_batch_payload,
    create_event_payload,
    create_fundraiser_payload,
    create_instrument_assignment_payload,
    create_instrument_payload,
    create_payment_payload,
    create_program_payload,
    create_student_payload,
    create_trip_enrollment_payload,
    create_trip_payload,
    create_truck_charter_payload,
    create_uniform_assignment_payload,
    create_uniform_payload,
    judge_score_payload,
    publish_placements_payload,
    return_assignment_payload,
    return_uniform_assignment_payload,
    set_clock_payload,
    truck_load_payload,
)
from .test_users import (
    ASSISTANT_HEADERS,
    DIRECTOR_HEADERS,
    EQUIPMENT_HEADERS,
    READER_HEADERS,
    TREASURER_HEADERS,
    make_director_headers,
)

DIRECTOR = DIRECTOR_HEADERS
ASSISTANT = ASSISTANT_HEADERS
TREASURER = TREASURER_HEADERS
EQUIPMENT = EQUIPMENT_HEADERS
READER = READER_HEADERS

DEFAULT_DEPARTURE = "2026-09-15T06:00:00Z"


# --- Tier 1: state progression ------------------------------------------------

def create_program(**overrides):
    """Create a program (starts SETUP per PRD §3.1). Returns program data."""
    resp = api_client.create_program(create_program_payload(**overrides), DIRECTOR)
    return get_success_data(resp, 201)


def create_open_program(**overrides):
    """Create a program and advance it to ENROLLMENT_OPEN. Returns refreshed data."""
    program = create_program(**overrides)
    resp = api_client.advance_program(
        program["id"], advance_program_payload("ENROLLMENT_OPEN"), DIRECTOR)
    get_success_data(resp)
    return get_success_data(api_client.get_program(program["id"], READER))


def create_student(program_id, **overrides):
    """Register a student (starts APPLIED per PRD §3.2). Returns student data."""
    resp = api_client.create_student(create_student_payload(program_id, **overrides),
                                     DIRECTOR)
    return get_success_data(resp, 201)


def create_enrolled_student(program_id, **overrides):
    """Register + enroll a student (APPLIED -> ENROLLED). Returns student data."""
    student = create_student(program_id, **overrides)
    resp = api_client.enroll_student(student["id"], DIRECTOR)
    get_success_data(resp)
    return get_success_data(api_client.get_student(student["id"], READER))


def suspend_student(student_id):
    resp = api_client.suspend_student(student_id, DIRECTOR)
    return get_success_data(resp)


def advance_clock(to_iso8601):
    """Advance the logical clock (PRD §2.6). Returns {current_utc}."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), DIRECTOR)
    return get_success_data(resp)


# --- Tier 2: instruments / uniforms -------------------------------------------

def create_instrument(program_id, **overrides):
    resp = api_client.create_instrument(
        create_instrument_payload(program_id, **overrides), EQUIPMENT)
    return get_success_data(resp, 201)


def create_uniform(program_id, **overrides):
    resp = api_client.create_uniform(create_uniform_payload(program_id, **overrides),
                                     EQUIPMENT)
    return get_success_data(resp, 201)


def issue_uniform(student_id, uniform_id):
    """Issue a garment; assignment starts ISSUED, garment -> ISSUED (PRD §3.4)."""
    resp = api_client.create_uniform_assignment(
        create_uniform_assignment_payload(student_id, uniform_id), EQUIPMENT)
    return get_success_data(resp, 201)


def return_uniform(assignment_id, soiling_level="NORMAL"):
    resp = api_client.return_uniform_assignment(
        assignment_id, return_uniform_assignment_payload(soiling_level), EQUIPMENT)
    return get_success_data(resp)


def create_issued_and_returned_garment(program_id, student_id, garment_type,
                                       size_label="M", soiling_level="NORMAL"):
    """Create a garment, issue it, return it with a soiling level.
    Returns (uniform, uniform_assignment) with the garment RETURNED_DIRTY."""
    uniform = create_uniform(program_id, garment_type=garment_type,
                             size_label=size_label)
    assignment = issue_uniform(student_id, uniform["id"])
    return_uniform(assignment["id"], soiling_level)
    return uniform, assignment


def create_cleaning_batch(program_id):
    resp = api_client.create_cleaning_batch(create_cleaning_batch_payload(program_id),
                                            EQUIPMENT)
    return get_success_data(resp, 201)


def attach_to_batch(batch_id, uniform_id):
    resp = api_client.add_cleaning_batch_item(
        batch_id, cleaning_batch_item_payload(uniform_id), EQUIPMENT)
    return get_success_data(resp, 201)


def send_batch(batch_id):
    resp = api_client.send_cleaning_batch(batch_id, EQUIPMENT)
    return get_success_data(resp)


def receive_batch(batch_id):
    resp = api_client.receive_cleaning_batch(batch_id, EQUIPMENT)
    return get_success_data(resp)


def setup_sent_batch(program_id, uniform_ids):
    """OPEN batch + attach garments + send. Returns sent batch data."""
    batch = create_cleaning_batch(program_id)
    for uniform_id in uniform_ids:
        attach_to_batch(batch["id"], uniform_id)
    return send_batch(batch["id"])


# --- Tier 2: instrument assignments -------------------------------------------

def checkout_instrument(student_id, instrument_id, due_date="2026-08-20T00:00:00Z"):
    """Check out an instrument; assignment starts ACTIVE, fee posted (PRD §3.3)."""
    resp = api_client.create_instrument_assignment(
        create_instrument_assignment_payload(student_id, instrument_id, due_date),
        EQUIPMENT)
    return get_success_data(resp, 201)


def setup_assignment(program_id=None, due_date="2026-08-20T00:00:00Z",
                     instrument_overrides=None, student_overrides=None):
    """Enrolled student + available instrument + ACTIVE assignment.
    Returns (program, student, instrument, assignment)."""
    if program_id is None:
        program = create_open_program()
        program_id = program["id"]
    else:
        program = get_success_data(api_client.get_program(program_id, READER))
    student = create_enrolled_student(program_id, **(student_overrides or {}))
    instrument = create_instrument(program_id, **(instrument_overrides or {}))
    assignment = checkout_instrument(student["id"], instrument["id"], due_date)
    return program, student, instrument, assignment


def get_instrument(instrument_id):
    return get_success_data(api_client.get_instrument(instrument_id, READER))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_instrument_assignment(assignment_id, READER))


def get_student(student_id):
    return get_success_data(api_client.get_student(student_id, READER))


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, READER))


def get_trip_enrollment(enrollment_id):
    return get_success_data(api_client.get_trip_enrollment(enrollment_id, READER))


def get_trip(trip_id):
    return get_success_data(api_client.get_trip(trip_id, READER))


def get_event(event_id):
    return get_success_data(api_client.get_event(event_id, READER))


# --- Tier 2/3: events, trips, enrollments -------------------------------------

def create_event(program_id, **overrides):
    resp = api_client.create_event(create_event_payload(program_id, **overrides),
                                   DIRECTOR)
    return get_success_data(resp, 201)


def create_trip(event_id, expected_event_version=None, **overrides):
    """Plan a trip against an event (OCC per PRD §2.10). When the expected event
    version is not supplied, the event is re-read for its current version."""
    if expected_event_version is None:
        expected_event_version = get_event(event_id)["version"]
    resp = api_client.create_trip(
        create_trip_payload(event_id, expected_event_version, **overrides), DIRECTOR)
    return get_success_data(resp, 201)


def setup_trip_with_open_roster(program_id=None, capacity=5,
                                estimated_cost_cents=10000,
                                departure_at=DEFAULT_DEPARTURE,
                                event_overrides=None, program_overrides=None):
    """Open program + outdoor event + trip with roster open.
    Returns (program, event, trip)."""
    if program_id is None:
        program = create_open_program(**(program_overrides or {}))
        program_id = program["id"]
    else:
        program = get_program(program_id)
    overrides = {
        "event_type": "COMPETITION",
        "starts_at": "2026-09-15T15:00:00Z",
        "ends_at": "2026-09-15T21:00:00Z",
        "is_outdoor": True,
    }
    overrides.update(event_overrides or {})
    event = create_event(program_id, **overrides)
    trip = create_trip(event["id"], event["version"], capacity=capacity,
                       estimated_cost_cents=estimated_cost_cents,
                       departure_at=departure_at)
    get_success_data(api_client.open_trip_roster(trip["id"], DIRECTOR))
    return program, event, get_trip(trip["id"])


def enroll_in_trip(trip_id, student_id, headers=None):
    resp = api_client.create_trip_enrollment(
        create_trip_enrollment_payload(trip_id, student_id), headers or DIRECTOR)
    return get_success_data(resp, 201)


def post_payment(student_id, kind, amount_cents, **extra):
    resp = api_client.create_payment(
        create_payment_payload(student_id, kind, amount_cents, **extra), TREASURER)
    return get_success_data(resp, 201)


def pay_enrollment_in_full(enrollment):
    """Pay exactly the enrollment's current amount_due_cents (PRD §3.6)."""
    return post_payment(enrollment["student_id"], "PAYMENT",
                        enrollment["amount_due_cents"],
                        trip_enrollment_id= enrollment["id"])


def confirm_enrollment(enrollment_id):
    resp = api_client.confirm_trip_enrollment(enrollment_id, DIRECTOR)
    return get_success_data(resp)


def setup_confirmed_enrollment(program_id=None, capacity=5,
                               estimated_cost_cents=5000,
                               departure_at=DEFAULT_DEPARTURE,
                               program_overrides=None):
    """Open trip + one enrolled student, paid in full and CONFIRMED.
    Returns (program, event, trip, student, enrollment)."""
    program, event, trip = setup_trip_with_open_roster(
        program_id=program_id, capacity=capacity,
        estimated_cost_cents=estimated_cost_cents, departure_at=departure_at,
        program_overrides=program_overrides)
    student = create_enrolled_student(program["id"])
    enrollment = enroll_in_trip(trip["id"], student["id"])
    pay_enrollment_in_full(enrollment)
    enrollment = confirm_enrollment(enrollment["id"])
    return program, event, trip, student, enrollment


def create_charter(program_id, event_id=None, **overrides):
    if event_id is not None:
        overrides["event_id"] = event_id
    resp = api_client.create_truck_charter(
        create_truck_charter_payload(program_id, **overrides), EQUIPMENT)
    return get_success_data(resp, 201)


def setup_locked_trip(program_id=None, capacity=5, estimated_cost_cents=5000,
                      departure_at=DEFAULT_DEPARTURE, program_overrides=None):
    """Confirmed enrollment + linked truck charter + roster locked.
    Returns (program, event, trip, student, enrollment)."""
    program, event, trip, student, enrollment = setup_confirmed_enrollment(
        program_id=program_id, capacity=capacity,
        estimated_cost_cents=estimated_cost_cents, departure_at=departure_at,
        program_overrides=program_overrides)
    create_charter(program["id"], event["id"])
    get_success_data(api_client.lock_trip_roster(trip["id"], DIRECTOR))
    return program, event, get_trip(trip["id"]), student, enrollment


def setup_finalized_trip(actual_cost_cents=5000, **kwargs):
    """Full trip lifecycle through FINALIZED (PRD §3.6 pinned order).
    Returns (program, event, trip, student, enrollment)."""
    program, event, trip, student, enrollment = setup_locked_trip(**kwargs)
    trip = get_success_data(
        api_client.finalize_trip(trip["id"], {"actual_cost_cents": actual_cost_cents},
                                 TREASURER))
    enrollment = get_trip_enrollment(enrollment["id"])
    return program, event, trip, student, enrollment


# --- Tier 3/4: arrangements ----------------------------------------------------

def create_arrangement(program_id, headers=None, **overrides):
    """Request a quote; starts QUOTED with creator recorded (PRD §3.5)."""
    resp = api_client.create_arrangement(
        create_arrangement_payload(program_id, **overrides), headers or DIRECTOR)
    return get_success_data(resp, 201)


def approve_arrangement(arrangement_id, headers):
    resp = api_client.approve_arrangement(arrangement_id, headers)
    return get_success_data(resp)


def purchase_arrangement(arrangement_id):
    resp = api_client.purchase_arrangement(arrangement_id, TREASURER)
    return get_success_data(resp)


def setup_licensed_arrangement(program_id=None, cost_cents=30000, **overrides):
    """Quote (dir-1) -> approve (dir-2) -> purchase. Returns (program, arrangement)."""
    if program_id is None:
        program = create_open_program()
        program_id = program["id"]
    else:
        program = get_program(program_id)
    arrangement = create_arrangement(program_id, make_director_headers("dir-1"),
                                     cost_cents=cost_cents, **overrides)
    arrangement = approve_arrangement(arrangement["id"],
                                      make_director_headers("dir-2"))
    arrangement = purchase_arrangement(arrangement_id=arrangement["id"])
    return program, arrangement


# --- Tier 3/4: auditions -------------------------------------------------------

def create_audition(program_id, **overrides):
    resp = api_client.create_audition(create_audition_payload(program_id, **overrides),
                                      DIRECTOR)
    return get_success_data(resp, 201)


def create_audition_entry(audition_id, student_id):
    resp = api_client.create_audition_entry(
        create_audition_entry_payload(audition_id, student_id), DIRECTOR)
    return get_success_data(resp, 201)


def submit_score(entry_id, judge_id, musicianship, marching, leadership):
    resp = api_client.submit_judge_scores(
        entry_id, judge_score_payload(judge_id, musicianship, marching, leadership),
        DIRECTOR)
    return get_success_data(resp, 201)


def finalize_scores(audition_id):
    resp = api_client.finalize_audition_scores(audition_id, DIRECTOR)
    return get_success_data(resp)


def publish_placements(audition_id, expected_audition_version):
    resp = api_client.publish_audition_placements(
        audition_id, publish_placements_payload(expected_audition_version), DIRECTOR)
    return get_success_data(resp)


def setup_scored_audition(entry_score_sets, chair_capacity=1, section="BRASS",
                          scoring_mode="RAW_WEIGHTED", program_id=None):
    """Audition with one entry per score-set, every entry scored, scores finalized.

    entry_score_sets: list of lists of (judge_id, musicianship, marching,
    leadership) tuples — one inner list per entry, created in order.
    Returns (program, audition, entries) with audition SCORES_FINALIZED.
    """
    if program_id is None:
        program = create_open_program(scoring_mode=scoring_mode)
        program_id = program["id"]
    else:
        program = get_program(program_id)
    audition = create_audition(program_id, section=section,
                               chair_capacity=chair_capacity)
    entries = []
    for score_set in entry_score_sets:
        student = create_enrolled_student(program_id, section=section)
        entry = create_audition_entry(audition["id"], student["id"])
        for judge_id, musicianship, marching, leadership in score_set:
            submit_score(entry["id"], judge_id, musicianship, marching, leadership)
        entries.append(entry)
    audition = finalize_scores(audition["id"])
    entries = [get_success_data(api_client.get_audition_entry(e["id"], READER))
               for e in entries]
    return program, audition, entries


def setup_published_audition(entry_score_sets, chair_capacity=1, section="BRASS",
                             scoring_mode="RAW_WEIGHTED"):
    """Scored audition + placements published. Returns (program, audition, entries)."""
    program, audition, entries = setup_scored_audition(
        entry_score_sets, chair_capacity=chair_capacity, section=section,
        scoring_mode=scoring_mode)
    audition = publish_placements(audition["id"], audition["version"])
    return program, audition, entries


def list_chair_placements(**params):
    data, _meta = validate_paginated(api_client.list_chair_placements(READER,
                                                                      params=params))
    return data


# --- Tier 2: fundraisers --------------------------------------------------------

def create_fundraiser(program_id, **overrides):
    resp = api_client.create_fundraiser(
        create_fundraiser_payload(program_id, **overrides), TREASURER)
    return get_success_data(resp, 201)


def close_fundraiser(fundraiser_id, raised_cents, participant_hours):
    resp = api_client.close_fundraiser(
        fundraiser_id, close_fundraiser_payload(raised_cents, participant_hours),
        TREASURER)
    return get_success_data(resp)
