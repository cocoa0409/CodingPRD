"""Catalog and account creation basics: required fields, defaults, computed
ceilings, system fields, type constraints, not-found, and listing envelope.

All tests here translate Corner/entities instances.
"""
from test_helpers import (
    api_client,
    make_admin_headers,
    make_owner_headers,
    validate_success,
    validate_error,
    validate_paginated,
    assert_subscription_plan,
    assert_account,
    is_valid_uuid,
    ApiErrorId,
)
import test_helpers as h


def test_create_subscription_plan_returns_201_all_fields(api):
    """PRD §3.1: "A subscription tier is created by supplying its tier — one of
    AD_SUPPORTED, AD_FREE, or PREMIUM — together with its monthly_fee_cents (a
    non-negative integer), its quota knobs max_profiles (at least 1),
    concurrent_stream_cap (at least 1), max_registered_devices (at least 1), and
    download_quota_per_profile (zero or more), and two playback flags."
    PRD §4: "Operations that create a brand-new resource return 201 Created".

    Design: Corner/entities/create_subscription_plan_returns_201_all_fields
    """
    resp = api.create_subscription_plan(
        h.create_plan_payload(
            tier="AD_FREE", monthly_fee_cents=800, max_profiles=4,
            concurrent_stream_cap=2, max_registered_devices=4,
            download_quota_per_profile=3, ad_free=True, hd_offline_allowed=False,
        ),
        make_admin_headers(),
    )
    data = validate_success(resp, 201)
    assert_subscription_plan(data)
    assert data["tier"] == "AD_FREE"
    assert data["monthly_fee_cents"] == 800
    assert data["ad_free"] is True
    assert is_valid_uuid(data["id"]), "id must be a bare UUID with no type prefix"


def test_create_account_default_status_active_billing_open(api):
    """PRD §3.2: "On creation the Account starts in ACTIVE status with
    billing_status set to OPEN, its wallet_credit_cents seeded to the supplied
    initial_credit_cents (or 0 when omitted), and period_charge_cents seeded to
    the plan's full-period fee."
    PRD §2.4: an integer "version that begins at its initial value and increments
    by one on each modification."

    Design: Corner/entities/create_account_default_status_active_billing_open
    """
    plan = h.create_plan()
    resp = api.create_account(
        h.create_account_payload(plan["id"], owner_email="def@x.com", billing_anchor_day=1),
        make_owner_headers("bootstrap"),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["billing_status"] == "OPEN"
    assert data["wallet_credit_cents"] == 0
    assert data["version"] == 1


def test_title_downloadable_default_true(api):
    """PRD §3.1: "a downloadable flag that defaults to true when omitted".

    Design: Corner/entities/title_downloadable_default_true
    """
    resp = api.create_title(
        {"name": "Def", "maturity_rating": "PG", "runtime_minutes": 30, "license_size_mb": 200},
        make_admin_headers(),
    )
    data = validate_success(resp, 201)
    assert data["downloadable"] is True


def test_profile_max_rating_allowed_computed_from_kind(api):
    """PRD §2.8: "The rating ceiling computation establishes a per-kind default: a
    KID profile defaults to G, a TEEN profile to PG13, and an ADULT profile to
    NC17." PRD §3.4: a new profile's "max_rating_allowed is computed straight from
    its kind since no control yet exists."

    Design: Corner/entities/profile_max_rating_allowed_computed_from_kind
    """
    plan = h.create_plan()
    account = h.create_account(plan["id"], owner_email="ceil@x.com")
    kid = h.create_profile(account["id"], display_name="K", kind="KID")
    adult = h.create_profile(account["id"], display_name="A", kind="ADULT")
    assert kid["max_rating_allowed"] == "G"
    assert adult["max_rating_allowed"] == "NC17"


def test_system_fields_seeded_on_account_create(api):
    """PRD §3.2: "On creation the Account starts in ACTIVE status with
    billing_status set to OPEN, its wallet_credit_cents seeded to the supplied
    initial_credit_cents (or 0 when omitted), and period_charge_cents seeded to
    the plan's full-period fee."

    Design: Corner/entities/system_fields_input_ignored_on_account_create
    """
    plan = h.create_plan()
    resp = api.create_account(
        h.create_account_payload(plan["id"], owner_email="sys@x.com", billing_anchor_day=1,
                                 initial_credit_cents=500),
        make_owner_headers("bootstrap"),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["wallet_credit_cents"] == 500


def test_invalid_enum_kind_returns_invalid_request(api):
    """PRD §3.10: "Field-level schema validation — required fields present, enums
    within their allowed sets, integers within their declared ranges — is the
    lowest-priority check and surfaces as ERR_INVALID_REQUEST".
    PRD §3.4: a profile's "kind of ADULT, TEEN, or KID."

    Design: Corner/entities/invalid_enum_kind_returns_invalid_request
    """
    plan = h.create_plan()
    account = h.create_account(plan["id"], owner_email="enum@x.com")
    resp = api.create_profile(
        {"account_id": account["id"], "display_name": "Bad", "kind": "GROWNUP"},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_missing_required_field_on_plan_create_returns_invalid_request(api):
    """PRD §3.10: "Field-level schema validation — required fields present, enums
    within their allowed sets, integers within their declared ranges — is the
    lowest-priority check and surfaces as ERR_INVALID_REQUEST".

    Design: Corner/entities/missing_required_field_on_plan_create_returns_invalid_request
    """
    resp = api.create_subscription_plan(
        {"tier": "AD_FREE", "monthly_fee_cents": 800, "max_profiles": 4,
         "max_registered_devices": 4, "download_quota_per_profile": 3,
         "ad_free": True, "hd_offline_allowed": False},
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_account_not_found_returns_not_found(api):
    """PRD §2.4: "the first identifier that fails to resolve to a stored entity
    yields ERR_NOT_FOUND before any later identifier is examined."

    Design: Corner/entities/account_not_found_returns_not_found
    """
    resp = api.get_account("00000000-0000-4000-8000-000000000000", make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_profiles_pagination_envelope(api):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope, where total_count is the size
    of the full unpaged result set and has_more indicates whether items remain
    beyond the current page."

    Design: Corner/entities/list_profiles_pagination_envelope
    """
    plan = h.create_plan()
    account = h.create_account(plan["id"], owner_email="list@x.com")
    h.create_profile(account["id"], display_name="P1", kind="ADULT")
    h.create_profile(account["id"], display_name="P2", kind="TEEN")
    resp = api.list_account_profiles(account["id"], make_owner_headers(account["id"]))
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
