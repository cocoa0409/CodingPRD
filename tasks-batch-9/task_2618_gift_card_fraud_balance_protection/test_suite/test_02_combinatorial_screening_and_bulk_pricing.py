"""Two multi-factor formulas whose evaluation order is load-bearing.

Digital screening: "Each raw signal is first pushed through its own transform, and
only then are the transformed components blended".
Bulk pricing: "fee_rate_bps is selected from that pre-fee subtotal".
"""

from test_helpers import (
    assert_bulk_pricing,
    assert_screening_components,
    expected_bulk_pricing,
    expected_screening_components,
    expected_screening_score,
)
from test_helpers.assertions import assert_empty
from test_helpers.fixtures import (
    create_store,
    open_bulk_order,
    open_digital_issuance,
    read_card,
    screen_issuance,
)

SIGNALS = {
    "device_reputation_score": 42,
    "email_age_days": 45,
    "payment_risk_band": "MEDIUM",
}


class TestDigitalScreeningComposition:
    """One signal set, two outcomes, decided by a post-blend surcharge."""

    def _world(self, client):
        """A store and a 10-card 12500-cent bulk order left in PENDING_IDENTITY, whose
        total of 127813 cents is "at or above bulk_identity_threshold_cents"."""
        store = create_store(client, name="Cedar Point Store", region_code="SE")
        order = open_bulk_order(
            client,
            store["id"],
            card_quantity=10,
            face_value_cents_each=12500,
            purchaser_name="Acme Rewards LLC",
            payment_method="CORPORATE_ACH",
        )
        return {"store": store, "order": order}

    def test_four_nonlinear_transforms_blend_to_the_stored_base(self, client):
        """The device component is "one hundred minus device_reputation_score", the email
        component is "a step function and is emphatically not interpolated", the payment
        component is "a categorical lookup" and the amount component is "a capped
        staircase over face_value_cents".  The four are then blended "with fixed weights
        and rounded, exactly once, half up to an integer: thirty-five hundredths of the
        device component, plus twenty-five hundredths of the email component, plus
        twenty-five hundredths of the payment component, plus fifteen hundredths of the
        amount component."

        Design: Difficulty/combinatorial_formula/digital_issuance_score_nonlinear_component_composition_with_bulk_surcharge
        """
        self._world(client)
        request = open_digital_issuance(
            client, face_value_cents=12500, recipient_email_hash="eh-standalone", **SIGNALS
        )

        screened = screen_issuance(client, request["id"])

        expected = expected_screening_components(42, 45, "MEDIUM", 12500, bulk_surcharge=0)
        assert expected == {
            "device": 58,
            "email": 45,
            "payment": 25,
            "amount": 10,
            "base": 39,
            "bulk_surcharge": 0,
        }
        assert_screening_components(screened, expected)
        assert screened["screening_score"] == 39
        assert screened["state"] == "APPROVED"
        assert_empty(screened["decline_reason"], "decline_reason")

        minted = read_card(client, screened["card_id"])
        assert minted["channel"] == "DIGITAL"
        assert minted["activation_state"] == "ACTIVE"
        assert minted["current_balance_cents"] == 12500
        assert_empty(minted["store_id"], "store_id")

    def test_pending_identity_bulk_surcharge_flips_the_same_signals_into_review(self, client):
        """"When the request carries a bulk_order_id and that bulk order has not yet
        cleared identity — meaning it is still in PENDING_IDENTITY — 15 points are added
        to the base and the result is capped at 100."  A score "at or above
        digital_hold_score_threshold sends it to HELD_FOR_REVIEW", and
        HELD_FOR_REVIEW "produces no funding movement whatsoever — no card is minted on
        the digital side".

        Design: Difficulty/combinatorial_formula/digital_issuance_score_nonlinear_component_composition_with_bulk_surcharge
        """
        world = self._world(client)
        assert world["order"]["state"] == "PENDING_IDENTITY"
        request = open_digital_issuance(
            client,
            face_value_cents=12500,
            recipient_email_hash="eh-bulk",
            bulk_order_id=world["order"]["id"],
            **SIGNALS,
        )

        screened = screen_issuance(client, request["id"])

        expected = expected_screening_components(42, 45, "MEDIUM", 12500, bulk_surcharge=15)
        assert_screening_components(screened, expected)
        assert screened["screening_components"]["base"] == 39
        assert screened["screening_components"]["bulk_surcharge"] == 15
        assert screened["screening_score"] == 54
        assert screened["screening_score"] == expected_screening_score(expected)
        assert screened["state"] == "HELD_FOR_REVIEW"
        assert_empty(screened["card_id"], "card_id")

    def test_the_surcharge_is_applied_after_the_blend_not_before_it(self, client):
        """"The order here is load-bearing: surcharging before the blend would scale
        those 15 points down by the blend weights and produce a different number."  The
        two requests carry identical signals, so the whole 15-point gap is the surcharge:
        39 against 54.

        Design: Difficulty/combinatorial_formula/digital_issuance_score_nonlinear_component_composition_with_bulk_surcharge
        """
        world = self._world(client)
        solo = open_digital_issuance(
            client, face_value_cents=12500, recipient_email_hash="eh-standalone", **SIGNALS
        )
        attached = open_digital_issuance(
            client,
            face_value_cents=12500,
            recipient_email_hash="eh-bulk",
            bulk_order_id=world["order"]["id"],
            **SIGNALS,
        )

        solo_screened = screen_issuance(client, solo["id"])
        attached_screened = screen_issuance(client, attached["id"])

        assert solo_screened["screening_score"] == 39
        assert attached_screened["screening_score"] == 54
        assert attached_screened["screening_score"] - solo_screened["screening_score"] == 15
        # Surcharging the raw signals before the blend would add 0.25 * 15 or similar.
        assert attached_screened["screening_score"] != 39 + round(0.35 * 15)
        assert (
            solo_screened["screening_components"]["base"]
            == attached_screened["screening_components"]["base"]
        )


