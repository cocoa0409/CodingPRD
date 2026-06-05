"""Claim-creation validations, RBAC, authentication, ownership, and listing.

Corner queue: validations (wellness rider, missing condition, cross-policy FK),
rbac (forbidden role, not-owner, unauthenticated), endpoints (listing/filtering).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_account, create_policy, activate_policy, create_condition,
    build_claim_in_review, get_year_zero_version, open_claim, add_line,
    upload_invoice, run_ocr, accept_invoice,
    make_policy_holder_headers, make_underwriter_headers, make_claims_adjuster_headers,
    ApiErrorId,
)


def _uw():
    return make_underwriter_headers()


def _adj():
    return make_claims_adjuster_headers()


def test_wellness_claim_on_non_rider_policy_rejected(api):
    """PRD 3.4: "a WELLNESS claim requires that the policy carry the wellness_rider ... A
    violation of either branch — a wellness claim on a riderless policy, or a non-wellness
    claim with no condition — is rejected with ERR_WELLNESS_RIDER_REQUIRED."

    Design: Corner/validations/wellness_claim_on_non_rider_policy_rejected
    """
    acct = create_account(email="v18@x.com")
    pol = create_policy(acct["id"], wellness_rider=False)
    activate_policy(acct["id"], pol["id"])

    resp = api.create_claim(acct["id"], pol["id"],
                            {"claim_type": "WELLNESS", "incident_date": "2026-03-01T00:00:00Z"},
                            make_policy_holder_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_WELLNESS_RIDER_REQUIRED.value)


def test_illness_claim_missing_condition_rejected(api):
    """PRD 3.4: "while an ILLNESS or ACCIDENT claim requires a non-null condition_id. A
    violation of either branch — a wellness claim on a riderless policy, or a non-wellness
    claim with no condition — is rejected with ERR_WELLNESS_RIDER_REQUIRED."

    Design: Corner/validations/illness_claim_missing_condition_id_rejected
    """
    acct = create_account(email="v19@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])

    resp = api.create_claim(acct["id"], pol["id"],
                            {"claim_type": "ILLNESS", "incident_date": "2026-03-01T00:00:00Z"},
                            make_policy_holder_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_WELLNESS_RIDER_REQUIRED.value)


def test_claim_condition_from_other_policy_is_fk_invalid(api):
    """PRD 3.4: "When a condition_id is supplied, it must resolve to a MedicalCondition
    belonging to the same policy named in the path, or the request is rejected with
    ERR_FK_INVALID."

    Condition recorded on P2, claim opened on P1 referencing it -> ERR_FK_INVALID.

    Design: Corner/validations/claim_condition_from_other_policy_fk_invalid
    """
    acct = create_account(email="v20@x.com")
    p1 = create_policy(acct["id"], pet_name="Rex")
    activate_policy(acct["id"], p1["id"])
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800)
    activate_policy(acct["id"], p2["id"])
    c2 = create_condition(acct["id"], p2["id"], name="other", first_diagnosed_date="2026-02-01T00:00:00Z")

    resp = api.create_claim(acct["id"], p1["id"],
                            {"claim_type": "ILLNESS", "incident_date": "2026-03-01T00:00:00Z", "condition_id": c2["id"]},
                            make_policy_holder_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_FK_INVALID.value)


def test_policyholder_cannot_adjudicate(api):
    """PRD 2.1: "A request whose role is recognized but not permitted for the targeted
    operation is rejected with ERR_FORBIDDEN_ROLE."
    PRD Section 4: adjudicate is authorized for ClaimsAdjuster only.

    Design: Corner/rbac/policyholder_cannot_adjudicate
    """
    set_clock("2026-06-01T00:00:00Z")
    acct = create_account(email="rb1@x.com")
    pol = create_policy(acct["id"], waiting_period_days=14)
    activate_policy(acct["id"], pol["id"])
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)
    version = get_year_zero_version(acct["id"], pol["id"])

    resp = api.adjudicate(claim["id"],
                          {"decision": "APPROVE", "expected_policy_year_version": version},
                          make_policy_holder_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_claimsadjuster_cannot_create_policy(api):
    """PRD 2.1: "A request whose role is recognized but not permitted for the targeted
    operation is rejected with ERR_FORBIDDEN_ROLE."
    PRD Section 4: POST /accounts/{id}/policies is authorized for Underwriter only.

    Design: Corner/rbac/claimsadjuster_cannot_create_policy
    """
    acct = create_account(email="rb2@x.com")
    from test_helpers import create_policy_payload
    resp = api.create_policy(acct["id"], create_policy_payload(), _adj())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_policyholder_not_owner_of_other_account_claim(api):
    """PRD 2.1: "ownership checks on any resource that chains back to an Account compare
    the resource's owning account_id (followed transitively through Policy, Claim,
    ClaimLine, and InvoiceDocument) to X-User-ID, and a PolicyHolder acting on a resource
    outside their own account chain is rejected with ERR_NOT_RESOURCE_OWNER."

    Account B submitting account A's DRAFT-ready claim -> ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/policyholder_not_owner_of_other_account_claim
    """
    acct_a = create_account(email="own-a@x.com", full_name="Acct A")
    acct_b = create_account(email="own-b@x.com", full_name="Acct B")
    pol = create_policy(acct_a["id"])
    activate_policy(acct_a["id"], pol["id"])
    cond = create_condition(acct_a["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = open_claim(acct_a["id"], pol["id"], claim_type="ILLNESS", condition_id=cond["id"])
    add_line(acct_a["id"], claim["id"], billed_amount_cents=40000)
    invoice = upload_invoice(acct_a["id"], claim["id"])
    run_ocr(claim["id"], invoice["id"], 40000)
    accept_invoice(claim["id"], invoice["id"])

    resp = api.submit_claim(claim["id"], make_policy_holder_headers(acct_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD 2.1: "Every request must include X-User-ID to identify the acting user and
    X-User-Role to declare their operational capacity ... A request missing either header,
    or carrying an unrecognized role value, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.get_account("00000000-0000-4000-8000-000000000000", {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_list_policies_by_account_paginated(api):
    """PRD 2.3: "List responses carry the pagination fields limit, offset, total_count,
    and has_more inside the meta object of the response envelope."
    PRD Section 4: GET /accounts/{id}/policies lists policies of an account.

    Design: Corner/endpoints/list_policies_by_account_pagination
    """
    acct = create_account(email="ls1@x.com")
    pol = create_policy(acct["id"])

    resp = api.list_policies_of_account(acct["id"], _uw(), params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"total_count: {meta['total_count']}"
    assert meta["has_more"] is False
    assert data[0]["id"] == pol["id"]


def test_claims_filtered_by_condition_id(api):
    """PRD Section 4: "GET /claims | List claims, filterable by policy or condition."
    PRD 4 (filters): "/claims accepts policy_id, condition_id, and status."

    Filtering by condition_id returns only the claim referencing that condition.

    Design: Corner/endpoints/claims_filtered_list_by_condition_id
    """
    acct = create_account(email="ls2@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = open_claim(acct["id"], pol["id"], claim_type="ILLNESS", condition_id=cond["id"])

    resp = api.list_claims(_adj(), params={"condition_id": cond["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"total_count: {meta['total_count']}"
    assert data[0]["id"] == claim["id"]
