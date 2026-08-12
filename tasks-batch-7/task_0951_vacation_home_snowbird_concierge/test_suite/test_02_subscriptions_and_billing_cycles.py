"""Subscriptions, the entitlement ledger, proration and the delinquency ladder."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    ApiErrorId,
    assert_entitlement_conservation,
    assert_entitlement_rollover_conservation,
    assert_same_instant,
    lines_of,
    new_owner,
    new_property,
    new_service_plan,
    new_subscription,
    open_draft_invoice,
    refresh_cycle,
    refresh_invoice,
    refresh_subscription,
    refresh_visit,
    set_clock,
    setup_completed_visit,
    setup_draft_invoice,
    setup_issued_invoice,
    setup_subscribed_property,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}
PREMIUM = {"tier": "PREMIUM", "monthly_fee_cents": 34944, "included_visit_units": 8,
           "covered_visit_types": ["ROUTINE_WATCH", "SEASONAL_CLOSE", "SEASONAL_OPEN"],
           "entitlement_rollover_policy": "CARRY_CAPPED", "storm_guarantee_included": True}
BASIC_CARRY = {"tier": "BASIC", "monthly_fee_cents": 9986, "included_visit_units": 3,
               "covered_visit_types": ["ROUTINE_WATCH"],
               "entitlement_rollover_policy": "CARRY_CAPPED"}
BASIC_EXPIRE = {"tier": "BASIC", "monthly_fee_cents": 9986, "included_visit_units": 3,
                "covered_visit_types": ["ROUTINE_WATCH"],
                "entitlement_rollover_policy": "EXPIRE"}


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

def test_new_subscription_is_pending_activation_with_no_cycle(api):
    """PRD 3.2: "A subscription binds a `property_id` to a `service_plan_id` from a
    `started_on` instant, and is born in `PENDING_ACTIVATION`. No billing cycle exists
    until activation."

    Design: Corner/state_machines/subscription_initial_state_is_pending_activation
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD, activate=False)
    subscription = ctx["subscription"]
    assert subscription["status"] == "PENDING_ACTIVATION"
    assert subscription["current_cycle_id"] is None
    _, meta = validate_paginated(
        api.list_billing_cycles(headers=AUDITOR, params={"subscription_id": subscription["id"]})
    )
    assert meta["total_count"] == 0, "no cycle exists before activation"


def test_second_activation_is_rejected_and_opens_no_second_cycle(api):
    """PRD 2.8: "The target entity's current status is a declared source state for the
    requested transition. This applies to every action endpoint that drives a state
    machine. Otherwise `ERR_INVALID_STATE_TRANSITION`, HTTP 409."
    PRD 3.2: "Activation creates the first billing cycle with `cycle_index` 1, a
    `period_start` equal to the subscription's `started_on` and a `status` of `OPEN`"

    Design: Corner/state_machines/subscription_activate_twice_second_call_rejected
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    response = api.activate_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    _, meta = validate_paginated(
        api.list_billing_cycles(headers=AUDITOR,
                                params={"subscription_id": ctx["subscription_id"]})
    )
    assert meta["total_count"] == 1, "a rejected activation must not open a second cycle"


def test_cancellation_is_terminal_and_force_closes_the_open_cycle(api):
    """PRD 3.2: "Cancellation stamps `cancelled_at` to the logical clock and force-closes
    the open cycle with `entitlement_carried_out_units` driven to zero regardless of the
    plan's rollover policy."
    PRD 3.2: "From the `ACTIVE` source state the cycle passes through `OPEN` to `CLOSING`
    to `CLOSED` inside the same request, running the rollover with the carry-out forced
    to zero, and `current_cycle_id` is cleared to null."

    Design: Corner/state_machines/cancelled_subscription_is_terminal_and_rejects_pause
    """
    ctx = setup_subscribed_property(plan_overrides=BASIC_CARRY)
    cycle_id = ctx["cycle_id"]
    validate_success(api.cancel_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))

    response = api.pause_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ALREADY_TERMINAL.value, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value],
    )
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "CANCELLED"
    assert subscription["current_cycle_id"] is None
    cycle = refresh_cycle(cycle_id)
    assert cycle["status"] == "CLOSED"
    assert cycle["entitlement_carried_out_units"] == 0
    assert cycle["entitlement_expired_units"] == 3


def test_activation_of_an_out_of_area_property_is_refused(api):
    """PRD 3.2: "Activation requires the plan's `status` to be `ACTIVE` — a retired plan
    is rejected with `ERR_PLAN_RETIRED` — and requires the property's `travel_zone` to be
    anything other than `OUT_OF_AREA`, an out-of-area property being rejected with
    `ERR_PROPERTY_OUT_OF_AREA`."

    Design: Corner/errors/err_property_out_of_area_blocks_activation_returns_409
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Remote House", "address_line": "70 Far Fwy",
                            "travel_distance_miles": 70.0},
        activate=False,
    )
    assert ctx["property"]["travel_zone"] == "OUT_OF_AREA"
    response = api.activate_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_PROPERTY_OUT_OF_AREA.value)
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "PENDING_ACTIVATION"
    assert subscription["current_cycle_id"] is None


