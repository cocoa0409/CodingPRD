"""Provider enrollment, abrasion profile auto-creation, authentication,
error envelope, reference existence, and claim intake schema checks."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_abrasion_profile,
    assert_claim_line,
    assert_provider,
    create_claim_line_payload,
    create_claim_payload,
    create_provider,
    get_success_data,
    make_provider_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_provider_creation_auto_creates_zeroed_abrasion_profile(api):
    """PRD §3.1: "A new provider's `status` defaults to `ACTIVE`"
    PRD §3.1: "the server auto-creates a ProviderAbrasionProfile, one-to-one
    with the provider, with every counter zeroed — `confirmed_count`,
    `overridden_count`, `fp_count`, `superseded_count`,
    `denied_cents_lifetime`, `released_cents_lifetime`, and `open_ibr_count`
    all start at zero, `standard_index` and `regulatory_index` start at zero,
    `tier` starts `LOW`, and `monitor_only` starts false."

    Design: Corner/entities/provider_creation_auto_creates_zeroed_abrasion_profile
    """
    provider = validate_success(
        api.create_provider({"npi": "NPI-E1", "name": "Entity Prov"}, ADMIN),
        expected_status=201)
    assert_provider(provider)
    assert provider["status"] == "ACTIVE"

    data, meta = validate_paginated(
        api.list_abrasion_profiles(ADMIN, params={"provider_id": provider["id"]}))
    assert meta["total_count"] == 1, "exactly one profile per provider"
    profile = data[0]
    assert_abrasion_profile(profile)
    assert profile["provider_id"] == provider["id"]
    assert profile["standard_index"] == 0
    assert profile["regulatory_index"] == 0
    assert profile["tier"] == "LOW"
    assert profile["monitor_only"] is False
    for field in ("confirmed_count", "overridden_count", "fp_count",
                  "superseded_count", "denied_cents_lifetime",
                  "released_cents_lifetime", "open_ibr_count"):
        assert profile[field] == 0, f"{field} must start at zero"


@pytest.mark.parametrize("path,error_id", [
    ("/payment-integrity/providers/{}", ApiErrorId.ERR_PROVIDER_NOT_FOUND),
    ("/payment-integrity/claims/{}", ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ("/payment-integrity/edit-rules/{}", ApiErrorId.ERR_EDIT_RULE_NOT_FOUND),
    ("/payment-integrity/edit-versions/{}", ApiErrorId.ERR_EDIT_VERSION_NOT_FOUND),
    ("/payment-integrity/edit-hits/{}", ApiErrorId.ERR_EDIT_HIT_NOT_FOUND),
    ("/payment-integrity/review-tasks/{}", ApiErrorId.ERR_REVIEW_TASK_NOT_FOUND),
    ("/payment-integrity/disputes/{}", ApiErrorId.ERR_DISPUTE_NOT_FOUND),
    ("/payment-integrity/itemized-bill-reviews/{}", ApiErrorId.ERR_IBR_NOT_FOUND),
    ("/payment-integrity/inpatient-reviews/{}",
     ApiErrorId.ERR_INPATIENT_REVIEW_NOT_FOUND),
    ("/payment-integrity/savings-periods/{}",
     ApiErrorId.ERR_SAVINGS_PERIOD_NOT_FOUND),
    ("/payment-integrity/vendor-edits/{}", ApiErrorId.ERR_VENDOR_EDIT_NOT_FOUND),
])
def test_get_missing_entities_return_not_found(api, path, error_id):
    """PRD §2.8: "the provider first, then the claim, the edit rule (the
    `ruleId` path parameter on version-creation URLs), the edit version, the
    edit hit (including the body-supplied `edit_hit_id` on dispute creation),
    the review task, the dispute, the itemized bill review, the inpatient
    review, the savings period, and finally the vendor edit — each unresolved
    reference producing its own 404: `ERR_PROVIDER_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_EDIT_RULE_NOT_FOUND`,
    `ERR_EDIT_VERSION_NOT_FOUND`, `ERR_EDIT_HIT_NOT_FOUND`,
    `ERR_REVIEW_TASK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_IBR_NOT_FOUND`,
    `ERR_INPATIENT_REVIEW_NOT_FOUND`, `ERR_SAVINGS_PERIOD_NOT_FOUND`, or
    `ERR_VENDOR_EDIT_NOT_FOUND`."

    Design: Corner/entities/get_missing_entities_return_not_found
    """
    resp = api.get(path.format(NON_EXISTENT_UUID), headers=ADMIN)
    validate_error(resp, error_id, expected_status=404)


def test_create_claim_missing_required_member_id(api):
    """PRD §2.8: "Required fields are present, types are correct, and no
    unknown fields appear, else `ERR_INVALID_REQUEST` (HTTP 400)"
    PRD §3.4: "The submission carries the provider-assigned `claim_number`
    (free-text), the `member_id` of the patient, the `claim_type` —
    `PROFESSIONAL`, `INSTITUTIONAL_INPATIENT`, or `INSTITUTIONAL_OUTPATIENT` —
    the header `total_billed_cents` (at least 1), and the service span
    `service_from` through `service_to`"

    Design: Corner/entities/create_claim_missing_required_member_id
    """
    provider = create_provider(npi="NPI-E2", name="Req Prov")
    payload = create_claim_payload(provider["id"], claim_number="X1",
                                   total_billed_cents=1000)
    del payload["member_id"]
    resp = api.create_claim(payload, make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"provider_id": provider["id"]}))
    assert meta["total_count"] == 0, "no claim row may be created"


def test_create_claim_rejects_injected_computed_field(api):
    """PRD §2.8: "Required fields are present, types are correct, and no
    unknown fields appear, else `ERR_INVALID_REQUEST` (HTTP 400)"
    PRD §2.10: "Screening establishes `initial_allowed_cents` — the DRG
    payment for an inpatient claim, the billed total otherwise"

    Design: Corner/entities/create_claim_rejects_injected_computed_field
    """
    provider = create_provider(npi="NPI-E4", name="Inj Prov")
    payload = create_claim_payload(provider["id"], claim_number="X2",
                                   member_id="M-X2", total_billed_cents=1000)
    payload["allowed_amount_cents"] = 999999
    resp = api.create_claim(payload, make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_claim_line_units_defaults_to_one(api):
    """PRD §3.4: "each line carries a 1-based `line_number` unique within the
    claim, a `procedure_code` string (CPT, HCPCS, or revenue code), a
    `billed_cents` of at least 1, and an optional `units` defaulting to 1 and
    never less than 1."

    Design: Corner/entities/claim_line_units_defaults_to_one
    """
    provider = create_provider(npi="NPI-E3", name="Def Prov")
    claim = get_success_data(api.create_claim(
        create_claim_payload(provider["id"], claim_number="D1",
                             member_id="M-D1", total_billed_cents=5000),
        make_provider_headers(provider["id"])), expected_status=201)
    line = validate_success(api.add_claim_line(
        claim["id"], create_claim_line_payload(1, "99213", 5000),
        make_provider_headers(provider["id"])), expected_status=201)
    assert_claim_line(line)
    assert line["units"] == 1, "units defaults to 1 when omitted"


def test_request_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role outside
    the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_missing_auth_headers_unauthenticated
    """
    provider = create_provider(npi="NPI-AU", name="Auth Prov")
    resp = api.get(f"/payment-integrity/providers/{provider['id']}", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_error_response_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/errors/error_response_envelope_shape
    """
    resp = api.get(f"/payment-integrity/claims/{NON_EXISTENT_UUID}",
                   headers=ADMIN)
    body = resp.json()
    assert body.get("response_type") == "error"
    assert set(body["data"].keys()) >= {"error_id", "message"}
    error_data = validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND,
                                expected_status=404)
    assert isinstance(error_data["message"], str) and error_data["message"].strip()


def test_invalid_enum_claim_type_rejected(api):
    """PRD §2.8: "enum-typed fields carry a declared member, else
    `ERR_INVALID_ENUM` (HTTP 400)."
    PRD §3.4: "the `claim_type` — `PROFESSIONAL`, `INSTITUTIONAL_INPATIENT`,
    or `INSTITUTIONAL_OUTPATIENT`"

    Design: Corner/validations/invalid_enum_claim_type_rejected
    """
    provider = create_provider(npi="NPI-EN", name="Enum Prov")
    payload = create_claim_payload(provider["id"], claim_number="EN1",
                                   member_id="M-EN1", claim_type="COSMIC",
                                   total_billed_cents=1000)
    resp = api.create_claim(payload, make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, expected_status=400)
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"provider_id": provider["id"]}))
    assert meta["total_count"] == 0, "no claim row may be created"


def test_provider_cannot_add_line_to_foreign_claim(api):
    """PRD §2.1: "When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of
    the acting Provider; ownership checks on any resource that references a
    provider compare the resource's foreign-key field (for example a claim's
    or dispute's `provider_id`) to `X-User-ID`, and a mismatch is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/provider_cannot_add_line_to_foreign_claim
    """
    prov_a = create_provider(npi="NPI-RA", name="Prov A")
    prov_b = create_provider(npi="NPI-RB", name="Prov B")
    claim = get_success_data(api.create_claim(
        create_claim_payload(prov_a["id"], claim_number="OW1", member_id="M-OW1",
                             total_billed_cents=5000),
        make_provider_headers(prov_a["id"])), expected_status=201)
    resp = api.add_claim_line(
        claim["id"], create_claim_line_payload(1, "99213", 5000),
        make_provider_headers(prov_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    lines, meta = validate_paginated(api.list_claim_lines(claim["id"], ADMIN))
    assert meta["total_count"] == 0, "no line may be added to a foreign claim"
