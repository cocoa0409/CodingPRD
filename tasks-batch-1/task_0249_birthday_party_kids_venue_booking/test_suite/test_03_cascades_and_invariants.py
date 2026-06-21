"""Cascades and conserved-quantity invariants: the cancel -> refund -> status chain,
the remove-extra-time -> duration -> window chain, payment charge/void money
conservation, and hold/release room-window conservation.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_config, create_quote_draft_booking, hold_booking, add_addon, add_waiver,
    sign_waiver, create_held_booking, create_confirmed_booking, create_completed_booking,
    take_payment, assert_instant_eq,
)

COORD = "coordinator_headers"
FIN = "finance_clerk_headers"


# ─── Difficulty: transitive_cascade / tc_cancel_refund_paymentstatus_chain ─────

def test_cancel_synthesizes_refund_and_drives_status_refunded(api, coordinator_headers,
                                                              finance_clerk_headers):
    """PRD 3.12: "That synthesized refund then flows through the reconciliation chain:
    `amount_paid_cents` is recomputed, then `balance_due_cents`, then `payment_status`
    — which lands on `REFUNDED` once the net paid returns to zero."

    Design: Difficulty/transitive_cascade/tc_cancel_refund_paymentstatus_chain
    """
    # Confirmed, fully paid 46500 (CAKE + CHARACTER), clock 2026-06-25 is >=72h before
    # the 2026-07-01 event, so the full-refund variant fires.
    ctx = create_confirmed_booking(
        children_count=8, base_price_cents=30000, included_children=8,
        addons=[("CAKE", 4500), ("CHARACTER", 12000)], pay_amount=46500)
    bid = ctx["booking"]["id"]

    cancelled = validate_success(api.cancel_booking(bid, coordinator_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["amount_paid_cents"] == 0
    assert cancelled["balance_due_cents"] == 46500
    assert cancelled["payment_status"] == "REFUNDED"

    payments, _ = validate_paginated(api.list_payments(bid, finance_clerk_headers))
    refunds = [p for p in payments if p["direction"] == "REFUND"
               and p["purpose"] == "CANCELLATION_REFUND" and p["status"] == "SETTLED"]
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 46500


def test_cancel_refund_recomputes_amount_paid_to_zero(api, coordinator_headers):
    """PRD 3.11: "The booking's `amount_paid_cents` is reconciled as the sum of
    `amount_cents` over all `SETTLED` charges minus the sum of `amount_cents` over all
    `SETTLED` refunds."

    Design: Difficulty/transitive_cascade/tc_cancel_refund_paymentstatus_chain
    """
    ctx = create_confirmed_booking(
        children_count=8, base_price_cents=30000, included_children=8,
        addons=[("CAKE", 4500), ("CHARACTER", 12000)], pay_amount=46500)
    bid = ctx["booking"]["id"]
    assert ctx["booking"]["amount_paid_cents"] == 46500
    cancelled = validate_success(api.cancel_booking(bid, coordinator_headers), 200)
    # 46500 charged - 46500 refunded = 0.
    assert cancelled["amount_paid_cents"] == 0


# ─── Difficulty: transitive_cascade / tc_remove_extratime_duration_window ──────

def test_remove_extra_time_shrinks_duration_and_window(api, coordinator_headers):
    """PRD 3.3: "Whenever an extra-time add-on is added or removed, the server
    recomputes `effective_duration_minutes` and `event_end_utc` and then re-checks the
    room window for overlap. When an extra-time add-on is removed, the event window can
    only shrink, and if the shrunken window still fits the room schedule the removal is
    accepted."

    Design: Difficulty/transitive_cascade/tc_remove_extratime_duration_window
    """
    venue, room, package = setup_config(base_duration_minutes=120)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    addon = add_addon(bid, "EXTRA_TIME", 5000, extra_minutes=60)
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["effective_duration_minutes"] == 180
    assert_instant_eq(booking["event_end_utc"], "2026-07-01T13:00:00Z")

    removed = validate_success(api.delete_add_on(bid, addon["id"], coordinator_headers), 200)
    assert removed["status"] == "REMOVED"
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["effective_duration_minutes"] == 120
    assert_instant_eq(booking["event_end_utc"], "2026-07-01T12:00:00Z")


def test_remove_extra_time_addon_status_removed(api, coordinator_headers):
    """PRD 3.3: "An add-on starts `ACTIVE` and may be removed to `REMOVED`, at which
    point it drops out of both pricing and duration."

    Design: Difficulty/transitive_cascade/tc_remove_extratime_duration_window
    """
    venue, room, package = setup_config(base_duration_minutes=120)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    addon = add_addon(bid, "EXTRA_TIME", 5000, extra_minutes=60)
    removed = validate_success(api.delete_add_on(bid, addon["id"], coordinator_headers), 200)
    assert removed["status"] == "REMOVED"


# ─── Difficulty: compensating_invariant / ci_payment_charge_void_money_conserved

def test_void_charge_restores_amount_paid(api, coordinator_headers, finance_clerk_headers):
    """PRD 3.11: "A `FinanceClerk` may void a payment, moving it from `SETTLED` to
    `VOIDED`, after which it no longer counts toward `amount_paid_cents`."

    Design: Difficulty/compensating_invariant/ci_payment_charge_void_money_conserved
    """
    venue, room, package, booking = create_held_booking(children_count=8, base_price_cents=30000)
    bid = booking["id"]
    payment = take_payment(bid, 7500, direction="CHARGE", purpose="DEPOSIT")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["amount_paid_cents"] == 7500

    voided = validate_success(api.void_payment(bid, payment["id"], finance_clerk_headers), 200)
    assert voided["status"] == "VOIDED"
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["amount_paid_cents"] == 0
    assert booking["balance_due_cents"] == 30000
    assert booking["payment_status"] == "UNPAID"


def test_void_charge_payment_marked_voided(api, coordinator_headers, finance_clerk_headers):
    """PRD 3.11: "A payment starts `SETTLED`."
    PRD 3.11: "A `FinanceClerk` may void a payment, moving it from `SETTLED` to
    `VOIDED`, after which it no longer counts toward `amount_paid_cents`."

    Design: Difficulty/compensating_invariant/ci_payment_charge_void_money_conserved
    """
    venue, room, package, booking = create_held_booking(children_count=8)
    bid = booking["id"]
    payment = take_payment(bid, 7500, direction="CHARGE", purpose="DEPOSIT")
    assert payment["status"] == "SETTLED"
    voided = validate_success(api.void_payment(bid, payment["id"], finance_clerk_headers), 200)
    assert voided["status"] == "VOIDED"


# ─── Difficulty: compensating_invariant / ci_hold_release_room_window_conserved ─

def test_release_hold_frees_window_for_competitor(api, coordinator_headers):
    """PRD 3.7: "A held booking may be released back to `QUOTE_DRAFT`, which frees the
    reserved room window."

    Design: Difficulty/compensating_invariant/ci_hold_release_room_window_conserved
    """
    venue, room, package = setup_config(buffer_minutes=30, max_capacity=20)
    a = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])
    released = validate_success(api.release_hold_booking(a["id"], coordinator_headers), 200)
    assert released["status"] == "QUOTE_DRAFT"

    b = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    held_b = validate_success(api.hold_booking(b["id"], coordinator_headers), 200)
    assert held_b["status"] == "HELD"


def test_competing_hold_blocked_until_release(api, coordinator_headers):
    """PRD 3.7: "Moving a booking from `QUOTE_DRAFT` to `HELD` reserves the room window
    so subsequent overlap checks can see it."

    Design: Difficulty/compensating_invariant/ci_hold_release_room_window_conserved
    """
    venue, room, package = setup_config(buffer_minutes=30, max_capacity=20)
    a = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])
    b = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    # While A holds the window, B cannot hold the identical slot.
    blocked = api.hold_booking(b["id"], coordinator_headers)
    validate_error(blocked, "ERR_ROOM_WINDOW_CONFLICT")
    # After A releases, B succeeds.
    validate_success(api.release_hold_booking(a["id"], coordinator_headers), 200)
    held_b = validate_success(api.hold_booking(b["id"], coordinator_headers), 200)
    assert held_b["status"] == "HELD"


# ─── Corner: state_machines / complete_releases_staff_assignments_cascade ──────

def test_complete_releases_assigned_staff(api, coordinator_headers):
    """PRD 3.10: "On completion the server recomputes `final_total_cents`, reconciles
    `balance_due_cents` as `final_total_cents` minus `amount_paid_cents`, recomputes
    `payment_status`, releases the room window, and releases every `ASSIGNED` staff
    assignment to `RELEASED`."

    Design: Corner/state_machines/complete_releases_staff_assignments_cascade
    """
    ctx = create_completed_booking(children_count=8, base_price_cents=30000,
                                   included_children=8, pay_amount=30000)
    bid = ctx["booking"]["id"]
    host_assignment_id = ctx["staff"]["HOST"]["id"]
    assignments, _ = validate_paginated(api.list_staff_assignments(bid, coordinator_headers))
    host = [a for a in assignments if a["id"] == host_assignment_id][0]
    assert host["status"] == "RELEASED"


# ─── Corner: state_machines / cancel_voids_waivers_and_removes_addons_cascade ──

def test_cancel_cascades_to_addons_and_waivers(api, coordinator_headers):
    """PRD 3.12: "active add-ons become `REMOVED`, assigned staff become `RELEASED`,
    and draft or signed waivers become `VOIDED`."

    Design: Corner/state_machines/cancel_voids_waivers_and_removes_addons_cascade
    """
    venue, room, package = setup_config(included_children=1)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    addon = add_addon(bid, "CAKE", 4500)
    hold_booking(bid)
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])

    cancelled = validate_success(api.cancel_booking(bid, coordinator_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    addons, _ = validate_paginated(api.list_add_ons(bid, coordinator_headers))
    assert [a for a in addons if a["id"] == addon["id"]][0]["status"] == "REMOVED"
    waivers, _ = validate_paginated(api.list_waivers(bid, coordinator_headers))
    assert [w for w in waivers if w["id"] == waiver["id"]][0]["status"] == "VOIDED"
