"""The pinned return-settlement waterfall and the cent it must conserve."""

from test_helpers import (
    ADMIN_HEADERS,
    assert_cents,
    assert_units_equal,
    fixtures as fx,
    validate_success,
)

DOORSTEP = "2026-08-20T16:00:00Z"
WINE_UNIT_PRICE_CENTS = 6800
GROSS_CENTS = 20400
DELIVERY_FEE_CENTS = 600
CHARGED_CENTS = 21000


def _refused_order_worth_twenty_thousand(api):
    """Three bottles at 6800 cents apiece, refused at the door for impairment.

    The gross refundable figure is therefore 20400 cents, which lands in the
    highest restocking tier, and the charge frozen at submission is 21000 cents.
    """
    world = fx.build_restricted_world(api, policy_overrides={"unit_scale_factor": 1.15})
    built = fx.build_returning_order(
        api,
        world,
        "INTOXICATED_RECIPIENT",
        quantity=3,
        started_at=DOORSTEP,
        scheduled_delivery_at=DOORSTEP,
        delivery_fee_cents=DELIVERY_FEE_CENTS,
    )
    built["world"] = world
    return built


def test_01_the_restocking_tier_is_keyed_on_the_pre_fee_gross(api):
    """PRD 3.7: "Third, the restocking tier is looked up **from that gross figure**
    and from nothing else: a gross below 5000 cents attracts no restocking fee at
    all, a gross of 5000 or more but below 20000 cents attracts 500 basis points,
    and a gross of 20000 cents or more attracts 800 basis points."

    Design: Difficulty/combinatorial_formula/return_settlement_restocking_tier_keyed_on_pre_fee_gross
    """
    built = _refused_order_worth_twenty_thousand(api)
    order_id = built["order"]["id"]
    before = fx.read_order(api, order_id)
    assert_cents(before["item_subtotal_cents"], GROSS_CENTS, "item_subtotal_cents")
    assert_cents(before["charged_cents"], CHARGED_CENTS, "charged_cents")

    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    assert_cents(settled["restocking_fee_cents"], 1632, "restocking_fee_cents")


def test_02_the_refund_is_the_gross_minus_the_floored_fee(api):
    """PRD 3.7: "Worked through: an order with `item_subtotal_cents` of 20400 and
    `delivery_fee_cents` of 600 refused for `UNDERAGE_RECIPIENT` takes a gross of
    20400, lands in the 800-basis-point tier, is charged a floored fee of 1632, and
    settles at `refunded_cents` 18768 against `retained_cents` 2232."

    Design: Difficulty/combinatorial_formula/return_settlement_restocking_tier_keyed_on_pre_fee_gross
    """
    built = _refused_order_worth_twenty_thousand(api)
    order_id = built["order"]["id"]

    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    assert_cents(settled["refunded_cents"], 18768, "refunded_cents")
    assert_cents(settled["retained_cents"], 2232, "retained_cents")
    assert int(settled["refunded_cents"]) != 19380, (
        "19380 is the figure a 500-basis-point tier would produce, which is what "
        "keying the tier on anything other than the pre-fee gross would yield"
    )


def test_03_settlement_withdraws_every_line_and_releases_the_units(api):
    """PRD 3.7: "Every line of the order moves `line_state` `INCLUDED →
    WITHDRAWN`, the order's `final_restricted_units` is reset to 0.00, and the
    order's `fulfillment_state` advances `RETURN_IN_TRANSIT → RETURN_COMPLETED`."

    Design: Difficulty/combinatorial_formula/return_settlement_restocking_tier_keyed_on_pre_fee_gross
    """
    built = _refused_order_worth_twenty_thousand(api)
    order_id = built["order"]["id"]

    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    assert settled["fulfillment_state"] == "RETURN_COMPLETED"
    assert_units_equal(settled["final_restricted_units"], 0.00, "final_restricted_units")
    line = validate_success(api.get_order_line(built["line"]["id"], ADMIN_HEADERS))
    assert line["line_state"] == "WITHDRAWN"


# ===========================================================================
# The conservation invariant the waterfall exists to satisfy
# ===========================================================================
def test_04_every_charged_cent_is_either_refunded_or_retained(api):
    """PRD 2.9: "And every return settlement preserves an exact invariant: the
    amount returned to the customer in `refunded_cents` plus the amount kept in
    `retained_cents` equals the order's frozen `charged_cents`, exactly, with no
    tolerance."

    Design: Difficulty/compensating_invariant/return_settlement_conserves_every_charged_cent
    """
    built = _refused_order_worth_twenty_thousand(api)
    order_id = built["order"]["id"]
    charged_at_submit = int(fx.read_order(api, order_id)["charged_cents"])
    assert_cents(charged_at_submit, CHARGED_CENTS, "charged_cents at submit")

    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    refunded = int(settled["refunded_cents"])
    retained = int(settled["retained_cents"])
    assert refunded + retained == charged_at_submit, (
        "the settlement must conserve the frozen charge exactly; "
        f"{refunded} + {retained} is not {charged_at_submit}"
    )


def test_05_the_retained_amount_is_the_fee_plus_the_unrefunded_delivery_charge(api):
    """PRD 3.7: "Fifth, the delivery fee is refunded only when the platform was at
    fault: a `COURIER_FAULT` refusal refunds the order's `delivery_fee_cents` in
    full, and every other reason refunds none of it."

    Design: Difficulty/compensating_invariant/return_settlement_conserves_every_charged_cent
    """
    built = _refused_order_worth_twenty_thousand(api)
    order_id = built["order"]["id"]

    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    retained = int(settled["retained_cents"])
    fee = int(settled["restocking_fee_cents"])
    assert retained == fee + DELIVERY_FEE_CENTS, (
        "an impairment refusal is not platform fault, so the delivery fee stays with "
        f"the platform alongside the restocking fee; {retained} is not {fee} + "
        f"{DELIVERY_FEE_CENTS}"
    )


def test_06_the_frozen_charge_and_subtotal_survive_the_settlement(api):
    """PRD 3.7: "Finally the settlement is written: `refunded_cents` is the gross
    figure minus `restocking_fee_cents` plus any refunded delivery fee, and
    `retained_cents` is the order's `charged_cents` minus `refunded_cents`, which
    makes the conservation invariant of 2.9 hold by construction."

    Design: Difficulty/compensating_invariant/return_settlement_conserves_every_charged_cent
    """
    built = _refused_order_worth_twenty_thousand(api)
    order_id = built["order"]["id"]

    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    assert_cents(settled["charged_cents"], CHARGED_CENTS, "charged_cents")
    assert_cents(settled["item_subtotal_cents"], GROSS_CENTS, "item_subtotal_cents")
    assert int(settled["retained_cents"]) == CHARGED_CENTS - int(settled["refunded_cents"])
