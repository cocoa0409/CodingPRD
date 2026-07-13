"""Pricing and estate-value calculations: signup price, renewal quote vs final
charge, the gross/net-probate estate summary, the estate-distribution waterfall,
prorated cancellation refunds, and witness requirements.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_active_subscription, add_asset, add_beneficiary, generate_document,
    setup_plan, set_clock, register_member, create_pending_subscription, activate,
    make_member_headers, ADMIN,
)


# ─── Difficulty: dual_variant_calc / gross_vs_net_probate_estate ─────────
def _setup_three_asset_estate():
    """PLUS subscription with A1=100000 FUNDED, A2=50000 UNFUNDED designated to a
    beneficiary, A3=30000 UNFUNDED undesignated."""
    member, sub, hdr = make_active_subscription(
        plan_tier="PLUS", base_price_cents=20000,
        included_document_types=["WILL", "TRUST", "POA", "HEALTHCARE_DIRECTIVE"],
        max_documents=10, allows_trust=True, state_code="CA")
    ben = add_beneficiary(sub["id"], hdr, full_name="Child A", allocation_pct=100)
    add_asset(sub["id"], hdr, asset_type="REAL_ESTATE", description="House",
              estimated_value_cents=100000, funding_status="FUNDED")
    add_asset(sub["id"], hdr, asset_type="BANK", description="Account",
              estimated_value_cents=50000, funding_status="UNFUNDED",
              assigned_beneficiary_id=ben["id"])
    add_asset(sub["id"], hdr, asset_type="PERSONAL", description="Jewelry",
              estimated_value_cents=30000, funding_status="UNFUNDED")
    return sub, hdr


def test_estate_summary_gross_sums_all_assets(api):
    """PRD §3.9: "It reports `gross_estate_value_cents`, the sum of
    `estimated_value_cents` across all of the subscription's assets, and
    `net_probate_estate_cents`, the sum of `estimated_value_cents` over only those
    assets that are not `FUNDED` and have no `assigned_beneficiary_id`"

    Design: Difficulty/dual_variant_calc/gross_vs_net_probate_estate
    """
    sub, hdr = _setup_three_asset_estate()
    summary = validate_success(api.get_estate_summary(sub["id"], hdr), 200)
    assert summary["gross_estate_value_cents"] == 180000


def test_estate_summary_net_probate_excludes_funded_and_designated(api):
    """PRD §3.9: "the sum of `estimated_value_cents` over only those assets that are
    not `FUNDED` and have no `assigned_beneficiary_id` — the same asset rows, but
    excluding in-trust (non-probate) assets and assets already earmarked to a
    beneficiary". The summary also reports "`total_assigned_value_cents`, the sum of
    `estimated_value_cents` across assets that carry an `assigned_beneficiary_id`".

    Design: Difficulty/dual_variant_calc/gross_vs_net_probate_estate
    """
    sub, hdr = _setup_three_asset_estate()
    summary = validate_success(api.get_estate_summary(sub["id"], hdr), 200)
    assert summary["net_probate_estate_cents"] == 30000
    assert summary["total_assigned_value_cents"] == 50000


# ─── Difficulty: dual_variant_calc / renewal_quote_vs_final_charge ──────
def _setup_renewal_initiated():
    """PLUS INDIVIDUAL active [2026-06-01, 2027-06-01); clock 2027-05-15; renewal
    initiated (provisional quote staked). Returns (sub_id, hdr, quote_cents)."""
    member, sub, hdr = make_active_subscription(
        plan_tier="PLUS", base_price_cents=20000, clock="2026-06-01T00:00:00Z")
    set_clock("2027-05-15T00:00:00Z")
    renewed = get_success_data(api_client.renew_subscription(sub["id"], hdr))
    return sub["id"], hdr, renewed["pending_charge_cents"]


def test_renewal_provisional_quote_has_no_loyalty_discount(api):
    """PRD §3.3: "The provisional quote is computed exactly like the signup price
    but using the catalog base price for the current tier at quote time: the current
    `base_price_cents`, plus the 15000-cent attorney add-on when `attorney_support`
    is on, multiplied by the bundle multiplier (1.0 individual, 1.6 couple), rounded
    half-up to whole cents. Crucially, no loyalty discount is applied at quote time —
    the provisional quote equals the undiscounted list price."

    Design: Difficulty/dual_variant_calc/renewal_quote_vs_final_charge
    """
    sub_id, hdr, quote_cents = _setup_renewal_initiated()
    assert quote_cents == 20000


def test_renewal_final_charge_applies_loyalty_discount(api):
    """PRD §3.3: "the amount actually charged — the final charge — is the provisional
    quote reduced by the loyalty discount, where the discount is determined from the
    post-increment renewal count. If the incremented count is 1 or 2 the discount is
    10 percent; if it is 3 or more the discount is 20 percent." "That final charge is
    added to `paid_to_date_cents`".

    Design: Difficulty/dual_variant_calc/renewal_quote_vs_final_charge
    """
    sub_id, hdr, _quote = _setup_renewal_initiated()
    settled = validate_success(
        api.simulate_payment({"subscription_id": sub_id, "outcome": "SUCCEEDED"}, ADMIN), 200)
    assert settled["renewal_count"] == 1
    # signup 20000 + loyalty-discounted renewal 18000 = 38000
    assert settled["paid_to_date_cents"] == 38000
    assert settled["pending_charge_cents"] == 0


# ─── Difficulty: combinatorial_formula / signup_price_bundle_addon_tiered ─
def test_signup_price_couple_bundle_with_attorney_addon(api):
    """PRD §3.2: "take the catalog `base_price_cents` for the chosen tier, add an
    attorney add-on of 15000 cents ($150.00) when `attorney_support` is enabled and
    nothing otherwise, then multiply that sum by the bundle multiplier — 1.0 for an
    `INDIVIDUAL` bundle and 1.6 for a `COUPLE` bundle — and round the product half-up
    to whole cents in a single rounding step."

    Design: Difficulty/combinatorial_formula/signup_price_bundle_addon_tiered
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(email="couple@example.com")
    hdr = make_member_headers(member["id"])
    sub = validate_success(api.create_subscription({
        "member_id": member["id"], "plan_tier": "PLUS", "bundle_type": "COUPLE",
        "spouse_name": "Spouse", "attorney_support": True}, hdr), 201)
    # (20000 + 15000) * 1.6 = 56000
    assert sub["price_cents"] == 56000


