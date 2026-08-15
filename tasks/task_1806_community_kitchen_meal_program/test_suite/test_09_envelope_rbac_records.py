"""Cross-cutting contracts: auth, validation, pagination, RBAC denials,
append-only record shape, and FK reverse-reachability listings."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_menu_item,
    assert_waste_log,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    OFFICER,
    create_accepted_batch,
    create_food_batch,
    create_guest,
    create_menu_day,
    create_menu_item,
    create_site,
    create_volunteer,
    create_waste_log,
    inspect_batch,
    set_clock,
)
from test_helpers.test_users import TEST_USERS, make_volunteer_headers

ADMIN = TEST_USERS["program_admin_headers"]


class TestAuthenticationAndValidation:
    def test_missing_auth_headers_returns_unauthenticated(self, api, no_auth_headers):
        """PRD 2.1: "A request missing either header, or carrying a role value
        outside this list, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_sites(no_auth_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401

    def test_missing_required_field_returns_validation(self, api):
        """PRD 2.6: "A structurally malformed body — a missing required field
        or a value of the wrong JSON type — fails first with `ERR_VALIDATION`
        (HTTP 400)."

        Design: Corner/errors/missing_required_field_returns_validation
        """
        resp = api.create_site(
            {"name": "Bad Site", "togo_capacity_per_window": 15,
             "delivery_radius_km": 5},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400


class TestPagination:
    def test_response_envelope_and_pagination(self, api):
        """PRD 2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and it is bounded below by 1 and above
        by 100. The `offset` parameter skips a number of items from the head
        of the result set and defaults to 0. Every list response is sorted by
        the resources' `created_at` timestamp in ascending order, and the
        `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/response_envelope_and_pagination
        """
        for i in range(1, 13):
            create_site(name=f"S{i:02d}", dine_in_capacity=10,
                        togo_capacity_per_window=5, delivery_radius_km=3)

        data, meta = validate_paginated(api.list_sites(ADMIN))
        assert len(data) == 10, (
            f"default page must honor the limit default of 10, got {len(data)}"
        )
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        data, meta = validate_paginated(
            api.list_sites(ADMIN, params={"limit": 10, "offset": 10})
        )
        assert len(data) == 2, (
            f"second page must return the remaining 2, got {len(data)}"
        )
        assert meta["has_more"] is False


class TestVolunteerUniqueness:
    def test_volunteer_duplicate_email_rejected(self, api):
        """PRD 3.4: "Volunteers are registered by a `ProgramAdmin` or
        `KitchenManager` with a `full_name`, a contact `email` (unique across
        the program; duplicates are rejected with `ERR_CONSTRAINT_VIOLATION`)"

        Design: Corner/entities/volunteer_duplicate_email_rejected
        """
        create_volunteer(full_name="First", email="dup@x.org")
        resp = api.create_volunteer(
            {"full_name": "Second", "email": "dup@x.org"}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)


class TestRbacDenials:
    def test_volunteer_cannot_create_menu_day(self, api):
        """PRD 2.1: "A request whose authenticated role is not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD 4: POST `/kitchen/menu-days` — Authorized Role(s): KitchenManager.

        Design: Corner/rbac/volunteer_cannot_create_menu_day
        """
        site = create_site(name="RBAC Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        volunteer = create_volunteer(full_name="Vol RBAC")
        resp = api.create_menu_day(
            {"site_id": site["id"], "service_date": "2026-08-11"},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert resp.status_code == 403

    def test_kitchen_manager_cannot_inspect_batches(self, api):
        """PRD 2.1: "A `FoodSafetyOfficer` is the independent inspector: the
        only role permitted to begin a batch inspection, record an inspection
        outcome, or reject a batch, a deliberate segregation from the kitchen
        staff who receive and allocate food"
        PRD 2.1: "A request whose authenticated role is not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/kitchen_manager_cannot_inspect_batches
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="SoD Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        batch = create_food_batch(
            site["id"], source_type="DONATION", item_description="cans",
            quantity_servings=5, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-30T00:00:00Z",
        )
        get_success_data(api.begin_inspection(batch["id"], OFFICER))
        resp = api.record_inspection(batch["id"], {"result": "PASSED"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert resp.status_code == 403


class TestAppendOnlyRecords:
    def test_waste_log_immutable_no_version(self, api):
        """PRD 2.4: "Two record types are append-only exceptions to this
        convention. A batch allocation and a waste log each carry only `id`
        and `created_at`; both `updated_at` and `version` are absent from
        these records, since neither is ever modified after being written."
        PRD 3.8: "the server stamps `logged_at`."

        Design: Corner/entities/waste_log_immutable_no_version
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Imm Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        batch = create_food_batch(
            site["id"], source_type="DONATION", item_description="cans",
            quantity_servings=10, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-30T00:00:00Z",
        )
        inspect_batch(batch["id"], "PASSED")
        menu_day = create_menu_day(site["id"], "2026-08-11")
        log = create_waste_log(menu_day["id"], batch["id"], servings_wasted=2,
                               reason="SPOILAGE", disposition="COMPOST")
        assert_waste_log(log)

        fetched = get_success_data(api.get_waste_log(log["id"], MANAGER))
        assert_waste_log(fetched)
        assert "logged_at" in fetched, "waste log must carry server-stamped logged_at"


class TestFkReverseReachability:
    def test_fk_reverse_reachability_menu_items(self, api):
        """PRD 4: GET `/kitchen/menu-days/{id}/menu-items` — "List items of a
        menu day".
        PRD 2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/entities/fk_reverse_reachability_menu_items
        """
        site = create_site(name="FK Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        create_menu_item(menu_day["id"], name="A", planned_servings=5)
        create_menu_item(menu_day["id"], name="B", planned_servings=5)

        data, meta = validate_paginated(api.list_menu_day_items(menu_day["id"], MANAGER))
        assert len(data) == 2, (
            f"the menu day's item listing must return both children, "
            f"got {len(data)}"
        )
        for item in data:
            assert_menu_item(item)
