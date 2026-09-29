"""Two reversals that must restore a conserved quantity to the exact cent or unit."""

from test_helpers import (
    ApiErrorId,
    assert_capital_conserved,
    assert_committed_matches_approved_plans,
    assert_instant_equals,
    assert_running_balance_replays,
    assert_two_decimals,
    assert_wear_ledger_conserved,
    factories,
    fixtures,
    validate_error,
)


def _confirmed_evening_game(client, roster, field_id, day):
    """A ninety-minute forty-strong evening game, confirmed at the default clock."""
    booking = fixtures.request_booking(
        client,
        roster,
        field_id,
        activity_type="GAME",
        window_start_utc=f"{day}T19:00:00Z",
        window_end_utc=f"{day}T20:30:00Z",
        expected_participant_count=40,
    )
    return fixtures.confirm_booking(client, roster, booking["id"])


class TestRainOutRelief:
    def test_the_relief_entry_returns_cumulative_wear_to_the_exact_unit(
        self, client, roster
    ):
        """Nothing is deleted; a second, opposite entry does the work.

        "`CONFIRMED → RAINED_OUT` computes `wear_load_units` and
        `rest_requirement_hours` exactly as `PLAYED` does and appends exactly the same
        `PLAY_WEAR` entry — and then immediately appends a second, compensating entry
        with `entry_type` `RAIN_OUT_RELIEF` whose `wear_units_delta` is the exact
        negative of that wear, whose `rest_requirement_hours` is 0.00 and whose
        `rest_credit_hours` is 0.00."

        "Sanctioned rain-out policy does not charge the tenant's wear allocation, so
        the two entries sum to exactly 0.00 and `Field.cumulative_wear_units` returns
        to precisely its pre-close-out value."

        "The **rest obligation from the `PLAY_WEAR` entry stands**, however — a wet
        surface still needs its rest window, whether or not anybody played on it — so
        `rest_debt_hours` rises even though cumulative wear did not, and the field can
        go `OPEN → RESTRICTED` on the strength of a fixture that never happened."

        "`usage_hours_ytd` still increases by `actual_duration_hours`, and
        `Field.version` increments by 1."

        Design: Difficulty/compensating_invariant/rain_out_relief_entry_restores_cumulative_wear_units_exactly
        """
        field = fixtures.register_grass_practice_3(client, roster)
        assert_two_decimals(
            field["cumulative_wear_units"], 0.00, "Field.cumulative_wear_units"
        )
        booking = _confirmed_evening_game(client, roster, field["id"], "2026-08-02")

        fixtures.set_clock(client, roster, "2026-08-02T20:30:00Z")
        closed = fixtures.close_out_booking(
            client,
            roster,
            booking["id"],
            outcome="RAINED_OUT",
            actual_duration_hours=1.50,
            actual_participant_count=40,
            weather_condition="WET",
        )
        assert closed["status"] == "RAINED_OUT"
        # 1.50 h x 1.50 game weight x a crowd factor of 1.00 at the free allowance
        # x 1.20 grass x 1.35 wet, rounded once.
        assert_two_decimals(closed["wear_load_units"], 3.65, "wear_load_units")
        # 3.65 units in the first tier at 0.50 hours each, plus the 2.00-hour wet
        # surcharge a natural surface attracts.
        assert_two_decimals(
            closed["rest_requirement_hours"], 3.83, "rest_requirement_hours"
        )

        entries = fixtures.list_ledger_entries(client, roster, booking_id=booking["id"])
        assert len(entries) == 2, "the charge is retained alongside its reversal"
        charge, relief = entries[0], entries[1]
        assert charge["entry_type"] == "PLAY_WEAR"
        assert_two_decimals(charge["wear_units_delta"], 3.65, "PLAY_WEAR delta")
        assert_two_decimals(
            charge["running_balance_after"], 3.65, "PLAY_WEAR running_balance_after"
        )
        assert_two_decimals(
            charge["rest_requirement_hours"], 3.83, "PLAY_WEAR rest_requirement_hours"
        )
        assert_instant_equals(
            charge["rest_window_end_utc"],
            "2026-08-03T00:19:48Z",
            "PLAY_WEAR rest_window_end_utc",
        )

        assert relief["entry_type"] == "RAIN_OUT_RELIEF"
        assert_two_decimals(
            relief["wear_units_delta"], -3.65, "RAIN_OUT_RELIEF delta"
        )
        assert_two_decimals(
            relief["running_balance_after"],
            0.00,
            "RAIN_OUT_RELIEF running_balance_after",
        )
        assert_two_decimals(
            relief["rest_requirement_hours"],
            0.00,
            "RAIN_OUT_RELIEF rest_requirement_hours",
        )
        assert_two_decimals(
            relief["rest_credit_hours"], 0.00, "RAIN_OUT_RELIEF rest_credit_hours"
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            after["cumulative_wear_units"], 0.00, "Field.cumulative_wear_units"
        )
        assert_wear_ledger_conserved(after, entries)
        assert_running_balance_replays(entries)

        # The rest obligation is not part of the reversal.
        assert_two_decimals(after["rest_debt_hours"], 3.83, "Field.rest_debt_hours")
        assert after["play_status"] == "RESTRICTED"
        # Nor are the hours booked.
        assert_two_decimals(after["usage_hours_ytd"], 1.50, "Field.usage_hours_ytd")

    def test_the_relief_restores_whatever_balance_was_standing_before_it(
        self, client, roster
    ):
        """The reversal is relative, not a reset to zero.

        "`CONFIRMED → PLAYED` appends a single `UsageLedgerEntry` with `entry_type`
        `PLAY_WEAR`, carrying `wear_units_delta` equal to the positive
        `wear_load_units`, the booking's `rest_requirement_hours`, and a
        `rest_window_end_utc` equal to the booking's `window_end_utc` advanced by
        those rest hours."

        "Sanctioned rain-out policy does not charge the tenant's wear allocation, so
        the two entries sum to exactly 0.00 and `Field.cumulative_wear_units` returns
        to precisely its pre-close-out value."

        "`Field.cumulative_wear_units` must always equal the sum of `wear_units_delta`
        over every `UsageLedgerEntry` whose `field_id` is that field, rounded half up
        to two decimal places, with no status filter of any kind — ledger entries are
        immutable, are never deleted and are never amended."

        "Each entry records `running_balance_after`, the value of
        `Field.cumulative_wear_units` immediately after that entry was applied;
        replaying a field's ledger in order of `effective_at_utc` ascending and then
        `created_at` ascending must reproduce that column exactly."

        Design: Difficulty/compensating_invariant/rain_out_relief_entry_restores_cumulative_wear_units_exactly
        """
        field = fixtures.register_grass_practice_3(client, roster)
        played = _confirmed_evening_game(client, roster, field["id"], "2026-08-02")
        washed_out = _confirmed_evening_game(client, roster, field["id"], "2026-08-04")

        fixtures.set_clock(client, roster, "2026-08-02T20:30:00Z")
        first = fixtures.close_out_booking(
            client,
            roster,
            played["id"],
            outcome="PLAYED",
            actual_duration_hours=1.50,
            actual_participant_count=40,
            weather_condition="WET",
        )
        assert first["status"] == "PLAYED"
        assert_two_decimals(first["wear_load_units"], 3.65, "played wear_load_units")
        standing = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            standing["cumulative_wear_units"], 3.65, "the balance before the rain-out"
        )

        fixtures.set_clock(client, roster, "2026-08-04T20:30:00Z")
        second = fixtures.close_out_booking(
            client,
            roster,
            washed_out["id"],
            outcome="RAINED_OUT",
            actual_duration_hours=1.50,
            actual_participant_count=40,
            weather_condition="WET",
        )
        assert second["status"] == "RAINED_OUT"
        assert_two_decimals(second["wear_load_units"], 3.65, "rained-out wear_load_units")

        entries = fixtures.list_ledger_entries(client, roster, field_id=field["id"])
        assert len(entries) == 3
        assert [e["entry_type"] for e in entries] == [
            "PLAY_WEAR",
            "PLAY_WEAR",
            "RAIN_OUT_RELIEF",
        ]
        # The charge climbed to 7.30 before the relief brought it back down.
        assert_two_decimals(
            entries[1]["running_balance_after"], 7.30, "second PLAY_WEAR balance"
        )
        assert_two_decimals(
            entries[2]["running_balance_after"], 3.65, "balance after the relief"
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            after["cumulative_wear_units"],
            3.65,
            "the rain-out restored the standing balance, not zero",
        )
        assert_wear_ledger_conserved(after, entries)
        assert_running_balance_replays(entries)
        # Both fixtures still cost their hours.
        assert_two_decimals(after["usage_hours_ytd"], 3.00, "Field.usage_hours_ytd")
        assert_two_decimals(after["rest_debt_hours"], 3.83, "Field.rest_debt_hours")