def test_activation_onto_a_retired_plan_is_refused(api):
    """PRD 3.2: "Retiring a plan sets its `status` to `RETIRED` so that no new
    subscription may reference it; subscriptions already in force keep the plan."
    PRD 2.9: "`ERR_PLAN_RETIRED` when a subscription is activated onto, or tier-changed
    onto, a service plan whose `status` is `RETIRED`"

    Design: Corner/errors/err_plan_retired_on_activation_returns_409
    """
    ctx = setup_subscribed_property(
        plan_overrides={"tier": "BASIC", "monthly_fee_cents": 9986, "included_visit_units": 2,
                        "covered_visit_types": ["ROUTINE_WATCH"]},
        activate=False,
    )
    from test_helpers import PLATFORM_ADMIN
    retired = validate_success(api.retire_service_plan(ctx["plan_id"], {}, PLATFORM_ADMIN))
    assert retired["status"] == "RETIRED"
    response = api.activate_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_PLAN_RETIRED.value)
    assert refresh_subscription(ctx["subscription_id"])["status"] == "PENDING_ACTIVATION"


# --------------------------------------------------------------------------
# Pause, resume and proration
# --------------------------------------------------------------------------

def test_pause_and_resume_reprorate_the_open_cycle_over_seven_paused_days(api):
    """PRD 3.2: "The resume stamps `resumed_at` to the logical clock, adds the whole days
    of the closed pause interval to `cumulative_paused_days` — the floor of that one
    interval's seconds divided by 86400, never below zero, accumulated interval by
    interval rather than by summing seconds across pauses and flooring once at the end —
    and reprorates the open cycle under the same mid-cycle-pause branch."
    PRD 3.2: "`prorated_fee_cents` becomes the plan's `monthly_fee_cents` multiplied by
    thirty minus that paused-day count, divided by thirty, rounded once to whole cents."

    Design: Corner/calculations/proration_pause_variant_reduces_fee_by_seven_unpaused_days
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    set_clock("2026-06-06T00:00:00Z")
    validate_success(api.pause_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))
    set_clock("2026-06-13T00:00:00Z")
    resumed = validate_success(api.resume_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))

    assert resumed["status"] == "ACTIVE"
    assert_same_instant(resumed["paused_at"], "2026-06-06T00:00:00Z", "paused_at")
    assert_same_instant(resumed["resumed_at"], "2026-06-13T00:00:00Z", "resumed_at")
    assert resumed["cumulative_paused_days"] == 7
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["prorated_fee_cents"] == 15323, (
        f"19986 * 23 / 30 rounds to 15323, got {cycle['prorated_fee_cents']}"
    )


def test_pause_cascades_through_the_cycle_the_invoice_and_the_scheduled_visits(api):
    """PRD 3.2: "If a draft invoice exists on that cycle, its `ACTIVE` subscription-fee
    line has its `amount_cents` rewritten to the new prorated figure and the invoice's
    `gross_service_cents`, `subtotal_cents`, `tax_cents` and `total_cents` are
    recomputed."
    PRD 3.2: "Finally, every visit on the property in status `SCHEDULED` whose
    `scheduled_start_at` falls at or after `paused_at` and strictly before the cycle's
    `period_end` is deferred with a `defer_reason` of `SUBSCRIPTION_PAUSED`."

    Design: Difficulty/transitive_cascade/subscription_pause_depth_five_cascade_to_invoice_and_visits
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    ctx = setup_draft_invoice(ctx)
    from test_helpers import new_template, new_visit
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    inside = new_visit(ctx["property_id"], template["id"],
                       scheduled_start_at="2026-06-20T13:00:00Z",
                       scheduled_end_at="2026-06-20T15:00:00Z")
    outside = new_visit(ctx["property_id"], template["id"],
                        scheduled_start_at="2026-07-20T13:00:00Z",
                        scheduled_end_at="2026-07-20T15:00:00Z")

    paused = validate_success(api.pause_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))

    # Hop 1 — the subscription itself.
    assert paused["status"] == "PAUSED"
    assert_same_instant(paused["paused_at"], "2026-06-01T00:00:00Z", "paused_at")
    # Hop 2 — the open cycle is reprorated over zero paused days.
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["prorated_fee_cents"] == 19986
    # Hop 3 — the seeded subscription-fee line follows the reproration.
    fee_lines = [ln for ln in lines_of(ctx["invoice_id"])
                 if ln["line_type"] == "SUBSCRIPTION_FEE" and ln["status"] == "ACTIVE"]
    assert len(fee_lines) == 1
    assert fee_lines[0]["amount_cents"] == 19986
    # Hop 4 — the invoice totals are recomputed.
    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["gross_service_cents"] == 19986
    assert invoice["tax_cents"] == 1399
    assert invoice["total_cents"] == 21385
    # Hop 5 — only the visit inside the remaining cycle window is deferred.
    assert refresh_visit(inside["id"])["status"] == "DEFERRED"
    assert refresh_visit(inside["id"])["defer_reason"] == "SUBSCRIPTION_PAUSED"
    assert refresh_visit(outside["id"])["status"] == "SCHEDULED"
    assert refresh_visit(outside["id"])["defer_reason"] is None


