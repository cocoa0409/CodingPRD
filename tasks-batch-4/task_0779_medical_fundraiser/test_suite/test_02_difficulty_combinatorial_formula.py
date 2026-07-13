"""Difficulty: combinatorial_formula — the pinned-order charge gross-up and the
per-donation-then-sum reserve rounding.
"""
from test_helpers import (
    setup_published_campaign,
    make_donation,
    get_campaign,
)


class TestDonationChargeGrossUp:
    """amount 10000 + tip 1500 -> subtotal 11500; total = ceil(11530/0.971) = 11875;
    fee = 11875 - 11500 = 375; net = 10000."""

    def test_total_charged_grosses_up_fee(self, api):
        """PRD §3.4: "Then compute total_charged_cents — the amount the donor's card is
        actually charged — by taking the subtotal plus a fixed 30-cent-per-transaction
        component, dividing that by one minus the processing rate of 0.029 (that is,
        dividing by 0.971), and rounding the quotient up to the next whole cent."

        Design: Difficulty/combinatorial_formula/donation_fee_on_total_gross_up
        """
        b = setup_published_campaign(api)
        don = make_donation(api, b["campaign"]["id"], b["donor"]["id"], 10000, tip_cents=1500)
        assert don["total_charged_cents"] == 11875, (
            f"ceil((11500+30)/0.971)=11875, got {don['total_charged_cents']}"
        )
        assert don["net_to_campaign_cents"] == 10000, (
            f"net = amount_cents = 10000, got {don['net_to_campaign_cents']}"
        )

    def test_processing_fee_is_residual(self, api):
        """PRD §3.4: "Then compute total_charged_cents — the amount the donor's card is
        actually charged — by taking the subtotal plus a fixed 30-cent-per-transaction
        component, dividing that by one minus the processing rate of 0.029 (that is, dividing
        by 0.971), and rounding the quotient up to the next whole cent. The processing_fee_cents
        is then the residual: total_charged_cents minus the subtotal."

        Design: Difficulty/combinatorial_formula/donation_fee_on_total_gross_up
        """
        b = setup_published_campaign(api)
        don = make_donation(api, b["campaign"]["id"], b["donor"]["id"], 10000, tip_cents=1500)
        assert don["processing_fee_cents"] == 375, (
            f"11875 - 11500 = 375, got {don['processing_fee_cents']}"
        )


class TestReserveRoundedPerDonation:
    """Two donations of net 333 each: reserve round_half_up(16.65)=17 per donation,
    summed to 34 (NOT round_half_up(666*0.05)=33). raised 666, provisional 632."""

    def test_reserve_total_is_per_donation_then_summed(self, api):
        """PRD §2.5: "A structural rule governs any reserve total spanning multiple
        donations: the reserve is rounded per donation and then summed, never computed by
        multiplying a summed net figure by the reserve rate."

        Design: Difficulty/combinatorial_formula/campaign_reserve_round_per_donation
        """
        b = setup_published_campaign(api)
        camp_id = b["campaign"]["id"]
        donor_id = b["donor"]["id"]
        make_donation(api, camp_id, donor_id, 333)
        make_donation(api, camp_id, donor_id, 333)
        camp = get_campaign(api, camp_id)
        assert camp["reserve_total_cents"] == 34, (
            f"round_half_up(16.65)=17 per donation, summed to 34, "
            f"got {camp['reserve_total_cents']}"
        )

    def test_provisional_uses_per_donation_reserve(self, api):
        """PRD §2.6: "Provisional (optimistic) availability, provisional_available_cents,
        equals raised_cents minus reserve_total_cents minus committed_cents. It ignores
        open disputes and active holds."

        Design: Difficulty/combinatorial_formula/campaign_reserve_round_per_donation
        """
        b = setup_published_campaign(api)
        camp_id = b["campaign"]["id"]
        donor_id = b["donor"]["id"]
        make_donation(api, camp_id, donor_id, 333)
        make_donation(api, camp_id, donor_id, 333)
        camp = get_campaign(api, camp_id)
        assert camp["provisional_available_cents"] == 632, (
            f"raised 666 - reserve 34 - committed 0 = 632, "
            f"got {camp['provisional_available_cents']}"
        )
