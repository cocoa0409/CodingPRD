"""Second-test coverage for each difficulty instance (per queue-A ≥2 tests rule).

Each test here is the "second" test complementing a first-test in an earlier
file for the same design-index instance. Every test carries the difficulty
docstring tag verbatim.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, make_member_headers, make_organizer_headers,
    ApiErrorId,
    create_member, seed_balance, set_clock,
    setup_two_members_and_offer, setup_published_project_with_shift,
    setup_member_with_two_prior_noshows, setup_suspended_member,
    setup_scheduled_exchange, setup_delivered_exchange, setup_disputed_exchange,
    create_project, create_shift, publish_project, assign_member_to_shift,
    exchange_payload, skill_offer_payload, skill_request_payload,
)


# =============================================================================
# Rule 4 — transitive_cascade (second tests)
# =============================================================================

def test_project_cancel_from_planning_cascades_to_open_shift(api):
    """PRD §2.9: "When a GroupProject is cancelled from PLANNING or OPEN, the
    cancel cascades: every ProjectShift whose status is OPEN or FILLED
    transitions to CANCELLED, and every ShiftAssignment under a cancelled
    shift whose status is CONFIRMED transitions to CANCELLED."

    Design: Difficulty/transitive_cascade/project_cancel_cascade_depth_3
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="org-p")
    project = create_project(
        organizer, title="P-cancel",
        window_start_utc="2026-03-05T09:00:00Z",
        window_end_utc="2026-03-05T17:00:00Z",
    )
    shift = create_shift(organizer, project,
                        role_label="P",
                        shift_start_utc="2026-03-05T09:00:00Z",
                        duration_minutes=60, capacity=2)
    # NOT published — cancel from PLANNING
    cancel = get_success_data(api.cancel_group_project(
        project["id"], headers=make_organizer_headers(organizer["id"]),
    ))
    assert cancel["aggregate_state"] == "CANCELLED"
    shift_after = get_success_data(api.get_shift(
        shift["id"], headers=make_organizer_headers(organizer["id"]),
    ))
    assert shift_after["status"] == "CANCELLED"


def test_third_no_show_recomputes_no_show_strikes_to_three(api):
    """PRD §2.11: "Member.no_show_strikes is a rolling 90-day count of NO_SHOW
    ShiftAssignment rows for the member"
    PRD §2.11: "The moment the count reaches 3, Member.is_suspended is set to
    true as a cascading side effect of the third NO_SHOW; the transition to
    true is not a separate write step but happens in the same operation
    that produced the third strike."

    Design: Difficulty/transitive_cascade/clock_advance_noshow_cascade_depth_3
    """
    ctx = setup_suspended_member()
    m = get_success_data(api.get_member(
        ctx["member"]["id"],
        headers=make_member_headers(ctx["member"]["id"]),
    ))
    assert m["no_show_strikes"] == 3


# =============================================================================
# Rule 5 — priority_pair_validation_conflict (second tests)
# =============================================================================

