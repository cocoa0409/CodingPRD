"""Catalogue creation, account registration, and append-only usage records.

Queue B (corner) translations for the `entities` section.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    create_plan_payload,
    create_account_payload,
    create_tax_jurisdiction_payload,
    record_usage_payload,
    assert_plan,
    assert_account,
    assert_usage_record,
    NON_EXISTENT_UUID,
    setup_active_subscription,
    setup_jurisdiction_and_clock,
    create_jurisdiction,
)

ADMIN = TEST_USERS["billing_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


def test_create_plan_returns_201_active(api):
    """PRD §3.1: "Every plan begins with `status` of `ACTIVE`."

    Design: Corner/entities/create_plan_returns_201_with_system_fields
    """
    res = api.create_plan(
        create_plan_payload(tier="BASIC", monthly_fee_cents=3000, trial_days=7), ADMIN
    )
    plan = validate_success(res, 201)
    assert_plan(plan)
    assert plan["status"] == "ACTIVE", f"new plan status, got {plan['status']}"


def test_create_plan_missing_monthly_fee_returns_invalid_request(api):
    """PRD §3.1: "A **plan** is created with a `tier` drawn from `BASIC`, `PRO`, or `ENTERPRISE`, a recurring `monthly_fee_cents` that must be zero or greater". PRD §2.7: "the body itself is validated for well-formedness (required fields present, enums within their allowed sets, numbers within range), failing with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_plan_missing_required_field_returns_invalid_request
    """
    payload = create_plan_payload(tier="BASIC")
    del payload["monthly_fee_cents"]
    res = api.create_plan(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_plan_defaults_trial_days_to_zero(api):
    """PRD §3.1: "It may also carry `trial_days`, the default trial length in days for subscriptions opened on this plan, which is zero or greater and defaults to 0 when omitted."

    Design: Corner/entities/create_plan_default_trial_days_zero_when_omitted
    """
    payload = create_plan_payload(tier="PRO", monthly_fee_cents=9000)
    del payload["trial_days"]
    plan = validate_success(api.create_plan(payload, ADMIN), 201)
    assert plan["trial_days"] == 0, f"omitted trial_days should default to 0, got {plan['trial_days']}"


def test_get_nonexistent_plan_returns_not_found(api):
    """PRD §2.8: "the system validates the chain of identifiers strictly left-to-right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve."

    Design: Corner/entities/get_plan_nonexistent_id_returns_not_found
    """
    res = api.get_plan(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_account_resolves_jurisdiction_and_zero_mrr(api):
    """PRD §3.2: "At creation the system resolves the matching jurisdiction and stores its `id` as the account's `tax_jurisdiction_id`". PRD §3.2: "A new account starts with `status` of `ACTIVE` and `mrr_cents` of 0."

    Design: Corner/entities/create_account_resolves_tax_jurisdiction_from_region_code
    """
    jur = create_jurisdiction(region_code="US-CA", tax_rate_bps=875)
    res = api.create_account(
        create_account_payload(email="comp@x.com", company_name="CompCo", region_code="US-CA"),
        ANON,
    )
    account = validate_success(res, 201)
    assert_account(account)
    assert account["tax_jurisdiction_id"] == jur["id"], (
        f"tax_jurisdiction_id should resolve to {jur['id']}, got {account['tax_jurisdiction_id']}"
    )
    assert account["mrr_cents"] == 0, f"new account mrr_cents, got {account['mrr_cents']}"


def test_create_account_unknown_region_returns_jurisdiction_not_found(api):
    """PRD §3.2: "if no jurisdiction has that `region_code` the registration is rejected with `ERR_JURISDICTION_NOT_FOUND`."

    Design: Corner/entities/create_account_unknown_region_code_returns_jurisdiction_not_found
    """
    res = api.create_account(
        create_account_payload(email="nojur@x.com", company_name="NoJur", region_code="US-ZZ"),
        ANON,
    )
    validate_error(res, "ERR_JURISDICTION_NOT_FOUND")


def test_duplicate_account_email_returns_duplicate(api):
    """PRD §3.2: "Creating an **account** requires an `email` that is unique across accounts".
    PRD §3.2: "A duplicate `email` is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_account_email_returns_duplicate
    """
    create_jurisdiction(region_code="US-CA", tax_rate_bps=875)
    first = api.create_account(
        create_account_payload(email="dup@x.com", company_name="First", region_code="US-CA"), ANON
    )
    validate_success(first, 201)
    res = api.create_account(
        create_account_payload(email="dup@x.com", company_name="Second", region_code="US-CA"), ANON
    )
    validate_error(res, "ERR_DUPLICATE")


def test_usage_record_is_appended_unbilled(api):
    """PRD §3.4: "Each accepted event is appended as a usage record carrying its `subscription_id`, the supplied `units` and `recorded_at`, and a `billed` flag that starts false." PRD §2.4: "A `UsageRecord` is an append-only metering event: it carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/usage_record_immutable_entity_has_no_version
    """
    plan, account, sub = setup_active_subscription(plan_tier="BASIC", email="imm@x.com")
    res = api.record_usage(
        account["id"],
        sub["id"],
        record_usage_payload(50, "2026-06-05T00:00:00Z"),
        _owner(account["id"]),
    )
    record = validate_success(res, 201)
    assert_usage_record(record)
    assert record["billed"] is False, f"new usage record billed flag, got {record['billed']}"
