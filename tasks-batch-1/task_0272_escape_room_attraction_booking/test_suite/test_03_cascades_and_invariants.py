"""Cascading side effects and compensating invariants.

Covers the depth-3 confirm cascade (SPEND -> balance recompute -> DEPLETED), the
depth-2 reschedule cascade (old slot freed -> GM count decremented), and two
conserved quantities (gift-card balance restored on cancel; GM assignment count
conserved on reschedule).
"""
from test_helpers import (
    validate_success,
    setup_draft_booking,
    setup_confirmed_booking,
    confirm_booking,
    cancel_booking,
    create_gift_card,
    create_time_slot,
    get_slot,
    get_game_master,
    get_gift_card,
    make_customer_headers,
    api_client,
)

OFFPEAK_SLOT_1 = "2026-07-01T09:00:00Z"
OFFPEAK_SLOT_2 = "2026-07-01T12:00:00Z"
PEAK_MASK_WED = 4


def _reschedule(booking, customer, new_slot, old_slot_version):
    payload = {
        "new_time_slot_id": new_slot["id"],
        "expected_time_slot_version": old_slot_version,
        "expected_booking_version": booking["version"],
    }
    return validate_success(
        api_client.reschedule_booking(booking["id"], payload, make_customer_headers(customer["id"])), 200)


# ─── transitive_cascade: confirm depth-3 ──────────────
def test_confirm_spend_depletes_gift_card(api):
    """PRD §3.5: "A ledger entry of type `SPEND` is appended to the card with
    `delta_cents` equal to the negative of `gift_card_applied_cents` and its
    `related_booking_id` pointing at this booking; the card's `balance_cents` is then
    recomputed from its full ledger, and if that recomputed balance reaches 0 the card's
    `status` moves from `ACTIVE` to `DEPLETED`."
    PRD §3.5: "`gift_card_applied_cents` is set to the smaller of `quoted_charge_cents`
    and the gift card's current `balance_cents`."

    Off-peak group 4 with large multiplier (2000 ->x1.2 ->2400, *4 = 9600). A 10000
    card spends 9600, leaving 400 -> card stays ACTIVE (not yet depleted).

    Design: Difficulty/transitive_cascade/confirm_cascade_depth3_giftcard_depletes
    """
    venue_ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": 720,
                           "peak_end_minute_of_day": 1080, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    gc = create_gift_card(venue_ctx["venue"]["id"], initial_balance_cents=10000)
    confirmed = confirm_booking(venue_ctx["booking"], venue_ctx["customer"], gift_card_id=gc["id"])

    assert confirmed["quoted_charge_cents"] == 9600
    assert confirmed["gift_card_applied_cents"] == 9600

    card_after = get_gift_card(gc["id"])
    assert card_after["balance_cents"] == 400
    assert card_after["status"] == "ACTIVE"


def test_confirm_spend_to_zero_moves_card_to_depleted(api):
    """PRD §3.5: "if that recomputed balance reaches 0 the card's `status` moves from
    `ACTIVE` to `DEPLETED`."
    PRD §3.5: "`gift_card_applied_cents` is set to the smaller of `quoted_charge_cents`
    and the gift card's current `balance_cents`."

    The terminal hop of the depth-3 chain: a card whose balance exactly equals the
    quote (9600) is drawn to 0 and auto-transitions ACTIVE->DEPLETED.

    Design: Difficulty/transitive_cascade/confirm_cascade_depth3_giftcard_depletes
    """
    venue_ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": 720,
                           "peak_end_minute_of_day": 1080, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    gc = create_gift_card(venue_ctx["venue"]["id"], initial_balance_cents=9600)
    confirmed = confirm_booking(venue_ctx["booking"], venue_ctx["customer"], gift_card_id=gc["id"])

    assert confirmed["gift_card_applied_cents"] == 9600
    card_after = get_gift_card(gc["id"])
    assert card_after["balance_cents"] == 0
    assert card_after["status"] == "DEPLETED"


