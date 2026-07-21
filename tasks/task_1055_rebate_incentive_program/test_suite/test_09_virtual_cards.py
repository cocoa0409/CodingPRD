"""Virtual cards: issuance, activation, spending and implicit clearing."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    read_claim,
    read_payout,
    read_virtual_card,
    setup_activated_card,
    setup_issued_card,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_clearing_a_virtual_card_payout_by_hand_is_refused(api):
    """PRD §3.8: "Clearing applies only to a payout whose `method` is `CHECK`; a
    `VIRTUAL_CARD` payout is cleared implicitly when its card is fully spent and
    may not be cleared by hand, and the attempt is refused with
    `ERR_NOT_CHECK_PAYOUT` (HTTP 409)."

    Design: Corner/state_machines/clear_on_a_virtual_card_payout_is_rejected
    """
    ctx = setup_issued_card(
        program_overrides={"name": "Card Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Card Offer"},
        claimant_overrides={"legal_name": "Card Consumer", "email": "cc@cc.example"},
        serial_number="SN-CRD-1",
    )
    resp = api.clear_payout(ctx["payout"]["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_NOT_CHECK_PAYOUT.value)

    assert read_payout(ctx["payout"]["id"])["status"] == "RELEASED"

    cards, meta = validate_paginated(
        api.list_virtual_cards(ADMIN, params={"payout_id": ctx["payout"]["id"]})
    )
    assert meta["total_count"] == 1
    assert cards[0]["status"] == "ISSUED"
    assert cards[0]["remaining_balance_cents"] == 2450


def test_spending_before_activation_is_refused_and_succeeds_afterwards(api):
    """PRD §3.8: "Activation or spending attempted from a state that does not
    declare it, or against a payout that is not `RELEASED`, is refused with
    `ERR_CARD_NOT_ACTIVE` (HTTP 409)."
    PRD §3.8: "A spend strictly less than the remaining balance reduces
    `remaining_balance_cents` by the spent amount, stamps `last_activity_at`, and
    leaves the card in `PARTIALLY_USED` — arriving there from `ACTIVATED` on the
    first partial spend and staying there on subsequent ones."

    Design: Corner/state_machines/spend_before_activation_is_rejected_then_succeeds_after_activate
    """
    ctx = setup_issued_card(
        program_overrides={"name": "Spend Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Spend Offer"},
        claimant_overrides={"legal_name": "Spend Consumer", "email": "sp@sp.example"},
        serial_number="SN-SPD-1",
    )
    too_early = api.spend_virtual_card(
        ctx["card"]["id"], {"amount_cents": 1000, "merchant_name": "Hardware Depot"},
        ctx["headers"],
    )
    validate_error(too_early, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)

    activated = validate_success(
        api.activate_virtual_card(ctx["card"]["id"], ctx["headers"])
    )
    assert activated["status"] == "ACTIVATED"
    assert activated["remaining_balance_cents"] == 2450

    spent = validate_success(
        api.spend_virtual_card(
            ctx["card"]["id"],
            {"amount_cents": 1000, "merchant_name": "Hardware Depot"},
            ctx["headers"],
        )
    )
    assert spent["status"] == "PARTIALLY_USED"
    assert spent["remaining_balance_cents"] == 1450


def test_exhausting_a_card_clears_its_parent_payout(api):
    """PRD §3.8: "A spend exactly equal to the remaining balance drives
    `remaining_balance_cents` to zero and moves the card to the terminal
    `EXHAUSTED` state, which in turn moves its parent payout
    `RELEASED → CLEARED`."

    Design: Corner/state_machines/exhausting_a_card_clears_the_parent_payout
    """
    ctx = setup_activated_card(
        program_overrides={"name": "Exhaust Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Exhaust Offer"},
        claimant_overrides={"legal_name": "Exhaust Consumer", "email": "ex@ex.example"},
        serial_number="SN-EXH-1",
    )
    spent = validate_success(
        api.spend_virtual_card(
            ctx["card"]["id"],
            {"amount_cents": 2450, "merchant_name": "Hardware Depot"},
            ctx["headers"],
        )
    )
    assert spent["status"] == "EXHAUSTED"
    assert spent["remaining_balance_cents"] == 0
    assert read_payout(ctx["payout"]["id"])["status"] == "CLEARED"
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "PAID"


def test_spending_above_the_remaining_balance_is_refused(api):
    """PRD §3.8: "The amount must be greater than zero and at most the card's
    `remaining_balance_cents`; anything outside that range is refused with
    `ERR_INSUFFICIENT_CARD_BALANCE` (HTTP 422)."

    Design: Corner/validations/spend_above_remaining_card_balance_is_rejected
    """
    ctx = setup_activated_card(
        program_overrides={"name": "Overspend Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Overspend Offer"},
        claimant_overrides={"legal_name": "Overspend Consumer", "email": "os@os.example"},
        serial_number="SN-OS-1",
    )
    resp = api.spend_virtual_card(
        ctx["card"]["id"],
        {"amount_cents": 3000, "merchant_name": "Hardware Depot"},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CARD_BALANCE.value)

    card = read_virtual_card(ctx["card"]["id"])
    assert card["remaining_balance_cents"] == 2450
    assert card["status"] == "ACTIVATED"
