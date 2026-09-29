"""Authentication and role-gate probes: the wrong identity is the assertion.

PRD.md section 2.1 declares three distinct header failures and one permission
failure, and PRD.md section 2.7 orders them ahead of existence and state. Every
call below is deliberately made by a principal the endpoint does not list, or
with headers that never name a role at all; the refusal is the subject of the
test, and each test also proves that nothing was written.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    Q_MASS,
    abort_payload,
    acknowledge_storage_guidance_payload,
    assert_decimal_equals,
    assert_instant_equals,
    build_user_headers,
    cancel_order_payload,
    create_plant_baseline,
    create_resin_lot,
    customer_payload,
    inspect_payload,
    mold_payload,
    molding_cycle_payload,
    product_model_payload,
    production_order_payload,
    production_order_version,
    quarantine_payload,
    release_storage_payload,
    resin_charge_payload,
    resin_lot_payload,
    resin_lot_version,
    retire_mold_payload,
    setup_stored_units,
    shipment_payload,
    trim_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warehouse_payload,
    zone,
)

ADMIN_USER = "admin-1"


def _p4_headers_without_role(user_id: str = ADMIN_USER) -> dict[str, str]:
    """Headers that carry an identity but never name a role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def _p4_headers_with_blank_identity(role: str) -> dict[str, str]:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def test_missing_blank_and_unknown_identity_headers_answer_before_role_lookup(
    api, no_auth_headers
):
    """The three header failures carry two codes, and both outrank 404 and 403.

    PRD.md section 2.1: "Every request must carry two headers: `X-User-ID`,
    which identifies the acting principal, and `X-User-Role`, which names the
    role being asserted. When either header is absent or empty the request is
    rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). When `X-User-Role` is
    not one of the eight role names below the request is rejected with
    `ERR_INVALID_ROLE` (HTTP 401). When the role is recognised but the endpoint
    being called does not list it among its authorised roles, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD.md section 2.7: "Authentication and authorization come first: missing or
    malformed identity headers, then an unknown role, then a role that is not
    permitted on the endpoint."
    PRD.md section 2.7: "Existence of every path identifier is checked next, so
    a request naming a resource that does not exist is a 404 before any body
    field is examined."

    Design: Corner/rbac/rbac_missing_blank_and_unknown_identity_headers_are_refused_before_role_lookup
    """
    admin = build_user_headers(ADMIN_USER, "PlantAdmin")
    model = validate_success(api.create_product_model(product_model_payload(), admin), 201)

    validate_error(
        api.get_product_model(model["id"], _p4_headers_without_role()),
        ApiErrorId.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.get_product_model(model["id"], no_auth_headers),
        ApiErrorId.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.get_product_model(model["id"], _p4_headers_with_blank_identity("PlantAdmin")),
        ApiErrorId.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.get_product_model(
            model["id"], build_user_headers(ADMIN_USER, "PlantAdministrator")
        ),
        ApiErrorId.INVALID_ROLE,
    )
    validate_error(
        api.get_product_model(NON_EXISTENT_UUID, _p4_headers_without_role()),
        ApiErrorId.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.create_product_model(product_model_payload(), _p4_headers_without_role()),
        ApiErrorId.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.create_mold(
            mold_payload(model["id"]), _p4_headers_with_blank_identity("MoldingOperator")
        ),
        ApiErrorId.MISSING_AUTH_HEADERS,
    )

    models, model_meta = validate_paginated(api.list_product_models(None, admin))
    assert model_meta["total_count"] == 1, (
        "the header-less create wrote nothing, so only the setup model exists"
    )
    assert models[0]["id"] == model["id"], "and it is the setup model"
    _, mold_meta = validate_paginated(api.list_molds(None, admin))
    assert mold_meta["total_count"] == 0, (
        "the blank-identity mould create wrote nothing either, and it was refused at "
        "the header check rather than at the role gate MoldingOperator would also fail"
    )

    readable = validate_success(api.get_product_model(model["id"], admin))
    assert readable["id"] == model["id"], (
        "the identical read succeeds once both headers are present and the role is "
        "one of the eight, which pins every refusal above on the headers alone"
    )


