"""Calculation rules: tiered bond sizing, dual-variant carrying value, and the
priority payment waterfall (Difficulty queue: dual_variant_calc, combinatorial_formula)."""
from test_helpers import (
    validate_success, get_success_data,
    create_estate, create_open_estate_with_nominated_pr,
    create_estate_with_appointed_pr, file_bond,
    list_asset, appraise_asset,
    setup_accounting_estate_with_marshaled_cash, allow_claim, file_claim,
    make_judge_headers, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
REP = TEST_USERS["representative_headers"]


def test_bond_required_amount_full_estate_tiered_cover(api):
    """PRD §2.8: "the required amount is a tiered marginal cover computed over the
    estate's `gross_estate_value_cents`: the first 1,000,000 cents of value are
    covered in full at 100 percent; the next 4,000,000 cents of value are covered
    at 50 percent, using integer floor division; and any value beyond the first
    5,000,000 cents is covered at 25 percent, again using integer floor division."
    PRD §3.3: "On filing, the system computes `required_amount_cents` (the tiered
    minimum from Section 2.8)".

    A gross of 6,000,000 -> 1,000,000 + (4,000,000*50//100) + (1,000,000*25//100)
    = 1,000,000 + 2,000,000 + 250,000 = 3,250,000.

    Design: Difficulty/dual_variant_calc/bond_required_amount_full_vs_independent
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    assert est["supervision_level"] == "FULL"
    bond = file_bond(est["id"], rep["id"], penal_amount_cents=3_250_000)
    got = get_success_data(api.get_bond(bond["id"], CLERK))
    assert got["required_amount_cents"] == 3_250_000, (
        f"FULL estate bond required amount should be 3250000, got "
        f"{got['required_amount_cents']}")


def test_bond_required_amount_independent_estate_waived(api):
    """PRD §2.8: "When the estate's supervision level is `INDEPENDENT`, no bond is
    required and the required amount is zero."
    PRD §2.9: "When the gross value is less than 500,000 cents, supervision is
    `INDEPENDENT`".

    An INDEPENDENT estate (gross 300000) yields required_amount_cents == 0, the
    opposite variant of the same bond-sizing calculation.

    Design: Difficulty/dual_variant_calc/bond_required_amount_full_vs_independent
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=300_000)
    assert est["supervision_level"] == "INDEPENDENT"
    bond = file_bond(est["id"], rep["id"], penal_amount_cents=0)
    got = get_success_data(api.get_bond(bond["id"], CLERK))
    assert got["required_amount_cents"] == 0, (
        f"INDEPENDENT estate bond required amount should be 0, got "
        f"{got['required_amount_cents']}")


def test_bond_required_amount_tiered_marginal_cover(api):
    """PRD §2.8: "The required amount is the first tier in full, plus the floor of
    the second tier multiplied by 50 and divided by 100, plus the floor of the
    third tier multiplied by 25 and divided by 100."

    gross 6,000,000 -> 1,000,000 (100%) + 2,000,000 (50% of 4,000,000) +
    250,000 (25% of 1,000,000) = 3,250,000, a non-linear tiered figure.

    Design: Difficulty/combinatorial_formula/bond_required_tiered_marginal_cover
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    resp = api.create_bond({
        "estate_id": est["id"],
        "representative_id": rep["id"],
        "surety_name": "S",
        "penal_amount_cents": 3_250_000,
    }, CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["required_amount_cents"] == 3_250_000, (
        f"tiered required amount should be 3250000, got {data['required_amount_cents']}")


def test_asset_carrying_value_provisional_while_listed(api):
    """PRD §3.6: "While an asset is `LISTED` and not yet appraised, its provisional
    carrying value is its PR-declared `declared_value_cents`; once it has been
    appraised — that is, in any of `APPRAISED`, `MARSHALED`, `LIQUIDATED`, or
    `DISTRIBUTED` — its final carrying value is the independent `appraised_value_cents`."

    A LISTED REAL_PROPERTY asset carries declared_value_cents 500000 (provisional).

    Design: Difficulty/dual_variant_calc/asset_carrying_value_provisional_vs_final
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    asset = list_asset(est["id"], "REAL_PROPERTY", declared_value_cents=500_000,
                       description="House")
    got = get_success_data(api.get_asset(asset["id"], REP))
    assert got["status"] == "LISTED"
    assert got["declared_value_cents"] == 500_000, (
        f"provisional carrying value should be declared 500000, got "
        f"{got['declared_value_cents']}")


