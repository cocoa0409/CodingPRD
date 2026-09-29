"""Manifest claims: refund pricing, the accuracy score, probation and reversal."""

from test_helpers import (
    ADMIN,
    CANONICAL_LOT_LINES,
    CLAIM_DECIDER_USER_ID,
    DEFAULT_EVIDENCE_URLS,
    SECOND_TRUST_SAFETY_USER_ID,
    TEST_USERS,
    api_client,
    assert_instant,
    book_appointment,
    bootstrap_marketplace,
    buy_at_ask,
    claim_decision_payload,
    claim_payload,
    claim_reversal_payload,
    complete_appointment,
    create_listing,
    create_lot_with_lines,
    decide_claim,
    file_claim,
    fixed_price_listing_payload,
    get_success_data,
    order_for_listing,
    pay_order,
    publish_listing,
    read_buyer,
    read_claim,
    read_lot,
    read_manifest_line,
    read_order,
    read_seller,
    review_manifest,
    set_clock,
    setup_claim_under_review,
    setup_picked_up_order,
    submit_manifest,
    total_count,
    validate_error,
    validate_success,
)

REVERSER = TEST_USERS["trust_safety_reverser_headers"]

# A third line the seller voids while the lot is still DRAFT.
VOIDED_LINE = {
    "sku": "APP-RET-0003",
    "unit_count": 50,
    "unit_retail_cents": 10_000,
    "declared_condition": "DAMAGED",
}

