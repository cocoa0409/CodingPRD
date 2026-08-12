"""Claims: settlement caps, negotiation cycle, filing gates, segregation (PRD 3.9, 2.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_claim,
    file_claim,
    get_order,
    make_claims_adjuster_headers,
    make_van_line_admin_headers,
    set_clock,
    setup_delivered_order,
    setup_delivered_order_with_claim,
    setup_in_transit_order,
    validate_error,
    validate_paginated,
    get_success_data,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


# ---------------------------------------------------------------------------
# Dual variant: released-value vs full-value settlement cap
# ---------------------------------------------------------------------------
def test_released_value_offer_capped_at_sixty_cents_per_pound(api):
    """PRD section 3.9: "Under a `RELEASED_VALUE` coverage the liability cap is
    sixty cents per pound times the claim's `claimed_item_weight_lbs`, regardless
    of any declared value. Under `FULL_VALUE_PROTECTION` the cap is the coverage's
    `declared_value_cents` minus its `deductible_cents`, floored at zero,
    independent of item weight. The maximum lawful offer is the smaller of the
    claimed amount and the liability cap; an offer exactly equal to the maximum is
    allowed, and anything above it is rejected with
    `ERR_OFFER_EXCEEDS_VALUATION_CAP` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/released_vs_full_value_claim_cap
    """
    ctx = setup_delivered_order_with_claim(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600,
        claim_kwargs={"claimed_amount_cents": 250000, "claimed_item_weight_lbs": 200},
    )
    claim = ctx["claim"]
    adjuster = make_claims_adjuster_headers("adj-1")

    # Cap is 60 * 200 = 12000: one cent over is rejected.
    over = api.offer_claim(claim["id"], {"offer_amount_cents": 12001}, adjuster)
    validate_error(over, ApiErrorId.ERR_OFFER_EXCEEDS_VALUATION_CAP)

    at_cap = get_success_data(api.offer_claim(claim["id"], {"offer_amount_cents": 12000}, adjuster))
    assert at_cap["offer_amount_cents"] == 12000, "an offer exactly equal to the cap is allowed"
    assert at_cap["status"] == "OFFER_MADE"


def test_full_value_offer_capped_at_declared_minus_deductible(api):
    """PRD section 3.9: "Under a `FULL_VALUE_PROTECTION` the cap is the coverage's
    `declared_value_cents` minus its `deductible_cents`, floored at zero,
    independent of item weight. The maximum lawful offer is the smaller of the
    claimed amount and the liability cap; an offer exactly equal to the maximum is
    allowed, and anything above it is rejected with
    `ERR_OFFER_EXCEEDS_VALUATION_CAP` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/released_vs_full_value_claim_cap
    """
    ctx = setup_delivered_order_with_claim(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600,
        coverage_type="FULL_VALUE_PROTECTION",
        declared_value_cents=6000000, deductible_cents=25000,
        claim_kwargs={"claimed_amount_cents": 250000, "claimed_item_weight_lbs": 200},
    )
    claim = ctx["claim"]
    assert claim["valuation_coverage_id"] == ctx["coverage"]["id"], (
        "the claim captures the order's LOCKED coverage at filing"
    )
    # FVP cap: min(250000, 6000000 - 25000) = 250000 — the full claim fits.
    offered = get_success_data(
        api.offer_claim(
            claim["id"], {"offer_amount_cents": 250000}, make_claims_adjuster_headers("adj-1")
        )
    )
    assert offered["offer_amount_cents"] == 250000
    assert offered["status"] == "OFFER_MADE"


# ---------------------------------------------------------------------------
# Negotiation cycle OFFER_MADE -> DISPUTED -> OFFER_MADE
# ---------------------------------------------------------------------------
def _setup_negotiation():
    ctx = setup_delivered_order_with_claim(
        pricing_mode="BINDING", mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
        claim_kwargs={"claimed_amount_cents": 250000, "claimed_item_weight_lbs": 200},
    )
    return ctx


def test_claim_negotiation_cycle_reenters_offer_made(api):
    """PRD section 3.9: "Settlement offers are made by a `ClaimsAdjuster` while
    the claim is `FILED` or `DISPUTED` (from any other state,
    `ERR_TRANSITION_NOT_ALLOWED`), via a payload `offer_amount_cents`."
    PRD section 3.9: "a successful rejection increments `round_count` and returns
    the claim to `DISPUTED`, from which the adjuster may offer again under the
    same rules."

    Design: Difficulty/non_linear_state_machine/claim_offer_reject_negotiation_cycle
    """
    ctx = _setup_negotiation()
    claim = ctx["claim"]
    get_success_data(
        api.offer_claim(claim["id"], {"offer_amount_cents": 12000}, make_claims_adjuster_headers("adj-1"))
    )
    disputed = get_success_data(api.reject_claim_offer(claim["id"], ctx["cust_h"]))
    assert disputed["status"] == "DISPUTED"
    assert disputed["round_count"] == 1

    reoffered = get_success_data(
        api.offer_claim(claim["id"], {"offer_amount_cents": 11500}, make_claims_adjuster_headers("adj-2"))
    )
    assert reoffered["status"] == "OFFER_MADE", "the machine re-entered OFFER_MADE from DISPUTED"


def test_claim_second_round_overwrites_offer(api):
    """PRD section 3.9: "A successful offer records `offer_amount_cents` and the
    adjuster's identity in `offered_by_user_id`, and the claim moves to
    `OFFER_MADE` with its `version` bumped."
    PRD section 3.9: "a successful rejection increments `round_count` and returns
    the claim to `DISPUTED`, from which the adjuster may offer again under the
    same rules."

    Design: Difficulty/non_linear_state_machine/claim_offer_reject_negotiation_cycle
    """
    ctx = _setup_negotiation()
    claim = ctx["claim"]
    get_success_data(
        api.offer_claim(claim["id"], {"offer_amount_cents": 12000}, make_claims_adjuster_headers("adj-1"))
    )
    get_success_data(api.reject_claim_offer(claim["id"], ctx["cust_h"]))
    reoffered = get_success_data(
        api.offer_claim(claim["id"], {"offer_amount_cents": 11500}, make_claims_adjuster_headers("adj-2"))
    )
    assert reoffered["round_count"] == 1
    assert reoffered["offer_amount_cents"] == 11500
    assert reoffered["offered_by_user_id"] == "adj-2", "the second round overwrites the first offer"


# ---------------------------------------------------------------------------
# Filing gates
# ---------------------------------------------------------------------------
def test_claim_filing_blocked_before_delivery(api):
    """PRD section 3.9: "A customer files a loss or damage claim once the order is
    `DELIVERED`, `SETTLED`, or `CLOSED` — filing earlier is rejected with
    `ERR_ORDER_NOT_DELIVERED` — and no later than 270 days after the order's
    `delivered_at`, beyond which filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`
    (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/claim_gated_on_order_delivered
    """
    ctx = setup_in_transit_order(pricing_mode="NON_BINDING", actual_weight_lbs=9600)
    resp = api.create_claim(
        ctx["order"]["id"],
        {"description": "Premature claim", "claimed_amount_cents": 50000, "claimed_item_weight_lbs": 100},
        ctx["cust_h"],
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERED)

    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 0, "no half-created claim may survive the rejection"


def test_claim_filing_opens_after_delivery(api):
    """PRD section 3.9: "A customer files a loss or damage claim once the order is
    `DELIVERED`, `SETTLED`, or `CLOSED` — filing earlier is rejected with
    `ERR_ORDER_NOT_DELIVERED` — and no later than 270 days after the order's
    `delivered_at`, beyond which filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`
    (HTTP 422). The payload carries a `description` of the loss, a
    `claimed_amount_cents` of at least 1, and a `claimed_item_weight_lbs` of at
    least 1; at filing the claim captures the order's `LOCKED` valuation coverage
    into `valuation_coverage_id`, stamps `filed_at` from the logical clock, and
    opens in `FILED` with `round_count` at 0 and `offer_amount_cents`,
    `offered_by_user_id`, and `settled_amount_cents` still null."

    Design: Difficulty/cross_entity_state_dependency/claim_gated_on_order_delivered
    """
    ctx = setup_delivered_order(pricing_mode="NON_BINDING", actual_weight_lbs=9600)
    claim = file_claim(ctx, claimed_amount_cents=50000, claimed_item_weight_lbs=100)
    assert_claim(claim)
    assert claim["status"] == "FILED"
    assert claim["round_count"] == 0
    assert claim["valuation_coverage_id"] == ctx["coverage"]["id"]


def test_claim_filing_window_270_days(api):
    """PRD section 3.9: "A customer files a loss or damage claim once the order is
    `DELIVERED`, `SETTLED`, or `CLOSED` — filing earlier is rejected with
    `ERR_ORDER_NOT_DELIVERED` — and no later than 270 days after the order's
    `delivered_at`, beyond which filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`
    (HTTP 422)."

    Design: Corner/validations/claim_filing_window_270_days
    """
    ctx = setup_delivered_order(
        pricing_mode="BINDING", mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
    )
    # delivered_at is 2026-06-10T10:00:00Z; +270 days is 2027-03-07T10:00:00Z.
    set_clock("2027-03-07T10:00:00Z")
    claim = file_claim(ctx, claimed_amount_cents=50000, claimed_item_weight_lbs=100)
    assert claim["status"] == "FILED", "filing at exactly delivered_at + 270 days is in window"

    set_clock("2027-03-08T10:00:00Z")
    resp = api.create_claim(
        ctx["order"]["id"],
        {"description": "out of window", "claimed_amount_cents": 50000, "claimed_item_weight_lbs": 100},
        ctx["cust_h"],
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


# ---------------------------------------------------------------------------
# Negotiation round cap and pay gates
# ---------------------------------------------------------------------------
def test_claim_rounds_exhausted_at_three(api):
    """PRD section 3.9: "Rejecting it requires `round_count` still below the hard
    cap of three negotiation rounds — a rejection at three rounds is rejected with
    `ERR_CLAIM_ROUNDS_EXHAUSTED`, further negotiation is forbidden, and the
    customer must turn to the arbitration program; a successful rejection
    increments `round_count` and returns the claim to `DISPUTED`, from which the
    adjuster may offer again under the same rules."

    Design: Corner/calculations/claim_rounds_exhausted_at_three
    """
    ctx = _setup_negotiation()
    claim = ctx["claim"]
    adjuster = make_claims_adjuster_headers("adj-1")
    for _round in range(3):
        get_success_data(api.offer_claim(claim["id"], {"offer_amount_cents": 12000}, adjuster))
        rejected = get_success_data(api.reject_claim_offer(claim["id"], ctx["cust_h"]))
    assert rejected["round_count"] == 3, "three reject cycles succeed"

    get_success_data(api.offer_claim(claim["id"], {"offer_amount_cents": 12000}, adjuster))
    resp = api.reject_claim_offer(claim["id"], ctx["cust_h"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_ROUNDS_EXHAUSTED)

    after = get_success_data(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "OFFER_MADE", "arbitration is now the only escalation path"
    assert after["round_count"] == 3


def test_claim_pay_from_filed_rejected(api):
    """PRD section 3.9: "Payment of an accepted claim is a `VanLineAdmin` act
    under segregation of duties: the paying operator's `X-User-ID` must differ
    from the claim's `offered_by_user_id`, so the adjuster who made the accepted
    offer can never be the one who pays it — violations are
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); when the acceptance came from
    arbitration, `offered_by_user_id` holds the arbitrator's identifier and the
    same rule keeps that arbitrator from paying. Payment moves the claim from
    `ACCEPTED` to the terminal `PAID` and, as a cascade, closes every dispute
    referencing this claim that is still `OPENED`, `RESPONSE_FILED`,
    `ARBITRATION_DOCKETED`, or `DECIDED`."
    PRD section 2.10: "Lifecycle-state gates — from-state and sub-state
    preconditions on the target resource, endpoint by endpoint (HTTP 409)."

    Design: Corner/state_machines/claim_pay_from_filed_rejected
    """
    ctx = _setup_negotiation()
    claim = ctx["claim"]
    assert claim["status"] == "FILED"

    resp = api.pay_claim(claim["id"], make_van_line_admin_headers("vl-admin-1"))
    validate_error(resp, ApiErrorId.ERR_TRANSITION_NOT_ALLOWED)

    after = get_success_data(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "FILED", "FILED is not payable"
    assert after["settled_amount_cents"] is None


def test_segregation_of_duties_claim_pay(api):
    """PRD section 3.9: "Payment of an accepted claim is a `VanLineAdmin` act
    under segregation of duties: the paying operator's `X-User-ID` must differ
    from the claim's `offered_by_user_id`, so the adjuster who made the accepted
    offer can never be the one who pays it — violations are
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); when the acceptance came from
    arbitration, `offered_by_user_id` holds the arbitrator's identifier and the
    same rule keeps that arbitrator from paying. Payment moves the claim from
    `ACCEPTED` to the terminal `PAID` and, as a cascade, closes every dispute
    referencing this claim that is still `OPENED`, `RESPONSE_FILED`,
    `ARBITRATION_DOCKETED`, or `DECIDED`."
    PRD section 3.9: "Accepting the offer sets `settled_amount_cents` to the
    current `offer_amount_cents`, moves the claim to `ACCEPTED`, and fires two
    cascades: the order's revenue statement adds the settled amount to its
    `chargeback_total_cents` (statement `version` bumped), and the `HAULING`
    agent's `quality_score` is recomputed per §2.9 from the new chargeback total
    (agent `version` bumped)."

    Design: Corner/rbac/segregation_of_duties_claim_pay
    """
    ctx = _setup_negotiation()
    claim = ctx["claim"]
    get_success_data(
        api.offer_claim(claim["id"], {"offer_amount_cents": 12000}, make_claims_adjuster_headers("adj-1"))
    )
    accepted = get_success_data(api.accept_claim(claim["id"], ctx["cust_h"]))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["settled_amount_cents"] == 12000

    # The payer's id equals offered_by_user_id -> refused.
    resp = api.pay_claim(claim["id"], make_van_line_admin_headers("adj-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    paid = get_success_data(api.pay_claim(claim["id"], make_van_line_admin_headers("vl-admin-2")))
    assert paid["status"] == "PAID"

    statement = get_success_data(api.get_revenue_statement(ctx["statement"]["id"], ADMIN))
    assert statement["chargeback_total_cents"] == 12000, (
        "the chargeback posted at accept and is unchanged by the pay retry"
    )
