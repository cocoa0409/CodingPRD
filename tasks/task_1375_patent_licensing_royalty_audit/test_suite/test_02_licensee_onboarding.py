"""Licensee onboarding: required fields, tax_id uniqueness, strict schema,
404s, standing gate, and cross-licensee read ownership (PRD sections 2.1, 2.8,
3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_active_agreement,
    create_licensee,
    create_licensee_payload,
    create_royalty_report_payload,
    make_licensee_headers,
    make_report_line,
    suspend_licensee,
    validate_error,
    validate_success,
)


def test_create_licensee_missing_required_field(api, analyst_headers):
    """PRD section 3.1: "A `LicensingAnalyst` registers each contracting
    company as a **Licensee**, supplying its `legal_name`, `tax_id`, and
    `contact_email`." PRD section 2.8 tier 5: "Required fields must be present,
    types must be valid, enum values must be members of their declared sets, no
    undeclared fields may appear ... Failures yield `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_licensee_missing_required_field
    """
    resp = api.create_licensee(
        {"tax_id": "TAX-NOF-1", "contact_email": "x@x.test"}, analyst_headers
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_licensee_duplicate_tax_id(api, analyst_headers):
    """PRD section 3.1: "The tax identifier is unique across all licensees: a
    registration attempt reusing an existing `tax_id` is rejected with
    `ERR_DUPLICATE_TAX_ID` (HTTP 409)."

    Design: Corner/entities/create_licensee_duplicate_tax_id
    """
    first = create_licensee(legal_name="First Co")
    resp = api.create_licensee(
        {"legal_name": "Second Co", "tax_id": first["tax_id"],
         "contact_email": "b@x.test"},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAX_ID)


def test_computed_and_system_fields_rejected_in_payload(api, analyst_headers):
    """PRD section 2.8 tier 5: "no undeclared fields may appear ... Failures
    yield `ERR_VALIDATION` (HTTP 400)." PRD section 3.1: "A new licensee starts
    in `ACTIVE` status with both `outstanding_balance_cents` and
    `credit_balance_cents` at zero." — those fields are system-managed, not
    client input.

    Design: Corner/entities/computed_and_system_fields_rejected_in_payload
    """
    payload = create_licensee_payload(legal_name="Bad Co")
    payload["outstanding_balance_cents"] = 999
    resp = api.create_licensee(payload, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_nonexistent_entities_return_404(api, analyst_headers):
    """PRD section 2.8 tier 3: "The first unresolvable reference produces the
    corresponding not-found error: `ERR_LICENSEE_NOT_FOUND` for a licensee,
    `ERR_AGREEMENT_NOT_FOUND` for a license agreement, `ERR_REPORT_NOT_FOUND`
    for a royalty report ... `ERR_DISPUTE_NOT_FOUND` for a dispute ... each
    with HTTP 404."

    Design: Corner/entities/get_nonexistent_entities_return_404
    """
    cases = [
        (api.get_licensee(NON_EXISTENT_UUID, analyst_headers),
         ApiErrorId.ERR_LICENSEE_NOT_FOUND),
        (api.get_agreement(NON_EXISTENT_UUID, analyst_headers),
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        (api.get_royalty_report(NON_EXISTENT_UUID, analyst_headers),
         ApiErrorId.ERR_REPORT_NOT_FOUND),
        (api.get_dispute(NON_EXISTENT_UUID, analyst_headers),
         ApiErrorId.ERR_DISPUTE_NOT_FOUND),
    ]
    for resp, err_id in cases:
        validate_error(resp, err_id)


def test_suspended_licensee_cannot_submit_report(api, analyst_headers):
    """PRD section 3.1: "Submitting a royalty report and requesting a
    sublicense grant both require the licensee to be `ACTIVE`; either attempt
    on a `SUSPENDED` or `TERMINATED` licensee is rejected with
    `ERR_LICENSEE_NOT_ACTIVE`."

    Design: Corner/errors/suspended_licensee_cannot_submit_report
    """
    licensee, agreement = create_active_agreement()
    suspend_licensee(licensee["id"])

    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"], lines=[make_report_line(gross_sales_cents=1000)]
    )
    resp = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_LICENSEE_NOT_ACTIVE)


def test_licensee_cross_read_forbidden(api, analyst_headers):
    """PRD section 2.1: "a `Licensee` caller retrieving a licensee record
    other than its own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/licensee_cross_read_forbidden
    """
    la = create_licensee(legal_name="Cr A")
    lb = create_licensee(legal_name="Cr B")
    resp = api.get_licensee(lb["id"], make_licensee_headers(la["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
