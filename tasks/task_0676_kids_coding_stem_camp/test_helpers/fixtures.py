"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so that setup failures
surface as clear "Setup failed" errors rather than confusing assertion
failures. Identity threading is mandatory: any ownership-gated call after a
Guardian is created uses make_guardian_headers(guardian["id"]).

Every fixture builds its preconditions from scratch (the harness restarts the
server with an empty database before every test) using only PRD-declared
endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_center_payload, create_program_payload, create_belt_level_payload,
    create_badge_payload, create_guardian_payload, create_wallet_adjustment_payload,
    create_member_payload, create_membership_payload, create_session_payload,
    create_enrollment_payload, create_badge_award_payload, create_showcase_payload,
    create_showcase_entry_payload, create_accept_payload, create_score_payload,
    create_clock_payload,
)
from .test_users import (
    TEST_USERS, make_center_admin_headers, make_instructor_headers, make_guardian_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# ─── Atomic creation helpers ──────────────────────────────────────────
def create_center(device_count=50, ratio=10, **overrides):
    res = api_client.create_center(
        create_center_payload(device_count=device_count,
                              min_student_instructor_ratio=ratio, **overrides),
        ADMIN,
    )
    return get_success_data(res)


def create_program(min_age=4, max_age=18, drop_in_fee_cents=4000, **overrides):
    res = api_client.create_program(
        create_program_payload(min_age=min_age, max_age=max_age,
                              drop_in_fee_cents=drop_in_fee_cents, **overrides),
        ADMIN,
    )
    return get_success_data(res)


def create_belt_level(program_id, rank=1, prereq_belt_level_id=None,
                      required_badge_count=0, **overrides):
    extra = dict(overrides)
    if prereq_belt_level_id is not None:
        extra["prereq_belt_level_id"] = prereq_belt_level_id
    res = api_client.create_belt_level(
        create_belt_level_payload(program_id, rank=rank,
                                 required_badge_count=required_badge_count, **extra),
        ADMIN,
    )
    return get_success_data(res)


def create_badge(belt_level_id, name="Loops"):
    res = api_client.create_badge(create_badge_payload(belt_level_id, name=name), ADMIN)
    return get_success_data(res)


def create_guardian(**overrides):
    res = api_client.create_guardian(create_guardian_payload(**overrides), ADMIN)
    return get_success_data(res)


def credit_wallet(guardian_id, amount_cents, reason="seed"):
    res = api_client.adjust_wallet(
        guardian_id, create_wallet_adjustment_payload(amount_cents, reason), ADMIN
    )
    return get_success_data(res)


def create_member(guardian_id, program_id, birth_date="2016-01-01", **overrides):
    res = api_client.create_member(
        create_member_payload(guardian_id, program_id, birth_date=birth_date, **overrides),
        make_guardian_headers(guardian_id),
    )
    return get_success_data(res)


def create_active_membership(guardian_id, member_id, monthly_fee_cents=8000,
                             included_sessions_per_cycle=8):
    """Create a PENDING membership and activate it. Returns the ACTIVE membership."""
    g_headers = make_guardian_headers(guardian_id)
    created = get_success_data(api_client.create_membership(
        create_membership_payload(member_id, monthly_fee_cents=monthly_fee_cents,
                                 included_sessions_per_cycle=included_sessions_per_cycle),
        g_headers,
    ))
    activated = get_success_data(
        api_client.activate_membership(created["id"], g_headers)
    )
    return activated


def create_open_session(center_id, program_id, **overrides):
    """Create a DRAFT session and open it. Returns (session, version_after_open)."""
    created = get_success_data(api_client.create_session(
        create_session_payload(center_id, program_id, **overrides), ADMIN
    ))
    opened = get_success_data(api_client.open_session(created["id"], ADMIN))
    return opened, opened["version"]


def current_session_version(session_id):
    """Fetch a session's current version (for OCC threading between enrollments)."""
    return get_success_data(api_client.get_session(session_id, ADMIN))["version"]


def enroll_drop_in(guardian_id, session_id, member_id, sibling_index=1,
                   expected_session_version=None):
    """Create a DROP_IN enrollment, threading the current session version if not
    supplied. Returns the enrollment."""
    if expected_session_version is None:
        expected_session_version = current_session_version(session_id)
    res = api_client.create_enrollment(
        create_enrollment_payload(session_id, member_id, expected_session_version,
                                 coverage="DROP_IN", sibling_index=sibling_index),
        make_guardian_headers(guardian_id),
    )
    return get_success_data(res)


def enroll_membership(guardian_id, session_id, member_id, expected_session_version=None):
    """Create a MEMBERSHIP-covered enrollment. Returns the enrollment."""
    if expected_session_version is None:
        expected_session_version = current_session_version(session_id)
    res = api_client.create_enrollment(
        create_enrollment_payload(session_id, member_id, expected_session_version,
                                 coverage="MEMBERSHIP"),
        make_guardian_headers(guardian_id),
    )
    return get_success_data(res)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(create_clock_payload(to_iso8601), ADMIN))


def award_badge(enrollment_id, badge_id):
    res = api_client.create_badge_award(
        create_badge_award_payload(enrollment_id, badge_id), INSTRUCTOR
    )
    return get_success_data(res)


# ─── Tier 2: Catalogue setup ──────────────────────────────────────────
def setup_catalogue(min_age=4, max_age=18, drop_in_fee_cents=4000,
                    device_count=50, ratio=10, required_badge_count=0):
    """Center + program + rank-1 belt. Returns (center, program, belt1)."""
    center = create_center(device_count=device_count, ratio=ratio)
    program = create_program(min_age=min_age, max_age=max_age,
                             drop_in_fee_cents=drop_in_fee_cents)
    belt1 = create_belt_level(program["id"], rank=1, required_badge_count=required_badge_count)
    return center, program, belt1


