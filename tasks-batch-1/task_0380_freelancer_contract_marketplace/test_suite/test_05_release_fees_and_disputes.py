"""Money movement: standard vs split release, the tiered+surcharge+clamp platform fee,
dispute resolution cascades, contract-termination cascades, and the escrow/wallet
conservation invariants.

Queue A: dual_variant_calc / dual_variant_milestone_release_standard_vs_split;
         combinatorial_formula / combinatorial_platform_fee_tier_plus_surcharge_clamp;
         transitive_cascade / cascade_dispute_clientfavor_depth3;
         transitive_cascade / cascade_contract_terminate_depth2;
         compensating_invariant / invariant_escrow_conservation_on_split_release;
         compensating_invariant / invariant_wallet_conservation_fund_then_terminate.
Queue B: platform_fee_min_fee_floor_applied; platform_fee_tier_b_after_lifetime_threshold;
         dispute_withdraw_returns_milestone_to_submitted; award_out_of_range_rejected.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_milestone_payload, fund_payload, release_payload, dispute_payload,
    resolve_payload, withdraw_dispute_payload,
    assert_escrow_conserved,
    make_client_headers, make_freelancer_headers, make_arbitrator_headers, make_admin_headers,
    create_client, create_freelancer,
    create_active_contract, add_milestone, fund_milestone,
    setup_approved_milestone, setup_released_milestone, milestone_payout,
    setup_submitted_milestone, setup_disputed_milestone, setup_dispute_under_arbitration,
    resolve_dispute,
)


# ─── Dual variant: standard full release vs split arbitration award ───
def test_standard_release_full_gross(api):
    """PRD §3.5: "a RELEASE EscrowTransaction is written for the full funded_cents in
    SETTLED status and the milestone's released_gross_cents is set to that full funded
    amount ... a Payout is created with gross_cents equal to the released gross".

    A standard approve->release of a 100000-cent escrow yields released_gross_cents=100000.

    Design: Difficulty/dual_variant_calc/dual_variant_milestone_release_standard_vs_split
    """
    ctx, m = setup_released_milestone(amount_cents=100000, budget_cents=300000,
                                      deposit_cents=500000)
    assert m["released_gross_cents"] == 100000
    payout = milestone_payout(m["id"])
    assert payout["gross_cents"] == 100000


def test_split_award_partial_gross_and_refund(api):
    """PRD §3.7: "For any award greater than zero the milestone moves to RELEASED: a RELEASE
    EscrowTransaction is emitted for the arbitrator_award_cents, and if that award is less
    than the funded amount a REFUND EscrowTransaction returns the remainder to the client's
    wallet_balance_cents; a Payout is created with gross equal to the award".

    A SPLIT award of 60000 on a 100000-cent escrow yields released_gross_cents=60000,
    refunded_cents=40000, and a Payout gross of 60000 — distinct from the standard path.

    Design: Difficulty/dual_variant_calc/dual_variant_milestone_release_standard_vs_split
    """
    ctx, m, dispute = setup_dispute_under_arbitration(amount_cents=100000, raised_by="FREELANCER",
                                                      budget_cents=300000, deposit_cents=500000)
    resolve_dispute(dispute["id"], 60000)
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["status"] == "RELEASED"
    assert milestone["released_gross_cents"] == 60000
    assert milestone["refunded_cents"] == 40000
    payout = milestone_payout(m["id"])
    assert payout["gross_cents"] == 60000


# ─── Combinatorial platform fee: tier + surcharge + clamp ─────────────
def _freelancer_with_three_losses(api):
    """Build a freelancer who has lost 3 CLIENT_FAVOR disputes (dispute_loss_count == 3)
    plus an APPROVED 100000-cent milestone ready to release. Returns (ctx, pay_milestone)."""
    ctx = create_active_contract(billing_type="FIXED", skills=("rust",), bid_amount_cents=400000,
                                 budget_cents=500000, deposit_cents=1000000, tax_id_on_file=True)
    cid_h = ctx["client_headers"]
    fid_h = ctx["freelancer_headers"]
    contract_id = ctx["contract"]["id"]

    # Three losing milestones: fund -> submit -> dispute -> arbitrate -> resolve(award 0).
    for i in range(3):
        m = add_milestone(ctx, 30000, ordinal=i + 1, title=f"L{i+1}")
        m = fund_milestone(ctx, m["id"])
        validate_success(api.submit_milestone(contract_id, m["id"], fid_h), 200)
        d = validate_success(api.dispute_milestone(
            contract_id, m["id"], dispute_payload("CLIENT", claimed_release_cents=30000, reason="bad"), cid_h), 201)
        validate_success(api.assign_arbitration(d["id"], make_arbitrator_headers()), 200)
        validate_success(api.resolve_dispute(d["id"], resolve_payload(0), make_arbitrator_headers()), 200)

    # The paying milestone: fund -> submit -> approve.
    pay = add_milestone(ctx, 100000, ordinal=4, title="PAY")
    pay = fund_milestone(ctx, pay["id"])
    validate_success(api.submit_milestone(contract_id, pay["id"], fid_h), 200)
    validate_success(api.approve_milestone(contract_id, pay["id"], cid_h), 200)
    return ctx, pay


def test_platform_fee_tier_a_plus_surcharge_clamped(api):
    """PRD §3.6: "if those pre-payout lifetime earnings are below fifty thousand dollars —
    five million cents — the base rate is twenty percent, which is TIER_A ... A risk
    surcharge is then applied: if the freelancer's dispute_loss_count is at least three,
    five percentage points are added to the rate. The resulting rate is then capped so it
    can never exceed twenty-five percent."

    TIER_A 0.20 + 0.05 surcharge = 0.25 (already at the cap): fee = floor(100000*0.25)=25000.

    Design: Difficulty/combinatorial_formula/combinatorial_platform_fee_tier_plus_surcharge_clamp
    """
    ctx, pay = _freelancer_with_three_losses(api)
    freelancer = validate_success(api.get_freelancer(ctx["freelancer"]["id"], make_admin_headers()), 200)
    assert freelancer["dispute_loss_count"] == 3
    released = api_client_release(api, ctx, pay["id"])
    payout = milestone_payout(pay["id"])
    assert payout["platform_fee_cents"] == 25000
    assert payout["net_cents"] == 75000


def test_platform_fee_net_is_gross_minus_fee(api):
    """PRD §3.6: "The platform_fee_cents is the gross multiplied by this effective rate and
    floored to a whole cent ... The net is the gross minus this fee."

    With the rate clamped to 0.25 on a 100000 gross, net = 100000 - 25000 = 75000.

    Design: Difficulty/combinatorial_formula/combinatorial_platform_fee_tier_plus_surcharge_clamp
    """
    ctx, pay = _freelancer_with_three_losses(api)
    api_client_release(api, ctx, pay["id"])
    payout = milestone_payout(pay["id"])
    assert payout["net_cents"] == payout["gross_cents"] - payout["platform_fee_cents"]
    assert payout["gross_cents"] == 100000
    assert payout["net_cents"] == 75000


# ─── Cascade: dispute CLIENT_FAVOR depth 3 ────────────────────────────
def test_dispute_clientfavor_refunds_wallet_and_increments_loss(api):
    """PRD §3.7: "For an award of zero the milestone moves to REFUNDED: a REFUND
    EscrowTransaction returns the full funded_cents to the client's wallet, the freelancer's
    dispute_loss_count increments, and the reputation is recomputed."

    Depth-3 cascade: resolve(award 0) -> milestone REFUNDED -> wallet credited 20000 ->
    dispute_loss_count incremented.

    Design: Difficulty/transitive_cascade/cascade_dispute_clientfavor_depth3
    """
    ctx, m, dispute = setup_dispute_under_arbitration(amount_cents=20000, raised_by="CLIENT",
                                                      budget_cents=30000, deposit_cents=20000)
    # After funding 20000 from a wallet of 20000, wallet is 0.
    client_before = validate_success(api.get_client(ctx["client"]["id"], ctx["client_headers"]), 200)
    assert client_before["wallet_balance_cents"] == 0
    resolve_dispute(dispute["id"], 0)
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["status"] == "REFUNDED"
    assert milestone["refunded_cents"] == 20000
    client_after = validate_success(api.get_client(ctx["client"]["id"], ctx["client_headers"]), 200)
    assert client_after["wallet_balance_cents"] == 20000
    freelancer = validate_success(api.get_freelancer(ctx["freelancer"]["id"], make_admin_headers()), 200)
    assert freelancer["dispute_loss_count"] == 1


def test_dispute_clientfavor_reputation_zero_after_single_loss(api):
    """PRD §3.1: "An acute penalty is then computed as the lost count multiplied by four,
    but never more than forty. The reputation score is the raw figure multiplied by one
    hundred, less that acute penalty, clamped to lie within zero and one hundred".
    PRD §3.1: "A brand-new freelancer with no outcomes and no reviews has a reputation
    score of exactly 0.0."

    With C=0 completed, L=1 lost, no reviews: completion_rate=0/(0+1)=0, raw=0, penalty=4,
    score = clamp(0*100 - 4, 0, 100) = 0.0.

    Design: Difficulty/transitive_cascade/cascade_dispute_clientfavor_depth3
    """
    ctx, m, dispute = setup_dispute_under_arbitration(amount_cents=20000, raised_by="CLIENT",
                                                      budget_cents=30000, deposit_cents=20000)
    resolve_dispute(dispute["id"], 0)
    freelancer = validate_success(api.get_freelancer(ctx["freelancer"]["id"], make_admin_headers()), 200)
    assert freelancer["dispute_loss_count"] == 1
    assert freelancer["reputation_score"] == 0.0


# ─── Cascade: contract terminate depth 2 ──────────────────────────────
def test_terminate_cancels_milestones_and_refunds_funded(api):
    """PRD §3.8: "Termination cascades in stages: each milestone in DRAFT, FUNDED, SUBMITTED,
    or APPROVED is moved to CANCELLED; then each cancelled milestone whose funded_cents is
    greater than zero emits a REFUND EscrowTransaction returning its held escrow to the
    client's wallet_balance_cents".

    Funded(15000) + Draft(10000) milestones: both CANCELLED; only the funded one refunds
    15000 back to the wallet.

    Design: Difficulty/transitive_cascade/cascade_contract_terminate_depth2
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("ops",), bid_amount_cents=25000,
                                 budget_cents=30000, deposit_cents=15000, tax_id_on_file=True)
    mf = add_milestone(ctx, 15000, ordinal=1, title="Funded")
    md = add_milestone(ctx, 10000, ordinal=2, title="Draft")
    fund_milestone(ctx, mf["id"])  # wallet -> 0
    contract = validate_success(api.terminate_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    assert contract["status"] == "TERMINATED"
    mf_after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], mf["id"], ctx["client_headers"]), 200)
    md_after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], md["id"], ctx["client_headers"]), 200)
    assert mf_after["status"] == "CANCELLED"
    assert md_after["status"] == "CANCELLED"
    client_after = validate_success(api.get_client(ctx["client"]["id"], ctx["client_headers"]), 200)
    assert client_after["wallet_balance_cents"] == 15000


