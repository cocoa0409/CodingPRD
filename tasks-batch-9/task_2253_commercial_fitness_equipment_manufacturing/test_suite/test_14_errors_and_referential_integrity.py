"""Not-found families, schema bounds and the order the validation ladder runs in."""
from test_helpers import (
    NON_EXISTENT_UUID,
    assert_error_envelope,
    equipment_model_payload,
    facility_payload,
    install_job_payload,
    maintenance_visit_payload,
    make_service_partner_tech_headers,
    new_equipment_model,
    new_facility,
    new_model_revision,
    new_order,
    new_service_partner,
    order_line_payload,
    order_payload,
    quote_payload,
    read_equipment_model,
    read_facility,
    read_order,
    read_service_partner,
    read_test_rig,
    revision_payload_for_preset,
    setup_configured_order,
    setup_released_revision,
    setup_staged_order,
    rig_payload,
    run_payload,
    validate_error,
    validate_paginated,
)

EQUAL_ENDPOINTS = ("2026-10-01T08:00:00Z", "2026-10-01T08:00:00Z")
REVERSED_ENDPOINTS = ("2026-10-01T12:00:00Z", "2026-10-01T08:00:00Z")


def test_every_not_found_family_answers_with_its_own_code(
    api, product_engineer_headers, order_planner_headers, service_ops_admin_headers
):
    """Fourteen unknown-id reads produce the ten codes the catalogue declares.

    The PRD states that "Path identifiers are resolved strictly left to right, and
    resolution stops at the first identifier that does not exist" and that "Each
    resource family has its own 404 identifier, and several families deliberately
    share one", naming among them "`ERR_TEST_RESOURCE_NOT_FOUND` — no durability
    test rig and no durability test run with the referenced identifier; the testing
    family shares one code."

    Design: Corner/errors/every_not_found_code_in_the_catalog_is_reachable_by_family
    """
    probes = [
        (api.get_equipment_model, product_engineer_headers, "ERR_MODEL_NOT_FOUND"),
        (api.get_model_revision, product_engineer_headers, "ERR_REVISION_NOT_FOUND"),
        (api.get_test_rig, product_engineer_headers, "ERR_TEST_RESOURCE_NOT_FOUND"),
        (api.get_test_run, product_engineer_headers, "ERR_TEST_RESOURCE_NOT_FOUND"),
        (api.get_firmware_release, product_engineer_headers, "ERR_FIRMWARE_NOT_FOUND"),
        (api.get_firmware_certification, product_engineer_headers,
         "ERR_FIRMWARE_NOT_FOUND"),
        (api.get_facility, order_planner_headers, "ERR_FACILITY_NOT_FOUND"),
        (api.get_service_partner, service_ops_admin_headers, "ERR_PARTNER_NOT_FOUND"),
        (api.get_order, order_planner_headers, "ERR_ORDER_NOT_FOUND"),
        (api.get_order_line, order_planner_headers, "ERR_ORDER_NOT_FOUND"),
        (api.get_install_job, order_planner_headers, "ERR_INSTALL_JOB_NOT_FOUND"),
        (api.get_serialized_asset, service_ops_admin_headers, "ERR_ASSET_NOT_FOUND"),
        (api.get_pm_program, service_ops_admin_headers, "ERR_SERVICE_PLAN_NOT_FOUND"),
        (api.get_maintenance_visit, service_ops_admin_headers,
         "ERR_SERVICE_PLAN_NOT_FOUND"),
    ]

    seen = []
    for read, headers, expected_error in probes:
        response = read(NON_EXISTENT_UUID, headers)
        error = validate_error(response, expected_error, 404)
        assert_error_envelope(response.json())
        assert error["message"].strip(), expected_error
        seen.append(error["error_id"])

    assert len(seen) == 14
    assert len(set(seen)) == 10, "the shared families answer with one code each"
    assert seen[2] == seen[3] == "ERR_TEST_RESOURCE_NOT_FOUND"
    assert seen[4] == seen[5] == "ERR_FIRMWARE_NOT_FOUND"
    assert seen[8] == seen[9] == "ERR_ORDER_NOT_FOUND"
    assert seen[12] == seen[13] == "ERR_SERVICE_PLAN_NOT_FOUND"


