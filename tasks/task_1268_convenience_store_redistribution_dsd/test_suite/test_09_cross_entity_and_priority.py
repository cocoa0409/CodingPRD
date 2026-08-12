"""Cross-entity state dependencies and validation-priority pair conflicts."""
import pytest

from test_helpers import (
    ADMIN,
    CREDIT,
    ApiErrorId,
    api_client,
    assign_order_to_manifest,
    begin_loading,
    close_manifest,
    create_credit_memo_payload,
    create_delivery_manifest_payload,
    create_purchase_order_payload,
    get_success_data,
    make_store_manager_headers,
    order_line,
    publish_fuel_rate,
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


def test_confirm_delivery_gated_by_manifest_close(api, route_driver_headers):
    """PRD §3.6: "At the store door the `RouteDriver` confirms delivery of
    each `CLOSED` order — the manifest itself must be `CLOSED` or
    `COMPLETED`." When the manifest is still LOADING the order is ASSIGNED,
    not CLOSED, so the confirm is rejected with `ERR_INVALID_STATE`.

    Design: Difficulty/cross_entity_state_dependency/confirm_delivery_gated_by_manifest_close
    """
    base = setup_submitted_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}])
    manifest = setup_manifest()
    publish_fuel_rate(doe_index_usd=3.00)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    # Manifest in LOADING; order still ASSIGNED. Confirm is invalid.
    resp = api_client.confirm_delivery(base["order"]["id"], route_driver_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_confirm_delivery_gated_by_manifest_close_never_begun(api, route_driver_headers):
    """PRD §3.6: "confirms delivery of each `CLOSED` order — the manifest
    itself must be `CLOSED` or `COMPLETED`". When the manifest is SCHEDULED
    the order is ASSIGNED (not CLOSED), so confirm is rejected.

    Design: Difficulty/cross_entity_state_dependency/confirm_delivery_gated_by_manifest_close
    """
    base = setup_submitted_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}])
    manifest = setup_manifest()
    publish_fuel_rate(doe_index_usd=3.00)
    manifest = assign_order_to_manifest(manifest, base["order"])
    # Manifest SCHEDULED; order ASSIGNED (not CLOSED).
    resp = api_client.confirm_delivery(base["order"]["id"], route_driver_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_memo_post_gated_by_invoice_state(api, credit_manager_headers):
    """PRD §3.7: "Posting is legal only from `DRAFT` and only while the
    invoice is `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE`". A PAID invoice is
    outside that set, so posting a DRAFT memo against it is rejected with
    `ERR_INVALID_STATE`.

    Design: Difficulty/cross_entity_state_dependency/memo_post_gated_by_invoice_state
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    memo = get_success_data(api_client.create_credit_memo(
        invoice["id"],
        create_credit_memo_payload(origin="MANUAL", amount_cents=100),
        credit_manager_headers,
    ))
    # Pay off the invoice in full -> PAID
    get_success_data(api_client.apply_payment(
        invoice["id"], {"amount_cents": 60600, "method": "ACH"}, credit_manager_headers,
    ))
    resp = api_client.post_credit_memo(memo["id"], credit_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_memo_post_allowed_on_partially_paid_invoice(api, credit_manager_headers):
    """PRD §3.7: "Posting is legal only from `DRAFT` and only while the
    invoice is `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE`". Posting succeeds on
    PARTIALLY_PAID.

    Design: Difficulty/cross_entity_state_dependency/memo_post_gated_by_invoice_state
    """
    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
                                fuel_doe=3.00)
    invoice = base["invoice"]
    memo = get_success_data(api_client.create_credit_memo(
        invoice["id"],
        create_credit_memo_payload(origin="MANUAL", amount_cents=100),
        credit_manager_headers,
    ))
    # Partial payment -> PARTIALLY_PAID
    get_success_data(api_client.apply_payment(
        invoice["id"], {"amount_cents": 20000, "method": "ACH"}, credit_manager_headers,
    ))
    resp = api_client.post_credit_memo(memo["id"], credit_manager_headers)
    posted = validate_success(resp)
    assert posted["status"] == "POSTED"


def test_manifest_state_beats_overweight_constraint(api):
    """PRD §2.10: "Fourth, state and concurrency — `ERR_INVALID_STATE` for an
    illegal from-state, `ERR_MANIFEST_NOT_OPEN`, and `ERR_STALE_VERSION`.
    ... Seventh, business constraints — the uniqueness rules, order-guide
    membership, split-case permission, manifest weight, guide-day matching".
    PRD §3.5: "The manifest must be in `SCHEDULED` or `LOADING`, else
    `ERR_MANIFEST_NOT_OPEN` (HTTP 409); its `overweight_flag` must still be
    false, else `ERR_MANIFEST_OVERWEIGHT` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/manifest_state_beats_overweight_constraint
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
    publish_fuel_rate(doe_index_usd=3.00)
    get_success_data(api_client.assign_order(
        manifest["id"],
        {"order_id": poa["id"], "expected_manifest_version": manifest["version"]},
        ADMIN,
    ))
    m = get_success_data(api_client.get_delivery_manifest(manifest["id"], ADMIN))
    m = get_success_data(api_client.begin_loading(m["id"], ADMIN))
    m = get_success_data(api_client.close_manifest(
        m["id"], {"expected_manifest_version": m["version"]}, ADMIN,
    ))
    # Manifest is now CLOSED AND overweight_flag is true. State error wins.
    resp = api_client.assign_order(
        m["id"],
        {"order_id": pob["id"], "expected_manifest_version": m["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_MANIFEST_NOT_OPEN, expected_status=409)


def test_manifest_state_beats_overweight_constraint_completed(api):
    """PRD §2.10: state-category errors (priority 4) beat business-constraint
    errors (priority 7). When the manifest has auto-COMPLETED (still overweight)
    the assign attempt is rejected with ERR_MANIFEST_NOT_OPEN, not
    ERR_MANIFEST_OVERWEIGHT.

    Design: Difficulty/priority_pair_validation_conflict/manifest_state_beats_overweight_constraint
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
    publish_fuel_rate(doe_index_usd=3.00)
    get_success_data(api_client.assign_order(
        manifest["id"],
        {"order_id": poa["id"], "expected_manifest_version": manifest["version"]},
        ADMIN,
    ))
    m = get_success_data(api_client.get_delivery_manifest(manifest["id"], ADMIN))
    m = get_success_data(api_client.begin_loading(m["id"], ADMIN))
    m = get_success_data(api_client.close_manifest(
        m["id"], {"expected_manifest_version": m["version"]}, ADMIN,
    ))
    # Confirm delivery -> manifest auto-completes
    from test_helpers import DRIVER
    get_success_data(api_client.confirm_delivery(poa["id"], DRIVER))
    m = get_success_data(api_client.get_delivery_manifest(m["id"], ADMIN))
    assert m["status"] == "COMPLETED"
    assert m["overweight_flag"] is True
    resp = api_client.assign_order(
        m["id"],
        {"order_id": pob["id"], "expected_manifest_version": m["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_MANIFEST_NOT_OPEN, expected_status=409)


def test_stamp_safety_beats_cutoff_temporal(api):
    """PRD §2.10: "Fifth, regulated-product safety — the tobacco license and
    tax-stamp supply checks. Sixth, temporal rules — the order cutoff". When
    both would fire, ERR_TAX_STAMP_UNAVAILABLE is reported.

    Design: Difficulty/priority_pair_validation_conflict/stamp_safety_beats_cutoff_temporal
    """
    retailer, sm = setup_retailer(jurisdiction_code="NV_CLARK", tobacco_license_id="TLIC-7")
    t1 = setup_product(sku="T1", case_pack_units=60, case_cost_cents=33000,
                       unit_cost_cents=550, split_case_allowed=True, is_tobacco=True,
                       weight_lbs_per_case=15)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": t1["id"], "par_cases": 0}])
    # Past the 24h cutoff for MON 2026-05-25: cutoff = 2026-05-24T00:00Z.
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-24T12:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(retailer_id=retailer["id"], order_guide_id=guide["id"],
                                      lines=[order_line(t1["id"], cases_qty=1, split_units_qty=0)]),
        sm,
    ))
    resp = api_client.submit_order(
        order["id"], {"expected_order_version": order["version"]}, sm,
    )
    validate_error(resp, ApiErrorId.ERR_TAX_STAMP_UNAVAILABLE, expected_status=422)


def test_stamp_safety_beats_cutoff_temporal_license_present(api):
    """PRD §2.10: "the missing license surfaces before the absent stamp supply;
    stamp supply before the cutoff". With a tobacco license present but no
    stamp supply for the jurisdiction AND the cutoff passed, the stamp-supply
    error wins.

    Design: Difficulty/priority_pair_validation_conflict/stamp_safety_beats_cutoff_temporal
    """
    retailer, sm = setup_retailer(jurisdiction_code="NV_CLARK", tobacco_license_id="TLIC-7")
    t1 = setup_product(sku="T1", case_pack_units=60, case_cost_cents=33000,
                       unit_cost_cents=550, split_case_allowed=True, is_tobacco=True,
                       weight_lbs_per_case=15)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": t1["id"], "par_cases": 0}])
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-24T12:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(retailer_id=retailer["id"], order_guide_id=guide["id"],
                                      lines=[order_line(t1["id"], cases_qty=1, split_units_qty=0)]),
        sm,
    ))
    resp = api_client.submit_order(
        order["id"], {"expected_order_version": order["version"]}, sm,
    )
    body = resp.json()
    # Stamp-supply (p5) beats cutoff (p6)
    assert body["data"]["error_id"] == "ERR_TAX_STAMP_UNAVAILABLE"
    assert resp.status_code == 422
