"""Offer counter negotiation loop, posture computation, and turn gating."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_listing_with_open_offer,
    setup_active_listing,
    submit_offer,
    make_listing_agent_headers,
    make_buyer_agent_headers,
    counter_payload,
)


def _counter(api, offer_id, price, actor_id, headers):
    resp = api.counter_offer(offer_id, counter_payload(price, actor_id), headers=headers)
    return resp


def test_offer_negotiation_cycle_seller_buyer_loop(api):
    """PRD §3.6: "From `OPEN`, the seller's listing agent may counter, moving the offer
    to `SELLER_COUNTERED`; from `SELLER_COUNTERED`, the offer's own buyer agent may
    counter back, moving it to `BUYER_COUNTERED`; and from `BUYER_COUNTERED`, the
    listing agent may counter again, returning it to `SELLER_COUNTERED` — this is the
    cycle that repeats until someone accepts, rejects, or withdraws."
    PRD §3.6: "On each counter, a new `CounterRound` is appended with `round_index`
    equal to the prior `round_count` plus one, the offer's `current_price_cents` is set
    to the new `counter_price_cents`, the `current_party` flips to the other side, and
    `round_count` is incremented by one."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_seller_buyer_loop
    """
    s = setup_active_listing_with_open_offer(initial_price_cents=49_000_000)
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = s["offer"]["id"]
    la_h, ba_h = make_listing_agent_headers(la), make_buyer_agent_headers(ba)

    validate_success(_counter(api, off, 50_000_000, la, la_h), 201)   # SELLER_COUNTERED
    validate_success(_counter(api, off, 49_500_000, ba, ba_h), 201)   # BUYER_COUNTERED
    validate_success(_counter(api, off, 49_800_000, la, la_h), 201)   # SELLER_COUNTERED

    data = validate_success(api.get_offer(off, headers=la_h), 200)
    assert data["status"] == "SELLER_COUNTERED", data
    assert data["round_count"] == 3, data
    assert data["current_price_cents"] == 49_800_000, data
    assert data["current_party"] == "BUYER", data


def test_offer_cycle_round_count_grows_while_state_oscillates(api):
    """PRD §3.6: "from `SELLER_COUNTERED`, the offer's own buyer agent may counter back,
    moving it to `BUYER_COUNTERED`; and from `BUYER_COUNTERED`, the listing agent may
    counter again, returning it to `SELLER_COUNTERED` — this is the cycle that repeats
    until someone accepts, rejects, or withdraws."
    PRD §3.6: "the `current_party` flips to the other side, and `round_count` is
    incremented by one."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_seller_buyer_loop
    """
    s = setup_active_listing_with_open_offer(initial_price_cents=49_000_000)
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = s["offer"]["id"]
    la_h, ba_h = make_listing_agent_headers(la), make_buyer_agent_headers(ba)

    # Two full SELLER<->BUYER cycles: state returns to SELLER_COUNTERED twice while
    # round_count climbs monotonically.
    validate_success(_counter(api, off, 50_000_000, la, la_h), 201)  # SELLER_COUNTERED, rc1
    after1 = validate_success(api.get_offer(off, headers=la_h), 200)
    assert after1["status"] == "SELLER_COUNTERED" and after1["round_count"] == 1, after1
    validate_success(_counter(api, off, 49_500_000, ba, ba_h), 201)  # BUYER_COUNTERED, rc2
    validate_success(_counter(api, off, 49_800_000, la, la_h), 201)  # SELLER_COUNTERED, rc3
    validate_success(_counter(api, off, 49_600_000, ba, ba_h), 201)  # BUYER_COUNTERED, rc4

    data = validate_success(api.get_offer(off, headers=la_h), 200)
    assert data["status"] == "BUYER_COUNTERED", data
    assert data["round_count"] == 4, data
    assert data["current_price_cents"] == 49_600_000, data
    assert data["current_party"] == "SELLER", data


def test_counter_replay_computes_current_price_and_party(api):
    """PRD §3.6: "When it has at least one round, the `current_price_cents` is the
    `counter_price_cents` of the latest round, and the `current_party` is the side
    opposite the latest round's `by_party` — if the latest round was issued by the
    `SELLER`, it is now the `BUYER`'s turn, and vice versa. The `round_count` is simply
    the number of rounds recorded."

    Design: Corner/calculations/counter_replay_computes_current_price_and_party
    """
    s = setup_active_listing_with_open_offer(initial_price_cents=49_000_000)
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = s["offer"]["id"]
    la_h, ba_h = make_listing_agent_headers(la), make_buyer_agent_headers(ba)

    validate_success(_counter(api, off, 50_000_000, la, la_h), 201)   # SELLER round
    validate_success(_counter(api, off, 49_500_000, ba, ba_h), 201)   # BUYER round

    data = validate_success(api.get_offer(off, headers=la_h), 200)
    assert data["current_price_cents"] == 49_500_000, data
    assert data["current_party"] == "SELLER", data
    assert data["round_count"] == 2, data
    assert data["status"] == "BUYER_COUNTERED", data


def test_offer_posture_two_live_offers_is_multiple(api):
    """PRD §3.5: "if there are no live offers the posture is `NONE`, if there is exactly
    one live offer the posture is `SINGLE`, and if there are two or more live offers the
    posture is `MULTIPLE`."

    Design: Corner/calculations/offer_posture_two_live_offers_is_multiple
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la = s["listing_agent"]["id"]
    # First live offer.
    submit_offer(s["listing"]["id"], s["buyer"]["id"], s["buyer_agent"]["id"],
                 initial_price_cents=49_000_000)
    # Second buyer agent + buyer + offer.
    from test_helpers import create_agent, create_buyer
    ba2 = create_agent(s["brokerage"]["id"], full_name="Cara")
    buyer2 = create_buyer(ba2["id"], max_budget_cents=60_000_000)
    submit_offer(s["listing"]["id"], buyer2["id"], ba2["id"],
                 initial_price_cents=50_000_000)

    data = validate_success(
        api.get_listing(s["listing"]["id"], headers=make_listing_agent_headers(la)), 200)
    assert data["offer_posture"] == "MULTIPLE", data


def test_offer_posture_single_with_one_live_offer(api):
    """PRD §3.5: "if there is exactly one live offer the posture is `SINGLE`"

    Design: Corner/calculations/offer_posture_two_live_offers_is_multiple
    """
    s = setup_active_listing_with_open_offer(initial_price_cents=49_000_000)
    la = s["listing_agent"]["id"]
    data = validate_success(
        api.get_listing(s["listing"]["id"], headers=make_listing_agent_headers(la)), 200)
    assert data["offer_posture"] == "SINGLE", data


def test_buyer_counter_on_fresh_offer_not_your_turn(api):
    """PRD §3.5: "A new offer begins in `OPEN` status with `current_party` of `SELLER`
    (a fresh buyer offer awaits the seller's response first)"
    PRD §2.10: "counter and side-specific acceptance operations are permitted only when
    the acting side matches `current_party`; a request from the wrong side is rejected
    with `ERR_NOT_YOUR_TURN` (HTTP 409)."

    Design: Corner/errors/not_your_turn_on_counter_409
    """
    s = setup_active_listing_with_open_offer(initial_price_cents=49_000_000)
    ba = s["buyer_agent"]["id"]
    resp = _counter(api, s["offer"]["id"], 48_000_000, ba,
                    make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_NOT_YOUR_TURN.value)
