"""Capacity allocation, the waitlist fork-join, seat-count conservation, and week overlap.

Covers difficulty instances for the enrollment fork-join, capacity-state posture vs raw
count, the seat boundary, withdraw/promotion seat conservation, and same-week overlap; plus
the corner consistency instance for immediate count visibility.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_program_payload,
    create_session_payload,
    create_enrollment_payload,
    make_guardian_headers,
    # fixtures
    create_guardian,
    setup_eligible_child,
    setup_open_session_with_offering,
    setup_offering_at_capacity,
    setup_confirmed_plus_waitlisted,
    get_offering,
    get_enrollment,
    enroll_child,
)

DIRECTOR = TEST_USERS["program_director_headers"]


# ---------------------------------------------------------------------------
# Consistency: immediate enrolled_count visibility after confirm (corner)
# ---------------------------------------------------------------------------
def test_enrolled_count_visible_immediately_after_confirm(api):
    """PRD §2.5: "Whenever an operation changes the underlying facts, the system re-runs
    the relevant reconciliation so these derived values stay in agreement, and it does so
    immediately within the same operation rather than on a delayed schedule."
    PRD §3.4: "The offering re-runs its count reconciliation so enrolled_count rises by one
    and capacity_state is recomputed."

    Design: Corner/consistency_model/immediate_visibility_of_enrolled_count_after_confirm
    """
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    scene = setup_open_session_with_offering(
        program_overrides={"name": "Im Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"weekly_capacity": 5, "base_weekly_tuition_cents": 15000},
    )
    enroll_child(gid, eligible["child"]["id"], scene["offering"]["id"], scene["offering"]["version"])
    data = validate_success(api.get_weekly_offering(scene["offering"]["id"], DIRECTOR), 200)
    assert data["enrolled_count"] == 1, f"expected enrolled_count 1, got {data['enrolled_count']}"
    assert data["capacity_state"] == "AVAILABLE", (
        f"capacity 5 with 1 enrolled must be AVAILABLE, got {data['capacity_state']}"
    )


# ---------------------------------------------------------------------------
# Capacity-state posture vs raw count (difficulty dual-variant)
# ---------------------------------------------------------------------------
def test_capacity_state_flips_full_while_count_rises_via_waitlist(api):
    """PRD §2.8: "An offering is AVAILABLE while its confirmed count is below its session's
    weekly_capacity and FULL once the confirmed count reaches or exceeds it. ... a request
    that arrives while a seat remains is confirmed, and one that arrives when the week is
    full is waitlisted."
    PRD §3.4: "the offering's reconciliation raises waitlist_count by one".

    Design: Difficulty/dual_variant_calc/capacity_state_posture_vs_offering_count
    """
    # Capacity 1: first child confirms (FULL), second waitlists.
    scene = setup_offering_at_capacity(capacity=1, session_overrides={"weekly_capacity": 1})
    gid = scene["guardian"]["id"]
    waitlister = setup_eligible_child(
        guardian_id=gid, child_overrides={"first_name": "Waiter", "birth_date": "2016-05-01"}
    )
    ver = get_offering(scene["offering"]["id"])["version"]
    eb = enroll_child(gid, waitlister["child"]["id"], scene["offering"]["id"], ver)
    assert eb["status"] == "WAITLISTED", f"second enroll on full week must waitlist, got {eb['status']}"
    data = validate_success(api.get_weekly_offering(scene["offering"]["id"], DIRECTOR), 200)
    assert data["enrolled_count"] == 1, f"expected enrolled_count 1, got {data['enrolled_count']}"
    assert data["waitlist_count"] == 1, f"expected waitlist_count 1, got {data['waitlist_count']}"
    assert data["capacity_state"] == "FULL", f"expected FULL, got {data['capacity_state']}"


# ---------------------------------------------------------------------------
# Seat boundary: last seat confirms, next waitlists (difficulty boundary)
# ---------------------------------------------------------------------------
def test_last_seat_confirms_then_next_waitlists_at_capacity_two(api):
    """PRD §2.8: "An offering is AVAILABLE while its confirmed count is below its session's
    weekly_capacity and FULL once the confirmed count reaches or exceeds it."
    PRD §3.4: "when the week is already full it lands WAITLISTED ... the new enrollment
    receives a waitlist_rank equal to its position among waitlisted siblings ordered by
    creation time ascending (so the first to join holds rank 1)."

    Design: Difficulty/boundary_precision_check/capacity_last_seat_confirm_then_next_waitlists
    """
    # Capacity 2: confirm two, third must waitlist at rank 1.
    scene = setup_offering_at_capacity(capacity=2, session_overrides={"weekly_capacity": 2})
    gid = scene["guardian"]["id"]
    third = setup_eligible_child(
        guardian_id=gid, child_overrides={"first_name": "Third", "birth_date": "2016-06-01"}
    )
    ver = get_offering(scene["offering"]["id"])["version"]
    e3 = enroll_child(gid, third["child"]["id"], scene["offering"]["id"], ver)
    assert e3["status"] == "WAITLISTED", f"3rd enroll at capacity 2 must waitlist, got {e3['status']}"
    assert e3["waitlist_rank"] == 1, f"first waitlisted must be rank 1, got {e3['waitlist_rank']}"
    data = validate_success(api.get_weekly_offering(scene["offering"]["id"], DIRECTOR), 200)
    assert data["enrolled_count"] == 2, f"expected enrolled_count 2, got {data['enrolled_count']}"


# ---------------------------------------------------------------------------
# Fork-join: withdraw frees a seat and promotes the waitlist head (difficulty)
# ---------------------------------------------------------------------------
def test_withdraw_confirmed_promotes_waitlist_head(api):
    """PRD §3.4: "if any enrollment is waitlisted on that offering, the head of the line —
    the one with the lowest waitlist_rank, equivalently the earliest by creation time — is
    automatically promoted from WAITLISTED to CONFIRMED, has its waitlist_rank cleared to
    null, and is given a freshly computed provisional_tuition_cents and a draft invoice
    line."

    Design: Difficulty/non_linear_state_machine/enrollment_fork_join_waitlist_promotion
    """
    scene = setup_confirmed_plus_waitlisted()
    gid = scene["guardian"]["id"]
    gh = make_guardian_headers(gid)
    # Withdraw the CONFIRMED child A; waitlisted child B should be promoted.
    validate_success(api.withdraw_enrollment(scene["enrollment_a"]["id"], gh), 200)
    promoted = get_enrollment(scene["enrollment_b"]["id"], guardian_id=gid)
    assert promoted["status"] == "CONFIRMED", f"waitlist head must be promoted to CONFIRMED, got {promoted['status']}"
    assert promoted["waitlist_rank"] is None, f"promoted enrollment waitlist_rank must be null, got {promoted['waitlist_rank']}"
    withdrawn = get_enrollment(scene["enrollment_a"]["id"], guardian_id=gid)
    assert withdrawn["status"] == "WITHDRAWN", f"withdrawn enrollment must be WITHDRAWN, got {withdrawn['status']}"


# ---------------------------------------------------------------------------
# Seat-count conservation under withdraw-then-promotion (difficulty compensating)
# ---------------------------------------------------------------------------
def test_withdraw_then_promotion_conserves_seat_count(api):
    """PRD §3.4: "the offering's reconciliation decrements enrolled_count, freeing a seat.
    Second, if any enrollment is waitlisted on that offering, the head of the line ... is
    automatically promoted from WAITLISTED to CONFIRMED".
    PRD §2.8: capacity is the scarce resource; one out, one in keeps the seat filled.

    Design: Difficulty/compensating_invariant/withdraw_promotion_conserves_offering_seat_count
    """
    scene = setup_confirmed_plus_waitlisted()
    gid = scene["guardian"]["id"]
    gh = make_guardian_headers(gid)
    validate_success(api.withdraw_enrollment(scene["enrollment_a"]["id"], gh), 200)
    data = validate_success(api.get_weekly_offering(scene["offering"]["id"], DIRECTOR), 200)
    assert data["enrolled_count"] == 1, f"seat count must be conserved at 1, got {data['enrolled_count']}"
    assert data["waitlist_count"] == 0, f"waitlist must drain to 0 after promotion, got {data['waitlist_count']}"
    promoted = get_enrollment(scene["enrollment_b"]["id"], guardian_id=gid)
    assert promoted["status"] == "CONFIRMED", f"promoted child must be CONFIRMED, got {promoted['status']}"


# ---------------------------------------------------------------------------
# Same-week overlap on one child across two sessions (difficulty temporal)
# ---------------------------------------------------------------------------
def test_same_week_overlap_for_one_child_rejected(api):
    """PRD §3.4: "The child must not already hold a CONFIRMED or WAITLISTED enrollment in
    another weekly offering whose seven-day week window overlaps this one — a child cannot
    be in two camps the same week ... — and a clash yields ERR_WEEK_OVERLAP_CHILD."

    Design: Difficulty/resource_temporal_overlap/child_week_overlap_same_week_rejected
    """
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    gh = make_guardian_headers(gid)
    # Two different sessions, each with an offering for the SAME week_start.
    program = api_client.create_program(create_program_payload(name="Ov Camp"), DIRECTOR).json()["data"]
    sa = api_client.create_session(create_session_payload(program["id"], title="OvA"), DIRECTOR).json()["data"]
    sb = api_client.create_session(create_session_payload(program["id"], title="OvB"), DIRECTOR).json()["data"]
    wa = api_client.create_weekly_offering({"session_id": sa["id"], "week_start": "2026-06-08"}, DIRECTOR).json()["data"]
    wb = api_client.create_weekly_offering({"session_id": sb["id"], "week_start": "2026-06-08"}, DIRECTOR).json()["data"]
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(sa["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(sb["id"], DIRECTOR), 200)
    # Confirm on A.
    enroll_child(gid, eligible["child"]["id"], wa["id"], get_offering(wa["id"])["version"])
    # Attempt same week on B -> overlap.
    ver_b = get_offering(wb["id"])["version"]
    resp = api.create_enrollment(create_enrollment_payload(eligible["child"]["id"], wb["id"], ver_b), gh)
    validate_error(resp, ApiErrorId.ERR_WEEK_OVERLAP_CHILD.value)
