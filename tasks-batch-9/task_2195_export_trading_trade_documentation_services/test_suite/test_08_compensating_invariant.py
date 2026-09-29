"""Reversals that must land back on the exact figures they started from."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    OPS_ALICE,
    REVIEWER_BOB,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_success,
)

Json = Dict[str, Any]

EXACT_FOUR_THOUSAND = [{"line_no": 1, "quantity": 16.000, "unit_price_usd": 250.0000}]


def _booked_then_cancelled_against_a_full_sailing(api) -> Json:
    """Fill a sailing to the kilogram and exhaust a licence, then cancel one leg."""
    ctx = fx.licensed_cleared_order(
        api,
        lines=EXACT_FOUR_THOUSAND,
        license_overrides={
            "license_number": "LIC-2195-C",
            "licensed_value_usd": 4000.00,
        },
    )
    ctx["sailing"] = fx.create_sailing(api, capacity_weight_kg=1000.000)
    ctx["sailing_id"] = ctx["sailing"]["id"]

    other = fx.cleared_order(api)
    ctx["order_b_id"] = other["order_id"]
    ctx["booking_b"] = fx.data(
        api.create_booking(
            f.booking_payload(
                other["order_id"],
                ctx["sailing_id"],
                ctx["sailing"]["version"],
                booked_weight_kg=600.000,
                container_type="LCL",
            ),
            OPS_ALICE,
        )
    )
    ctx["booking_a"] = fx.data(
        api.create_booking(
            f.booking_payload(
                ctx["order_id"],
                ctx["sailing_id"],
                fx.sailing_version(api, ctx["sailing_id"]),
                booked_weight_kg=400.000,
                container_type="LCL",
            ),
            OPS_ALICE,
        )
    )
    ctx["sailing_when_full"] = fx.read_sailing(api, ctx["sailing_id"])
    ctx["licence_when_exhausted"] = fx.data(
        api.get_license(ctx["license_id"], COMPLIANCE_CARL)
    )
    ctx["cancel_response"] = api.cancel_booking(
        ctx["booking_a"]["id"],
        {"cancel_reason": "buyer deferred the shipment to the following month"},
        OPS_ALICE,
    )
    return ctx


class TestBookingCancelRestoresBothLedgers:
    def test_cancel_hands_the_sailing_capacity_back_to_its_prior_figure(self, api):
        """PRD §2.12: "A sailing's `booked_weight_kg` always equals the sum of
        `booked_weight_kg` over its bookings whose `status` is `BOOKED`,
        `CONFIRMED` or `SHIPPED`; a `CANCELLED` booking contributes 0.000."

        Design: Difficulty/compensating_invariant/booking_cancel_restores_sailing_weight_and_license_value_to_exact_prior_figures
        """
        ctx = _booked_then_cancelled_against_a_full_sailing(api)
        assert ctx["sailing_when_full"]["booked_weight_kg"] == approx_weight(1000.000)
        assert ctx["sailing_when_full"]["status"] == "FULL"

        cancelled = validate_success(ctx["cancel_response"], 200)
        assert cancelled["status"] == "CANCELLED"

        sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert sailing["booked_weight_kg"] == approx_weight(600.000)
        assert sailing["status"] == "OPEN"

        untouched = fx.data(api.get_booking(ctx["booking_b"]["id"], OPS_ALICE))
        assert untouched["status"] == "BOOKED"
        assert untouched["booked_weight_kg"] == approx_weight(600.000)

    def test_cancel_hands_the_whole_licence_value_back_and_reactivates_it(self, api):
        """PRD §3.6: "A book-then-cancel pair leaves both ledgers at their exact
        prior values."

        Design: Difficulty/compensating_invariant/booking_cancel_restores_sailing_weight_and_license_value_to_exact_prior_figures
        """
        ctx = _booked_then_cancelled_against_a_full_sailing(api)
        assert ctx["licence_when_exhausted"]["consumed_value_usd"] == approx_money(4000.00)
        assert ctx["licence_when_exhausted"]["remaining_value_usd"] == approx_money(0.00)
        assert ctx["licence_when_exhausted"]["status"] == "EXHAUSTED"

        validate_success(ctx["cancel_response"], 200)

        licence = fx.data(api.get_license(ctx["license_id"], COMPLIANCE_CARL))
        assert licence["consumed_value_usd"] == approx_money(0.00)
        assert licence["remaining_value_usd"] == approx_money(4000.00)
        assert licence["status"] == "ACTIVE"

        order = fx.read_order(api, ctx["order_id"])
        assert order["licensed_value_allocated_usd"] == approx_money(0.00)
        assert_order_dimensions(order, fulfillment="COMPLIANCE_CLEARED")


# ---------------------------------------------------------------------------
# Amending an accepted credit releases the insured exposure it charged
# ---------------------------------------------------------------------------

TWENTY_FIVE_THOUSAND = [{"line_no": 1, "quantity": 50.000, "unit_price_usd": 500.0000}]


def _amended_after_the_exposure_was_charged(api) -> Json:
    """Charge a policy through credit acceptance, then amend the credit."""
    ctx = fx.cleared_order(api, lines=TWENTY_FIVE_THOUSAND)
    ctx["policy"] = fx.create_policy(
        api,
        ctx["buyer_id"],
        policy_number="POL-F-2195",
        credit_limit_usd=30000.00,
        insured_pct=90.00,
        deductible_usd=1000.00,
    )
    ctx["policy_id"] = ctx["policy"]["id"]
    ctx = fx.accepted_credit(
        api,
        ctx,
        lc_number="LC-2195-009",
        amount_usd=25000.00,
        tolerance_pct=5.00,
        availability="SIGHT",
    )
    ctx["order_when_secured"] = fx.read_order(api, ctx["order_id"])
    ctx["policy_when_charged"] = fx.read_policy(api, ctx["policy_id"])
    ctx["amend_response"] = api.amend_credit(
        ctx["lc_id"],
        {
            "expected_letter_of_credit_version": fx.credit_version(api, ctx["lc_id"]),
            "amount_usd": 27000.00,
            "tolerance_pct": 3.00,
        },
        OPS_ALICE,
    )
    return ctx


class TestAmendmentReleasesInsuredExposure:
    def test_amendment_returns_the_credit_to_received_and_the_order_to_unsecured(
        self, api
    ):
        """PRD §3.4: "The amendment applies the submitted fields in place,
        increments `amendment_round` by one, recomputes `max_drawable_usd` and
        `min_drawable_usd`, moves the credit back to `RECEIVED`"

        Design: Difficulty/compensating_invariant/lc_amendment_releases_insured_exposure_back_to_the_full_credit_limit
        """
        ctx = _amended_after_the_exposure_was_charged(api)
        assert_order_dimensions(ctx["order_when_secured"], settlement="LC_ACCEPTED")

        credit = validate_success(ctx["amend_response"], 200)
        assert credit["status"] == "RECEIVED"
        assert credit["amendment_round"] == 1
        assert credit["max_drawable_usd"] == approx_money(27810.00)
        assert credit["min_drawable_usd"] == approx_money(26190.00)

        review = fx.data(api.get_terms_review(ctx["review_id"], REVIEWER_BOB))
        assert review["status"] == "SUPERSEDED"

    def test_amendment_hands_the_whole_credit_limit_back_to_the_policy(self, api):
        """PRD §3.4: "Amending from `ACCEPTED` also moves the order's
        `settlement_status` from `LC_ACCEPTED` back to `UNSECURED`, releasing
        insured exposure"

        Design: Difficulty/compensating_invariant/lc_amendment_releases_insured_exposure_back_to_the_full_credit_limit
        """
        ctx = _amended_after_the_exposure_was_charged(api)
        assert ctx["policy_when_charged"]["utilized_usd"] == approx_money(25000.00)
        assert ctx["policy_when_charged"]["available_limit_usd"] == approx_money(5000.00)

        validate_success(ctx["amend_response"], 200)

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, settlement="UNSECURED")
        assert order["insured_exposure_usd"] == approx_money(0.00)

        policy = fx.read_policy(api, ctx["policy_id"])
        assert policy["utilized_usd"] == approx_money(0.00)
        assert policy["available_limit_usd"] == approx_money(30000.00)
        assert policy["status"] == "ACTIVE"

        buyer = fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))
        assert buyer["aggregate_exposure_usd"] == approx_money(0.00)