# A second lot for the same seller that is never listed.
FOREIGN_LOT_LINES = [
    {
        "sku": "HG-OTH-0100",
        "unit_count": 100,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

LATE_PURCHASE_CLOCK = "2026-08-10T00:00:00Z"
PICKUP_START = "2026-08-18T14:00:00Z"
PICKUP_END = "2026-08-18T15:00:00Z"


def test_approving_a_shortage_claim_credits_the_order_and_the_buyer_wallet():
    """The refund is priced from the line's share of the hammer price and lands as a
    credit, not as a reduction of the cash the buyer already sent.

    PRD 3.8: "Worked through on a lot whose `declared_retail_value_cents` is 10,000,000
    with a line of 100 units at 40,000 cents each, an order with a hammer price of
    2,700,000 cents and a premium rate of 1,000 basis points: the line share is 1,080,000
    cents, the per-unit recovery is 10,800 cents, 80 confirmed units give a base refund of
    864,000 cents, the premium portion is 86,400 cents, and `refund_cents` is 950,400
    cents."
    PRD 3.8: "An approval or partial approval increases the order's `claim_credit_cents` by
    the computed `refund_cents`, which lowers `total_due_cents` and recomputes
    `balance_due_cents` under the zero clamp of §3.6, and advances the order `PAID →
    REFUND_ISSUED`."
    PRD 3.8: "Both record `decided_by_user_id` and the confirmed `verified_units`, and both
    advance the claim's `version` by one."

    Design: Difficulty/transitive_cascade/claim_approval_cascades_through_lot_score_to_seller_probation_tier
    """
    built = setup_claim_under_review()
    env = built["env"]
    assert built["claim"]["claim_status"] == "UNDER_REVIEW"
    assert built["claim"]["evidence_item_count"] == 2

    decided = decide_claim(env, built["claim"], "APPROVE", 80)
    assert decided["claim_status"] == "APPROVED"
    assert decided["verified_units"] == 80
    assert decided["refund_cents"] == 950_400
    assert decided["decided_by_user_id"] == CLAIM_DECIDER_USER_ID
    assert decided["version"] == built["claim"]["version"] + 1

    order = read_order(env, built["order"]["id"])
    assert order["claim_credit_cents"] == 950_400
    assert order["payment_status"] == "REFUND_ISSUED"
    assert order["total_due_cents"] == 2_036_600
    assert order["amount_paid_cents"] == 2_987_000
    assert order["balance_due_cents"] == 0

    assert read_buyer(env)["wallet_credit_cents"] == 950_400
    assert read_manifest_line(env, built["claim_line"]["id"])["verified_unit_count"] == 80


def test_the_same_approval_scores_the_lot_and_forces_the_seller_onto_probation():
    """One decision walks on from the money to the lot score, to the seller average, to
    probation, to the commission tier that probation overrides.

    PRD 3.8: "On that 400-unit `CUSTOMER_RETURNS` lot, 80 verified units give an excess of
    68 and a score of 0.830; 72 verified units give an excess of 60 and a score of exactly
    0.850; and any shortfall inside the 12-unit allowance leaves the score at 1.000."
    PRD 3.9: "When `manifest_accuracy_avg` falls strictly below 0.850, the seller advances
    `ACTIVE → MANIFEST_PROBATION`; an average landing exactly on 0.850 keeps the seller
    `ACTIVE`."
    PRD 3.9: "Probation has two consequences: `commission_tier` is forced to
    `TIER_PROBATION` with `commission_rate_bps` of 2,500 basis points, overriding whatever
    the recovery-based tier would otherwise have been, and every publication attempt on any
    of that seller's lots is refused with `ERR_SELLER_NOT_ACTIVE`."
    PRD 3.9: "First, the rate in force is read from the seller's `commission_rate_bps` at
    that instant — after the same request's recovery recomputation, and then frozen into the
    order's `seller_commission_rate_bps`, so a later tier change never reprices an already
    settled order."

    Design: Difficulty/transitive_cascade/claim_approval_cascades_through_lot_score_to_seller_probation_tier
    """
    built = setup_claim_under_review()
    env = built["env"]
    before = read_seller(env)
    assert before["account_status"] == "ACTIVE"
    assert before["commission_tier"] == "TIER_PREFERRED"
    assert before["manifest_accuracy_avg"] == 1.000
    assert before["scored_lot_count"] == 0

    decide_claim(env, built["claim"], "APPROVE", 80)

    assert read_lot(env, built["lot"]["id"])["manifest_accuracy_score"] == 0.830

    after = read_seller(env)
    assert after["manifest_accuracy_avg"] == 0.830
    assert after["scored_lot_count"] == 1
    assert after["account_status"] == "MANIFEST_PROBATION"
    assert after["commission_tier"] == "TIER_PROBATION"
    assert after["commission_rate_bps"] == 2_500
    assert after["gross_recovery_rate"] == 0.2700
    assert after["net_recovery_rate"] == 0.2295

    order = read_order(env, built["order"]["id"])
    assert order["seller_commission_rate_bps"] == 1_500
    assert order["seller_net_proceeds_cents"] == 2_295_000


def test_the_refund_lowers_the_buyer_net_outlay_without_touching_the_cash_paid():
    """Net outlay is amount_paid_cents less wallet_credit_cents; the approval must move it
    by exactly the refund and by no other route.

    PRD 3.8: "It increases the buyer's `wallet_credit_cents` by the same amount, and — this
    is the crucial asymmetry — it does **not** reduce `amount_paid_cents`, because the cash
    genuinely changed hands."
    PRD 3.8: "The net cash the buyer is out of pocket, being `amount_paid_cents` less
    `wallet_credit_cents`, therefore falls by exactly the refund and by nothing else."

    Design: Difficulty/compensating_invariant/buyer_net_outlay_restored_by_claim_reversal
    """
    built = setup_claim_under_review()
    env = built["env"]
    opening = read_order(env, built["order"]["id"])
    assert opening["amount_paid_cents"] == 2_987_000
    assert opening["total_due_cents"] == 2_987_000
    assert opening["payment_status"] == "PAID"
    assert opening["claim_credit_cents"] == 0
    assert read_buyer(env)["wallet_credit_cents"] == 0
    assert opening["amount_paid_cents"] - 0 == 2_987_000

    decided = decide_claim(env, built["claim"], "APPROVE", 80)
    assert decided["refund_cents"] == 950_400

    order = read_order(env, built["order"]["id"])
    buyer = read_buyer(env)
    assert order["payment_status"] == "REFUND_ISSUED"
    assert order["claim_credit_cents"] == 950_400
    assert order["total_due_cents"] == 2_036_600
    assert order["amount_paid_cents"] == 2_987_000
    assert buyer["wallet_credit_cents"] == 950_400
    assert order["amount_paid_cents"] - buyer["wallet_credit_cents"] == 2_036_600


def test_reversing_the_claim_restores_the_buyer_net_outlay_with_no_drift():
    """The reversal undoes every hop of the approval - wallet, order ledger, lot score,
    seller standing - and leaves the frozen seller payout alone.

    PRD 3.8: "It is a complete compensation of the decision: the order's
    `claim_credit_cents` and the buyer's `wallet_credit_cents` each fall by the reversed
    `refund_cents`, and when `claim_credit_cents` returns to zero the order returns
    `REFUND_ISSUED → PAID`; the buyer's net cash position returns to exactly its pre-claim
    value with no residual drift."
    PRD 3.8: "A reversal advances the claim `APPROVED → REVERSED` or `PARTIALLY_APPROVED →
    REVERSED`, records `reversed_by_user_id`, and advances the claim's `version` by one."
    PRD 3.8: "The reversed claim leaves the scoring population, so the lot's
    `manifest_accuracy_score` returns to its pre-claim value, which restores the seller's
    `manifest_accuracy_avg` and `scored_lot_count`, which may return the seller's
    `account_status` to `ACTIVE` and reassign its `commission_tier`."
    PRD 3.9: "Note what is absent: an approved claim never reduces
    `seller_net_proceeds_cents`."

    Design: Difficulty/compensating_invariant/buyer_net_outlay_restored_by_claim_reversal
    """
    built = setup_claim_under_review()
    env = built["env"]
    decided = decide_claim(env, built["claim"], "APPROVE", 80)

    reversed_claim = get_success_data(
        api_client.reverse_claim(decided["id"], claim_reversal_payload(), REVERSER)
    )
    assert reversed_claim["claim_status"] == "REVERSED"
    assert reversed_claim["reversed_by_user_id"] == SECOND_TRUST_SAFETY_USER_ID
    assert reversed_claim["refund_cents"] == 950_400
    assert reversed_claim["version"] == decided["version"] + 1

    order = read_order(env, built["order"]["id"])
    buyer = read_buyer(env)
    assert buyer["wallet_credit_cents"] == 0
    assert order["claim_credit_cents"] == 0
    assert order["payment_status"] == "PAID"
    assert order["total_due_cents"] == 2_987_000
    assert order["amount_paid_cents"] == 2_987_000
    assert order["balance_due_cents"] == 0
    assert order["amount_paid_cents"] - buyer["wallet_credit_cents"] == 2_987_000

    # PRD 2.8: "every field the decision moved returns to the value it held before
    # the decision - ... the lot's accuracy score, the seller's average, scored lot
    # count, account status and commission tier - with no residual drift."  Before
    # the decision this lot had never been claimed against, so its pre-claim score
    # is null (PRD 3.8: "A lot's `manifest_accuracy_score` stays null until the
    # first claim against it is resolved") and the line's verified_unit_count is
    # null (PRD 3.1: "Every appended line begins with `line_status` set to `ACTIVE`
    # and `verified_unit_count` null").
    assert read_lot(env, built["lot"]["id"])["manifest_accuracy_score"] is None
    assert read_manifest_line(env, built["claim_line"]["id"])["verified_unit_count"] is None

    seller = read_seller(env)
    assert seller["manifest_accuracy_avg"] == 1.000
    assert seller["scored_lot_count"] == 0
    assert seller["account_status"] == "ACTIVE"
    assert seller["commission_tier"] == "TIER_PREFERRED"
    assert seller["commission_rate_bps"] == 1_500

    assert order["seller_commission_cents"] == 405_000
    assert order["seller_net_proceeds_cents"] == 2_295_000


def test_a_partial_approval_prices_only_the_units_it_verified():
    """Eight of the ten claimed units are confirmed, so the refund is priced on eight - and
    eight units sit inside the tolerance, so the lot keeps a perfect score.

    PRD 3.8: "An `APPROVE` decision advances `UNDER_REVIEW → APPROVED` and a
    `PARTIALLY_APPROVE` decision advances `UNDER_REVIEW → PARTIALLY_APPROVED`; the two are
    otherwise identical in every side effect, the only difference being that a partial
    approval computes the refund on the smaller confirmed count."
    PRD 3.8: "Fourth, the base refund is that per-unit recovery multiplied by
    `verified_units` — a plain multiplication of an already-rounded figure, with no further
    rounding."
    PRD 3.8: "Fifth, the premium portion of the refund is the base refund multiplied by the
    order's snapshotted `buyer_premium_bps`, divided by 10,000, rounded half up to a whole
    cent."
    PRD 3.8: "The allowance in units is the lot's `declared_unit_count` multiplied by that
    fraction and rounded **down** to a whole unit, so a 400-unit `CUSTOMER_RETURNS` lot
    absorbs exactly 12 units of shortfall for free while the same 400 units graded
    `NEW_OVERSTOCK` absorb only 4 and graded `SALVAGE` absorb 32."

    Design: Corner/calculations/claim_partial_approval_refunds_only_the_verified_units
    """
    built = setup_claim_under_review(claimed_units=10)
    env = built["env"]

    decided = decide_claim(env, built["claim"], "PARTIALLY_APPROVE", 8)
    assert decided["claim_status"] == "PARTIALLY_APPROVED"
    assert decided["verified_units"] == 8
    assert decided["evidence_item_count"] == 2
    assert decided["decided_by_user_id"] == CLAIM_DECIDER_USER_ID
    assert decided["refund_cents"] == 95_040

    order = read_order(env, built["order"]["id"])
    assert order["claim_credit_cents"] == 95_040
    assert order["total_due_cents"] == 2_891_960
    assert order["amount_paid_cents"] == 2_987_000
    assert order["balance_due_cents"] == 0
    assert order["payment_status"] == "REFUND_ISSUED"

    buyer = read_buyer(env)
    assert buyer["wallet_credit_cents"] == 95_040
    assert buyer["outstanding_exposure_cents"] == 0

    assert read_lot(env, built["lot"]["id"])["manifest_accuracy_score"] == 1.000
    assert read_manifest_line(env, built["claim_line"]["id"])["verified_unit_count"] == 8

    seller = read_seller(env)
    assert seller["manifest_accuracy_avg"] == 1.000
    assert seller["scored_lot_count"] == 1
    assert seller["account_status"] == "ACTIVE"


def test_denied_and_undecided_claims_stay_out_of_the_credit_and_the_score():
    """Three claims sit on one line; only the approved one funds a refund or costs the lot
    any accuracy.

    PRD 3.8: "A `DENY` decision advances `UNDER_REVIEW → DENIED`, sets `refund_cents` to
    zero and `verified_units` to zero, records `decided_by_user_id`, and touches no order,
    buyer or seller aggregate whatsoever."
    PRD 3.8: "The total verified shortfall is the sum of `verified_units` over every claim
    against a manifest line of this lot whose `claim_status` is `APPROVED` or
    `PARTIALLY_APPROVED`; claims that are `REVERSED`, `DENIED`, `SUBMITTED`, `UNDER_REVIEW`
    or `EVIDENCE_REQUESTED` contribute nothing."
    PRD 3.8: "The score is then one minus the excess divided by `declared_unit_count`,
    rounded half up to three decimal places and clamped to the range from 0.000 through
    1.000."

    Design: Corner/calculations/claim_credit_and_accuracy_score_ignore_denied_and_undecided_claims
    """
    built = setup_picked_up_order()
    env = built["env"]
    line = built["lines"][0]
    set_clock("2026-08-18T15:00:00Z")
    claim_a = file_claim(
        env, built["order"], line["id"], claimed_units=10,
        evidence_urls=DEFAULT_EVIDENCE_URLS,
    )
    claim_b = file_claim(
        env, built["order"], line["id"], claimed_units=50,
        evidence_urls=DEFAULT_EVIDENCE_URLS,
    )
    claim_c = file_claim(
        env, built["order"], line["id"], claimed_units=20,
        evidence_urls=DEFAULT_EVIDENCE_URLS,
    )

    denied = decide_claim(env, claim_a, "DENY", 0)
    approved = decide_claim(env, claim_c, "APPROVE", 20)

    assert denied["claim_status"] == "DENIED"
    assert denied["refund_cents"] == 0
    assert denied["verified_units"] == 0

    pending = read_claim(env, claim_b["id"])
    assert pending["claim_status"] == "UNDER_REVIEW"
    assert pending["refund_cents"] == 0
    assert pending["verified_units"] is None

    assert approved["claim_status"] == "APPROVED"
    assert approved["verified_units"] == 20
    assert approved["refund_cents"] == 237_600

    order = read_order(env, built["order"]["id"])
    assert order["claim_credit_cents"] == 237_600
    assert order["total_due_cents"] == 2_749_400
    assert order["balance_due_cents"] == 0
    assert order["payment_status"] == "REFUND_ISSUED"
    assert read_buyer(env)["wallet_credit_cents"] == 237_600

    assert read_lot(env, built["lot"]["id"])["manifest_accuracy_score"] == 0.980
    assert read_manifest_line(env, line["id"])["verified_unit_count"] == 20

    seller = read_seller(env)
    assert seller["manifest_accuracy_avg"] == 0.980
    assert seller["scored_lot_count"] == 1
    assert seller["account_status"] == "ACTIVE"


def test_the_filing_gate_refuses_five_different_ways_and_writes_nothing():
    """Possession, unit counts, lot membership, voided lines and the window each turn a
    filing away, and none of the refusals leaves a claim behind.

    PRD 3.8: "At band 10, the order's `logistics_status` must be `PICKED_UP` — a buyer cannot
    dispute a manifest before taking possession — reported as
    `ERR_ORDER_LOGISTICS_STATE_INVALID`; and the referenced line's `line_status` must be
    `ACTIVE`, since a voided line was never sold, reported as `ERR_LINE_VOIDED`."
    PRD 3.8: "At band 12, the current logical clock must be at or before the order's
    `claim_window_closes_at`, with the boundary inclusive, or the filing is refused with
    `ERR_CLAIM_WINDOW_CLOSED`."
    PRD 3.8: "At band 15, `claimed_units` must not exceed the line's own `unit_count`, or the
    filing is `ERR_CLAIMED_UNITS_EXCEED_LINE`, and the line's `lot_id` must identify the very
    lot behind the order's listing, or the filing is `ERR_LINE_NOT_ON_ORDER_LOT`."
    PRD 3.1: "A voided line has its `line_status` set to `VOIDED` and is retained permanently
    for audit, but it leaves every aggregate immediately: the three lot aggregates are
    recomputed over the remaining `ACTIVE` lines, which restores the declared unit total to
    exactly what it would have been had the voided line never been appended."

    Design: Corner/errors/claim_filing_errors_are_all_reachable
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(
        env, CANONICAL_LOT_LINES + [VOIDED_LINE],
        title="Apparel customer returns with a correction",
    )
    lot_id = built["lot"]["id"]
    kept_line, voided_line = built["lines"][0], built["lines"][2]
    validate_success(
        api_client.void_manifest_line(voided_line["id"], {}, env["seller_headers"])
    )
    submit_manifest(env, lot_id)
    review_manifest(env, lot_id)
    listing = create_listing(env, lot_id, fixed_price_listing_payload(2_700_000))
    listing = publish_listing(env, listing["id"])
    foreign = create_lot_with_lines(
        env, FOREIGN_LOT_LINES, title="Unlisted home goods lot", category_code="HOME_GOODS",
    )

    set_clock(LATE_PURCHASE_CLOCK)
    buy_at_ask(env, listing)
    order = order_for_listing(listing["id"], env["buyer_headers"])
    order = pay_order(env, order)
    appointment = book_appointment(
        env, order, window_start_at=PICKUP_START, window_end_at=PICKUP_END,
        bol_number="BOL-CLAIM",
    )

    before_possession = api_client.file_claim(
        order["id"],
        claim_payload(kept_line["id"], "UNIT_SHORTAGE", 5, DEFAULT_EVIDENCE_URLS),
        env["buyer_headers"],
    )
    validate_error(before_possession, "ERR_ORDER_LOGISTICS_STATE_INVALID", 409)

    complete_appointment(
        env, appointment, actual_freight_cents=17_000, picked_up_unit_count=395
    )
    picked_up = read_order(env, order["id"])
    assert picked_up["logistics_status"] == "PICKED_UP"
    assert_instant(picked_up["claim_window_closes_at"], "2026-08-23T14:00:00Z")

    too_many_units = api_client.file_claim(
        order["id"],
        claim_payload(kept_line["id"], "UNIT_SHORTAGE", 101, DEFAULT_EVIDENCE_URLS),
        env["buyer_headers"],
    )
    validate_error(too_many_units, "ERR_CLAIMED_UNITS_EXCEED_LINE", 422)

    another_lots_line = api_client.file_claim(
        order["id"],
        claim_payload(foreign["lines"][0]["id"], "MISSING_SKU", 5, DEFAULT_EVIDENCE_URLS),
        env["buyer_headers"],
    )
    validate_error(another_lots_line, "ERR_LINE_NOT_ON_ORDER_LOT", 422)

    on_a_voided_line = api_client.file_claim(
        order["id"],
        claim_payload(voided_line["id"], "UNIT_SHORTAGE", 5, DEFAULT_EVIDENCE_URLS),
        env["buyer_headers"],
    )
    validate_error(on_a_voided_line, "ERR_LINE_VOIDED", 409)

    set_clock("2026-08-23T14:00:01Z")
    one_second_late = api_client.file_claim(
        order["id"],
        claim_payload(kept_line["id"], "UNIT_SHORTAGE", 5, DEFAULT_EVIDENCE_URLS),
        env["buyer_headers"],
    )
    validate_error(one_second_late, "ERR_CLAIM_WINDOW_CLOSED", 422)

    assert total_count(
        api_client.list_claims(ADMIN, {"sale_order_id": order["id"]})
    ) == 0
    assert read_order(env, order["id"])["claim_credit_cents"] == 0

    lot = read_lot(env, lot_id)
    assert lot["manifest_line_count"] == 2
    assert lot["declared_unit_count"] == 400
    assert lot["declared_retail_value_cents"] == 10_000_000


def test_the_decision_gate_refuses_on_state_on_arithmetic_and_on_the_request_cap():
    """A SUBMITTED claim is undecidable, every inconsistent verified_units is refused, and the
    third evidence request is one too many.

    PRD 3.8: "At band 9 the claim must be `UNDER_REVIEW`, or the decision is
    `ERR_CLAIM_STATE_INVALID`."
    PRD 3.8: "At band 15 the counters and the arithmetic are checked: a `REQUEST_EVIDENCE`
    decision requires `evidence_request_count` to be strictly below two, or it is refused with
    `ERR_EVIDENCE_REQUEST_LIMIT`; every other decision requires `evidence_item_count` to be at
    least two, or it is refused with `ERR_EVIDENCE_INSUFFICIENT`; and `verified_units` must be
    consistent with the decision — exactly equal to `claimed_units` for `APPROVE`, strictly
    greater than zero and strictly less than `claimed_units` for `PARTIALLY_APPROVE`, and
    exactly zero for `DENY` — with any inconsistency reported as `ERR_VERIFIED_UNITS_MISMATCH`."
    PRD 3.8: "From `SUBMITTED`, once `evidence_item_count` reaches at least two the claim
    advances `SUBMITTED → UNDER_REVIEW`; from `EVIDENCE_REQUESTED`, any evidence submission
    returns the claim `EVIDENCE_REQUESTED → UNDER_REVIEW`, closing the review loop."
    PRD 3.8: "A `REQUEST_EVIDENCE` decision advances the claim `UNDER_REVIEW →
    EVIDENCE_REQUESTED` and increments `evidence_request_count` by one; no money moves."
    PRD 3.8: "The claim records its parent order through `sale_order_id`, stamps `filed_at`
    with the current logical clock, sets `evidence_item_count` to the number of entries
    supplied in `evidence_urls`, sets `refund_cents` to zero, `verified_units` to null,
    `evidence_request_count` to zero, `decided_by_user_id` and `reversed_by_user_id` to null,
    and enters `claim_status` `SUBMITTED`."

    Design: Corner/errors/claim_decision_errors_are_all_reachable
    """
    built = setup_picked_up_order(
        sale="fixed_price", ask_price_cents=2_700_000, lines=CANONICAL_LOT_LINES,
        clock=LATE_PURCHASE_CLOCK,
    )
    env = built["env"]
    set_clock("2026-08-18T15:00:00Z")
    claim = file_claim(
        env, built["order"], built["lines"][0]["id"], claimed_units=8,
        evidence_urls=["https://evidence.example/only-one.jpg"],
    )
    claim_id = claim["id"]
    assert claim["claim_status"] == "SUBMITTED"
    assert claim["evidence_item_count"] == 1

    too_soon = api_client.decide_claim(
        claim_id, claim_decision_payload("APPROVE", 8), env["claims_headers"]
    )
    validate_error(too_soon, "ERR_CLAIM_STATE_INVALID", 409)
    still_submitted = read_claim(env, claim_id)
    assert still_submitted["claim_status"] == "SUBMITTED"
    assert still_submitted["evidence_item_count"] == 1

    second_item = get_success_data(
        api_client.add_claim_evidence_item(
            claim_id, {"evidence_url": "https://evidence.example/two.jpg"},
            env["buyer_headers"],
        )
    )
    assert second_item["claim_status"] == "UNDER_REVIEW"
    assert second_item["evidence_item_count"] == 2

    for payload in (
        claim_decision_payload("APPROVE", 3),
        claim_decision_payload("PARTIALLY_APPROVE", 8),
        claim_decision_payload("DENY", 2),
    ):
        validate_error(
            api_client.decide_claim(claim_id, payload, env["claims_headers"]),
            "ERR_VERIFIED_UNITS_MISMATCH", 422,
        )
    undecided = read_claim(env, claim_id)
    assert undecided["claim_status"] == "UNDER_REVIEW"
    assert undecided["verified_units"] is None
    assert undecided["refund_cents"] == 0

    first_request = get_success_data(
        api_client.decide_claim(
            claim_id, claim_decision_payload("REQUEST_EVIDENCE"), env["claims_headers"]
        )
    )
    assert first_request["claim_status"] == "EVIDENCE_REQUESTED"
    assert first_request["evidence_request_count"] == 1

    third_item = get_success_data(
        api_client.add_claim_evidence_item(
            claim_id, {"evidence_url": "https://evidence.example/three.jpg"},
            env["buyer_headers"],
        )
    )
    assert third_item["claim_status"] == "UNDER_REVIEW"
    assert third_item["evidence_item_count"] == 3

    second_request = get_success_data(
        api_client.decide_claim(
            claim_id, claim_decision_payload("REQUEST_EVIDENCE"), env["claims_headers"]
        )
    )
    assert second_request["claim_status"] == "EVIDENCE_REQUESTED"
    assert second_request["evidence_request_count"] == 2

    fourth_item = get_success_data(
        api_client.add_claim_evidence_item(
            claim_id, {"evidence_url": "https://evidence.example/four.jpg"},
            env["buyer_headers"],
        )
    )
    assert fourth_item["claim_status"] == "UNDER_REVIEW"
    assert fourth_item["evidence_item_count"] == 4

    over_the_cap = api_client.decide_claim(
        claim_id, claim_decision_payload("REQUEST_EVIDENCE"), env["claims_headers"]
    )
    validate_error(over_the_cap, "ERR_EVIDENCE_REQUEST_LIMIT", 422)
    assert read_claim(env, claim_id)["evidence_request_count"] == 2

    assert read_order(env, built["order"]["id"])["claim_credit_cents"] == 0
    assert read_buyer(env)["wallet_credit_cents"] == 0
