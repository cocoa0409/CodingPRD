"""Filtered catalogues, the card endpoint, and what one batch call reports back."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    REVENUE_MANAGER_HEADERS,
    api_client,
    create_active_institutional_plan,
    create_active_plan,
    create_paywall_rule,
    create_reader,
    create_registered_reader,
    invoice_for_cycle,
    list_invoices,
    make_reader_headers,
    open_subscription,
    read_reader,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f


def test_the_rule_catalogue_filters_by_status_and_orders_by_specificity():
    """Three rules go in; the ACTIVE query returns two of them, most specific first.

    PRD: "Paywall-rule listings accept `status`, `content_type_match` and `propensity_band_match`."
    PRD: "Unless a specific listing states otherwise, list endpoints return their rows sorted by `created_at` ascending. Four listings override that default because their domain ordering is more useful: paywall-rule listings are ordered by `specificity_score` descending, then `priority` ascending, then `created_at` ascending; reader-event listings by `occurred_at` ascending then `created_at` ascending; a subscription's invoice listing by `cycle_index` ascending; a subscription's hold listing and the seat listing by `start_date` (respectively `starts_on`) ascending then `created_at` ascending; an invoice's payment-attempt listing by `attempt_no` ascending; and a cancellation request's save-offer listing by `presented_on` ascending then `created_at` ascending."
    PRD: "It is the sum of three contributions: one hundred if `content_type_match` is anything other than `ANY`, ten if `section_match` is anything other than `ANY`, and one if `propensity_band_match` is anything other than `ANY`."

    Design: Corner/endpoints/paywall_rules_created_then_listed_by_status_filter
    """
    set_clock_date("2026-09-01")

    generic = create_paywall_rule(
        name="Generic Meter",
        action="METER",
        priority=10,
        content_type_match="ANY",
        section_match="ANY",
        propensity_band_match="ANY",
        meter_allowance_override=6,
        status="ACTIVE",
    )
    specific = create_paywall_rule(
        name="Politics Opinion Wall",
        action="REGISTRATION_WALL",
        priority=20,
        content_type_match="OPINION",
        section_match="politics",
        propensity_band_match="LOW",
        status="ACTIVE",
    )
    retired = create_paywall_rule(
        name="Retired Rule",
        action="HARD_PAYWALL",
        priority=30,
        content_type_match="NEWS",
        section_match="ANY",
        propensity_band_match="ANY",
        status="INACTIVE",
    )

    rows, meta = validate_paginated(
        api_client.list_paywall_rules(
            REVENUE_MANAGER_HEADERS, {"status": "ACTIVE", "limit": 10, "offset": 0}
        )
    )
    assert generic["specificity_score"] == 0
    assert generic["meter_allowance_override"] == 6
    assert specific["specificity_score"] == 111
    assert retired["status"] == "INACTIVE"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [specific["id"], generic["id"]]


def test_replacing_an_expired_card_re_arms_the_recovery_pipeline():
    """A fresh 2028 expiry recomputes the status and hands the updater back its reset.

    PRD: "Either the `Reader` themselves or a `SubscriptionOpsAgent` may replace the stored card by supplying a fresh `card_last4`, `card_exp_month`, `card_exp_year` and optionally `card_updater_registered`; doing so recomputes `card_status` against the clock, resets `card_updater_status` to `NOT_APPLICABLE`, and increments the reader's `version`."
    PRD: "It is `EXPIRED` when the stored expiry — the pair of `card_exp_year` and `card_exp_month` — precedes the clock's year-and-month pair, comparing year first and month second."

    Design: Corner/endpoints/card_replacement_recomputes_status_and_resets_updater
    """
    set_clock_date("2026-09-01")
    reader = create_registered_reader(
        "card@mail.test",
        card_last4="1111",
        card_exp_month=7,
        card_exp_year=2026,
        card_updater_registered=False,
    )
    assert reader["card_status"] == "EXPIRED"
    assert reader["version"] == 1

    replaced = validate_success(
        api_client.replace_reader_card(
            reader["id"],
            f.replace_card_payload(
                card_last4="9876",
                card_exp_month=5,
                card_exp_year=2028,
                card_updater_registered=True,
            ),
            make_reader_headers(reader["id"]),
        ),
        200,
    )

    assert replaced["card_last4"] == "9876"
    assert replaced["card_exp_month"] == 5
    assert replaced["card_exp_year"] == 2028
    assert replaced["card_status"] == "CURRENT"
    assert replaced["card_updater_status"] == "NOT_APPLICABLE"
    assert replaced["card_updater_registered"] is True
    assert read_reader(reader["id"])["version"] == 2


def test_a_group_account_is_findable_through_the_plan_that_funds_it():
    """Two institutional plans, two groups, and the plan filter separates them cleanly.

    PRD: "Group-account listings accept `offer_plan_id` and `status`."
    PRD: "The group is created with `status` `ACTIVE`, `seats_assigned_count` at 0 and `seats_available_count` equal to `seat_capacity`."

    Design: Corner/endpoints/group_account_links_funding_plan_and_lists_by_plan_filter
    """
    set_clock_date("2026-09-01")
    plan_a = create_active_institutional_plan(
        name="Seats A",
        intro_price_cents=5000,
        intro_cycles=1,
        standard_price_cents=5000,
        standard_from_cycle=2,
        cycle_days=30,
        per_seat_price_cents=400,
    )
    plan_b = create_active_institutional_plan(
        name="Seats B",
        intro_price_cents=7000,
        intro_cycles=1,
        standard_price_cents=7000,
        standard_from_cycle=2,
        cycle_days=30,
        per_seat_price_cents=500,
    )
    group_b = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan_b["id"],
                seat_capacity=4,
                name="Library B",
                admin_email="admin@libb.test",
                allowed_email_domain="libb.test",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )

    group_a = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan_a["id"],
                seat_capacity=7,
                name="Library A",
                admin_email="admin@liba.test",
                allowed_email_domain="liba.test",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )

    assert group_a["status"] == "ACTIVE"
    assert group_a["seats_assigned_count"] == 0
    assert group_a["seats_available_count"] == 7
    assert group_a["offer_plan_id"] == plan_a["id"]
    assert group_a["version"] == 1
    rows, meta = validate_paginated(
        api_client.list_group_accounts(
            OPS_AGENT_HEADERS, {"offer_plan_id": plan_a["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [group_a["id"]]
    assert group_b["id"] not in [row["id"] for row in rows]


def test_one_full_run_bills_both_due_subscriptions_and_reports_them_as_arrays():
    """The pinned pass order leaves every other array empty on this epoch advance.

    PRD: "It is a record of what the epoch advance did, carrying `run_id`, the echoed `scope`, and ten arrays of identifiers: `holds_activated`, `holds_completed`, `subscriptions_paused`, `subscriptions_resumed`, `cancellations_completed`, `seats_expired`, `invoices_created`, `subscriptions_cancelled_nonpay`, `cards_updated` and `readers_rescored`."
    PRD: "The BILLING pass of a run picks up every subscription whose `paid_through_on` has fallen on or before the clock date and generates that subscription's next invoice through the waterfall above, sweeping any unapplied completed hold credits and decrementing `retention_discount_cycles_remaining` where a discount applied."
    PRD: "That pass walks every reader in `created_at` ascending order, rescores `engagement_score` against the current clock, re-derives `churn_risk_band`, resets any meter period that has aged past thirty days, and then re-bands propensity from the freshly written score: 30 or above becomes `HIGH`, from 10 up to but not including 30 becomes `MEDIUM`, and below 10 becomes `LOW`."

    Design: Corner/endpoints/full_billing_run_returns_bulk_arrays_for_two_subscriptions
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Bulk")
    first_reader = create_registered_reader("bulk1@mail.test")
    second_reader = create_registered_reader("bulk2@mail.test")
    first = open_subscription(first_reader["id"], plan["id"])
    record_payment(invoice_for_cycle(first["id"], 1), "SUCCEEDED", 499)
    second = open_subscription(second_reader["id"], plan["id"])
    record_payment(invoice_for_cycle(second["id"], 1), "SUCCEEDED", 499)
    set_clock_date("2026-10-01")

    report = run_billing("FULL")

    assert report["scope"] == "FULL"
    assert len(report["invoices_created"]) == 2
    created = set(report["invoices_created"])
    assert invoice_for_cycle(first["id"], 2)["id"] in created
    assert invoice_for_cycle(second["id"], 2)["id"] in created
    assert sorted(report["readers_rescored"]) == sorted(
        [first_reader["id"], second_reader["id"]]
    )
    for empty in (
        "holds_activated",
        "holds_completed",
        "subscriptions_paused",
        "subscriptions_resumed",
        "cancellations_completed",
        "seats_expired",
        "subscriptions_cancelled_nonpay",
        "cards_updated",
    ):
        assert report[empty] == []
    assert read_subscription(first["id"])["cycle_index"] == 2
    assert read_subscription(second["id"])["cycle_index"] == 2
    assert len(list_invoices(first["id"])) == 2
    assert float(read_reader(first_reader["id"])["engagement_score"]) == 0.00
    assert read_reader(first_reader["id"])["propensity_band"] == "LOW"
    assert read_reader(second_reader["id"])["propensity_band"] == "LOW"


