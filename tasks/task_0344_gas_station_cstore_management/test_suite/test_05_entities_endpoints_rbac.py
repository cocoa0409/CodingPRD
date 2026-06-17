"""Entity CRUD, action endpoints, and role-based access control.

Covers the entities, endpoints, and rbac corner-design instances PRD prose uniquely
determines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_manager_headers, make_cashier_headers,
    ApiErrorId, NON_EXISTENT_UUID,
    factories as f,
)
import test_helpers.fixtures as fx

MANAGER = make_manager_headers()
CASHIER = make_cashier_headers("cash1")
CASHIER2 = make_cashier_headers("cash2")


class TestEntityCrud:
    def test_create_station_returns_201_with_defaults(self, api):
        """PRD §3.1: "`tax_rate_bp`, the sales tax in basis points applied to taxable store
        items, defaults to 825 (that is, 8.25%); and `cash_variance_tolerance_cents`, the
        absolute drawer variance in cents within which a closing shift is judged `BALANCED`,
        defaults to 200 (two dollars). On creation the station's `current_utc` is set to the
        epoch baseline and its `version` is 1."

        Design: Corner/entities/create_station_returns_201_with_defaults
        """
        st = validate_success(api.create_station(
            f.create_station_payload(name="Main St Fuel", brand="Acme"), MANAGER), 201)
        assert st["tax_rate_bp"] == 825
        assert st["cash_variance_tolerance_cents"] == 200
        assert st["version"] == 1

    def test_get_station_returns_stored_entity(self, api):
        """PRD §3.1: "A `StationManager` brings a site online by creating a `Station` with a
        display `name` and a `brand` banner."

        Design: Corner/entities/get_station_returns_stored_entity
        """
        st = validate_success(api.create_station(
            f.create_station_payload(name="Main St Fuel", brand="Acme"), MANAGER), 201)
        fetched = validate_success(api.get_station(st["id"], MANAGER), 200)
        assert fetched["name"] == "Main St Fuel"

    def test_list_fuel_grades_paginated_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_fuel_grades_paginated_envelope
        """
        station = fx.create_station()
        fx.create_grade(station["id"], code="REGULAR")
        data, meta = validate_paginated(api.list_fuel_grades(MANAGER, params={"station_id": station["id"]}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_get_tank_nonexistent_returns_not_found(self, api):
        """PRD §2.6: "The first reference that does not resolve causes the request to be
        rejected with `ERR_NOT_FOUND` before any later reference or business rule is evaluated."

        Design: Corner/entities/get_tank_nonexistent_returns_not_found
        """
        validate_error(api.get_tank(NON_EXISTENT_UUID, MANAGER), ApiErrorId.ERR_NOT_FOUND)

    def test_create_pump_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.8: "(4) body well-formedness — required fields present, enum values legal,
        numeric fields non-negative (`ERR_INVALID_REQUEST`)"
        PRD §3.2: "A `Pump` is created under a `station_id` and bound to the tank it draws
        from via `tank_id`, with an island `number` that is unique within the station."

        Design: Corner/entities/create_pump_missing_required_field_returns_invalid_request
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        # number is omitted.
        validate_error(api.create_pump(
            {"station_id": station["id"], "tank_id": tank["id"]}, MANAGER),
            ApiErrorId.ERR_INVALID_REQUEST)

    def test_delivery_invoice_total_is_computed(self, api):
        """PRD §3.3: "At creation the system computes `invoice_total_cents` as the net gallons
        multiplied by the unit cost, rounded half-up to whole cents."

        Design: Corner/entities/delivery_invoice_total_is_computed
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        tank = fx.create_tank(station["id"], grade["id"])
        delivery = validate_success(api.create_delivery(
            f.create_delivery_payload(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280),
            MANAGER), 201)
        assert delivery["invoice_total_cents"] == 1400000, f"got {delivery['invoice_total_cents']}"

    def test_create_fuel_grade_invalid_enum_code_rejected(self, api):
        """PRD §3.1: "A grade is created with its owning `station_id`, a `code` — one of
        `REGULAR`, `MIDGRADE`, `PREMIUM`, or `DIESEL`, unique within the station"
        PRD §2.8: "(4) body well-formedness — required fields present, enum values legal,
        numeric fields non-negative (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/create_fuel_grade_invalid_enum_code_rejected
        """
        station = fx.create_station()
        validate_error(api.create_fuel_grade(
            {"station_id": station["id"], "code": "SUPER_ULTRA", "octane": 100}, MANAGER),
            ApiErrorId.ERR_INVALID_REQUEST)

    def test_reprice_records_prior_price_computed_field(self, api):
        """PRD §3.1: "A new grade starts with `current_price_cents` and `weighted_avg_cost_cents`
        both at 0; `prior_price_cents` is also 0 until the first reprice. Repricing a grade
        records the move: the existing `current_price_cents` is copied into `prior_price_cents`,
        and `current_price_cents` is set to the supplied `new_price_cents`."

        Design: Corner/entities/reprice_records_prior_price_computed_field
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        repriced = validate_success(api.reprice_fuel_grade(
            grade["id"], f.reprice_payload(399), MANAGER), 200)
        assert repriced["prior_price_cents"] == 0, "grade started at 0"
        assert repriced["current_price_cents"] == 399

    def test_create_tank_wrong_parent_grade_not_found(self, api):
        """PRD §2.6: "The system validates that every referenced resource exists, checking
        them left to right — path identifiers first, then body foreign keys in declaration
        order. The first reference that does not resolve causes the request to be rejected with
        `ERR_NOT_FOUND` before any later reference or business rule is evaluated."

        Design: Corner/entities/create_tank_wrong_parent_grade_not_found
        """
        station = fx.create_station()
        validate_error(api.create_tank(
            f.create_tank_payload(station["id"], NON_EXISTENT_UUID, label="T1",
                                  capacity_gallons=10000, reorder_point_gallons=1500), MANAGER),
            ApiErrorId.ERR_NOT_FOUND)

    def test_tanks_filtered_by_grade(self, api):
        """PRD §4 (endpoint table): "GET `/tanks` List tanks, filterable by station and grade"
        PRD §2.3: "Paginated list responses include the following fields in the `meta` object
        of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/fk_reverse_tanks_filtered_by_grade
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR")
        fx.create_tank(station["id"], grade["id"], label="T1")
        fx.create_tank(station["id"], grade["id"], label="T2", capacity_gallons=8000,
                       reorder_point_gallons=1000)
        data, meta = validate_paginated(api.list_tanks(MANAGER, params={"fuel_grade_id": grade["id"]}))
        assert meta["total_count"] == 2


class TestActionEndpoints:
    def test_cash_drop_reduces_expected_drawer(self, api):
        """PRD §3.5: "When the cashier moves cash to the safe, the recorded drop's
        `amount_cents` is added to `cash_drops_cents` and `expected_drawer_cents` is
        recomputed; the shift's `version` is incremented."
        PRD §3.5: "The shift's `expected_drawer_cents` is always the opening float plus
        accumulated cash sales, minus accumulated cash payouts, minus accumulated cash drops."

        Design: Corner/endpoints/cash_drop_reduces_expected_drawer
        """
        station = fx.create_station()
        shift = fx.open_shift(station["id"], opening_float_cents=20000)
        updated = validate_success(api.record_drop(
            shift["id"], f.drop_payload(5000), CASHIER), 200)
        assert updated["cash_drops_cents"] == 5000
        assert updated["expected_drawer_cents"] == 15000

    def test_reprice_updates_current_and_prior_price(self, api):
        """PRD §3.1: "Repricing a grade records the move: the existing `current_price_cents`
        is copied into `prior_price_cents`, and `current_price_cents` is set to the supplied
        `new_price_cents`."

        Design: Corner/endpoints/reprice_updates_grade_current_and_prior_price
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=399)
        repriced = validate_success(api.reprice_fuel_grade(
            grade["id"], f.reprice_payload(425), MANAGER), 200)
        assert repriced["prior_price_cents"] == 399
        assert repriced["current_price_cents"] == 425


class TestRbac:
    def test_cashier_cannot_create_station(self, api):
        """PRD §2.1: "A `StationManager` cannot ring sales or operate a shift drawer."
        PRD §2.1: "When the headers are present but the declared role is not permitted to
        perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/cashier_cannot_create_station
        """
        validate_error(api.create_station(
            f.create_station_payload(name="S", brand="Acme"), CASHIER),
            ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_open_shift(self, api):
        """PRD §2.1: "A `CashierAttendant` runs the register and the drawer: opening shifts,
        recording cash drops, beginning the count and closing shifts"
        PRD §2.1: "When the headers are present but the declared role is not permitted to
        perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/manager_cannot_open_shift
        """
        station = fx.create_station()
        validate_error(api.create_shift(
            f.create_shift_payload(station["id"], opening_float_cents=20000), MANAGER),
            ApiErrorId.ERR_FORBIDDEN)

    def test_non_owner_cashier_cannot_close_shift(self, api):
        """PRD §3.5: "Only the cashier who owns the shift may begin the count or close it. For
        these two owner-only operations the acting cashier's `X-User-ID` must equal the shift's
        `cashier_user_id`, or the request is rejected with `ERR_NOT_SHIFT_OWNER`."

        Design: Corner/rbac/non_owner_cashier_cannot_close_shift
        """
        station = fx.create_station()
        counting = fx.open_shift_counting(station["id"], cashier_id="cash1")
        # cash2 (not the owner) tries to close.
        validate_error(api.close_shift(
            counting["id"], f.close_shift_payload(20000, counting["version"]), CASHIER2),
            ApiErrorId.ERR_NOT_SHIFT_OWNER)

    def test_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must be authenticated with two mandatory HTTP
        headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which
        declares the operational capacity under which the request is made. If either header is
        missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_header_unauthenticated
        """
        validate_error(api.get_station(NON_EXISTENT_UUID, {}), ApiErrorId.ERR_UNAUTHENTICATED)
