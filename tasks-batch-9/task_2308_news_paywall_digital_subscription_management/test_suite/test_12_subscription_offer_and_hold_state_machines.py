"""Activation, the retention branch, and what terminal states refuse to accept."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_plan,
    create_active_print_plan,
    create_hold,
    create_registered_reader,
    invoice_for_cycle,
    list_holds,
    make_reader_headers,
    open_subscription,
    present_save_offer,
    read_cancellation_request,
    read_hold,
    read_invoice,
    read_reader,
    read_save_offer,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    start_cancellation,
    validate_error,
    validate_success,
)
from test_helpers import factories as f


def test_the_first_successful_payment_is_what_makes_a_subscription_live():
    """One attempt against the cycle-1 invoice moves lifecycle, invoice and entitlement.

    PRD: "Recording a `SUCCEEDED` outcome against the cycle-1 invoice of a `PENDING_ACTIVATION` subscription — the invoice must be `OPEN`, must have `cycle_index` 1, and must belong to that subscription — drives `PENDING_ACTIVATION → ACTIVE`."
    PRD: "It sets the invoice to `PAID` with `paid_on` at the clock date, sets `paid_through_on` to `cycle_start_on` advanced by the plan's `cycle_days`, recomputes `tenure_cycles` as the count of paid invoices, recomputes the reader's `entitlement_source` to `SUBSCRIPTION`, and recomputes `next_cycle_price_cents`."
    PRD: "On a `PRINT_DIGITAL` plan the same success also moves `print_fulfillment_status` from `NOT_APPLICABLE` to `SCHEDULED`; on any other bundle that dimension stays `NOT_APPLICABLE` for life."

    Design: Corner/state_machines/subscription_activates_on_first_successful_payment
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Activate Sub")
    reader = create_registered_reader("activate@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    invoice = invoice_for_cycle(subscription["id"], 1)

    attempt = validate_success(
        api_client.create_payment_attempt(
            invoice["id"],
            f.create_payment_attempt_payload("SUCCEEDED", 499),
            OPS_AGENT_HEADERS,
        ),
        201,
    )

    assert attempt["attempt_no"] == 1
    assert attempt["is_final"] is False
    assert attempt["attempted_on"] == "2026-09-01"
    paid = read_invoice(invoice["id"])
    assert paid["status"] == "PAID"
    assert paid["paid_on"] == "2026-09-01"
    assert paid["base_line_cents"] == 499
    assert paid["price_source"] == "INTRO"
    live = read_subscription(subscription["id"])
    assert live["lifecycle_status"] == "ACTIVE"
    assert live["paid_through_on"] == "2026-10-01"
    assert live["print_fulfillment_status"] == "NOT_APPLICABLE"
    assert live["next_cycle_price_cents"] == 1499
    assert read_reader(reader["id"])["entitlement_source"] == "SUBSCRIPTION"


def _arrange_accepted_retention_discount(plan_name, reader_email):
    """A 25 percent discount for three cycles, accepted by the reader on 2026-09-01."""
    set_clock_date("2026-09-01")
    plan = create_active_plan(name=plan_name)
    reader = create_registered_reader(reader_email)
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    request = start_cancellation(subscription["id"], "PRICE", reader_headers)
    offer = present_save_offer(
        request["id"], "RETENTION_DISCOUNT", discount_pct=0.25, duration_cycles=3
    )
    validate_success(
        api_client.decide_save_offer(offer["id"], "ACCEPTED", reader_headers), 200
    )
    return {
        "reader_headers": reader_headers,
        "subscription": subscription,
        "request": request,
        "offer": offer,
    }


def test_accepting_the_offer_retains_the_reader_and_arms_the_discount():
    """The retention branch closes the flow without cancelling anything.

    PRD: "Accepting takes the retention branch. The offer becomes `ACCEPTED` with `decided_on` at the clock date, the request moves `SAVE_OFFER_PRESENTED → SAVE_OFFER_ACCEPTED`, and `retained` becomes true."
    PRD: "On a `RETENTION_DISCOUNT` or `DOWNGRADE`, the subscription's `retention_discount_pct` is set to the offer's `discount_pct` and its `retention_discount_cycles_remaining` to the offer's `duration_cycles`, then `next_cycle_price_cents` is recomputed."
    PRD: "On either shape, `lifecycle_status` stays `ACTIVE`: nothing is cancelled on this branch."

    Design: Corner/state_machines/save_offer_accepted_applies_retention_discount
    """
    state = _arrange_accepted_retention_discount("Digital Retain", "retain@mail.test")

    offer = read_save_offer(state["offer"]["id"])
    assert offer["status"] == "ACCEPTED"
    assert offer["decided_on"] == "2026-09-01"
    request = read_cancellation_request(state["request"]["id"])
    assert request["status"] == "SAVE_OFFER_ACCEPTED"
    assert request["retained"] is True
    subscription = read_subscription(state["subscription"]["id"])
    assert float(subscription["retention_discount_pct"]) == 0.25
    assert subscription["retention_discount_cycles_remaining"] == 3
    assert subscription["lifecycle_status"] == "ACTIVE"
    assert subscription["cancel_effective_on"] is None


def test_a_second_decision_on_a_decided_offer_cannot_stack_another_discount():
    """Deciding is once-only, so the late decline is refused and the terms hold.

    PRD: "The offer must still be `PRESENTED`, otherwise `ERR_SAVE_OFFER_ALREADY_DECIDED`, and the subscription must still be `ACTIVE`, otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Corner/state_machines/save_offer_second_decision_rejected
    """
    state = _arrange_accepted_retention_discount("Digital Retain2", "retain2@mail.test")

    response = api_client.decide_save_offer(
        state["offer"]["id"], "DECLINED", state["reader_headers"]
    )

    validate_error(response, "ERR_SAVE_OFFER_ALREADY_DECIDED", 409)
    assert read_save_offer(state["offer"]["id"])["status"] == "ACCEPTED"
    request = read_cancellation_request(state["request"]["id"])
    assert request["status"] == "SAVE_OFFER_ACCEPTED"
    subscription = read_subscription(state["subscription"]["id"])
    assert subscription["retention_discount_cycles_remaining"] == 3


def test_a_completed_hold_can_no_longer_be_released():
    """COMPLETED is terminal, so the credit the hold earned cannot be unwound.

    PRD: "A `SubscriptionOpsAgent` may release a hold whose `status` is `SCHEDULED` or `ACTIVE` and whose `credit_applied` is still false; a hold that is already `COMPLETED` or `RELEASED`, or whose credit has already been swept onto an invoice, answers `ERR_HOLD_NOT_RELEASABLE`."
    PRD: "The same pass retires holds that have run their course: an `ACTIVE` hold whose `end_date` is strictly before the clock date becomes `COMPLETED`, is reported in `holds_completed`, and its credit stays inside `pending_credit_cents` until a BILLING pass sweeps it onto an invoice."

    Design: Corner/state_machines/hold_release_after_completion_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_print_plan(
        name="Print Lockdown",
        intro_price_cents=999,
        intro_cycles=1,
        standard_price_cents=1899,
        standard_from_cycle=2,
        cycle_days=30,
        print_component_cents=900,
        print_deliveries_per_cycle=4,
        print_delivery_days=["SUN"],
    )
    reader = create_registered_reader("lockdown@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 999)
    hold = create_hold(
        subscription["id"],
        "VACATION_DELIVERY",
        "2026-09-06",
        "2026-09-13",
        make_reader_headers(reader["id"]),
    )
    set_clock_date("2026-09-06")
    run_billing("HOLDS_ONLY")
    set_clock_date("2026-09-14")
    run_billing("HOLDS_ONLY")

    response = api_client.release_hold(hold["id"], OPS_AGENT_HEADERS)

    validate_error(response, "ERR_HOLD_NOT_RELEASABLE", 409)
    settled = read_hold(hold["id"])
    assert settled["status"] == "COMPLETED"
    assert settled["credit_cents"] == 450
    assert settled["credit_applied"] is False
    after = read_subscription(subscription["id"])
    assert after["pending_credit_cents"] == 450
    assert after["print_fulfillment_status"] == "SCHEDULED"


def test_a_cancelled_subscription_answers_the_terminal_code_not_the_not_active_code():
    """Once the EXPIRY pass completes the cancellation, nothing may be booked on it.

    PRD: "A subscription whose `lifecycle_status` is `CANCELLED` or `CANCELLED_NONPAY` answers `ERR_SUBSCRIPTION_TERMINAL`; one that exists but is not `ACTIVE` — `PENDING_ACTIVATION`, `PAUSED` or `CANCEL_SCHEDULED` — answers `ERR_SUBSCRIPTION_NOT_ACTIVE`."
    PRD: "When the clock date passes `cancel_effective_on` — strictly after it — the pass drives `CANCEL_SCHEDULED → CANCELLED`, moves the print dimension `STOPPED_AT_CYCLE_END → STOPPED`, moves the linked `CONFIRMED` cancellation request `CONFIRMED → COMPLETED` (reported in `cancellations_completed`), and recomputes the reader's `entitlement_source` to `NONE` unless an `ACTIVE` seat still entitles them."

    Design: Corner/state_machines/hold_on_cancelled_subscription_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Terminal")
    reader = create_registered_reader("terminal@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    request = start_cancellation(subscription["id"], "OTHER", reader_headers)
    validate_success(
        api_client.confirm_cancellation(request["id"], reader_headers), 200
    )
    set_clock_date("2026-10-02")
    run_billing("EXPIRY_ONLY")

    response = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("PAUSE_BILLING", "2026-10-10", "2026-10-20"),
        OPS_AGENT_HEADERS,
    )

    error = validate_error(response, "ERR_SUBSCRIPTION_TERMINAL", 409)
    assert error["error_id"] != "ERR_SUBSCRIPTION_NOT_ACTIVE"
    after = read_subscription(subscription["id"])
    assert after["lifecycle_status"] == "CANCELLED"
    assert after["access_until"] == "2026-10-01"
    assert read_cancellation_request(request["id"])["status"] == "COMPLETED"
    assert list_holds(subscription["id"]) == []
    assert read_reader(reader["id"])["entitlement_source"] == "NONE"
