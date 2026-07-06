"""Pricing engine: PPC management fee (tiered, dual-variant) and retainer billing price.

Covers queue A dual_variant_calc + combinatorial_formula (fee) instances and the
queue B record-spend / billing-price corner instances.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_ppc_fee_live_estimate_then_frozen_on_invoice(api):
    """PRD §3.7: "While the campaign's `billing_status` is `UNBILLED`, the fee is a
    live provisional estimate over the current `spent_cents`, recomputed on every
    spend recording and on read, and it excludes any spend later removed by an
    upheld dispute. When the campaign transitions from `UNBILLED` to `INVOICED`,
    the fee is recomputed once over the then-current post-dispute `spent_cents`
    and frozen: an upheld dispute settled after invoicing does not retroactively
    lower an already-`INVOICED` fee."
    PRD §3.7: "Apply each tier's rate to the portion of spend that falls in that
    tier, sum the per-tier fees, and only then floor the summed total down to whole
    cents — the floor is applied once, on the total, never per tier."

    Live estimate over 800,000c at base rate 0.20:
    floor(500000*0.20 + 300000*0.17) = floor(100000 + 51000) = 151000.

    Design: Difficulty/dual_variant_calc/ppc_fee_live_estimate_vs_invoiced_final
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        800000, campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 1000000}
    )
    assert campaign["management_fee_cents"] == 151000, (
        f"live estimate fee over 800000c should be 151000, "
        f"got {campaign['management_fee_cents']}"
    )

    invoiced = validate_success(api.invoice_ad_campaign(campaign["id"], AM))
    assert invoiced["billing_status"] == "INVOICED"
    assert invoiced["management_fee_cents"] == 151000, (
        f"invoiced_final fee frozen at 151000, got {invoiced['management_fee_cents']}"
    )


def test_invoiced_fee_not_lowered_by_later_upheld_dispute(api):
    """PRD §3.7: "When the campaign transitions from `UNBILLED` to `INVOICED`, the fee
    is recomputed once over the then-current post-dispute `spent_cents` and frozen: an
    upheld dispute settled after invoicing does not retroactively lower an
    already-`INVOICED` fee."

    Invoice freezes the fee at 151000 over 800000c; a dispute upheld AFTER invoicing
    (reducing spent_cents) does not lower the already-INVOICED fee.

    Design: Difficulty/dual_variant_calc/ppc_fee_live_estimate_vs_invoiced_final
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        800000, campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 1000000}
    )
    invoiced = validate_success(api.invoice_ad_campaign(campaign["id"], AM))
    assert invoiced["management_fee_cents"] == 151000

    dispute = get_success_data(
        api.create_dispute(
            factories.create_dispute_payload(
                ad_campaign_id=campaign["id"], client_id=client["id"],
                disputed_cents=300000,
            ),
            AM,
        )
    )
    get_success_data(api.review_dispute(dispute["id"], AM))
    get_success_data(api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, AM))

    after = validate_success(api.get_ad_campaign(campaign["id"], ADMIN))
    assert after["management_fee_cents"] == 151000, (
        f"invoiced fee must stay frozen at 151000 after a later upheld dispute, "
        f"got {after['management_fee_cents']}"
    )


def test_retainer_billing_price_direct_vs_reseller_markup(api):
    """PRD §3.4: "The `billing_price_cents` is the client-facing price: for a direct
    client whose `reseller_id` is null it equals `wholesale_price_cents` with no
    markup; for a reseller's client it is `wholesale_price_cents` multiplied by the
    quantity one plus the reseller's `markup_pct`, with the product floored to whole
    cents."

    Reseller markup 0.30 over wholesale 200000c -> floor(200000*1.30) = 260000;
    direct client -> 200000.

    Design: Difficulty/dual_variant_calc/retainer_billing_price_direct_vs_reseller_markup
    """
    reseller = fixtures.create_reseller(brand_name="WhiteLabel Co", markup_pct=0.30)

    _, reseller_retainer = fixtures.create_active_client_with_active_retainer(
        client_overrides={
            "company_name": "Reseller Client",
            "primary_domain": "rc.example",
            "reseller_id": reseller["id"],
        },
        retainer_overrides={"wholesale_price_cents": 200000},
    )
    assert reseller_retainer["billing_price_cents"] == 260000, (
        f"reseller variant should be 260000, got {reseller_retainer['billing_price_cents']}"
    )

    _, direct_retainer = fixtures.create_active_client_with_active_retainer(
        client_overrides={
            "company_name": "Direct Client",
            "primary_domain": "dc.example",
        },
        retainer_overrides={"wholesale_price_cents": 200000},
    )
    assert direct_retainer["billing_price_cents"] == 200000, (
        f"direct variant should be 200000, got {direct_retainer['billing_price_cents']}"
    )


def test_reseller_billing_price_floors_after_markup(api):
    """PRD §3.4: "for a reseller's client it is `wholesale_price_cents` multiplied by
    the quantity one plus the reseller's `markup_pct`, with the product floored to
    whole cents."

    A reseller markup of 0.30 over wholesale 150001c yields a fractional product
    floored to whole cents: floor(150001 * 1.30) = floor(195001.3) = 195001.

    Design: Difficulty/dual_variant_calc/retainer_billing_price_direct_vs_reseller_markup
    """
    reseller = fixtures.create_reseller(brand_name="Floor Reseller", markup_pct=0.30)
    _, retainer = fixtures.create_active_client_with_active_retainer(
        client_overrides={
            "company_name": "Floor Client",
            "primary_domain": "fc.example",
            "reseller_id": reseller["id"],
        },
        retainer_overrides={"wholesale_price_cents": 150001},
    )
    assert retainer["billing_price_cents"] == 195001, (
        f"floor(150001 * 1.30) should be 195001, got {retainer['billing_price_cents']}"
    )


def test_ppc_fee_two_tier_single_floor_at_tier2_boundary(api):
    """PRD §3.7: "the portion of spend below five thousand dollars (500000 cents) is
    charged at the base rate; the portion from five thousand dollars up to twenty
    thousand dollars (between 500000 and 2000000 cents) is charged at the base rate
    reduced by three hundredths".
    PRD §3.7: "Apply each tier's rate to the portion of spend that falls in that tier,
    sum the per-tier fees, and only then floor the summed total down to whole cents —
    the floor is applied once, on the total, never per tier."

    Spend exactly 2,000,000c at base 0.20 fills tier 1 and tier 2 only:
    floor(500000*0.20 + 1500000*0.17) = floor(355000.0) = 355000.

    Design: Difficulty/combinatorial_formula/ppc_fee_nested_tier_rounding_order
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        2000000,
        campaign_overrides={"channel": "META", "budget_cents": 3000000},
        retainer_overrides={"tier": "DOMINATE", "wholesale_price_cents": 500000},
    )
    assert campaign["spent_cents"] == 2000000
    assert campaign["management_fee_cents"] == 355000, (
        f"single floor over tier-1 + tier-2 fees should be 355000, "
        f"got {campaign['management_fee_cents']}"
    )