def test_an_unknown_order_and_an_unknown_order_line_share_one_code(
    api, order_planner_headers
):
    """The order family answers for its lines as well as for its orders.

    The PRD states that "`ERR_ORDER_NOT_FOUND` — no order and no order line with
    the referenced identifier" and that path existence means "Every identifier
    embedded in the request path is resolved, left to right, and the first one that
    does not resolve produces that resource family's 404 code".

    Design: Corner/entities/order_not_found_returns_order_not_found
    """
    order_probe = api.get_order(NON_EXISTENT_UUID, order_planner_headers)
    line_probe = api.get_order_line(NON_EXISTENT_UUID, order_planner_headers)

    order_error = validate_error(order_probe, "ERR_ORDER_NOT_FOUND", 404)
    line_error = validate_error(line_probe, "ERR_ORDER_NOT_FOUND", 404)
    assert order_error["error_id"] == line_error["error_id"]
    assert_error_envelope(order_probe.json())
    assert_error_envelope(line_probe.json())
    assert order_error["message"].strip()
    assert line_error["message"].strip()
    _, order_meta = validate_paginated(api.list_orders(order_planner_headers))
    assert order_meta["total_count"] == 0
    _, line_meta = validate_paginated(api.list_order_lines(order_planner_headers))
    assert line_meta["total_count"] == 0


def test_a_missing_required_body_field_is_refused_on_each_creation_endpoint(
    api, order_planner_headers, product_engineer_headers
):
    """Three unrelated creates each name their own required field.

    The PRD states that the schema check requires "Required fields present, JSON
    types correct, enum values within range" and that "Any violation is
    `ERR_INVALID_REQUEST` (400). Applies to every endpoint that accepts a body or
    query parameters."

    Design: Corner/entities/missing_required_body_fields_return_invalid_request
    """
    facility = new_facility(account_name="Grandstand Fitness", freight_zone="Z1")
    no_zone = facility_payload(account_name="Riverside Athletic Club")
    no_zone.pop("freight_zone")
    # The order probe names a facility that does resolve, so the only fault in it
    # is the missing window end.
    no_window_end = order_payload(facility["id"])
    no_window_end.pop("requested_install_window_end")
    no_stations = rig_payload(name="RIG-B")
    no_stations.pop("parallel_station_count")

    validate_error(api.create_facility(no_zone, order_planner_headers),
                   "ERR_INVALID_REQUEST", 400)
    validate_error(api.create_order(no_window_end, order_planner_headers),
                   "ERR_INVALID_REQUEST", 400)
    validate_error(api.create_test_rig(no_stations, product_engineer_headers),
                   "ERR_INVALID_REQUEST", 400)

    _, order_meta = validate_paginated(api.list_orders(order_planner_headers))
    assert order_meta["total_count"] == 0
    _, model_meta = validate_paginated(api.list_equipment_models(
        product_engineer_headers))
    assert model_meta["total_count"] == 0
    unchanged = read_facility(facility["id"])
    assert unchanged["version"] == facility["version"]
    assert unchanged["account_name"] == "Grandstand Fitness"