def test_resume_does_not_undefer_the_visits_the_pause_deferred(api):
    """PRD 3.2: "**The resume deliberately does not un-defer the visits the pause
    deferred**; those must be rescheduled explicitly."
    PRD 3.4: "deferral advances `deferral_count` by one and records the reason, leaves
    `billable_amount_cents` at zero and consumes no entitlement unit."

    Design: Difficulty/transitive_cascade/subscription_pause_depth_five_cascade_to_invoice_and_visits
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    from test_helpers import new_template, new_visit
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"],
                      scheduled_start_at="2026-06-20T13:00:00Z",
                      scheduled_end_at="2026-06-20T15:00:00Z")
    validate_success(api.pause_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))
    deferred = refresh_visit(visit["id"])
    assert deferred["status"] == "DEFERRED"
    assert deferred["deferral_count"] == 1
    assert deferred["billable_amount_cents"] == 0

    set_clock("2026-06-05T00:00:00Z")
    validate_success(api.resume_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))
    still_deferred = refresh_visit(visit["id"])
    assert still_deferred["status"] == "DEFERRED", "the resume must not un-defer the visit"
    assert still_deferred["defer_reason"] == "SUBSCRIPTION_PAUSED"
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["entitlement_consumed_units"] == 0


def test_pause_after_the_only_cycle_closed_has_no_open_cycle(api):
    """PRD 3.2: "Pausing an active subscription requires `current_cycle_id` to be non-null
    and that cycle to be `OPEN`; a missing open cycle is rejected with
    `ERR_NO_OPEN_CYCLE`."
    PRD 3.2: "it runs the rollover, sets `closed_at` to the logical clock, and clears the
    subscription's `current_cycle_id` when it pointed at this cycle."

    Design: Corner/errors/err_no_open_cycle_when_pausing_after_the_cycle_closed_returns_409
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api.close_billing_cycle(ctx["cycle_id"], {}, ACCOUNT_MANAGER))
    assert refresh_subscription(ctx["subscription_id"])["current_cycle_id"] is None

    response = api.pause_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_NO_OPEN_CYCLE.value)
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "ACTIVE"
    assert subscription["paused_at"] is None


# --------------------------------------------------------------------------
# Tier changes
# --------------------------------------------------------------------------

