"""Authentication and role-based authorization across the endpoint surface."""
from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    add_order_line,
    approve_order,
    create_advertiser,
    create_avail_unit,
    create_avail_week,
    create_log_day,
    create_order,
    create_program,
    get_order,
    get_spot,
    list_line_spots,
    place_spot_payload,
    submit_order,
    validate_error,
    get_avail_unit,
)

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]
COPYDESK = TEST_USERS["copycoordinator_headers"]
BILLING = TEST_USERS["billingclerk_headers"]


class TestAuthentication:
    def test_missing_headers_rejected_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act."
        PRD §2.1: "A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        resp = api.list_programs(NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenials:
    def test_salesrep_cannot_approve_orders(self, api):
        """PRD §2.1: "A request whose authenticated role is not in the target endpoint's authorized list is rejected with `ERR_FORBIDDEN`."
        PRD §4: the approve endpoint `/traffic/orders/{id}/approve` lists TrafficManager as its only authorized role.

        Design: Corner/rbac/salesrep_cannot_approve_orders
        """
        advertiser = create_advertiser(name="RB")
        program = create_program(
            title="RB P", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        order = create_order(advertiser["id"])
        add_order_line(order["id"], program["id"], gross_rate_cents=5000)
        submit_order(order["id"])
        resp = api.approve_order(
            order["id"],
            {"expected_order_version": get_order(order["id"])["version"]},
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_order(order["id"])["status"] == "SUBMITTED"

    def test_billingclerk_cannot_place_spots(self, api):
        """PRD §2.1: "A request whose authenticated role is not in the target endpoint's authorized list is rejected with `ERR_FORBIDDEN`."
        PRD §4: the placement endpoint `/traffic/spots/{id}/place` lists TrafficManager as its only authorized role.

        Design: Corner/rbac/billingclerk_cannot_place_spots
        """
        advertiser = create_advertiser(name="RB2")
        program = create_program(
            title="RB2 P", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(week["id"], program["id"], "2026-08-08", total_seconds=60)
        order = create_order(advertiser["id"])
        line = add_order_line(order["id"], program["id"], gross_rate_cents=5000)
        submit_order(order["id"])
        approve_order(order["id"])
        spot = list_line_spots(line["id"])[0]
        resp = api.place_spot(
            spot["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_spot(spot["id"])["status"] == "PENDING_PLACEMENT"

    def test_copycoordinator_cannot_reconcile(self, api):
        """PRD §2.1: "A request whose authenticated role is not in the target endpoint's authorized list is rejected with `ERR_FORBIDDEN`."
        PRD §4: the reconcile endpoint `/traffic/log-days/{id}/reconcile` lists BillingClerk as its only authorized role.

        Design: Corner/rbac/copycoordinator_cannot_reconcile
        """
        week = create_avail_week("2026-08-03")
        log = create_log_day(week["id"], "2026-08-03")
        resp = api.reconcile_log_day(log["id"], {"entries": []}, COPYDESK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_trafficmanager_cannot_create_copy(self, api):
        """PRD §2.1: "A request whose authenticated role is not in the target endpoint's authorized list is rejected with `ERR_FORBIDDEN`."
        PRD §4: the copy registration endpoint `/traffic/copy-instructions` lists CopyCoordinator as its only authorized role.

        Design: Corner/rbac/trafficmanager_cannot_create_copy
        """
        advertiser = create_advertiser(name="RB4", credit_limit_cents=100000)
        resp = api.create_copy_instruction(
            {"advertiser_id": advertiser["id"], "length_seconds": 30}, TRAFFIC
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
