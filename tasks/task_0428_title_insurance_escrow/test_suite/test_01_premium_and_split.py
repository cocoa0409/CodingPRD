"""Premium calculation, the agency/underwriter split, endorsement charge, and claim reserve.

Covers queue A: dual_variant_calc, combinatorial_formula, boundary_precision (owner tier),
plus queue B computed-field corners under sections entities / calculations.
"""
from test_helpers import (
    validate_success,
    setup_order_with_issued_commitment,
    setup_issued_owner_policy,
    create_pending_policy,
    issue_policy,
    get_policy_remittance,
    add_curative_action,
    file_claim,
    assert_premium_split_conserves,
    UW,
)


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc
# ---------------------------------------------------------------------------
def test_owner_premium_standard_rate(api):
    """PRD §3.6: "For a standard owner policy (`is_reissue` false) that un-rounded base
    in cents is rounded half-up to whole cents to give `gross_premium_cents`."
    Owner coverage $250,000: first $100k at $5/1000 ($500) + next $150k at $4/1000 ($600)
    = $1,100 base = 110000 cents.

    Design: Difficulty/dual_variant_calc/owner_premium_standard_vs_reissue
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=25_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000, is_reissue=False)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 110000, (
        f"Expected standard owner premium 110000, got {data['gross_premium_cents']}"
    )


def test_owner_premium_reissue_rate_differs_from_standard(api):
    """PRD §3.6: "For a reissue owner policy (`is_reissue` true), the un-rounded base in
    cents is first multiplied by the reissue factor of 0.60 and only then rounded half-up
    to whole cents — the factor is applied to the un-rounded base and the rounding happens
    exactly once, which yields a strictly lower premium than the standard rate for
    identical coverage."
    Owner coverage $250,000 base 110000 * 0.60 = 66000.

    Design: Difficulty/dual_variant_calc/owner_premium_standard_vs_reissue
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=25_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000, is_reissue=True)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 66000, (
        f"Expected reissue owner premium 66000, got {data['gross_premium_cents']}"
    )
    assert data["gross_premium_cents"] != 110000, "reissue must be strictly lower than standard 110000"


def test_claim_reserve_provisional_is_loaded_estimate(api):
    """PRD §3.9: "`reserve_cents` is the `estimated_loss_cents` multiplied by the
    loss-loading factor of 1.15 (covering defense and curative cost), rounded half-up to
    whole cents and then capped so that it never exceeds the parent policy's
    `coverage_amount_cents`."
    estimated_loss 80000 * 1.15 = 92000 (well under coverage 25,000,000).

    Design: Difficulty/dual_variant_calc/claim_reserve_provisional_vs_final_payout
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy(coverage_amount_cents=25_000_000)
    claim = file_claim(policy, claim_type="UNDISCLOSED_LIEN", estimated_loss_cents=80_000)
    data = validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    assert data["reserve_cents"] == 92000, (
        f"Expected provisional reserve 92000, got {data['reserve_cents']}"
    )


def test_claim_final_payout_uses_settled_loss_and_releases_reserve(api):
    """PRD §3.9: "On payment, `paid_cents` is set to the lesser of the supplied
    `settled_loss_cents` and the parent policy's `coverage_amount_cents` — the actual
    settled loss with no loading factor, capped at coverage — and `reserve_cents` is
    released to 0."
    Same claim that reserved 92000 provisionally now pays the unloaded settled 70000.

    Design: Difficulty/dual_variant_calc/claim_reserve_provisional_vs_final_payout
    """
    _agency, order, _commitment, policy = setup_issued_owner_policy(coverage_amount_cents=25_000_000)
    claim = file_claim(policy, claim_type="UNDISCLOSED_LIEN", estimated_loss_cents=80_000)
    invest = validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    assert invest["reserve_cents"] == 92000, "provisional reserve should be 92000 before settlement"
    validate_success(api.transition_claim(claim["id"], {"to_status": "CURATIVE"}, UW))
    add_curative_action(order, "CLAIM", claim["id"], action_type="PAYOFF", resolve=True)
    data = validate_success(
        api.transition_claim(claim["id"], {"to_status": "PAID", "settled_loss_cents": 70_000}, UW)
    )
    assert data["paid_cents"] == 70000, f"Expected paid_cents 70000, got {data['paid_cents']}"
    assert data["reserve_cents"] == 0, "reserve must be released to 0 on PAID"


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula
# ---------------------------------------------------------------------------
def test_owner_premium_spans_all_three_tiers(api):
    """PRD §3.6: "The first 100,000 dollars of coverage are priced at 5.00 dollars per
    1,000 dollars; the portion of coverage above 100,000 dollars and up to 500,000 dollars
    is priced at 4.00 dollars per 1,000 dollars; and any coverage above 500,000 dollars is
    priced at 3.00 dollars per 1,000 dollars."
    Coverage $600,000: 500 + 1600 + 300 = $2400 base = 240000 cents.

    Design: Difficulty/combinatorial_formula/owner_premium_tiered_three_inputs_mode_a
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=60_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=60_000_000, is_reissue=False)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 240000, (
        f"Expected three-tier owner premium 240000, got {data['gross_premium_cents']}"
    )