def test_tier_change_rounds_each_proration_leg_before_summing(api):
    """PRD 3.2: "**The rounding order is pinned: each leg is rounded to whole cents on its
    own and only then are the two legs added.**"
    PRD 3.2: "Worked: a change from the standard tier at 19986 to the premium tier at
    34944 with seven used days rounds 4663.4 to 4663 and 26790.4 to 26790, for 31453 —
    where summing first and rounding once would have produced 31454, a one-cent
    divergence."

    Design: Difficulty/dual_variant_calc/tier_change_two_leg_proration_round_each_leg_then_sum
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    premium = new_service_plan(**PREMIUM)
    subscription = refresh_subscription(ctx["subscription_id"])
    set_clock("2026-06-08T00:00:00Z")

    changed = validate_success(api.tier_changes_subscription(
        ctx["subscription_id"],
        {"service_plan_id": premium["id"], "expected_subscription_version": subscription["version"]},
        ACCOUNT_MANAGER,
    ))
    assert changed["service_plan_id"] == premium["id"]
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["prorated_fee_cents"] == 31453, (
        f"4663 + 26790 = 31453, got {cycle['prorated_fee_cents']}"
    )


def test_tier_change_re_derives_the_entitlement_grant_then_floors_the_remainder(api):
    """PRD 3.2: "the cycle's `entitlement_granted_units` is replaced by the new plan's
    `included_visit_units` first; `entitlement_remaining_units` is then re-derived as the
    new grant plus `entitlement_carried_in_units` minus `entitlement_consumed_units`; and
    only then is a floor of zero applied to the result."
    PRD 3.2: "Applying the floor to the grant instead would stop a downgrade from ever
    pushing the remaining count below what has already been consumed."

    Design: Difficulty/dual_variant_calc/tier_change_two_leg_proration_round_each_leg_then_sum
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)

    from test_helpers import complete_visit, new_template, new_visit, run_visit_to_in_progress
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    for day, clock in (("02", "2026-06-02T14:00:00Z"), ("03", "2026-06-03T14:00:00Z")):
        visit = new_visit(ctx["property_id"], template["id"],
                          scheduled_start_at=f"2026-06-{day}T13:00:00Z",
                          scheduled_end_at=f"2026-06-{day}T15:00:00Z")
        run_visit_to_in_progress(visit["id"], clock)
        complete_visit(visit["id"], ["EXT_WALK"], [])

    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["entitlement_consumed_units"] == 2
    downgrade = new_service_plan(tier="BASIC", monthly_fee_cents=9986, included_visit_units=1,
                                 covered_visit_types=["ROUTINE_WATCH"])
    subscription = refresh_subscription(ctx["subscription_id"])
    set_clock("2026-06-08T00:00:00Z")
    changed = validate_success(api.tier_changes_subscription(
        ctx["subscription_id"],
        {"service_plan_id": downgrade["id"],
         "expected_subscription_version": subscription["version"]},
        ACCOUNT_MANAGER,
    ))
    assert changed["service_plan_id"] == downgrade["id"]
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["entitlement_granted_units"] == 1, "the grant takes the new plan's value first"
    assert cycle["entitlement_consumed_units"] == 2
    assert cycle["entitlement_remaining_units"] == 0, "1 + 0 - 2 = -1, floored at zero"
    assert cycle["prorated_fee_cents"] == 12319, (
        f"4663 + 7656 = 12319, got {cycle['prorated_fee_cents']}"
    )


# --------------------------------------------------------------------------
# Entitlement rollover
# --------------------------------------------------------------------------

def test_carry_capped_close_carries_two_units_into_the_next_cycle(api):
    """PRD 3.2: "Under `CARRY_CAPPED` the carry-out is the smaller of the remainder and
    two, and only the excess is destroyed."
    PRD 2.11: "Once a cycle reaches `CLOSED`, its `entitlement_remaining_units` equals
    `entitlement_carried_out_units` plus `entitlement_expired_units`. Opening the next
    cycle immediately afterwards sets that cycle's `entitlement_carried_in_units` to
    exactly the closed cycle's `entitlement_carried_out_units`."

    Design: Difficulty/compensating_invariant/entitlement_rollover_carry_out_equals_next_cycle_carry_in
    """
    ctx = setup_subscribed_property(plan_overrides=BASIC_CARRY)
    set_clock("2026-07-01T00:00:00Z")
    closed = validate_success(api.close_billing_cycle(ctx["cycle_id"], {}, ACCOUNT_MANAGER))
    assert closed["status"] == "CLOSED"
    assert closed["entitlement_granted_units"] == 3
    assert closed["entitlement_consumed_units"] == 0
    assert closed["entitlement_remaining_units"] == 3
    assert closed["entitlement_carried_out_units"] == 2
    assert closed["entitlement_expired_units"] == 1
    assert_entitlement_rollover_conservation(closed)

    opened = validate_success(api.create_subscription_billing_cycle(
        ctx["subscription_id"], {"period_start": "2026-07-01T00:00:00Z"}, ACCOUNT_MANAGER
    ), 201)
    assert opened["cycle_index"] == 2
    assert opened["entitlement_carried_in_units"] == 2
    assert opened["entitlement_granted_units"] == 3
    assert opened["entitlement_remaining_units"] == 5
    assert_entitlement_conservation(opened)


