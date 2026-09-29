"""List pages, filters and per-resource not-found codes."""
import pytest

from test_helpers import (
    validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    create_warehouse, create_account, create_battery_model, receive_lot, create_order,
)

ADMIN = TEST_USERS["admin_headers"]
REP = TEST_USERS["sales_rep_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]


def test_unknown_account_id_reports_the_account_not_found_code(api):
    """PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."
    PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."

    Design: Corner/entities/get_account_with_unknown_id_returns_account_not_found
    """
    resp = api.get_account("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


def test_unknown_order_line_id_reports_its_own_not_found_code(api):
    """PRD §2.10: "Nested paths are resolved left to right, and each segment
    must resolve before the next is examined."
    PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."

    Design: Corner/entities/get_order_line_with_unknown_id_returns_order_line_not_found
    """
    resp = api.get_order_line("1b2c3d4e-5f60-4718-9a2b-3c4d5e6f7081", REP)
    validate_error(resp, ApiErrorId.ERR_ORDER_LINE_NOT_FOUND.value)


def test_order_listing_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and
    `offset` echoing the values in effect, `total_count` giving the number of
    rows matching the filters before pagination, and `has_more` set true when
    rows remain beyond the current page."
    PRD §2.3: "Results on every list endpoint are ordered by `created_at`
    ascending, oldest row first, before the offset and limit are applied."

    Design: Corner/entities/list_orders_paginates_with_total_count_and_has_more
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
        create_order(account["id"], warehouse["id"], requested_ship_date=day)

    first, meta = validate_paginated(api.list_orders(
        REP, params={"account_id": account["id"], "limit": 2, "offset": 0}))
    assert meta["total_count"] == 3, f"Expected 3 matching rows, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(first) == 2, f"Expected a page of 2, got {len(first)}"

    second, meta2 = validate_paginated(api.list_orders(
        REP, params={"account_id": account["id"], "limit": 2, "offset": 2}))
    assert len(second) == 1
    assert meta2["has_more"] is False


def test_lot_listing_combines_the_site_and_posture_filters(api):
    """PRD §3.2: "Lots may be listed and filtered by `battery_model_id`, by
    `warehouse_id`, by `scrap_manifest_id` and by `condition_state`."
    PRD §2.3: "Filters named on individual list endpoints in Section 4 are
    combined conjunctively — a request naming both a foreign key and a status
    filter returns only rows matching both."

    Design: Corner/entities/list_inventory_lots_filters_by_warehouse_and_condition_state
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-31-FLD")
    fresh = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                        quantity_on_hand=20)
    expired = receive_lot(model["id"], warehouse["id"], manufactured_on="2024-01-01",
                          quantity_on_hand=4)

    rows, meta = validate_paginated(api.list_inventory_lots(OPERATOR, params={
        "warehouse_id": warehouse["id"], "condition_state": "SHELF_EXPIRED",
        "limit": 10, "offset": 0,
    }))
    assert meta["total_count"] == 1, f"Only the expired lot matches, got {meta['total_count']}"
    assert rows[0]["id"] == expired["id"]
    assert fresh["id"] not in [row["id"] for row in rows]


# --------------------------------------------------------------------------
# Per-collection not-found codes
# --------------------------------------------------------------------------


def test_unknown_battery_model_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_battery_model_id_returns_not_found
    """
    resp = api.get_battery_model("9c8b7a65-4321-4fed-8ba9-876543210fed", REP)
    validate_error(resp, ApiErrorId.ERR_BATTERY_MODEL_NOT_FOUND.value)


def test_unknown_carrier_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_carrier_id_returns_not_found
    """
    resp = api.get_carrier("9c8b7a65-4321-4fed-8ba9-876543210fed", OPERATOR)
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND.value)


def test_unknown_inventory_lot_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_inventory_lot_id_returns_not_found
    """
    resp = api.get_inventory_lot("9c8b7a65-4321-4fed-8ba9-876543210fed", OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVENTORY_LOT_NOT_FOUND.value)


def test_unknown_order_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_order_id_returns_not_found
    """
    resp = api.get_order("9c8b7a65-4321-4fed-8ba9-876543210fed", REP)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_unknown_shipment_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_shipment_id_returns_not_found
    """
    resp = api.get_shipment("9c8b7a65-4321-4fed-8ba9-876543210fed", OPERATOR)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value)


def test_unknown_core_return_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_core_return_id_returns_not_found
    """
    resp = api.get_core_return("9c8b7a65-4321-4fed-8ba9-876543210fed", REP)
    validate_error(resp, ApiErrorId.ERR_CORE_RETURN_NOT_FOUND.value)


def test_unknown_warranty_claim_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_warranty_claim_id_returns_not_found
    """
    resp = api.get_warranty_claim("9c8b7a65-4321-4fed-8ba9-876543210fed", REP)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND.value)


