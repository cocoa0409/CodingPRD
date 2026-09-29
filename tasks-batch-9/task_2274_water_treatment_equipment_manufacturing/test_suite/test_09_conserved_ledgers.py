"""Compensating entries that must restore a conserved ledger to the cent and the minute."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    assert_append_only_fields,
    assert_bay_ledger,
    assert_money,
    assert_reserve_conserved,
    assert_skid_state,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
    make_fabrication_manager_headers,
)


class TestDrawReversalRestoresTheReserveExactly:
    """A reversal is the exact integer negation of the row it compensates."""

    REVERSAL_REASON = "Elements returned unopened to the vendor"

    def _reversed_draw(self, api):
        state = fixtures.service_active_project(api)
        state["draw"] = fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            quantity=3,
            catalog_unit_cost_cents=500000,
            invoiced_unit_cost_cents=480000,
        )
        state["reversal"] = validate_success(
            api.reverse_consumable_draw(
                state["draw"]["id"],
                make_contracts_administrator_headers(),
                {"reversal_reason": self.REVERSAL_REASON},
            ),
            201,
        )
        return state

    def test_the_reversal_row_negates_both_money_lines_of_its_target(self, api):
        """The compensating row carries minus 1,830,000 accrual and minus 1,533,600 settled.

        A reversal is "a new row with `draw_type` `REVERSAL`, `reverses_draw_id`
        pointing at the target, the target's `quantity`, `catalog_unit_cost_cents` and
        `invoiced_unit_cost_cents` copied across, and `accrual_amount_cents` and
        `settled_amount_cents` equal to the exact negations of the target's amounts."
        A draw row carries only `id` and `created_at` because "both `updated_at` and
        `version` are **absent** from a consumable draw -- not null, absent."

        Design: Difficulty/compensating_invariant/draw_reversal_restores_reserve_money_exactly
        """
        state = self._reversed_draw(api)

        reversal = state["reversal"]
        assert reversal["reverses_draw_id"] == state["draw"]["id"]
        assert reversal["draw_type"] == "REVERSAL"
        assert_money(reversal["accrual_amount_cents"], -1830000, "accrual_amount_cents")
        assert_money(reversal["settled_amount_cents"], -1533600, "settled_amount_cents")
        assert_append_only_fields(reversal)

    def test_the_agreement_returns_to_its_exact_pre_draw_position(self, api):
        """Both reserve figures return to their pre-draw values and the agreement stays ACTIVE.

        Section 2.11 pins that "for any forward draw followed by its reversal, both
        `reserve_available_cents` and `reserve_committed_accrual_cents` return to
        exactly the values they held before the forward draw was posted -- restored
        exactly, not approximately." A reversal "subtracts the reversed accrual from
        `reserve_committed_accrual_cents`, subtracts the reversed settled amount from
        `reserve_committed_settled_cents`, adds the reversed accrual back to
        `reserve_available_cents`, recomputes `settlement_variance_cents`, and advances
        the agreement's `version` by 1."

        Design: Difficulty/compensating_invariant/draw_reversal_restores_reserve_money_exactly
        """
        state = self._reversed_draw(api)

        agreement = fixtures.current_agreement(api, state["agreement"]["id"])
        assert_money(
            agreement["reserve_committed_accrual_cents"],
            0,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_committed_settled_cents"],
            0,
            "reserve_committed_settled_cents",
        )
        assert_money(
            agreement["reserve_available_cents"], 12200000, "reserve_available_cents"
        )
        assert_money(
            agreement["settlement_variance_cents"], 0, "settlement_variance_cents"
        )
        assert agreement["status"] == "ACTIVE"
        assert_reserve_conserved(agreement)

        _, meta = validate_paginated(
            api.list_consumable_draws(
                make_contracts_administrator_headers(),
                {"service_agreement_id": agreement["id"]},
            )
        )
        assert meta["total_count"] == 2


class TestCancellationRestoresTheBayLedgerExactly:
    """Book, cancel, rebook and cancel again: the bay ends where it started."""

    FIRST_START = "2026-08-10T08:00:00.000Z"
    FIRST_END = "2026-08-10T16:00:00.000Z"
    SECOND_START = "2026-08-11T08:00:00.000Z"
    SECOND_END = "2026-08-11T16:00:00.000Z"

    def _two_cancelled_runs(self, api):
        state = fixtures.fat_ready_single_stage_project(api)
        first = fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["skid"]["id"]),
            state["test_bay"]["id"],
            self.FIRST_START,
            self.FIRST_END,
        )
        api.cancel_fat_run(first["id"], make_fabrication_manager_headers())
        second = fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["skid"]["id"]),
            state["test_bay"]["id"],
            self.SECOND_START,
            self.SECOND_END,
        )
        api.cancel_fat_run(second["id"], make_fabrication_manager_headers())
        state["first_run"] = first
        state["second_run"] = second
        return state

    def test_the_second_booking_is_a_fresh_round_of_the_same_size(self, api):
        """The rebooking is round two, still 480 minutes of 5400 square feet.

        A booking derives "`duration_minutes` as the whole minutes between
        `scheduled_start_at` and `scheduled_end_at`, discarding any partial minute" and
        "the new run's `round_no` is then one greater than the number of runs on that
        skid whose status is `PASSED`, `FAILED`, `CONDITIONAL`, `SUPERSEDED` or
        `CANCELLED`, and is at least 1."

        Design: Difficulty/compensating_invariant/fat_cancellation_restores_bay_footprint_minutes_exactly
        """
        state = self._two_cancelled_runs(api)

        second = state["second_run"]
        assert second["round_no"] == 2
        assert second["duration_minutes"] == 480
        assert second["footprint_sf"] == 5400

        for run_id in (state["first_run"]["id"], second["id"]):
            run = validate_success(
                api.get_fat_run(run_id, make_fabrication_manager_headers())
            )
            assert run["status"] == "CANCELLED"

    def test_the_bay_ledger_returns_to_zero_and_the_skid_stays_ready(self, api):
        """Cancelling subtracts exactly what booking added, and the skid is still bookable.

        Cancellation moves the run "`SCHEDULED → CANCELLED` and subtract[s] exactly the
        footprint-minutes the booking added, restoring the bay's
        `reserved_footprint_minutes` to its exact pre-booking value". Readiness is
        unaffected: it is `READY` while "`mechanical_status` is `MECH_COMPLETE` **and**
        `controls_status` is `CONTROLS_COMPLETE` **and** the parent package's status is
        `RELEASED_FOR_FAB`".

        Design: Difficulty/compensating_invariant/fat_cancellation_restores_bay_footprint_minutes_exactly
        """
        state = self._two_cancelled_runs(api)

        bay = validate_success(
            api.get_test_bay(state["test_bay"]["id"], make_fabrication_manager_headers())
        )
        assert_bay_ledger(bay, 0)

        skid = fixtures.current_skid(api, state["skid"]["id"])
        assert_skid_state(
            skid,
            mechanical_status="MECH_COMPLETE",
            controls_status="CONTROLS_COMPLETE",
            fat_readiness="READY",
        )

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "RELEASED_FOR_FAB"
