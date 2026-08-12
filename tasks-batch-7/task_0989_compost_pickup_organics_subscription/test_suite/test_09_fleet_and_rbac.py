"""Bin-fleet conservation across subscribe/cancel, and role/ownership denials.

Covers PRD §2.1 (roles and ownership), §2.11 (visibility scoping), §3.2
(bin assignment), §3.5 (cancel returns bins).
"""
from test_helpers import (
    ApiErrorId,
    cancel_subscription,
    create_bins,
    create_plan_res,
    create_route,
    create_subscriber,
    create_subscription,
    create_subscription_payload,
    create_route_payload,
    generate_and_get_pickups,
    get_bin,
    get_pickup,
    make_subscriber_headers,
    setup_active_subscription,
    tag_pickup,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBinFleetConservation:
    def _fleet_counts(self, api, ops_headers):
        depot, meta_d = validate_paginated(
            api.list_bins(ops_headers, params={"status": "IN_DEPOT"})
        )
        at_customer, meta_c = validate_paginated(
            api.list_bins(ops_headers, params={"status": "AT_CUSTOMER"})
        )
        return meta_d["total_count"], meta_c["total_count"]

    def test_subscription_create_consumes_depot_bin(self, api, ops_headers):
        """PRD §3.2: "First, the depot must yield the bins: the system selects
        `included_bins` bins whose `bin_type` matches the plan's, whose
        `status` is `IN_DEPOT`, and whose `condition` is `CLEAN`, taking the
        earliest-created eligible bins first; if the depot runs short, creation
        fails with `ERR_NO_BIN_AVAILABLE`."
        PRD §3.2: "Each selected bin moves to `AT_CUSTOMER` with its
        `current_subscription_id` set to the new subscription."

        Design: Difficulty/compensating_invariant/subscription_create_then_cancel_conserves_bin_fleet
        """
        plan = create_plan_res()
        route = create_route()
        create_bins(3)
        sub = create_subscriber()
        before_depot, before_customer = self._fleet_counts(api, ops_headers)
        assert (before_depot, before_customer) == (3, 0)
        create_subscription(sub["id"], plan["id"], route["id"])
        after_depot, after_customer = self._fleet_counts(api, ops_headers)
        assert (after_depot, after_customer) == (2, 1)

    def test_cancel_returns_bin_dirty_and_conserves_fleet(self, api, ops_headers):
        """PRD §3.5: "cancelling transitions all of the subscription's
        `SCHEDULED` pickups to `CANCELLED_SYSTEM` and returns every assigned
        bin to the depot — `status` to `IN_DEPOT`, `condition` to
        `NEEDS_WASH`, `current_subscription_id` cleared — then increments the
        subscription's `version`."

        Design: Difficulty/compensating_invariant/subscription_create_then_cancel_conserves_bin_fleet
        """
        plan = create_plan_res()
        route = create_route()
        bins = create_bins(3)
        sub = create_subscriber()
        subscription = create_subscription(sub["id"], plan["id"], route["id"])
        cancel_subscription(subscription["id"])
        depot, at_customer = self._fleet_counts(api, ops_headers)
        assert (depot, at_customer) == (3, 0), "fleet cardinality is conserved"
        returned = get_bin(bins[0]["id"])
        assert returned["status"] == "IN_DEPOT"
        assert returned["condition"] == "NEEDS_WASH"
        assert returned.get("current_subscription_id") is None


class TestRoleDenials:
    def test_subscriber_cannot_create_routes(self, api):
        """PRD §2.1: "A request whose role is not listed on the target endpoint
        — or, for a `Subscriber` caller, one that targets a resource the caller
        does not own — is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /routes is listed for OperationsManager only.

        Design: Corner/rbac/subscriber_cannot_create_routes_forbidden
        """
        sub = create_subscriber()
        resp = api.create_route(
            create_route_payload(), make_subscriber_headers(sub["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_subscriber_cannot_skip_others_pickup(self, api):
        """PRD §2.1: "or, for a `Subscriber` caller, one that targets a resource
        the caller does not own — is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §2.11: "`Subscriber` callers never see other subscribers' data."

        Design: Corner/rbac/subscriber_cannot_skip_others_pickup_forbidden
        """
        env = setup_active_subscription(bin_count=1, subscriber_email="a@x.com")
        other = create_subscriber(email="b@x.com", full_name="Sub B", address="2 B St")
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01"]
        )[0]
        resp = api.skip_pickup(pickup["id"], make_subscriber_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_pickup(pickup["id"])["status"] == "SCHEDULED"


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request with missing headers, or whose declared role is
        not one of these four, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.10: "When several checks apply to one request, the server
        evaluates them in a fixed order, so an earlier failure masks every
        later one. First, authentication: both headers present and the role
        recognized, otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_route(create_route_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
