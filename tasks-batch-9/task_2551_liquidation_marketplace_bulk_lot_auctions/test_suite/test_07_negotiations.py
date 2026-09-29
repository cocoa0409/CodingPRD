"""Negotiated terms: the alternating ladder, the round cap, OCC and acceptance."""

from test_helpers import (
    ADMIN,
    add_buyer,
    api_client,
    assert_instant,
    assert_negotiation,
    assert_offer,
    assert_sale_order,
    bootstrap_marketplace,
    counter_offer,
    counter_offer_payload,
    get_success_data,
    make_buyer_headers,
    negotiation_payload,
    open_negotiation,
    order_for_listing,
    read_listing,
    read_lot,
    read_negotiation,
    read_order,
    set_clock,
    setup_open_negotiated,
    total_count,
    validate_error,
    validate_success,
)

TWO_HUNDRED_UNIT_LINES = [
    {
        "sku": "APP-NEG-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

OFFER_TTL_INSTANT = "2026-08-07T01:00:00Z"


def _offers_by_round(negotiation_id, headers):
    """The negotiation's append-only offer ledger, keyed by round_number."""
    rows = validate_success(
        api_client.list_negotiation_offers(negotiation_id, headers, {"limit": 10, "offset": 0})
    )
    return {row["round_number"]: row for row in rows}


def test_the_ladder_re_enters_both_waiting_states_as_the_round_number_climbs():
    """Four alternating turns occupy AWAITING_SELLER and AWAITING_BUYER twice each,
    and every accepted counter bumps the negotiation's version exactly once.

    PRD 3.5: "The ladder then alternates. A counter-offer states an `amount_cents`
    and the `expected_negotiation_version` of §2.7, and the acting side is inferred
    from `X-User-Role`: `SellerOps` counters from `AWAITING_SELLER` and `Buyer`
    counters from `AWAITING_BUYER`."
    PRD 3.5: "An accepted counter appends the next `Offer` with `offer_side` matching
    the acting side and `round_number` one higher than the previous round, then
    updates the negotiation: `round_number` to the new round, `current_offer_cents`
    to the countered amount, `current_offer_side` to the countering side, and
    `current_offer_expires_at` to the current logical clock plus 48 hours — each
    counter restarts the 48-hour clock rather than inheriting the previous deadline."
    PRD 3.5: "The state flips `AWAITING_SELLER → AWAITING_BUYER` when the seller
    countered and `AWAITING_BUYER → AWAITING_SELLER` when the buyer countered, and
    the negotiation's `version` advances by one."

    Design: Difficulty/non_linear_state_machine/negotiation_cycles_four_alternating_turns_then_hits_round_cap
    """
    built = setup_open_negotiated()
    env = built["env"]

    round_one = open_negotiation(env, built["listing"], 900_000)
    assert_negotiation(round_one)
    assert round_one["negotiation_status"] == "AWAITING_SELLER"
    assert round_one["round_number"] == 1
    assert round_one["current_offer_side"] == "BUYER"

    round_two = counter_offer(env, round_one, 1_500_000, as_seller=True)
    assert round_two["negotiation_status"] == "AWAITING_BUYER"
    assert round_two["round_number"] == 2
    assert round_two["current_offer_side"] == "SELLER"

    round_three = counter_offer(env, round_two, 1_200_000)
    assert round_three["negotiation_status"] == "AWAITING_SELLER"
    assert round_three["round_number"] == 3
    assert round_three["current_offer_side"] == "BUYER"

    round_four = counter_offer(env, round_three, 1_350_000, as_seller=True)
    assert round_four["negotiation_status"] == "AWAITING_BUYER"
    assert round_four["round_number"] == 4
    assert round_four["current_offer_side"] == "SELLER"

    assert round_two["version"] == round_one["version"] + 1
    assert round_three["version"] == round_two["version"] + 1
    assert round_four["version"] == round_three["version"] + 1
    assert_instant(round_four["current_offer_expires_at"], OFFER_TTL_INSTANT)

    ledger = _offers_by_round(round_one["id"], env["buyer_headers"])
    assert sorted(ledger) == [1, 2, 3, 4]
    assert [ledger[n]["offer_side"] for n in (1, 2, 3, 4)] == [
        "BUYER",
        "SELLER",
        "BUYER",
        "SELLER",
    ]
    assert [ledger[n]["amount_cents"] for n in (1, 2, 3, 4)] == [
        900_000,
        1_500_000,
        1_200_000,
        1_350_000,
    ]


def test_the_fifth_counter_offer_is_refused_and_leaves_round_four_standing():
    """The cap terminates the cycle rather than the cycle terminating itself: the
    fifth counter changes nothing at all, and no sale results.

    PRD 3.5: "And the round cap must hold: the round the counter would create is the
    current `round_number` plus one, and that value must be no greater than four, or
    the counter is refused with `ERR_NEGOTIATION_ROUND_LIMIT` without creating any
    `Offer` and without changing `round_number`."
    PRD 3.5: "Since the buyer's opening offer is itself round 1, at most three
    counter-offers can ever occur on a negotiation."
    PRD 2.4: "Concretely: every accepted live bid, proxy bid, publication and closure
    on a listing increments that `Listing`'s `version` by exactly 1, and every
    accepted counter-offer and acceptance on a negotiation increments that
    `Negotiation`'s `version` by exactly 1."

    Design: Difficulty/non_linear_state_machine/negotiation_cycles_four_alternating_turns_then_hits_round_cap
    """
    built = setup_open_negotiated()
    env = built["env"]
    listing = built["listing"]

    negotiation = open_negotiation(env, listing, 900_000)
    negotiation = counter_offer(env, negotiation, 1_500_000, as_seller=True)
    negotiation = counter_offer(env, negotiation, 1_200_000)
    negotiation = counter_offer(env, negotiation, 1_350_000, as_seller=True)
    assert negotiation["round_number"] == 4

    refused = api_client.create_counter_offer(
        negotiation["id"],
        counter_offer_payload(1_300_000, negotiation["version"]),
        env["buyer_headers"],
    )
    validate_error(refused, "ERR_NEGOTIATION_ROUND_LIMIT", 422)

    unchanged = read_negotiation(env, negotiation["id"])
    assert unchanged["negotiation_status"] == "AWAITING_BUYER"
    assert unchanged["round_number"] == 4
    assert unchanged["current_offer_cents"] == 1_350_000
    assert unchanged["current_offer_side"] == "SELLER"
    assert unchanged["version"] == negotiation["version"]
    assert_instant(unchanged["current_offer_expires_at"], OFFER_TTL_INSTANT)

    assert len(_offers_by_round(negotiation["id"], env["buyer_headers"])) == 4
    assert read_listing(env, listing["id"])["listing_status"] == "OPEN"
    assert total_count(
        api_client.list_sale_orders(ADMIN, {"listing_id": listing["id"]})
    ) == 0


def test_accepting_one_negotiation_declines_its_live_sibling_on_the_same_listing():
    """The acceptance cascade sells the lot to the accepted buyer and closes the other
    live negotiation without touching its standing amount.

    PRD 3.5: "An accepted negotiation advances `AWAITING_SELLER → ACCEPTED` or
    `AWAITING_BUYER → ACCEPTED`, freezes `accepted_price_cents` at whatever
    `current_offer_cents` held at that instant, and advances the negotiation's
    `version` by one."
    PRD 3.5: "The cascade is broad: the listing advances `OPEN → CLOSED_SOLD`, the lot
    advances `LISTED → SOLD`, one sale order is created with `sale_source`
    `NEGOTIATED_ACCEPTANCE` and `hammer_price_cents` equal to `accepted_price_cents`,
    the seller recovery aggregates and commission tier are recomputed, and **every
    other negotiation on the same listing whose `negotiation_status` was
    `AWAITING_SELLER` or `AWAITING_BUYER` is advanced to `DECLINED`**, each such
    sibling having its own `version` advanced by one."
    PRD 3.6: "A hammer price above 1,000,000 cents and at most 2,500,000 cents selects
    1,200 basis points, 12 percent."

    Design: Corner/state_machines/negotiated_acceptance_declines_the_sibling_negotiation
    """
    env = bootstrap_marketplace()
    second_buyer = add_buyer(env)
    built = setup_open_negotiated(env, min_offer_cents=900_000, lines=TWO_HUNDRED_UNIT_LINES)
    listing = built["listing"]

    accepted_side = open_negotiation(env, listing, 1_200_000)
    sibling = open_negotiation(
        env,
        listing,
        1_000_000,
        buyer=second_buyer,
        buyer_headers=make_buyer_headers(second_buyer["id"]),
    )

    get_success_data(
        api_client.accept_negotiation(accepted_side["id"], {}, env["seller_headers"])
    )

    winner = read_negotiation(env, accepted_side["id"])
    assert winner["negotiation_status"] == "ACCEPTED"
    assert winner["accepted_price_cents"] == 1_200_000
    assert winner["round_number"] == 1

    loser = read_negotiation(env, sibling["id"])
    assert loser["negotiation_status"] == "DECLINED"
    assert loser["current_offer_cents"] == 1_000_000
    assert loser["accepted_price_cents"] is None

    assert read_listing(env, listing["id"])["listing_status"] == "CLOSED_SOLD"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "SOLD"

    assert total_count(
        api_client.list_sale_orders(ADMIN, {"listing_id": listing["id"]})
    ) == 1
    order = read_order(env, order_for_listing(listing["id"], ADMIN)["id"])
    assert_sale_order(order)
    assert order["sale_source"] == "NEGOTIATED_ACCEPTANCE"
    assert order["buyer_id"] == env["buyer"]["id"]
    assert order["hammer_price_cents"] == 1_200_000
    assert order["buyer_premium_bps"] == 1_200
    assert order["buyer_premium_cents"] == 144_000
    assert order["estimated_freight_cents"] == 8_500
    assert order["total_due_cents"] == 1_352_500


def test_the_four_negotiation_refusals_all_arise_from_one_live_negotiation():
    """A floor breach, a duplicate opening, a counter out of turn and a counter at the
    expiry instant each fail on their own terms and leave round 1 intact.

    PRD 3.5: "That opening amount must be at least the listing's `min_offer_cents`, or
    the request is refused with `ERR_OFFER_BELOW_MINIMUM`; the same floor applies to
    every subsequent counter-offer, and both operations report the same error."
    PRD 3.5: "A buyer may hold only one live negotiation per listing: if that buyer
    already has a negotiation on this listing whose `negotiation_status` is
    `AWAITING_SELLER` or `AWAITING_BUYER`, the attempt is refused with
    `ERR_DUPLICATE_NEGOTIATION`."
    PRD 3.5: "The negotiation must be in `AWAITING_SELLER` or `AWAITING_BUYER` — a
    negotiation already `ACCEPTED` or `DECLINED` yields
    `ERR_NEGOTIATION_STATE_INVALID` — and the acting side must be the side the
    negotiation is awaiting, or the attempt is `ERR_NOT_YOUR_TURN`."
    PRD 3.5: "The current logical clock must be strictly before
    `current_offer_expires_at`; an action attempted at exactly the expiry instant is
    too late and is refused with `ERR_OFFER_EXPIRED`."

    Design: Corner/errors/negotiation_offer_turn_and_expiry_errors_are_all_reachable
    """
    built = setup_open_negotiated(min_offer_cents=800_000, lines=TWO_HUNDRED_UNIT_LINES)
    env = built["env"]
    listing = built["listing"]
    buyer_id = env["buyer"]["id"]

    below_floor = api_client.open_negotiation(
        listing["id"], negotiation_payload(buyer_id, 799_999), env["buyer_headers"]
    )
    validate_error(below_floor, "ERR_OFFER_BELOW_MINIMUM", 422)
    assert total_count(
        api_client.list_negotiations(ADMIN, {"listing_id": listing["id"]})
    ) == 0

    opened = validate_success(
        api_client.open_negotiation(
            listing["id"], negotiation_payload(buyer_id, 800_000), env["buyer_headers"]
        ),
        201,
    )
    assert opened["negotiation_status"] == "AWAITING_SELLER"
    assert opened["round_number"] == 1
    assert opened["current_offer_side"] == "BUYER"
    assert opened["current_offer_cents"] == 800_000
    assert_instant(opened["current_offer_expires_at"], OFFER_TTL_INSTANT)

    duplicate = api_client.open_negotiation(
        listing["id"], negotiation_payload(buyer_id, 900_000), env["buyer_headers"]
    )
    validate_error(duplicate, "ERR_DUPLICATE_NEGOTIATION", 422)
    assert total_count(
        api_client.list_negotiations(ADMIN, {"listing_id": listing["id"]})
    ) == 1

    out_of_turn = api_client.create_counter_offer(
        opened["id"],
        counter_offer_payload(850_000, opened["version"]),
        env["buyer_headers"],
    )
    validate_error(out_of_turn, "ERR_NOT_YOUR_TURN", 409)

    set_clock(OFFER_TTL_INSTANT)
    too_late = api_client.create_counter_offer(
        opened["id"],
        counter_offer_payload(1_000_000, opened["version"]),
        env["seller_headers"],
    )
    validate_error(too_late, "ERR_OFFER_EXPIRED", 422)

    unchanged = read_negotiation(env, opened["id"])
    assert unchanged["round_number"] == 1
    assert unchanged["version"] == opened["version"]
    assert len(_offers_by_round(opened["id"], env["buyer_headers"])) == 1


def test_a_counter_offer_on_an_accepted_negotiation_reports_the_state_error():
    """ACCEPTED is terminal: a counter carrying the negotiation's current version is
    still refused on state grounds, not on turn or version grounds.

    PRD 3.5: "The negotiation must be in `AWAITING_SELLER` or `AWAITING_BUYER` — a
    negotiation already `ACCEPTED` or `DECLINED` yields
    `ERR_NEGOTIATION_STATE_INVALID` — and the acting side must be the side the
    negotiation is awaiting, or the attempt is `ERR_NOT_YOUR_TURN`."
    PRD 2.5: "…the platform evaluates checks in sixteen numbered bands and returns the
    error belonging to the **lowest-numbered band** that fails, stopping there. Within
    the sequence, safety and identity questions come before time, time comes before
    physical capacity, and money comes last…"
    PRD 3.6: "A `hammer_price_cents` of at most 1,000,000 cents selects a
    `buyer_premium_bps` of 1,400 basis points, that is 14 percent."

    Design: Corner/errors/counter_offer_on_an_accepted_negotiation_is_refused
    """
    built = setup_open_negotiated(min_offer_cents=800_000, lines=TWO_HUNDRED_UNIT_LINES)
    env = built["env"]
    listing = built["listing"]

    opened = open_negotiation(env, listing, 900_000)
    set_clock("2026-08-05T02:00:00Z")
    get_success_data(
        api_client.accept_negotiation(opened["id"], {}, env["seller_headers"])
    )
    accepted = read_negotiation(env, opened["id"])
    assert accepted["negotiation_status"] == "ACCEPTED"

    refused = api_client.create_counter_offer(
        opened["id"],
        counter_offer_payload(950_000, accepted["version"]),
        env["buyer_headers"],
    )
    error = validate_error(refused, "ERR_NEGOTIATION_STATE_INVALID", 409)
    assert error["error_id"] != "ERR_NOT_YOUR_TURN"
    assert error["error_id"] != "ERR_STALE_NEGOTIATION_VERSION"

    unchanged = read_negotiation(env, opened["id"])
    assert unchanged["negotiation_status"] == "ACCEPTED"
    assert unchanged["accepted_price_cents"] == 900_000
    assert unchanged["round_number"] == 1
    assert unchanged["version"] == accepted["version"]

    assert read_listing(env, listing["id"])["listing_status"] == "CLOSED_SOLD"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "SOLD"

    order = read_order(env, order_for_listing(listing["id"], ADMIN)["id"])
    assert order["sale_source"] == "NEGOTIATED_ACCEPTANCE"
    assert order["hammer_price_cents"] == 900_000
    assert order["buyer_premium_bps"] == 1_400
    assert order["buyer_premium_cents"] == 126_000
    assert order["estimated_freight_cents"] == 8_500
    assert order["total_due_cents"] == 1_034_500


def test_a_superseded_negotiation_version_is_refused_even_though_the_turn_is_right():
    """The buyer legitimately holds the turn, yet the version it read before the
    seller's counter is stale, so the counter is refused and the replay succeeds.

    PRD 2.7: "A counter-offer — `POST /liquidation/negotiations/{id}/counter-offers` —
    requires a non-optional `expected_negotiation_version` field carrying the `version`
    the client last read from the target `Negotiation`."
    PRD 2.7: "A counter is only meaningful against the offer the caller actually saw;
    if the other side has already countered, advancing `round_number` and `version`,
    the stale counter-offer is rejected with `ERR_STALE_NEGOTIATION_VERSION` (HTTP
    412), no `Offer` row is created, `round_number` is unchanged and the negotiation's
    turn does not flip."
    PRD 3.5: "An accepted counter appends the next `Offer` with `offer_side` matching
    the acting side and `round_number` one higher than the previous round, then
    updates the negotiation: `round_number` to the new round, `current_offer_cents` to
    the countered amount, `current_offer_side` to the countering side, and
    `current_offer_expires_at` to the current logical clock plus 48 hours — each
    counter restarts the 48-hour clock rather than inheriting the previous deadline."

    Design: Corner/cross_cutting_complexity_layers/superseded_expected_negotiation_version_rejects_the_counter_offer
    """
    built = setup_open_negotiated(
        min_offer_cents=800_000,
        lines=TWO_HUNDRED_UNIT_LINES,
        clock="2026-08-06T01:00:00Z",
    )
    env = built["env"]

    opened = open_negotiation(env, built["listing"], 850_000)
    stale_version = opened["version"]

    countered = get_success_data(
        api_client.create_counter_offer(
            opened["id"],
            counter_offer_payload(1_200_000, stale_version),
            env["seller_headers"],
        )
    )
    assert countered["round_number"] == 2
    assert countered["current_offer_side"] == "SELLER"
    assert countered["current_offer_cents"] == 1_200_000
    assert countered["negotiation_status"] == "AWAITING_BUYER"

    stale = api_client.create_counter_offer(
        opened["id"],
        counter_offer_payload(900_000, stale_version),
        env["buyer_headers"],
    )
    validate_error(stale, "ERR_STALE_NEGOTIATION_VERSION", 412)

    held = read_negotiation(env, opened["id"])
    assert held["round_number"] == 2
    assert held["current_offer_cents"] == 1_200_000
    assert len(_offers_by_round(opened["id"], env["buyer_headers"])) == 2

    fresh_version = held["version"]
    assert fresh_version == stale_version + 1

    replayed = get_success_data(
        api_client.create_counter_offer(
            opened["id"],
            counter_offer_payload(900_000, fresh_version),
            env["buyer_headers"],
        )
    )
    assert replayed["round_number"] == 3
    assert replayed["current_offer_side"] == "BUYER"
    assert replayed["current_offer_cents"] == 900_000
    assert replayed["negotiation_status"] == "AWAITING_SELLER"

    ledger = _offers_by_round(opened["id"], env["buyer_headers"])
    assert [ledger[n]["amount_cents"] for n in (1, 2, 3)] == [850_000, 1_200_000, 900_000]


def test_offer_rows_are_append_only_and_carry_neither_version_nor_updated_at():
    """The round ledger grows by one immutable row per accepted offer, and the earlier
    row keeps its own deadline when the next round restarts the clock.

    PRD 2.4: "There is one deliberate exception: an `Offer` is an immutable record of a
    single negotiation round. An `Offer` carries only `id` and `created_at` — it has no
    `updated_at` and no `version`, because once written it is never touched again."
    PRD 3.5: "Offers are append-only: an `Offer` row is never mutated after creation,
    which is why it carries no `version`."
    PRD 3.5: "It simultaneously creates the round-1 `Offer`, which names its parent
    through `negotiation_id` and records `offer_side` `BUYER`, `amount_cents` equal to
    the opening amount, `round_number` 1, and an `expires_at` equal to the same
    clock-plus-48-hours instant."

    Design: Corner/entities/offer_rows_are_immutable_and_carry_no_version_field
    """
    built = setup_open_negotiated(min_offer_cents=900_000, lines=TWO_HUNDRED_UNIT_LINES)
    env = built["env"]

    opened = open_negotiation(env, built["listing"], 1_000_000)
    counter_offer(env, opened, 1_400_000, as_seller=True)

    response = api_client.list_negotiation_offers(
        opened["id"], env["buyer_headers"], {"limit": 10, "offset": 0}
    )
    validate_success(response)
    assert total_count(response) == 2

    ledger = _offers_by_round(opened["id"], env["buyer_headers"])
    first, second = ledger[1], ledger[2]
    assert first["amount_cents"] == 1_000_000
    assert first["offer_side"] == "BUYER"
    assert second["amount_cents"] == 1_400_000
    assert second["offer_side"] == "SELLER"

    for offer in (first, second):
        assert_offer(offer)
        assert offer["negotiation_id"] == opened["id"]
        assert "version" not in offer
        assert "updated_at" not in offer

    assert_instant(first["expires_at"], OFFER_TTL_INSTANT)
    reread = validate_success(api_client.get_offer(first["id"], env["buyer_headers"]))
    assert reread["amount_cents"] == 1_000_000
    assert reread["round_number"] == 1
    assert_instant(reread["expires_at"], OFFER_TTL_INSTANT)
    assert reread["created_at"] == first["created_at"]