# ─── transitive_cascade: reschedule depth-2 ───────────
def test_reschedule_frees_old_slot_and_keeps_gamemaster_count(api):
    """PRD §3.6: "The old slot is released `BOOKED → OPEN`: its `booking_id` is cleared,
    its `assigned_game_master_id` is cleared, the previously assigned master's
    `active_assignment_count` is recomputed downward, and the old slot's `version` is
    incremented."
    PRD §3.6: "The new slot is taken `OPEN → HELD → BOOKED`: a master is chosen by the
    same selector, the new slot's `assigned_game_master_id` and `booking_id` are set."

    The depth-2 reschedule cascade originating from CONFIRMED->CONFIRMED: old slot goes
    BOOKED->OPEN and the freed GM's count is decremented (-1), while the new grab adds
    +1 to the selected GM. With one GM the net is 1.

    Design: Difficulty/transitive_cascade/reschedule_cascade_depth2_old_slot_frees_gamemaster
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, customer, gm = ctx["booking"], ctx["customer"], ctx["game_masters"][0]
    slot1 = ctx["slot"]
    slot2 = create_time_slot(ctx["room"]["id"], OFFPEAK_SLOT_2)

    gm_before = get_game_master(gm["id"])
    assert gm_before["active_assignment_count"] == 1

    old_slot_now = get_slot(slot1["id"])
    _reschedule(booking, customer, slot2, old_slot_now["version"])

    slot1_after = get_slot(slot1["id"])
    slot2_after = get_slot(slot2["id"])
    assert slot1_after["status"] == "OPEN"
    assert slot2_after["status"] == "BOOKED"

    gm_after = get_game_master(gm["id"])
    assert gm_after["active_assignment_count"] == 1


def test_reschedule_repoints_booking_to_new_slot(api):
    """PRD §3.6: "The booking's `time_slot_id` and its room-derived fields are updated
    to the new slot."
    PRD §3.6: "The old slot is released `BOOKED → OPEN`."

    The reschedule cascade's primary effect on the booking entity: its `time_slot_id`
    now names the new slot, and the old slot has been freed back to OPEN.

    Design: Difficulty/transitive_cascade/reschedule_cascade_depth2_old_slot_frees_gamemaster
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, customer = ctx["booking"], ctx["customer"]
    slot1 = ctx["slot"]
    slot2 = create_time_slot(ctx["room"]["id"], OFFPEAK_SLOT_2)

    old_slot_now = get_slot(slot1["id"])
    rescheduled = _reschedule(booking, customer, slot2, old_slot_now["version"])
    assert rescheduled["time_slot_id"] == slot2["id"]

    slot1_after = get_slot(slot1["id"])
    assert slot1_after["status"] == "OPEN"


# ─── compensating_invariant: gift card balance ────────
def test_cancel_restores_gift_card_balance_exactly(api):
    """PRD §3.8: "a confirm-then-cancel cycle returns the card's running balance to its
    pre-confirm value precisely."
    PRD §3.8: "a `REFUND` ledger entry is appended to that card with `delta_cents` equal
    to the positive of `gift_card_applied_cents` and `related_booking_id` pointing at
    this booking; the card's `balance_cents` is recomputed, and if the card had
    previously been `DEPLETED` and now carries a positive balance its `status` returns to
    `ACTIVE`. After the refund, the booking's `gift_card_applied_cents` is reset to 0."

    Conserved quantity: a 50000 card spends 9600 at confirm (balance 40400), then a
    cancel refunds +9600, returning to exactly 50000 with no drift.

    Design: Difficulty/compensating_invariant/cancel_restores_gift_card_balance_exactly
    """
    venue_ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": 0, "peak_start_minute_of_day": 720,
                           "peak_end_minute_of_day": 1080, "large_group_threshold": 4,
                           "peak_multiplier_bps": 10000, "large_group_multiplier_bps": 12000},
    )
    gc = create_gift_card(venue_ctx["venue"]["id"], initial_balance_cents=50000)
    confirmed = confirm_booking(venue_ctx["booking"], venue_ctx["customer"], gift_card_id=gc["id"])
    assert confirmed["gift_card_applied_cents"] == 9600
    assert get_gift_card(gc["id"])["balance_cents"] == 40400

    cancelled = cancel_booking(confirmed, venue_ctx["customer"])
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["gift_card_applied_cents"] == 0

    card_after = get_gift_card(gc["id"])
    assert card_after["balance_cents"] == 50000
    assert card_after["status"] == "ACTIVE"


