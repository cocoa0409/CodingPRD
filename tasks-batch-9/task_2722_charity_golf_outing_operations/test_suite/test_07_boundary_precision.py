"""Values sitting exactly on a declared threshold, and one step past it."""

import pytest

from test_helpers import (
    DIRECTOR_HEADERS,
    SPONSORSHIP_HEADERS,
    ApiErrorId,
    assert_inventory_conservation,
    assert_rollup_chain,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

TOKEN_OUTING = {"name": "Token Ceiling Cup", "field_capacity_teams": 2, "prize_pool_cents": 0}
TOKEN_TIER = {"code": "TOKEN", "price_cents": 65000, "player_slots": 4, "gsv_cents": 1300}
OVER_TIER = {"code": "OVER", "price_cents": 65000, "player_slots": 4, "gsv_cents": 1301}

FEE_OUTING = {"name": "Fee Ladder Invitational", "field_capacity_teams": 1, "prize_pool_cents": 0}
FEE_CONTRACT = {
    "rate_per_player_cents": 25000,
    "guaranteed_player_count": 4,
    "fnb_minimum_cents": 0,
    "fnb_per_player_cents": 0,
}
EDGE_LOW = {"code": "EDGE_LOW", "price_cents": 2099999, "player_slots": 4, "gsv_cents": 24000}
EDGE_HIGH = {"code": "EDGE_HIGH", "price_cents": 2100000, "player_slots": 4, "gsv_cents": 24000}

CAPACITY_TIER = {
    "code": "GOLD",
    "price_cents": 250000,
    "player_slots": 0,
    "gsv_cents": 0,
    "inventory_cap": 5,
    "entitled_asset_type": "HOLE_SIGN",
    "entitled_asset_count": 2,
}
HOLE_11_SIGN = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 11 tee sign",
    "hole_number": 11,
    "capacity": 1,
    "exclusive": False,
    "list_price_cents": 50000,
}


class TestTokenBenefitCeiling:
    def _two_paid_packages(self, api):
        ctx = fx.open_outing(api, outing=TOKEN_OUTING, contract={"guaranteed_player_count": 0},
                             tier=TOKEN_TIER)
        over = fx.add_tier(api, ctx, **OVER_TIER)
        token_reg = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="On The Line Co", player_count=4
        )
        fx.pay_registration(api, token_reg["id"], 65000)
        over_reg = fx.new_registration(
            api, ctx["outing_id"], over["id"], buyer_name="One Cent Over Co", player_count=4
        )
        fx.pay_registration(api, over_reg["id"], 65000)
        ctx["token_registration_id"] = token_reg["id"]
        ctx["over_registration_id"] = over_reg["id"]
        return ctx

    def test_a_benefit_exactly_on_the_ceiling_is_disregarded_entirely(self, api):
        """The PRD makes the comparison inclusive: "a token ceiling is computed as the
        smaller of 1300 cents" "and two percent of the receipt's `payment_cents` rounded
        half up to whole cents. If the declared benefit is less than or equal to that
        ceiling it is disregarded entirely and the receipt's `gsv_cents` is recorded as
        0", and "A benefit sitting exactly on the ceiling is disregarded, because the
        comparison is inclusive."

        Design: Difficulty/boundary_precision_check/token_benefit_gsv_exactly_on_the_ceiling_is_disregarded
        """
        ctx = self._two_paid_packages(api)

        receipt = fx.issue_registration_receipt(
            api, ctx["outing_id"], ctx["token_registration_id"]
        )
        assert receipt["payment_cents"] == 65000
        assert receipt["gsv_cents"] == 0
        assert receipt["deductible_amount_cents"] == 65000
        assert receipt["receipt_number"] == "GR-0001"
        assert fx.read_registration(api, ctx["token_registration_id"])["receipt_issued"] is True

    def test_one_cent_above_the_ceiling_is_subtracted_in_full(self, api):
        """The PRD carries a benefit past the ceiling at its declared value: "only a
        benefit strictly above the ceiling is carried through at its declared value",
        and "The `deductible_amount_cents` is then the `payment_cents` minus the
        applicable `gsv_cents`, floored at 0 so it is never negative."  Numbering is
        per-outing, so "the first receipt of an outing reads `GR-0001`, the second
        `GR-0002`".

        Design: Difficulty/boundary_precision_check/token_benefit_gsv_exactly_on_the_ceiling_is_disregarded
        """
        ctx = self._two_paid_packages(api)
        fx.issue_registration_receipt(api, ctx["outing_id"], ctx["token_registration_id"])

        receipt = fx.issue_registration_receipt(
            api, ctx["outing_id"], ctx["over_registration_id"]
        )
        assert receipt["payment_cents"] == 65000
        assert receipt["gsv_cents"] == 1301
        assert receipt["deductible_amount_cents"] == 63699
        assert receipt["receipt_number"] == "GR-0002"

        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 128699
        assert fx.read_registration(api, ctx["over_registration_id"])["receipt_issued"] is True