def test_enum_and_numeric_bound_violations_are_refused_before_business_rules(
    api, order_planner_headers, product_engineer_headers
):
    """Five type-level faults, including one that hides a finish-code fault.

    The PRD states that the schema check requires "every numeric bound respected:
    `quantity` at least 1 and at most 500, `reserved_units` at least 0 and at most
    50, `parallel_station_count` at least 1 and at most 8" as well as "`limit`
    between 1 and 100 inclusive and `offset` at least 0", and that a line's
    `finish_codes` list "may be empty, must contain no duplicates".

    Design: Corner/entities/enum_and_numeric_range_violations_return_invalid_request
    """
    released = setup_released_revision("T900")
    facility = new_facility(account_name="Grandstand Fitness", freight_zone="Z1")
    order = new_order(facility["id"])
    revision_id = released["revision"]["id"]

    validate_error(
        api.create_equipment_model(equipment_model_payload("S500",
                                                           category="AQUATIC"),
                                   product_engineer_headers),
        "ERR_INVALID_REQUEST", 400,
    )
    validate_error(
        api.create_order_line(order["id"],
                              order_line_payload(revision_id,
                                                 finish_codes=["GRAPHITE",
                                                               "GRAPHITE"]),
                              order_planner_headers),
        "ERR_INVALID_REQUEST", 400,
    )
    validate_error(
        api.create_test_rig(rig_payload(name="RIG-B", parallel_station_count=9),
                            product_engineer_headers),
        "ERR_INVALID_REQUEST", 400,
    )
    oversized = api.create_order_line(
        order["id"],
        order_line_payload(revision_id, quantity=501,
                           finish_codes=["CUSTOM_BRAND_DECAL"]),
        order_planner_headers,
    )
    error = validate_error(oversized, "ERR_INVALID_REQUEST", 400)
    assert error["error_id"] != "ERR_FINISH_NOT_ALLOWED"
    assert oversized.status_code != 422, "the bound is checked before the finish set"
    validate_error(
        api.list_orders(order_planner_headers, params={"limit": 101}),
        "ERR_INVALID_REQUEST", 400,
    )

    assert read_order(order["id"])["line_subtotal_cents"] == 0
    _, meta = validate_paginated(
        api.list_order_lines(order_planner_headers, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
    models, model_meta = validate_paginated(
        api.list_equipment_models(product_engineer_headers)
    )
    assert model_meta["total_count"] == 1, "the rejected enum created no model"
    assert models[0]["id"] == released["model"]["id"]


def test_body_foreign_keys_resolve_before_version_pinning_and_state_gates(
    api, order_planner_headers, product_engineer_headers
):
    """An unknown parent in the body wins over a stale pin and over an empty path.

    The PRD states that "Body-borne foreign keys are resolved after the schema
    check, in the same all-or-nothing spirit: an unresolvable reference means the
    request never reaches business logic" and that the check itself is "Every
    foreign key carried in the body resolves to an existing row, otherwise that
    resource family's 404 code".

    Design: Corner/entities/body_foreign_keys_are_resolved_before_occ_and_state_rules
    """
    model = new_equipment_model("T900")
    captured_version = model["version"]
    new_model_revision(model, "T900")
    current = read_equipment_model(model["id"])
    assert current["version"] == captured_version + 1
    facility = new_facility(account_name="Grandstand Fitness", freight_zone="Z1")
    order = new_order(facility["id"])
    partner = new_service_partner(name="Meridian Service Co",
                                  certified_categories=["CARDIO"])

    stale_and_unknown = api.create_model_revision(
        revision_payload_for_preset("T900", NON_EXISTENT_UUID, captured_version,
                                    revision_code="T900-R2"),
        product_engineer_headers,
    )

    validate_error(stale_and_unknown, "ERR_MODEL_NOT_FOUND", 404)
    assert stale_and_unknown.status_code != 412, (
        "the unresolvable parent is reported before the pin is compared"
    )
    validate_error(
        api.create_order_line(order["id"], order_line_payload(NON_EXISTENT_UUID),
                              order_planner_headers),
        "ERR_REVISION_NOT_FOUND", 404,
    )
    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            make_service_partner_tech_headers(partner["id"])),
        "ERR_SERVICE_PLAN_NOT_FOUND", 404,
    )

    _, meta = validate_paginated(
        api.list_model_revisions(product_engineer_headers,
                                 params={"equipment_model_id": model["id"]})
    )
    assert meta["total_count"] == 1, "the rejected create wrote nothing"
    assert read_equipment_model(model["id"])["version"] == current["version"]
    assert read_order(order["id"])["line_subtotal_cents"] == 0