def test_unknown_service_contract_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_service_contract_id_returns_not_found
    """
    resp = api.get_service_contract("9c8b7a65-4321-4fed-8ba9-876543210fed", REP)
    validate_error(resp, ApiErrorId.ERR_SERVICE_CONTRACT_NOT_FOUND.value)


def test_unknown_storm_event_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_storm_event_id_returns_not_found
    """
    resp = api.get_storm_event("9c8b7a65-4321-4fed-8ba9-876543210fed", COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_STORM_EVENT_NOT_FOUND.value)


def test_unknown_disposal_manifest_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."
    PRD §2.6: "Every id embedded in the request path resolving to a stored
    row, checked left to right, otherwise the corresponding not-found code."

    Design: Corner/errors/unknown_disposal_manifest_id_returns_not_found
    """
    resp = api.get_disposal_manifest("9c8b7a65-4321-4fed-8ba9-876543210fed", COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_DISPOSAL_MANIFEST_NOT_FOUND.value)


COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_shipments_can_be_filtered_by_carrier(api):
    """PRD §3.5: "Shipments may be listed and filtered by `order_id`, by
    `carrier_id` and by `status`, whose full enumeration is `PACKED`,
    `CERTIFIED`, `HAZMAT_REJECTED`, `DISPATCHED`, `DELIVERED` and `VOIDED`."
    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset`
    echoing the values in effect, `total_count` giving the number of rows
    matching the filters before pagination, and `has_more` set true when rows
    remain beyond the current page."

    Design: Corner/endpoints/shipments_filtered_by_carrier_id_returns_an_array
    """
    from test_helpers import setup_packed_shipment
    env = setup_packed_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )

    rows, meta = validate_paginated(api.list_shipments(
        OPERATOR, params={"carrier_id": env["carrier"]["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"Expected the one tender, got {meta['total_count']}"
    assert rows[0]["id"] == env["shipment"]["id"]
    assert rows[0]["carrier_id"] == env["carrier"]["id"]
    assert rows[0]["status"] == "PACKED"


def test_service_contracts_can_be_filtered_by_the_sized_model(api):
    """PRD §3.8: "Contracts may be listed and filtered by `account_id`, by
    `order_id`, by `sized_battery_model_id` and by `status`, whose full
    enumeration is `DRAFT`, `SIZED`, `ATTACHED`, `ACTIVE`, `SUPERSEDED` and
    `CANCELLED`."
    PRD §3.8: "The winner's figures are written onto the contract as
    `sized_battery_model_id`, `required_peukert_ah`, `sized_string_count`,
    `sized_units_per_string` and `sized_unit_count`, along with the
    `dc_load_amps` and `temp_derate_factor` computed earlier, and the
    `covered_value_cents` equal to the sized unit count multiplied by the
    winner's list price."

    Design: Corner/endpoints/service_contracts_filtered_by_sized_battery_model_id_returns_an_array
    """
    from test_helpers import create_service_contract, size_service_contract
    account = create_account(name="Metro Data Halls", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=3)
    agm = create_battery_model("IB-AGM-95")
    create_battery_model("IB-LFP-100")
    contract = create_service_contract(account["id"], coverage_tier="GOLD")
    sized = size_service_contract(contract["id"])
    assert sized["sized_battery_model_id"] == agm["id"]

    rows, meta = validate_paginated(api.list_service_contracts(
        REP, params={"sized_battery_model_id": agm["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == contract["id"]
    assert rows[0]["status"] == "SIZED"