class TestAdminFeeTierBoundary:
    def _package_one_cent_below_the_limit(self, api):
        ctx = fx.open_outing(api, outing=FEE_OUTING, contract=FEE_CONTRACT, tier=EDGE_LOW)
        ctx["high_tier_id"] = fx.add_tier(api, ctx, **EDGE_HIGH)["id"]
        reg = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Edge Case Capital",
            player_count=4,
        )
        ctx["registration"] = fx.pay_registration(api, reg["id"], 2099999)
        ctx["registration_id"] = reg["id"]
        return ctx

    def test_one_cent_below_the_limit_stays_in_the_five_percent_band(self, api):
        """The first fee band is bounded strictly: `admin_fee_pct` is "0.05 when it is
        below 2000000 cents (twenty thousand dollars)", and "`admin_fee_cents` is then
        `admin_fee_pct` multiplied by `gross_revenue_cents`, rounded half up to whole
        cents".

        Design: Difficulty/boundary_precision_check/admin_fee_tier_boundary_at_exactly_two_million_before_fee
        """
        ctx = self._package_one_cent_below_the_limit(api)
        outing = fx.read_outing(api, ctx["outing_id"])

        assert outing["gross_revenue_cents"] == 2099999
        assert outing["course_charge_cents"] == 100000
        assert outing["fnb_shortfall_cents"] == 0
        assert outing["direct_costs_cents"] == 100000
        assert outing["net_proceeds_before_fee_cents"] == 1999999
        assert outing["admin_fee_pct"] == pytest.approx(0.05, abs=0.0001)
        assert outing["admin_fee_cents"] == 105000
        assert outing["net_proceeds_cents"] == 1894999
        assert_rollup_chain(outing)

    def test_landing_exactly_on_the_limit_drops_the_fee_and_lifts_the_net(self, api):
        """Exactly on the limit the next band applies - "0.035 when it is below 5000000
        cents (fifty thousand dollars)" - while the base stays gross revenue, so one
        further cent of revenue raises the net.  The PRD keeps the order: "evaluating
        the tier against the after-fee net would be circular and is forbidden".

        Design: Difficulty/boundary_precision_check/admin_fee_tier_boundary_at_exactly_two_million_before_fee
        """
        ctx = self._package_one_cent_below_the_limit(api)
        before = fx.read_outing(api, ctx["outing_id"])["net_proceeds_cents"]

        amended = validate_success(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(
                    ctx["high_tier_id"], ctx["registration"]["version"], amount_cents=1
                ),
                DIRECTOR_HEADERS,
            )
        )
        assert amended["status"] == "AMENDED"
        assert amended["amount_paid_cents"] == 2100000

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["gross_revenue_cents"] == 2100000
        assert outing["net_proceeds_before_fee_cents"] == 2000000
        assert outing["admin_fee_pct"] == pytest.approx(0.035, abs=0.0001)
        assert outing["admin_fee_cents"] == 73500
        assert outing["net_proceeds_cents"] == 1926500
        assert outing["net_proceeds_cents"] - before == 31501
        assert_rollup_chain(outing)


class TestAssetCapacityBoundary:
    def _asset_with_its_single_slot_reserved(self, api):
        ctx = fx.open_outing(
            api,
            outing={"name": "Capacity Boundary Open", "field_capacity_teams": 1},
            contract={"guaranteed_player_count": 0},
            tier=CAPACITY_TIER,
            sponsor_tier=True,
        )
        first = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="First Sponsor Bank",
            player_count=0,
        )
        fx.pay_registration(api, first["id"], 250000)
        second = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Second Sponsor Trust",
            player_count=0,
        )
        fx.pay_registration(api, second["id"], 250000)

        asset = fx.new_asset(api, ctx["outing_id"], **HOLE_11_SIGN)
        allocation = fx.new_allocation(api, first["id"], asset["id"], "PACKAGE_ENTITLEMENT")
        ctx.update(
            {
                "first_id": first["id"],
                "second_id": second["id"],
                "asset_id": asset["id"],
                "allocation_id": allocation["id"],
            }
        )
        return ctx

    def test_the_first_reservation_consumes_the_only_unit_of_capacity(self, api):
        """Capacity is consumed at reservation: "The unit's `reserved_count` increments
        by one, its `remaining_capacity` is re-derived downward, its posture moves
        `AVAILABLE → RESERVED`, and the outing's `reserved_asset_slot_count`
        increments."

        Design: Difficulty/boundary_precision_check/asset_remaining_capacity_zero_is_a_rejection
        """
        ctx = self._asset_with_its_single_slot_reserved(api)
        assert fx.read_allocation(api, ctx["allocation_id"])["status"] == "RESERVED"

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["reserved_count"] == 1
        assert asset["committed_count"] == 0
        assert asset["fulfilled_count"] == 0
        assert asset["remaining_capacity"] == 0
        assert asset["status"] == "RESERVED"
        assert_inventory_conservation(asset)

        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 1

    def test_a_fully_entitled_second_sponsor_is_refused_at_zero_remaining(self, api):
        """The PRD rejects exactly at the boundary: "the unit's `remaining_capacity` must
        be at least 1, and a live unit sitting exactly on the boundary value of 0 is
        refused with `ERR_ASSET_CAPACITY_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/asset_remaining_capacity_zero_is_a_rejection
        """
        ctx = self._asset_with_its_single_slot_reserved(api)

        validate_error(
            api.create_sponsor_allocation(
                f.sponsor_allocation_payload(
                    ctx["second_id"], ctx["asset_id"], "PACKAGE_ENTITLEMENT"
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.ASSET_CAPACITY_EXCEEDED,
            409,
        )

        assert fx.read_registration(api, ctx["second_id"])["entitled_asset_balance"] == 2
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 1
        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["reserved_count"] == 1
        assert asset["remaining_capacity"] == 0
