"""Finished-compost redemptions and the stock position.

Covers PRD §3.8 (redemption gates, stock accounting, fulfillment debit).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_redemption,
    create_redemption,
    get_stock,
    get_subscriber,
    list_credit_entries,
    make_subscriber_headers,
    post_credit_adjustment,
    setup_active_subscription,
    setup_completed_pickup,
    setup_weighed_pickup,
    validate_error,
    validate_success,
    post_weigh_ticket,
)


def _setup_stocked_subscriber(api):
    """One RES subscriber: week 2026-06-01 completed at 0.5 then weighed at
    net 100.00 kg, plus a +5000 manual adjustment.

    Credit: EARNED_ESTIMATED 120, EARNED_FINAL_ADJUSTMENT round(100x10x1.2)-120
    = +1080, MANUAL_ADJUSTMENT +5000 -> balance 6200.
    Stock: produced = 0.3 x 100.00 = 30.00 kg.
    """
    env = setup_weighed_pickup(
        service_date="2026-06-01", fullness_pct=0.5, gross_kg=110.0, tare_kg=10.0
    )
    assert env["pickup"]["final_kg"] == pytest.approx(100.0)
    post_credit_adjustment(env["subscriber"]["id"], 5000)
    assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 6200
    return env


class TestRedemptionStockBoundary:
    def test_redemption_equal_to_available_stock_succeeds(self, api):
        """PRD §3.8: "the requested `total_kg` must not exceed the
        `available_kg` — a request exactly equal to the available stock is
        allowed — otherwise `ERR_INSUFFICIENT_STOCK`."
        PRD §3.8: "Each bag is ten kilograms of finished compost priced at five
        hundred cents, so the request's `total_kg` is the bag count multiplied
        by ten and its `total_cents` the bag count multiplied by five hundred."

        Design: Difficulty/boundary_precision_check/redemption_at_exact_stock_boundary
        """
        env = _setup_stocked_subscriber(api)
        data = validate_success(
            api.create_redemption(
                {"subscriber_id": env["subscriber"]["id"], "bags": 3},
                make_subscriber_headers(env["subscriber"]["id"]),
            ),
            201,
        )
        assert_redemption(data)
        assert data["status"] == "REQUESTED"
        assert data["total_kg"] == pytest.approx(30.0)
        assert data["total_cents"] == 1500

    def test_redemption_beyond_available_stock_rejected(self, api):
        """PRD §3.8: "the requested `total_kg` must not exceed the
        `available_kg` — a request exactly equal to the available stock is
        allowed — otherwise `ERR_INSUFFICIENT_STOCK`." PRD §3.8: "the stock is
        reserved at creation, but no credit is debited yet."

        Design: Difficulty/boundary_precision_check/redemption_at_exact_stock_boundary
        """
        env = _setup_stocked_subscriber(api)
        sub_headers = make_subscriber_headers(env["subscriber"]["id"])
        validate_success(
            api.create_redemption(
                {"subscriber_id": env["subscriber"]["id"], "bags": 3}, sub_headers
            ),
            201,
        )
        # All 30.00 kg are now reserved; one more bag exceeds the stock.
        resp = api.create_redemption(
            {"subscriber_id": env["subscriber"]["id"], "bags": 1}, sub_headers
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        stock = get_stock()
        assert stock["produced_kg"] == pytest.approx(30.0)
        assert stock["reserved_kg"] == pytest.approx(30.0)
        assert stock["available_kg"] == pytest.approx(0.0)


class TestRedemptionGates:
    def test_redemption_with_zero_balance_rejected(self, api):
        """PRD §3.8: "Four gates guard creation, in the order of §2.10: the
        subscriber must hold an `ACTIVE` subscription, otherwise
        `ERR_SUBSCRIPTION_NOT_ACTIVE`; the subscriber must be in
        `GOOD_STANDING`, otherwise `ERR_ACCOUNT_DELINQUENT`; the subscriber's
        `credit_balance_cents` must cover the `total_cents`, otherwise
        `ERR_INSUFFICIENT_CREDIT`; and the requested `total_kg` must not exceed
        the `available_kg` — a request exactly equal to the available stock is
        allowed — otherwise `ERR_INSUFFICIENT_STOCK`."

        Design: Corner/validations/redemption_with_zero_balance_returns_insufficient_credit
        """
        env = setup_active_subscription(bin_count=1)
        # Zero credit balance and zero stock: the credit gate fires first.
        resp = api.create_redemption(
            {"subscriber_id": env["subscriber"]["id"], "bags": 1},
            make_subscriber_headers(env["subscriber"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)

    def test_fulfill_cancelled_redemption_rejected(self, api, ops_headers):
        """PRD §3.8: "Fulfillment is an `OperationsManager` action on a
        `REQUESTED` redemption — any other status is rejected with
        `ERR_REDEMPTION_NOT_FULFILLABLE`." PRD §3.8: "Cancelling a pending
        request — by the owning subscriber or an `OperationsManager` —
        likewise requires `REQUESTED`, otherwise
        `ERR_REDEMPTION_NOT_FULFILLABLE`; it releases the stock reservation,
        takes no debit because none was ever taken, moves the redemption to
        `CANCELLED`, and increments its `version`."

        Design: Corner/state_machines/fulfill_cancelled_redemption_returns_not_fulfillable
        """
        env = setup_weighed_pickup(
            service_date="2026-06-01", fullness_pct=0.5, gross_kg=45.0, tare_kg=5.0
        )
        # Balance: 120 estimated + 360 adjustment + 2000 manual = 2480.
        post_credit_adjustment(env["subscriber"]["id"], 2000)
        redemption = create_redemption(env["subscriber"]["id"], 1)
        cancel_resp = validate_success(
            api.cancel_redemption(
                redemption["id"], make_subscriber_headers(env["subscriber"]["id"])
            )
        )
        assert cancel_resp["status"] == "CANCELLED"

        resp = api.fulfill_redemption(redemption["id"], ops_headers)
        validate_error(resp, ApiErrorId.ERR_REDEMPTION_NOT_FULFILLABLE)
        assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 2480
        assert get_stock()["available_kg"] == pytest.approx(12.0)


class TestStockDerivation:
    def test_stock_derivation_and_fulfill_debit(self, api, ops_headers):
        """PRD §3.8: "The `produced_kg` is thirty percent of everything ever
        weighed — the sum of `final_kg` across all pickups that have one —
        rounded half-up to two decimal places. The `redeemed_kg` is the sum of
        `total_kg` over all redemptions in `FULFILLED`, and the `reserved_kg`
        is the same sum over redemptions still `REQUESTED`. The `available_kg`
        is what remains: produced minus redeemed minus reserved."
        PRD §3.8: "On success the system posts a `REDEMPTION_DEBIT` entry of
        negative `total_cents` with the `redemption_id` set, the subscriber's
        balance falls by that amount, the reserved stock converts to redeemed,
        the redemption moves to `FULFILLED`, and its `version` increments."

        Design: Corner/calculations/compost_stock_derivation_and_fulfill_debit
        """
        env = setup_weighed_pickup(
            service_date="2026-06-01", fullness_pct=0.5, gross_kg=45.0, tare_kg=5.0
        )
        post_credit_adjustment(env["subscriber"]["id"], 2000)  # balance 2480
        redemption = create_redemption(env["subscriber"]["id"], 1)
        fulfilled = validate_success(api.fulfill_redemption(redemption["id"], ops_headers))
        assert fulfilled["status"] == "FULFILLED"

        stock = get_stock()
        assert stock["produced_kg"] == pytest.approx(12.0)  # 0.3 x 40.00
        assert stock["redeemed_kg"] == pytest.approx(10.0)
        assert stock["reserved_kg"] == pytest.approx(0.0)
        assert stock["available_kg"] == pytest.approx(2.0)

        debits = [
            e for e in list_credit_entries(subscriber_id=env["subscriber"]["id"])
            if e["entry_type"] == "REDEMPTION_DEBIT"
        ]
        assert len(debits) == 1
        assert debits[0]["amount_cents"] == -500
        assert debits[0].get("redemption_id") == redemption["id"]
        assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 1980