def setup_guardian_and_member(program_id, birth_date="2016-01-01"):
    """Guardian + one member on the program. Returns (guardian, member)."""
    guardian = create_guardian()
    member = create_member(guardian["id"], program_id, birth_date=birth_date)
    return guardian, member


# ─── Tier 3: Full lifecycle shortcuts ─────────────────────────────────
def setup_open_session_with_drop_in_enrollment(drop_in_fee_cents=4000, wallet_cents=0,
                                               birth_date="2016-01-01", device_count=50,
                                               ratio=10, session_overrides=None):
    """Catalogue + guardian (optionally pre-credited wallet) + member + OPEN
    AFTER_SCHOOL session + one DROP_IN enrollment.

    Returns dict with center, program, belt1, guardian, member, session,
    enrollment.
    """
    center, program, belt1 = setup_catalogue(
        drop_in_fee_cents=drop_in_fee_cents, device_count=device_count, ratio=ratio
    )
    guardian = create_guardian()
    if wallet_cents:
        credit_wallet(guardian["id"], wallet_cents)
    member = create_member(guardian["id"], program["id"], birth_date=birth_date)
    session, _ = create_open_session(center["id"], program["id"], **(session_overrides or {}))
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    return {
        "center": center, "program": program, "belt1": belt1,
        "guardian": guardian, "member": member, "session": session,
        "enrollment": enrollment,
    }


def setup_open_session_with_membership_enrollment(included_sessions_per_cycle=8,
                                                  monthly_fee_cents=8000):
    """Catalogue + guardian + member + ACTIVE membership + OPEN session +
    one MEMBERSHIP enrollment. Returns dict."""
    center, program, belt1 = setup_catalogue()
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    membership = create_active_membership(
        guardian["id"], member["id"],
        monthly_fee_cents=monthly_fee_cents,
        included_sessions_per_cycle=included_sessions_per_cycle,
    )
    session, _ = create_open_session(center["id"], program["id"], format="WEEKLY")
    enrollment = enroll_membership(guardian["id"], session["id"], member["id"])
    return {
        "center": center, "program": program, "belt1": belt1,
        "guardian": guardian, "member": member, "membership": membership,
        "session": session, "enrollment": enrollment,
    }


def fill_session_to_capacity(guardian_id, session_id, member_ids):
    """Enroll each member sequentially (each a sibling) into the session,
    threading session version between calls. Returns the list of enrollments."""
    enrollments = []
    for i, member_id in enumerate(member_ids, start=1):
        enrollments.append(
            enroll_drop_in(guardian_id, session_id, member_id, sibling_index=i)
        )
    return enrollments


def setup_session_near_capacity(effective_capacity, fee_cents=1000):
    """Build a session whose effective_capacity equals `effective_capacity` by
    using device_count == effective_capacity, ratio == effective_capacity,
    device_seats_requested 1, one instructor. Pre-enrolls `effective_capacity`
    members of one guardian (filling it to FULL) plus prepares one extra member.

    Returns dict with center, program, guardian, members (filling list),
    extra_member, session.
    """
    center = create_center(device_count=effective_capacity, ratio=effective_capacity)
    program = create_program(drop_in_fee_cents=fee_cents)
    create_belt_level(program["id"], rank=1, required_badge_count=0)
    guardian = create_guardian()
    members = [create_member(guardian["id"], program["id"])
               for _ in range(effective_capacity)]
    extra_member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(
        center["id"], program["id"], device_seats_requested=1, assigned_instructor_count=1
    )
    fill_session_to_capacity(guardian["id"], session["id"],
                             [m["id"] for m in members])
    return {
        "center": center, "program": program, "guardian": guardian,
        "members": members, "extra_member": extra_member, "session": session,
    }


# ─── Tier 5: Showcase lifecycle helpers ───────────────────────────────
def setup_open_showcase(min_belt_rank=1, capacity=10,
                        starts_at="2026-05-11T09:00:00Z",
                        entry_deadline_at="2026-05-10T12:00:00Z"):
    """Catalogue + guardian + member + OPEN showcase. Returns dict with center,
    program, belt1, guardian, member, showcase, showcase_version_after_open."""
    center, program, belt1 = setup_catalogue()
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    created = get_success_data(api_client.create_showcase(
        create_showcase_payload(center["id"], program["id"], min_belt_rank=min_belt_rank,
                               capacity=capacity, starts_at=starts_at,
                               entry_deadline_at=entry_deadline_at),
        ADMIN,
    ))
    opened = get_success_data(api_client.open_showcase(created["id"], ADMIN))
    return {
        "center": center, "program": program, "belt1": belt1,
        "guardian": guardian, "member": member, "showcase": opened,
        "showcase_version": opened["version"],
    }


def submit_entry(guardian_id, showcase_id, member_id):
    res = api_client.create_showcase_entry(
        create_showcase_entry_payload(showcase_id, member_id),
        make_guardian_headers(guardian_id),
    )
    return get_success_data(res)


def accept_entry(entry_id, showcase_id):
    """Accept an entry using the showcase's current version (OCC-fresh)."""
    showcase = get_success_data(api_client.get_showcase(showcase_id, ADMIN))
    res = api_client.accept_showcase_entry(
        entry_id, create_accept_payload(showcase["version"]), ADMIN
    )
    return get_success_data(res)


def score_entry(entry_id, score):
    res = api_client.score_showcase_entry(entry_id, create_score_payload(score), ADMIN)
    return get_success_data(res)


def current_showcase_version(showcase_id):
    return get_success_data(api_client.get_showcase(showcase_id, ADMIN))["version"]
