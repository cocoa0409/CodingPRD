"""Endpoint behaviour and error conditions on the Pro Desk contractor surface."""

from test_helpers import (
    CREDIT_MANAGER,
    PLATFORM_ADMIN,
    PRO_DESK_ASSOCIATE,
    SKU_SHINGLE_BUNDLE,
    STORE_OPERATIONS,
    TAX_COMPLIANCE_OFFICER,
    ApiErrorId,
    allocate_reservations,
    create_draft_order,
    create_order_line_payload,
    create_pro_account,
    create_quote_line_payload,
    create_store,
    create_store_stock,
    create_store_stock_payload,
    create_will_call_staging_payload,
    get_success_data,
    make_contractor_admin_headers,
    read_pro_account,
    read_store_stock,
    reserve_order,
    set_clock,
    setup_account_with_credit_line,
    setup_pro_desk,
    setup_reserved_order,
    stage_and_pick_up,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)


# =========================================================================== #
# Endpoint behaviour                                                          #
# =========================================================================== #


def test_pricing_preview_reports_the_whole_breakdown_and_writes_nothing(api):
    """PRD §3.6: "Before committing, the contractor or the desk can ask for a **read-only pricing preview**, which runs the whole pricing computation against the current clock and the current tier and persists nothing at all."
    PRD §3.6: "The preview reports `tier_code_applied`, `list_subtotal_cents`, `subtotal_cents`, `discount_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents`, `tax_exempt_applied`, `tax_cents` and `total_cents`."
    PRD §3.6: "Like submission, it refuses an order with no lines, reporting `ERR_NO_ORDER_LINES`."
    PRD §3.6: "On success the server writes `tier_code_applied`, every order-line price field and every order money field, stamps `priced_at` with the current clock instant, recomputes the credit line's `exposure_cents` and `available_cents`, and increments the order's `version`."

    Design: Corner/endpoints/pricing_preview_is_a_computed_read_that_persists_nothing
    """
    store = create_store(store_code="HD-101", tax_rate_pct=0.0825, max_stage_hours=48)
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Preview Only Painting")
    admin_headers = make_contractor_admin_headers(account["id"])

    order, _ = create_draft_order(
        account["id"],
        store["id"],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    version_at_creation = order["version"]

    # A preview of a line-less order fails exactly as submission would.
    validate_error(
        api.get_pricing_preview(order["id"], admin_headers),
        ApiErrorId.ERR_NO_ORDER_LINES.value,
        expected_status=422,
    )

    get_success_data(
        api.create_order_line(
            order["id"],
            create_order_line_payload(SKU_SHINGLE_BUNDLE, 10),
            admin_headers,
        )
    )

    preview = validate_success(
        api.get_pricing_preview(order["id"], PRO_DESK_ASSOCIATE), expected_status=200
    )
    assert preview["tier_code_applied"] == "MEMBER"
    assert preview["list_subtotal_cents"] == 19990
    assert preview["subtotal_cents"] == 19990
    assert preview["discount_cents"] == 0
    assert preview["freight_surcharge_cents"] == 0
    assert preview["lift_gate_fee_cents"] == 0
    assert preview["tax_exempt_applied"] is False
    assert preview["tax_cents"] == 1649
    assert preview["total_cents"] == 21639

    # Nothing about the order moved: it is still an unpriced DRAFT.
    after_preview = validate_success(api.get_pro_order(order["id"], admin_headers))
    assert after_preview["version"] == version_at_creation
    assert after_preview["fulfillment_status"] == "DRAFT"
    assert after_preview["total_cents"] is None
    assert after_preview["priced_at"] is None
    assert after_preview["tier_code_applied"] is None

    # The identical figures become persisted state only at submission.
    submitted = validate_success(api.submit_pro_order(order["id"], admin_headers))
    assert submitted["total_cents"] == 21639
    assert submitted["tax_cents"] == 1649
    assert submitted["tier_code_applied"] == "MEMBER"
    assert submitted["priced_at"] is not None
    assert submitted["priced_at"].startswith("2026-08-01T00:00:00")


def test_will_call_sweep_expires_only_the_due_staging_and_repeats_cleanly(api):
    """PRD §3.8: "The sweep drives every staging at that store whose `expires_at` is at or before the current clock instant, and whose `status` is `SCHEDULED` or `STAGED`, to `EXPIRED`."
    PRD §3.8: "First, every reservation of the affected order in `HELD` or `ALLOCATED` is released with `released_reason_code` set to `STAGING_EXPIRED`."
    PRD §3.8: "Third, because every reservation of the order is now `RELEASED`, the order's `fulfillment_status` falls back from `RESERVED` or `STAGED` to `SUBMITTED` — the order survives, keeps its prices and its credit authorization, and can be sourced and staged again."
    PRD §3.8: "The server computes `expires_at` as `stage_start` advanced by `stage_hours` hours."
    PRD §3.1: "Every release recomputes `reserved_units` and `available_units` at the store that lost the units."

    Design: Corner/endpoints/will_call_sweep_expires_only_the_due_staging_and_is_idempotent
    """
    scenario = setup_pro_desk(
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        store_overrides={"will_call_bay_slots": 2, "max_stage_hours": 48},
        account_overrides={"business_name": "Sweep Street Sheds"},
    )
    store = scenario["store"]
    stock = scenario["stocks"][SKU_SHINGLE_BUNDLE]
    account = scenario["account"]

    order_a, _, reservations_a = setup_reserved_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    staging_a = get_success_data(
        api.create_will_call_staging(
            create_will_call_staging_payload(
                order_a["id"],
                store["id"],
                stage_start="2026-08-01T00:00:00Z",
                stage_hours=24,
            ),
            STORE_OPERATIONS,
        )
    )

    order_b, _, reservations_b = setup_reserved_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    staging_b = get_success_data(
        api.create_will_call_staging(
            create_will_call_staging_payload(
                order_b["id"],
                store["id"],
                stage_start="2026-08-01T00:00:00Z",
                stage_hours=48,
            ),
            STORE_OPERATIONS,
        )
    )

    set_clock("2026-08-02T00:00:00Z")

    validate_success(
        api.run_will_call_sweep(store["id"], STORE_OPERATIONS), expected_status=200
    )

    swept = validate_success(api.get_will_call_staging(staging_a["id"], STORE_OPERATIONS))
    assert swept["status"] == "EXPIRED"

    untouched = validate_success(
        api.get_will_call_staging(staging_b["id"], STORE_OPERATIONS)
    )
    assert untouched["status"] == "SCHEDULED"
    assert untouched["expires_at"].startswith("2026-08-03T00:00:00")

    released = validate_success(
        api.get_reservation(reservations_a[0]["id"], STORE_OPERATIONS)
    )
    assert released["status"] == "RELEASED"
    assert released["released_reason_code"] == "STAGING_EXPIRED"

    still_held = validate_success(
        api.get_reservation(reservations_b[0]["id"], STORE_OPERATIONS)
    )
    assert still_held["status"] == "HELD"

    reverted = validate_success(
        api.get_pro_order(order_a["id"], make_contractor_admin_headers(account["id"]))
    )
    assert reverted["fulfillment_status"] == "SUBMITTED"
    intact = validate_success(
        api.get_pro_order(order_b["id"], make_contractor_admin_headers(account["id"]))
    )
    assert intact["fulfillment_status"] == "RESERVED"

    position = read_store_stock(stock["id"])
    assert position["reserved_units"] == 10
    assert position["available_units"] == 590

    # A second sweep finds nothing due and disturbs nothing already expired.
    validate_success(
        api.run_will_call_sweep(store["id"], STORE_OPERATIONS), expected_status=200
    )
    assert (
        validate_success(api.get_will_call_staging(staging_a["id"], STORE_OPERATIONS))[
            "status"
        ]
        == "EXPIRED"
    )
    assert (
        validate_success(api.get_will_call_staging(staging_b["id"], STORE_OPERATIONS))[
            "status"
        ]
        == "SCHEDULED"
    )
    assert (
        validate_success(
            api.get_pro_order(
                order_a["id"], make_contractor_admin_headers(account["id"])
            )
        )["fulfillment_status"]
        == "SUBMITTED"
    )
    assert (
        validate_success(
            api.get_reservation(reservations_b[0]["id"], STORE_OPERATIONS)
        )["status"]
        == "HELD"
    )
    position_again = read_store_stock(stock["id"])
    assert position_again["reserved_units"] == 10
    assert position_again["available_units"] == 590


def test_store_stock_uniqueness_binds_the_store_and_sku_pair_only(api):
    """PRD §3.1: "A store may hold only one position per SKU: a second attempt at the same store-and-SKU pair is rejected with `ERR_DUPLICATE_STORE_STOCK`."
    PRD §3.1: "A freshly opened position starts with `reserved_units` at 0 and `available_units` equal to `on_hand_units`."
    PRD §3.1: "Stock positions can be listed filtered by `store_id` and by `sku`."

    Design: Corner/endpoints/store_stock_uniqueness_is_per_store_sku_pair_and_lists_are_scoped
    """
    store_one = create_store(
        store_code="HD-101",
        region_code="MIDWEST",
        state_code="IL",
        distance_rank=1,
        will_call_bay_slots=2,
        lift_gate_available=True,
        tax_rate_pct=0.0825,
        max_stage_hours=48,
    )
    store_two = create_store(
        store_code="HD-202",
        region_code="MIDWEST",
        state_code="IL",
        distance_rank=2,
        will_call_bay_slots=1,
        lift_gate_available=False,
        tax_rate_pct=0.0700,
        max_stage_hours=24,
    )

    first = validate_success(
        api.create_store_stock(
            create_store_stock_payload(
                store_one["id"],
                SKU_SHINGLE_BUNDLE,
                on_hand_units=600,
                list_unit_price_cents=1999,
            ),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )
    assert first["on_hand_units"] == 600
    assert first["reserved_units"] == 0
    assert first["available_units"] == 600

    validate_error(
        api.create_store_stock(
            create_store_stock_payload(
                store_one["id"],
                SKU_SHINGLE_BUNDLE,
                on_hand_units=40,
                list_unit_price_cents=1899,
            ),
            PLATFORM_ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_STORE_STOCK.value,
        expected_status=409,
    )

    # The rejected re-seed left the incumbent position exactly as it was.
    incumbent = read_store_stock(first["id"])
    assert incumbent["on_hand_units"] == 600
    assert incumbent["list_unit_price_cents"] == 1999

    # The same SKU at a different store is a clean create.
    second = validate_success(
        api.create_store_stock(
            create_store_stock_payload(
                store_two["id"],
                SKU_SHINGLE_BUNDLE,
                on_hand_units=40,
                list_unit_price_cents=2099,
            ),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )
    assert second["list_unit_price_cents"] == 2099
    assert second["available_units"] == 40

    by_store, by_store_meta = validate_paginated(
        api.list_store_stocks(PRO_DESK_ASSOCIATE, params={"store_id": store_one["id"]})
    )
    assert by_store_meta["total_count"] == 1
    assert len(by_store) == 1
    assert by_store[0]["id"] == first["id"]

    by_sku, by_sku_meta = validate_paginated(
        api.list_store_stocks(PRO_DESK_ASSOCIATE, params={"sku": SKU_SHINGLE_BUNDLE})
    )
    assert by_sku_meta["total_count"] == 2
    assert len(by_sku) == 2

    both, both_meta = validate_paginated(
        api.list_store_stocks(
            PRO_DESK_ASSOCIATE,
            params={"store_id": store_two["id"], "sku": SKU_SHINGLE_BUNDLE},
        )
    )
    assert both_meta["total_count"] == 1
    assert [row["id"] for row in both] == [second["id"]]


# =========================================================================== #
# Error conditions                                                            #
# =========================================================================== #


def test_invoice_and_settlement_guard_the_credit_dimension(api):
    """PRD §3.9: "Two conditions guard it: the order's `fulfillment_status` must be `FULFILLED`, otherwise `ERR_ORDER_NOT_FULFILLED`, which is the one place the credit dimension reads the physical dimension; and the order's `payment_method` must be `CREDIT_LINE`, otherwise `ERR_INVALID_STATE`, since a card order is never invoiced against a credit line."
    PRD §3.9: "A `CreditManager` records payment against an invoiced order, moving `credit_status` from `INVOICED` to `PAID`, and must supply an `amount_cents` that equals the order's `total_cents` less its `credited_refund_cents` — exactly, to the cent — otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`. Partial payments and overpayments are both refused."
    PRD §3.9: "Payment then recomputes the credit line's `exposure_cents` and `available_cents`, because `PAID` orders leave the exposure base."

    Design: Corner/errors/invoice_and_settlement_guards_on_the_credit_dimension
    """
    scenario = setup_account_with_credit_line(
        tier_code="MEMBER",
        limit_cents=100000,
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        account_overrides={"business_name": "Settle Up Siding"},
    )
    store = scenario["store"]
    account = scenario["account"]
    credit_line = scenario["credit_line"]
    admin_headers = make_contractor_admin_headers(account["id"])

    order, _ = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
    )
    submit_order(order["id"], account["id"])

    # The commercial dimension may not run ahead of the physical one.
    validate_error(
        api.invoice_pro_order(order["id"], CREDIT_MANAGER),
        ApiErrorId.ERR_ORDER_NOT_FULFILLED.value,
        expected_status=409,
    )
    still_authorized = validate_success(api.get_pro_order(order["id"], admin_headers))
    assert still_authorized["credit_status"] == "AUTHORIZED"
    assert still_authorized["invoiced_at"] is None

    reservations = reserve_order(order["id"])
    allocate_reservations(reservations)
    stage_and_pick_up(
        order["id"], store["id"], stage_start="2026-08-01T00:00:00Z", stage_hours=24
    )

    invoiced = validate_success(
        api.invoice_pro_order(order["id"], CREDIT_MANAGER), expected_status=200
    )
    assert invoiced["credit_status"] == "INVOICED"
    assert invoiced["invoiced_at"] is not None
    assert invoiced["invoiced_at"].startswith("2026-08-01T00:00:00")

    # A short payment is refused outright; the order stays invoiced.
    validate_error(
        api.pay_pro_order(order["id"], 21000, CREDIT_MANAGER),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value,
        expected_status=422,
    )
    assert (
        validate_success(api.get_pro_order(order["id"], admin_headers))["credit_status"]
        == "INVOICED"
    )

    settled = validate_success(
        api.pay_pro_order(order["id"], 21639, CREDIT_MANAGER), expected_status=200
    )
    assert settled["credit_status"] == "PAID"

    line_after = validate_success(api.get_credit_line(credit_line["id"], CREDIT_MANAGER))
    assert line_after["exposure_cents"] == 0
    assert line_after["available_cents"] == 100000
    assert line_after["status"] == "ACTIVE"
    assert read_pro_account(account["id"])["status"] == "ACTIVE"


def test_a_clawed_down_payable_blocks_the_rebate_payout(api):
    """PRD §3.9: "Pay-out requires `payable_cents` to be strictly positive at that instant, otherwise `ERR_NO_REBATE_PAYABLE`."
    PRD §3.9: "Clawbacks reach one rung wider than accruals do: a period that has been closed but not yet paid is still clawable, and can be driven all the way down to a `payable_cents` of zero — which is precisely what makes a later pay-out attempt on it fail with `ERR_NO_REBATE_PAYABLE`."
    PRD §3.9: "After every booking, `payable_cents` is set to `accrued_cents` less `clawed_back_cents`, floored at zero, and the account's `rebate_accrued_cents` is recomputed as the sum of `payable_cents` across the account's accruals whose `payout_status` is `ACCRUING` or `PAYABLE`."
    PRD §3.9: "`payout_status` goes from `ACCRUING` to `PAYABLE` when `payable_cents` is strictly positive, and from `ACCRUING` to `VOIDED` when `payable_cents` is exactly zero, which happens when clawbacks have consumed the whole accrual."

    Design: Corner/errors/a_clawed_down_payable_blocks_the_rebate_payout
    """
    scenario = setup_account_with_credit_line(
        tier_code="MEMBER",
        limit_cents=100000000,
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        account_overrides={"business_name": "Rebate Zeroed Roofing"},
    )
    store = scenario["store"]
    account = scenario["account"]
    admin_headers = make_contractor_admin_headers(account["id"])

    lifted = validate_success(
        api.adjust_pro_account_volume(
            account["id"], 5000000, "legacy migration", CREDIT_MANAGER
        ),
        expected_status=200,
    )
    assert lifted["tier_code"] == "GOLD"

    order, order_lines = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 100)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
    )
    submitted = submit_order(order["id"], account["id"])
    assert submitted["total_cents"] == 205567

    reservations = reserve_order(order["id"])
    allocate_reservations(reservations)
    stage_and_pick_up(
        order["id"], store["id"], stage_start="2026-08-01T00:00:00Z", stage_hours=24
    )
    validate_success(
        api.invoice_pro_order(order["id"], CREDIT_MANAGER), expected_status=200
    )

    accruals, _ = validate_paginated(
        api.list_rebate_accruals(
            CREDIT_MANAGER, params={"pro_account_id": account["id"]}
        )
    )
    assert len(accruals) == 1
    accrual = accruals[0]
    assert accrual["accrued_cents"] == 1899

    closed = validate_success(
        api.close_rebate_accrual(accrual["id"], CREDIT_MANAGER), expected_status=200
    )
    assert closed["payout_status"] == "PAYABLE"
    assert closed["payable_cents"] == 1899

    request = validate_success(
        api.create_return_request(
            {
                "pro_order_id": order["id"],
                "reason_code": "JOB_CANCELLED",
                "lines": [{"order_line_id": order_lines[0]["id"], "qty_units": 100}],
            },
            admin_headers,
        ),
        expected_status=201,
    )
    approved = validate_success(
        api.approve_return_request(request["id"], PRO_DESK_ASSOCIATE),
        expected_status=200,
    )
    assert approved["gross_refund_cents"] == 189900
    assert approved["refund_total_cents"] == 205567

    credited = validate_success(
        api.credit_return_request(request["id"], CREDIT_MANAGER), expected_status=200
    )
    assert credited["status"] == "CREDITED"

    clawed_down = validate_success(
        api.get_rebate_accrual(accrual["id"], CREDIT_MANAGER)
    )
    assert clawed_down["accrued_cents"] == 1899
    assert clawed_down["clawed_back_cents"] == 1899
    assert clawed_down["payable_cents"] == 0
    assert clawed_down["payout_status"] == "PAYABLE"

    validate_error(
        api.pay_out_rebate_accrual(accrual["id"], "ACH-0001", CREDIT_MANAGER),
        ApiErrorId.ERR_NO_REBATE_PAYABLE.value,
        expected_status=422,
    )

    after_refusal = validate_success(
        api.get_rebate_accrual(accrual["id"], CREDIT_MANAGER)
    )
    assert after_refusal["payout_status"] == "PAYABLE"

    account_after = read_pro_account(account["id"])
    assert account_after["rebate_accrued_cents"] == 0
    assert account_after["tier_code"] == "GOLD"
    assert (
        validate_success(api.get_pro_order(order["id"], admin_headers))[
            "net_volume_cents"
        ]
        == 0
    )


def test_verifying_a_certificate_that_lapses_today_is_refused(api):
    """PRD §3.4: "Verification is refused with `ERR_CERTIFICATE_STATE_MISMATCH` unless `expires_on` is **strictly after** the current clock date — the comparison is strict, so a certificate whose `expires_on` falls on today's date is already lapsed and cannot be verified."
    PRD §3.4: "A successful verification moves `status` from `PENDING` to `VERIFIED`, stamps `verified_at` with the current clock instant, and increments the certificate's `version`."
    PRD §3.4: "That derived array holds exactly those `state_code` values for which the account has a certificate whose `status` is `VERIFIED` and whose `expires_on` is strictly after the current clock date — the same strict comparison, applied continuously, so a verified certificate silently drops out of the array on the day it expires without any transition being recorded against it."
    PRD §2.4: "Before any client sets the clock, it reads exactly `2026-08-01T00:00:00Z`; that startup default is fixed and the server must never fall back to real time."

    Design: Corner/errors/verifying_a_certificate_that_lapses_today_returns_certificate_state_mismatch
    """
    store = create_store(store_code="HD-101", state_code="IL")
    account = create_pro_account(
        store["id"], business_name="Lapsed Cert Contracting"
    )
    admin_headers = make_contractor_admin_headers(account["id"])

    cert_today = validate_success(
        api.create_tax_exempt_certificate(
            {
                "pro_account_id": account["id"],
                "state_code": "IL",
                "certificate_number": "IL-TODAY",
                "expires_on": "2026-08-01",
                "expected_pro_account_version": account["version"],
            },
            admin_headers,
        ),
        expected_status=201,
    )

    refreshed = read_pro_account(account["id"])
    cert_tomorrow = validate_success(
        api.create_tax_exempt_certificate(
            {
                "pro_account_id": account["id"],
                "state_code": "IL",
                "certificate_number": "IL-TOMORROW",
                "expires_on": "2026-08-02",
                "expected_pro_account_version": refreshed["version"],
            },
            admin_headers,
        ),
        expected_status=201,
    )

    validate_error(
        api.verify_tax_exempt_certificate(cert_today["id"], TAX_COMPLIANCE_OFFICER),
        ApiErrorId.ERR_CERTIFICATE_STATE_MISMATCH.value,
        expected_status=422,
    )
    lapsed = validate_success(
        api.get_tax_exempt_certificate(cert_today["id"], TAX_COMPLIANCE_OFFICER)
    )
    assert lapsed["status"] == "PENDING"
    assert lapsed["verified_at"] is None
    assert read_pro_account(account["id"])["tax_exempt_state_codes"] == []

    verified = validate_success(
        api.verify_tax_exempt_certificate(cert_tomorrow["id"], TAX_COMPLIANCE_OFFICER),
        expected_status=200,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_at"] is not None
    assert verified["verified_at"].startswith("2026-08-01T00:00:00")
    assert read_pro_account(account["id"])["tax_exempt_state_codes"] == ["IL"]


def test_lines_for_a_sku_the_relevant_store_does_not_stock_are_rejected(api):
    """PRD §2.11: "**SKU stocked** — the `sku` has a stock position at the relevant store — the fulfillment store for order lines, the originating store for quote lines — otherwise `ERR_SKU_NOT_STOCKED`."
    PRD §3.6: "A `sku` with no stock position at the fulfillment store is refused with `ERR_SKU_NOT_STOCKED`."
    PRD §3.5: "A quote may carry only one line per SKU, and a line whose `sku` has no stock position at the originating store is refused with `ERR_SKU_NOT_STOCKED`."

    Design: Corner/errors/lines_for_a_sku_the_relevant_store_does_not_stock_are_rejected
    """
    stocked_store = create_store(
        store_code="HD-101",
        distance_rank=1,
        will_call_bay_slots=2,
        lift_gate_available=True,
        tax_rate_pct=0.0825,
        max_stage_hours=48,
    )
    bare_store = create_store(
        store_code="HD-202",
        distance_rank=2,
        will_call_bay_slots=1,
        lift_gate_available=False,
        tax_rate_pct=0.0700,
        max_stage_hours=24,
    )
    create_store_stock(
        stocked_store["id"],
        SKU_SHINGLE_BUNDLE,
        on_hand_units=600,
        list_unit_price_cents=1999,
    )
    account = create_pro_account(
        stocked_store["id"], business_name="Ghost Sku Framing"
    )
    admin_headers = make_contractor_admin_headers(account["id"])

    order_at_stocked_store, _ = create_draft_order(
        account["id"],
        stocked_store["id"],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    order_at_bare_store, _ = create_draft_order(
        account["id"],
        bare_store["id"],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    quote = get_success_data(
        api.create_job_quote(
            {
                "pro_account_id": account["id"],
                "originating_store_id": stocked_store["id"],
                "job_name": "GHOST-A",
                "requested_term_days": 15,
            },
            admin_headers,
        )
    )

    validate_error(
        api.create_order_line(
            order_at_stocked_store["id"],
            create_order_line_payload("GHOST-SKU", 5),
            admin_headers,
        ),
        ApiErrorId.ERR_SKU_NOT_STOCKED.value,
        expected_status=422,
    )
    validate_error(
        api.create_order_line(
            order_at_bare_store["id"],
            create_order_line_payload(SKU_SHINGLE_BUNDLE, 5),
            admin_headers,
        ),
        ApiErrorId.ERR_SKU_NOT_STOCKED.value,
        expected_status=422,
    )
    validate_error(
        api.create_quote_line(
            quote["id"], create_quote_line_payload("GHOST-SKU", 5), admin_headers
        ),
        ApiErrorId.ERR_SKU_NOT_STOCKED.value,
        expected_status=422,
    )

    accepted_line = validate_success(
        api.create_order_line(
            order_at_stocked_store["id"],
            create_order_line_payload(SKU_SHINGLE_BUNDLE, 5),
            admin_headers,
        ),
        expected_status=201,
    )
    assert accepted_line["qty_units"] == 5

    kept, kept_meta = validate_paginated(
        api.list_order_lines_of_order(order_at_stocked_store["id"], admin_headers)
    )
    assert kept_meta["total_count"] == 1
    assert [row["id"] for row in kept] == [accepted_line["id"]]

    empty_order_lines, empty_order_meta = validate_paginated(
        api.list_order_lines_of_order(order_at_bare_store["id"], admin_headers)
    )
    assert empty_order_meta["total_count"] == 0
    assert empty_order_lines == []

    empty_quote_lines, empty_quote_meta = validate_paginated(
        api.list_quote_lines_of_quote(quote["id"], admin_headers)
    )
    assert empty_quote_meta["total_count"] == 0
    assert empty_quote_lines == []
