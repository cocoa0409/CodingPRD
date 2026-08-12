"""Subscription creation, the two payment bases, activation, arrears and the counter ledger."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    assert_subscription,
    activate_subscription,
    delivery_of_week,
    deliveries_of,
    file_skip,
    make_member_headers,
    new_hub,
    new_member,
    new_subscription,
    pay_subscription,
    read_delivery,
    read_plan,
    read_subscription,
    setup_hub_box_packed,
    setup_member_subscription,
    setup_open_season,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _two_bases_fixture():
    """One MEDIUM x PREMIUM_FINFISH x WEEKLY plan, one hub, two distinct members, both
    joining at week 11 of a 20-week season on the two different payment bases."""
    ctx = setup_open_season(offered_species=("COD", "HADDOCK", "HALIBUT", "SALMON", "LOBSTER"))
    hub = new_hub()
    member_one = new_member(full_name="Mara One", email="m1@csf.test")
    member_two = new_member(full_name="Nils Two", email="m2@csf.test")
    installment = new_subscription(
        member_one["id"],
        ctx["plan"]["id"],
        ctx["season_id"],
        fulfillment_mode="HUB_PICKUP",
        payment_basis="INSTALLMENT",
        join_week_index=11,
        pickup_hub_id=hub["id"],
    )
    prepaid = new_subscription(
        member_two["id"],
        ctx["plan"]["id"],
        ctx["season_id"],
        fulfillment_mode="HUB_PICKUP",
        payment_basis="PREPAID_FULL_SEASON",
        join_week_index=11,
        pickup_hub_id=hub["id"],
    )
    ctx.update(
        {
            "hub": hub,
            "member_one": member_one,
            "member_two": member_two,
            "installment": installment,
            "prepaid": prepaid,
        }
    )
    return ctx


def test_installment_and_prepaid_commitments_diverge_on_the_same_plan_and_join_week(api):
    """PRD 3.2: "Under `INSTALLMENT`, the subscription's `price_per_delivery_cents` is the
    plan's undiscounted list price, and `commitment_cents` is that unit price multiplied by
    the number of deliveries promised from the join week onward — the commitment is prorated
    to what the member will actually receive."
    PRD 3.2: "Under `PREPAID_FULL_SEASON`, every unit is discounted: `PREPAY_DISCOUNT_PCT` is
    0.08, so `price_per_delivery_cents` is the list price multiplied by 0.92 and rounded half
    up to whole cents, that rounding happening once on the unit price and never on the season
    total."
    PRD 3.2: "But the prepaid commitment is *not* prorated: `commitment_cents` is the
    discounted unit price multiplied by the plan's full-season `scheduled_delivery_count`,
    regardless of when the member joins."

    Design: Difficulty/dual_variant_calc/prepaid_vs_installment_commitment_diverge
    """
    ctx = _two_bases_fixture()

    plan = read_plan(ctx["plan"]["id"])
    assert plan["price_per_delivery_cents"] == 4500
    assert plan["scheduled_delivery_count"] == 20
    assert float(plan["target_pounds_per_delivery"]) == pytest.approx(5.00)

    installment = read_subscription(ctx["installment"]["id"])
    assert_subscription(installment)
    assert installment["price_per_delivery_cents"] == 4500
    assert installment["commitment_cents"] == 45000

    prepaid = read_subscription(ctx["prepaid"]["id"])
    assert_subscription(prepaid)
    assert prepaid["price_per_delivery_cents"] == 4140
    assert prepaid["commitment_cents"] == 82800


def test_both_payment_bases_promise_the_same_ten_deliveries_from_week_eleven(api):
    """PRD 3.2: "Joining at week 11 of a 20-week season gives a weekly subscriber ten
    deliveries and a biweekly subscriber five, in weeks 11, 13, 15, 17 and 19.
    `promised_delivery_count` is the size of that set."
    PRD 3.2: "Activation records `promised_delivery_count` as the number of rows it created,
    and sets the money axis: `billing_status` moves `UNBILLED → PREPAID_SETTLED` for a prepaid
    subscription and `UNBILLED → CURRENT` for an installment one."

    Design: Difficulty/dual_variant_calc/prepaid_vs_installment_commitment_diverge
    """
    ctx = _two_bases_fixture()
    pay_subscription(ctx["prepaid"]["id"], 82800)

    installment = activate_subscription(ctx["installment"]["id"])
    prepaid = activate_subscription(ctx["prepaid"]["id"])

    assert installment["promised_delivery_count"] == 10
    assert installment["commitment_cents"] == 45000
    assert installment["billing_status"] == "CURRENT"

    assert prepaid["promised_delivery_count"] == 10
    assert prepaid["commitment_cents"] == 82800
    assert prepaid["billing_status"] == "PREPAID_SETTLED"

    weeks = sorted(row["week_index"] for row in deliveries_of(ctx["installment"]["id"], limit=100))
    assert weeks == list(range(11, 21)), "a weekly subscriber joining at week 11 takes weeks 11..20"


def test_plain_create_lands_in_pending_and_a_waitlisted_create_materialises_no_boxes(api):
    """PRD 3.2: "A `waitlist_requested` flag, when true, puts the new subscription straight
    into `WAITLISTED` instead of `PENDING`; no boxes are created for it and it becomes
    eligible to receive a share transfer. Otherwise the subscription is created in `PENDING`
    with `billing_status` `UNBILLED` and `true_up_status` `NOT_DUE`."
    PRD 3.2: "Activation moves the subscription `PENDING → ACTIVE` and is what turns the
    schedule into rows."

    Design: Corner/state_machines/subscription_starts_in_pending_and_waitlist_creates_no_deliveries
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    member_one = new_member(full_name="Mara One", email="m1@csf.test")
    member_two = new_member(full_name="Nils Two", email="m2@csf.test")

    pending = new_subscription(
        member_one["id"],
        ctx["plan"]["id"],
        ctx["season_id"],
        fulfillment_mode="HUB_PICKUP",
        payment_basis="INSTALLMENT",
        join_week_index=1,
        pickup_hub_id=hub["id"],
    )
    waitlisted = new_subscription(
        member_two["id"],
        ctx["plan"]["id"],
        ctx["season_id"],
        fulfillment_mode="HUB_PICKUP",
        payment_basis="INSTALLMENT",
        join_week_index=1,
        pickup_hub_id=hub["id"],
        waitlist_requested=True,
    )

    assert pending["lifecycle_status"] == "PENDING"
    assert pending["billing_status"] == "UNBILLED"
    assert waitlisted["lifecycle_status"] == "WAITLISTED"

    _, meta_waitlisted = validate_paginated(
        api.list_share_deliveries(ADMIN, {"subscription_id": waitlisted["id"]})
    )
    assert meta_waitlisted["total_count"] == 0, "a waitlisted subscription materialises no boxes"

    _, meta_pending = validate_paginated(
        api.list_share_deliveries(ADMIN, {"subscription_id": pending["id"]})
    )
    assert meta_pending["total_count"] == 0, "a pending subscription has no rows before activation"