def test_shop_floor_and_planner_roles_are_denied_each_others_exclusive_actions(
    api, admin_headers, planner_headers
):
    """Nine cross-remit calls all answer 403, and none of them writes anything.

    PRD.md section 2.1: "When the role is recognised but the endpoint being
    called does not list it among its authorised roles, the request is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD.md section 2.1: "`ResinTechnician` reserves resin against cycles and
    releases those reservations. `MoldingOperator` schedules and runs moulding
    cycles. `AssemblyTechnician` performs the trim and outfit steps on demoulded
    hulls. `QualityInspector` inspects hulls, records verdicts and quarantines
    resin lots. `LogisticsPlanner` owns warehouses, storage placement,
    shipments and their lines. `PlantAdmin` owns the plant's reference data:
    product models, moulds, oven stations, cooling bays, technicians and
    customers."
    PRD.md section 2.7: "Authentication and authorization come first ... then a
    role that is not permitted on the endpoint. Existence of every path
    identifier is checked next."

    Design: Corner/rbac/rbac_shop_floor_and_planner_roles_denied_on_each_others_exclusive_actions
    """
    ctx = setup_stored_units()
    first_unit_id, second_unit_id = ctx["stored_unit_ids"]
    lot_before = api.read_entity("get_resin_lot", ctx["resin_lot_id"], admin_headers)

    validate_error(
        api.create_molding_cycle(
            molding_cycle_payload(
                ctx["production_order_id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(ctx["production_order_id"]),
                oven_start_at="2026-08-02T09:00:00Z",
                oven_end_at="2026-08-02T10:00:00Z",
                cooling_window_end_at="2026-08-02T10:30:00Z",
            ),
            ctx["resin_tech_headers"],
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_resin_charge(
            resin_charge_payload(
                ctx["molding_cycle_id"],
                ctx["resin_lot_id"],
                resin_lot_version(ctx["resin_lot_id"]),
            ),
            ctx["operator_headers"],
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.trim_finished_unit(first_unit_id, trim_payload(), ctx["inspector_headers"]),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.inspect_finished_unit(
            second_unit_id, inspect_payload(), ctx["assembly_headers"]
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.quarantine_resin_lot(
            ctx["resin_lot_id"], quarantine_payload(), ctx["operator_headers"]
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.release_storage(
            first_unit_id, release_storage_payload(), ctx["assembly_headers"]
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_shipment(shipment_payload(ctx["warehouse_id"]), admin_headers),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_mold(mold_payload(ctx["product_model_id"]), planner_headers),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.retire_mold(NON_EXISTENT_UUID, retire_mold_payload(), planner_headers),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    _, cycle_meta = validate_paginated(
        api.list_molding_cycles(
            {"production_order_id": ctx["production_order_id"]}, admin_headers
        )
    )
    assert cycle_meta["total_count"] == 1, (
        "the ResinTechnician's cycle create wrote nothing, so the order still has "
        "only the cycle the setup scheduled"
    )
    _, charge_meta = validate_paginated(
        api.list_resin_charges(
            {"molding_cycle_id": ctx["molding_cycle_id"]}, admin_headers
        )
    )
    assert charge_meta["total_count"] == 1, (
        "and the MoldingOperator's charge create wrote nothing either"
    )
    lot_after = api.read_entity("get_resin_lot", ctx["resin_lot_id"], admin_headers)
    assert lot_after["status"] == "AVAILABLE", (
        "the MoldingOperator's quarantine attempt left the lot untouched"
    )
    assert lot_after["version"] == lot_before["version"], (
        "and did not advance its version"
    )
    for unit_id in (first_unit_id, second_unit_id):
        unit = api.read_entity("get_finished_unit", unit_id, admin_headers)
        assert unit["build_status"] == "SELLABLE", (
            "neither the QualityInspector's trim nor the AssemblyTechnician's "
            "inspect moved a hull along the build axis"
        )
        assert unit["logistics_status"] == "STORED", (
            "and the AssemblyTechnician's release-storage did not move the "
            "logistics axis either"
        )
    _, shipment_meta = validate_paginated(api.list_shipments(None, planner_headers))
    assert shipment_meta["total_count"] == 0, (
        "the PlantAdmin's shipment create wrote nothing"
    )
    _, mold_meta = validate_paginated(
        api.list_molds({"product_model_id": ctx["product_model_id"]}, admin_headers)
    )
    assert mold_meta["total_count"] == 1, (
        "and the LogisticsPlanner's mould create wrote nothing, leaving only the "
        "tool the baseline created; the planner's retire attempt against an id "
        "that resolves to no mould answered 403 rather than 404, because the "
        "role gate is checked before path existence"
    )


def test_role_code_must_agree_with_the_backing_technician_on_all_four_roles(
    api, admin_headers
):
    """A permitted role asserted with the wrong technician is a mismatch, not a denial.

    PRD.md section 2.1: "Because all four shop-floor roles share a single
    backing entity, the role asserted in the header must agree with the backing
    technician's `role_code`: `ResinTechnician` requires `role_code`
    `RESIN_TECH`, `MoldingOperator` requires `MOLDING_OPERATOR`,
    `AssemblyTechnician` requires `ASSEMBLY_TECH`, and `QualityInspector`
    requires `QUALITY_INSPECTOR`. Asserting one shop-floor role with the
    identifier of a technician carrying a different `role_code` fails with
    `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."
    PRD.md section 2.1: "Four roles ... are backed by the `Technician` entity,
    so `X-User-ID` must resolve to a `Technician` row; if it does not, the
    request fails with `ERR_IDENTITY_NOT_FOUND` (HTTP 401)."
    PRD.md section 2.7 band 1: "header presence, role validity, endpoint
    permission, identity resolution, role/identity agreement, customer scope."

    Design: Corner/rbac/rbac_role_code_discrimination_among_the_four_technician_backed_roles
    """
    ctx = setup_stored_units()
    first_unit_id, second_unit_id = ctx["stored_unit_ids"]

    validate_error(
        api.create_molding_cycle(
            molding_cycle_payload(
                ctx["production_order_id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(ctx["production_order_id"]),
                arm_index=2,
                oven_start_at="2026-08-01T13:00:00Z",
            ),
            build_user_headers(ctx["assembly_technician_id"], "MoldingOperator"),
        ),
        ApiErrorId.ROLE_IDENTITY_MISMATCH,
    )
    validate_error(
        api.trim_finished_unit(
            first_unit_id,
            trim_payload(),
            build_user_headers(ctx["quality_inspector_id"], "AssemblyTechnician"),
        ),
        ApiErrorId.ROLE_IDENTITY_MISMATCH,
    )
    validate_error(
        api.create_resin_charge(
            resin_charge_payload(
                ctx["molding_cycle_id"],
                ctx["resin_lot_id"],
                resin_lot_version(ctx["resin_lot_id"]),
            ),
            build_user_headers(ctx["molding_operator_id"], "ResinTechnician"),
        ),
        ApiErrorId.ROLE_IDENTITY_MISMATCH,
    )
    validate_error(
        api.inspect_finished_unit(
            second_unit_id,
            inspect_payload(),
            build_user_headers(ctx["resin_technician_id"], "QualityInspector"),
        ),
        ApiErrorId.ROLE_IDENTITY_MISMATCH,
    )
    validate_error(
        api.create_molding_cycle(
            molding_cycle_payload(
                ctx["production_order_id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(ctx["production_order_id"]),
                arm_index=2,
                oven_start_at="2026-08-01T13:00:00Z",
            ),
            build_user_headers(NON_EXISTENT_UUID, "MoldingOperator"),
        ),
        ApiErrorId.IDENTITY_NOT_FOUND,
    )

    _, cycle_meta = validate_paginated(
        api.list_molding_cycles(
            {"production_order_id": ctx["production_order_id"]}, admin_headers
        )
    )
    assert cycle_meta["total_count"] == 1, "neither cycle create wrote a row"
    _, charge_meta = validate_paginated(
        api.list_resin_charges(
            {"molding_cycle_id": ctx["molding_cycle_id"]}, admin_headers
        )
    )
    assert charge_meta["total_count"] == 1, "and the charge create wrote nothing"
    for unit_id in (first_unit_id, second_unit_id):
        unit = api.read_entity("get_finished_unit", unit_id, admin_headers)
        assert unit["build_status"] == "SELLABLE", (
            "both hulls are untouched: the mismatched trim and the mismatched "
            "inspect were both refused in the authorization band, before the "
            "inspector's certifications were ever consulted"
        )


def test_every_role_performs_its_own_and_its_shared_operations(
    api, admin_headers, planner_headers
):
    """The positive half of the matrix: each listed role is actually accepted.

    PRD.md section 4 lists `PlantAdmin, LogisticsPlanner` for POST /customers,
    POST /warehouses, POST /production-orders, the order release and the order
    cancel; `PlantAdmin, ResinTechnician` for POST /resin-lots;
    `MoldingOperator` for POST /molding-cycles; `MoldingOperator, PlantAdmin`
    for the cycle abort; `PlantAdmin, LogisticsPlanner, Customer` for the
    storage-guidance acknowledgement; `PlantAdmin, LogisticsPlanner` for the
    footprint summary; and `PlantAdmin, ResinTechnician, MoldingOperator,
    QualityInspector` for GET /resin-charges.
    PRD.md section 2.1: "Shares order and site creation with `LogisticsPlanner`,
    resin-lot intake with `ResinTechnician`, cycle abort with `MoldingOperator`."
    PRD.md section 2.1: "Shares customer, site, demand-bucket and
    production-order creation, release and cancellation with `PlantAdmin`, and
    shares the storage-guidance acknowledgement with `PlantAdmin` and
    `Customer`."

    Design: Corner/rbac/rbac_positive_matrix_every_role_performs_its_own_and_its_shared_operations
    """
    ctx = create_plant_baseline()
    lot = create_resin_lot()

    planner_customer = validate_success(
        api.create_customer(customer_payload(), planner_headers), 201
    )
    admin_customer = validate_success(
        api.create_customer(customer_payload(), admin_headers), 201
    )

    warehouse = validate_success(
        api.create_warehouse(
            warehouse_payload(footprint_capacity_cube_m3=30.0, zones=[zone("Z-P", 30.0)]),
            planner_headers,
        ),
        201,
    )
    validate_success(
        api.create_resin_lot(
            resin_lot_payload(received_kg=100.0), ctx["resin_tech_headers"]
        ),
        201,
    )

    order = validate_success(
        api.create_production_order(
            production_order_payload(ctx["product_model_id"], warehouse["id"]),
            planner_headers,
        ),
        201,
    )
    assert order["status"] == "DRAFT", "a new order opens in DRAFT"
    released = validate_success(
        api.release_production_order(order["id"], planner_headers)
    )
    assert released["status"] == "READY_TO_SCHEDULE", (
        "the planner's release moves a DRAFT order to the floor because a "
        "qualified lot exists and the target site is not frozen"
    )

    cycle = validate_success(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                released["version"],
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert cycle["status"] == "SCHEDULED", "the operator's cycle opens SCHEDULED"
    assert cycle["operator_technician_id"] == ctx["molding_operator_id"], (
        "and the acting MoldingOperator becomes the cycle's operator"
    )
    aborted = validate_success(
        api.abort_molding_cycle(
            cycle["id"], abort_payload("OPERATOR_ABORT"), ctx["operator_headers"]
        )
    )
    assert aborted["status"] == "ABORTED", "the same operator may abort it"
    assert aborted["abort_reason"] == "OPERATOR_ABORT", "with the reason it sent"
    lot_after = api.read_entity("get_resin_lot", lot["id"], admin_headers)
    assert_decimal_equals(lot_after["available_kg"], "500.000", Q_MASS, "available_kg")

    cancelled = validate_success(
        api.cancel_production_order(order["id"], cancel_order_payload(), admin_headers)
    )
    assert cancelled["status"] == "CANCELLED", (
        "PlantAdmin may cancel an order the planner created and released, "
        "because the two roles share that endpoint"
    )

    self_acked = validate_success(
        api.acknowledge_storage_guidance(
            planner_customer["id"],
            acknowledge_storage_guidance_payload(),
            build_user_headers(planner_customer["id"], "Customer"),
        )
    )
    assert_instant_equals(
        self_acked["storage_guidance_acknowledged_at"],
        "2026-08-01T00:00:00Z",
        "a customer may acknowledge for itself at the instant it sends",
    )
    validate_success(
        api.acknowledge_storage_guidance(
            admin_customer["id"], acknowledge_storage_guidance_payload(), planner_headers
        )
    )

    planner_summary = validate_success(
        api.get_warehouse_footprint_summary(warehouse["id"], planner_headers)
    )
    admin_summary = validate_success(
        api.get_warehouse_footprint_summary(warehouse["id"], admin_headers)
    )
    assert planner_summary == admin_summary, (
        "the computed read is identical for both roles that may call it"
    )

    _, charge_meta = validate_paginated(
        api.list_resin_charges(None, ctx["resin_tech_headers"])
    )
    assert charge_meta["total_count"] == 0, (
        "the ResinTechnician may list charges, and none was ever reserved"
    )
