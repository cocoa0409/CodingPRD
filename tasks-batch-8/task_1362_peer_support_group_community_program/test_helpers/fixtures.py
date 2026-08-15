"""Composite setup helpers.

Every fixture builds preconditions from scratch via PRD-declared endpoints,
using the lenient get_success_data() validator so setup failures surface as
clear "Setup failed" errors rather than assertion failures.

Timestamp conventions: the logical clock starts at 2026-08-01T00:00:00Z
(PRD §2.4); sessions are typically placed on 2026-08-02; agreements sign
2026-07-25 and expire 2027-07-25.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    DEFAULT_COMPLETED_AT,
    DEFAULT_REVIEW_AT,
)
from .factories import (
    create_agreement_payload,
    create_attendance_payload,
    create_enrollment_payload,
    create_facilitator_payload,
    create_group_payload,
    create_incident_payload,
    create_participant_payload,
    create_program_payload,
    create_room_payload,
    create_session_payload,
    create_supervision_review_payload,
    create_training_completion_payload,
    create_training_course_payload,
    unique_course_code,
)
from .test_users import (
    TEST_USERS,
    make_facilitator_headers,
    make_participant_headers,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _ctx(**kwargs):
    """Simple attribute-access namespace for fixture return bundles."""

    class Ctx:
        pass

    ctx = Ctx()
    for key, value in kwargs.items():
        setattr(ctx, key, value)
    return ctx


# ---------------------------------------------------------------------------
# Tier 0: clock + simple creators
# ---------------------------------------------------------------------------

def reset_clock(to_iso8601: str = CLOCK_START):
    """Set the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def make_program(name="Test Program", focus_area="GRIEF"):
    reset_clock()
    data = get_success_data(api_client.create_program(
        create_program_payload(name=name, focus_area=focus_area), ADMIN))
    return data


def make_room(name="Room A", physical_capacity=10):
    return get_success_data(api_client.create_room(
        create_room_payload(name=name, physical_capacity=physical_capacity), ADMIN))


def make_group(pid, name="Group A", modality="VIRTUAL", base_capacity=5,
               required_facilitator_level=1):
    return get_success_data(api_client.create_group(
        pid,
        create_group_payload(
            name=name, modality=modality, base_capacity=base_capacity,
            required_facilitator_level=required_facilitator_level),
        ADMIN))


def make_active_group(pid, **kwargs):
    """Create a group and activate it (DRAFT -> ACTIVE)."""
    group = make_group(pid, **kwargs)
    return get_success_data(api_client.activate_group(pid, group["id"], ADMIN))


