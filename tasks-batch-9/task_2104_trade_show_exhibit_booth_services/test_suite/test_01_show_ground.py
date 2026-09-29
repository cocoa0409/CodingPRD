"""Show-ground surface: venues, jurisdictions, warehouses, shows, exhibitors and booths.

Covers the creation defaults each of those rows is born with, the read-back of a
show's stored calendar, booth listing and pagination, and the not-found identifiers
that path segments and body foreign keys resolve to.
"""
from datetime import datetime

import pytest

from test_helpers import (
    DEFAULTS,
    NON_EXISTENT_UUID,
    SHOW_CALENDAR,
    TEST_USERS,
    ApiErrorId,
    add_booth,
    assert_booth,
    assert_show,
    assert_venue,
    assert_warehouse,
    create_booth_payload,
    create_exhibitor,
    create_jurisdiction_payload,
    create_labor_call_payload,
    create_show,
    create_show_payload,
    create_venue,
    create_venue_payload,
    create_warehouse_payload,
    make_exhibitor_headers,
    setup_show_ground,
    validate_error,
    validate_paginated,
    validate_success,
    walk_show_to,
)

OPS = TEST_USERS["show_operations_headers"]


def _as_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so a stored calendar field compares by instant."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestVenueCreation:

    def test_create_venue_returns_201_with_declared_and_default_fields(self, api):
        """PRD §3.1: "The straight-time labor band is declared as two UTC times of day in `HH:MM` form: `straight_time_start_hhmm`, defaulting to `08:00`, and `straight_time_end_hhmm`, defaulting to `16:30`, whose instant is the exclusive end of the band."

        PRD §3.1: "`max_forklift_capacity_lbs` is the heaviest single crate the venue's material-handling equipment may lift and defaults to 6000 pounds."

        PRD §3.1: "`dock_count` records how many receiving docks the building has and defaults to 4."

        PRD §3.1: "A venue's `status` is either `ACTIVE` or `INACTIVE` and defaults to `ACTIVE`."

        PRD §2.5: "`version` — an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including server-initiated cascades."

        Design: Corner/entities/create_venue_returns_201_with_declared_and_default_fields
        """
        response = api.create_venue(create_venue_payload(), OPS)

        venue = validate_success(response, 201)
        assert_venue(venue)
        assert venue["name"] == "Metro Convention Center", \
            "The venue echoes back the trade name it was registered with"
        assert venue["city"] == "Chicago", "The venue echoes back the city it sits in"
        assert venue["straight_time_start_hhmm"] == DEFAULTS["VENUE_STRAIGHT_TIME_START"], \
            "straight_time_start_hhmm defaults to 08:00"
        assert venue["straight_time_end_hhmm"] == DEFAULTS["VENUE_STRAIGHT_TIME_END"], \
            "straight_time_end_hhmm defaults to 16:30"
        assert venue["max_forklift_capacity_lbs"] == DEFAULTS["VENUE_MAX_FORKLIFT_LBS"], \
            "max_forklift_capacity_lbs defaults to 6000 pounds"
        assert venue["dock_count"] == DEFAULTS["VENUE_DOCK_COUNT"], \
            "dock_count defaults to 4 receiving docks"
        assert venue["status"] == "ACTIVE", "A venue's status defaults to ACTIVE"
        assert venue["version"] == 1, "A freshly written row begins at version 1"

    def test_create_venue_defaults_the_hanging_sign_booth_types(self, api):
        """PRD §3.1: "`hanging_sign_booth_types` lists the booth geometries permitted to fly a hanging sign here and defaults to `ISLAND` and `PENINSULA`."

        Design: Corner/entities/create_venue_returns_201_with_declared_and_default_fields
        """
        response = api.create_venue(create_venue_payload(), OPS)

        venue = validate_success(response, 201)
        assert sorted(venue["hanging_sign_booth_types"]) == \
            sorted(DEFAULTS["VENUE_HANGING_SIGN_BOOTH_TYPES"]), \
            "hanging_sign_booth_types defaults to ISLAND and PENINSULA"

    def test_create_venue_response_carries_the_object_envelope(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/create_venue_returns_201_with_declared_and_default_fields
        """
        response = api.create_venue(create_venue_payload(), OPS)
        validate_success(response, 201)

        body = response.json()
        assert body["response_type"] == "object", \
            "A single created resource is reported with response_type object"
        assert body["meta"]["api_request_id"].startswith("req_"), \
            f"api_request_id must start with req_, got {body['meta']['api_request_id']}"


class TestShowReadBack:

    def test_get_show_returns_the_stored_calendar_instants(self, api):
        """PRD §3.1: "Creating one supplies `venue_id`, a `name`, and seven instants that together define every deadline the pricing engine reads: `discount_deadline`, `advance_warehouse_deadline`, `move_in_start`, `move_in_end`, `show_open`, `show_close` and `move_out_end`."

        Design: Corner/entities/get_show_by_id_returns_stored_calendar_and_derived_fields
        """
        venue = create_venue()
        show = create_show(venue["id"])

        response = api.get_show(show["id"], OPS)

        read_back = validate_success(response, 200)
        assert_show(read_back)
        assert read_back["venue_id"] == venue["id"], \
            "The show reports the venue it was bound to"
        for field, supplied in SHOW_CALENDAR.items():
            assert _as_instant(read_back[field]) == _as_instant(supplied), \
                f"Show.{field} must read back as {supplied}, got {read_back[field]}"

    def test_get_show_reports_zeroed_derived_counters_on_a_fresh_show(self, api):
        """PRD §3.1: "Shows are born in `DRAFT` with `committed_labor_hours` at 0 and `cancelled_labor_call_count` at 0, and their `status` is server-managed throughout."

        Design: Corner/entities/get_show_by_id_returns_stored_calendar_and_derived_fields
        """
        venue = create_venue()
        show = create_show(venue["id"])

        response = api.get_show(show["id"], OPS)

        read_back = validate_success(response, 200)
        assert read_back["status"] == "DRAFT", \
            f"A fresh show is DRAFT, got {read_back['status']}"
        assert read_back["committed_labor_hours"] == pytest.approx(0, abs=0.01), \
            "committed_labor_hours starts at 0 on a fresh show"
        assert read_back["cancelled_labor_call_count"] == 0, \
            "cancelled_labor_call_count starts at 0 on a fresh show"


class TestBoothListing:

    def test_list_booths_first_page_reports_total_count_and_has_more(self, api):
        """PRD §2.3: "`total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."

        Design: Corner/entities/list_booths_paginated_reports_total_count_and_has_more
        """
        ground = setup_show_ground(booth_number="1024")
        add_booth(ground, "1026", booth_type="INLINE")
        add_booth(ground, "1028", booth_type="CORNER")

        response = api.list_booths(
            OPS, params={"show_id": ground["show"]["id"], "limit": 2, "offset": 0})

        rows, meta = validate_paginated(response)
        assert len(rows) == 2, f"limit=2 caps the page at 2 booths, got {len(rows)}"
        assert meta["total_count"] == 3, \
            f"total_count counts all 3 booths on the show, got {meta['total_count']}"
        assert meta["has_more"] is True, \
            "has_more is true while a third booth remains beyond the window"
        assert meta["limit"] == 2 and meta["offset"] == 0, \
            "The envelope echoes the requested limit and offset"
        for booth in rows:
            assert_booth(booth)
            assert booth["show_id"] == ground["show"]["id"], \
                "The show_id filter restricts the page to that show's booths"

    def test_list_booths_last_page_reports_has_more_false(self, api):
        """PRD §2.3: "`total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."

        Design: Corner/entities/list_booths_paginated_reports_total_count_and_has_more
        """
        ground = setup_show_ground(booth_number="1024")
        add_booth(ground, "1026", booth_type="INLINE")
        add_booth(ground, "1028", booth_type="CORNER")

        response = api.list_booths(
            OPS, params={"show_id": ground["show"]["id"], "limit": 2, "offset": 2})

        rows, meta = validate_paginated(response)
        assert len(rows) == 1, f"Only the third booth remains at offset 2, got {len(rows)}"
        assert meta["total_count"] == 3, \
            f"total_count is unaffected by the page window, got {meta['total_count']}"
        assert meta["has_more"] is False, \
            "has_more is false once the window reaches the last matching row"


class TestExhibitorNotFound:

    def test_get_exhibitor_with_unknown_id_returns_exhibitor_not_found(self, api):
        """PRD §2.8: "Each resource type has its own not-found identifier, all of them HTTP 404: `ERR_VENUE_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_EXHIBITOR_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_CRATE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_LABOR_CALL_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REFURB_NOT_FOUND` and `ERR_LICENSE_NOT_FOUND`."

        Design: Corner/entities/get_exhibitor_not_found_returns_404
        """
        response = api.get_exhibitor(NON_EXISTENT_UUID, OPS)

        validate_error(response, ApiErrorId.ERR_EXHIBITOR_NOT_FOUND)
        assert response.json()["response_type"] == "error", \
            "A 404 is reported through the error envelope"


class TestWarehouseCreation:

    def test_create_warehouse_applies_free_days_and_rate_defaults(self, api):
        """PRD §3.1: "`storage_rate_cents_per_cwt_per_month` sets the between-show storage rate in cents per hundredweight per billable month and defaults to 2200."

        PRD §3.1: "`free_days` grants a grace period before metered storage begins and defaults to 30 days."

        PRD §3.1: "`dock_capacity_cwt` caps the aggregate hundredweight of receiving appointments that may overlap any single instant and defaults to 300."

        Design: Corner/entities/create_warehouse_applies_free_days_and_rate_defaults
        """
        response = api.create_warehouse(create_warehouse_payload(), OPS)

        warehouse = validate_success(response, 201)
        assert_warehouse(warehouse)
        assert warehouse["free_days"] == DEFAULTS["WAREHOUSE_FREE_DAYS"], \
            "free_days defaults to a 30 day grace period"
        assert warehouse["storage_rate_cents_per_cwt_per_month"] == \
            DEFAULTS["WAREHOUSE_STORAGE_RATE"], \
            "storage_rate_cents_per_cwt_per_month defaults to 2200 cents"
        assert warehouse["dock_capacity_cwt"] == DEFAULTS["WAREHOUSE_DOCK_CAPACITY_CWT"], \
            "dock_capacity_cwt defaults to 300 hundredweight"

    def test_create_warehouse_starts_accepting_with_zero_committed_cwt(self, api):
        """PRD §3.1: "A warehouse's `status` is `ACCEPTING` or `CLOSED` and defaults to `ACCEPTING`; a `CLOSED` warehouse takes no new crates."

        PRD §3.1: "`committed_cwt` is derived, starts at 0, and is described in §3.6."

        Design: Corner/entities/create_warehouse_applies_free_days_and_rate_defaults
        """
        response = api.create_warehouse(create_warehouse_payload(), OPS)

        warehouse = validate_success(response, 201)
        assert warehouse["status"] == "ACCEPTING", \
            f"A new warehouse defaults to ACCEPTING, got {warehouse['status']}"
        assert warehouse["committed_cwt"] == 0, \
            f"committed_cwt starts at 0, got {warehouse['committed_cwt']}"


class TestBoothRequestShape:

    def test_create_booth_with_undeclared_booth_type_returns_invalid_request(self, api):
        """PRD §2.9: "Request shape: every required body field is present, every enum value is a declared member of its enumeration, every integer field is a non-negative integer, and every datetime parses as ISO 8601 — otherwise `ERR_INVALID_REQUEST` (400)."

        PRD §3.2: "`ShowOperations` assigns one by supplying the `show_id` it sits on, the `exhibitor_id` holding it, a `booth_number` from the floor plan, the contracted `sqft`, and a `booth_type` of `INLINE`, `CORNER`, `PENINSULA` or `ISLAND`."

        Design: Corner/entities/create_booth_invalid_enum_booth_type_returns_invalid_request
        """
        venue = create_venue()
        show = create_show(venue["id"])
        walk_show_to(show["id"], "OPEN_FOR_ORDERS")
        exhibitor = create_exhibitor()

        response = api.create_booth(
            create_booth_payload(show["id"], exhibitor["id"],
                                 booth_number="1024", booth_type="PERIMETER"),
            OPS)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api.list_booths(OPS, params={"show_id": show["id"]}))
        assert meta["total_count"] == 0, \
            f"A rejected booth is never persisted, found {meta['total_count']} rows"
        assert rows == [], "A rejected booth is never persisted"


class TestJurisdictionPathParent:

    def test_create_jurisdiction_under_unknown_venue_returns_venue_not_found(self, api):
        """PRD §2.8: "A request naming a jurisdiction under a venue that does not exist therefore fails with `ERR_VENUE_NOT_FOUND`, never with `ERR_JURISDICTION_NOT_FOUND`."

        Design: Corner/entities/create_jurisdiction_under_missing_venue_returns_404
        """
        response = api.create_jurisdiction(
            NON_EXISTENT_UUID,
            create_jurisdiction_payload(trade="ELECTRICAL",
                                        straight_time_rate_cents_per_hour=11000),
            OPS)

        validate_error(response, ApiErrorId.ERR_VENUE_NOT_FOUND)


class TestBoothNumberUniqueness:

    def test_duplicate_booth_number_within_show_is_rejected(self, api):
        """PRD §3.2: "Booth numbers must be unique within their show; a repeat within the same `show_id` is refused with `ERR_DUPLICATE_BOOTH_NUMBER`, while the same number on a different show is perfectly acceptable."

        Design: Corner/entities/duplicate_booth_number_within_show_rejected
        """
        ground = setup_show_ground(booth_number="1024")

        response = api.create_booth(
            create_booth_payload(ground["show"]["id"], ground["exhibitor"]["id"],
                                 booth_number="1024", sqft=200, booth_type="INLINE"),
            OPS)

        validate_error(response, ApiErrorId.ERR_DUPLICATE_BOOTH_NUMBER)
        rows, meta = validate_paginated(
            api.list_booths(OPS, params={"show_id": ground["show"]["id"]}))
        assert meta["total_count"] == 1, \
            f"The refused booth left the show with 1 row, got {meta['total_count']}"
        assert len(rows) == 1, "The refused booth was never persisted"

    def test_same_booth_number_on_a_different_show_is_accepted(self, api):
        """PRD §3.2: "Booth numbers must be unique within their show; a repeat within the same `show_id` is refused with `ERR_DUPLICATE_BOOTH_NUMBER`, while the same number on a different show is perfectly acceptable."

        Design: Corner/entities/duplicate_booth_number_within_show_rejected
        """
        ground = setup_show_ground(booth_number="1024")
        second_show = create_show(ground["venue"]["id"], name="AutoTech 2026 East")
        walk_show_to(second_show["id"], "OPEN_FOR_ORDERS")

        response = api.create_booth(
            create_booth_payload(second_show["id"], ground["exhibitor"]["id"],
                                 booth_number="1024", sqft=200, booth_type="INLINE"),
            OPS)

        booth = validate_success(response, 201)
        assert_booth(booth)
        assert booth["booth_number"] == "1024", \
            "Booth 1024 is free again on a second show"
        assert booth["show_id"] == second_show["id"], \
            "The accepted booth sits on the second show"


class TestShowInitialState:

    def test_new_show_starts_in_draft_with_zeroed_counters(self, api):
        """PRD §3.1: "Shows are born in `DRAFT` with `committed_labor_hours` at 0 and `cancelled_labor_call_count` at 0, and their `status` is server-managed throughout."

        PRD §2.5: "`version` — an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including server-initiated cascades."

        Design: Corner/state_machines/new_show_starts_in_draft_initial_state
        """
        venue = create_venue()

        response = api.create_show(create_show_payload(venue["id"]), OPS)

        show = validate_success(response, 201)
        assert_show(show)
        assert show["status"] == "DRAFT", \
            f"A show is born in DRAFT, got {show['status']}"
        assert show["committed_labor_hours"] == pytest.approx(0, abs=0.01), \
            "A show is born with committed_labor_hours at 0"
        assert show["cancelled_labor_call_count"] == 0, \
            "A show is born with cancelled_labor_call_count at 0"
        assert show["version"] == 1, "A freshly written show begins at version 1"


class TestPaginationBounds:

    def test_list_booths_with_limit_zero_returns_invalid_pagination(self, api):
        """PRD §2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_zero_returns_invalid_pagination
        """
        ground = setup_show_ground(booth_number="1024")

        response = api.list_booths(
            OPS, params={"show_id": ground["show"]["id"], "limit": 0})

        validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION)


class TestPathNotFoundCodes:

    @pytest.mark.parametrize("client_method,expected_error", [
        ("get_show", ApiErrorId.ERR_SHOW_NOT_FOUND),
        ("get_venue", ApiErrorId.ERR_VENUE_NOT_FOUND),
        ("get_warehouse", ApiErrorId.ERR_WAREHOUSE_NOT_FOUND),
        ("get_booth", ApiErrorId.ERR_BOOTH_NOT_FOUND),
        ("get_exhibit_asset", ApiErrorId.ERR_ASSET_NOT_FOUND),
        ("get_exhibit_design", ApiErrorId.ERR_DESIGN_NOT_FOUND),
        ("get_service_order", ApiErrorId.ERR_SERVICE_ORDER_NOT_FOUND),
        ("get_crate", ApiErrorId.ERR_CRATE_NOT_FOUND),
        ("get_drayage_shipment", ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
        ("get_labor_call", ApiErrorId.ERR_LABOR_CALL_NOT_FOUND),
        ("get_change_order", ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND),
        ("get_invoice", ApiErrorId.ERR_INVOICE_NOT_FOUND),
        ("get_damage_claim", ApiErrorId.ERR_CLAIM_NOT_FOUND),
        ("get_refurb_work_order", ApiErrorId.ERR_REFURB_NOT_FOUND),
    ])
    def test_unknown_path_resource_returns_the_entity_specific_code(
            self, api, client_method, expected_error):
        """PRD §2.8: "Each resource type has its own not-found identifier, all of them HTTP 404: `ERR_VENUE_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_EXHIBITOR_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_CRATE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_LABOR_CALL_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REFURB_NOT_FOUND` and `ERR_LICENSE_NOT_FOUND`."

        Design: Corner/errors/path_resource_not_found_returns_the_entity_specific_code
        """
        response = getattr(api, client_method)(NON_EXISTENT_UUID, OPS)

        validate_error(response, expected_error)


class TestBodyForeignKeyNotFoundCodes:

    def test_create_booth_with_unknown_exhibitor_returns_exhibitor_not_found(self, api):
        """PRD §2.8: "They are resolved in the order the endpoint declares its input fields, and the first one that fails to resolve produces the not-found identifier matching the entity it referenced."

        Design: Corner/errors/body_foreign_key_not_found_returns_the_referenced_entity_code
        """
        ground = setup_show_ground(booth_number="1024")

        response = api.create_booth(
            create_booth_payload(ground["show"]["id"], NON_EXISTENT_UUID,
                                 booth_number="9999", sqft=100, booth_type="INLINE"),
            OPS)

        validate_error(response, ApiErrorId.ERR_EXHIBITOR_NOT_FOUND)
        rows, meta = validate_paginated(
            api.list_booths(OPS, params={"show_id": ground["show"]["id"]}))
        assert meta["total_count"] == 1, \
            f"The rejected booth was not persisted, got {meta['total_count']} rows"
        assert len(rows) == 1, "The rejected booth was not persisted"

    def test_create_labor_call_with_unknown_jurisdiction_returns_jurisdiction_not_found(
            self, api):
        """PRD §2.8: "They are resolved in the order the endpoint declares its input fields, and the first one that fails to resolve produces the not-found identifier matching the entity it referenced."

        Design: Corner/errors/body_foreign_key_not_found_returns_the_referenced_entity_code
        """
        ground = setup_show_ground(show_status="ON_SITE", booth_number="1024",
                                   with_jurisdiction=True)

        response = api.create_labor_call(
            create_labor_call_payload(ground["booth"]["id"], NON_EXISTENT_UUID), OPS)

        validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_FOUND)

    def test_lead_batch_against_unknown_license_returns_license_not_found(self, api):
        """PRD §2.8: "Identifiers that appear in a URL path are resolved strictly left to right, and the first identifier that does not name an existing row terminates the request with the 404 that belongs to *that* resource type — the server does not proceed to look up anything further to its right."

        Design: Corner/errors/body_foreign_key_not_found_returns_the_referenced_entity_code
        """
        ground = setup_show_ground(show_status="ON_SITE", booth_number="1024")

        response = api.ingest_lead_batch(
            NON_EXISTENT_UUID,
            {"badge_ids": ["B1"], "captured_at": "2026-09-21T12:00:00Z"},
            make_exhibitor_headers(ground["exhibitor"]["id"]))

        validate_error(response, ApiErrorId.ERR_LICENSE_NOT_FOUND)