def test_expire_close_carries_nothing_into_the_next_cycle(api):
    """PRD 3.2: "Under `EXPIRE` the whole remainder is destroyed:
    `entitlement_carried_out_units` is zero and `entitlement_expired_units` is the
    remainder, and the next cycle's carry-in is zero regardless of how large the
    remainder was."
    PRD 3.2: "its `entitlement_carried_in_units` is set to the closed cycle's
    `entitlement_carried_out_units` exactly"

    Design: Difficulty/compensating_invariant/entitlement_rollover_carry_out_equals_next_cycle_carry_in
    """
    ctx = setup_subscribed_property(plan_overrides=BASIC_EXPIRE)
    set_clock("2026-07-01T00:00:00Z")
    closed = validate_success(api.close_billing_cycle(ctx["cycle_id"], {}, ACCOUNT_MANAGER))
    assert closed["entitlement_carried_out_units"] == 0
    assert closed["entitlement_expired_units"] == 3
    assert_entitlement_rollover_conservation(closed)

    opened = validate_success(api.create_subscription_billing_cycle(
        ctx["subscription_id"], {"period_start": "2026-07-01T00:00:00Z"}, ACCOUNT_MANAGER
    ), 201)
    assert opened["entitlement_carried_in_units"] == 0
    assert opened["entitlement_remaining_units"] == 3
    assert_entitlement_conservation(opened)