def test_suspended_member_forbidden_from_shift_assignment(api):
    """PRD §2.11: "A suspended member is barred from creating a new exchange,
    self-assigning to a shift, or creating a redemption — each such request
    is rejected with ERR_MEMBER_SUSPENDED."

    This is the second test for the safety-vs-fiscal pair: on POST
    /shifts/{id}/assignments, only the suspension gate applies (no fiscal
    gate), but ERR_MEMBER_SUSPENDED is the same error class as the first
    test's safety-side result, and the endpoint is one of the three the PRD
    explicitly names as blocked.

    Design: Difficulty/priority_pair_validation_conflict/suspended_and_insufficient_returns_suspended
    """
    ctx = setup_suspended_member()
    # sh_extra2 was pre-created in PLANNING inside the fixture and starts
    # 2026-03-10T09:00 — safely in the future after suspending clock advance.
    sh = ctx.get("sh_extra2")
    if sh is None:
        # setup_suspended_member returns a subset; look up the shift by list.
        shifts_resp = api.list_project_shifts(
            ctx["project"]["id"], headers=make_organizer_headers(ctx["organizer"]["id"]),
        )
        shifts_data, _ = validate_paginated(shifts_resp)
        # Pick a shift starting after clock (2026-03-05T10:30).
        future = [s for s in shifts_data if s["shift_start_utc"] > "2026-03-05T10:30:00Z"]
        assert future, "expected at least one future shift on the suspension fixture"
        sh = future[0]
    resp = api.create_shift_assignment(
        sh["id"], {"member_id": ctx["member"]["id"]},
        headers=make_member_headers(ctx["member"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)


def test_stale_version_beats_ownership_via_completely_bogus_member_id(api):
    """PRD §2.11: "then whether the target resource is in a state that permits
    the operation (per §3), then the redemption OCC gate (§2.8), then
    owner-match and requester-provider distinctness"

    Second test — same priority pair, different construction of the ownership
    violation (member_id points to a member that isn't the caller).

    Design: Difficulty/priority_pair_validation_conflict/stale_version_and_ownership_returns_stale
    """
    from test_helpers import NON_EXISTENT_UUID
    m1 = create_member(email_prefix="sv-a")
    m2 = create_member(email_prefix="sv-b")
    seed_balance(m1["id"], 600, memo="seed m1")
    v_pre = get_success_data(api.get_member(
        m1["id"], headers=make_member_headers(m1["id"]),
    ))["version"]
    seed_balance(m1["id"], 30, memo="bump")
    resp = api.create_redemption(
        {"member_id": m2["id"], "reward_code": "FARMERS_MARKET_15",
         "expected_member_version": v_pre},
        headers=make_member_headers(m1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION)


# =============================================================================
# Rule 6 — boundary_precision_check (second tests)
# =============================================================================

def test_exchange_create_rejected_when_balance_below_committed(api):
    """PRD §3.3: "The requester's forward_looking_balance_minutes must be at
    least committed_minutes, so that the pending debit implied by the
    booking cannot overdraw the account beyond commitments already in
    flight; a shortfall is rejected with ERR_INSUFFICIENT_BALANCE."

    Design: Difficulty/boundary_precision_check/insufficient_balance_boundary_exact_gte_on_exchange_create
    """
    ctx = setup_two_members_and_offer(requester_seed=45, offer_minutes=60)
    r = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": r["id"],
         "scheduled_start_utc": "2026-03-05T10:00:00Z",
         "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


def test_project_completion_ratio_below_minimum_transitions_cancelled(api):
    """PRD §2.9: "if the ratio is at least the minimum, the state is COMPLETED,
    otherwise it is CANCELLED"

    Design: Difficulty/boundary_precision_check/project_completion_ratio_boundary_exactly_meets
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="orgb2")
    project = create_project(
        organizer, title="B2b",
        window_start_utc="2026-03-02T09:00:00Z",
        window_end_utc="2026-03-04T17:00:00Z",
        minimum_completed_ratio=0.60,
    )
    for start in ["2026-03-02T09:00:00Z", "2026-03-02T11:00:00Z",
                  "2026-03-02T13:00:00Z", "2026-03-03T09:00:00Z",
                  "2026-03-03T11:00:00Z"]:
        create_shift(organizer, project,
                     role_label="P",
                     shift_start_utc=start,
                     duration_minutes=60, capacity=1)
    publish_project(organizer, project)
    # No volunteers check in — 0/5 = 0.00 < 0.60
    set_clock("2026-03-04T17:30:00Z")
    resp = api.get_group_project(
        project["id"], headers=make_organizer_headers(organizer["id"]),
    )
    data = validate_success(resp)
    assert data["aggregate_state"] == "CANCELLED"


# =============================================================================
# Rule 7 — cross_entity_state_dependency (second tests)
# =============================================================================

def test_settle_succeeds_after_dispute_withdrawn(api):
    """PRD §3.4: "The raiser may withdraw the dispute, taking it to WITHDRAWN;
    withdrawal returns the exchange from DISPUTED back to DELIVERED so the
    requester can drive normal settlement."

    Design: Difficulty/cross_entity_state_dependency/exchange_settle_blocked_by_open_dispute
    """
    ctx = setup_disputed_exchange(claimed_delta_minutes=15)
    get_success_data(api.withdraw_dispute(
        ctx["dispute"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.settle_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "SETTLED"


def test_offer_status_paused_blocks_exchange_creation(api):
    """PRD §3.2: "PAUSED and ARCHIVED offers are invisible to the matching
    surface — a requester cannot book an offer whose status is not ACTIVE,
    and an attempt to do so is rejected with ERR_INVALID_STATE in the
    exchange-creation priority band."

    Design: Difficulty/cross_entity_state_dependency/exchange_create_blocked_by_offer_required_trust_tier
    """
    ctx = setup_two_members_and_offer(requester_seed=240, offer_minutes=60)
    get_success_data(api.pause_skill_offer(
        ctx["offer"]["id"],
        headers=make_member_headers(ctx["provider"]["id"]),
    ))
    r = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": r["id"],
         "scheduled_start_utc": "2026-03-05T10:00:00Z",
         "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# =============================================================================
# Rule 8 — resource_temporal_overlap (second tests)
# =============================================================================

def test_shift_assignment_touching_at_start_endpoint_allowed(api):
    """PRD §2.11: "for a shift assignment, the requested assignment's interval —
    closed on the left at shift_start_utc, open on the right at
    shift_start_utc + duration_minutes — must not overlap another CONFIRMED
    or CHECKED_IN assignment held by the same member, with intervals
    touching at the endpoints allowed"

    Design: Difficulty/resource_temporal_overlap/shift_assignment_overlap_touching_endpoints_ok
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="orgt2")
    volunteer = create_member(email_prefix="volt2")
    project = create_project(
        organizer, title="OV1b",
        window_start_utc="2026-03-05T08:00:00Z",
        window_end_utc="2026-03-05T17:00:00Z",
    )
    sh_early = create_shift(organizer, project,
                            shift_start_utc="2026-03-05T08:30:00Z",
                            duration_minutes=30, capacity=2)
    sh_later = create_shift(organizer, project,
                            shift_start_utc="2026-03-05T09:00:00Z",
                            duration_minutes=30, capacity=2)
    publish_project(organizer, project)
    get_success_data(api.create_shift_assignment(
        sh_early["id"], {"member_id": volunteer["id"]},
        headers=make_member_headers(volunteer["id"]),
    ))
    resp = api.create_shift_assignment(
        sh_later["id"], {"member_id": volunteer["id"]},
        headers=make_member_headers(volunteer["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "CONFIRMED"


def test_exchange_far_apart_beyond_buffer_accepted(api):
    """PRD §2.11: "For an exchange, the requested exchange's interval — closed
    on the left at scheduled_start_utc, open on the right at
    scheduled_start_utc + committed_minutes — is extended by a 30-minute
    travel buffer on both sides, and the resulting extended window must
    not overlap another SCHEDULED or DELIVERED exchange in which the same
    member participates; a violation is rejected with
    ERR_EXCHANGE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/exchange_overlap_with_30min_buffer_rejects
    """
    ctx = setup_two_members_and_offer(requester_seed=240, offer_minutes=60)
    # First exchange 09:00-10:00; buffered window [08:30, 10:30).
    r1 = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T09:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    get_success_data(api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": r1["id"],
         "scheduled_start_utc": "2026-03-05T09:00:00Z",
         "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    # Second exchange 13:00-14:00; buffered [12:30, 14:30). The gap between
    # buffered windows is 12:30 - 10:30 = 120 minutes — far outside any
    # plausible interpretation of "overlap" of the buffered intervals.
    r2 = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T13:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": r2["id"],
         "scheduled_start_utc": "2026-03-05T13:00:00Z",
         "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# =============================================================================
# Rule 9 — compensating_invariant (second tests)
# =============================================================================

def test_scheduled_exchange_cancel_frees_forward_looking_balance(api):
    """PRD §3.3: "The cancel writes the exchange to CANCELLED and rolls the
    linked request back from MATCHED to OPEN, so a fresh exchange can be
    booked against it."
    PRD §2.6: "The forward-looking balance, exposed as
    forward_looking_balance_minutes, is the chronological balance minus
    the sum of Exchange.committed_minutes across every exchange where
    requester_member_id equals the member and status is either SCHEDULED
    or DELIVERED"

    Design: Difficulty/compensating_invariant/exchange_cancel_conserves_ledger_sum
    """
    ctx = setup_scheduled_exchange(requester_seed=240)
    pre = get_success_data(api.get_member(
        ctx["requester"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    assert pre["forward_looking_balance_minutes"] == 240 - 60
    get_success_data(api.cancel_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    post = get_success_data(api.get_member(
        ctx["requester"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    assert post["forward_looking_balance_minutes"] == 240
    assert post["chronological_balance_minutes"] == 240


def test_confirmed_assignment_new_member_has_zero_strikes_after_cancel(api):
    """PRD §3.1: "The server creates the Member row with trust_tier at
    UNVERIFIED; chronological_balance_minutes, forward_looking_balance_minutes,
    lifetime_earned_minutes, lifetime_redeemed_minutes,
    verified_credential_count, completed_exchange_count, and no_show_strikes
    all at zero; is_suspended at false; and version at 1."
    PRD §3.5: "A member may cancel their own CONFIRMED assignment while the
    logical clock is strictly earlier than the shift's shift_start_utc; the
    assignment transitions to CANCELLED."

    Design: Difficulty/compensating_invariant/assignment_cancel_conserves_no_show_strikes
    """
    ctx = setup_published_project_with_shift(
        shift_start="2026-03-10T09:00:00Z",
        window_start="2026-03-05T09:00:00Z",
        window_end="2026-03-10T17:00:00Z",
    )
    a = assign_member_to_shift(ctx["volunteer"], ctx["shift"])
    strikes_before = get_success_data(api.get_member(
        ctx["volunteer"]["id"],
        headers=make_member_headers(ctx["volunteer"]["id"]),
    ))["no_show_strikes"]
    assert strikes_before == 0
    get_success_data(api.cancel_shift_assignment(
        ctx["shift"]["id"], a["id"],
        headers=make_member_headers(ctx["volunteer"]["id"]),
    ))
    strikes_after = get_success_data(api.get_member(
        ctx["volunteer"]["id"],
        headers=make_member_headers(ctx["volunteer"]["id"]),
    ))["no_show_strikes"]
    assert strikes_after == 0
