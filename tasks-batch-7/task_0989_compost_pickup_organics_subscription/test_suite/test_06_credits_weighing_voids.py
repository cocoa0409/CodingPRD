"""The credit ledger: estimated vs weighed diversion credit variants, the
weigh-ticket cascade, voids, manual adjustments, and balance reconciliation.

Covers PRD §2.6 (ledger), §2.9 (seasons), §3.4 (estimated credit), §3.7
(weigh tickets and reconciliation), §3.8 (adjustments).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_ledger_sum_matches_balance,
    complete_pickup,
    create_bins,
    create_plan_res,
    create_route,
    create_subscriber,
    create_subscription,
    generate_and_get_pickups,
    get_bin,
    get_pickup,
    get_subscriber,
    list_credit_entries,
    post_credit_adjustment,
    post_weigh_ticket,
    setup_active_subscription,
    setup_completed_pickup,
    setup_weighed_pickup,
    validate_error,
    validate_success,
    void_pickup,
)


class TestDualVariantCredit:
    def _setup_two_pickups(self, api):
        """Two residential subscribers on one route; week 2026-06-01 (SUMMER).
        A completes at 0.5 (est 10.00 kg), B at 0.75 (est 15.00 kg)."""
        plan = create_plan_res()
        route = create_route()
        create_bins(4)
        sub_a = create_subscriber(email="a@x.com")
        sub_b = create_subscriber(email="b@x.com", full_name="Sub B", address="2 B St")
        subs_a = create_subscription(sub_a["id"], plan["id"], route["id"])
        subs_b = create_subscription(sub_b["id"], plan["id"], route["id"])
        pk_a = generate_and_get_pickups(route["id"], subs_a["id"], ["2026-06-01"])[0]
        pk_b = generate_and_get_pickups(route["id"], subs_b["id"], ["2026-06-01"])[0]
        complete_pickup(pk_a["id"], 0.5)
        complete_pickup(pk_b["id"], 0.75)
        return plan, route, sub_a, sub_b, pk_a, pk_b

    def test_estimated_variant_posts_provisional_credit(self, api):
        """PRD §3.4: "The pickup's `estimated_kg` is computed as the collected
        bin's `nominal_capacity_kg` multiplied by `fullness_pct`, rounded
        half-up to two decimal places." PRD §3.4: "an `EARNED_ESTIMATED` credit
        entry is created: the `estimated_kg` multiplied by the plan's
        `credit_rate_cents_per_kg` and by the seasonal multiplier of the
        service date, rounded half-up to integer cents, and the subscriber's
        `credit_balance_cents` rises by that amount."

        Design: Difficulty/dual_variant_calc/diversion_credit_estimated_vs_weighed
        """
        _, route, sub_a, sub_b, pk_a, pk_b = self._setup_two_pickups(api)
        pickup_a = get_pickup(pk_a["id"])
        pickup_b = get_pickup(pk_b["id"])
        assert pickup_a["estimated_kg"] == pytest.approx(10.0)
        assert pickup_b["estimated_kg"] == pytest.approx(15.0)
        assert get_subscriber(sub_a["id"])["credit_balance_cents"] == 120
        assert get_subscriber(sub_b["id"])["credit_balance_cents"] == 180

        # Weighed variant: net 20.00 kg allocated 8.00 / 12.00 by estimate share.
        post_weigh_ticket(route["id"], "2026-06-01", 25.0, 5.0)
        assert get_pickup(pk_a["id"])["final_kg"] == pytest.approx(8.0)
        assert get_pickup(pk_b["id"])["final_kg"] == pytest.approx(12.0)

    def test_weighed_variant_reconciles_ledger_with_adjustments(self, api):
        """PRD §3.7: "the delta between that final credit and the pickup's
        earlier `EARNED_ESTIMATED` amount is posted, whenever nonzero, as an
        `EARNED_FINAL_ADJUSTMENT` entry carrying the signed delta." PRD §3.7:
        "This weighed variant of the diversion credit replaces the driver's
        curb estimate with scale truth, which is why the same pickup data
        yields different cents before and after the ticket."

        Design: Difficulty/dual_variant_calc/diversion_credit_estimated_vs_weighed
        """
        _, route, sub_a, sub_b, pk_a, pk_b = self._setup_two_pickups(api)
        post_weigh_ticket(route["id"], "2026-06-01", 25.0, 5.0)

        entries_a = list_credit_entries(pickup_id=pk_a["id"])
        adj_a = [e for e in entries_a if e["entry_type"] == "EARNED_FINAL_ADJUSTMENT"]
        assert len(adj_a) == 1 and adj_a[0]["amount_cents"] == -24  # 96 - 120

        entries_b = list_credit_entries(pickup_id=pk_b["id"])
        adj_b = [e for e in entries_b if e["entry_type"] == "EARNED_FINAL_ADJUSTMENT"]
        assert len(adj_b) == 1 and adj_b[0]["amount_cents"] == -36  # 144 - 180

        bal_a = get_subscriber(sub_a["id"])["credit_balance_cents"]
        bal_b = get_subscriber(sub_b["id"])["credit_balance_cents"]
        assert bal_a == 96 and bal_b == 144
        assert_ledger_sum_matches_balance(
            list_credit_entries(subscriber_id=sub_a["id"]), bal_a
        )
        assert_ledger_sum_matches_balance(
            list_credit_entries(subscriber_id=sub_b["id"]), bal_b
        )


class TestWeighTicketCascade:
    def test_weigh_ticket_sets_final_kg(self, api):
        """PRD §3.7: "Each included pickup receives a `final_kg` equal to the
        ticket's `net_kg` multiplied by the pickup's own `estimated_kg` divided
        by the sum of `estimated_kg` across the whole set, rounded half-up to
        two decimal places." A single included pickup receives the whole net.

        Design: Difficulty/transitive_cascade/weigh_ticket_cascade_finalizes_pickups_entries_balances
        """
        env = setup_completed_pickup(service_date="2026-06-01", fullness_pct=0.5)
        post_weigh_ticket(env["route"]["id"], "2026-06-01", 17.0, 5.0)
        assert get_pickup(env["pickup"]["id"])["final_kg"] == pytest.approx(12.0)

    def test_weigh_ticket_reconciles_ledger_and_balance(self, api):
        """PRD §3.7: "the delta between that final credit and the pickup's
        earlier `EARNED_ESTIMATED` amount is posted, whenever nonzero, as an
        `EARNED_FINAL_ADJUSTMENT` entry carrying the signed delta. Every
        affected subscriber's `credit_balance_cents` is then recomputed as the
        sum of all their signed entries."

        Design: Difficulty/transitive_cascade/weigh_ticket_cascade_finalizes_pickups_entries_balances
        """
        env = setup_completed_pickup(service_date="2026-06-01", fullness_pct=0.5)
        post_weigh_ticket(env["route"]["id"], "2026-06-01", 17.0, 5.0)
        # final 12.00 kg x 10 x 1.2 = 144; delta over the 120 estimated = +24.
        entries = list_credit_entries(pickup_id=env["pickup"]["id"])
        adj = [e for e in entries if e["entry_type"] == "EARNED_FINAL_ADJUSTMENT"]
        assert len(adj) == 1 and adj[0]["amount_cents"] == 24
        balance = get_subscriber(env["subscriber"]["id"])["credit_balance_cents"]
        assert balance == 144
        assert_ledger_sum_matches_balance(
            list_credit_entries(subscriber_id=env["subscriber"]["id"]), balance
        )


class TestCompleteThenVoid:
    def test_complete_posts_estimated_credit(self, api):
        """PRD §3.4: "an `EARNED_ESTIMATED` credit entry is created: the
        `estimated_kg` multiplied by the plan's `credit_rate_cents_per_kg` and
        by the seasonal multiplier of the service date, rounded half-up to
        integer cents, and the subscriber's `credit_balance_cents` rises by
        that amount."

        Design: Difficulty/compensating_invariant/complete_then_void_nets_credit_balance_to_zero_drift
        """
        env = setup_completed_pickup(service_date="2026-06-01", fullness_pct=0.5)
        entries = list_credit_entries(pickup_id=env["pickup"]["id"])
        earned = [e for e in entries if e["entry_type"] == "EARNED_ESTIMATED"]
        assert len(earned) == 1 and earned[0]["amount_cents"] == 120
        assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 120

    def test_void_nets_balance_to_zero_drift(self, api):
        """PRD §3.7: "Voiding moves the pickup to `VOIDED` and posts a
        `REVERSAL` entry negating the pickup's `EARNED_ESTIMATED` amount, so a
        completion followed by a void nets the subscriber's balance to zero
        drift. The physical swap is deliberately not undone: the bins stay
        exactly as the completion left them."

        Design: Difficulty/compensating_invariant/complete_then_void_nets_credit_balance_to_zero_drift
        """
        env = setup_completed_pickup(service_date="2026-06-01", fullness_pct=0.5)
        pickup_id = env["pickup"]["id"]
        completed = env["completed"]
        void_pickup(pickup_id)

        assert get_pickup(pickup_id)["status"] == "VOIDED"
        entries = list_credit_entries(pickup_id=pickup_id)
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type["EARNED_ESTIMATED"] == 120
        assert by_type["REVERSAL"] == -120
        balance = get_subscriber(env["subscriber"]["id"])["credit_balance_cents"]
        assert balance == 0, "complete+void must net to zero drift"
        assert_ledger_sum_matches_balance(entries, balance)

        # The swap is not undone.
        collected = get_bin(completed["collected_bin_id"])
        replacement = get_bin(completed["replacement_bin_id"])
        assert (collected["status"], collected["condition"]) == ("IN_DEPOT", "NEEDS_WASH")
        assert replacement["status"] == "AT_CUSTOMER"


class TestWeighTicketRules:
    def test_duplicate_weigh_ticket_rejected(self, api, driver_headers):
        """PRD §3.7: "Only one ticket may exist for a given route and service
        date — a second posting is rejected with `ERR_DUPLICATE_WEIGH_TICKET` —
        and once created the ticket sits in `POSTED`, its only state: ticket
        posting is final."

        Design: Corner/validations/duplicate_weigh_ticket_returns_error
        """
        env = setup_weighed_pickup(
            service_date="2026-06-01", fullness_pct=0.5, gross_kg=25.0, tare_kg=5.0
        )
        assert env["pickup"]["final_kg"] == pytest.approx(20.0)
        resp = api.post_weigh_ticket(
            env["route"]["id"],
            {"service_date": "2026-06-01", "gross_kg": 30.0, "tare_kg": 5.0},
            driver_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WEIGH_TICKET)
        assert get_pickup(env["pickup"]["id"])["final_kg"] == pytest.approx(20.0)

    def test_nonpositive_net_weight_rejected(self, api, driver_headers):
        """PRD §3.7: "The ticket's `net_kg` is the gross minus the tare and
        must be greater than zero, otherwise the posting is rejected with
        `ERR_INVALID_WEIGHT`."

        Design: Corner/validations/weigh_ticket_nonpositive_net_returns_invalid_weight
        """
        env = setup_completed_pickup(service_date="2026-06-01", fullness_pct=0.5)
        resp = api.post_weigh_ticket(
            env["route"]["id"],
            {"service_date": "2026-06-01", "gross_kg": 5.0, "tare_kg": 5.0},
            driver_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT)
        assert get_pickup(env["pickup"]["id"]).get("final_kg") is None

    def test_void_after_weigh_ticket_locked(self, api, ops_headers):
        """PRD §3.7: "A completed pickup can still be voided by an
        `OperationsManager`, but only while no weigh ticket exists for its
        route and date — once the ticket is posted the void is rejected with
        `ERR_PICKUP_LOCKED_BY_WEIGH_TICKET`, and any other from-state is
        rejected with `ERR_PICKUP_NOT_ACTIONABLE`."

        Design: Corner/validations/void_after_weigh_ticket_returns_locked
        """
        env = setup_weighed_pickup(
            service_date="2026-06-01", fullness_pct=0.5, gross_kg=25.0, tare_kg=5.0
        )
        resp = api.void_pickup(env["pickup"]["id"], ops_headers)
        validate_error(resp, ApiErrorId.ERR_PICKUP_LOCKED_BY_WEIGH_TICKET)
        assert get_pickup(env["pickup"]["id"])["status"] == "COMPLETED"
        # Estimated 120 + adjustment round(20 x 10 x 1.2) - 120 = +120.
        assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 240


class TestSeasonalMultiplier:
    def test_season_changes_estimated_credit(self, api):
        """PRD §2.9: "The multipliers are 1.0 for `SPRING`, 1.2 for `SUMMER`,
        1.0 for `FALL`, and 0.8 for `WINTER`." PRD §2.9: "Wherever a credit is
        computed from kilograms — the estimated credit at completion and the
        weighed credit at ticket posting alike — the multiplier of the service
        date's season is applied before the final cent rounding, and the entry
        records the resulting `season` label."

        Design: Corner/calculations/seasonal_multiplier_changes_estimated_credit
        """
        env = setup_active_subscription(bin_count=3)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-05-04", "2026-06-01"]
        )
        complete_pickup(pickups[0]["id"], 0.5)
        complete_pickup(pickups[1]["id"], 0.5)

        spring = list_credit_entries(pickup_id=pickups[0]["id"])
        summer = list_credit_entries(pickup_id=pickups[1]["id"])
        assert spring[0]["entry_type"] == "EARNED_ESTIMATED"
        assert spring[0]["amount_cents"] == 100  # 10.00 x 10 x 1.0
        assert spring[0]["season"] == "2026-SPRING"
        assert summer[0]["amount_cents"] == 120  # 10.00 x 10 x 1.2
        assert summer[0]["season"] == "2026-SUMMER"
        assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 220


class TestCreditAdjustments:
    def test_negative_adjustment_below_zero_rejected(self, api, ops_headers):
        """PRD §3.8: "If the result would take the balance below zero, the
        adjustment is rejected with `ERR_INSUFFICIENT_CREDIT`."
        PRD §2.6: "The balance is never allowed to go negative: a manual
        adjustment that would push `credit_balance_cents` below zero is
        rejected with `ERR_INSUFFICIENT_CREDIT`."

        Design: Corner/validations/negative_adjustment_below_zero_returns_insufficient_credit
        """
        sub = create_subscriber()
        resp = api.create_credit_adjustment(
            sub["id"], {"amount_cents": -100, "reason": "clawback"}, ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)
        assert get_subscriber(sub["id"])["credit_balance_cents"] == 0

    def test_balance_reconciles_with_ledger(self, api):
        """PRD §2.6: "the subscriber's `credit_balance_cents` is, at all times,
        exactly the sum of the signed `amount_cents` values across all of that
        subscriber's entries." PRD §2.6: "Only `MANUAL_ADJUSTMENT` takes its
        `amount_cents` from client input, accompanied by an operator `reason`;
        every other entry's amount is computed by the system."

        Design: Corner/complexity_layers/derived_credit_balance_reconciles_with_ledger
        """
        sub = create_subscriber()
        post_credit_adjustment(sub["id"], 250, reason="promo")
        assert get_subscriber(sub["id"])["credit_balance_cents"] == 250
        entries = list_credit_entries(subscriber_id=sub["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "MANUAL_ADJUSTMENT"
        assert entry["amount_cents"] == 250
        assert entry.get("reason") == "promo"
        # The logical clock sits at 2026-05-01, which is SPRING (PRD §2.9).
        assert entry["season"] == "2026-SPRING"
        assert_ledger_sum_matches_balance(entries, 250)