def test_the_card_updater_sweep_passes_over_a_reader_with_nothing_failing():
    """Enrolment alone is not enough: the sweep needs a RETRYING subscription too.

    PRD: "The DUNNING pass of a run handles cards for subscriptions whose `dunning_status` is `RETRYING` and whose reader's `card_updater_status` is `PENDING`. When the reader's `card_updater_registered` is true, the sweep succeeds: `card_exp_year` is advanced by three years, `card_status` becomes `CURRENT` and `card_updater_status` becomes `UPDATED` — which is precisely what raises `max_payment_attempts` to five."
    PRD: "The ceiling is `max_payment_attempts`, which is four normally and five when the reader's `card_updater_status` is `UPDATED` — successfully refreshing a card through the network buys exactly one bonus attempt."

    Design: Corner/endpoints/card_updater_sweep_only_touches_retrying_subscriptions
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Updater")
    failing_reader = create_registered_reader(
        "updater@mail.test",
        card_last4="4444",
        card_exp_month=9,
        card_exp_year=2026,
        card_updater_registered=True,
    )
    control_reader = create_reader(
        f.create_registered_reader_payload(
            email="control@mail.test",
            card_last4="5555",
            card_exp_month=9,
            card_exp_year=2026,
            card_updater_registered=True,
        )
    )
    subscription = open_subscription(failing_reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    second_invoice = invoice_for_cycle(subscription["id"], 2)
    record_payment(second_invoice, "SOFT_DECLINE", 1499, "expired_card")
    assert read_reader(failing_reader["id"])["card_updater_status"] == "PENDING"

    report = run_billing("DUNNING_ONLY")

    assert report["cards_updated"] == [failing_reader["id"]]
    swept = read_reader(failing_reader["id"])
    assert swept["card_exp_year"] == 2029
    assert swept["card_status"] == "CURRENT"
    assert swept["card_updater_status"] == "UPDATED"
    untouched = read_reader(control_reader["id"])
    assert untouched["card_exp_year"] == 2026
    assert untouched["card_updater_status"] == "NOT_APPLICABLE"
    assert untouched["card_status"] == "EXPIRED"
    after = read_subscription(subscription["id"])
    assert after["dunning_status"] == "RETRYING"
    assert after["max_payment_attempts"] == 5
