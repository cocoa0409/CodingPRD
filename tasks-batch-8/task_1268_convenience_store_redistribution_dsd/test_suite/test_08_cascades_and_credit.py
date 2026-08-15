"""Cascades: short-credit releasing credit hold, weight flipping manifest posture,
compensating invariants, submit/cancel conservation."""
import pytest

from test_helpers import (
    ADMIN,
    CREDIT,
    DRIVER,
    ApiErrorId,
    api_client,
    assign_order_to_manifest,
    begin_loading,
    close_manifest,
    create_credit_memo_payload,
    create_delivery_exception_payload,
    create_delivery_manifest_payload,
    create_purchase_order_payload,
    get_order_line_id_for_product,
    get_success_data,
    order_line,
    publish_fuel_rate,
    setup_canonical_submitted_promoted_order,
    setup_draft_order,
    setup_guide,
    setup_invoiced_order,
    setup_manifest,
    setup_product,
    setup_retailer,
    setup_submitted_order,
    validate_error,
    validate_success,
)


def test_short_credit_releases_credit_hold(api, credit_manager_headers, route_driver_headers):
    """PRD §3.6: "When the order's invoice already exists, the system
    additionally creates a credit memo whose `origin` matches the exception
    type, whose `exception_id` points back to the exception, and auto-posts it
    — reducing the invoice's `balance_cents` and the retailer's
    `ar_balance_cents` and re-evaluating `credit_status`".
    PRD §2.9: "a re-evaluation may automatically release the hold when the
    condition that forced it has cleared".

    Design: Difficulty/transitive_cascade/short_credit_releases_credit_hold
    """
    base = setup_canonical_submitted_promoted_order()
    # Lower credit limit below current 58500 exposure to force CREDIT_HOLD
    patch_resp = api_client.update_retailer(
        base["retailer"]["id"], {"credit_limit_cents": 55000}, credit_manager_headers,
    )
    patched = validate_success(patch_resp)
    assert patched["credit_status"] == "CREDIT_HOLD"
    # Drive order through close
    manifest = setup_manifest()
    publish_fuel_rate(doe_index_usd=3.75)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    invoice = get_success_data(api_client.confirm_delivery(base["order"]["id"], route_driver_headers))
    # After invoicing exposure is still 59963 > 55000, hold persists; short 8 cases of P1.
    p1_id = base["products"]["P1"]["id"]
    line_id = get_order_line_id_for_product(base["order"]["id"], p1_id, headers=ADMIN)
    exc_resp = api_client.create_delivery_exception(
        manifest["id"],
        create_delivery_exception_payload(
            order_id=base["order"]["id"],
            order_line_id=line_id,
            exception_type="SHORT",
            cases_qty=8,
            split_units_qty=0,
        ),
        route_driver_headers,
    )
    exc = validate_success(exc_resp, expected_status=201)
    assert exc["credit_amount_cents"] == 9600  # 8 * 1200
    assert exc["status"] == "CREDITED"
    memos = get_success_data(api_client.list_invoice_credit_memos(invoice["id"], credit_manager_headers))
    assert memos[0]["status"] == "POSTED"
    assert memos[0]["amount_cents"] == 9600
    inv = get_success_data(api_client.get_invoice(invoice["id"], credit_manager_headers))
    # final invoiced = 57779 (as computed in provisional_vs_final test); balance = 57779 - 9600
    # But we did NOT short before confirm here; confirm ran first with no shorts,
    # so invoiced_total = 59963 (no-shorts final at 3.75). balance = 59963 - 9600 = 50363.
    assert inv["balance_cents"] == 50363
    ret = get_success_data(api_client.get_retailer(base["retailer"]["id"], credit_manager_headers))
    assert ret["credit_status"] == "GOOD_STANDING"


