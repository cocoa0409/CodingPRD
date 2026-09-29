"""Ladder rungs, seat-line input sets, the retry ladder and the zero-total invoice."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_institutional_plan,
    create_active_plan,
    create_active_print_plan,
    create_article,
    create_hold,
    create_paywall_rule,
    create_registered_reader,
    decide_access,
    fresh_group_version,
    invoice_for_cycle,
    list_invoices,
    log_event,
    make_group_admin_headers,
    make_reader_headers,
    open_subscription,
    read_hold,
    read_invoice,
    read_reader,
    read_seat,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    validate_success,
)
from test_helpers import factories as f


def test_cycle_two_bills_the_step_up_rung_rather_than_the_standard_price():
    """The ladder is walked in order, so cycle 2 costs 999 and cycle 3 is quoted at 1299.

    PRD: "Otherwise, among the `step_up_schedule` entries whose `from_cycle` is less than or equal to the cycle index, the entry with the greatest `from_cycle` supplies the answer through its `price_cents`, labelled `STEP_UP`."
    PRD: "The **forward-looking variant** is written to `next_cycle_price_cents` and answers "what will this reader be charged next time if nothing changes"."

    Design: Corner/calculations/cycle_two_step_up_rung_billed_from_schedule
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(
        name="Digital Ladder",
        standard_from_cycle=4,
        step_up_schedule=f.step_up_schedule((2, 999), (3, 1299)),
    )
    reader = create_registered_reader("ladder@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    first = invoice_for_cycle(subscription["id"], 1)
    record_payment(first, "SUCCEEDED", 499)
    set_clock_date("2026-10-01")

    run_billing("BILLING_ONLY")

    assert read_invoice(first["id"])["base_line_cents"] == 499
    assert read_invoice(first["id"])["price_source"] == "INTRO"
    second = invoice_for_cycle(subscription["id"], 2)
    assert second["base_line_cents"] == 999
    assert second["price_source"] == "STEP_UP"
    assert second["total_cents"] == 999
    assert second["status"] == "OPEN"
    after = read_subscription(subscription["id"])
    assert after["cycle_index"] == 2
    assert after["next_cycle_price_cents"] == 1299


def test_an_unclaimed_invitation_is_never_billed_as_a_seat():
    """Only ACTIVE and RECLAIMED seats reach the seat line, so the cycle costs 5000 flat.

    PRD: "The seats that participate are those on the subscription's group account whose `status` is `ACTIVE` or `RECLAIMED`, whose `starts_on` is strictly before the cycle end, and whose `ends_on` is either null or strictly after the cycle start; `INVITED` and `EXPIRED` seats are never billed."
    PRD: "the seat is created with `status` `INVITED`, its `group_account_id` set from the path, `invited_on` at the clock date, `invite_expires_on` at `invited_on` advanced by fourteen days (two weeks to claim), and `claimed_on` null."

    Design: Corner/calculations/seat_line_excludes_invited_seats
    """
    set_clock_date("2026-09-01")
    plan = create_active_institutional_plan(
        name="Campus Seats",
        intro_price_cents=5000,
        intro_cycles=1,
        standard_price_cents=5000,
        standard_from_cycle=2,
        cycle_days=30,
        per_seat_price_cents=400,
    )
    bursar = create_registered_reader("bursar@campus.test")
    student = create_registered_reader("student1@campus.test")
    group = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan["id"],
                seat_capacity=3,
                name="Campus Library",
                admin_email="bursar@campus.test",
                allowed_email_domain="campus.test",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )
    admin_headers = make_group_admin_headers(group["id"])
    subscription = open_subscription(bursar["id"], plan["id"], group["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 5000)
    seat = validate_success(
        api_client.create_seat(
            group["id"],
            f.create_seat_payload(
                student["id"],
                "2026-09-05",
                fresh_group_version(group["id"], admin_headers),
            ),
            admin_headers,
        ),
        201,
    )
    set_clock_date("2026-10-01")

    run_billing("BILLING_ONLY")

    second = invoice_for_cycle(subscription["id"], 2)
    assert second["base_line_cents"] == 5000
    assert second["seat_line_cents"] == 0
    assert second["total_cents"] == 5000
    unclaimed = read_seat(seat["id"])
    assert unclaimed["status"] == "INVITED"
    assert unclaimed["invite_expires_on"] == "2026-09-15"
    assert unclaimed["claimed_on"] is None


def test_retry_dates_are_measured_from_the_first_failure_not_from_the_last_attempt():
    """Three soft declines from 2026-10-01 land on 10-04, 10-06 and 10-08.

    PRD: "`next_retry_on` is then computed as `dunning_first_failed_on` advanced by an offset drawn from the ladder of three, five and seven days: the first attempt schedules three days out, the second five days out, and the third and every later one seven days out."
    PRD: "Offsets are **cumulative from the first failure, never measured from the previous attempt** — failures beginning on day 0 schedule retries on day 3, day 5 and day 7, not day 3, day 8 and day 15."
    PRD: "The same failure arms the card-updater pipeline: the reader's `card_updater_status` moves from `NOT_APPLICABLE` to `PENDING` when `card_updater_registered` is true and `card_status` is `EXPIRED`, and to `UNAVAILABLE` otherwise."

    Design: Corner/calculations/dunning_offsets_measured_from_first_failure
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Dunning")
    reader = create_registered_reader(
        "dunning@mail.test",
        card_last4="4242",
        card_exp_month=11,
        card_exp_year=2027,
        card_updater_registered=False,
    )
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    second = invoice_for_cycle(subscription["id"], 2)

    ordinals = []
    finality = []
    retry_dates = []
    for clock_date in ("2026-10-01", "2026-10-04", "2026-10-06"):
        set_clock_date(clock_date)
        attempt = record_payment(second, "SOFT_DECLINE", 1499, "insufficient_funds")
        ordinals.append(attempt["attempt_no"])
        finality.append(attempt["is_final"])
        retry_dates.append(read_subscription(subscription["id"])["next_retry_on"])

    assert ordinals == [1, 2, 3]
    assert finality == [False, False, False]
    assert retry_dates == ["2026-10-04", "2026-10-06", "2026-10-08"]
    after = read_subscription(subscription["id"])
    assert after["dunning_first_failed_on"] == "2026-10-01"
    assert after["dunning_status"] == "RETRYING"
    assert after["lifecycle_status"] == "ACTIVE"
    assert read_invoice(second["id"])["status"] == "PAST_DUE"
    borrower = read_reader(reader["id"])
    assert borrower["card_updater_status"] == "UNAVAILABLE"
    assert borrower["churn_risk_band"] == "SEVERE"


def test_an_invoice_whose_credit_cancels_the_cycle_is_born_void():
    """450 of vacation credit against a 450 cycle floors the total and skips payment.

    PRD: "If `total_cents` came out as zero the invoice is created directly in `status` `VOID`; otherwise it is created `OPEN`."
    PRD: "A `VOID` invoice is a real transition, `OPEN → VOID`, taken at generation time when the assembled `total_cents` is zero. It is the one path by which service advances without any money changing hands: `paid_through_on` is advanced by the plan's `cycle_days` at creation, with no payment attempt ever recorded, and the credits swept onto it are still marked applied."

    Design: Corner/calculations/invoice_voids_when_credits_cover_the_cycle
    """
    set_clock_date("2026-09-01")
    plan = create_active_print_plan(
        name="Print Credit Wash",
        intro_price_cents=999,
        intro_cycles=1,
        standard_price_cents=450,
        standard_from_cycle=2,
        cycle_days=30,
        print_component_cents=450,
        print_deliveries_per_cycle=2,
        print_delivery_days=["SUN"],
    )
    reader = create_registered_reader("creditwash@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 999)
    hold = create_hold(
        subscription["id"],
        "VACATION_DELIVERY",
        "2026-09-06",
        "2026-09-13",
        make_reader_headers(reader["id"]),
    )
    assert hold["delivery_days_credited"] == 2
    assert hold["credit_cents"] == 450
    set_clock_date("2026-09-06")
    run_billing("HOLDS_ONLY")
    set_clock_date("2026-09-14")
    run_billing("HOLDS_ONLY")
    set_clock_date("2026-10-01")

    run_billing("BILLING_ONLY")

    assert len(list_invoices(subscription["id"])) == 2
    second = invoice_for_cycle(subscription["id"], 2)
    assert second["base_line_cents"] == 450
    assert second["price_source"] == "STANDARD"
    assert second["discount_line_cents"] == 0
    assert second["credit_line_cents"] == 450
    assert second["total_cents"] == 0
    assert second["status"] == "VOID"
    swept = read_hold(hold["id"])
    assert swept["credit_applied"] is True
    assert swept["credit_applied_cycle_index"] == 2
    after = read_subscription(subscription["id"])
    assert after["pending_credit_cents"] == 0
    assert after["lifetime_credit_cents"] == 450


def test_a_blocked_premium_read_leaves_both_the_score_and_the_meter_untouched():
    """The paywall verdict is logged at weight zero, so 2.00 stays 2.00.

    PRD: "Granted events recompute the reader's `engagement_score` and re-derive their `churn_risk_band`; blocked events carry a `weight` of 0 and leave the score exactly where it was."
    PRD: "Otherwise, an article whose `access_class` is `PREMIUM` yields `BLOCKED_PAYWALL`."
    PRD: "`meter_index` and `effective_allowance` are both null when the meter was never consulted, and `applied_rule_id` is null when the pool was empty or an article-level override decided the outcome."

    Design: Corner/calculations/blocked_verdict_carries_weight_zero_and_leaves_score_unchanged
    """
    set_clock_date("2026-09-01")
    reader = create_registered_reader("blocked@mail.test", propensity_band="MEDIUM")
    article = create_article(
        headline="Premium Investigation",
        section="politics",
        content_type="INVESTIGATION",
        access_class="PREMIUM",
    )
    log_event(reader["id"], "NEWSLETTER_OPEN", make_reader_headers(reader["id"]))

    event = decide_access(reader["id"], article["id"], make_reader_headers(reader["id"]))

    assert event["decision"] == "BLOCKED_PAYWALL"
    assert event["event_type"] == "ARTICLE_VIEW_BLOCKED"
    assert event["weight"] == 0
    assert event["meter_index"] is None
    after = read_reader(reader["id"])
    assert float(after["engagement_score"]) == 2.00
    assert after["churn_risk_band"] == "SEVERE"
    assert after["metered_distinct_article_count"] == 0
    assert after["metered_article_ids"] == []


def test_the_more_specific_rule_wins_even_though_its_priority_number_is_worse():
    """Specificity 100 at priority 99 beats specificity 0 at priority 1.

    PRD: "Candidates are ranked by `specificity_score` descending, then by `priority` ascending, then by `created_at` ascending — and never by `id`."
    PRD: "It is the sum of three contributions: one hundred if `content_type_match` is anything other than `ANY`, ten if `section_match` is anything other than `ANY`, and one if `propensity_band_match` is anything other than `ANY`."

    Design: Corner/calculations/rule_selection_prefers_specificity_over_operator_priority
    """
    set_clock_date("2026-09-01")
    generic = create_paywall_rule(
        name="Generic Free",
        action="ALLOW_FREE",
        priority=1,
        content_type_match="ANY",
        section_match="ANY",
        propensity_band_match="ANY",
        status="ACTIVE",
    )
    specific = create_paywall_rule(
        name="Investigations Hard",
        action="HARD_PAYWALL",
        priority=99,
        content_type_match="INVESTIGATION",
        section_match="ANY",
        propensity_band_match="ANY",
        status="ACTIVE",
    )
    article = create_article(
        headline="Follow The Money",
        section="politics",
        content_type="INVESTIGATION",
        access_class="METERED",
    )
    reader = create_registered_reader("selector@mail.test", propensity_band="MEDIUM")

    event = decide_access(reader["id"], article["id"], make_reader_headers(reader["id"]))

    assert generic["specificity_score"] == 0
    assert specific["specificity_score"] == 100
    assert event["decision"] == "BLOCKED_PAYWALL"
    assert event["applied_rule_id"] == specific["id"]
    assert read_reader(reader["id"])["metered_distinct_article_count"] == 0
