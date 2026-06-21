"""Buddy tickets: the RESERVED->REDEEMED/CANCELLED branches, allotment accounting
and conservation, the same-day double-book conflict, and the exhausted-allotment
guardrail.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
)

OPS = TEST_USERS["resort_ops_headers"]


def test_buddy_ticket_branches_to_redeemed_or_cancelled(api):
    """PRD §3.4: "Redeeming it transitions it from `RESERVED` to `REDEEMED`".
    PRD §3.4: "Cancelling a ticket transitions it from `RESERVED` to `CANCELLED`;
    cancellation is permitted only when the ticket is currently `RESERVED`, frees
    the consumed slot by recomputing the host pass's `buddy_tickets_remaining`
    upward".

    Design: Difficulty/non_linear_state_machine/buddy_ticket_branching_reserved_to_redeemed_or_cancelled
    """
    _product, _resort, active, buddies = fixtures.setup_active_pass_with_buddies(
        api, num_buddies=2, allotment=2, buddy_price_cents=2500,
        clock_iso="2026-01-06T08:00:00Z", base_date="2026-01-07",
    )
    bt1, bt2 = buddies
    redeemed = validate_success(api.redeem_buddy_ticket(bt1["id"], OPS), 200)
    assert redeemed["status"] == "REDEEMED"
    cancelled = validate_success(api.cancel_buddy_ticket(bt2["id"], OPS), 200)
    assert cancelled["status"] == "CANCELLED"
    pass_now = fixtures.get_pass(api, active["id"])
    assert pass_now["buddy_tickets_remaining"] == 1, \
        "one REDEEMED (consumes) + one CANCELLED (frees) on allotment 2 -> remaining 1"


def test_buddy_redeem_keeps_slot_cancel_frees_slot(api):
    """PRD §3.4: "A redeemed ticket keeps its allotment slot consumed."
    PRD §3.4: "Cancelling a ticket transitions it from `RESERVED` to `CANCELLED`;
    cancellation is permitted only when the ticket is currently `RESERVED`, frees
    the consumed slot by recomputing the host pass's `buddy_tickets_remaining`
    upward".

    Design: Difficulty/non_linear_state_machine/buddy_ticket_branching_reserved_to_redeemed_or_cancelled
    """
    _product, _resort, active, buddies = fixtures.setup_active_pass_with_buddies(
        api, num_buddies=2, allotment=2, buddy_price_cents=2500,
        clock_iso="2026-01-09T08:00:00Z", base_date="2026-01-10",
    )
    bt1, bt2 = buddies
    validate_success(api.redeem_buddy_ticket(bt1["id"], OPS), 200)
    after_redeem = fixtures.get_pass(api, active["id"])
    assert after_redeem["buddy_tickets_remaining"] == 0, \
        "REDEEMED ticket keeps its slot consumed; remaining stays 0 with both still counted"
    validate_success(api.cancel_buddy_ticket(bt2["id"], OPS), 200)
    after_cancel = fixtures.get_pass(api, active["id"])
    assert after_cancel["buddy_tickets_remaining"] == 1, \
        "cancelling the second ticket frees only its slot -> remaining 1"


def test_buddy_allotment_conserved_across_reserve_then_cancel(api):
    """PRD §3.4: "the host pass's `buddy_tickets_remaining` is recomputed downward
    to reflect the newly consumed slot."
    PRD §3.4: "Cancelling a ticket transitions it from `RESERVED` to `CANCELLED`;
    cancellation is permitted only when the ticket is currently `RESERVED`, frees
    the consumed slot by recomputing the host pass's `buddy_tickets_remaining`
    upward".

    Design: Difficulty/compensating_invariant/buddy_allotment_conservation_reserve_cancel
    """
    fixtures.set_clock(api, "2026-01-29T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="Conserve Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Conserve Host")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-30", guest_name="G1")
    after_reserve = fixtures.get_pass(api, issued["id"])
    assert after_reserve["buddy_tickets_remaining"] == 1, \
        "reserve decrements remaining from 2 to 1"
    validate_success(api.cancel_buddy_ticket(bt["id"], OPS), 200)
    after_cancel = fixtures.get_pass(api, issued["id"])
    assert after_cancel["buddy_tickets_remaining"] == 2, \
        "cancel restores remaining to the original allotment 2 with zero drift"


def test_buddy_cancel_restores_remaining_with_zero_net_drift(api):
    """PRD §3.4: "the host pass's `buddy_tickets_remaining` is recomputed downward
    to reflect the newly consumed slot."
    PRD §3.4: "Cancelling a ticket transitions it from `RESERVED` to `CANCELLED`...
    frees the consumed slot by recomputing the host pass's `buddy_tickets_remaining`
    upward".

    Design: Difficulty/compensating_invariant/buddy_allotment_conservation_reserve_cancel
    """
    fixtures.set_clock(api, "2026-01-30T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="Conserve2 Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Conserve Host 2")
    fixtures.activate_pass(api, issued["id"])
    bt_a = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-01", guest_name="GA")
    bt_b = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-02", guest_name="GB")
    assert fixtures.get_pass(api, issued["id"])["buddy_tickets_remaining"] == 0, \
        "two reserves on allotment 2 -> remaining 0"
    validate_success(api.cancel_buddy_ticket(bt_a["id"], OPS), 200)
    validate_success(api.cancel_buddy_ticket(bt_b["id"], OPS), 200)
    assert fixtures.get_pass(api, issued["id"])["buddy_tickets_remaining"] == 2, \
        "cancelling both restores remaining to the full allotment 2 — conserved quantity"


def test_buddy_remaining_excludes_cancelled_counts_redeemed(api):
    """PRD §3.4: "it is the product's `buddy_ticket_allotment` minus the count of
    this pass's buddy tickets whose `status` is `RESERVED` or `REDEEMED`. Tickets
    in `CANCELLED` are excluded from that count and therefore do not consume
    allotment".

    Design: Corner/calculations/buddy_remaining_excludes_cancelled
    """
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=3,
        buddy_ticket_price_cents=1000,
    )
    resort = fixtures.create_resort(api, name="Excl Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Excl Host")
    fixtures.activate_pass(api, issued["id"])
    bt1 = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-07", guest_name="G1")
    bt2 = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-08", guest_name="G2")
    validate_success(api.redeem_buddy_ticket(bt1["id"], OPS), 200)
    validate_success(api.cancel_buddy_ticket(bt2["id"], OPS), 200)
    pass_now = fixtures.get_pass(api, issued["id"])
    assert pass_now["buddy_tickets_remaining"] == 2, \
        "allotment 3 minus one REDEEMED (CANCELLED excluded) -> 2"


def test_buddy_reserve_copies_price_charged_from_product(api):
    """PRD §3.4: "its `price_charged_cents` is copied from the host product's
    `buddy_ticket_price_cents`".

    Design: Corner/entities/buddy_reserve_copies_price_charged_from_product
    """
    fixtures.set_clock(api, "2026-01-04T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=2500,
    )
    resort = fixtures.create_resort(api, name="Price Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Price Host")
    fixtures.activate_pass(api, issued["id"])
    bt = validate_success(
        api.create_buddy_ticket(
            factories.create_buddy_ticket_payload(
                issued["id"], resort["id"], "2026-01-06", guest_name="G1"
            ),
            OPS,
        ),
        201,
    )
    assert bt["price_charged_cents"] == 2500, \
        "price_charged_cents copied from product buddy_ticket_price_cents (2500)"
    assert bt["status"] == "RESERVED"


def test_buddy_reserve_exhausted_allotment_returns_exhausted(api):
    """PRD §3.4: "reserving a ticket requires the host pass to have at least one
    buddy slot left, meaning its `buddy_tickets_remaining` must be 1 or greater; a
    reservation against an exhausted allotment is rejected with
    `ERR_BUDDY_ALLOTMENT_EXHAUSTED`."

    Design: Corner/validations/buddy_reserve_exhausted_allotment_returns_exhausted
    """
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=1,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="Exhaust Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Exhaust Host")
    fixtures.activate_pass(api, issued["id"])
    fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-09", guest_name="G1")
    resp = api.create_buddy_ticket(
        factories.create_buddy_ticket_payload(
            issued["id"], resort["id"], "2026-02-10", guest_name="G2"
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_BUDDY_ALLOTMENT_EXHAUSTED.value, 409)


def test_buddy_same_day_same_guest_same_resort_conflict(api):
    """PRD §3.4: "a `guest_name` may not hold two non-`CANCELLED` buddy tickets for
    the same `valid_date` at the same `resort_id`. A reservation that would collide
    with an existing `RESERVED` or `REDEEMED` ticket for that same guest, date, and
    resort is rejected with `ERR_BUDDY_DATE_CONFLICT`".

    Design: Difficulty/resource_temporal_overlap/buddy_same_day_calendar_point_overlap
    """
    fixtures.set_clock(api, "2026-01-28T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=3,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="DatePoint Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Date Host")
    fixtures.activate_pass(api, issued["id"])
    fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-30", guest_name="Sam Lee")
    resp = api.create_buddy_ticket(
        factories.create_buddy_ticket_payload(
            issued["id"], resort["id"], "2026-01-30", guest_name="Sam Lee"
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_BUDDY_DATE_CONFLICT.value, 409)


def test_buddy_same_guest_different_date_is_allowed(api):
    """PRD §3.4: "a `guest_name` may not hold two non-`CANCELLED` buddy tickets for
    the same `valid_date` at the same `resort_id`. A reservation that would collide
    with an existing `RESERVED` or `REDEEMED` ticket for that same guest, date, and
    resort is rejected with `ERR_BUDDY_DATE_CONFLICT`; this is a same-calendar-day
    collision".

    Design: Difficulty/resource_temporal_overlap/buddy_same_day_calendar_point_overlap
    """
    fixtures.set_clock(api, "2026-01-28T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=3,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="DatePoint2 Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Date Host 2")
    fixtures.activate_pass(api, issued["id"])
    fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-30", guest_name="Sam Lee")
    # Same guest, same resort, DIFFERENT date -> no same-calendar-day collision.
    second = validate_success(
        api.create_buddy_ticket(
            factories.create_buddy_ticket_payload(
                issued["id"], resort["id"], "2026-01-31", guest_name="Sam Lee"
            ),
            OPS,
        ),
        201,
    )
    assert second["status"] == "RESERVED", \
        "the conflict is a same-calendar-day point collision; a different date is allowed"


def test_redeem_requires_host_pass_active_blocked_after_suspend_cascade(api):
    """PRD §3.4: "redemption is permitted only when the ticket is currently
    `RESERVED` and additionally requires the host pass to be `ACTIVE` at that
    moment — a cross-entity guard."
    PRD §3.2: "Suspension cascades: every buddy ticket of the pass that is still
    `RESERVED` is moved to `CANCELLED`".
    PRD §3.4: "Attempting either transition on a ticket that is not `RESERVED` is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/buddy_redeem_requires_pass_active
    """
    fixtures.set_clock(api, "2026-01-22T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="Kirkwood", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="XEntity Host")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-23", guest_name="G1")
    validate_success(api.suspend_pass(issued["id"], OPS), 200)
    bt_now = validate_success(api.get_buddy_ticket(bt["id"], OPS), 200)
    assert bt_now["status"] == "CANCELLED", \
        "suspending the host pass cancels its RESERVED ticket via cascade"
    resp = api.redeem_buddy_ticket(bt["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_redeem_succeeds_while_host_pass_active(api):
    """PRD §3.4: "Redeeming it transitions it from `RESERVED` to `REDEEMED`;
    redemption is permitted only when the ticket is currently `RESERVED` and
    additionally requires the host pass to be `ACTIVE` at that moment — a
    cross-entity guard."

    Design: Difficulty/cross_entity_state_dependency/buddy_redeem_requires_pass_active
    """
    fixtures.set_clock(api, "2026-01-23T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="Kirkwood2", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="XEntity Host 2")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-24", guest_name="G1")
    redeemed = validate_success(api.redeem_buddy_ticket(bt["id"], OPS), 200)
    assert redeemed["status"] == "REDEEMED", \
        "with the host pass ACTIVE, the cross-entity guard is satisfied and redeem succeeds"


def test_redeem_cancelled_buddy_ticket_returns_invalid_state(api):
    """PRD §3.4: "Attempting either transition on a ticket that is not `RESERVED`
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/redeem_cancelled_buddy_ticket_returns_invalid_state
    """
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=2000,
    )
    resort = fixtures.create_resort(api, name="Cancel Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Cancel Host")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-02", guest_name="G1")
    validate_success(api.cancel_buddy_ticket(bt["id"], OPS), 200)
    resp = api.redeem_buddy_ticket(bt["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_suspend_pass_cancels_reserved_buddy_tickets_cascade(api):
    """PRD §3.2: "Suspension cascades: every buddy ticket of the pass that is still
    `RESERVED` is moved to `CANCELLED`, the pass's `buddy_tickets_remaining` is
    recomputed accordingly, and the pass's `version` increments by one."

    Design: Corner/state_machines/suspend_pass_cancels_reserved_buddy_tickets_cascade
    """
    _product, _resort, active, buddies = fixtures.setup_active_pass_with_buddies(
        api, num_buddies=2, allotment=2, buddy_price_cents=2000,
        clock_iso="2026-02-03T08:00:00Z", base_date="2026-02-03",
    )
    bt1, bt2 = buddies
    suspended = validate_success(api.suspend_pass(active["id"], OPS), 200)
    assert suspended["status"] == "SUSPENDED"
    assert validate_success(api.get_buddy_ticket(bt1["id"], OPS), 200)["status"] == "CANCELLED"
    assert validate_success(api.get_buddy_ticket(bt2["id"], OPS), 200)["status"] == "CANCELLED"
    assert suspended["buddy_tickets_remaining"] == 2, \
        "both RESERVED tickets cancelled -> remaining recomputed to full allotment 2"


def test_reactivate_suspended_does_not_restore_cancelled_buddies(api):
    """PRD §3.2: "on reinstatement `activated_on` and `refund_basis_cents` are left
    exactly as they were at first activation — they are not recomputed — and buddy
    tickets that were previously cancelled are not restored."

    Design: Corner/state_machines/reactivate_suspended_does_not_restore_cancelled_buddy_tickets
    """
    fixtures.set_clock(api, "2026-02-05T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, buddy_ticket_allotment=1,
        buddy_ticket_price_cents=1000,
    )
    resort = fixtures.create_resort(api, name="Reinstate Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Reinstate Host")
    fixtures.activate_pass(api, issued["id"])
    bt = fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-06", guest_name="G1")
    validate_success(api.suspend_pass(issued["id"], OPS), 200)
    reactivated = validate_success(api.activate_pass(issued["id"], OPS), 200)
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["refund_basis_cents"] == 5000
    assert validate_success(api.get_buddy_ticket(bt["id"], OPS), 200)["status"] == "CANCELLED"
    assert reactivated["buddy_tickets_remaining"] == 1


def test_buddy_remaining_consistent_immediately_after_reserve(api):
    """PRD §2.6: "These propagations are immediate and consistent: a read of the
    pass after any such event reflects the new counts and the new version with no
    deferral."
    PRD §3.4: "the host pass's `buddy_tickets_remaining` is recomputed downward to
    reflect the newly consumed slot."

    Design: Corner/consistency_model/buddy_remaining_consistent_immediately_after_reserve
    """
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=4000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=1000,
    )
    resort = fixtures.create_resort(api, name="Immed Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Immed Host")
    fixtures.activate_pass(api, issued["id"])
    fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-02-13", guest_name="G1")
    pass_now = fixtures.get_pass(api, issued["id"])
    assert pass_now["buddy_tickets_remaining"] == 1, \
        "remaining reflects the decrement in the same request cycle (allotment 2 -> 1)"