def test_short_credit_auto_posts_memo(api, credit_manager_headers, route_driver_headers):
    """PRD §3.6: "the system additionally creates a credit memo whose `origin`
    matches the exception type, whose `exception_id` points back to the
    exception, and auto-posts it".

    Design: Difficulty/transitive_cascade/short_credit_releases_credit_hold
    """
    base = setup_canonical_submitted_promoted_order()
    manifest = setup_manifest()
    publish_fuel_rate(doe_index_usd=3.75)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    invoice = get_success_data(api_client.confirm_delivery(base["order"]["id"], route_driver_headers))
    p1_id = base["products"]["P1"]["id"]
    line_id = get_order_line_id_for_product(base["order"]["id"], p1_id, headers=ADMIN)
    exc = get_success_data(api_client.create_delivery_exception(
        manifest["id"],
        create_delivery_exception_payload(
            order_id=base["order"]["id"],
            order_line_id=line_id,
            exception_type="SHORT",
            cases_qty=8,
            split_units_qty=0,
        ),
        route_driver_headers,
    ))
    assert exc["status"] == "CREDITED"
    assert exc["credit_amount_cents"] == 9600
    memos = get_success_data(api_client.list_invoice_credit_memos(invoice["id"], credit_manager_headers))
    assert memos[0]["origin"] == "SHORT"
    assert memos[0]["status"] == "POSTED"
    assert memos[0]["exception_id"] == exc["id"]


