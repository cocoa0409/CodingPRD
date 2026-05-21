"""Account CRUD, settings, OCC, and closure tests.

PRD §3.1 covers creation and configuration; PRD §2.7 covers OCC;
PRD §3.1 also covers the deliberate close action and obligations.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_account,
    assert_version_incremented_by,
    create_account,
    create_account_payload,
    ingest_hov_fraud_event,
    make_account_holder_headers,
    patch_account_payload,
    setup_account_with_vehicle,
    setup_suspended_account_via_two_hov_frauds,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Creation defaults — PRD §3.1
# ---------------------------------------------------------------------------
def test_account_create_defaults(api):
    """PRD §3.1: "A new account begins in the `ACTIVE` state with
    `balance_cents` of 0 and `outstanding_fine_cents` of 0."

    Claim: a freshly created Account has status=ACTIVE, balance_cents=0,
    outstanding_fine_cents=0.
    """
    res = api.create_account(
        create_account_payload(holder_name="Alpha"),
        TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert_account(data)
    assert data["status"] == "ACTIVE"
    assert data["balance_cents"] == 0
    assert data["outstanding_fine_cents"] == 0
    assert data["holder_name"] == "Alpha"
    assert data["version"] == 1


def test_account_create_threshold_default(api):
    """PRD §3.1: "`auto_reload_threshold_cents`, the breakpoint at or
    below which the system will automatically credit the account,
    accepts any integer from 0 through 10000 inclusive and defaults
    to 1000".

    Claim: omitting auto_reload_threshold_cents on POST /accounts
    results in auto_reload_threshold_cents == 1000.
    """
    res = api.create_account(
        create_account_payload(holder_name="Beta"),
        TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert data["auto_reload_threshold_cents"] == 1000


def test_account_create_topup_default(api):
    """PRD §3.1: "`auto_reload_topup_cents`, the credit amount, accepts
    any integer from 1000 through 20000 inclusive and defaults to 4000".

    Claim: omitting auto_reload_topup_cents on POST /accounts results
    in auto_reload_topup_cents == 4000.
    """
    res = api.create_account(
        create_account_payload(holder_name="Gamma"),
        TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert data["auto_reload_topup_cents"] == 4000


# ---------------------------------------------------------------------------
# PRD §3.2 referenced via §3.1 — home_agency enum
# ---------------------------------------------------------------------------
def test_account_create_with_each_agency_code(api):
    """PRD §3.1: "a `home_agency_code` chosen from `NY_EZPASS`,
    `NJ_EZPASS`, `PA_TURNPIKE`, or `FL_SUNPASS`."

    Claim: each of the four declared agency codes is accepted.
    """
    for code in ("NY_EZPASS", "NJ_EZPASS", "PA_TURNPIKE", "FL_SUNPASS"):
        res = api.create_account(
            create_account_payload(home_agency_code=code),
            TEST_USERS["agency_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["home_agency_code"] == code


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def test_account_get_nonexistent(api):
    """PRD §2.5 / §5: path lookup that fails → ERR_NOT_FOUND.

    Claim: GET /accounts/{nonexistent} → 404 ERR_NOT_FOUND.
    """
    res = api.get_account(NON_EXISTENT_UUID,
                          TEST_USERS["agency_admin_headers"])
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_account_list_paginated(api):
    """PRD §2.3: list endpoints page through `limit`/`offset` and
    surface limit/offset/total_count/has_more.

    Claim: GET /accounts returns paginated meta with the four fields.
    """
    create_account(home_agency_code="NY_EZPASS")
    create_account(home_agency_code="NY_EZPASS")
    create_account(home_agency_code="NY_EZPASS")
    res = api.list_accounts(TEST_USERS["agency_admin_headers"])
    data, meta = validate_paginated(res)
    assert meta["total_count"] >= 3
    assert "limit" in meta and "offset" in meta and "has_more" in meta


# ---------------------------------------------------------------------------
# Summary view
# ---------------------------------------------------------------------------
def test_account_summary_returns_account_shape(api):
    """PRD §3.1: "A read of the account through either the regular
    fetch or the dedicated summary view returns the same `Account`
    shape, including the live `balance_cents`, `outstanding_fine_cents`,
    and `status` values."

    Claim: GET /accounts/{id}/summary returns an Account-shaped object
    carrying balance_cents, outstanding_fine_cents, and status.
    """
    a = create_account()
    res = api.get_account_summary(
        a["id"], TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=200)
    assert data["id"] == a["id"]
    assert "balance_cents" in data
    assert "outstanding_fine_cents" in data
    assert "status" in data


# ---------------------------------------------------------------------------
# PATCH + OCC — PRD §2.7
# ---------------------------------------------------------------------------
def test_patch_account_increments_version(api):
    """PRD §2.4: "an integer `version` that starts at 1 and increments
    by 1 on every mutation."
    PRD §2.7: "After any successful mutation the resource's `version`
    increments by one and `updated_at` is refreshed."

    Claim: PATCH /accounts/{id} (auto_reload_threshold_cents tweak)
    increments version by 1.
    """
    a = create_account()
    old = a["version"]
    res = api.patch_account(
        a["id"],
        patch_account_payload(auto_reload_threshold_cents=2500),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=200)
    assert_version_incremented_by(data["version"], old, 1)
    assert data["auto_reload_threshold_cents"] == 2500


def test_patch_account_stale_version_rejected(api):
    """PRD §2.7: "When `version` is present and does not match the
    current `Account.version` on the server, the request is rejected
    with `ERR_VERSION_CONFLICT`."

    Claim: PATCH carrying a stale version → 409 ERR_VERSION_CONFLICT.
    """
    a = create_account()
    stale_version = a["version"]
    # First successful patch bumps the version.
    api.patch_account(
        a["id"],
        patch_account_payload(auto_reload_threshold_cents=2000),
        make_account_holder_headers(a["id"]),
    )
    # Second patch with the stale version is rejected.
    res = api.patch_account(
        a["id"],
        patch_account_payload(
            auto_reload_threshold_cents=3000, version=stale_version,
        ),
        make_account_holder_headers(a["id"]),
    )
    validate_error(res, "ERR_VERSION_CONFLICT", expected_status=409)


def test_patch_account_omitted_version_succeeds(api):
    """PRD §2.7: "When `version` is omitted from the request body, the
    server processes the mutation without an OCC check."

    Claim: PATCH without a version field succeeds regardless of stale
    expectations.
    """
    a = create_account()
    # Bump version once.
    api.patch_account(
        a["id"],
        patch_account_payload(auto_reload_threshold_cents=2000),
        make_account_holder_headers(a["id"]),
    )
    # Now patch without a version — should succeed.
    res = api.patch_account(
        a["id"],
        patch_account_payload(auto_reload_threshold_cents=3000),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=200)
    assert data["auto_reload_threshold_cents"] == 3000


# ---------------------------------------------------------------------------
# Closure — PRD §3.1
# ---------------------------------------------------------------------------
def test_account_close_with_zero_obligations_succeeds(api):
    """PRD §3.1: "The transition from `ACTIVE` to `CLOSED` is permitted
    only when `outstanding_fine_cents` is exactly 0 *and* no
    transponder owned by the account is in `ACTIVE` or `SUSPENDED`
    status — every transponder on the account must be either `UNBOUND`
    or `RETURNED`."

    Claim: a fresh account with no fines and no active transponders
    closes successfully (HTTP 204).
    """
    a = create_account()
    res = api.delete_account(a["id"], TEST_USERS["agency_admin_headers"])
    assert res.status_code == 204


def test_account_close_cascades_vehicles_to_blocked(api):
    """PRD §3.1: "On a successful close the account transitions to
    `CLOSED` and every vehicle owned by the account cascades to
    `BLOCKED`."

    Claim: after close, every Vehicle.status == BLOCKED.
    """
    a, v = setup_account_with_vehicle()
    api.delete_account(a["id"], TEST_USERS["agency_admin_headers"])
    res = api.get_vehicle(
        a["id"], v["id"], TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=200)
    assert data["status"] == "BLOCKED"


def test_account_close_with_outstanding_fines_rejected(api):
    """PRD §3.1: "Otherwise the request is rejected with
    `ERR_ACCOUNT_HAS_OBLIGATIONS`."

    Note: per PRD §2.11, when the account is ACTIVE but has fines, the
    state precondition is satisfied; only ERR_ACCOUNT_HAS_OBLIGATIONS
    fires.

    Claim: an ACTIVE account with outstanding fines below the
    suspension threshold but > 0 → DELETE rejected with
    ERR_ACCOUNT_HAS_OBLIGATIONS.
    """
    # Build a single HOV fraud (one fine = 10230 cents < 15000 threshold)
    # so the account stays ACTIVE while outstanding > 0.
    a = create_account(home_agency_code="NY_EZPASS")
    v = api.create_vehicle(
        a["id"],
        {"plate_number": "OBLIG1", "plate_state": "NY", "axle_count": 2,
         "hov_capable": True},
        make_account_holder_headers(a["id"]),
    )
    v_data = validate_success(v, expected_status=201)
    ingest_hov_fraud_event(a, v_data, base_rate_cents=200,
                           agency_code="NY_EZPASS")
    # Confirm account remained ACTIVE.
    refreshed = validate_success(
        api.get_account(a["id"], TEST_USERS["agency_admin_headers"]),
        expected_status=200,
    )
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["outstanding_fine_cents"] > 0

    res = api.delete_account(a["id"], TEST_USERS["agency_admin_headers"])
    validate_error(res, "ERR_ACCOUNT_HAS_OBLIGATIONS",
                   expected_status=409)


def test_account_close_with_active_transponder_rejected(api):
    """PRD §3.1: "no transponder owned by the account is in `ACTIVE` or
    `SUSPENDED` status — every transponder on the account must be
    either `UNBOUND` or `RETURNED`. Otherwise the request is rejected
    with `ERR_ACCOUNT_HAS_OBLIGATIONS`."

    Claim: account with an ACTIVE transponder cannot be closed.
    """
    from test_helpers import setup_account_with_bound_transponder
    a, v, t = setup_account_with_bound_transponder()
    res = api.delete_account(a["id"], TEST_USERS["agency_admin_headers"])
    validate_error(res, "ERR_ACCOUNT_HAS_OBLIGATIONS",
                   expected_status=409)


# ---------------------------------------------------------------------------
# Holder-name length — PRD §3.1
# ---------------------------------------------------------------------------
def test_account_create_holder_name_too_long_rejected(api):
    """PRD §3.1: "An `AgencyAdmin` creates a new account by supplying the
    customer's `holder_name` (between 1 and 120 characters in length)
    and a `home_agency_code` chosen from `NY_EZPASS`, `NJ_EZPASS`,
    `PA_TURNPIKE`, or `FL_SUNPASS`."

    Claim: a 121-character holder_name → 422 ERR_VALIDATION.
    """
    res = api.create_account(
        create_account_payload(holder_name="X" * 121),
        TEST_USERS["agency_admin_headers"],
    )
    assert res.status_code == 422
    body = res.json()
    assert body["data"]["error_id"] == "ERR_VALIDATION"


def test_account_create_holder_name_empty_rejected(api):
    """PRD §3.1: "An `AgencyAdmin` creates a new account by supplying the
    customer's `holder_name` (between 1 and 120 characters in length)
    and a `home_agency_code` chosen from `NY_EZPASS`, `NJ_EZPASS`,
    `PA_TURNPIKE`, or `FL_SUNPASS`."

    Claim: an empty holder_name → 422 ERR_VALIDATION.
    """
    res = api.create_account(
        create_account_payload(holder_name=""),
        TEST_USERS["agency_admin_headers"],
    )
    assert res.status_code == 422
    body = res.json()
    assert body["data"]["error_id"] == "ERR_VALIDATION"