def test_terminate_draft_only_milestone_no_refund(api):
    """PRD §3.8: "each cancelled milestone whose funded_cents is greater than zero emits a
    REFUND EscrowTransaction" — a DRAFT (never funded) milestone has funded_cents == 0 and
    so produces no wallet credit; it is still moved to CANCELLED.

    Design: Difficulty/transitive_cascade/cascade_contract_terminate_depth2
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("ops",), bid_amount_cents=25000,
                                 budget_cents=30000, deposit_cents=0, tax_id_on_file=True)
    md = add_milestone(ctx, 10000, ordinal=1, title="DraftOnly")
    contract = validate_success(api.terminate_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    assert contract["status"] == "TERMINATED"
    md_after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], md["id"], ctx["client_headers"]), 200)
    assert md_after["status"] == "CANCELLED"
    assert md_after["funded_cents"] == 0
    client_after = validate_success(api.get_client(ctx["client"]["id"], ctx["client_headers"]), 200)
    assert client_after["wallet_balance_cents"] == 0


# ─── Compensating invariant: escrow conservation on split ─────────────
def test_escrow_conserved_on_split_release(api):
    """PRD §2.9: "the sum of all of its FUND amounts regardless of status equals its
    released gross plus its refunded cents plus the cents still held."

    On a SPLIT (award 60000) of a 100000 funded milestone: 100000 == 60000 + 40000 + 0.

    Design: Difficulty/compensating_invariant/invariant_escrow_conservation_on_split_release
    """
    ctx, m, dispute = setup_dispute_under_arbitration(amount_cents=100000, raised_by="FREELANCER",
                                                      budget_cents=120000, deposit_cents=100000)
    resolve_dispute(dispute["id"], 60000)
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["released_gross_cents"] == 60000
    assert milestone["refunded_cents"] == 40000
    assert milestone["funded_cents"] == 0
    assert_escrow_conserved(milestone, fund_total=100000)


def test_escrow_ledger_balances_on_split_release(api):
    """PRD §2.9: "A milestone's funded_cents is exactly the held escrow — the sum of its
    FUND amounts minus its REFUND amounts." After a split (60000 released, 40000 refunded),
    held escrow is zero.

    Design: Difficulty/compensating_invariant/invariant_escrow_conservation_on_split_release
    """
    ctx, m, dispute = setup_dispute_under_arbitration(amount_cents=100000, raised_by="FREELANCER",
                                                      budget_cents=120000, deposit_cents=100000)
    resolve_dispute(dispute["id"], 60000)
    rows, _ = api_paginated(api.list_milestone_escrow(m["id"], make_admin_headers()))
    fund_total = sum(r["amount_cents"] for r in rows if r["txn_type"] == "FUND")
    release_total = sum(r["amount_cents"] for r in rows if r["txn_type"] == "RELEASE")
    refund_total = sum(r["amount_cents"] for r in rows if r["txn_type"] == "REFUND")
    assert fund_total == 100000
    assert release_total == 60000
    assert refund_total == 40000


# ─── Compensating invariant: wallet conservation fund-then-terminate ──
def test_wallet_conserved_fund_then_terminate(api):
    """PRD §2.9: "Every FUND debits the client's wallet_balance_cents by exactly the funded
    amount, every REFUND credits the wallet by exactly the refunded amount".

    Funding 30000 then terminating (which refunds 30000) returns the wallet to its pre-fund
    balance of 30000.

    Design: Difficulty/compensating_invariant/invariant_wallet_conservation_fund_then_terminate
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=30000,
                                 budget_cents=40000, deposit_cents=30000, tax_id_on_file=True)
    m = add_milestone(ctx, 30000, ordinal=1)
    fund_milestone(ctx, m["id"])  # wallet 30000 -> 0
    mid_client = validate_success(api.get_client(ctx["client"]["id"], ctx["client_headers"]), 200)
    assert mid_client["wallet_balance_cents"] == 0
    validate_success(api.terminate_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    client_after = validate_success(api.get_client(ctx["client"]["id"], ctx["client_headers"]), 200)
    assert client_after["wallet_balance_cents"] == 30000


def test_terminated_milestone_funded_cents_zero(api):
    """PRD §3.8: a cancelled funded milestone "emits a REFUND EscrowTransaction returning
    its held escrow to the client's wallet_balance_cents" — leaving held escrow at zero.
    PRD §2.9: "funded_cents is exactly the held escrow".

    Design: Difficulty/compensating_invariant/invariant_wallet_conservation_fund_then_terminate
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=30000,
                                 budget_cents=40000, deposit_cents=30000, tax_id_on_file=True)
    m = add_milestone(ctx, 30000, ordinal=1)
    fund_milestone(ctx, m["id"])
    validate_success(api.terminate_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["status"] == "CANCELLED"
    assert milestone["funded_cents"] == 0


# ─── Corner: platform fee floor and tier B ────────────────────────────
def test_platform_fee_min_fee_floor_applied(api):
    """PRD §3.6: "it is never less than a floor of 100 cents unless the gross is itself zero,
    in which case the fee is zero, and it never exceeds the gross."

    A 200-cent release at TIER_A 0.20 would floor to 40, but the 100-cent minimum applies;
    net = 100.

    Design: Corner/calculations/platform_fee_min_fee_floor_applied
    """
    ctx, m = setup_approved_milestone(amount_cents=200, budget_cents=1000, deposit_cents=200)
    release_milestone_inline(api, ctx, m["id"])
    payout = milestone_payout(m["id"])
    assert payout["gross_cents"] == 200
    assert payout["platform_fee_cents"] == 100
    assert payout["net_cents"] == 100


def test_platform_fee_tier_b_after_lifetime_threshold(api):
    """PRD §3.6: "if they are at or above that figure but below ten thousand dollars
    expressed as one hundred million cents, the base rate is ten percent, which is TIER_B".
    PRD §3.6: "Settling a PENDING payout when the freelancer's tax_id_on_file is true moves
    the payout to PAID, adds its net_cents to the freelancer's lifetime_earnings_cents —
    which recomputes the fee_tier".

    First release of 6250000 nets 5000000 to lifetime (TIER_A 0.20 fee 1250000 -> net
    5000000); after settling, a second 100000 release is at TIER_B 0.10 -> fee 10000, net 90000.

    Design: Corner/calculations/platform_fee_tier_b_after_lifetime_threshold
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=6250000,
                                 budget_cents=7000000, deposit_cents=6400000, tax_id_on_file=True)
    cid_h = ctx["client_headers"]
    fid_h = ctx["freelancer_headers"]
    contract_id = ctx["contract"]["id"]

    mbig = add_milestone(ctx, 6250000, ordinal=1, title="Big")
    msmall = add_milestone(ctx, 100000, ordinal=2, title="Small")
    fund_milestone(ctx, mbig["id"])
    fund_milestone(ctx, msmall["id"])
    validate_success(api.submit_milestone(contract_id, mbig["id"], fid_h), 200)
    validate_success(api.approve_milestone(contract_id, mbig["id"], cid_h), 200)
    release_milestone_inline(api, ctx, mbig["id"])
    big_payout = milestone_payout(mbig["id"])
    validate_success(api.settle_payout(big_payout["id"], make_admin_headers()), 200)

    freelancer = validate_success(api.get_freelancer(ctx["freelancer"]["id"], make_admin_headers()), 200)
    assert freelancer["lifetime_earnings_cents"] == 5000000
    assert freelancer["fee_tier"] == "TIER_B"

    validate_success(api.submit_milestone(contract_id, msmall["id"], fid_h), 200)
    validate_success(api.approve_milestone(contract_id, msmall["id"], cid_h), 200)
    release_milestone_inline(api, ctx, msmall["id"])
    small_payout = milestone_payout(msmall["id"])
    assert small_payout["platform_fee_cents"] == 10000
    assert small_payout["net_cents"] == 90000


