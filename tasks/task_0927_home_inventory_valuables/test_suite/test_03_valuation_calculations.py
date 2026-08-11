"""Calculation claims: the valuation precedence order, the appraisal-required
threshold, the salvage floor, the evidence ladder, the fair-division variants,
tier proration and the appraisal credit entitlement."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_appraiser,
    add_asset,
    add_cataloged_item,
    add_estate_plan,
    add_item,
    add_member_to_household,
    add_policy,
    add_room,
    allocate,
    assert_same_instant,
    billing_event,
    bootstrap_household,
    certify_appraisal,
    declare_value,
    make_estate_executor_headers,
    propose_plan,
    read_policy_version,
    read_subscription_version,
    request_appraisal,
    set_clock,
    validate_error,
    validate_success,
    void_appraisal,
)

GENERAL_SCHEDULE = {
    "category": "GENERAL",
    "useful_life_months": 120,
    "annual_depreciation_pct": 8.0,
    "salvage_floor_pct": 20.0,
    "blanket_sublimit_cents": 900000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}

ELECTRONICS_SCHEDULE = {
    "category": "ELECTRONICS",
    "useful_life_months": 60,
    "annual_depreciation_pct": 20.0,
    "salvage_floor_pct": 10.0,
    "blanket_sublimit_cents": 500000,
    "appraisal_scope": "ELECTRONICS",
    "serial_required": True,
}

JEWELRY_SCHEDULE = {
    "category": "JEWELRY",
    "useful_life_months": 240,
    "annual_depreciation_pct": 4.0,
    "salvage_floor_pct": 40.0,
    "blanket_sublimit_cents": 300000,
    "appraisal_scope": "JEWELRY",
    "serial_required": False,
}


def test_effective_value_prefers_appraisal_then_acv_over_the_declared_figure(api):
    """PRD 3.4: "The **appraisal** regime is considered first: the candidates are
    the item's appraisals whose `status` is `CERTIFIED` and whose `valid_until_at` is
    strictly after the current instant."
    PRD 3.4: "Failing that, the **actual-cash-value** regime applies when
    `purchase_price_cents` is not null and a category schedule exists for the item's
    category: `effective_value_cents` becomes the current-clock actual cash value
    and `effective_value_basis` becomes `ACV`. Failing that, the **declared** regime
    applies when `declared_value_cents` is strictly greater than zero"
    PRD 3.4: "Hop 1 writes `appraised_value_cents`, stamps `certified_at` with the
    current instant, and sets `valid_until_at` to 1,095 days after `certified_at`."

    Deviation: the design recipe certifies while the clock still stands before
    `inspection_end_at`, which the PRD refuses.  The clock is advanced to
    2026-05-10T00:00:00Z first — the item's age in whole 30-day months is unchanged
    at 4, so every asserted value, including `valid_until_at`, is preserved.

    Design: Corner/calculations/effective_value_precedence_appraisal_then_acv_then_declared
    """
    ctx = bootstrap_household(
        tier="PLUS", activate=False, categories=[ELECTRONICS_SCHEDULE]
    )
    room = add_room(ctx, name="Media Room", floor_label="1")
    appraiser = add_appraiser(
        display_name="Elle Tech",
        credential_id="CRED-EL-1",
        scope_categories=["ELECTRONICS"],
    )
    item = add_cataloged_item(
        ctx,
        room["id"],
        350000,
        name="Projector",
        category="ELECTRONICS",
        acquired_at="2026-01-01T00:00:00Z",
        serial_number="EL-1",
        purchase_price_cents=400000,
    )
    appraisal = request_appraisal(
        ctx,
        item["id"],
        appraiser["id"],
        inspection_start_at="2026-05-09T09:00:00Z",
        inspection_end_at="2026-05-09T17:00:00Z",
    )
    set_clock("2026-05-10T00:00:00Z")

    before = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert before["effective_value_basis"] == "ACV"
    assert before["effective_value_cents"] == 373333
    assert before["valuation_state"] == "DECLARED_ONLY"

    certified = certify_appraisal(appraisal["id"], appraiser["id"], 900000)
    assert_same_instant(
        certified["valid_until_at"], "2029-05-09T00:00:00Z", "Appraisal.valid_until_at"
    )

    after_certify = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert after_certify["effective_value_basis"] == "APPRAISAL"
    assert after_certify["effective_value_cents"] == 900000
    assert after_certify["valuation_state"] == "CERTIFIED"

    void_appraisal(appraisal["id"], "APPRAISER_WITHDRAWN")

    after_void = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert after_void["effective_value_basis"] == "ACV", (
        "the ACV regime outranks the DECLARED regime on the fallback path"
    )
    assert after_void["effective_value_cents"] == 373333
    assert after_void["acv_value_cents"] == 373333


def test_declared_value_at_the_threshold_flips_the_valuation_state(api):
    """PRD 3.4: "For every non-appraisal outcome the `valuation_state` is decided
    afterwards, in this order: when `declared_value_cents` is at or above 1,000,000
    cents — the appraisal-required threshold — the state is `APPRAISAL_REQUIRED`,
    regardless of which of the two remaining regimes supplied the number; otherwise,
    when the basis is `ACV` or `DECLARED`, the state is `DECLARED_ONLY`; otherwise it
    is `UNVALUED`."
    PRD 3.5: "An item whose `valuation_state` is `APPRAISAL_REQUIRED` cannot be
    scheduled and is refused with `ERR_APPRAISAL_REQUIRED`"

    Design: Corner/calculations/declared_value_at_the_appraisal_threshold_flips_valuation_state
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Safe", floor_label="0")
    policy = add_policy(
        ctx, policy_number="NW-C20", scheduled_allowance_cents=5000000
    )
    item_lo = add_item(
        ctx, room["id"], name="Just Under", acquired_at="2025-01-01T00:00:00Z"
    )
    add_asset(ctx, item_lo["id"], asset_kind="PHOTO", byte_size=9000, checksum="sha-c20a")
    item_hi = add_item(
        ctx, room["id"], name="Exactly At", acquired_at="2025-01-02T00:00:00Z"
    )
    add_asset(ctx, item_hi["id"], asset_kind="PHOTO", byte_size=9000, checksum="sha-c20b")
    policy_version = read_policy_version(ctx, policy["id"])

    declare_value(ctx, item_lo["id"], 999999)
    declare_value(ctx, item_hi["id"], 1000000)

    low = validate_success(api.get_item(item_lo["id"], ctx["owner_headers"]))
    assert low["valuation_state"] == "DECLARED_ONLY"
    assert low["effective_value_basis"] == "DECLARED"
    assert low["effective_value_cents"] == 999999

    high = validate_success(api.get_item(item_hi["id"], ctx["owner_headers"]))
    assert high["valuation_state"] == "APPRAISAL_REQUIRED"
    assert high["effective_value_cents"] == 1000000

    response = api.schedule_item(
        item_hi["id"],
        {
            "policy_id": policy["id"],
            "scheduled_value_cents": 1000000,
            "expected_policy_version": policy_version,
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_APPRAISAL_REQUIRED.value, 422)

    stored_policy = validate_success(api.get_policy(policy["id"], ctx["owner_headers"]))
    assert stored_policy["scheduled_consumed_cents"] == 0


def test_actual_cash_value_never_falls_below_the_salvage_floor(api):
    """PRD 3.4: "the depreciated percentage is the category's
    `annual_depreciation_pct` divided by 12 and multiplied by the age in months,
    capped at 100; the raw amount is `purchase_price_cents` multiplied by one minus
    the depreciated percentage divided by one hundred; the salvage floor is
    `purchase_price_cents` multiplied by `salvage_floor_pct` divided by one hundred;
    and the result is the larger of the raw amount and the salvage floor, rounded
    half up to whole cents **once**, at the very end."
    PRD 3.3: "A new item lands in `lifecycle_state` `DRAFT` with `evidence_tier`
    `NONE`, `valuation_state` `UNVALUED`, `effective_value_cents` 0,
    `effective_value_basis` `NONE`, ...; its `acv_value_cents` is computed
    immediately against the current clock."

    Scope note: the design recipe additionally asserted `effective_value_basis`
    `ACV` and `effective_value_cents` 40000 on the freshly created row.  PRD 3.3
    pins the opposite verbatim — a new item lands with `effective_value_cents` 0
    and `effective_value_basis` `NONE`, with only `acv_value_cents` computed
    immediately — and PRD 3.4's trigger list ("re-run whenever an item's assets,
    declared value, serial number or appraisals change, and at the end of every
    clock advance") does not include item creation.  Those two assertions are
    dropped; the salvage-floor claim this test exists to pin is carried entirely
    by `acv_value_cents`.

    Design: Corner/calculations/acv_bottoms_out_at_the_salvage_floor_for_a_fully_depreciated_item
    """
    ctx = bootstrap_household(
        tier="PLUS", activate=False, categories=[ELECTRONICS_SCHEDULE]
    )
    room = add_room(ctx, name="Basement", floor_label="0")

    response = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": room["id"],
            "name": "Old Receiver",
            "category": "ELECTRONICS",
            "acquired_at": "2021-05-01T00:00:00Z",
            "serial_number": "EL-OLD",
            "purchase_price_cents": 400000,
        },
        ctx["owner_headers"],
    )
    item = validate_success(response, 201)

    assert item["acv_value_cents"] == 40000, (
        "60 whole months at 20%/yr caps the curve at 100%, so the 10% salvage floor "
        f"of 400000 wins; got {item['acv_value_cents']}"
    )
    assert item["effective_value_cents"] == 0
    assert item["effective_value_basis"] == "NONE"
    assert item["valuation_state"] == "UNVALUED"
    assert item["lifecycle_state"] == "DRAFT"


