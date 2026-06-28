"""Pricing engine: savings, copay-offset waterfall, best-price selection,
gold-fee resolution, coupon credentials, mail-order totals, insurance choice.

Every test creates its own entities from scratch (DB is reset per test).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success,
    make_member_headers, TEST_USERS,
    create_gold_membership_payload, create_discount_card_payload,
    create_claim_payload, create_copay_card_payload, create_copay_link_payload,
    create_member_payload, create_comparison_payload, create_pharmacy_payload,
    create_price_quote_payload, create_insurance_estimate_payload,
    setup_resolved_comparison, setup_discount_card, setup_submitted_claim,
    setup_submitted_claim_with_copay_link, create_active_gold_member,
    create_member, create_drug, create_pharmacy, create_quote, set_clock,
    assert_claim, assert_discount_card, assert_insurance_estimate,
    assert_gold_membership,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
OPERATOR = TEST_USERS["pharmacy_operator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Rule 1 / dual_variant_calc — savings_discount_vs_gold_basis_on_claim
# ─────────────────────────────────────────────────────────────────────────────

def test_discount_basis_claim_savings_and_net(api):
    """PRD §3.7: "the discounted amount is the quantity multiplied by the basis
    price, plus the dispense fee; net_cents is that discounted amount minus the
    claim's copay_offset_cents (computed by the copay-offset rule below, and 0
    when no copay link applies); net_cents is then floored at zero so it can never
    go negative; and savings_cents is gross_cents minus net_cents."

    With quantity=2, cash=7000, discount=5500, dispense=200:
    gross = 2*7000+200 = 14200; net = 2*5500+200 = 11200; savings = 3000.

    Design: Difficulty/dual_variant_calc/savings_discount_vs_gold_basis_on_claim
    """
    ctx = setup_submitted_claim(quantity=2)  # standard (non-gold) member -> DISCOUNT basis
    assert ctx["card"]["pricing_basis"] == "DISCOUNT"
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert_claim(claim)
    assert claim["status"] == "ADJUDICATED"
    assert claim["net_cents"] == 11200, f"expected net 11200, got {claim['net_cents']}"
    assert claim["savings_cents"] == 3000, f"expected savings 3000, got {claim['savings_cents']}"


def test_gold_basis_claim_savings_and_net(api):
    """PRD §3.7: "The basis price is the quote's gold_price_cents when the card's
    pricing_basis is GOLD, and the quote's discount_price_cents otherwise." and
    "A GOLD-basis card and a DISCOUNT-basis card over identical quantity and quote
    inputs therefore yield different net_cents and savings_cents, because the
    discounted amount draws on a different price tier."

    With quantity=2, cash=7000, gold=5200, dispense=200:
    gross = 14200; net = 2*5200+200 = 10600; savings = 3600.

    Design: Difficulty/dual_variant_calc/savings_discount_vs_gold_basis_on_claim
    """
    member, _ = create_active_gold_member(member_overrides={"email": "gold@x.com"})
    ctx = setup_submitted_claim(quantity=2, member=member)
    assert ctx["card"]["pricing_basis"] == "GOLD"
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["net_cents"] == 10600, f"expected net 10600, got {claim['net_cents']}"
    assert claim["savings_cents"] == 3600, f"expected savings 3600, got {claim['savings_cents']}"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 1 / dual_variant_calc — insurance_vs_discount_recommendation_on_estimate
# ─────────────────────────────────────────────────────────────────────────────

def test_insurance_recommendation_when_insurance_strictly_cheaper(api):
    """PRD §3.4: "if the discount net is strictly greater than the insurance net,
    the recommendation is INSURANCE". The insurance out-of-pocket is "the sum of
    the member's copay_cents plus the lesser of their deductible_remaining_cents
    and the single-fill AWP".

    best=5500; insurance = 1000 + min(2000, 10000) = 3000 < 5500 -> INSURANCE.

    Design: Difficulty/dual_variant_calc/insurance_vs_discount_recommendation_on_estimate
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "ins@x.com",
                                                      "has_insurance": True})
    assert ctx["comparison"]["best_price_cents"] == 5500
    headers = make_member_headers(ctx["member"]["id"])
    est = validate_success(api.create_insurance_estimate(
        ctx["comparison"]["id"],
        create_insurance_estimate_payload(ctx["member"]["id"], copay_cents=1000,
                                          deductible_remaining_cents=2000),
        headers), 201)
    assert_insurance_estimate(est)
    assert est["recommended_path"] == "INSURANCE"


