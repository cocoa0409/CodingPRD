"""Subscription plans, subscription ledgers, tier changes and the billing cycle."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_config_row,
    assert_same_instant,
    assert_subscription,
    assert_subscription_plan,
    claim_device_payload,
    create_subscription_payload,
    fetch_household,
    fetch_subscription,
    list_subscriptions,
    make_billing_admin_headers,
    make_owner_headers,
    new_catalog,
    new_household,
    new_member,
    new_plan,
    set_clock,
    setup_account,
    setup_account_with_catalog,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_subscription_omitting_allow_overage_defaults_to_false(api):
    """PRD 3.2: "The operator supplies `household_id`, `plan_id` and optionally
    `allow_overage` (which defaults to false)."
    PRD 3.2: "The service pins `monthly_fee_cents` by copying it from the plan, sets
    `cycle_index` to 1, sets `cycle_start_at` to the current logical-clock instant,
    computes `cycle_end_at` as `cycle_start_at` plus 30 days, and grants the plan's
    `included_install_credits` — setting both `install_credits_granted` and
    `install_credits_remaining` to that number while `install_credits_consumed`
    stays 0."

    Design: Corner/entities/subscription_allow_overage_defaults_to_false_when_omitted
    """
    set_clock("2026-05-01T00:00:00Z")
    plan = new_plan("PRO")
    household = new_household(
        name="Default House", region_code="NWA", billing_email="def@example.com"
    )

    # allow_overage is deliberately omitted from the request body.
    data = validate_success(
        api.create_subscription(
            create_subscription_payload(household["id"], plan["id"]), ADMIN
        ),
        201,
    )

    assert_subscription(data)
    assert data["allow_overage"] is False
    assert data["status"] == "ACTIVE"
    assert data["cycle_index"] == 1
    assert data["monthly_fee_cents"] == 9999
    assert_same_instant(
        data["cycle_start_at"], "2026-05-01T00:00:00Z", "Subscription.cycle_start_at"
    )
    assert_same_instant(
        data["cycle_end_at"], "2026-05-31T00:00:00Z", "Subscription.cycle_end_at"
    )
    assert data["install_credits_granted"] == 3
    assert data["install_credits_consumed"] == 0
    assert data["install_credits_remaining"] == 3


def test_subscription_plan_is_configuration_without_version_or_updated_at(api):
    """PRD 2.4: "Two entities are configuration entities and are the exception: a
    `SubscriptionPlan` row and a `DeviceCatalogEntry` row carry only `id` and
    `created_at`. Neither `updated_at` nor `version` exists on those two entities,
    and neither is returned in their payloads."

    Design: Corner/entities/subscription_plan_is_immutable_configuration_without_version
    """
    set_clock("2026-05-01T00:00:00Z")
    plan = new_plan("PRO")

    data = validate_success(api.get_subscription_plan(plan["id"], ADMIN), 200)

    assert_config_row(data, "SubscriptionPlan")
    assert_subscription_plan(data)
    assert data["monthly_fee_cents"] == 9999
    assert data["included_device_count"] == 2


def test_subscription_plan_read_with_unknown_id_reports_plan_not_found(api):
    """PRD 2.9 rung 6: "Every `SubscriptionPlan` id named in the path or body exists,
    covering both `plan_id` and `target_plan_id` — otherwise `ERR_PLAN_NOT_FOUND`.
    Applies to subscription creation, tier change and the single-plan read."

    Design: Corner/entities/subscription_plan_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_subscription_plan("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)


def test_subscription_read_with_unknown_id_reports_subscription_not_found(api):
    """PRD 2.9 rung 7: "Every `Subscription` id named in the path or body exists —
    otherwise `ERR_SUBSCRIPTION_NOT_FOUND`. Applies to the subscription endpoints
    and to add-on order placement."

    Design: Corner/entities/subscription_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_subscription("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value, 404)


def test_catalog_entry_read_with_unknown_id_reports_catalog_entry_not_found(api):
    """PRD 2.9 rung 8: "Every `DeviceCatalogEntry` id named in the path or body exists,
    including every `catalog_entry_id` appearing inside an order's `lines` —
    otherwise `ERR_CATALOG_ENTRY_NOT_FOUND`. Applies to device claiming, add-on
    order placement, campaign creation and the single-catalog read."

    Design: Corner/entities/catalog_entry_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_catalog_entry("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_CATALOG_ENTRY_NOT_FOUND.value, 404)


def test_tier_upgrade_bills_at_once_while_the_reverse_change_is_only_pending(api):
    """PRD 3.2: "When the target fee is **strictly greater** than the current fee the
    change is an immediate upgrade: `plan_id` is switched to the target plan,
    `monthly_fee_cents` is re-pinned from the target plan, any recorded
    `pending_tier_plan_id` is cleared to null, and a prorated charge is booked."
    PRD 3.2: "That charge is the difference between the new fee and the old fee,
    multiplied by the number of whole days remaining in the cycle, divided by 30,
    rounded half up to whole cents, and added to `next_invoice_adjustment_cents`."
    PRD 3.2: "When the target fee is **less than or equal to** the current fee the
    change is a deferred downgrade: nothing is charged, `plan_id` and
    `monthly_fee_cents` are left exactly as they were, and only
    `pending_tier_plan_id` is set to the target plan."

    15 whole days remain at 2026-05-16 of a cycle ending 2026-05-31, so the upgrade
    charge is round_half_up((9999 - 4999) * 15 / 30) == 2500 cents.

    Design: Corner/calculations/tier_upgrade_bills_immediately_while_a_downgrade_is_only_pending
    """
    set_clock("2026-05-01T00:00:00Z")
    plus_plan = new_plan("PLUS")
    pro_plan = new_plan("PRO")
    household = new_household(
        name="Tier2 House", region_code="NWA", billing_email="tier2@example.com"
    )
    billing = new_member(
        household["id"], "BILLING_ADMIN", full_name="Tie R", email="tie@example.com"
    )
    billing_headers = make_billing_admin_headers(billing["id"])
    subscription = validate_success(
        api.create_subscription(
            create_subscription_payload(household["id"], plus_plan["id"], allow_overage=False),
            ADMIN,
        ),
        201,
    )
    set_clock("2026-05-16T00:00:00Z")

    upgraded = validate_success(
        api.change_tier(
            subscription["id"],
            {
                "target_plan_id": pro_plan["id"],
                "expected_subscription_version": subscription["version"],
            },
            billing_headers,
        ),
        200,
    )
    assert upgraded["plan_id"] == pro_plan["id"]
    assert upgraded["monthly_fee_cents"] == 9999
    assert upgraded["next_invoice_adjustment_cents"] == 2500

    downgraded = validate_success(
        api.change_tier(
            subscription["id"],
            {
                "target_plan_id": plus_plan["id"],
                "expected_subscription_version": upgraded["version"],
            },
            billing_headers,
        ),
        200,
    )
    assert downgraded["plan_id"] == pro_plan["id"]
    assert downgraded["monthly_fee_cents"] == 9999
    assert downgraded["pending_tier_plan_id"] == plus_plan["id"]
    assert downgraded["next_invoice_adjustment_cents"] == 2500

    rows = list_subscriptions(pending_tier_plan_id=plus_plan["id"])
    assert len(rows) == 1 and rows[0]["id"] == subscription["id"]


def test_second_failed_close_cycle_suspends_the_subscription_and_the_household(api):
    """PRD 3.2: "From `ACTIVE` with `FAILED`, the subscription moves to `PAST_DUE`"
    PRD 3.2: "From `PAST_DUE` with `FAILED`, the subscription moves to `SUSPENDED`
    and the failure cascades to the account: the owning household's
    `account_status` is set to `SUSPENDED`, its `suspended_at` is stamped with the
    logical-clock instant, and `Household.version` is bumped alongside
    `Subscription.version`."

    Design: Corner/state_machines/subscription_close_cycle_failure_twice_suspends_the_household
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Susp House", email_prefix="sus"
    )
    subscription_id = world["subscription"]["id"]

    set_clock("2026-05-31T00:00:00Z")
    after_first = validate_success(
        api.close_cycle(subscription_id, {"payment_outcome": "FAILED"}, ADMIN), 200
    )
    assert after_first["status"] == "PAST_DUE"
    assert fetch_household(world["household"]["id"])["account_status"] == "ACTIVE"

    set_clock("2026-06-30T00:00:00Z")
    after_second = validate_success(
        api.close_cycle(subscription_id, {"payment_outcome": "FAILED"}, ADMIN), 200
    )
    assert after_second["status"] == "SUSPENDED"

    household = fetch_household(world["household"]["id"])
    assert household["account_status"] == "SUSPENDED"
    assert_same_instant(
        household["suspended_at"], "2026-06-30T00:00:00Z", "Household.suspended_at"
    )


def test_cancelled_subscription_gate_blocks_a_device_claim(api):
    """PRD 3.2: "Requesting cancellation moves the subscription from `ACTIVE` or from
    `PAST_DUE` into `CANCEL_PENDING`, clears `pending_tier_plan_id` to null, and
    bumps the version; the subscription does not actually become `CANCELLED` until
    the next cycle close, at which point gate 4 arms for every subsequent
    household-scoped mutating request."
    PRD 2.8: "If the household's `Subscription` has `status` equal to `CANCELLED`,
    the request is refused with `ERR_SUBSCRIPTION_CANCELLED` (HTTP 409)."

    Design: Corner/validations/cancelled_subscription_gate_blocks_a_device_claim
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Cancel House", email_prefix="can"
    )
    subscription_id = world["subscription"]["id"]

    validate_success(api.cancel_subscription(subscription_id, {}, world["owner_headers"]), 200)
    set_clock("2026-05-31T00:00:00Z")
    validate_success(
        api.close_cycle(subscription_id, {"payment_outcome": "SUCCEEDED"}, ADMIN), 200
    )

    response = api.claim_device(
        claim_device_payload(
            world["household"]["id"], world["catalog"]["id"], "HBX000001", "2026-04-01"
        ),
        world["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_CANCELLED.value, 409)

    assert fetch_subscription(subscription_id)["status"] == "CANCELLED"
    household = fetch_household(world["household"]["id"])
    assert household["account_status"] == "ACTIVE"
    assert household["entitled_device_count"] == 0


def test_change_tier_replaying_a_stale_subscription_version_is_rejected(api):
    """PRD 2.7: "**Changing a subscription's tier** requires the non-optional field
    `expected_subscription_version`, carrying the client's last observed `version`
    of the target `Subscription`. A mismatch with that subscription's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_change_tier_with_a_stale_subscription_version_is_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    plus_plan = new_plan("PLUS")
    pro_plan = new_plan("PRO")
    household = new_household(
        name="Occ2 House", region_code="NWA", billing_email="occ2@example.com"
    )
    billing = new_member(
        household["id"], "BILLING_ADMIN", full_name="Occ2 B", email="occ2b@example.com"
    )
    billing_headers = make_billing_admin_headers(billing["id"])
    subscription = validate_success(
        api.create_subscription(
            create_subscription_payload(household["id"], plus_plan["id"], allow_overage=False),
            ADMIN,
        ),
        201,
    )
    stale_version = subscription["version"]

    set_clock("2026-05-16T00:00:00Z")
    validate_success(
        api.change_tier(
            subscription["id"],
            {
                "target_plan_id": pro_plan["id"],
                "expected_subscription_version": stale_version,
            },
            billing_headers,
        ),
        200,
    )

    response = api.change_tier(
        subscription["id"],
        {"target_plan_id": plus_plan["id"], "expected_subscription_version": stale_version},
        billing_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    current = fetch_subscription(subscription["id"])
    assert current["plan_id"] == pro_plan["id"]
    assert current["monthly_fee_cents"] == 9999
    assert current["pending_tier_plan_id"] is None
    assert current["next_invoice_adjustment_cents"] == 2500


def test_logical_clock_reads_its_declared_default_when_never_set(api):
    """PRD 2.5: "Before any client sets it, the clock reads exactly
    `2026-05-01T00:00:00Z`, and it never falls back to real time."
    PRD 3.3: "A single-use `activation_token` is generated and returned on the created
    row, and `activation_expires_at` is set to the claim instant plus 1440 minutes,
    which is 24 hours."

    No set_current_utc call is made anywhere in this test.

    Design: Corner/endpoints/logical_clock_defaults_to_2026_05_01_when_never_set
    """
    plan = new_plan("PRO")
    household = new_household(
        name="Clock2 House", region_code="NWA", billing_email="clk2@example.com"
    )
    owner = new_member(household["id"], "OWNER", full_name="Clk2 O", email="clk2o@example.com")
    owner_headers = make_owner_headers(owner["id"])
    subscription = validate_success(
        api.create_subscription(
            create_subscription_payload(household["id"], plan["id"], allow_overage=False), ADMIN
        ),
        201,
    )
    catalog = new_catalog("HUB")

    device = validate_success(
        api.claim_device(
            claim_device_payload(household["id"], catalog["id"], "HBX000001", "2026-04-01"),
            owner_headers,
        ),
        201,
    )

    assert_same_instant(device["created_at"], "2026-05-01T00:00:00Z", "Device.created_at")
    assert_same_instant(
        device["activation_expires_at"],
        "2026-05-02T00:00:00Z",
        "Device.activation_expires_at",
    )
    assert_same_instant(
        subscription["cycle_start_at"],
        "2026-05-01T00:00:00Z",
        "Subscription.cycle_start_at",
    )
    assert_same_instant(
        subscription["cycle_end_at"], "2026-05-31T00:00:00Z", "Subscription.cycle_end_at"
    )