def test_asset_carrying_value_final_after_appraise(api):
    """PRD §3.6: "once it has been appraised — that is, in any of `APPRAISED`,
    `MARSHALED`, `LIQUIDATED`, or `DISTRIBUTED` — its final carrying value is the
    independent `appraised_value_cents`."
    PRD §3.6: "the estate's `inventory_total_cents` is recomputed as the sum of
    `appraised_value_cents` over every asset whose status is `APPRAISED`,
    `MARSHALED`, `LIQUIDATED`, or `DISTRIBUTED`".

    After APPRAISE the same asset carries appraised 620000 (final, not the
    provisional 500000) and the estate inventory reflects 620000.

    Design: Difficulty/dual_variant_calc/asset_carrying_value_provisional_vs_final
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    asset = list_asset(est["id"], "REAL_PROPERTY", declared_value_cents=500_000,
                       description="House")
    appraised = appraise_asset(est["id"], asset["id"], appraised_value_cents=620_000)
    assert appraised["appraised_value_cents"] == 620_000, (
        f"final carrying value should be appraised 620000, got "
        f"{appraised['appraised_value_cents']}")
    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["inventory_total_cents"] == 620_000, (
        f"inventory should use final appraised 620000, got "
        f"{est_after['inventory_total_cents']}")


def test_claim_payment_waterfall_pool_order_pinned(api):
    """PRD §3.8: "A claim may be paid only when it is the lowest-ordered claim that
    is `ALLOWED` and not yet `PAID`". PRD §3.8: "the claim's `paid_amount_cents` is
    set to the smaller of the claim's `allowed_amount_cents` and the pool, so that
    when the pool is smaller than the allowed amount the claim receives the partial
    remainder rather than being rejected. The pool is then debited by that
    `paid_amount_cents`".

    Pool starts at 200000. SECURED(allowed 150000) is senior and pays first,
    draining the pool to 50000; GENERAL(allowed 300000) then receives the partial
    remainder 50000, leaving the pool at 0.

    Design: Difficulty/combinatorial_formula/claim_payment_waterfall_pool_order_pinned
    """
    est, rep, asset = setup_accounting_estate_with_marshaled_cash(cash_cents=200_000)
    claim_sec = file_claim(est["id"], "SECURED", 150_000, "Bank")
    claim_gen = file_claim(est["id"], "GENERAL", 300_000, "Vendor")
    allow_claim(est["id"], claim_sec["id"], 150_000)
    allow_claim(est["id"], claim_gen["id"], 300_000)

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    paid_sec = validate_success(
        api.pay_claim(claim_sec["id"], {"expected_estate_version": v}, REP))
    assert paid_sec["paid_amount_cents"] == 150_000, (
        f"SECURED should pay in full 150000, got {paid_sec['paid_amount_cents']}")

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    paid_gen = validate_success(
        api.pay_claim(claim_gen["id"], {"expected_estate_version": v}, REP))
    assert paid_gen["paid_amount_cents"] == 50_000, (
        f"GENERAL should receive partial remainder 50000, got "
        f"{paid_gen['paid_amount_cents']}")

    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["marshaled_cash_cents"] == 0, (
        f"pool should be drained to 0, got {est_after['marshaled_cash_cents']}")


def test_bond_required_amount_tiered_second_tier_only(api):
    """PRD §2.8: "take the first tier as the smaller of the gross value and
    1,000,000 cents; take the second tier as the portion of gross value above
    1,000,000 cents but not exceeding a further 4,000,000 cents ... The required
    amount is the first tier in full, plus the floor of the second tier multiplied
    by 50 and divided by 100".

    A gross of 3,000,000 exercises the first two tiers only: 1,000,000 (100%) +
    (2,000,000 * 50 // 100 = 1,000,000) = 2,000,000, with no third tier.

    Design: Difficulty/combinatorial_formula/bond_required_tiered_marginal_cover
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=3_000_000)
    assert est["supervision_level"] == "LIMITED"
    resp = api.create_bond({
        "estate_id": est["id"], "representative_id": rep["id"],
        "surety_name": "S", "penal_amount_cents": 2_000_000,
    }, CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["required_amount_cents"] == 2_000_000, (
        f"tiered required amount for gross 3000000 should be 2000000, got "
        f"{data['required_amount_cents']}")


def test_claim_payment_full_when_pool_exceeds_allowed(api):
    """PRD §3.8: "the claim's `paid_amount_cents` is set to the smaller of the
    claim's `allowed_amount_cents` and the pool". PRD §3.8: "The pool is then
    debited by that `paid_amount_cents`, the estate's `residue_cents` is recomputed".

    With a pool of 200000 and a single senior SECURED claim allowed for 150000, the
    claim is paid in full (min(150000, 200000) = 150000) and the pool drops to 50000.

    Design: Difficulty/combinatorial_formula/claim_payment_waterfall_pool_order_pinned
    """
    est, rep, asset = setup_accounting_estate_with_marshaled_cash(cash_cents=200_000)
    claim_sec = file_claim(est["id"], "SECURED", 150_000, "Bank")
    allow_claim(est["id"], claim_sec["id"], 150_000)

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    paid = validate_success(
        api.pay_claim(claim_sec["id"], {"expected_estate_version": v}, REP))
    assert paid["paid_amount_cents"] == 150_000, (
        f"claim should pay in full 150000, got {paid['paid_amount_cents']}")
    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["marshaled_cash_cents"] == 50_000, (
        f"pool should be debited to 50000, got {est_after['marshaled_cash_cents']}")
