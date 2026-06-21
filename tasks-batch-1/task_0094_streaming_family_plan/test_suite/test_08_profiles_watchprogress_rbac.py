"""Profiles and parental controls, watch-progress upsert, RBAC denials, the
reactivate state-vs-fiscal precedence, and the archived-profile soft-delete
semantics.

Translates Difficulty/priority_pair_validation_conflict (state beats fiscal),
and Corner/validations + Corner/calculations + Corner/endpoints + Corner/rbac +
Corner/cross_cutting_complexity_layers instances.
"""
from test_helpers import (
    make_admin_headers,
    make_owner_headers,
    make_profile_headers,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)
import test_helpers as h


# ---------------------------------------------------------------------------
# Priority precedence: state legality beats fiscal sufficiency on reactivate
# ---------------------------------------------------------------------------

def test_reactivate_active_account_state_beats_fiscal(api):
    """PRD §3.10: "after which state legality is checked with ERR_INVALID_STATE
    ... alongside ... the fiscal-sufficiency check (ERR_INSUFFICIENT_CREDIT)."
    PRD §3.2: "Reactivation is the revert leg of this loop: it is permitted only
    while the account is SUSPENDED".

    An ACTIVE (non-SUSPENDED) account with wallet 0 fails both the state check and
    the credit check; the higher-priority state check wins with ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reactivate
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="owner10@x.com", initial_credit_cents=0)
    resp = api.reactivate_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Profile caps, duplicates, and parental-control rating ceiling
# ---------------------------------------------------------------------------

def test_profile_cap_reached_on_create(api):
    """PRD §3.4: a profile "may be created only while the account is ACTIVE, only
    while the count of non-ARCHIVED profiles remains below the plan's max_profiles
    (otherwise ERR_PROFILE_CAP_REACHED)".

    Design: Corner/validations/profile_cap_reached_on_create
    """
    plan = h.create_ad_supported_plan(max_profiles=1, concurrent_stream_cap=1,
                                      max_registered_devices=2, download_quota_per_profile=1,
                                      monthly_fee_cents=300)
    account = h.create_account(plan["id"], owner_email="cap@x.com")
    h.create_profile(account["id"], display_name="Only", kind="ADULT")

    resp = api.create_profile(
        {"account_id": account["id"], "display_name": "Extra", "kind": "TEEN"},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROFILE_CAP_REACHED.value, 409)


def test_duplicate_display_name_rejected(api):
    """PRD §3.4: a profile may be created "only when the display_name is unique
    among the account's non-ARCHIVED profiles (otherwise ERR_DUPLICATE)."

    Design: Corner/validations/duplicate_display_name_rejected
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="dup@x.com")
    h.create_profile(account["id"], display_name="Sam", kind="ADULT")

    resp = api.create_profile(
        {"account_id": account["id"], "display_name": "Sam", "kind": "TEEN"},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value, 409)


