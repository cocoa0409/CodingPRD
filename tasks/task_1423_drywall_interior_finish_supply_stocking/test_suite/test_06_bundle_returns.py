"""Bundle returns: rated-product bar, restock-fee rate selection, and the AR
credit invariant (PRD §3.9)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    get_account, file_bundle_return,
    set_logical_clock,
    setup_stocked_order_scenario,
)
from test_helpers import api_client

WH = TEST_USERS["warehouse_manager_headers"]

FIRE_PRODUCT = {
    "sku": "FIRE-4x8-5/8", "board_kind": "FIRE_RATED", "thickness_in": "5/8",
    "sheets_per_bundle": 16, "unit_price_cents_per_sheet": 2400, "lead_time_days": 7,
}


def test_restock_fee_full_bundle_rate_after_free_window(api):
    """PRD §3.9: "if the return is accepted no more than 7 whole days after the
    order was stocked (elapsed time measured in floored days), the rate is zero
    and the material is credited in full; otherwise, a return of intact bundles
    only — `loose_sheets_returned` equal to zero — is charged 1,500 basis
    points (15%), while a return containing loose sheets from an opened bundle
    is charged 2,500 basis points (25%)."
    PRD §3.9: "The `restock_fee_cents` is the material value multiplied by the
    applicable rate over the 10,000 basis-point denominator, rounded half up to
    whole cents, and the `credit_cents` granted to the account is the material
    value minus that fee."

    2 intact bundles × 20 sheets × 1500c = 60000 material; fee 15% = 9000;
    credit 51000.

    Design: Difficulty/combinatorial_formula/restock_fee_partial_bundle_uses_higher_rate
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "Restock Co", "credit_limit_cents": 9000000},
        sheet_count=100, bundle_count=5)
    set_logical_clock("2026-08-12T00:00:00Z")

    ret = file_bundle_return(ctx["order"]["id"], ctx["product"]["id"],
                             bundles_returned=2, loose_sheets_returned=0)
    accepted = validate_success(api_client.accept_bundle_return(ret["id"], WH), 200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["restock_fee_cents"] == 9000, (
        f"Full-bundle returns after the free window carry the 15% rate: "
        f"60000 * 0.15 = 9000, got {accepted['restock_fee_cents']}")
    assert accepted["credit_cents"] == 51000


def test_restock_fee_partial_bundle_rate_is_higher(api):
    """PRD §3.9: "if the return is accepted no more than 7 whole days after the
    order was stocked (elapsed time measured in floored days), the rate is zero
    and the material is credited in full; otherwise, a return of intact bundles
    only — `loose_sheets_returned` equal to zero — is charged 1,500 basis
    points (15%), while a return containing loose sheets from an opened bundle
    is charged 2,500 basis points (25%)."

    1 bundle + 5 loose sheets = 25 sheets × 1500c = 37500 material; the
    opened-bundle 25% rate yields fee 9375 and credit 28125 — a different rate
    row from the intact-bundle 15%.

    Design: Difficulty/combinatorial_formula/restock_fee_partial_bundle_uses_higher_rate
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "Restock Co 2", "credit_limit_cents": 9000000},
        sheet_count=100, bundle_count=5)
    set_logical_clock("2026-08-12T00:00:00Z")

    ret_full = file_bundle_return(ctx["order"]["id"], ctx["product"]["id"],
                                  bundles_returned=2, loose_sheets_returned=0)
    ret_part = file_bundle_return(ctx["order"]["id"], ctx["product"]["id"],
                                  bundles_returned=1, loose_sheets_returned=5)
    acc_full = validate_success(api_client.accept_bundle_return(ret_full["id"], WH), 200)
    acc_part = validate_success(api_client.accept_bundle_return(ret_part["id"], WH), 200)

    assert acc_part["restock_fee_cents"] == 9375, (
        f"Opened-bundle returns carry the 25% rate: 37500 * 0.25 = 9375, "
        f"got {acc_part['restock_fee_cents']}")
    assert acc_part["credit_cents"] == 28125
    assert acc_full["restock_fee_cents"] == 9000
    assert acc_full["restock_fee_cents"] != acc_part["restock_fee_cents"], (
        "Different rate rows must produce different fees for these payloads")


def test_return_accept_credit_reduces_account_ar(api):
    """PRD §3.9: "The returned **material value** is the total returned sheets
    — `bundles_returned` full bundles of `sheets_per_bundle` sheets each, plus
    the `loose_sheets_returned` — multiplied by the product's current
    `unit_price_cents_per_sheet`."
    PRD §3.9: "The account's `ar_outstanding_cents` then decreases by
    `credit_cents`, floored at zero so a credit can never drive the ledger
    negative."

    Draw 112213 (price moved to 1700 pre-lock); return of 1 intact bundle at
    day 10 → material 34000, fee 5100 (15%), credit 28900; AR falls to 83313.

    Design: Difficulty/compensating_invariant/bundle_return_accept_conserves_account_ar
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "AR Inv Co", "credit_limit_cents": 5000000,
                           "default_waste_pct_bp": 1000},
        project_overrides={"distance_miles": 10},
        sheet_count=50, pre_lock_price=1700, bundle_count=3)
    assert get_account(ctx["account"]["id"])["ar_outstanding_cents"] == 112213
    set_logical_clock("2026-08-12T00:00:00Z")

    ret = file_bundle_return(ctx["order"]["id"], ctx["product"]["id"],
                             bundles_returned=1, loose_sheets_returned=0)
    accepted = validate_success(api_client.accept_bundle_return(ret["id"], WH), 200)
    assert accepted["restock_fee_cents"] == 5100
    assert accepted["credit_cents"] == 28900

    account_after = get_account(ctx["account"]["id"])
    assert account_after["ar_outstanding_cents"] == 83313, (
        f"AR must fall by exactly the credit: 112213 - 28900 = 83313, "
        f"got {account_after['ar_outstanding_cents']}")


