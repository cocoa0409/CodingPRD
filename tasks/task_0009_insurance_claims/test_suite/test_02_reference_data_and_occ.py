"""Reference-data CRUD and optimistic concurrency control.

Pinned to PRD §2.4 (common fields), §2.10 (OCC), §3.9 (reference data).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_policy_payload, create_adjuster_payload, create_repair_shop_payload,
    create_policy, create_adjuster, create_repair_shop,
    patch_policy_status, get_policy, get_repair_shop,
    is_valid_uuid, is_iso8601_timestamp,
    assert_policy, assert_adjuster, assert_repair_shop,
    days_ago, days_ahead,
)


# ─── §2.4 common fields ───────────────────────────────────────────
def test_policy_carries_id_created_updated_version(api, admin_headers):
    """PRD §2.4: "Top-level resources whose lifecycles include modification
    — `Policy`, `Adjuster`, `RepairShop`, `Claim`, `Investigation`, `Appeal`,
    and `Payout` — carry four system-managed fields: `id` ... `created_at`
    ... `updated_at` ... `version`: an integer that starts at 1 on creation
    and increments by 1 on every persisted mutation of the resource."

    Claim: a freshly-created Policy carries id, created_at, updated_at, version==1.
    """
    policy = create_policy()
    assert is_valid_uuid(policy["id"])
    assert is_iso8601_timestamp(policy["created_at"])
    assert is_iso8601_timestamp(policy["updated_at"])
    assert policy["version"] == 1
    assert_policy(policy)


def test_adjuster_carries_common_fields(api, admin_headers):
    """PRD §2.4: a freshly-created Adjuster carries id, created_at, updated_at, version==1."""
    a = create_adjuster()
    assert is_valid_uuid(a["id"])
    assert is_iso8601_timestamp(a["created_at"])
    assert is_iso8601_timestamp(a["updated_at"])
    assert a["version"] == 1
    assert_adjuster(a)


def test_repair_shop_starts_with_trust_one_active(api, admin_headers):
    """PRD §2.11: "A `RepairShop` carries a `trust_score` that begins at
    1.00 on creation and decays as repair-shop-collusion fraud signals
    accumulate against the shop."

    PRD §3.9: "the shop starts at `trust_score` 1.00 and `status` `ACTIVE`."

    Claim: new shop has trust_score 1.00 and status ACTIVE.
    """
    s = create_repair_shop()
    assert s["trust_score"] == 1.00
    assert s["status"] == "ACTIVE"
    assert_repair_shop(s)


# ─── §3.9 / §2.6 policy creation defaults ─────────────────────────
def test_policy_default_status_active(api, admin_headers):
    """PRD §3.9: "the policy's `status` is automatically set to `ACTIVE`
    on creation, and may later be moved to `SUSPENDED`, `EXPIRED`, or
    `CANCELLED` via the policy update capability"

    Claim: newly-created Policy has status ACTIVE.
    """
    policy = create_policy()
    assert policy["status"] == "ACTIVE"


def test_policy_reporting_window_defaults_to_30(api, admin_headers):
    """PRD §2.6: "The `reporting_window_days` is at least 1, and when omitted
    at policy creation it defaults to 30 days."

    Claim: omitting reporting_window_days at creation -> 30.
    """
    payload = create_policy_payload(reporting_window_days=None)
    res = api.create_policy(payload, admin_headers)
    policy = validate_success(res, expected_status=201)
    assert policy["reporting_window_days"] == 30


def test_policy_number_too_short_rejected(api, admin_headers):
    """PRD §2.6: "the `policy_number` is a unique uppercase alphanumeric
    string of length between 8 and 24 characters inclusive."

    Claim: policy_number of length 7 -> ERR_VALIDATION_FAILED.
    """
    payload = create_policy_payload(policy_number="ABC1234")  # length 7
    res = api.create_policy(payload, admin_headers)
    validate_error(res, "ERR_VALIDATION_FAILED")


def test_policy_number_too_long_rejected(api, admin_headers):
    """PRD §2.6: "the `policy_number` is a unique uppercase alphanumeric
    string of length between 8 and 24 characters inclusive."

    Claim: policy_number of length 25 -> ERR_VALIDATION_FAILED.
    """
    payload = create_policy_payload(policy_number="A" * 25)
    res = api.create_policy(payload, admin_headers)
    validate_error(res, "ERR_VALIDATION_FAILED")


# ─── §2.10 OCC ────────────────────────────────────────────────────
def test_policy_patch_with_correct_version_succeeds_and_increments(api, admin_headers):
    """PRD §2.10: "Modification endpoints for the reference-data resources
    — the policy update endpoint, the adjuster update endpoint, and the
    repair-shop update endpoint — accept an optional `version` field in
    the request body. When `version` is present, the server compares it
    to the resource's current `version`; a mismatch is rejected with
    `ERR_VERSION_CONFLICT`. When `version` is omitted, the server processes
    the mutation without performing the OCC check. On a successful mutation,
    `version` increments by 1 and `updated_at` refreshes."

    Claim: PATCH with the correct version succeeds and bumps version by 1.
    """
    policy = create_policy()
    body = {"status": "SUSPENDED", "version": policy["version"]}
    res = api.patch_policy(policy["id"], body, admin_headers)
    updated = validate_success(res)
    assert updated["status"] == "SUSPENDED"
    assert updated["version"] == policy["version"] + 1


def test_policy_patch_with_stale_version_rejected(api, admin_headers):
    """PRD §2.10: "When `version` is present, the server compares it to the
    resource's current `version`; a mismatch is rejected with
    `ERR_VERSION_CONFLICT`."

    Claim: PATCH with a stale version -> ERR_VERSION_CONFLICT.
    """
    policy = create_policy()
    # Bump once with correct version.
    patch_policy_status(policy["id"], "SUSPENDED", version=policy["version"])
    # Now use the stale version.
    res = api.patch_policy(policy["id"], {"status": "EXPIRED", "version": policy["version"]}, admin_headers)
    validate_error(res, "ERR_VERSION_CONFLICT")


def test_policy_patch_without_version_skips_occ_check(api, admin_headers):
    """PRD §2.10: "When `version` is omitted, the server processes the
    mutation without performing the OCC check."

    Claim: PATCH without version succeeds even after the version has been
    bumped on the server (no OCC enforcement).
    """
    policy = create_policy()
    # Mutate once (bump version).
    patch_policy_status(policy["id"], "SUSPENDED", version=policy["version"])
    # Now PATCH without version — must succeed despite stale local view.
    res = api.patch_policy(policy["id"], {"status": "EXPIRED"}, admin_headers)
    updated = validate_success(res)
    assert updated["status"] == "EXPIRED"


def test_adjuster_patch_with_stale_version_rejected(api, admin_headers):
    """PRD §2.10: OCC also applies to PATCH /adjusters/{id}.

    Claim: stale version on adjuster PATCH -> ERR_VERSION_CONFLICT.
    """
    a = create_adjuster()
    # Bump once.
    res_first = api.patch_adjuster(a["id"], {"status": "SUSPENDED", "version": a["version"]}, admin_headers)
    validate_success(res_first)
    # Stale.
    res = api.patch_adjuster(a["id"], {"status": "ACTIVE", "version": a["version"]}, admin_headers)
    validate_error(res, "ERR_VERSION_CONFLICT")


def test_repair_shop_patch_with_stale_version_rejected(api, admin_headers):
    """PRD §2.10: OCC also applies to PATCH /repair-shops/{id}.

    Claim: stale version on repair-shop PATCH -> ERR_VERSION_CONFLICT.
    """
    s = create_repair_shop()
    res = api.patch_repair_shop(s["id"], {"status": "BLACKLISTED", "version": s["version"]}, admin_headers)
    validate_success(res)
    # Stale.
    res2 = api.patch_repair_shop(s["id"], {"status": "ACTIVE", "version": s["version"]}, admin_headers)
    validate_error(res2, "ERR_VERSION_CONFLICT")


# ─── RBAC on reference data ───────────────────────────────────────
def test_create_policy_requires_admin(api, customer_headers):
    """PRD §4 endpoints table: POST /policies authorised role is
    PlatformAdmin only.

    Claim: Customer calling POST /policies -> ERR_FORBIDDEN.
    """
    res = api.create_policy(create_policy_payload(), customer_headers)
    validate_error(res, "ERR_FORBIDDEN")


def test_create_adjuster_requires_admin(api, customer_headers):
    """PRD §4 endpoints table: POST /adjusters authorised role is
    PlatformAdmin only.

    Claim: Customer calling POST /adjusters -> ERR_FORBIDDEN.
    """
    res = api.create_adjuster(create_adjuster_payload(license_number="LIC-RB-1"), customer_headers)
    validate_error(res, "ERR_FORBIDDEN")


def test_create_repair_shop_requires_admin(api, customer_headers):
    """PRD §4 endpoints table: POST /repair-shops authorised role is
    PlatformAdmin only.

    Claim: Customer calling POST /repair-shops -> ERR_FORBIDDEN.
    """
    res = api.create_repair_shop(
        create_repair_shop_payload(name="X", tax_id=f"TAX-RB-1"),
        customer_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")
