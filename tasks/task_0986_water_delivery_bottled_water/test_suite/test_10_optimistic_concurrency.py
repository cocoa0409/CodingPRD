"""Optimistic concurrency: stale version rejection on customer update and on
stop delivery against the parent route."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_customer, setup_two_customers, create_route, plan_stop, publish_route,
    start_route, arrive_stop, create_deliver_payload,
    get_route,
    OPS_ADMIN, DISPATCHER, DRIVER,
)


class TestCustomerOcc:
    def test_occ_stale_customer_version(self, api):
        """PRD §2.9: "First, updating a customer record requires the request to
        carry `expected_customer_version`, holding the customer `version` the
        client last observed. If another writer has advanced the customer's
        `version` since that read — for example because a delivery cascaded a
        `bottles_on_site` update onto the account — the value will no longer
        match and the update is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from overwriting an account state it has not
        observed."

        Design: Corner/cross_cutting_layers/occ_stale_customer_version
        """
        world = setup_customer(account_type="HOME", business_name="OCC",
                               billing_email="o@x.example", service_address="1 O")
        customer = world["customer"]
        v1 = customer["version"]

        updated = validate_success(
            api.update_customer(customer["id"],
                                {"expected_customer_version": v1,
                                 "business_name": "OCC-Updated"},
                                OPS_ADMIN),
            200,
        )
        assert updated["version"] == v1 + 1, "a successful update bumps the version by one"

        res = api.update_customer(customer["id"],
                                  {"expected_customer_version": v1,
                                   "business_name": "Stale"},
                                  OPS_ADMIN)
        validate_error(res, "ERR_STALE_VERSION")


class TestRouteOccOnDeliver:
    def test_occ_stale_route_version_on_deliver(self, api):
        """PRD §2.9: "Second, recording a delivery against a stop requires the
        request to carry `expected_route_version`, holding the parent route's
        `version` as last observed by the driver. Because every delivery, skip,
        or failure on a route mutates the route's `committed_bottles` and bumps
        the route's `version`, a stale value signals that the driver's view of
        the route is out of date, and the delivery is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_route_version_on_deliver
        """
        world = setup_two_customers(
            a_overrides={"service_mode": "AUTO", "par_level_bottles": 1},
            b_overrides={"service_mode": "AUTO", "par_level_bottles": 1},
        )
        zone = world["zone"]
        route = create_route(zone["id"], "2026-06-01")
        stop_1 = plan_stop(route["id"], world["customer_a"]["id"], sequence_index=1)
        stop_2 = plan_stop(route["id"], world["customer_b"]["id"], sequence_index=2)
        publish_route(route["id"])
        start_route(route["id"], "2026-06-01T08:00:00Z")
        arrive_stop(stop_1["id"])
        arrive_stop(stop_2["id"])

        stale_version = get_route(route["id"])["version"]
        # First delivery succeeds against the observed version and bumps it.
        first = validate_success(
            api.deliver_stop(stop_1["id"],
                             create_deliver_payload(stale_version, 1, 1),
                             DRIVER),
            200,
        )
        assert first["stop_status"] == "DELIVERED"
        assert get_route(route["id"])["version"] != stale_version, \
            "a delivery mutates committed_bottles and bumps the route version"

        # Second delivery with the now-stale version is rejected.
        res = api.deliver_stop(stop_2["id"],
                               create_deliver_payload(stale_version, 1, 1),
                               DRIVER)
        validate_error(res, "ERR_STALE_VERSION")
