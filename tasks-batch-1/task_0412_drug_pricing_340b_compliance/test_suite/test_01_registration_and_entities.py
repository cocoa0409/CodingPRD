"""Covered-entity registration, sub-resource creation, identity/computed fields, and
the structural validations around them.

Design sources: Corner/entities/*, Corner/validations/mef_number_required_for_carve_in_ce,
and the duplicate-key constraints from Corner/entities.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_covered_entity_payload, create_drug_product_payload,
    create_accumulator_payload, create_prescriber_payload,
    create_and_approve_covered_entity, create_drug_product,
    assert_covered_entity, assert_prescriber,
    NON_EXISTENT_UUID,
)

CO = TEST_USERS["compliance_officer_headers"]
HRSA = TEST_USERS["hrsa_auditor_headers"]
PHARM = TEST_USERS["pharmacy_operator_headers"]


def test_create_covered_entity_returns_pending_good(api):
    """PRD §3.1: "Every newly registered entity begins with `registration_status` of
    `PENDING`, `recert_period_index` of 0, `compliance_posture` of `GOOD`, and
    `open_repayment_cents` of 0."

    Design: Corner/entities/create_covered_entity_minimal_required_fields_201
    """
    resp = api.create_covered_entity(
        create_covered_entity_payload(legal_name="Create CE", entity_type="FQHC"), CO,
    )
    data = validate_success(resp, expected_status=201)
    assert_covered_entity(data)
    assert data["registration_status"] == "PENDING"
    assert data["compliance_posture"] == "GOOD"
    assert data["recert_period_index"] == 0
    assert data["open_repayment_cents"] == 0


def test_create_covered_entity_missing_entity_type_rejected(api):
    """PRD §2.6: "then request-shape validity — required fields present, correct types,
    enum members drawn from their declared sets, and integer fields meeting their lower
    bounds (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/covered_entity_missing_required_entity_type_invalid_request
    """
    payload = create_covered_entity_payload(legal_name="No Type CE")
    payload.pop("entity_type")
    resp = api.create_covered_entity(payload, CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_gpo_prohibited_computed_from_entity_type(api):
    """PRD §3.1: "it is set `true` exactly when the `entity_type` is one of `DSH`,
    `CHILDRENS_HOSPITAL`, or `FREESTANDING_CANCER`, and `false` otherwise. This computed
    flag is never overwritten by any input the client supplies."

    Design: Corner/entities/covered_entity_gpo_prohibited_computed_from_entity_type
    """
    dsh = validate_success(
        api.create_covered_entity(
            create_covered_entity_payload(legal_name="DSH CE", entity_type="DSH"), CO), 201)
    fqhc = validate_success(
        api.create_covered_entity(
            create_covered_entity_payload(legal_name="FQHC CE", entity_type="FQHC"), CO), 201)
    assert dsh["gpo_prohibited"] is True
    assert fqhc["gpo_prohibited"] is False


def test_medicaid_mode_defaults_to_carve_out(api):
    """PRD §3.1: "The registration payload also accepts `medicaid_billing_mode`, one of
    `CARVE_IN` or `CARVE_OUT`, defaulting to `CARVE_OUT` when omitted."

    Design: Corner/entities/covered_entity_medicaid_mode_default_carve_out
    """
    payload = create_covered_entity_payload(legal_name="Default Mode CE", entity_type="FQHC")
    payload.pop("medicaid_billing_mode")
    data = validate_success(api.create_covered_entity(payload, CO), 201)
    assert data["medicaid_billing_mode"] == "CARVE_OUT"


def test_covered_entity_version_starts_at_one_status_system_set(api):
    """PRD §2.4: "an integer `version` that begins at 1 and increments by one on each
    mutation."
    PRD §3.1: "Every newly registered entity begins with `registration_status` of
    `PENDING`, `recert_period_index` of 0, `compliance_posture` of `GOOD`, and
    `open_repayment_cents` of 0."

    Design: Corner/entities/covered_entity_system_id_created_at_generated
    """
    data = validate_success(
        api.create_covered_entity(
            create_covered_entity_payload(legal_name="Sys Fields CE", entity_type="FQHC"), CO), 201)
    assert data["version"] == 1
    assert data["registration_status"] == "PENDING"


def test_covered_entity_invalid_enum_entity_type_rejected(api):
    """PRD §2.6: "then request-shape validity — required fields present, correct types,
    enum members drawn from their declared sets, and integer fields meeting their lower
    bounds (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/covered_entity_invalid_enum_entity_type_rejected
    """
    resp = api.create_covered_entity(
        create_covered_entity_payload(legal_name="Bad Enum CE", entity_type="NOT_A_TYPE"), CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_get_covered_entity_not_found(api):
    """PRD §2.5: "the system validates the identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve
    to an existing resource."

    Design: Corner/entities/get_covered_entity_not_found
    """
    resp = api.get_covered_entity(NON_EXISTENT_UUID, CO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_list_covered_entities_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_covered_entities_pagination_envelope
    """
    api.create_covered_entity(
        create_covered_entity_payload(legal_name="List CE 1", entity_type="FQHC"), CO)
    api.create_covered_entity(
        create_covered_entity_payload(legal_name="List CE 2", entity_type="FQHC"), CO)
    resp = api.list_covered_entities(HRSA)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2
    assert isinstance(meta["has_more"], bool)


def test_duplicate_hrsa_id_rejected(api):
    """PRD §3.1: "its `hrsa_id` (the HRSA-assigned grant or registration identifier,
    which must be non-empty and unique across all covered entities — a collision is
    rejected with `ERR_DUPLICATE_HRSA_ID`)".

    Design: Corner/entities/duplicate_hrsa_id_rejected
    """
    payload = create_covered_entity_payload(hrsa_id="DSH-DUP-1", legal_name="Dup A", entity_type="FQHC")
    validate_success(api.create_covered_entity(payload, CO), 201)
    payload2 = create_covered_entity_payload(hrsa_id="DSH-DUP-1", legal_name="Dup B", entity_type="FQHC")
    resp = api.create_covered_entity(payload2, CO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_HRSA_ID.value, expected_status=409)


def test_duplicate_ndc_rejected(api):
    """PRD §3.3: "an `ndc` (the 11-digit National Drug Code, which must be non-empty and
    unique across all drug products — a collision is rejected with `ERR_DUPLICATE_NDC`)".

    Design: Corner/entities/duplicate_ndc_rejected
    """
    p1 = create_drug_product_payload(ndc="00021-0021-21", drug_name="Dup NDC A")
    validate_success(api.create_drug_product(p1, CO), 201)
    p2 = create_drug_product_payload(ndc="00021-0021-21", drug_name="Dup NDC B")
    resp = api.create_drug_product(p2, CO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_NDC.value, expected_status=409)


def test_duplicate_accumulator_for_ce_ndc_pair_rejected(api):
    """PRD §3.6: "each entity may hold at most one accumulator per drug product, so a
    second accumulator for an existing `(covered_entity_id, drug_product_id)` pair is
    rejected with `ERR_DUPLICATE_ACCUMULATOR` (HTTP 409)."

    Design: Corner/entities/duplicate_accumulator_for_ce_ndc_pair_rejected
    """
    ce = create_and_approve_covered_entity()
    drug = create_drug_product()
    validate_success(
        api.create_accumulator(ce["id"], create_accumulator_payload(drug["id"]), CO), 201)
    resp = api.create_accumulator(ce["id"], create_accumulator_payload(drug["id"]), CO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCUMULATOR.value, expected_status=409)


def test_child_site_under_missing_ce_not_found(api):
    """PRD §2.5: "the system validates the identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve
    to an existing resource."

    Design: Corner/entities/child_site_wrong_parent_not_found
    """
    resp = api.create_child_site(
        NON_EXISTENT_UUID,
        {"site_name": "Orphan Site", "service_address": "1 Main St"}, CO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_prescriber_is_immutable_no_version_field(api):
    """PRD §2.4: "One entity is the exception: the **prescriber** record carries only
    `id` and `created_at`. A prescriber has no `updated_at` and no `version`; it is
    effectively immutable after creation."

    Design: Corner/entities/prescriber_immutable_entity_no_version_field
    """
    ce = create_and_approve_covered_entity()
    data = validate_success(
        api.create_prescriber(
            ce["id"], create_prescriber_payload(full_name="Dr Immutable"), CO), 201)
    assert_prescriber(data)
    assert "version" not in data, "prescriber carries no version (common_fields:false)"
    assert "updated_at" not in data, "prescriber carries no updated_at (common_fields:false)"


def test_mef_number_required_for_carve_in_ce(api):
    """PRD §3.1: "A `CARVE_IN` registration submitted without a `medicaid_provider_number`
    is rejected with `ERR_MEF_NUMBER_REQUIRED` (HTTP 422)".

    Design: Corner/validations/mef_number_required_for_carve_in_ce
    """
    payload = create_covered_entity_payload(
        legal_name="CarveIn CE", entity_type="FQHC", medicaid_billing_mode="CARVE_IN")
    payload.pop("medicaid_provider_number", None)
    resp = api.create_covered_entity(payload, CO)
    validate_error(resp, ApiErrorId.ERR_MEF_NUMBER_REQUIRED.value, expected_status=422)


def test_child_site_defaults_registered_false(api):
    """PRD §3.2: "A child site carries a `registered` boolean — `true` only once the site
    is listed in the 340B OPAIS database — which defaults to `false` and may be supplied
    at creation."

    Design: Corner/endpoints/child_site_default_registered_false
    """
    ce = create_and_approve_covered_entity()
    data = validate_success(
        api.create_child_site(
            ce["id"], {"site_name": "Default Site", "service_address": "2 Oak Ave"}, CO), 201)
    assert data["registered"] is False
