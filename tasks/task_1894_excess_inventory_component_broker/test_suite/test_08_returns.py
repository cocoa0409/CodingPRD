"""Return cases: full refund path with escrow and lot-unit reconciliation."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    place_order, advance_order_to_delivered,
    setup_listed_broker_owned_scenario,
    create_return_case_payload,
    make_customer_headers,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


def _delivered_scenario(api, quantity=3, lot_quantity=6, mpn="TIP120"):
    sc = setup_listed_broker_owned_scenario(
        mpn=mpn, quantity=lot_quantity, agreed_unit_price_cents=4000,
        asking_price_per_unit_cents=5000,
        credit_limit_cents=100000, urgency_tier="STANDARD", bin_capacity=20,
    )
    order = place_order(sc["customer"], sc["listing"], quantity=quantity)
    delivered = advance_order_to_delivered(sc["customer"], order)
    return sc, delivered


class TestFullRefundPath:
    def test_refund_issuance_closes_case_and_refunds_order(self, api):
        """PRD section 3.8: "`FinanceAdmin` issues the refund against an
        `APPROVED` case, which books a `CUSTOMER_REFUND` escrow entry for the
        negative of `refund_amount_cents`, moves the order from
        `REFUND_PENDING` to `REFUNDED`, returns the units to the lot's books by
        decreasing `qty_reserved` and increasing `qty_returned` by the order
        quantity, recomputes the lot posture and the customer's exposure, and
        closes the case as `REFUND_ISSUED`."

        Design: Corner/state_machines/return_flow_full_refund_path
        """
        sc, delivered = _delivered_scenario(api)
        # STANDARD on asking 5000, qty 3 -> escrow 15000.
        assert delivered["escrow_funded_cents"] == 15000

        case = validate_success(
            api.create_return_case(
                create_return_case_payload(delivered["id"], reason="WRONG_PART"),
                make_customer_headers(sc["customer"]["id"]),
            ),
            201,
        )
        validate_success(api.start_return_case_review(case["id"], BROKER), 200)
        approved = validate_success(api.approve_return_case(case["id"], BROKER), 200)
        assert approved["status"] == "APPROVED"
        assert approved["refund_amount_cents"] == 15000, (
            "approval sets the refund to the order's full escrow_funded_cents"
        )

        order_mid = validate_success(api.get_sales_order(delivered["id"], BROKER), 200)
        assert order_mid["status"] == "REFUND_PENDING"

        issued = validate_success(
            api.issue_return_case_refund(case["id"], FINANCE), 200
        )
        assert issued["status"] == "REFUND_ISSUED"
        assert issued["refund_amount_cents"] == 15000

        order_after = validate_success(api.get_sales_order(delivered["id"], BROKER), 200)
        assert order_after["status"] == "REFUNDED"

    def test_refund_issuance_returns_units_and_nets_ledger_to_zero(self, api):
        """PRD section 3.8: "approval requires the order to still be
        `DELIVERED` at approval time — again failing with
        `ERR_ORDER_NOT_DELIVERED` when it is not — sets the case's
        `refund_amount_cents` to the order's full `escrow_funded_cents`, moves
        the case to `APPROVED`, and pushes the order itself from `DELIVERED` to
        `REFUND_PENDING`."
        PRD section 2.8: "`CUSTOMER_REFUND`, `BROKER_FEE`, `SELLER_PAYOUT`, and
        `BROKER_REVENUE` entries are negative and disburse funds out of
        escrow."

        Design: Corner/state_machines/return_flow_full_refund_path
        """
        sc, delivered = _delivered_scenario(api)
        case = validate_success(
            api.create_return_case(
                create_return_case_payload(
                    delivered["id"], reason="FAILED_INCOMING_INSPECTION"
                ),
                make_customer_headers(sc["customer"]["id"]),
            ),
            201,
        )
        validate_success(api.start_return_case_review(case["id"], BROKER), 200)
        validate_success(api.approve_return_case(case["id"], BROKER), 200)
        validate_success(api.issue_return_case_refund(case["id"], FINANCE), 200)

        lot = validate_success(api.get_lot(sc["lot"]["id"], BROKER), 200)
        assert lot["qty_returned"] == 3
        assert lot["qty_reserved"] == 0
        assert lot["qty_available"] == 3

        entries, _ = validate_paginated(
            api.list_escrow_entries(delivered["id"], FINANCE)
        )
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type["DEPOSIT"] == 15000
        assert by_type["CUSTOMER_REFUND"] == -15000
        assert sum(e["amount_cents"] for e in entries) == 0
