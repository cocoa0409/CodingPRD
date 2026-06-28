"""Optimistic concurrency on reservation create, coach certification gate, and
role / ownership / authentication enforcement.

Queue B: occ stale-version rejection, occ correct-version success + version bump,
coach-not-certified verify, RBAC exclusive-op denial, ownership denial, missing auth.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS,
    make_member_headers, make_coach_headers,
    set_clock, create_coach, create_track, create_unlimited_plan,
    register_member, create_session, create_active_membership, reserve,
)
from test_helpers import api_client

BOX = TEST_USERS["box_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ==========================================================================
# Queue B — cross_cutting / occ_stale_session_version_on_reservation
# ==========================================================================

def test_reserve_with_stale_session_version_rejected(api):
    """PRD §2.6: "If another writer has advanced the session's version since the client read it — for example, because a reservation that landed on the last open seat legitimately superseded the client's earlier view of seat availability by bumping the session version — the create is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412), and the client must re-read the session's current seat state before retrying."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_on_reservation
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    sess_v0 = session["version"]

    m1 = register_member()
    ms1 = create_active_membership(m1["id"], plan["id"])
    m2 = register_member()
    ms2 = create_active_membership(m2["id"], plan["id"])

    # m1 reserves -> session version advances past sess_v0
    reserve(session["id"], m1["id"], sess_v0, membership_id=ms1["id"],
            reservation_kind="MEMBERSHIP")

    # m2 reserves carrying the pre-advance version
    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": m2["id"],
         "membership_id": ms2["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": sess_v0},
        make_member_headers(m2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SESSION_VERSION.value)


# ==========================================================================
# Queue B — cross_cutting / occ_correct_session_version_succeeds
# ==========================================================================

def test_reserve_with_correct_session_version_succeeds_and_bumps_version(api):
    """PRD §2.6: "The server compares this value to the session's current `version`."
    PRD §3.4: "Every successful reservation create increments the session's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_session_version_succeeds
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": session["version"]},
        make_member_headers(member["id"]),
    )
    rv = validate_success(resp, expected_status=201)
    assert rv["status"] == "RESERVED"

    session_after = validate_success(api.get_session(session["id"], BOX))
    assert session_after["seats_reserved"] == 1
    assert session_after["version"] == session["version"] + 1


# ==========================================================================
# Queue B — validations / coach_not_certified_verify_returns_error
# ==========================================================================

def test_non_certified_coach_verify_returns_error(api):
    """PRD §3.6: "Only a certified coach may verify a result: when a `Coach` whose `certified` flag is not set attempts verification, the request is rejected with `ERR_COACH_NOT_CERTIFIED`."

    Design: Corner/validations/coach_not_certified_verify_returns_error
    """
    coach = create_coach(certified=False)
    member = register_member()
    result = validate_success(api.create_benchmark_result(
        {"member_id": member["id"], "benchmark_name": "GRACE",
         "metric_kind": "TIME_SECONDS", "value": 120,
         "recorded_at": "2026-05-01T10:00:00Z"},
        make_member_headers(member["id"]),
    ), expected_status=201)

    resp = api.verify_benchmark_result(result["id"], make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_COACH_NOT_CERTIFIED.value)


# ==========================================================================
# Queue B — rbac / member_cannot_create_membership_plan_forbidden
# ==========================================================================

def test_member_cannot_create_membership_plan(api):
    """PRD §2.1: "A well-formed but insufficiently privileged caller — one whose role is not permitted to perform the requested operation — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_membership_plan_forbidden
    """
    member = register_member()
    resp = api.create_membership_plan(
        {"name": "Sneak", "plan_type": "UNLIMITED", "monthly_fee_cents": 5000},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ==========================================================================
# Queue B — rbac / member_cannot_cancel_other_members_membership_not_owner
# ==========================================================================

def test_member_cannot_cancel_other_members_membership(api):
    """PRD §2.1: "When an entity-backed `Member` attempts to act on a `Membership`, `Reservation`, `BenchmarkResult`, or competition team resource that is not their own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/member_cannot_cancel_other_members_membership_not_owner
    """
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    m_a = register_member()
    m_b = register_member()
    ms_a = create_active_membership(m_a["id"], plan["id"])

    resp = api.cancel_membership(ms_a["id"], make_member_headers(m_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ==========================================================================
# Queue B — rbac / missing_auth_headers_returns_unauthenticated
# ==========================================================================

def test_protected_read_without_auth_rejected(api):
    """PRD §2.1: "A request that omits the required headers or presents them malformed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the sole exception is member self-registration".

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_memberships(ANON)
    error_id = validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_UNAUTHENTICATED.value, ApiErrorId.ERR_FORBIDDEN_ROLE.value],
    )
    assert error_id in (ApiErrorId.ERR_UNAUTHENTICATED.value,
                        ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert resp.status_code in (401, 403)