def test_discount_recommendation_when_discount_strictly_cheaper(api):
    """PRD §3.4: "if the discount net is strictly less than the insurance net,
    the recommendation is DISCOUNT". The discount net cost is "the comparison's
    best_price_cents (a single-fill basis)."

    best=5500; insurance = 5000 + min(5000, 10000) = 10000 > 5500 -> DISCOUNT.

    Design: Difficulty/dual_variant_calc/insurance_vs_discount_recommendation_on_estimate
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "ins2@x.com",
                                                      "has_insurance": True})
    assert ctx["comparison"]["best_price_cents"] == 5500
    headers = make_member_headers(ctx["member"]["id"])
    est = validate_success(api.create_insurance_estimate(
        ctx["comparison"]["id"],
        create_insurance_estimate_payload(ctx["member"]["id"], copay_cents=5000,
                                          deductible_remaining_cents=5000),
        headers), 201)
    assert est["recommended_path"] == "DISCOUNT"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2 / combinatorial_formula — copay_offset_waterfall_min_of_three_caps
# ─────────────────────────────────────────────────────────────────────────────

def test_copay_offset_capped_by_per_fill(api):
    """PRD §3.8: "The applied offset is the smallest of these three caps." and
    "If the per-fill cap is the binding minimum, the offset equals
    per_fill_cap_cents and the benefit is reduced by that amount".

    caps = min(per_fill 4000, remaining 50000, discounted 11200) = 4000.
    net = 11200 - 4000 = 7200; savings = 14200 - 7200 = 7000; remaining = 46000.

    Design: Difficulty/combinatorial_formula/copay_offset_waterfall_min_of_three_caps
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=50000, per_fill_cap_cents=4000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["copay_offset_cents"] == 4000
    assert claim["net_cents"] == 7200
    assert claim["savings_cents"] == 7000
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 46000


def test_copay_offset_capped_by_remaining_benefit(api):
    """PRD §3.8: "if the remaining benefit is the binding minimum, the offset
    equals remaining_benefit_cents, which drives the balance to zero." and
    "Whenever the draw brings remaining_benefit_cents to zero, the copay card
    itself transitions from ACTIVE to EXHAUSTED as a further transitive hop."

    caps = min(per_fill 8000, remaining 3000, discounted 11200) = 3000.
    net = 11200 - 3000 = 8200; savings = 6000; remaining = 0; card EXHAUSTED.

    Design: Difficulty/combinatorial_formula/copay_offset_waterfall_min_of_three_caps
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=3000, per_fill_cap_cents=8000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["copay_offset_cents"] == 3000
    assert claim["net_cents"] == 8200
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 0
    assert cc["status"] == "EXHAUSTED"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2 / combinatorial_formula — savings_net_pinned_eval_order_offset_before_floor
# ─────────────────────────────────────────────────────────────────────────────

def test_net_floored_at_zero_after_offset_subtraction(api):
    """PRD §3.7: "net_cents is that discounted amount minus the claim's
    copay_offset_cents ... net_cents is then floored at zero so it can never go
    negative; and savings_cents is gross_cents minus net_cents."

    discounted=11200, remaining-benefit 3000 binds -> offset 3000;
    net = 11200 - 3000 = 8200 (positive, no floor needed); savings = 6000.

    Design: Difficulty/combinatorial_formula/savings_net_pinned_eval_order_offset_before_floor
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=3000, per_fill_cap_cents=8000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["copay_offset_cents"] == 3000
    assert claim["net_cents"] == 8200
    assert claim["savings_cents"] == 6000
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 0
    assert cc["status"] == "EXHAUSTED"


