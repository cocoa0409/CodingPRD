"""Entity CRUD, defaults, system fields, type/required-field validation, immutability.

Covers corner queue (B) section: entities.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    assert_parcel,
    assert_owner,
    assert_assessment,
    assert_deferral_payment,
    is_valid_uuid,
    create_owner,
    create_open_roll,
    create_parcel,
    create_assessment,
    setup_deferral_with_accrual,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]


def test_create_parcel_returns_201_with_fields(api):
    """PRD §3.2: "Parcels are listed in `created_at` order, filterable by `owner_id`, and
    begin life `ACTIVE`."
    PRD §3.2: "A parcel also carries `last_certified_capped_base`, a computed figure equal to
    the `capped_base_value` of its most recent certified assessment and serving as the
    baseline for next year's cap; it reads 0 before any certification."

    Design: Corner/entities/create_parcel_returns_201_with_fields
    """
    owner = create_owner()
    resp = api.create_parcel(f.create_parcel_payload(owner["id"]), ASSESSOR)
    data = validate_success(resp, expected_status=201)
    assert_parcel(data)
    assert data["status"] == "ACTIVE"
    assert data["last_certified_capped_base"] == 0
    assert is_valid_uuid(data["id"])


def test_get_parcel_not_found_returns_404(api):
    """PRD §2.6: "Any referenced `id` that does not resolve to a stored resource — whether in
    the path or the request body — yields `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_parcel_not_found_returns_404
    """
    resp = api.get_parcel(NON_EXISTENT_UUID, ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_tax_roll_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "Last of all, generic request-body schema validation (`ERR_INVALID_REQUEST`,
    HTTP 400) catches malformed payloads: a missing required field, a bad enum value, or an
    out-of-range numeric."

    Design: Corner/entities/create_tax_roll_missing_required_field_returns_invalid_request
    """
    # mill_rate is required (PRD §3.1).
    resp = api.create_tax_roll({"tax_year": 2026, "growth_cap_pct": 0.02}, ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_owner_defaults_is_veteran_false_and_disability_zero(api):
    """PRD §3.2: "Two optional attributes round out eligibility: `is_veteran`, a
    verified-veteran flag defaulting to false, and `disability_pct`, a service or medical
    disability rating between 0 and 100 that defaults to 0."

    Design: Corner/entities/owner_default_is_veteran_false
    """
    resp = api.create_owner(f.create_owner_payload(), ASSESSOR)
    data = validate_success(resp, expected_status=201)
    assert_owner(data)
    assert data["is_veteran"] is False
    assert data["disability_pct"] == 0


def test_assessment_system_fields_set_by_server(api):
    """PRD §3.3: "A fresh assessment begins in `DRAFT`."
    PRD §3.3: "In either regime `assessed_value` equals `capped_base_value`".
    PRD §2.4: "`version` is an integer that begins at 1 on creation".

    Design: Corner/entities/assessment_system_fields_ignore_client_input
    """
    owner = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(owner["id"])
    asmt = create_assessment(parcel["id"], roll["id"], 90000, reassessment_event="NONE")
    assert_assessment(asmt)
    assert asmt["status"] == "DRAFT"
    # First-ever assessment (prior base 0) -> market rebase: assessed_value == market 90000.
    assert asmt["assessed_value"] == 90000
    assert asmt["version"] == 1


def test_create_assessment_bad_enum_reassessment_event_rejected(api):
    """PRD §3.3: "The creator may also supply `reassessment_event`, an enumeration of `NONE`,
    `SALE`, or `NEW_CONSTRUCTION` that defaults to `NONE`".
    PRD §2.8: "generic request-body schema validation (`ERR_INVALID_REQUEST`, HTTP 400)
    catches malformed payloads: a missing required field, a bad enum value, or an
    out-of-range numeric."

    Design: Corner/entities/create_assessment_bad_enum_reassessment_event_rejected
    """
    owner = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(owner["id"])
    resp = api.create_assessment(
        f.create_assessment_payload(parcel["id"], roll["id"], 90000, reassessment_event="REMODEL"),
        ASSESSOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_deferral_payment_immutable_no_version_field(api):
    """PRD §2.4: "The one exception to the common-field set is `DeferralPayment`, which is an
    immutable append-only event: it carries only `id` and `created_at`, and has neither
    `updated_at` nor `version` because it is never modified once written."

    Design: Corner/entities/deferral_payment_immutable_no_version_field
    """
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )  # accrued 10000
    payment = validate_success(
        api.create_payment(deferral["id"], f.create_payment_payload(5000, deferral["version"]), ASSESSOR),
        expected_status=201,
    )
    assert_deferral_payment(payment)
    assert payment["applied_to_interest_cents"] == 5000


def test_create_assessment_nonexistent_parcel_not_found(api):
    """PRD §2.6: "Any referenced `id` that does not resolve to a stored resource — whether in
    the path or the request body — yields `ERR_NOT_FOUND` (HTTP 404), and existence is always
    checked before any state or business rule."

    Design: Corner/entities/parent_relationship_assessment_wrong_parcel_not_found
    """
    roll = create_open_roll()
    resp = api.create_assessment(
        f.create_assessment_payload(NON_EXISTENT_UUID, roll["id"], 90000, reassessment_event="NONE"),
        ASSESSOR,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
