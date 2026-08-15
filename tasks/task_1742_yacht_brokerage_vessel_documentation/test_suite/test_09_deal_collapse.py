"""Deal collapse: offer-fail kick-out cascade, escrow refund obligation, and
contingency deadline enforcement."""
from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    list_offer_contingencies,
    listing_headers,
    record_cleared_deposit,
    selling_headers,
    set_clock,
    setup_accepted_offer,
    validate_error,
    validate_success,
)

ESCROW = TEST_USERS["escrow_officer_headers"]


def _iso_plus_days(iso: str, days: int) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestOfferFailCascade:
    def test_unresolved_objection_collapse_reactivates_listing_and_refunds(self, api):
        """PRD §3.5: "once at least one contingency on the accepted offer stands
        OBJECTED with its objection unresolved for at least five days, or has
        already EXPIRED, the selling side may collapse the deal, moving the offer
        from ACCEPTED to FAILED. That collapse cascades — the listing is kicked
        back from UNDER_CONTRACT to ACTIVE with a LISTING_REACTIVATED event, the
        offer's `version` bumps, and every cleared deposit on the offer becomes
        obligated toward refund."
        PRD §3.6: "Refund is the EscrowOfficer's action, moving a CLEARED entry to
        REFUNDED whenever the parent offer stands FAILED, WITHDRAWN, EXPIRED, or
        REJECTED"

        Design: Difficulty/transitive_cascade/offer_fail_cascades_listing_reactivate_and_escrow_refund
        """
        deal = setup_accepted_offer(offer_price_cents=190000000,
                                    list_price_cents=200000000)
        entry = record_cleared_deposit(deal, amount_cents=19000000)
        contingencies = list_offer_contingencies(deal)
        objected = contingencies[0]
        validate_success(
            api.object_contingency(
                objected["id"],
                {"objection_note": "Survey found hull blistering"},
                selling_headers(deal),
            )
        )
        for c in contingencies[1:]:
            validate_success(api.waive_contingency(c["id"], selling_headers(deal)))

        # Objection lodged at the fixture clock 2026-08-02; six days later the
        # five-day cure window has elapsed and the sweep expires the objection.
        set_clock("2026-08-08T00:00:00Z")
        after_sweep = get_success_data(
            api.list_contingencies(deal["offer"]["id"], selling_headers(deal))
        )
        target = [c for c in after_sweep if c["id"] == objected["id"]][0]
        assert target["status"] == "EXPIRED"

        failed = validate_success(
            api.fail_offer(deal["offer"]["id"], selling_headers(deal)), 200
        )
        assert failed["status"] == "FAILED"
        listing = get_success_data(
            api.get_listing(deal["listing"]["id"], listing_headers(deal))
        )
        assert listing["status"] == "ACTIVE", "kick-out reactivation to ACTIVE"

        refunded = validate_success(api.refund_escrow_entry(entry["id"], ESCROW))
        assert refunded["status"] == "REFUNDED"

    def test_lapsed_open_contingency_deadline_arms_collapse(self, api):
        """PRD §3.5: "Either form of expiry is what arms the deal's kick-out:
        once at least one contingency on the accepted offer stands OBJECTED with
        its objection unresolved for at least five days, or has already EXPIRED,
        the selling side may collapse the deal, moving the offer from ACCEPTED to
        FAILED." and "the same sweep expires an OPEN contingency whose `deadline`
        passes unactioned"

        Design: Difficulty/transitive_cascade/offer_fail_cascades_listing_reactivate_and_escrow_refund
        """
        deal = setup_accepted_offer(offer_price_cents=190000000,
                                    list_price_cents=200000000)
        contingencies = list_offer_contingencies(deal)
        expiring = contingencies[0]
        for c in contingencies[1:]:
            validate_success(api.waive_contingency(c["id"], selling_headers(deal)))

        set_clock(_iso_plus_days(expiring["deadline"], 1))
        after_sweep = get_success_data(
            api.list_contingencies(deal["offer"]["id"], selling_headers(deal))
        )
        target = [c for c in after_sweep if c["id"] == expiring["id"]][0]
        assert target["status"] == "EXPIRED", (
            "an OPEN contingency whose deadline passes unactioned is swept EXPIRED"
        )

        failed = validate_success(
            api.fail_offer(deal["offer"]["id"], selling_headers(deal)), 200
        )
        assert failed["status"] == "FAILED"
        listing = get_success_data(
            api.get_listing(deal["listing"]["id"], listing_headers(deal))
        )
        assert listing["status"] == "ACTIVE"


def test_satisfy_after_deadline_rejected(api):
    """PRD §3.5: "Satisfaction, waiver, and objection are all available only
    while the contingency is OPEN, the clock has not passed its `deadline`, and
    the parent offer still stands ACCEPTED." and "the same sweep expires an OPEN
    contingency whose `deadline` passes unactioned"
    PRD §2.8: "does the server ask whether the target resource's current state
    permits the requested transition, rejecting with `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/contingency_satisfy_after_deadline_rejected
    """
    deal = setup_accepted_offer()
    contingencies = list_offer_contingencies(deal)
    target = contingencies[0]
    set_clock(_iso_plus_days(target["deadline"], 1))
    after_sweep = get_success_data(
        api.list_contingencies(deal["offer"]["id"], selling_headers(deal))
    )
    swept = [c for c in after_sweep if c["id"] == target["id"]][0]
    assert swept["status"] == "EXPIRED"

    res = api.satisfy_contingency(target["id"], selling_headers(deal))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
