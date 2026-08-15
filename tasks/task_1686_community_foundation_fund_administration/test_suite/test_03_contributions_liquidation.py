"""Contribution acceptance, parallel status dimensions, and the liquidation
waterfall."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_fund_payload,
    create_contribution_payload,
    create_lot_payload,
    create_active_fund,
    get_fund,
    assert_contribution,
    assert_asset_lot,
    assert_money_eq,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
GIFT = TEST_USERS["gift_officer_headers"]


def _setup_accepted_noncash(api, declared_value, lots):
    """ACTIVE fund (20000 seed) plus an ACCEPTED non-cash contribution carrying
    the given lots. Returns (fund_id, contribution, lot_ids)."""
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=20000.00)
    fund_id = bundle["fund"]["id"]
    contribution = get_success_data(
        api.create_contribution(
            create_contribution_payload(
                fund_id=fund_id,
                asset_kind="PUBLICLY_TRADED",
                declared_value=declared_value,
            ),
            GIFT,
        )
    )
    lot_ids = [
        get_success_data(
            api.add_lot(contribution["id"], create_lot_payload(**lot), GIFT)
        )["id"]
        for lot in lots
    ]
    contribution = get_success_data(api.accept_contribution(contribution["id"], GIFT))
    return fund_id, contribution, lot_ids


def test_noncash_accept_leaves_liquidation_pending_and_cash_unmoved(api):
    """PRD §3.3: "For any non-cash kind, acceptance leaves `liquidation_status`
    at `PENDING_LIQUIDATION` and no cash moves yet — the gift has been taken in,
    but its value is not spendable until liquidation completes."

    Design: Difficulty/non_linear_state_machine/contribution_parallel_dimensions
    """
    fund_id, contribution, _ = _setup_accepted_noncash(
        api, 10000.00, [{"description": "GAMMA shares", "quantity": 50, "appraised_value": 10000.00}]
    )
    assert_contribution(contribution)
    assert contribution["acceptance_status"] == "ACCEPTED"
    assert contribution["liquidation_status"] == "PENDING_LIQUIDATION"
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 20000.00, "cash_balance after non-cash accept")


def test_liquidation_credits_cash_and_completes_dimensions(api):
    """PRD §3.3: "Completion moves the contribution to `LIQUIDATED`, credits
    the fund's `cash_balance` with the `net_proceeds`, refreshes the fund's
    `last_activity_at`, advances the fund's `version`, and — if the fund was
    `INACTIVE` — returns it to `ACTIVE` automatically."
    PRD §3.3: "For each lot, the lot fee is the lot's `gross_proceeds`
    multiplied by its `liquidation_fee_pct` and divided by one hundred, rounded
    half-up to two decimal places; the lot's net is then its `gross_proceeds`
    minus that fee minus a flat brokerage charge of 75.00 dollars per lot, and
    if that net would be negative it is floored at zero, so a lot's fee never
    exceeds its proceeds."

    Design: Difficulty/non_linear_state_machine/contribution_parallel_dimensions
    """
    fund_id, contribution, lot_ids = _setup_accepted_noncash(
        api, 10000.00, [{"description": "GAMMA shares", "quantity": 50, "appraised_value": 10000.00}]
    )
    resp = api.liquidate_contribution(
        contribution["id"],
        {"lot_proceeds": [{"lot_id": lot_ids[0], "gross_proceeds": 10000.00}]},
        GIFT,
    )
    data = validate_success(resp, 200)
    assert data["liquidation_status"] == "LIQUIDATED"
    # 10000.00 - 150.00 (1.50% fee) - 75.00 (brokerage) = 9775.00
    assert_money_eq(data["net_proceeds"], 9775.00, "net_proceeds")
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 29775.00, "cash_balance after liquidation")


def test_liquidation_rounds_each_lot_fee_before_summing(api):
    """PRD §3.3: "The contribution's `net_proceeds` is the sum of the per-lot
    nets, rounded half-up to two decimal places."
    PRD §3.3: "The per-lot-then-sum order is normative: summing gross proceeds
    first and applying the fee afterward is non-conformant."

    Design: Difficulty/combinatorial_formula/liquidation_per_lot_rounding_then_sum
    """
    _, contribution, lot_ids = _setup_accepted_noncash(
        api,
        83383.88,
        [
            {"description": "ACME shares", "quantity": 100, "appraised_value": 50000.55},
            {"description": "BETA shares", "quantity": 250, "appraised_value": 33333.33},
        ],
    )
    resp = api.liquidate_contribution(
        contribution["id"],
        {
            "lot_proceeds": [
                {"lot_id": lot_ids[0], "gross_proceeds": 50000.55},
                {"lot_id": lot_ids[1], "gross_proceeds": 33333.33},
            ]
        },
        GIFT,
    )
    data = validate_success(resp, 200)
    assert data["liquidation_status"] == "LIQUIDATED"
    # lot1: fee round2(50000.55*0.015)=750.01 -> net 49175.54
    # lot2: fee round2(33333.33*0.015)=500.00 -> net 32758.33
    assert_money_eq(data["net_proceeds"], 81933.87, "net_proceeds")


def test_liquidation_waterfall_credits_fund_cash(api):
    """PRD §3.3: "Completion moves the contribution to `LIQUIDATED`, credits
    the fund's `cash_balance` with the `net_proceeds`, refreshes the fund's
    `last_activity_at`, advances the fund's `version`, and — if the fund was
    `INACTIVE` — returns it to `ACTIVE` automatically."

    Design: Difficulty/combinatorial_formula/liquidation_per_lot_rounding_then_sum
    """
    fund_id, contribution, lot_ids = _setup_accepted_noncash(
        api,
        83383.88,
        [
            {"description": "ACME shares", "quantity": 100, "appraised_value": 50000.55},
            {"description": "BETA shares", "quantity": 250, "appraised_value": 33333.33},
        ],
    )
    validate_success(
        api.liquidate_contribution(
            contribution["id"],
            {
                "lot_proceeds": [
                    {"lot_id": lot_ids[0], "gross_proceeds": 50000.55},
                    {"lot_id": lot_ids[1], "gross_proceeds": 33333.33},
                ]
            },
            GIFT,
        ),
        200,
    )
    fund = get_fund(fund_id)
    # 20000.00 seed + 81933.87 liquidation net
    assert_money_eq(fund["cash_balance"], 101933.87, "cash_balance after liquidation")


def test_asset_lot_carries_only_id_and_created_at(api):
    """PRD §2.4: "An asset lot, a unitization event, a disbursement, a spending
    policy run, a market value snapshot, a fee assessment, a score entry, and an
    annual statement each carry only `id` and `created_at`; both `updated_at`
    and `version` are absent on these record types, and no endpoint mutates them
    in place after creation."

    Design: Corner/entities/immutable_asset_lot_has_no_version
    """
    fund = get_success_data(api.create_fund(create_fund_payload(), ADMIN))
    contribution = get_success_data(
        api.create_contribution(
            create_contribution_payload(
                fund_id=fund["id"], asset_kind="REAL_PROPERTY", declared_value=80000.00
            ),
            GIFT,
        )
    )
    lot = validate_success(
        api.add_lot(
            contribution["id"],
            create_lot_payload(description="Parcel 9", quantity=1, appraised_value=80000.00),
            GIFT,
        ),
        201,
    )
    assert_asset_lot(lot)


def test_decline_records_reason_and_leaves_cash_untouched(api):
    """PRD §3.3: "A `GiftOfficer` may instead decline a pledge, which moves
    `acceptance_status` to `DECLINED` and records the supplied `decline_reason`;
    the field is null on any contribution that was never declined."

    Design: Corner/state_machines/contribution_decline_side_effect_records_reason
    """
    fund = get_success_data(api.create_fund(create_fund_payload(), ADMIN))
    contribution = get_success_data(
        api.create_contribution(
            create_contribution_payload(fund_id=fund["id"], declared_value=5000.00), GIFT
        )
    )
    resp = api.decline_contribution(
        contribution["id"], {"decline_reason": "Donor restriction unacceptable"}, GIFT
    )
    data = validate_success(resp, 200)
    assert data["acceptance_status"] == "DECLINED"
    assert data["decline_reason"] == "Donor restriction unacceptable"
    fund_after = get_fund(fund["id"])
    assert_money_eq(fund_after["cash_balance"], 0.00, "cash_balance after decline")


def test_liquidate_with_missing_lot_proceeds_rejected(api):
    """PRD §3.3: "The `GiftOfficer` submits the actual sale results as
    `lot_proceeds`, recording a `gross_proceeds` figure — zero or greater, at 2
    decimal places — for every asset lot of the contribution; if any lot is
    missing its `gross_proceeds`, the liquidation is rejected with
    `ERR_LOT_PROCEEDS_MISSING` (HTTP 422)."

    Design: Corner/errors/err_lot_proceeds_missing_triggerable
    """
    fund_id, contribution, lot_ids = _setup_accepted_noncash(
        api,
        5000.00,
        [
            {"description": "L1", "quantity": 10, "appraised_value": 2500.00},
            {"description": "L2", "quantity": 10, "appraised_value": 2500.00},
        ],
    )
    resp = api.liquidate_contribution(
        contribution["id"],
        {"lot_proceeds": [{"lot_id": lot_ids[0], "gross_proceeds": 2500.00}]},
        GIFT,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_PROCEEDS_MISSING)
    after = validate_success(api.get_contribution(contribution["id"], GIFT))
    assert after["liquidation_status"] == "PENDING_LIQUIDATION"
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 20000.00, "cash_balance unchanged")
