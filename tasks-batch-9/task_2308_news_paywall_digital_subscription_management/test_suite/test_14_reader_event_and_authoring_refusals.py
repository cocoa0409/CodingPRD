"""Refusals that guard readers, editorial inventory, engagement signals and ladders."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    REVENUE_MANAGER_HEADERS,
    api_client,
    create_active_plan,
    create_article,
    create_reader,
    create_registered_reader,
    fresh_plan_version,
    invoice_for_cycle,
    log_event,
    make_reader_headers,
    open_subscription,
    read_cancellation_request,
    read_plan,
    read_reader,
    read_subscription,
    record_payment,
    set_clock_date,
    start_cancellation,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f


def test_an_anonymous_device_row_may_not_be_turned_into_a_paying_subscription():
    """Existence, version and plan state all pass; only registration is missing.

    PRD: "The reader must be a real subscriber first: a reader whose `is_registered` is false or whose `email` is null answers `ERR_READER_NOT_REGISTERED` (HTTP 422)."
    PRD: "The same request generates the cycle-1 invoice, computes `next_cycle_price_cents` through the forward-looking price variant, recomputes the plan's `active_subscription_count` — the count of subscriptions on that plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE`, `PAUSED` or `CANCEL_SCHEDULED` — and increments the plan's `version`."

    Design: Corner/validations/unregistered_reader_cannot_open_subscription_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Reg")
    anonymous = create_reader(is_registered=False)
    assert anonymous["is_registered"] is False

    response = api_client.create_subscription(
        f.create_subscription_payload(
            anonymous["id"], plan["id"], fresh_plan_version(plan["id"])
        ),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_READER_NOT_REGISTERED", 422)
    rows, meta = validate_paginated(api_client.list_subscriptions(OPS_AGENT_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []
    after = read_plan(plan["id"])
    assert after["active_subscription_count"] == 0
    assert after["version"] == 2


def test_an_embargoed_article_yields_no_verdict_and_writes_no_event():
    """The refusal is total: unlike a blocked verdict, nothing at all is recorded.

    PRD: "An access decision requested for an article whose `published_at` is later than the clock instant is refused with `ERR_ARTICLE_UNPUBLISHED` (HTTP 422): an embargoed article yields no verdict."
    PRD: "Every access decision appends exactly one reader event."

    Design: Corner/validations/embargoed_article_access_decision_rejected
    """
    set_clock_date("2026-09-01")
    reader = create_registered_reader("embargo@mail.test")
    article = create_article(
        headline="Embargoed Scoop",
        section="politics",
        content_type="NEWS",
        access_class="METERED",
        published_at="2026-09-05T00:00:00Z",
    )

    response = api_client.create_access_decision(
        f.access_decision_payload(reader["id"], article["id"]),
        make_reader_headers(reader["id"]),
    )

    validate_error(response, "ERR_ARTICLE_UNPUBLISHED", 422)
    rows, meta = validate_paginated(
        api_client.list_reader_events(OPS_AGENT_HEADERS, {"reader_id": reader["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    after = read_reader(reader["id"])
    assert after["metered_distinct_article_count"] == 0
    assert after["metered_article_ids"] == []


def test_a_reader_may_not_hand_write_a_granted_view_to_inflate_their_own_score():
    """The value is inside the enum, so only the system-only rule can stop it.

    PRD: "The full event-type vocabulary is `ARTICLE_VIEW_GRANTED`, `ARTICLE_VIEW_BLOCKED`, `NEWSLETTER_OPEN`, `APP_OPEN`, `COMMENT_POST`, `INTERVENTION_EDITORIAL`, `INTERVENTION_PRODUCT` and `PRICE_INCREASE_NOTICE`, but three of those are system-generated and cannot be posted directly: an attempt to log `ARTICLE_VIEW_GRANTED`, `ARTICLE_VIEW_BLOCKED` or `PRICE_INCREASE_NOTICE` answers `ERR_EVENT_TYPE_SYSTEM_ONLY` (HTTP 422)."
    PRD: "**Request-body shape** on every write endpoint: all required fields present, enum-valued fields inside their declared value sets, integer fields non-negative, date fields in `YYYY-MM-DD` form, datetime fields RFC 3339 with a trailing `Z`, discount fractions between 0 and 1 inclusive, and the billing-run `scope` inside its enum — `ERR_INVALID_REQUEST`."

    Design: Corner/validations/system_only_event_type_posted_directly_rejected
    """
    set_clock_date("2026-09-01")
    reader = create_registered_reader("sysonly@mail.test")

    response = api_client.create_reader_event(
        reader["id"],
        f.create_reader_event_payload("ARTICLE_VIEW_GRANTED"),
        make_reader_headers(reader["id"]),
    )

    error = validate_error(response, "ERR_EVENT_TYPE_SYSTEM_ONLY", 422)
    assert error["error_id"] != "ERR_INVALID_REQUEST"
    rows, meta = validate_paginated(
        api_client.list_reader_events(OPS_AGENT_HEADERS, {"reader_id": reader["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert float(read_reader(reader["id"])["engagement_score"]) == 0.00


def test_the_third_intervention_inside_one_meter_period_is_rationed_away():
    """The band half of the rule passes at SEVERE, so the count half must bite.

    PRD: "An `INTERVENTION_EDITORIAL` or `INTERVENTION_PRODUCT` event may only be logged for a reader whose `churn_risk_band` is `HIGH` or `SEVERE`, and only while `intervention_count_in_period` is less than two; a reader whose band is `LOW` or `MEDIUM`, or whose count has already reached two, answers `ERR_INTERVENTION_NOT_WARRANTED` (HTTP 422)."
    PRD: "`intervention_count_in_period` is the number of the reader's `INTERVENTION_EDITORIAL` and `INTERVENTION_PRODUCT` events whose `occurred_at` falls on or after `meter_period_started_on`, so the intervention budget refills whenever the meter period rolls over."

    Design: Corner/validations/third_intervention_in_period_rejected
    """
    set_clock_date("2026-09-01")
    reader = create_registered_reader("intervene@mail.test")
    log_event(reader["id"], "INTERVENTION_EDITORIAL", OPS_AGENT_HEADERS)
    log_event(reader["id"], "INTERVENTION_EDITORIAL", OPS_AGENT_HEADERS)
    assert read_reader(reader["id"])["intervention_count_in_period"] == 2

    response = api_client.create_reader_event(
        reader["id"],
        f.create_reader_event_payload("INTERVENTION_PRODUCT"),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_INTERVENTION_NOT_WARRANTED", 422)
    after = read_reader(reader["id"])
    assert after["intervention_count_in_period"] == 2
    assert after["churn_risk_band"] == "SEVERE"
    assert float(after["engagement_score"]) == 0.00


def test_a_pitch_above_the_forty_percent_ceiling_does_not_consume_the_single_offer():
    """The rejected offer leaves the flow exactly where it was, still pitchable.

    PRD: "Ranges are enforced with `ERR_SAVE_OFFER_DISCOUNT_CAP` (HTTP 422): `discount_pct` must not exceed 0.40 — the forty-percent ceiling that also caps the high-value uplift in §3.5 — `duration_cycles` must be between 1 and 12 inclusive for a `RETENTION_DISCOUNT` or `DOWNGRADE`, and `pause_days` must be between 7 and 90 inclusive for a `PAUSE`."
    PRD: "The request is created with `status` `INITIATED`, `save_offer_count` at 0 and `retained` false, and its `confirmed_on` and `effective_on` null."

    Design: Corner/validations/save_offer_above_discount_cap_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Cap")
    reader = create_registered_reader("cap@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    request = start_cancellation(
        subscription["id"], "PRICE", make_reader_headers(reader["id"])
    )

    response = api_client.create_save_offer(
        request["id"],
        f.create_save_offer_payload(
            "RETENTION_DISCOUNT", discount_pct=0.55, duration_cycles=3
        ),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_SAVE_OFFER_DISCOUNT_CAP", 422)
    after = read_cancellation_request(request["id"])
    assert after["status"] == "INITIATED"
    assert after["save_offer_count"] == 0
    rows, meta = validate_paginated(
        api_client.list_save_offers(request["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert float(read_subscription(subscription["id"])["retention_discount_pct"]) == 0


def test_a_step_rung_outside_the_open_window_is_refused_at_authoring_time():
    """Prices rise correctly, but a rung at cycle 5 sits beyond the standard boundary.

    PRD: "The ladder is checked for monotonicity both when the plan is authored and again when it is activated, and a ladder that fails answers `ERR_STEP_UP_SCHEDULE_INVALID` (HTTP 422)."
    PRD: "To pass, the `from_cycle` values must be strictly increasing across the array, every `from_cycle` must be strictly greater than `intro_cycles` and strictly less than `standard_from_cycle`, the `price_cents` values must be strictly increasing across the array, the first step's `price_cents` must be greater than or equal to `intro_price_cents`, and the last step's `price_cents` must be less than or equal to `standard_price_cents`."

    Design: Corner/validations/non_monotonic_step_up_schedule_rejected
    """
    set_clock_date("2026-09-01")

    response = api_client.create_offer_plan(
        f.create_offer_plan_payload(
            name="Bad Ladder",
            standard_from_cycle=4,
            step_up_schedule=f.step_up_schedule((2, 999), (5, 1299)),
        ),
        REVENUE_MANAGER_HEADERS,
    )

    validate_error(response, "ERR_STEP_UP_SCHEDULE_INVALID", 422)
    rows, meta = validate_paginated(api_client.list_offer_plans(REVENUE_MANAGER_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []
