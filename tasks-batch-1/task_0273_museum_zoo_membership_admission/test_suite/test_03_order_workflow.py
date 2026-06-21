"""Order workflow: branching at CONFIRMED, check-in / cancel / refund side
effects, and the cascade chains that void tickets and release capacity.
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
    make_patron_headers,
)


def _membership_id_of(api, patron_id):
    data = validate_success(api.list_memberships(fx.ADMIN, {"primary_patron_id": patron_id}))
    assert len(data) >= 1
    return data[0]["id"]


# ─── Difficulty: AdmissionOrder branching CONFIRMED -> {CHECKED_IN | CANCELLED} ─

def test_confirmed_order_cancel_branch_releases_slot_capacity(api):
    """PRD §3.7: "Cancelling a CONFIRMED order moves it to CANCELLED and runs the
    full release: every still-ACTIVE ticket moves to VOIDED; voiding the tickets
    decrements the slot's reserved_count by the order's party_size."

    The cancel branch from CONFIRMED voids tickets and returns the held seat, so
    the slot's reserved_count drops back to 0.

    Design: Difficulty/non_linear_state_machine/admission_order_branching_confirmed_to_checkin_or_cancel
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "P Six"}],
    )
    cancelled = validate_success(api.cancel_order(order["id"], make_patron_headers(patron["id"])))
    assert cancelled["status"] == "CANCELLED"
    slot_after = fx.get_slot(slot["id"])
    assert slot_after["reserved_count"] == 0, \
        f"cancel should release the held seat, got reserved_count={slot_after['reserved_count']}"