# ─── Corner: dispute withdraw and award range ─────────────────────────
def test_dispute_withdraw_returns_milestone_to_submitted(api):
    """PRD §3.7: "A dispute may be withdrawn by its raiser while it is still OPEN — the
    acting party must equal the dispute's raised_by, supplied as an actor_role — which
    returns the milestone to SUBMITTED and decrements the contract's open_dispute_count."

    Design: Corner/state_machines/dispute_withdraw_returns_milestone_to_submitted
    """
    ctx, m, dispute = setup_disputed_milestone(amount_cents=20000, raised_by="FREELANCER")
    withdrawn = validate_success(api.withdraw_dispute(
        dispute["id"], withdraw_dispute_payload("FREELANCER"), ctx["freelancer_headers"]), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["status"] == "SUBMITTED"
    contract = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    assert contract["open_dispute_count"] == 0


def test_award_out_of_range_rejected(api):
    """PRD §3.7: "the award must satisfy being at least zero and at most the milestone's
    funded_cents; an award outside that inclusive range is rejected with
    ERR_AWARD_OUT_OF_RANGE".

    Design: Corner/validations/award_out_of_range_rejected
    """
    ctx, m, dispute = setup_dispute_under_arbitration(amount_cents=20000, raised_by="CLIENT")
    res = api.resolve_dispute(dispute["id"], resolve_payload(25000), make_arbitrator_headers())
    validate_error(res, "ERR_AWARD_OUT_OF_RANGE", expected_status=422)
    after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert after["status"] == "DISPUTED"


# ─── small inline helpers (read live version then release) ────────────
def api_client_release(api, ctx, milestone_id):
    cv = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)["version"]
    return validate_success(api.release_milestone(
        ctx["contract"]["id"], milestone_id, release_payload(cv), ctx["client_headers"]), 200)


def release_milestone_inline(api, ctx, milestone_id):
    return api_client_release(api, ctx, milestone_id)


def api_paginated(response):
    from test_helpers import validate_paginated
    return validate_paginated(response)
