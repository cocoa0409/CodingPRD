"""Add-on orders: bundle pricing, the install-credit waterfall, proration and fulfilment."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_addon_order,
    assert_install_credit_conservation,
    assert_same_instant,
    claim,
    fetch_household,
    fetch_order,
    fetch_subscription,
    list_devices,
    list_orders,
    make_billing_admin_headers,
    new_catalog,
    new_household,
    new_member,
    new_plan,
    new_subscription,
    order_line,
    place_order,
    set_clock,
    setup_account,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_addon_order_read_with_unknown_id_reports_order_not_found(api):
    """PRD 2.9 rung 17: "Every `AddOnOrder` id named in the path exists — otherwise
    `ERR_ORDER_NOT_FOUND`. Applies to order fulfilment and the single-order read."

    Design: Corner/entities/addon_order_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_addon_order("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)


def test_install_credit_exhaustion_charges_the_uncovered_unit(api):
    """PRD 3.10: "`bundle_discount_pct` is 0.15 when `subtotal_cents` is at least 50
    000 cents, otherwise 0.10 when it is at least 20 000 cents, otherwise 0."
    PRD 3.10: "The participating units are expanded one row per unit and sorted by the
    model's `msrp_cents` **descending**, breaking ties by the line's position in the
    request ascending and then by the unit's index within its line ascending — the
    most expensive installation is covered first."
    PRD 3.10: "**Step 4 — the install charge.** The uncovered units are the
    participating units less those covered, and `install_charge_cents` is 12 900
    cents per uncovered unit."
    PRD 2.10: "For every subscription, `install_credits_remaining` plus
    `install_credits_consumed` equals `install_credits_granted`."

    19000 + 24900 == 43900 earns the 10% tier: 43900 - 4390 == 39510, plus one
    uncovered install at 12900 and no proration, giving 52410.

    Design: Corner/calculations/install_credit_exhaustion_charges_the_install_visit_fee_for_the_uncovered_unit
    """
    world = setup_account(
        plan_kind="PLUS",
        allow_overage=True,
        roles=("BILLING_ADMIN",),
        name="Credit House",
        email_prefix="crd",
    )
    thermostat = new_catalog("THERMOSTAT")
    hub = new_catalog("HUB")

    data = validate_success(
        api.place_addon_order(
            {
                "household_id": world["household"]["id"],
                "subscription_id": world["subscription"]["id"],
                "lines": [
                    order_line(thermostat["id"], 1),
                    order_line(hub["id"], 1),
                ],
                "expected_subscription_version": world["subscription"]["version"],
            },
            world["billing_headers"],
        ),
        201,
    )

    assert_addon_order(data)
    assert data["subtotal_cents"] == 43900
    assert data["bundle_discount_pct"] == 0.10
    assert data["bundle_discount_cents"] == 4390
    assert data["discounted_subtotal_cents"] == 39510
    assert data["install_credits_applied"] == 1
    assert data["install_charge_cents"] == 12900
    assert data["monthly_delta_cents"] == 0
    assert data["proration_cents"] == 0
    assert data["order_total_cents"] == 52410

    subscription = fetch_subscription(world["subscription"]["id"])
    assert subscription["install_credits_granted"] == 1
    assert subscription["install_credits_consumed"] == 1
    assert subscription["install_credits_remaining"] == 0
    assert_install_credit_conservation(subscription)
    assert subscription["next_invoice_adjustment_cents"] == 52410


def test_fulfilment_creates_one_claimed_device_per_ordered_unit(api):
    """PRD 3.10: "One `Device` row is created in `CLAIMED` per ordered unit, walking
    the lines in the pinned request order and the units within each line in turn,
    consuming the entries of `serial_numbers` positionally in that same order."
    PRD 3.10: "The new device ids are recorded in the order's `fulfilled_device_ids`,
    the household's `entitled_device_count` and the subscription's
    `overage_device_count` are recomputed, the order moves `PLACED → FULFILLED`, and
    `AddOnOrder.version` rises by one."
    PRD 3.10: "Each created device has the warranty pin of §3.3 applied to it — base
    term from its catalog model, extended when the subscription is `ACTIVE` or
    `PAST_DUE` and the plan grants a positive `warranty_extension_months`, with
    `warranty_basis` recorded accordingly."

    A 12-month SENSOR term plus the PLUS plan's 6-month extension from a 2026-05-01
    purchase expires 2027-11-01.

    Design: Corner/endpoints/addon_order_fulfillment_creates_one_claimed_device_per_unit
    """
    world = setup_account(
        plan_kind="PLUS",
        allow_overage=False,
        roles=("BILLING_ADMIN",),
        name="Fulfil House",
        email_prefix="ful",
    )
    sensor = new_catalog("SENSOR")
    order = place_order(
        world["household"]["id"],
        world["subscription"]["id"],
        [order_line(sensor["id"], 2)],
        world["subscription"]["version"],
        world["billing_headers"],
    )

    data = validate_success(
        api.fulfill_addon_order(
            order["id"],
            {"serial_numbers": ["SNB000001", "SNB000002"], "purchase_date": "2026-05-01"},
            world["billing_headers"],
        ),
        200,
    )

    assert data["status"] == "FULFILLED"
    assert len(data["fulfilled_device_ids"]) == 2
    assert order["subtotal_cents"] == 9800
    assert order["bundle_discount_pct"] == 0
    assert order["order_total_cents"] == 9800

    devices = list_devices(household_id=world["household"]["id"])
    assert len(devices) == 2
    for device in devices:
        assert device["lifecycle_status"] == "CLAIMED"
        assert device["warranty_basis"] == "TIER_EXTENDED"
        assert_same_instant(
            device["warranty_expires_at"],
            "2027-11-01T00:00:00Z",
            "Device.warranty_expires_at",
        )

    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 2
    assert (
        fetch_subscription(world["subscription"]["id"])["next_invoice_adjustment_cents"] == 9800
    )


def test_replaying_a_stale_subscription_version_on_a_second_order_is_rejected(api):
    """PRD 2.7: "**Placing an add-on order** requires the non-optional field
    `expected_subscription_version`, carrying the client's last observed `version` of
    the `Subscription` named by `subscription_id`. A caller who priced a basket
    against an install-credit balance that has since been consumed will find its
    supplied version no longer matching, and the order is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.10: "The created order begins with `status` `PLACED` and an empty
    `fulfilled_device_ids`, and placing it bumps `Subscription.version` by one."

    Design: Corner/cross_cutting_layers/occ_addon_order_with_a_stale_subscription_version_is_rejected
    """
    world = setup_account(
        plan_kind="PLUS",
        plan_overrides={"included_device_count": 4},
        allow_overage=False,
        roles=("BILLING_ADMIN",),
        name="Occ3 House",
        email_prefix="occ3",
    )
    hub = new_catalog("HUB")
    stale_version = world["subscription"]["version"]
    first_order = place_order(
        world["household"]["id"],
        world["subscription"]["id"],
        [order_line(hub["id"], 1)],
        stale_version,
        world["billing_headers"],
    )

    response = api.place_addon_order(
        {
            "household_id": world["household"]["id"],
            "subscription_id": world["subscription"]["id"],
            "lines": [order_line(hub["id"], 1)],
            "expected_subscription_version": stale_version,
        },
        world["billing_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    order = fetch_order(first_order["id"])
    assert order["install_credits_applied"] == 1
    assert order["install_charge_cents"] == 0

    subscription = fetch_subscription(world["subscription"]["id"])
    assert subscription["install_credits_consumed"] == 1
    assert subscription["install_credits_remaining"] == 0
    assert_install_credit_conservation(subscription)
    assert len(list_orders(subscription_id=world["subscription"]["id"])) == 1


# ==========================================================================
# Difficulty: proration mode diverges purely on days remaining
# ==========================================================================
def _identical_household(plan_id: str, name: str, email_prefix: str):
    """One household on the SHARED plan with an OWNER, a BILLING_ADMIN and a subscription."""
    household = new_household(
        name=name, region_code="NWA", billing_email=f"{email_prefix}@example.com"
    )
    billing = new_member(
        household["id"],
        "BILLING_ADMIN",
        full_name=f"Bill {name}",
        email=f"{email_prefix}.billing@example.com",
    )
    subscription = new_subscription(household["id"], plan_id, allow_overage=True)
    return {
        "household": household,
        "billing_headers": make_billing_admin_headers(billing["id"]),
        "subscription": subscription,
    }


def _two_identical_households():
    """Two households with byte-identical plans, device counts and available credits."""
    set_clock("2026-05-01T00:00:00Z")
    plan = new_plan("PLUS")
    camera = new_catalog("CAMERA")
    hub = new_catalog("HUB")
    world_a = _identical_household(plan["id"], "House A", "a")
    world_b = _identical_household(plan["id"], "House B", "b")
    return world_a, world_b, camera, hub


def test_mid_cycle_order_prorates_the_overage_unit_across_the_days_remaining(api):
    """PRD 3.10: "If at least 5 days remain, `proration_mode` is `MID_CYCLE_PRORATED`
    and `proration_cents` is the sum over lines of the value obtained by taking
    `overage_fee_cents_per_device`, multiplying by that line's extras, multiplying by
    the days remaining, dividing by 30 and **rounding each line half up to whole
    cents before summing**"
    PRD 3.10: "**Step 6 — the total.** `order_total_cents` is
    `discounted_subtotal_cents` plus `install_charge_cents` plus `proration_cents`,
    with no further rounding, and that total is added to the subscription's
    `next_invoice_adjustment_cents`."

    A 50700 subtotal earns the 15% tier (7605 off, 43095 left); one install credit
    covers the single HUB; the third unit is the only extra, giving
    round_half_up(399 * 1 * 11 / 30) == 146 and a total of 43241.

    Design: Difficulty/dual_variant_calc/addon_proration_mode_diverges_on_days_remaining
    """
    world_a, _world_b, camera, hub = _two_identical_households()

    set_clock("2026-05-20T00:00:00Z")
    data = validate_success(
        api.place_addon_order(
            {
                "household_id": world_a["household"]["id"],
                "subscription_id": world_a["subscription"]["id"],
                "lines": [order_line(camera["id"], 2), order_line(hub["id"], 1)],
                "expected_subscription_version": world_a["subscription"]["version"],
            },
            world_a["billing_headers"],
        ),
        201,
    )

    assert_addon_order(data)
    assert data["subtotal_cents"] == 50700
    assert data["bundle_discount_pct"] == 0.15
    assert data["bundle_discount_cents"] == 7605
    assert data["discounted_subtotal_cents"] == 43095
    assert data["install_credits_applied"] == 1
    assert data["install_charge_cents"] == 0
    assert data["proration_mode"] == "MID_CYCLE_PRORATED"
    assert data["monthly_delta_cents"] == 399
    assert data["proration_cents"] == 146
    assert data["order_total_cents"] == 43241


def test_late_cycle_order_defers_the_whole_delta_to_the_next_cycle(api):
    """PRD 3.10: "If fewer than 5 days remain, `proration_mode` is `NEXT_CYCLE_FULL`
    and `proration_cents` is 0; `monthly_delta_cents` is still recorded on the order
    and takes effect from the next cycle."
    PRD 3.10: "The same basket on the same plan therefore produces a different
    `order_total_cents` depending only on where in the cycle it was placed."

    The identical basket placed with 3 days left drops the 146-cent proration,
    leaving exactly the discounted subtotal of 43095.

    Design: Difficulty/dual_variant_calc/addon_proration_mode_diverges_on_days_remaining
    """
    _world_a, world_b, camera, hub = _two_identical_households()

    set_clock("2026-05-28T00:00:00Z")
    data = validate_success(
        api.place_addon_order(
            {
                "household_id": world_b["household"]["id"],
                "subscription_id": world_b["subscription"]["id"],
                "lines": [order_line(camera["id"], 2), order_line(hub["id"], 1)],
                "expected_subscription_version": world_b["subscription"]["version"],
            },
            world_b["billing_headers"],
        ),
        201,
    )

    assert data["proration_mode"] == "NEXT_CYCLE_FULL"
    assert data["monthly_delta_cents"] == 399
    assert data["proration_cents"] == 0
    assert data["order_total_cents"] == 43095


# ==========================================================================
# Difficulty: per-line rounding, and the tier pinned to the subtotal
# ==========================================================================
def _rounding_world():
    world = setup_account(
        plan_kind="PLUS",
        allow_overage=True,
        roles=("OWNER", "BILLING_ADMIN"),
        name="Rounding House",
        email_prefix="round",
    )
    camera = new_catalog("CAMERA")
    sensor = new_catalog("SENSOR")
    claim(
        world["household"]["id"], sensor["id"], "SNB000001", world["owner_headers"]
    )
    claim(
        world["household"]["id"], sensor["id"], "SNB000002", world["owner_headers"]
    )
    set_clock("2026-05-20T00:00:00Z")
    world["camera"] = camera
    world["sensor"] = sensor
    world["subscription"] = fetch_subscription(world["subscription"]["id"])
    return world


def test_proration_rounds_each_line_before_summing_them(api):
    """PRD 2.6: "First, in add-on order proration each **line** is rounded to whole
    cents and only then are the rounded line values summed; summing the unrounded
    line values and rounding once at the end is a different and incorrect number."
    PRD 3.10: "**rounding each line half up to whole cents before summing** — summing
    first and rounding once at the end is a different and incorrect number."

    Two lines each carrying one extra unit at 399 cents with 11 of 30 days left give
    146 + 146 == 292; summing first would give round_half_up(292.6) == 293.

    Design: Difficulty/combinatorial_formula/addon_proration_rounds_per_line_then_sums
    """
    world = _rounding_world()

    data = validate_success(
        api.place_addon_order(
            {
                "household_id": world["household"]["id"],
                "subscription_id": world["subscription"]["id"],
                "lines": [
                    order_line(world["camera"]["id"], 1),
                    order_line(world["sensor"]["id"], 1),
                ],
                "expected_subscription_version": world["subscription"]["version"],
            },
            world["billing_headers"],
        ),
        201,
    )

    assert data["monthly_delta_cents"] == 798
    assert data["proration_cents"] == 292
    assert data["proration_cents"] != 293
    assert data["order_total_cents"] == 18092


def test_a_subtotal_below_the_first_tier_earns_no_bundle_discount(api):
    """PRD 3.10: "**Step 1 — subtotal.** `subtotal_cents` is the sum over the lines of
    the catalog entry's `msrp_cents` multiplied by that line's `quantity`."
    PRD 3.10: "**Step 3 — the install-credit waterfall.** Only units whose catalog
    model has `requires_install` true participate; units of non-install models are
    skipped entirely and never consume a credit."

    12900 + 4900 == 17800 sits below the 20 000-cent tier-1 threshold, so no discount
    applies and neither model requires an install credit.

    Design: Difficulty/combinatorial_formula/addon_proration_rounds_per_line_then_sums
    """
    world = _rounding_world()

    data = validate_success(
        api.place_addon_order(
            {
                "household_id": world["household"]["id"],
                "subscription_id": world["subscription"]["id"],
                "lines": [
                    order_line(world["camera"]["id"], 1),
                    order_line(world["sensor"]["id"], 1),
                ],
                "expected_subscription_version": world["subscription"]["version"],
            },
            world["billing_headers"],
        ),
        201,
    )

    assert data["subtotal_cents"] == 17800
    assert data["bundle_discount_pct"] == 0
    assert data["discounted_subtotal_cents"] == 17800
    assert data["install_credits_applied"] == 0
    assert data["install_charge_cents"] == 0


def _tier_pinning_world():
    world = setup_account(
        plan_kind="BASIC",
        allow_overage=False,
        roles=("BILLING_ADMIN",),
        name="Tier House",
        email_prefix="tier",
    )
    world["thermostat"] = new_catalog("THERMOSTAT")
    return world


def test_bundle_tier_is_pinned_to_the_subtotal_not_to_the_order_total(api):
    """PRD 2.6: "Second, in add-on bundle pricing the discount is computed from the
    subtotal alone and rounded once, before any install charge or proration is added
    to the order."
    PRD 3.10: "In particular the discount tier is keyed on the subtotal **alone** and
    is deliberately *not* recomputed after the install charge or the proration is
    added, even though both raise the amount the customer pays."

    The 31900-cent order total sits above the 20 000-cent tier-1 threshold while the
    19000-cent subtotal sits below it, so the discount percentage must be 0.

    Design: Difficulty/combinatorial_formula/bundle_discount_tier_pinned_to_subtotal_before_install_charge
    """
    world = _tier_pinning_world()

    data = validate_success(
        api.place_addon_order(
            {
                "household_id": world["household"]["id"],
                "subscription_id": world["subscription"]["id"],
                "lines": [order_line(world["thermostat"]["id"], 1)],
                "expected_subscription_version": world["subscription"]["version"],
            },
            world["billing_headers"],
        ),
        201,
    )

    assert data["subtotal_cents"] == 19000
    assert data["bundle_discount_pct"] == 0
    assert data["bundle_discount_cents"] == 0
    assert data["discounted_subtotal_cents"] == 19000
    assert data["order_total_cents"] == 31900


def test_an_uncovered_install_unit_is_charged_the_install_visit_fee(api):
    """PRD 3.10: "**Step 4 — the install charge.** The uncovered units are the
    participating units less those covered, and `install_charge_cents` is 12 900
    cents per uncovered unit."
    PRD 3.10: "The available credits are the subscription's
    `install_credits_remaining`. Walking the sorted units, each unit consumes one
    credit while credits remain."

    The BASIC plan grants no install credits, so the single install-requiring
    thermostat is charged the full 12 900 cents and nothing is prorated.

    Design: Difficulty/combinatorial_formula/bundle_discount_tier_pinned_to_subtotal_before_install_charge
    """
    world = _tier_pinning_world()

    data = validate_success(
        api.place_addon_order(
            {
                "household_id": world["household"]["id"],
                "subscription_id": world["subscription"]["id"],
                "lines": [order_line(world["thermostat"]["id"], 1)],
                "expected_subscription_version": world["subscription"]["version"],
            },
            world["billing_headers"],
        ),
        201,
    )

    assert data["install_credits_applied"] == 0
    assert data["install_charge_cents"] == 12900
    assert data["proration_cents"] == 0
    assert_install_credit_conservation(fetch_subscription(world["subscription"]["id"]))
