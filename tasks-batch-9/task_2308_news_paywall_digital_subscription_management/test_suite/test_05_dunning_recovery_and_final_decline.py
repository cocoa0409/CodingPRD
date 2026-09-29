"""The recovery cycle across three dimensions, and the five-hop final decline."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_print_plan,
    create_hold,
    create_registered_reader,
    invoice_for_cycle,
    make_reader_headers,
    open_subscription,
    read_hold,
    read_invoice,
    read_reader,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    validate_paginated,
)


def _print_plan(name):
    return create_active_print_plan(
        name=name,
        intro_price_cents=999,
        intro_cycles=1,
        standard_price_cents=1899,
        standard_from_cycle=2,
        cycle_days=30,
        print_component_cents=900,
        print_deliveries_per_cycle=4,
        print_delivery_days=["SUN"],
    )


def _arrange_recovered_episode_while_a_vacation_hold_is_in_force():
    """One soft decline, one recovery, and a DUNNING pass closing the episode."""
    set_clock_date("2026-09-01")
    plan = _print_plan("Print + Digital P3")
    reader = create_registered_reader("reader6@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 999)
    hold = create_hold(
        subscription["id"],
        "VACATION_DELIVERY",
        "2026-10-04",
        "2026-10-11",
        reader_headers,
    )

    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    cycle2 = invoice_for_cycle(subscription["id"], 2)

    set_clock_date("2026-10-05")
    run_billing("HOLDS_ONLY")
    record_payment(cycle2, "SOFT_DECLINE", 1899, "insufficient_funds")

    set_clock_date("2026-10-08")
    record_payment(cycle2, "SUCCEEDED", 1899)
    run_billing("DUNNING_ONLY")
    return {
        "plan": plan,
        "reader": reader,
        "subscription": read_subscription(subscription["id"]),
        "invoice": read_invoice(cycle2["id"]),
        "hold": read_hold(hold["id"]),
    }


def test_recovery_closes_the_dunning_episode_while_the_print_dimension_stays_held():
    """Lifecycle, dunning and print end this scenario at ACTIVE, CURRENT and HELD.

    PRD: "A subscription does not have "a status". It has **three independent status dimensions**, each with its own value set, its own transitions and its own cycles, and any combination that the transition rules permit is legal."
    PRD: "The DUNNING pass then closes the episode: a subscription whose `dunning_status` is `RECOVERED` and none of whose invoices is `PAST_DUE` moves `RECOVERED → CURRENT` with `dunning_first_failed_on` cleared to null."
    PRD: "A `VACATION_DELIVERY` hold reaching its start date moves the hold to `ACTIVE` and drives the print dimension `SCHEDULED → HELD`."

    Design: Difficulty/non_linear_state_machine/subscription_three_dimensions_move_independently_through_dunning_cycle
    """
    state = _arrange_recovered_episode_while_a_vacation_hold_is_in_force()

    subscription = state["subscription"]
    assert subscription["lifecycle_status"] == "ACTIVE"
    assert subscription["dunning_status"] == "CURRENT"
    assert subscription["print_fulfillment_status"] == "HELD"
    assert subscription["dunning_first_failed_on"] is None
    assert subscription["next_retry_on"] is None
    assert state["hold"]["status"] == "ACTIVE"


def test_recovered_invoice_is_paid_on_the_retry_date_and_advances_the_paid_through_date():
    """Two attempts sit on the cycle-2 invoice, and service runs to 2026-10-31.

    PRD: "A `SUCCEEDED` outcome against a `PAST_DUE` invoice drives `RETRYING → RECOVERED` and moves the invoice `PAST_DUE → PAID`. It sets `paid_on` to the clock date, clears `next_retry_on` to null, advances `paid_through_on` by the plan's `cycle_days`, recomputes `tenure_cycles`, and re-derives the reader's `churn_risk_band` from `engagement_score` — the dunning override is lifted, so a well-engaged reader immediately climbs back out of `SEVERE`."
    PRD: "`credit_line_cents` is the sum of `credit_cents` over the subscription's holds whose `status` is `COMPLETED` and whose `credit_applied` is false, taken in `end_date` ascending then `created_at` ascending order. Holds that are `SCHEDULED`, `ACTIVE` or `RELEASED` never contribute."

    Design: Difficulty/non_linear_state_machine/subscription_three_dimensions_move_independently_through_dunning_cycle
    """
    state = _arrange_recovered_episode_while_a_vacation_hold_is_in_force()

    invoice = state["invoice"]
    assert invoice["base_line_cents"] == 1899
    assert invoice["credit_line_cents"] == 0
    assert invoice["status"] == "PAID"
    assert invoice["paid_on"] == "2026-10-08"
    assert state["subscription"]["paid_through_on"] == "2026-10-31"

    attempts, meta = validate_paginated(
        api_client.list_payment_attempts(invoice["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 2
    assert len(attempts) == 2


def _arrange_hard_decline_against_the_second_cycle_invoice():
    """A single card_revoked hard decline fired while a hold is still SCHEDULED."""
    set_clock_date("2026-09-01")
    plan = _print_plan("Print + Digital P4")
    reader = create_registered_reader("reader7@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 999)
    hold = create_hold(
        subscription["id"],
        "VACATION_DELIVERY",
        "2026-10-04",
        "2026-10-11",
        reader_headers,
    )

    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    cycle2 = invoice_for_cycle(subscription["id"], 2)
    attempt = record_payment(cycle2, "HARD_DECLINE", 1899, "card_revoked")
    return {
        "plan": plan,
        "reader": reader,
        "subscription": read_subscription(subscription["id"]),
        "invoice": read_invoice(cycle2["id"]),
        "hold": read_hold(hold["id"]),
        "attempt": attempt,
    }


def test_first_hard_decline_is_final_and_writes_the_invoice_off():
    """A hard decline is final at attempt one, with no retry ever scheduled.

    PRD: "`is_final` is true when the `outcome` is `HARD_DECLINE`, and also when the `outcome` is `SOFT_DECLINE` and `attempt_no` is greater than or equal to `max_payment_attempts`."
    PRD: "Hop one persists the attempt with `is_final` true. Hop two moves the invoice to `WRITTEN_OFF`."

    Design: Difficulty/transitive_cascade/final_decline_cascades_five_hops_to_released_credit
    """
    state = _arrange_hard_decline_against_the_second_cycle_invoice()

    assert state["attempt"]["attempt_no"] == 1
    assert state["attempt"]["is_final"] is True
    assert state["invoice"]["status"] == "WRITTEN_OFF"
    assert state["subscription"]["next_retry_on"] is None


def test_final_decline_ends_the_relationship_today_rather_than_at_the_cycle_end():
    """The dunning dimension fails for good and access lapses on the clock date.

    PRD: "Hop three closes the dunning episode unsuccessfully: `dunning_status` becomes `FAILED_FINAL`, `next_retry_on` is cleared to null, and `lifecycle_status` moves `ACTIVE → CANCELLED_NONPAY` with `access_until` set to the clock date, so entitlement lapses today rather than at the end of a paid period."

    Design: Difficulty/transitive_cascade/final_decline_cascades_five_hops_to_released_credit
    """
    state = _arrange_hard_decline_against_the_second_cycle_invoice()

    subscription = state["subscription"]
    assert subscription["dunning_status"] == "FAILED_FINAL"
    assert subscription["lifecycle_status"] == "CANCELLED_NONPAY"
    assert subscription["access_until"] == "2026-10-01"


def test_released_hold_credit_leaves_pending_at_zero_without_ever_reaching_lifetime():
    """The scheduled hold is released with its frozen credit reversed, not banked.

    PRD: "Hop four releases the terminal subscription's occupations and seats: every hold on it whose `status` is `SCHEDULED` or `ACTIVE` becomes `RELEASED`, and when `group_account_id` is set, the funding relationship collapses — the group account's `status` becomes `SUSPENDED` and every seat under it whose `status` is `INVITED` or `ACTIVE` becomes `RECLAIMED` with `ends_on` set to the clock date."
    PRD: "Hop five recomputes the counters the previous hop invalidated: the released holds leave the pending-credit input set so `pending_credit_cents` falls to 0, the reclaimed seats leave the occupancy measure so the group's `seats_assigned_count` and `seats_available_count` are recomputed, the reader's `entitlement_source` becomes `NONE`, and the reader's `churn_risk_band` is recomputed to `SEVERE` under the dunning override."

    Design: Difficulty/transitive_cascade/final_decline_cascades_five_hops_to_released_credit
    """
    state = _arrange_hard_decline_against_the_second_cycle_invoice()

    hold = state["hold"]
    assert hold["status"] == "RELEASED"
    assert hold["credit_cents"] == 450
    assert hold["credit_applied"] is False
    assert state["subscription"]["pending_credit_cents"] == 0
    assert state["subscription"]["lifetime_credit_cents"] == 0

    reader = read_reader(state["reader"]["id"])
    assert reader["entitlement_source"] == "NONE"
    assert reader["churn_risk_band"] == "SEVERE"