def test_rollover_policy_is_the_only_discriminator_between_two_identical_cycles(api):
    """PRD 3.2: "The rollover itself is discriminated by the in-force plan's
    `entitlement_rollover_policy`."
    PRD 3.2: "The two branches diverge whenever any remainder exists at all."

    Design: Corner/cross_cutting_complexity_layers/dual_variant_entitlement_rollover_expire_versus_carry_capped
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Roll Own", primary_residence_state="MN")
    prop_expire = new_property(owner["id"], label="Expire House", address_line="1 Gone Gr",
                               travel_distance_miles=8.0)
    prop_carry = new_property(owner["id"], label="Carry House", address_line="2 Keep Ct",
                              travel_distance_miles=8.0)
    plan_expire = new_service_plan(**BASIC_EXPIRE)
    plan_carry = new_service_plan(**BASIC_CARRY)
    sub_expire = new_subscription(prop_expire["id"], plan_expire["id"], "2026-06-01T00:00:00Z")
    cycle_expire = validate_success(
        api.activate_subscription(sub_expire["id"], {}, ACCOUNT_MANAGER)
    )["current_cycle_id"]
    sub_carry = new_subscription(prop_carry["id"], plan_carry["id"], "2026-06-01T00:00:00Z")
    cycle_carry = validate_success(
        api.activate_subscription(sub_carry["id"], {}, ACCOUNT_MANAGER)
    )["current_cycle_id"]

    set_clock("2026-07-01T00:00:00Z")
    closed_expire = validate_success(api.close_billing_cycle(cycle_expire, {}, ACCOUNT_MANAGER))
    closed_carry = validate_success(api.close_billing_cycle(cycle_carry, {}, ACCOUNT_MANAGER))

    assert closed_expire["entitlement_remaining_units"] == 3
    assert closed_carry["entitlement_remaining_units"] == 3
    assert closed_expire["entitlement_carried_out_units"] == 0
    assert closed_expire["entitlement_expired_units"] == 3
    assert closed_carry["entitlement_carried_out_units"] == 2
    assert closed_carry["entitlement_expired_units"] == 1
    assert_entitlement_rollover_conservation(closed_expire)
    assert_entitlement_rollover_conservation(closed_carry)


# --------------------------------------------------------------------------
# Delinquency
# --------------------------------------------------------------------------

def test_late_fee_applies_at_exactly_twenty_one_days_after_issue(api):
    """PRD 3.2: "Marking a subscription delinquent requires at least one invoice on its
    cycles in status `ISSUED` with a positive `balance_due_cents` whose `issued_at` plus
    twenty-one days is at or before the logical clock — the threshold is inclusive, so
    exactly twenty-one days after issue already qualifies."
    PRD 3.2: "`late_fee_cents` becomes that invoice's `balance_due_cents` multiplied by
    0.015 and rounded to whole cents, and the invoice's `total_cents` and
    `balance_due_cents` are recomputed."

    Design: Corner/calculations/late_fee_applied_at_exactly_twenty_one_days_after_issue
    """
    ctx = setup_issued_invoice(plan_overrides=STANDARD)
    set_clock("2026-06-22T00:00:00Z")
    subscription = validate_success(
        api.mark_delinquent_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    )
    assert subscription["status"] == "DELINQUENT"
    assert_same_instant(subscription["delinquent_since"], "2026-06-22T00:00:00Z",
                        "delinquent_since")
    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["late_fee_cents"] == 321, "21385 * 0.015 rounds to 321"
    assert invoice["total_cents"] == 21706
    assert invoice["balance_due_cents"] == 21706


def test_marking_delinquent_at_twenty_days_is_too_early(api):
    """PRD 2.8: "Marking a subscription delinquent requires at least one issued invoice
    with a positive `balance_due_cents` whose `issued_at` plus twenty-one days is at or
    before the logical clock. Otherwise `ERR_NOT_YET_DELINQUENT`, HTTP 409."
    PRD 3.2: "An invoice that does not qualify keeps a `late_fee_cents` of zero."

    Design: Corner/errors/err_not_yet_delinquent_at_twenty_days_returns_409
    """
    ctx = setup_issued_invoice(plan_overrides=STANDARD)
    set_clock("2026-06-21T00:00:00Z")
    response = api.mark_delinquent_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_NOT_YET_DELINQUENT.value)
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "ACTIVE"
    assert subscription["delinquent_since"] is None
    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["late_fee_cents"] == 0
    assert invoice["total_cents"] == 21385


def test_clearing_delinquency_while_a_balance_remains_is_refused(api):
    """PRD 3.2: "Clearing delinquency requires that no issued invoice on the
    subscription's cycles still carries a positive balance, and simply clears
    `delinquent_since` back to null."
    PRD 2.8: "Clearing delinquency requires that no issued invoice on the subscription's
    cycles carries a positive `balance_due_cents`. Otherwise
    `ERR_BALANCE_STILL_OUTSTANDING`, HTTP 409."

    Design: Corner/errors/err_balance_still_outstanding_on_clear_delinquency_returns_409
    """
    ctx = setup_issued_invoice(plan_overrides=STANDARD)
    set_clock("2026-06-22T00:00:00Z")
    validate_success(api.mark_delinquent_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))
    assert refresh_invoice(ctx["invoice_id"])["balance_due_cents"] == 21706

    response = api.clear_delinquency_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_BALANCE_STILL_OUTSTANDING.value)
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "DELINQUENT"
    assert_same_instant(subscription["delinquent_since"], "2026-06-22T00:00:00Z",
                        "delinquent_since")


def test_mark_delinquent_on_a_paused_subscription_reports_the_state_gate(api):
    """PRD 2.7: "The gates are evaluated strictly in ascending gate number, the **first
    gate that fails determines both the `error_id` and the HTTP status**, and no later
    gate is evaluated at all."
    PRD 2.8: "The target entity's current status is a declared source state for the
    requested transition. This applies to every action endpoint that drives a state
    machine. Otherwise `ERR_INVALID_STATE_TRANSITION`, HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/mark_delinquent_on_paused_subscription_returns_409_invalid_state
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    validate_success(api.pause_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER))

    response = api.mark_delinquent_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "PAUSED"
    assert subscription["delinquent_since"] is None


def test_mark_delinquent_on_a_pending_subscription_reports_the_state_gate(api):
    """PRD 2.7: "5. **G5 — TARGET STATE.** The target entity's own current state must be a
    declared source state for the requested transition, together with those transition
    preconditions that reference only the target entity."
    PRD 2.7: "9. **G9 — ENTITLEMENT.** Subscription status, billing-cycle status and the
    included-visit entitlement balance."

    Design: Difficulty/priority_pair_validation_conflict/mark_delinquent_on_paused_subscription_returns_409_invalid_state
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD, activate=False)
    response = api.mark_delinquent_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "PENDING_ACTIVATION"
    assert subscription["delinquent_since"] is None