def test_return_accept_fee_and_credit_sum_to_material_value(api):
    """PRD §3.9: "The `restock_fee_cents` is the material value multiplied by
    the applicable rate over the 10,000 basis-point denominator, rounded half
    up to whole cents, and the `credit_cents` granted to the account is the
    material value minus that fee."

    Same return (1 intact bundle of 20 sheets at the current 1700c price,
    accepted on day 10): fee 5100 + credit 28900 = 34000 material value — the
    compensating pair conserves the material value exactly.

    Design: Difficulty/compensating_invariant/bundle_return_accept_conserves_account_ar
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "AR Inv Co 2", "credit_limit_cents": 5000000,
                           "default_waste_pct_bp": 1000},
        project_overrides={"distance_miles": 10},
        sheet_count=50, pre_lock_price=1700, bundle_count=3)
    set_logical_clock("2026-08-12T00:00:00Z")

    ret = file_bundle_return(ctx["order"]["id"], ctx["product"]["id"],
                             bundles_returned=1, loose_sheets_returned=0)
    accepted = validate_success(api_client.accept_bundle_return(ret["id"], WH), 200)
    material_value = 1 * 20 * 1700
    assert accepted["restock_fee_cents"] + accepted["credit_cents"] == material_value, (
        f"fee + credit must equal material value {material_value}, got "
        f"{accepted['restock_fee_cents']} + {accepted['credit_cents']}")


def test_rated_product_return_rejected(api):
    """PRD §3.9: "Two product-level bars apply both at filing and again at
    acceptance. Only `REGULAR` board is returnable: a return naming a
    `FIRE_RATED` or `MOISTURE_RATED` product is rejected with
    `ERR_RATED_NON_RETURNABLE`."

    Filing a return against a stocked FIRE_RATED order is rejected at filing.

    Design: Corner/validations/rated_product_non_returnable
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "NR Co", "credit_limit_cents": 9000000},
        product_overrides=dict(FIRE_PRODUCT),
        sheet_count=16, bundle_count=1,
        scheduled_date="2026-08-08",
        dispatch_time="2026-08-08T08:00:00Z")

    res = api_client.create_bundle_return(
        {"stocking_order_id": ctx["order"]["id"], "product_id": ctx["product"]["id"],
         "bundles_returned": 1, "loose_sheets_returned": 0}, WH)
    validate_error(res, ApiErrorId.ERR_RATED_NON_RETURNABLE)
