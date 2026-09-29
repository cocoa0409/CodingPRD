"""What the server mints for itself when a resource is created."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    REVENUE_MANAGER_HEADERS,
    api_client,
    assert_common_fields,
    assert_group_account,
    assert_offer_plan,
    assert_reader,
    assert_response_envelope,
    assert_subscription,
    create_active_institutional_plan,
    create_active_plan,
    create_registered_reader,
    fresh_plan_version,
    list_holds,
    read_group,
    read_reader,
    read_subscription,
    set_clock_date,
    setup_print_digital_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f


def test_new_offer_plan_is_born_draft_with_no_pipeline_and_no_subscribers():
    """The client sends a ladder; the server adds status, pipeline, count and version.

    PRD: "A newly authored plan is born in `status` `DRAFT`, with `active_subscription_count` at 0 and its `price_change_state` at `NONE`."
    PRD: "`version` (integer): an integer that starts at 1 and increments by one on every mutation of that resource, including mutations that only touch derived fields."

    Design: Corner/entities/offer_plan_created_with_declared_defaults
    """
    response = api_client.create_offer_plan(
        f.create_offer_plan_payload(name="Digital Basic"), REVENUE_MANAGER_HEADERS
    )

    plan = assert_response_envelope(response, "object")["data"]
    assert response.status_code == 201
    assert plan["status"] == "DRAFT"
    assert plan["price_change_state"] == "NONE"
    assert plan["active_subscription_count"] == 0
    assert plan["version"] == 1
    assert plan["name"] == "Digital Basic"
    assert plan["standard_price_cents"] == 1499
    assert_offer_plan(plan)
    assert_common_fields(plan)


def test_reader_created_from_an_empty_body_takes_every_declared_default():
    """No email, no card, no propensity seed: the reader still comes back fully derived.

    PRD: "`email` is optional in general but must be present, and unique among readers that have one, whenever `is_registered` is true; `is_registered` itself defaults to false."
    PRD: "On creation, `meter_period_started_on` is set to the clock date, `engagement_score` is 0.00, `churn_risk_band` is `SEVERE`, `entitlement_source` is `NONE`, `metered_article_ids` is empty, `metered_distinct_article_count` is 0, and `card_updater_status` is `NOT_APPLICABLE`."
    PRD: "It is `MISSING` whenever `card_last4` is null."

    Design: Corner/entities/reader_defaults_applied_when_optional_fields_omitted
    """
    set_clock_date("2026-09-01")

    reader = validate_success(
        api_client.create_reader(f.create_reader_payload(), OPS_AGENT_HEADERS), 201
    )

    assert reader["is_registered"] is False
    assert reader["propensity_band"] == "MEDIUM"
    assert float(reader["engagement_score"]) == 0.00
    assert reader["churn_risk_band"] == "SEVERE"
    assert reader["card_status"] == "MISSING"
    assert reader["card_updater_status"] == "NOT_APPLICABLE"
    assert reader["entitlement_source"] == "NONE"
    assert reader["metered_distinct_article_count"] == 0
    assert reader["meter_period_started_on"] == "2026-09-01"
    assert reader["intervention_count_in_period"] == 0
    assert_reader(reader)


def test_client_supplied_cycle_and_credit_figures_are_discarded_on_a_new_subscription():
    """Everything beyond the three inputs is derived, so the sent figures never land.

    PRD: "A `SubscriptionOpsAgent` opens a subscription by supplying the `reader_id` of the paying reader, the `offer_plan_id` of the governing plan, the mandatory `expected_offer_plan_version` guard, and — only for the institutional subscription that funds a group's seats — a `group_account_id`. Everything else is derived."
    PRD: "On creation the subscription's `lifecycle_status` is `PENDING_ACTIVATION`, its `dunning_status` is `CURRENT`, its `print_fulfillment_status` is `NOT_APPLICABLE` — print fulfilment does not begin until the first payment succeeds, even on a print bundle — its `cycle_index` is 1, and `cycle_start_on` is the clock date."

    Design: Corner/entities/subscription_create_computed_cycle_fields_input_ignored
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Ignore")
    reader = create_registered_reader("ignore@mail.test")

    payload = f.create_subscription_payload(
        reader["id"],
        plan["id"],
        fresh_plan_version(plan["id"]),
        cycle_index=7,
        next_cycle_price_cents=1,
        pending_credit_cents=9999,
        lifecycle_status="ACTIVE",
    )
    created = validate_success(
        api_client.create_subscription(payload, OPS_AGENT_HEADERS), 201
    )

    subscription = read_subscription(created["id"])
    assert subscription["cycle_index"] == 1
    assert subscription["next_cycle_price_cents"] == 1499
    assert subscription["pending_credit_cents"] == 0
    assert subscription["lifecycle_status"] == "PENDING_ACTIVATION"
    assert subscription["dunning_status"] == "CURRENT"
    assert subscription["print_fulfillment_status"] == "NOT_APPLICABLE"
    assert subscription["cycle_start_on"] == "2026-09-01"
    assert_subscription(subscription)


