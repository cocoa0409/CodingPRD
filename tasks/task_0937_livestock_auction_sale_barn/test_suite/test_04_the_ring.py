"""Entering the ring, bidding, increments, credit standing and the hammer."""

from test_helpers import (
    ApiErrorId,
    AUCTIONEER,
    BARN_ADMIN,
    RING_CLERK,
    YARD_OPERATOR,
    add_buyer,
    advance_sale_day,
    api_client,
    assert_money,
    assign_pen,
    create_bid_payload,
    create_buyer_registration_payload,
    create_buyer_party,
    create_lot,
    create_sale_day,
    enter_ring,
    hammer_lot,
    invoice_for_registration,
    lot_version,
    mark_lot_ready,
    open_the_ring,
    place_bid,
    purchase_for_lot,
    read_bid,
    read_buyer_registration,
    read_lot,
    read_sale_day,
    register_buyer,
    set_clock,
    setup_checked_in_consignment,
    setup_ready_lot,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_lot,
)


def _lot_passed_out_twice():
    """A ready lot rung and passed out three times, re-rung twice on the way."""
    scn = setup_ready_lot(head_received=10, head_count=10)
    open_the_ring(scn, enter=False)
    for _ in range(2):
        enter_ring(scn.lot["id"])
        validate_success(api_client.no_sale_lot(scn.lot["id"], AUCTIONEER))
        validate_success(api_client.re_ring_lot(scn.lot["id"], AUCTIONEER))
    enter_ring(scn.lot["id"])
    validate_success(api_client.no_sale_lot(scn.lot["id"], AUCTIONEER))
    return scn


def test_third_re_ring_attempt_is_refused_by_the_cap(api):
    """PRD §3.8: "A passed lot may be put back into the sale order, `NO_SALE →
    READY`, which increments `rering_count` by one and re-issues `ring_order` from the
    sale day's `next_ring_order`, advancing that counter by 10 again."
    PRD §3.8: "The cap is two: the third re-ring attempt is refused with
    `ERR_RERING_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/lot_parallel_axes_with_capped_rering_loop
    """
    scn = _lot_passed_out_twice()

    response = api.re_ring_lot(scn.lot["id"], AUCTIONEER)
    validate_error(response, ApiErrorId.ERR_RERING_LIMIT_EXCEEDED.value)

    lot = read_lot(scn.lot["id"])
    assert lot["rering_count"] == 2
    assert lot["sale_status"] == "NO_SALE"


def test_the_custody_axis_stands_still_through_the_whole_re_ring_loop(api):
    """PRD §3.3: "A new lot is `DRAFT` on the sale axis and `BARN` on the custody
    axis."
    PRD §3.8: "On the parallel custody axis the lot moves `BARN → BUYER_PEN` — the
    animals are now in the buyer's account while still standing in their physical pen."
    PRD §3.8: "A passed lot may be put back into the sale order, `NO_SALE → READY`,
    which increments `rering_count` by one and re-issues `ring_order` from the sale
    day's `next_ring_order`, advancing that counter by 10 again."

    Design: Difficulty/non_linear_state_machine/lot_parallel_axes_with_capped_rering_loop
    """
    scn = _lot_passed_out_twice()

    lot = read_lot(scn.lot["id"])
    assert lot["custody_status"] == "BARN", (
        "no hammer ever fell, so the custody axis never moved"
    )
    assert lot["ring_order"] == 30
    assert read_sale_day(scn.sale_day["id"])["next_ring_order"] == 40


