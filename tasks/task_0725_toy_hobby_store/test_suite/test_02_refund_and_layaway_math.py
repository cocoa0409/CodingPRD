"""Return refund tiering and layaway installment rounding."""
from test_helpers import (
    validate_success,
    create_customer, setup_fulfilled_order_with_return,
    TEST_USERS,
)

MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]


def test_refund_fee_tier_keyed_on_gross_at_20000(api):
    """PRD §3.13: "Next the restocking-fee tier is looked up from `gross_refund_cents`: a
    gross below 5000 cents incurs no fee, a gross from 5000 through 19999 cents incurs 10
    percent, and a gross of 20000 cents or more incurs 15 percent."
    PRD §3.13: "The `net_refund_cents` is `gross_refund_cents` minus `restocking_fee_cents`."

    Design: Difficulty/combinatorial_formula/return_refund_circular_fee_tier_keyed_on_gross
    """
    ctx = setup_fulfilled_order_with_return(msrp_cents=2000, qty=10, on_hand_qty=50)
    data = validate_success(api.approve_return(ctx["ret"]["id"], {"decision": "APPROVE"}, MANAGER))
    assert data["gross_refund_cents"] == 20000
    assert data["restocking_fee_cents"] == 3000, "gross 20000 -> tier3 0.15 -> fee 3000"
    assert data["net_refund_cents"] == 17000


def test_refund_gross_computed_before_fee_tier(api):
    """PRD §3.13: "First the gross refund is accumulated over the returned lines: for each
    returned line, the line's effective total after discount is `extended_cents` minus
    `line_discount_cents`, the effective paid amount per unit is that effective total
    divided by the line's `qty` rounded down, and the contribution is the per-unit amount
    multiplied by the returned quantity; `gross_refund_cents` is the sum of these
    contributions."

    Design: Difficulty/combinatorial_formula/return_refund_circular_fee_tier_keyed_on_gross
    """
    # BRONZE, non-exclusive, qty 10 @ 2000 => extended 20000, no discount => gross 20000.
    ctx = setup_fulfilled_order_with_return(msrp_cents=2000, qty=10, on_hand_qty=50)
    data = validate_success(api.approve_return(ctx["ret"]["id"], {"decision": "APPROVE"}, MANAGER))
    assert data["gross_refund_cents"] == 20000
    # net = gross - floor(gross*0.15)
    assert data["net_refund_cents"] == data["gross_refund_cents"] - data["restocking_fee_cents"]


def test_layaway_schedule_floors_with_remainder_on_last_installment(api):
    """PRD §3.9: "the base installment is `total_cents` divided by `installment_count`
    rounded down, every installment is set to that base, and the leftover remainder —
    `total_cents` minus the base times `installment_count` — is added onto the final
    installment so the schedule sums exactly to `total_cents`."

    Design: Difficulty/combinatorial_formula/layaway_installment_rounding_remainder_on_last
    """
    customer = create_customer()
    data = validate_success(
        api.create_layaway(
            {"customer_id": customer["id"], "total_cents": 10000, "installment_count": 3},
            ASSOCIATE),
        expected_status=201,
    )
    assert data["installment_schedule_cents"] == [3333, 3333, 3334]
    assert data["remaining_cents"] == 10000


def test_layaway_schedule_sums_to_total(api):
    """PRD §3.9: "the leftover remainder — `total_cents` minus the base times
    `installment_count` — is added onto the final installment so the schedule sums exactly
    to `total_cents`."

    Design: Difficulty/combinatorial_formula/layaway_installment_rounding_remainder_on_last
    """
    customer = create_customer()
    data = validate_success(
        api.create_layaway(
            {"customer_id": customer["id"], "total_cents": 10000, "installment_count": 3},
            ASSOCIATE),
        expected_status=201,
    )
    assert sum(data["installment_schedule_cents"]) == 10000
