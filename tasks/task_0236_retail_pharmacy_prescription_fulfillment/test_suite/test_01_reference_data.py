"""Reference-data CRUD, creation defaults, computed fields, uniqueness, lookups.

Translations of SCAFFOLD_CORNER_DESIGN.yaml §1.9 `entities` and `errors`
(uniqueness) instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    assert_drug_product, assert_patient,
    create_drug_product_payload, create_insurance_plan_payload,
    create_prescriber_payload, create_prescription_payload,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
PHARM = TEST_USERS["pharmacist_headers"]


def test_create_drug_product_returns_201_with_system_fields(api):
    """PRD §3.1: "On creation the drug's `status` is `ACTIVE` and its computed
    `is_active` flag is true."
    PRD §2.4: "an integer `version` that begins at 1 and increments by one on
    every mutation of that resource."

    Design: Corner/entities/create_drug_product_returns_201_with_system_fields
    """
    fx.set_clock()
    resp = api.create_drug_product(
        create_drug_product_payload(ndc="11111-1111-11", name="Aspirin", unit_price_cents=200),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_drug_product(data)
    assert data["status"] == "ACTIVE"
    assert data["is_active"] is True
    assert data["version"] == 1


def test_get_nonexistent_drug_returns_not_found(api):
    """PRD §2.7: "if a path `id` does not resolve to an existing resource, the
    request fails immediately with `ERR_NOT_FOUND` (HTTP 404) before any body
    validation runs."

    Design: Corner/entities/get_nonexistent_drug_returns_not_found
    """
    fx.set_clock()
    resp = api.get_drug_product(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_prescription_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "generic body-schema validation — malformed body, missing
    required field, illegal enum value, or out-of-range numeric — which is
    reported as `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "the `quantity_per_fill` (a positive number of dispensing units),
    the `days_supply` each fill is expected to last (positive)".

    Design: Corner/entities/create_prescription_missing_required_field_returns_invalid_request
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="22222-2222-22", name="DrugX", unit_price_cents=300)
    patient = fx.create_patient(full_name="P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr X", npi="2000000001")
    # Omit days_supply (a required positive field).
    payload = {
        "patient_id": patient["id"],
        "prescriber_id": prescriber["id"],
        "drug_id": drug["id"],
        "quantity_per_fill": 30,
        "written_utc": "2026-01-01T00:00:00.000Z",
    }
    resp = api.create_prescription(payload, TECH)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_patient_defaults_applied(api):
    """PRD §3.2: "an optional `allergy_classes` array ... (defaulting to an empty
    list) ... an optional `auto_refill_enrolled` flag (defaulting to false) ...
    At registration the patient's computed `pdmp_flag` is `CLEAR` and the
    parallel `controlled_status` is `ELIGIBLE`."

    Design: Corner/entities/create_patient_defaults_applied
    """
    fx.set_clock()
    resp = api.create_patient(
        {"full_name": "Defaulter", "date_of_birth": "1990-01-01"}, TECH
    )
    data = validate_success(resp, expected_status=201)
    assert_patient(data)
    assert data["auto_refill_enrolled"] is False
    assert data["allergy_classes"] == []
    assert data["pdmp_flag"] == "CLEAR"
    assert data["controlled_status"] == "ELIGIBLE"


def test_prescription_expires_utc_computed_180_for_controlled(api):
    """PRD §3.3: "a non-controlled drug expires 365 days after `written_utc`,
    while a controlled drug (any schedule from `CII` through `CV`) expires 180
    days after `written_utc`."

    Design: Corner/entities/prescription_expires_utc_computed_180_for_controlled
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="33333-3333-33", name="CtrlDrug",
                          dea_schedule="CII", unit_price_cents=1000)
    patient = fx.create_patient(full_name="P2", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Y", npi="2000000002",
                                      dea_number="BY1234567", dea_active=True)
    resp = api.create_prescription(
        create_prescription_payload(patient["id"], prescriber["id"], drug["id"],
                                    quantity_per_fill=10, days_supply=30,
                                    written_utc="2026-01-01T00:00:00.000Z"),
        TECH,
    )
    data = validate_success(resp, expected_status=201)
    assert data["expires_utc"] == "2026-06-30T00:00:00.000Z", \
        f"CII expiry must be +180d, got {data['expires_utc']}"