def test_rating_ceiling_tightened_by_parental_control(api):
    """PRD §2.8: "When a ParentalControl row exists for the profile,
    max_rating_allowed becomes the stricter (the lower on the ordered scale) of
    that kind default and the control's max_rating". PRD §3.4: "Setting or
    replacing the control recomputes the profile's max_rating_allowed as the
    stricter of the kind default and the control's max_rating".

    ADULT (default NC17) + control max_rating PG13 => ceiling drops to PG13.

    Design: Corner/calculations/rating_ceiling_tightened_by_control
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="tighten@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    h.set_parental_control(account["id"], profile["id"], max_rating="PG13",
                           daily_watch_limit_minutes=0, curfew_start_min=0, curfew_end_min=0)
    prof = h.fetch_profile(account["id"], profile["id"])
    assert prof["max_rating_allowed"] == "PG13"


# ---------------------------------------------------------------------------
# Watch-progress upsert
# ---------------------------------------------------------------------------

def test_watch_progress_completed_when_position_reaches_runtime(api):
    """PRD §3.9: "On each upsert the row's completed flag is recomputed to true
    once position_min reaches the title's runtime_minutes, and false otherwise."

    Design: Corner/endpoints/watch_progress_completed_computed
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Ep", maturity_rating="PG", runtime_minutes=60, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="wp@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)

    resp = api.upsert_watch_progress(
        {"profile_id": profile["id"], "title_id": title["id"], "position_min": 60,
         "last_device_id": device["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 200)["completed"] is True


def test_watch_progress_upsert_same_pair_updates_in_place(api):
    """PRD §3.9: "At most one row may exist per profile-and-title pair, so a second
    upsert against the same pair replaces the first rather than duplicating it".

    Design: Corner/endpoints/watch_progress_upsert_same_pair_updates
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Ep", maturity_rating="PG", runtime_minutes=60, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="wp2@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    first = api.upsert_watch_progress(
        {"profile_id": profile["id"], "title_id": title["id"], "position_min": 10,
         "last_device_id": device["id"]},
        make_profile_headers(profile["id"]),
    )
    first_data = validate_success(first, 200)

    second = api.upsert_watch_progress(
        {"profile_id": profile["id"], "title_id": title["id"], "position_min": 25,
         "last_device_id": device["id"]},
        make_profile_headers(profile["id"]),
    )
    second_data = validate_success(second, 200)
    assert second_data["position_min"] == 25
    assert second_data["id"] == first_data["id"]


# ---------------------------------------------------------------------------
# RBAC denials
# ---------------------------------------------------------------------------

def test_profileuser_cannot_create_plan(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE." PRD §4: POST /subscription-plans is authorized for
    PlatformAdmin only.

    Design: Corner/rbac/profileuser_cannot_create_plan
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="rb@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")

    resp = api.create_subscription_plan(
        {"tier": "AD_FREE", "monthly_fee_cents": 1, "max_profiles": 1,
         "concurrent_stream_cap": 1, "max_registered_devices": 1,
         "download_quota_per_profile": 0, "ad_free": True, "hd_offline_allowed": False},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_account_owner_cannot_suspend_other_account(api):
    """PRD §2.1: "When an entity-backed role is well-formed and permitted but does
    not own the resource it targets, the request is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/account_owner_cannot_suspend_other_account
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    acct_a = h.create_account(plan["id"], owner_email="oa@x.com")
    acct_b = h.create_account(plan["id"], owner_email="ob@x.com")
    # Owner of A attempts to suspend B.
    resp = api.suspend_account(
        acct_b["id"], {"expected_account_version": acct_b["version"]},
        make_owner_headers(acct_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "When either header is missing or malformed on an endpoint that
    requires authentication, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="ua@x.com")
    # Send POST /profiles with NO auth headers.
    resp = api.create_profile(
        {"account_id": account["id"], "display_name": "P", "kind": "ADULT"},
        {"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ---------------------------------------------------------------------------
# Archived-profile soft-delete semantics
# ---------------------------------------------------------------------------

def test_archived_profile_excluded_and_name_reusable(api):
    """PRD §3.4: "Archiving a profile drives it from ACTIVE to ARCHIVED". PRD §3.4:
    a profile may be created "only when the display_name is unique among the
    account's non-ARCHIVED profiles". PRD §3.10: account-scoped profile lists are
    "narrowed by a status filter".

    Design: Corner/cross_cutting_complexity_layers/archived_profile_excluded_and_name_reusable
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="arch@x.com")
    profile = h.create_profile(account["id"], display_name="Gone", kind="ADULT")
    h.api_client.archive_profile(profile["id"], make_owner_headers(account["id"]))

    listed = api.list_account_profiles(account["id"], make_owner_headers(account["id"]),
                                       params={"status": "ACTIVE"})
    data, meta = validate_paginated(listed)
    assert all(p["id"] != profile["id"] for p in data), "archived profile must be excluded"

    reuse = api.create_profile(
        {"account_id": account["id"], "display_name": "Gone", "kind": "TEEN"},
        make_owner_headers(account["id"]),
    )
    validate_success(reuse, 201)