def test_evidence_tier_climbs_one_rung_per_evidence_kind(api):
    """PRD 3.3: "The photo predicate holds when the item has at least one stored
    asset of kind `PHOTO`. The serial predicate holds when the item has at least one
    stored asset of kind `SERIAL_PLATE` **or** its `serial_number` is not null. The
    document predicate holds when the item has at least one stored asset of kind
    `RECEIPT` or `PROVENANCE_DOC`. The tier is `DOCUMENTED` when all three hold;
    otherwise `PHOTO_SERIAL` when the photo and serial predicates hold; otherwise
    `PHOTO_ONLY` when the photo predicate holds; otherwise `NONE`."
    PRD 3.3: "`asset_count` counts evidence blobs with `status` `STORED` across all
    of the household's items, and `asset_bytes_used` sums their `byte_size`."

    Design: Corner/calculations/evidence_tier_climbs_none_photo_only_photo_serial_documented
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Workshop", floor_label="0")
    item = add_item(ctx, room["id"], name="Lathe", acquired_at="2025-01-01T00:00:00Z")

    after_photo = add_asset(
        ctx, item["id"], asset_kind="PHOTO", byte_size=5000, checksum="sha-t1"
    )
    assert after_photo is not None
    stored = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored["evidence_tier"] == "PHOTO_ONLY"
    assert stored["lifecycle_state"] == "DRAFT"

    add_asset(ctx, item["id"], asset_kind="SERIAL_PLATE", byte_size=2000, checksum="sha-t2")
    stored = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored["evidence_tier"] == "PHOTO_SERIAL"

    add_asset(ctx, item["id"], asset_kind="RECEIPT", byte_size=1000, checksum="sha-t3")
    stored = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored["evidence_tier"] == "DOCUMENTED"

    declare_value(ctx, item["id"], 500000)
    stored = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored["lifecycle_state"] == "CATALOGED"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["asset_count"] == 3
    assert household["asset_bytes_used"] == 8000


def test_fair_division_is_balanced_under_gross_and_unbalanced_under_net(api):
    """PRD 3.8: "Under the `GROSS` mode the distributable pool is the sale pool
    untouched. Under the `NET` mode the distributable pool is the sale pool
    multiplied by one minus the 12 percent sale disposition cost divided by one
    hundred, rounded half up to whole cents."
    PRD 3.8: "otherwise it is the greatest heir total minus the smallest heir total,
    divided by the mean, multiplied by 100, rounded half up to two decimal places.
    `balanced` is true exactly when `balance_spread_pct` is at or below the 5.0
    percent fair-division tolerance."
    PRD 3.8: "Because the `NET` mode lowers every heir's total by the same aggregate
    amount, it lowers the mean while leaving the gap between the largest and
    smallest totals unchanged: the spread is strictly larger under `NET`, and a plan
    can be balanced under `GROSS` and unbalanced under `NET` on identical
    allocations."

    Design: Corner/calculations/estate_fair_division_gross_passes_and_net_fails_the_same_allocations
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    executor = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "EXECUTOR", full_name="Exec 23"
    )
    heir_a = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "HEIR", full_name="Heir A"
    )
    heir_b = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "HEIR", full_name="Heir B"
    )
    executor_headers = make_estate_executor_headers(executor["id"])
    room = add_room(ctx, name="Estate Room", floor_label="1")

    item_keep_a = add_cataloged_item(
        ctx, room["id"], 155000, photo_bytes=5000, name="Keep A",
        acquired_at="2024-01-01T00:00:00Z", quantity=1,
    )
    item_keep_b = add_cataloged_item(
        ctx, room["id"], 145000, photo_bytes=5000, name="Keep B",
        acquired_at="2024-01-02T00:00:00Z", quantity=1,
    )
    item_sell = add_cataloged_item(
        ctx, room["id"], 100000, photo_bytes=5000, name="Sell One",
        acquired_at="2024-01-03T00:00:00Z", quantity=1,
    )

    plan = add_estate_plan(ctx, executor["id"], valuation_mode="GROSS")
    allocate(plan["id"], executor_headers, item_keep_a["id"], "KEEP", 1, heir_member_id=heir_a["id"])
    allocate(plan["id"], executor_headers, item_keep_b["id"], "KEEP", 1, heir_member_id=heir_b["id"])
    allocate(plan["id"], executor_headers, item_sell["id"], "SELL", 1)

    gross = propose_plan(plan["id"], executor_headers)
    assert gross["status"] == "PROPOSED"
    assert gross["heir_count"] == 2
    assert gross["balance_spread_pct"] == pytest.approx(5.00, abs=0.005)
    assert gross["balanced"] is True

    net = propose_plan(plan["id"], executor_headers, valuation_mode="NET")
    assert net["valuation_mode"] == "NET"
    assert net["balance_spread_pct"] == pytest.approx(5.15, abs=0.005)
    assert net["balanced"] is False
    assert net["unallocated_item_count"] == 0


