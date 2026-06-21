"""Confirm-time guards: capacity & household boundaries, validation precedence,
cross-entity state dependencies, slot/exhibit temporal rules, guest-pass pool.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    fixtures as fx,
    make_patron_headers,
)


def _membership_id_of(api, patron_id):
    data = validate_success(api.list_memberships(fx.ADMIN, {"primary_patron_id": patron_id}))
    assert len(data) >= 1
    return data[0]["id"]


# ─── Difficulty: slot-capacity boundary (exact fill / +1) ─────────────

def test_slot_capacity_one_over_full_rejected(api):
    """PRD §3.6: "Capacity (ERR_SLOT_CAPACITY) requires that the slot's current
    reserved_count plus this order's party_size not exceed the slot's
    capacity_total ... reaching the limit exactly is allowed and only exceeding
    it rejects."

    Slot capacity 2 already exactly filled; a third party member (2+1 > 2) is
    rejected with ERR_SLOT_CAPACITY, and the slot stays at reserved_count == 2.

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fill_succeeds_one_more_rejects
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    slot = fx.create_slot(capacity_total=2)
    p1 = fx.create_patron()
    fx.build_confirmed_order(
        p1["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"},
         {"ticket_type": "NON_MEMBER", "person_name": "B"}],
    )
    p2 = fx.create_patron()
    order2 = fx.build_draft_order_with_tickets(
        p2["id"], slot["id"], [{"ticket_type": "NON_MEMBER", "person_name": "C"}],
    )
    resp = api.confirm_order(order2["id"], make_patron_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY.value)
    assert fx.get_slot(slot["id"])["reserved_count"] == 2, \
        "the rejected confirm must not change reserved_count"


