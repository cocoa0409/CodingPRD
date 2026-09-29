"""The single save offer, the decline-and-return path, and the four-hop confirm chain."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_plan,
    create_active_print_plan,
    create_hold,
    create_registered_reader,
    invoice_for_cycle,
    make_reader_headers,
    open_subscription,
    present_save_offer,
    read_cancellation_request,
    read_hold,
    read_reader,
    read_save_offer,
    read_subscription,
    record_payment,
    set_clock_date,
    start_cancellation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f


def _digital_plan(name):
    return create_active_plan(
        name=name,
        bundle_type="DIGITAL_ONLY",
        intro_price_cents=499,
        intro_cycles=1,
        standard_price_cents=1499,
        standard_from_cycle=2,
        cycle_days=30,
    )


def _arrange_declined_save_offer_inside_an_open_flow():
    """A 25 percent retention discount presented and then declined by the reader."""
    set_clock_date("2026-09-01")
    plan = _digital_plan("Digital Standard C")
    reader = create_registered_reader("declineflow@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    request = start_cancellation(subscription["id"], "CONTENT", reader_headers)
    offer = present_save_offer(
        request["id"], "RETENTION_DISCOUNT", discount_pct=0.25, duration_cycles=3
    )
    decided = validate_success(
        api_client.decide_save_offer(offer["id"], "DECLINED", reader_headers), 200
    )
    return {
        "plan": plan,
        "reader": reader,
        "reader_headers": reader_headers,
        "subscription": subscription,
        "request": request,
        "offer": decided,
    }


def test_declining_the_offer_returns_the_request_to_initiated_with_no_discount_applied():
    """One keystroke puts the reader back on the cancellation path, discount-free.

    PRD: "Declining takes the decline branch. The offer becomes `DECLINED` with `decided_on` at the clock date and the request returns `SAVE_OFFER_PRESENTED → INITIATED`, so the reader is back on the cancellation path with one keystroke."

    Design: Difficulty/non_linear_state_machine/cancellation_flow_declines_offer_reverts_then_confirms
    """
    state = _arrange_declined_save_offer_inside_an_open_flow()

    offer = read_save_offer(state["offer"]["id"])
    assert offer["status"] == "DECLINED"
    assert offer["decided_on"] == "2026-09-01"

    request = read_cancellation_request(state["request"]["id"])
    assert request["status"] == "INITIATED"
    assert request["retained"] is False
    subscription = read_subscription(state["subscription"]["id"])
    assert subscription["lifecycle_status"] == "ACTIVE"
    assert float(subscription["retention_discount_pct"]) == 0


def test_a_declined_offer_still_consumes_the_only_permitted_presentation():
    """A second instrument of a different type is refused, and no row is written.

    PRD: "Because the regulatory cap is one offer per flow, a second presentation answers `ERR_SAVE_OFFER_LIMIT_EXCEEDED` — and a **declined** offer still counts, so a reader who says no can never be re-pitched inside the same flow."
    PRD: "`save_offer_count` stays at 1, which is what makes the single-offer rule bite on the way back."

    Design: Difficulty/non_linear_state_machine/cancellation_flow_declines_offer_reverts_then_confirms
    """
    state = _arrange_declined_save_offer_inside_an_open_flow()

    response = api_client.create_save_offer(
        state["request"]["id"],
        f.create_save_offer_payload("PAUSE", pause_days=30),
        OPS_AGENT_HEADERS,
    )
    validate_error(response, "ERR_SAVE_OFFER_LIMIT_EXCEEDED", 409)

    assert read_cancellation_request(state["request"]["id"])["save_offer_count"] == 1
    offers, meta = validate_paginated(
        api_client.list_save_offers(state["request"]["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 1
    assert len(offers) == 1


def test_confirming_after_a_decline_schedules_the_cancellation_for_the_paid_through_date():
    """The reader keeps what they paid for: access runs to 2026-10-01, not to today.

    PRD: "Hop one sets the request's `status` to `CONFIRMED`, its `confirmed_on` to the clock date and its `effective_on` to the subscription's `paid_through_on`, and expires any save offer on that request still in `PRESENTED` to `EXPIRED`."
    PRD: "Hop two moves the subscription `ACTIVE → CANCEL_SCHEDULED`, sets both `access_until` and `cancel_effective_on` to `paid_through_on` — the reader keeps what they paid for — and moves the print dimension from `SCHEDULED`, `HELD` or `INTERRUPTED` to `STOPPED_AT_CYCLE_END`."

    Design: Difficulty/non_linear_state_machine/cancellation_flow_declines_offer_reverts_then_confirms
    """
    state = _arrange_declined_save_offer_inside_an_open_flow()

    confirmed = validate_success(
        api_client.confirm_cancellation(
            state["request"]["id"], state["reader_headers"]
        ),
        200,
    )

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_on"] == "2026-09-01"
    assert confirmed["effective_on"] == "2026-10-01"
    assert confirmed["retained"] is False
    subscription = read_subscription(state["subscription"]["id"])
    assert subscription["lifecycle_status"] == "CANCEL_SCHEDULED"
    assert subscription["access_until"] == "2026-10-01"


def _arrange_pending_pause_offer_and_a_future_vacation_hold():
    """An undecided PAUSE offer plus a hold that starts after the paid-through date."""
    set_clock_date("2026-09-01")
    plan = create_active_print_plan(
        name="Print + Digital P5",
        intro_price_cents=999,
        intro_cycles=1,
        standard_price_cents=1899,
        standard_from_cycle=2,
        cycle_days=30,
        print_component_cents=900,
        print_deliveries_per_cycle=4,
        print_delivery_days=["SUN"],
    )
    reader = create_registered_reader("reader8@mail.test")
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
    request = start_cancellation(subscription["id"], "LIFE_CHANGE", reader_headers)
    offer = present_save_offer(request["id"], "PAUSE", pause_days=30)
    set_clock_date("2026-09-14")
    confirmed = validate_success(
        api_client.confirm_cancellation(request["id"], reader_headers), 200
    )
    return {
        "reader": reader,
        "subscription": read_subscription(subscription["id"]),
        "hold": read_hold(hold["id"]),
        "request": confirmed,
        "offer": read_save_offer(offer["id"]),
    }


def test_confirmation_expires_the_undecided_offer_and_stops_print_at_the_cycle_end():
    """Hops one and two: the request confirms today and print stops at the cycle end.

    PRD: "**Confirming the cancellation** is the regulated one-step exit, and it is reachable both directly from `INITIATED` and from `SAVE_OFFER_PRESENTED` without deciding the offer at all — that is the point of the regulation."
    PRD: "Hop one sets the request's `status` to `CONFIRMED`, its `confirmed_on` to the clock date and its `effective_on` to the subscription's `paid_through_on`, and expires any save offer on that request still in `PRESENTED` to `EXPIRED`."

    Design: Difficulty/transitive_cascade/cancellation_confirm_cascades_four_hops_to_credit_recompute
    """
    state = _arrange_pending_pause_offer_and_a_future_vacation_hold()

    assert state["request"]["status"] == "CONFIRMED"
    assert state["request"]["confirmed_on"] == "2026-09-14"
    assert state["request"]["effective_on"] == "2026-10-01"
    assert state["offer"]["status"] == "EXPIRED"
    subscription = state["subscription"]
    assert subscription["lifecycle_status"] == "CANCEL_SCHEDULED"
    assert subscription["access_until"] == "2026-10-01"
    assert subscription["cancel_effective_on"] == "2026-10-01"
    assert subscription["print_fulfillment_status"] == "STOPPED_AT_CYCLE_END"


def test_confirmation_releases_the_unservable_hold_and_recomputes_pending_credit_downward():
    """Hops three and four: a hold beyond access_until is released and its credit reversed.

    PRD: "Hop three follows from the print stop: every hold on the subscription whose `status` is `SCHEDULED` and whose `start_date` falls after `access_until` becomes `RELEASED`, because a hold can no longer be served once service has ended."
    PRD: "Hop four recomputes what hop three invalidated: each hold released in hop three drops out of the pending-credit input set, so `pending_credit_cents` is recomputed downward by exactly the sum of those holds' `credit_cents`, while `lifetime_credit_cents` is unchanged."

    Design: Difficulty/transitive_cascade/cancellation_confirm_cascades_four_hops_to_credit_recompute
    """
    state = _arrange_pending_pause_offer_and_a_future_vacation_hold()

    hold = state["hold"]
    assert hold["status"] == "RELEASED"
    assert hold["credit_cents"] == 450
    assert state["subscription"]["pending_credit_cents"] == 0
    assert state["subscription"]["lifetime_credit_cents"] == 0
    assert read_reader(state["reader"]["id"])["entitlement_source"] == "SUBSCRIPTION"


def _arrange_presented_offer_then_an_out_of_range_second_offer():
    """One PRESENTED offer, then a second one whose discount also breaks the cap."""
    set_clock_date("2026-09-01")
    plan = _digital_plan("Digital Standard S")
    reader = create_registered_reader("reader9@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    request = start_cancellation(subscription["id"], "PRICE", reader_headers)
    offer = present_save_offer(
        request["id"], "RETENTION_DISCOUNT", discount_pct=0.25, duration_cycles=3
    )
    return {"request": request, "offer": offer, "reader_headers": reader_headers}


def test_save_offer_limit_is_reported_ahead_of_the_discount_cap():
    """Both rules fire; the ladder reports the limit, never the range violation.

    PRD: "**Domain and safety rules**, in this relative order: notice window too short (`ERR_PRICE_NOTICE_WINDOW_TOO_SHORT`), notices not sent (`ERR_PRICE_NOTICE_NOT_SENT`), step-up ladder invalid (`ERR_STEP_UP_SCHEDULE_INVALID`), price change not yet effective (`ERR_PRICE_CHANGE_NOT_EFFECTIVE_YET`), save-offer limit exceeded (`ERR_SAVE_OFFER_LIMIT_EXCEEDED`), save-offer parameters out of range (`ERR_SAVE_OFFER_DISCOUNT_CAP`), seat domain mismatch (`ERR_SEAT_DOMAIN_MISMATCH`), group funding subscription not active (`ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE`), intervention not warranted (`ERR_INTERVENTION_NOT_WARRANTED`), system-only event type (`ERR_EVENT_TYPE_SYSTEM_ONLY`), reader not registered (`ERR_READER_NOT_REGISTERED`), article unpublished (`ERR_ARTICLE_UNPUBLISHED`), plan not a print bundle (`ERR_PLAN_NOT_PRINT_BUNDLE`), plan not institutional (`ERR_PLAN_NOT_INSTITUTIONAL`), hold start not future (`ERR_HOLD_START_NOT_FUTURE`), hold start in the past (`ERR_HOLD_START_IN_PAST`), hold interval invalid (`ERR_HOLD_INTERVAL_INVALID`), hold buffer violation (`ERR_HOLD_BUFFER_VIOLATION`), vacation day cap exceeded (`ERR_VACATION_DAY_CAP_EXCEEDED`), pause limit exceeded (`ERR_PAUSE_LIMIT_EXCEEDED`), seat interval invalid (`ERR_SEAT_INTERVAL_INVALID`), duplicate seat for the same reader (`ERR_SEAT_READER_DUPLICATE`), seat capacity exceeded (`ERR_SEAT_CAPACITY_EXCEEDED`), payment amount mismatch (`ERR_PAYMENT_AMOUNT_MISMATCH`), and finally the clock monotonicity rule (`ERR_CLOCK_NOT_MONOTONIC`)."
    PRD: "When more than one rule could reject a request, the rejection reported is always the one from the earliest rule in the following ladder. The ordering is normative, not incidental; a later check must never mask an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/save_offer_limit_outranks_discount_cap_rejected
    """
    state = _arrange_presented_offer_then_an_out_of_range_second_offer()

    response = api_client.create_save_offer(
        state["request"]["id"],
        f.create_save_offer_payload(
            "RETENTION_DISCOUNT", discount_pct=0.55, duration_cycles=3
        ),
        OPS_AGENT_HEADERS,
    )

    error = validate_error(response, "ERR_SAVE_OFFER_LIMIT_EXCEEDED", 409)
    assert error["error_id"] != "ERR_SAVE_OFFER_DISCOUNT_CAP"


def test_rejected_second_offer_leaves_the_first_offer_presented_and_the_count_at_one():
    """The refused presentation writes nothing: one PRESENTED row, count still one.

    PRD: "The presented offer is created with `status` `PRESENTED` and `presented_on` at the clock date, its `decided_on` null, carrying the `cancellation_request_id` of the flow it belongs to; its states are `PRESENTED`, `ACCEPTED`, `DECLINED` and `EXPIRED`."
    PRD: "A `SubscriptionOpsAgent` may present a single retention instrument inside an open flow, moving the request `INITIATED → SAVE_OFFER_PRESENTED`."

    Design: Difficulty/priority_pair_validation_conflict/save_offer_limit_outranks_discount_cap_rejected
    """
    state = _arrange_presented_offer_then_an_out_of_range_second_offer()
    api_client.create_save_offer(
        state["request"]["id"],
        f.create_save_offer_payload(
            "RETENTION_DISCOUNT", discount_pct=0.55, duration_cycles=3
        ),
        OPS_AGENT_HEADERS,
    )

    request = read_cancellation_request(state["request"]["id"])
    assert request["status"] == "SAVE_OFFER_PRESENTED"
    assert request["save_offer_count"] == 1
    offers, meta = validate_paginated(
        api_client.list_save_offers(state["request"]["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 1
    assert offers[0]["id"] == state["offer"]["id"]
    assert offers[0]["status"] == "PRESENTED"
