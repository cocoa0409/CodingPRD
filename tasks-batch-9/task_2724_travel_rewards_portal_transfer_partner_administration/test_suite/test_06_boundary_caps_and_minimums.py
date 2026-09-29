"""
Boundary precision: a rotation cap exhausted mid-transaction, a benefit allowance
spent to its last unit, and a statement credit at exactly the floor.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_BENEFIT_ALLOWANCE_EXHAUSTED
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_sweep_counters,
    assert_timestamp_equals,
)
from test_helpers.test_users import ADMIN_HEADERS
from test_helpers.types import (
    BENEFIT_TRAVEL_INSURANCE,
    CATEGORY_GROCERY,
    CHANNEL_STATEMENT_CREDIT,
    ENTITLEMENT_ACTIVE,
    FULFILLMENT_QUOTED,
    ROTATION_ACTIVE,
    SETTLEMENT_UNSETTLED,
)

GROCERY_MCC = "5411"


def _capped_grocery_rotation(api):
    """A 2.0x grocery rotation, capped at 50,000 cents of spend per account."""
    fx.set_clock(api, "2026-07-01T00:00:00.000Z")
    category = fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Supermarkets",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    rotation = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="Q3-GROCERY",
                bonus_multiplier=2.0,
                capped_spend_cents=50000,
                window_start="2026-08-01T00:00:00.000Z",
                window_end="2026-09-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(api.publish_rotation(rotation["id"], {}, ADMIN_HEADERS))
    fx.set_clock(api, "2026-08-01T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), rotations_activated=1)
    assert (
        validate_success(api.get_rotation(rotation["id"], ADMIN_HEADERS))["status"]
        == ROTATION_ACTIVE
    )
    account, _ = fx.funded_account(api, 0)
    return rotation, account


def _spend(api, account_id, amount_cents, posted_at):
    return fx.post_purchase(
        api,
        account_id,
        amount_cents,
        headers=ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        posted_at=posted_at,
    )


def test_the_first_purchase_earns_the_bonus_on_its_whole_amount(api):
    """
    "`rotation_eligible_cents` is the smaller of the purchase's `amount_cents` and
    that headroom."

    Design: Difficulty/boundary_precision_check/boundary_rotation_cap_headroom_exhausts_mid_transaction
    """
    rotation, account = _capped_grocery_rotation(api)

    first = _spend(api, account["id"], 30000, "2026-08-05T00:00:00.000Z")

    assert first["rotation_id"] == rotation["id"]
    assert first["rotation_eligible_cents"] == 30000
    assert first["base_points"] == 300
    assert first["bonus_points"] == 300
    assert first["total_points_earned"] == 600


def test_the_headroom_splits_the_second_purchase_between_the_two_legs(api):
    """
    "Headroom is the rotation's `capped_spend_cents` less that prior sum, floored at
    zero."

    Design: Difficulty/boundary_precision_check/boundary_rotation_cap_headroom_exhausts_mid_transaction
    """
    rotation, account = _capped_grocery_rotation(api)
    _spend(api, account["id"], 30000, "2026-08-05T00:00:00.000Z")

    second = _spend(api, account["id"], 30000, "2026-08-06T00:00:00.000Z")

    assert second["rotation_id"] == rotation["id"]
    assert second["rotation_eligible_cents"] == 20000
    assert second["base_points"] == 300
    assert second["bonus_points"] == 200
    assert second["total_points_earned"] == 500


def test_an_exhausted_cap_still_records_the_rotation_while_paying_no_bonus(api):
    """
    "the system sums `rotation_eligible_cents` over this account's earlier purchases
    against this same rotation — counting only rows whose `status` is `POSTED`, in
    `created_at` ascending order, and whose `created_at` precedes this purchase's
    `created_at`"

    Design: Difficulty/boundary_precision_check/boundary_rotation_cap_headroom_exhausts_mid_transaction
    """
    rotation, account = _capped_grocery_rotation(api)
    _spend(api, account["id"], 30000, "2026-08-05T00:00:00.000Z")
    _spend(api, account["id"], 30000, "2026-08-06T00:00:00.000Z")

    third = _spend(api, account["id"], 10000, "2026-08-07T00:00:00.000Z")

    assert third["rotation_id"] == rotation["id"]
    assert third["rotation_eligible_cents"] == 0
    assert third["base_points"] == 100
    assert third["bonus_points"] == 0
    assert third["total_points_earned"] == 100
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=1200,
        lifetime_points_earned=1200,
    )


def _single_unit_insurance(api):
    """An entitlement whose whole annual allowance is one consumption."""
    account, cardholder = fx.funded_account(api, 0)
    entitlement = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_TRAVEL_INSURANCE,
        annual_allowance=1,
        requires_portal_booking=False,
    )
    assert entitlement["remaining_allowance"] == 1
    return entitlement, cardholder


def test_the_last_allowance_unit_is_admitted_and_stamps_the_consumption(api):
    """
    "On success `used_count` rises by 1, `remaining_allowance` falls by 1,
    `last_consumed_at` is set to the clock instant, and `version` increments by 1."

    Design: Difficulty/boundary_precision_check/boundary_benefit_allowance_last_unit_admitted_then_exhausted
    """
    entitlement, cardholder = _single_unit_insurance(api)

    consumed = validate_success(
        api.consume_entitlement(entitlement["id"], f.consume_payload(), cardholder)
    )

    assert consumed["used_count"] == 1
    assert consumed["remaining_allowance"] == 0
    assert consumed["status"] == ENTITLEMENT_ACTIVE
    assert_timestamp_equals(consumed["last_consumed_at"], "2026-08-01T00:00:00.000Z")
    assert consumed["version"] == entitlement["version"] + 1


def test_the_next_consumption_past_the_allowance_is_refused_and_changes_nothing(api):
    """
    "`remaining_allowance` must be at least 1, or the call is refused with
    `ERR_BENEFIT_ALLOWANCE_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/boundary_benefit_allowance_last_unit_admitted_then_exhausted
    """
    entitlement, cardholder = _single_unit_insurance(api)
    consumed = validate_success(
        api.consume_entitlement(entitlement["id"], f.consume_payload(), cardholder)
    )

    validate_error(
        api.consume_entitlement(entitlement["id"], f.consume_payload(), cardholder),
        ERR_BENEFIT_ALLOWANCE_EXHAUSTED,
        409,
    )

    after = fx.read_entitlement(api, entitlement["id"])
    assert after["used_count"] == 1
    assert after["remaining_allowance"] == 0
    assert after["version"] == consumed["version"]


def test_a_statement_credit_at_exactly_the_floor_and_exactly_the_balance_is_priced(api):
    """
    "A statement credit must be for at least 2,500 points; anything smaller is
    rejected with `ERR_STATEMENT_CREDIT_BELOW_MINIMUM` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/boundary_statement_credit_exact_minimum_and_exact_balance_admitted
    """
    account, cardholder = fx.funded_account(api, 2500)

    order = fx.statement_credit(api, account["id"], cardholder, points_requested=2500)

    assert order["channel"] == CHANNEL_STATEMENT_CREDIT
    assert order["points_debited"] == 2500
    assert order["statement_credit_cents"] == 2500
    assert order["cash_copay_cents"] == 0
    assert order["inventory_offer_id"] is None
    assert order["traveler_name"] is None
    assert order["fulfillment_status"] == FULFILLMENT_QUOTED
    assert order["settlement_status"] == SETTLEMENT_UNSETTLED


def test_the_exactly_equal_burn_reserves_the_whole_balance_without_costing_the_issuer(api):
    """
    "A requested burn is admitted when it is less than or equal to available points;
    equality is admitted, and a burn strictly greater than available points is
    rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/boundary_statement_credit_exact_minimum_and_exact_balance_admitted
    """
    account, cardholder = fx.funded_account(api, 2500)

    order = fx.statement_credit(api, account["id"], cardholder, points_requested=2500)

    assert order["issuer_cost_provisional_cents"] == 0
    assert order["cost_per_1k_provisional_cents"] == 0
    assert order["issuer_cost_final_cents"] is None
    assert order["settlement_adjustment_cents"] == 0
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=2500,
        points_pending_redemption=2500,
    )