def test_slot_capacity_exact_fill_succeeds(api):
    """PRD §3.6: "reaching the limit exactly is allowed and only exceeding it
    rejects."

    The X-side of the boundary: filling a capacity-2 slot exactly (reserved 0 +
    party 2 == 2) confirms successfully and leaves reserved_count == 2.

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fill_succeeds_one_more_rejects
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    slot = fx.create_slot(capacity_total=2)
    p1 = fx.create_patron()
    order = fx.build_confirmed_order(
        p1["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"},
         {"ticket_type": "NON_MEMBER", "person_name": "B"}],
    )
    assert order["status"] == "CONFIRMED"
    assert fx.get_slot(slot["id"])["reserved_count"] == 2


# ─── Difficulty: household_max boundary ───────────────────────────────

def test_household_add_over_max_rejected(api):
    """PRD §3.4: "an add is rejected with ERR_HOUSEHOLD_FULL when that active
    count plus the one being added would exceed the plan's household_max."

    household_max=1: the first add fills the household (count 1 == max), the
    second add (would be 2 > 1) is rejected with ERR_HOUSEHOLD_FULL.

    Design: Difficulty/boundary_precision_check/household_max_exact_fill_succeeds_one_more_rejects
    """
    plan = fx.create_plan(tier="DUAL", household_max=1)
    patron = fx.create_patron()
    m = fx.create_pending_membership(plan["id"], patron["id"])
    validate_success(api.add_household_member(
        m["id"], {"full_name": "Spouse", "relationship": "SPOUSE"},
        make_patron_headers(patron["id"]),
    ), expected_status=201)
    resp = api.add_household_member(
        m["id"], {"full_name": "Child", "relationship": "CHILD"},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FULL.value)


def test_household_add_exact_fill_succeeds(api):
    """PRD §3.4: "The household is counted by tallying the household members of
    the membership whose active is true; an add is rejected with
    ERR_HOUSEHOLD_FULL when that active count plus the one being added would
    exceed the plan's household_max."

    The X-side: with household_max=1 the first add (0+1 == 1, not exceeding)
    succeeds and the member is born active.

    Design: Difficulty/boundary_precision_check/household_max_exact_fill_succeeds_one_more_rejects
    """
    plan = fx.create_plan(tier="DUAL", household_max=1)
    patron = fx.create_patron()
    m = fx.create_pending_membership(plan["id"], patron["id"])
    member = validate_success(api.add_household_member(
        m["id"], {"full_name": "Spouse", "relationship": "SPOUSE"},
        make_patron_headers(patron["id"]),
    ), expected_status=201)
    assert member["active"] is True


# ─── Difficulty: validation precedence (single design pair each) ──────

def test_reconfirm_full_slot_returns_invalid_state_not_capacity(api):
    """PRD §3.6: "Confirming an order that is not in DRAFT is rejected with
    ERR_INVALID_STATE."
    PRD §3.6: "they are evaluated in the following order. First, the
    membership-and-ownership and existence checks of Section 2 apply as everywhere
    else."

    An already-CONFIRMED order on a now-full slot, re-confirmed, returns
    ERR_INVALID_STATE because the state check precedes the capacity check.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_slot_capacity
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot(capacity_total=1)
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reconfirm_full_slot_leaves_order_confirmed_state_wins(api):
    """PRD §3.6: "Confirming an order that is not in DRAFT is rejected with
    ERR_INVALID_STATE."

    Second test of the state-vs-capacity pair: the re-confirm of an already
    CONFIRMED order on a full (capacity-1) slot returns ERR_INVALID_STATE and the
    order remains CONFIRMED - the state guard pre-empts the capacity guard.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_slot_capacity
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot(capacity_total=1)
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert fx.get_order(order["id"], patron["id"])["status"] == "CONFIRMED"


def test_confirm_after_window_open_on_full_slot_returns_slot_window(api):
    """PRD §3.6: "the confirm-specific guards, in priority order: ticket
    eligibility first, then membership-active, then the slot window, then slot
    overlap, then the exhibit buffer, then guest-pass availability, and finally
    slot and session capacity."
    PRD §3.6: "The slot-window check (ERR_SLOT_WINDOW) requires that the slot's
    starts_at is strictly after the current clock."

    A DRAFT on a slot that is BOTH full AND past its window-open returns
    ERR_SLOT_WINDOW, since the window check precedes the capacity check.

    Design: Difficulty/priority_pair_validation_conflict/confirm_slot_window_open_beats_slot_capacity
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    slot = fx.create_slot(capacity_total=1)
    filler = fx.create_patron()
    fx.build_confirmed_order(
        filler["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "Filler"}],
    )
    patron = fx.create_patron()
    order = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"], [{"ticket_type": "NON_MEMBER", "person_name": "P Ten"}],
    )
    fx.set_clock("2026-06-10T10:05:00Z")
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW.value)