def test_premium_split_rounds_agency_share_first(api):
    """PRD §3.8: "The agency's share, `agency_retained_cents`, is the snapshotted
    `gross_premium_cents` multiplied by the owning agency's `remit_split_pct`, rounded
    half-up to whole cents. The underwriter's share, `underwriter_remit_cents`, is then
    the gross minus the agency-retained amount."
    gross 110000 * 0.82 = 90200 retained; 110000 - 90200 = 19800 remit.

    Design: Difficulty/combinatorial_formula/premium_split_rounding_order_mode_b
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy(
        coverage_amount_cents=25_000_000, remit_split_pct=0.82
    )
    remittance = get_policy_remittance(policy)
    assert remittance["agency_retained_cents"] == 90200, (
        f"Expected agency_retained_cents 90200, got {remittance['agency_retained_cents']}"
    )
    assert remittance["underwriter_remit_cents"] == 19800, (
        f"Expected underwriter_remit_cents 19800, got {remittance['underwriter_remit_cents']}"
    )


def test_premium_split_conserves_gross(api):
    """PRD §3.8: "Rounding the agency share first and deriving the underwriter share by
    subtraction is deliberate and is part of the contract: it guarantees that
    `agency_retained_cents` plus `underwriter_remit_cents` equals the gross with zero
    drift, which independently rounding both halves would not."

    Design: Difficulty/combinatorial_formula/premium_split_rounding_order_mode_b
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy(
        coverage_amount_cents=25_000_000, remit_split_pct=0.82
    )
    remittance = get_policy_remittance(policy)
    assert remittance["gross_premium_cents"] == 110000, "remittance snapshots gross 110000"
    assert_premium_split_conserves(remittance)


# ---------------------------------------------------------------------------
# Queue A — boundary_precision (owner tier crossing at $500,000)
# ---------------------------------------------------------------------------
def test_owner_premium_at_tier2_ceiling_boundary(api):
    """PRD §3.6: "the portion of coverage above 100,000 dollars and up to 500,000 dollars
    is priced at 4.00 dollars per 1,000 dollars; and any coverage above 500,000 dollars is
    priced at 3.00 dollars per 1,000 dollars."
    At exactly $500,000 the 500,000th dollar is tier-2: 500 + 1600 = $2100 = 210000 cents
    (no tier-3 contribution).

    Design: Difficulty/boundary_precision_check/owner_premium_tier_boundary_at_500000
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=50_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=50_000_000, is_reissue=False)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 210000, (
        f"Expected $500k boundary premium 210000, got {data['gross_premium_cents']}"
    )


def test_owner_premium_just_above_tier2_ceiling_uses_tier3(api):
    """PRD §3.6: "the portion of coverage above 100,000 dollars and up to 500,000 dollars
    is priced at 4.00 dollars per 1,000 dollars; and any coverage above 500,000 dollars is
    priced at 3.00 dollars per 1,000 dollars."
    At $501,000 (just past the boundary) the extra $1,000 is tier-3 ($3): 210000 + 300 =
    210300 cents, confirming tier-3 only applies strictly above $500,000.

    Design: Difficulty/boundary_precision_check/owner_premium_tier_boundary_at_500000
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=50_100_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=50_100_000, is_reissue=False)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 210300, (
        f"Expected $501k premium 210300, got {data['gross_premium_cents']}"
    )


