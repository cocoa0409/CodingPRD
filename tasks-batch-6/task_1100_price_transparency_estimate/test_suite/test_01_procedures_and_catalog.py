"""Catalog CRUD, required-field validation, versioning and reverse-reach listing.

Every test translates exactly one non-stub corner-design instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_procedure,
    create_procedure_payload, create_payer_contract_payload,
    create_negotiated_rate_payload,
    TEST_USERS, NON_EXISTENT_UUID, fixtures,
)

PROVIDER = TEST_USERS["provider_staff_headers"]
PAYER = TEST_USERS["payer_analyst_headers"]


def test_create_procedure_success(api):
    """PRD §3.1: "Each procedure declares a `code_system` — one of `CPT`,
    `HCPCS`, or `DRG` — together with the `code` string itself." PRD §2.4: "The
    `version` begins at 1 on creation and increments by exactly 1 on every
    mutation that changes the resource."

    Design: Corner/entities/create_procedure_success
    """
    payload = create_procedure_payload(
        code_system="CPT", code="70450", setting="OUTPATIENT",
        gross_charge_cents=300000)
    data = validate_success(api.create_procedure(payload, PROVIDER), 201)
    assert_procedure(data)
    assert data["code_system"] == "CPT"
    assert data["code"] == "70450"
    assert data["gross_charge_cents"] == 300000
    assert data["version"] == 1


def test_procedure_default_is_shoppable_and_prior_auth(api):
    """PRD §3.1: "is_shoppable, which defaults to true and controls whether the
    procedure surfaces in shoppable comparison, and requires_prior_auth, which
    defaults to false."

    Design: Corner/entities/procedure_default_is_shoppable_applied
    """
    payload = create_procedure_payload()
    payload.pop("is_shoppable", None)
    payload.pop("requires_prior_auth", None)
    data = validate_success(api.create_procedure(payload, PROVIDER), 201)
    assert data["is_shoppable"] is True
    assert data["requires_prior_auth"] is False


def test_get_procedure_not_found(api):
    """PRD §2.7: "The first identifier that does not resolve to an existing
    resource stops the request with the not-found error specific to that
    resource type: ERR_PROCEDURE_NOT_FOUND ... returned with HTTP 404."

    Design: Corner/entities/get_procedure_not_found_returns_404
    """
    resp = api.get_procedure(NON_EXISTENT_UUID, PROVIDER)
    validate_error(resp, ApiErrorId.ERR_PROCEDURE_NOT_FOUND.value, 404)


def test_create_procedure_missing_gross_charge(api):
    """PRD §2.7: "Body well-formedness covers presence of required fields,
    correct types, legal enum values, and honored numeric ranges; a violation
    yields ERR_VALIDATION (HTTP 422)."

    Design: Corner/entities/create_procedure_missing_required_field_returns_validation
    """
    payload = create_procedure_payload()
    payload.pop("gross_charge_cents")
    resp = api.create_procedure(payload, PROVIDER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_activate_contract_increments_version(api):
    """PRD §3.2: "Activating the contract advances it from `DRAFT` to `ACTIVE`
    and increments the contract's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_contract_activate
    """
    contract = validate_success(
        api.create_payer_contract(create_payer_contract_payload(), PAYER), 201)
    assert contract["status"] == "DRAFT"
    assert contract["version"] == 1
    activated = validate_success(api.activate_payer_contract(contract["id"], PAYER), 200)
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2


def test_negotiated_rate_flat_without_amount(api):
    """PRD §3.2: "a `FLAT` rate carries a non-negative `flat_amount_cents`,
    while a `PERCENT` rate carries `percent_of_charge`, a fraction strictly
    greater than 0 and at most 1." PRD §2.7: "the wrong pairing is an
    `ERR_VALIDATION`."

    Design: Corner/validations/negotiated_rate_flat_without_amount_returns_validation
    """
    contract = validate_success(
        api.create_payer_contract(create_payer_contract_payload(), PAYER), 201)
    procedure = validate_success(
        api.create_procedure(create_procedure_payload(), PROVIDER), 201)
    payload = create_negotiated_rate_payload(
        contract["id"], procedure["id"], contract["version"],
        rate_type="FLAT")
    payload.pop("flat_amount_cents")
    resp = api.create_negotiated_rate(payload, PAYER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_list_rates_filter_by_procedure(api):
    """PRD §3.2: "Negotiated rates can be fetched individually and listed with
    optional filters on contract_id, procedure_id, and superseded."

    Design: Corner/endpoints/filtered_list_rates_by_procedure_reverse_reach
    """
    contract = validate_success(
        api.create_payer_contract(create_payer_contract_payload(), PAYER), 201)
    procedure = validate_success(
        api.create_procedure(create_procedure_payload(), PROVIDER), 201)
    fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], 200000,
                              expected_contract_version=contract["version"])
    resp = api.list_negotiated_rates(PAYER, params={"procedure_id": procedure["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["procedure_id"] == procedure["id"]
