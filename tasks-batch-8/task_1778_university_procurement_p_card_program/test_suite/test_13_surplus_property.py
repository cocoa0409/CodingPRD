"""Surplus property: redistribution window, sale floor, proceeds waterfall."""
from test_helpers import (
    ApiErrorId,
    assert_proceeds_conservation,
    assert_surplus_asset,
    create_declared_asset,
    create_department,
    create_listed_asset,
    create_surplus_asset_payload,
    get_success_data,
    make_requester_headers,
    set_clock,
    validate_error,
)
from test_helpers.fixtures import ADMIN, SURPLUS_MANAGER

ADMIN_H = ADMIN
SM = SURPLUS_MANAGER


class TestRedistributionWindow:
    def test_surplus_claim_inside_window_transfers(self, api):
        """PRD §3.9: "During that window, any `Requester` may claim the asset for
        another department by naming a `claiming_department_id`."
        PRD §3.9: "A successful claim moves the asset to `TRANSFERRED`, records
        the claiming department, and creates no proceeds."

        Design: Corner/state_machines/surplus_redistribution_window_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        d1 = create_department(name="ChemStore")
        d2 = create_department(name="PhysStore")
        asset = create_declared_asset(
            department_id=d1["id"], asset_tag="AST-10", description="centrifuge",
            condition="FAIR", estimated_value_cents=100000,
        )
        claimed = get_success_data(
            api.claim_surplus_asset(
                asset["id"], {"claiming_department_id": d2["id"]},
                make_requester_headers("req-user-2"),
            )
        )
        assert claimed["status"] == "TRANSFERRED"
        assert claimed["claiming_department_id"] == d2["id"]

        live = get_success_data(api.get_surplus_asset(asset["id"], ADMIN_H))
        assert live["status"] == "TRANSFERRED"
        assert live["claiming_department_id"] == d2["id"]
        # Terminal: the asset can no longer be listed for sale.
        listed = api.list_surplus_asset_for_sale(asset["id"], SM)
        validate_error(listed, ApiErrorId.ERR_SURPLUS_NOT_LISTABLE, 409)

    def test_surplus_window_edge_at_exact_ten_days(self, api):
        """PRD §3.9: "opens a redistribution window that runs from `declared_at`
        up to — but not including — ten days later" and "at or after the window's
        end the claim fails with `ERR_REDISTRIBUTION_WINDOW_EXPIRED`".
        PRD §3.9: "listing before the window ends is rejected with
        `ERR_REDISTRIBUTION_WINDOW_ACTIVE`" — at the exact boundary it is allowed.

        Design: Corner/state_machines/surplus_window_edge_at_exact_ten_days
        """
        set_clock("2026-08-01T00:00:00Z")
        d1 = create_department(name="GeoStore")
        d2 = create_department(name="AstroStore")
        asset = create_declared_asset(
            department_id=d1["id"], asset_tag="AST-11", description="telescope",
            condition="GOOD", estimated_value_cents=100000,
        )
        set_clock("2026-08-11T00:00:00Z")  # exactly declared_at + 10 days
        claim = api.claim_surplus_asset(
            asset["id"], {"claiming_department_id": d2["id"]},
            make_requester_headers("req-user-2"),
        )
        validate_error(claim, ApiErrorId.ERR_REDISTRIBUTION_WINDOW_EXPIRED, 409)
        listed = get_success_data(api.list_surplus_asset_for_sale(asset["id"], SM))
        assert listed["status"] == "LISTED"


class TestProceedsWaterfall:
    def test_waterfall_rounding_remainder_lands_central(self, api):
        """PRD §3.9: "first, cost recovery returns `min(disposal_cost_cents,
        sale_price_cents)` into `proceeds_cost_recovery_cents`; second, the
        department's share is half of what remains after cost recovery, rounded
        half up to whole cents, stored in `proceeds_dept_share_cents`; third, the
        central share takes the entire remainder into
        `proceeds_central_share_cents`, so the rounding remainder lands centrally
        and the three buckets always sum back to the sale price."

        Design: Difficulty/compensating_invariant/surplus_proceeds_conservation_invariant
        """
        dept = create_department(name="IT")
        asset = create_listed_asset(
            department_id=dept["id"], asset_tag="AST-9", description="projector",
            condition="GOOD", estimated_value_cents=200000,
            disposal_cost_cents=20000,
        )
        sold = get_success_data(
            api.sell_surplus_asset(
                asset["id"],
                {"sale_price_cents": 100001, "buyer_name": "Bidder-7"},
                SM,
            )
        )
        assert sold["status"] == "SOLD"
        # min(20,000, 100,001) = 20,000; remainder 80,001;
        # dept = round_half_up(40,000.5) = 40,001; central absorbs 40,000.
        assert sold["proceeds_cost_recovery_cents"] == 20000
        assert sold["proceeds_dept_share_cents"] == 40001
        assert sold["proceeds_central_share_cents"] == 40000
        assert_proceeds_conservation(sold)

    def test_waterfall_cost_recovery_min_binding(self, api):
        """PRD §3.9: "first, cost recovery returns `min(disposal_cost_cents,
        sale_price_cents)` into `proceeds_cost_recovery_cents`" — when the
        disposal cost exceeds the sale price, cost recovery caps at the price
        and no further shares exist; "the three buckets always sum back to the
        sale price".

        Design: Difficulty/compensating_invariant/surplus_proceeds_conservation_invariant
        """
        dept = create_department(name="IT2")
        asset = create_listed_asset(
            department_id=dept["id"], asset_tag="AST-9B", description="printer",
            condition="FAIR", estimated_value_cents=10000,
            disposal_cost_cents=50000,
        )
        # floor: max(2,500, round_half_up(0.40 * 10,000) = 4,000) = 4,000
        sold = get_success_data(
            api.sell_surplus_asset(
                asset["id"], {"sale_price_cents": 30000, "buyer_name": "B-2"}, SM,
            )
        )
        assert sold["status"] == "SOLD"
        assert sold["proceeds_cost_recovery_cents"] == 30000, (
            "min(50,000 disposal, 30,000 sale) caps at the sale price"
        )
        assert sold["proceeds_dept_share_cents"] == 0
        assert sold["proceeds_central_share_cents"] == 0
        assert_surplus_asset(sold)
        assert_proceeds_conservation(sold)