def test_daily_and_whole_period_proration_price_the_same_upgrade_differently(api):
    """PRD 3.2: "Under the `DAILY` mode — the default when `proration_mode` is
    omitted — the credit is the old fee multiplied by remaining days divided by 30,
    rounded half up to whole cents, the charge is the new fee multiplied by
    remaining days divided by 30, rounded half up to whole cents, and
    `last_proration_charge_cents` is the charge minus the credit, which may be
    negative."
    PRD 3.2: "Under the `WHOLE_PERIOD` mode, `last_proration_charge_cents` is simply
    the new fee minus the old fee, with no proration at all"
    PRD 3.2: "Both modes then set `tier` to the requested tier, set
    `monthly_fee_cents` to the new fee, and clip `appraisal_credits_remaining` down
    to the new tier's included credits — taking the smaller of the current balance
    and the new allowance, so a downgrade never grows a balance and an upgrade never
    grants credits mid-period. A tier change does **not** reset `period_start_at`."

    Design: Corner/calculations/subscription_proration_daily_differs_from_whole_period
    """
    ctx_a = bootstrap_household(tier="PLUS", activate=True, household_name="Corner House 24A")
    ctx_b = bootstrap_household(
        tier="PLUS", activate=True, clock=None, household_name="Corner House 24B"
    )
    set_clock("2026-05-11T00:00:00Z")

    version_a = read_subscription_version(ctx_a)
    version_b = read_subscription_version(ctx_b)

    daily = validate_success(
        api.change_tier(
            ctx_a["subscription_id"],
            {
                "tier": "ESTATE",
                "proration_mode": "DAILY",
                "expected_subscription_version": version_a,
            },
            ctx_a["owner_headers"],
        )
    )
    whole = validate_success(
        api.change_tier(
            ctx_b["subscription_id"],
            {
                "tier": "ESTATE",
                "proration_mode": "WHOLE_PERIOD",
                "expected_subscription_version": version_b,
            },
            ctx_b["owner_headers"],
        )
    )

    assert daily["last_proration_charge_cents"] == 3334, (
        "charge 5267 minus credit 1933 over 20 remaining days; got "
        f"{daily['last_proration_charge_cents']}"
    )
    assert whole["last_proration_charge_cents"] == 5000
    assert daily["tier"] == "ESTATE" and daily["monthly_fee_cents"] == 7900
    assert whole["tier"] == "ESTATE" and whole["monthly_fee_cents"] == 7900
    assert daily["appraisal_credits_remaining"] == 2, (
        "an upgrade never tops the entitlement up mid-period"
    )
    assert_same_instant(
        daily["period_start_at"], "2026-05-01T00:00:00Z", "Subscription.period_start_at"
    )