def _two_ready_lots_with_one_hammered():
    """A 20-head consignment sorted into two ready 10-head lots; lot 1 is sold."""
    scn = setup_checked_in_consignment(head_received=20)
    scn.lot_one = create_lot(scn.consignment["id"], head_count=10)
    assign_pen(scn.lot_one["id"], scn.pen["id"])
    weigh_lot(scn.lot_one["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    mark_lot_ready(scn.lot_one["id"])

    scn.lot_two = create_lot(scn.consignment["id"], head_count=10)
    assign_pen(scn.lot_two["id"], scn.pen["id"])
    weigh_lot(scn.lot_two["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    mark_lot_ready(scn.lot_two["id"])

    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    advance_sale_day(scn.sale_day["id"], "RINGING")

    enter_ring(scn.lot_one["id"])
    scn.lot = scn.lot_one
    hammer_lot(scn, unit_price=182.50)
    enter_ring(scn.lot_two["id"])
    return scn


def test_credit_hold_freezes_bidding_without_cancelling_prior_purchases(api):
    """PRD §3.7: "Supplying `hold` as true moves an `APPROVED` registration to
    `CREDIT_HOLD`, freezing bidding; supplying it as false moves `CREDIT_HOLD →
    APPROVED` and bidding resumes."
    PRD §3.7: "Freezing does **not** cancel prior purchases — they stay in the buyer's
    exposure, which is exactly the point of the state."
    PRD §3.8: "It must not be on `CREDIT_HOLD`, or the answer is
    `ERR_BUYER_CREDIT_HOLD`."

    Design: Difficulty/non_linear_state_machine/buyer_registration_credit_hold_bidirectional_toggle
    """
    scn = _two_ready_lots_with_one_hammered()
    held = validate_success(
        api.set_credit_hold(scn.registration["id"], {"hold": True}, BARN_ADMIN)
    )
    assert held["status"] == "CREDIT_HOLD"

    response = api.create_bid(
        create_bid_payload(scn.lot_two["id"], scn.registration["id"], 182.50), RING_CLERK
    )
    validate_error(response, ApiErrorId.ERR_BUYER_CREDIT_HOLD.value)

    registration = read_buyer_registration(scn.registration["id"])
    assert_money(
        registration["open_purchase_amount"],
        12391.75,
        "a credit hold does not cancel the purchase already made:",
    )


def test_lifting_the_credit_hold_lets_the_identical_bid_through(api):
    """PRD §3.7: "supplying it as false moves `CREDIT_HOLD → APPROVED` and bidding
    resumes."
    PRD §3.7: "`exposure` is the sum of those two figures less `payments_applied`,
    rounded half up to two decimal places, and `available_credit` is `effective_limit`
    less `exposure`, likewise rounded."
    PRD §3.8: "An accepted bid is created at `WINNING` immediately, takes the next
    `bid_seq` on the lot, and has its `projected_extension` computed."

    Design: Difficulty/non_linear_state_machine/buyer_registration_credit_hold_bidirectional_toggle
    """
    scn = _two_ready_lots_with_one_hammered()
    api.set_credit_hold(scn.registration["id"], {"hold": True}, BARN_ADMIN)

    resumed = validate_success(
        api.set_credit_hold(scn.registration["id"], {"hold": False}, BARN_ADMIN)
    )
    assert resumed["status"] == "APPROVED"

    bid = validate_success(
        api.create_bid(
            create_bid_payload(scn.lot_two["id"], scn.registration["id"], 182.50), RING_CLERK
        ),
        201,
    )
    assert bid["status"] == "WINNING"
    assert_money(bid["projected_extension"], 12391.75, "projected extension of the new bid:")

    registration = read_buyer_registration(scn.registration["id"])
    assert_money(registration["exposure"], 24783.50, "open purchase plus standing bid:")
    assert_money(registration["available_credit"], 50216.50, "effective limit less exposure:")


def _lot_with_a_standing_high_bid():
    """A 10-head lot IN_RING carrying a 182.50 high bid, with a second bidder ready."""
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(scn, bond_type="BONDED", credit_limit=50000, buyer_number=101)
    scn.registration_one = scn.registration
    second_party = create_buyer_party(
        legal_name="Prairie Cattle Co",
        party_type="DEALER",
        origin_county="Buffalo",
        tax_id="47-4444444",
    )
    scn.registration_two = register_buyer(
        second_party["id"],
        scn.sale_day["id"],
        buyer_number=102,
        bond_type="BONDED",
        credit_limit=50000,
    )
    open_the_ring(scn)
    scn.bid_one = place_bid(scn.lot["id"], scn.registration_one["id"], 182.50)
    return scn


def test_bid_landing_exactly_on_the_tiered_minimum_is_accepted(api):
    """PRD §3.8: "The increment is tiered off the **current high**, not off the new
    bid: 0.25 while the current high is below 100.00, 1.00 while it is at least 100.00
    and below 500.00, and 5.00 at 500.00 and above; the minimum acceptable price is the
    current high plus that increment, rounded half up to two decimal places, and the
    comparison is inclusive, so a bid landing exactly on the minimum is accepted."
    PRD §3.8: "Whatever bid previously stood at `WINNING` on that lot transitions
    `WINNING → OUTBID`, and both buyers' `winning_bid_amount`, `exposure` and
    `available_credit` are recomputed."

    Design: Difficulty/boundary_precision_check/bid_exactly_at_tiered_increment_boundary_is_accepted
    """
    scn = _lot_with_a_standing_high_bid()

    data = validate_success(
        api.create_bid(
            create_bid_payload(scn.lot["id"], scn.registration_two["id"], 183.50), RING_CLERK
        ),
        201,
    )
    assert data["status"] == "WINNING"
    assert_money(data["projected_extension"], 12459.65, "183.50 per cwt on 6790 lb:")
    assert read_bid(scn.bid_one["id"])["status"] == "OUTBID"


def test_bid_one_cent_below_the_next_minimum_is_refused(api):
    """PRD §3.8: "when the lot does have a standing high bid, the bid must be at least
    that high plus the applicable increment or the answer is `ERR_BID_BELOW_INCREMENT`."
    PRD §3.7: "`winning_bid_amount` is the total `projected_extension` of the buyer's
    bids whose `status` is `WINNING` — outbid, hammered and voided bids are excluded,
    since a hammered bid has already become a purchase and would otherwise be counted
    twice."

    Design: Difficulty/boundary_precision_check/bid_exactly_at_tiered_increment_boundary_is_accepted
    """
    scn = _lot_with_a_standing_high_bid()
    place_bid(scn.lot["id"], scn.registration_two["id"], 183.50)

    response = api.create_bid(
        create_bid_payload(scn.lot["id"], scn.registration_one["id"], 184.49), RING_CLERK
    )
    validate_error(response, ApiErrorId.ERR_BID_BELOW_INCREMENT.value)

    _, meta = validate_paginated(api.list_bids(RING_CLERK, params={"lot_id": scn.lot["id"]}))
    assert meta["total_count"] == 2

    assert_money(
        read_buyer_registration(scn.registration_one["id"])["exposure"],
        0.00,
        "an outbid bidder carries no exposure:",
    )
    assert_money(
        read_buyer_registration(scn.registration_two["id"])["exposure"],
        12459.65,
        "the standing high bidder carries the projected extension:",
    )


def test_entering_the_ring_from_draft_is_an_invalid_transition(api):
    """PRD §3.8: "Entering the ring, `READY → IN_RING`, is an `Auctioneer` action and
    requires the sale day to be `RINGING`."
    PRD §2.7 rung 16: "The target row's current state appears in the from-set of the
    requested transition | `ERR_INVALID_STATE` | 409 | every state-transition
    endpoint"

    Design: Corner/state_machines/corner_enter_ring_from_draft_lot_returns_invalid_state
    """
    scn = setup_ready_lot(head_received=10, head_count=10, weigh=False, pen=False, ready=False)
    advance_sale_day(scn.sale_day["id"], "RINGING")

    response = api.enter_ring(scn.lot["id"], AUCTIONEER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "DRAFT"
    assert lot["ring_order"] is None


def test_bid_from_a_still_pending_registration_is_refused(api):
    """PRD §3.8: "The registration must be `APPROVED`, or the answer is
    `ERR_BUYER_NOT_APPROVED`; a registration that is still `PENDING`, or has been
    `REVOKED`, cannot bid."
    PRD §3.7: "A new registration is `PENDING` with `override_limit` and
    `payments_applied` at zero."

    Design: Corner/validations/corner_bid_from_pending_registration_is_rejected
    """
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(scn, approve=False, bond_type="BONDED", credit_limit=50000)
    open_the_ring(scn)

    response = api.create_bid(
        create_bid_payload(scn.lot["id"], scn.registration["id"], 182.50), RING_CLERK
    )
    validate_error(response, ApiErrorId.ERR_BUYER_NOT_APPROVED.value)

    assert read_buyer_registration(scn.registration["id"])["status"] == "PENDING"
    _, meta = validate_paginated(api.list_bids(RING_CLERK, params={"lot_id": scn.lot["id"]}))
    assert meta["total_count"] == 0


def test_first_bid_must_reach_the_opening_bid_and_may_equal_it(api):
    """PRD §3.8: "when the lot has no bid standing at `WINNING` yet, the bid must be at
    least the lot's `opening_bid` or the answer is `ERR_BID_BELOW_OPENING`"
    PRD §2.5: "A bid is accepted when it is greater than or equal to the minimum
    acceptable price."
    PRD §3.8: "On a `PER_CWT` lot the extension is the unit price multiplied by
    `settle_weight_lb` divided by 100, rounded half up to two decimal places — the
    weigh-in result drives the money directly, and the lot must have a settle weight for
    the figure to exist at all."

    Design: Corner/validations/corner_first_bid_below_opening_bid_is_rejected
    """
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    open_the_ring(scn)

    response = api.create_bid(
        create_bid_payload(scn.lot["id"], scn.registration["id"], 149.99), RING_CLERK
    )
    validate_error(response, ApiErrorId.ERR_BID_BELOW_OPENING.value)

    data = validate_success(
        api.create_bid(
            create_bid_payload(scn.lot["id"], scn.registration["id"], 150.00), RING_CLERK
        ),
        201,
    )
    assert data["status"] == "WINNING"
    assert data["bid_seq"] == 1
    assert_money(data["projected_extension"], 10185.00, "150.00 per cwt on 6790 lb:")


def test_hammer_below_reserve_without_a_buy_back_is_refused(api):
    """PRD §3.8: "Its `unit_price` must be at least the lot's `reserve_price`, unless
    the request elects buy-back **and** the winning registration's party is the same
    party as the consignment's consignor; falling short of reserve without a qualifying
    buy-back is refused with `ERR_RESERVE_NOT_MET`."

    Design: Corner/validations/corner_hammer_below_reserve_without_buyback_is_rejected
    """
    scn = setup_ready_lot(
        head_received=10, head_count=10, lot_overrides={"reserve_price": 200.00}
    )
    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    open_the_ring(scn)
    bid = place_bid(scn.lot["id"], scn.registration["id"], 182.50)

    response = api.hammer_down(
        scn.lot["id"],
        {"winning_bid_id": bid["id"], "expected_lot_version": lot_version(scn.lot["id"])},
        AUCTIONEER,
    )
    validate_error(response, ApiErrorId.ERR_RESERVE_NOT_MET.value)

    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "IN_RING"
    assert lot["custody_status"] == "BARN"
    assert lot["hammer_price"] is None
    assert read_bid(bid["id"])["status"] == "WINNING"

    _, meta = validate_paginated(
        api.list_purchases(BARN_ADMIN, params={"lot_id": scn.lot["id"]})
    )
    assert meta["total_count"] == 0


def test_bid_whose_registration_belongs_to_another_sale_day_is_refused(api):
    """PRD §3.8: "A bid whose registration and whose lot belong to different sale days
    never gets that far — it is refused with `ERR_SALE_DAY_MISMATCH`."
    PRD §2.7 rung 8: "Cross-referenced rows belong to the same sale day: a bid's
    registration and its lot share a sale day"

    Design: Corner/validations/corner_bid_across_sale_days_is_rejected
    """
    scn = setup_ready_lot(head_received=10, head_count=10)
    other_day = create_sale_day(sale_date="2026-06-02")
    buyer_party = create_buyer_party()
    registration = register_buyer(
        buyer_party["id"], other_day["id"], buyer_number=101, bond_type="BONDED", credit_limit=50000
    )
    open_the_ring(scn)

    response = api.create_bid(
        create_bid_payload(scn.lot["id"], registration["id"], 182.50), RING_CLERK
    )
    validate_error(response, ApiErrorId.ERR_SALE_DAY_MISMATCH.value)

    _, meta = validate_paginated(api.list_bids(RING_CLERK, params={"lot_id": scn.lot["id"]}))
    assert meta["total_count"] == 0
    assert_money(
        read_buyer_registration(registration["id"])["exposure"],
        0.00,
        "a refused bid leaves no exposure:",
    )


def test_reusing_a_buyer_number_on_the_same_sale_day_is_refused(api):
    """PRD §3.7: "Bidder numbers are unique within a sale day; reusing one is refused
    with `ERR_DUPLICATE_BUYER_NUMBER`."

    Design: Corner/validations/corner_duplicate_buyer_number_on_same_sale_day_is_rejected
    """
    set_clock("2026-06-01T08:00:00Z")
    first_party = create_buyer_party()
    second_party = create_buyer_party(
        legal_name="Prairie Cattle Co",
        party_type="DEALER",
        origin_county="Buffalo",
        tax_id="47-4444444",
    )
    sale_day = create_sale_day()
    register_buyer(
        first_party["id"], sale_day["id"], approve=False, buyer_number=101, bond_type="BONDED"
    )

    response = api.create_buyer_registration(
        create_buyer_registration_payload(
            second_party["id"],
            sale_day["id"],
            buyer_number=101,
            bond_type="UNSECURED",
            credit_limit=5000,
        ),
        BARN_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BUYER_NUMBER.value)

    _, meta = validate_paginated(
        api.list_buyer_registrations(BARN_ADMIN, params={"sale_day_id": sale_day["id"]})
    )
    assert meta["total_count"] == 1


def test_hammer_carrying_a_stale_lot_version_is_refused_then_succeeds_when_refreshed(api):
    """PRD §2.8: "In each case the request carries a non-optional expected-version
    field, and if the value does not match the parent row's current `version`, the write
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "Dropping the hammer on a lot — `POST /sale-barn/lots/{id}/hammer-down` —
    requires `expected_lot_version`, carrying the client's last observed `version` of
    the `Lot`."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
    mutation, and `version`, an integer that starts at 1 and increments by one on every
    mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_hammer_down_with_stale_lot_version_returns_412
    """
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    open_the_ring(scn)
    bid = place_bid(scn.lot["id"], scn.registration["id"], 182.50)

    stale_version = lot_version(scn.lot["id"])
    validate_success(api.quarantine_lot(scn.lot["id"], {"hold": True}, YARD_OPERATOR))
    validate_success(api.quarantine_lot(scn.lot["id"], {"hold": False}, YARD_OPERATOR))

    response = api.hammer_down(
        scn.lot["id"],
        {"winning_bid_id": bid["id"], "expected_lot_version": stale_version},
        AUCTIONEER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert read_lot(scn.lot["id"])["sale_status"] == "IN_RING"

    fresh_version = lot_version(scn.lot["id"])
    assert fresh_version == stale_version + 2, (
        "two quarantine writes advanced the lot by two versions"
    )

    purchase = validate_success(
        api.hammer_down(
            scn.lot["id"],
            {"winning_bid_id": bid["id"], "expected_lot_version": fresh_version},
            AUCTIONEER,
        ),
        201,
    )
    assert purchase["status"] == "CONFIRMED"
    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "SOLD"
    assert lot["custody_status"] == "BUYER_PEN"


def test_credit_override_carrying_a_stale_registration_version_is_refused(api):
    """PRD §2.8: "Issuing a credit override — `POST
    /sale-barn/buyer-registrations/{id}/credit-override` — requires
    `expected_buyer_registration_version`, carrying the client's last observed `version`
    of the `BuyerRegistration`."
    PRD §2.8: "A new override **replaces** the prior `override_limit` rather than
    adding to it, so a writer working from a stale view would silently erase headroom
    another supervisor had just granted."
    PRD §3.7: "That figure is the `credit_limit` multiplied by a bond multiplier, plus
    the `cash_deposit_amount`, plus the `override_limit`, rounded half up to two decimal
    places."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_credit_override_with_stale_registration_version_returns_412
    """
    set_clock("2026-06-01T08:00:00Z")
    buyer_party = create_buyer_party()
    sale_day = create_sale_day()
    registration = register_buyer(
        buyer_party["id"],
        sale_day["id"],
        buyer_number=101,
        bond_type="UNSECURED",
        credit_limit=10000,
    )
    stale_version = read_buyer_registration(registration["id"])["version"]
    validate_success(
        api.credit_override(
            registration["id"],
            {"override_limit": 5000.00, "expected_buyer_registration_version": stale_version},
            BARN_ADMIN,
        )
    )

    response = api.credit_override(
        registration["id"],
        {"override_limit": 250.00, "expected_buyer_registration_version": stale_version},
        BARN_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    fresh = read_buyer_registration(registration["id"])
    assert_money(fresh["override_limit"], 5000.00, "the first supervisor's headroom survives:")
    assert_money(fresh["effective_limit"], 15000.00, "10000 x 1.0 plus 5000 override:")
    assert_money(fresh["available_credit"], 15000.00, "no exposure has been taken on:")


def test_hammer_response_and_immediate_reads_carry_every_side_effect(api):
    """PRD §3.8: "A purchase row is created at `CONFIRMED`, copying `lot_id`,
    `buyer_registration_id`, `winning_bid_id`, `bid_basis`, `unit_price`, `head_count`,
    `total_weight_lb` from the lot's settle weight, and `extended_amount`, with
    `doa_head` and `doa_credit_amount` at zero."
    PRD §3.8: "On success a great deal happens at once: `hammer_price` is set from the
    bid's unit price, `extended_amount` is computed, `buy_back` is recorded as true
    exactly when the buying registration's party equals the consignment's
    `consignor_party_id`, and `destination_state_code` is set from the buying party's
    `origin_state_code`."
    PRD §3.8: "If the buyer has no invoice yet for this sale day, one is created at
    `DRAFT` and the purchase's `buyer_invoice_id` points at it; the invoice's `subtotal`
    is recomputed."
    PRD §3.8: "The named bid moves `WINNING → HAMMERED`."

    Design: Corner/consistency_model/corner_hammer_down_response_reflects_every_immediate_side_effect
    """
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    open_the_ring(scn)
    bid = place_bid(scn.lot["id"], scn.registration["id"], 182.50)

    body = validate_success(
        api.hammer_down(
            scn.lot["id"],
            {"winning_bid_id": bid["id"], "expected_lot_version": lot_version(scn.lot["id"])},
            AUCTIONEER,
        ),
        201,
    )
    assert body["status"] == "CONFIRMED"
    assert body["head_count"] == 10
    assert body["total_weight_lb"] == 6790
    assert_money(body["extended_amount"], 12391.75, "purchase extension in the response body:")

    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "SOLD"
    assert lot["custody_status"] == "BUYER_PEN"
    assert_money(lot["hammer_price"], 182.50, "hammer price on the lot:")
    assert read_bid(bid["id"])["status"] == "HAMMERED"

    invoice = invoice_for_registration(scn.registration["id"])
    assert invoice["status"] == "DRAFT"
    assert_money(invoice["subtotal"], 12391.75, "invoice subtotal after the hammer:")

    registration = read_buyer_registration(scn.registration["id"])
    assert_money(registration["open_purchase_amount"], 12391.75, "open purchase amount:")
    assert_money(registration["winning_bid_amount"], 0.00, "a hammered bid leaves the pool:")
    assert_money(registration["exposure"], 12391.75, "exposure after the hammer:")
    assert_money(registration["available_credit"], 62608.25, "75000 effective less exposure:")

    assert purchase_for_lot(scn.lot["id"])["id"] == body["id"]