def make_course(code="T100", credit_hours=4, level_weight=2, title=None):
    return get_success_data(api_client.create_training_course(
        create_training_course_payload(
            code=code, title=title or f"Course {code}",
            credit_hours=credit_hours, level_weight=level_weight),
        ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: facilitator pipeline
# ---------------------------------------------------------------------------

def make_facilitator(full_name="Facilitator One", email=None):
    payload = create_facilitator_payload(full_name=full_name)
    if email:
        payload["email"] = email
    return get_success_data(api_client.create_facilitator(payload, ADMIN))


def advance_facilitator_to_practice(fid, course_ids=(), score=90):
    """APPLIED -> SCREENING -> IN_TRAINING -> (completions) -> SUPERVISED_PRACTICE."""
    get_success_data(api_client.advance_to_screening(fid, ADMIN))
    get_success_data(api_client.advance_to_training(fid, ADMIN))
    for index, course_id in enumerate(course_ids):
        day = f"2026-07-{1 + index:02d}T00:00:00Z"
        get_success_data(api_client.create_training_completion(
            fid,
            create_training_completion_payload(course_id, completed_at=day, score=score),
            ADMIN))
    get_success_data(api_client.advance_to_practice(fid, ADMIN))


def make_bootstrap_reviewer(email=None):
    """A CERTIFIED reviewer with level 5, built from two high-weight courses
    (level_weight 2 + 3 -> training points 5 -> raw level 6, clamped to 5).
    Returns (reviewer, [course_a, course_b]).

    PRD §3.2 gates certification on "at least one SupervisionReview with a
    `rating` of at least 3", and the reviewer of that review must hold "a
    `level` of at least 4 ... at the moment the review is created". From an
    empty store the first review therefore comes from a peer facilitator who
    has reached level >= 4 through training (a single level_weight-3 course
    yields 3 training points -> level 4) but is never certified."""
    course_a = make_course(code="RVW-200", credit_hours=4, level_weight=2)
    course_b = make_course(code="RVW-300", credit_hours=6, level_weight=3)
    reviewer = make_facilitator(full_name="Reviewer Root", email=email)
    advance_facilitator_to_practice(reviewer["id"], [course_a["id"], course_b["id"]], score=95)
    peer = make_facilitator(full_name="Reviewer Peer")
    advance_facilitator_to_practice(peer["id"], [course_b["id"]], score=95)
    get_success_data(api_client.create_supervision_review(
        reviewer["id"],
        create_supervision_review_payload(peer["id"], rating=4),
        ADMIN))
    reviewer = get_success_data(api_client.certify_facilitator(reviewer["id"], ADMIN))
    return reviewer, [course_a, course_b]


def make_certified_facilitator(reviewer_id, email=None, course=None,
                               review_rating=4, full_name="Facilitator One"):
    """Full pipeline to CERTIFIED: one passing completion on `course`
    (default: a fresh 4-credit, level_weight-2 course -> level 3), a
    supervision review from `reviewer_id`, then certification."""
    if course is None:
        course = make_course(
            code=unique_course_code("FAC"), credit_hours=4, level_weight=2)
    facilitator = make_facilitator(full_name=full_name, email=email)
    advance_facilitator_to_practice(facilitator["id"], [course["id"]], score=90)
    get_success_data(api_client.create_supervision_review(
        facilitator["id"],
        create_supervision_review_payload(reviewer_id, rating=review_rating),
        ADMIN))
    facilitator = get_success_data(api_client.certify_facilitator(facilitator["id"], ADMIN))
    return facilitator


# ---------------------------------------------------------------------------
# Tier 1: participants + agreements
# ---------------------------------------------------------------------------

def make_participant(full_name="Participant One", email=None, household_size=1):
    payload = create_participant_payload(
        full_name=full_name, household_size=household_size)
    if email:
        payload["email"] = email
    return get_success_data(api_client.create_participant(payload, ADMIN))


def sign_agreement(participant_id, **overrides):
    return get_success_data(api_client.create_agreement(
        participant_id, create_agreement_payload(**overrides), ADMIN))


def make_active_participant(**kwargs):
    """Register a participant, sign an agreement, activate (REGISTERED -> ACTIVE).
    Returns (participant, agreement)."""
    participant = make_participant(**kwargs)
    agreement = sign_agreement(participant["id"])
    participant = get_success_data(api_client.activate_participant(participant["id"], ADMIN))
    return participant, agreement


# ---------------------------------------------------------------------------
# Tier 2: enrollments
# ---------------------------------------------------------------------------

def make_enrollment(pid, gid, participant_id, as_participant=False):
    headers = make_participant_headers(participant_id) if as_participant else ADMIN
    return get_success_data(api_client.create_enrollment(
        pid, gid, create_enrollment_payload(participant_id), headers))


def get_group_version(pid, gid):
    group = get_success_data(api_client.get_group(pid, gid, ADMIN))
    return group["version"]


def confirm_enrollment(pid, gid, eid, headers=None):
    """Confirm an enrollment with a fresh expected_group_version (PRD §2.8)."""
    version = get_group_version(pid, gid)
    response = api_client.confirm_enrollment(
        pid, gid, eid, {"expected_group_version": version}, headers or ADMIN)
    return get_success_data(response)


def make_confirmed_enrollment(pid, gid, participant_id):
    """Enroll + confirm. Returns the confirmed enrollment."""
    enrollment = make_enrollment(pid, gid, participant_id)
    return confirm_enrollment(pid, gid, enrollment["id"])


# ---------------------------------------------------------------------------
# Tier 3: sessions
# ---------------------------------------------------------------------------

def make_session(pid, gid, primary_facilitator_id, start_at="2026-08-02T10:00:00Z",
                 end_at="2026-08-02T11:00:00Z", room_id=None, cofacilitator_id=None):
    payload = create_session_payload(
        primary_facilitator_id, start_at=start_at, end_at=end_at)
    if room_id is not None:
        payload["room_id"] = room_id
    if cofacilitator_id is not None:
        payload["cofacilitator_id"] = cofacilitator_id
    return get_success_data(api_client.create_session(pid, gid, payload, ADMIN))


def get_facilitator_version(fid):
    facilitator = get_success_data(api_client.get_facilitator(fid, ADMIN))
    return facilitator["version"]


def schedule_session(pid, gid, sid):
    """Schedule a DRAFT session with a fresh expected_facilitator_version (PRD §2.8)."""
    session = get_success_data(api_client.get_session(pid, gid, sid, ADMIN))
    version = get_facilitator_version(session["primary_facilitator_id"])
    return get_success_data(api_client.schedule_session(
        pid, gid, sid, {"expected_facilitator_version": version}, ADMIN))


def make_scheduled_session(pid, gid, primary_facilitator_id, **kwargs):
    session = make_session(pid, gid, primary_facilitator_id, **kwargs)
    return schedule_session(pid, gid, session["id"])


# ---------------------------------------------------------------------------
# Tier 3: composite scenarios
# ---------------------------------------------------------------------------

def setup_program_with_active_group(modality="IN_PERSON", base_capacity=5,
                                    required_facilitator_level=1,
                                    room_capacity=10, focus_area="GRIEF"):
    """Program + (room when modality needs one) + ACTIVE group.
    Returns ctx(program, group, room|None)."""
    reset_clock()
    program = make_program()
    room = None
    if modality in ("IN_PERSON", "HYBRID"):
        room = make_room(physical_capacity=room_capacity)
    group = make_active_group(
        program["id"], modality=modality, base_capacity=base_capacity,
        required_facilitator_level=required_facilitator_level)
    return _ctx(program=program, group=group, room=room)


def setup_certified_facilitator(email=None, full_name="Facilitator One"):
    """Bootstrap reviewer + one CERTIFIED facilitator (level 3).
    Returns ctx(facilitator, reviewer, facilitator_course)."""
    reviewer, _ = make_bootstrap_reviewer()
    facilitator = make_certified_facilitator(
        reviewer["id"], email=email, full_name=full_name)
    return _ctx(facilitator=facilitator, reviewer=reviewer)


def setup_session_scenario(modality="IN_PERSON", base_capacity=5,
                           required_facilitator_level=1, room_capacity=10,
                           start_at="2026-08-02T10:00:00Z",
                           end_at="2026-08-02T11:00:00Z"):
    """Program + room (if needed) + ACTIVE group + CERTIFIED facilitator +
    reviewer + one SCHEDULED session. Returns ctx(program, group, room,
    facilitator, reviewer, session)."""
    env = setup_program_with_active_group(
        modality=modality, base_capacity=base_capacity,
        required_facilitator_level=required_facilitator_level,
        room_capacity=room_capacity)
    fac = setup_certified_facilitator()
    session = make_scheduled_session(
        env.program["id"], env.group["id"], fac.facilitator["id"],
        start_at=start_at, end_at=end_at,
        room_id=env.room["id"] if env.room else None)
    return _ctx(program=env.program, group=env.group, room=env.room,
                facilitator=fac.facilitator, reviewer=fac.reviewer,
                session=session)


def setup_in_progress_session(check_in_time="2026-08-02T10:05:00Z", **kwargs):
    """setup_session_scenario + clock advanced into the session window
    (SCHEDULED -> IN_PROGRESS, PRD §2.4)."""
    env = setup_session_scenario(**kwargs)
    reset_clock(check_in_time)
    session = get_success_data(api_client.get_session(
        env.program["id"], env.group["id"], env.session["id"], ADMIN))
    env.session = session
    return env


def setup_completed_session_with_attendance(start_at="2026-08-02T10:00:00Z",
                                            end_at="2026-08-02T11:00:00Z",
                                            modality="IN_PERSON"):
    """Full happy path: program + ACTIVE group + CERTIFIED facilitator +
    ACTIVE participant (signed agreement) + CONFIRMED enrollment + session
    scheduled -> check-in -> checkout -> clock past end -> complete.
    Returns ctx(program, group, room, facilitator, reviewer, participant,
    agreement, enrollment, session, attendance)."""
    env = setup_session_scenario(
        modality=modality, start_at=start_at, end_at=end_at)
    participant, agreement = make_active_participant()
    enrollment = make_confirmed_enrollment(
        env.program["id"], env.group["id"], participant["id"])
    reset_clock("2026-08-02T10:05:00Z")
    fac_headers = make_facilitator_headers(env.facilitator["id"])
    access = "VIRTUAL" if modality == "VIRTUAL" else "IN_PERSON"
    attendance = get_success_data(api_client.check_in(
        env.program["id"], env.group["id"], env.session["id"],
        create_attendance_payload(participant["id"], access_modality=access),
        fac_headers))
    attendance = get_success_data(api_client.checkout_attendance(
        env.program["id"], env.group["id"], env.session["id"],
        attendance["id"], fac_headers))
    reset_clock("2026-08-02T11:30:00Z")
    session = get_success_data(api_client.complete_session(
        env.program["id"], env.group["id"], env.session["id"], fac_headers))
    return _ctx(program=env.program, group=env.group, room=env.room,
                facilitator=env.facilitator, reviewer=env.reviewer,
                participant=participant, agreement=agreement,
                enrollment=enrollment, session=session, attendance=attendance)


# ---------------------------------------------------------------------------
# Tier 3: incidents and posture
# ---------------------------------------------------------------------------

def make_incident(pid, gid, sid, raised_by_facilitator_id, severity="STANDARD",
                  category="OTHER", description="incident"):
    return get_success_data(api_client.create_incident(
        pid, gid, sid,
        create_incident_payload(
            raised_by_facilitator_id, severity=severity,
            category=category, description=description),
        make_facilitator_headers(raised_by_facilitator_id)))


def setup_program_in_posture(severity="CRITICAL"):
    """Program driven to LOCKDOWN (CRITICAL) or CAUTION (STANDARD) by raising
    an incident on an IN_PROGRESS session. Returns ctx(program, group, room,
    facilitator, reviewer, session, incident)."""
    env = setup_in_progress_session()
    incident = make_incident(
        env.program["id"], env.group["id"], env.session["id"],
        env.facilitator["id"], severity=severity, category="SAFETY")
    env.incident = incident
    return env


# ---------------------------------------------------------------------------
# Tier 3: clinical referral via escalation
# ---------------------------------------------------------------------------

def setup_pending_referral():
    """Escalate a CRITICAL incident -> ClinicalReferral PENDING. The referral
    is located through the top-level collection filtered by source_incident_id
    (PRD §3.7). Returns ctx(program, group, room, facilitator, reviewer,
    participant, session, incident, referral)."""
    env = setup_in_progress_session()
    participant, _ = make_active_participant()
    make_confirmed_enrollment(env.program["id"], env.group["id"], participant["id"])
    incident = make_incident(
        env.program["id"], env.group["id"], env.session["id"],
        env.facilitator["id"], severity="CRITICAL", category="SAFETY")
    # A ClinicalReferral "belongs to a participant" (PRD §3.7), so the
    # escalation names the enrolled participant for the created referral.
    get_success_data(api_client.escalate_incident(
        env.program["id"], env.group["id"], env.session["id"],
        incident["id"], ADMIN, payload={"participant_id": participant["id"]}))
    referrals, _meta = _split_paginated(api_client.list_all_clinical_referrals(
        ADMIN, params={"source_incident_id": incident["id"]}))
    assert referrals, "Setup failed: escalation must create a ClinicalReferral"
    referral = referrals[0]
    return _ctx(program=env.program, group=env.group, room=env.room,
                facilitator=env.facilitator, reviewer=env.reviewer,
                participant=participant, session=env.session,
                incident=incident, referral=referral)


def _split_paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)
