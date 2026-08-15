"""Registration defaults, input validation, uniqueness, auth headers, RBAC
role denials, and existence-before-state ordering (PRD §2.1, §2.5, §3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    complete_trip_at,
    create_distributor,
    create_driver,
    create_pricing_period,
    create_product,
    create_return,
    create_route,
    create_store,
    make_distributor_owner_headers,
    make_driver_headers,
    make_store_receiver_headers,
    run_trip_readings,
    set_clock,
    setup_delivered_order,
    validate_error,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]
MA = TEST_USERS["market_admin_headers"]
QI = TEST_USERS["quality_inspector_headers"]
OWNER_SHARED = TEST_USERS["distributor_owner_headers"]
DRIVER_SHARED = TEST_USERS["route_driver_headers"]
RECEIVER_SHARED = TEST_USERS["store_receiver_headers"]


def test_distributor_store_product_defaults_applied(api, territory_manager_headers):
    """PRD §3.1: "`credit_terms_days`, the number of days a store may carry an
    open invoice, defaulting to 7 when omitted."
    PRD §3.1: "an optional `credit_price_basis` of `ORIGINAL` or `CURRENT`,
    defaulting to `ORIGINAL`"
    PRD §3.1: "A new store starts `ACTIVE` with `crate_balance`,
    `open_ar_cents`, and `deposit_liability_cents` all at zero."
    PRD §3.1: "`weight_lbs_per_unit` defaulting to 8.6 (one gallon of milk
    weighs 8.6 pounds), `list_price_cents` defaulting to 0 as the flat
    per-unit price for non-regulated products, and `margin_cents_per_unit`
    defaulting to 0 as the distributor margin layered onto regulated products
    after the fuel surcharge."
    PRD §3.1: "A product starts `ACTIVE`"

    Design: Corner/entities/distributor_store_product_defaults_applied
    """
    d_resp = api.create_distributor(
        {"name": "Dairy Dist T", "license_number": "LIC-T-1"}, territory_manager_headers
    )
    distributor = validate_success(d_resp, 201)
    assert distributor["credit_terms_days"] == 7

    r_resp = api.create_route(
        {
            "distributor_id": distributor["id"],
            "route_code": "R-T",
            "name": "Route T",
            "service_weekdays": ["MON"],
        },
        territory_manager_headers,
    )
    route = validate_success(r_resp, 201)
    assert route["credit_price_basis"] == "ORIGINAL"
    assert route["status"] == "DRAFT"

    owner = make_distributor_owner_headers(distributor["id"])
    s_resp = api.create_store(
        {"route_id": route["id"], "store_code": "S-T", "name": "Store T"}, owner
    )
    store = validate_success(s_resp, 201)
    assert store["pull_window_days"] == 4
    assert store["crate_deposit_cents"] == 400
    assert store["credit_limit_cents"] == 0
    assert store["merchandising_rate_cents_per_min"] == 0
    assert store["free_merchandising_minutes"] == 15
    assert store["dock_open_min"] == 480
    assert store["dock_close_min"] == 720
    assert store["crate_balance"] == 0
    assert store["open_ar_cents"] == 0
    assert store["deposit_liability_cents"] == 0
    assert store["status"] == "ACTIVE"

    p_resp = api.create_product(
        {
            "sku": "DEF-1",
            "name": "Default Prod",
            "units_per_case": 4,
            "shelf_life_days": 30,
            "regulated": False,
        },
        territory_manager_headers,
    )
    product = validate_success(p_resp, 201)
    assert product["list_price_cents"] == 0
    assert product["weight_lbs_per_unit"] == pytest.approx(8.6)
    assert product["margin_cents_per_unit"] == 0
    assert product["status"] == "ACTIVE"


def test_missing_required_fields_rejected(api, territory_manager_headers):
    """PRD §2.5: "(5) request well-formedness — required fields present, enums
    in-domain, numeric ranges valid, uniqueness respected — producing
    `ERR_INVALID_REQUEST`"

    Design: Corner/entities/missing_required_fields_rejected
    """
    distributor = create_distributor(name="Dairy Dist U", license_number="LIC-U-1")
    route = create_route(distributor["id"], route_code="R-U")

    err1 = api.create_store(
        {"store_code": "S-U", "name": "Store U"},
        make_distributor_owner_headers(distributor["id"]),
    )
    validate_error(err1, ApiErrorId.ERR_INVALID_REQUEST)

    err2 = api.create_product(
        {"name": "No SKU", "units_per_case": 1, "shelf_life_days": 10, "regulated": False},
        territory_manager_headers,
    )
    validate_error(err2, ApiErrorId.ERR_INVALID_REQUEST)


def test_invalid_enum_and_range_rejected(api, territory_manager_headers):
    """PRD §2.5: "(5) request well-formedness — required fields present, enums
    in-domain, numeric ranges valid, uniqueness respected — producing
    `ERR_INVALID_REQUEST`"
    PRD §3.4: "the return must be strictly later than the departure, else
    `ERR_INVALID_REQUEST`"

    Design: Corner/entities/invalid_enum_and_range_rejected
    """
    distributor = create_distributor(name="Dairy Dist V", license_number="LIC-V-1")
    route = create_route(distributor["id"], route_code="R-V")
    period = create_pricing_period("2026-08")
    driver = create_driver(distributor["id"], name="Val Driver")
    owner = make_distributor_owner_headers(distributor["id"])

    err1 = api.create_driver(
        {"distributor_id": distributor["id"], "name": "Bad CDL", "cdl_class": "C"},
        owner,
    )
    validate_error(err1, ApiErrorId.ERR_INVALID_REQUEST)

    err2 = api.publish_announcement(
        period["id"],
        {
            "kind": "ESTIMATE",
            "class_i_base_cents_per_cwt": 2000,
            "processor_assessment_cents_per_cwt": 35,
            "hauling_cents_per_cwt": 60,
            "diesel_index_cents": 299,
            "expected_pricing_period_version": period["version"],
        },
        MA,
    )
    validate_error(err2, ApiErrorId.ERR_INVALID_REQUEST)

    err3 = api.create_trip(
        {
            "route_id": route["id"],
            "driver_id": driver["id"],
            "service_date": "2026-08-10",
            "truck_plate": "TK-1",
            "case_capacity": 10,
            "planned_depart_at": "2026-08-10T13:00:00Z",
            "planned_return_at": "2026-08-10T05:00:00Z",
        },
        owner,
    )
    validate_error(err3, ApiErrorId.ERR_INVALID_REQUEST)


def test_uniqueness_violations_rejected(api, territory_manager_headers):
    """PRD §3.1: "a unique `route_code` (duplicates are `ERR_INVALID_REQUEST`)"
    PRD §3.3: "A `MarketAdministrator` creates a `PricingPeriod` for a `month`
    in `YYYY-MM` form, unique across periods (a duplicate is
    `ERR_INVALID_REQUEST`)"

    Design: Corner/entities/uniqueness_violations_rejected
    """
    distributor = create_distributor(name="Dairy Dist X", license_number="LIC-X-1")
    create_route(distributor["id"], route_code="R-X")
    create_pricing_period("2026-08")

    err1 = api.create_route(
        {
            "distributor_id": distributor["id"],
            "route_code": "R-X",
            "name": "Route X Again",
            "service_weekdays": ["TUE"],
        },
        territory_manager_headers,
    )
    validate_error(err1, ApiErrorId.ERR_INVALID_REQUEST)

    err2 = api.create_pricing_period({"month": "2026-08"}, MA)
    validate_error(err2, ApiErrorId.ERR_INVALID_REQUEST)

    # license_number and sku uniqueness are likewise documented (PRD §3.1).
    err3 = api.create_distributor(
        {"name": "Dup Lic", "license_number": "LIC-X-1"}, territory_manager_headers
    )
    validate_error(err3, ApiErrorId.ERR_INVALID_REQUEST)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request whose headers are missing, or whose role value is
    not one of these names, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    resp = api.create_distributor({"name": "No Auth", "license_number": "LIC-NA"}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    bad_role = api.create_distributor(
        {"name": "Bad Role", "license_number": "LIC-NB"},
        {"X-User-ID": "x", "X-User-Role": "SuperUser"},
    )
    validate_error(bad_role, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_existence_trumps_state_on_confirm(api):
    """PRD §2.5: "the API applies a single global priority ladder, and a
    dual-failure request returns the error from the lowest priority number"
    with existence at "(4) existence of every path- and body-referenced
    resource" ahead of the state family at rung (6).

    Design: Corner/validations/existence_trumps_state_on_confirm
    """
    distributor = create_distributor(name="Dairy Dist CB", license_number="LIC-CB-1")
    resp = api.confirm_order(
        NON_EXISTENT_UUID, make_distributor_owner_headers(distributor["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_rbac_forbidden_matrix(api, territory_manager_headers):
    """PRD §2.1: "A request whose role is valid but not listed for the target
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/rbac_forbidden_matrix
    """
    refs = setup_delivered_order(prefix="FA", quantity_units=4)
    d_id = refs["distributor"]["id"]
    s1 = refs["store"]["id"]
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    o1 = refs["order"]["id"]
    pl = refs["product"]["id"]

    ret = create_return(o1, s1, t1, pl, 1, "DAMAGED", "2026-09-01", dr1)
    # Drive the trip to COMPLETED with a breach so qa-review is a live action.
    run_trip_readings(t1, dr1, [
        ("2026-08-10T10:00:00Z", 510, "BOX"),
        ("2026-08-10T10:01:00Z", 380, "BOX"),
    ])
    complete_trip_at(t1, dr1, "2026-08-10T12:00:00Z")

    # RouteDriver cannot create products.
    e1 = api.create_product(
        {"sku": "RB-2", "name": "Nope", "units_per_case": 1,
         "shelf_life_days": 5, "regulated": False},
        make_driver_headers(dr1),
    )
    validate_error(e1, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    # StoreReceiver cannot plan trips.
    e2 = api.create_trip(
        {
            "route_id": refs["route"]["id"], "driver_id": dr1,
            "service_date": "2026-08-11", "truck_plate": "TK-2",
            "case_capacity": 5,
            "planned_depart_at": "2026-08-11T05:00:00Z",
            "planned_return_at": "2026-08-11T13:00:00Z",
        },
        make_store_receiver_headers(s1),
    )
    validate_error(e2, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    # TerritoryManager cannot deliver.
    e3 = api.deliver_order(
        o1,
        {"delivered_lines": [
            {"product_id": pl, "delivered_units": 1, "scanned_code_date": "2026-09-01"}
        ]},
        territory_manager_headers,
    )
    validate_error(e3, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    # QualityInspector cannot approve returns (segregation of duties).
    e4 = api.approve_return(ret["id"], QI)
    validate_error(e4, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    # MarketAdministrator cannot suspend routes.
    e5 = api.suspend_route(refs["route"]["id"], MA)
    validate_error(e5, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    # DistributorOwner cannot qa-review (segregated from operations).
    e6 = api.qa_review_trip(t1, make_distributor_owner_headers(d_id))
    validate_error(e6, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
