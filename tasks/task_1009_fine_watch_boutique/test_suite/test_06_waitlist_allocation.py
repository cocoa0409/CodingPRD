"""Waitlist joins, offer allocation, the offer-expiry boundary, and the
offer-decline compensating invariant on in-stock counts."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    set_clock, new_customer, new_model, new_authenticated_watch, waiting_entry,
    offered_watch, count_in_stock, get_watch, get_waitlist,
    make_client_headers, TEST_USERS,
)
from test_helpers.factories import create_waitlist_entry_payload

ASSOC = TEST_USERS["associate_headers"]


def test_accept_at_exact_expiry_instant_rejected(api):
    """PRD §3.3: "an acceptance at or after that instant is rejected with
    ERR_OFFER_EXPIRED (409) and, in the same lazy step, the entry lapses OFFERED →
    EXPIRED, its allocated_watch_id is cleared, and the watch returns OFFERED →
    IN_STOCK."

    Design: Difficulty/boundary_precision_check/offer_accept_at_exact_expiry_instant
    """
    ctx = offered_watch(clock="2026-07-02T00:00:00Z")  # offer window closes 2026-07-09
    set_clock("2026-07-09T00:00:00Z")  # exactly offer_expires_at
    client = make_client_headers(ctx["customer"]["id"])
    validate_error(api.accept_waitlist_entry(ctx["entry"]["id"], client),
                   ApiErrorId.ERR_OFFER_EXPIRED)


def test_lapsed_offer_expires_entry_and_frees_watch(api):
    """PRD §3.3: "an acceptance at or after that instant is rejected with
    ERR_OFFER_EXPIRED (409) and, in the same lazy step, the entry lapses OFFERED →
    EXPIRED, its allocated_watch_id is cleared, and the watch returns OFFERED →
    IN_STOCK."

    Design: Difficulty/boundary_precision_check/offer_accept_at_exact_expiry_instant
    """
    ctx = offered_watch(clock="2026-07-02T00:00:00Z")
    set_clock("2026-07-09T00:00:00Z")
    client = make_client_headers(ctx["customer"]["id"])
    api.accept_waitlist_entry(ctx["entry"]["id"], client)  # rejected + lazy lapse
    assert get_waitlist(ctx["entry"]["id"])["status"] == "EXPIRED"
    assert get_watch(ctx["watch"]["id"])["status"] == "IN_STOCK"


def test_offer_drops_model_in_stock_count(api):
    """PRD §3.3: "A successful offer advances the selected entry WAITING → OFFERED,
    sets its allocated_watch_id to the watch, sets offer_expires_at to the current
    clock instant plus seven days, moves the watch's inventory status IN_STOCK →
    OFFERED, and appends an ALLOCATED provenance event."

    Design: Difficulty/compensating_invariant/offer_decline_conserves_instock_count
    """
    set_clock("2026-07-02T00:00:00Z")
    customer = new_customer()
    model = new_model(allocation_controlled=True)
    watch = new_authenticated_watch(model["id"], list_price_cents=3000000)
    waiting_entry(model["id"], customer_id=customer["id"], priority_tier="VIP",
                  deposit_cents=100000)
    assert count_in_stock(model["id"]) == 1
    validate_success(api.offer_watch(watch["id"], ASSOC))
    assert count_in_stock(model["id"]) == 0
    assert get_watch(watch["id"])["status"] == "OFFERED"


def test_decline_restores_model_in_stock_count(api):
    """PRD §3.3: "Declining advances the entry OFFERED → DECLINED, clears its
    allocated_watch_id, and returns the watch OFFERED → IN_STOCK under the
    compensating invariant that restores the model's in-stock count."

    Design: Difficulty/compensating_invariant/offer_decline_conserves_instock_count
    """
    set_clock("2026-07-02T00:00:00Z")
    customer = new_customer()
    model = new_model(allocation_controlled=True)
    watch = new_authenticated_watch(model["id"], list_price_cents=3000000)
    entry = waiting_entry(model["id"], customer_id=customer["id"], priority_tier="VIP",
                          deposit_cents=100000)
    validate_success(api.offer_watch(watch["id"], ASSOC))
    assert count_in_stock(model["id"]) == 0
    declined = validate_success(
        api.decline_waitlist_entry(entry["id"], make_client_headers(customer["id"])))
    assert declined["status"] == "DECLINED"
    assert get_watch(watch["id"])["status"] == "IN_STOCK"
    assert count_in_stock(model["id"]) == 1


def test_join_discontinued_model_rejected(api):
    """PRD §3.3: "Two constraints guard the join: a model whose lifecycle is
    DISCONTINUED cannot be joined (ERR_MODEL_DISCONTINUED, 409)".

    Design: Difficulty/cross_entity_state_dependency/waitlist_join_requires_model_active
    """
    customer = new_customer()
    model = new_model(lifecycle="DISCONTINUED")
    validate_error(
        api.create_waitlist_entry(
            create_waitlist_entry_payload(customer["id"], model["id"]), ASSOC),
        ApiErrorId.ERR_MODEL_DISCONTINUED,
    )


def test_join_active_model_succeeds(api):
    """PRD §3.3: "A new entry is born WAITING, with a null allocated_watch_id and
    null offer_expires_at."

    Design: Difficulty/cross_entity_state_dependency/waitlist_join_requires_model_active
    """
    customer = new_customer()
    model = new_model(lifecycle="ACTIVE")
    entry = validate_success(
        api.create_waitlist_entry(
            create_waitlist_entry_payload(customer["id"], model["id"]), ASSOC),
        expected_status=201,
    )
    assert entry["status"] == "WAITING"


def test_offer_with_empty_waitlist_rejected(api):
    """PRD §3.3: "If the candidate set is empty, the offer is refused with
    ERR_NO_ELIGIBLE_WAITLIST (409)."

    Design: Corner/endpoints/offer_with_empty_waitlist_no_eligible
    """
    model = new_model(allocation_controlled=True)
    watch = new_authenticated_watch(model["id"], list_price_cents=3000000)
    validate_error(api.offer_watch(watch["id"], ASSOC), ApiErrorId.ERR_NO_ELIGIBLE_WAITLIST)


def test_accept_waiting_entry_without_offer_rejected(api):
    """PRD §3.3: "Accepting advances the entry OFFERED → ALLOCATED and the watch
    OFFERED → RESERVED, but only while the current clock reads strictly before
    offer_expires_at".
    PRD §2.10: "Among the business rules, state-validity checks (ERR_INVALID_STATE,
    409) and the specific business constraints described throughout Section 3
    apply".

    Design: Corner/state_machines/accept_waiting_entry_without_offer_invalid_state
    """
    customer = new_customer()
    model = new_model()
    entry = waiting_entry(model["id"], customer_id=customer["id"])
    validate_error(api.accept_waitlist_entry(entry["id"], ASSOC), ApiErrorId.ERR_INVALID_STATE)


def test_duplicate_waitlist_same_model_rejected(api):
    """PRD §3.3: "a customer may hold only one non-terminal entry — one in WAITING
    or OFFERED — per model, a second attempt being rejected with
    ERR_DUPLICATE_WAITLIST (409)."

    Design: Corner/validations/duplicate_waitlist_same_model_rejected
    """
    customer = new_customer()
    model = new_model()
    waiting_entry(model["id"], customer_id=customer["id"])
    validate_error(
        api.create_waitlist_entry(
            create_waitlist_entry_payload(customer["id"], model["id"]), ASSOC),
        ApiErrorId.ERR_DUPLICATE_WAITLIST,
    )
