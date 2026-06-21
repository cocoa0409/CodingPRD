"""State machines (two-axis membership, reservation amend loop, waitlist, clock-
gated completion) and transitive cascades (settle-resignation -> waitlist offer;
waitlist accept -> membership + initiation chit + balance debit).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_member_headers,
    create_club, create_category, create_and_activate_membership,
    create_membership, activate_membership, post_chit, close_period,
    create_resource, create_reservation, setup_reservation,
    create_waitlist_entry, offer_waitlist_entry, get_category_version,
    get_club_version, set_clock, list_member_chits,
)

_MANAGER = TEST_USERS["club_manager_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine
# ===========================================================================

def test_membership_billing_axis_advances_independently_of_account_axis(api):
    """PRD §2.7: "The two membership axes never share a transition — a member can
    be ACTIVE yet PAST_DUE at the same time, or SUSPENDED yet CURRENT."
    PRD §3.7: "A FINALIZED statement left with total_due_cents greater than zero
    and not yet PAID advances the member's billing axis from CURRENT to PAST_DUE."

    Design: Difficulty/non_linear_state_machine/membership_parallel_account_x_billing_axes
    """
    club = create_club(name="Axis Club")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    # Finalize a statement with unpaid dues 15000 -> billing PAST_DUE.
    close_period(club["id"])

    # Now suspend the still-ACTIVE member: account axis moves, billing axis holds.
    data = validate_success(api.suspend_membership(m["id"], _MANAGER))
    assert data["account_status"] == "SUSPENDED"
    assert data["billing_status"] == "PAST_DUE", (
        f"billing axis should have advanced independently to PAST_DUE, "
        f"got {data['billing_status']}"
    )


def test_membership_billing_advances_while_account_stays_active(api):
    """PRD §2.7: "The two membership axes never share a transition — a member can
    be ACTIVE yet PAST_DUE at the same time, or SUSPENDED yet CURRENT."
    PRD §3.7: "A FINALIZED statement left with total_due_cents greater than zero
    and not yet PAID advances the member's billing axis from CURRENT to PAST_DUE."

    Design: Difficulty/non_linear_state_machine/membership_parallel_account_x_billing_axes
    """
    club = create_club(name="Axis Club 2")
    cat = create_category(club["id"], code="SOCIAL", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=15000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    # One unpaid finalized statement advances billing while the account axis,
    # untouched by finalization, remains ACTIVE.
    close_period(club["id"])

    data = validate_success(api.get_membership(m["id"], _MANAGER))
    assert data["account_status"] == "ACTIVE", f"got {data['account_status']}"
    assert data["billing_status"] == "PAST_DUE", (
        f"billing axis should advance independently of the ACTIVE account axis, "
        f"got {data['billing_status']}"
    )


def test_reservation_amend_confirm_applies_proposed_window(api):
    """PRD §3.4: "Confirming the amend moves the reservation from AMEND_PENDING
    back to CONFIRMED, but only after the overlap is re-checked against the live
    occupancy map ... on success the proposed values become the new starts_at and
    ends_at, and proposed_starts_at and proposed_ends_at are cleared to null."

    Design: Difficulty/non_linear_state_machine/reservation_amend_cycle_loop
    """
    club, cat, m, resource, rsv = setup_reservation(
        kind="COURT", turnaround_minutes=0,
        starts_at="2026-02-01T10:00:00Z", ends_at="2026-02-01T11:00:00Z",
    )
    mh = make_member_headers(m["id"])
    validate_success(api.propose_amend(
        rsv["id"],
        {"proposed_starts_at": "2026-02-01T12:00:00Z",
         "proposed_ends_at": "2026-02-01T13:00:00Z"},
        mh,
    ))
    data = validate_success(api.confirm_amend(rsv["id"], mh))
    assert data["status"] == "CONFIRMED"
    assert data["starts_at"] == "2026-02-01T12:00:00Z", f"got {data['starts_at']}"
    assert data["proposed_starts_at"] is None, (
        f"proposed_starts_at must be cleared to null, got {data['proposed_starts_at']}"
    )


def test_reservation_amend_loop_enters_amend_pending(api):
    """PRD §3.4: "A member proposes a new window for their own CONFIRMED
    reservation, moving it from CONFIRMED to AMEND_PENDING; the request supplies
    proposed_starts_at and proposed_ends_at, which are stored on the reservation
    while the original window continues to be held."

    Design: Difficulty/non_linear_state_machine/reservation_amend_cycle_loop
    """
    club, cat, m, resource, rsv = setup_reservation(
        kind="COURT", turnaround_minutes=0,
        starts_at="2026-02-01T10:00:00Z", ends_at="2026-02-01T11:00:00Z",
    )
    mh = make_member_headers(m["id"])
    data = validate_success(api.propose_amend(
        rsv["id"],
        {"proposed_starts_at": "2026-02-01T12:00:00Z",
         "proposed_ends_at": "2026-02-01T13:00:00Z"},
        mh,
    ))
    assert data["status"] == "AMEND_PENDING"
    assert data["proposed_starts_at"] == "2026-02-01T12:00:00Z", f"got {data['proposed_starts_at']}"
    # Original window remains held.
    assert data["starts_at"] == "2026-02-01T10:00:00Z", f"got {data['starts_at']}"


# ===========================================================================
# Difficulty: transitive_cascade
# ===========================================================================

def test_settle_resignation_frees_seat_and_promotes_waitlist(api):
    """PRD §3.3: "On settlement the freed seat is reclaimed: the category's
    active_member_count is recomputed and now falls by one, and that newly free
    seat cascades to the waitlist — if any WaitlistEntry for this category is in
    WAITING, the earliest by created_at is promoted to OFFERED."

    Design: Difficulty/transitive_cascade/settle_resignation_cascade_seat_to_waitlist_offer
    """
    club = create_club(name="Cascade Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    w = create_waitlist_entry(club["id"], cat["id"], applicant_name="W")
    mh = make_member_headers(m["id"])
    validate_success(api.resign_membership(m["id"], mh))  # balance is 0 (initiation 0)

    data = validate_success(api.settle_resignation(m["id"], _MANAGER))
    assert data["account_status"] == "RESIGNED"

    cat_after = validate_success(api.get_category(cat["id"], _MANAGER))
    assert cat_after["active_member_count"] == 0, f"got {cat_after['active_member_count']}"

    w_after = validate_success(api.get_waitlist_entry(w["id"], _MANAGER))
    assert w_after["status"] == "OFFERED", (
        f"freed seat should cascade to a waitlist offer, got {w_after['status']}"
    )


def test_settle_resignation_frees_seat_count_without_waitlist(api):
    """PRD §3.3: "On settlement the freed seat is reclaimed: the category's
    active_member_count is recomputed and now falls by one."
    PRD §3.3: "A resignation is finalized by a manager through the
    settle-resignation action, moving the account from RESIGNED_PENDING to the
    terminal RESIGNED."

    Design: Difficulty/transitive_cascade/settle_resignation_cascade_seat_to_waitlist_offer
    """
    club = create_club(name="Cascade Club 2")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")  # count -> 1
    mh = make_member_headers(m["id"])
    validate_success(api.resign_membership(m["id"], mh))

    data = validate_success(api.settle_resignation(m["id"], _MANAGER))
    assert data["account_status"] == "RESIGNED", f"got {data['account_status']}"
    cat_after = validate_success(api.get_category(cat["id"], _MANAGER))
    assert cat_after["active_member_count"] == 0, (
        f"the freed seat must drop the count by one, got {cat_after['active_member_count']}"
    )


def test_waitlist_accept_creates_active_membership_with_initiation_chit(api):
    """PRD §3.2: "A successful accept moves the entry from OFFERED to ACCEPTED and
    cascades: it creates a fresh Membership in PENDING for the category and
    immediately activates it, applying the very same activation side effects —
    recording the activation period, posting the EVENT initiation chit, debiting
    the new member's charge_balance_cents, and recomputing active_member_count."
    PRD §3.2: "On a successful activation the system ... posts the initiation
    charge as a chit of kind EVENT whose amount_cents equals the category's
    initiation_fee_cents."

    Design: Difficulty/transitive_cascade/waitlist_accept_cascade_membership_chit_balance
    """
    club = create_club(name="Accept Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    w = create_waitlist_entry(club["id"], cat["id"], applicant_name="W")
    offer_waitlist_entry(w["id"])
    cat_v = get_category_version(cat["id"])

    data = validate_success(api.accept_waitlist_entry(
        w["id"], {"expected_category_version": cat_v}, _MANAGER))
    assert data["status"] == "ACCEPTED"
    new_m_id = data["created_membership_id"]
    assert new_m_id, "created_membership_id must be recorded on accept"

    new_m = validate_success(api.get_membership(new_m_id, _MANAGER))
    assert new_m["account_status"] == "ACTIVE", f"got {new_m['account_status']}"
    assert new_m["charge_balance_cents"] == 50000, (
        f"initiation chit must debit the new member's balance, got {new_m['charge_balance_cents']}"
    )

    chits = list_member_chits(new_m_id)
    event_chits = [c for c in chits if c["kind"] == "EVENT" and c["amount_cents"] == 50000]
    assert len(event_chits) == 1, (
        f"expected one EVENT initiation chit of 50000, got {[(c['kind'], c['amount_cents']) for c in chits]}"
    )


def test_waitlist_accept_recomputes_category_count(api):
    """PRD §3.2: "it creates a fresh Membership in PENDING for the category and
    immediately activates it, applying the very same activation side effects —
    recording the activation period, posting the EVENT initiation chit, debiting
    the new member's charge_balance_cents, and recomputing active_member_count."

    Design: Difficulty/transitive_cascade/waitlist_accept_cascade_membership_chit_balance
    """
    club = create_club(name="Accept Club 2")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=50000,
                          refundable_equity_cents=40000, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    w = create_waitlist_entry(club["id"], cat["id"], applicant_name="W")
    offer_waitlist_entry(w["id"])
    cat_v = get_category_version(cat["id"])

    validate_success(api.accept_waitlist_entry(
        w["id"], {"expected_category_version": cat_v}, _MANAGER))
    cat_after = validate_success(api.get_category(cat["id"], _MANAGER))
    assert cat_after["active_member_count"] == 1, (
        f"accept must create+activate a member, lifting the count to 1, "
        f"got {cat_after['active_member_count']}"
    )


# ===========================================================================
# Corner: state_machines
# ===========================================================================

def test_cancel_already_cancelled_reservation_invalid_state(api):
    """PRD §3.4: "a cancel or complete from any non-CONFIRMED state, with
    ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/cancel_reservation_from_cancelled_invalid_state
    """
    club, cat, m, resource, rsv = setup_reservation(kind="COURT", turnaround_minutes=0)
    mh = make_member_headers(m["id"])
    validate_success(api.cancel_reservation(rsv["id"], mh))  # -> CANCELLED

    resp = api.cancel_reservation(rsv["id"], mh)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_reservation(rsv["id"], _MANAGER))
    assert after["status"] == "CANCELLED", f"got {after['status']}"


def test_complete_reservation_before_end_time_invalid(api):
    """PRD §3.4: "A manager completes a CONFIRMED reservation, moving it to the
    terminal COMPLETED, but only once the logical clock has reached or passed the
    reservation's ends_at; a completion attempted before that instant is
    rejected ... with ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/complete_reservation_before_end_time_invalid
    """
    # Logical clock defaults to 2026-01-01T00:00:00Z, before the 2026-02-01 window.
    club, cat, m, resource, rsv = setup_reservation(
        kind="COURT", turnaround_minutes=0,
        starts_at="2026-02-01T10:00:00Z", ends_at="2026-02-01T11:00:00Z",
    )
    resp = api.complete_reservation(rsv["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_complete_reservation_after_clock_set_succeeds(api):
    """PRD §3.8: "a manager may invoke an administrative capability that sets the
    server logical clock to an explicit UTC instant supplied as to_iso8601."
    PRD §3.4: "A manager completes a CONFIRMED reservation, moving it to the
    terminal COMPLETED, but only once the logical clock has reached or passed the
    reservation's ends_at."

    Design: Corner/state_machines/complete_reservation_after_clock_set_succeeds
    """
    club, cat, m, resource, rsv = setup_reservation(
        kind="COURT", turnaround_minutes=0,
        starts_at="2026-02-01T10:00:00Z", ends_at="2026-02-01T11:00:00Z",
    )
    set_clock("2026-02-01T11:00:00Z")
    data = validate_success(api.complete_reservation(rsv["id"], _MANAGER))
    assert data["status"] == "COMPLETED", f"got {data['status']}"


def test_reinstate_active_membership_invalid_state(api):
    """PRD §3.3: "Suspending a membership that is not ACTIVE, or reinstating one
    that is not SUSPENDED, yields ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/reinstate_non_suspended_invalid_state
    """
    club = create_club(name="S4 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=50, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")  # ACTIVE
    resp = api.reinstate_membership(m["id"], _MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_resign_after_resigned_terminal_invalid_state(api):
    """PRD §2.7: "PENDING, ACTIVE, SUSPENDED, RESIGNED_PENDING, or RESIGNED, where
    RESIGNED is terminal."
    PRD §3.3: "resigning from any other state yields ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/resigned_terminal_lockdown_no_resign_again
    """
    club = create_club(name="S5 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=5, guest_fee_cents=5000,
                          allows_golf=True)
    m = create_and_activate_membership(club["id"], cat["id"], holder_name="M")
    mh = make_member_headers(m["id"])
    validate_success(api.resign_membership(m["id"], mh))           # -> RESIGNED_PENDING
    validate_success(api.settle_resignation(m["id"], _MANAGER))    # -> RESIGNED (terminal)

    resp = api.resign_membership(m["id"], mh)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_membership(m["id"], _MANAGER))
    assert after["account_status"] == "RESIGNED", f"got {after['account_status']}"


def test_waitlist_decline_promotes_next_waiting_entry(api):
    """PRD §3.2: "a manager declines an OFFERED entry, moving it from OFFERED to
    DECLINED, and if any other entry for that category is still WAITING, the
    earliest by created_at is promoted to OFFERED as a cascade."

    Design: Corner/state_machines/waitlist_decline_promotes_next_waiting
    """
    club = create_club(name="S6 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    w1 = create_waitlist_entry(club["id"], cat["id"], applicant_name="W1")
    w2 = create_waitlist_entry(club["id"], cat["id"], applicant_name="W2")
    offer_waitlist_entry(w1["id"])

    validate_success(api.decline_waitlist_entry(w1["id"], _MANAGER))
    w1_after = validate_success(api.get_waitlist_entry(w1["id"], _MANAGER))
    w2_after = validate_success(api.get_waitlist_entry(w2["id"], _MANAGER))
    assert w1_after["status"] == "DECLINED", f"got {w1_after['status']}"
    assert w2_after["status"] == "OFFERED", f"next WAITING should be promoted, got {w2_after['status']}"


def test_waitlist_offer_expires_on_close_period(api):
    """PRD §3.7: "Any WaitlistEntry still in OFFERED whose offered_period_index is
    earlier than the club's billing_period_index after the advance has let its
    offer lapse and is moved to the terminal EXPIRED."

    Design: Corner/state_machines/waitlist_offer_expires_on_close_period
    """
    club = create_club(name="S7 Club")
    cat = create_category(club["id"], code="GOLF", initiation_fee_cents=0,
                          refundable_equity_cents=0, monthly_dues_cents=30000,
                          fb_minimum_cents=0, capacity=1, guest_fee_cents=5000,
                          allows_golf=True)
    w = create_waitlist_entry(club["id"], cat["id"], applicant_name="W")
    offer_waitlist_entry(w["id"])  # offered in period 0
    club_v = get_club_version(club["id"])

    club_after = validate_success(api.close_period(
        club["id"], {"expected_club_version": club_v}, _MANAGER))
    assert club_after["billing_period_index"] == 1, f"got {club_after['billing_period_index']}"

    w_after = validate_success(api.get_waitlist_entry(w["id"], _MANAGER))
    assert w_after["status"] == "EXPIRED", f"got {w_after['status']}"


def test_abandon_amend_keeps_original_window(api):
    """PRD §3.4: "Abandoning the amend also returns the reservation to CONFIRMED
    but discards the proposal, clearing proposed_starts_at and proposed_ends_at to
    null and retaining the original window."

    Design: Corner/state_machines/abandon_amend_keeps_original_window
    """
    club, cat, m, resource, rsv = setup_reservation(
        kind="COURT", turnaround_minutes=0,
        starts_at="2026-02-01T10:00:00Z", ends_at="2026-02-01T11:00:00Z",
    )
    mh = make_member_headers(m["id"])
    validate_success(api.propose_amend(
        rsv["id"],
        {"proposed_starts_at": "2026-02-01T12:00:00Z",
         "proposed_ends_at": "2026-02-01T13:00:00Z"},
        mh,
    ))
    data = validate_success(api.abandon_amend(rsv["id"], mh))
    assert data["status"] == "CONFIRMED", f"got {data['status']}"
    assert data["starts_at"] == "2026-02-01T10:00:00Z", f"got {data['starts_at']}"
    assert data["proposed_starts_at"] is None, f"got {data['proposed_starts_at']}"