def test_cancel_appends_refund_returning_balance_to_initial(api):
    """PRD §3.8: "Because the refund magnitude equals the original spend exactly — both
    derive from the single `gift_card_applied_cents` figure — a confirm-then-cancel
    cycle returns the card's running balance to its pre-confirm value precisely."
    PRD §3.9: "its `balance_cents` is the running total of `initial_balance_cents` plus
    the signed sum of every ledger entry written against it — across all entries."

    The conserved-quantity invariant viewed through the ledger: SPEND -9600 then
    REFUND +9600 net to zero, so balance returns to the 50000 initial face value.

    Design: Difficulty/compensating_invariant/cancel_restores_gift_card_balance_exactly
    """
    venue_ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": 0, "peak_start_minute_of_day": 720,
                           "peak_end_minute_of_day": 1080, "large_group_threshold": 4,
                           "peak_multiplier_bps": 10000, "large_group_multiplier_bps": 12000},
    )
    gc = create_gift_card(venue_ctx["venue"]["id"], initial_balance_cents=50000)
    confirmed = confirm_booking(venue_ctx["booking"], venue_ctx["customer"], gift_card_id=gc["id"])
    cancel_booking(confirmed, venue_ctx["customer"])

    card_after = get_gift_card(gc["id"])
    assert card_after["balance_cents"] == gc["initial_balance_cents"]


# ─── compensating_invariant: GM assignment count ──────
def test_reschedule_conserves_total_gamemaster_assignment_count(api):
    """PRD §3.6: "the previously assigned master's `active_assignment_count` is
    recomputed downward."
    PRD §2.6: "A game master's `active_assignment_count` always equals the number of
    that master's time slots whose status is `HELD` or `BOOKED`."

    Conserved quantity: reschedule frees the old slot (-1 on its GM) and grabs the new
    (+1 on the selected GM); with one GM the net stays 1 — no double-count, no drift.

    Design: Difficulty/compensating_invariant/reschedule_conserves_gamemaster_assignment_count
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, customer, gm = ctx["booking"], ctx["customer"], ctx["game_masters"][0]
    slot1 = ctx["slot"]
    slot2 = create_time_slot(ctx["room"]["id"], OFFPEAK_SLOT_2)

    assert get_game_master(gm["id"])["active_assignment_count"] == 1

    old_slot_now = get_slot(slot1["id"])
    _reschedule(booking, customer, slot2, old_slot_now["version"])

    assert get_game_master(gm["id"])["active_assignment_count"] == 1
    assert get_slot(slot1["id"])["status"] == "OPEN"
    assert get_slot(slot2["id"])["status"] == "BOOKED"


def test_reschedule_does_not_leave_old_slot_counted(api):
    """PRD §3.6: "The old slot is released `BOOKED → OPEN`: its `booking_id` is cleared,
    its `assigned_game_master_id` is cleared, the previously assigned master's
    `active_assignment_count` is recomputed downward."
    PRD §2.6: "A game master's `active_assignment_count` always equals the number of
    that master's time slots whose status is `HELD` or `BOOKED`."

    The conservation seen from the old slot's side: after reschedule the old slot is
    OPEN with no assigned GM, so it no longer contributes to the count — the single GM
    is still at exactly 1 (the new slot).

    Design: Difficulty/compensating_invariant/reschedule_conserves_gamemaster_assignment_count
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, customer, gm = ctx["booking"], ctx["customer"], ctx["game_masters"][0]
    slot1 = ctx["slot"]
    slot2 = create_time_slot(ctx["room"]["id"], OFFPEAK_SLOT_2)

    old_slot_now = get_slot(slot1["id"])
    _reschedule(booking, customer, slot2, old_slot_now["version"])

    slot1_after = get_slot(slot1["id"])
    assert slot1_after["status"] == "OPEN"
    assert slot1_after["assigned_game_master_id"] is None
    assert get_game_master(gm["id"])["active_assignment_count"] == 1
