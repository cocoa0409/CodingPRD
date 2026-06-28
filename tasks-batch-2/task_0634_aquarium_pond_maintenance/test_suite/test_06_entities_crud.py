"""Entity creation, required fields, defaults, computed fields, parent
existence, not-found, and the immutable WaterTest reading.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_field_tech_headers,
    create_started_visit,
    TEST_USERS,
)
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]


def test_create_contract_minimal_fields_returns_201_draft(api):
    """PRD §3.1: "A new contract starts in DRAFT ... Its account_balance_cents and
    alive_livestock_count both start at zero."
    PRD §2.4: "The version is an integer that begins at its initial value on
    creation".

    Design: Corner/entities/create_contract_minimal_required_fields_returns_201
    """
    resp = api.create_contract(
        f.create_contract_payload(customer_name="Acme", customer_user_id="owner-1",
                                  service_tier="BASIC", route_day="MON"),
        AM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"Expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"
    assert data["account_balance_cents"] == 0
    assert data["alive_livestock_count"] == 0


def test_create_contract_missing_service_tier_rejected(api):
    """PRD §3.1: "An AccountManager opens a contract by supplying the account
    holder's customer_name, the customer_user_id that anchors which CustomerOwner
    owns it, a service_tier of BASIC, PLUS, or PREMIUM, and a route_day".
    PRD §3.12: "generic request validation of required fields, enum domains, and
    numeric ranges (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_contract_missing_service_tier_returns_invalid_request
    """
    resp = api.create_contract(
        {"customer_name": "Acme", "customer_user_id": "owner-1", "route_day": "MON"},
        AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_contract_bad_service_tier_enum_rejected(api):
    """PRD §3.12: "generic request validation of required fields, enum domains, and
    numeric ranges (ERR_INVALID_REQUEST)".
    PRD §3.1: "a service_tier of BASIC, PLUS, or PREMIUM".

    Design: Corner/entities/create_contract_bad_service_tier_enum_returns_invalid_request
    """
    resp = api.create_contract(
        f.create_contract_payload(service_tier="GOLD"),
        AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_nonexistent_contract_returns_not_found(api):
    """PRD §2.6: "the system validates existence left-to-right, in path order
    first and then body order, rejecting on the first identifier that does not
    resolve to an existing record with ERR_NOT_FOUND."

    Design: Corner/entities/get_contract_nonexistent_returns_not_found
    """
    resp = api.get_contract(NON_EXISTENT_UUID, AM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_system_defaults_substrate_displacement_zero(api):
    """PRD §3.1: "an optional substrate_displacement_pct that is at least zero and
    strictly less than one, defaulting to 0.0. A system enters in PROVISIONING".
    PRD §2.9: a system with no livestock has bioload 0.0 and NORMAL posture.

    Design: Corner/entities/create_system_default_substrate_displacement_zero
    """
    contract = validate_success(api.create_contract(f.create_contract_payload(), AM),
                                expected_status=201)
    resp = api.create_system(
        f.create_system_payload(contract["id"], label="Tank",
                                system_kind="FRESHWATER", nominal_volume_l=200),
        AM)
    data = validate_success(resp, expected_status=201)
    assert data["substrate_displacement_pct"] == 0.0
    assert data["status"] == "PROVISIONING"
    assert data["bioload_index"] == 0.0
    assert data["stocking_posture"] == "NORMAL"


def test_system_computed_fields_default_with_no_livestock(api):
    """PRD §2.9: "Each SystemProfile continuously reflects how heavily it is
    stocked through a derived bioload_index carried to two decimal places and a
    derived stocking_posture. ... The stocking_posture is OVERSTOCKED when
    bioload_index is strictly greater than 100.0 and NORMAL otherwise".

    A freshly created system with no ALIVE livestock is bioload 0.0 / NORMAL,
    regardless of any client-supplied body values for the computed fields.

    Design: Corner/entities/system_computed_fields_ignore_client_input
    """
    contract = validate_success(api.create_contract(f.create_contract_payload(), AM),
                                expected_status=201)
    resp = api.create_system(
        {"contract_id": contract["id"], "label": "Tank", "system_kind": "REEF",
         "nominal_volume_l": 500, "substrate_displacement_pct": 0.2},
        AM)
    data = validate_success(resp, expected_status=201)
    assert data["bioload_index"] == 0.0
    assert data["stocking_posture"] == "NORMAL"


def test_create_system_under_nonexistent_contract_not_found(api):
    """PRD §2.6: "For any request whose path or body references other resources,
    the system validates existence left-to-right ... rejecting on the first
    identifier that does not resolve to an existing record with ERR_NOT_FOUND."

    Design: Corner/entities/system_create_nonexistent_contract_returns_not_found
    """
    resp = api.create_system(
        {"contract_id": NON_EXISTENT_UUID, "label": "T",
         "system_kind": "FRESHWATER", "nominal_volume_l": 200},
        AM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_water_test_is_immutable_with_no_version_field(api):
    """PRD §2.4: "a WaterTest is an immutable reading and carries only id and
    created_at. It has no updated_at and no version, because a logged measurement
    is never modified after the fact."

    Design: Corner/entities/watertest_immutable_entity_no_version_field
    """
    base = create_started_visit(service_tier="BASIC", tech_user_id="tech-1",
                                nominal_volume_l=200,
                                scheduled_start="2026-02-20T09:00:00Z",
                                scheduled_end="2026-02-20T10:00:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    resp = api.create_water_test(
        base["visit"]["id"],
        f.create_water_test_payload(parameter="PH", measured_value=7.0,
                                    target_value=8.0, product_strength_ppm_per_ml=50),
        tech_headers)
    data = validate_success(resp, expected_status=201)
    assert "id" in data and data["id"]
    assert "version" not in data, "WaterTest must not carry a version field"
    assert "updated_at" not in data, "WaterTest must not carry an updated_at field"