def test_create_drug_system_fields_ignore_client_input(api):
    """PRD §3.1: "On creation the drug's `status` is `ACTIVE` and its computed
    `is_active` flag is true."

    Design: Corner/entities/create_drug_system_fields_ignore_client_input
    """
    fx.set_clock()
    resp = api.create_drug_product(
        create_drug_product_payload(ndc="44444-4444-44", name="SysFieldDrug",
                                    unit_price_cents=100),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["is_active"] is True


def test_duplicate_ndc_rejected(api):
    """PRD §2.10: "A drug product's `ndc` must not duplicate an existing drug; a
    collision is rejected with `ERR_DUPLICATE_NDC` (HTTP 409)."

    Design: Corner/entities/duplicate_ndc_rejected
    """
    fx.set_clock()
    fx.create_drug(ndc="55555-5555-55", name="Dup1", unit_price_cents=100)
    resp = api.create_drug_product(
        create_drug_product_payload(ndc="55555-5555-55", name="Dup2",
                                    unit_price_cents=200),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_NDC.value)


def test_self_referential_substitute_link_filter(api):
    """PRD §3.1: "The drug list may be filtered by `therapeutic_substitute_of_id`
    to find all generics linked to a given brand."

    Design: Corner/entities/self_referential_substitute_link_filter
    """
    fx.set_clock()
    brand = fx.create_drug(ndc="66666-6666-66", name="Brand", unit_price_cents=5000)
    generic = fx.create_drug(ndc="66666-6666-67", name="Generic", unit_price_cents=500,
                             therapeutic_substitute_of_id=brand["id"])
    resp = api.list_drug_products(PHARM, params={"therapeutic_substitute_of_id": brand["id"]})
    items, _meta = validate_paginated(resp)
    ids = [d["id"] for d in items]
    assert generic["id"] in ids, "generic linked to brand must appear"
    assert brand["id"] not in ids, "brand itself must be excluded from the filter"


def test_reference_not_found_on_prescription_bad_drug(api):
    """PRD §2.7: "Body fields that reference other resources — `patient_id`,
    `prescriber_id`, `drug_id`, `plan_id`, and `fill_id` on the creating
    endpoints — are validated next; a reference to a non-existent resource is
    rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/reference_not_found_on_prescription_bad_drug
    """
    fx.set_clock()
    patient = fx.create_patient(full_name="P3", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Z", npi="2000000003")
    resp = api.create_prescription(
        create_prescription_payload(patient["id"], prescriber["id"], NON_EXISTENT_UUID,
                                    quantity_per_fill=10, days_supply=30,
                                    written_utc="2026-01-01T00:00:00.000Z"),
        TECH,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_list_patients_pagination_envelope(api):
    """PRD §2.3: "Every list response surfaces `limit`, `offset`, `total_count`,
    and `has_more` inside the envelope's `meta` object, where `total_count` is
    the count of all matching records before pagination and `has_more` is true
    when records remain beyond the current page."

    Design: Corner/entities/list_patients_pagination_envelope
    """
    fx.set_clock()
    fx.create_patient(full_name="PA", date_of_birth="1980-01-01")
    fx.create_patient(full_name="PB", date_of_birth="1981-01-01")
    resp = api.list_patients(PHARM, params={"limit": 1, "offset": 0})
    items, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(items) == 1


def test_duplicate_plan_routing_rejected(api):
    """PRD §2.10: "An insurance plan's routing pair, the combination of `bin` and
    `pcn`, must be unique; a collision is rejected with
    `ERR_DUPLICATE_PLAN_ROUTING` (HTTP 409)."

    Design: Corner/errors/duplicate_plan_routing_rejected
    """
    fx.set_clock()
    fx.create_plan(bin="800001", pcn="ZZ", name="Dup Plan 1",
                   copay_pct=0.10, copay_max_cents=10000)
    resp = api.create_insurance_plan(
        create_insurance_plan_payload(bin="800001", pcn="ZZ", name="Dup Plan 2",
                                      copay_pct=0.20, copay_max_cents=5000),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PLAN_ROUTING.value)


def test_duplicate_npi_rejected(api):
    """PRD §2.10: "A prescriber's `npi` must be unique; a collision is rejected
    with `ERR_DUPLICATE_NPI` (HTTP 409)."

    Design: Corner/errors/duplicate_npi_rejected
    """
    fx.set_clock()
    fx.create_prescriber(full_name="Dr Dup1", npi="2000000099")
    resp = api.create_prescriber(
        create_prescriber_payload(full_name="Dr Dup2", npi="2000000099"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_NPI.value)
