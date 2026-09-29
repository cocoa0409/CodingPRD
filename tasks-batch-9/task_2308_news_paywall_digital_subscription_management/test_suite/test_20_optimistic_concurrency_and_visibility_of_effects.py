"""Stale views, version arithmetic, and which effects wait for the nightly batch."""

from test_helpers import (
    OFFICER_NINE_HEADERS,
    OPS_AGENT_HEADERS,
    REVENUE_MANAGER_HEADERS,
    api_client,
    create_active_plan,
    create_hold,
    create_registered_reader,
    fresh_group_version,
    invite_seat,
    invoice_for_cycle,
    list_invoices,
    make_reader_headers,
    open_subscription,
    read_cancellation_request,
    read_group,
    read_hold,
    read_plan,
    read_reader,
    read_seat,
    read_subscription,
    record_payment,
    run_billing,
    schedule_price_change,
    set_clock_date,
    setup_institutional_group,
    start_cancellation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f


def test_a_price_change_between_read_and_write_invalidates_the_captured_plan_version():
    """The guard compares versions: the same body succeeds once the client re-reads.

    PRD: "**Opening a subscription** requires `expected_offer_plan_version` carrying the client's last observed `version` of the target `OfferPlan`. If that value does not equal the plan's current `version`, the create is rejected with `ERR_STALE_OFFER_PLAN_VERSION` (HTTP 412)."
    PRD: "A plan's `version` advances whenever a price change is scheduled, whenever notices are dispatched, whenever the change is applied, and whenever another subscription is opened against it — because `active_subscription_count` is a derived field on the plan."

    Design: Corner/cross_cutting_complexity_layers/stale_offer_plan_version_rejected_on_subscription_create
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital OCC")
    stale_version = plan["version"]
    reader = create_registered_reader("occ@mail.test")
    bumped = schedule_price_change(plan["id"], 1699, "2026-10-20", "ALL_EXISTING")
    fresh_version = bumped["version"]
    assert fresh_version == stale_version + 1

    response = api_client.create_subscription(
        f.create_subscription_payload(reader["id"], plan["id"], stale_version),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_STALE_OFFER_PLAN_VERSION", 412)
    _, meta = validate_paginated(api_client.list_subscriptions(OPS_AGENT_HEADERS))
    assert meta["total_count"] == 0
    assert read_plan(plan["id"])["version"] == fresh_version
    retried = validate_success(
        api_client.create_subscription(
            f.create_subscription_payload(reader["id"], plan["id"], fresh_version),
            OPS_AGENT_HEADERS,
        ),
        201,
    )
    assert retried["lifecycle_status"] == "PENDING_ACTIVATION"
    assert retried["cycle_index"] == 1
    assert retried["version"] == 1


def test_the_first_invitation_invalidates_the_capacity_picture_the_second_one_replays():
    """Capacity is free, so the 412 can only come from the replayed group version.

    PRD: "**Inviting a reader to a seat** requires `expected_group_account_version` carrying the client's last observed `version` of the target `GroupAccount`. If that value does not equal the group's current `version`, the invitation is rejected with `ERR_STALE_GROUP_ACCOUNT_VERSION` (HTTP 412)."
    PRD: "Because `seats_assigned_count` and `seats_available_count` are derived fields on the group, any prior seat assignment, reclaim or invite expiry has already advanced the version and invalidated the capacity picture the administrator based this assignment on."

    Design: Corner/cross_cutting_complexity_layers/stale_group_account_version_rejected_on_seat_assign
    """
    scenario = setup_institutional_group(
        seat_capacity=3,
        group_name="Lab Group",
        allowed_email_domain="lab.test",
        funding_reader_email="bursar@lab.test",
        clock_date="2026-09-01",
        name="Seats OCC",
        per_seat_price_cents=400,
    )
    group_id = scenario["group"]["id"]
    admin_headers = scenario["group_headers"]
    first_reader = create_registered_reader("one@lab.test")
    second_reader = create_registered_reader("two@lab.test")
    stale_version = fresh_group_version(group_id, admin_headers)
    invite_seat(
        group_id,
        first_reader["id"],
        "2026-09-02",
        admin_headers=admin_headers,
        expected_group_account_version=stale_version,
    )

    response = api_client.create_seat(
        group_id,
        f.create_seat_payload(second_reader["id"], "2026-09-02", stale_version),
        admin_headers,
    )

    error = validate_error(response, "ERR_STALE_GROUP_ACCOUNT_VERSION", 412)
    assert error["error_id"] != "ERR_SEAT_CAPACITY_EXCEEDED"
    _, meta = validate_paginated(
        api_client.list_seats(OPS_AGENT_HEADERS, {"group_account_id": group_id})
    )
    assert meta["total_count"] == 1
    after_refusal = read_group(group_id, admin_headers)
    assert after_refusal["seats_assigned_count"] == 1
    assert after_refusal["version"] == stale_version + 1
    second_seat = invite_seat(
        group_id,
        second_reader["id"],
        "2026-09-02",
        admin_headers=admin_headers,
        expected_group_account_version=after_refusal["version"],
    )
    assert read_seat(second_seat["id"], admin_headers)["status"] == "INVITED"
    settled = read_group(group_id, admin_headers)
    assert settled["seats_assigned_count"] == 2
    assert settled["seats_available_count"] == 1


def test_each_mutating_write_on_a_plan_moves_the_version_by_exactly_one():
    """Create, activate, schedule and notice make 1, 2, 3, 4; the read in between makes none.

    PRD: "Each entity touched in a chain has its own `updated_at` refreshed and its own `version` incremented."
    PRD: "Dispatch sets `notice_sent_on` to the clock date, records the acting `X-User-ID` in `notice_sent_by_user_id`, and creates one reader event of type `PRICE_INCREASE_NOTICE` — carrying a `weight` of 0, so notices never move an engagement score — for each reader holding a subscription on this plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE`, `PAUSED` or `CANCEL_SCHEDULED`. The plan's `version` increments."
    PRD: "Scheduling persists all three inputs, sets `price_change_state` to `SCHEDULED`, recomputes `next_cycle_price_cents` on every subscription of the plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE` or `PAUSED` — which is how a merely scheduled increase already shows up in a reader's forward-looking quote once `pending_effective_on` falls on or before their next cycle start — and increments the plan's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_mutating_write_on_the_plan
    """
    set_clock_date("2026-09-01")

    created = validate_success(
        api_client.create_offer_plan(
            f.create_offer_plan_payload(name="Digital Versioned"), REVENUE_MANAGER_HEADERS
        ),
        201,
    )
    read_back = read_plan(created["id"])
    activated = validate_success(
        api_client.activate_offer_plan(created["id"], REVENUE_MANAGER_HEADERS), 200
    )
    scheduled = validate_success(
        api_client.schedule_price_change(
            created["id"],
            f.schedule_price_change_payload(
                activated["version"], 1599, "2026-10-05", "TENURE_12_CYCLES"
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        200,
    )
    noticed = validate_success(
        api_client.dispatch_price_change_notices(created["id"], OFFICER_NINE_HEADERS), 200
    )

    assert created["version"] == 1
    assert read_back["version"] == 1
    assert activated["version"] == 2
    assert scheduled["version"] == 3
    assert noticed["version"] == 4
    assert noticed["status"] == "ACTIVE"
    assert noticed["price_change_state"] == "NOTICE_SENT"
    assert noticed["notice_sent_on"] == "2026-09-01"
    assert noticed["notice_sent_by_user_id"] == "officer-9"
    assert noticed["standard_price_cents"] == 1499


def test_confirming_a_cancellation_is_readable_everywhere_before_any_batch_runs():
    """Four hops in one request: lifecycle, access date and the doomed hold all move now.

    PRD: "Where §3 describes such a chain, every hop is part of the same request: there is no partial application and no deferred step."
    PRD: "Hop two moves the subscription `ACTIVE → CANCEL_SCHEDULED`, sets both `access_until` and `cancel_effective_on` to `paid_through_on` — the reader keeps what they paid for — and moves the print dimension from `SCHEDULED`, `HELD` or `INTERRUPTED` to `STOPPED_AT_CYCLE_END`."
    PRD: "Hop three follows from the print stop: every hold on the subscription whose `status` is `SCHEDULED` and whose `start_date` falls after `access_until` becomes `RELEASED`, because a hold can no longer be served once service has ended."

    Design: Corner/consistency_model/cancellation_confirm_effects_readable_without_a_billing_run
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Immediate")
    reader = create_registered_reader("immediate@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    hold = create_hold(
        subscription["id"], "PAUSE_BILLING", "2026-10-20", "2026-10-26", reader_headers
    )
    request = start_cancellation(subscription["id"], "PRICE", reader_headers)

    confirmed = validate_success(
        api_client.confirm_cancellation(request["id"], reader_headers), 200
    )

    assert confirmed["effective_on"] == "2026-10-01"
    assert read_cancellation_request(request["id"])["confirmed_on"] == "2026-09-01"
    after = read_subscription(subscription["id"])
    assert after["lifecycle_status"] == "CANCEL_SCHEDULED"
    assert after["access_until"] == "2026-10-01"
    assert after["cancel_effective_on"] == "2026-10-01"
    assert after["print_fulfillment_status"] == "NOT_APPLICABLE"
    assert read_hold(hold["id"])["status"] == "RELEASED"
    assert read_reader(reader["id"])["entitlement_source"] == "SUBSCRIPTION"


def test_a_scheduled_cancellation_ends_only_on_the_run_after_the_effective_date():
    """The clock reaching the date is not enough; the pass needs to be strictly past it.

    PRD: "When the clock date passes `cancel_effective_on` — strictly after it — the pass drives `CANCEL_SCHEDULED → CANCELLED`, moves the print dimension `STOPPED_AT_CYCLE_END → STOPPED`, moves the linked `CONFIRMED` cancellation request `CONFIRMED → COMPLETED` (reported in `cancellations_completed`), and recomputes the reader's `entitlement_source` to `NONE` unless an `ACTIVE` seat still entitles them."
    PRD: "Five passes exist and they always execute in the pinned order **HOLDS, then EXPIRY, then BILLING, then DUNNING, then ENGAGEMENT**; `scope` restricts which of them run, and `FULL` runs all five in that order."
    PRD: "A pass that is out of scope contributes an empty array rather than being absent."

    Design: Corner/consistency_model/scheduled_cancellation_completes_only_in_the_expiry_pass
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Eventual")
    reader = create_registered_reader("eventual@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    request = start_cancellation(subscription["id"], "OTHER", reader_headers)
    validate_success(api_client.confirm_cancellation(request["id"], reader_headers), 200)
    set_clock_date("2026-10-01")
    assert read_subscription(subscription["id"])["lifecycle_status"] == "CANCEL_SCHEDULED"

    same_day = run_billing("EXPIRY_ONLY")

    assert same_day["cancellations_completed"] == []
    assert read_subscription(subscription["id"])["lifecycle_status"] == "CANCEL_SCHEDULED"
    set_clock_date("2026-10-02")

    next_day = run_billing("EXPIRY_ONLY")

    assert next_day["cancellations_completed"] == [request["id"]]
    assert read_subscription(subscription["id"])["lifecycle_status"] == "CANCELLED"
    assert read_cancellation_request(request["id"])["status"] == "COMPLETED"
    assert read_reader(reader["id"])["entitlement_source"] == "NONE"
    assert len(list_invoices(subscription["id"])) == 1