def test_a_supplied_window_must_be_strictly_ordered_on_all_three_creates(
    api, order_planner_headers, product_engineer_headers
):
    """Equal endpoints are as invalid as reversed ones, on each of the three creates.

    The PRD states that "Wherever a pair of window instants is supplied — a
    durability run's reservation window, an install job's window, or an order's
    requested install window — the end must be strictly after the start, otherwise
    `ERR_INVALID_TIME_WINDOW` (422). Applies to exactly three creation operations:
    order creation, durability-run creation and install-job creation."

    Design: Corner/errors/invalid_time_window_covers_equal_and_reversed_endpoints
    """
    ctx = setup_staged_order(
        preset="T900", quantity=1,
        facility_overrides={"account_name": "Grandstand Fitness", "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"})
    assert ctx["revision"]["status"] == "RELEASED"

    validate_error(
        api.create_order(order_payload(ctx["facility"]["id"], *EQUAL_ENDPOINTS),
                         order_planner_headers),
        "ERR_INVALID_TIME_WINDOW", 422,
    )
    validate_error(
        api.create_install_job(
            install_job_payload(ctx["order"]["id"], ctx["partner"]["id"],
                                *REVERSED_ENDPOINTS, estimated_labor_hours=3.0),
            order_planner_headers),
        "ERR_INVALID_TIME_WINDOW", 422,
    )
    on_a_released_revision = api.create_test_run(
        run_payload(ctx["revision"]["id"], ctx["rig"]["id"], *EQUAL_ENDPOINTS),
        product_engineer_headers,
    )

    validate_error(on_a_released_revision, "ERR_INVALID_TIME_WINDOW", 422)
    assert on_a_released_revision.status_code != 409, (
        "window geometry is settled before the revision's state is consulted"
    )
    _, order_meta = validate_paginated(
        api.list_orders(order_planner_headers,
                        params={"facility_id": ctx["facility"]["id"]})
    )
    assert order_meta["total_count"] == 1
    _, job_meta = validate_paginated(
        api.list_install_jobs(order_planner_headers,
                              params={"order_id": ctx["order"]["id"]})
    )
    assert job_meta["total_count"] == 0
    assert read_test_rig(ctx["rig"]["id"])["occupied_station_count"] == 0
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 0.0
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "STAGED"


def test_header_schema_and_window_checks_outrank_the_referential_checks(
    api, service_ops_admin_headers, order_planner_headers, product_engineer_headers
):
    """Three over-determined requests each surface the earlier rung's code.

    The PRD states that "Checks are evaluated in one strict, globally ordered
    ladder" and that when one fails "no later check runs, no side effect of any kind
    is persisted, and the response carries exactly that check's error identifier and
    status."

    Design: Corner/validations/header_schema_and_window_checks_outrank_later_referential_checks
    """
    ctx = setup_configured_order(
        preset="T900", quantity=1,
        facility_overrides={"account_name": "Grandstand Fitness", "freight_zone": "Z1"})

    role_before_path = api.quote_order(NON_EXISTENT_UUID, quote_payload(1),
                                       service_ops_admin_headers)
    schema_before_body_reference = api.create_order_line(
        ctx["order"]["id"], order_line_payload(NON_EXISTENT_UUID, quantity=0),
        order_planner_headers,
    )
    window_before_body_reference = api.create_test_run(
        run_payload(ctx["revision"]["id"], NON_EXISTENT_UUID,
                         *REVERSED_ENDPOINTS),
        product_engineer_headers,
    )

    validate_error(role_before_path, "ERR_ROLE_NOT_PERMITTED", 403)
    assert role_before_path.status_code != 404
    validate_error(schema_before_body_reference, "ERR_INVALID_REQUEST", 400)
    assert schema_before_body_reference.status_code != 404
    validate_error(window_before_body_reference, "ERR_INVALID_TIME_WINDOW", 422)
    assert window_before_body_reference.status_code != 404

    _, line_meta = validate_paginated(
        api.list_order_lines(order_planner_headers,
                             params={"order_id": ctx["order"]["id"]})
    )
    assert line_meta["total_count"] == 1
    order = read_order(ctx["order"]["id"])
    assert order["line_subtotal_cents"] == 508_747
    assert order["billing_status"] == "UNQUOTED"
    _, run_meta = validate_paginated(
        api.list_test_runs(product_engineer_headers,
                           params={"model_revision_id": ctx["revision"]["id"]})
    )
    assert run_meta["total_count"] == len(ctx["runs"])
