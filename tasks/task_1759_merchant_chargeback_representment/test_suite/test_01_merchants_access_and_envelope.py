"""Merchant onboarding, RBAC, existence/auth ordering, and the list envelope."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_merchant,
    assert_reserve_account,
    create_enrollment,
    create_merchant,
    create_plan,
    create_rule,
    ingest_chargeback,
    ingest_sale,
    make_merchant_user_headers,
    notify,
    reserve_account_for,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_merchant_creation_applies_defaults_and_reserve_cascade(api):
    """PRD §3.1: "The `risk_tier` is `STANDARD` by default" ... "The
    `reserve_mode` selects the reserve-target algorithm and defaults to
    `FIXED_TIER`" ... "it defaults to 500 (that is, 5.00%) and must lie between
    0 and 10000 inclusive" ... "A new merchant starts in `ACTIVE` status with
    `clearing_balance_cents` at zero, and onboarding cascades to create its 1:1
    `ReserveAccount` with `held_cents` and `target_cents` both zero."

    Design: Corner/entities/merchant_creation_defaults_and_reserve_cascade
    """
    resp = api.create_merchant(
        {"legal_name": "Defaults M", "merchant_category_code": "5411"},
        TEST_USERS["acquirer_ops_headers"],
    )
    data = validate_success(resp, 201)
    assert_merchant(data)
    assert data["risk_tier"] == "STANDARD"
    assert data["reserve_mode"] == "FIXED_TIER"
    assert data["reserve_rate_bps"] == 500
    assert data["status"] == "ACTIVE"
    assert data["clearing_balance_cents"] == 0
    assert data.get("current_count_ratio_bps") is None

    account = reserve_account_for(api, data["id"])
    assert_reserve_account(account)
    assert account["held_cents"] == 0
    assert account["target_cents"] == 0


def test_merchant_create_missing_legal_name_rejected(api):
    """PRD §3.1: "An `AcquirerOps` operator onboards a merchant by supplying
    its `legal_name` and `merchant_category_code` — the ISO 18245 four-digit
    MCC — together with three optional risk controls."
    PRD §2.9: "Payload shape — required fields present, types valid
    (`ERR_INVALID_REQUEST`, 400)".

    Design: Corner/validations/merchant_create_missing_required_field_rejected
    """
    resp = api.create_merchant(
        {"merchant_category_code": "5411"}, TEST_USERS["acquirer_ops_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_merchant_user_cross_merchant_access_hidden(api):
    """PRD §2.7: "A `MerchantUser` that touches a merchant-scoped resource
    whose `merchant_id` differs from its `X-User-ID` is answered with
    `ERR_NOT_FOUND` as well — existence is hidden, never surfaced as a
    permission failure."

    Design: Corner/rbac/merchant_user_cross_merchant_access_hidden
    """
    create_rule(api)
    m1 = create_merchant(api, legal_name="M1", reserve_rate_bps=0)
    m2 = create_merchant(api, legal_name="M2", reserve_rate_bps=0)
    ingest_sale(api, m2["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    cb = ingest_chargeback(api, m2["id"], "T-1", "NC-XM1", 10000)
    notify(api, cb["id"])

    stranger = make_merchant_user_headers(m1["id"])
    read_resp = api.get_chargeback(cb["id"], stranger)
    validate_error(read_resp, ApiErrorId.ERR_NOT_FOUND)

    write_resp = api.create_evidence_item(
        {
            "chargeback_id": cb["id"],
            "evidence_type": "RECEIPT",
            "document_uri": "s3://ev/x.pdf",
        },
        stranger,
    )
    validate_error(write_resp, ApiErrorId.ERR_NOT_FOUND)


def test_role_matrix_exclusive_denials_forbidden(api):
    """PRD §2.1: "An authenticated caller whose role is not admitted by the
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/acquirer/reserve-accounts/{id}/release` | Release
    matured settlement holds down to the reserve target | RiskOfficer |" and
    "| POST | `/acquirer/fee-assessments` | Manual fee assessment, restricted
    to ARBITRATION_FEE | FinanceOps |" and "| POST |
    `/acquirer/remediation-plans/{id}/review` | Review a submitted plan
    (APPROVE or RETURN) | RiskOfficer |".

    Design: Corner/rbac/role_matrix_exclusive_denials_forbidden
    """
    m = create_merchant(api, legal_name="RBAC M", reserve_rate_bps=0)
    ra = reserve_account_for(api, m["id"])
    enr = create_enrollment(api, m["id"], enrolled_month="2026-05")
    plan = create_plan(api, enr["id"], m["id"])
    submit_plan(api, plan["id"], m["id"])

    rel = api.release_reserve(ra["id"], TEST_USERS["finance_ops_headers"])
    validate_error(rel, ApiErrorId.ERR_FORBIDDEN_ROLE)

    fee = api.create_fee_assessment(
        {"merchant_id": m["id"], "kind": "ARBITRATION_FEE", "amount_cents": 1000},
        TEST_USERS["acquirer_ops_headers"],
    )
    validate_error(fee, ApiErrorId.ERR_FORBIDDEN_ROLE)

    review = api.review_remediation_plan(
        plan["id"], {"decision": "APPROVE"}, make_merchant_user_headers(m["id"])
    )
    validate_error(review, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_unauthenticated_request_rejected_before_existence(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value
    in one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: the priority order is "evaluated from first to last: 1.
    Authentication — the `X-User-Role` and `X-User-ID` headers are present and
    non-empty (`ERR_UNAUTHENTICATED`, 401)."

    Design: Corner/validations/unauthenticated_request_rejected_before_existence
    """
    resp = api.get_chargeback("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_chargeback_get_nonexistent_returns_not_found_envelope(api):
    """PRD §2.7: "Requests that address nested resources are validated left to
    right along the path: the first identifier that does not resolve to an
    existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404)".
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/chargeback_get_nonexistent_returns_not_found
    """
    resp = api.get_chargeback(NON_EXISTENT_UUID, TEST_USERS["acquirer_ops_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"]
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"].strip()


def test_list_pagination_defaults_and_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items and defaults to 0. Unless otherwise
    specified, every list endpoint returns resources sorted by `created_at`
    ascending; entries created within the same timestamp keep their creation
    order. The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/cross_cutting/list_pagination_defaults_and_envelope
    """
    create_rule(api)
    m = create_merchant(api, legal_name="Page M", reserve_rate_bps=0)
    for ref, case in (("T-1", "NC-PG1"), ("T-2", "NC-PG2"), ("T-3", "NC-PG3")):
        ingest_sale(api, m["id"], ref, 10000, "2026-07-10T00:00:00Z")
        ingest_chargeback(api, m["id"], ref, case, 5000)

    page1, meta1 = validate_paginated(
        api.list_chargebacks(
            TEST_USERS["finance_ops_headers"],
            params={"merchant_id": m["id"], "limit": 2},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert page1[0]["network_case_id"] == "NC-PG1"

    page2, meta2 = validate_paginated(
        api.list_chargebacks(
            TEST_USERS["finance_ops_headers"],
            params={"merchant_id": m["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False

    default_page, default_meta = validate_paginated(
        api.list_chargebacks(
            TEST_USERS["finance_ops_headers"], params={"merchant_id": m["id"]}
        )
    )
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert len(default_page) == 3

