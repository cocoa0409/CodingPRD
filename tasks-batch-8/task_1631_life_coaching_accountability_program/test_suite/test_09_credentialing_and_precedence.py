"""Cross-entity credential gates and validation-order precedence pairs."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_session,
    create_client,
    create_coach,
    create_fit_approved_enrollment,
    create_tier,
    get_coach,
    get_enrollment,
    get_session,
    get_success_data,
    make_client_headers,
    make_coach_headers,
    pause_enrollment,
    set_clock,
    setup_active_enrollment,
    setup_coach_pair,
    setup_multi_client_active_enrollments,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import complete_discovery_call_with_fit, create_enrollment_payload

PM = TEST_USERS["practice_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
# session_completion_gated_by_coach_credential
# ---------------------------------------------------------------------------

def _setup_session_under_expiring_coach(api):
    """Coach credential expires 2026-08-20; enrollment ACTIVE 2026-08-03;
    one session scheduled 2026-08-25 (inside the 56-day window)."""
    ctx = setup_active_enrollment(
        coach_overrides={"credential_expires_on": "2026-08-20"})
    sess = book_session(
        ctx["enrollment"]["id"], ctx["client"],
        scheduled_start="2026-08-25T10:00:00Z")
    return ctx, sess


def test_credential_expiry_blocks_session_completion(api):
    """PRD §3.1: "once the current UTC date reaches `credential_expires_on`,
    the credential becomes `EXPIRED` on its own, again advancing `version`.
    Expiry performs no session cascade — already-completed sessions stand,
    and sessions still `SCHEDULED` remain on the books, but they cannot be
    completed while the credential is not `VERIFIED`; the gate of §2.7 stops
    them at completion time."

    Design: Difficulty/cross_entity_state_dependency/session_completion_gated_by_coach_credential
    """
    ctx, sess = _setup_session_under_expiring_coach(api)
    set_clock("2026-08-25T10:30:00Z")  # past the 2026-08-20 expiry
    assert get_coach(ctx["coach_a"]["id"])["credential_status"] == "EXPIRED"
    resp = api.complete_session(
        sess["id"], make_coach_headers(ctx["coach_a"]["id"]))
    validate_error(resp, ApiErrorId.ERR_COACH_NOT_CREDENTIALED)


def test_credential_expiry_leaves_scheduled_session_on_the_books(api):
    """PRD §3.1: "Expiry performs no session cascade — already-completed
    sessions stand, and sessions still `SCHEDULED` remain on the books".
    PRD §2.7: "A coach is delivery-eligible only while the credential stands
    `VERIFIED` and ethics stands `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/session_completion_gated_by_coach_credential
    """
    ctx, sess = _setup_session_under_expiring_coach(api)
    set_clock("2026-08-25T10:30:00Z")
    resp = api.complete_session(
        sess["id"], make_coach_headers(ctx["coach_a"]["id"]))
    validate_error(resp, ApiErrorId.ERR_COACH_NOT_CREDENTIALED)
    assert get_session(sess["id"])["session_status"] == "SCHEDULED", \
        "expiry performs no cascade; the session remains SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
# state_beats_business_temporal_on_paused_booking
# ---------------------------------------------------------------------------

def _setup_paused_enrollment_with_conflicting_slot(api):
    """Enrollment ES1 PAUSED; enrollment ES2 (same coach) holds a SCHEDULED
    session at 2026-08-10T10:00Z 60m, occupying [10:00, 11:15)."""
    ctx = setup_multi_client_active_enrollments(2)
    client_s1, client_s2 = ctx["clients"]
    enr_s1, enr_s2 = ctx["enrollments"]
    book_session(enr_s2["id"], client_s2,
                 scheduled_start="2026-08-10T10:00:00Z")
    pause_enrollment(enr_s1["id"], client_s1)
    return ctx


def test_paused_booking_into_overlapping_slot_reports_state_error(api):
    """PRD §2.11: "Checks on any request run in a fixed order, and the first
    failure wins."
    PRD §2.11: "Fourth, the target's state must permit the operation —
    booking a session additionally requires the parent enrollment to be
    `ACTIVE`, and a habit check-in requires its goal to be `OPEN` — else
    `ERR_INVALID_STATE` (HTTP 409)." The state check precedes the business
    sequence that contains session overlap (`ERR_SESSION_OVERLAP`).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_paused_booking
    """
    ctx = _setup_paused_enrollment_with_conflicting_slot(api)
    enr_s1 = ctx["enrollments"][0]
    client_s1 = ctx["clients"][0]
    resp = api.book_session(
        enr_s1["id"],
        {"scheduled_start": "2026-08-10T10:30:00Z", "duration_minutes": 60},
        make_client_headers(client_s1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_paused_booking_leaves_enrollment_and_calendar_unchanged(api):
    """PRD §2.11: "Checks on any request run in a fixed order, and the first
    failure wins." PRD §3.4: "Booking requires the enrollment's
    `lifecycle_status` to stand `ACTIVE` (otherwise `ERR_INVALID_STATE`)" —
    the rejected booking mutates nothing.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_paused_booking
    """
    ctx = _setup_paused_enrollment_with_conflicting_slot(api)
    enr_s1, enr_s2 = ctx["enrollments"]
    client_s1 = ctx["clients"][0]
    resp = api.book_session(
        enr_s1["id"],
        {"scheduled_start": "2026-08-10T10:30:00Z", "duration_minutes": 60},
        make_client_headers(client_s1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_enrollment(enr_s1["id"])["lifecycle_status"] == "PAUSED"
    # The other enrollment's session is untouched.
    data, _meta = validate_paginated(
        api.list_enrollment_sessions(enr_s2["id"], PM))
    assert len(data) == 1
    assert data[0]["session_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
# business_safety_beats_business_fiscal_on_enrollment
# ---------------------------------------------------------------------------

def _setup_refer_out_call(api):
    """Discovery call COMPLETED with an OUTSIDE_SCOPE fit assessment
    (computed outcome REFER_OUT)."""
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier()
    fa = complete_discovery_call_with_fit(
        client, coach_a, coach_b, scope_fit="OUTSIDE_SCOPE", commitment_score=40)
    return coach_a, client, tier, fa


def test_refer_out_blocks_enrollment_despite_invalid_payment_plan(api):
    """PRD §2.11: "Business rules follow, in this exact sequence: coach
    credentialing (`ERR_COACH_NOT_CREDENTIALED`); the fit gate
    (`ERR_FIT_NOT_ESTABLISHED`); session overlap (`ERR_SESSION_OVERLAP`);
    discovery-call overlap (`ERR_DISCOVERY_CALL_OVERLAP`); the program window
    (`ERR_OUTSIDE_PROGRAM_WINDOW`); the reschedule cap
    (`ERR_RESCHEDULE_CAP_REACHED`); session-credit availability
    (`ERR_NO_SESSIONS_REMAINING`); coach capacity (`ERR_COACH_CAPACITY_FULL`);
    cohort joinability (`ERR_COHORT_NOT_JOINABLE`); uniqueness
    (`ERR_DUPLICATE_RESOURCE`); segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`); tier retirement (`ERR_TIER_RETIRED`);
    payment-plan shape (`ERR_PAYMENT_PLAN_INVALID`); and the refund
    precondition (`ERR_REFUND_NOT_ALLOWED`)." The fit gate precedes the
    payment-plan check, so a request failing both reports the fit gate.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_enrollment
    """
    coach_a, client, tier, fa = _setup_refer_out_call(api)
    assert fa["outcome"] == "REFER_OUT"
    resp = api.create_enrollment(
        create_enrollment_payload(
            client["id"], coach_a["id"], tier["id"], fa["_call"]["id"],
            installment_count=5),  # exceeds installment_count_allowed 3
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FIT_NOT_ESTABLISHED)


def test_refer_out_alone_blocks_enrollment(api):
    """PRD §3.3: "Creation is rejected with `ERR_FIT_NOT_ESTABLISHED` unless
    that call carries a fit assessment whose `outcome` is `PROCEED`; a
    `REFER_OUT` outcome permanently blocks enrollment from that call."
    PRD §3.2: "The server stamps `assessor_coach_id` with the acting coach
    and computes the `outcome` at creation: `OUTSIDE_SCOPE` forces
    `REFER_OUT`, and `WITHIN_SCOPE` forces `PROCEED`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_enrollment
    """
    coach_a, client, tier, fa = _setup_refer_out_call(api)
    assert fa["outcome"] == "REFER_OUT", "OUTSIDE_SCOPE forces REFER_OUT"
    resp = api.create_enrollment(
        create_enrollment_payload(
            client["id"], coach_a["id"], tier["id"], fa["_call"]["id"],
            installment_count=1),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FIT_NOT_ESTABLISHED)
