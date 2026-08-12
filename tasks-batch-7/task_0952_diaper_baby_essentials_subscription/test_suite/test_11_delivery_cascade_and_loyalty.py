"""Cycle delivery, the six-hop loyalty cascade, redemptions, expiry and tier moves."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_points_ledger_conserved,
    assert_same_instant,
    list_points_entries,
    make_sku,
    read_account,
    read_cycle,
    read_loyalty_account,
    read_subscription,
    set_clock,
    setup_delivered_cycle,
    setup_dispatched_cycle,
    setup_household,
    setup_shipment_in_transit,
    unique_code,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    allocate_cycle,
    charge_cycle,
    deliver_cycle,
    dispatch_cycle,
    generate_cycle,
    lock_cycle,
)

OPS = TEST_USERS["ops_admin_headers"]


def _luxury_then_cheap_cycles(api, email_prefix):
    """Cycle 1 on a 100000-cent SKU, cycle 2 on a 1200-cent SKU, cycle 1 dispatched."""
    ctx = setup_household(
        api,
        email_prefix=email_prefix,
        sku_overrides={"code": unique_code("S2-LUX"), "name": "Stage 2 Luxury",
                       "pack_price_cents": 100000, "stock_packs": 2},
    )
    cheap = make_sku(api, code=unique_code("S2-CHEAP"), name="Stage 2 Cheap",
                     pack_price_cents=1200, stock_packs=0)

    first = generate_cycle(api, ctx["subscription"]["id"])
    allocate_cycle(api, first["id"])
    validate_success(api.adjust_sku_stock(cheap["id"], 50, OPS))
    second = generate_cycle(api, ctx["subscription"]["id"])
    second = allocate_cycle(api, second["id"])

    set_clock(api, "2026-06-08T00:00:00Z")
    lock_cycle(api, first["id"])
    charge_cycle(api, first["id"])
    dispatch_cycle(api, first["id"])
    return ctx, first, second


def test_delivery_earns_points_and_lifts_the_wallet_into_silver(api):
    """PRD §3.8: "Hop two: because the cycle became `DELIVERED`, a `PointsLedgerEntry` is
    written with `entry_type` `EARN`. Its `delta_points` is the cycle's `points_earned`,
    computed from an earn base and the household's tier."
    PRD §3.8: "`points_earned` is then the earn base divided by 100 cents and floored to a
    whole number of points, that result multiplied by the tier multiplier, and the product
    floored again."
    PRD §3.8: "The tier is `GOLD` when that figure is at least 6000 points, `SILVER` when it
    is at least 2000, and `BRONZE` otherwise, with both thresholds inclusive."

    Design: Difficulty/transitive_cascade/deliver_cascade_points_tier_shipping_repricing_depth_six
    """
    ctx, first, _second = _luxury_then_cheap_cycles(api, "cascade")
    delivered = validate_success(api.deliver_cycle(first["id"], OPS))
    assert delivered["points_earned"] == 2000

    wallet = read_loyalty_account(api, ctx["loyalty_account_id"])
    assert wallet["points_balance"] == 2000
    assert wallet["trailing_earned_points"] == 2000
    assert wallet["tier"] == "SILVER"


def test_the_silver_tier_waives_shipping_on_the_next_planned_cycle(api):
    """PRD §3.8: "Hop four: because the tier entered `SILVER` or `GOLD`, every subscription
    of that household whose `lifecycle_state` is `ACTIVE` or `PAUSED` has
    `free_shipping_eligible` set to true."
    PRD §3.8: "Hop five: because `free_shipping_eligible` flipped to true, the earliest cycle
    of that subscription whose `status` is `PLANNED` or `ALLOCATED` has its `shipping_cents`
    recomputed to 0 and its `total_due_cents` recomputed accordingly."
    PRD §3.8: "Hop six: because that cycle's `total_due_cents` changed, the household's
    `next_charge_estimate_cents` is recomputed."

    Design: Difficulty/transitive_cascade/deliver_cascade_points_tier_shipping_repricing_depth_six
    """
    ctx, first, second = _luxury_then_cheap_cycles(api, "cascade2")
    assert second["shipping_cents"] == 599 and second["total_due_cents"] == 2999

    validate_success(api.deliver_cycle(first["id"], OPS))

    assert read_subscription(api, ctx["subscription"]["id"])["free_shipping_eligible"] is True
    repriced = read_cycle(api, second["id"])
    assert repriced["shipping_cents"] == 0
    assert repriced["total_due_cents"] == 2400
    assert read_account(api, ctx["account_id"])["next_charge_estimate_cents"] == 2400


def test_the_delivery_response_already_shows_the_points_it_earned(api):
    """PRD §3.8: "Hop one: the cycle moves `DISPATCHED → DELIVERED` and its `delivered_at`
    is stamped with the logical clock."
    PRD §3.8: "The earn base, exposed as `points_earn_base_cents`, is the cycle's
    `subtotal_cents` minus its `gift_credit_applied_cents` minus its `promo_discount_cents`,
    floored at 0 — taken after gift credit and after the promotional discount but *before*
    referral credit and *before* loyalty redemption, and never including `shipping_cents`."
    PRD §3.8: "The entry records the `earn_base_cents` it was computed from and the
    `tier_multiplier_applied` in force, carries `expires_at` 540 days after its creation,
    names the producing `cycle_id`, and belongs to the wallet named by `loyalty_account_id`."

    Design: Corner/cross_cutting_layers/corner_deliver_cascade_visible_in_the_same_response
    """
    ctx, cycle, _shipment = setup_dispatched_cycle(api, email_prefix="casc")
    delivered = validate_success(api.deliver_cycle(cycle["id"], OPS))
    assert delivered["points_earned"] == 24, "2400 earn base / 100 cents, floored, x 1.00"
    assert_same_instant(delivered["delivered_at"], "2026-06-08T00:00:00Z", "delivered_at")

    wallet = read_loyalty_account(api, ctx["loyalty_account_id"])
    assert wallet["points_balance"] == 24
    assert wallet["tier"] == "BRONZE"

    entries = list_points_entries(api, ctx["loyalty_account_id"])
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "EARN"
    assert entries[0]["delta_points"] == 24
    assert entries[0]["earn_base_cents"] == 2400
    assert_points_ledger_conserved(wallet, entries)


def test_an_operator_can_drive_the_whole_fulfilment_chain(api):
    """PRD §3.8: "Confirming carrier delivery moves the shipment `IN_TRANSIT → DELIVERED`
    and stamps its `delivered_at`; when the shipment carries a `gift_order_id`, that
    confirmation also drives the gift order from `CLAIMED_ITEM` to `FULFILLED`."
    PRD §3.8: "Hop one: the cycle moves `DISPATCHED → DELIVERED` and its `delivered_at` is
    stamped with the logical clock."

    Design: Corner/rbac/corner_ops_admin_may_run_the_whole_fulfilment_chain
    """
    ctx, cycle, shipment = setup_shipment_in_transit(api, email_prefix="opsall")
    validate_success(api.deliver_shipment(shipment["id"], OPS))

    delivered = validate_success(api.deliver_cycle(cycle["id"], OPS))
    assert delivered["status"] == "DELIVERED"
    assert delivered["points_earned"] == 24
    assert validate_success(api.get_shipment(shipment["id"], OPS))["status"] == "DELIVERED"
    assert read_cycle(api, cycle["id"])["charged_cash_cents"] == 2999


# ==========================================================================
# Manual redemption
# ==========================================================================
def _wallet_with_five_hundred_points(api, email_prefix):
    ctx, cycle = setup_delivered_cycle(
        api,
        email_prefix=email_prefix,
        sku_overrides={"code": unique_code("S2-PREM"), "name": "Stage 2 Premium",
                       "pack_price_cents": 25000, "stock_packs": 10},
    )
    assert cycle["points_earned"] == 500
    return ctx, cycle


def test_a_redemption_of_exactly_the_floor_is_accepted(api):
    """PRD §3.11: "The request names a `points` figure, which must be at least the
    redemption floor of 500 points — exactly 500 is accepted, and fewer is refused with
    `ERR_REDEMPTION_BELOW_FLOOR` (HTTP 422) — and may not exceed the wallet's
    `points_balance`, or the request is refused with `ERR_INSUFFICIENT_POINTS` (HTTP 402)."
    PRD §3.11: "The redemption writes a `PointsLedgerEntry` with `entry_type` `REDEEM` and a
    `delta_points` equal to the negation of the points burned, and issues a `GOODWILL`
    `Credit` worth the points multiplied by the 1-cent value of a point."

    Design: Difficulty/boundary_precision_check/redemption_exactly_at_points_floor_is_accepted
    """
    ctx, _cycle = _wallet_with_five_hundred_points(api, "points")
    entry = validate_success(
        api.redeem_points(ctx["loyalty_account_id"], 500, ctx["headers"]), 201
    )
    assert entry["delta_points"] == -500

    wallet = read_loyalty_account(api, ctx["loyalty_account_id"])
    assert wallet["points_balance"] == 0
    assert_points_ledger_conserved(wallet, list_points_entries(api, ctx["loyalty_account_id"]))


def test_a_redemption_one_point_below_the_floor_is_refused(api):
    """PRD §3.11: "The request names a `points` figure, which must be at least the
    redemption floor of 500 points — exactly 500 is accepted, and fewer is refused with
    `ERR_REDEMPTION_BELOW_FLOOR` (HTTP 422) — and may not exceed the wallet's
    `points_balance`, or the request is refused with `ERR_INSUFFICIENT_POINTS` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/redemption_exactly_at_points_floor_is_accepted
    """
    ctx, _cycle = _wallet_with_five_hundred_points(api, "points2")
    resp = api.redeem_points(ctx["loyalty_account_id"], 499, ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_BELOW_FLOOR.value, 422)

    assert read_loyalty_account(api, ctx["loyalty_account_id"])["points_balance"] == 500


def test_a_redemption_above_the_balance_is_refused_for_insufficient_points(api):
    """PRD §3.11: "and may not exceed the wallet's `points_balance`, or the request is
    refused with `ERR_INSUFFICIENT_POINTS` (HTTP 402)."

    Design: Corner/validations/corner_redemption_above_balance_rejected_after_floor_passes
    """
    ctx, _cycle = _wallet_with_five_hundred_points(api, "insuff")
    resp = api.redeem_points(ctx["loyalty_account_id"], 600, ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value, 402)

    assert read_loyalty_account(api, ctx["loyalty_account_id"])["points_balance"] == 500
    assert len(list_points_entries(api, ctx["loyalty_account_id"])) == 1


# ==========================================================================
# Points expiry and tier maintenance
# ==========================================================================
def test_the_expiry_sweep_removes_an_unconsumed_earning_lot(api):
    """PRD §3.11: "Earning lots expire 540 days after they are written, and the sweep is
    first-in-first-out."
    PRD §3.11: "For each lot whose `expires_at` is at or before the logical clock and which
    has not already been swept, the server computes the portion of that lot which was never
    consumed, and, when that portion is positive, writes a `PointsLedgerEntry` with
    `entry_type` `EXPIRE`, a `delta_points` equal to the negation of the unconsumed portion,
    and a null `cycle_id`."

    Design: Corner/calculations/corner_points_expiry_sweep_removes_unconsumed_lot
    """
    ctx, _cycle = _wallet_with_five_hundred_points(api, "expire")
    set_clock(api, "2027-12-01T00:00:00Z")

    swept = validate_success(api.expire_points(ctx["loyalty_account_id"], OPS))
    assert swept["points_balance"] == 0

    entries = list_points_entries(api, ctx["loyalty_account_id"])
    assert len(entries) == 2
    earn = next(e for e in entries if e["entry_type"] == "EARN")
    expire = next(e for e in entries if e["entry_type"] == "EXPIRE")
    assert earn["delta_points"] == 500
    assert_same_instant(earn["expires_at"], "2027-11-30T00:00:00Z", "EARN.expires_at")
    assert expire["delta_points"] == -500
    assert expire.get("cycle_id") is None


def test_a_tier_only_falls_on_an_explicit_re_evaluation(api):
    """PRD §3.11: "Operators may also re-evaluate a wallet's tier on demand, and this is the
    only path in the whole system that can move a tier *downward*. It applies the same
    trailing-365-day earning computation and the same `SILVER` threshold of 2000 points and
    `GOLD` threshold of 6000 points described in section 3.8, but applies the result in both
    directions: a wallet whose earning lots have aged past 365 days is downgraded here and
    only here."
    PRD §3.11: "The re-evaluation also recomputes `free_shipping_eligible` on every
    non-cancelled subscription of that household, which is true exactly when the resulting
    tier is `SILVER` or `GOLD`."

    Design: Corner/calculations/corner_tier_downgrade_happens_only_on_explicit_reevaluation
    """
    ctx, cycle = setup_delivered_cycle(
        api,
        email_prefix="downgrade",
        sku_overrides={"code": unique_code("S2-LUX"), "name": "Stage 2 Luxury",
                       "pack_price_cents": 100000, "stock_packs": 10},
    )
    assert cycle["points_earned"] == 2000
    set_clock(api, "2027-06-10T00:00:00Z")
    assert read_loyalty_account(api, ctx["loyalty_account_id"])["tier"] == "SILVER", (
        "the stored tier does not fall on its own"
    )

    reevaluated = validate_success(api.reevaluate_tier(ctx["loyalty_account_id"], OPS))
    assert reevaluated["tier"] == "BRONZE"
    assert reevaluated["trailing_earned_points"] == 0
    assert reevaluated["points_balance"] == 2000, "a tier move never touches the balance"
    assert read_subscription(api, ctx["subscription"]["id"])["free_shipping_eligible"] is False
