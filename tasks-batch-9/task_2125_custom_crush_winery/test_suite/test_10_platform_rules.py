"""System-wide contracts: authentication, the evaluation ladder, uniqueness,
pagination, client scoping and resource versioning."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    ApiErrorId,
    build_user_headers,
    create_bottling_line_payload,
    create_client_payload,
    create_contract_payload,
    create_harvest_intake_payload,
    create_vessel_payload,
    make_client_rep_headers,
    new_bottling_line,
    new_client,
    new_contract,
    new_vessel,
    read_vessel_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_or_unknown_auth_headers_are_unauthenticated(api, facility_admin_headers):
    """PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which that
    user acts. If either header is missing or empty, the request is rejected
    with `ERR_UNAUTHENTICATED` (401). The same rejection applies when
    `X-User-Role` carries a value that is not one of the four roles the facility
    recognises: `FacilityAdmin`, `CellarSupervisor`, `ComplianceOfficer`, and
    `ClientRep`."

    Design: Corner/errors/corner_missing_x_user_headers_returns_unauthenticated
    """
    client = new_client()

    anonymous = api.get_client(client["id"], NO_AUTH_HEADERS)
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    sommelier = api.get_client(
        client["id"], build_user_headers("someone", "Sommelier")
    )
    validate_error(sommelier, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_every_collection_answers_its_own_not_found_code(
    api, facility_admin_headers, compliance_officer_headers
):
    """PRD 2.10: "Each collection has its own not-found code, so a missing
    allocation reports `ERR_ALLOCATION_NOT_FOUND` while a missing lot reports
    `ERR_LOT_NOT_FOUND`, and the same codes are reused when the identifier
    arrives in the body rather than the path."

    Design: Corner/errors/corner_path_id_sweep_returns_entity_specific_not_found
    """
    set_clock("2026-08-01T00:00:00Z")

    admin_probes = [
        (api.get_vessel, ApiErrorId.ERR_VESSEL_NOT_FOUND),
        (api.get_vessel_allocation, ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api.get_harvest_intake, ApiErrorId.ERR_INTAKE_NOT_FOUND),
        (api.get_blend_trial, ApiErrorId.ERR_TRIAL_NOT_FOUND),
        (api.get_work_order, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
        (api.get_bottling_line, ApiErrorId.ERR_LINE_NOT_FOUND),
        (api.get_bottling_run, ApiErrorId.ERR_RUN_NOT_FOUND),
        (api.get_dry_goods_item, ApiErrorId.ERR_DRY_GOODS_ITEM_NOT_FOUND),
        (api.get_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
    ]
    for reader, expected in admin_probes:
        response = reader(NON_EXISTENT_UUID, facility_admin_headers)
        validate_error(response, expected.value, 404)

    officer_probes = [
        (api.get_ttb_report, ApiErrorId.ERR_TTB_REPORT_NOT_FOUND),
        (api.get_release_order, ApiErrorId.ERR_RELEASE_ORDER_NOT_FOUND),
    ]
    for reader, expected in officer_probes:
        response = reader(NON_EXISTENT_UUID, compliance_officer_headers)
        validate_error(response, expected.value, 404)


def test_each_uniqueness_constraint_raises_its_own_conflict(api, facility_admin_headers):
    """PRD 2.5: "`ttb_permit_number`, `vessel_code`, `line_code` and
    `delivery_ticket` are each unique across all stored rows of their type,
    failing with `ERR_DUPLICATE_PERMIT_NUMBER`, `ERR_DUPLICATE_VESSEL_CODE`,
    `ERR_DUPLICATE_LINE_CODE` and `ERR_DUPLICATE_DELIVERY_TICKET` respectively;
    and a new reporting window must not overlap another `TTBReport` for the same
    client in status `OPEN`, `PREPARED`, `FILED` or `AMENDED`, failing with
    `ERR_TTB_PERIOD_OVERLAP`."

    Design: Corner/errors/corner_duplicate_code_sweep_rejected
    """
    new_client()
    new_vessel()
    new_bottling_line()

    permit_clash = api.create_client(
        create_client_payload(name="Impostor Cellars", contact_email="x@x.example"),
        facility_admin_headers,
    )
    validate_error(permit_clash, ApiErrorId.ERR_DUPLICATE_PERMIT_NUMBER.value, 409)

    vessel_clash = api.create_vessel(
        create_vessel_payload(
            vessel_type="BARREL", capacity_gallons=60, facility_zone="BARREL_HALL"
        ),
        facility_admin_headers,
    )
    validate_error(vessel_clash, ApiErrorId.ERR_DUPLICATE_VESSEL_CODE.value, 409)

    line_clash = api.create_bottling_line(
        create_bottling_line_payload(cases_per_hour=90, changeover_minutes=30),
        facility_admin_headers,
    )
    validate_error(line_clash, ApiErrorId.ERR_DUPLICATE_LINE_CODE.value, 409)

    _, clients_meta = validate_paginated(api.list_clients(facility_admin_headers))
    assert clients_meta["total_count"] == 1
    _, vessels_meta = validate_paginated(api.list_vessels(facility_admin_headers))
    assert vessels_meta["total_count"] == 1
    _, lines_meta = validate_paginated(api.list_bottling_lines(facility_admin_headers))
    assert lines_meta["total_count"] == 1


def test_pagination_limit_above_one_hundred_is_a_malformed_request(
    api, facility_admin_headers
):
    """PRD 2.3: "A `limit` outside the 1-to-100 band or a negative `offset` is a
    malformed request and is rejected with `ERR_INVALID_REQUEST` (400)."
    PRD 2.3: "The `offset` parameter is the number of records to skip and
    defaults to 0; it may not be negative."

    Design: Corner/endpoints/corner_pagination_limit_above_max_returns_invalid_request
    """
    new_client()

    response = api.list_clients(facility_admin_headers, params={"limit": 101})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_clients(facility_admin_headers, params={"limit": 100})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    _, defaults = validate_paginated(api.list_clients(facility_admin_headers))
    assert defaults["limit"] == 10
    assert defaults["offset"] == 0


def test_request_shape_outranks_body_foreign_key_existence(api, cellar_supervisor_headers):
    """PRD 2.5: "Requests are validated in a strictly ordered ladder, and the
    **first** rung that fails decides the response."
    PRD 2.5: "The body must carry every required field for the endpoint; each
    field must have its declared type; every enum-valued field must carry a
    declared member; every numeric constraint must hold, including the "greater
    than zero", "at least zero", bounded-range and decimal-place constraints
    stated per field in §3; and the pagination `limit` must lie between 1 and
    100 with `offset` at least 0."

    Design: Corner/validations/corner_schema_outranks_existence_invalid_enum_with_unknown_contract
    """
    set_clock("2026-09-01T00:00:00Z", cellar_supervisor_headers)

    response = api.create_harvest_intake(
        create_harvest_intake_payload(
            NON_EXISTENT_UUID,
            delivery_ticket="DT-N1",
            varietal="SYRAH",
            gross_weight_lbs=14000,
            tare_weight_lbs=4000,
        ),
        cellar_supervisor_headers,
    )

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert error["error_id"] != ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, (
        "the request-shape rung sits above body foreign-key existence"
    )


def test_endpoint_authorization_outranks_request_shape(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 2.5: "**Endpoint and action authorization** (rung 3, all endpoints).
    The caller's role must be authorized for the endpoint and, on
    action-multiplexing endpoints, must equal the actor declared for the
    requested `action`; otherwise `ERR_FORBIDDEN_ROLE` (403)."
    PRD 2.5: "Two rungs are never both reported: if a caller sends an
    unauthorized role together with a malformed body and a non-existent path id,
    the role rejection wins, because it sits higher on the ladder."

    Design: Corner/validations/corner_authorization_outranks_schema_forbidden_role_with_bad_payload
    """
    set_clock("2026-09-01T00:00:00Z", cellar_supervisor_headers)
    payload = create_client_payload()
    payload.pop("contact_email")

    response = api.create_client(payload, cellar_supervisor_headers)

    error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    rows, meta = validate_paginated(api.list_clients(facility_admin_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_cellar_supervisor_may_not_create_contracts(api, cellar_supervisor_headers,
                                                      facility_admin_headers):
    """PRD 2.1: "First, the caller's role must appear in the authorized-role
    list published for the target endpoint in §4; a caller whose role is absent
    from that list is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD 3.1: "A `FacilityAdmin` creates one against a `client_id` with a
    `harvest_year` between 2020 and 2035 inclusive, the `committed_tons` the
    client undertakes to deliver (greater than zero), and the cooperage
    envelope: `tank_gallons_entitled` (greater than zero) caps the aggregate
    gallons the client may hold in tanks at one time, and
    `barrel_slots_entitled` (zero or more) caps the number of barrels the client
    may occupy at one time."

    Design: Corner/rbac/corner_cellar_supervisor_cannot_create_contracts
    """
    client = new_client()

    response = api.create_contract(
        create_contract_payload(client["id"]), cellar_supervisor_headers
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    rows, meta = validate_paginated(
        api.list_contracts(facility_admin_headers, params={"client_id": client["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_a_client_rep_may_not_read_another_clients_contract(api, facility_admin_headers):
    """PRD 2.1: "When `X-User-Role` is `ClientRep`, `X-User-ID` is the `id` of
    the acting `Client`. Ownership checks on any resource that resolves back to
    a client compare that resolution to `X-User-ID`, and a mismatch is rejected
    with `ERR_CLIENT_SCOPE_VIOLATION` (403)."
    PRD 2.5: "**Client scoping** (rung 20, every endpoint on which `ClientRep`
    is an authorized role). A `ClientRep` whose `X-User-ID` does not resolve to
    the owning client of the target resource is rejected with
    `ERR_CLIENT_SCOPE_VIOLATION` (403)."

    Design: Corner/rbac/corner_client_rep_cannot_read_another_clients_contract
    """
    client_a = new_client(name="Coombsville Cellars", ttb_permit_number="BW-CA-15001",
                          contact_email="a@x.example")
    client_b = new_client(name="Pritchard Hill Partners", ttb_permit_number="BW-CA-15002",
                          contact_email="b@x.example")
    contract_b = new_contract(client_b["id"])

    response = api.get_contract(contract_b["id"], make_client_rep_headers(client_a["id"]))
    validate_error(response, ApiErrorId.ERR_CLIENT_SCOPE_VIOLATION.value, 403)

    rows, _ = validate_paginated(
        api.list_contracts(facility_admin_headers, params={"client_id": client_b["id"]})
    )
    assert [row["id"] for row in rows] == [contract_b["id"]], (
        "the FacilityAdmin still reads the contract the ClientRep could not"
    )

    own = validate_success(
        api.get_contract(contract_b["id"], make_client_rep_headers(client_b["id"]))
    )
    assert own["id"] == contract_b["id"], "the owning ClientRep reads its own contract"


def test_version_starts_at_one_and_advances_once_per_mutation(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 2.4: "`version` (integer): a counter that starts at 1 when the
    resource is created and increases by exactly 1 on every mutation."
    PRD 2.8: "The rule is that every touched resource is a full mutation: its
    `updated_at` is refreshed and its `version` increases by 1, even when the
    client never named it in the request."
    PRD 3.2: "It recomputes the contract's `gallons_allocated` (the total
    `allocated_gallons` over that contract's `RESERVED` and `COMMITTED`
    allocations pointing at `TANK` vessels) and `barrel_slots_used` (the count
    of that contract's `RESERVED` and `COMMITTED` allocations pointing at
    `BARREL` vessels), incrementing the contract's `version`, and it increments
    the vessel's `version` as well."

    Design: Corner/cross_cutting_layers/corner_version_increments_on_every_mutation_across_entities
    """
    set_clock("2026-09-01T00:00:00Z")
    client = new_client()

    contract = validate_success(
        api.create_contract(create_contract_payload(client["id"]), facility_admin_headers),
        201,
    )
    assert contract["version"] == 1

    submitted = validate_success(
        api.contract_transition(contract["id"], {"action": "SUBMIT"}, facility_admin_headers)
    )
    assert submitted["version"] == 2
    activated = validate_success(
        api.contract_transition(contract["id"], {"action": "ACTIVATE"}, facility_admin_headers)
    )
    assert activated["version"] == 3

    vessel = new_vessel()
    assert vessel["version"] == 1

    allocation = validate_success(
        api.create_vessel_allocation(
            {
                "contract_id": contract["id"],
                "vessel_id": vessel["id"],
                "start_at": "2026-09-01T00:00:00Z",
                "end_at": "2026-11-01T00:00:00Z",
                "allocated_gallons": 2000,
                "expected_vessel_version": vessel["version"],
            },
            cellar_supervisor_headers,
        ),
        201,
    )
    assert allocation["version"] == 1, "a brand-new allocation opens at version 1"

    assert read_vessel_version(vessel["id"]) == 2, "the reserve advanced the vessel"

    after = validate_success(api.get_contract(contract["id"], facility_admin_headers))
    assert after["version"] == 4, (
        f"the reserve's counter recompute advanced the contract, got {after['version']}"
    )

    stored_client = validate_success(api.get_client(client["id"], facility_admin_headers))
    assert stored_client["version"] == 1, "the client was untouched by any of these calls"
