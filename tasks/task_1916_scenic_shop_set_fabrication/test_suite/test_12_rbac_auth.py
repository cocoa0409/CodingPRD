"""RBAC denials and authentication failures. PRD §2.1."""
import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    EST,
    FOREMAN,
    PAINT,
    TC,
    ApiErrorId,
    create_engineering_review_payload,
    create_rom_bid,
    get_success_data,
    make_client_pm_headers,
    setup_accepted_production,
    setup_basic_scenario,
    setup_client,
    setup_in_build_production,
    setup_shop,
    submit_bid,
    accept_bid,
    validate_error,
)


class TestAuthFailures:
    def test_request_without_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value outside this declared set, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_without_auth_headers_returns_401
        """
        shop = setup_shop()
        # No auth headers at all
        resp = api.get_shop(shop["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_request_with_undeclared_role_returns_401(self, api):
        """PRD §2.1: "presenting an `X-User-Role` value outside this declared
        set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_with_invalid_role_returns_401
        """
        from test_helpers import TEST_USERS
        shop = setup_shop()
        resp = api.get_shop(shop["id"], headers=TEST_USERS["super_user_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_auth_failure_beats_not_found(self, api):
        """PRD §2.6: "Requests are evaluated in a fixed priority order, and a
        failure at any tier short-circuits the rest: 1. **Authentication and
        role** — headers present, role declared, role listed for the endpoint
        (failures: `ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN`). ... 3.
        **Existence** — ... `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/errors/auth_failure_beats_not_found
        """
        from test_helpers import NON_EXISTENT_UUID
        # No auth headers + nonexistent id
        resp = api.get_bid(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleDenials:
    def test_estimator_cannot_approve_engineering_review(self, api):
        """PRD §4 endpoint table: "Stamp approval ... | StaffEngineer" (the
        listed role is exclusive). PRD §2.1: "A request whose role is not
        listed for the endpoint it targets is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/estimator_cannot_approve_engineering_review
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        resp = api.approve_engineering_review(rev["id"], EST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api.get_engineering_review(rev["id"], ENGINEER))
        assert after["status"] == "PENDING"

    def test_client_cannot_create_takeoff(self, api):
        """PRD §4 endpoint table: "Open a material takeoff against a design
        package | Estimator". PRD §2.1: "A request whose role is not listed
        for the endpoint it targets is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/client_cannot_create_takeoff
        """
        _, client, pkg = setup_basic_scenario()
        resp = api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10},
            make_client_pm_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_foreman_cannot_adjust_stock(self, api):
        """PRD §4 endpoint table: "Adjust on-hand quantity by a signed delta
        ... | ShopAdmin". PRD §2.1: "A request whose role is not listed for
        the endpoint it targets is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/foreman_cannot_adjust_stock
        """
        shop = setup_shop()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 30,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        resp = api.adjust_stock_item(
            si["id"],
            {"delta_quantity": 5, "expected_stock_item_version": si["version"]},
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert after["quantity_on_hand"] == 30

    def test_transport_coordinator_cannot_start_build(self, api):
        """PRD §4 endpoint table: "Begin fabrication ... | ShopForeman". PRD
        §2.1: "A request whose role is not listed for the endpoint it targets
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/transport_coordinator_cannot_start_build
        """
        _, _, _, _, production, _rev, _res = setup_in_build_production()
        # production is now IN_BUILD; a fresh start-build on a new production
        # is what we want — rebuild to SCHEDULED state by creating a new one.
        _, _, _, _, prod2 = setup_accepted_production()
        # Approve review and reserve bay so only the role gate fails
        get_success_data(api.create_engineering_review(
            {"production_id": prod2["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        revs = api.list_engineering_reviews(
            FOREMAN, params={"production_id": prod2["id"]},
        )
        from test_helpers import validate_paginated
        rows, _ = validate_paginated(revs)
        api.approve_engineering_review(rows[0]["id"], ENGINEER)
        get_success_data(api.create_bay_reservation(
            {"production_id": prod2["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.start_build(prod2["id"], TC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api.get_production(prod2["id"], EST))
        assert after["status"] == "SCHEDULED"

    def test_estimator_cannot_run_epoch(self, api):
        """PRD §4 endpoint table: "Operations checkpoint ... | ShopAdmin".
        PRD §2.1: "A request whose role is not listed for the endpoint it
        targets is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/estimator_cannot_run_epoch
        """
        shop = setup_shop()
        resp = api.run_epoch(shop["id"], EST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert after["epoch_index"] == 0

    def test_staff_engineer_cannot_create_bay_reservation(self, api):
        """PRD §4 endpoint table: "Reserve a bay slot for a production window
        ... | ShopForeman". PRD §2.1: "A request whose role is not listed for
        the endpoint it targets is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/staff_engineer_cannot_create_bay_reservation
        """
        _, _, _, _, production = setup_accepted_production()
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        # No reservation persisted
        from test_helpers import validate_paginated
        data, meta = validate_paginated(api.list_bay_reservations(
            FOREMAN, params={"production_id": production["id"]},
        ))
        assert meta["total_count"] == 0


class TestOwnership:
    def test_client_cannot_accept_other_clients_bid(self, api):
        """PRD §2.1: "When `X-User-Role` is `ClientPM`, `X-User-ID` is the
        `id` of the acting `Client`; ownership checks on any resource that
        references a `Client` — a bid's `client_id`, a production's
        `client_id`, a design package's `client_id` — compare the resource's
        foreign-key field to `X-User-ID`, and a mismatch is rejected with
        `ERR_NOT_OWN_RESOURCE` (HTTP 403)."

        Design: Corner/validations/client_cannot_accept_other_clients_bid_returns_403
        """
        shop = setup_shop()
        cl_alpha = get_success_data(api.create_client(
            {"shop_id": shop["id"], "company_name": "Alpha Productions",
             "contact_email": "a@x.example", "credit_limit_cents": 100000000},
            ADMIN,
        ))
        cl_bravo = get_success_data(api.create_client(
            {"shop_id": shop["id"], "company_name": "Bravo Productions",
             "contact_email": "b@x.example", "credit_limit_cents": 100000000},
            ADMIN,
        ))
        from test_helpers import setup_design_package
        pkg = setup_design_package(cl_alpha["id"], show_title="Hamlet")
        bid = create_rom_bid(cl_alpha["id"], pkg["id"], estimated_crew_hours=100)
        submit_bid(bid["id"])
        # cl_bravo attempts to accept cl_alpha's bid
        resp = api.accept_bid(bid["id"], make_client_pm_headers(cl_bravo["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWN_RESOURCE, 403)
        after = get_success_data(api.get_bid(bid["id"], EST))
        assert after["status"] == "SUBMITTED"
