"""Temporal overlap rules (delivery windows, promos) and optimistic concurrency."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    begin_loading,
    create_delivery_manifest_payload,
    create_delivery_window_payload,
    create_order_guide_payload,
    create_product_payload,
    create_promo_event_payload,
    create_purchase_order_payload,
    create_retailer_payload,
    get_success_data,
    make_store_manager_headers,
    order_line,
    publish_fuel_rate,
    setup_draft_order,
    setup_guide,
    setup_product,
    setup_retailer,
    validate_error,
    validate_success,
)


def test_route_window_half_open_plus_buffer(api, admin_headers):
    """PRD §3.3: "Windows are half-open intervals: a window occupies its start
    up to but not including its end. A new window is rejected with
    `ERR_DELIVERY_WINDOW_OVERLAP` (HTTP 409) when its half-open span overlaps
    an existing window on the same route, when it begins before an earlier
    window's end plus that window's turnaround buffer".

    Design: Difficulty/resource_temporal_overlap/route_window_half_open_plus_buffer
    """
    get_success_data(api_client.create_delivery_window(
        create_delivery_window_payload(
            route_code="R-7",
            window_start="2026-06-01T06:00:00Z",
            window_end="2026-06-01T08:00:00Z",
            turnaround_buffer_minutes=30,
        ),
        admin_headers,
    ))
    # 08:15 start is inside 08:00+30 buffer -> rejected
    resp = api_client.create_delivery_window(
        create_delivery_window_payload(
            route_code="R-7",
            window_start="2026-06-01T08:15:00Z",
            window_end="2026-06-01T09:00:00Z",
            turnaround_buffer_minutes=30,
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP, expected_status=409)
    # 08:30 start == end + buffer -> allowed (half-open + exact buffer adjacency)
    ok_resp = api_client.create_delivery_window(
        create_delivery_window_payload(
            route_code="R-7",
            window_start="2026-06-01T08:30:00Z",
            window_end="2026-06-01T09:30:00Z",
            turnaround_buffer_minutes=30,
        ),
        admin_headers,
    )
    ok = validate_success(ok_resp, expected_status=201)
    assert ok["id"]


def test_route_window_distinct_routes_do_not_overlap(api, admin_headers):
    """PRD §3.3: overlap is checked "on the same route". Windows on different
    routes do not conflict even when their times intersect.

    Design: Difficulty/resource_temporal_overlap/route_window_half_open_plus_buffer
    """
    get_success_data(api_client.create_delivery_window(
        create_delivery_window_payload(
            route_code="R-7",
            window_start="2026-06-01T06:00:00Z",
            window_end="2026-06-01T08:00:00Z",
            turnaround_buffer_minutes=30,
        ),
        admin_headers,
    ))
    # Same time span but different route -> allowed
    resp = api_client.create_delivery_window(
        create_delivery_window_payload(
            route_code="R-99",
            window_start="2026-06-01T07:00:00Z",
            window_end="2026-06-01T09:00:00Z",
            turnaround_buffer_minutes=30,
        ),
        admin_headers,
    )
    ok = validate_success(resp, expected_status=201)
    assert ok["route_code"] == "R-99"


def test_promo_closed_interval_touch_overlap(api, admin_headers, sales_rep_headers):
    """PRD §3.2: "Two promos for the same product may not overlap: because the
    windows are closed inclusive intervals, a new event whose date range
    touches any existing event's range for that product is rejected with
    `ERR_PROMO_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/promo_closed_interval_touch_overlap
    """
    p4 = setup_product(sku="P4")
    get_success_data(api_client.create_promo_event(
        create_promo_event_payload(product_id=p4["id"], promo_type="OFF_INVOICE",
                                   discount_pct_bps=500,
                                   start_date="2026-06-01", end_date="2026-06-07"),
        sales_rep_headers,
    ))
    # Touch at inclusive end -> rejected
    resp = api_client.create_promo_event(
        create_promo_event_payload(product_id=p4["id"], promo_type="SCAN_BACK",
                                   discount_pct_bps=250,
                                   start_date="2026-06-07", end_date="2026-06-14"),
        sales_rep_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PROMO_WINDOW_OVERLAP, expected_status=409)
    # First non-overlapping start (day after inclusive end) -> allowed
    ok_resp = api_client.create_promo_event(
        create_promo_event_payload(product_id=p4["id"], promo_type="SCAN_BACK",
                                   discount_pct_bps=250,
                                   start_date="2026-06-08", end_date="2026-06-14"),
        sales_rep_headers,
    )
    ok = validate_success(ok_resp, expected_status=201)
    assert ok["id"]


def test_promo_overlap_only_same_product(api, admin_headers, sales_rep_headers):
    """PRD §3.2: "Two promos for the same product may not overlap". A promo on
    a different product may overlap freely.

    Design: Difficulty/resource_temporal_overlap/promo_closed_interval_touch_overlap
    """
    p4 = setup_product(sku="P4")
    p5 = setup_product(sku="P5")
    get_success_data(api_client.create_promo_event(
        create_promo_event_payload(product_id=p4["id"], promo_type="OFF_INVOICE",
                                   discount_pct_bps=500,
                                   start_date="2026-06-01", end_date="2026-06-07"),
        sales_rep_headers,
    ))
    resp = api_client.create_promo_event(
        create_promo_event_payload(product_id=p5["id"], promo_type="OFF_INVOICE",
                                   discount_pct_bps=500,
                                   start_date="2026-06-01", end_date="2026-06-07"),
        sales_rep_headers,
    )
    ok = validate_success(resp, expected_status=201)
    assert ok["product_id"] == p5["id"]


def test_occ_stale_version_on_order_submit(api):
    """PRD §2.7: "Submitting a purchase order requires the request to carry
    `expected_order_version`, holding the order's current `version` as the
    client last read it. If the order's version has advanced since that read
    ... the submission is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_order_submit
    """
    base = setup_draft_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}])
    stale_version = base["order_version"] - 1
    resp = api_client.submit_order(
        base["order"]["id"], {"expected_order_version": stale_version}, base["sm_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    # Fresh version succeeds
    ok_resp = api_client.submit_order(
        base["order"]["id"], {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    ok = validate_success(ok_resp)
    assert ok["status"] == "SUBMITTED"
    assert ok["version"] == base["order_version"] + 1


def test_occ_stale_version_on_manifest_close(api, admin_headers):
    """PRD §2.7: "Closing a delivery manifest requires the request to carry
    `expected_manifest_version` ... Assigning orders to a manifest legitimately
    increments the manifest's version, so a close that carries an older
    observed version is stale and is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_manifest_close
    """
    manifest = get_success_data(api_client.create_delivery_manifest(
        create_delivery_manifest_payload(), admin_headers,
    ))
    publish_fuel_rate(doe_index_usd=3.00)
    manifest_v2 = get_success_data(api_client.begin_loading(manifest["id"], admin_headers))
    # Close carrying pre-begin-loading version -> stale
    resp = api_client.close_manifest(
        manifest["id"], {"expected_manifest_version": manifest_v2["version"] - 1},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    # Correct version succeeds and increments
    ok_resp = api_client.close_manifest(
        manifest["id"], {"expected_manifest_version": manifest_v2["version"]},
        admin_headers,
    )
    ok = validate_success(ok_resp)
    assert ok["status"] == "CLOSED"
    assert ok["version"] == manifest_v2["version"] + 1


def test_read_after_write_submit_computed_fields(api, admin_headers):
    """PRD §3.4: "the pricing engine computes the order's commercial fields"
    at submit; the response and a follow-up GET must agree (no lag, no
    recompute drift).

    Design: Corner/consistency_model/read_after_write_submit_computed_fields
    """
    base = setup_draft_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}])
    submit_resp = api_client.submit_order(
        base["order"]["id"], {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    submitted = validate_success(submit_resp)
    assert submitted["merch_subtotal_cents"] == 60000
    assert submitted["provisional_total_cents"] == 60600
    reread = get_success_data(api_client.get_purchase_order(base["order"]["id"], admin_headers))
    assert reread["merch_subtotal_cents"] == submitted["merch_subtotal_cents"]
    assert reread["provisional_total_cents"] == submitted["provisional_total_cents"]
