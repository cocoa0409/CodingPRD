"""Listing/pagination, reverse-reachability filtering, and the AVL action endpoint.

Corner queue: endpoints section.
"""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS,
    new_depot, new_vehicle, setup_started_assignment, new_application,
    make_operator_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]
YARD = TEST_USERS["yard_headers"]


def test_list_vehicles_reports_pagination_meta(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the total
    number of records matching the filter, disregarding pagination), and `has_more` (true
    when records remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/list_vehicles_paginated
    """
    depot = new_depot(salt_tons_on_hand=10, brine_gallons_on_hand=10)
    new_vehicle(depot["id"], unit_number="T1", vehicle_type="COMBO")
    new_vehicle(depot["id"], unit_number="T2", vehicle_type="PLOW")
    resp = api.list_vehicles(DISPATCH, params={"home_depot_id": depot["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_list_applications_filtered_by_depot(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the total
    number of records matching the filter, disregarding pagination), and `has_more` (true
    when records remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/reverse_reachability_applications_by_depot
    """
    scene = setup_started_assignment(planned_material_tons=5.0)
    new_application(scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"],
                    material_type="SALT", salt_tons=5.0, lane_miles_treated=2.0, pavement_temp_f=15)
    resp = api.list_applications(YARD, params={"depot_id": scene["depot"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta


def test_avl_ping_updates_last_position(api):
    """PRD §3.5: "A ping supplies a `lat` and a `lon`, and may optionally supply
    `plow_down`. Recording a ping updates the assignment's `last_lat` and `last_lon`, sets
    `plow_down` (which defaults to false and reflects whether the blade was down on the
    latest ping), and stamps `last_ping_at` from the logical clock."

    Design: Corner/endpoints/avl_ping_updates_position
    """
    scene = setup_started_assignment(planned_material_tons=2.0)
    resp = api.avl_ping(scene["assignment"]["id"], {"lat": 40.5, "lon": -74.2, "plow_down": True},
                        make_operator_headers(scene["operator"]["id"]))
    data = validate_success(resp, 200)
    assert data["last_lat"] == 40.5, data
    assert data["plow_down"] is True, data
