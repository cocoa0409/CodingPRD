"""What a settled invoice, a closed flow and a mis-cast role are all refused."""

from test_helpers import (
    OFFICER_ONE_HEADERS,
    OFFICER_TWO_HEADERS,
    OPS_AGENT_HEADERS,
    api_client,
    create_active_plan,
    create_hold,
    create_registered_reader,
    fresh_group_version,
    fresh_plan_version,
    invite_seat,
    invoice_for_cycle,
    list_holds,
    make_group_admin_headers,
    make_reader_headers,
    open_subscription,
    read_cancellation_request,
    read_group,
    read_invoice,
    read_plan,
    read_reader,
    read_seat,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    setup_institutional_group,
    setup_noticed_price_change,
    start_cancellation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f


def test_a_settled_invoice_takes_no_second_payment():
    """The episode is still open, so the refusal has to come from the invoice status.

    PRD: "Before any attempt is admitted at all, the episode must still be open — the `dunning_status` must not be `FAILED_FINAL` and `attempt_no` must not exceed `max_payment_attempts`, otherwise `ERR_DUNNING_EXHAUSTED` — and only then is the invoice checked for payability: it must be `OPEN` or `PAST_DUE`, since a `PAID` or `VOID` invoice takes no further attempt, otherwise `ERR_INVOICE_NOT_PAYABLE`."
    PRD: "It sets the invoice to `PAID` with `paid_on` at the clock date, sets `paid_through_on` to `cycle_start_on` advanced by the plan's `cycle_days`, recomputes `tenure_cycles` as the count of paid invoices, recomputes the reader's `entitlement_source` to `SUBSCRIPTION`, and recomputes `next_cycle_price_cents`."

    Design: Corner/errors/payment_attempt_on_paid_invoice_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Paid")
    reader = create_registered_reader("paid@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    invoice = invoice_for_cycle(subscription["id"], 1)
    record_payment(invoice, "SUCCEEDED", 499)
    assert read_subscription(subscription["id"])["dunning_status"] == "CURRENT"

    response = api_client.create_payment_attempt(
        invoice["id"], f.create_payment_attempt_payload("SUCCEEDED", 499), OPS_AGENT_HEADERS
    )

    validate_error(response, "ERR_INVOICE_NOT_PAYABLE", 409)
    _, meta = validate_paginated(
        api_client.list_payment_attempts(invoice["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 1
    settled = read_invoice(invoice["id"])
    assert settled["status"] == "PAID"
    assert settled["paid_on"] == "2026-09-01"
    after = read_subscription(subscription["id"])
    assert after["paid_through_on"] == "2026-10-01"
    assert after["tenure_cycles"] == 1


def test_a_retry_on_the_day_of_the_decline_is_too_early():
    """The invoice is PAST_DUE and therefore payable, so only the ladder can refuse.

    PRD: "A retry is only admissible once the clock has caught up: when `next_retry_on` is set, the clock date must be on or after it, and an earlier attempt answers `ERR_RETRY_TOO_EARLY`."
    PRD: "A non-final `SOFT_DECLINE` against an `OPEN` or `PAST_DUE` invoice drives the dunning dimension `CURRENT → RETRYING` and moves the invoice `OPEN → PAST_DUE`."

    Design: Corner/errors/retry_before_scheduled_retry_date_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Early Retry")
    reader = create_registered_reader("early@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    second = invoice_for_cycle(subscription["id"], 2)
    record_payment(second, "SOFT_DECLINE", 1499, "do_not_honor")
    assert read_subscription(subscription["id"])["next_retry_on"] == "2026-10-04"

    response = api_client.create_payment_attempt(
        second["id"], f.create_payment_attempt_payload("SUCCEEDED", 1499), OPS_AGENT_HEADERS
    )

    error = validate_error(response, "ERR_RETRY_TOO_EARLY", 409)
    assert error["error_id"] != "ERR_INVOICE_NOT_PAYABLE"
    _, meta = validate_paginated(
        api_client.list_payment_attempts(second["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 1
    assert read_invoice(second["id"])["status"] == "PAST_DUE"
    after = read_subscription(subscription["id"])
    assert after["next_retry_on"] == "2026-10-04"
    assert after["dunning_status"] == "RETRYING"


def test_an_exhausted_episode_outranks_the_written_off_invoice_and_the_dead_lifecycle():
    """Two rules could answer here; the dunning rule is the one the ladder names first.

    PRD: "First, the dunning-episode check precedes the invoice-status check: a further payment attempt against the written-off invoice of a non-pay-cancelled subscription answers `ERR_DUNNING_EXHAUSTED`, not `ERR_INVOICE_NOT_PAYABLE`."
    PRD: "This is also why recording a payment attempt is **not** covered by the terminal-subscription rule at all — an attempt against a subscription whose lifecycle has already ended is answered by the dunning rule."
    PRD: "Hop three closes the dunning episode unsuccessfully: `dunning_status` becomes `FAILED_FINAL`, `next_retry_on` is cleared to null, and `lifecycle_status` moves `ACTIVE → CANCELLED_NONPAY` with `access_until` set to the clock date, so entitlement lapses today rather than at the end of a paid period."

    Design: Corner/errors/payment_attempt_after_final_decline_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Exhausted")
    reader = create_registered_reader("exhausted@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    second = invoice_for_cycle(subscription["id"], 2)
    record_payment(second, "SOFT_DECLINE", 1499, "do_not_honor")
    set_clock_date("2026-10-04")
    final = record_payment(second, "HARD_DECLINE", 1499, "stolen_card")
    assert final["attempt_no"] == 2
    assert final["is_final"] is True
    assert read_invoice(second["id"])["status"] == "WRITTEN_OFF"
    ended = read_subscription(subscription["id"])
    assert ended["dunning_status"] == "FAILED_FINAL"
    assert ended["next_retry_on"] is None
    assert ended["lifecycle_status"] == "CANCELLED_NONPAY"
    assert ended["access_until"] == "2026-10-04"

    response = api_client.create_payment_attempt(
        second["id"], f.create_payment_attempt_payload("SUCCEEDED", 1499), OPS_AGENT_HEADERS
    )

    error = validate_error(response, "ERR_DUNNING_EXHAUSTED", 409)
    assert error["error_id"] != "ERR_INVOICE_NOT_PAYABLE"
    assert error["error_id"] != "ERR_SUBSCRIPTION_TERMINAL"
    _, meta = validate_paginated(
        api_client.list_payment_attempts(second["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 2
    lapsed = read_reader(reader["id"])
    assert lapsed["entitlement_source"] == "NONE"
    assert lapsed["churn_risk_band"] == "SEVERE"


def test_a_confirmed_flow_can_no_longer_be_pitched_a_save_offer():
    """The check reads the request, not the subscription that is merely scheduled to end.

    PRD: "A request that is `CONFIRMED`, `COMPLETED` or `ABANDONED` — or `SAVE_OFFER_ACCEPTED`, since retention closes the flow — accepts nothing further and answers `ERR_CANCELLATION_REQUEST_CLOSED`."
    PRD: "Hop one sets the request's `status` to `CONFIRMED`, its `confirmed_on` to the clock date and its `effective_on` to the subscription's `paid_through_on`, and expires any save offer on that request still in `PRESENTED` to `EXPIRED`."

    Design: Corner/errors/save_offer_on_confirmed_request_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Closed")
    reader = create_registered_reader("closed@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    request = start_cancellation(subscription["id"], "CONTENT", reader_headers)
    validate_success(api_client.confirm_cancellation(request["id"], reader_headers), 200)

    response = api_client.create_save_offer(
        request["id"],
        f.create_save_offer_payload(
            "RETENTION_DISCOUNT", discount_pct=0.2, duration_cycles=2
        ),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_CANCELLATION_REQUEST_CLOSED", 409)
    closed = read_cancellation_request(request["id"])
    assert closed["status"] == "CONFIRMED"
    assert closed["effective_on"] == "2026-10-01"
    assert closed["save_offer_count"] == 0
    assert read_subscription(subscription["id"])["lifecycle_status"] == "CANCEL_SCHEDULED"
    _, meta = validate_paginated(
        api_client.list_save_offers(request["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_reader_may_not_open_their_own_subscription_or_run_the_nightly_batch():
    """The identical body that a Reader is refused succeeds for the ops agent.

    PRD: "If the headers are well formed but the declared role is not permitted to perform the requested operation, or a role bound to a specific entity acts on a resource it does not own, the answer is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "This role runs consumer-revenue operations: it creates readers, opens subscriptions, creates group accounts, records processor results, presents save offers, releases holds, and triggers the nightly batch."
    PRD: "A `SubscriptionOpsAgent` opens a subscription by supplying the `reader_id` of the paying reader, the `offer_plan_id` of the governing plan, the mandatory `expected_offer_plan_version` guard, and — only for the institutional subscription that funds a group's seats — a `group_account_id`."

    Design: Corner/rbac/reader_cannot_open_a_subscription_or_run_the_batch_denied
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital RBAC")
    reader = create_registered_reader("rbac@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    payload = f.create_subscription_payload(
        reader["id"], plan["id"], fresh_plan_version(plan["id"])
    )

    denied_open = api_client.create_subscription(payload, reader_headers)
    denied_run = api_client.create_billing_run("FULL", reader_headers)

    validate_error(denied_open, "ERR_UNAUTHORIZED", 403)
    validate_error(denied_run, "ERR_UNAUTHORIZED", 403)
    _, meta = validate_paginated(api_client.list_subscriptions(OPS_AGENT_HEADERS))
    assert meta["total_count"] == 0
    granted = validate_success(
        api_client.create_subscription(payload, OPS_AGENT_HEADERS), 201
    )
    assert granted["lifecycle_status"] == "PENDING_ACTIVATION"
    assert granted["cycle_index"] == 1


def test_a_group_admin_is_powerless_over_a_group_they_do_not_own():
    """Both admins carry the same role; only ownership of the group separates them.

    PRD: "When `X-User-Role` is `GroupAdmin`, `X-User-ID` is the `id` of the acting `GroupAccount`; ownership checks compare the `GroupAccount` identifier in the path (or the `group_account_id` of the targeted seat) to `X-User-ID`."
    PRD: "**Reclaiming a seat** is the `GroupAdmin`'s exclusive act and works from either `INVITED` — revoking a pending invitation before it is claimed — or `ACTIVE`. Either way the seat becomes `RECLAIMED` with `ends_on` set to the clock date, the group's `seats_assigned_count` and `seats_available_count` are recomputed so the conservation invariant still holds, the group's `version` increments, and the reader's `entitlement_source` is recomputed to `NONE` unless a subscription entitles them."

    Design: Corner/rbac/group_admin_cannot_touch_another_groups_seats_rejected
    """
    scenario = setup_institutional_group(
        seat_capacity=2,
        group_name="Group A",
        allowed_email_domain="a.test",
        funding_reader_email="bursar@a.test",
        clock_date="2026-09-01",
        name="Seats RBAC",
        per_seat_price_cents=400,
    )
    group_a = scenario["group"]["id"]
    admin_a = scenario["group_headers"]
    group_b = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                scenario["plan"]["id"],
                seat_capacity=2,
                name="Group B",
                admin_email="bursar@b.test",
                allowed_email_domain="b.test",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )
    admin_b = make_group_admin_headers(group_b["id"])
    student = create_registered_reader("student@a.test")
    version_before = fresh_group_version(group_a, admin_a)

    intruding_invite = api_client.create_seat(
        group_a,
        f.create_seat_payload(student["id"], "2026-09-02", version_before),
        admin_b,
    )

    validate_error(intruding_invite, "ERR_UNAUTHORIZED", 403)
    untouched = read_group(group_a, admin_a)
    assert untouched["seats_assigned_count"] == 0
    assert untouched["version"] == version_before
    seat = invite_seat(group_a, student["id"], "2026-09-02", admin_headers=admin_a)
    assert seat["status"] == "INVITED"
    assert read_group(group_a, admin_a)["seats_assigned_count"] == 1

    intruding_reclaim = api_client.reclaim_seat(seat["id"], admin_b)

    validate_error(intruding_reclaim, "ERR_UNAUTHORIZED", 403)
    assert read_seat(seat["id"], admin_a)["status"] == "INVITED"
    reclaimed = validate_success(api_client.reclaim_seat(seat["id"], admin_a), 200)
    assert reclaimed["status"] == "RECLAIMED"
    assert reclaimed["ends_on"] == "2026-09-01"
    freed = read_group(group_a, admin_a)
    assert freed["seats_assigned_count"] == 0
    assert freed["seats_available_count"] == 2


def test_a_shared_operation_is_still_scoped_to_the_reader_who_owns_the_subscription():
    """Reader and ops agent both act on this subscription; a second reader may not.

    PRD: "Concretely, a `Reader` may only act on a subscription whose `reader_id` equals `X-User-ID`, on reader events whose `reader_id` equals `X-User-ID`, and on a seat whose `reader_id` equals `X-User-ID`; the same rule extends transitively to invoices, holds, cancellation requests and save offers hanging beneath that reader's own subscription."
    PRD: "A `Reader` on their own subscription, or a `SubscriptionOpsAgent` on their behalf, starts it by supplying a `reason_code` — one of `PRICE`, `CONTENT`, `TECHNICAL`, `LIFE_CHANGE` or `OTHER`."
    PRD: "The request is created with `status` `INITIATED`, `save_offer_count` at 0 and `retained` false, and its `confirmed_on` and `effective_on` null."

    Design: Corner/rbac/holds_and_cancellations_shared_but_scoped_to_the_owning_reader
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Shared")
    owner = create_registered_reader("owner@mail.test")
    stranger = create_registered_reader("stranger@mail.test")
    subscription = open_subscription(owner["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)

    hold = create_hold(
        subscription["id"],
        "PAUSE_BILLING",
        "2026-09-20",
        "2026-09-26",
        make_reader_headers(owner["id"]),
    )
    intruding_hold = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("PAUSE_BILLING", "2026-10-10", "2026-10-16"),
        make_reader_headers(stranger["id"]),
    )

    assert hold["status"] == "SCHEDULED"
    validate_error(intruding_hold, "ERR_UNAUTHORIZED", 403)
    assert len(list_holds(subscription["id"])) == 1
    request = validate_success(
        api_client.create_cancellation_request(
            subscription["id"], {"reason_code": "PRICE"}, OPS_AGENT_HEADERS
        ),
        201,
    )
    assert request["status"] == "INITIATED"
    assert request["save_offer_count"] == 0
    assert request["retained"] is False
    assert read_subscription(subscription["id"])["lifecycle_status"] == "ACTIVE"


def test_the_officer_who_sent_the_notices_may_not_also_apply_the_increase():
    """One role, two identities: only the recorded notice sender is barred.

    PRD: "And the officer applying the increase must not be the officer who noticed it: the acting `X-User-ID` must differ from `notice_sent_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."
    PRD: "Dispatch sets `notice_sent_on` to the clock date, records the acting `X-User-ID` in `notice_sent_by_user_id`, and creates one reader event of type `PRICE_INCREASE_NOTICE` — carrying a `weight` of 0, so notices never move an engagement score — for each reader holding a subscription on this plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE`, `PAUSED` or `CANCEL_SCHEDULED`."
    PRD: "In the first hop, `standard_price_cents` is overwritten with `pending_price_cents` and `price_change_state` becomes `APPLIED`."

    Design: Corner/rbac/price_change_apply_by_the_noticing_officer_rejected
    """
    scenario = setup_noticed_price_change(
        OFFICER_ONE_HEADERS,
        pending_price_cents=1799,
        pending_effective_on="2026-10-15",
        grandfather_policy="NONE",
        clock_date="2026-09-01",
        name="Digital SoD",
    )
    plan_id = scenario["plan"]["id"]
    assert scenario["plan"]["notice_sent_by_user_id"] == "officer-1"
    assert scenario["plan"]["price_change_state"] == "NOTICE_SENT"
    set_clock_date("2026-10-15")

    response = api_client.apply_price_change(plan_id, OFFICER_ONE_HEADERS)

    error = validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)
    assert error["error_id"] != "ERR_UNAUTHORIZED"
    unchanged = read_plan(plan_id)
    assert unchanged["standard_price_cents"] == 1499
    assert unchanged["price_change_state"] == "NOTICE_SENT"
    applied = validate_success(
        api_client.apply_price_change(plan_id, OFFICER_TWO_HEADERS), 200
    )
    assert applied["standard_price_cents"] == 1799
    assert applied["price_change_state"] == "APPLIED"
    assert applied["version"] > unchanged["version"]
