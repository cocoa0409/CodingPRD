"""Registry onboarding: clinics, producers, drugs — creation defaults, uniqueness,
required fields, pagination envelope (PRD §2.3, §2.4, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    create_clinic_payload, create_producer_payload, create_drug_payload,
    assert_clinic, assert_drug, ApiErrorId,
    INITIAL_COMPLIANCE_SCORE,
)


def test_create_clinic_returns_computed_defaults(api, inspector_headers):
    """PRD §3.1: "At registration the clinic's `compliance_score` is set to 1000
    and its `audit_ready` flag to true."
    PRD §2.4: "a `version` integer that starts at 1 and increments on every mutation."

    Design: Corner/entities/create_clinic_returns_defaults
    """
    created = validate_success(api.create_clinic(
        create_clinic_payload(name="Clinic Default", license_number="LIC-D1"),
        inspector_headers,
    ), 201)
    assert_clinic(created)
    assert created["compliance_score"] == INITIAL_COMPLIANCE_SCORE
    assert created["audit_ready"] is True
    assert created["version"] == 1

    fetched = validate_success(api.get_clinic(created["id"], inspector_headers), 200)
    assert fetched["compliance_score"] == INITIAL_COMPLIANCE_SCORE
    assert fetched["audit_ready"] is True


def test_get_clinic_not_found_returns_404(api, inspector_headers):
    """PRD §2.4: "Referenced identifiers are validated left-to-right: the path's
    identifiers are checked first, then the body's, and the first missing reference
    yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_clinic_not_found_returns_404
    """
    res = api.get_clinic(NON_EXISTENT_UUID, inspector_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_list_producers_pagination_envelope(api, inspector_headers):
    """PRD §2.3: "`limit` controls the page size and defaults to 10; it must be
    at least 1 and may not exceed 100."
    PRD §2.3: "The `meta` block of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_producers_pagination_shape
    """
    for letter in ("A", "B", "C"):
        validate_success(api.create_producer(
            create_producer_payload(legal_name=f"P-{letter}", premise_id=f"PIN-{letter}"),
            inspector_headers,
        ), 201)

    data, meta = validate_paginated(
        api.list_producers(inspector_headers, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2, f"Expected page of 2, got {len(data)}"
    assert meta["total_count"] == 3, f"Expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_create_drug_pins_prohibited_extra_label(api, inspector_headers):
    """PRD §3.1: "Every VFD drug's `prohibited_extra_label` flag is pinned to true
    at registration and cannot be unset — extra-label use of a VFD drug is always
    prohibited under 21 CFR 530."

    Design: Corner/entities/create_drug_default_prohibited_extra_label
    """
    created = validate_success(api.create_drug(
        create_drug_payload(drug_code="DRUG-D1", withdrawal_hours=48),
        inspector_headers,
    ), 201)
    assert_drug(created)
    assert created["prohibited_extra_label"] is True

    fetched = validate_success(api.get_drug(created["id"], inspector_headers), 200)
    assert fetched["prohibited_extra_label"] is True


def test_duplicate_drug_code_rejected(api, inspector_headers):
    """PRD §3.1: "A duplicate `drug_code` is rejected with
    `ERR_DUPLICATE_DRUG_CODE` (HTTP 409)."

    Design: Corner/entities/duplicate_drug_code_rejected
    """
    validate_success(api.create_drug(
        create_drug_payload(drug_code="DRUG-DUP", label_name="First"),
        inspector_headers,
    ), 201)
    res = api.create_drug(
        create_drug_payload(
            drug_code="DRUG-DUP", label_name="Second", withdrawal_hours=48,
            allowed_species_classes=["SWINE:BREEDING"], max_duration_days=14,
        ),
        inspector_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_DRUG_CODE, expected_status=409)


def test_create_clinic_missing_license_number_rejected(api, inspector_headers):
    """PRD §3.1: "A `VeterinaryClinic` is registered with its legal `name`, its
    state-issued `license_number`, and its two-letter `state_code`; a duplicate
    `license_number` is rejected with `ERR_DUPLICATE_CLINIC_LICENSE` (HTTP 409)."
    PRD §3.5: "A missing `rejection_reason` is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)" — the PRD's missing-required-field convention.

    Design: Corner/entities/missing_required_field_rejected
    """
    payload = create_clinic_payload(name="No License", state_code="IA")
    payload.pop("license_number")
    res = api.create_clinic(payload, inspector_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
