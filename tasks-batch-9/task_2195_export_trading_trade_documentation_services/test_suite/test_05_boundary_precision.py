"""Inclusive ceilings, exclusive floors, and the empty-collection guard."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    OPS_ALICE,
    ApiErrorId,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

Json = Dict[str, Any]


def _sailing_filled_to_the_last_kilogram(api) -> Json:
    """600 kg already booked, then a 400 kg request against a 1,000 kg sailing."""
    ctx = fx.cleared_order(api)
    ctx = fx.booked_order(
        api,
        base=ctx,
        sailing_overrides={"capacity_weight_kg": 1000.000},
        booking_overrides={"booked_weight_kg": 600.000, "container_type": "LCL"},
    )
    ctx_a = fx.cleared_order_for_buyer(api, ctx["buyer"])
    ctx["order_a_id"] = ctx_a["order_id"]
    ctx["attempt"] = api.create_booking(
        f.booking_payload(
            ctx_a["order_id"],
            ctx["sailing_id"],
            fx.sailing_version(api, ctx["sailing_id"]),
            booked_weight_kg=400.000,
            container_type="LCL",
        ),
        OPS_ALICE,
    )
    return ctx


class TestSailingCapacityIsInclusive:
    def test_booking_landing_exactly_on_capacity_is_accepted(self, api):
        """PRD §2.11: "The sailing's current `booked_weight_kg` plus the requested
        `booked_weight_kg` is at most `capacity_weight_kg`, with equality accepted
        and only strict excess rejected, on freight booking"

        Design: Difficulty/boundary_precision_check/sailing_capacity_accepts_booking_that_lands_exactly_on_capacity_and_flips_to_full
        """
        ctx = _sailing_filled_to_the_last_kilogram(api)
        booking = validate_success(ctx["attempt"], 201)

        assert booking["status"] == "BOOKED"
        assert booking["booked_weight_kg"] == approx_weight(400.000)

    def test_sailing_flips_to_full_at_exactly_its_capacity(self, api):
        """PRD §3.6: "note the capacity gate uses a strict excess while the `FULL`
        posture uses at-or-above, so a sailing booked to exactly its capacity is
        accepted **and** becomes `FULL`."

        Design: Difficulty/boundary_precision_check/sailing_capacity_accepts_booking_that_lands_exactly_on_capacity_and_flips_to_full
        """
        ctx = _sailing_filled_to_the_last_kilogram(api)
        validate_success(ctx["attempt"], 201)

        sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert sailing["booked_weight_kg"] == approx_weight(1000.000)
        assert sailing["status"] == "FULL"


# ---------------------------------------------------------------------------
# The empty shipment-line collection
# ---------------------------------------------------------------------------


def _order_with_no_lines(api) -> Json:
    buyer = fx.create_buyer(api)
    order = fx.create_order(api, buyer["id"])
    return {
        "buyer_id": buyer["id"],
        "order_id": order["id"],
        "attempt": api.submit_for_compliance(order["id"], OPS_ALICE),
    }


class TestEmptyShipmentLineCollection:
    def test_compliance_submission_on_a_lineless_order_is_rejected(self, api):
        """PRD §2.11: "an order has at least one shipment line before compliance
        submission (`ERR_NO_SHIPMENT_LINES`)"

        Design: Difficulty/boundary_precision_check/compliance_submission_rejected_on_empty_shipment_line_collection
        """
        ctx = _order_with_no_lines(api)
        validate_error(ctx["attempt"], ApiErrorId.ERR_NO_SHIPMENT_LINES.value)

    def test_rejected_submission_opens_no_screening_and_holds_the_order_in_draft(
        self, api
    ):
        """PRD §3.2: "The submission creates exactly one screening for the order,
        with `status` `INITIATED` and `ruleset_version` 1, recomputes
        `ordered_goods_value_usd` from the lines, and increments the order's
        `version` by one."

        Design: Difficulty/boundary_precision_check/compliance_submission_rejected_on_empty_shipment_line_collection
        """
        ctx = _order_with_no_lines(api)

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="DRAFT", settlement="UNSECURED")
        assert order["ordered_goods_value_usd"] == approx_money(0.00)

        assert (
            fx.rows(
                api.list_screenings(
                    COMPLIANCE_CARL, {"export_order_id": ctx["order_id"]}
                )
            )
            == []
        )
        buyer = fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))
        assert buyer["open_order_count"] == 1


# ---------------------------------------------------------------------------
# The tier-one exposure ceiling is inclusive
# ---------------------------------------------------------------------------


def _policy_at_the_tier_one_ceiling(api) -> Json:
    buyer = fx.create_buyer(api, credit_rating="AAA")
    policy = fx.create_policy(
        api,
        buyer["id"],
        credit_limit_usd=250000.00,
        insured_pct=90.00,
        deductible_usd=5000.00,
    )
    return {"buyer_id": buyer["id"], "policy": policy}


class TestTierOneCeilingIsInclusive:
    def test_basis_of_exactly_two_hundred_fifty_thousand_stays_in_tier_one(self, api):
        """PRD §3.8: "Both ceilings are inclusive, so a basis of exactly
        250,000.00 is `TIER_1` and exactly 1,000,000.00 is `TIER_2`."

        Design: Difficulty/boundary_precision_check/insurance_tier_ceiling_is_inclusive_at_exactly_250000_usd
        """
        ctx = _policy_at_the_tier_one_ceiling(api)

        assert ctx["policy"]["exposure_tier"] == "TIER_1"
        assert ctx["policy"]["premium_usd"] == approx_money(1530.00)

    def test_new_policy_starts_with_its_whole_limit_available_and_no_buyer_exposure(
        self, api
    ):
        """PRD §3.8: "Persist the policy with `utilized_usd` 0.00,
        `available_limit_usd` equal to `credit_limit_usd`, `indemnified_total_usd`
        0.00 and `status` `ACTIVE`"

        Design: Difficulty/boundary_precision_check/insurance_tier_ceiling_is_inclusive_at_exactly_250000_usd
        """
        ctx = _policy_at_the_tier_one_ceiling(api)

        assert ctx["policy"]["utilized_usd"] == approx_money(0.00)
        assert ctx["policy"]["available_limit_usd"] == approx_money(250000.00)
        assert ctx["policy"]["indemnified_total_usd"] == approx_money(0.00)
        assert ctx["policy"]["status"] == "ACTIVE"

        buyer = fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))
        assert buyer["aggregate_exposure_usd"] == approx_money(0.00)
