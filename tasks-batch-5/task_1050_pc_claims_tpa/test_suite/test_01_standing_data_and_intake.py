"""Standing data creation, claim intake, required-field / enum / auth guards, and listing.

Covers entity creation, not-found, required-field, default, computed-field, RBAC, and
listing behaviours from the PRD.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_client_account_payload, create_policy_payload, create_claim_payload,
    create_vendor_payload,
    TEST_USERS, make_vendor_headers,
    create_account, create_policy, create_vendor,
    assert_client_account, assert_policy, assert_claim,
)

CM = TEST_USERS["claims_manager_headers"]
ADJ = TEST_USERS["adjuster_headers"]


def test_create_client_account_zeroes_rollup_totals(api):
    """PRD §3.1: "On creation the account's three roll-up totals — `open_case_reserve_total_cents`,
    `gross_incurred_total_cents`, and `recovered_total_cents` — all begin at zero."

    Design: Corner/entities/create_client_account_success
    """
    resp = api.create_client_account(
        create_client_account_payload(account_code="C-OK1"), CM)
    data = validate_success(resp, 201)
    assert_client_account(data)
    assert data["open_case_reserve_total_cents"] == 0
    assert data["gross_incurred_total_cents"] == 0
    assert data["recovered_total_cents"] == 0


def test_fetch_missing_claim_returns_not_found(api):
    """PRD §2.8: "every `id` in the path and every foreign key in the body resolves to an
    existing resource, checked left to right, else `ERR_NOT_FOUND`."

    Design: Corner/entities/claim_not_found_returns_404
    """
    resp = api.get_claim(NON_EXISTENT_UUID, CM)
    validate_error(resp, "ERR_NOT_FOUND")


def test_claim_intake_without_policy_id_is_rejected(api):
    """PRD §2.8: "required fields present, enum values legal, and the field-level constraints
    in §3 (positive amounts, non-zero deltas, ordered time windows), else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/claim_missing_required_policy_id
    """
    payload = create_claim_payload(policy_id="placeholder")
    del payload["policy_id"]
    resp = api.create_claim(payload, ADJ)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_policy_deductible_defaults_zero_and_status_active(api):
    """PRD §3.1: "an optional `deductible_cents` (default 0)"
    PRD §3.1: "a policy reads `ACTIVE` while the current clock instant is before its
    `expiration_date`, and `EXPIRED` once the clock reaches or passes it."

    Design: Corner/entities/policy_deductible_defaults_zero
    """
    account = create_account(api, account_code="C-DF")
    payload = create_policy_payload(account["id"], policy_number="P-DF")
    del payload["deductible_cents"]
    resp = api.create_policy(payload, CM)
    data = validate_success(resp, 201)
    assert_policy(data)
    assert data["deductible_cents"] == 0
    assert data["status"] == "ACTIVE"


def test_new_claim_starts_zeroed_and_copies_account(api):
    """PRD §3.2: "A new claim enters `INTAKE` status with a fraud posture `siu_status` of
    `NONE`; its `assigned_adjuster_id` is null, all of its monetary buckets —
    `indemnity_reserve_cents`, `expense_reserve_cents`, `paid_indemnity_cents`,
    `paid_expense_cents`, `recovered_cents`, `recovered_indemnity_cents`,
    `recovered_expense_cents` — start at zero, and its `ack_at` is null."
    PRD §3.2: "The claim's `client_account_id` is copied from the policy rather than supplied."

    Design: Corner/entities/new_claim_computed_fields_zero
    """
    account = create_account(api, account_code="C-NC")
    policy = create_policy(api, account["id"], policy_number="P-NC")
    resp = api.create_claim(create_claim_payload(policy["id"]), ADJ)
    data = validate_success(resp, 201)
    assert_claim(data)
    assert data["status"] == "INTAKE"
    assert data["siu_status"] == "NONE"
    assert data["gross_incurred_cents"] == 0
    assert data["net_incurred_cents"] == 0
    assert data["client_account_id"] == account["id"]


def test_vendor_with_illegal_type_is_rejected(api):
    """PRD §2.8: "required fields present, enum values legal, and the field-level constraints
    in §3 (positive amounts, non-zero deltas, ordered time windows), else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/vendor_invalid_enum_type_rejected
    """
    resp = api.create_vendor(
        create_vendor_payload(vendor_type="WIZARD", credentialed_coverages=["PROPERTY"]), CM)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_vendor_may_not_open_a_claim(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/vendor_cannot_create_claim
    """
    account = create_account(api, account_code="C-VC")
    policy = create_policy(api, account["id"], policy_number="P-VC")
    vendor = create_vendor(api, vendor_type="APPRAISER", credentialed_coverages=["PROPERTY"])
    resp = api.create_claim(create_claim_payload(policy["id"]), make_vendor_headers(vendor["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED")


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role that is not one of
    the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    anon_headers = {"Content-Type": "application/json"}
    resp = api.get_claim(NON_EXISTENT_UUID, anon_headers)
    validate_error(resp, "ERR_UNAUTHENTICATED")


def test_intake_against_expired_policy_is_rejected(api):
    """PRD §3.2: "Intake is permitted only while the policy is `ACTIVE`; against an expired
    policy it is rejected with `ERR_POLICY_INACTIVE`."

    Design: Corner/validations/policy_inactive_on_claim_intake
    """
    account = create_account(api, account_code="C-PI")
    policy = create_policy(api, account["id"], policy_number="P-PI",
                           expiration_date="2030-01-01T00:00:00Z")
    # Advance the logical clock past expiration so the policy computes EXPIRED.
    validate_success(api.set_clock("2031-06-01T00:00:00Z", CM), 200)
    resp = api.create_claim(create_claim_payload(policy["id"]), ADJ)
    validate_error(resp, "ERR_POLICY_INACTIVE")


def test_filtered_claim_list_returns_array_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §3.2: "Claims can be listed with reverse-lookup filters `policy_id`,
    `client_account_id`, `assigned_adjuster_id`, `status`, and `coverage_type`."

    Design: Corner/endpoints/claims_filtered_list_envelope
    """
    account = create_account(api, account_code="C-LS")
    policy = create_policy(api, account["id"], policy_number="P-LS")
    claim = validate_success(api.create_claim(create_claim_payload(policy["id"]), ADJ), 201)
    resp = api.list_claims(CM, params={"policy_id": policy["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == claim["id"]
    assert "total_count" in meta and "has_more" in meta