def test_offset_capped_by_discounted_owed_never_negative_net(api):
    """PRD §3.8: "the owed cap is the discounted amount, since the offset can
    never exceed what is owed." PRD §3.7: "net_cents is then floored at zero so
    it can never go negative".

    discounted=11200; remaining 11200 == discounted, per_fill 20000 -> offset
    11200; net = 0 (floored, exact); savings = gross 14200 - 0 = 14200.

    Design: Difficulty/combinatorial_formula/savings_net_pinned_eval_order_offset_before_floor
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=11200, per_fill_cap_cents=20000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["copay_offset_cents"] == 11200
    assert claim["net_cents"] == 0
    assert claim["savings_cents"] == 14200


# ─────────────────────────────────────────────────────────────────────────────
# Rule 6 / boundary_precision_check — copay_remaining_exactly_equals_discounted
# ─────────────────────────────────────────────────────────────────────────────

def test_copay_remaining_exactly_equals_discounted_offset_boundary(api):
    """PRD §3.8: "The applied offset is the smallest of these three caps." with
    remaining == owed; PRD §3.7: "net_cents is then floored at zero". PRD §3.8:
    "Whenever the draw brings remaining_benefit_cents to zero, the copay card
    itself transitions from ACTIVE to EXHAUSTED".

    remaining 11200 == discounted 11200; offset 11200; net 0; remaining 0; EXHAUSTED.

    Design: Difficulty/boundary_precision_check/copay_remaining_exactly_equals_discounted_offset_boundary
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=11200, per_fill_cap_cents=20000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["copay_offset_cents"] == 11200
    assert claim["net_cents"] == 0
    assert claim["savings_cents"] == 14200
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 0
    assert cc["status"] == "EXHAUSTED"


