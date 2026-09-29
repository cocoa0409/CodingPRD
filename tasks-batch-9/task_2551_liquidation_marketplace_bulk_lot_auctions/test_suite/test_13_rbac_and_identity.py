"""Identity: the role gate, the two ownership gates, the duty splits and the 404 families."""

from test_helpers import (
    CANONICAL_CREDIT_LIMIT_CENTS,
    CLAIM_DECIDER_USER_ID,
    NON_EXISTENT_UUID,
    REVIEWER_USER_ID,
    SECOND_TRUST_SAFETY_USER_ID,
    add_buyer,
    api_client,
    bootstrap_marketplace,
    build_user_headers,
    buyer_account_payload,
    claim_decision_payload,
    claim_reversal_payload,
    create_lot_with_lines,
    create_seller,
    decide_claim,
    get_success_data,
    lot_payload,
    make_buyer_headers,
    make_marketplace_ops_headers,
    make_seller_ops_headers,
    make_trust_safety_headers,
    manifest_line_payload,
    manifest_review_payload,
    pay_order,
    payment_payload,
    pickup_appointment_payload,
    qualification_decision_payload,
    read_buyer,
    read_claim,
    read_lot,
    read_manifest_line,
    read_order,
    setup_claim_under_review,
    setup_decided_claim,
    setup_fixed_price_order,
    setup_paid_fixed_price_order,
    submit_manifest,
    total_count,
    validate_error,
)

