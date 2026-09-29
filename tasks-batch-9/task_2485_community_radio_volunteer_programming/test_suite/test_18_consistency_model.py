"""Roll-ups on a parent record, read immediately after a write to its child.

The settlement here touches a pledge, but every figure asserted afterwards lives on
the drive that owns it. An implementation that recomputed those aggregates on a
later schedule would satisfy a pledge-only assertion and fail this one.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import (
    DEVELOPMENT_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
)

CLOCK = "2026-08-01T00:00:00Z"


class TestImmediateRollUp:
    def test_settling_one_pledge_is_visible_on_the_drive_at_once(self):
        """The parent's five aggregates and its attainment share move in the same cycle.

        "The drive's five money aggregates are all recomputed from its pledges
        whenever any of them changes ... `pledged_total_cents` is the sum over pledges
        whose `payment_status` is `PENDING` or `PAID` ... `fulfilled_total_cents` is
        the sum over pledges that are `PAID` ... Finally `attainment_pct` is one
        hundred multiplied by `pledged_total_cents`, divided by `goal_cents`, rounded
        half up to two decimal places". Settlement moves only the payment dimension:
        "An `outcome` of `PAID` moves the pledge `PENDING → PAID`", so the held unit
        stays held.

        Design: Corner/consistency model/drive_roll_ups_reflect_the_settlement_in_the_same_request
        """
        fixtures.set_clock(CLOCK)
        mug = fixtures.create_premium(
            sku="MUG-01",
            name="Station mug",
            tier_threshold_cents=5000,
            fair_market_value_cents=1500,
            units_received_qty=2,
        )
        drive = fixtures.create_active_drive(
            name="Fall Drive 2026",
            goal_cents=500000,
            start_at="2026-08-01T00:00:00Z",
            end_at="2026-08-10T00:00:00Z",
            phone_line_count=2,
        )
        pledge = fixtures.create_pledge(
            drive["id"], donor_name="Marisol Vega", amount_cents=6000, wants_premium=True
        )
        assert pledge["premium_status"] == "RESERVED"
        assert pledge["premium_item_id"] == mug["id"]

        paid = validate_success(
            api_client.settle_pledge(
                pledge["id"],
                factories.pledge_payment_payload(outcome="PAID"),
                DEVELOPMENT_HEADERS,
            ),
            200,
        )
        assert paid["payment_status"] == "PAID"

        rolled_up = validate_success(
            api_client.get_membership_drive(drive["id"], DEVELOPMENT_HEADERS), 200
        )
        assert rolled_up["pledged_total_cents"] == 6000
        assert rolled_up["fulfilled_total_cents"] == 6000
        assert rolled_up["lapsed_total_cents"] == 0
        assert rolled_up["refunded_total_cents"] == 0
        assertions.assert_two_decimals_equal(
            rolled_up["attainment_pct"], 1.20, "attainment_pct"
        )
        assertions.assert_drive_money_partition(rolled_up)

        stock = validate_success(
            api_client.get_premium_item(mug["id"], DEVELOPMENT_HEADERS), 200
        )
        assert stock["reserved_qty"] == 1
