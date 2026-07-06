"""Ad campaigns: parallel lifecycle/billing dimensions, spend conservation, disputes.

Covers queue A non_linear_state_machine (parallel dimensions) and
compensating_invariant (ad spend conservation) instances, plus queue B
state_machines / validations corner instances on campaigns and disputes.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_campaign_can_be_invoiced_while_paused(api):
    """PRD §3.7: "The spend-lifecycle dimension runs across `DRAFT`, `LIVE`, `PAUSED`,
    and the terminal `ENDED`; the billing dimension runs independently across
    `UNBILLED`, `INVOICED`, and the terminal `SETTLED`. A transition on one dimension
    never moves the other."

    A campaign paused (lifecycle PAUSED) can still be invoiced (billing INVOICED),
    proving the dimensions do not gate each other.

    Design: Difficulty/non_linear_state_machine/adcampaign_parallel_lifecycle_and_billing_dimensions
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        300000,
        campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 500000},
        retainer_overrides={"tier": "STARTER", "monthly_credits": 10,
                            "wholesale_price_cents": 100000},
    )
    validate_success(api.pause_ad_campaign(campaign["id"], AM))
    invoiced = validate_success(api.invoice_ad_campaign(campaign["id"], AM))
    assert invoiced["lifecycle_status"] == "PAUSED", (
        f"lifecycle must stay PAUSED across the billing transition, "
        f"got {invoiced['lifecycle_status']}"
    )
    assert invoiced["billing_status"] == "INVOICED"


def test_campaign_invoice_freezes_fee_over_paused_spend(api):
    """PRD §3.7: "When the campaign transitions from `UNBILLED` to `INVOICED`, the
    fee is recomputed once over the then-current post-dispute `spent_cents` and
    frozen".
    PRD §3.7: "the portion of spend below five thousand dollars (500000 cents) is
    charged at the base rate" and "the agency default rate of twenty hundredths (0.20)".

    Direct campaign, PAUSED with spent 300000c: invoiced fee = floor(300000*0.20) =
    60000, regardless of the PAUSED lifecycle.

    Design: Difficulty/non_linear_state_machine/adcampaign_parallel_lifecycle_and_billing_dimensions
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        300000,
        campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 500000},
        retainer_overrides={"tier": "STARTER", "monthly_credits": 10,
                            "wholesale_price_cents": 100000},
    )
    validate_success(api.pause_ad_campaign(campaign["id"], AM))
    invoiced = validate_success(api.invoice_ad_campaign(campaign["id"], AM))
    assert invoiced["management_fee_cents"] == 60000, (
        f"invoiced fee should be floor(300000*0.20)=60000, "
        f"got {invoiced['management_fee_cents']}"
    )


def test_ad_spend_conserved_credited_cents_on_upheld(api):
    """PRD §3.8: "on success it sets `credited_cents` equal to `disputed_cents`,
    subtracts `disputed_cents` from the campaign's `spent_cents`".

    Recorded spend 800000c; uphold a 300000c dispute -> credited_cents 300000.

    Design: Difficulty/compensating_invariant/ad_spend_conserved_across_record_then_upheld_dispute
    """
    client, retainer, campaign, dispute = fixtures.setup_dispute_under_review(
        disputed_cents=300000, spend_cents=800000,
        campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 1000000},
    )
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, AM)
    )
    assert resolved["credited_cents"] == 300000, (
        f"credited_cents should equal disputed 300000, got {resolved['credited_cents']}"
    )


def test_ad_spend_conserved_spent_plus_credited_equals_recorded(api):
    """PRD §3.8: "subtracts `disputed_cents` from the campaign's `spent_cents`".
    PRD §3.7: "Recording spend adds `amount_cents` to `spent_cents`".

    Conservation: after upholding the 300000c dispute, campaign.spent_cents (500000)
    plus dispute.credited_cents (300000) equals the 800000c originally recorded.

    Design: Difficulty/compensating_invariant/ad_spend_conserved_across_record_then_upheld_dispute
    """
    client, retainer, campaign, dispute = fixtures.setup_dispute_under_review(
        disputed_cents=300000, spend_cents=800000,
        campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 1000000},
    )
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, AM)
    )
    campaign_after = validate_success(api.get_ad_campaign(campaign["id"], ADMIN))
    assert campaign_after["spent_cents"] == 500000, (
        f"spent_cents should be 800000-300000=500000, got {campaign_after['spent_cents']}"
    )
    assert campaign_after["spent_cents"] + resolved["credited_cents"] == 800000, (
        "spent_cents + credited_cents must conserve the originally recorded 800000"
    )


def test_invoice_blocked_by_open_dispute(api):
    """PRD §3.7: "Invoicing is permitted only when the campaign has no dispute in
    `OPEN` or `UNDER_REVIEW`, otherwise `ERR_CAMPAIGN_HAS_OPEN_DISPUTE`".

    Design: Corner/state_machines/invoice_blocked_by_open_dispute
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    campaign = fixtures.create_live_campaign(
        client["id"], retainer["id"], channel="META", budget_cents=1000000
    )
    validate_success(api.record_spend(campaign["id"], {"amount_cents": 200000}, AM))
    get_success_data(
        api.create_dispute(
            factories.create_dispute_payload(
                ad_campaign_id=campaign["id"], client_id=client["id"],
                disputed_cents=50000,
            ),
            AM,
        )
    )
    resp = api.invoice_ad_campaign(campaign["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_HAS_OPEN_DISPUTE.value)

    after = validate_success(api.get_ad_campaign(campaign["id"], ADMIN))
    assert after["billing_status"] == "UNBILLED", (
        f"billing_status must stay UNBILLED, got {after['billing_status']}"
    )


def test_dispute_uphold_exceeding_spend_rejected(api):
    """PRD §3.8: "An `UPHELD` resolution credits the client and claws spend back: it
    requires `disputed_cents` to be at most the linked campaign's current
    `spent_cents`, otherwise `ERR_DISPUTE_EXCEEDS_SPEND`".

    Spend 100000c; uphold a 150000c dispute -> ERR_DISPUTE_EXCEEDS_SPEND; dispute
    stays UNDER_REVIEW.

    Design: Corner/validations/dispute_exceeds_spend_on_uphold
    """
    client, retainer, campaign, dispute = fixtures.setup_dispute_under_review(
        disputed_cents=150000, spend_cents=100000,
        campaign_overrides={"channel": "BING", "budget_cents": 500000},
    )
    resp = api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, AM)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_EXCEEDS_SPEND.value)

    after = validate_success(api.get_dispute(dispute["id"], ADMIN))
    assert after["status"] == "UNDER_REVIEW", (
        f"dispute must stay UNDER_REVIEW, got {after['status']}"
    )
