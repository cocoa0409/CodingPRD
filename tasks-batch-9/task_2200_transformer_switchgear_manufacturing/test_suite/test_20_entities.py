"""Entity creation, defaults, common fields and foreign-key echo."""

from test_helpers import (
    CONTRACT_ADMIN,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    assert_component_buckets,
    assert_index_point_common_fields,
    assert_order_state,
    assert_pagination_defaults,
    assert_versioned_common_fields,
    commodity_index_point_payload,
    component_allocation_payload,
    create_order,
    create_supplier,
    engineered_order_payload,
    long_lead_component_payload,
    set_clock,
    supplier_payload,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def test_a_new_order_lands_on_both_initial_dimensions_with_an_open_posture(api):
    """PRD 3.1: "On creation the server sets `engineering_status` to `ENG_OPEN`,
    `fulfillment_status` to `PLANNING`, `production_posture` to `OPEN` with an
    empty `posture_reason_codes`, and `net_contract_value_cents` equal to
    `contract_value_cents`."

    Design: Corner/entities/create_engineered_order_returns_initial_states_and_open_posture
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    response = api.create_engineered_order(
        engineered_order_payload(
            order_number="ORD-CORNER-001",
            customer_name="Riverbend Utility",
            product_family="MV_SWITCHGEAR",
            rated_kv=15,
            contract_value_cents=4000000,
            sold_at="2026-01-05T00:00:00Z",
            promised_ship_at="2026-10-01T00:00:00Z",
        ),
        CONTRACT_ADMIN,
    )
    order = validate_success(response, 201)
    assert_order_state(
        order,
        engineering_status="ENG_OPEN",
        fulfillment_status="PLANNING",
        production_posture="OPEN",
        posture_reason_codes=[],
    )
    assert order["order_number"] == "ORD-CORNER-001"
    assert order["rated_kv"] == 15
    assert order["net_contract_value_cents"] == 4000000
    assert order["version"] == 1
    assert_versioned_common_fields(order)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_an_unknown_order_id_is_a_not_found_and_not_an_empty_success(api):
    """PRD 2.5: "An unresolvable engineered order yields `ERR_ORDER_NOT_FOUND`...
    All twenty are HTTP 404."

    Design: Corner/entities/get_engineered_order_unknown_id_returns_order_not_found
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    response = api.get_engineered_order(NON_EXISTENT_UUID, PLANT_ADMIN)
    validate_error(response, ApiErrorId.ORDER_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert "engineering_status" not in body["data"]


def test_listing_an_empty_collection_returns_a_well_formed_empty_page(api):
    """PRD 2.3: "`limit` controls page size; it defaults to 10 when omitted...
    `offset` controls how many rows are skipped... it defaults to 0"; list
    responses "carry `response_type` of `"array"` and populate all four
    pagination fields in `meta`".

    Design: Corner/entities/list_engineered_orders_on_empty_database_returns_empty_page
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    response = api.list_engineered_orders(PLANT_ADMIN)
    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "array"
    assert body["data"] == []
    assert_pagination_defaults(body["meta"], 0)


def test_a_supplier_without_a_legal_name_is_refused_and_persists_nothing(api):
    """PRD 2.11: "Every required body field must be present and non-null, or the
    response is `ERR_MISSING_REQUIRED_FIELD` (HTTP 422)"; PRD 3.4 registers a
    supplier "with a `supplier_code` unique across all suppliers, a `legal_name`,
    and a sourcing `region`".

    Design: Corner/entities/create_supplier_missing_legal_name_returns_missing_required_field
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    validate_error(
        api.create_supplier(
            {"supplier_code": "SUP-NOLEGAL", "region": "NA"}, PLANT_ADMIN
        ),
        ApiErrorId.MISSING_REQUIRED_FIELD,
        422,
    )
    body = api.list_suppliers(PLANT_ADMIN).json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0


def test_an_omitted_allocation_policy_defaults_to_preemptible(api):
    """PRD 3.4: a component is registered with "an opening `quantity_on_hand`, and
    an optional `allocation_policy` which defaults to `PREEMPTIBLE` and may
    instead be `PROTECTED`. The component is born `ACTIVE`."

    Design: Corner/entities/create_long_lead_component_omitting_allocation_policy_defaults_to_preemptible
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    supplier = create_supplier(
        api,
        supplier_code="SUP-DEF-01",
        legal_name="Copperline Windings AG",
        region="EU",
    )
    component = validate_success(
        api.create_long_lead_component(
            supplier["id"],
            {
                "part_number": "PN-BUSH-15",
                "category": "HV_BUSHING",
                "lead_time_days": 120,
                "quantity_on_hand": 10,
            },
            MATERIALS_PLANNER,
        ),
        201,
    )
    assert component["allocation_policy"] == "PREEMPTIBLE"
    assert component["status"] == "ACTIVE"
    assert_component_buckets(
        component,
        quantity_on_hand=10,
        quantity_reserved=0,
        quantity_committed=0,
        quantity_consumed=0,
        quantity_available=10,
    )


def test_a_component_under_an_unknown_supplier_resolves_the_parent_first(api):
    """PRD 2.5: "a supplier, `ERR_SUPPLIER_NOT_FOUND`"; PRD 2.11: "existence
    resolution (7–26), payload shape and enum domains (27–31)".

    Design: Corner/entities/create_long_lead_component_under_unknown_supplier_returns_supplier_not_found
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    validate_error(
        api.create_long_lead_component(
            NON_EXISTENT_UUID,
            long_lead_component_payload(
                part_number="PN-ORPHAN",
                category="TAP_CHANGER",
                lead_time_days=90,
                quantity_on_hand=4,
                allocation_policy="PROTECTED",
            ),
            MATERIALS_PLANNER,
        ),
        ApiErrorId.SUPPLIER_NOT_FOUND,
        404,
    )
    body = api.list_long_lead_components(MATERIALS_PLANNER).json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0


def test_a_commodity_index_point_carries_no_version_because_it_is_immutable(api):
    """PRD 2.4: "Nineteen of the twenty resource types are version-tracked" and
    the index point is the exception, carrying only `id` and `created_at`.

    Design: Corner/entities/commodity_index_point_is_immutable_entity_without_version_field
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    point = validate_success(
        api.create_commodity_index_point(
            commodity_index_point_payload(
                commodity="COPPER",
                index_month="2026-01",
                index_value=41250,
                published_at="2026-02-10T00:00:00Z",
                is_provisional=False,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    assert point["commodity"] == "COPPER"
    assert point["index_month"] == "2026-01"
    assert point["is_provisional"] is False
    assert_index_point_common_fields(point)


def test_a_rated_voltage_of_zero_is_a_range_violation_not_a_type_violation(api):
    """PRD 2.11: "Numeric inputs must respect their declared ranges — an
    allocation quantity of at least 1, a rated voltage above zero... or the
    response is `ERR_FIELD_VALUE_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/entities/create_engineered_order_rated_kv_zero_returns_field_value_out_of_range
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    validate_error(
        api.create_engineered_order(
            engineered_order_payload(
                order_number="ORD-CORNER-KV0",
                customer_name="Riverbend Utility",
                product_family="MV_SWITCHGEAR",
                rated_kv=0,
                contract_value_cents=4000000,
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.FIELD_VALUE_OUT_OF_RANGE,
        422,
    )
    assert api.list_engineered_orders(PLANT_ADMIN).json()["meta"]["total_count"] == 0


def test_a_client_supplied_engineering_status_is_never_persisted(api):
    """PRD 3.1: "On creation the server sets `engineering_status` to `ENG_OPEN`",
    and PRD 2.11 polices the payload with `ERR_FIELD_TYPE_INVALID` for inputs
    outside the declared create schema.

    Design: Corner/entities/create_engineered_order_extra_field_input_ignored
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    response = api.create_engineered_order(
        engineered_order_payload(
            order_number="ORD-CORNER-SYS",
            customer_name="Riverbend Utility",
            product_family="POWER_TRANSFORMER",
            rated_kv=69,
            contract_value_cents=4000000,
            engineering_status="DESIGN_RELEASED",
            released_drawing_revision=7,
        ),
        CONTRACT_ADMIN,
    )
    assert response.status_code in (201, 422), response.status_code
    if response.status_code == 201:
        created = response.json()["data"]
        assert created["engineering_status"] == "ENG_OPEN"
    else:
        validate_error(response, ApiErrorId.FIELD_TYPE_INVALID, 422)

    # Whichever arm the server takes, no order may carry a released design.
    rows = api.list_engineered_orders(PLANT_ADMIN, {"limit": 100}).json()["data"]
    for row in rows:
        assert row["engineering_status"] == "ENG_OPEN"


def test_an_allocation_echoes_both_of_its_cross_aggregate_foreign_keys(api):
    """PRD 3.4: reserving units carries "the `long_lead_component_id`, the
    `engineered_order_id`, the `quantity`... The allocation is born `RESERVED`
    with `release_penalty_cents` of 0."

    Design: Corner/entities/get_component_allocation_resolves_both_component_and_order_foreign_keys
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    order = create_order(
        api,
        order_number="ORD-CORNER-FK1",
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )
    supplier = validate_success(
        api.create_supplier(
            supplier_payload(
                supplier_code="SUP-FK-01",
                legal_name="Copperline Windings AG",
                region="NA",
            ),
            PLANT_ADMIN,
        ),
        201,
    )
    component = validate_success(
        api.create_long_lead_component(
            supplier["id"],
            long_lead_component_payload(
                part_number="PN-FK-01",
                category="HV_BUSHING",
                lead_time_days=120,
                quantity_on_hand=10,
                allocation_policy="PROTECTED",
            ),
            MATERIALS_PLANNER,
        ),
        201,
    )
    created = validate_success(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                component["version"],
                quantity=4,
                priority_class=2,
                need_by_date="2026-09-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        201,
    )

    allocation = validate_success(
        api.get_component_allocation(created["id"], MATERIALS_PLANNER)
    )
    assert allocation["long_lead_component_id"] == component["id"]
    assert allocation["engineered_order_id"] == order["id"]
    assert allocation["status"] == "RESERVED"
    assert allocation["quantity"] == 4
    assert allocation["priority_class"] == 2

    body = api.list_component_allocations(
        MATERIALS_PLANNER, {"engineered_order_id": order["id"]}
    ).json()
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["id"] == created["id"]