def test_window_open_full_slot_leaves_order_draft_window_wins(api):
    """PRD §3.6: "the confirm-specific guards, in priority order: ... then the
    slot window ... and finally slot and session capacity."
    PRD §3.6: "The slot-window check (ERR_SLOT_WINDOW) requires that the slot's
    starts_at is strictly after the current clock - the window must not yet have
    opened."

    Second test of the window-vs-capacity pair: on a slot that is both full and
    past its window-open, the confirm returns ERR_SLOT_WINDOW and the order stays
    DRAFT - the temporal guard pre-empts the capacity guard.

    Design: Difficulty/priority_pair_validation_conflict/confirm_slot_window_open_beats_slot_capacity
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    slot = fx.create_slot(capacity_total=1)
    filler = fx.create_patron()
    fx.build_confirmed_order(
        filler["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "Filler"}],
    )
    patron = fx.create_patron()
    order = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"], [{"ticket_type": "NON_MEMBER", "person_name": "P Ten"}],
    )
    fx.set_clock("2026-06-10T10:05:00Z")
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW.value)
    assert fx.get_order(order["id"], patron["id"])["status"] == "DRAFT"


# ─── Difficulty: cross-entity state dependency ────────────────────────

def test_confirm_member_ticket_requires_membership_active(api):
    """PRD §3.6: "Membership-active (ERR_MEMBERSHIP_NOT_ACTIVE) requires that,
    when any MEMBER ticket is present, the referenced membership's status is
    ACTIVE at confirm time."

    A DRAFT order with a MEMBER ticket whose membership is in GRACE is rejected
    with ERR_MEMBERSHIP_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_membership_active
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "household_max": 0, "reinstatement_fee_cents": 3000},
        membership_overrides={"auto_renew": False},
    )
    membership_id = _membership_id_of(api, patron["id"])
    fx.drive_membership_to_grace(membership_id, patron["id"])
    # Move clock back before the slot window so the slot-window guard passes and
    # the membership-active guard is the one that fires.
    fx.set_clock("2026-06-05T00:00:00Z")
    slot = fx.create_slot()
    order = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "P Thirteen"}],
        order_overrides={"membership_id": membership_id},
    )
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_grace_membership_member_ticket_confirm_leaves_order_draft(api):
    """PRD §3.6: "Membership-active (ERR_MEMBERSHIP_NOT_ACTIVE) requires that,
    when any MEMBER ticket is present, the referenced membership's status is
    ACTIVE at confirm time."

    Second test of the AdmissionOrder -> Membership dependency: the rejected
    confirm leaves the order in DRAFT (nothing committed) when the membership is
    in GRACE.

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_membership_active
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "household_max": 0, "reinstatement_fee_cents": 3000},
        membership_overrides={"auto_renew": False},
    )
    membership_id = _membership_id_of(api, patron["id"])
    fx.drive_membership_to_grace(membership_id, patron["id"])
    fx.set_clock("2026-06-05T00:00:00Z")
    slot = fx.create_slot()
    order = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "P Thirteen"}],
        order_overrides={"membership_id": membership_id},
    )
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)
    after = fx.get_order(order["id"], patron["id"])
    assert after["status"] == "DRAFT", "rejected confirm must leave the order in DRAFT"


# ─── Difficulty: temporal overlap / exhibit buffer ────────────────────

def test_overlapping_slot_windows_rejected(api):
    """PRD §3.6: "The slot-overlap check (ERR_SLOT_OVERLAP) requires that the
    patron has no other CONFIRMED or CHECKED_IN order whose slot window overlaps
    this slot's window, where windows are treated as half-open intervals from
    starts_at (inclusive) to ends_at (exclusive)."

    A patron's second order on a strictly-overlapping window (11:00-13:00 vs an
    existing 10:00-12:00) is rejected with ERR_SLOT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/patron_slot_windows_overlap_rejected_half_open
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot_a = fx.create_slot(starts_at="2026-06-10T10:00:00Z", ends_at="2026-06-10T12:00:00Z")
    slot_b = fx.create_slot(starts_at="2026-06-10T11:00:00Z", ends_at="2026-06-10T13:00:00Z")
    fx.build_confirmed_order(
        patron["id"], slot_a["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    order2 = fx.build_draft_order_with_tickets(
        patron["id"], slot_b["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A2"}],
    )
    resp = api.confirm_order(order2["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_overlapping_slot_confirm_leaves_second_order_draft(api):
    """PRD §3.6: "The slot-overlap check (ERR_SLOT_OVERLAP) requires that the
    patron has no other CONFIRMED or CHECKED_IN order whose slot window overlaps
    this slot's window, where windows are treated as half-open intervals from
    starts_at (inclusive) to ends_at (exclusive)."

    Second test of the half-open slot timeline: the rejected confirm leaves the
    overlapping second order in DRAFT.

    Design: Difficulty/resource_temporal_overlap/patron_slot_windows_overlap_rejected_half_open
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot_a = fx.create_slot(starts_at="2026-06-10T10:00:00Z", ends_at="2026-06-10T12:00:00Z")
    slot_b = fx.create_slot(starts_at="2026-06-10T11:00:00Z", ends_at="2026-06-10T13:00:00Z")
    fx.build_confirmed_order(
        patron["id"], slot_a["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    order2 = fx.build_draft_order_with_tickets(
        patron["id"], slot_b["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A2"}],
    )
    resp = api.confirm_order(order2["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)
    assert fx.get_order(order2["id"], patron["id"])["status"] == "DRAFT"


def test_exhibit_sessions_within_buffer_rejected(api):
    """PRD §3.6: "The exhibit-buffer check (ERR_EXHIBIT_BUFFER_CONFLICT) applies
    only when the order has an exhibit_session_id: the patron must have no other
    booked exhibit session within buffer_minutes of this order's session window,
    where the buffer is a closed interval so that a booking exactly buffer_minutes
    away is disallowed."

    Two of a patron's sessions on the same exhibit are 15 minutes apart with a
    30-minute buffer, on non-overlapping (adjacent) slots so the slot rule does
    not fire; the second confirm is rejected with ERR_EXHIBIT_BUFFER_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/patron_exhibit_sessions_within_buffer_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot1 = fx.create_slot(starts_at="2026-06-10T10:00:00Z", ends_at="2026-06-10T12:00:00Z")
    slot2 = fx.create_slot(starts_at="2026-06-10T12:00:00Z", ends_at="2026-06-10T14:00:00Z")
    exhibit = fx.create_exhibit(name="Butterflies", surcharge_cents=1000, buffer_minutes=30)
    es1 = fx.create_session(exhibit["id"], starts_at="2026-06-10T10:30:00Z",
                            ends_at="2026-06-10T11:00:00Z")
    es2 = fx.create_session(exhibit["id"], starts_at="2026-06-10T11:15:00Z",
                            ends_at="2026-06-10T11:45:00Z")
    fx.build_confirmed_order(
        patron["id"], slot1["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
        order_overrides={"exhibit_session_id": es1["id"]},
    )
    order2 = fx.build_draft_order_with_tickets(
        patron["id"], slot2["id"], [{"ticket_type": "NON_MEMBER", "person_name": "B"}],
        order_overrides={"exhibit_session_id": es2["id"]},
    )
    resp = api.confirm_order(order2["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_EXHIBIT_BUFFER_CONFLICT.value)


def test_exhibit_buffer_conflict_leaves_second_order_draft(api):
    """PRD §3.6: "the patron must have no other booked exhibit session within
    buffer_minutes of this order's session window, where the buffer is a closed
    interval so that a booking exactly buffer_minutes away is disallowed."

    Second test of the buffered closed-interval exhibit rule: the rejected
    confirm leaves the conflicting second order in DRAFT.

    Design: Difficulty/resource_temporal_overlap/patron_exhibit_sessions_within_buffer_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot1 = fx.create_slot(starts_at="2026-06-10T10:00:00Z", ends_at="2026-06-10T12:00:00Z")
    slot2 = fx.create_slot(starts_at="2026-06-10T12:00:00Z", ends_at="2026-06-10T14:00:00Z")
    exhibit = fx.create_exhibit(name="Moths", surcharge_cents=1000, buffer_minutes=30)
    es1 = fx.create_session(exhibit["id"], starts_at="2026-06-10T10:30:00Z",
                            ends_at="2026-06-10T11:00:00Z")
    es2 = fx.create_session(exhibit["id"], starts_at="2026-06-10T11:15:00Z",
                            ends_at="2026-06-10T11:45:00Z")
    fx.build_confirmed_order(
        patron["id"], slot1["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
        order_overrides={"exhibit_session_id": es1["id"]},
    )
    order2 = fx.build_draft_order_with_tickets(
        patron["id"], slot2["id"], [{"ticket_type": "NON_MEMBER", "person_name": "B"}],
        order_overrides={"exhibit_session_id": es2["id"]},
    )
    resp = api.confirm_order(order2["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_EXHIBIT_BUFFER_CONFLICT.value)
    assert fx.get_order(order2["id"], patron["id"])["status"] == "DRAFT"


# ─── Corner: validation single-failure scenarios ──────────────────────

def test_confirm_after_window_open_returns_slot_window(api):
    """PRD §3.6: "The slot-window check (ERR_SLOT_WINDOW) requires that the slot's
    starts_at is strictly after the current clock - the window must not yet have
    opened ... a confirm attempted at or after the window opens, cannot proceed."

    Design: Corner/validations/confirm_slot_window_already_open_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    fx.set_clock("2026-06-10T10:05:00Z")
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW.value)


def test_confirm_empty_order_rejected_invalid_state(api):
    """PRD §3.6: "Throughout, at least one ticket must be present - the party
    size must be one or more - for the order to confirm."
    PRD §3.6: "Confirming an order that is not in DRAFT is rejected with
    ERR_INVALID_STATE."

    Confirming a DRAFT order with zero tickets fails the at-least-one-ticket
    precondition with ERR_INVALID_STATE.

    Design: Corner/validations/confirm_empty_order_rejected_invalid_state
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.create_draft_order(patron["id"], slot["id"])
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reciprocal_ticket_without_partner_rejected(api):
    """PRD §3.6: "Ticket eligibility (ERR_TICKET_ELIGIBILITY) requires that ...
    every RECIPROCAL ticket carries a reciprocal_partner_id that resolves to a
    partner."

    A RECIPROCAL ticket added without a reciprocal_partner_id is rejected at
    confirm with ERR_TICKET_ELIGIBILITY.

    Design: Corner/validations/reciprocal_ticket_without_partner_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"], [{"ticket_type": "RECIPROCAL", "person_name": "NoPartner"}],
    )
    resp = api.confirm_order(order["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_ELIGIBILITY.value)


def test_adjacent_slot_windows_allowed(api):
    """PRD §3.6: "windows are treated as half-open intervals from starts_at
    (inclusive) to ends_at (exclusive) so that two back-to-back windows touching
    only at an endpoint are allowed."

    Two orders on exactly-adjacent slots (A ends 12:00, B starts 12:00) both
    confirm - no ERR_SLOT_OVERLAP.

    Design: Corner/validations/slot_overlap_adjacent_windows_allowed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot_a = fx.create_slot(starts_at="2026-06-10T10:00:00Z", ends_at="2026-06-10T12:00:00Z")
    slot_b = fx.create_slot(starts_at="2026-06-10T12:00:00Z", ends_at="2026-06-10T14:00:00Z")
    fx.build_confirmed_order(
        patron["id"], slot_a["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    order2 = fx.build_confirmed_order(
        patron["id"], slot_b["id"], [{"ticket_type": "NON_MEMBER", "person_name": "B"}],
    )
    assert order2["status"] == "CONFIRMED"


def test_checkin_before_window_opens_returns_slot_window(api):
    """PRD §3.7: "Check-in moves the order from CONFIRMED to CHECKED_IN and is
    permitted only within the entry window - the slot's starts_at at or before the
    current clock and the current clock strictly before the slot's ends_at;
    outside that window the check-in is rejected with ERR_SLOT_WINDOW."

    Design: Corner/state_machines/checkin_before_window_opens_returns_slot_window
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    # Clock still at 2026-06-01, before the 06-10 window.
    resp = api.check_in_order(order["id"], fx.BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW.value)


def test_empty_guest_pass_pool_rejects_second_guest_confirm(api):
    """PRD §3.6: "Guest-pass availability (ERR_NO_GUEST_PASS) requires that the
    membership hold at least one UNUSED guest pass for each GUEST ticket on the
    order; an empty pool rejects."

    With guest_passes_granted=1 and the single pass already RESERVED on a prior
    CONFIRMED order, confirming a second GUEST ticket is rejected with
    ERR_NO_GUEST_PASS.

    Design: Corner/state_machines/guest_pass_empty_pool_rejects_second_guest_confirm
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "household_max": 0, "guest_passes_granted": 1},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot1 = fx.create_slot(starts_at="2026-06-10T10:00:00Z", ends_at="2026-06-10T11:00:00Z")
    slot2 = fx.create_slot(starts_at="2026-06-10T13:00:00Z", ends_at="2026-06-10T14:00:00Z")
    fx.build_confirmed_order(
        patron["id"], slot1["id"], [{"ticket_type": "GUEST", "person_name": "Visitor 1"}],
        order_overrides={"membership_id": membership_id},
    )
    order2 = fx.build_draft_order_with_tickets(
        patron["id"], slot2["id"], [{"ticket_type": "GUEST", "person_name": "Visitor 2"}],
        order_overrides={"membership_id": membership_id},
    )
    resp = api.confirm_order(order2["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_GUEST_PASS.value)