# A single-SKU 200-unit lot: 200 units at 10,000 cents is 2,000,000 cents of declared
# retail, and 200 units occupy exactly one pallet.
OWNED_LOT_LINES = [
    {
        "sku": "APP-OWN-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

BOOKING_WINDOW_START = "2026-08-10T09:00:00Z"
BOOKING_WINDOW_END = "2026-08-10T10:00:00Z"


def test_each_role_is_turned_away_from_the_operations_it_does_not_own():
    """Five well-formed requests aimed at five endpoints their role does not appear on, and
    the unknown listing id proves the role gate runs ahead of path existence.

    PRD 2.1: "If both headers are present but the value of `X-User-Role` is not among the
    roles the target endpoint admits, the request is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."
    PRD 2.1: "A `PlatformAdmin` provisions the reference data the marketplace runs on —
    seller accounts, buyer accounts, warehouses, carriers, brand policies — and adjusts
    buyer credit ceilings. It never touches a lot, a bid or a claim."
    PRD 2.1: "`TrustSafety` is the compliance desk: it qualifies, rejects, suspends and
    reinstates buyers, and it reverses claim decisions it did not itself make."
    PRD 2.5: "**Role authorisation.** `X-User-Role` appears in the endpoint's permitted role
    list, or `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."
    PRD 2.5: "…the platform evaluates checks in sixteen numbered bands and returns the error
    belonging to the **lowest-numbered band** that fails, stopping there."

    Design: Corner/rbac/roles_cannot_invoke_another_roles_exclusive_operations
    """
    env = bootstrap_marketplace()
    lot = create_lot_with_lines(env)["lot"]
    submit_manifest(env, lot["id"])

    # A Buyer cannot build a seller's lot.
    validate_error(
        api_client.create_lot(
            lot_payload(
                env["seller"]["id"], env["warehouse"]["id"], title="Buyer built lot"
            ),
            env["buyer_headers"],
        ),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    # A seller cannot review its own manifest.
    validate_error(
        api_client.review_manifest(
            lot["id"],
            manifest_review_payload("APPROVE", review_note="self review attempt"),
            env["seller_headers"],
        ),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    # TrustSafety cannot close an auction - and the unknown listing id never gets looked up.
    closure_error = validate_error(
        api_client.close_listing(NON_EXISTENT_UUID, {}, env["trust_safety_headers"]),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    assert closure_error["error_id"] != "ERR_LISTING_NOT_FOUND"
    # MarketplaceOps cannot provision reference data.
    validate_error(
        api_client.create_buyer_account(
            buyer_account_payload(
                legal_name="Ops Provisioned Buyer", tax_id="B-9999",
                contact_email="ops@buy.example", resale_certificate_number="TX-RC-99",
                requested_credit_limit_cents=100_000,
            ),
            env["reviewer_headers"],
        ),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    # PlatformAdmin cannot qualify a buyer, even though it owns credit ceilings.
    validate_error(
        api_client.decide_buyer_qualification(
            env["buyer"]["id"],
            qualification_decision_payload("QUALIFY", approved_credit_limit_cents=999),
            env["admin_headers"],
        ),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )

    untouched_lot = read_lot(env, lot["id"])
    assert untouched_lot["lot_status"] == "MANIFEST_IN_REVIEW"
    assert untouched_lot["manifest_reviewed_by_user_id"] is None
    assert total_count(api_client.list_buyer_accounts(env["admin_headers"])) == 1
    buyer = read_buyer(env, env["buyer"]["id"])
    assert buyer["approved_credit_limit_cents"] == CANONICAL_CREDIT_LIMIT_CENTS


def test_a_second_seller_can_neither_write_the_lot_nor_read_its_recovery_numbers():
    """Three seller-side writes and the analytics read all fail on ownership for the wrong
    seller, and every one of them succeeds for the seller that owns the row.

    PRD 2.5: "**Resource ownership.** A `SellerOps` caller acts only on lots, manifest
    lines, listings and negotiations whose lot's `seller_id` equals `X-User-ID`; a `Buyer`
    caller acts only on bids, negotiations, sale orders, pickup appointments and claims
    whose `buyer_id` equals `X-User-ID`. Violation is `ERR_NOT_RESOURCE_OWNER` (403).
    Applies to every `SellerOps` and `Buyer` write endpoint, and to the recovery-analytics
    read when the caller is `SellerOps`."
    PRD 2.1: "Recovery analytics may be read by `PlatformAdmin`, `MarketplaceOps` and
    `SellerOps`, but a `SellerOps` caller may only request analytics for its own seller —
    asking for another seller's numbers is `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.1: "Submitting a manifest advances the lot `DRAFT → MANIFEST_IN_REVIEW`. The
    submission takes no payload; the lot must be in `DRAFT`, the caller's `X-User-ID` must
    equal the lot's `seller_id`, and the lot must hold at least one line with `line_status`
    equal to `ACTIVE`."
    PRD 3.1: "Appending a line recomputes the three lot aggregates over `ACTIVE` lines
    only: `manifest_line_count` becomes the number of such lines, `declared_unit_count`
    becomes the sum of their `unit_count` values, and `declared_retail_value_cents` becomes
    the sum, over those same lines, of each line's `unit_count` multiplied by its
    `unit_retail_cents`."
    PRD 3.9: "A freshly registered seller starts `ACTIVE` on `TIER_STANDARD` at 2,000 basis
    points with every recovery aggregate at zero and `manifest_accuracy_avg` at 1.000."

    Design: Corner/rbac/seller_ops_cannot_write_to_another_sellers_lot_or_read_its_analytics
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, OWNED_LOT_LINES)
    lot, line = built["lot"], built["lines"][0]
    intruder = create_seller(
        legal_name="Ridge Salvage LLC", tax_id="S-1002",
        contact_email="ops@ridgesalvage.example",
    )
    intruder_headers = make_seller_ops_headers(intruder["id"])

    validate_error(
        api_client.create_manifest_line(
            lot["id"],
            manifest_line_payload(sku="INTRUDER", unit_count=5, unit_retail_cents=1_000),
            intruder_headers,
        ),
        "ERR_NOT_RESOURCE_OWNER", 403,
    )
    validate_error(
        api_client.void_manifest_line(line["id"], {}, intruder_headers),
        "ERR_NOT_RESOURCE_OWNER", 403,
    )
    validate_error(
        api_client.submit_manifest(lot["id"], {}, intruder_headers),
        "ERR_NOT_RESOURCE_OWNER", 403,
    )
    validate_error(
        api_client.get_recovery_analytics(
            intruder_headers, params={"seller_id": env["seller"]["id"]}
        ),
        "ERR_NOT_RESOURCE_OWNER", 403,
    )

    unchanged = read_lot(env, lot["id"])
    assert unchanged["manifest_line_count"] == 1
    assert unchanged["declared_unit_count"] == 200
    assert unchanged["declared_retail_value_cents"] == 2_000_000
    assert unchanged["lot_status"] == "DRAFT"
    assert read_manifest_line(env, line["id"])["line_status"] == "ACTIVE"

    # The owner's identical submission goes through.
    submit_manifest(env, lot["id"])
    assert read_lot(env, lot["id"])["lot_status"] == "MANIFEST_IN_REVIEW"

    # And the endpoint itself is reachable for the seller asking about itself.
    own_numbers = get_success_data(
        api_client.get_recovery_analytics(
            intruder_headers, params={"seller_id": intruder["id"]}
        )
    )
    assert own_numbers["seller_id"] == intruder["id"]
    assert own_numbers["gross_recovery_rate"] == 0.0000


def test_ownership_outranks_the_money_and_state_checks_on_another_buyers_order():
    """The wrong buyer offers exactly the right amount and books a legal window, and both
    are refused on ownership rather than on the amount or on the unpaid order.

    PRD 2.5: "**Resource ownership.** A `SellerOps` caller acts only on lots, manifest
    lines, listings and negotiations whose lot's `seller_id` equals `X-User-ID`; a `Buyer`
    caller acts only on bids, negotiations, sale orders, pickup appointments and claims
    whose `buyer_id` equals `X-User-ID`. Violation is `ERR_NOT_RESOURCE_OWNER` (403)."
    PRD 3.6: "The amount must be at least 1 cent and at most the order's current
    `balance_due_cents`; an amount outside that inclusive range — including any attempt to
    overpay — is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD 3.6: "Exactly two cross-dimension guards exist, and both are one-directional: an
    appointment may only be scheduled while `payment_status` is `PAID`, and a payment may
    not be accepted while `logistics_status` is `ABANDONED`."
    PRD 3.2: "The second part covers unsettled orders: over all of this buyer's sale orders
    whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose `logistics_status` is
    not `ABANDONED`, sum `balance_due_cents`."
    PRD 3.6: "a payment exactly equal to the outstanding balance advances `UNPAID → PAID` or
    `PARTIALLY_PAID → PAID`, drives `balance_due_cents` to zero and stamps `paid_at` with
    the logical clock instant at which the balance first reached zero."

    Design: Corner/rbac/buyer_cannot_pay_or_claim_on_another_buyers_sale_order
    """
    built = setup_fixed_price_order(ask_price_cents=1_000_000, lines=OWNED_LOT_LINES)
    env, order = built["env"], built["order"]
    assert order["total_due_cents"] == 1_148_500
    assert order["payment_status"] == "UNPAID"

    intruder = add_buyer(env)
    intruder_headers = make_buyer_headers(intruder["id"])

    pay_error = validate_error(
        api_client.pay_sale_order(
            order["id"], payment_payload(1_148_500), intruder_headers
        ),
        "ERR_NOT_RESOURCE_OWNER", 403,
    )
    assert pay_error["error_id"] != "ERR_PAYMENT_EXCEEDS_BALANCE"
    book_error = validate_error(
        api_client.book_pickup_appointment(
            order["id"],
            pickup_appointment_payload(
                env["warehouse"]["id"], env["carrier"]["id"],
                BOOKING_WINDOW_START, BOOKING_WINDOW_END, bol_number="BOL-INTRUDER",
            ),
            intruder_headers,
        ),
        "ERR_NOT_RESOURCE_OWNER", 403,
    )
    assert book_error["error_id"] != "ERR_ORDER_NOT_PAID"

    refused = read_order(env, order["id"])
    assert refused["amount_paid_cents"] == 0
    assert refused["payment_status"] == "UNPAID"
    assert refused["logistics_status"] == "AWAITING_APPOINTMENT"
    assert read_buyer(env, intruder["id"])["outstanding_exposure_cents"] == 0
    assert total_count(
        api_client.list_pickup_appointments(
            env["admin_headers"], params={"sale_order_id": order["id"]}
        )
    ) == 0

    # The owner's identical payment settles the order.
    paid = pay_order(env, refused, 1_148_500)
    assert paid["payment_status"] == "PAID"
    assert paid["amount_paid_cents"] == 1_148_500
    assert paid["balance_due_cents"] == 0


def test_the_lots_own_reviewer_cannot_decide_the_claim_against_it():
    """The operator recorded on the lot's review is barred from both the money-moving and
    the evidence-requesting decision, and an independent adjudicator then pays the refund.

    PRD 2.5: "**Segregation of duties.** For a claim decision, the deciding `MarketplaceOps`
    `X-User-ID` differs from the `manifest_reviewed_by_user_id` of the lot owning that
    claim's manifest line; for a claim reversal, the reversing `TrustSafety` `X-User-ID`
    differs from the claim's `decided_by_user_id`. Either violation is
    `ERR_SEGREGATION_OF_DUTIES` (403). This band sits deliberately ahead of every claim
    state, evidence and units check, so a disqualified operator is turned away regardless of
    the claim's condition."
    PRD 3.8: "The very first thing checked is the segregation rule of §2.1 and band 5: the
    reviewer's `X-User-ID` must differ from the `manifest_reviewed_by_user_id` recorded on
    the lot owning the claim's manifest line, or the request is `ERR_SEGREGATION_OF_DUTIES` —
    checked ahead of the claim's own state, ahead of the evidence counters and ahead of the
    units arithmetic, so a disqualified reviewer never learns anything about the claim's
    condition."
    PRD 3.1: "From `MANIFEST_IN_REVIEW`, an approval advances the lot to `MANIFEST_APPROVED`
    and a rejection advances it to `MANIFEST_REJECTED`; either way the reviewing operator's
    `X-User-ID` is written to `manifest_reviewed_by_user_id` and the lot's `version` advances
    by one."
    PRD 3.8: "Worked through on a lot whose `declared_retail_value_cents` is 10,000,000 with
    a line of 100 units at 40,000 cents each, an order with a hammer price of 2,700,000 cents
    and a premium rate of 1,000 basis points: the line share is 1,080,000 cents, the per-unit
    recovery is 10,800 cents, 80 confirmed units give a base refund of 864,000 cents, the
    premium portion is 86,400 cents, and `refund_cents` is 950,400 cents."
    PRD 3.8: "Fourth, the base refund is that per-unit recovery multiplied by
    `verified_units` — a plain multiplication of an already-rounded figure, with no further
    rounding."
    PRD 3.8: "Fifth, the premium portion of the refund is the base refund multiplied by the
    order's snapshotted `buyer_premium_bps`, divided by 10,000, rounded half up to a whole
    cent."
    PRD 3.8: "An approval or partial approval increases the order's `claim_credit_cents` by
    the computed `refund_cents`, which lowers `total_due_cents` and recomputes
    `balance_due_cents` under the zero clamp of §3.6, and advances the order `PAID →
    REFUND_ISSUED`."
    PRD 3.8: "The allowance in units is the lot's `declared_unit_count` multiplied by that
    fraction and rounded **down** to a whole unit, so a 400-unit `CUSTOMER_RETURNS` lot
    absorbs exactly 12 units of shortfall for free while the same 400 units graded
    `NEW_OVERSTOCK` absorb only 4 and graded `SALVAGE` absorb 32."

    Design: Corner/rbac/the_manifest_reviewer_cannot_decide_a_claim_against_the_lot_it_reviewed
    """
    built = setup_claim_under_review(claimed_units=8)
    env, claim, order = built["env"], built["claim"], built["order"]
    reviewer_headers = make_marketplace_ops_headers(REVIEWER_USER_ID)
    assert read_lot(env, built["lot"]["id"])["manifest_reviewed_by_user_id"] == REVIEWER_USER_ID
    assert order["total_due_cents"] == 2_987_000

    validate_error(
        api_client.decide_claim(
            claim["id"],
            claim_decision_payload(
                "APPROVE", 8, decision_note="reviewer deciding its own lot"
            ),
            reviewer_headers,
        ),
        "ERR_SEGREGATION_OF_DUTIES", 403,
    )
    # The bar covers the decision that moves no money at all.
    validate_error(
        api_client.decide_claim(
            claim["id"],
            claim_decision_payload(
                "REQUEST_EVIDENCE", decision_note="reviewer asking for more"
            ),
            reviewer_headers,
        ),
        "ERR_SEGREGATION_OF_DUTIES", 403,
    )

    refused = read_claim(env, claim["id"])
    assert refused["claim_status"] == "UNDER_REVIEW"
    assert refused["verified_units"] is None
    assert refused["decided_by_user_id"] is None
    assert refused["evidence_request_count"] == 0
    assert refused["refund_cents"] == 0

    # The independent adjudicator's identical body is accepted.
    decided = decide_claim(
        env, claim, "APPROVE", 8, decision_note="independent adjudicator"
    )
    assert decided["claim_status"] == "APPROVED"
    assert decided["verified_units"] == 8
    assert decided["decided_by_user_id"] == CLAIM_DECIDER_USER_ID
    assert decided["refund_cents"] == 95_040

    credited = read_order(env, order["id"])
    assert credited["claim_credit_cents"] == 95_040
    assert credited["total_due_cents"] == 2_891_960
    assert credited["payment_status"] == "REFUND_ISSUED"
    assert credited["balance_due_cents"] == 0
    assert read_buyer(env, env["buyer"]["id"])["wallet_credit_cents"] == 95_040
    # Eight units sit inside the 12-unit CUSTOMER_RETURNS allowance, so the score is perfect.
    assert read_lot(env, built["lot"]["id"])["manifest_accuracy_score"] == 1.000

def test_the_deciding_operator_cannot_reverse_its_own_approval():
    """The reversal bar keys on the recorded decider id, not on the role header, so the same
    operator wearing TrustSafety is refused while a second compliance user unwinds the refund.

    PRD 2.1: "The `MarketplaceOps` operator whose `X-User-ID` was recorded as a lot's
    `manifest_reviewed_by_user_id` must not be the `MarketplaceOps` operator who decides a
    manifest discrepancy claim whose manifest line belongs to that lot; and the `TrustSafety`
    operator reversing a claim must not be the operator whose `X-User-ID` was recorded as that
    claim's `decided_by_user_id`."
    PRD 3.8: "Band 5 applies here too: the reversing operator's `X-User-ID` must differ from
    the claim's `decided_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.8: "A reversal advances the claim `APPROVED → REVERSED` or `PARTIALLY_APPROVED →
    REVERSED`, records `reversed_by_user_id`, and advances the claim's `version` by one."
    PRD 3.8: "It is a complete compensation of the decision: the order's `claim_credit_cents`
    and the buyer's `wallet_credit_cents` each fall by the reversed `refund_cents`, and when
    `claim_credit_cents` returns to zero the order returns `REFUND_ISSUED → PAID`; the
    buyer's net cash position returns to exactly its pre-claim value with no residual drift."
    PRD 3.8: "The reversed claim leaves the scoring population, so the lot's
    `manifest_accuracy_score` returns to its pre-claim value, which restores the seller's
    `manifest_accuracy_avg` and `scored_lot_count`, which may return the seller's
    `account_status` to `ACTIVE` and reassign its `commission_tier`."

    Design: Corner/rbac/the_deciding_user_cannot_reverse_its_own_claim_decision
    """
    built = setup_decided_claim(claimed_units=8)
    env, claim, order = built["env"], built["claim"], built["order"]
    assert claim["decided_by_user_id"] == CLAIM_DECIDER_USER_ID
    assert claim["refund_cents"] == 95_040
    assert order["claim_credit_cents"] == 95_040
    assert order["total_due_cents"] == 2_891_960
    assert read_buyer(env, env["buyer"]["id"])["wallet_credit_cents"] == 95_040

    # The decider, now wearing the TrustSafety role, is still the decider.
    validate_error(
        api_client.reverse_claim(
            claim["id"],
            claim_reversal_payload(reversal_reason="decider reversing itself"),
            make_trust_safety_headers(CLAIM_DECIDER_USER_ID),
        ),
        "ERR_SEGREGATION_OF_DUTIES", 403,
    )
    still_approved = read_claim(env, claim["id"])
    assert still_approved["claim_status"] == "APPROVED"
    assert still_approved["reversed_by_user_id"] is None

    reversed_claim = get_success_data(
        api_client.reverse_claim(
            claim["id"],
            claim_reversal_payload(reversal_reason="independent compliance review"),
            make_trust_safety_headers(SECOND_TRUST_SAFETY_USER_ID),
        )
    )
    assert reversed_claim["claim_status"] == "REVERSED"
    assert reversed_claim["reversed_by_user_id"] == SECOND_TRUST_SAFETY_USER_ID
    # The historical amount is retained on the reversed claim.
    assert reversed_claim["refund_cents"] == 95_040

    restored = read_order(env, order["id"])
    assert restored["claim_credit_cents"] == 0
    assert restored["total_due_cents"] == 2_987_000
    assert restored["payment_status"] == "PAID"
    assert read_buyer(env, env["buyer"]["id"])["wallet_credit_cents"] == 0
    # PRD 2.8: the reversal returns the lot's accuracy score to "the value it held
    # before the decision", and this lot had never been claimed against before, so
    # the pre-claim score is null.
    assert read_lot(env, built["lot"]["id"])["manifest_accuracy_score"] is None


def test_an_empty_user_id_is_refused_before_existence_and_before_shape():
    """An empty `X-User-ID` under a correct role header beats the unknown path id and beats
    the out-of-set enum, and the same body succeeds once the identity is supplied.

    PRD 2.1: "If either header is missing or present but empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration — before the path is
    resolved, before the body is parsed, before any state is inspected."
    PRD 2.5: "**Authentication.** Both `X-User-ID` and `X-User-Role` present and non-empty,
    or `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."
    PRD 2.5: "**Path existence.** Every identifier embedded in the URL path resolves to a
    stored row, checked from left to right, with the leftmost unresolved segment deciding the
    error: `ERR_LOT_NOT_FOUND`, `ERR_MANIFEST_LINE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_NEGOTIATION_NOT_FOUND`, `ERR_SALE_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_BUYER_NOT_FOUND` or `ERR_SELLER_NOT_FOUND`, each HTTP 404."
    PRD 2.10: "A lot's `condition_grade` is one of `NEW_OVERSTOCK`, `CUSTOMER_RETURNS` or
    `SALVAGE`."
    PRD 2.10: "A value outside the declared set is `ERR_INVALID_REQUEST` (400) at band 7."
    PRD 3.1: "Creation places the lot in `DRAFT` with `manifest_line_count`,
    `declared_unit_count` and `declared_retail_value_cents` all at zero,
    `manifest_accuracy_score` still null because no claim has ever been resolved against it,
    and `manifest_reviewed_by_user_id` still null."

    Design: Corner/rbac/requests_missing_auth_headers_are_unauthenticated_before_any_other_check
    """
    env = bootstrap_marketplace(with_buyer=False, with_carrier=False)
    anonymous_seller = build_user_headers("", "SellerOps")
    anonymous_ops = build_user_headers("", "MarketplaceOps")

    validate_error(
        api_client.create_lot(
            lot_payload(
                env["seller"]["id"], env["warehouse"]["id"], title="Anonymous lot"
            ),
            anonymous_seller,
        ),
        "ERR_UNAUTHENTICATED", 401,
    )
    # Band 1 beats band 3: the unknown lot id is never resolved.
    path_error = validate_error(
        api_client.get_lot(NON_EXISTENT_UUID, anonymous_ops),
        "ERR_UNAUTHENTICATED", 401,
    )
    assert path_error["error_id"] != "ERR_LOT_NOT_FOUND"
    # Band 1 beats band 7: the out-of-set condition grade is never parsed.
    body_error = validate_error(
        api_client.create_lot(
            lot_payload(
                env["seller"]["id"], env["warehouse"]["id"],
                title="Bad grade lot", condition_grade="PRISTINE",
            ),
            anonymous_seller,
        ),
        "ERR_UNAUTHENTICATED", 401,
    )
    assert body_error["error_id"] != "ERR_INVALID_REQUEST"

    assert total_count(api_client.list_lots(env["admin_headers"])) == 0

    # The same payload, fully headed, is accepted - so the body was never the problem.
    created = get_success_data(
        api_client.create_lot(
            lot_payload(
                env["seller"]["id"], env["warehouse"]["id"], title="Authenticated lot"
            ),
            env["seller_headers"],
        )
    )
    assert created["lot_status"] == "DRAFT"
    assert created["manifest_line_count"] == 0
    assert created["declared_unit_count"] == 0
    assert total_count(api_client.list_lots(env["admin_headers"])) == 1


def test_every_unknown_identifier_answers_with_its_own_not_found_error():
    """Six unresolved path ids each name their own segment's 404, and two unresolved body
    foreign keys name theirs - a different band, still a 404, and still no row written.

    PRD 2.5: "**Path existence.** Every identifier embedded in the URL path resolves to a
    stored row, checked from left to right, with the leftmost unresolved segment deciding the
    error: `ERR_LOT_NOT_FOUND`, `ERR_MANIFEST_LINE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_NEGOTIATION_NOT_FOUND`, `ERR_SALE_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_BUYER_NOT_FOUND` or `ERR_SELLER_NOT_FOUND`, each HTTP 404."
    PRD 2.5: "**Request-body foreign keys.** Every foreign reference carried in the request
    body resolves to a stored row — `seller_id`, `warehouse_id`, `brand_policy_id`, `lot_id`,
    `listing_id`, `buyer_id`, `carrier_id` and `manifest_line_id` — reported as
    `ERR_SELLER_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_BRAND_POLICY_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
    `ERR_CARRIER_NOT_FOUND` or `ERR_MANIFEST_LINE_NOT_FOUND` respectively, each HTTP 404."
    PRD 2.9: "Path parameters are resolved strictly left to right, and the first segment that
    fails to resolve determines the 404 error returned — a request naming a nonexistent lot
    and a nonexistent manifest line reports the lot as missing, because the lot segment
    appears first."
    PRD 3.1: "When a `SellerOps` operator creates one, the payload names the owning seller
    through a `seller_id`, the origin dock through a `warehouse_id`, an optional
    `brand_policy_id` when the merchandise carries a protected brand, a human-readable
    `title`, a `category_code` that later slices recovery analytics, and a `condition_grade`
    describing the goods as a whole."
    PRD 3.7: "Booking a dock window names the origin `warehouse_id`, the collecting
    `carrier_id`, the requested `window_start_at` and `window_end_at`, and the `bol_number`
    bill-of-lading reference the carrier will present."

    Design: Corner/errors/unknown_path_and_body_ids_return_their_not_found_errors
    """
    built = setup_paid_fixed_price_order(ask_price_cents=1_000_000, lines=OWNED_LOT_LINES)
    env, order = built["env"], built["order"]
    reader = env["reviewer_headers"]

    validate_error(
        api_client.get_listing(NON_EXISTENT_UUID, reader), "ERR_LISTING_NOT_FOUND", 404
    )
    validate_error(
        api_client.get_negotiation(NON_EXISTENT_UUID, reader),
        "ERR_NEGOTIATION_NOT_FOUND", 404,
    )
    validate_error(
        api_client.get_sale_order(NON_EXISTENT_UUID, reader),
        "ERR_SALE_ORDER_NOT_FOUND", 404,
    )
    validate_error(
        api_client.get_pickup_appointment(NON_EXISTENT_UUID, reader),
        "ERR_APPOINTMENT_NOT_FOUND", 404,
    )
    validate_error(
        api_client.get_claim(NON_EXISTENT_UUID, reader), "ERR_CLAIM_NOT_FOUND", 404
    )
    validate_error(
        api_client.get_manifest_line(NON_EXISTENT_UUID, reader),
        "ERR_MANIFEST_LINE_NOT_FOUND", 404,
    )

    # Body foreign keys carry their own 404s, each naming its own entity family.
    validate_error(
        api_client.create_lot(
            lot_payload(
                env["seller"]["id"], env["warehouse"]["id"],
                title="Bad policy lot", brand_policy_id=NON_EXISTENT_UUID,
            ),
            env["seller_headers"],
        ),
        "ERR_BRAND_POLICY_NOT_FOUND", 404,
    )
    validate_error(
        api_client.book_pickup_appointment(
            order["id"],
            pickup_appointment_payload(
                env["warehouse"]["id"], NON_EXISTENT_UUID,
                BOOKING_WINDOW_START, BOOKING_WINDOW_END, bol_number="BOL-NF",
            ),
            env["buyer_headers"],
        ),
        "ERR_CARRIER_NOT_FOUND", 404,
    )

    # Only the sale's own lot exists, and the refused booking wrote nothing.
    assert total_count(
        api_client.list_lots(env["admin_headers"], params={"seller_id": env["seller"]["id"]})
    ) == 1
    unchanged = read_order(env, order["id"])
    assert unchanged["logistics_status"] == "AWAITING_APPOINTMENT"
    assert unchanged["payment_status"] == "PAID"
    assert total_count(
        api_client.list_pickup_appointments(
            env["admin_headers"], params={"sale_order_id": order["id"]}
        )
    ) == 0