def test_copay_offset_one_below_owed_leaves_positive_net(api):
    """PRD §3.8: "the owed cap is the discounted amount" and "The applied offset
    is the smallest of these three caps." PRD §3.7: net = discounted - offset.

    Boundary X-1: remaining 11199 < discounted 11200 -> offset 11199; net = 1.

    Design: Difficulty/boundary_precision_check/copay_remaining_exactly_equals_discounted_offset_boundary
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=11199, per_fill_cap_cents=20000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["copay_offset_cents"] == 11199
    assert claim["net_cents"] == 1
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 0
    assert cc["status"] == "EXHAUSTED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations — best_price_selection_picks_lowest_discount_price
# ─────────────────────────────────────────────────────────────────────────────

def test_best_price_selection_picks_lowest_discount_price(api):
    """PRD §3.3: "The selector sorts the pool ascending by effective price ...
    The winner is the first quote after this ordering: its pharmacy becomes the
    comparison's selected_pharmacy_id, and the winner's effective price becomes
    best_price_cents." For a standard member effective price is discount_price_cents.

    Two CA quotes (discount 6000 vs 5500): winner 5500; candidate_count 2.

    Design: Corner/calculations/best_price_selection_picks_lowest_discount_price
    """
    set_clock()
    drug = create_drug()
    ph1 = create_pharmacy(name="PH1", chain_code="CVS", dispense_fee_cents=300)
    ph2 = create_pharmacy(name="PH2", chain_code="RITE", dispense_fee_cents=200)
    create_quote(drug["id"], ph1["id"], cash_price_cents=8000,
                 discount_price_cents=6000, gold_price_cents=5000)
    create_quote(drug["id"], ph2["id"], cash_price_cents=7000,
                 discount_price_cents=5500, gold_price_cents=5200)
    member = create_member(email="bp@x.com")
    headers = make_member_headers(member["id"])
    cmp = get_success_data(api.create_comparison(
        create_comparison_payload(member["id"], drug["id"]), headers))
    cmp = validate_success(api.run_comparison(cmp["id"], {"member_id": member["id"]},
                                              headers), 200)
    assert cmp["best_price_cents"] == 5500
    assert cmp["candidate_count"] == 2
    assert cmp["selected_pharmacy_id"] == ph2["id"]


def test_best_price_gold_basis_changes_winner(api):
    """PRD §3.3: "The effective price used to rank each candidate depends on
    whether the searching member has Gold access ... For a Gold member the
    effective price of a quote is its gold_price_cents". "Because a Gold member
    ranks on gold_price_cents rather than discount_price_cents, the same pool can
    yield a different winning pharmacy and a lower best_price_cents".

    Gold eff prices PH1 5000 vs PH2 5200 -> winner flips to PH1; best=5000.

    Design: Corner/calculations/best_price_gold_basis_changes_winner
    """
    set_clock()
    drug = create_drug()
    ph1 = create_pharmacy(name="PH1", chain_code="CVS", dispense_fee_cents=300)
    ph2 = create_pharmacy(name="PH2", chain_code="RITE", dispense_fee_cents=200)
    create_quote(drug["id"], ph1["id"], cash_price_cents=8000,
                 discount_price_cents=6000, gold_price_cents=5000)
    create_quote(drug["id"], ph2["id"], cash_price_cents=7000,
                 discount_price_cents=5500, gold_price_cents=5200)
    member, _ = create_active_gold_member(member_overrides={"email": "bpg@x.com"})
    headers = make_member_headers(member["id"])
    cmp = get_success_data(api.create_comparison(
        create_comparison_payload(member["id"], drug["id"]), headers))
    cmp = validate_success(api.run_comparison(cmp["id"], {"member_id": member["id"]},
                                              headers), 200)
    assert cmp["best_price_cents"] == 5000
    assert cmp["selected_pharmacy_id"] == ph1["id"]


def test_expired_quote_excluded_from_candidate_pool(api):
    """PRD §3.3: "The candidate pool for a run consists of every PriceQuote whose
    drug_id equals the comparison's drug, whose status is PUBLISHED, whose
    half-open validity window contains the current logical clock ... and whose
    pharmacy is ACTIVE and located in a state_code equal to the comparison's
    state_code."

    Cheaper quote (5000) expired before run -> candidate_count 1; best=5500.

    Design: Corner/calculations/expired_quote_excluded_from_candidate_pool
    """
    set_clock()
    drug = create_drug()
    ph1 = create_pharmacy(name="PH1", chain_code="CVS", dispense_fee_cents=300)
    ph2 = create_pharmacy(name="PH2", chain_code="RITE", dispense_fee_cents=200)
    q1 = create_quote(drug["id"], ph1["id"], cash_price_cents=8000,
                      discount_price_cents=5000, gold_price_cents=4500)
    create_quote(drug["id"], ph2["id"], cash_price_cents=7000,
                 discount_price_cents=5500, gold_price_cents=5200)
    get_success_data(api.expire_price_quote(q1["id"], ADMIN))
    member = create_member(email="ex@x.com")
    headers = make_member_headers(member["id"])
    cmp = get_success_data(api.create_comparison(
        create_comparison_payload(member["id"], drug["id"]), headers))
    cmp = validate_success(api.run_comparison(cmp["id"], {"member_id": member["id"]},
                                              headers), 200)
    assert cmp["candidate_count"] == 1
    assert cmp["best_price_cents"] == 5500
    assert cmp["selected_pharmacy_id"] == ph2["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations — gold_fee_resolution_individual_constant
# ─────────────────────────────────────────────────────────────────────────────

def test_gold_fee_resolution_individual_constant(api):
    """PRD §3.5: "The monthly_fee_cents is never taken from the request body; it
    is derived from the tier at creation. A GOLD_INDIVIDUAL membership is assigned
    a monthly fee of 999 cents". "A newly created membership starts at
    PENDING_PAYMENT for billing and INACTIVE for access."

    Design: Corner/calculations/gold_fee_resolution_individual_constant
    """
    member = create_member(email="fee@x.com")
    headers = make_member_headers(member["id"])
    gm = validate_success(api.create_gold_membership(
        create_gold_membership_payload(member["id"], tier="GOLD_INDIVIDUAL"),
        headers), 201)
    assert_gold_membership(gm)
    assert gm["monthly_fee_cents"] == 999
    assert gm["billing_status"] == "PENDING_PAYMENT"
    assert gm["access_status"] == "INACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations — coupon_credential_assignment_standard_basis
# ─────────────────────────────────────────────────────────────────────────────

def test_coupon_credential_assignment_standard_basis(api):
    """PRD §3.6: "The bin Bank Identification Number is always the fixed network
    value "610279"." and "a DISCOUNT-basis card receives a pcn of "STD" and a
    group_code of "DISCRX"." and "The card's pricing_basis ... is GOLD when the
    member's active_gold_membership_id is not null at issuance and DISCOUNT
    otherwise."

    Design: Corner/calculations/coupon_credential_assignment_standard_basis
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "cr@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    card = validate_success(api.create_discount_card(
        create_discount_card_payload(ctx["member"]["id"], ctx["comparison"]["id"]),
        headers), 201)
    assert_discount_card(card)
    assert card["bin"] == "610279"
    assert card["pcn"] == "STD"
    assert card["group_code"] == "DISCRX"
    assert card["pricing_basis"] == "DISCOUNT"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations — mail_order_total_discount_basis_correct
