"""Chart-of-accounts creation, lookup, and company computed-field defaults.

Translates queue-B (Corner) entities instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_account, assert_company,
    create_company_payload, create_account_payload, configure_company_payload,
    TEST_USERS,
)

OWNER = TEST_USERS["owner_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _company(api):
    return validate_success(api.create_company(create_company_payload(), OWNER), 201)


def test_create_account_returns_201_with_defaults(api):
    """PRD §3.1: "A new account is born `ACTIVE` with `posted_balance_cents` of 0".
    PRD §2.4: "The `version` field is an integer that begins at 1 on creation".

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    co = _company(api)
    resp = api.create_account(
        create_account_payload(co["id"], "1000", "Cash", "ASSET", is_cash=True), OWNER)
    acct = validate_success(resp, 201)
    assert_account(acct)
    assert acct["status"] == "ACTIVE", f"expected ACTIVE, got {acct['status']}"
    assert acct["posted_balance_cents"] == 0, f"expected 0, got {acct['posted_balance_cents']}"
    assert acct["version"] == 1, f"expected version 1, got {acct['version']}"


def test_create_account_missing_required_field_rejected(api):
    """PRD §3.1: "A missing or malformed required field on account creation is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_account_missing_required_field_rejected
    """
    co = _company(api)
    # Omit account_type (a required input field).
    payload = {"company_id": co["id"], "code": "1000", "name": "Cash"}
    resp = api.create_account(payload, OWNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_sub_account_type_mismatch_rejected(api):
    """PRD §3.1: "a sub-account must share its parent's `account_type`, and a
    mismatch is rejected with `ERR_ACCOUNT_TYPE_MISMATCH`."

    Design: Corner/entities/sub_account_type_mismatch_rejected
    """
    co = _company(api)
    parent = validate_success(api.create_account(
        create_account_payload(co["id"], "1000", "Cash", "ASSET", is_cash=True), OWNER), 201)
    resp = api.create_account(
        create_account_payload(co["id"], "1001", "Sub", "EXPENSE",
                               parent_account_id=parent["id"]), OWNER)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_TYPE_MISMATCH.value)


def test_duplicate_account_code_rejected(api):
    """PRD §3.1: "The `code` must be unique per company among all accounts that
    are not `ARCHIVED`; a collision with a live account's code is rejected with
    `ERR_DUPLICATE_ACCOUNT_CODE`."

    Design: Corner/entities/duplicate_account_code_rejected
    """
    co = _company(api)
    validate_success(api.create_account(
        create_account_payload(co["id"], "1000", "Cash", "ASSET", is_cash=True), OWNER), 201)
    resp = api.create_account(
        create_account_payload(co["id"], "1000", "Cash2", "ASSET"), OWNER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT_CODE.value)


def test_company_retained_earnings_starts_zero(api):
    """PRD §3.1: "On creation the company's `version` is 1, its
    `retained_earnings_cents` is 0, its `trial_balance_status` is `BALANCED`, and
    its `current_period_id` is null."

    Design: Corner/entities/computed_field_retained_earnings_starts_zero
    """
    resp = api.create_company(create_company_payload(accounting_basis="CASH"), OWNER)
    co = validate_success(resp, 201)
    assert_company(co)
    assert co["retained_earnings_cents"] == 0, f"got {co['retained_earnings_cents']}"
    assert co["trial_balance_status"] == "BALANCED", f"got {co['trial_balance_status']}"


def test_list_accounts_filtered_by_company_paginated(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_accounts_filtered_by_company_paginated
    """
    co = _company(api)
    validate_success(api.create_account(
        create_account_payload(co["id"], "1000", "Cash", "ASSET", is_cash=True), OWNER), 201)
    validate_success(api.create_account(
        create_account_payload(co["id"], "4000", "Rev", "REVENUE"), OWNER), 201)
    data, meta = validate_paginated(api.list_accounts(AUDITOR, params={"company_id": co["id"]}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"