def test_activation_materialises_the_biweekly_delivery_week_set(api):
    """PRD 3.2: "A biweekly subscription takes every other week starting at the join week —
    formally, every week between the join week and `total_weeks` inclusive whose distance from
    the join week is an even number."
    PRD 3.2: "It creates one share delivery per week in the delivery-week set, each in
    `fulfillment_status` `SCHEDULED`, `fill_status` `PENDING` and `billing_status` `PENDING`,
    each stamped with its `week_index`, its `season_id` and a `scheduled_at` instant computed
    as the season's `start_date` advanced by seven days for each week beyond the first — that
    is, `start_date` plus seven days multiplied by one less than the week index — preserving
    the time of day of `start_date`."

    Design: Corner/state_machines/activation_materialises_the_biweekly_delivery_week_set
    """
    ctx = setup_open_season(
        offered_species=("COD",),
        plans=[
            {
                "plan_code": "MED-WHITE-B",
                "share_size": "MEDIUM",
                "delivery_frequency": "BIWEEKLY",
                "species_tier": "WHITEFISH",
            }
        ],
    )
    hub = new_hub()
    part = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        activate=False,
        join_week_index=11,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    subscription = activate_subscription(part["subscription_id"])

    assert subscription["lifecycle_status"] == "ACTIVE"
    assert subscription["billing_status"] == "CURRENT"
    assert subscription["promised_delivery_count"] == 5
    assert subscription["commitment_cents"] == 19800
    assert read_plan(ctx["plan"]["id"])["price_per_delivery_cents"] == 3960

    rows, meta = validate_paginated(
        api.list_share_deliveries(ADMIN, {"subscription_id": part["subscription_id"]})
    )
    assert meta["total_count"] == 5
    assert sorted(row["week_index"] for row in rows) == [11, 13, 15, 17, 19]

    week_eleven = delivery_of_week(part["subscription_id"], 11)
    assert_same_instant(
        week_eleven["scheduled_at"], "2026-07-13T00:00:00.000Z", "week-11 scheduled_at"
    )
    assert week_eleven["fulfillment_status"] == "SCHEDULED"


