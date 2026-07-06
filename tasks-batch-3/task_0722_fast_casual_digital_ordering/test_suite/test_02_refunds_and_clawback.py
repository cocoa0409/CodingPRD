"""Make-it-right refunds: wallet vs original destination, points clawback, fiscal gate."""
from test_helpers import (
    setup_store_item_slot_customer, create_store, create_menu_item, create_pickup_slot,
    create_customer, create_completed_order, make_it_right, validate_error,
    get_customer, get_loyalty_account, api_client, TEST_USERS,
)

MANAGER = TEST_USERS["store_manager_headers"]


def test_refund_destination_wallet_credits_wallet(api):
    """PRD §3.8: "If the `refund_destination` is `WALLET`, the customer's `wallet_credit_cents`
    is increased by `refund_amount_cents`; if it is `ORIGINAL`, the wallet is unchanged because
    the charge is reversed externally off-ledger."

    Design: Difficulty/dual_variant_calc/refund_destination_wallet_vs_original
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Item1000", base_price_cents=1000, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    make_it_right(done["id"], 500, "WALLET")

    refreshed = get_customer(customer["id"])
    assert refreshed["wallet_credit_cents"] == 500


def test_refund_destination_original_leaves_wallet_unchanged(api):
    """PRD §3.8: "If the `refund_destination` is `WALLET`, the customer's `wallet_credit_cents`
    is increased by `refund_amount_cents`; if it is `ORIGINAL`, the wallet is unchanged because
    the charge is reversed externally off-ledger."

    Design: Difficulty/dual_variant_calc/refund_destination_wallet_vs_original
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Item1000", base_price_cents=1000, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    make_it_right(done["id"], 500, "ORIGINAL")

    refreshed = get_customer(customer["id"])
    assert refreshed["wallet_credit_cents"] == 0


def test_points_clawback_rounds_per_call_no_drift(api):
    """PRD §3.8: "the refund share is `refund_amount_cents` divided by `total_cents` as a
    rational fraction, the raw clawback is `points_earned` multiplied by that share and rounded
    half up".
    PRD §3.8: "a cumulative refund reaching the full `total_cents` claws back exactly the points
    earned with no drift."

    Design: Difficulty/combinatorial_formula/points_clawback_nested_rounding_then_sum
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Item1000", base_price_cents=1000, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    make_it_right(done["id"], 500, "ORIGINAL")
    final = make_it_right(done["id"], 500, "ORIGINAL")

    account = get_loyalty_account(customer["loyalty_account_id"])
    assert account["points_balance"] == 0
    assert final["settlement_status"] == "REFUNDED"
    assert final["refunded_cents"] == 1000


def test_points_clawback_partial_proportional_single_call(api):
    """PRD §3.8: "the refund share is `refund_amount_cents` divided by `total_cents` as a
    rational fraction, the raw clawback is `points_earned` multiplied by that share and rounded
    half up".
    PRD §3.8: "A partial refund thus claws back fewer points than were earned".

    Design: Difficulty/combinatorial_formula/points_clawback_nested_rounding_then_sum
    """
    # total 1000, points_earned 100; one 500-cent refund -> share 0.5 -> clawback 50 -> balance 50.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Item1000", base_price_cents=1000, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    partial = make_it_right(done["id"], 500, "ORIGINAL")

    account = get_loyalty_account(customer["loyalty_account_id"])
    assert account["points_balance"] == 50
    assert partial["settlement_status"] == "PARTIALLY_REFUNDED"


def test_refund_exceeds_charge_rejected(api):
    """PRD §3.8: "The `refund_amount_cents` must be strictly greater than 0 and at most that
    remainder; a non-positive amount or one exceeding the remainder is rejected with
    `ERR_REFUND_EXCEEDS_CHARGE`."

    Design: Corner/validations/refund_exceeds_charge_rejected
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)

    res = api.make_it_right(
        done["id"], {"refund_amount_cents": 9999, "refund_destination": "WALLET"}, MANAGER)
    validate_error(res, "ERR_REFUND_EXCEEDS_CHARGE")
