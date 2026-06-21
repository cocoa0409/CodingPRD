"""Corner breadth tests for list endpoints, payment action, auth/RBAC errors,
optimistic-concurrency on confirm, derived-counter reconciliation, and immediate
consistency in the confirm response.

Covers corner sections: endpoints, errors, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    setup_open_season, setup_confirmed_subscription,
    register_member, confirm_subscription, get_season_version,
    make_member_headers,
    create_subscription_payload, create_payment_payload, create_pickup_site_payload,
    ApiErrorId, TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]
DC = TEST_USERS["delivery_coordinator_headers"]


# ─── endpoints ───────────────────────────────────────────────────────────────

def test_list_subscriptions_array_envelope_pagination(api):
    """PRD §2.2: "The `response_type` is either"object"for a single resource or"array"for a list of resources."
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_subscriptions_pagination_envelope
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    season_id = base["season"]["id"]
    for _ in range(2):
        member = register_member(tier="BASELINE")
        mh = make_member_headers(member["id"])
        get_success_data(api_client.create_subscription(
            create_subscription_payload(season_id, member["id"],
                                        base["share"]["id"], base["site"]["id"]), mh))

    data, meta = validate_paginated(
        api_client.list_subscriptions(FM, params={"season_id": season_id, "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count expected 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more expected True with limit 1 of 2"
    assert len(data) == 1


def test_list_ledger_entries_for_subscription(api):
    """PRD §3.3: "A `CHARGE_SEASON` ledger entry is posted for that amount."
    PRD §3.4: "Every financial movement on a subscription is recorded as an immutable, append-only **ledger entry** carrying a `subscription_id`, an `entry_type`, a signed `amount_cents`, and an optional free-text `memo".

    Design: Corner/endpoints/list_ledger_entries_reverse_reachability
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    confirm_subscription(base["season"]["id"], sub["id"])

    data, _meta = validate_paginated(
        api_client.list_ledger_entries(sub["id"], mh, params={"limit": 100}))
    charge = [e for e in data if e["entry_type"] == "CHARGE_SEASON"]
    assert charge, "expected a CHARGE_SEASON entry in the subscription's ledger"
    assert charge[0]["amount_cents"] == 50000


def test_apply_payment_reduces_outstanding_balance(api):
    """PRD §3.4: "A `Member` (or a `FarmManager` on their behalf) may apply a payment, which posts a `PAYMENT` entry with a negative amount and recomputes the balance."

    Design: Corner/endpoints/apply_payment_reduces_outstanding_balance
    """
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=10, signup_close_date="2026-12-25T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    # Outstanding starts at 50000.
    validate_success(api_client.create_payment(
        sub_id, create_payment_payload(20000, memo="partial"), mh), 201)
    sub = validate_success(api_client.get_subscription(sub_id, FM), 200)
    assert sub["outstanding_balance_cents"] == 30000, (
        f"balance expected 30000 (50000 − 20000), got {sub['outstanding_balance_cents']}")


# ─── errors ──────────────────────────────────────────────────────────────────

def test_confirm_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request to a protected endpoint that is missing either header, or that carries a malformed one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    sea_v = get_season_version(base["season"]["id"])
    # Confirm with no auth headers at all.
    res = api_client.confirm_subscription(
        sub["id"], {"expected_season_version": sea_v}, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── rbac ────────────────────────────────────────────────────────────────────

def test_member_cannot_confirm_subscription(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: confirm is authorized only for FarmManager.

    Design: Corner/rbac/member_cannot_confirm_subscription
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    sea_v = get_season_version(base["season"]["id"])
    # Member (the owner) calls a FarmManager-exclusive operation.
    res = api_client.confirm_subscription(sub["id"], {"expected_season_version": sea_v}, mh)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_farm_manager_cannot_create_pickup_site(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /pickup-sites is authorized only for DeliveryCoordinator.

    Design: Corner/rbac/farmmanager_cannot_create_pickup_site
    """
    season = get_success_data(api_client.create_season(
        {"name": "S-rbac2", "week_count": 10,
         "first_delivery_date": "2026-09-01T00:00:00Z",
         "signup_close_date": "2026-12-25T00:00:00Z", "total_share_capacity": 50}, FM))
    res = api_client.create_pickup_site(
        create_pickup_site_payload(season["id"], name="Site", kind="PICKUP",
                                   weekly_capacity=100), FM)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── cross_cutting_complexity_layers ─────────────────────────────────────────

def test_confirm_correct_season_version_succeeds_and_bumps(api):
    """PRD §2.9: "The request must carry `expected_season_version` matching the target season's current `version`. Each confirm increments the season's `version` (because it changes `confirmed_share_count`)".

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_correct_season_version_succeeds
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    season_id = base["season"]["id"]
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    sea_v = get_season_version(season_id)
    confirmed = validate_success(api_client.confirm_subscription(
        sub["id"], {"expected_season_version": sea_v}, FM), 200)
    assert confirmed["billing_status"] == "CONFIRMED"
    season_after = validate_success(api_client.get_season(season_id, FM), 200)
    assert season_after["version"] == sea_v + 1, (
        f"season version expected {sea_v + 1}, got {season_after['version']}")


def test_confirm_stale_season_version_rejected(api):
    """PRD §2.9: "if another writer has advanced the season's version since this client last read it, the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_stale_season_version_rejected
    """
    base = setup_open_season(week_count=10, total_share_capacity=5,
                             base_price_cents=50000, signup_close_date="2026-12-25T00:00:00Z")
    season_id = base["season"]["id"]
    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    sub_a = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    member_b = register_member(tier="BASELINE")
    mhb = make_member_headers(member_b["id"])
    sub_b = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_b["id"],
                                    base["share"]["id"], base["site"]["id"]), mhb))

    sea_v_stale = get_season_version(season_id)
    # First confirm with the fresh version bumps Season.version.
    validate_success(api_client.confirm_subscription(
        sub_a["id"], {"expected_season_version": sea_v_stale}, FM), 200)
    # Second confirm reuses the now-stale version.
    res = api_client.confirm_subscription(
        sub_b["id"], {"expected_season_version": sea_v_stale}, FM)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    sub_b_after = validate_success(api_client.get_subscription(sub_b["id"], FM), 200)
    assert sub_b_after["billing_status"] == "PENDING_PAYMENT"


def test_site_active_count_reconciles_on_cancel(api):
    """PRD §3.10: "recomputes `outstanding_balance_cents`, decrements the season's `confirmed_share_count` by one and the site's `active_subscription_count` by one, and increments the subscription's `version`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_active_subscription_count_reconciles_on_cancel
    """
    base = setup_open_season(week_count=10, site_weekly_capacity=10,
                             base_price_cents=50000, signup_close_date="2026-12-25T00:00:00Z")
    season_id = base["season"]["id"]
    site_id = base["site"]["id"]
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member["id"],
                                    base["share"]["id"], site_id), mh))
    confirm_subscription(season_id, sub["id"])
    # After confirm the site counter is 1; cancel reconciles it back to 0.
    validate_success(api_client.cancel_subscription(sub["id"], mh), 200)
    site = validate_success(api_client.get_pickup_site(site_id, FM), 200)
    assert site["active_subscription_count"] == 0, (
        f"active_subscription_count expected 0 after cancel, "
        f"got {site['active_subscription_count']}")
    season = validate_success(api_client.get_season(season_id, FM), 200)
    assert season["confirmed_share_count"] == 0


# ─── consistency_model ───────────────────────────────────────────────────────

def test_confirm_response_carries_immediate_balance(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.3: "A `CHARGE_SEASON` ledger entry is posted for that amount."
    PRD §3.3: "The subscription's `outstanding_balance_cents` is recomputed, the season's `confirmed_share_count` is incremented by one, the assigned site's `active_subscription_count` is incremented by one, and the subscription's `version` is incremented."

    Design: Corner/consistency_model/confirm_response_reflects_immediate_charges
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    sea_v = get_season_version(base["season"]["id"])
    confirmed = validate_success(api_client.confirm_subscription(
        sub["id"], {"expected_season_version": sea_v}, FM), 200)
    # The confirm response body itself reflects the charges — no re-read needed.
    assert confirmed["billing_status"] == "CONFIRMED"
    assert confirmed["outstanding_balance_cents"] == 50000, (
        f"confirm response balance expected 50000, "
        f"got {confirmed['outstanding_balance_cents']}")
