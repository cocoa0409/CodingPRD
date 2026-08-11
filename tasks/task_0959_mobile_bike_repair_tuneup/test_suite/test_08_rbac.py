"""Role-based access control denials."""
from test_helpers import (
    ApiErrorId,
    get_request,
    make_customer,
    make_customer_headers,
    make_mechanic,
    make_mechanic_headers,
    make_van,
    setup_quoted_request,
    validate_error,
    validate_success,
)


class TestRbacDenials:
    def test_customer_cannot_create_zone_returns_forbidden(self, api, dispatcher_headers):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "A `PlatformAdmin` defines the service territory as a set of
        zones."

        Design: Corner/rbac/customer_cannot_create_zone_returns_forbidden
        """
        cust = make_customer("INDIVIDUAL")
        resp = api.create_zone({"name": "Z9", "base_callout_fee_cents": 100},
                               make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_mechanic_cannot_dispatch_stop_returns_forbidden(self, api, dispatcher_headers):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "Dispatching places a `QUOTED` request onto an `OPEN` route
        day" — an operation the §4 index lists for `Dispatcher` only.

        Design: Corner/rbac/mechanic_cannot_dispatch_stop_returns_forbidden
        """
        ctx = setup_quoted_request()
        mech = make_mechanic(ctx["zone"]["id"])
        van = make_van(ctx["zone"]["id"], mechanic_id=mech["id"])
        rd = validate_success(api.create_route_day(
            {"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers), 201)
        resp = api.create_route_stop(rd["id"], {
            "service_request_id": ctx["request"]["id"],
            "planned_start": "2026-05-02T10:00:00Z", "planned_end": "2026-05-02T11:00:00Z",
        }, make_mechanic_headers(mech["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_request(ctx["request"]["id"])["work_status"] == "QUOTED", (
            "forbidden dispatch must leave the request QUOTED")

    def test_customer_cannot_register_bike_for_other_customer_returns_forbidden(
            self, api, dispatcher_headers):
        """PRD §3.1: "Bikes are registered by a `Customer` — only for their own
        account, meaning the supplied `customer_id` must belong to the caller —
        or by a `Dispatcher` on a customer's behalf."
        PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
        the acting `Customer`; ownership checks on any resource that references a
        customer compare the resource's foreign-key field (for example a bike's
        `customer_id`) to `X-User-ID`"

        Design: Corner/rbac/customer_cannot_register_bike_for_other_customer_returns_forbidden
        """
        ann = make_customer("INDIVIDUAL")
        bob = make_customer("INDIVIDUAL")
        resp = api.create_bike({"customer_id": bob["id"], "bike_type": "MECHANICAL"},
                               make_customer_headers(ann["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
