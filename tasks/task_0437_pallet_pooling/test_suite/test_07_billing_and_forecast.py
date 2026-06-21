"""Invoice totals (round-per-line-then-sum), invoice/location constraints, forecast.

Translates Difficulty queue (A) instance `combinatorial_formula /
invoice_round_per_line_then_sum_pinned_order`; and Corner queue (B) instances from
`state_machines` (invoice empty), `validations` (location close with balance), and
`calculations` (demand forecast).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_invoice,
    assert_demand_forecast,
    make_pool_admin_headers,
    make_pool_operator_headers,
)
import test_helpers as H

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


# --------------------------------------------------------------------------
# Difficulty: invoice round-per-line-then-sum pinned order
# --------------------------------------------------------------------------
def test_invoice_round_per_line_then_sum_subtotal_and_credit(api):
    """PRD §3.9: "On issue the invoice's totals are pinned: subtotal_cents is the
    sum of the amount_cents of all lines whose kind is HIRE, LOSS, or REPAIR;
    credit_cents is the sum of the amount_cents of all CREDIT lines (their positive
    magnitudes); and total_cents is subtotal_cents minus credit_cents, floored at
    0."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_pinned_order
    """
    H.create_policy()
    account = H.create_account(role_type="RETAILER", credit_limit_cents=100_000_000)
    inv, _lines = H.setup_invoice_with_lines(
        account["id"], [("HIRE", 45900), ("LOSS", 9000), ("CREDIT", 2000)]
    )
    issued = validate_success(api.issue_invoice(inv["id"], OPERATOR))
    assert_invoice(issued)
    assert issued["subtotal_cents"] == 54900, f"subtotal {issued['subtotal_cents']}"
    assert issued["credit_cents"] == 2000, f"credit {issued['credit_cents']}"


def test_invoice_round_per_line_then_sum_total(api):
    """PRD §3.9: "These totals are produced by summing the already-rounded per-line
    integers, never by rounding a running fractional sum." PRD §3.9: "total_cents
    is subtotal_cents minus credit_cents, floored at 0."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_pinned_order
    """
    H.create_policy()
    account = H.create_account(role_type="RETAILER", credit_limit_cents=100_000_000)
    inv, _lines = H.setup_invoice_with_lines(
        account["id"], [("HIRE", 45900), ("LOSS", 9000), ("CREDIT", 2000)]
    )
    issued = validate_success(api.issue_invoice(inv["id"], OPERATOR))
    # 54900 - 2000 = 52900.
    assert issued["total_cents"] == 52900, f"total {issued['total_cents']}"


# --------------------------------------------------------------------------
# Corner: invoice issue empty
# --------------------------------------------------------------------------
def test_invoice_issue_empty_returns_invoice_empty(api):
    """PRD §3.9: "Issue requires the invoice to have at least one line (otherwise
    ERR_INVOICE_EMPTY)".

    Design: Corner/state_machines/invoice_issue_empty_returns_invoice_empty
    """
    H.create_policy()
    account = H.create_account(role_type="RETAILER")
    inv = H.create_invoice(account["id"])
    resp = api.issue_invoice(inv["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVOICE_EMPTY.value, expected_status=409)


# --------------------------------------------------------------------------
# Corner: location close with non-zero balance
# --------------------------------------------------------------------------
def test_location_close_with_balance_returns_invalid_state(api):
    """PRD §3.1: "A location may be closed only when both its physical_balance and
    its equity_balance equal 0; if either is non-zero the close is rejected with
    ERR_INVALID_STATE".

    Design: Corner/validations/location_close_with_balance_returns_invalid_state
    """
    ctx = H.bootstrap_program()
    # Minting an asset at the location raises physical_balance to 1.
    H.create_asset(ctx["asset_type"]["id"], ctx["location"]["id"], serial="S1")
    resp = api.close_location(ctx["location"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# --------------------------------------------------------------------------
# Corner: demand forecast blended result
# --------------------------------------------------------------------------
def test_forecast_projected_demand_blended_correct(api):
    """PRD §3.10: "The projected_demand is that blended per-day figure multiplied
    by horizon_days, rounded up to a whole number of assets. The
    recommended_reposition is the projected_demand minus the location's
    physical_balance at compute time, floored at 0".

    Design: Corner/calculations/forecast_projected_demand_blended_correct
    """
    ctx = H.bootstrap_program(account_overrides={"role_type": "DISTRIBUTOR"})
    stock = H.create_location(ctx["account"]["id"], name="Stock")
    l1 = H.create_location(ctx["account"]["id"], name="L1")
    H.set_clock("2026-06-15T00:00:00Z")
    H.issue_assets_into_location(ctx["asset_type"]["id"], stock["id"], l1["id"], 3, serial_prefix="F")
    H.set_clock("2026-06-20T00:00:00Z")
    resp = api.create_demand_forecast(
        {
            "location_id": l1["id"],
            "asset_type_id": ctx["asset_type"]["id"],
            "horizon_days": 60,
        },
        OPERATOR,
    )
    data = validate_success(resp, expected_status=201)
    assert_demand_forecast(data)
    # issuance_velocity 3/30=0.1; blended 0.70*0.1=0.07; ceil(0.07*60)=5.
    assert data["projected_demand"] == 5, f"projected {data['projected_demand']}"
    # recommended = max(0, 5 - physical_balance 3) = 2.
    assert data["recommended_reposition"] == 2, f"reposition {data['recommended_reposition']}"