def test_ppc_fee_single_floor_over_three_tier_sum(api):
    """PRD §3.7: "Spend is split across three tiers by cumulative amount: the portion
    of spend below five thousand dollars (500000 cents) is charged at the base rate;
    the portion from five thousand dollars up to twenty thousand dollars (between
    500000 and 2000000 cents) is charged at the base rate reduced by three hundredths;
    and the portion of spend at or above twenty thousand dollars (2000000 cents) is
    charged at the base rate reduced by six hundredths."
    PRD §3.7: "Apply each tier's rate to the portion of spend that falls in that tier,
    sum the per-tier fees, and only then floor the summed total down to whole cents —
    the floor is applied once, on the total, never per tier."

    Spend 2,500,000c at base 0.20 spans all three tiers:
    floor(500000*0.20 + 1500000*0.17 + 500000*0.14) = floor(425000.0) = 425000.

    Design: Difficulty/combinatorial_formula/ppc_fee_nested_tier_rounding_order
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        2500000,
        campaign_overrides={"channel": "META", "budget_cents": 3000000},
        retainer_overrides={"tier": "DOMINATE", "wholesale_price_cents": 500000},
    )
    assert campaign["spent_cents"] == 2500000
    assert campaign["management_fee_cents"] == 425000, (
        f"single floor over summed per-tier fees should be 425000, "
        f"got {campaign['management_fee_cents']}"
    )


def test_record_spend_accumulates_and_updates_live_fee(api):
    """PRD §3.7: "Recording spend adds `amount_cents` to `spent_cents` and recomputes
    the live `management_fee_cents`."
    PRD §3.7: "the portion of spend below five thousand dollars (500000 cents) is
    charged at the base rate" and "the agency default rate of twenty hundredths (0.20)".

    Direct campaign, single tier-1 spend 300000c: fee = floor(300000*0.20) = 60000.

    Design: Corner/endpoints/record_spend_updates_spent_and_live_fee
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"tier": "STARTER", "monthly_credits": 10,
                            "wholesale_price_cents": 100000},
    )
    campaign = fixtures.create_live_campaign(
        client["id"], retainer["id"], channel="GOOGLE_ADS", budget_cents=500000
    )
    updated = validate_success(
        api.record_spend(campaign["id"], {"amount_cents": 300000}, AM)
    )
    assert updated["spent_cents"] == 300000
    assert updated["management_fee_cents"] == 60000, (
        f"live fee floor(300000*0.20) should be 60000, "
        f"got {updated['management_fee_cents']}"
    )
