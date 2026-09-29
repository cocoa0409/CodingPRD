"""The price ladder, its two disagreeing readings, and the regulated increase pipeline."""

from test_helpers import (
    OFFICER_ONE_ID,
    OFFICER_ONE_HEADERS,
    OPS_AGENT_HEADERS,
    api_client,
    create_active_plan,
    create_plan,
    create_registered_reader,
    invoice_for_cycle,
    open_subscription,
    read_plan,
    read_reader,
    read_subscription,
    record_payment,
    run_billing,
    schedule_price_change,
    set_clock_date,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f


def _standard_digital_plan(name):
    return {
        "name": name,
        "bundle_type": "DIGITAL_ONLY",
        "intro_price_cents": 499,
        "intro_cycles": 1,
        "standard_price_cents": 1499,
        "standard_from_cycle": 2,
        "cycle_days": 30,
    }


def _arrange_cycle_two_billed_under_a_scheduled_increase():
    """Cycle 2 billed at the standard price while an increase sits at SCHEDULED."""
    set_clock_date("2026-09-01")
    plan = create_active_plan(**_standard_digital_plan("Digital Standard"))
    reader = create_registered_reader("reader1@mail.test", propensity_band="MEDIUM")
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    schedule_price_change(plan["id"], 1999, "2026-10-01", "NONE")
    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    return {
        "plan": read_plan(plan["id"]),
        "subscription": read_subscription(subscription["id"]),
        "invoice": invoice_for_cycle(subscription["id"], 2),
    }


def test_cycle_two_invoice_bills_the_standard_rung_and_ignores_the_scheduled_increase():
    """The billed variant sees only applied prices, so cycle 2 costs 1499 not 1999.

    PRD: "It evaluates the rungs for the cycle actually being billed, and it uses only prices that have already been applied — a `SCHEDULED` or `NOTICE_SENT` change is invisible to it."
    PRD: "Otherwise, if the cycle index is greater than or equal to `standard_from_cycle`, the answer is `standard_price_cents`, labelled `STANDARD`."
    PRD: "The BILLING pass of a run picks up every subscription whose `paid_through_on` has fallen on or before the clock date and generates that subscription's next invoice through the waterfall above, sweeping any unapplied completed hold credits and decrementing `retention_discount_cycles_remaining` where a discount applied."

    Design: Difficulty/dual_variant_calc/cycle_price_preview_quote_diverges_from_billed_amount
    """
    state = _arrange_cycle_two_billed_under_a_scheduled_increase()

    assert state["subscription"]["cycle_index"] == 2
    invoice = state["invoice"]
    assert invoice["cycle_index"] == 2
    assert invoice["base_line_cents"] == 1499
    assert invoice["price_source"] == "STANDARD"
    assert invoice["discount_line_cents"] == 0
    assert invoice["credit_line_cents"] == 0
    assert invoice["total_cents"] == 1499


def test_forward_looking_quote_substitutes_the_pending_price_and_diverges_from_the_billed_line():
    """next_cycle_price_cents assumes the scheduled 1999 lands, so quote and bill disagree.

    PRD: "When the resolved rung is `STANDARD` and the plan's `price_change_state` is either `SCHEDULED` or `NOTICE_SENT` and the plan's `pending_effective_on` falls on or before the next cycle's start date (that is, `cycle_start_on` advanced by `cycle_days`), it substitutes `pending_price_cents`: a not-yet-applied increase is assumed to land."
    PRD: "Scheduling persists all three inputs, sets `price_change_state` to `SCHEDULED`, recomputes `next_cycle_price_cents` on every subscription of the plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE` or `PAUSED` — which is how a merely scheduled increase already shows up in a reader's forward-looking quote once `pending_effective_on` falls on or before their next cycle start — and increments the plan's `version`."

    Design: Difficulty/dual_variant_calc/cycle_price_preview_quote_diverges_from_billed_amount
    """
    state = _arrange_cycle_two_billed_under_a_scheduled_increase()

    assert state["subscription"]["next_cycle_price_cents"] == 1999
    assert state["invoice"]["base_line_cents"] != state["subscription"]["next_cycle_price_cents"]
    assert state["plan"]["price_change_state"] == "SCHEDULED"
    assert state["plan"]["standard_price_cents"] == 1499


def _arrange_two_plans_with_notice_windows_of_29_and_30_days():
    """Two SCHEDULED increases, one 29 days out and one exactly 30 days out."""
    set_clock_date("2026-09-01")
    plan_a = create_active_plan(**_standard_digital_plan("Digital Notice A"))
    schedule_price_change(plan_a["id"], 1799, "2026-09-30", "NONE")
    plan_b = create_active_plan(**_standard_digital_plan("Digital Notice B"))
    schedule_price_change(plan_b["id"], 1799, "2026-10-01", "NONE")
    return {"plan_a": plan_a, "plan_b": plan_b}


def test_notice_dispatch_refuses_a_twenty_nine_day_window_and_leaves_the_pipeline_scheduled():
    """29 days from the clock date is short of the gate, so nothing is recorded.

    PRD: "The notice window is the hard compliance gate: the number of days from the clock date to `pending_effective_on` must be at least thirty (a full four weeks plus two days of margin), and a shorter window is refused with `ERR_PRICE_NOTICE_WINDOW_TOO_SHORT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/price_notice_window_boundary_thirty_days_exactly
    """
    state = _arrange_two_plans_with_notice_windows_of_29_and_30_days()

    response = api_client.dispatch_price_change_notices(
        state["plan_a"]["id"], OFFICER_ONE_HEADERS
    )
    validate_error(response, "ERR_PRICE_NOTICE_WINDOW_TOO_SHORT", 422)

    plan_a = read_plan(state["plan_a"]["id"])
    assert plan_a["price_change_state"] == "SCHEDULED"
    assert plan_a["notice_sent_on"] is None
    assert plan_a["notice_sent_by_user_id"] is None


def test_notice_dispatch_accepts_a_window_of_exactly_thirty_days_and_records_the_officer():
    """Exactly thirty days clears the gate and stamps the acting compliance identity.

    PRD: "Only a `ComplianceOfficer` may dispatch the regulated advance notices, moving the pipeline `SCHEDULED → NOTICE_SENT`."
    PRD: "Dispatch sets `notice_sent_on` to the clock date, records the acting `X-User-ID` in `notice_sent_by_user_id`, and creates one reader event of type `PRICE_INCREASE_NOTICE` — carrying a `weight` of 0, so notices never move an engagement score — for each reader holding a subscription on this plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE`, `PAUSED` or `CANCEL_SCHEDULED`."

    Design: Difficulty/boundary_precision_check/price_notice_window_boundary_thirty_days_exactly
    """
    state = _arrange_two_plans_with_notice_windows_of_29_and_30_days()

    response = api_client.dispatch_price_change_notices(
        state["plan_b"]["id"], OFFICER_ONE_HEADERS
    )
    validate_success(response, 200)

    plan_b = read_plan(state["plan_b"]["id"])
    assert plan_b["price_change_state"] == "NOTICE_SENT"
    assert plan_b["notice_sent_on"] == "2026-09-01"
    assert plan_b["notice_sent_by_user_id"] == OFFICER_ONE_ID
    assert plan_b["pending_effective_on"] == "2026-10-01"


def _arrange_draft_plan_and_registered_reader():
    """A plan that was never activated, plus a reader who could otherwise pay."""
    set_clock_date("2026-09-01")
    plan = create_plan(**_standard_digital_plan("Digital Draft D"))
    reader = create_registered_reader("draftsub@mail.test", propensity_band="MEDIUM")
    return {"plan": plan, "reader": reader}


def test_subscription_on_a_draft_plan_is_refused_even_with_a_current_version_guard():
    """The body is well formed and the guard is fresh; only DRAFT stands in the way.

    PRD: "Draft plans are fully authored but not sellable; only a plan whose `status` is `ACTIVE` may take a new subscription, fund a group account, or receive a scheduled price change, and an attempt to do any of those against a `DRAFT` plan answers `ERR_PLAN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/subscription_cannot_be_created_on_draft_plan_rejected
    """
    state = _arrange_draft_plan_and_registered_reader()

    response = api_client.create_subscription(
        f.create_subscription_payload(
            state["reader"]["id"], state["plan"]["id"], state["plan"]["version"]
        ),
        OPS_AGENT_HEADERS,
    )
    validate_error(response, "ERR_PLAN_NOT_ACTIVE", 409)


def test_refused_draft_subscription_leaves_plan_counters_and_reader_entitlement_untouched():
    """No subscription row, no version bump on the plan, no entitlement for the reader.

    PRD: "A newly authored plan is born in `status` `DRAFT`, with `active_subscription_count` at 0 and its `price_change_state` at `NONE`."
    PRD: "A reader's `entitlement_source` is `SUBSCRIPTION`, `SEAT` or `NONE`, and `SUBSCRIPTION` outranks `SEAT` when both apply."

    Design: Difficulty/cross_entity_state_dependency/subscription_cannot_be_created_on_draft_plan_rejected
    """
    state = _arrange_draft_plan_and_registered_reader()

    api_client.create_subscription(
        f.create_subscription_payload(
            state["reader"]["id"], state["plan"]["id"], state["plan"]["version"]
        ),
        OPS_AGENT_HEADERS,
    )

    plan = read_plan(state["plan"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan["version"] == 1
    assert plan["active_subscription_count"] == 0

    rows, _ = validate_paginated(
        api_client.list_subscriptions(
            OPS_AGENT_HEADERS, {"offer_plan_id": state["plan"]["id"]}
        )
    )
    assert rows == []
    assert read_reader(state["reader"]["id"])["entitlement_source"] == "NONE"
