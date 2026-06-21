"""Compensating-action invariants: a refund must return every ledger total it
touched to its pre-acknowledgement value.

Difficulty queue: compensating_invariant.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_open_campaign, create_donor, setup_household_with_members,
    record_gift, acknowledge_gift, create_acknowledged_gift,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


class TestRefundConservation:
    def test_refund_conserves_campaign_raised_hard(self, api):
        """PRD §3.9: "A permitted refund moves the gift to `REFUNDED` (terminal) and
        runs the full compensating cascade ... it recomputes the campaign's
        `raised_hard_cents` and `raised_with_match_cents`". PRD §3.4: "A donor's
        `lifetime_hard_credit_cents` is the sum of `amount_cents` over that donor's
        gifts whose `status` is either `ACKNOWLEDGED` or `RECEIPTED`."

        acknowledge(+7000) then refund(-7000) returns raised_hard_cents to 0.

        Design: Difficulty/compensating_invariant/refund_conserves_campaign_raised_hard
        """
        camp = create_open_campaign(goal_cents=1000000)
        donor = create_donor()
        gift = record_gift(camp["id"], donor["id"], amount_cents=7000)
        acked = acknowledge_gift(gift["id"])

        mid = validate_success(api.get_campaign(camp["id"], CM))
        assert mid["raised_hard_cents"] == 7000, "raised_hard reflects the acknowledged gift"

        validate_success(api.refund_gift(gift["id"], {"expected_gift_version": acked["version"]}, GA))
        final = validate_success(api.get_campaign(camp["id"], CM))
        assert final["raised_hard_cents"] == 0, "refund returns raised_hard_cents to its pre-ack value"
        assert final["raised_with_match_cents"] == 0, "with-match total also returns to 0"

    def test_refund_conserves_donor_lifetime_credit(self, api):
        """PRD §3.4: "The figure is recomputed at every acknowledgement (which adds the
        newly acknowledged gift) and at every refund (which subtracts the refunded
        gift)."

        Design: Difficulty/compensating_invariant/refund_conserves_campaign_raised_hard
        """
        camp = create_open_campaign(goal_cents=1000000)
        donor = create_donor()
        gift = record_gift(camp["id"], donor["id"], amount_cents=7000)
        acked = acknowledge_gift(gift["id"])
        assert validate_success(api.get_donor(donor["id"], GA))["lifetime_hard_credit_cents"] == 7000

        validate_success(api.refund_gift(gift["id"], {"expected_gift_version": acked["version"]}, GA))
        d = validate_success(api.get_donor(donor["id"], GA))
        assert d["lifetime_hard_credit_cents"] == 0, "refund subtracts the gift back out"
        assert d["giving_status"] == "NONE", "lifetime 0 re-tiers giving_status to NONE"

    def test_refund_conserves_household_soft_credit(self, api):
        """PRD §3.9: "if the donor has a `household_id` it sets `reversed` to true on
        this gift's soft-credit rows and recomputes the household's
        `total_soft_credit_cents` so that conserved household credit returns to its
        pre-acknowledgement value".

        Design: Difficulty/compensating_invariant/refund_conserves_household_soft_credit
        """
        hh, donors = setup_household_with_members(policy="FULL_TO_ALL", member_count=3)
        giver = donors[0]
        camp = create_open_campaign(goal_cents=1000000)
        gift = record_gift(camp["id"], giver["id"], amount_cents=8000)
        acked = acknowledge_gift(gift["id"])
        assert validate_success(api.get_household(hh["id"], CM))["total_soft_credit_cents"] == 16000

        validate_success(api.refund_gift(gift["id"], {"expected_gift_version": acked["version"]}, GA))
        h = validate_success(api.get_household(hh["id"], CM))
        assert h["total_soft_credit_cents"] == 0, \
            "refund reverses every soft-credit row, returning the household total to 0"

    def test_refund_marks_soft_credit_rows_reversed(self, api):
        """PRD §2.4: "When the originating gift is refunded, a soft-credit row is not
        deleted or re-versioned — instead its `reversed` flag is flipped, and the
        household total is recomputed to exclude reversed rows."

        Design: Difficulty/compensating_invariant/refund_conserves_household_soft_credit
        """
        hh, donors = setup_household_with_members(policy="FULL_TO_ALL", member_count=3)
        giver = donors[0]
        camp = create_open_campaign(goal_cents=1000000)
        gift = record_gift(camp["id"], giver["id"], amount_cents=8000)
        acked = acknowledge_gift(gift["id"])
        validate_success(api.refund_gift(gift["id"], {"expected_gift_version": acked["version"]}, GA))

        data = get_success_data(api.list_gift_soft_credits(gift["id"], GA, params={"limit": 100}))
        rows = data if isinstance(data, list) else data.get("items", data)
        assert len(rows) == 2, "the soft-credit rows are flipped, not deleted"
        for row in rows:
            assert row["reversed"] is True, "every row of the refunded gift is marked reversed"
