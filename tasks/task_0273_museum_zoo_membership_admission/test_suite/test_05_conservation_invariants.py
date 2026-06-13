"""Conservation invariants: guest-pass pool conservation and slot-seat
conservation under confirm-then-compensating-cancel.
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


def test_guest_pass_count_conserved_unused_after_confirm_then_cancel(api):
    """PRD §2.8: "Reserving a guest pass and later releasing it must net to zero:
    a release returns the pass and reverses every downstream effect the
    reservation caused, so the institution never loses or gains a pass through
    ordinary order churn."
    PRD §3.7: "every guest pass RESERVED against the order returns to UNUSED with
    its reserved_order_id cleared to null."

    Confirm reserves 1 of 2 passes; cancelling the order returns it, leaving both
    passes UNUSED (the conserved quantity is restored).

    Design: Difficulty/compensating_invariant/guest_pass_count_conserved_under_confirm_then_cancel
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"], [{"ticket_type": "GUEST", "person_name": "Visitor"}],
        order_overrides={"membership_id": membership_id},
    )
    assert fx.count_guest_passes(membership_id, "RESERVED") == 1

    validate_success(api.cancel_order(order["id"], make_patron_headers(patron["id"])))
    assert fx.count_guest_passes(membership_id, "UNUSED") == 2, \
        "both passes should be UNUSED again after the compensating cancel"


def test_guest_pass_count_conserved_zero_reserved_after_cancel(api):
    """PRD §2.8: "across that term the count of passes in UNUSED, RESERVED, and
    REDEEMED together always equals the number minted for the term."

    Second test of guest-pass conservation: after the compensating cancel no pass
    remains RESERVED.

    Design: Difficulty/compensating_invariant/guest_pass_count_conserved_under_confirm_then_cancel
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"], [{"ticket_type": "GUEST", "person_name": "Visitor"}],
        order_overrides={"membership_id": membership_id},
    )
    validate_success(api.cancel_order(order["id"], make_patron_headers(patron["id"])))
    assert fx.count_guest_passes(membership_id, "RESERVED") == 0


def test_slot_seat_count_conserved_after_confirm_then_cancel(api):
    """PRD §2.8: "Reserved counts move only through the order lifecycle - they
    rise when an order confirms and fall when an order cancels or refunds ... and
    they are floored at zero, never negative."

    A confirm of 3 NON_MEMBER tickets raises reserved_count to 3; the compensating
    cancel returns it to 0 on a capacity-5 slot.

    Design: Difficulty/compensating_invariant/slot_seat_count_conserved_under_confirm_then_cancel
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot(capacity_total=5)
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"},
         {"ticket_type": "NON_MEMBER", "person_name": "B"},
         {"ticket_type": "NON_MEMBER", "person_name": "C"}],
    )
    assert fx.get_slot(slot["id"])["reserved_count"] == 3

    cancelled = validate_success(api.cancel_order(order["id"], make_patron_headers(patron["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert fx.get_slot(slot["id"])["reserved_count"] == 0, \
        "reserved_count should return to its pre-confirm value"


def test_slot_seat_conservation_order_reaches_cancelled(api):
    """PRD §3.7: "Cancelling a CONFIRMED order moves it to CANCELLED and runs the
    full release."

    Second test of slot-seat conservation: the order ends in CANCELLED and the
    slot is fully released (reserved_count 0).

    Design: Difficulty/compensating_invariant/slot_seat_count_conserved_under_confirm_then_cancel
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot(capacity_total=5)
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "NON_MEMBER", "person_name": "A"},
         {"ticket_type": "NON_MEMBER", "person_name": "B"},
         {"ticket_type": "NON_MEMBER", "person_name": "C"}],
    )
    cancelled = validate_success(api.cancel_order(order["id"], make_patron_headers(patron["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert fx.get_slot(slot["id"])["reserved_count"] == 0
