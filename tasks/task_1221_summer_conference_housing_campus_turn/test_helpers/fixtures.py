"""Composite setup helpers.

Every test starts against an empty database, so these helpers build complete
precondition chains (building release -> group contract -> rooming list ->
confirm -> stays -> billing) out of PRD-declared endpoints only.

Identity threading: ClientCoordinator is entity-backed by ConferenceGroup, so
every ownership-gated call uses make_coordinator_headers(group["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assignment_entry,
    create_building_payload,
    create_conference_group_payload,
    create_participant_payload,
    create_revision_payload,
)
from .test_users import (
    TEST_USERS,
    make_coordinator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
FACILITIES = TEST_USERS["facilities_headers"]
HOUSEKEEPING = TEST_USERS["housekeeping_headers"]
FINANCE = TEST_USERS["finance_headers"]
SCREENING = TEST_USERS["screening_headers"]

DEFAULT_CHECKIN = "2026-06-15T15:00:00Z"
DEFAULT_CHECKOUT = "2026-06-17T11:00:00Z"
DEFAULT_ARRIVAL = "2026-06-15"
DEFAULT_DEPARTURE = "2026-06-17"


# ---------------------------------------------------------------------------
# Tier 1: building season progression
# ---------------------------------------------------------------------------

def create_building(name="Test Hall", fall_opening_date="2026-08-20", key_pool_size=10):
    """Create a building (initial status ACADEMIC_USE)."""
    resp = api_client.create_building(
        create_building_payload(name=name, fall_opening_date=fall_opening_date,
                                key_pool_size=key_pool_size), ADMIN)
    return get_success_data(resp)


def create_room(building_id, room_number="R1", bed_count=1):
    resp = api_client.create_room(
        building_id, {"room_number": room_number, "bed_count": bed_count}, FACILITIES)
    return get_success_data(resp)


def create_building_turn_active(name="Test Hall", key_pool_size=10,
                                rooms=(("R1", 1),), fall_opening_date="2026-08-20"):
    """Building with rooms, walked to TURN_ACTIVE. Returns (building, rooms_dict)."""
    building = create_building(name=name, fall_opening_date=fall_opening_date,
                               key_pool_size=key_pool_size)
    room_map = {}
    for room_number, bed_count in rooms:
        room = create_room(building["id"], room_number=room_number, bed_count=bed_count)
        room_map[room_number] = room
    get_success_data(api_client.initiate_release(building["id"], FACILITIES))
    building = get_success_data(api_client.confirm_release(building["id"], FACILITIES))
    building = get_success_data(api_client.begin_turn_season(building["id"], FACILITIES))
    return building, room_map


def create_building_released(name="Test Hall", key_pool_size=10,
                             rooms=(("R1", 1),), fall_opening_date="2026-08-20"):
    """Building with rooms, walked to RELEASED only (turn season NOT begun)."""
    building = create_building(name=name, fall_opening_date=fall_opening_date,
                               key_pool_size=key_pool_size)
    room_map = {}
    for room_number, bed_count in rooms:
        room = create_room(building["id"], room_number=room_number, bed_count=bed_count)
        room_map[room_number] = room
    get_success_data(api_client.initiate_release(building["id"], FACILITIES))
    building = get_success_data(api_client.confirm_release(building["id"], FACILITIES))
    return building, room_map


def get_building(building_id):
    return get_success_data(api_client.get_building(building_id, ADMIN))


def get_group(group_id):
    return get_success_data(api_client.get_conference_group(group_id, ADMIN))


def get_room(room_id):
    return get_success_data(api_client.get_room(room_id, ADMIN))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, FINANCE))


# ---------------------------------------------------------------------------
# Tier 2: group + participants + rooming list hierarchy
# ---------------------------------------------------------------------------

def create_group(building_id, client_name="Test Client", arrival_date=DEFAULT_ARRIVAL,
                 departure_date=DEFAULT_DEPARTURE, contracted_bed_count=1,
                 deposit_paid_cents=5000, has_minor_participants=False,
                 linen_tier="STANDARD"):
    payload = create_conference_group_payload(
        building_id, client_name=client_name, arrival_date=arrival_date,
        departure_date=departure_date, contracted_bed_count=contracted_bed_count,
        deposit_paid_cents=deposit_paid_cents,
        has_minor_participants=has_minor_participants, linen_tier=linen_tier)
    return get_success_data(api_client.create_conference_group(payload, ADMIN))


def add_participant(group_id, full_name="Test Person", date_of_birth="1990-01-01",
                    role_in_group="ATTENDEE"):
    payload = create_participant_payload(full_name=full_name, date_of_birth=date_of_birth,
                                         role_in_group=role_in_group)
    resp = api_client.add_participant(group_id, payload, make_coordinator_headers(group_id))
    return get_success_data(resp)


def add_participants(group_id, specs):
    """specs: list of (full_name, date_of_birth, role_in_group). Returns participants."""
    return [add_participant(group_id, full_name=s[0], date_of_birth=s[1],
                            role_in_group=s[2]) for s in specs]


def create_revision(group_id, assignment_specs):
    """Create a rooming-list revision with a fresh OCC version read.

    assignment_specs: list of dicts {participant_id, room_id, checkin_at, checkout_at}.
    Returns the created revision."""
    group = get_group(group_id)
    entries = [create_assignment_entry(**spec) for spec in assignment_specs]
    payload = create_revision_payload(group["version"], entries)
    resp = api_client.create_rooming_list_revision(
        group_id, payload, make_coordinator_headers(group_id))
    return get_success_data(resp)


def submit_group(group_id):
    return get_success_data(api_client.submit_group(group_id, make_coordinator_headers(group_id)))


def confirm_group(group_id):
    return get_success_data(api_client.confirm_group(group_id, ADMIN))


def create_group_with_revision(building_id, rooms, client_name="Test Client",
                               participant_specs=None, assignment_room_map=None,
                               arrival_date=DEFAULT_ARRIVAL, departure_date=DEFAULT_DEPARTURE,
                               checkin_at=DEFAULT_CHECKIN, checkout_at=DEFAULT_CHECKOUT,
                               contracted_bed_count=None, deposit_paid_cents=5000,
                               has_minor_participants=False, linen_tier="STANDARD"):
    """Group in DRAFT with participants and one ACTIVE revision of assignments.

    participant_specs: list of (name, dob, role). Defaults to a single adult ATTENDEE.
    assignment_room_map: list of room_numbers, one per participant, in order.
    Returns (group, participants, revision).
    """
    if participant_specs is None:
        participant_specs = [("A One", "1990-01-01", "ATTENDEE")]
    if assignment_room_map is None:
        assignment_room_map = ["R1"] * len(participant_specs)
    if contracted_bed_count is None:
        contracted_bed_count = len(participant_specs)
    group = create_group(building_id, client_name=client_name, arrival_date=arrival_date,
                         departure_date=departure_date,
                         contracted_bed_count=contracted_bed_count,
                         deposit_paid_cents=deposit_paid_cents,
                         has_minor_participants=has_minor_participants,
                         linen_tier=linen_tier)
    participants = add_participants(group["id"], participant_specs)
    specs = []
    for participant, room_number in zip(participants, assignment_room_map):
        specs.append({"participant_id": participant["id"],
                      "room_id": rooms[room_number]["id"],
                      "checkin_at": checkin_at, "checkout_at": checkout_at})
    revision = create_revision(group["id"], specs)
    return get_group(group["id"]), participants, revision


def list_assignments(group_id=None, participant_id=None, room_id=None, revision_id=None):
    params = {}
    if group_id:
        params["group_id"] = group_id
    if participant_id:
        params["participant_id"] = participant_id
    if room_id:
        params["room_id"] = room_id
    if revision_id:
        params["revision_id"] = revision_id
    data, _meta = _validate_paginated(api_client.list_stay_assignments(ADMIN, params=params))
    return data


def _validate_paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def get_assignment_for_participant(group_id, participant_id):
    rows = list_assignments(group_id=group_id, participant_id=participant_id)
    assert len(rows) >= 1, f"Setup failed: no assignment for participant {participant_id}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 3: confirmed group / in-house / departed lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_confirmed_group(building, rooms, **kwargs):
    """Group walked DRAFT -> SUBMITTED -> CONFIRMED. Returns (group, participants, revision, invoice_id).

    When has_minor_participants is true, every CHAPERONE/STAFF participant is
    walked through a CLEARED screening first so the confirm gate can pass.
    """
    group, participants, revision = create_group_with_revision(building["id"], rooms, **kwargs)
    if group["has_minor_participants"]:
        for participant in participants:
            if participant["role_in_group"] in ("CHAPERONE", "STAFF"):
                clear_screening(participant["id"], group["id"],
                                consent_reference=f"CONS-{participant['id'][:8]}")
    submit_group(group["id"])
    group = confirm_group(group["id"])
    return group, participants, revision, group["provisional_invoice_id"]


def setup_checked_in_group(building, rooms, checkin_clock="2026-06-15T16:00:00Z", **kwargs):
    """Confirmed group with every assignment checked in. Returns (group, participants, assignments, invoice_id)."""
    group, participants, revision, invoice_id = setup_confirmed_group(building, rooms, **kwargs)
    set_clock(checkin_clock)
    assignments = []
    for participant in participants:
        assignment = get_assignment_for_participant(group["id"], participant["id"])
        assignment = get_success_data(api_client.check_in_assignment(assignment["id"], ADMIN))
        assignments.append(assignment)
    return get_group(group["id"]), participants, assignments, invoice_id


def setup_departed_group(building, rooms, checkin_clock="2026-06-15T16:00:00Z",
                         checkout_clock="2026-06-17T10:00:00Z", **kwargs):
    """Group walked all the way to DEPARTED (all assignments checked out).

    Returns (group, participants, assignments, invoice_id)."""
    group, participants, assignments, invoice_id = setup_checked_in_group(
        building, rooms, checkin_clock=checkin_clock, **kwargs)
    set_clock(checkout_clock)
    for assignment in assignments:
        get_success_data(api_client.check_out_assignment(assignment["id"], ADMIN))
    get_success_data(api_client.close_out_group(group["id"], ADMIN))
    return get_group(group["id"]), participants, assignments, invoice_id


def setup_finalized_invoice(building, rooms, **kwargs):
    """Group DEPARTED with its invoice FINALIZED. Returns (group, assignments, invoice)."""
    group, participants, assignments, invoice_id = setup_departed_group(building, rooms, **kwargs)
    invoice = get_success_data(api_client.finalize_invoice(invoice_id, FINANCE))
    return group, assignments, invoice


def setup_paid_group(building, rooms, payment_clock=None, **kwargs):
    """Full lifecycle through invoice PAID and group CLOSED. Returns (group, invoice)."""
    group, assignments, invoice = setup_finalized_invoice(building, rooms, **kwargs)
    if payment_clock is not None:
        set_clock(payment_clock)
    invoice = get_success_data(
        api_client.record_payment(invoice["id"], invoice["balance_due_cents"], FINANCE))
    return get_group(group["id"]), invoice


def setup_room_needs_turn(building, rooms, room_number="R1", **kwargs):
    """Drive a stay through checkout so the room is NEEDS_TURN with a SCHEDULED
    turn task. Returns (group, assignment, turn_task)."""
    group, participants, assignments, invoice_id = setup_checked_in_group(
        building, rooms, **kwargs)
    set_clock("2026-06-17T10:00:00Z")
    assignment = assignments[0]
    get_success_data(api_client.check_out_assignment(assignment["id"], ADMIN))
    room = get_room(rooms[room_number]["id"])
    assert room["active_turn_task_id"], "Setup failed: room has no active turn task"
    task = get_success_data(api_client.get_turn_task(room["active_turn_task_id"], HOUSEKEEPING))
    return get_group(group["id"]), assignment, task


# ---------------------------------------------------------------------------
# Tier 4: screening helpers
# ---------------------------------------------------------------------------

def submit_screening(participant_id, group_id, consent_reference="CONS-1"):
    resp = api_client.create_background_screening(
        participant_id, {"consent_reference": consent_reference},
        make_coordinator_headers(group_id))
    return get_success_data(resp)


def clear_screening(participant_id, group_id, consent_reference="CONS-1"):
    """Submit a screening and walk it SUBMITTED -> IN_REVIEW -> CLEARED."""
    screening = submit_screening(participant_id, group_id, consent_reference=consent_reference)
    get_success_data(api_client.begin_review_screening(screening["id"], SCREENING))
    return get_success_data(api_client.decide_screening(screening["id"], "CLEAR", SCREENING))


def flag_screening(participant_id, group_id, consent_reference="CONS-1"):
    """Submit a screening and walk it SUBMITTED -> IN_REVIEW -> FLAGGED."""
    screening = submit_screening(participant_id, group_id, consent_reference=consent_reference)
    get_success_data(api_client.begin_review_screening(screening["id"], SCREENING))
    return get_success_data(api_client.decide_screening(screening["id"], "FLAG", SCREENING))


# ---------------------------------------------------------------------------
# Tier 5: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
