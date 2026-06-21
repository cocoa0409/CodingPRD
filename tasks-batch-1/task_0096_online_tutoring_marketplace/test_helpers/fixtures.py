"""Composite setup helpers for the online tutoring marketplace.

Most interesting claims require the system to be walked through several API
calls before the behavior under test can even be reached: the clock must be set,
a commission policy activated, a tutor verified and tagged to a subject, a parent
funded with a student, and (for settlement/refund tests) a lesson booked,
delivered, and confirmed. These helpers encapsulate those multi-step chains so
the tests can focus on a single assertion.

Every helper uses get_success_data() (the lenient validator) for its setup calls
so that a broken precondition surfaces as a clear "Setup step failed" error
rather than a confusing downstream assertion failure.

Identity threading: after a Tutor or ParentAccount is created, every
ownership-gated call uses make_tutor_headers(tutor_id) /
make_parent_headers(parent_id) with the real entity id — never the shared
placeholder constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_booking_payload,
    create_commission_policy_payload,
    create_credential_payload,
    create_parent_account_payload,
    create_refund_case_payload,
    create_student_payload,
    create_subject_payload,
    create_subject_tag_payload,
    create_tutor_payload,
)
from .test_users import (
    make_parent_headers,
    make_tutor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["trust_officer_headers"]
ARBITER = TEST_USERS["arbiter_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: atomic building blocks
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the deterministic server clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def create_active_policy(**overrides):
    """Create a commission policy and activate it. Returns the active policy."""
    policy = get_success_data(
        api_client.create_commission_policy(
            create_commission_policy_payload(**overrides), ADMIN
        )
    )
    return get_success_data(api_client.activate_commission_policy(policy["id"], ADMIN))


def create_subject(**overrides):
    """Create a subject. Returns the subject."""
    return get_success_data(
        api_client.create_subject(create_subject_payload(**overrides), ADMIN)
    )


def create_tutor(**overrides):
    """Register a tutor (UNVERIFIED). Returns the tutor."""
    return get_success_data(api_client.create_tutor(create_tutor_payload(**overrides), ADMIN))


def create_verified_tutor(subject_id, base_hourly_rate_cents=6000, kind="DEGREE"):
    """Register a tutor and verify it via a credential on the given subject.
    Returns (tutor, credential). The credential ends VERIFIED, the tutor VERIFIED.
    """
    tutor = create_tutor(base_hourly_rate_cents=base_hourly_rate_cents)
    t_headers = make_tutor_headers(tutor["id"])
    cred = get_success_data(
        api_client.create_credential(
            create_credential_payload(tutor["id"], subject_id, kind=kind), t_headers
        )
    )
    get_success_data(api_client.start_review_credential(cred["id"], OFFICER))
    get_success_data(api_client.verify_credential(cred["id"], OFFICER))
    tutor = get_success_data(api_client.get_tutor(tutor["id"], ADMIN))
    return tutor, cred


def propose_and_approve_tag(tutor_id, subject_id, subject_rate_cents=None):
    """Propose a subject tag (as the tutor) and approve it (as the officer).
    Returns the APPROVED tag."""
    t_headers = make_tutor_headers(tutor_id)
    overrides = {}
    if subject_rate_cents is not None:
        overrides["subject_rate_cents"] = subject_rate_cents
    tag = get_success_data(
        api_client.create_subject_tag(
            create_subject_tag_payload(tutor_id, subject_id, **overrides), t_headers
        )
    )
    return get_success_data(api_client.approve_subject_tag(tag["id"], OFFICER))


def create_funded_parent(amount_cents=100000):
    """Register a parent account and deposit funds. Returns the parent."""
    parent = get_success_data(
        api_client.create_parent_account(create_parent_account_payload(), TEST_USERS["parent_headers"])
    )
    p_headers = make_parent_headers(parent["id"])
    if amount_cents > 0:
        get_success_data(api_client.deposit(parent["id"], {"amount_cents": amount_cents}, p_headers))
    return get_success_data(api_client.get_parent_account(parent["id"], p_headers))


def create_student(parent_id, **overrides):
    """Register a student under a parent. Returns the student."""
    p_headers = make_parent_headers(parent_id)
    return get_success_data(
        api_client.create_student(parent_id, create_student_payload(**overrides), p_headers)
    )


# ---------------------------------------------------------------------------
# Tier 1: the standard marketplace baseline
# ---------------------------------------------------------------------------
def setup_marketplace(
    clock=DEFAULT_CLOCK,
    base_hourly_rate_cents=6000,
    subject_rate_cents=None,
    requires_credential=False,
    wallet_cents=100000,
    with_policy=True,
):
    """Active policy + one subject + one VERIFIED+tagged tutor + one funded
    parent + one student. The most common precondition.

    Returns a dict:
      { policy, subject, tutor, credential, tag, parent, student,
        tutor_headers, parent_headers }
    """
    set_clock(clock)
    policy = create_active_policy() if with_policy else None
    subject = create_subject(requires_credential=requires_credential)
    tutor, cred = create_verified_tutor(subject["id"], base_hourly_rate_cents=base_hourly_rate_cents)
    tag = propose_and_approve_tag(tutor["id"], subject["id"], subject_rate_cents=subject_rate_cents)
    parent = create_funded_parent(amount_cents=wallet_cents)
    student = create_student(parent["id"])
    return {
        "policy": policy,
        "subject": subject,
        "tutor": tutor,
        "credential": cred,
        "tag": tag,
        "parent": parent,
        "student": student,
        "tutor_headers": make_tutor_headers(tutor["id"]),
        "parent_headers": make_parent_headers(parent["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2/3: bookings → sessions → settlements
# ---------------------------------------------------------------------------
def create_booking(mk, scheduled_start, planned_minutes=60, student_id=None):
    """Create a booking inside a setup_marketplace() result `mk`.
    Returns the booking."""
    sid = student_id or mk["student"]["id"]
    return get_success_data(
        api_client.create_booking(
            create_booking_payload(
                mk["parent"]["id"], sid, mk["tutor"]["id"], mk["subject"]["id"],
                scheduled_start, planned_minutes=planned_minutes,
            ),
            mk["parent_headers"],
        )
    )


def deliver_booking(mk, booking_id, actual_minutes, clock_at):
    """Advance the clock to `clock_at` and deliver the booking. Returns the
    created Session."""
    set_clock(clock_at)
    return get_success_data(
        api_client.deliver_booking(booking_id, {"actual_minutes": actual_minutes}, mk["tutor_headers"])
    )


def confirm_session(mk, session_id):
    """Confirm a reported session (settles it). Returns the updated Session."""
    return get_success_data(api_client.confirm_session(session_id, mk["parent_headers"]))


def book_deliver_confirm(
    mk, scheduled_start, deliver_at, planned_minutes=60, actual_minutes=60, student_id=None
):
    """Create a booking, deliver it, and confirm it (full settlement).
    Returns (booking, session)."""
    booking = create_booking(mk, scheduled_start, planned_minutes=planned_minutes, student_id=student_id)
    session = deliver_booking(mk, booking["id"], actual_minutes, deliver_at)
    confirm_session(mk, session["id"])
    booking = get_success_data(api_client.get_booking(booking["id"], mk["parent_headers"]))
    session = get_success_data(api_client.get_session(session["id"], mk["parent_headers"]))
    return booking, session


def consume_trial_slot(mk, scheduled_start="2026-06-02T08:00:00Z", deliver_at="2026-06-02T09:00:00Z"):
    """Burn the (student, tutor) trial slot with a delivered+confirmed first
    booking so the next booking for the pair is a standard (non-trial) session.
    Returns (trial_booking, trial_session)."""
    return book_deliver_confirm(
        mk, scheduled_start, deliver_at, planned_minutes=30, actual_minutes=30
    )


def settlement_for_session(session_id, headers=None):
    """Fetch the (single) Settlement linked to a session via the list filter.
    Returns the settlement dict or None."""
    h = headers or OFFICER
    data, _ = _list(api_client.list_settlements(h, params={"session_id": session_id}))
    return data[0] if data else None


def _list(response):
    body = get_success_data(response)
    # get_success_data returns the `data` payload (a list for list endpoints).
    # The full meta is not returned here; callers that need meta use the raw
    # validate_paginated path in the test itself.
    return body, None


# ---------------------------------------------------------------------------
# Tier 3: a settled standard session ready for a refund case
# ---------------------------------------------------------------------------
def setup_confirmed_standard_session(
    base_hourly_rate_cents=6000,
    subject_rate_cents=None,
    std_planned_minutes=60,
    std_actual_minutes=60,
):
    """Marketplace baseline + a consumed trial slot + one CONFIRMED standard
    session (settled). Returns (mk, std_booking, std_session).
    """
    mk = setup_marketplace(base_hourly_rate_cents=base_hourly_rate_cents, subject_rate_cents=subject_rate_cents)
    consume_trial_slot(mk)
    std_booking, std_session = book_deliver_confirm(
        mk,
        "2026-06-03T10:00:00Z",
        "2026-06-03T11:00:00Z",
        planned_minutes=std_planned_minutes,
        actual_minutes=std_actual_minutes,
    )
    return mk, std_booking, std_session


def open_refund_case(mk, session_id, claimed_amount_cents):
    """Open a refund case against a session. Returns the RefundCase."""
    return get_success_data(
        api_client.create_refund_case(
            create_refund_case_payload(session_id, claimed_amount_cents), mk["parent_headers"]
        )
    )


def setup_open_refund_case(claimed_amount_cents=2000, std_planned_minutes=60):
    """Marketplace + consumed trial + CONFIRMED standard session + an open
    RefundCase in PARENT_PROPOSED. Returns (mk, std_session, refund_case).
    """
    mk, std_booking, std_session = setup_confirmed_standard_session(
        std_planned_minutes=std_planned_minutes
    )
    case = open_refund_case(mk, std_session["id"], claimed_amount_cents)
    return mk, std_session, case


def setup_countered_refund_case(claimed_amount_cents=2000, counter_amount_cents=800):
    """An open RefundCase that the tutor has countered once (now TUTOR_COUNTERED,
    round_count still 0). Returns (mk, std_session, open_case, case_after_counter)
    so callers can use the pre-counter version (stale) and post-counter version.
    """
    mk, std_session, case = setup_open_refund_case(claimed_amount_cents=claimed_amount_cents)
    countered = get_success_data(
        api_client.counter_refund_case(
            case["id"],
            {"counter_amount_cents": counter_amount_cents, "expected_refund_case_version": case["version"]},
            mk["tutor_headers"],
        )
    )
    return mk, std_session, case, countered
