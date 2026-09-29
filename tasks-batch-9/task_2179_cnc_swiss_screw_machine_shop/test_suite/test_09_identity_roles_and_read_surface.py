"""Headers, role authority, uniqueness, not-found codes and the read envelope."""

from test_helpers import (
    MISSING_UUID,
    ApiErrorId,
    add_characteristic,
    api_client,
    assert_three_fractional_digits,
    create_part_payload,
    headers_without_identity,
    is_valid_uuid,
    machine_version,
    make_inspector_headers,
    make_machinist_headers,
    make_quality_manager_headers,
    make_shop_planner_headers,
    read_bar_lot,
    register_machine,
    register_part,
    register_second_part,
    set_clock,
    setup_machining_complete_work_order,
    setup_scheduled_work_order,
    setup_shop_floor,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = make_shop_planner_headers()
QUALITY = make_quality_manager_headers()


def test_registering_a_part_answers_201_with_its_seeded_computed_fields():
    """PRD 3.1: "Two computed fields are seeded at creation and never typed in —
    `observed_avg_cycle_time_sec` starts null and `observed_accepted_qty` starts 0;
    §3.8 explains what fills them."
    PRD 4: "Operations that mint a brand-new resource answer 201 Created; every
    other successful operation, including all state-advancing actions and all reads,
    answers 200 OK."

    Design: Corner/entities/create_part_returns_201_with_every_declared_field
    """
    set_clock()

    part = validate_success(api_client.create_part(create_part_payload(), PLANNER), 201)
    assert part["part_number"] == "P-4471"
    assert part["alloy_code"] == "303SS"
    assert part["bar_diameter_mm"] == 12.7
    assert part["cycle_time_sec"] == 42
    assert part["finished_mass_g"] == 18.3
    assert part["observed_avg_cycle_time_sec"] is None
    assert part["observed_accepted_qty"] == 0
    assert part["version"] == 1


def test_reading_a_machine_returns_its_live_state_and_empty_accrual():
    """PRD 3.1: "A newly registered machine has `status` `AVAILABLE` — the three
    legal values are `AVAILABLE`, `RUNNING` and `DOWN` — with `current_work_order_id`
    null, an empty `chip_accrual_by_alloy` map, `coolant_makeup_liters` at 0,
    `last_reclamation_credit_cents` null because nothing has ever been settled, and
    `lifetime_reclamation_credit_cents` at 0."

    Design: Corner/entities/get_machine_returns_the_stored_machine
    """
    set_clock()
    machine = register_machine()

    stored = validate_success(
        api_client.get_machine(machine["id"], make_machinist_headers(MISSING_UUID)), 200
    )
    assert stored["asset_tag"] == "SW-01"
    assert stored["status"] == "AVAILABLE"
    assert stored["version"] == 1
    assert stored["coolant_makeup_liters"] == 0
    assert stored["last_reclamation_credit_cents"] is None


def test_characteristics_can_be_narrowed_to_one_part_and_windowed():
    """PRD 3.1: "Characteristics may be listed across the shop or narrowed to a
    single part by supplying `part_id` as a filter."
    PRD 2.3: "List responses set `response_type` to `"array"` and populate four
    pagination fields inside `meta`: `limit` and `offset` echo the effective values
    used, `total_count` reports the number of rows matching the filter before the
    window was applied, and `has_more` is true when rows remain beyond the current
    window."

    Design: Corner/entities/list_characteristics_filtered_by_part_with_pagination
    """
    set_clock()
    first_part = register_part()
    second_part = register_second_part()
    own_a = add_characteristic(first_part["id"], char_code="OD-A", sample_freq_pieces=200)
    own_b = add_characteristic(first_part["id"], char_code="OD-B", sample_freq_pieces=100)
    foreign = add_characteristic(
        second_part["id"],
        char_code="ID-C",
        sample_freq_pieces=50,
        required_gauge_type="BORE_GAUGE",
    )

    rows, meta = validate_paginated(
        api_client.list_characteristics(PLANNER, {"part_id": first_part["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(rows) == 1
    assert rows[0]["id"] in (own_a["id"], own_b["id"])
    assert rows[0]["id"] != foreign["id"]


def test_reading_a_work_order_that_does_not_exist_is_a_not_found():
    """PRD 2.9: "Next, every resource named in the URL path must exist, validated
    strictly left to right, so on a nested path the leftmost missing segment
    determines the reported code."
    PRD 2.9: "`ERR_WORK_ORDER_NOT_FOUND` for a work order"

    Design: Corner/entities/get_work_order_with_unknown_id_returns_not_found
    """
    set_clock()

    response = api_client.get_work_order(MISSING_UUID, PLANNER)
    validate_error(response, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value)


def test_the_server_mints_the_identifier_timestamp_and_version():
    """PRD 2.4: "Every stored resource is addressed by an `id`, which is a
    server-minted UUID carrying no type prefix and no client-supplied component.
    Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three
    fractional digits recording when the row was first written."
    PRD 3.1: "and `status`, which is either `ACTIVE` or `INACTIVE` and defaults to
    `ACTIVE`."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/server_mints_id_created_at_and_version_on_every_entity
    """
    set_clock()

    response = api_client.create_operator(
        {"name": "Rey Molina", "badge_code": "BM-01", "certifications": ["SWISS_SETUP"]},
        PLANNER,
    )
    operator = validate_success(response, 201)
    assert is_valid_uuid(operator["id"]), "the id must be a bare UUID with no type prefix"
    assert not operator["id"].startswith("op_")
    assert operator["version"] == 1
    assert operator["status"] == "ACTIVE"
    assert_three_fractional_digits(operator["created_at"])

    body = response.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"


def test_characteristic_with_an_unknown_gauge_family_is_rejected():
    """PRD 3.1: "`required_gauge_type` names the instrument family that must be
    used and is one of `MICROMETER`, `BORE_GAUGE`, `OPTICAL_COMPARATOR` or `CMM`."
    PRD 2.9: "then request-body well-formedness, yielding `ERR_INVALID_REQUEST` —
    this covers missing required fields, wrong types, enum members outside their
    declared sets, numeric fields outside their declared bounds, a
    `scheduled_end_at` that is not strictly after `scheduled_start_at`, and
    out-of-range pagination."

    Design: Corner/entities/create_characteristic_invalid_enum_returns_invalid_request
    """
    set_clock()
    part = register_part()

    response = api_client.create_characteristic(
        {
            "part_id": part["id"],
            "char_code": "OD-A",
            "nominal": 6.35,
            "usl": 6.375,
            "lsl": 6.325,
            "sample_freq_pieces": 200,
            "required_gauge_type": "LASER_MIC",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_characteristic_naming_an_unknown_part_is_a_part_not_found():
    """PRD 2.9: "Next, every foreign key named in the request body must exist,
    validated in the order the fields are declared on the owning entity — this
    applies to creating a characteristic, a quote, a kanban release, a tool
    assignment, a work order, an SPC subgroup and a routing step."
    PRD 2.9: "`ERR_PART_NOT_FOUND` for a part"

    Design: Corner/entities/create_characteristic_with_unknown_part_returns_part_not_found
    """
    set_clock()

    response = api_client.create_characteristic(
        {
            "part_id": MISSING_UUID,
            "char_code": "OD-A",
            "nominal": 6.35,
            "usl": 6.375,
            "lsl": 6.325,
            "sample_freq_pieces": 200,
            "required_gauge_type": "MICROMETER",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_PART_NOT_FOUND.value)


def test_every_resource_family_answers_with_its_own_not_found_code():
    """PRD 2.9: "Each resource family carries its own not-found code, all of them
    HTTP 404: `ERR_OPERATOR_NOT_FOUND` for an operator, `ERR_MACHINE_NOT_FOUND` for
    a machine, `ERR_PART_NOT_FOUND` for a part, `ERR_CHARACTERISTIC_NOT_FOUND` for a
    print characteristic, `ERR_GAUGE_NOT_FOUND` for a gauge, `ERR_BAR_LOT_NOT_FOUND`
    for a bar stock lot, `ERR_QUOTE_NOT_FOUND` for a quote,
    `ERR_BLANKET_PO_NOT_FOUND` for a blanket order, `ERR_RELEASE_NOT_FOUND` for a
    kanban release, `ERR_WORK_ORDER_NOT_FOUND` for a work order,
    `ERR_TOOL_ASSIGNMENT_NOT_FOUND` for a tool station, `ERR_SPC_SAMPLE_NOT_FOUND`
    for a measured subgroup, and `ERR_ROUTING_STEP_NOT_FOUND` for a routing step."

    Design: Corner/errors/unknown_ids_on_every_read_endpoint_return_their_own_not_found_code
    """
    set_clock()
    probes = [
        (api_client.get_machine, ApiErrorId.ERR_MACHINE_NOT_FOUND.value),
        (api_client.get_gauge, ApiErrorId.ERR_GAUGE_NOT_FOUND.value),
        (api_client.get_bar_stock_lot, ApiErrorId.ERR_BAR_LOT_NOT_FOUND.value),
        (api_client.get_quote, ApiErrorId.ERR_QUOTE_NOT_FOUND.value),
        (api_client.get_blanket_po, ApiErrorId.ERR_BLANKET_PO_NOT_FOUND.value),
        (api_client.get_kanban_release, ApiErrorId.ERR_RELEASE_NOT_FOUND.value),
        (api_client.get_tool_assignment, ApiErrorId.ERR_TOOL_ASSIGNMENT_NOT_FOUND.value),
        (api_client.get_spc_sample, ApiErrorId.ERR_SPC_SAMPLE_NOT_FOUND.value),
        (api_client.get_routing_step, ApiErrorId.ERR_ROUTING_STEP_NOT_FOUND.value),
        (api_client.get_characteristic, ApiErrorId.ERR_CHARACTERISTIC_NOT_FOUND.value),
        (api_client.get_operator, ApiErrorId.ERR_OPERATOR_NOT_FOUND.value),
    ]
    for read, expected in probes:
        response = read(MISSING_UUID, PLANNER)
        validate_error(response, expected)
        assert response.json()["response_type"] == "error"


def test_a_repeated_part_number_collides():
    """PRD 3.1: "Uniqueness is enforced on creation across the master file and
    rejected with `ERR_DUPLICATE_KEY` (HTTP 409): a repeated `part_number` on a
    part, `asset_tag` on a machine, `gauge_code` on a gauge, `heat_number` on a bar
    lot, `badge_code` on an operator, `char_code` within the same part, `station`
    within the same machine, or `sequence` within the same work order."

    Design: Corner/errors/duplicate_part_number_is_rejected_with_duplicate_key
    """
    set_clock()
    register_part()

    response = api_client.create_part(create_part_payload(), PLANNER)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_a_page_size_above_one_hundred_is_malformed():
    """PRD 2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/endpoints/pagination_limit_above_one_hundred_is_rejected
    """
    set_clock()

    response = api_client.list_spc_samples(PLANNER, {"limit": 101, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_a_request_without_identity_headers_is_unauthenticated():
    """PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of
    those four strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD 2.1: "Authentication is checked before authorization, and both are checked
    before anything else about the request is examined."

    Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
    """
    set_clock()

    response = api_client.create_part({}, headers_without_identity())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401, (
        "the missing headers must be reported before the empty body"
    )


def test_a_machinist_may_not_schedule_a_work_order():
    """PRD 2.1: "If both headers are well formed but the named role is not among
    the roles listed for the requested endpoint in §4, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: | POST | `/swiss-shop/work-orders` | Schedules a work order against a
    kanban release, a machine window and a staged bar lot. | ShopPlanner |

    Design: Corner/rbac/machinist_cannot_schedule_a_work_order
    """
    shop = setup_shop_floor()
    version = machine_version(shop.machine_id)

    response = api_client.create_work_order(
        {
            "release_id": shop.release_id,
            "machine_id": shop.machine_id,
            "bar_lot_id": shop.lot_id,
            "qty_ordered": 200,
            "scheduled_start_at": "2026-09-02T06:00:00Z",
            "scheduled_end_at": "2026-09-02T14:00:00Z",
            "expected_machine_version": version,
            "lights_out_hours": 0,
        },
        make_machinist_headers(shop.machinist_id),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    _, meta = validate_paginated(
        api_client.list_work_orders(PLANNER, {"release_id": shop.release_id})
    )
    assert meta["total_count"] == 0
    assert read_bar_lot(shop.lot_id)["reserved_length_mm"] == 0


def test_quality_and_measurement_duties_are_not_interchangeable():
    """PRD 2.10: "A second separation is structural rather than per-request: only
    a `QualityManager` may certify bar stock, calibrate gauges or issue a final
    disposition, and a `QualityManager` never runs a spindle or posts a
    measurement."
    PRD 2.1: "If both headers are well formed but the named role is not among the
    roles listed for the requested endpoint in §4, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/inspector_cannot_disposition_and_planner_cannot_post_subgroups
    """
    shop = setup_machining_complete_work_order()

    inspector_verdict = api_client.disposition_work_order(
        shop.work_order_id,
        {"decision": "ACCEPT", "note": "looks fine"},
        make_inspector_headers(shop.inspector_id),
    )
    validate_error(inspector_verdict, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    planner_subgroup = api_client.create_spc_sample(
        {
            "work_order_id": shop.work_order_id,
            "characteristic_id": shop.characteristic_id,
            "gauge_id": shop.gauge_id,
            "piece_index": 150,
            "measurements": [6.343, 6.35, 6.35, 6.35, 6.357],
        },
        PLANNER,
    )
    validate_error(planner_subgroup, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    summary = validate_success(api_client.get_work_order(shop.work_order_id, QUALITY), 200)
    assert summary["quality_status"] == "IN_SPC"


def test_all_four_roles_may_read_a_work_order():
    """PRD 2.1: "Four roles exist and their spellings are exact: `ShopPlanner`,
    `Machinist`, `Inspector`, and `QualityManager`."
    PRD 4: | GET | `/swiss-shop/work-orders/{id}` | Reads one work order including
    both state dimensions. | ShopPlanner, Machinist, Inspector, QualityManager |

    Design: Corner/rbac/every_role_can_read_the_shared_get_surface
    """
    shop = setup_scheduled_work_order()

    readers = [
        PLANNER,
        make_machinist_headers(shop.machinist_id),
        make_inspector_headers(shop.inspector_id),
        QUALITY,
    ]
    for headers in readers:
        data = validate_success(api_client.get_work_order(shop.work_order_id, headers), 200)
        assert data["machining_status"] == "SCHEDULED"


def test_a_machinist_header_naming_no_operator_is_a_not_found():
    """PRD 2.1: "For both of these roles, the header must name an `Operator` that
    exists and whose `status` is `ACTIVE`; if it names no operator, or names one
    whose `status` is `INACTIVE`, the request is rejected with
    `ERR_OPERATOR_NOT_FOUND` (HTTP 404)."
    PRD 2.9: "Next, for `Machinist` and `Inspector` calls, `X-User-ID` must name an
    `ACTIVE` operator, yielding `ERR_OPERATOR_NOT_FOUND`."

    Design: Corner/errors/machinist_header_naming_no_operator_returns_operator_not_found
    """
    shop = setup_scheduled_work_order()

    response = api_client.start_work_order(
        shop.work_order_id, make_machinist_headers(MISSING_UUID)
    )
    validate_error(response, ApiErrorId.ERR_OPERATOR_NOT_FOUND.value)

    work_order = validate_success(api_client.get_work_order(shop.work_order_id, PLANNER), 200)
    assert work_order["machining_status"] == "SCHEDULED"