def test_cancelling_twice_is_refused_and_the_first_cancel_voided_every_box(api):
    """PRD 3.2: "Cancellation is available from `ACTIVE`, from `PAUSED` and — as an
    administrative act — from `PAST_DUE`, and in every one of those three cases it behaves
    identically: the subscription moves to `CANCELLED`, every one of its deliveries still in
    `SCHEDULED` moves to `VOIDED` with `fill_status` `VOID` and *no* member credit, and
    `billing_status` moves to `SETTLED`."
    PRD 2.5: "The addressed resource sits in a from-state the requested transition declares,
    including terminal-state lockdown: a resource in a terminal state accepts no further
    transition. Failure is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancelled_subscription_is_terminal_and_cannot_be_cancelled_again
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    part = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    member_headers = make_member_headers(part["member_id"])
    validate_success(api.cancel_subscription(part["subscription_id"], member_headers))

    response = api.cancel_subscription(part["subscription_id"], member_headers)
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    subscription = read_subscription(part["subscription_id"])
    assert subscription["lifecycle_status"] == "CANCELLED"
    assert subscription["billing_status"] == "SETTLED"
    assert validate_success(api.get_member(part["member_id"], ADMIN))["credit_balance_cents"] == 0

    rows = deliveries_of(part["subscription_id"], limit=100)
    assert len(rows) == 20
    for row in rows:
        assert row["fulfillment_status"] == "VOIDED"
        assert row["fill_status"] == "VOID"


def test_prepaid_activation_below_the_commitment_is_refused(api):
    """PRD 2.5: "Money owed is in place — otherwise `ERR_PAYMENT_REQUIRED` (HTTP 402). A
    `PREPAID_FULL_SEASON` activation requires `paid_cents` to be at least `commitment_cents`"
    PRD 3.2: "It requires the subscription to be `PENDING`, the season to be `OPEN`, the
    member's `standing` to be `GOOD` or `WARNED`, and — on the prepaid basis only —
    `paid_cents` to be at least `commitment_cents`."

    Design: Corner/validations/prepaid_activation_without_full_payment_returns_payment_required
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    part = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        activate=False,
        paid_cents=80000,
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        payment_basis="PREPAID_FULL_SEASON",
        pickup_hub_id=hub["id"],
    )

    response = api.activate_subscription(part["subscription_id"], ADMIN)
    assert response.status_code == 402
    validate_error(response, ApiErrorId.ERR_PAYMENT_REQUIRED.value)

    subscription = read_subscription(part["subscription_id"])
    assert subscription["commitment_cents"] == 82800
    assert subscription["paid_cents"] == 80000
    assert subscription["lifecycle_status"] == "PENDING"

    _, meta = validate_paginated(
        api.list_share_deliveries(ADMIN, {"subscription_id": part["subscription_id"]})
    )
    assert meta["total_count"] == 0


