"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints — the test harness restarts the server (empty DB) before each test.

Fixtures use get_success_data() (lenient) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion mismatches.

Identity threading: after creating a Family, any ownership-gated Parent call
uses make_parent_headers(family["id"]); opaque StudioAdmin/FrontDeskStaff calls
use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_parent_headers
from . import factories as f

ADMIN = TEST_USERS["studio_admin_headers"]
STAFF = TEST_USERS["front_desk_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(instant: str):
    """Move the logical clock to a UTC instant (StudioAdmin only)."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


# --------------------------------------------------------------------------
# Catalog primitives (program / room / instructor)
# --------------------------------------------------------------------------
def create_program(level_index=0, min_age_months=6, max_age_months=60,
                   tuition_cents=2500, participation_required=False, **overrides):
    payload = f.create_program_payload(
        level_index=level_index, min_age_months=min_age_months,
        max_age_months=max_age_months, tuition_cents=tuition_cents,
        participation_required=participation_required, **overrides,
    )
    return get_success_data(api_client.create_program(payload, ADMIN))


def create_room(physical_capacity=12, name="Room A"):
    return get_success_data(
        api_client.create_room(f.create_room_payload(physical_capacity=physical_capacity, name=name), ADMIN)
    )


def create_instructor(certified_level_indices=(0,), buffer_minutes=15, full_name="Ms. Lee"):
    payload = f.create_instructor_payload(
        certified_level_indices=list(certified_level_indices),
        buffer_minutes=buffer_minutes, full_name=full_name,
    )
    return get_success_data(api_client.create_instructor(payload, ADMIN))


def create_session(program_id, room_id, instructor_id,
                   start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z",
                   capacity=5):
    payload = f.create_session_payload(
        program_id, room_id, instructor_id,
        start_at=start_at, end_at=end_at, capacity=capacity,
    )
    return get_success_data(api_client.create_session(payload, STAFF))


def setup_catalog(level_index=0, min_age_months=6, max_age_months=60,
                  tuition_cents=2500, participation_required=False,
                  certified_level_indices=None, physical_capacity=12,
                  buffer_minutes=15):
    """Create one program + one room + one certified instructor.

    Returns (program, room, instructor). The shared preamble for nearly every
    scheduling/enrollment scenario.
    """
    program = create_program(
        level_index=level_index, min_age_months=min_age_months,
        max_age_months=max_age_months, tuition_cents=tuition_cents,
        participation_required=participation_required,
    )
    room = create_room(physical_capacity=physical_capacity)
    certs = certified_level_indices if certified_level_indices is not None else [level_index]
    instructor = create_instructor(certified_level_indices=certs, buffer_minutes=buffer_minutes)
    return program, room, instructor


# --------------------------------------------------------------------------
# Family / Child / Membership
# --------------------------------------------------------------------------
_email_counter = {"n": 0}


def _next_email():
    _email_counter["n"] += 1
    return f"fam{_email_counter['n']}@example.com"


def create_family(account_email=None, primary_contact_name="Test Parent"):
    payload = f.create_family_payload(
        account_email=account_email or _next_email(),
        primary_contact_name=primary_contact_name,
    )
    return get_success_data(api_client.create_family(payload, STAFF))


def create_child(family_id, full_name="Test Child", birth_date="2024-01-01"):
    payload = f.create_child_payload(family_id, full_name=full_name, birth_date=birth_date)
    return get_success_data(api_client.create_child(payload, STAFF))


def create_membership(family_id, tier="CORE", cycle_anchor_day=1):
    payload = f.create_membership_payload(family_id, tier=tier, cycle_anchor_day=cycle_anchor_day)
    return get_success_data(api_client.create_membership(payload, STAFF))


def activate_membership(membership_id):
    return get_success_data(api_client.activate_membership(membership_id, STAFF))


def create_active_membership(family_id=None, tier="CORE", cycle_anchor_day=1):
    """Create a family (if needed) + PENDING_PAYMENT membership + activate it.

    Returns (family, membership). Membership is ACTIVE with base fee snapshotted.
    """
    if family_id is None:
        family = create_family()
        family_id = family["id"]
    else:
        family = get_success_data(api_client.get_family(family_id, STAFF))
    membership = create_membership(family_id, tier=tier, cycle_anchor_day=cycle_anchor_day)
    activate_membership(membership["id"])
    membership = get_success_data(api_client.get_membership(membership["id"], STAFF))
    return family, membership


# --------------------------------------------------------------------------
# Enrollment helpers
# --------------------------------------------------------------------------
def get_session_version(session_id):
    return get_success_data(api_client.get_session(session_id, STAFF))["version"]


def enroll_child(child_id, session_id, membership_id, kind="RECURRING",
                 expected_session_version=None, accompanying_adult=None):
    """Enroll a child, auto-fetching the live session version if not supplied."""
    if expected_session_version is None:
        expected_session_version = get_session_version(session_id)
    payload = f.create_enrollment_payload(
        child_id, session_id, membership_id, expected_session_version, kind=kind,
    )
    if accompanying_adult is not None:
        payload["accompanying_adult"] = accompanying_adult
    return get_success_data(api_client.create_enrollment(payload, STAFF))


def setup_enrolled_child(level_index=0, tuition_cents=2500, capacity=5,
                         tier="CORE", kind="RECURRING",
                         birth_date="2024-01-01", participation_required=False,
                         min_age_months=6, max_age_months=60):
    """Full preamble to a single ENROLLED child on a SCHEDULED session.

    Builds clock-independent catalog (caller should set clock first if age
    matters) + active membership + one enrollment.

    Returns dict with keys: program, room, instructor, session, family,
    child, membership, enrollment.
    """
    program, room, instructor = setup_catalog(
        level_index=level_index, tuition_cents=tuition_cents,
        participation_required=participation_required,
        min_age_months=min_age_months, max_age_months=max_age_months,
        physical_capacity=max(capacity, 12),
    )
    session = create_session(program["id"], room["id"], instructor["id"], capacity=capacity)
    family, membership = create_active_membership(tier=tier)
    child = create_child(family["id"], birth_date=birth_date)
    enrollment = enroll_child(child["id"], session["id"], membership["id"], kind=kind)
    return {
        "program": program, "room": room, "instructor": instructor,
        "session": session, "family": family, "child": child,
        "membership": membership, "enrollment": enrollment,
    }


# --------------------------------------------------------------------------
# Waitlist setup (capacity-1 session with one ENROLLED + one WAITLISTED)
# --------------------------------------------------------------------------
def setup_waitlisted_pair(level_index=0, tuition_cents=2500, tier="PLUS"):
    """Capacity-1 level session: child A ENROLLED, child B WAITLISTED behind it.

    Returns dict: program, room, instructor, session, family, membership,
    child_a, child_b, enrollment_a, enrollment_b.
    """
    program, room, instructor = setup_catalog(
        level_index=level_index, tuition_cents=tuition_cents,
    )
    session = create_session(program["id"], room["id"], instructor["id"], capacity=1)
    family, membership = create_active_membership(tier=tier)
    child_a = create_child(family["id"], full_name="First", birth_date="2024-01-01")
    child_b = create_child(family["id"], full_name="Second", birth_date="2024-02-01")
    enr_a = enroll_child(child_a["id"], session["id"], membership["id"], kind="RECURRING")
    enr_b = enroll_child(child_b["id"], session["id"], membership["id"], kind="RECURRING")
    return {
        "program": program, "room": room, "instructor": instructor,
        "session": session, "family": family, "membership": membership,
        "child_a": child_a, "child_b": child_b,
        "enrollment_a": enr_a, "enrollment_b": enr_b,
    }


# --------------------------------------------------------------------------
# Session state progression
# --------------------------------------------------------------------------
def hold_session(session_id, attendance=None):
    payload = {"attendance": attendance if attendance is not None else []}
    return get_success_data(api_client.hold_session(session_id, payload, STAFF))


def cancel_session(session_id):
    return get_success_data(api_client.cancel_session(session_id, STAFF))


# --------------------------------------------------------------------------
# Makeup-credit setup (cancel a session holding one ENROLLED RECURRING child)
# --------------------------------------------------------------------------
def setup_membership_with_credit(issued_tuition_cents=2500, tier="CORE",
                                 target_level_index=0, target_tuition_cents=None,
                                 target_certified_levels=None):
    """Mint one AVAILABLE makeup credit on a membership by cancelling a level-0
    session that held one ENROLLED RECURRING child, and provide a second
    SCHEDULED target session for redemption.

    The source session (level 0, issued_tuition_cents) is cancelled. The target
    session (target_level_index, target_tuition_cents) remains SCHEDULED.

    Returns dict: program_src, program_tgt, room, instructor, family,
    membership, child, source_enrollment, target_session, target_session_id.
    """
    if target_tuition_cents is None:
        target_tuition_cents = issued_tuition_cents
    levels_needed = sorted({0, target_level_index})
    certs = target_certified_levels if target_certified_levels is not None else levels_needed

    program_src = create_program(level_index=0, tuition_cents=issued_tuition_cents)
    if target_level_index == 0:
        program_tgt = program_src
    else:
        program_tgt = create_program(level_index=target_level_index,
                                     tuition_cents=target_tuition_cents)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=certs)

    source_session = create_session(
        program_src["id"], room["id"], instructor["id"],
        start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5,
    )
    target_session = create_session(
        program_tgt["id"], room["id"], instructor["id"],
        start_at="2026-05-17T09:00:00Z", end_at="2026-05-17T10:00:00Z", capacity=5,
    )
    family, membership = create_active_membership(tier=tier)
    child = create_child(family["id"], birth_date="2024-01-01")
    source_enr = enroll_child(child["id"], source_session["id"], membership["id"], kind="RECURRING")
    cancel_session(source_session["id"])
    membership = get_success_data(api_client.get_membership(membership["id"], STAFF))
    return {
        "program_src": program_src, "program_tgt": program_tgt,
        "room": room, "instructor": instructor,
        "family": family, "membership": membership, "child": child,
        "source_enrollment": source_enr,
        "target_session": target_session,
        "target_session_id": target_session["id"],
    }


# --------------------------------------------------------------------------
# Invoice via renew
# --------------------------------------------------------------------------
def renew_membership(membership_id):
    return get_success_data(api_client.renew_membership(membership_id, STAFF))


def setup_billable_membership(num_children, tuition_cents, tier="PLUS",
                              level_index=0, capacity=10):
    """Active membership with N children all ENROLLED RECURRING on one level
    session (tuition_cents each). Ready for renew → invoice.

    Returns dict: program, room, instructor, session, family, membership,
    children (list).
    """
    program, room, instructor = setup_catalog(
        level_index=level_index, tuition_cents=tuition_cents,
        physical_capacity=max(capacity, 12),
    )
    session = create_session(program["id"], room["id"], instructor["id"], capacity=capacity)
    family, membership = create_active_membership(tier=tier)
    children = []
    for i in range(num_children):
        child = create_child(
            family["id"], full_name=f"Kid{i+1}",
            birth_date=f"2024-0{(i % 9) + 1}-01",
        )
        enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
        children.append(child)
    return {
        "program": program, "room": room, "instructor": instructor,
        "session": session, "family": family, "membership": membership,
        "children": children,
    }
