"""Shop and client primitives: creation defaults, summary, pagination."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    EST,
    NON_EXISTENT_UUID,
    STANDARD_CAPACITY_HORIZON_HOURS,
    assert_client,
    assert_shop,
    create_client_payload,
    create_shop_payload,
    get_success_data,
    make_client_pm_headers,
    setup_basic_scenario,
    setup_client,
    setup_shop,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShopCreation:
    def test_create_shop_returns_computed_defaults(self, api):
        """PRD §3.1: "A new shop starts with `committed_crew_hours` 0,
        `capacity_ratio_bp` 0, `posture` `OPEN`, `inventory_value_cents` 0, and
        `epoch_index` 0."

        Design: Corner/entities/create_shop_returns_201_with_computed_defaults
        """
        shop = get_success_data(api.create_shop(create_shop_payload(), ADMIN))
        assert_shop(shop)
        assert shop["posture"] == "OPEN"
        assert shop["committed_crew_hours"] == 0
        assert shop["capacity_ratio_bp"] == 0
        assert shop["inventory_value_cents"] == 0
        assert shop["epoch_index"] == 0
        assert shop["version"] == 1

    def test_create_shop_returns_201_status_code(self, api):
        """PRD §4: "Operations that create a new resource return `201 Created`."

        Design: Corner/entities/create_shop_returns_201_with_computed_defaults
        """
        resp = api.create_shop(create_shop_payload(), ADMIN)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}"
        data = validate_success(resp, expected_status=201)
        assert_shop(data)


class TestClientPagination:
    def test_list_clients_first_page(self, api):
        """PRD §2.3: "`limit` specifies the maximum number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        specifies how many items to skip and defaults to 0. ... The `meta`
        object of a list response carries four pagination fields: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_clients_pagination_window_and_flags
        """
        shop = setup_shop()
        for name in ("Alpha Productions", "Bravo Productions", "Charlie Productions"):
            setup_client(
                shop["id"],
                company_name=name,
                contact_email=f"{name[0].lower()}@x.example",
                credit_limit_cents=1000000,
            )
        data, meta = validate_paginated(
            api.list_clients(EST, params={"shop_id": shop["id"], "limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2 and meta["offset"] == 0

    def test_list_clients_second_page(self, api):
        """PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_clients_pagination_window_and_flags
        """
        shop = setup_shop()
        for name in ("Alpha Productions", "Bravo Productions", "Charlie Productions"):
            setup_client(
                shop["id"],
                company_name=name,
                contact_email=f"{name[0].lower()}@x.example",
                credit_limit_cents=1000000,
            )
        data, meta = validate_paginated(
            api.list_clients(EST, params={"shop_id": shop["id"], "limit": 2, "offset": 2})
        )
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestShopSummary:
    def test_shop_summary_matches_components_after_accept(self, api):
        """PRD §3.7: "A separate computed read, the shop summary, reports
        `posture`, `committed_crew_hours`, `capacity_crew_hours_horizon` (the
        product of `weekly_crew_hours_capacity` and `horizon_weeks`),
        `capacity_ratio_bp`, `active_productions` (the count of productions in
        the committed set), `inventory_value_cents`, and `epoch_index` on
        demand."

        Design: Corner/endpoints/shop_summary_computed_read_matches_components
        """
        from test_helpers import (
            create_rom_bid, setup_basic_scenario, submit_bid, accept_bid,
        )
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"], estimated_crew_hours=320)
        submit_bid(bid["id"])
        accept_bid(bid["id"], client["id"])
        summary = get_success_data(api.get_shop_summary(shop["id"], ADMIN))
        assert summary["posture"] == "TIGHT"
        assert summary["capacity_ratio_bp"] == 8000
        assert summary["committed_crew_hours"] == 320
        assert summary["capacity_crew_hours_horizon"] == STANDARD_CAPACITY_HORIZON_HOURS
        assert summary["active_productions"] == 1
        assert summary["inventory_value_cents"] == 0
        assert summary["epoch_index"] == 0
