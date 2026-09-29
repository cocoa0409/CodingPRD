"""Resource-specific 404 identifiers, the error envelope, and the peer-based
role model."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    build_cycle_scenario,
    create_cycle_payload,
    create_customer,
    set_clock,
    create_product_payload,
    get_cycle,
    get_lot,
    make_customer_rep_headers,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["regulatory_admin_headers"]
OPERATOR = TEST_USERS["cycle_operator_headers"]
ANALYST = TEST_USERS["dosimetry_analyst_headers"]
OFFICER = TEST_USERS["quality_release_officer_headers"]

UNKNOWN = "00000000-0000-4000-8000-0000000000{:02d}"


def test_reference_data_reads_raise_resource_specific_not_found_ids():
    """PRD 2.7: "Every identifier in the URL is resolved left to right, and
    each resource type raises its own 404: `ERR_CUSTOMER_NOT_FOUND` for a
    customer segment, `ERR_PRODUCT_NOT_FOUND` for a product,
    `ERR_PERMIT_NOT_FOUND` for an emission permit, `ERR_CHAMBER_NOT_FOUND` for
    a chamber, `ERR_RECIPE_NOT_FOUND` for a cycle recipe,
    `ERR_QUALIFICATION_NOT_FOUND` for a qualification, `ERR_LOT_NOT_FOUND` for
    a lot, `ERR_CYCLE_NOT_FOUND` for a cycle, `ERR_LOAD_POSITION_NOT_FOUND` for
    a load position, `ERR_INDICATOR_NOT_FOUND` for an indicator,
    `ERR_AERATION_RECORD_NOT_FOUND` for an aeration record and
    `ERR_ADVERSE_EVENT_NOT_FOUND` for an adverse event."

    Design: Corner/errors/corner_reference_data_not_found_ids_are_resource_specific
    """
    seen = []
    seen.append(
        validate_error(
            api_client.get_product(UNKNOWN.format(1), ADMIN),
            ApiErrorId.ERR_PRODUCT_NOT_FOUND,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api_client.get_permit(UNKNOWN.format(2), ADMIN),
            ApiErrorId.ERR_PERMIT_NOT_FOUND,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api_client.get_chamber(UNKNOWN.format(3), ADMIN),
            ApiErrorId.ERR_CHAMBER_NOT_FOUND,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api_client.get_recipe(UNKNOWN.format(4), ADMIN),
            ApiErrorId.ERR_RECIPE_NOT_FOUND,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api_client.get_qualification(UNKNOWN.format(5), ADMIN),
            ApiErrorId.ERR_QUALIFICATION_NOT_FOUND,
        )["error_id"]
    )

    assert len(set(seen)) == 5, "each resource type raises its own identifier"


def test_operational_endpoints_raise_resource_specific_not_found_ids():
    """PRD 2.7: "Every identifier in the URL is resolved left to right, and
    each resource type raises its own 404: `ERR_CUSTOMER_NOT_FOUND` for a
    customer segment, `ERR_PRODUCT_NOT_FOUND` for a product,
    `ERR_PERMIT_NOT_FOUND` for an emission permit, `ERR_CHAMBER_NOT_FOUND` for
    a chamber, `ERR_RECIPE_NOT_FOUND` for a cycle recipe,
    `ERR_QUALIFICATION_NOT_FOUND` for a qualification, `ERR_LOT_NOT_FOUND` for
    a lot, `ERR_CYCLE_NOT_FOUND` for a cycle, `ERR_LOAD_POSITION_NOT_FOUND` for
    a load position, `ERR_INDICATOR_NOT_FOUND` for an indicator,
    `ERR_AERATION_RECORD_NOT_FOUND` for an aeration record and
    `ERR_ADVERSE_EVENT_NOT_FOUND` for an adverse event."

    Design: Corner/errors/corner_operational_not_found_ids_are_resource_specific
    """
    validate_error(
        api_client.get_lot(UNKNOWN.format(11), ADMIN), ApiErrorId.ERR_LOT_NOT_FOUND
    )
    validate_error(
        api_client.get_load_position(UNKNOWN.format(12), OPERATOR),
        ApiErrorId.ERR_LOAD_POSITION_NOT_FOUND,
    )
    validate_error(
        api_client.record_reading(
            UNKNOWN.format(13), {"measured_dose_kgy": 30.00}, ANALYST
        ),
        ApiErrorId.ERR_INDICATOR_NOT_FOUND,
    )
    validate_error(
        api_client.record_residual_test(
            UNKNOWN.format(14), {"eto_residual_ppm": 1.0, "ech_residual_ppm": 1.0}, ANALYST
        ),
        ApiErrorId.ERR_AERATION_RECORD_NOT_FOUND,
    )
    validate_error(
        api_client.disposition_adverse_event(
            UNKNOWN.format(15), {"disposition": "DISMISS"}, OFFICER
        ),
        ApiErrorId.ERR_ADVERSE_EVENT_NOT_FOUND,
    )


def test_error_envelope_carries_meta_and_a_typed_error_body():
    """PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/corner_error_envelope_shape_matches_the_contract
    """
    response = api_client.get_customer(UNKNOWN.format(21), ADMIN)

    body = response.json()
    assert response.status_code == 404
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    error_data = validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
    assert error_data["error_id"] == "ERR_CUSTOMER_NOT_FOUND"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()


def test_a_cycle_operator_cannot_release_a_lot():
    """PRD 2.1: "If the headers are well formed but the role is not among those
    authorised for the requested operation — the authorised roles for every
    operation are listed in the endpoint table of §4 — the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 3.9: "Quarantine is the default resting place of processed goods, and a
    `QualityReleaseOfficer` is the only role that can end it."
    PRD 4: "| POST   | `/sterilization/lots/{id}/release`                        | Release a quarantined lot.                                                                                         | `QualityReleaseOfficer`                                                                        |"

    Design: Corner/rbac/corner_cycle_operator_cannot_release_a_lot
    """
    env = build_cycle_scenario(stage="closed")

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, OPERATOR
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["release_mode"] == "NONE"


def test_a_quality_release_officer_cannot_schedule_a_cycle():
    """PRD 2.1: "If the headers are well formed but the role is not among those
    authorised for the requested operation — the authorised roles for every
    operation are listed in the endpoint table of §4 — the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST   | `/sterilization/cycles`                                   | Schedule a cycle in a chamber against an approved recipe.                                                          | `CycleOperator`                                                                                |"

    Design: Corner/rbac/corner_quality_release_officer_cannot_schedule_a_cycle
    """
    env = setup_reference_data(qualify=False)

    response = api_client.create_cycle(
        create_cycle_payload(env["chamber"]["id"], env["recipe"]["id"]), OFFICER
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    _, meta = validate_paginated(
        api_client.list_cycles(OPERATOR, params={"chamber_id": env["chamber"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_dosimetry_analyst_cannot_place_indicators():
    """PRD 2.1: "If the headers are well formed but the role is not among those
    authorised for the requested operation — the authorised roles for every
    operation are listed in the endpoint table of §4 — the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST   | `/sterilization/load-positions/{id}/indicators`           | Place a dosimeter or biological indicator in a load-map slot.                                                      | `CycleOperator`                                                                                |"

    Design: Corner/rbac/corner_dosimetry_analyst_cannot_place_indicators
    """
    env = build_cycle_scenario(stage="loading", place_indicators=False)

    response = api_client.create_indicator(
        env["position"]["id"],
        {"indicator_type": "DOSIMETER", "placement_zone": "MIN_DOSE", "serial_code": "D-MIN"},
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    _, meta = validate_paginated(
        api_client.list_indicators(env["position"]["id"], OPERATOR)
    )
    assert meta["total_count"] == 0


def test_a_customer_rep_cannot_register_products():
    """PRD 2.1: "If the headers are well formed but the role is not among those
    authorised for the requested operation — the authorised roles for every
    operation are listed in the endpoint table of §4 — the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST   | `/sterilization/products`                                 | Register a product family with its mass, volume, dose and residual limits.                                         | `RegulatoryAdmin`                                                                              |"

    Design: Corner/rbac/corner_customer_rep_cannot_create_products
    """
    set_clock("2026-08-10T00:00:00Z")
    customer = create_customer()

    response = api_client.create_product(
        create_product_payload(customer["id"]), make_customer_rep_headers(customer["id"])
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    _, meta = validate_paginated(
        api_client.list_customer_products(customer["id"], ADMIN)
    )
    assert meta["total_count"] == 0


def test_a_regulatory_admin_cannot_start_a_cycle():
    """PRD 2.1: "If the headers are well formed but the role is not among those
    authorised for the requested operation — the authorised roles for every
    operation are listed in the endpoint table of §4 — the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST   | `/sterilization/cycles/{id}/start`                        | Start the cycle.                                                                                                   | `CycleOperator`                                                                                |"

    Design: Corner/rbac/corner_regulatory_admin_cannot_start_a_cycle
    """
    env = build_cycle_scenario(stage="ready")

    response = api_client.start_cycle(env["cycle"]["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "READY"
    assert cycle["operator_user_id"] is None


def test_a_customer_rep_cannot_enumerate_the_customer_roster():
    """PRD 2.1: "If the headers are well formed but the role is not among those
    authorised for the requested operation — the authorised roles for every
    operation are listed in the endpoint table of §4 — the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| GET    | `/sterilization/customers`                                | List customers with pagination.                                                                                    | `RegulatoryAdmin`                                                                              |"
    PRD 4: "| GET    | `/sterilization/customers/{id}`                           | Read one customer.                                                                                                 | `RegulatoryAdmin`, `CustomerRep`, `QualityReleaseOfficer`                                      |"

    Design: Corner/rbac/corner_customer_rep_cannot_list_all_customers
    """
    set_clock("2026-08-10T00:00:00Z")
    customer = create_customer(account_code="ACME-01")
    create_customer(account_code="BETA-02")
    rep = make_customer_rep_headers(customer["id"])

    response = api_client.list_customers(rep)

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    own = validate_success(api_client.get_customer(customer["id"], rep))
    assert own["id"] == customer["id"]


def test_a_shared_cycle_read_is_open_to_every_authorised_role():
    """PRD 4: "| GET    | `/sterilization/cycles/{id}`                              | Read one cycle including its density, dose and emission ledger fields.                                             | `CycleOperator`, `DosimetryAnalyst`, `QualityReleaseOfficer`, `RegulatoryAdmin`                |"
    PRD 2.1: "If the headers are well formed but the role is not among those
    authorised for the requested operation — the authorised roles for every
    operation are listed in the endpoint table of §4 — the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_shared_reads_are_available_to_every_declared_role
    """
    env = build_cycle_scenario(stage="planned", qualify=False)

    as_operator = validate_success(api_client.get_cycle(env["cycle"]["id"], OPERATOR))
    as_analyst = validate_success(api_client.get_cycle(env["cycle"]["id"], ANALYST))
    as_officer = validate_success(api_client.get_cycle(env["cycle"]["id"], OFFICER))
    as_admin = validate_success(api_client.get_cycle(env["cycle"]["id"], ADMIN))

    for seen in (as_operator, as_analyst, as_officer, as_admin):
        assert seen["status"] == "PLANNED"
        assert seen["cycle_code"] == "C-001"
        assert seen["id"] == env["cycle"]["id"]
