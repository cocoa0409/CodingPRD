"""Calculation rules of the Satellite Broadband Provisioning API.

Every test in this module drives the live API from an empty database and pins one
piece of the PRD's arithmetic: the fair-use threshold and its inclusive boundary,
the `counted` filter on metered readings, the provisional outage-credit rounding
and its half-a-month cap, the waitlist ranking key and its tie-break, the
governing-licence ranking rule, and the different input sets the cell-slot and
beam-megabit ledgers draw from.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    create_active_license,
    create_beam,
    create_cell,
    create_order,
    create_plan,
    create_subscriber,
    ingest_usage,
    iso_shift,
    open_outage_event,
    request_roaming,
    set_clock,
    setup_active_subscription,
    setup_topology,
    setup_waitlisted_order,
    usage_record_payload,
    validate_paginated,
    validate_success,
)


# ─────────────────────── fair-use metering threshold ──────────────────────


class TestFairUseThreshold:
    """The effective threshold, and the direction of its boundary."""

    def test_counter_landing_exactly_on_the_effective_threshold_deprioritizes(
        self, api, netops_headers, agent_headers
    ):
        """Readings of 99.5 then 0.5 GB land the counter on exactly 100.000 GB and throttle.

        PRD §3.6: "It is the plan's `priority_data_gb` plus the governing beam's `deprioritization_grace_gb` — the beam-level generosity described in §3.2."
        PRD §3.6: "A reading whose `counted` is true adds its `gb_used` to `cycle_priority_gb_used` and the sum is rounded half up to 3 decimal places."
        PRD §3.6: "If the subscription's `priority_state` is `PRIORITY` and its `cycle_priority_gb_used` is greater than or equal to the effective threshold, the fair-use dimension flips `PRIORITY → DEPRIORITIZED`."
        PRD §3.6: "The boundary is inclusive: landing exactly on the threshold throttles."
        PRD §3.6: "On the flip, `deprioritized_at` is stamped with the logical clock's current instant and `effective_rate_mbps` is replaced by the plan's `deprioritized_rate_mbps` — this is the field a subscriber-facing portal reads to explain the slowdown, and it holds the plan's `committed_rate_mbps` whenever `priority_state` is `PRIORITY` and the plan's `deprioritized_rate_mbps` whenever it is `DEPRIORITIZED`."
        PRD §2.8: "The weight is taken from the subscription's fair-use dimension first: a subscription whose `priority_state` is `DEPRIORITIZED` weighs 0.25 regardless of what plan it holds."

        Design: Corner/calculations/fair_use_deprioritization_triggers_at_exactly_the_effective_threshold
        """
        env = setup_active_subscription(
            clock=CLOCK_EPOCH,
            forward_capacity_mbps=100,
            oversubscription_limit=4.0,
            max_active_terminals=1,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            monthly_fee_cents=9900,
            priority_data_gb=100,
        )
        subscription_id = env["subscription"]["id"]

        # A freshly created beam carries deprioritization_grace_gb 0, so the
        # effective threshold is the plan's 100 GB allowance exactly.
        beam_before = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert beam_before["deprioritization_grace_gb"] == 0, (
            "a freshly created beam starts with deprioritization_grace_gb at 0, got "
            f"{beam_before['deprioritization_grace_gb']}"
        )

        ingest_usage(subscription_id, 99.5, 0)

        response = api.create_usage_record(
            subscription_id, usage_record_payload(0.5, 0), netops_headers
        )
        reading = validate_success(response, 201)
        assert reading["counted"] is True, "a reading tagged with the current cycle index counts"
        assert reading["gb_used"] == pytest.approx(0.5, abs=0.001), (
            f"the ingested volume must be echoed back, got {reading['gb_used']}"
        )

        subscription = validate_success(api.get_subscription(subscription_id, agent_headers))
        assert subscription["cycle_priority_gb_used"] == pytest.approx(100.000, abs=0.001), (
            "99.5 + 0.5 must accumulate to exactly 100.000 GB, got "
            f"{subscription['cycle_priority_gb_used']}"
        )
        assert subscription["priority_state"] == "DEPRIORITIZED", (
            "landing exactly on the 100 GB effective threshold throttles, got "
            f"{subscription['priority_state']}"
        )
        assert subscription["deprioritized_at"] == "2026-08-01T00:00:00.000Z", (
            "deprioritized_at is the logical clock's current instant, got "
            f"{subscription['deprioritized_at']}"
        )
        assert subscription["effective_rate_mbps"] == pytest.approx(20, abs=0.001), (
            "effective_rate_mbps becomes the plan's deprioritized_rate_mbps of 20, got "
            f"{subscription['effective_rate_mbps']}"
        )
        assert subscription["service_state"] == "ACTIVE", (
            "the fair-use flip leaves the provisioning dimension alone, got "
            f"{subscription['service_state']}"
        )
        assert subscription["authorization_state"] == "AUTHORIZED_FIXED", (
            "the fair-use flip leaves the authorisation dimension alone, got "
            f"{subscription['authorization_state']}"
        )

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert beam["weighted_sold_mbps"] == pytest.approx(50, abs=0.001), (
            "200 Mbps weighted at 0.25 sells 50 Mbps, got "
            f"{beam['weighted_sold_mbps']}"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(0.5, abs=0.001), (
            f"50 / 100 Mbps is a ratio of 0.5, got {beam['oversubscription_ratio']}"
        )
        assert beam["capacity_state"] == "NORMAL", (
            "0.5 is at or below three quarters of the 4.0 limit, got "
            f"{beam['capacity_state']}"
        )

    def test_counter_one_step_below_the_effective_threshold_stays_priority(
        self, api, netops_headers, agent_headers
    ):
        """A single 99.5 GB reading stops short of the 100 GB threshold and does not throttle.

        PRD §3.6: "It is the plan's `priority_data_gb` plus the governing beam's `deprioritization_grace_gb` — the beam-level generosity described in §3.2."
        PRD §3.6: "If the subscription's `priority_state` is `PRIORITY` and its `cycle_priority_gb_used` is greater than or equal to the effective threshold, the fair-use dimension flips `PRIORITY → DEPRIORITIZED`."
        PRD §3.6: "On the flip, `deprioritized_at` is stamped with the logical clock's current instant and `effective_rate_mbps` is replaced by the plan's `deprioritized_rate_mbps` — this is the field a subscriber-facing portal reads to explain the slowdown, and it holds the plan's `committed_rate_mbps` whenever `priority_state` is `PRIORITY` and the plan's `deprioritized_rate_mbps` whenever it is `DEPRIORITIZED`."

        Design: Corner/calculations/fair_use_deprioritization_triggers_at_exactly_the_effective_threshold
        """
        env = setup_active_subscription(
            clock=CLOCK_EPOCH,
            forward_capacity_mbps=100,
            oversubscription_limit=4.0,
            max_active_terminals=1,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            priority_data_gb=100,
        )
        subscription_id = env["subscription"]["id"]

        response = api.create_usage_record(
            subscription_id, usage_record_payload(99.5, 0), netops_headers
        )
        reading = validate_success(response, 201)
        assert reading["counted"] is True, "a reading tagged with the current cycle index counts"

        subscription = validate_success(api.get_subscription(subscription_id, agent_headers))
        assert subscription["cycle_priority_gb_used"] == pytest.approx(99.500, abs=0.001), (
            f"the counter carries 99.500 GB, got {subscription['cycle_priority_gb_used']}"
        )
        assert subscription["priority_state"] == "PRIORITY", (
            "99.5 GB is strictly below the 100 GB effective threshold, got "
            f"{subscription['priority_state']}"
        )
        assert subscription["effective_rate_mbps"] == pytest.approx(200, abs=0.001), (
            "a PRIORITY subscription reads its plan's committed_rate_mbps of 200, got "
            f"{subscription['effective_rate_mbps']}"
        )

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001), (
            "a PRIORITY_1 subscription still weighs 1.0, so 200 Mbps stay sold, got "
            f"{beam['weighted_sold_mbps']}"
        )


def test_usage_record_for_a_foreign_billing_cycle_is_stored_uncounted(
    api, netops_headers, agent_headers
):
    """A 500 GB reading tagged with cycle 1 against a cycle-0 subscription is inert.

    PRD §3.5: "Its `cycle_billing_index` is copied from the governing beam's current `billing_cycle_index`, which is what makes metered readings from a stale cycle identifiable later."
    PRD §3.6: "The reading is stamped with `recorded_at` from the logical clock and is immutable thereafter; like a sky survey, it carries only an `id` and a `created_at` from §2.5."
    PRD §3.6: "Its `counted` flag is computed at ingest as true exactly when the supplied `billing_cycle_index` equals the subscription's current `cycle_billing_index`, and false otherwise."
    PRD §3.6: "A reading with `counted` false is still persisted and still readable, but it **never** advances `cycle_priority_gb_used`, and it is invisible both to the deprioritisation threshold and to the overage calculation."

    Design: Corner/calculations/usage_record_for_a_foreign_billing_cycle_is_stored_uncounted
    """
    env = setup_active_subscription(
        clock=CLOCK_EPOCH,
        forward_capacity_mbps=100,
        oversubscription_limit=4.0,
        max_active_terminals=1,
        committed_rate_mbps=200,
        priority_tier="PRIORITY_1",
        priority_data_gb=100,
    )
    subscription_id = env["subscription"]["id"]

    before = validate_success(api.get_subscription(subscription_id, agent_headers))
    assert before["cycle_billing_index"] == 0, (
        "the subscription inherits the beam's billing_cycle_index of 0, got "
        f"{before['cycle_billing_index']}"
    )

    response = api.create_usage_record(
        subscription_id, usage_record_payload(500, 1), netops_headers
    )
    reading = validate_success(response, 201)
    assert reading["counted"] is False, (
        "cycle index 1 does not equal the subscription's cycle index 0, so counted is false"
    )
    assert reading["billing_cycle_index"] == 1, (
        f"the supplied cycle index is stored as given, got {reading['billing_cycle_index']}"
    )
    assert reading["gb_used"] == pytest.approx(500, abs=0.001), (
        f"the uncounted volume is still persisted, got {reading['gb_used']}"
    )
    assert reading["recorded_at"] == "2026-08-01T00:00:00.000Z", (
        f"recorded_at is read from the logical clock, got {reading['recorded_at']}"
    )

    subscription = validate_success(api.get_subscription(subscription_id, agent_headers))
    assert subscription["cycle_priority_gb_used"] == pytest.approx(0.000, abs=0.001), (
        "an uncounted reading never advances the counter, got "
        f"{subscription['cycle_priority_gb_used']}"
    )
    assert subscription["priority_state"] == "PRIORITY", (
        "500 GB invisible to the threshold cannot throttle, got "
        f"{subscription['priority_state']}"
    )
    assert subscription["effective_rate_mbps"] == pytest.approx(200, abs=0.001), (
        "a PRIORITY subscription reads its plan's committed_rate_mbps of 200, got "
        f"{subscription['effective_rate_mbps']}"
    )

    beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
    assert beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001), (
        "the subscription is still PRIORITY_1 at weight 1.0, got "
        f"{beam['weighted_sold_mbps']}"
    )
    assert beam["oversubscription_ratio"] == pytest.approx(2.0, abs=0.001), (
        f"200 / 100 Mbps is a ratio of 2.0, got {beam['oversubscription_ratio']}"
    )

    readings, meta = validate_paginated(api.list_usage_records(subscription_id, netops_headers))
    assert meta["total_count"] == 1, (
        f"the uncounted reading is still readable, got total_count {meta['total_count']}"
    )
    assert readings[0]["counted"] is False, "the persisted reading keeps its counted flag false"


# ───────────────────────── outage credit arithmetic ────────────────────────


def test_outage_credit_provisional_amount_rounds_half_up_to_whole_cents(
    api, netops_headers, agent_headers
):
    """A 300-minute rain-fade degradation on a 12000-cent plan stores 21 cents, not 20.

    PRD §3.8: "Resolution moves the event `OPEN → RESOLVED` and computes `outage_minutes` as the number of whole minutes between `started_at` and `ended_at`, discarding any partial minute."
    PRD §3.8: "It then computes `credit_eligible`, which is true only when the `cause` is anything other than `PLANNED_MAINTENANCE` **and** `outage_minutes` is at least 30 — a shorter blip is beneath the service-level floor."
    PRD §3.8: "Each drafted credit's `provisional_credit_cents` is computed by the provisional rule below, and each affected subscriber's `pending_credit_cents` is increased by that amount."
    PRD §3.8: "The event's `generated_credit_count` records how many credits were created."
    PRD §3.8: "The cause factor is 0.5 for `WEATHER_RAIN_FADE`, 1.0 for `EQUIPMENT_FAILURE`, 1.0 for `SPECTRUM_INTERFERENCE` and 0.0 for `PLANNED_MAINTENANCE`."
    PRD §3.8: "The severity factor is 1.0 for `FULL_OUTAGE` and 0.5 for `DEGRADATION`."
    PRD §3.8: "Take the plan's `monthly_fee_cents`, multiply it by the event's `outage_minutes` divided by a nominal billing month of 43,200 minutes — thirty days of minutes — then multiply by the multiplier."
    PRD §3.8: "Round that product half up to whole cents, and take the smaller of it and the cap."

    Design: Corner/calculations/outage_credit_provisional_amount_rounds_half_up_to_whole_cents
    """
    env = setup_active_subscription(
        clock=CLOCK_EPOCH,
        forward_capacity_mbps=100,
        max_active_terminals=1,
        committed_rate_mbps=200,
        priority_tier="PRIORITY_1",
        monthly_fee_cents=12000,
    )
    set_clock("2026-08-02T06:00:00Z")
    event = open_outage_event(
        env["beam"]["id"],
        cause="WEATHER_RAIN_FADE",
        severity="DEGRADATION",
        started_at="2026-08-02T00:00:00Z",
    )

    response = api.resolve_outage_event(
        event["id"], {"ended_at": "2026-08-02T05:00:00Z"}, netops_headers
    )
    resolved = validate_success(response, 200)
    assert resolved["outage_minutes"] == 300, (
        f"five hours is 300 whole minutes, got {resolved['outage_minutes']}"
    )
    assert resolved["credit_eligible"] is True, (
        "a non-maintenance impairment of at least 30 minutes is eligible"
    )
    assert resolved["generated_credit_count"] == 1, (
        "the single affected subscription draws one credit, got "
        f"{resolved['generated_credit_count']}"
    )

    credits, meta = validate_paginated(
        api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one credit row was drafted, got total_count {meta['total_count']}"
    )
    credit = credits[0]
    # 12000 * 300 / 43200 * 0.5 * 0.5 = 20.8333... cents, rounded half up to 21.
    assert credit["provisional_credit_cents"] == 21, (
        "20.8333 cents must round half up to 21 whole cents, got "
        f"{credit['provisional_credit_cents']}"
    )
    assert credit["credit_state"] == "DRAFT", (
        f"a resolution cascade drafts the credit, got {credit['credit_state']}"
    )
    assert credit.get("final_credit_cents") is None, (
        "the final amount is only written at approval, got "
        f"{credit.get('final_credit_cents')}"
    )

    subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
    assert subscriber["pending_credit_cents"] == 21, (
        "the provisional amount lands on the pending ledger, got "
        f"{subscriber['pending_credit_cents']}"
    )
    assert subscriber["credit_balance_cents"] == 0, (
        "a DRAFT credit never reaches the balance, got "
        f"{subscriber['credit_balance_cents']}"
    )


def test_outage_credit_capped_at_half_the_monthly_fee_for_a_multi_week_outage(
    api, netops_headers, agent_headers
):
    """A 24-day equipment failure computes 7920 cents but is clamped to the 4950-cent cap.

    PRD §3.8: "Resolution moves the event `OPEN → RESOLVED` and computes `outage_minutes` as the number of whole minutes between `started_at` and `ended_at`, discarding any partial minute."
    PRD §3.8: "It then computes `credit_eligible`, which is true only when the `cause` is anything other than `PLANNED_MAINTENANCE` **and** `outage_minutes` is at least 30 — a shorter blip is beneath the service-level floor."
    PRD §3.8: "The cause factor is 0.5 for `WEATHER_RAIN_FADE`, 1.0 for `EQUIPMENT_FAILURE`, 1.0 for `SPECTRUM_INTERFERENCE` and 0.0 for `PLANNED_MAINTENANCE`."
    PRD §3.8: "The severity factor is 1.0 for `FULL_OUTAGE` and 0.5 for `DEGRADATION`."
    PRD §3.8: "The cap is half the plan's `monthly_fee_cents`, rounded half up to whole cents — no single event can credit more than half a month of service."
    PRD §3.8: "Take the plan's `monthly_fee_cents`, multiply it by the event's `outage_minutes` divided by a nominal billing month of 43,200 minutes — thirty days of minutes — then multiply by the multiplier."
    PRD §3.8: "Round that product half up to whole cents, and take the smaller of it and the cap."

    Design: Corner/calculations/outage_credit_capped_at_half_the_monthly_fee_for_a_multi_week_outage
    """
    env = setup_active_subscription(
        clock=CLOCK_EPOCH,
        forward_capacity_mbps=100,
        max_active_terminals=1,
        committed_rate_mbps=200,
        priority_tier="PRIORITY_1",
        monthly_fee_cents=9900,
    )
    set_clock("2026-08-26T01:00:00Z")
    event = open_outage_event(
        env["beam"]["id"],
        cause="EQUIPMENT_FAILURE",
        severity="FULL_OUTAGE",
        started_at="2026-08-02T00:00:00Z",
    )

    response = api.resolve_outage_event(
        event["id"], {"ended_at": "2026-08-26T00:00:00Z"}, netops_headers
    )
    resolved = validate_success(response, 200)
    assert resolved["outage_minutes"] == 34560, (
        f"24 days is 34560 whole minutes, got {resolved['outage_minutes']}"
    )
    assert resolved["credit_eligible"] is True, (
        "an equipment failure well beyond 30 minutes is eligible"
    )
    assert resolved["generated_credit_count"] == 1, (
        "the single affected subscription draws one credit, got "
        f"{resolved['generated_credit_count']}"
    )

    credits, meta = validate_paginated(
        api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one credit row was drafted, got total_count {meta['total_count']}"
    )
    credit = credits[0]
    # 9900 * 34560 / 43200 * 1.0 * 1.0 = 7920 cents, clamped to the cap of 9900 * 0.5 = 4950.
    assert credit["provisional_credit_cents"] == 4950, (
        "the smaller of the 7920-cent product and the 4950-cent cap is stored, got "
        f"{credit['provisional_credit_cents']}"
    )
    assert credit["credit_state"] == "DRAFT", (
        f"a resolution cascade drafts the credit, got {credit['credit_state']}"
    )

    subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
    assert subscriber["pending_credit_cents"] == 4950, (
        "the capped amount, not the raw product, reaches the pending ledger, got "
        f"{subscriber['pending_credit_cents']}"
    )


# ────────────────────────── waitlist ranking key ───────────────────────────


class TestWaitlistPromotionRanking:
    """`waitlist_priority_score` descending, `created_at` ascending as the tie-break."""

    def test_promotion_breaks_the_score_tie_on_created_at_ascending(
        self, api, agent_headers, netops_headers
    ):
        """Two orders tie at 3000; cancelling the reservation promotes the earlier-created one.

        PRD §3.3: "The plan tier contributes a rank multiplied by one thousand: 3 for a `requested_plan_id` whose `priority_tier` is `PRIORITY_1`, 2 for `PRIORITY_2` and 1 for `BEST_EFFORT`."
        PRD §3.3: "Waiting time contributes the number of whole days the order has been waiting — the elapsed time from the order's `created_at` to the logical clock's current instant, expressed in whole days with any partial day discarded — capped at 365 so that no amount of patience can outrank a whole tier."
        PRD §3.3: "They are ranked by `waitlist_priority_score` descending, and ties are broken by `created_at` ascending — never by record `id`."
        PRD §3.3: "While the cell has at least one free slot and at least one eligible order remains, the top-ranked order is promoted `WAITLISTED → RESERVED`, its `reservation_expires_at` is set to the logical clock's current instant plus 72 hours, its `promoted_at` is stamped with that same instant, and its subscriber's `account_state` moves from `WAITLISTED` back to `PROSPECT`."
        PRD §3.3: "Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`, clears `reservation_expires_at` back to empty, drops the cell's `reserved_slot_count` by 1 to release the slot, and then runs the promotion routine on that cell, so a cancellation typically hands the slot straight to the top-ranked waitlisted order and moves that order's subscriber from `WAITLISTED` to `PROSPECT`."
        PRD §3.3: "Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."

        Design: Corner/calculations/waitlist_promotion_breaks_the_score_tie_on_created_at_ascending
        """
        env = setup_topology(
            clock=CLOCK_EPOCH,
            max_active_terminals=1,
            priority_tier="PRIORITY_1",
        )
        subscriber_1 = create_subscriber(index=1, jurisdiction_code="US-CA")
        order_1 = create_order(subscriber_1["id"], env["cell"]["id"], env["plan"]["id"])
        assert order_1["order_state"] == "RESERVED", (
            f"the first order takes the only slot, got {order_1['order_state']}"
        )
        earlier = setup_waitlisted_order(env, 2)
        later = setup_waitlisted_order(env, 3)

        response = api.cancel_service_order(
            order_1["id"], {"cancel_reason": "subscriber withdrew"}, agent_headers
        )
        cancelled = validate_success(response, 200)
        assert cancelled["order_state"] == "CANCELLED", (
            f"cancelling from RESERVED lands on CANCELLED, got {cancelled['order_state']}"
        )
        assert cancelled["cancel_reason"] == "subscriber withdrew", (
            f"the mandatory reason is recorded, got {cancelled['cancel_reason']}"
        )

        promoted = validate_success(api.get_service_order(earlier["order"]["id"], agent_headers))
        assert promoted["order_state"] == "RESERVED", (
            "the earlier-created of two tied orders wins the freed slot, got "
            f"{promoted['order_state']}"
        )
        assert promoted["waitlist_priority_score"] == 3000, (
            "a PRIORITY_1 order waiting zero whole days scores 3 * 1000, got "
            f"{promoted['waitlist_priority_score']}"
        )
        assert promoted["promoted_at"] == "2026-08-01T00:00:00.000Z", (
            f"promoted_at is the logical clock's current instant, got {promoted['promoted_at']}"
        )
        assert promoted["reservation_expires_at"] == "2026-08-04T00:00:00.000Z", (
            "the promotion hold runs 72 hours from the clock, got "
            f"{promoted['reservation_expires_at']}"
        )

        still_waiting = validate_success(
            api.get_service_order(later["order"]["id"], agent_headers)
        )
        assert still_waiting["order_state"] == "WAITLISTED", (
            "only one slot was freed, so the later-created tied order keeps waiting, got "
            f"{still_waiting['order_state']}"
        )
        assert still_waiting["waitlist_priority_score"] == 3000, (
            "the loser of the tie-break carries the identical score, got "
            f"{still_waiting['waitlist_priority_score']}"
        )
        assert not still_waiting.get("promoted_at"), (
            "an order that was never promoted carries no promoted_at, got "
            f"{still_waiting.get('promoted_at')}"
        )

        promoted_subscriber = validate_success(
            api.get_subscriber(earlier["subscriber"]["id"], agent_headers)
        )
        assert promoted_subscriber["account_state"] == "PROSPECT", (
            "promotion moves the subscriber back to PROSPECT, got "
            f"{promoted_subscriber['account_state']}"
        )
        waiting_subscriber = validate_success(
            api.get_subscriber(later["subscriber"]["id"], agent_headers)
        )
        assert waiting_subscriber["account_state"] == "WAITLISTED", (
            "the still-waitlisted subscriber stays WAITLISTED, got "
            f"{waiting_subscriber['account_state']}"
        )

        cell = validate_success(api.get_service_cell(env["cell"]["id"], netops_headers))
        assert cell["reserved_slot_count"] == 1, (
            "the released slot was handed straight to the promoted order, got "
            f"{cell['reserved_slot_count']}"
        )
        assert cell["waitlist_depth"] == 1, (
            f"one order remains on the waitlist, got {cell['waitlist_depth']}"
        )
        assert cell["free_slot_count"] == 0, (
            f"the single slot is held again, got {cell['free_slot_count']}"
        )
        assert cell["availability_state"] == "WAITLIST_ONLY", (
            "no free slot with a waitlist depth below 3 advertises WAITLIST_ONLY, got "
            f"{cell['availability_state']}"
        )

    def test_promotion_prefers_the_higher_score_over_the_earlier_created_order(
        self, api, agent_headers
    ):
        """A later BEST_EFFORT order at 1000 loses to an earlier-ranked PRIORITY_1 order at 3000.

        PRD §3.3: "The plan tier contributes a rank multiplied by one thousand: 3 for a `requested_plan_id` whose `priority_tier` is `PRIORITY_1`, 2 for `PRIORITY_2` and 1 for `BEST_EFFORT`."
        PRD §3.3: "They are ranked by `waitlist_priority_score` descending, and ties are broken by `created_at` ascending — never by record `id`."
        PRD §3.3: "Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`, clears `reservation_expires_at` back to empty, drops the cell's `reserved_slot_count` by 1 to release the slot, and then runs the promotion routine on that cell, so a cancellation typically hands the slot straight to the top-ranked waitlisted order and moves that order's subscriber from `WAITLISTED` to `PROSPECT`."

        Design: Corner/calculations/waitlist_promotion_breaks_the_score_tie_on_created_at_ascending
        """
        env = setup_topology(
            clock=CLOCK_EPOCH,
            max_active_terminals=1,
            priority_tier="PRIORITY_1",
        )
        best_effort_plan = create_plan(
            plan_code="PLAN-BE-050",
            committed_rate_mbps=50,
            priority_tier="BEST_EFFORT",
            priority_data_gb=50,
        )
        subscriber_1 = create_subscriber(index=1, jurisdiction_code="US-CA")
        subscriber_2 = create_subscriber(index=2, jurisdiction_code="US-CA")
        subscriber_3 = create_subscriber(index=3, jurisdiction_code="US-CA")

        order_1 = create_order(subscriber_1["id"], env["cell"]["id"], env["plan"]["id"])
        assert order_1["order_state"] == "RESERVED", (
            f"the first order takes the only slot, got {order_1['order_state']}"
        )
        low_score = create_order(
            subscriber_2["id"], env["cell"]["id"], best_effort_plan["id"]
        )
        high_score = create_order(subscriber_3["id"], env["cell"]["id"], env["plan"]["id"])
        assert low_score["order_state"] == "WAITLISTED", (
            f"no slot remains, so the order waits, got {low_score['order_state']}"
        )
        assert high_score["order_state"] == "WAITLISTED", (
            f"no slot remains, so the order waits, got {high_score['order_state']}"
        )

        validate_success(
            api.cancel_service_order(
                order_1["id"], {"cancel_reason": "subscriber withdrew"}, agent_headers
            ),
            200,
        )

        winner = validate_success(api.get_service_order(high_score["id"], agent_headers))
        assert winner["waitlist_priority_score"] == 3000, (
            "a PRIORITY_1 order waiting zero whole days scores 3 * 1000, got "
            f"{winner['waitlist_priority_score']}"
        )
        assert winner["order_state"] == "RESERVED", (
            "the higher score wins the slot even though it was created later, got "
            f"{winner['order_state']}"
        )

        loser = validate_success(api.get_service_order(low_score["id"], agent_headers))
        assert loser["waitlist_priority_score"] == 1000, (
            "a BEST_EFFORT order waiting zero whole days scores 1 * 1000, got "
            f"{loser['waitlist_priority_score']}"
        )
        assert loser["order_state"] == "WAITLISTED", (
            "the lower-scoring order keeps waiting despite being older, got "
            f"{loser['order_state']}"
        )


# ─────────────────────── governing licence selection ──────────────────────


class TestGoverningLicenseSelection:
    """Candidate filtering, `expires_at` descending, `created_at` ascending."""

    def test_selection_picks_the_latest_expiring_coordinated_licence(
        self, api, compliance_headers, agent_headers
    ):
        """Approval pins the 2029 coordinated licence, not the beam's own nor the uncoordinated 2031 one.

        PRD §2.10: "For a roaming approval, no beam is implied, so the platform searches instead: candidate licences are those whose `jurisdiction_code` equals the request's `target_jurisdiction_code` and whose `license_state` is `ACTIVE` and whose `coordination_state` is `COORDINATED`."
        PRD §2.10: "Licences in `PENDING_COORDINATION`, `SUSPENDED`, `REFUSED` or `EXPIRED` are never candidates."
        PRD §2.10: "Candidates are ranked by `expires_at` descending — the longest-lived licence wins — and ties are broken by `created_at` ascending."
        PRD §3.7: "**Approval** moves the record `REQUESTED → APPROVED`, stores the supplied note in `decision_note`, and stamps `governing_license_id` with the licence selected by the ranking rule of §2.10 — candidates whose `jurisdiction_code` equals `target_jurisdiction_code` and which are both `ACTIVE` and `COORDINATED`, ranked by `expires_at` descending with `created_at` ascending as the tie-break."
        PRD §3.7: "For `mode` `ROAM_TEMPORARY`, approval changes nothing beyond the authorisation record itself."

        Design: Corner/calculations/governing_license_selection_picks_the_latest_expiring_coordinated_licence
        """
        env = setup_topology(
            clock=CLOCK_EPOCH,
            max_active_terminals=1,
            jurisdiction_code="US-CA",
            roaming_allowed=True,
        )
        later_coordinated = create_active_license(
            license_code="LIC-US-CA-KA-02",
            jurisdiction_code="US-CA",
            max_eirp_dbw=60.0,
            expires_at="2029-06-30T00:00:00Z",
            consumer_disclosure_version="CD-2026.2",
        )
        # Filed but never coordinated, so it is never a candidate no matter how
        # long-lived it is.
        uncoordinated_response = api.create_spectrum_license(
            {
                "license_code": "LIC-US-CA-KA-03",
                "jurisdiction_code": "US-CA",
                "frequency_band": "KA_FORWARD",
                "max_eirp_dbw": 58.0,
                "expires_at": "2031-01-01T00:00:00Z",
                "consumer_disclosure_version": "CD-2026.3",
                "in_motion_permitted": True,
            },
            compliance_headers,
        )
        uncoordinated = validate_success(uncoordinated_response, 201)

        env = setup_active_subscription(env)
        request = request_roaming(
            env["subscription"]["id"],
            subscriber_id=env["subscriber"]["id"],
            mode="ROAM_TEMPORARY",
            target_jurisdiction_code="US-CA",
            effective_from="2026-08-05T00:00:00Z",
            effective_until="2026-08-06T00:00:00Z",
        )

        response = api.decide_roaming_authorization(
            request["id"],
            {"decision": "APPROVE", "decision_note": "roam window granted"},
            compliance_headers,
        )
        approved = validate_success(response, 200)
        assert approved["auth_state"] == "APPROVED", (
            f"the request was approved, got {approved['auth_state']}"
        )
        assert approved["governing_license_id"] == later_coordinated["id"], (
            "the longest-lived ACTIVE and COORDINATED US-CA licence wins, got "
            f"{approved['governing_license_id']}"
        )
        assert approved["governing_license_id"] != env["license"]["id"], (
            "the beam's own licence does not win by association"
        )
        assert approved["governing_license_id"] != uncoordinated["id"], (
            "an UNCOORDINATED licence is never a candidate however late it expires"
        )
        assert approved["decision_note"] == "roam window granted", (
            f"the supplied note is stored, got {approved['decision_note']}"
        )

        ignored = validate_success(
            api.get_spectrum_license(uncoordinated["id"], compliance_headers)
        )
        assert ignored["license_state"] == "PENDING_COORDINATION", (
            f"the ignored licence is untouched, got {ignored['license_state']}"
        )
        assert ignored["coordination_state"] == "UNCOORDINATED", (
            f"the ignored licence is untouched, got {ignored['coordination_state']}"
        )

        subscription = validate_success(
            api.get_subscription(env["subscription"]["id"], agent_headers)
        )
        assert subscription["service_cell_id"] == env["cell"]["id"], (
            "a temporary roam never relocates the service, got "
            f"{subscription['service_cell_id']}"
        )

    def test_selection_breaks_the_expiry_tie_on_created_at_ascending(
        self, api, compliance_headers
    ):
        """Two candidates expiring on the same instant resolve to the earlier-filed one.

        PRD §2.10: "For a roaming approval, no beam is implied, so the platform searches instead: candidate licences are those whose `jurisdiction_code` equals the request's `target_jurisdiction_code` and whose `license_state` is `ACTIVE` and whose `coordination_state` is `COORDINATED`."
        PRD §2.10: "Candidates are ranked by `expires_at` descending — the longest-lived licence wins — and ties are broken by `created_at` ascending."
        PRD §2.10: "The record `id` is never a ranking key."

        Design: Corner/calculations/governing_license_selection_picks_the_latest_expiring_coordinated_licence
        """
        set_clock(CLOCK_EPOCH)
        beam_license = create_active_license(
            license_code="LIC-US-CA-KA-01",
            jurisdiction_code="US-CA",
            expires_at="2027-12-31T00:00:00Z",
            consumer_disclosure_version="CD-2026.1",
        )
        set_clock(iso_shift(CLOCK_EPOCH, hours=1))
        first_filed = create_active_license(
            license_code="LIC-US-CA-KA-02",
            jurisdiction_code="US-CA",
            max_eirp_dbw=60.0,
            expires_at="2030-01-01T00:00:00Z",
            consumer_disclosure_version="CD-2026.2",
        )
        set_clock(iso_shift(CLOCK_EPOCH, hours=2))
        second_filed = create_active_license(
            license_code="LIC-US-CA-KA-03",
            jurisdiction_code="US-CA",
            max_eirp_dbw=58.0,
            expires_at="2030-01-01T00:00:00Z",
            consumer_disclosure_version="CD-2026.3",
        )
        earlier_filing = validate_success(
            api.get_spectrum_license(first_filed["id"], compliance_headers)
        )
        later_filing = validate_success(
            api.get_spectrum_license(second_filed["id"], compliance_headers)
        )
        assert earlier_filing["expires_at"] == later_filing["expires_at"], (
            "the two candidates must expire on the same instant for the tie-break to "
            f"be the deciding rule, got {earlier_filing['expires_at']} and "
            f"{later_filing['expires_at']}"
        )
        assert earlier_filing["created_at"] < later_filing["created_at"], (
            "the tied candidates must have been filed at distinct instants for the "
            f"tie-break to be observable, got {earlier_filing['created_at']} and "
            f"{later_filing['created_at']}"
        )

        beam = create_beam(beam_license["id"], forward_capacity_mbps=100)
        cell = create_cell(beam["id"], jurisdiction_code="US-CA", max_active_terminals=1)
        plan = create_plan(roaming_allowed=True)
        env = setup_active_subscription(
            {"license": beam_license, "beam": beam, "cell": cell, "plan": plan}
        )
        request = request_roaming(
            env["subscription"]["id"],
            subscriber_id=env["subscriber"]["id"],
            mode="ROAM_TEMPORARY",
            target_jurisdiction_code="US-CA",
            effective_from="2026-08-05T00:00:00Z",
            effective_until="2026-08-06T00:00:00Z",
        )

        response = api.decide_roaming_authorization(
            request["id"],
            {"decision": "APPROVE", "decision_note": "roam window granted"},
            compliance_headers,
        )
        approved = validate_success(response, 200)
        assert approved["auth_state"] == "APPROVED", (
            f"the request was approved, got {approved['auth_state']}"
        )
        assert approved["governing_license_id"] == first_filed["id"], (
            "on an expires_at tie the earlier created_at wins, got "
            f"{approved['governing_license_id']}"
        )
        assert approved["governing_license_id"] != second_filed["id"], (
            "the later-filed of two equally long-lived candidates loses the tie-break"
        )


# ────────────────── the two ledgers draw on different sets ─────────────────


def test_suspended_subscription_frees_beam_mbps_but_keeps_its_cell_slot(
    api, agent_headers, netops_headers
):
    """Suspension empties the beam's sold total while the cell keeps the committed slot.

    PRD §2.8: "Only subscriptions whose `service_state` is `PENDING_ACTIVATION` or `ACTIVE` contribute to that sold total."
    PRD §2.8: "`SUSPENDED` and `TERMINATED` subscriptions contribute nothing — which is the asymmetry worth internalising: **a suspended subscription keeps its cell slot but releases its beam megabits.**"
    PRD §3.3: "The free slot figure is the cell's `max_active_terminals` less the number of subscriptions occupying slots less the number of orders in `RESERVED`, floored at 0 so it is never negative."
    PRD §3.3: "Otherwise it is `AVAILABLE` when the free slot figure is at least 1."
    PRD §3.9: "Hop one: the governing beam's `weighted_sold_mbps` drops by this subscription's weighted contribution, because a suspended subscription leaves the sold set entirely; the beam's `oversubscription_ratio` and `capacity_state` are recomputed and its `version` increases by 1."
    PRD §3.9: "What does **not** move is the cell's `committed_terminal_count` — a suspended subscription keeps its slot, so suspending a customer frees megabits but does not free a seat, and no waitlist promotion runs."

    Design: Corner/calculations/suspended_subscription_frees_beam_mbps_but_keeps_its_cell_slot
    """
    env = setup_active_subscription(
        clock=CLOCK_EPOCH,
        forward_capacity_mbps=100,
        oversubscription_limit=4.0,
        max_active_terminals=2,
        committed_rate_mbps=200,
        priority_tier="PRIORITY_1",
    )
    beam_before = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
    assert beam_before["weighted_sold_mbps"] == pytest.approx(200, abs=0.001), (
        "the live PRIORITY_1 subscription sells 200 Mbps before suspension, got "
        f"{beam_before['weighted_sold_mbps']}"
    )

    response = api.suspend_subscription(
        env["subscription"]["id"], {"suspend_reason": "non-payment hold"}, agent_headers
    )
    suspended = validate_success(response, 200)
    assert suspended["service_state"] == "SUSPENDED", (
        f"the provisioning dimension lands on SUSPENDED, got {suspended['service_state']}"
    )
    assert suspended["suspension_reason"] == "non-payment hold", (
        f"the supplied reason is recorded, got {suspended['suspension_reason']}"
    )

    beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
    assert beam["weighted_sold_mbps"] == pytest.approx(0, abs=0.001), (
        "a suspended subscription contributes nothing to the sold total, got "
        f"{beam['weighted_sold_mbps']}"
    )
    assert beam["oversubscription_ratio"] == pytest.approx(0, abs=0.001), (
        f"0 / 100 Mbps is a ratio of 0, got {beam['oversubscription_ratio']}"
    )
    assert beam["capacity_state"] == "NORMAL", (
        "a ratio of 0 is at or below three quarters of the 4.0 limit, got "
        f"{beam['capacity_state']}"
    )

    cell = validate_success(api.get_service_cell(env["cell"]["id"], netops_headers))
    assert cell["committed_terminal_count"] == 1, (
        "the suspended service still holds its cell slot, got "
        f"{cell['committed_terminal_count']}"
    )
    assert cell["reserved_slot_count"] == 0, (
        "the reservation became a commitment at activation, got "
        f"{cell['reserved_slot_count']}"
    )
    assert cell["free_slot_count"] == 1, (
        "2 slots less 1 commitment less 0 reservations leaves 1 free, got "
        f"{cell['free_slot_count']}"
    )
    assert cell["availability_state"] == "AVAILABLE", (
        f"one free slot advertises AVAILABLE, got {cell['availability_state']}"
    )
