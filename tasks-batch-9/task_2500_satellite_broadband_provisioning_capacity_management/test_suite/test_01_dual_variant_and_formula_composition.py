"""Dual-variant readings of one stored fact, and composed multi-input formulas.

Four behaviours are exercised here, each one a place where the PRD sanctions two
different answers computed from the same stored data, or pins the evaluation
order of a formula whose inputs feed each other:

* the outage-credit provisional amount (one rounding over the whole event)
  against the final amount (round per UTC day, then sum);
* the advertised availability projection against the expiry-aware admission
  reading a write path computes;
* the cycle charge, whose discount band is keyed on a gross total that already
  contains the overage fee;
* a beam's weighted sold megabits, where the fair-use override outranks the
  plan's tier weight and the resulting ratio is banded against the beam's own
  policy limit.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    add_active_subscription,
    assert_beam_congestion_band,
    create_order,
    create_service_order_payload,
    create_subscriber,
    credit_decision_payload,
    get_beam_version,
    ingest_usage,
    iso_shift,
    list_credits_for_subscription,
    open_outage_event,
    resolve_outage_event,
    set_clock,
    setup_active_subscription,
    setup_topology,
    validate_error,
    validate_success,
    write_capacity_policy,
)

# The impairment window used by the divergence tests: 300 whole minutes split
# 150/150 across the UTC midnight between 10 and 11 August.
STRADDLING_START = "2026-08-10T21:30:00Z"
STRADDLING_END = "2026-08-11T02:30:00Z"

# The same 300-minute duration wholly inside one UTC calendar day.
SAME_DAY_START = "2026-08-10T10:00:00Z"
SAME_DAY_END = "2026-08-10T15:00:00Z"


def _drafted_credit_for_span(started_at: str, ended_at: str) -> dict:
    """One ACTIVE, AUTHORIZED_FIXED subscription impaired by a resolved event.

    Returns the environment extended with "event" and "credit". The subscription
    is activated while the clock still sits at 2026-08-01T00:00:00Z, so its
    `activated_at` is at or before any `started_at` these tests use.
    """
    env = setup_active_subscription()
    set_clock(iso_shift(ended_at, minutes=30))
    event = open_outage_event(
        env["beam"]["id"],
        cause="EQUIPMENT_FAILURE",
        severity="FULL_OUTAGE",
        started_at=started_at,
    )
    env["event"] = resolve_outage_event(event["id"], ended_at)
    credits = list_credits_for_subscription(env["subscription"]["id"])
    assert len(credits) == 1, (
        f"resolution should draft exactly one credit for the impaired subscription, "
        f"got {len(credits)}"
    )
    env["credit"] = credits[0]
    return env


class TestOutageCreditProvisionalVersusFinal:
    """The two sanctioned readings of one stored impairment window."""

    def test_provisional_amount_is_one_rounding_over_the_whole_event(
        self, api, netops_headers, agent_headers
    ):
        """A 300-minute FULL_OUTAGE / EQUIPMENT_FAILURE on a 9,900-cent plan drafts 69 cents.

        PRD §3.8: "Resolution moves the event `OPEN → RESOLVED` and computes `outage_minutes` as the number of whole minutes between `started_at` and `ended_at`, discarding any partial minute."
        PRD §3.8: "It then computes `credit_eligible`, which is true only when the `cause` is anything other than `PLANNED_MAINTENANCE` **and** `outage_minutes` is at least 30 — a shorter blip is beneath the service-level floor."
        PRD §3.8: "The **provisional** amount, written at resolution, treats the whole impairment as one span."
        PRD §3.8: "Take the plan's `monthly_fee_cents`, multiply it by the event's `outage_minutes` divided by a nominal billing month of 43,200 minutes — thirty days of minutes — then multiply by the multiplier."
        PRD §3.8: "Round that product half up to whole cents, and take the smaller of it and the cap. That value is `provisional_credit_cents`."
        PRD §3.8: "Each drafted credit's `provisional_credit_cents` is computed by the provisional rule below, and each affected subscriber's `pending_credit_cents` is increased by that amount."
        PRD §3.8: "The event's `generated_credit_count` records how many credits were created."

        Design: Difficulty/dual_variant_calc/outage_credit_provisional_event_level_vs_final_daily_prorated_diverge
        """
        env = _drafted_credit_for_span(STRADDLING_START, STRADDLING_END)

        event = validate_success(api.get_outage_event(env["event"]["id"], netops_headers))
        assert event["outage_minutes"] == 300, (
            f"21:30 to 02:30 is 300 whole minutes, got {event['outage_minutes']}"
        )
        assert event["credit_eligible"] is True, (
            "EQUIPMENT_FAILURE lasting 300 minutes is above the 30-minute SLA floor"
        )
        assert event["generated_credit_count"] == 1, (
            f"exactly one affected subscription should be credited, "
            f"got generated_credit_count {event['generated_credit_count']}"
        )

        credit = validate_success(api.get_outage_credit(env["credit"]["id"], agent_headers))
        assert credit["provisional_credit_cents"] == 69, (
            "9900 * 300/43200 * 1.0 = 68.75 rounds half up to 69 cents, "
            f"got {credit['provisional_credit_cents']}"
        )
        assert credit["credit_state"] == "DRAFT", (
            f"a resolution-drafted credit lands in DRAFT, got {credit['credit_state']}"
        )

        subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert subscriber["pending_credit_cents"] == 69, (
            "the drafted provisional estimate is the whole pending credit ledger, "
            f"got {subscriber['pending_credit_cents']}"
        )
        assert subscriber["credit_balance_cents"] == 0, (
            "nothing reaches the balance before approval, "
            f"got {subscriber['credit_balance_cents']}"
        )

    def test_final_amount_rounds_per_utc_day_then_sums_and_lands_one_cent_lower(
        self, api, agent_headers, compliance_headers
    ):
        """Approval prorates the straddling span per UTC day, giving 68 against the provisional 69.

        PRD §3.8: "Split the half-open impairment span — from `started_at` inclusive to `ended_at` exclusive — into UTC calendar days, each day itself treated as half-open."
        PRD §3.8: "Then, walking the overlapping days in chronological order, compute for each day the number of whole minutes that day's overlap contributes, discarding any partial minute, and compute that day's amount as the plan's `monthly_fee_cents` multiplied by those day minutes divided by 43,200, multiplied by the multiplier, **rounded half up to whole cents for that day**."
        PRD §3.8: "Sum the per-day whole-cent amounts, and take the smaller of that sum and the cap. That value is `final_credit_cents`."
        PRD §3.8: "The evaluation order is normative: rounding each day first and then summing is the rule, and summing the minutes across days and rounding once is explicitly **not** the rule — the two produce different answers, and a span that straddles midnight is exactly where they diverge."
        PRD §3.8: "An approval moves the credit `SUBMITTED → APPROVED`, computes `final_credit_cents` by the final per-day rule, and increases the subscriber's `credit_balance_cents` by that final amount."
        PRD §3.8: "Both branches stamp `decided_by_user_id` with the deciding operator's `X-User-ID` and store the supplied reason in `decision_reason`, and both branches decrease the subscriber's `pending_credit_cents` by the credit's `provisional_credit_cents` — the estimate always leaves the pending ledger."

        Design: Difficulty/dual_variant_calc/outage_credit_provisional_event_level_vs_final_daily_prorated_diverge
        """
        env = _drafted_credit_for_span(STRADDLING_START, STRADDLING_END)
        credit_id = env["credit"]["id"]

        validate_success(api.submit_outage_credit(credit_id, agent_headers))
        decided = validate_success(
            api.decide_outage_credit(
                credit_id,
                credit_decision_payload(decision="APPROVE", decision_reason="SLA breach confirmed"),
                compliance_headers,
            )
        )

        assert decided["credit_state"] == "APPROVED", (
            f"an approved credit lands in APPROVED, got {decided['credit_state']}"
        )
        assert decided["provisional_credit_cents"] == 69, (
            "the provisional estimate is untouched by approval, "
            f"got {decided['provisional_credit_cents']}"
        )
        assert decided["final_credit_cents"] == 68, (
            "150 minutes on 10 Aug rounds to 34 cents and 150 minutes on 11 Aug rounds to 34 "
            f"cents, summing to 68, got {decided['final_credit_cents']}"
        )
        assert decided["final_credit_cents"] != decided["provisional_credit_cents"], (
            "the per-day reading must diverge from the whole-span reading across midnight"
        )

        subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert subscriber["credit_balance_cents"] == 68, (
            "the balance takes the final per-day amount, not the provisional one, "
            f"got {subscriber['credit_balance_cents']}"
        )
        assert subscriber["pending_credit_cents"] == 0, (
            "the provisional estimate always leaves the pending ledger on decision, "
            f"got {subscriber['pending_credit_cents']}"
        )

    def test_span_inside_one_utc_day_makes_the_two_readings_agree(
        self, api, agent_headers, compliance_headers
    ):
        """The same 300 minutes wholly inside 10 August yields 69 provisionally and 69 finally.

        PRD §3.8: "Take the plan's `monthly_fee_cents`, multiply it by the event's `outage_minutes` divided by a nominal billing month of 43,200 minutes — thirty days of minutes — then multiply by the multiplier."
        PRD §3.8: "Then, walking the overlapping days in chronological order, compute for each day the number of whole minutes that day's overlap contributes, discarding any partial minute, and compute that day's amount as the plan's `monthly_fee_cents` multiplied by those day minutes divided by 43,200, multiplied by the multiplier, **rounded half up to whole cents for that day**."
        PRD §3.8: "The evaluation order is normative: rounding each day first and then summing is the rule, and summing the minutes across days and rounding once is explicitly **not** the rule — the two produce different answers, and a span that straddles midnight is exactly where they diverge."

        Design: Difficulty/dual_variant_calc/outage_credit_provisional_event_level_vs_final_daily_prorated_diverge
        """
        env = _drafted_credit_for_span(SAME_DAY_START, SAME_DAY_END)
        credit_id = env["credit"]["id"]

        drafted = validate_success(api.get_outage_credit(credit_id, agent_headers))
        assert drafted["provisional_credit_cents"] == 69, (
            "9900 * 300/43200 = 68.75 rounds half up to 69 cents, "
            f"got {drafted['provisional_credit_cents']}"
        )

        validate_success(api.submit_outage_credit(credit_id, agent_headers))
        decided = validate_success(
            api.decide_outage_credit(
                credit_id,
                credit_decision_payload(decision="APPROVE", decision_reason="SLA breach confirmed"),
                compliance_headers,
            )
        )
        assert decided["final_credit_cents"] == 69, (
            "one UTC day contributes all 300 minutes, so the single per-day rounding also gives "
            f"69, got {decided['final_credit_cents']}"
        )
        assert decided["final_credit_cents"] == decided["provisional_credit_cents"], (
            "with no midnight in the span the two readings must agree"
        )


class TestCellAvailabilityReadVersusAdmissionPath:
    """The advertised projection is strict about lapsed holds; the write path is not."""

    def test_availability_read_counts_a_lapsed_hold_and_expires_nothing(self, api, agent_headers):
        """One RESERVED order whose 72-hour hold has lapsed still reads as WAITLIST_ONLY at 0 free slots.

        PRD §3.3: "The **advertised** answer is what an availability determination returns, and it is a pure projection: it never mutates a record and never expires a reservation."
        PRD §3.3: "The free slot figure is the cell's `max_active_terminals` less the number of subscriptions occupying slots less the number of orders in `RESERVED`, floored at 0 so it is never negative."
        PRD §3.3: "Crucially, the advertised reading counts **every** order in `RESERVED`, including reservations whose `reservation_expires_at` has already passed but which no sweep has yet moved to `EXPIRED`."
        PRD §3.3: "Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."
        PRD §3.3: "It reports the cell's identity as `service_cell_id`, the cell's `availability_state`, the free slot figure as `advertised_free_slot_count`, the raw counters `committed_terminal_count`, `reserved_slot_count` and `waitlist_depth`, the constant `waitlist_cap` of 3 orders per cell, and the governing beam's congestion band as `beam_capacity_state` alongside its `beam_state`."
        PRD §2.4: "Moving the clock is inert with respect to business state: no entity is mutated, no reservation expires, no waitlist promotion runs, no licence expires, and no billing cycle closes as a side effect of the move."

        Design: Difficulty/dual_variant_calc/cell_availability_read_reports_waitlist_only_while_admission_path_reserves
        """
        env = setup_topology(max_active_terminals=1)
        subscriber_a = create_subscriber(index=1)
        order_a = create_order(subscriber_a["id"], env["cell"]["id"], env["plan"]["id"])
        assert order_a["order_state"] == "RESERVED", (
            f"the only order on an empty cell must reserve, got {order_a['order_state']}"
        )
        assert order_a["reservation_expires_at"] == "2026-08-04T00:00:00.000Z", (
            "the hold runs 72 hours from the logical clock, "
            f"got {order_a['reservation_expires_at']}"
        )

        cell_before = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        set_clock("2026-08-05T00:00:00Z")

        projection = validate_success(
            api.get_cell_availability(env["cell"]["id"], agent_headers)
        )
        assert projection["service_cell_id"] == env["cell"]["id"]
        assert projection["availability_state"] == "WAITLIST_ONLY", (
            "no free slot and a waitlist depth below 3 advertises WAITLIST_ONLY, "
            f"got {projection['availability_state']}"
        )
        assert projection["advertised_free_slot_count"] == 0, (
            "1 slot less 0 commitments less 1 lapsed-but-still-RESERVED hold is 0, "
            f"got {projection['advertised_free_slot_count']}"
        )
        assert projection["reserved_slot_count"] == 1, (
            f"the lapsed hold is still counted, got {projection['reserved_slot_count']}"
        )
        assert projection["committed_terminal_count"] == 0
        assert projection["waitlist_depth"] == 0
        assert projection["waitlist_cap"] == 3, (
            f"the waitlist cap is the constant 3, got {projection['waitlist_cap']}"
        )
        assert projection["beam_capacity_state"] == "NORMAL", (
            "a beam with nothing sold sits at ratio 0, which bands as NORMAL, "
            f"got {projection['beam_capacity_state']}"
        )
        assert projection["beam_state"] == "ACTIVE"

        order_after = validate_success(api.get_service_order(order_a["id"], agent_headers))
        assert order_after["order_state"] == "RESERVED", (
            "neither the clock move nor the availability read may expire the hold, "
            f"got {order_after['order_state']}"
        )
        cell_after = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        assert cell_after["version"] == cell_before["version"], (
            "a pure projection mutates no record, so the cell version must not move: "
            f"{cell_before['version']} -> {cell_after['version']}"
        )
        assert cell_after["reserved_slot_count"] == 1

    def test_order_filing_lazily_expires_the_lapsed_hold_and_reserves_the_new_order(
        self, api, agent_headers
    ):
        """The same stored data admits the next customer: filing sweeps the lapsed hold first.

        PRD §3.3: "Before an order is filed on a cell, one further thing happens that no other write path does."
        PRD §3.3: "Filing performs a **lazy expiry** sweep first: every order on that cell whose `order_state` is `RESERVED` and whose `reservation_expires_at` is at or before the logical clock's current instant is moved to `order_state` `EXPIRED`, processed in `created_at` ascending order."
        PRD §3.3: "An expired order keeps its `reservation_expires_at` value for audit; the cell's `reserved_slot_count` drops by one per expiry and `availability_state` is recomputed."
        PRD §3.3: "The consequence is intentional and must be preserved: for identical stored data an availability read can report `WAITLIST_ONLY` while the write path admits the customer anyway."
        PRD §3.3: "When the admission figure after lazy expiry is at least 1 and the governing beam's `beam_state` is `ACTIVE`, the order moves `PENDING_DETERMINATION → RESERVED`."
        PRD §3.3: "Its `reservation_expires_at` is set to the logical clock's current instant plus three days — the reservation hold is 72 hours, long enough for hardware to ship."
        PRD §3.3: "No waitlist promotion runs on this branch and the subscriber's `account_state` does not move."

        Design: Difficulty/dual_variant_calc/cell_availability_read_reports_waitlist_only_while_admission_path_reserves
        """
        env = setup_topology(max_active_terminals=1)
        subscriber_a = create_subscriber(index=1)
        order_a = create_order(subscriber_a["id"], env["cell"]["id"], env["plan"]["id"])
        subscriber_b = create_subscriber(index=2)
        set_clock("2026-08-05T00:00:00Z")

        order_b = validate_success(
            api.create_service_order(
                create_service_order_payload(
                    subscriber_id=subscriber_b["id"],
                    service_cell_id=env["cell"]["id"],
                    requested_plan_id=env["plan"]["id"],
                ),
                agent_headers,
            ),
            expected_status=201,
        )
        assert order_b["order_state"] == "RESERVED", (
            "the slot released by lazy expiry admits the new order, "
            f"got {order_b['order_state']}"
        )
        assert order_b["reservation_expires_at"] == "2026-08-08T00:00:00.000Z", (
            "the new hold runs 72 hours from the current logical clock, "
            f"got {order_b['reservation_expires_at']}"
        )

        swept = validate_success(api.get_service_order(order_a["id"], agent_headers))
        assert swept["order_state"] == "EXPIRED", (
            f"the lapsed hold is swept by the filing, got {swept['order_state']}"
        )
        assert swept["reservation_expires_at"] == "2026-08-04T00:00:00.000Z", (
            "an expired order keeps its reservation instant for audit, "
            f"got {swept['reservation_expires_at']}"
        )

        subscriber_b_after = validate_success(api.get_subscriber(subscriber_b["id"], agent_headers))
        assert subscriber_b_after["account_state"] == "PROSPECT", (
            "the reserved branch leaves the account in PROSPECT, "
            f"got {subscriber_b_after['account_state']}"
        )

        cell = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        assert cell["reserved_slot_count"] == 1, (
            "one hold expired and one was created, "
            f"got reserved_slot_count {cell['reserved_slot_count']}"
        )
        assert cell["committed_terminal_count"] == 0
        assert cell["free_slot_count"] == 0
        assert cell["waitlist_depth"] == 0, (
            f"nothing was waitlisted, got waitlist_depth {cell['waitlist_depth']}"
        )
        assert cell["availability_state"] == "WAITLIST_ONLY", (
            "the cell is full again with room on its waitlist, "
            f"got {cell['availability_state']}"
        )


class TestCycleChargeDiscountBandOnGrossTotal:
    """The discount band is keyed on a gross total that already carries the overage fee."""

    @pytest.mark.parametrize(
        "gb_used, expected_cycle_charge_cents",
        [
            (None, 9900),
            (150.0, 10593),
            (704.0, 22500),
        ],
        ids=[
            "gross_9900_below_the_first_band_takes_no_discount",
            "gross_11150_from_50_gb_overage_takes_five_percent",
            "gross_25000_from_604_gb_overage_takes_ten_percent",
        ],
    )
    def test_discount_band_is_selected_from_the_gross_total(
        self, api, netops_headers, agent_headers, gb_used, expected_cycle_charge_cents
    ):
        """A 9,900-cent plan lands in three different bands purely through its overage fee.

        PRD §3.9: "Step 5's charge calculation has a pinned evaluation order of its own, because the discount band is keyed on a total that already contains the overage fee."
        PRD §3.9: "First, the effective threshold is the plan's `priority_data_gb` plus the beam's `deprioritization_grace_gb`, and the overage volume is the amount by which the subscription's `cycle_priority_gb_used` exceeds that threshold, rounded half up to 3 decimal places and floored at 0."
        PRD §3.9: "The overage fee in cents is that volume multiplied by the plan's `overage_rate_cents_per_gb`, rounded half up to whole cents."
        PRD §3.9: "Second, the gross total in cents is the plan's `monthly_fee_cents` plus that overage fee."
        PRD §3.9: "Third, the discount rate is selected from the **gross** total, never from the monthly fee alone: no discount when the gross total is strictly below 10,000 cents, five percent when the gross total is at least 10,000 cents but strictly below 25,000 cents, and ten percent when the gross total is at or above 25,000 cents."
        PRD §3.9: "Fourth, the subscription's `cycle_charge_cents` is the gross total multiplied by one minus that discount rate, rounded half up to whole cents — a single rounding applied after the discount, not before it."
        PRD §3.9: "That charge is then added to the subscriber's `pending_charge_cents`."

        Design: Difficulty/combinatorial_formula/cycle_charge_discount_band_keyed_on_gross_total_that_contains_the_overage_fee
        """
        env = setup_active_subscription()
        if gb_used is not None:
            ingest_usage(env["subscription"]["id"], gb_used, billing_cycle_index=0)

        report = validate_success(api.close_billing_cycle(env["beam"]["id"], netops_headers))
        assert report["charged_subscription_count"] == 1, (
            "the single ACTIVE subscription on the beam is charged, "
            f"got {report['charged_subscription_count']}"
        )

        subscription = validate_success(
            api.get_subscription(env["subscription"]["id"], netops_headers)
        )
        assert subscription["cycle_charge_cents"] == expected_cycle_charge_cents, (
            f"gb_used {gb_used} against a 100 GB allowance and a 9900-cent fee should charge "
            f"{expected_cycle_charge_cents} cents, got {subscription['cycle_charge_cents']}"
        )

        subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert subscriber["pending_charge_cents"] == expected_cycle_charge_cents, (
            "the cycle charge is added to the account's unbilled charges, "
            f"got {subscriber['pending_charge_cents']}"
        )

    def test_charge_sees_the_closing_cycle_before_the_fair_use_reset_wipes_it(
        self, api, netops_headers, agent_headers
    ):
        """150 GB charges 10,593 cents and only then resets the counter and restores PRIORITY.

        PRD §3.9: "Because step 5 runs before step 6, the charge sees the closing cycle's accumulated `cycle_priority_gb_used` rather than the zero the reset is about to write."
        PRD §3.9: "Fourth, the subscription's `cycle_charge_cents` is the gross total multiplied by one minus that discount rate, rounded half up to whole cents — a single rounding applied after the discount, not before it."
        PRD §3.9: "The beam's `billing_cycle_index` increases by 1 and its `last_cycle_closed_at` is stamped with the logical clock's current instant."
        PRD §3.9: "Every subscription on the beam's cells whose `service_state` is `ACTIVE` has its `cycle_priority_gb_used` reset to 0, has its `deprioritized_at` cleared to empty, and has its `cycle_billing_index` set to the beam's newly incremented `billing_cycle_index`."
        PRD §3.9: "Those among them whose `priority_state` was `DEPRIORITIZED` move `DEPRIORITIZED → PRIORITY`, which is the only way a throttled subscription is ever restored."
        PRD §3.9: "Its response carries the `beam_id` it ran against, the beam's new `billing_cycle_index`, a `license_expired` flag recording whether step 2 fired, a `disclosure_expired_count` from step 3, an `expired_order_count` from step 4, a `charged_subscription_count` from step 5, a `restored_subscription_count` from step 6, a `promoted_order_count` from step 8, and the beam's resulting `capacity_state`."

        Design: Difficulty/combinatorial_formula/cycle_charge_discount_band_keyed_on_gross_total_that_contains_the_overage_fee
        """
        env = setup_active_subscription()
        ingest_usage(env["subscription"]["id"], 150.0, billing_cycle_index=0)

        before = validate_success(api.get_subscription(env["subscription"]["id"], netops_headers))
        assert before["cycle_priority_gb_used"] == pytest.approx(150.0, abs=0.001), (
            f"the counted reading must accumulate, got {before['cycle_priority_gb_used']}"
        )
        assert before["priority_state"] == "DEPRIORITIZED", (
            "150 GB is at or above the 100 GB effective threshold, "
            f"got {before['priority_state']}"
        )

        report = validate_success(api.close_billing_cycle(env["beam"]["id"], netops_headers))
        assert report["beam_id"] == env["beam"]["id"]
        assert report["billing_cycle_index"] == 1, (
            f"the closing run advances the beam's cycle index to 1, "
            f"got {report['billing_cycle_index']}"
        )
        assert report["license_expired"] is False, (
            "the licence expires in 2027, well after the clock"
        )
        assert report["disclosure_expired_count"] == 0, (
            "the disclosure was acknowledged before the run, "
            f"got {report['disclosure_expired_count']}"
        )
        assert report["expired_order_count"] == 0, (
            "the only order was consumed by activation, "
            f"got {report['expired_order_count']}"
        )
        assert report["charged_subscription_count"] == 1
        assert report["restored_subscription_count"] == 1, (
            "the throttled subscription is restored by the fair-use reset, "
            f"got {report['restored_subscription_count']}"
        )
        assert report["promoted_order_count"] == 0, (
            f"no order was waitlisted, got {report['promoted_order_count']}"
        )
        assert report["capacity_state"] == "NORMAL", (
            "a restored PRIORITY_1 subscription sells 200 of 400 permitted megabits, "
            f"which bands as NORMAL, got {report['capacity_state']}"
        )

        after = validate_success(api.get_subscription(env["subscription"]["id"], netops_headers))
        assert after["cycle_charge_cents"] == 10593, (
            "overage 50.000 GB * 25 = 1250, gross 11150, five percent band, "
            f"11150 * 0.95 = 10592.5 rounds half up to 10593, got {after['cycle_charge_cents']}"
        )
        assert after["cycle_priority_gb_used"] == pytest.approx(0.0, abs=0.001), (
            f"the reset zeroes the metered counter, got {after['cycle_priority_gb_used']}"
        )
        assert after["priority_state"] == "PRIORITY", (
            f"the reset restores the fair-use dimension, got {after['priority_state']}"
        )
        assert after["cycle_billing_index"] == 1, (
            "the subscription is moved onto the newly opened cycle, "
            f"got {after['cycle_billing_index']}"
        )

        subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert subscriber["pending_charge_cents"] == 10593, (
            f"the charge is booked against the account, got {subscriber['pending_charge_cents']}"
        )

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert beam["billing_cycle_index"] == 1
        assert beam["last_cycle_closed_at"] == "2026-08-01T00:00:00.000Z", (
            "the close stamps the logical clock's current instant, "
            f"got {beam['last_cycle_closed_at']}"
        )


class TestBeamWeightedOversubscription:
    """Tier weight, the fair-use override and the policy limit compose into one band."""

    @staticmethod
    def _two_sold_subscriptions_under_a_three_times_limit() -> dict:
        """Two ACTIVE PRIORITY_1 subscriptions at 200 Mbps each on a 100 Mbps beam,
        with capacity policy tightened to an oversubscription limit of 3.0."""
        env = setup_active_subscription(max_active_terminals=2)
        env["second"] = add_active_subscription(env, subscriber_index=2, terminal_index=2)
        write_capacity_policy(
            env["beam"]["id"], oversubscription_limit=3.0, deprioritization_grace_gb=0
        )
        return env

    def test_tightened_policy_limit_rebands_the_full_beam_as_saturated(
        self, api, netops_headers, agent_headers
    ):
        """400 weighted megabits on 100 physical megabits is ratio 4.0, above a 3.0 limit.

        PRD §2.8: "Each contributing subscription contributes its plan's `committed_rate_mbps` multiplied by a weight."
        PRD §2.8: "Otherwise the weight comes from the plan's `priority_tier` — 1.0 for `PRIORITY_1`, 0.7 for `PRIORITY_2`, and 0.4 for `BEST_EFFORT`."
        PRD §2.8: "The sum of those products across the beam's contributing subscriptions, rounded half up to 3 decimal places, is the beam's `weighted_sold_mbps`."
        PRD §2.8: "Dividing that by `forward_capacity_mbps` and rounding half up to 4 decimal places gives `oversubscription_ratio`."
        PRD §2.8: "It is `NORMAL` when the ratio is less than or equal to three quarters of `oversubscription_limit`; `CONSTRAINED` when the ratio is strictly greater than three quarters of the limit but still less than or equal to the limit itself; and `SATURATED` when the ratio is strictly greater than the limit."
        PRD §3.2: "Writing the policy recomputes the beam's `oversubscription_ratio` and `capacity_state` against the new limit, re-evaluates every subscription on the beam against the new effective fair-use threshold, recomputes `availability_state` on every cell of the beam, and increases the beam's `version` by 1."
        PRD §3.3: "It is `CLOSED` if the governing beam's `beam_state` is `SUSPENDED`, or the beam's `capacity_state` is `SATURATED`, or the cell's `max_active_terminals` is 0 — those three override everything below."

        Design: Difficulty/combinatorial_formula/beam_weighted_oversubscription_combines_tier_weight_priority_override_and_policy_limit
        """
        env = self._two_sold_subscriptions_under_a_three_times_limit()

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert beam["oversubscription_limit"] == pytest.approx(3.0, abs=0.001), (
            f"the policy write installs the new limit, got {beam['oversubscription_limit']}"
        )
        assert beam["weighted_sold_mbps"] == pytest.approx(400.0, abs=0.001), (
            "two PRIORITY_1 subscriptions at 200 Mbps and weight 1.0 sell 400.0, "
            f"got {beam['weighted_sold_mbps']}"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(4.0, abs=0.001), (
            f"400.0 over 100 Mbps is a ratio of 4.0, got {beam['oversubscription_ratio']}"
        )
        assert beam["capacity_state"] == "SATURATED", (
            "a ratio of 4.0 is strictly greater than the 3.0 limit, "
            f"got {beam['capacity_state']}"
        )
        assert_beam_congestion_band(beam)

        cell = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        assert cell["availability_state"] == "CLOSED", (
            "a SATURATED governing beam closes the cell outright, "
            f"got {cell['availability_state']}"
        )

    def test_fair_use_override_outranks_the_tier_weight_and_rebands_to_constrained(
        self, api, netops_headers, agent_headers
    ):
        """Throttling one of the two subscriptions reweights it at 0.25, giving 250.0 and CONSTRAINED.

        PRD §3.6: "If the subscription's `priority_state` is `PRIORITY` and its `cycle_priority_gb_used` is greater than or equal to the effective threshold, the fair-use dimension flips `PRIORITY → DEPRIORITIZED`."
        PRD §3.6: "On the flip, `deprioritized_at` is stamped with the logical clock's current instant and `effective_rate_mbps` is replaced by the plan's `deprioritized_rate_mbps` — this is the field a subscriber-facing portal reads to explain the slowdown, and it holds the plan's `committed_rate_mbps` whenever `priority_state` is `PRIORITY` and the plan's `deprioritized_rate_mbps` whenever it is `DEPRIORITIZED`."
        PRD §2.8: "The weight is taken from the subscription's fair-use dimension first: a subscription whose `priority_state` is `DEPRIORITIZED` weighs 0.25 regardless of what plan it holds."
        PRD §2.8: "The sum of those products across the beam's contributing subscriptions, rounded half up to 3 decimal places, is the beam's `weighted_sold_mbps`."
        PRD §2.8: "It is `NORMAL` when the ratio is less than or equal to three quarters of `oversubscription_limit`; `CONSTRAINED` when the ratio is strictly greater than three quarters of the limit but still less than or equal to the limit itself; and `SATURATED` when the ratio is strictly greater than the limit."
        PRD §3.3: "Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."

        Design: Difficulty/combinatorial_formula/beam_weighted_oversubscription_combines_tier_weight_priority_override_and_policy_limit
        """
        env = self._two_sold_subscriptions_under_a_three_times_limit()
        second_subscription_id = env["second"]["subscription"]["id"]

        ingest_usage(second_subscription_id, 100.0, billing_cycle_index=0)

        throttled = validate_success(api.get_subscription(second_subscription_id, netops_headers))
        assert throttled["cycle_priority_gb_used"] == pytest.approx(100.0, abs=0.001), (
            f"the counted reading accumulates, got {throttled['cycle_priority_gb_used']}"
        )
        assert throttled["priority_state"] == "DEPRIORITIZED", (
            "landing exactly on the 100 GB effective threshold throttles, "
            f"got {throttled['priority_state']}"
        )
        assert throttled["effective_rate_mbps"] == pytest.approx(20.0, abs=0.001), (
            "a throttled subscription reports the plan's deprioritized rate, "
            f"got {throttled['effective_rate_mbps']}"
        )

        untouched = validate_success(
            api.get_subscription(env["subscription"]["id"], netops_headers)
        )
        assert untouched["priority_state"] == "PRIORITY", (
            "the other subscription consumed nothing and keeps its tier weight, "
            f"got {untouched['priority_state']}"
        )

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert beam["weighted_sold_mbps"] == pytest.approx(250.0, abs=0.001), (
            "200 * 1.0 plus 200 * 0.25 is 250.0, "
            f"got {beam['weighted_sold_mbps']}"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(2.5, abs=0.001), (
            f"250.0 over 100 Mbps is a ratio of 2.5, got {beam['oversubscription_ratio']}"
        )
        assert beam["capacity_state"] == "CONSTRAINED", (
            "2.5 is strictly above three quarters of the 3.0 limit (2.25) and at or below 3.0, "
            f"so the band is CONSTRAINED and not NORMAL, got {beam['capacity_state']}"
        )
        assert_beam_congestion_band(beam)

        cell = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        assert cell["committed_terminal_count"] == 2, (
            "both subscriptions still occupy their slots, "
            f"got {cell['committed_terminal_count']}"
        )
        assert cell["free_slot_count"] == 0
        assert cell["availability_state"] == "WAITLIST_ONLY", (
            "the beam is no longer SATURATED, so the cell reopens to its waitlist, "
            f"got {cell['availability_state']}"
        )

    def test_capacity_policy_write_against_a_stale_beam_version_is_refused(
        self, api, netops_headers
    ):
        """A limit computed from an out-of-date congestion picture cannot overwrite the newer one.

        PRD §2.6: "Writing a beam's capacity policy (`POST /satellite-broadband/beams/{id}/capacity-policy`) likewise requires `expected_beam_version`."
        PRD §2.6: "A policy write supersedes the previous policy and has no state precondition to fail, so the version token is the only thing standing between a policy computed from an out-of-date congestion picture and the newer policy it would otherwise overwrite."
        PRD §2.6: "A mismatch is rejected with `ERR_STALE_BEAM_VERSION` (HTTP 412)."

        Design: Difficulty/combinatorial_formula/beam_weighted_oversubscription_combines_tier_weight_priority_override_and_policy_limit
        """
        env = setup_active_subscription(max_active_terminals=2)
        stale_version = get_beam_version(env["beam"]["id"])

        # A second activation recomputes the beam's sold megabits, moving its version on.
        add_active_subscription(env, subscriber_index=2, terminal_index=2)
        current_version = get_beam_version(env["beam"]["id"])
        assert current_version != stale_version, (
            "a second activation must advance the beam version for this test to be meaningful"
        )

        response = api.write_capacity_policy(
            env["beam"]["id"],
            {
                "oversubscription_limit": 3.0,
                "deprioritization_grace_gb": 0,
                "expected_beam_version": stale_version,
            },
            netops_headers,
        )
        validate_error(response, ApiErrorId.ERR_STALE_BEAM_VERSION, 412)

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert beam["oversubscription_limit"] == pytest.approx(4.0, abs=0.001), (
            "the refused write must not install its limit, "
            f"got {beam['oversubscription_limit']}"
        )
        assert beam["version"] == current_version, (
            f"a refused write mutates nothing, {current_version} -> {beam['version']}"
        )
