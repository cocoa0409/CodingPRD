"""Sourcing-candidate cardinality on reserve, and the resale-certificate gate on submit."""

from typing import Any, Dict, List

from test_helpers import (
    PRO_DESK_ASSOCIATE,
    SKU_MORTAR_BAG,
    SKU_TRIM_PACK,
    STORE_OPERATIONS,
    TAX_COMPLIANCE_OFFICER,
    ApiErrorId,
    api_client,
    file_tax_exempt_certificate,
    make_contractor_admin_headers,
    read_pro_account,
    read_pro_order,
    read_store_stock,
    reserve_order,
    setup_account_at_tier,
    setup_store_with_stock,
    setup_submitted_order,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Scenario builders (inlined: every test starts from an empty database)         #
# --------------------------------------------------------------------------- #


def _three_unit_store_with_three_orders() -> Dict[str, Any]:
    """One store holding just 3 TRIM-PACK units, with orders for 2, 3 and 1 units.

    The 2-unit order is already reserved, leaving a single bookable unit.
    """
    store, stocks = setup_store_with_stock([(SKU_TRIM_PACK, 3)])
    account = setup_account_at_tier(store["id"], "MEMBER")
    submitted: List[Dict[str, Any]] = []
    for qty_units in (2, 3, 1):
        order, _lines = setup_submitted_order(
            account["id"],
            store["id"],
            [(SKU_TRIM_PACK, qty_units)],
            payment_method="CARD",
            delivery_mode="WILL_CALL",
        )
        submitted.append(order)
    reserve_order(submitted[0]["id"])
    return {
        "store": store,
        "stock": stocks[SKU_TRIM_PACK],
        "account": account,
        "order_two_units": submitted[0],
        "order_three_units": submitted[1],
        "order_one_unit": submitted[2],
    }


def _resale_order_with_pending_certificate() -> Dict[str, Any]:
    """A DRAFT resale purchase whose Illinois certificate is filed but not yet verified."""
    store, stocks = setup_store_with_stock([(SKU_MORTAR_BAG, 500)])
    account = setup_account_at_tier(
        store["id"], "MEMBER", business_name="Resale Remodelers"
    )
    admin_headers = make_contractor_admin_headers(account["id"])
    certificate = file_tax_exempt_certificate(
        account["id"],
        state_code="IL",
        certificate_number="IL-RESALE-77120",
        expires_on="2027-12-31",
    )
    order = validate_success(
        api_client.create_pro_order(
            {
                "pro_account_id": account["id"],
                "fulfillment_store_id": store["id"],
                "payment_method": "CARD",
                "delivery_mode": "WILL_CALL",
                "lift_gate_required": False,
                "job_lot_required": False,
                "resale_purchase": True,
            },
            admin_headers,
        ),
        expected_status=201,
    )
    validate_success(
        api_client.create_order_line(
            order["id"], {"sku": SKU_MORTAR_BAG, "qty_units": 10}, admin_headers
        ),
        expected_status=201,
    )
    return {
        "store": store,
        "stock": stocks[SKU_MORTAR_BAG],
        "account": account,
        "admin_headers": admin_headers,
        "certificate": certificate,
        "order": order,
    }


# =========================================================================== #
# Sourcing-candidate cardinality: one bookable unit against none              #
# =========================================================================== #


class TestSourcingCandidateCardinality:
    def test_shortfall_with_one_bookable_unit_reports_insufficient_job_lot(self):
        """PRD §3.7: "For a given SKU, a store is a candidate when its `region_code` equals the `region_code` of the order's fulfillment store **and** it holds a stock position for that SKU whose `on_hand_units` less `reserved_units` is strictly greater than zero."
        PRD §3.7: "If any line finishes the walk with units still unfound, the entire call — every line, not just the short one — is rejected with `ERR_INSUFFICIENT_JOB_LOT`."
        PRD §3.7: "**Rejection is atomic in the strongest sense: no reservation row and no change to any store's `reserved_units` survives a failed reservation call.**"

        Design: Difficulty/boundary_precision_check/empty_sourcing_candidate_set_on_reserve
        """
        scenario = _three_unit_store_with_three_orders()
        short_order = scenario["order_three_units"]

        before = read_store_stock(scenario["stock"]["id"])
        assert before["reserved_units"] == 2
        assert before["available_units"] == 1

        validate_error(
            api_client.reserve_pro_order(short_order["id"], PRO_DESK_ASSOCIATE),
            ApiErrorId.ERR_INSUFFICIENT_JOB_LOT.value,
            expected_status=409,
        )

        after = validate_success(
            api_client.get_store_stock(scenario["stock"]["id"], STORE_OPERATIONS),
            expected_status=200,
        )
        assert after["on_hand_units"] == 3
        assert after["reserved_units"] == 2
        assert after["available_units"] == 1

        order = read_pro_order(short_order["id"], scenario["account"]["id"])
        assert order["fulfillment_status"] == "SUBMITTED"

        rows, _meta = validate_paginated(
            api_client.list_reservations(
                PRO_DESK_ASSOCIATE, params={"pro_order_id": short_order["id"]}
            )
        )
        assert len(rows) == 0

    def test_shortfall_with_no_bookable_unit_reports_no_sourcing_candidates(self):
        """PRD §3.7: "For a given SKU, a store is a candidate when its `region_code` equals the `region_code` of the order's fulfillment store **and** it holds a stock position for that SKU whose `on_hand_units` less `reserved_units` is strictly greater than zero."
        PRD §3.7: "If for any line of the order that candidate set is empty, the entire call is rejected with `ERR_NO_SOURCING_CANDIDATES`."
        PRD §3.1: "`reserved_units` is always the sum of `qty_units` across the reservations at that store for that SKU whose status is `HELD` or `ALLOCATED`, and `available_units` is `on_hand_units` less `reserved_units`; both are recomputed whenever a reservation is created, released or consumed, and reads of a position always show live figures."

        Design: Difficulty/boundary_precision_check/empty_sourcing_candidate_set_on_reserve
        """
        scenario = _three_unit_store_with_three_orders()
        short_order = scenario["order_three_units"]

        validate_error(
            api_client.reserve_pro_order(short_order["id"], PRO_DESK_ASSOCIATE),
            ApiErrorId.ERR_INSUFFICIENT_JOB_LOT.value,
            expected_status=409,
        )

        validate_success(
            api_client.reserve_pro_order(
                scenario["order_one_unit"]["id"], PRO_DESK_ASSOCIATE
            ),
            expected_status=201,
        )

        validate_error(
            api_client.reserve_pro_order(short_order["id"], PRO_DESK_ASSOCIATE),
            ApiErrorId.ERR_NO_SOURCING_CANDIDATES.value,
            expected_status=409,
        )

        stock = validate_success(
            api_client.get_store_stock(scenario["stock"]["id"], STORE_OPERATIONS),
            expected_status=200,
        )
        assert stock["on_hand_units"] == 3
        assert stock["reserved_units"] == 3
        assert stock["available_units"] == 0

        order = read_pro_order(short_order["id"], scenario["account"]["id"])
        assert order["fulfillment_status"] == "SUBMITTED"

        for_short_order, _meta = validate_paginated(
            api_client.list_reservations(
                PRO_DESK_ASSOCIATE, params={"pro_order_id": short_order["id"]}
            )
        )
        assert len(for_short_order) == 0

        for_one_unit_order, _meta = validate_paginated(
            api_client.list_reservations(
                PRO_DESK_ASSOCIATE,
                params={"pro_order_id": scenario["order_one_unit"]["id"]},
            )
        )
        assert len(for_one_unit_order) == 1


# =========================================================================== #
# The resale-exemption gate on order submission                               #
# =========================================================================== #


class TestResaleCertificateGatesOrderSubmission:
    def test_resale_order_cannot_be_submitted_while_the_certificate_is_pending(self):
        """PRD §3.4: "A filing lands in `status` `PENDING` and, as a mutation of the account's exemption picture, increments the owning account's `version` by one."
        PRD §3.4: "That derived array holds exactly those `state_code` values for which the account has a certificate whose `status` is `VERIFIED` and whose `expires_on` is strictly after the current clock date — the same strict comparison, applied continuously, so a verified certificate silently drops out of the array on the day it expires without any transition being recorded against it."
        PRD §3.4: "At order submission it gates the order: an order whose `resale_purchase` is true is rejected with `ERR_NO_VALID_TAX_CERTIFICATE` unless the fulfillment store's `state_code` appears in the account's `tax_exempt_state_codes`."

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_until_certificate_verified
        """
        scenario = _resale_order_with_pending_certificate()

        assert scenario["certificate"]["status"] == "PENDING"
        account_before = read_pro_account(scenario["account"]["id"])
        assert "IL" not in account_before["tax_exempt_state_codes"]

        validate_error(
            api_client.submit_pro_order(
                scenario["order"]["id"], scenario["admin_headers"]
            ),
            ApiErrorId.ERR_NO_VALID_TAX_CERTIFICATE.value,
            expected_status=422,
        )

        order = read_pro_order(scenario["order"]["id"], scenario["account"]["id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["credit_status"] == "UNBILLED"

    def test_verifying_the_certificate_unblocks_submission_and_suppresses_tax(self):
        """PRD §3.4: "A successful verification moves `status` from `PENDING` to `VERIFIED`, stamps `verified_at` with the current clock instant, and increments the certificate's `version`."
        PRD §3.6: "The order's `tax_exempt_applied` is true when its `resale_purchase` is true **and** the fulfillment store's `state_code` is among the account's `tax_exempt_state_codes` evaluated at the pricing instant."
        PRD §3.6: "When `tax_exempt_applied` is true, `tax_cents` is 0; otherwise `tax_cents` is the tax base multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent in a single rounding on the summed base, never per line."
        PRD §3.6: "Finally, `total_cents` is the sum of `subtotal_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents` and `tax_cents`."

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_until_certificate_verified
        """
        scenario = _resale_order_with_pending_certificate()

        validate_error(
            api_client.submit_pro_order(
                scenario["order"]["id"], scenario["admin_headers"]
            ),
            ApiErrorId.ERR_NO_VALID_TAX_CERTIFICATE.value,
            expected_status=422,
        )

        verified = validate_success(
            api_client.verify_tax_exempt_certificate(
                scenario["certificate"]["id"], TAX_COMPLIANCE_OFFICER
            ),
            expected_status=200,
        )
        assert verified["status"] == "VERIFIED"

        account = read_pro_account(scenario["account"]["id"])
        assert "IL" in account["tax_exempt_state_codes"]

        submitted = validate_success(
            api_client.submit_pro_order(
                scenario["order"]["id"], scenario["admin_headers"]
            ),
            expected_status=200,
        )
        assert submitted["fulfillment_status"] == "SUBMITTED"
        assert submitted["subtotal_cents"] == 20000
        assert submitted["tax_exempt_applied"] is True
        assert submitted["tax_cents"] == 0
        assert submitted["total_cents"] == 20000
