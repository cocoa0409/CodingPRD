"""Transitive cascades: layaway default → free watch → auto-offer, and
flag-inauthentic → void active layaway → refund store credit."""
from test_helpers import (
    api_client, validate_success,
    set_clock, new_customer, new_model, new_authenticated_watch, waiting_entry,
    active_layaway, get_watch, get_layaway, get_waitlist, get_customer, TEST_USERS,
)
from test_helpers.factories import create_layaway_plan_payload

ASSOC = TEST_USERS["associate_headers"]


def _default_cascade_setup():
    """Alice's ACTIVE layaway reserves W on an allocation-controlled model; Bea
    holds a WAITING VIP entry; the clock is past the default grace window."""
    set_clock("2026-07-02T00:00:00Z")
    alice = new_customer()
    bea = new_customer()
    model = new_model(allocation_controlled=True)
    watch = new_authenticated_watch(model["id"], list_price_cents=500000)
    plan = validate_success(
        api_client.create_layaway_plan(
            create_layaway_plan_payload(alice["id"], watch["id"], 100000, 5,
                                        "2026-07-05T00:00:00Z"),
            ASSOC),
        expected_status=201,
    )
    entry = waiting_entry(model["id"], customer_id=bea["id"], priority_tier="VIP",
                          deposit_cents=50000)
    set_clock("2026-07-16T00:00:00Z")  # past 2026-07-05 + 10 grace days
    return {"model": model, "watch": watch, "plan": plan, "entry": entry}


def test_default_defaults_plan_and_reoffers_freed_watch(api):
    """PRD §3.4: "On default the paid_cents is forfeited to the boutique with no
    refund, and the watch is freed RESERVED → IN_STOCK; that freeing in turn
    auto-offers the watch to the top eligible waiting client when the model is
    allocation-controlled and an eligible entry exists."

    Design: Difficulty/transitive_cascade/layaway_default_frees_watch_then_autooffer
    """
    ctx = _default_cascade_setup()
    plan = validate_success(api.default_layaway(ctx["plan"]["id"], ASSOC))
    assert plan["status"] == "DEFAULTED"
    # Freed to IN_STOCK, then auto-offered on the allocation-controlled model.
    assert get_watch(ctx["watch"]["id"])["status"] == "OFFERED"


def test_default_auto_offer_lands_on_top_waitlist_entry(api):
    """PRD §2.8: "When a layaway plan is defaulted, the plan leaves ACTIVE, which
    frees its reserved watch back to inventory, which — when the watch's model is
    allocation-controlled and a waiting client qualifies — in turn extends a fresh
    offer to the top-ranked eligible waitlist entry."

    Design: Difficulty/transitive_cascade/layaway_default_frees_watch_then_autooffer
    """
    ctx = _default_cascade_setup()
    validate_success(api.default_layaway(ctx["plan"]["id"], ASSOC))
    entry = get_waitlist(ctx["entry"]["id"])
    assert entry["status"] == "OFFERED"
    assert entry["allocated_watch_id"] == ctx["watch"]["id"]


def test_flag_voids_active_layaway_plan(api):
    """PRD §3.1: "Any ACTIVE LayawayPlan whose watch_id is this watch is voided —
    its status moves ACTIVE → VOIDED — and the entire paid_cents amount is refunded
    to the customer's store_credit_cents."

    Design: Difficulty/transitive_cascade/flag_inauthentic_voids_active_layaway
    """
    ctx = active_layaway(80000, 4, "2026-08-01T00:00:00Z", list_price_cents=400000)
    flagged = validate_success(api.flag_watch(ctx["watch"]["id"], ASSOC,
                                              {"reason": "serial does not match maker records"}))
    assert flagged["authentication_status"] == "FLAGGED"
    assert get_layaway(ctx["plan"]["id"])["status"] == "VOIDED"


def test_flag_void_refunds_full_paid_to_store_credit(api):
    """PRD §3.1: "Any ACTIVE LayawayPlan whose watch_id is this watch is voided —
    its status moves ACTIVE → VOIDED — and the entire paid_cents amount is refunded
    to the customer's store_credit_cents. This void is caused by the watch flagging,
    not by the customer."

    Design: Difficulty/transitive_cascade/flag_inauthentic_voids_active_layaway
    """
    ctx = active_layaway(80000, 4, "2026-08-01T00:00:00Z", list_price_cents=400000)
    assert get_customer(ctx["customer"]["id"])["store_credit_cents"] == 0
    validate_success(api.flag_watch(ctx["watch"]["id"], ASSOC))
    # Deposit of 80000 was the only payment; the full amount is refunded on void.
    assert get_customer(ctx["customer"]["id"])["store_credit_cents"] == 80000
