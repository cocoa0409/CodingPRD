"""Authentication, role authorisation, referential 404s and uniqueness codes."""

from test_helpers import (
    ApiErrorId,
    add_contract_line,
    create_contract,
    create_contract_line_payload,
    create_contract_payload,
    create_delivery_route_payload,
    create_item,
    create_item_payload,
    create_order_line_payload,
    create_route,
    create_supply_room,
    headers_without_auth,
    make_clinician_headers,
    make_materials_manager_headers,
    read_order,
    setup_draft_order,
    validate_error,
    validate_paginated,
    validate_success,
    CLINICIAN_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
OPERATOR = TEST_USERS["distribution_operator_headers"]


def test_request_without_the_two_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API — reads included — must carry two
    headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`,
    naming the role it acts in. If either header is absent, or if `X-User-Role`
    carries a string outside the five roles defined below, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other aspect of
    the request is inspected."
    PRD §2.9: "**Authentication.** Both headers present, `X-User-Role` one of the
    five declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies
    everywhere."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    response = api.create_supply_room({"facility_code": "FAC-400"},
                                      headers_without_auth())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.ERR_VALIDATION.value
    ), "authentication is inspected before the request schema"


def test_pagination_limit_above_one_hundred_is_a_schema_violation(api):
    """PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of
    100; `offset` defaults to 0 and has a minimum of 0. A `limit` below 1 or
    above 100, or an `offset` below 0, is a schema violation and is rejected
    with `ERR_VALIDATION` (HTTP 400) — the values are not silently clamped."

    Design: Corner/validations/pagination_limit_above_maximum_returns_validation_error
    """
    item = create_item(
        sku="SKU-PG-CS", description="Pagination probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=1000, handling_class="AMBIENT", units_per_parent=10,
    )

    rejected = api.list_items(ADMIN, params={"limit": 101, "offset": 0})
    validate_error(rejected, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(
        api.list_items(ADMIN, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == item["id"]


def test_unresolvable_body_reference_is_a_not_found_on_the_referenced_entity(api):
    """PRD §2.5: "Any of `item_id`, `lot_id`, `lum_parent_item_id`,
    `supersedes_contract_id`, `supply_room_id`, `order_id`, `contract_id` or
    `proposed_item_id` that does not resolve to an existing row is a 404,
    reported under the not-found code of the entity it should have named —
    `ERR_ITEM_NOT_FOUND` for `item_id`, `lum_parent_item_id` and
    `proposed_item_id`; `ERR_LOT_NOT_FOUND` for `lot_id`;
    `ERR_CONTRACT_NOT_FOUND` for `contract_id` and `supersedes_contract_id`;
    `ERR_SUPPLY_ROOM_NOT_FOUND` for `supply_room_id`; and
    `ERR_ORDER_NOT_FOUND` for `order_id`."

    Design: Corner/validations/contract_line_body_fk_item_not_found_returns_404
    """
    contract = create_contract(manufacturer_code="MFR-ACME", contract_code="CTR-FK")

    response = api.create_contract_line(
        contract["id"],
        create_contract_line_payload(
            "00000000-0000-4000-8000-0000000000ff",
            tier_price_cents=1000,
            floor_price_cents=900,
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 404)

    _rows, meta = validate_paginated(
        api.list_contract_lines(
            ADMIN, params={"contract_id": contract["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, "the refused line must not be written"


def test_every_collection_reports_its_own_not_found_code(api):
    """PRD §2.5: "Each path variable has its own dedicated 404: `supply_room_id`
    yields `ERR_SUPPLY_ROOM_NOT_FOUND`, `item_id` yields `ERR_ITEM_NOT_FOUND`,
    `contract_id` yields `ERR_CONTRACT_NOT_FOUND`, `contract_line_id` yields
    `ERR_CONTRACT_LINE_NOT_FOUND`, `formulary_item_id` yields
    `ERR_FORMULARY_ITEM_NOT_FOUND`, `lot_id` yields `ERR_LOT_NOT_FOUND`,
    `order_id` yields `ERR_ORDER_NOT_FOUND`, `order_line_id` yields
    `ERR_ORDER_LINE_NOT_FOUND`, `substitution_request_id` yields
    `ERR_SUBSTITUTION_REQUEST_NOT_FOUND`, `recall_notice_id` yields
    `ERR_RECALL_NOTICE_NOT_FOUND`, `route_id` yields `ERR_ROUTE_NOT_FOUND` and
    `chargeback_claim_id` yields `ERR_CHARGEBACK_CLAIM_NOT_FOUND`. All of them
    are HTTP 404."

    Design: Corner/errors/unknown_path_ids_map_to_their_own_not_found_error_ids
    """
    probes = [
        (api.get_supply_room, "00000000-0000-4000-8000-000000000001",
         ApiErrorId.ERR_SUPPLY_ROOM_NOT_FOUND),
        (api.get_contract, "00000000-0000-4000-8000-000000000002",
         ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_contract_line, "00000000-0000-4000-8000-000000000003",
         ApiErrorId.ERR_CONTRACT_LINE_NOT_FOUND),
        (api.get_order, "00000000-0000-4000-8000-000000000004",
         ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_lot, "00000000-0000-4000-8000-000000000005",
         ApiErrorId.ERR_LOT_NOT_FOUND),
        (api.get_formulary_item, "00000000-0000-4000-8000-000000000006",
         ApiErrorId.ERR_FORMULARY_ITEM_NOT_FOUND),
        (api.get_order_line, "00000000-0000-4000-8000-000000000007",
         ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
        (api.get_substitution_request, "00000000-0000-4000-8000-000000000008",
         ApiErrorId.ERR_SUBSTITUTION_REQUEST_NOT_FOUND),
        (api.get_recall_notice, "00000000-0000-4000-8000-000000000009",
         ApiErrorId.ERR_RECALL_NOTICE_NOT_FOUND),
        (api.get_delivery_route, "00000000-0000-4000-8000-00000000000a",
         ApiErrorId.ERR_ROUTE_NOT_FOUND),
        (api.get_chargeback_claim, "00000000-0000-4000-8000-00000000000b",
         ApiErrorId.ERR_CHARGEBACK_CLAIM_NOT_FOUND),
    ]

    for read_method, unknown_id, expected in probes:
        response = read_method(unknown_id, ADMIN)
        validate_error(response, expected.value, 404)
        assert response.json()["response_type"] == "error"


def test_each_uniqueness_constraint_raises_its_own_conflict_code(api):
    """PRD §3.1: "Each record carries a distributor `sku` that is globally unique
    (a repeat is `ERR_DUPLICATE_SKU`), a human-readable `description`, and the
    `manufacturer_code` that will later be matched against contracts and
    chargeback counterparties."
    PRD §3.2: "It names the `manufacturer_code` it is written against, a globally
    unique `contract_code` (a repeat is `ERR_DUPLICATE_CONTRACT_CODE`), the
    committed-volume `tier` — `TIER_1`, `TIER_2` or `TIER_3` — and a
    `member_class_scope` of `ACUTE`, `NON_ACUTE` or `SURGERY_CENTER`."
    PRD §3.2: "A contract may price a given item only once — a second line for
    the same item on the same contract is `ERR_DUPLICATE_CONTRACT_LINE`."
    PRD §3.7: "A `DistributionOperator` plans one by naming a globally unique
    `route_code` — a repeat is `ERR_DUPLICATE_ROUTE_CODE` — a `service_date` in
    `YYYY-MM-DD` form, and a `vehicle_class` of either `AMBIENT_VAN` or
    `REEFER_VAN`."

    Design: Corner/errors/duplicate_sku_contract_code_contract_line_and_route_code_each_rejected
    """
    item = create_item(
        sku="SKU-UNQ-CS", description="Uniqueness probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=4000, handling_class="AMBIENT", units_per_parent=10,
    )
    contract = create_contract(manufacturer_code="MFR-ACME", contract_code="CTR-UNQ")
    add_contract_line(
        contract["id"], item["id"], tier_price_cents=2000, floor_price_cents=1000
    )
    create_route(
        route_code="RT-UNQ", service_date="2026-08-05", vehicle_class="AMBIENT_VAN"
    )

    duplicate_sku = api.create_item(
        create_item_payload(
            sku="SKU-UNQ-CS", description="Duplicate sku",
            manufacturer_code="MFR-OMNI", uom="EA", wac_cents=100,
            handling_class="AMBIENT",
        ),
        ADMIN,
    )
    validate_error(duplicate_sku, ApiErrorId.ERR_DUPLICATE_SKU.value, 409)

    duplicate_contract = api.create_contract(
        create_contract_payload(
            manufacturer_code="MFR-OMNI", contract_code="CTR-UNQ", tier="TIER_2",
            member_class_scope="NON_ACUTE",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T23:59:59Z",
        ),
        ADMIN,
    )
    validate_error(duplicate_contract, ApiErrorId.ERR_DUPLICATE_CONTRACT_CODE.value, 409)

    duplicate_line = api.create_contract_line(
        contract["id"],
        create_contract_line_payload(
            item["id"], tier_price_cents=2100, floor_price_cents=1000
        ),
        ADMIN,
    )
    validate_error(duplicate_line, ApiErrorId.ERR_DUPLICATE_CONTRACT_LINE.value, 409)

    duplicate_route = api.create_delivery_route(
        create_delivery_route_payload(
            route_code="RT-UNQ", service_date="2026-08-06",
            vehicle_class="REEFER_VAN",
        ),
        OPERATOR,
    )
    validate_error(duplicate_route, ApiErrorId.ERR_DUPLICATE_ROUTE_CODE.value, 409)

    _items, item_meta = validate_paginated(
        api.list_items(ADMIN, params={"limit": 10, "offset": 0})
    )
    assert item_meta["total_count"] == 1
    _lines, line_meta = validate_paginated(
        api.list_contract_lines(
            ADMIN, params={"contract_id": contract["id"], "limit": 10, "offset": 0}
        )
    )
    assert line_meta["total_count"] == 1


def test_write_endpoints_reject_roles_outside_their_authorised_list(api):
    """PRD §2.1: "If both headers are well formed but the named role is not among
    the roles authorised for the endpoint (see the catalogue in §4), the
    rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.9: "**Role authorisation.** The acting role appears in the endpoint's
    role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies everywhere."

    Design: Corner/rbac/clinician_cannot_write_order_lines
    """
    world = setup_draft_order(
        room_overrides={
            "facility_code": "FAC-700", "room_code": "GEN-700",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        item_overrides={
            "sku": "SKU-RB1-CS", "description": "RBAC probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-RB1",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        tier_price_cents=3000,
        floor_price_cents=2000,
        formulary_overrides={"facility_item_code": "FAC-RB1", "par_qty": 50,
                             "reorder_point": 10},
    )

    clinician_write = api.create_order_line(
        world["order"]["id"],
        create_order_line_payload(world["item"]["id"], 1, world["order"]["version"]),
        make_clinician_headers(CLINICIAN_USER_ID),
    )
    validate_error(clinician_write, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    manager_allocate = api.allocate_order(
        world["order"]["id"], make_materials_manager_headers(world["room"]["id"])
    )
    validate_error(manager_allocate, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    after = read_order(world["order"]["id"])
    assert after["version"] == world["order"]["version"]
    assert after["order_total_cents"] == 0
    assert after["fulfillment_status"] == "DRAFT"


def test_all_five_roles_may_read_a_supply_room(api):
    """PRD §2.1: "Every read endpoint in this API is open to all five roles.
    Write endpoints are narrow, and the authoritative per-endpoint role list is
    the table in §4."
    PRD §2.1: "The five roles are `ContractAdmin`, `MaterialsManager`,
    `Clinician`, `DistributionOperator` and `ManufacturerRep`, spelled exactly
    so."

    Design: Corner/rbac/every_declared_role_may_read_a_supply_room
    """
    room = create_supply_room(
        facility_code="FAC-704", room_code="GEN-704", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )

    readers = [
        TEST_USERS["contract_admin_headers"],
        make_materials_manager_headers(room["id"]),
        TEST_USERS["clinician_headers"],
        TEST_USERS["distribution_operator_headers"],
        TEST_USERS["manufacturer_rep_headers"],
    ]

    codes = []
    for headers in readers:
        data = validate_success(api.get_supply_room(room["id"], headers), 200)
        codes.append(data["room_code"])

    assert codes == ["GEN-704"] * 5, (
        f"every declared role must read the same room, got {codes}"
    )
