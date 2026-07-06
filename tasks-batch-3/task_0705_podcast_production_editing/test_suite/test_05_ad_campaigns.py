"""Ad campaign revenue split (round-per-slot-then-sum), gross-conservation
invariant, reconcile cross-entity dependency, OCC stale reconcile, and approve
with no slots. Covers difficulty rules combinatorial_formula (ad split),
compensating_invariant (ad split), cross_entity_state_dependency (reconcile),
plus corner/cross_cutting OCC + errors instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_platform_admin_headers,
    make_ad_ops_headers,
    ApiErrorId,
    create_show,
    create_ad_campaign_payload,
    setup_approved_campaign_with_slots,
    assert_revenue_split_conserves_gross,
)

ADMIN = make_platform_admin_headers()
ADOPS = make_ad_ops_headers()


class TestAdRevenueSplit:
    def test_round_per_slot_then_sum(self, api):
        """PRD §3.10: "show_payout_cents is the sum, over every slot, of each slot's
        gross_cents multiplied by the keep fraction and rounded half up to whole cents —
        rounding each slot individually and only then summing, which differs in cents from
        summing first and rounding once; the gross total is the sum of every slot's
        gross_cents; and platform_take_cents is the gross total minus show_payout_cents."

        Design: Difficulty/combinatorial_formula/ad_revenue_split_round_per_slot_then_sum_order
        """
        show, contract, engineer, campaign, episodes = setup_approved_campaign_with_slots(
            [{"gross_cents": 105, "placement": "MID_ROLL"},
             {"gross_cents": 105, "placement": "MID_ROLL"}],
            platform_fee_pct=0.30, sponsor="Acme")
        camp = get_success_data(api_client.get_ad_campaign(campaign["id"], ADOPS))

        reconciled = validate_success(api_client.reconcile_ad_campaign(
            campaign["id"], {"expected_adcampaign_version": camp["version"]}, ADOPS))
        assert reconciled["show_payout_cents"] == 148, (
            f"round_half_up(105*0.70)=74 per slot, summed=148 (NOT 147 sum-then-round), "
            f"got {reconciled['show_payout_cents']}")
        assert reconciled["platform_take_cents"] == 62, (
            f"gross 210 - payout 148 = 62, got {reconciled['platform_take_cents']}")
        assert reconciled["status"] == "RECONCILED"

    def test_revenue_split_precision_on_uneven_slots(self, api):
        """PRD §3.10: "show_payout_cents is the sum, over every slot, of each slot's
        gross_cents multiplied by the keep fraction and rounded half up to whole cents —
        rounding each slot individually and only then summing"

        Design: Difficulty/combinatorial_formula/ad_revenue_split_round_per_slot_then_sum_order
        """
        show, contract, engineer, campaign, episodes = setup_approved_campaign_with_slots(
            [{"gross_cents": 333, "placement": "PRE_ROLL"},
             {"gross_cents": 777, "placement": "POST_ROLL"}],
            platform_fee_pct=0.30, sponsor="Gamma")
        camp = get_success_data(api_client.get_ad_campaign(campaign["id"], ADOPS))
        reconciled = validate_success(api_client.reconcile_ad_campaign(
            campaign["id"], {"expected_adcampaign_version": camp["version"]}, ADOPS))
        assert reconciled["show_payout_cents"] == 777, (
            f"round_half_up(333*0.70)=233 + round_half_up(777*0.70)=544 = 777, "
            f"got {reconciled['show_payout_cents']}")

    def test_split_conserves_gross_total(self, api):
        """PRD §3.10: "the gross total is the sum of every slot's gross_cents; and
        platform_take_cents is the gross total minus show_payout_cents."

        Design: Difficulty/compensating_invariant/ad_revenue_split_conserves_gross_total
        """
        show, contract, engineer, campaign, episodes = setup_approved_campaign_with_slots(
            [{"gross_cents": 333, "placement": "PRE_ROLL"},
             {"gross_cents": 777, "placement": "POST_ROLL"}],
            platform_fee_pct=0.30, sponsor="Gamma")
        camp = get_success_data(api_client.get_ad_campaign(campaign["id"], ADOPS))
        reconciled = validate_success(api_client.reconcile_ad_campaign(
            campaign["id"], {"expected_adcampaign_version": camp["version"]}, ADOPS))
        assert reconciled["show_payout_cents"] == 777
        assert reconciled["platform_take_cents"] == 333
        assert_revenue_split_conserves_gross(reconciled, gross_total=1110)

    def test_split_conserves_gross_total_even_split(self, api):
        """PRD §3.10: "platform_take_cents is the gross total minus show_payout_cents."

        Design: Difficulty/compensating_invariant/ad_revenue_split_conserves_gross_total
        """
        show, contract, engineer, campaign, episodes = setup_approved_campaign_with_slots(
            [{"gross_cents": 105, "placement": "MID_ROLL"},
             {"gross_cents": 105, "placement": "MID_ROLL"}],
            platform_fee_pct=0.30, sponsor="Acme")
        camp = get_success_data(api_client.get_ad_campaign(campaign["id"], ADOPS))
        reconciled = validate_success(api_client.reconcile_ad_campaign(
            campaign["id"], {"expected_adcampaign_version": camp["version"]}, ADOPS))
        assert_revenue_split_conserves_gross(reconciled, gross_total=210)


class TestReconcileCrossEntityDependency:
    def test_reconcile_blocked_when_slot_episode_not_published(self, api):
        """PRD §3.10: "Reconciliation further requires every slot's episode to be
        PUBLISHED; if any slot's episode is not yet published the request is rejected with
        ERR_SLOT_EPISODE_NOT_PUBLISHED."

        Design: Difficulty/cross_entity_state_dependency/ad_campaign_reconcile_depends_on_adslot_episode_published
        """
        show, contract, engineer, campaign, episodes = setup_approved_campaign_with_slots(
            [{"gross_cents": 1000, "placement": "PRE_ROLL", "published": True},
             {"gross_cents": 1000, "placement": "PRE_ROLL", "published": False}],
            platform_fee_pct=0.30, sponsor="Beta")
        camp = get_success_data(api_client.get_ad_campaign(campaign["id"], ADOPS))

        resp = api_client.reconcile_ad_campaign(
            campaign["id"], {"expected_adcampaign_version": camp["version"]}, ADOPS)
        validate_error(resp, ApiErrorId.ERR_SLOT_EPISODE_NOT_PUBLISHED.value)

        after = get_success_data(api_client.get_ad_campaign(campaign["id"], ADOPS))
        assert after["status"] == "APPROVED", (
            f"reconcile blocked, campaign stays APPROVED, got {after['status']}")

    def test_reconcile_succeeds_when_all_slot_episodes_published(self, api):
        """PRD §3.10: "Reconciliation further requires every slot's episode to be
        PUBLISHED; if any slot's episode is not yet published the request is rejected with
        ERR_SLOT_EPISODE_NOT_PUBLISHED."

        Design: Difficulty/cross_entity_state_dependency/ad_campaign_reconcile_depends_on_adslot_episode_published
        """
        show, contract, engineer, campaign, episodes = setup_approved_campaign_with_slots(
            [{"gross_cents": 1000, "placement": "PRE_ROLL", "published": True},
             {"gross_cents": 1000, "placement": "PRE_ROLL", "published": True}],
            platform_fee_pct=0.30, sponsor="Beta")
        camp = get_success_data(api_client.get_ad_campaign(campaign["id"], ADOPS))
        reconciled = validate_success(api_client.reconcile_ad_campaign(
            campaign["id"], {"expected_adcampaign_version": camp["version"]}, ADOPS))
        assert reconciled["status"] == "RECONCILED"


class TestAdCampaignApproval:
    def test_approve_with_no_slots_rejected(self, api):
        """PRD §3.10: "approved (DRAFT → APPROVED) while it is DRAFT and it carries at
        least one slot — approving a campaign with zero slots is rejected with
        ERR_NO_SLOTS."

        Design: Corner/errors/error_no_slots_on_campaign_approve
        """
        show = create_show(billing_model="PER_EPISODE")
        campaign = get_success_data(api_client.create_ad_campaign(
            create_ad_campaign_payload(show["id"], sponsor_name="Empty"), ADOPS))
        resp = api_client.approve_ad_campaign(campaign["id"], ADOPS)
        validate_error(resp, ApiErrorId.ERR_NO_SLOTS.value)
