"""Payment waterfall, gift-card lifecycle, and reload OCC.

Queue A: non_linear_state_machine (gift card cycle), compensating_invariant
(gift-card + wallet conservation). Queue B: waterfall split, txn immutability,
reload errors.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_member,
    create_open_session,
    create_booking,
    confirm_booking,
    create_confirmed_booking,
    create_gift_card,
    seed_wallet,
    get_session_version,
    get_gift_card_version,
    set_clock,
    make_member_headers,
    make_instructor_headers,
)


def test_waterfall_draws_gift_cards_oldest_first_then_wallet(api):
    """PRD §3.6: "Every GiftCard that the member owns and that is ACTIVE is
    consulted in ascending created_at order - oldest card first, never by
    identifier - and each card contributes the lesser of its remaining
    balance_cents and the amount still owed"
    PRD §3.6: "Whatever remains then draws on the member's wallet_credit_cents,
    contributing the lesser of the wallet balance and the remaining amount,
    recorded on the booking as wallet_applied_cents. Any residual is charged to
    the external card and recorded as card_applied_cents."

    Charge 52380: GC1 20000 (oldest) + GC2 30000 = 50000 gift, then wallet 2380,
    card 0.

    Design: Corner/calculations/waterfall_multi_giftcard_oldest_first_then_wallet
    """
    member = create_member()
    gc1 = create_gift_card(member["id"], 20000, code="GC-WF-1")
    gc2 = create_gift_card(member["id"], 30000, code="GC-WF-2")
    seed_wallet(member["id"], 5000)
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "ADVANCED", "base_price_cents": 8500, "default_capacity": 6,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 6, "station_id": "ST-WF"},
        ingredient_overrides={"name": "w", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    booking = create_booking(session["id"], member["id"], 6)
    confirmed = confirm_booking(booking["id"], session["id"], member["id"])

    assert confirmed["gift_card_applied_cents"] == 50000
    assert confirmed["wallet_applied_cents"] == 2380
    assert confirmed["card_applied_cents"] == 0
    gc1_after = validate_success(api.get_gift_card(gc1["id"], make_member_headers(member["id"])), 200)
    gc2_after = validate_success(api.get_gift_card(gc2["id"], make_member_headers(member["id"])), 200)
    assert gc1_after["balance_cents"] == 0
    assert gc2_after["balance_cents"] == 0
    member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert member_after["wallet_credit_cents"] == 2620, (
        f"wallet 5000 - 2380 applied = 2620, got {member_after['wallet_credit_cents']}"
    )


def test_gift_card_depletes_then_reload_reactivates(api):
    """PRD §3.6: "When a gift card's balance_cents reaches 0 through redemption,
    that card transitions ACTIVE -> DEPLETED and is no longer selected by the
    waterfall."
    PRD §3.6: "A successful reload appends a RELOAD ledger entry, increases
    balance_cents by the reloaded amount, transitions the card DEPLETED -> ACTIVE,
    and increments its version."

    A 9000 INTERMEDIATE charge drains a 9000 card to DEPLETED; a 5000 reload
    returns it to ACTIVE with balance 5000.

    Design: Difficulty/non_linear_state_machine/gift_card_active_depleted_active_cycle
    """
    member = create_member()
    gc = create_gift_card(member["id"], 9000, code="GC-CYCLE")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 2, "station_id": "ST-GC-CYCLE"},
        ingredient_overrides={"name": "yeast", "qty_per_seat": 0.01, "unit_cost_cents": 50},
    )
    create_confirmed_booking(session["id"], member["id"], 1)  # charge 9000 drains the card

    depleted = validate_success(api.get_gift_card(gc["id"], make_member_headers(member["id"])), 200)
    assert depleted["status"] == "DEPLETED"
    assert depleted["balance_cents"] == 0

    reloaded = validate_success(
        api.reload_gift_card(gc["id"], 5000, depleted["version"], make_member_headers(member["id"])), 200
    )
    assert reloaded["status"] == "ACTIVE"
    assert reloaded["balance_cents"] == 5000


def test_gift_card_cycle_second_witness_via_void(api):
    """PRD §3.6: "A StudioAdmin may void an ACTIVE card, transitioning it
    ACTIVE -> VOIDED, after which its balance is frozen and it is no longer
    redeemable."

    A second witness on the GiftCard machine's branch out of ACTIVE: voiding an
    ACTIVE card freezes it at VOIDED with its balance intact.

    Design: Difficulty/non_linear_state_machine/gift_card_active_depleted_active_cycle
    """
    from test_helpers import TEST_USERS
    member = create_member()
    gc = create_gift_card(member["id"], 4000, code="GC-VOID")
    voided = validate_success(
        api.void_gift_card(gc["id"], TEST_USERS["studio_admin_headers"]), 200
    )
    assert voided["status"] == "VOIDED"
    assert voided["balance_cents"] == 4000, "balance frozen on void"


def test_issuing_gift_card_writes_issue_ledger_entry(api):
    """PRD §3.6: "The new card is ACTIVE, its balance_cents is seeded to the
    initial value, and an ISSUE ledger entry records the load."
    PRD §2.4: "A GiftCardTxn ... and a NoShowRecord ... are immutable once
    written: each carries only an id and a created_at, and neither carries an
    updated_at nor a version."

    A freshly issued 5000 card has exactly one ISSUE txn of amount 5000, and the
    ledger row has no version field.

    Design: Corner/entities/giftcardtxn_immutable_no_version_field
    """
    member = create_member()
    gc = create_gift_card(member["id"], 5000, code="GC-ISSUE")
    res = api.list_gift_card_transactions(gc["id"], make_member_headers(member["id"]))
    data, meta = validate_paginated(res)
    assert len(data) == 1
    txn = data[0]
    assert txn["kind"] == "ISSUE"
    assert txn["amount_cents"] == 5000
    assert "version" not in txn, "GiftCardTxn is append-only — no version"
    assert "updated_at" not in txn, "GiftCardTxn is append-only — no updated_at"


def test_reload_with_stale_version_rejected(api):
    """PRD §2.6: "If the card's current version no longer equals the supplied
    expected_gift_card_version - because another redemption has depleted it
    further or another reload has already run - the reload is rejected with
    ERR_STALE_GIFT_CARD_VERSION at HTTP status 412."

    A reload carrying expected_gift_card_version one behind the current version is
    rejected as stale.

    Design: Corner/errors/stale_gift_card_version_on_reload
    """
    member = create_member()
    gc = create_gift_card(member["id"], 9000, code="GC-STALE")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 2, "station_id": "ST-GC-STALE"},
        ingredient_overrides={"name": "y", "qty_per_seat": 0.01, "unit_cost_cents": 50},
    )
    create_confirmed_booking(session["id"], member["id"], 1)  # depletes the card
    current_v = get_gift_card_version(gc["id"], member["id"])
    res = api.reload_gift_card(gc["id"], 5000, current_v - 1, make_member_headers(member["id"]))
    validate_error(res, "ERR_STALE_GIFT_CARD_VERSION", expected_status=412)


def test_reload_zero_amount_rejected(api):
    """PRD §3.6: "the request supplies an amount_cents to add (which must be at
    least 1 cent, else ERR_INVALID_RELOAD_AMOUNT)"

    A reload of amount_cents=0 on a depleted card with a matching version is
    rejected with ERR_INVALID_RELOAD_AMOUNT.

    Design: Corner/errors/invalid_reload_amount_rejected
    """
    member = create_member()
    gc = create_gift_card(member["id"], 9000, code="GC-INVAMT")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 2, "station_id": "ST-GC-INV"},
        ingredient_overrides={"name": "y", "qty_per_seat": 0.01, "unit_cost_cents": 50},
    )
    create_confirmed_booking(session["id"], member["id"], 1)  # depletes the card
    current_v = get_gift_card_version(gc["id"], member["id"])
    res = api.reload_gift_card(gc["id"], 0, current_v, make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_RELOAD_AMOUNT", expected_status=422)


def test_void_nonexistent_gift_card_not_found(api):
    """PRD §2.8: "a referenced resource that does not exist yields ERR_NOT_FOUND."

    Voiding a gift card whose id does not resolve returns ERR_NOT_FOUND (404).

    Design: Corner/errors/gift_card_not_found_on_void
    """
    from test_helpers import TEST_USERS
    res = api.void_gift_card(
        "00000000-0000-4000-8000-0000000000aa", TEST_USERS["studio_admin_headers"]
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_booking_cancel_conserves_gift_card_plus_wallet_value(api):
    """PRD §3.7: "a cancellation at least 168 hours before the start refunds 100
    percent" and "the base refund is that gross minus a flat cancellation fee of
    300 cents, floored at 0".
    PRD §3.7: "the gift-card portion of the original payment is reversed first via
    REVERSAL ledger entries up to gift_card_applied_cents with any remainder
    returned to the wallet".

    A 9000 booking paid fully from a 9000 gift card, cancelled 200h before: refund
    8700, all reversed to the gift card (none spills to wallet). Conserved value
    gift_card_balance + wallet = 8700 (the 300 fee consumed).

    Design: Difficulty/compensating_invariant/booking_cancel_conserves_gift_card_plus_wallet_value
    """
    set_clock("2026-10-01T00:00:00Z")
    member = create_member()
    gc = create_gift_card(member["id"], 9000, code="GC-CONS")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-CONS",
            "start_at": "2026-10-09T08:00:00Z", "end_at": "2026-10-09T10:00:00Z",
        },
        ingredient_overrides={"name": "egg", "qty_per_seat": 0.1, "unit_cost_cents": 30},
    )
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])
    gc_after_confirm = validate_success(api.get_gift_card(gc["id"], make_member_headers(member["id"])), 200)
    assert gc_after_confirm["balance_cents"] == 0

    validate_success(api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200)
    gc_after = validate_success(api.get_gift_card(gc["id"], make_member_headers(member["id"])), 200)
    member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert gc_after["balance_cents"] == 8700, (
        f"gift card reversed first to 8700, got {gc_after['balance_cents']}"
    )
    assert member_after["wallet_credit_cents"] == 0, "entire refund returned to the gift card"
    assert gc_after["balance_cents"] + member_after["wallet_credit_cents"] == 8700, (
        "conserved stored value == 9000 - 300 fee"
    )


def test_booking_cancel_reverses_gift_card_via_reversal_txn(api):
    """PRD §3.7: "the gift-card portion of the original payment is reversed first
    via REVERSAL ledger entries up to gift_card_applied_cents with any remainder
    returned to the wallet".
    PRD §3.6: "a kind of ISSUE, REDEEM, RELOAD, or REVERSAL, and a signed
    amount_cents that is positive for ISSUE, RELOAD, and REVERSAL and negative for
    REDEEM."

    A second witness on the conserved gift-card+wallet value: the cancel appends a
    REVERSAL txn that restores the gift-card balance to 8700 (the full 8700 refund
    fits within the 9000 gift-card-applied portion, so none spills to the wallet).

    Design: Difficulty/compensating_invariant/booking_cancel_conserves_gift_card_plus_wallet_value
    """
    set_clock("2026-10-01T00:00:00Z")
    member = create_member()
    gc = create_gift_card(member["id"], 9000, code="GC-REV")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-REV",
            "start_at": "2026-10-09T08:00:00Z", "end_at": "2026-10-09T10:00:00Z",
        },
        ingredient_overrides={"name": "egg", "qty_per_seat": 0.1, "unit_cost_cents": 30},
    )
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])
    validate_success(api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200)

    data, _meta = validate_paginated(
        api.list_gift_card_transactions(gc["id"], make_member_headers(member["id"]))
    )
    kinds = [t["kind"] for t in data]
    assert "REVERSAL" in kinds, f"a REVERSAL txn must be appended on cancel, got {kinds}"
    reversal_total = sum(t["amount_cents"] for t in data if t["kind"] == "REVERSAL")
    assert reversal_total == 8700, (
        f"REVERSAL credits the 8700 refund back to the gift card, got {reversal_total}"
    )
    gc_after = validate_success(api.get_gift_card(gc["id"], make_member_headers(member["id"])), 200)
    assert gc_after["balance_cents"] == 8700