class TestPlanRescissionReleasesCapital:
    def _approved_plan_with_a_deferred_sibling(self, client, full_roster):
        """Commit exactly the lock threshold and let the cascade defer a sibling."""
        synthetic = fixtures.register_synthetic_stadium_1(client, full_roster)
        grass = fixtures.register_grass_practice_3(client, full_roster)
        budget = fixtures.authorize_budget(client, full_roster)

        main = fixtures.draft_plan(
            client,
            full_roster,
            synthetic["id"],
            budget["id"],
            synthetic["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )
        sibling = fixtures.draft_plan(
            client,
            full_roster,
            grass["id"],
            budget["id"],
            grass["version"],
            target_surface_type="NATURAL_GRASS",
            area_sq_ft=60000,
            priority_basis="REMAINING_LIFE",
            planned_install_year=2029,
        )
        fixtures.submit_plan(client, full_roster, main["id"])
        fixtures.decide_plan(client, full_roster, main["id"], decision="APPROVE")
        return synthetic, budget, main, sibling

    def test_a_rescission_puts_every_cent_and_every_consequence_back(
        self, client, full_roster
    ):
        """The reversal is arithmetic plus the two derived effects of the approval.

        "For every `CapitalBudget`, `available_amount_cents` plus
        `committed_amount_cents` must always equal `total_authorized_amount_cents`,
        and `committed_amount_cents` must always equal the sum of
        `plan_funding_amount_cents` over the plans on that budget whose
        `funding_status` is `APPROVED`."

        "An approval followed by a rescission of the same plan therefore leaves all
        three amounts exactly where they were before the approval."

        "If that release drops `committed_amount_cents` back below
        `lock_threshold_amount_cents`, the budget moves `LOCKED → OPEN`, and every
        plan on that budget whose `funding_status` is `DEFERRED` moves `DEFERRED →
        DRAFT` and becomes submittable again."

        "`Field.open_replacement_plan_count` decrements by 1 and `Field.version`
        increments by 1."

        Design: Difficulty/compensating_invariant/plan_rescission_releases_committed_capital_and_unlocks_budget
        """
        synthetic, budget, main, sibling = self._approved_plan_with_a_deferred_sibling(
            client, full_roster
        )

        before = fixtures.read_budget(client, full_roster, budget["id"])
        assert before["committed_amount_cents"] == 5243000
        assert before["available_amount_cents"] == 582556
        assert before["status"] == "LOCKED"
        assert (
            fixtures.read_plan(client, full_roster, sibling["id"])["funding_status"]
            == "DEFERRED"
        )

        rescinded = fixtures.decide_plan(
            client,
            full_roster,
            main["id"],
            decision="RESCIND",
            decision_notes="Capital deferred to the following biennium.",
        )
        assert rescinded["funding_status"] == "RESCINDED"
        assert rescinded["disposal_status"] == "NOT_APPLICABLE"
        assert rescinded["plan_funding_amount_cents"] == 5243000

        after = fixtures.read_budget(client, full_roster, budget["id"])
        assert after["committed_amount_cents"] == 0
        assert after["available_amount_cents"] == 5825556
        assert after["total_authorized_amount_cents"] == 5825556
        assert_capital_conserved(after)
        # The threshold is a property of the authorisation, not of the round trip.
        assert after["lock_threshold_amount_cents"] == 5243000
        assert after["status"] == "OPEN"

        plans = fixtures.list_plans(client, full_roster, capital_budget_id=budget["id"])
        assert_committed_matches_approved_plans(after, plans)

        undeferred = fixtures.read_plan(client, full_roster, sibling["id"])
        assert undeferred["funding_status"] == "DRAFT"
        assert undeferred["plan_funding_amount_cents"] == 1452000

        retired_nothing = fixtures.read_field(client, full_roster, synthetic["id"])
        assert retired_nothing["open_replacement_plan_count"] == 0
        assert retired_nothing.get("retired_at") is None
        assert retired_nothing["play_status"] == "OPEN"

    def test_the_released_capital_is_genuinely_spendable_again(
        self, client, full_roster
    ):
        """Releasing the money is only proved by committing it a second time.

        "`RESCIND` is the compensating action and requires `funding_status` to be
        `APPROVED` and `disposal_status` to be anything other than `COMPLETED`; a plan
        that is not approved, or whose disposal has already completed, is refused with
        `ERR_PLAN_NOT_APPROVED`."

        "then that `plan_funding_amount_cents` does not exceed the budget's
        `available_amount_cents`, refusing with `ERR_BUDGET_INSUFFICIENT`."

        "Hop four is the consequence of that lock — **every other** plan on the same
        `capital_budget_id` whose `funding_status` is `DRAFT` moves `DRAFT →
        DEFERRED`, visited in order of `replacement_priority_score` descending and
        then `created_at` ascending — and a deferred plan can no longer be submitted
        until its budget reopens."

        Design: Difficulty/compensating_invariant/plan_rescission_releases_committed_capital_and_unlocks_budget
        """
        synthetic, budget, main, sibling = self._approved_plan_with_a_deferred_sibling(
            client, full_roster
        )
        fixtures.decide_plan(client, full_roster, main["id"], decision="RESCIND")

        # `RESCINDED` is terminal, so the release cannot be replayed.
        validate_error(
            client.decide_replacement_plan(
                main["id"],
                factories.make_plan_decide_payload(
                    decision="RESCIND",
                    decided_by_staff_member_id=full_roster.id_of("director_two"),
                ),
                full_roster.headers_of("director_two"),
            ),
            ApiErrorId.PLAN_NOT_APPROVED,
            409,
        )
        held = fixtures.read_budget(client, full_roster, budget["id"])
        assert held["committed_amount_cents"] == 0
        assert held["available_amount_cents"] == 5825556

        # The same money buys the same replacement all over again.
        refreshed = fixtures.read_field(client, full_roster, synthetic["id"])
        second_attempt = fixtures.draft_plan(
            client,
            full_roster,
            synthetic["id"],
            budget["id"],
            refreshed["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2029,
        )
        assert second_attempt["plan_funding_amount_cents"] == 5243000
        fixtures.submit_plan(client, full_roster, second_attempt["id"])
        approved = fixtures.decide_plan(
            client, full_roster, second_attempt["id"], decision="APPROVE"
        )
        assert approved["funding_status"] == "APPROVED"

        relocked = fixtures.read_budget(client, full_roster, budget["id"])
        assert relocked["committed_amount_cents"] == 5243000
        assert relocked["available_amount_cents"] == 582556
        assert relocked["status"] == "LOCKED"
        assert_capital_conserved(relocked)
        plans = fixtures.list_plans(
            client, full_roster, capital_budget_id=budget["id"]
        )
        assert_committed_matches_approved_plans(relocked, plans)

        # And the sibling, undeferred by the rescission, is deferred once more.
        assert (
            fixtures.read_plan(client, full_roster, sibling["id"])["funding_status"]
            == "DEFERRED"
        )
