"""Distribution allocation: pro-rata largest-remainder, tiered flat awards,
backup withholding, and the boundary at the tax reporting threshold.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, and the
withholding half of boundary_precision_check.
"""
from test_helpers import (
    get_success_data,
    validate_paginated,
    fixtures,
)
from test_helpers.api_client import api_client

CONTROLLER = fixtures.CONTROLLER


def _payment_for_claim(claim_id):
    resp = api_client.list_payments(CONTROLLER, params={"claim_id": claim_id})
    data, _ = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly one Payment for claim {claim_id}, got {len(data)}"
    return data[0]


# ─── dual_variant_calc: pro_rata_vs_tiered_award_diverge_on_payment ──────────
def test_pro_rata_award_three_claims_largest_remainder():
    """PRD §3.6: "For each claim, the exact weighted share is the remaining
    headroom multiplied by that claim's recognized loss divided by the total
    recognized loss; the claim's provisional gross is the integer floor of that
    exact share."
    PRD §3.6: "These leftover cents are handed out one each, to the claims ordered by the fractional part of their exact share descending, ties broken by `created_at` ascending — never by id; each such claim's gross is raised by one cent until the leftover is exhausted."

    Design: Difficulty/dual_variant_calc/pro_rata_vs_tiered_award_diverge_on_payment
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=100000,
        members=[
            {"email": "a@x.com", "full_name": "A", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "b@x.com", "full_name": "B", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "c@x.com", "full_name": "C", "claimed_loss_cents": 10001, "recognized_loss_cents": 10001},
        ],
    )
    ca, cb, cc = ctx["claims"]
    assert _payment_for_claim(ca["id"])["gross_amount_cents"] == 33332
    assert _payment_for_claim(cb["id"])["gross_amount_cents"] == 33332
    assert _payment_for_claim(cc["id"])["gross_amount_cents"] == 33336
    assert ctx["batch"]["planned_total_cents"] == 100000


def test_pro_rata_award_sums_exactly_to_headroom():
    """PRD §3.6: "Because the leftover is distributed in full, the pro-rata
    grosses sum to exactly the headroom, leaving no residual within the batch."

    Design: Difficulty/dual_variant_calc/pro_rata_vs_tiered_award_diverge_on_payment
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=100000,
        members=[
            {"email": "a@x.com", "full_name": "A", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "b@x.com", "full_name": "B", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "c@x.com", "full_name": "C", "claimed_loss_cents": 10001, "recognized_loss_cents": 10001},
        ],
    )
    grosses = [_payment_for_claim(c["id"])["gross_amount_cents"] for c in ctx["claims"]]
    assert sum(grosses) == 100000


# ─── dual_variant_calc: residual_sweep_vs_standing_diverge_on_settlement ─────
def test_sub_floor_residual_swept_to_cy_pres_zeroes_residual():
    """PRD §3.7: "If that residual is strictly greater than 0 and strictly less than the settlement's `cy_pres_floor_cents`, it is too small to redistribute and is swept to charity: the cy pres sweep (§3.8) runs, each approved cy pres recipient is funded and moved to `FUNDED`, the corresponding `CY_PRES_DEBIT` ledger entries are appended, and the residual is driven to 0."

    Design: Difficulty/dual_variant_calc/residual_sweep_vs_standing_diverge_on_settlement
    """
    ctx = fixtures.setup_posted_batch(
        distribution_method="TIERED",
        gross_fund_cents=760000,
        attorney_fee_cents=100000,
        admin_cost_cents=100000,
        tier_a_amount_cents=250000,
        tier_b_amount_cents=150000,
        cy_pres_floor_cents=20000,
        approve_cy_pres=[
            {"recipient_name": "R1", "share_bps": 6000},
            {"recipient_name": "R2", "share_bps": 4000},
        ],
        members=[
            {"email": "x@x.com", "full_name": "X", "claimant_tier": "TIER_A", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "y@x.com", "full_name": "Y", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "z@x.com", "full_name": "Z", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
        ],
    )
    s_id = ctx["settlement"]["id"]
    # residual = 560000 - 550000 = 10000 < floor 20000 -> swept
    version = fixtures.get_settlement_version(s_id)
    settlement = get_success_data(api_client.reconcile(s_id, version, CONTROLLER))
    assert settlement["status"] == "RECONCILED"
    assert settlement["residual_cents"] == 0

    desigs, _ = validate_paginated(
        api_client.list_cy_pres_designations(s_id, CONTROLLER)
    )
    by_name = {d["recipient_name"]: d for d in desigs}
    assert by_name["R1"]["funded_cents"] == 6000
    assert by_name["R1"]["status"] == "FUNDED"
    assert by_name["R2"]["funded_cents"] == 4000
    assert by_name["R2"]["status"] == "FUNDED"


def test_tiered_award_full_flat_amounts_diverge_from_pro_rata():
    """PRD §3.6: "a claim whose member's `claimant_tier` is `TIER_A` receives
    `tier_a_amount_cents`, and a claim whose member's tier is `TIER_B` receives
    `tier_b_amount_cents`."

    Design: Difficulty/dual_variant_calc/residual_sweep_vs_standing_diverge_on_settlement
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="TIERED",
        gross_fund_cents=760000,
        attorney_fee_cents=100000,
        admin_cost_cents=100000,
        tier_a_amount_cents=250000,
        tier_b_amount_cents=150000,
        cy_pres_floor_cents=20000,
        approve_cy_pres=[
            {"recipient_name": "R1", "share_bps": 6000},
            {"recipient_name": "R2", "share_bps": 4000},
        ],
        members=[
            {"email": "x@x.com", "full_name": "X", "claimant_tier": "TIER_A", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "y@x.com", "full_name": "Y", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "z@x.com", "full_name": "Z", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
        ],
    )
    cx, cy, cz = ctx["claims"]
    assert _payment_for_claim(cx["id"])["gross_amount_cents"] == 250000
    assert _payment_for_claim(cy["id"])["gross_amount_cents"] == 150000
    assert _payment_for_claim(cz["id"])["gross_amount_cents"] == 150000


# ─── combinatorial_formula: pro_rata_largest_remainder_three_inputs_mode_a ───
def test_single_leftover_cent_lands_on_highest_fraction_claim():
    """PRD §3.6: "These leftover cents are handed out one each, to the claims ordered by the fractional part of their exact share descending, ties broken by `created_at` ascending — never by id; each such claim's gross is raised by one cent until the leftover is exhausted."

    Design: Difficulty/combinatorial_formula/pro_rata_largest_remainder_three_inputs_mode_a
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=100000,
        members=[
            {"email": "a@x.com", "full_name": "A", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "b@x.com", "full_name": "B", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "c@x.com", "full_name": "C", "claimed_loss_cents": 10001, "recognized_loss_cents": 10001},
        ],
    )
    ca, _cb, cc = ctx["claims"]
    assert _payment_for_claim(cc["id"])["gross_amount_cents"] == 33336
    assert _payment_for_claim(ca["id"])["gross_amount_cents"] == 33332


