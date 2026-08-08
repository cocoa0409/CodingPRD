"""Onboarding basics, existence/validation guards, RBAC, pagination, and FK listing.

Translates queue-B (Corner) instances from the entities, endpoints, rbac, and
pagination sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_practice_payload, create_payer_payload, create_provider_payload,
    create_claim_payload, create_claim_line_payload,
    make_account_manager_headers, make_coder_headers, make_biller_headers,
    make_credentialing_specialist_headers, make_payment_poster_headers,
    make_practice_user_headers, ANONYMOUS_HEADERS,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()
CODER = make_coder_headers()
CRED = make_credentialing_specialist_headers()


def test_practice_creation_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created practice begins in `PROSPECT` status. Its
    accounts-receivable figure `ar_balance_cents` and its year-to-date collections
    figure `collected_ytd_cents` both start at 0 and are maintained by the platform
    thereafter."
    PRD §2.4: "The `version` field is an integer that begins at 1 on creation and
    increments by one on every mutation"

    Design: Corner/entities/practice_creation_returns_201_with_defaults
    """
    resp = api.create_practice(create_practice_payload(name="New Clinic", npi="1111111130",
                                                       tax_id="22-9999999", billing_fee_pct=0.06), AM)
    data = validate_success(resp, 201)
    assert data["status"] == "PROSPECT", f"expected PROSPECT, got {data['status']}"
    assert data["ar_balance_cents"] == 0
    assert data["version"] == 1


def test_get_nonexistent_claim_returns_not_found(api):
    """PRD §2.8: "The request is rejected on the first identifier that does not
    resolve, using the not-found error specific to that resource type:
    `ERR_PRACTICE_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    ... each carrying HTTP 404."

    Design: Corner/entities/claim_get_nonexistent_returns_not_found
    """
    resp = api.get_claim(NON_EXISTENT_UUID, CODER)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND.value)


def test_practice_missing_billing_fee_pct_returns_validation(api):
    """PRD §3: "Malformed input — a missing required field, a wrong type, or an
    out-of-range value — is rejected with `ERR_VALIDATION` (HTTP 422)"

    Design: Corner/entities/practice_missing_billing_fee_pct_returns_validation
    """
    payload = {"name": "No Fee Clinic", "npi": "1111111131", "tax_id": "22-8888888"}
    resp = api.create_practice(payload, AM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_payer_invalid_payer_type_returns_invalid_enum(api):
    """PRD §3: "an enum field carrying a value outside its declared set is rejected
    with `ERR_INVALID_ENUM` (HTTP 422)"

    Design: Corner/entities/payer_invalid_payer_type_returns_invalid_enum
    """
    resp = api.create_payer(create_payer_payload(name="WeirdCo", payer_type="SELF_PAY"), AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_coder_cannot_submit_claim_returns_unauthorized(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation according to the role matrix, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.4: "Submission is a `Biller`'s responsibility and moves a claim from
    `SCRUBBED` to `SUBMITTED`."

    Design: Corner/rbac/coder_cannot_submit_claim_returns_unauthorized
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    prac = fx.new_practice(api)
    payer = fx.new_payer(api)
    prov = fx.new_provider(api, prac["id"])
    claim = fx.new_claim(api, prac["id"], prov["id"], payer["id"])
    resp = api.submit_claim(claim["id"], make_coder_headers("coder-c7"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.list_practices(ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_practiceuser_reads_own_practice(api):
    """PRD §2.1: "A `PracticeUser` may read its own practice, that practice's claims,
    statements, KPI, and billing-fee figures, but performs no mutating operation."
    PRD §2.1: "when `X-User-Role` is `PracticeUser`, `X-User-ID` is the `id` of the
    acting `Practice`."

    Design: Corner/rbac/practiceuser_reads_own_practice
    """
    prac = fx.new_practice(api, name="FF Clinic", npi="1111111145", tax_id="22-6060606")
    resp = api.get_practice(prac["id"], make_practice_user_headers(prac["id"]))
    data = validate_success(resp, 200)
    assert data["id"] == prac["id"]


def test_paymentposter_cannot_scrub_returns_unauthorized(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation according to the role matrix, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.3: "A `Coder` opens a new claim as charge-entry work."

    Design: Corner/rbac/paymentposter_cannot_scrub_returns_unauthorized
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    prac = fx.new_practice(api)
    payer = fx.new_payer(api)
    prov = fx.new_provider(api, prac["id"])
    claim = fx.new_claim(api, prac["id"], prov["id"], payer["id"])
    fx.add_claim_line(api, claim["id"])
    resp = api.scrub_claim(claim["id"], make_payment_poster_headers("pp-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_credentialingspecialist_cannot_create_claim_returns_unauthorized(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation according to the role matrix, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.3: "A `Coder` opens a new claim as charge-entry work."

    Design: Corner/rbac/credentialingspecialist_cannot_create_claim_returns_unauthorized
    """
    prac = fx.new_practice(api, name="MM Clinic", npi="1111111154", tax_id="22-4445556")
    payer = fx.new_payer(api)
    prov = fx.new_provider(api, prac["id"])
    resp = api.create_claim(
        create_claim_payload(prac["id"], prov["id"], payer["id"]),
        make_credentialing_specialist_headers("cred-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_list_practices_returns_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` reports
    the full size of the matching collection and `has_more` indicates whether further
    items remain beyond the current page."

    Design: Corner/pagination/list_practices_returns_pagination_envelope
    """
    fx.new_practice(api, name="NN Clinic", npi="1111111155", tax_id="22-5556667")
    fx.new_practice(api, name="OO Clinic", npi="1111111156", tax_id="22-6667778")
    resp = api.list_practices(AM, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is False


def test_list_providers_by_practice_returns_children(api):
    """PRD §3.2: "A `CredentialingSpecialist` registers a rendering `Provider` under a
    practice by supplying the `practice_id`, the provider's individual ten-digit
    `npi`, `first_name`, `last_name`, and `specialty`."
    PRD §2.3: "list results are sorted by the resource's `created_at` timestamp in
    ascending order."

    Design: Corner/endpoints/list_providers_by_practice_returns_children
    """
    prac = fx.new_practice(api, name="DD Clinic", npi="1111111143", tax_id="22-4040404")
    prov = fx.new_provider(api, prac["id"])
    resp = api.list_practice_providers(prac["id"], AM)
    data, _ = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly one provider, got {len(data)}"
    assert data[0]["id"] == prov["id"]
