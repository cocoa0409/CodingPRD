"""Machine-availability tests: press buffered-adjacency conflict and embroidery-station
half-open oversubscription — the two distinct interval geometries of §3.2.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_shop_catalog,
    setup_confirmed_order,
    create_press,
    create_station,
    create_production_run_payload,
    api_client,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# resource_temporal_overlap — press buffered adjacency
# ═══════════════════════════════════════════════════════════════════════════

def test_press_buffered_adjacency_conflict(api):
    """PRD §3.2: "On a press, a new run is rejected when its window starts within
    `teardown_buffer_min` minutes after a prior non-terminal run's `window_end`, or when
    it ends within `teardown_buffer_min` minutes before a prior run's `window_start`;
    that buffered-adjacency conflict raises `ERR_PRESS_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/press_buffered_adjacency_conflict
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(cat, size_run={"L": 30})
    order_id = parts["order"]["id"]
    press_id = create_press(cat["shop"]["id"], teardown_buffer_min=30)["id"]
    # Run A [10:00,12:00).
    validate_success(
        api.create_production_run(
            order_id,
            create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z", press_id=press_id
            ), SM,
        ), 201
    )
    # Run B [12:15,13:00): 15-min gap < 30-min teardown buffer -> conflict.
    res = api.create_production_run(
        order_id,
        create_production_run_payload(
            "2026-06-02T12:15:00.000Z", "2026-06-02T13:00:00.000Z", press_id=press_id
        ), SM,
    )
    validate_error(res, "ERR_PRESS_WINDOW_CONFLICT", expected_status=409)


def test_press_run_well_clear_of_buffer_accepted(api):
    """PRD §3.2: "On a press, a new run is rejected when its window starts within
    `teardown_buffer_min` minutes after a prior non-terminal run's `window_end`, or when
    it ends within `teardown_buffer_min` minutes before a prior run's `window_start`".

    Design: Difficulty/resource_temporal_overlap/press_buffered_adjacency_conflict
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(cat, size_run={"L": 30})
    order_id = parts["order"]["id"]
    press_id = create_press(cat["shop"]["id"], teardown_buffer_min=30)["id"]
    # Run A [10:00,12:00).
    validate_success(
        api.create_production_run(
            order_id,
            create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z", press_id=press_id
            ), SM,
        ), 201
    )
    # Run B [14:00,15:00): 120-min gap, well beyond the 30-min teardown buffer -> accepted.
    res = api.create_production_run(
        order_id,
        create_production_run_payload(
            "2026-06-02T14:00:00.000Z", "2026-06-02T15:00:00.000Z", press_id=press_id
        ), SM,
    )
    run = validate_success(res, 201)
    assert run["status"] == "SCHEDULED"


# ═══════════════════════════════════════════════════════════════════════════
# resource_temporal_overlap — embroidery station half-open oversubscription
# ═══════════════════════════════════════════════════════════════════════════

def test_embroidery_station_oversubscribed_on_true_overlap(api):
    """PRD §3.2: "On an embroidery station, runs may touch exactly (a gap of zero is
    allowed), but the count of non-terminal runs whose half-open windows overlap a new
    run's window may not exceed the station's `head_count`; exceeding it raises
    `ERR_STATION_OVERSUBSCRIBED`."

    Design: Difficulty/resource_temporal_overlap/embroidery_station_halfopen_oversubscribe
    """
    cat = setup_shop_catalog(
        method_type="EMBROIDERY",
        method_overrides={"digitizing_fee_cents": 5000, "stitch_run_per_1k_cents": 90},
        style_overrides={
            "sku_code": "CAP-100", "name": "Cap", "blank_cost_cents": 600,
            "available_colors": ["BLACK"], "available_sizes": ["OS"],
        },
        sku_size="OS", stock_qty=100,
    )
    parts = setup_confirmed_order(
        cat, size_run={"OS": 30}, line_overrides={"num_locations": 1, "stitch_count": 8500}
    )
    order_id = parts["order"]["id"]
    station_id = create_station(cat["shop"]["id"], head_count=1)["id"]
    # Run A [10:00,12:00).
    validate_success(
        api.create_production_run(
            order_id,
            create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z",
                embroidery_station_id=station_id
            ), SM,
        ), 201
    )
    # Run B [11:00,13:00): true [11:00,12:00) overlap exceeds head_count 1.
    res = api.create_production_run(
        order_id,
        create_production_run_payload(
            "2026-06-02T11:00:00.000Z", "2026-06-02T13:00:00.000Z",
            embroidery_station_id=station_id
        ), SM,
    )
    validate_error(res, "ERR_STATION_OVERSUBSCRIBED", expected_status=409)


def test_embroidery_station_touching_window_accepted(api):
    """PRD §3.2: "On an embroidery station, runs may touch exactly (a gap of zero is
    allowed), but the count of non-terminal runs whose half-open windows overlap a new
    run's window may not exceed the station's `head_count`".

    Design: Difficulty/resource_temporal_overlap/embroidery_station_halfopen_oversubscribe
    """
    cat = setup_shop_catalog(
        method_type="EMBROIDERY",
        method_overrides={"digitizing_fee_cents": 5000, "stitch_run_per_1k_cents": 90},
        style_overrides={
            "sku_code": "CAP-100", "name": "Cap", "blank_cost_cents": 600,
            "available_colors": ["BLACK"], "available_sizes": ["OS"],
        },
        sku_size="OS", stock_qty=100,
    )
    parts = setup_confirmed_order(
        cat, size_run={"OS": 30}, line_overrides={"num_locations": 1, "stitch_count": 8500}
    )
    order_id = parts["order"]["id"]
    station_id = create_station(cat["shop"]["id"], head_count=1)["id"]
    # Run A [10:00,12:00).
    validate_success(
        api.create_production_run(
            order_id,
            create_production_run_payload(
                "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z",
                embroidery_station_id=station_id
            ), SM,
        ), 201
    )
    # Run B [12:00,13:00): touches exactly at 12:00 (gap zero, half-open) -> accepted.
    res = api.create_production_run(
        order_id,
        create_production_run_payload(
            "2026-06-02T12:00:00.000Z", "2026-06-02T13:00:00.000Z",
            embroidery_station_id=station_id
        ), SM,
    )
    run = validate_success(res, 201)
    assert run["status"] == "SCHEDULED"