def test_appraisal_credits_are_reassigned_and_never_rolled_over(api):
    """PRD 3.2: "From `PAST_DUE`, a `PAYMENT_SUCCEEDED` outcome moves `PAST_DUE →
    ACTIVE`, clears `past_due_since_at` to null, resets `period_start_at` to now with
    `period_end_at` recomputed, reassigns `appraisal_credits_remaining` to the tier's
    included credits — an assignment, so an unused balance is discarded and never
    rolls over — and resets `packages_used_this_period` to 0."
    PRD 3.4: "From `REQUESTED`, voiding is the shallow `REQUESTED → VOIDED` move: the
    reason is written, the item's appraisal hold is released so its inspection window
    is free for a new request, and if `credit_consumed` was true the credit is **not**
    refunded — entitlements never roll back."

    Design: Corner/calculations/appraisal_credits_reset_without_rolling_over_on_a_new_period
    """
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[JEWELRY_SCHEDULE])
    room = add_room(ctx, name="Dressing", floor_label="2")
    appraiser = add_appraiser(
        display_name="Gem Two", credential_id="CRED-JW-25", scope_categories=["JEWELRY"]
    )
    item = add_cataloged_item(
        ctx,
        room["id"],
        300000,
        photo_bytes=5000,
        name="Garnet Pin",
        category="JEWELRY",
        acquired_at="2024-01-01T00:00:00Z",
        serial_number="JW-25",
    )
    appraisal = request_appraisal(
        ctx,
        item["id"],
        appraiser["id"],
        inspection_start_at="2026-06-01T09:00:00Z",
        inspection_end_at="2026-06-01T17:00:00Z",
    )

    before = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert before["appraisal_credits_remaining"] == 1

    voided = void_appraisal(appraisal["id"], "APPRAISER_WITHDRAWN")
    assert voided["status"] == "VOIDED"
    assert voided["credit_consumed"] is True

    after_void = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert after_void["appraisal_credits_remaining"] == 1, (
        "voiding never refunds the credit the request consumed"
    )

    billing_event(ctx, "PAYMENT_FAILED")
    restored = billing_event(ctx, "PAYMENT_SUCCEEDED")

    assert restored["status"] == "ACTIVE"
    assert restored["appraisal_credits_remaining"] == 2, (
        "the reset is an assignment to 2, never an addition to the remaining 1"
    )
    assert restored["packages_used_this_period"] == 0
    assert restored["past_due_since_at"] is None