# ─────────────────────────────────────────────────────────────────────────────

def test_mail_order_total_discount_basis_correct(api):
    """PRD §3.10: "The total_cents is the quantity multiplied by the basis price,
    plus the pharmacy's dispense_fee_cents." The basis price for a DISCOUNT card
    is "its discount_price_cents".

    qty=2, discount=5500, dispense=150 -> total = 2*5500 + 150 = 11150.

    Design: Corner/calculations/mail_order_total_discount_basis_correct
    """
    ctx = setup_discount_card(pharmacy_overrides={
        "name": "PHM", "chain_code": "MAIL", "state_code": "CA",
        "dispense_fee_cents": 150, "is_mail_order": True})
    headers = make_member_headers(ctx["member"]["id"])
    from test_helpers import create_mail_order_payload
    mo = validate_success(api.create_mail_order(
        create_mail_order_payload(ctx["card"]["id"], ctx["pharmacy"]["id"],
                                  ctx["member"]["id"], quantity=2, ship_to_state="CA"),
        headers), 201)
    assert mo["total_cents"] == 11150


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations — insurance_choice_tie_resolves_to_discount
# ─────────────────────────────────────────────────────────────────────────────

def test_insurance_choice_tie_resolves_to_discount(api):
    """PRD §3.4: "if the two are exactly equal, the recommendation is TIE_DISCOUNT
    — ties resolve in favor of the discount path."

    insurance = 500 + min(5000, 10000) = 5500 == discount best 5500 -> TIE_DISCOUNT.

    Design: Corner/calculations/insurance_choice_tie_resolves_to_discount
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "tie@x.com",
                                                      "has_insurance": True})
    assert ctx["comparison"]["best_price_cents"] == 5500
    headers = make_member_headers(ctx["member"]["id"])
    est = validate_success(api.create_insurance_estimate(
        ctx["comparison"]["id"],
        create_insurance_estimate_payload(ctx["member"]["id"], copay_cents=500,
                                          deductible_remaining_cents=5000),
        headers), 201)
    assert est["recommended_path"] == "TIE_DISCOUNT"