def test_confirmed_order_checkin_branch_scans_tickets_and_redeems_passes(api):
    """PRD §3.7: "On check-in every still-ACTIVE ticket on the order moves to
    SCANNED, and every guest pass RESERVED against the order moves to REDEEMED."

    The other branch from CONFIRMED: check-in inside the window scans tickets and
    redeems the reserved guest pass - divergent side effects from the cancel
    branch on the same fork.

    Design: Difficulty/non_linear_state_machine/admission_order_branching_confirmed_to_checkin_or_cancel
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "GUEST", "person_name": "V"}],
        order_overrides={"membership_id": membership_id},
    )
    fx.set_clock("2026-06-10T10:30:00Z")
    checked = validate_success(api.check_in_order(order["id"], fx.BOX_OFFICE))
    assert checked["status"] == "CHECKED_IN"
    assert fx.count_guest_passes(membership_id, "REDEEMED") == 1, \
        "reserved guest pass should be REDEEMED on check-in"


# ─── Difficulty: depth-3 membership-cancel cascade ────────────────────

def test_membership_cancel_cascade_depth3_releases_slot_seat(api):
    """PRD §3.3: "Each guest pass currently RESERVED is released back to UNUSED
    and then immediately expired to EXPIRED; releasing it voids the guest ticket
    linked to that pass and gives back the held capacity, decrementing the
    reserved count on that order's slot."

    Membership cancel -> RESERVED guest pass released -> linked GUEST ticket
    VOIDED -> slot reserved_count decremented to 0 (three cascade hops).

    Design: Difficulty/transitive_cascade/membership_cancel_cascade_depth3_to_guestpass_ticket_slot
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "GUEST", "person_name": "Visitor"}],
        order_overrides={"membership_id": membership_id},
    )
    assert fx.get_slot(slot["id"])["reserved_count"] == 1

    cancelled = validate_success(api.cancel_membership(membership_id, make_patron_headers(patron["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert fx.get_slot(slot["id"])["reserved_count"] == 0, \
        "depth-3 cascade should release the slot seat"


def test_membership_cancel_is_terminal_cancelled(api):
    """PRD §3.3: "Cancellation is available from PENDING_PAYMENT, ACTIVE, or
    GRACE and is terminal, moving the membership to CANCELLED."

    Second test of the depth-3 cascade origin: the membership itself ends in the
    terminal CANCELLED status.

    Design: Difficulty/transitive_cascade/membership_cancel_cascade_depth3_to_guestpass_ticket_slot
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot()
    fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "GUEST", "person_name": "Visitor"}],
        order_overrides={"membership_id": membership_id},
    )
    cancelled = validate_success(api.cancel_membership(membership_id, make_patron_headers(patron["id"])))
    assert cancelled["status"] == "CANCELLED"


# ─── Difficulty: depth-2 order-cancel cascade ─────────────────────────

def test_order_cancel_cascade_depth2_releases_slot_capacity(api):
    """PRD §3.7: "Cancelling a CONFIRMED order moves it to CANCELLED and runs the
    full release: every still-ACTIVE ticket moves to VOIDED; voiding the tickets
    decrements the slot's reserved_count by the order's party_size."

    Order cancel -> tickets VOIDED -> slot reserved_count decremented from 2 to 0
    (two cascade hops, different trigger from membership cancel).

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2_to_ticket_then_slot
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"},
         {"ticket_type": "NON_MEMBER", "person_name": "B"}],
    )
    assert fx.get_slot(slot["id"])["reserved_count"] == 2

    cancelled = validate_success(api.cancel_order(order["id"], make_patron_headers(patron["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert fx.get_slot(slot["id"])["reserved_count"] == 0, \
        "order cancel should release both held seats"


def test_order_cancel_marks_order_cancelled(api):
    """PRD §3.7: "Cancelling a CONFIRMED order moves it to CANCELLED."

    Second test of the depth-2 cascade: the order's own status reaches CANCELLED.

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2_to_ticket_then_slot
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"},
         {"ticket_type": "NON_MEMBER", "person_name": "B"}],
    )
    cancelled = validate_success(api.cancel_order(order["id"], make_patron_headers(patron["id"])))
    assert cancelled["status"] == "CANCELLED"


# ─── Corner: check-in / refund side effects ───────────────────────────

def test_checkin_within_window_scans_tickets_and_redeems_passes(api):
    """PRD §3.7: "On check-in every still-ACTIVE ticket on the order moves to
    SCANNED, and every guest pass RESERVED against the order moves to REDEEMED."

    Design: Corner/state_machines/checkin_within_window_scans_tickets_and_redeems_passes
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "GUEST", "person_name": "V"}],
        order_overrides={"membership_id": membership_id},
    )
    fx.set_clock("2026-06-10T10:30:00Z")
    checked = validate_success(api.check_in_order(order["id"], fx.BOX_OFFICE))
    assert checked["status"] == "CHECKED_IN"
    assert fx.count_guest_passes(membership_id, "REDEEMED") == 1


def test_refund_checked_in_order_voids_and_expires_redeemed_pass(api):
    """PRD §3.7: "Refunding moves the order to REFUNDED, voids all of its tickets,
    releases the held capacity by decrementing the slot's reserved_count by
    party_size ... and expires every REDEEMED guest pass of the order to EXPIRED -
    a redeemed pass has been consumed and is not returned to the pool."

    Design: Corner/state_machines/refund_checked_in_order_voids_and_expires_redeemed_pass
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "GUEST", "person_name": "V"}],
        order_overrides={"membership_id": membership_id},
    )
    fx.set_clock("2026-06-10T10:30:00Z")
    validate_success(api.check_in_order(order["id"], fx.BOX_OFFICE))

    refunded = validate_success(api.refund_order(order["id"], fx.BOX_OFFICE))
    assert refunded["status"] == "REFUNDED"
    assert fx.get_slot(slot["id"])["reserved_count"] == 0, "refund releases the seat"
    assert fx.count_guest_passes(membership_id, "EXPIRED") == 1, \
        "the redeemed pass should be EXPIRED, not returned"


def test_confirm_immediately_reflects_reserved_count(api):
    """PRD §2.8: "The reserved count of a slot is the sum of party_size over every
    order on that slot whose status is CONFIRMED or CHECKED_IN."
    PRD §2.8: "Every cascade in this system is atomic within the request that
    triggers it."

    A GET on the slot right after confirm already shows reserved_count == 2
    (immediate consistency, no lag).

    Design: Corner/consistency_model/confirm_immediately_reflects_reserved_count
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"},
         {"ticket_type": "NON_MEMBER", "person_name": "B"}],
    )
    assert fx.get_slot(slot["id"])["reserved_count"] == 2
