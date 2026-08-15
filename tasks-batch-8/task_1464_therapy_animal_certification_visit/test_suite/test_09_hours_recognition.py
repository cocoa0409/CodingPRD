"""Volunteer hour ledger: PROVISIONAL/FINAL variants, pinned rounding order,
verification reconciliation, recognition tiers, deemed verification."""
import pytest

from test_helpers import (
    assert_ledger_consistency,
    check_in_visit_ok,
    check_out_visit_ok,
    complete_visit_ok,
    get_handler,
    get_recognition,
    get_visit,
    list_hour_credits_for,
    run_sweeps,
    schedule_visit_ok,
    seed_lifetime,
    set_clock,
    setup_certified_team_at_facility,
    verify_visit_ok,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _bookable_ctx(name: str, weekly_cap: int = 5):
    return setup_certified_team_at_facility(
        team_kwargs={"handler_name": name, "team_name": f"{name} Team"},
        facility_kwargs={"name": f"School {name}", "visits_per_week_cap": weekly_cap},
        # facility cap 60, agreement cap 90 -> effective cap 60 minutes.
    )


class TestProvisionalVsFinalReconciliation:
    def test_checkout_posts_provisional_at_scheduled_minutes(self):
        """PRD §3.7: "It then posts the provisional hour credit — a `PROVISIONAL` row equal to the scheduled minutes regardless of how long the visit actually ran — and recomputes the handler's `lifetime_minutes` and `recognition_tier`."
        PRD §2.10: "Whole-quantity extractions floor toward zero: a visit's `actual_minutes` is the elapsed seconds between check-in and check-out divided by sixty and floored to whole minutes; late-cancel notice, volunteer tenure years, recency weeks, and workload-penalty ten-minute blocks all floor to whole units before thresholds apply."

        Design: Difficulty/dual_variant_calc/visit_credit_provisional_vs_final_reconciliation
        """
        ctx = _bookable_ctx("H One")
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        check_in_visit_ok(visit["id"], ctx["handler"]["id"], "2026-08-03T10:00:00Z")
        completed = check_out_visit_ok(visit["id"], ctx["handler"]["id"],
                                       "2026-08-03T10:45:00Z")
        assert completed["actual_minutes"] == 45, (
            "actual_minutes is elapsed seconds floored to whole minutes"
        )
        handler = get_handler(ctx["handler"]["id"])
        # PROVISIONAL variant: credit = scheduled 60, actual 45 ignored.
        assert handler["lifetime_minutes"] == 60, (
            f"PROVISIONAL credit must equal the scheduled minutes, got {handler['lifetime_minutes']}"
        )

    def test_verify_reconciles_to_exactly_the_final_amount(self):
        """PRD §2.9: "A completed visit first earns an optimistic `PROVISIONAL` credit; verification replaces it by posting a `REVERSAL` row that exactly negates the provisional amount followed by the definitive `FINAL` row, so the net effect of the full cycle on the handler's lifetime total equals the final amount."
        PRD §3.8: "the credit is reconciled in two postings — a `REVERSAL` row negating the provisional amount, then a `FINAL` row computed as the smallest of the visit's `actual_minutes`, its scheduled minutes, and the effective cap in minutes, divided by fifteen, rounded half-up to the nearest whole unit, and multiplied by fifteen."

        Design: Difficulty/dual_variant_calc/visit_credit_provisional_vs_final_reconciliation
        """
        ctx = _bookable_ctx("H OneV")
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        complete_visit_ok(visit["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T10:45:00Z")
        set_clock("2026-08-03T12:00:00Z")  # distinct ledger timestamps
        verified = verify_visit_ok(visit["id"], ctx["facility"]["id"])
        assert verified["verification_status"] == "VERIFIED"
        handler = get_handler(ctx["handler"]["id"])
        # FINAL = round_half_up(min(45, 60, 60) / 15) * 15 = 45.
        assert handler["lifetime_minutes"] == 45, (
            f"Net lifetime after verification must equal the FINAL amount, got {handler['lifetime_minutes']}"
        )
        rows = list_hour_credits_for(visit_id=visit["id"])
        assert [row["kind"] for row in rows] == ["PROVISIONAL", "REVERSAL", "FINAL"]
        assert [row["minutes"] for row in rows] == [60, -60, 45]


class TestPerCreditRoundingPinned:
    def _two_short_visits_verified(self):
        ctx = _bookable_ctx("H R")
        v1 = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                               "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        v2 = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                               "2026-08-03T11:30:00Z", "2026-08-03T12:00:00Z")
        # Each visit actually runs 8 minutes; the clock moves between check-out
        # and verify so the ledger rows get strictly ordered created_at values.
        complete_visit_ok(v1["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T10:08:00Z")
        set_clock("2026-08-03T10:20:00Z")
        verify_visit_ok(v1["id"], ctx["facility"]["id"])
        complete_visit_ok(v2["id"], ctx["handler"]["id"],
                          "2026-08-03T11:30:00Z", "2026-08-03T11:38:00Z")
        set_clock("2026-08-03T11:50:00Z")
        verify_visit_ok(v2["id"], ctx["facility"]["id"])
        return ctx, v1, v2

    def test_rounding_applied_per_credit_before_summation(self):
        """PRD §2.9: "Rounding order is pinned: each `FINAL` credit is rounded to whole fifteen-minute units at posting time, and the lifetime total then sums the already-rounded entries; summing raw durations and rounding once at the end is not the same calculation and is not used."
        PRD §3.8: "the credit is reconciled in two postings — a `REVERSAL` row negating the provisional amount, then a `FINAL` row computed as the smallest of the visit's `actual_minutes`, its scheduled minutes, and the effective cap in minutes, divided by fifteen, rounded half-up to the nearest whole unit, and multiplied by fifteen."

        Design: Difficulty/combinatorial_formula/recognition_per_credit_rounding_pinned
        """
        ctx, _v1, _v2 = self._two_short_visits_verified()
        summary = get_recognition(ctx["handler"]["id"])
        # Per-credit: round_half_up(8/15)*15 = 15 twice -> 30. Sum-then-round
        # would wrongly yield round_half_up(16/15)*15 = 15.
        assert summary["lifetime_minutes"] == 30
        assert summary["recognition_tier"] == "NONE", "30 minutes is below BRONZE (1500)"

    def test_each_visit_posts_its_own_rounded_final(self):
        """PRD §2.9: "Rounding order is pinned: each `FINAL` credit is rounded to whole fifteen-minute units at posting time, and the lifetime total then sums the already-rounded entries; summing raw durations and rounding once at the end is not the same calculation and is not used."
        PRD §2.9: "Each row records its `kind` — `PROVISIONAL`, `FINAL`, `REVERSAL`, or `ADJUSTMENT` — and a signed `minutes` amount: provisional and final rows are positive, reversal rows negative, and adjustment rows may carry either sign."

        Design: Difficulty/combinatorial_formula/recognition_per_credit_rounding_pinned
        """
        _ctx, v1, v2 = self._two_short_visits_verified()
        for visit in (v1, v2):
            rows = list_hour_credits_for(visit_id=visit["id"])
            assert [row["kind"] for row in rows] == ["PROVISIONAL", "REVERSAL", "FINAL"]
            assert [row["minutes"] for row in rows] == [30, -30, 15], (
                "Each 8-actual-minute visit posts its own FINAL rounded to 15"
            )


class TestRecognitionTierThreshold:
    def _seeded_ctx(self):
        ctx = _bookable_ctx("H B3")
        seed_lifetime(ctx["handler"]["id"], 5985)
        return ctx

    def test_one_minute_below_silver_floor(self):
        """PRD §3.8: "The handler's `lifetime_minutes` — the floored algebraic sum over `PROVISIONAL`, `FINAL`, `REVERSAL`, and `ADJUSTMENT` rows alike — maps to the highest `recognition_tier` whose threshold it meets: `NONE` below fifteen hundred minutes, `BRONZE` at fifteen hundred, `SILVER` at six thousand, `GOLD` at fifteen thousand, and `PLATINUM` at thirty thousand, each threshold inclusive at the exact boundary."
        PRD §3.8: "The recognition summary for a handler reports the `handler_id`, the `lifetime_minutes`, the derived `lifetime_hours` — minutes divided by sixty and displayed to two decimal places, rounded half-up — the current `recognition_tier`, the `next_tier` naming the next higher tier, and `minutes_to_next_tier` giving the additional lifetime minutes needed to reach it."

        Design: Difficulty/boundary_precision_check/recognition_tier_exact_threshold
        """
        ctx = self._seeded_ctx()
        summary = get_recognition(ctx["handler"]["id"])
        assert summary["lifetime_minutes"] == 5985
        # 5985 >= 1500 meets BRONZE but not SILVER (6000).
        assert summary["recognition_tier"] == "BRONZE"
        assert summary["next_tier"] == "SILVER"
        assert summary["minutes_to_next_tier"] == 15

    def test_exact_threshold_is_inclusive_after_reconciliation(self):
        """PRD §3.8: "The handler's `lifetime_minutes` — the floored algebraic sum over `PROVISIONAL`, `FINAL`, `REVERSAL`, and `ADJUSTMENT` rows alike — maps to the highest `recognition_tier` whose threshold it meets: `NONE` below fifteen hundred minutes, `BRONZE` at fifteen hundred, `SILVER` at six thousand, `GOLD` at fifteen thousand, and `PLATINUM` at thirty thousand, each threshold inclusive at the exact boundary."
        PRD §2.9: "A completed visit first earns an optimistic `PROVISIONAL` credit; verification replaces it by posting a `REVERSAL` row that exactly negates the provisional amount followed by the definitive `FINAL` row, so the net effect of the full cycle on the handler's lifetime total equals the final amount."

        Design: Difficulty/boundary_precision_check/recognition_tier_exact_threshold
        """
        ctx = self._seeded_ctx()
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        check_in_visit_ok(visit["id"], ctx["handler"]["id"], "2026-08-03T10:00:00Z")
        check_out_visit_ok(visit["id"], ctx["handler"]["id"], "2026-08-03T10:08:00Z")
        mid = get_recognition(ctx["handler"]["id"])
        # PROVISIONAL +30 inflates the total before verification.
        assert mid["lifetime_minutes"] == 6015
        assert mid["recognition_tier"] == "SILVER"
        set_clock("2026-08-03T12:00:00Z")
        verify_visit_ok(visit["id"], ctx["facility"]["id"])
        end = get_recognition(ctx["handler"]["id"])
        # REVERSAL -30 then FINAL round_half_up(8/15)*15 = 15 -> exactly 6000.
        assert end["lifetime_minutes"] == 6000
        assert end["recognition_tier"] == "SILVER", (
            "Exactly 6000 meets the SILVER threshold (inclusive)"
        )
        assert end["lifetime_hours"] == pytest.approx(100.0)


class TestProvisionalCycleNetsToFinal:
    def _seeded_cycle(self):
        ctx = _bookable_ctx("H V1")
        seed_lifetime(ctx["handler"]["id"], 100)
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        complete_visit_ok(visit["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T10:45:00Z")
        return ctx, visit

    def test_lifetime_mid_and_end_of_cycle(self):
        """PRD §2.9: "A completed visit first earns an optimistic `PROVISIONAL` credit; verification replaces it by posting a `REVERSAL` row that exactly negates the provisional amount followed by the definitive `FINAL` row, so the net effect of the full cycle on the handler's lifetime total equals the final amount."
        PRD §2.9: "The handler's `lifetime_minutes` is the algebraic sum over all of the handler's ledger rows, floored at zero — a posting that would drive the total below zero is rejected with `ERR_INVALID_ADJUSTMENT`."

        Design: Difficulty/compensating_invariant/provisional_cycle_nets_to_final
        """
        ctx, visit = self._seeded_cycle()
        mid = get_handler(ctx["handler"]["id"])
        assert mid["lifetime_minutes"] == 160, "seed 100 + PROVISIONAL 60"
        set_clock("2026-08-03T12:00:00Z")
        verify_visit_ok(visit["id"], ctx["facility"]["id"])
        end = get_handler(ctx["handler"]["id"])
        # FINAL = round_half_up(min(45, 60, 60)/15)*15 = 45; 100 + 45 = 145.
        assert end["lifetime_minutes"] == 145, (
            "PROVISIONAL +60 and REVERSAL -60 net to zero — no provisional residue"
        )

    def test_ledger_sum_equals_derived_lifetime(self):
        """PRD §2.9: "Volunteer time is accounted in an append-only ledger of hour-credit rows rather than by overwriting balances. Each row records its `kind` — `PROVISIONAL`, `FINAL`, `REVERSAL`, or `ADJUSTMENT` — and a signed `minutes` amount: provisional and final rows are positive, reversal rows negative, and adjustment rows may carry either sign."
        PRD §2.9: "The handler's `lifetime_minutes` is the algebraic sum over all of the handler's ledger rows, floored at zero — a posting that would drive the total below zero is rejected with `ERR_INVALID_ADJUSTMENT`."

        Design: Difficulty/compensating_invariant/provisional_cycle_nets_to_final
        """
        ctx, visit = self._seeded_cycle()
        set_clock("2026-08-03T12:00:00Z")
        verify_visit_ok(visit["id"], ctx["facility"]["id"])
        rows = list_hour_credits_for(handler_id=ctx["handler"]["id"])
        assert [row["kind"] for row in rows] == [
            "ADJUSTMENT", "PROVISIONAL", "REVERSAL", "FINAL",
        ]
        assert [row["minutes"] for row in rows] == [100, 60, -60, 45]
        handler = get_handler(ctx["handler"]["id"])
        assert_ledger_consistency(rows, handler["lifetime_minutes"])
        assert handler["lifetime_minutes"] == 145


class TestDeemedVerified:
    def test_deemed_verified_posts_final_credit(self):
        """PRD §3.8: "Silence resolves in the volunteer's favor by default: a completed visit left `UNVERIFIED` more than fourteen days past `actual_end` is deemed verified by the sweep, running the same reconciliation from `actual_minutes`."
        PRD §2.9: "A completed visit first earns an optimistic `PROVISIONAL` credit; verification replaces it by posting a `REVERSAL` row that exactly negates the provisional amount followed by the definitive `FINAL` row, so the net effect of the full cycle on the handler's lifetime total equals the final amount."

        Design: Corner/state_machines/deemed_verified_posts_final_credit
        """
        ctx = _bookable_ctx("H DV")
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        complete_visit_ok(visit["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        # actual_end 2026-08-03T11:00Z; +14 days = 2026-08-17T11:00Z.
        set_clock("2026-08-17T11:00:01Z")
        sweep = run_sweeps()
        assert sweep["visits_deemed_verified"] == 1
        fetched = get_visit(visit["id"])
        assert fetched["verification_status"] == "VERIFIED"
        handler = get_handler(ctx["handler"]["id"])
        # PROVISIONAL 60 reversed once; FINAL round_half_up(min(60,60,60)/15)*15 = 60.
        assert handler["lifetime_minutes"] == 60, (
            f"Deemed verification reconciles to the FINAL amount exactly once, got {handler['lifetime_minutes']}"
        )