def test_client_supplied_identity_and_seat_counters_are_discarded_on_a_new_group_account():
    """A sent id, version, status and occupancy figure are all overwritten by the server.

    PRD: "The group is created with `status` `ACTIVE`, `seats_assigned_count` at 0 and `seats_available_count` equal to `seat_capacity`."
    PRD: "`id` (string): a server-minted UUID with no type prefix."

    Design: Corner/entities/group_account_system_fields_input_ignored
    """
    set_clock_date("2026-09-01")
    plan = create_active_institutional_plan(
        name="Institution Sys",
        intro_price_cents=5000,
        intro_cycles=0,
        standard_price_cents=5000,
        standard_from_cycle=1,
        cycle_days=30,
        per_seat_price_cents=400,
    )

    payload = f.create_group_account_payload(
        plan["id"],
        seat_capacity=3,
        name="Sys Library",
        admin_email="sys@univ.edu",
        allowed_email_domain="univ.edu",
        id="00000000-0000-0000-0000-000000000001",
        version=42,
        status="SUSPENDED",
        seats_assigned_count=7,
    )
    created = validate_success(
        api_client.create_group_account(payload, OPS_AGENT_HEADERS), 201
    )

    assert created["id"] != "00000000-0000-0000-0000-000000000001"
    group = read_group(created["id"])
    assert group["version"] == 1
    assert group["status"] == "ACTIVE"
    assert group["seats_assigned_count"] == 0
    assert group["seats_available_count"] == 3
    assert_group_account(group)
    assert_common_fields(group)


def test_subscription_create_without_an_offer_plan_id_fails_body_shape_validation():
    """The guard is present and the reader is real, so only the omission can fail.

    PRD: "**Request-body shape** on every write endpoint: all required fields present, enum-valued fields inside their declared value sets, integer fields non-negative, date fields in `YYYY-MM-DD` form, datetime fields RFC 3339 with a trailing `Z`, discount fractions between 0 and 1 inclusive, and the billing-run `scope` inside its enum — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/subscription_create_missing_required_offer_plan_id_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital ReqField")
    reader = create_registered_reader("reqfield@mail.test")

    response = api_client.create_subscription(
        {
            "reader_id": reader["id"],
            "expected_offer_plan_version": fresh_plan_version(plan["id"]),
        },
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    rows, meta = validate_paginated(api_client.list_subscriptions(OPS_AGENT_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_hold_type_outside_the_closed_enum_is_refused_before_any_hold_is_stored():
    """A fourth hold type does not exist, so nothing is written against the subscription.

    PRD: "A **hold** is an occupation of a subscription's service window, and its `hold_type` selects entirely different semantics. `PAUSE_BILLING` suspends billing and access. `VACATION_DELIVERY` is a reader-requested suspension of print delivery. `DELIVERY_INTERRUPTION` is a publisher-caused failure of print delivery."
    PRD: "**Request-body shape** on every write endpoint: all required fields present, enum-valued fields inside their declared value sets, integer fields non-negative, date fields in `YYYY-MM-DD` form, datetime fields RFC 3339 with a trailing `Z`, discount fractions between 0 and 1 inclusive, and the billing-run `scope` inside its enum — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/hold_type_outside_enum_rejected
    """
    scenario = setup_print_digital_subscription(
        reader_email="enum@mail.test", clock_date="2026-09-01", name="Print Enum"
    )

    response = api_client.create_hold(
        scenario["subscription"]["id"],
        {
            "hold_type": "SABBATICAL",
            "start_date": "2026-09-10",
            "end_date": "2026-09-14",
        },
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    assert list_holds(scenario["subscription"]["id"]) == []
    assert read_reader(scenario["reader"]["id"])["entitlement_source"] == "SUBSCRIPTION"
