"""Corner queue B tests: entity defaults, required fields, not-found, system fields,
pagination envelope, and audit-run immutability."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_applicant,
    create_application,
    create_landlord_payload,
    make_landlord_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SCREENER = TEST_USERS["screener_headers"]


def test_landlord_creation_applies_system_defaults():
    """PRD §3.1: "New landlords begin with `status` `ACTIVE`, a
    `fee_balance_cents` of zero, and `version` 1."
    PRD §2.5: "`id` (string): a server-minted unique identifier formatted as
    a UUID, with no type prefix."

    Design: Corner/entities/landlord_creation_applies_system_defaults
    """
    set_clock()
    resp = api_client.create_landlord(create_landlord_payload(name="L Defaults", contact_email="ldef@x.com"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["fee_balance_cents"] == 0
    assert data["version"] == 1
    assert data["id"], "server-minted id"
    # PRD §2.5 pins created_at as "an ISO 8601 UTC timestamp with three
    # fractional digits"; with the startup clock at 2026-08-01T00:00:00Z the
    # uniquely derivable serialization carries .000.
    assert data["created_at"] == "2026-08-01T00:00:00.000Z"
    assert data["updated_at"]


def test_criteria_create_missing_required_field_returns_invalid_request():
    """PRD §2.6: "Malformed request bodies — a missing required field, a type
    mismatch, an out-of-range scalar — fail with `ERR_INVALID_REQUEST`
    (HTTP 400) as the payload is parsed."

    Design: Corner/entities/criteria_create_missing_required_field_returns_invalid_request
    """
    landlord = validate_success(api_client.create_landlord(
        create_landlord_payload(name="L Req", contact_email="lreq@x.com"), ADMIN
    ), expected_status=201)
    payload = {
        "name": "CR-X",
        "disclosure_summary": "missing min score",
        "income_multiplier": 3.0,
        "guarantor_policy": "COMBINED_ALLOWED",
        "guarantor_income_multiplier": 4.0,
        "accepts_portable_reports": True,
        "accepts_voucher_income": True,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2026-12-31T00:00:00Z",
    }
    resp = api_client.create_criteria(payload, make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_nonexistent_application_returns_not_found():
    """PRD §2.6: "Resource identifiers in the path are validated left to
    right, and then identifiers referenced in the body (such as
    `applicant_id` or `portable_report_id`); the first missing resource fails
    the request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_application_returns_not_found
    """
    set_clock()
    resp = api_client.get_application(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_consent_stamps_logical_clock_time():
    """PRD §3.2: "Federal-style consent is captured when the owning
    `Applicant` signs the screening consent, at which point the system stamps
    `consent_signed_at` with the clock."
    PRD §3.2: "Identity verification runs on its own state dimension,
    independent of the application's main `status`, and is never advanced by
    it."

    Design: Corner/entities/consent_stamps_logical_clock_time
    """
    from test_helpers import create_landlord, make_applicant_headers, assert_same_instant
    set_clock("2026-08-05T10:30:00Z")
    landlord = create_landlord(name="L Consent", contact_email="lcon@x.com")
    applicant = create_applicant(full_name="Ann Con", email="acon@x.com", ssn_last4="1111")
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    resp = api_client.consent_application(app["id"], make_applicant_headers(applicant["id"]))
    data = validate_success(resp)
    assert_same_instant(data["consent_signed_at"], "2026-08-05T10:30:00Z", "consent_signed_at")
    assert data["identity_status"] == "UNVERIFIED", "identity dimension untouched by consent"


def test_applications_list_paginates_with_envelope_fields():
    """PRD §2.3: "List endpoints paginate through two query parameters."
    PRD §2.3: "Unless a subsection states otherwise, every list is returned sorted by creation timestamp (`created_at`) in ascending order, and list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/applications_list_paginates_with_envelope_fields
    """
    from test_helpers import create_landlord
    landlord = create_landlord(name="L Page", contact_email="lpage@x.com")
    ll_headers = make_landlord_headers(landlord["id"])
    for i, (name, rent, income) in enumerate([
        ("P One", 200000, 600000), ("P Two", 210000, 630000), ("P Three", 220000, 660000),
    ], start=1):
        ap = create_applicant(full_name=name, email=f"p{i}@x.com", ssn_last4=f"000{i}")
        create_application(landlord, ap, monthly_rent_cents=rent, stated_monthly_income_cents=income)
    resp1 = api_client.list_applications(ADMIN, params={"landlord_id": landlord["id"], "limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    resp2 = api_client.list_applications(ADMIN, params={"landlord_id": landlord["id"], "limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_audit_run_has_no_version_or_updated_at():
    """PRD §2.5: "One resource deliberately breaks this pattern: the
    **ConsistencyAuditRun** is an immutable event record carrying only `id`
    and `created_at`. It has no `updated_at` and no `version`, because an
    audit run is never modified after it is written."
    PRD §3.9: "The `deviation_rate` is `inconsistencies_found` divided by
    `applications_examined`, rounded half-up to four decimal places, and is
    zero when no applications were examined."

    Design: Corner/entities/audit_run_has_no_version_or_updated_at
    """
    from test_helpers import create_landlord
    landlord = create_landlord(name="L Audit0", contact_email="la0@x.com")
    resp = api_client.run_consistency_audit(landlord["id"], ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["applications_examined"] == 0
    assert data["inconsistencies_found"] == 0
    assert data["deviation_rate"] == 0
    assert "id" in data and "created_at" in data
    assert "version" not in data, "audit run must not carry version"
    assert "updated_at" not in data, "audit run must not carry updated_at"
