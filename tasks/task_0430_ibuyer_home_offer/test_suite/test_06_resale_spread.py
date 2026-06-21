"""Resale listing and the spread: projected spread at listing vs net spread at sale,
and the closed-transaction precondition for relisting.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    setup_closed_transaction,
    setup_scheduled_transaction,
    list_resale,
    sell_resale,
    STANDARD_REPAIR_LINES,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def test_resale_projected_spread_at_listing(api):
    """PRD §3.8: "The projected commission is the `list_price` multiplied by
    `resale_commission_pct`, rounded half-up to two decimal places. The
    `projected_spread` is then the `list_price` minus the acquisition cost minus the
    transaction's `repair_credit` minus that projected commission, rounded half-up to
    two decimal places."

    Design: Difficulty/dual_variant_calc/resale_spread_projected_vs_net_diverge_on_resale
    """
    seller, prop, offer, txn, assessment, _ = setup_closed_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=0,
        final_concession=7650.00,
    )
    resale = list_resale(txn["id"], list_price=560000, resale_commission_pct=0.03)
    # acquisition=510000, repair=6634.57, commission=round(560000*0.03,2)=16800.00
    # projected = 560000 - 510000 - 6634.57 - 16800.00 = 26565.43.
    assert resale["projected_spread"] == 26565.43, resale["projected_spread"]


def test_resale_net_spread_diverges_from_projected(api):
    """PRD §3.8: "the net commission is the `sold_price` multiplied by
    `resale_commission_pct`, rounded half-up to two decimal places, and the
    `net_spread` is the `sold_price` minus the acquisition cost minus the
    `repair_credit` minus that net commission, rounded half-up to two decimal places."
    PRD §3.8: "The `net_spread` is null until the sale is recorded, and it diverges
    from the `projected_spread` whenever `sold_price` differs from `list_price`."

    Design: Difficulty/dual_variant_calc/resale_spread_projected_vs_net_diverge_on_resale
    """
    seller, prop, offer, txn, assessment, _ = setup_closed_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=0,
        final_concession=7650.00,
    )
    resale = list_resale(txn["id"], list_price=560000, resale_commission_pct=0.03)
    sold = validate_success(
        api.sell_resale(resale["id"], {"sold_price": 555000}, _ADMIN)
    )
    # net commission = round(555000*0.03,2)=16650.00
    # net = 555000 - 510000 - 6634.57 - 16650.00 = 21715.43.
    assert sold["net_spread"] == 21715.43, sold["net_spread"]
    assert sold["projected_spread"] == 26565.43, sold["projected_spread"]
    assert sold["net_spread"] != sold["projected_spread"]
    assert sold["status"] == "SOLD", sold["status"]


def test_resale_from_non_closed_transaction_rejected(api):
    """PRD §3.8: "A resale references the closed acquisition through `transaction_id`
    and may only be created from a transaction in `CLOSED` status; an attempt against
    any other transaction status is rejected with `ERR_TRANSACTION_NOT_CLOSED`."

    Design: Corner/validations/resale_from_non_closed_transaction_returns_error
    """
    seller, prop, offer, txn, assessment, _ = setup_scheduled_transaction()
    # Transaction is SCHEDULED, not CLOSED.
    validate_error(
        api.create_resale(
            {"transaction_id": txn["id"], "list_price": 560000, "resale_commission_pct": 0.03},
            _ANALYST,
        ),
        ApiErrorId.ERR_TRANSACTION_NOT_CLOSED,
    )