def test_pro_rata_grosses_tile_headroom_exactly():
    """PRD §3.6: "Because the leftover is distributed in full, the pro-rata
    grosses sum to exactly the headroom, leaving no residual within the batch."

    Design: Difficulty/combinatorial_formula/pro_rata_largest_remainder_three_inputs_mode_a
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=100000,
        members=[
            {"email": "a@x.com", "full_name": "A", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "b@x.com", "full_name": "B", "claimed_loss_cents": 10000, "recognized_loss_cents": 10000},
            {"email": "c@x.com", "full_name": "C", "claimed_loss_cents": 10001, "recognized_loss_cents": 10001},
        ],
    )
    grosses = [_payment_for_claim(c["id"])["gross_amount_cents"] for c in ctx["claims"]]
    assert sum(grosses) == 100000


# ─── combinatorial_formula: per_claim_withholding_round_then_net_mode_b ──────
def test_no_tin_withholding_floor_per_claim_then_net():
    """PRD §3.6: "the `withholding_cents` is the integer floor of the gross multiplied by the backup withholding rate of 2400 basis points — that is, twenty-four percent of the gross, floored to whole cents."
    PRD §3.6: "Each payment's `amount_cents` — the net cents that will actually debit the fund — is its gross minus its withholding."

    Design: Difficulty/combinatorial_formula/per_claim_withholding_round_then_net_mode_b
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=80000,
        members=[
            {"email": "n@x.com", "full_name": "NoTIN", "tin_on_file": False, "claimed_loss_cents": 80000, "recognized_loss_cents": 80000},
        ],
    )
    pay = _payment_for_claim(ctx["claims"][0]["id"])
    assert pay["gross_amount_cents"] == 80000
    assert pay["withholding_cents"] == 19200
    assert pay["amount_cents"] == 60800


def test_no_tin_withholding_net_amount_value():
    """PRD §3.6: "Each payment's `amount_cents` — the net cents that will actually debit the fund — is its gross minus its withholding."

    Design: Difficulty/combinatorial_formula/per_claim_withholding_round_then_net_mode_b
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=80000,
        members=[
            {"email": "n@x.com", "full_name": "NoTIN", "tin_on_file": False, "claimed_loss_cents": 80000, "recognized_loss_cents": 80000},
        ],
    )
    pay = _payment_for_claim(ctx["claims"][0]["id"])
    assert pay["amount_cents"] == pay["gross_amount_cents"] - pay["withholding_cents"]
    assert pay["amount_cents"] == 60800


# ─── boundary_precision_check: withholding_threshold_at_60000_fires ──────────
def test_withholding_fires_at_exactly_threshold_60000():
    """PRD §3.6: "For a claim whose member has no taxpayer identification on file and whose gross is at least the tax reporting threshold of 60000 cents (six hundred dollars), the `withholding_cents` is the integer floor of the gross multiplied by the backup withholding rate of 2400 basis points — that is, twenty-four percent of the gross, floored to whole cents."

    Design: Difficulty/boundary_precision_check/withholding_threshold_at_60000_fires
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=60000,
        members=[
            {"email": "m@x.com", "full_name": "M", "tin_on_file": False, "claimed_loss_cents": 60000, "recognized_loss_cents": 60000},
        ],
    )
    pay = _payment_for_claim(ctx["claims"][0]["id"])
    assert pay["gross_amount_cents"] == 60000
    assert pay["withholding_cents"] == 14400
    assert pay["amount_cents"] == 45600


def test_withholding_below_threshold_at_59999_not_applied():
    """PRD §3.6: "For a claim whose member has no taxpayer identification on file and whose gross is at least the tax reporting threshold of 60000 cents (six hundred dollars), the `withholding_cents` is the integer floor of the gross multiplied by the backup withholding rate of 2400 basis points — that is, twenty-four percent of the gross, floored to whole cents. For every other claim the withholding is 0."

    Design: Difficulty/boundary_precision_check/withholding_threshold_at_60000_fires
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=59999,
        members=[
            {"email": "m@x.com", "full_name": "M", "tin_on_file": False, "claimed_loss_cents": 59999, "recognized_loss_cents": 59999},
        ],
    )
    pay = _payment_for_claim(ctx["claims"][0]["id"])
    assert pay["gross_amount_cents"] == 59999
    assert pay["withholding_cents"] == 0
    assert pay["amount_cents"] == 59999
