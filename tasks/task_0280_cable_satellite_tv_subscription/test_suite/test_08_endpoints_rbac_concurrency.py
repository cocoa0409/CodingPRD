"""Endpoint actions, RBAC enforcement, optimistic-concurrency, and immediate
consistency breadth (corner `endpoints`, `rbac`, `cross_cutting_complexity_layers`,
`consistency_model`).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_field_technician_headers,
    make_subscriber_headers,
    create_package,
    create_premium_channel,
    create_equipment_model,
    create_rsf_rule,
    create_promotion_offer,
    create_technician,
    create_active_account,
    create_prospect_account,
    activate_first_subscription,
    attach_add_on,
    assign_equipment,
    account_version,
    get_account,
    set_clock,
    schedule_visit,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]
FIELD_TECH = TEST_USERS["field_technician_headers"]


# ─── Endpoints ─────────────────────────────────────────────────────────────
def test_return_equipment_marks_returned(api):
    """PRD §3.5: "A lease may be **returned** by a `CustomerServiceAgent` or a `FieldTechnician`,
    transitioning `ASSIGNED → RETURNED`; on return the lease's monthly contribution is removed
    from the recurring charge, `unreturned_charge_cents` stays 0, and the account `version`
    increments."

    Design: Corner/endpoints/return_equipment_marks_returned_and_recomputes
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    dvr = create_equipment_model(model_code="DVR-4K", kind="DVR", monthly_lease_cents=1000, replacement_cost_cents=30000)
    account, _ = create_active_account(package, service_state_code="CA")
    lease = assign_equipment(account["id"], dvr["id"], quantity=1)
    # Equipment return is not technician-ownership-gated; any FieldTechnician may return.
    returned = validate_success(api.return_equipment_lease(account["id"], lease["id"], FIELD_TECH), 200)
    assert returned["status"] == "RETURNED"
    assert returned["unreturned_charge_cents"] == 0


def test_list_account_subscriptions_returns_the_subscription(api):
    """PRD §3.11: "Every account-scoped list — subscriptions, add-ons, equipment leases,
    service visits, promotions, and billing statements under an account — also supports a
    `status` (or, for statements, `cycle_index` and `status`) filter alongside the standard
    `limit` and `offset`."
    PRD §2.3: "Unless a specific endpoint states otherwise, all list endpoints return resources
    sorted by their creation timestamp (`created_at`) in ascending order."

    Design: Corner/endpoints/list_subscriptions_reverse_reachability
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    data, meta = validate_paginated(api.list_account_subscriptions(account["id"], CSA))
    assert meta["total_count"] == 1
    assert len(data) == 1


# ─── RBAC ──────────────────────────────────────────────────────────────────
def test_subscriber_cannot_apply_promotion(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation under the role matrix below, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_apply_promotion
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    offer = create_promotion_offer(code="PX", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.1, promo_months=6, requires_min_rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    v = account_version(account["id"])
    res = api.apply_promotion(
        account["id"],
        {"promotion_offer_id": offer["id"], "expected_account_version": v},
        make_subscriber_headers(account["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_technician_not_assigned_cannot_dispatch(api):
    """PRD §2.1: "a `FieldTechnician` may dispatch, complete, or mark a no-show only on a
    `ServiceVisit` whose `technician_id` equals their `X-User-ID`; a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/technician_not_assigned_to_visit_cannot_dispatch
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech1 = create_technician(name="T1", home_state_code="CA")
    tech2 = create_technician(name="T2", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    visit = schedule_visit(account["id"], tech1["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", visit_type="SERVICE")
    res = api.dispatch_service_visit(
        account["id"], visit["id"], make_field_technician_headers(tech2["id"])
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that is missing either header, or that carries a malformed value,
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/anonymous_missing_headers_unauthenticated
    """
    res = api.create_account(
        {"customer_name": "NoAuth", "service_state_code": "CA", "contract_term_months": 0}, {}
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Optimistic concurrency ────────────────────────────────────────────────
def test_downgrade_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.9: "The server compares `expected_account_version` to the account's current
    `version`. If they match, the operation proceeds and (as every account mutation does)
    advances the account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_downgrade_succeeds
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    plus = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, sub = create_active_account(plus, service_state_code="CA")
    v1 = account_version(account["id"])
    validate_success(
        api.downgrade_subscription(
            account["id"], sub["id"], {"package_id": basic["id"], "expected_account_version": v1}, CSA
        ),
        201,
    )
    v2 = account_version(account["id"])
    assert v2 == v1 + 1, f"version expected {v1 + 1}, got {v2}"


def test_downgrade_with_stale_version_rejected(api):
    """PRD §3.4: "A tier-change request whose `expected_account_version` does not equal the
    account's current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) and makes
    no change; this is the serialization point that prevents a second tier change from clobbering
    an account whose subscription a prior tier change already superseded."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_downgrade_rejected
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    plus = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premier = create_package(tier_code="PREMIER", monthly_fee_cents=9000, rank=3, channel_count=200)
    account, sub = create_active_account(plus, service_state_code="CA")
    v1 = account_version(account["id"])
    # First tier change is an UPGRADE PLUS->PREMIER: the new subscription is ACTIVE
    # (PRD §3.4: a downgrade leaves the new row in DOWNGRADED, an upgrade leaves it
    # ACTIVE). Using an upgrade here keeps the new subscription in the legal source
    # state for a subsequent tier change, so the second request reaches the OCC
    # guard instead of being masked by the higher-precedence ERR_INVALID_STATE
    # state check (PRD §2.7). The upgrade advances the version; v1 is now stale.
    new_sub = validate_success(
        api.upgrade_subscription(
            account["id"], sub["id"], {"package_id": premier["id"], "expected_account_version": v1}, CSA
        ),
        201,
    )
    # Second tier change (a downgrade PREMIER->BASIC) on the now-ACTIVE subscription
    # carries the stale v1 -> state/account-active pass, version mismatch fires.
    res = api.downgrade_subscription(
        account["id"], new_sub["id"], {"package_id": basic["id"], "expected_account_version": v1}, CSA
    )
    validate_error(res, "ERR_STALE_ACCOUNT_VERSION", expected_status=412)


# ─── Immediate consistency ─────────────────────────────────────────────────
def test_monthly_recurring_visible_immediately_after_addon_attach(api):
    """PRD §3.5: "A successful attach creates an `AddOnSubscription` in `ACTIVE` status whose
    `fee_cents` is snapshotted from the premium channel's `monthly_fee_cents` at attach time,
    recomputes the account's recurring charge, and increments the account `version`."

    Design: Corner/consistency_model/monthly_recurring_visible_same_request_immediate
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=300, premier_surcharge_cents=0)
    account, _ = create_active_account(package, service_state_code="CA")
    attach_add_on(account["id"], premium["id"])
    # 6000 package + 1500 add-on + 300 rsf = 7800
    net = get_account(account["id"])["monthly_recurring_cents"]
    assert net == 7800, f"immediate net expected 7800, got {net}"