class TestBulkOrderFeeTier:
    """The fee band is keyed on the subtotal, and the fee is rounded once."""

    def test_fee_tier_is_selected_from_the_pre_fee_subtotal(self, client):
        """"a subtotal of 99900 cents sits in the 150-basis-point band and pays a fee of
        1499 cents (the exact half-cent at 1498.5 rounds up), for a total of 101399
        cents; reading the tier off that total would wrongly place it in the
        225-basis-point band."

        Design: Difficulty/combinatorial_formula/bulk_order_fee_tier_pinned_to_pre_fee_subtotal
        """
        store = create_store(client, name="Northline Depot", region_code="MW")

        order = open_bulk_order(
            client,
            store["id"],
            card_quantity=4,
            face_value_cents_each=24975,
            purchaser_name="Nadia Okonjo",
            payment_method="CREDIT",
        )

        expected = expected_bulk_pricing(4, 24975)
        assert expected == {
            "face_value_subtotal_cents": 99900,
            "fee_rate_bps": 150,
            "activation_fee_cents": 1499,
            "total_cents": 101399,
        }
        assert_bulk_pricing(order, expected)
        assert order["fee_rate_bps"] != 225

    def test_the_activation_fee_is_rounded_once_over_the_whole_order(self, client):
        """"Rounding per card and then multiplying by the quantity is equally wrong,
        because it accumulates up to one half-cent error per card instead of one for the
        whole order."  Four cards each rounding to 375 would give 1500, not 1499.

        Design: Difficulty/combinatorial_formula/bulk_order_fee_tier_pinned_to_pre_fee_subtotal
        """
        store = create_store(client, name="Northline Depot", region_code="MW")

        order = open_bulk_order(
            client, store["id"], card_quantity=4, face_value_cents_each=24975
        )

        assert order["activation_fee_cents"] == 1499
        assert order["activation_fee_cents"] != 4 * 375
        assert order["total_cents"] == 99900 + 1499

    def test_the_order_state_and_identity_fields_fall_out_of_the_total(self, client):
        """"When total_cents is at or above bulk_identity_threshold_cents the order is
        created in PENDING_IDENTITY", with the identity fields still empty and
        info_request_count at 0.

        Design: Difficulty/combinatorial_formula/bulk_order_fee_tier_pinned_to_pre_fee_subtotal
        """
        store = create_store(client, name="Northline Depot", region_code="MW")

        order = open_bulk_order(
            client, store["id"], card_quantity=4, face_value_cents_each=24975
        )

        assert order["total_cents"] == 101399
        assert order["state"] == "PENDING_IDENTITY"
        assert_empty(order["identity_id_number_hash"], "identity_id_number_hash")
        assert_empty(order["identity_id_type"], "identity_id_type")
        assert order["info_request_count"] == 0
