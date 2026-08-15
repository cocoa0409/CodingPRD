"""Rebate claims: per-line rounding, fund reservation/exhaustion, adjudication, RBAC split."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_practice,
    create_product,
    create_order_payload,
    create_rebate_promotion_payload,
    create_rebate_claim_payload,
    setup_rebate_claim,
    make_practice_manager_headers,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
MANUFACTURER = TEST_USERS["manufacturer_agent_headers"]


def _promo(api, promo_id):
    return validate_success(api.get_promotion(promo_id, ADMIN), 200)


def test_rebate_claim_settle_from_draft_rejected(api):
    """PRD §3.4: "Or the agent may settle a `SUBMITTED` claim, moving it to `PAID` and
    stamping `paid_at`; `PAID` is terminal." — settle is undefined from DRAFT.
    PRD §2.8: "the requested transition must exist from the resource's current state,
    terminal states reject every transition, and violations yield `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/rebate_claim_settle_from_draft_rejected
    """
    ctx = setup_rebate_claim()
    res = api.settle_rebate_claim(ctx["claim"]["id"], MANUFACTURER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_rebate_claim(ctx["claim"]["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"
    assert after.get("paid_at") is None


def test_rebate_claim_paid_terminal_lockdown(api):
    """PRD §3.4: "Or the agent may settle a `SUBMITTED` claim, moving it to `PAID` and
    stamping `paid_at`; `PAID` is terminal."
    PRD §2.8: "terminal states reject every transition, and violations yield
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/rebate_claim_paid_terminal_lockdown
    """
    ctx = setup_rebate_claim(submit=True)
    paid = validate_success(api.settle_rebate_claim(ctx["claim"]["id"], MANUFACTURER), 200)
    assert paid["status"] == "PAID"

    res = api.deny_rebate_claim(ctx["claim"]["id"], {"denial_reason": "late"}, MANUFACTURER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_rebate_claim(ctx["claim"]["id"], ADMIN), 200)
    assert after["status"] == "PAID"


def test_rebate_per_line_round_then_sum_elite(api):
    """PRD §3.4: "The practice's tier supplies a multiplier — 1.0 for `STANDARD`, 1.1 for
    `PREMIER`, 1.25 for `ELITE` — read at claim-creation time. The rounding order is
    pinned: for each line of the referenced order whose product appears in
    `eligible_product_ids`, multiply the line quantity by `rebate_per_unit_cents` and by
    the tier multiplier, and round that line's rebate half up to whole cents first; the
    claim amount is then the sum of those per-line rounded rebates."

    Design: Difficulty/combinatorial_formula/rebate_per_line_round_then_sum
    """
    ctx = setup_rebate_claim(
        practice_tier="ELITE", rebate_per_unit_cents=50, fund_total_cents=100000,
        order_quantities=(1, 1),
    )
    # Per line: round_half_up(1 x 50 x 1.25) = 63; two lines -> 126.
    # The rejected sum-then-round reading would yield 125.
    assert ctx["claim"]["claim_amount_cents"] == 126


def test_rebate_per_line_round_then_sum_premier(api):
    """PRD §3.4: "The rounding order is pinned: for each line of the referenced order whose
    product appears in `eligible_product_ids`, multiply the line quantity by
    `rebate_per_unit_cents` and by the tier multiplier, and round that line's rebate half
    up to whole cents first; the claim amount is then the sum of those per-line rounded
    rebates. Rounding only the grand total instead is a different, rejected reading."

    Design: Difficulty/combinatorial_formula/rebate_per_line_round_then_sum
    """
    ctx = setup_rebate_claim(
        practice_tier="PREMIER", rebate_per_unit_cents=55, fund_total_cents=100000,
        order_quantities=(1, 1),
    )
    # Per line: round_half_up(1 x 55 x 1.1) = round_half_up(60.5) = 61; two lines -> 122.
    # Sum-then-round would yield round_half_up(121.0) = 121.
    assert ctx["claim"]["claim_amount_cents"] == 122


def test_claim_submit_debits_fund_exhausts_promotion(api):
    """PRD §3.4: "A successful submit stamps `submitted_at`, then reserves funds by
    subtracting the claim amount from `fund_remaining_cents`, and if that subtraction
    leaves the fund at zero or below, the promotion flips `ACTIVE` → `EXHAUSTED`."

    Design: Difficulty/transitive_cascade/claim_submit_debits_fund_exhausts_promotion
    """
    # ELITE: claim = 2 x round_half_up(1 x 50 x 1.25) = 126; fund exactly 126.
    ctx = setup_rebate_claim(
        practice_tier="ELITE", rebate_per_unit_cents=50, fund_total_cents=126,
        order_quantities=(1, 1),
    )
    pm = make_practice_manager_headers(ctx["practice"]["id"])
    submitted = validate_success(api.submit_rebate_claim(ctx["claim"]["id"], pm), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted.get("submitted_at") is not None

    promo = _promo(api, ctx["promotion"]["id"])
    assert promo["fund_remaining_cents"] == 0, "126 - 126"
    assert promo["status"] == "EXHAUSTED", "Fund at zero flips the promotion"


def test_claim_submit_partial_fund_stays_active(api):
    """PRD §3.4: "if that subtraction leaves the fund at zero or below, the promotion
    flips `ACTIVE` → `EXHAUSTED`" — a fund left strictly above zero does not flip.

    Design: Difficulty/transitive_cascade/claim_submit_debits_fund_exhausts_promotion
    """
    ctx = setup_rebate_claim(
        practice_tier="ELITE", rebate_per_unit_cents=50, fund_total_cents=200,
        order_quantities=(1, 1),
    )
    pm = make_practice_manager_headers(ctx["practice"]["id"])
    submitted = validate_success(api.submit_rebate_claim(ctx["claim"]["id"], pm), 200)
    assert submitted["status"] == "SUBMITTED"

    promo = _promo(api, ctx["promotion"]["id"])
    assert promo["fund_remaining_cents"] == 74, "200 - 126"
    assert promo["status"] == "ACTIVE"


def test_rebate_fund_released_on_deny_compensation(api):
    """PRD §3.4: "A `ManufacturerAgent` may deny a `SUBMITTED` claim, supplying a
    `denial_reason`: the claim moves to `DENIED`, the reserved amount is added back to
    `fund_remaining_cents`, and if the promotion had been `EXHAUSTED` and the release lifts
    its fund above zero, the promotion returns to `ACTIVE`."

    Design: Corner/calculations/rebate_fund_released_on_deny_compensation
    """
    ctx = setup_rebate_claim(
        practice_tier="ELITE", rebate_per_unit_cents=50, fund_total_cents=100000,
        order_quantities=(1, 1),
        submit=True,
    )
    promo_mid = _promo(api, ctx["promotion"]["id"])
    assert promo_mid["fund_remaining_cents"] == 99874, "100000 - 126 reserved at submit"

    denied = validate_success(
        api.deny_rebate_claim(ctx["claim"]["id"], {"denial_reason": "paperwork"}, MANUFACTURER),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied.get("denial_reason") == "paperwork"

    promo = _promo(api, ctx["promotion"]["id"])
    assert promo["fund_remaining_cents"] == 100000, "Reservation fully released"
    assert promo["status"] == "ACTIVE"


def test_claim_submit_when_fund_insufficient(api):
    """PRD §3.4: "the promotion's `fund_remaining_cents` must be at least the
    `claim_amount_cents`, else `ERR_REBATE_FUND_EXHAUSTED`."

    Design: Corner/validations/claim_submit_when_fund_insufficient
    """
    ctx = setup_rebate_claim(
        practice_tier="ELITE", rebate_per_unit_cents=50, fund_total_cents=100,
        order_quantities=(1, 1),
    )
    assert ctx["claim"]["claim_amount_cents"] == 126
    pm = make_practice_manager_headers(ctx["practice"]["id"])
    res = api.submit_rebate_claim(ctx["claim"]["id"], pm)
    validate_error(res, ApiErrorId.ERR_REBATE_FUND_EXHAUSTED)

    promo = _promo(api, ctx["promotion"]["id"])
    assert promo["fund_remaining_cents"] == 100, "Rejected submit must not debit the fund"
    assert promo["status"] == "ACTIVE"
    after = validate_success(api.get_rebate_claim(ctx["claim"]["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_duplicate_claim_rejected(api):
    """PRD §3.4: "no other non-`DENIED` claim may already exist for the same
    order-and-promotion pair, else `ERR_DUPLICATE_CLAIM`."

    Design: Corner/validations/duplicate_claim_rejected
    """
    ctx = setup_rebate_claim()
    pm = make_practice_manager_headers(ctx["practice"]["id"])
    res = api.create_rebate_claim(
        create_rebate_claim_payload(
            ctx["practice"]["id"], ctx["order"]["id"], ctx["promotion"]["id"]
        ),
        pm,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CLAIM)
    data, _meta = validate_paginated(
        api.list_rebate_claims(ADMIN, params={"order_id": ctx["order"]["id"],
                                              "promotion_id": ctx["promotion"]["id"]})
    )
    assert len(data) == 1


def test_claim_with_mismatched_practice_rejected(api):
    """PRD §3.4: "the claim's practice must be the order's practice, else
    `ERR_PRACTICE_MISMATCH`".

    Design: Corner/validations/claim_with_mismatched_practice_rejected
    """
    pa = create_practice(name="PA", credit_limit_cents=1000000)
    pb = create_practice(name="PB", credit_limit_cents=1000000)
    product = create_product(sku="C-19", name="Floss", unit_price_cents=1000)
    promo = validate_success(
        api.create_promotion(create_rebate_promotion_payload([product["id"]]), ADMIN), 201
    )
    pm_a = make_practice_manager_headers(pa["id"])
    order = validate_success(
        api.create_order(
            create_order_payload(pa["id"], [{"product_id": product["id"], "quantity": 1}]), pm_a
        ),
        201,
    )
    validate_success(api.submit_order(order["id"], pm_a), 200)
    validate_success(api.deliver_order(order["id"], ADMIN), 200)

    res = api.create_rebate_claim(
        create_rebate_claim_payload(pb["id"], order["id"], promo["id"]),
        make_practice_manager_headers(pb["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PRACTICE_MISMATCH)


def test_claim_submit_blocked_until_order_delivered(api):
    """PRD §3.4: "the referenced order must be `DELIVERED`, else
    `ERR_ORDER_NOT_DELIVERED`" — a merely SUBMITTED order blocks the claim submit.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_until_order_delivered
    """
    practice = create_practice(name="P Clm", credit_limit_cents=1000000)
    product = create_product(sku="C-3", name="Floss", unit_price_cents=1000)
    promo = validate_success(
        api.create_promotion(create_rebate_promotion_payload([product["id"]]), ADMIN), 201
    )
    pm = make_practice_manager_headers(practice["id"])
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            pm,
        ),
        201,
    )
    validate_success(api.submit_order(order["id"], pm), 200)  # SUBMITTED, never delivered
    claim = validate_success(
        api.create_rebate_claim(
            create_rebate_claim_payload(practice["id"], order["id"], promo["id"]), pm
        ),
        201,
    )

    res = api.submit_rebate_claim(claim["id"], pm)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_DELIVERED)
    after = validate_success(api.get_rebate_claim(claim["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"
    promo_after = _promo(api, promo["id"])
    assert promo_after["fund_remaining_cents"] == 10000, "Rejected submit leaves the fund untouched"


def test_claim_submit_blocked_while_order_draft(api):
    """PRD §3.4: "the referenced order must be `DELIVERED`, else
    `ERR_ORDER_NOT_DELIVERED`" — a still-DRAFT order blocks the claim submit as well.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_until_order_delivered
    """
    practice = create_practice(name="P ClmD", credit_limit_cents=1000000)
    product = create_product(sku="C-3D", name="Floss", unit_price_cents=1000)
    promo = validate_success(
        api.create_promotion(create_rebate_promotion_payload([product["id"]]), ADMIN), 201
    )
    pm = make_practice_manager_headers(practice["id"])
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            pm,
        ),
        201,
    )
    claim = validate_success(
        api.create_rebate_claim(
            create_rebate_claim_payload(practice["id"], order["id"], promo["id"]), pm
        ),
        201,
    )
    res = api.submit_rebate_claim(claim["id"], pm)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_DELIVERED)
    after = validate_success(api.get_rebate_claim(claim["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_manufacturer_agent_cannot_file_claim(api):
    """PRD §2.1: "A request whose role is not permitted on the targeted endpoint, or that
    fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/rebate-claims is authorized for PracticeManager only.

    Design: Corner/rbac/manufacturer_agent_cannot_file_claim
    """
    practice = create_practice(name="P Ma", credit_limit_cents=1000000)
    product = create_product(sku="C-22", name="Floss", unit_price_cents=1000)
    promo = validate_success(
        api.create_promotion(create_rebate_promotion_payload([product["id"]]), ADMIN), 201
    )
    pm = make_practice_manager_headers(practice["id"])
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            pm,
        ),
        201,
    )
    validate_success(api.submit_order(order["id"], pm), 200)
    validate_success(api.deliver_order(order["id"], ADMIN), 200)

    res = api.create_rebate_claim(
        create_rebate_claim_payload(practice["id"], order["id"], promo["id"]), MANUFACTURER
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_practice_manager_cannot_settle_claim(api):
    """PRD §2.1: "A request whose role is not permitted on the targeted endpoint, or that
    fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/rebate-claims/{id}/settle is authorized for ManufacturerAgent only.

    Design: Corner/rbac/practice_manager_cannot_settle_claim
    """
    ctx = setup_rebate_claim(submit=True)
    res = api.settle_rebate_claim(
        ctx["claim"]["id"], make_practice_manager_headers(ctx["practice"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    after = validate_success(api.get_rebate_claim(ctx["claim"]["id"], ADMIN), 200)
    assert after["status"] == "SUBMITTED"
