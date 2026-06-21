"""Entity creation, defaults, computed fields, uniqueness, type/relationship
constraints, pagination, and FK-filtered computed reads.

Covers the entities and endpoints corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_dealership_customer_unit,
    setup_started_service_order,
    create_deal_on_unit,
    create_customer,
    create_unit,
    create_part_item,
    create_recall_campaign,
    reserve_part,
    create_dealership,
    create_pdi_inspection_payload,
    appraise_trade_payload,
)

SALES = TEST_USERS["sales_agent_headers"]
MGR = TEST_USERS["dealer_manager_headers"]
SVC = TEST_USERS["service_advisor_headers"]


# ===========================================================================
# Corner: entities / create_dealership_returns_201_with_system_fields
# ===========================================================================
def test_create_dealership_returns_201_with_system_fields(api):
    """PRD §2.4: "The `version` field is an integer that begins at its initial
    value on creation".
    PRD §2.4: "Each Dealership owns a `current_utc` field — its own deterministic
    clock — which is initialized to the Unix epoch, `1970-01-01T00:00:00.000Z`,
    when the dealership is created."

    Design: Corner/entities/create_dealership_returns_201_with_system_fields
    """
    created = validate_success(
        api.create_dealership(
            {"name": "Acme RV", "state_code": "TX", "doc_fee_cents": 15000, "sales_tax_rate_bps": 625},
            MGR,
        ),
        expected_status=201,
    )
    assert created["version"] == 1, created["version"]
    assert created["current_utc"] == "1970-01-01T00:00:00.000Z", created["current_utc"]


# ===========================================================================
# Corner: entities / get_unit_nonexistent_returns_not_found
# ===========================================================================
def test_get_nonexistent_unit_returns_not_found(api):
    """PRD §2.5: "The first reference that cannot be resolved produces the
    corresponding not-found error — ... `ERR_UNIT_NOT_FOUND` ... each returned with
    HTTP 404".

    Design: Corner/entities/get_unit_nonexistent_returns_not_found
    """
    create_dealership(name="NF RV")
    resp = api.get_unit(NON_EXISTENT_UUID, SALES)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / create_customer_missing_email_returns_invalid_request
# ===========================================================================
def test_create_customer_missing_email_rejected(api):
    """PRD §3.1: "Customers are created against a dealership with a `full_name`, an
    `email` unique within that dealership, and an optional `credit_tier`."
    PRD §2.6: "come the field-level input validations: missing or wrong-typed
    fields ... These surface as `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_customer_missing_email_returns_invalid_request
    """
    dealer = create_dealership(name="Req RV")
    resp = api.create_customer(
        {"dealership_id": dealer["id"], "full_name": "No Email"}, SALES
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / customer_credit_tier_default_standard
# ===========================================================================
def test_customer_credit_tier_defaults_to_standard(api):
    """PRD §3.1: "The credit tier is one of `PRIME`, `STANDARD`, or `SUBPRIME` and
    defaults to `STANDARD` when omitted".

    Design: Corner/entities/customer_credit_tier_default_standard
    """
    dealer = create_dealership(name="Def RV")
    created = validate_success(
        api.create_customer(
            {"dealership_id": dealer["id"], "full_name": "Defaulter", "email": "def@x.com"}, SALES
        ),
        expected_status=201,
    )
    assert created["credit_tier"] == "STANDARD", created["credit_tier"]


# ===========================================================================
# Corner: entities / part_qty_available_computed_from_reservations
# ===========================================================================
def test_part_qty_available_computed_from_reservations(api):
    """PRD §2.8: "a PartItem's `qty_reserved` is the sum of quantities across that
    part's reservations still in `RESERVED` state, and its `qty_available` is its
    on-hand count minus that reserved figure and is never negative".

    Reserve 3 of 10 -> qty_reserved 3, qty_available 7.

    Design: Corner/entities/part_qty_available_computed_from_reservations
    """
    dealer, customer, unit, so = setup_started_service_order()
    part = create_part_item(dealer["id"], unit_price_cents=4000, qty_on_hand=10)
    reserve_part(so["id"], part["id"], 3)
    part_after = validate_success(api.get_part_item(part["id"], SVC))
    assert part_after["qty_reserved"] == 3, part_after["qty_reserved"]
    assert part_after["qty_available"] == 7, part_after["qty_available"]


# ===========================================================================
# Corner: entities / unit_invalid_class_type_enum_rejected
# ===========================================================================
def test_unit_invalid_class_type_rejected(api):
    """PRD §3.1: "a `class_type` drawn from `CLASS_A`, `CLASS_B`, `CLASS_C`,
    `TRAVEL_TRAILER`, or `FIFTH_WHEEL`".
    PRD §2.6: "the field-level input validations: missing or wrong-typed fields,
    negative amounts, invalid enums ... These surface as `ERR_INVALID_REQUEST`".

    Design: Corner/entities/unit_invalid_class_type_enum_rejected
    """
    dealer = create_dealership(name="Enum RV")
    resp = api.create_unit(
        {
            "dealership_id": dealer["id"], "vin": "VIN-EN-1", "model_year": 2024,
            "class_type": "SPACESHIP", "acquisition": "STOCK", "list_price_cents": 5000000,
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / consignment_unit_requires_consignor
# ===========================================================================
def test_consignment_unit_without_consignor_rejected(api):
    """PRD §3.1: "when `acquisition` is `CONSIGNMENT`, the request must supply the
    `consignor_customer_id` identifying the consignor, the `consignment_floor_cents`
    naming the minimum net the consignor must receive, and the `consignment_fee_bps`
    setting the dealer's commission as basis points of sale price; omitting any of
    these for a consignment unit is rejected with `ERR_CONSIGNOR_REQUIRED`."

    Design: Corner/entities/consignment_unit_requires_consignor
    """
    dealer = create_dealership(name="ConsC RV")
    resp = api.create_unit(
        {
            "dealership_id": dealer["id"], "vin": "VIN-CS-1", "model_year": 2024,
            "class_type": "CLASS_A", "acquisition": "CONSIGNMENT", "list_price_cents": 9000000,
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_CONSIGNOR_REQUIRED.value)


# ===========================================================================
# Corner: entities / stock_unit_with_consignor_rejected
# ===========================================================================
def test_stock_unit_with_consignor_rejected(api):
    """PRD §3.1: "Conversely, supplying a `consignor_customer_id` on a unit that is
    not a consignment is rejected with `ERR_CONSIGNOR_NOT_ALLOWED`."

    Design: Corner/entities/stock_unit_with_consignor_rejected
    """
    dealer = create_dealership(name="Stk RV")
    customer = create_customer(dealer["id"])
    resp = api.create_unit(
        {
            "dealership_id": dealer["id"], "vin": "VIN-SK-1", "model_year": 2024,
            "class_type": "CLASS_C", "acquisition": "STOCK",
            "consignor_customer_id": customer["id"], "list_price_cents": 5000000,
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_CONSIGNOR_NOT_ALLOWED.value)


# ===========================================================================
# Corner: entities / duplicate_vin_rejected
# ===========================================================================
def test_duplicate_vin_in_dealership_rejected(api):
    """PRD §2.5: "A Unit's `vin` must be unique within its dealership; a duplicate
    is rejected with `ERR_DUPLICATE_VIN`."

    Design: Corner/entities/duplicate_vin_rejected
    """
    dealer = create_dealership(name="Dup RV")
    get_success_data(
        api_client.create_unit(
            {"dealership_id": dealer["id"], "vin": "VIN-DUP", "model_year": 2024,
             "class_type": "CLASS_C", "acquisition": "STOCK", "list_price_cents": 5000000},
            SALES,
        )
    )
    resp = api.create_unit(
        {"dealership_id": dealer["id"], "vin": "VIN-DUP", "model_year": 2023,
         "class_type": "CLASS_B", "acquisition": "STOCK", "list_price_cents": 4000000},
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN.value)


# ===========================================================================
# Corner: entities / list_units_pagination_shape
# ===========================================================================
def test_list_units_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return".
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Two units, limit 1 -> total_count 2, has_more true, one item returned.

    Design: Corner/entities/list_units_pagination_shape
    """
    dealer = create_dealership(name="Pag RV")
    get_success_data(
        api_client.create_unit(
            {"dealership_id": dealer["id"], "vin": "VIN-P1", "model_year": 2024,
             "class_type": "CLASS_C", "acquisition": "STOCK", "list_price_cents": 5000000}, SALES
        )
    )
    get_success_data(
        api_client.create_unit(
            {"dealership_id": dealer["id"], "vin": "VIN-P2", "model_year": 2024,
             "class_type": "CLASS_B", "acquisition": "STOCK", "list_price_cents": 4000000}, SALES
        )
    )
    resp = api.list_units(SALES, params={"dealership_id": dealer["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


# ===========================================================================
# Corner: endpoints / list_units_filtered_by_consignor
# ===========================================================================
def test_list_units_filtered_by_consignor(api):
    """PRD §4 endpoint table: "GET `/units` List/filter units".
    PRD §3.1: "when `acquisition` is `CONSIGNMENT`, the request must supply the
    `consignor_customer_id` identifying the consignor".

    Filtering by consignor returns only the matching consignment unit.

    Design: Corner/endpoints/list_units_filtered_by_consignor
    """
    dealer = create_dealership(name="Filt RV")
    consignor = create_customer(dealer["id"])
    cunit = get_success_data(
        api_client.create_unit(
            {"dealership_id": dealer["id"], "vin": "VIN-FC-1", "model_year": 2024,
             "class_type": "CLASS_A", "acquisition": "CONSIGNMENT",
             "consignor_customer_id": consignor["id"], "list_price_cents": 9000000,
             "consignment_floor_cents": 8000000, "consignment_fee_bps": 800}, SALES
        )
    )
    get_success_data(
        api_client.create_unit(
            {"dealership_id": dealer["id"], "vin": "VIN-FC-2", "model_year": 2024,
             "class_type": "CLASS_C", "acquisition": "STOCK", "list_price_cents": 5000000}, SALES
        )
    )
    data, meta = validate_paginated(
        api.list_units(SALES, params={"consignor_customer_id": consignor["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert data[0]["id"] == cunit["id"], data


# ===========================================================================
# Corner: endpoints / list_remedies_filtered_by_unit
# ===========================================================================
def test_list_recall_remedies_filtered_by_unit(api):
    """PRD §3.11: "As a side effect of opening, the system creates a `PENDING`
    **RecallRemedy** for each existing unit whose class and model year match the
    campaign's target, recording the remedy's `recall_campaign_id` and `unit_id`".

    Filtering remedies by unit returns the auto-created PENDING remedy for that unit.

    Design: Corner/endpoints/list_remedies_filtered_by_unit
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"class_type": "CLASS_A", "list_price_cents": 9000000}
    )
    create_recall_campaign(
        dealer["id"], target_class_type="CLASS_A", target_model_year=2024, severity="ADVISORY"
    )
    data, meta = validate_paginated(
        api.list_recall_remedies(SVC, params={"unit_id": unit["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert data[0]["unit_id"] == unit["id"], data
    assert data[0]["status"] == "PENDING", data[0]["status"]


# ===========================================================================
# Corner: endpoints / list_part_reservations_for_service_order
# ===========================================================================
def test_list_part_reservations_for_service_order(api):
    """PRD §4 endpoint table: "GET `/part-reservations` List/filter part
    reservations".
    PRD §3.7: "A successful reservation opens in `RESERVED` status".

    Filtering by service_order_id returns that order's reservation in RESERVED.

    Design: Corner/endpoints/list_part_reservations_for_service_order
    """
    dealer, customer, unit, so = setup_started_service_order()
    part = create_part_item(dealer["id"], unit_price_cents=2000, qty_on_hand=10)
    resv = reserve_part(so["id"], part["id"], 2)
    data, meta = validate_paginated(
        api.list_part_reservations(SVC, params={"service_order_id": so["id"]})
    )
    assert any(r["id"] == resv["id"] for r in data), data
    match = next(r for r in data if r["id"] == resv["id"])
    assert match["status"] == "RESERVED", match["status"]
    assert match["quantity"] == 2, match["quantity"]


# ===========================================================================
# Corner: endpoints / list_pdi_inspections_for_deal
# ===========================================================================
def test_list_pdi_inspections_for_deal(api):
    """PRD §3.5: "The inspection's `result` is computed: it is `PASS` only when
    `defects_found` equals zero and the deal's unit has an `open_recall_count` of
    zero at the moment of inspection, and `FAIL` otherwise."

    A FAIL inspection is listed for its deal when filtering by deal_id.

    Design: Corner/endpoints/list_pdi_inspections_for_deal
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 7000000}
    )
    deal = create_deal_on_unit(dealer, customer, unit, 7000000)
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    get_success_data(api_client.start_pdi(deal["id"], SALES))
    insp = get_success_data(
        api_client.create_pdi_inspection(
            create_pdi_inspection_payload(dealer["id"], deal["id"], 1), SVC
        )
    )
    data, meta = validate_paginated(
        api.list_pdi_inspections(SALES, params={"deal_id": deal["id"]})
    )
    assert any(i["id"] == insp["id"] for i in data), data
    match = next(i for i in data if i["id"] == insp["id"])
    assert match["result"] == "FAIL", match["result"]


# ===========================================================================
# Corner: endpoints / list_trade_units_by_origin
# ===========================================================================
def test_list_trade_units_by_origin(api):
    """PRD §3.3: "The system creates the trade unit with `acquisition` of
    `TRADE_IN`, `status` of `AVAILABLE`, and a `trade_in_origin_unit_id` pointing
    back at the unit being sold on this deal".

    Filtering by trade_in_origin_unit_id returns the appraised TRADE_IN unit.

    Design: Corner/endpoints/list_trade_units_by_origin
    """
    dealer, customer, unit_x = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 8000000}
    )
    deal = create_deal_on_unit(dealer, customer, unit_x, 8000000)
    trade = get_success_data(
        api_client.appraise_trade(
            deal["id"],
            appraise_trade_payload(
                model_year=2016, class_type="TRAVEL_TRAILER", list_price_cents=1500000,
                trade_allowance_cents=1200000, trade_payoff_cents=0, trade_recon_cost_cents=100000,
            ),
            SALES,
        )
    )
    data, meta = validate_paginated(
        api.list_units(SALES, params={"trade_in_origin_unit_id": unit_x["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert data[0]["id"] == trade["id"], data
