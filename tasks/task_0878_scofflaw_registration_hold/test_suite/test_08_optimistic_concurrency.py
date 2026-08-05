"""Optimistic concurrency control on ScofflawCase.version for the two guarded writes.

Covers corner cross_cutting instances plan_create_stale_version_returns_412 and
boot_dispatch_stale_version_returns_412.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_case_with_violations, setup_scofflaw_boot_eligible,
    case_version, make_owner_headers, make_enforcement_headers,
    create_payment_plan_payload, create_boot_tow_order_payload,
)


def test_plan_create_with_stale_case_version_rejected(api):
    """PRD §2.4: "Creating a payment plan for a case requires the caller to submit
    expected_scofflaw_case_version, carrying the version of the ScofflawCase the client
    last observed. If that value does not equal the case's current version — because
    another writer has advanced it since the client last read the case — the request is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/plan_create_stale_version_returns_412
    """
    owner, _, case, _ = setup_case_with_violations(2, 30000)
    ver = case_version(case["id"], make_owner_headers(owner["id"]))
    # Plan A succeeds and bumps the case version.
    validate_success(api.create_payment_plan(
        case["id"],
        create_payment_plan_payload(ver, total_amount_cents=60000,
                                    installment_count=6, down_payment_cents=6000),
        make_owner_headers(owner["id"])), 201)
    # Plan B carries the now-stale pre-A version.
    res = api.create_payment_plan(
        case["id"],
        create_payment_plan_payload(ver, total_amount_cents=60000,
                                    installment_count=6, down_payment_cents=6000),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_boot_dispatch_with_stale_case_version_rejected(api):
    """PRD §2.4: "Dispatching a boot or tow order carries the identical guard: it, too,
    requires expected_scofflaw_case_version to equal the case's current version, and a
    mismatch is rejected with ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting/boot_dispatch_stale_version_returns_412
    """
    _, _, case, _ = setup_scofflaw_boot_eligible(fine_each=13000, count=5)
    ver = case_version(case["id"])
    # Dispatch A succeeds and bumps the case version.
    validate_success(api.create_boot_tow_order(
        case["id"], create_boot_tow_order_payload(ver, action_type="BOOT"),
        make_enforcement_headers("eo-d")), 201)
    # Dispatch B carries the stale pre-A version.
    res = api.create_boot_tow_order(
        case["id"], create_boot_tow_order_payload(ver, action_type="BOOT"),
        make_enforcement_headers("eo-d"))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