def test_signup_pending_charge_matches_signup_price(api):
    """PRD §3.2: "At creation the subscription's signup price is computed and stored
    in `price_cents`, and that same amount is placed in `pending_charge_cents` as the
    outstanding charge awaiting settlement."

    Design: Difficulty/combinatorial_formula/signup_price_bundle_addon_tiered
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(email="couple2@example.com")
    hdr = make_member_headers(member["id"])
    sub = validate_success(api.create_subscription({
        "member_id": member["id"], "plan_tier": "PLUS", "bundle_type": "COUPLE",
        "spouse_name": "Spouse", "attorney_support": True}, hdr), 201)
    assert sub["price_cents"] == 56000
    assert sub["pending_charge_cents"] == 56000


# ─── Difficulty: combinatorial_formula / estate_distribution_residual_rounding ─
def _setup_three_primary_beneficiaries():
    """ACTIVE subscription; primaries B1(33.34, first), B2(33.33), B3(33.33); a
    single 100001-cent asset (gross estate 100001). Returns (sub, hdr, [b1,b2,b3])."""
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    b1 = add_beneficiary(sub["id"], hdr, full_name="B One", allocation_pct=33.34)
    b2 = add_beneficiary(sub["id"], hdr, full_name="B Two", allocation_pct=33.33)
    b3 = add_beneficiary(sub["id"], hdr, full_name="B Three", allocation_pct=33.33)
    add_asset(sub["id"], hdr, asset_type="INVESTMENT", description="Portfolio",
              estimated_value_cents=100001, funding_status="UNFUNDED")
    return sub, hdr, [b1, b2, b3]


def test_estate_distribution_floor_then_residual_by_created_at(api):
    """PRD §3.9: "For each non-contingent (primary) beneficiary, a floor share is
    computed as the pool multiplied by that beneficiary's `allocation_pct` divided by
    100, taking the floor to whole cents. The residual — the pool minus the sum of all
    floor shares — is then distributed one cent at a time to the primary beneficiaries
    ordered by `created_at` ascending, cycling through them in that order until the
    residual is exhausted."

    Design: Difficulty/combinatorial_formula/estate_distribution_residual_rounding
    """
    from test_helpers import validate_paginated
    sub, hdr, bens = _setup_three_primary_beneficiaries()
    data, _meta = validate_paginated(api.list_subscription_beneficiaries(sub["id"], hdr))
    alloc = {b["id"]: b["allocated_cents"] for b in data}
    assert alloc[bens[0]["id"]] == 33341
    assert alloc[bens[1]["id"]] == 33330
    assert alloc[bens[2]["id"]] == 33330


def test_estate_distribution_conserves_full_pool(api):
    """PRD §3.9: "Each primary beneficiary's `allocated_cents` is its floor share plus
    any residual cents it received; contingent beneficiaries receive 0. This ordering
    (floor-per-beneficiary first, then residual by creation order) is authoritative and
    must not be replaced by rounding each share independently and summing."

    Design: Difficulty/combinatorial_formula/estate_distribution_residual_rounding
    """
    from test_helpers import validate_paginated
    sub, hdr, _bens = _setup_three_primary_beneficiaries()
    data, _meta = validate_paginated(api.list_subscription_beneficiaries(sub["id"], hdr))
    assert sum(b["allocated_cents"] for b in data) == 100001


# ─── Corner: calculations / signup_price_basic_individual ────────────────
def test_signup_price_basic_individual_no_addon(api):
    """PRD §3.2: "then multiply that sum by the bundle multiplier — 1.0 for an
    `INDIVIDUAL` bundle and 1.6 for a `COUPLE` bundle — and round the product half-up
    to whole cents in a single rounding step."

    Design: Corner/calculations/signup_price_basic_individual
    """
    setup_plan(plan_tier="BASIC", base_price_cents=10000,
               included_document_types=["WILL"], max_documents=3)
    member = register_member(email="basic@example.com")
    hdr = make_member_headers(member["id"])
    sub = validate_success(api.create_subscription({
        "member_id": member["id"], "plan_tier": "BASIC", "bundle_type": "INDIVIDUAL"}, hdr), 201)
    # (10000 + 0) * 1.0 = 10000
    assert sub["price_cents"] == 10000


# ─── Corner: calculations / cancel_refund_midperiod_prorated ─────────────
def test_cancel_refund_prorated_midperiod(api):
    """PRD §3.4: "Otherwise the refund is the most recently applicable list price —
    the subscription's `price_cents` — multiplied by the number of remaining days in
    the coverage window divided by the 365-day term, rounded half-up to whole cents."
    "The final refund amount is added to `refunded_cents` and subtracted from
    `paid_to_date_cents`."

    Design: Corner/calculations/cancel_refund_midperiod_prorated
    """
    member, sub, hdr = make_active_subscription(
        plan_tier="PLUS", base_price_cents=20000, clock="2026-06-01T00:00:00Z")
    set_clock("2026-12-01T00:00:00Z")
    cancelled = validate_success(api.cancel_subscription(sub["id"], hdr), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refunded_cents"] == 9973
    assert cancelled["paid_to_date_cents"] == 10027


# ─── Corner: calculations / witness_requirement_la_will_surcharge ────────
def test_witness_requirement_la_will_surcharge_and_notary(api):
    """PRD §3.6: "The `witness_count_required` is a base count for the document type —
    2 witnesses for a `WILL`, 0 for a `TRUST`, 1 for a `POA`, and 1 for a
    `HEALTHCARE_DIRECTIVE` — plus a surcharge of 1 additional witness when the
    `state_code` is either `LA` or `VT`, and no surcharge otherwise." "A document
    `requires_notary` when its `document_type` is either `TRUST` or `POA`, or when its
    `state_code` is `LA`."

    Design: Corner/calculations/witness_requirement_la_will_surcharge
    """
    member, sub, hdr = make_active_subscription(
        plan_tier="PLUS", base_price_cents=20000, state_code="LA")
    _q, doc = generate_document(sub["id"], hdr, document_type="WILL", state_code="LA")
    assert doc["witness_count_required"] == 3
    assert doc["requires_notary"] is True