def test_home_delivery_subscription_naming_a_hub_is_a_reference_mismatch(api):
    """PRD 2.8: "A subscription on the hub-pickup pipeline must supply a `pickup_hub_id` and
    must not supply a `delivery_zone_id`; a subscription on the home-delivery pipeline must
    supply a `delivery_zone_id` and must not supply a `pickup_hub_id`, and the zone it names
    must have `is_serviceable` set to true."
    PRD 2.5: "Declared cross-references agree — otherwise `ERR_REFERENCE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/home_delivery_subscription_supplying_a_hub_returns_reference_mismatch
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    member = new_member(full_name="Mara One", email="m1@csf.test")

    response = api.create_subscription(
        {
            "member_id": member["id"],
            "share_plan_id": ctx["plan"]["id"],
            "season_id": ctx["season_id"],
            "fulfillment_mode": "HOME_DELIVERY",
            "payment_basis": "INSTALLMENT",
            "join_week_index": 1,
            "pickup_hub_id": hub["id"],
        },
        ADMIN,
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_REFERENCE_MISMATCH.value)

    _, meta = validate_paginated(api.list_subscriptions(ADMIN, {"member_id": member["id"]}))
    assert meta["total_count"] == 0


def test_packing_an_unpaid_installment_box_drives_both_subscription_axes(api):
    """PRD 3.7: "It is also the moment arrears are tested on an installment subscription: when
    `paid_cents` is less than the sum of `charged_cents` across that subscription's deliveries
    standing in `CHARGED` or `PARTIALLY_CREDITED`, the subscription moves `ACTIVE → PAST_DUE`
    and its `billing_status` moves `CURRENT → DUNNING`."
    PRD 3.7: "Packing moves the delivery `ALLOCATED → PACKED` and its money axis `PENDING →
    CHARGED`."

    Design: Difficulty/non_linear_state_machine/subscription_lifecycle_and_billing_axes_loop_independently
    """
    ctx = setup_hub_box_packed(pool_pounds=5.00, paid_cents=0)

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["lifecycle_status"] == "PAST_DUE"
    assert subscription["billing_status"] == "DUNNING"

    delivery = read_delivery(ctx["delivery_id"])
    assert delivery["fulfillment_status"] == "PACKED"
    assert delivery["billing_status"] == "CHARGED"
    assert delivery["charged_cents"] == 4500


def test_a_payment_returns_both_subscription_axes_from_past_due_and_dunning(api):
    """PRD 3.2: "In `PAST_DUE`, the subscription returns `PAST_DUE → ACTIVE` provided that
    `paid_cents` after the payment is at least the cumulative charged amount, defined as the
    sum of `charged_cents` over this subscription's deliveries whose `billing_status` is
    `CHARGED` or `PARTIALLY_CREDITED`; the money axis moves `DUNNING → CURRENT` alongside it."
    PRD 3.2: "Payments are recorded against a subscription by supplying an `amount_cents`
    figure, which is added to `paid_cents`."

    Design: Difficulty/non_linear_state_machine/subscription_lifecycle_and_billing_axes_loop_independently
    """
    ctx = setup_hub_box_packed(pool_pounds=5.00, paid_cents=0)
    assert read_subscription(ctx["subscription_id"])["lifecycle_status"] == "PAST_DUE"

    pay_subscription(ctx["subscription_id"], 4500, make_member_headers(ctx["member_id"]))

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["lifecycle_status"] == "ACTIVE"
    assert subscription["billing_status"] == "CURRENT"
    assert subscription["paid_cents"] == 4500

    delivery = read_delivery(ctx["delivery_id"])
    assert delivery["billing_status"] == "CHARGED"
    assert delivery["fulfillment_status"] == "PACKED"


def test_subscription_ledger_reports_the_subscription_counters(api):
    """PRD 3.2: "A subscription's counters are readable as a computed ledger that reports
    `promised_delivery_count`, `delivered_count`, `credited_count`, `member_fault_count`,
    `skip_credited_count`, `undelivered_count`, `skip_credit_balance_cents`,
    `expired_credit_cents`, `commitment_cents`, `paid_cents`, `rollover_credit_cents` and
    `true_up_amount_cents` in one place."
    PRD 3.8: "Filing **at or before** `cutoff_at` takes the credit branch: `settlement_variant`
    is `CREDIT`, the skip's `credit_cents` is the subscription's full
    `price_per_delivery_cents`, that amount is banked on the subscription's
    `skip_credit_balance_cents`, `skip_credited_count` rises by 1"

    Design: Corner/cross_cutting_complexity_layers/subscription_ledger_computed_read_matches_the_stored_counters
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    part = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    week_three = delivery_of_week(part["subscription_id"], 3)
    file_skip(week_three["id"], part["member_id"])

    ledger = validate_success(
        api.get_subscription_ledger(
            part["subscription_id"], make_member_headers(part["member_id"])
        )
    )
    assert ledger["promised_delivery_count"] == 20
    assert ledger["skip_credit_balance_cents"] == 4500
    assert ledger["delivered_count"] == 0
    assert ledger["credited_count"] == 0
    assert ledger["member_fault_count"] == 0
    assert ledger["skip_credited_count"] == 1
    assert ledger["commitment_cents"] == 90000
    assert ledger["paid_cents"] == 0
    assert ledger["rollover_credit_cents"] == 0


def test_share_delivery_list_pages_within_a_subscription_filter(api):
    """PRD 2.3: "Every list endpoint accepts two optional query parameters. `limit` defaults to
    10, may not be smaller than 1, and may not be larger than 100. `offset` defaults to 0 and
    counts from the start of the result set."
    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`
    (the number of rows matching the filters before the window is applied) and `has_more`
    (true when rows remain beyond the current window)."

    Design: Corner/cross_cutting_complexity_layers/share_delivery_list_supports_limit_offset_and_filtering
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    part = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )

    first_rows, first_meta = validate_paginated(
        api.list_share_deliveries(
            ADMIN, {"subscription_id": part["subscription_id"], "limit": 5, "offset": 0}
        )
    )
    assert len(first_rows) == 5
    assert first_meta["total_count"] == 20
    assert first_meta["has_more"] is True

    last_rows, last_meta = validate_paginated(
        api.list_share_deliveries(
            ADMIN, {"subscription_id": part["subscription_id"], "limit": 5, "offset": 18}
        )
    )
    assert len(last_rows) == 2
    assert last_meta["total_count"] == 20
    assert last_meta["has_more"] is False

    for row in first_rows + last_rows:
        assert row["subscription_id"] == part["subscription_id"]