def test_owner_premium_two_tier_split_at_250k(api):
    """PRD §3.6: "The first 100,000 dollars of coverage are priced at 5.00 dollars per
    1,000 dollars; the portion of coverage above 100,000 dollars and up to 500,000 dollars
    is priced at 4.00 dollars per 1,000 dollars".
    Coverage $250,000 lands in tiers 1 and 2 only: 500 + 600 = $1100 = 110000 cents,
    confirming the tiered selection across a different coverage than the three-tier case.

    Design: Difficulty/combinatorial_formula/owner_premium_tiered_three_inputs_mode_a
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=25_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000, is_reissue=False)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 110000, (
        f"Expected two-tier owner premium 110000, got {data['gross_premium_cents']}"
    )


# ---------------------------------------------------------------------------
# Queue B — entities / calculations computed-field corners
# ---------------------------------------------------------------------------
def test_owner_premium_first_tier_only_computed_on_issue(api):
    """PRD §3.6: "the premium itself is not client-supplied: `gross_premium_cents` is
    computed at issuance and any input value for it is ignored."
    Owner coverage $100,000 -> $5/1000 over $100k = $500 = 50000 cents.

    Design: Corner/entities/policy_gross_premium_is_computed_input_ignored
    """
    _agency, order, commitment = setup_order_with_issued_commitment(insured_amount_cents=10_000_000)
    policy = create_pending_policy(order, commitment, coverage_amount_cents=10_000_000)
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 50000, (
        f"Expected owner premium 50000, got {data['gross_premium_cents']}"
    )


def test_standalone_lender_premium_uses_tiered_base(api):
    """PRD §3.6: "For a standalone lender policy (`co_issued_with_owner` false) that
    tiered base in cents is rounded half-up to whole cents to give `gross_premium_cents`."
    Lender coverage $200,000: 500 + 400 = $900 = 90000 cents.

    Design: Corner/entities/lender_premium_standalone_computed
    """
    _agency, order, commitment = setup_order_with_issued_commitment(
        insured_amount_cents=20_000_000, transaction_type="REFINANCE", sales_price_cents=0, loan_amount_cents=20_000_000
    )
    policy = create_pending_policy(
        order, commitment, policy_type="LENDER", coverage_amount_cents=20_000_000, co_issued_with_owner=False
    )
    data = validate_success(api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 90000, (
        f"Expected standalone lender premium 90000, got {data['gross_premium_cents']}"
    )


def test_co_issued_lender_premium_is_flat(api):
    """PRD §3.6: "For a co-issued lender policy (`co_issued_with_owner` true), the premium
    is instead a flat 2,500 cents regardless of the tiered base; the owner policy is priced
    first and the lender policy is then written at this flat co-issue rate."

    Design: Corner/entities/lender_premium_co-issue_flat_rate
    """
    _agency, order, commitment = setup_order_with_issued_commitment(
        insured_amount_cents=20_000_000, sales_price_cents=20_000_000, loan_amount_cents=20_000_000
    )
    owner = create_pending_policy(order, commitment, policy_type="OWNER", coverage_amount_cents=20_000_000)
    issue_policy(owner)
    lender = create_pending_policy(
        order, commitment, policy_type="LENDER", coverage_amount_cents=20_000_000, co_issued_with_owner=True
    )
    data = validate_success(api.transition_policy(lender["id"], {"to_status": "ISSUED"}, UW))
    assert data["gross_premium_cents"] == 2500, (
        f"Expected co-issue flat lender premium 2500, got {data['gross_premium_cents']}"
    )


def test_claim_reserve_loading_factor_under_coverage(api):
    """PRD §3.9: "`reserve_cents` is the `estimated_loss_cents` multiplied by the
    loss-loading factor of 1.15 (covering defense and curative cost), rounded half-up to
    whole cents and then capped so that it never exceeds the parent policy's
    `coverage_amount_cents`."
    estimated_loss 200000 * 1.15 = 230000, under coverage 10,000,000 -> no cap.

    Design: Corner/entities/claim_reserve_capped_at_coverage
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy(coverage_amount_cents=10_000_000)
    claim = file_claim(policy, claim_type="FORGERY", estimated_loss_cents=200_000)
    data = validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    assert data["reserve_cents"] == 230000, (
        f"Expected reserve 230000, got {data['reserve_cents']}"
    )


def test_endorsement_charge_computed_on_attach(api):
    """PRD §3.6: "on attachment the system computes `charge_cents` as the policy's
    `gross_premium_cents` multiplied by `charge_pct`, rounded half-up to whole cents."
    gross 110000 * 0.10 = 11000.

    Design: Corner/calculations/endorsement_charge_computed_on_attach
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy(coverage_amount_cents=25_000_000)
    endorsement = validate_success(
        api.create_endorsement(policy["id"], {"form_code": "ZONING", "charge_pct": 0.10}, UW),
        expected_status=201,
    )
    data = validate_success(api.transition_endorsement(endorsement["id"], {"to_status": "ATTACHED"}, UW))
    assert data["charge_cents"] == 11000, f"Expected charge_cents 11000, got {data['charge_cents']}"
    assert data["status"] == "ATTACHED"
