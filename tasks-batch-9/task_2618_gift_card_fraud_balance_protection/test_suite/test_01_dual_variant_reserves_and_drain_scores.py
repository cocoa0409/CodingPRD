"""Two calculations that each carry two variants over the same data.

Period reserves: the provisional variant "pairs a wider alert-state filter with a
higher rate, the final one pairs a narrower filter with a lower rate".
Card drain scores: "they are not two roundings of one number".
"""

from test_helpers import (
    FINAL_RESERVE_RATE_BPS,
    PROVISIONAL_RESERVE_RATE_BPS,
    expected_inquiry_drain_score,
    expected_redemption_drain_score,
    expected_reserve,
)
from test_helpers.assertions import assert_empty
from test_helpers.fixtures import (
    close_period,
    create_rack,
    create_store,
    funded_physical_card,
    inquire,
    open_alert,
    open_period,
    read_alert,
    read_card,
    redeem,
    resolve_alert,
    restate_period,
    triage_alert,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_risk_manager_headers,
)


def _three_alerted_cards(client):
    """One store, one rack, three ACTIVE cards of 10001, 20003 and 30007 cents, and one
    alert per card left OPEN, TRIAGED and CONFIRMED respectively."""
    store = create_store(client, name="Riverbend Market", region_code="NW")
    rack = create_rack(client, store["id"], rack_label="RACK-A", expected_card_count=10)
    cards = []
    for face_value in (10001, 20003, 30007):
        built = funded_physical_card(client, face_value, store=store, rack=rack)
        cards.append(built["card"])
    period = open_period(client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", label="2026-08")

    analyst = make_fraud_analyst_headers("analyst-1")
    risk = make_risk_manager_headers("risk-1")
    alert_a = open_alert(client, cards[0]["id"], "MANUAL_REVIEW", headers=analyst)
    alert_b = open_alert(client, cards[1]["id"], "MANUAL_REVIEW", headers=analyst)
    triage_alert(client, alert_b["id"], headers=analyst)
    alert_c = open_alert(client, cards[2]["id"], "MANUAL_REVIEW", headers=analyst)
    triage_alert(client, alert_c["id"], headers=analyst)
    resolve_alert(client, alert_c["id"], "CONFIRM", headers=risk)
    return {
        "store": store,
        "cards": cards,
        "period": period,
        "alerts": [alert_a, alert_b, alert_c],
    }


class TestPeriodReserveVariants:
    """The two reserve variants on one LiabilityPeriod."""

    def test_provisional_reserve_uses_the_wide_alert_basis_at_the_higher_rate(self, client):
        """Closing books the provisional reserve over alerts "whose state is OPEN,
        TRIAGED or CONFIRMED", where "gross_exposure_cents is the sum of exposure_cents
        over that basis, reserve_basis_alert_count is its cardinality, and
        provisional_reserve_cents is provisional_reserve_rate_bps applied to
        gross_exposure_cents, rounded half-up once over the aggregate rather than per
        alert".  Each alert's exposure is "the card's current_balance_cents plus its
        total_redeemed_cents", so an unredeemed card's exposure is its face value.

        Design: Difficulty/dual_variant_calc/reserve_provisional_vs_final_basis_and_rate_on_liability_period
        """
        world = _three_alerted_cards(client)
        alerts = [read_alert(client, alert["id"]) for alert in world["alerts"]]
        assert [alert["exposure_cents"] for alert in alerts] == [10001, 20003, 30007]

        closed = close_period(client, world["period"]["id"], close_note="provisional close")

        assert closed["state"] == "CLOSED"
        assert closed["gross_exposure_cents"] == 60011
        assert closed["reserve_basis_alert_count"] == 3
        assert closed["provisional_reserve_cents"] == 21004
        assert closed["provisional_reserve_cents"] == expected_reserve(
            60011, PROVISIONAL_RESERVE_RATE_BPS
        )
        assert_empty(closed["final_reserve_cents"], "final_reserve_cents")
        assert closed["outstanding_liability_cents"] == 60011

    def test_final_reserve_narrows_to_confirmed_alerts_at_the_lower_rate(self, client):
        """Restating narrows "the basis ... to in-period alerts whose state is exactly
        CONFIRMED", and "final_reserve_cents is final_reserve_rate_bps applied to the
        recomputed gross_exposure_cents".  A restatement "overwrites
        gross_exposure_cents, reserve_basis_alert_count and
        outstanding_liability_cents, but it never overwrites
        provisional_reserve_cents".

        Design: Difficulty/dual_variant_calc/reserve_provisional_vs_final_basis_and_rate_on_liability_period
        """
        world = _three_alerted_cards(client)
        closed = close_period(client, world["period"]["id"], close_note="provisional close")

        restated = restate_period(
            client,
            world["period"]["id"],
            closed["version"],
            restatement_note="final basis after confirmation",
        )

        assert restated["state"] == "RESTATED"
        assert restated["gross_exposure_cents"] == 30007
        assert restated["reserve_basis_alert_count"] == 1
        assert restated["final_reserve_cents"] == 3001
        assert restated["final_reserve_cents"] == expected_reserve(30007, FINAL_RESERVE_RATE_BPS)
        assert restated["provisional_reserve_cents"] == 21004
        assert restated["restatement_count"] == 1

    def test_the_two_reserve_figures_are_not_one_scaled_from_the_other(self, client):
        """"neither can be derived from the other by any single scale factor" — on one
        population the same period stores 21004 against 3001, a difference of 18003,
        because the basis narrows from three alerts to one at the same time as the rate
        drops from 3500 to 1000 basis points.

        Design: Difficulty/dual_variant_calc/reserve_provisional_vs_final_basis_and_rate_on_liability_period
        """
        world = _three_alerted_cards(client)
        closed = close_period(client, world["period"]["id"])
        restated = restate_period(client, world["period"]["id"], closed["version"])

        provisional = restated["provisional_reserve_cents"]
        final = restated["final_reserve_cents"]
        assert provisional != final
        assert provisional - final == 18003
        assert expected_reserve(30007, PROVISIONAL_RESERVE_RATE_BPS) != final


class TestCardDrainScoreVariants:
    """The inquiry-weighted and redemption-weighted drain scores on one GiftCard."""

    def _drained_card(self, client):
        """A 20000-cent card with three 4000-cent redemptions across two merchants and
        three inquiries: balance 8000, redeemed 12000, drawdown 0.60, merchants 2,
        recent redemptions 3, velocity 3."""
        store1 = create_store(client, name="Harbor Plaza", region_code="NE")
        store2 = create_store(client, name="Westgate Annex", region_code="NE")
        built = funded_physical_card(client, 20000, store=store1)
        card_id = built["card"]["id"]
        redeem(client, card_id, 4000, store1["id"], memo="leg 1")
        redeem(client, card_id, 4000, store2["id"], memo="leg 2")
        redeem(client, card_id, 4000, store1["id"], memo="leg 3")
        inquire(client, card_id, "IVR")
        inquire(client, card_id, "IVR")
        third = inquire(client, card_id, "IVR")
        return {"card_id": card_id, "third_inquiry": third}

    def test_inquiry_weighted_variant_reads_velocity_drawdown_and_merchants(self, client):
        """The inquiry-weighted score "is recomputed on every balance inquiry, written to
        the card's drain_risk_score_inquiry and copied onto the inquiry row as
        drain_score_at_inquiry.  Its raw figure is 12 points per inquiry in the current
        velocity count, plus 30 multiplied by the card's drawdown_ratio, plus 5 points
        per entry in distinct_merchant_count."

        Design: Difficulty/dual_variant_calc/drain_score_inquiry_vs_redemption_variant_on_gift_card
        """
        built = self._drained_card(client)
        card = read_card(client, built["card_id"])

        assert built["third_inquiry"]["velocity_count_at_inquiry"] == 3
        assert float(card["drawdown_ratio"]) == 0.60
        assert card["distinct_merchant_count"] == 2
        assert card["recent_redemption_count"] == 3
        assert card["current_balance_cents"] == 8000
        assert card["total_redeemed_cents"] == 12000

        assert built["third_inquiry"]["drain_score_at_inquiry"] == 64
        assert card["drain_risk_score_inquiry"] == 64
        assert card["drain_risk_score_inquiry"] == expected_inquiry_drain_score(3, 0.60, 2)

    def test_redemption_weighted_variant_is_recomputed_on_triage_only(self, client):
        """The redemption-weighted score "is recomputed when an alert on the card is
        triaged, written to the card's drain_risk_score_redemption and copied into the
        alert's basis_drain_score.  Its raw figure is 45 multiplied by the card's
        drawdown_ratio, plus 14 points per entry in distinct_merchant_count, plus 6
        points per event in recent_redemption_count.  It ignores inquiry velocity
        entirely."

        Design: Difficulty/dual_variant_calc/drain_score_inquiry_vs_redemption_variant_on_gift_card
        """
        built = self._drained_card(client)
        alert = open_alert(
            client,
            built["card_id"],
            "REDEMPTION_PATTERN",
            headers=make_fraud_analyst_headers("analyst-7"),
            note="three legs across two merchants",
        )

        triaged = triage_alert(
            client, alert["id"], headers=make_fraud_analyst_headers("analyst-7")
        )

        assert triaged["state"] == "TRIAGED"
        assert triaged["basis_drain_score"] == 73
        assert triaged["basis_drain_score"] == expected_redemption_drain_score(0.60, 2, 3)
        card = read_card(client, built["card_id"])
        assert card["drain_risk_score_redemption"] == 73

    def test_both_scores_live_side_by_side_and_the_higher_one_drives_the_posture(self, client):
        """"a card normally carries two different live scores at once", and the freshly
        recomputed one drives the ladder: a score "at or above
        drain_restrict_score_threshold" targets RESTRICTED and applies "only when the
        target sits strictly higher on the ladder than the card's current rung".

        Design: Difficulty/dual_variant_calc/drain_score_inquiry_vs_redemption_variant_on_gift_card
        """
        built = self._drained_card(client)
        alert = open_alert(
            client, built["card_id"], "REDEMPTION_PATTERN", headers=make_fraud_analyst_headers("analyst-7")
        )
        triage_alert(client, alert["id"], headers=make_fraud_analyst_headers("analyst-7"))

        card = read_card(client, built["card_id"])
        assert card["drain_risk_score_inquiry"] == 64
        assert card["drain_risk_score_redemption"] == 73
        assert card["drain_risk_score_redemption"] - card["drain_risk_score_inquiry"] == 9
        assert card["risk_posture"] == "RESTRICTED"
