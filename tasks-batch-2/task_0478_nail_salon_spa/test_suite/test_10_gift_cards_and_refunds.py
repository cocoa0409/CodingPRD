"""Gift-card lifecycle (the ACTIVE -> DEPLETED -> ACTIVE cycle, void, overdraw)
and the compensating-refund invariants that conserve gift-card balance and client
loyalty points."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    create_gift_card_payload, redeem_gift_card_payload,
    make_station, make_menu_item, make_technician, make_client, make_gift_card,
    drive_to_in_service, checkout, inject_client_state, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: gift-card ACTIVE -> DEPLETED -> ACTIVE cycle
# ---------------------------------------------------------------------------
def test_gift_card_depletes_on_full_draw_at_checkout(api):
    """PRD §3.10: "If the gift-card draw brought the card's `balance_cents` to
    exactly 0, the card's `status` transitions from `ACTIVE` to `DEPLETED` (a
    system-driven cascade hop) and the card's `version` increments."

    Design: Difficulty/non_linear_state_machine/gift_card_cyclic_active_depleted_active
    """
    set_clock("2026-03-15T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    gc = make_gift_card(initial_balance_cents=4500)
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-03-15T13:00:00Z")
    checkout(started["id"], started["version"], gift_card_id=gc["id"])

    gc_after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert gc_after["balance_cents"] == 0
    assert gc_after["status"] == "DEPLETED"


def test_gift_card_reactivates_on_refund(api):
    """PRD §3.15: "A depleted card returns to `ACTIVE` when a previously-settled
    appointment that drew it is refunded and the restored `balance_cents` is
    positive, completing the cyclic `ACTIVE` -> `DEPLETED` -> `ACTIVE` path, again
    incrementing `version`."

    Design: Difficulty/non_linear_state_machine/gift_card_cyclic_active_depleted_active
    """
    set_clock("2026-03-15T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    gc = make_gift_card(initial_balance_cents=4500)
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-03-15T13:00:00Z")
    completed = checkout(started["id"], started["version"], gift_card_id=gc["id"])

    refunded = validate_success(api.refund_settled(completed["id"], MANAGER))
    assert refunded["payment_status"] == "REFUNDED"
    gc_after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert gc_after["balance_cents"] == 4500
    assert gc_after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: compensating invariant — gift-card balance conserved
# ---------------------------------------------------------------------------
def test_giftcard_balance_restored_to_initial_after_refund(api):
    """PRD §3.14: "The refund restores the gift-card draw to the card's
    `balance_cents`; if that card had been `DEPLETED`, restoring a positive balance
    reverts its `status` from `DEPLETED` to `ACTIVE`".

    Design: Difficulty/compensating_invariant/giftcard_balance_conserved_on_draw_and_refund
    """
    set_clock("2026-04-20T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    gc = make_gift_card(initial_balance_cents=4500)
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-04-20T13:00:00Z")
    completed = checkout(started["id"], started["version"], gift_card_id=gc["id"])

    validate_success(api.refund_settled(completed["id"], MANAGER))
    gc_after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert gc_after["balance_cents"] == 4500   # equals initial_balance_cents


def test_giftcard_reverts_to_active_after_refund(api):
    """PRD §3.14: "The net effect leaves the gift card's `balance_cents` and the
    client's `loyalty_points_balance` at the values they held before checkout ran."
    PRD §3.14: "if that card had been `DEPLETED`, restoring a positive balance
    reverts its `status` from `DEPLETED` to `ACTIVE`".

    Design: Difficulty/compensating_invariant/giftcard_balance_conserved_on_draw_and_refund
    """
    set_clock("2026-04-20T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    gc = make_gift_card(initial_balance_cents=4500)
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-04-20T13:00:00Z")
    completed = checkout(started["id"], started["version"], gift_card_id=gc["id"])

    validate_success(api.refund_settled(completed["id"], MANAGER))
    gc_after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert gc_after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: compensating invariant — loyalty points conserved
# ---------------------------------------------------------------------------
def test_loyalty_consumed_at_checkout_then_restored_on_refund(api):
    """PRD §3.14: "It returns the redeemed loyalty points to the client's
    `loyalty_points_balance` and removes the loyalty points that the completion had
    awarded, leaving the client's balance at its pre-checkout value."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_redeem_and_refund
    """
    set_clock("2026-04-21T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], loyalty_points_balance=60)
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-04-21T13:00:00Z")
    completed = checkout(started["id"], started["version"], loyalty_points_redeemed=50)
    assert completed["total_charged_cents"] == 4000   # 4500 - 50*10

    after_checkout = validate_success(api.get_client(client["id"], FRONT_DESK))
    assert after_checkout["loyalty_points_balance"] == 10   # 60 - 50 + 0 award


def test_loyalty_balance_returns_to_precheckout_after_refund(api):
    """PRD §3.14: "It returns the redeemed loyalty points to the client's
    `loyalty_points_balance` and removes the loyalty points that the completion had
    awarded, leaving the client's balance at its pre-checkout value."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_redeem_and_refund
    """
    set_clock("2026-04-21T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], loyalty_points_balance=60)
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-04-21T13:00:00Z")
    completed = checkout(started["id"], started["version"], loyalty_points_redeemed=50)

    validate_success(api.refund_settled(completed["id"], MANAGER))
    after_refund = validate_success(api.get_client(client["id"], FRONT_DESK))
    assert after_refund["loyalty_points_balance"] == 60   # fully reversed


# ---------------------------------------------------------------------------
# Corner: gift-card void + standalone overdraw
# ---------------------------------------------------------------------------
def test_gift_card_void_zeroes_balance(api):
    """PRD §3.15: "A `SalonManager` may void an `ACTIVE` gift card, which sets its
    `balance_cents` to 0, moves its `status` to the terminal `VOID`, and increments
    its `version` by one."

    Design: Corner/endpoints/gift_card_void_zeroes_balance
    """
    gc = make_gift_card(initial_balance_cents=5000)
    voided = validate_success(api.void_gift_card(gc["id"], MANAGER))
    assert voided["status"] == "VOID"
    assert voided["balance_cents"] == 0


def test_gift_card_overdraw_redeem_rejected(api):
    """PRD §3.15: "The card must be `ACTIVE` and the `amount_cents` must not exceed
    the card's `balance_cents`; an attempt to overdraw or to draw against a
    non-active card is rejected with `ERR_GIFT_CARD_OVERDRAW`."

    Design: Corner/validations/gift_card_overdraw_redeem_rejected
    """
    gc = make_gift_card(initial_balance_cents=3000)
    res = api.redeem_gift_card(
        gc["id"], redeem_gift_card_payload(5000, gc["version"]), FRONT_DESK
    )
    validate_error(res, "ERR_GIFT_CARD_OVERDRAW")
    gc_after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert gc_after["balance_cents"] == 3000