def test_assign_weight_flips_manifest_posture(api, admin_headers):
    """PRD §3.5: "Should that addition push `total_weight_lbs` above
    `capacity_lbs`, the manifest's `overweight_flag` flips to true — the
    assignment that tipped the scale still succeeds, but the flag blocks every
    later assignment until the manifest closes." PRD §3.5: "its
    `overweight_flag` must still be false, else `ERR_MANIFEST_OVERWEIGHT`
    (HTTP 422)".

    Design: Difficulty/transitive_cascade/assign_weight_flips_manifest_posture
    """
    retailer, sm = setup_retailer()
    p1 = setup_product(sku="P1", weight_lbs_per_case=10)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": p1["id"], "par_cases": 0}])
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    poa = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(retailer_id=retailer["id"], order_guide_id=guide["id"],
                                      lines=[order_line(p1["id"], cases_qty=15, split_units_qty=0)]),
        sm,
    ))
    get_success_data(api_client.submit_order(poa["id"], {"expected_order_version": poa["version"]}, sm))
    pob = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(retailer_id=retailer["id"], order_guide_id=guide["id"],
                                      lines=[order_line(p1["id"], cases_qty=1, split_units_qty=0)]),
        sm,
    ))
    get_success_data(api_client.submit_order(pob["id"], {"expected_order_version": pob["version"]}, sm))
    manifest = get_success_data(api_client.create_delivery_manifest(
        create_delivery_manifest_payload(route_code="R-9", delivery_date="2026-05-25",
                                         capacity_lbs=100),
        ADMIN,
    ))
    # Assign A: succeeds and flips overweight
    get_success_data(api_client.assign_order(
        manifest["id"],
        {"order_id": poa["id"], "expected_manifest_version": manifest["version"]},
        ADMIN,
    ))
    after_a = get_success_data(api_client.get_delivery_manifest(manifest["id"], ADMIN))
    assert after_a["total_weight_lbs"] == 150
    assert after_a["overweight_flag"] is True
    # Assign B: rejected
    resp = api_client.assign_order(
        manifest["id"],
        {"order_id": pob["id"], "expected_manifest_version": after_a["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_MANIFEST_OVERWEIGHT, expected_status=422)


def test_assign_weight_boundary_assignment_still_succeeds(api):
    """PRD §3.5: "the assignment that tipped the scale still succeeds, but the
    flag blocks every later assignment until the manifest closes".

    Design: Difficulty/transitive_cascade/assign_weight_flips_manifest_posture
    """
    retailer, sm = setup_retailer()
    p1 = setup_product(sku="P1", weight_lbs_per_case=10)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": p1["id"], "par_cases": 0}])
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    poa = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(retailer_id=retailer["id"], order_guide_id=guide["id"],
                                      lines=[order_line(p1["id"], cases_qty=15, split_units_qty=0)]),
        sm,
    ))
    get_success_data(api_client.submit_order(poa["id"], {"expected_order_version": poa["version"]}, sm))
    manifest = get_success_data(api_client.create_delivery_manifest(
        create_delivery_manifest_payload(route_code="R-9", delivery_date="2026-05-25",
                                         capacity_lbs=100),
        ADMIN,
    ))
    assign_resp = api_client.assign_order(
        manifest["id"],
        {"order_id": poa["id"], "expected_manifest_version": manifest["version"]},
        ADMIN,
    )
    assigned = validate_success(assign_resp)
    assert assigned["status"] == "ASSIGNED"
    assert assigned["manifest_id"] == manifest["id"]


def test_payment_reverse_restores_invoice_conservation(api, credit_manager_headers):
    """PRD §3.7: "Reversing an `APPLIED` payment marks it `REVERSED`, adds its
    amount back to the invoice's `balance_cents`". Conservation:
    invoiced_total == balance + applied payments + posted memos.

    Design: Difficulty/compensating_invariant/payment_reverse_restores_invoice_conservation
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    assert invoice["invoiced_total_cents"] == 60600
    pay = get_success_data(api_client.apply_payment(
        invoice["id"], {"amount_cents": 20000, "method": "CHECK"}, credit_manager_headers,
    ))
    get_success_data(api_client.reverse_payment(pay["id"], credit_manager_headers))
    inv = get_success_data(api_client.get_invoice(invoice["id"], credit_manager_headers))
    payments = get_success_data(api_client.list_invoice_payments(invoice["id"], credit_manager_headers))
    memos = get_success_data(api_client.list_invoice_credit_memos(invoice["id"], credit_manager_headers))
    applied_sum = sum(p["amount_cents"] for p in payments if p["status"] == "APPLIED")
    posted_sum = sum(m["amount_cents"] for m in memos if m["status"] == "POSTED")
    assert inv["invoiced_total_cents"] == inv["balance_cents"] + applied_sum + posted_sum
    assert inv["balance_cents"] == 60600
    assert payments[0]["status"] == "REVERSED"


def test_payment_reverse_restores_ar_balance(api, credit_manager_headers):
    """PRD §3.7: "adds its amount back to the invoice's `balance_cents` and to
    the retailer's `ar_balance_cents`".

    Design: Difficulty/compensating_invariant/payment_reverse_restores_invoice_conservation
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    pay = get_success_data(api_client.apply_payment(
        invoice["id"], {"amount_cents": 20000, "method": "CHECK"}, credit_manager_headers,
    ))
    summary_mid = get_success_data(api_client.get_credit_summary(
        base["retailer"]["id"], credit_manager_headers,
    ))
    assert summary_mid["ar_balance_cents"] == 40600
    get_success_data(api_client.reverse_payment(pay["id"], credit_manager_headers))
    summary_end = get_success_data(api_client.get_credit_summary(
        base["retailer"]["id"], credit_manager_headers,
    ))
    assert summary_end["ar_balance_cents"] == 60600


def test_submit_cancel_conserves_exposure(api, credit_manager_headers):
    """PRD §3.4: "cancellation then releases the order's provisional total
    from `exposure_forward_cents`, re-evaluates the retailer's
    `credit_status`". The submit+cancel pair returns exposure_forward_cents
    to its pre-submit value.

    Design: Difficulty/compensating_invariant/submit_cancel_conserves_exposure
    """
    base = setup_canonical_submitted_promoted_order()
    summary_after_submit = get_success_data(api_client.get_credit_summary(
        base["retailer"]["id"], credit_manager_headers,
    ))
    assert summary_after_submit["exposure_forward_cents"] == 58500
    cancel_resp = api_client.cancel_order(base["order"]["id"], base["sm_headers"])
    cancelled = validate_success(cancel_resp)
    assert cancelled["status"] == "CANCELLED"
    summary_after_cancel = get_success_data(api_client.get_credit_summary(
        base["retailer"]["id"], credit_manager_headers,
    ))
    assert summary_after_cancel["exposure_forward_cents"] == 0


def test_submit_cancel_conserves_exposure_zero_baseline(api, credit_manager_headers):
    """PRD §3.4: "cancellation then releases the order's provisional total
    from `exposure_forward_cents`". With no other invoices or pipeline orders
    the post-cancel exposure equals the pre-submit value (zero).

    Design: Difficulty/compensating_invariant/submit_cancel_conserves_exposure
    """
    base = setup_canonical_submitted_promoted_order()
    summary_pre = get_success_data(api_client.get_credit_summary(
        base["retailer"]["id"], credit_manager_headers,
    ))
    # Sanity: submit moved it up
    assert summary_pre["exposure_forward_cents"] == 58500
    get_success_data(api_client.cancel_order(base["order"]["id"], base["sm_headers"]))
    summary_post = get_success_data(api_client.get_credit_summary(
        base["retailer"]["id"], credit_manager_headers,
    ))
    assert summary_post["exposure_forward_cents"] == 0
    assert summary_post["ar_balance_cents"] == 0
