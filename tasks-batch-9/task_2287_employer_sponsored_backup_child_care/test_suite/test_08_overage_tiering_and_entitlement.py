"""Overage tier snapshots, the entitlement waterfall and the append-only day ledger."""

from typing import Any, Dict

import pytest
from test_helpers import (
    TEST_USERS,
    assert_block_seats_reconcile,
    assert_employee_days_reconcile,
    assert_entitlement_projection,
    assert_ledger_memos,
    assert_ledger_sequence,
    assert_usage_ledger_entry,
    cancel,
    confirm_reservation,
    create_capacity_block,
    create_reservation,
    drive_to_completed,
    match_reservation,
    read_capacity_block,
    read_employee,
    read_employee_ledger,
    read_employer,
    read_entitlement,
    read_reservation,
    read_reservation_ledger,
    setup_confirmed_reservation,
    setup_enrolled_employee,
    setup_provider_with_block,
    validate_paginated,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]

TIER_PLAN = {
    "annual_use_limit_days": 1,
    "copay_center_cents_per_day": 1500,
    "overage_rate_center_cents_per_day": 200000,
    "max_dependents_per_reservation": 3,
}

RECONCILE_PLAN = {
    "annual_use_limit_days": 10,
    "copay_center_cents_per_day": 1500,
    "cancellation_window_hours": 24,
    "max_dependents_per_reservation": 3,
}


class TestOverageTierSnapshot:
    """Two reservations against a one-day limit, where the first one's accrual
    decides the second one's multiplier but never its own."""

    @staticmethod
    def _tier_world(api) -> Dict[str, Any]:
        world = setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-10T09:00:00Z",
            care_end_utc="2026-08-10T17:00:00Z",
            block_start_utc="2026-08-10T08:00:00Z",
            block_end_utc="2026-08-10T18:00:00Z",
            market_code="MKT-CHI",
            total_slots=3,
            dependent_count=3,
            plan_overrides=dict(TIER_PLAN),
        )
        world["second_block"] = create_capacity_block(
            api,
            world["provider"]["id"],
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=3,
        )
        world["first_reservation"] = drive_to_completed(
            api,
            world["reservation"]["id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T17:00:00Z",
            check_in_clock="2026-08-10T08:30:00Z",
            complete_clock="2026-08-10T18:00:00Z",
        )
        return world

    def test_first_reservation_accrues_four_thousand_dollars_at_the_base_tier(self, api):
        """Three charged days against a one-day limit, priced at multiplier 1.00.

        PRD 3.6: "the overage unit rate is the plan's `overage_rate_center_cents_per_day`
        multiplied by `overage_tier_multiplier` and rounded to a whole cent;
        `overage_cents` is `overage_days` multiplied by that rounded unit rate and
        rounded again to a whole cent"

        Design: Difficulty/combinatorial_formula/overage_tier_snapshot_excludes_the_reservations_own_accrual
        """
        world = self._tier_world(api)
        first = world["first_reservation"]

        assert first["fulfillment_status"] == "COMPLETED"
        assert first["days_charged_final"] == pytest.approx(3, abs=0.01)
        assert first["covered_days"] == pytest.approx(1, abs=0.01)
        assert first["overage_days"] == pytest.approx(2, abs=0.01)
        assert first["overage_tier_multiplier"] == pytest.approx(1.00, abs=0.01)
        assert first["copay_cents"] == 1500
        assert first["overage_cents"] == 400000

        ledger = read_reservation_ledger(api, first["id"])
        assert_ledger_sequence(ledger, ["RESERVE", "RELEASE", "COMMIT", "OVERAGE_ACCRUE"])
        assert_ledger_memos(
            ledger, ["CONFIRM", "COMPLETE_RELEASE", "COMPLETE_COMMIT", "COMPLETE_OVERAGE"]
        )
        assert ledger[-1]["cents_delta"] == 400000

        employer = read_employer(api, world["employer"]["id"])
        assert employer["accrued_overage_cents_current_period"] == 400000

    def test_second_reservation_reads_the_accrual_that_predates_its_own(self, api):
        """A 400000-cent accrual selects 0.90, so the charge is 540000 and not 480000.

        PRD 3.6: "Step six snapshots the tier: reading the employer's
        `accrued_overage_cents_current_period` *as it stands before this reservation's
        own overage accrual exists*, `overage_tier_multiplier` becomes 1.00 when that
        accrual is below 100000 cents (one thousand dollars), 0.90 when it is below
        500000 cents (five thousand dollars), and 0.80 otherwise."

        Design: Difficulty/combinatorial_formula/overage_tier_snapshot_excludes_the_reservations_own_accrual
        """
        world = self._tier_world(api)

        second = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T17:00:00Z",
            market_code="MKT-CHI",
        )
        match_reservation(api, second["id"])
        confirmed = confirm_reservation(api, second["id"], world["second_block"]["id"])

        assert confirmed["overage_tier_multiplier"] == pytest.approx(0.90, abs=0.01)
        assert confirmed["overage_tier_multiplier"] != pytest.approx(0.80, abs=0.01)
        assert confirmed["overage_cents"] == 540000
        assert confirmed["overage_cents"] != 480000
        assert confirmed["copay_cents"] == 0
        assert confirmed["covered_days"] == pytest.approx(0, abs=0.01)
        assert confirmed["overage_days"] == pytest.approx(3, abs=0.01)
        assert confirmed["days_charged_provisional"] == pytest.approx(3, abs=0.01)
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["billing_status"] == "NOT_BILLABLE"

        employer = read_employer(api, world["employer"]["id"])
        assert employer["accrued_overage_cents_current_period"] == 400000


class TestEntitlementDaysReconcileToLedger:
    """One completion and one free cancellation, each compensated by an appended row."""

    @staticmethod
    def _reconcile_world(api) -> Dict[str, Any]:
        world = setup_enrolled_employee(
            api, dependent_count=2, plan_overrides=dict(RECONCILE_PLAN)
        )
        bundle = setup_provider_with_block(
            api,
            "2026-08-10T08:00:00Z",
            "2026-08-10T18:00:00Z",
            total_slots=4,
            market_code="MKT-RDU",
            daily_capacity_slots=4,
        )
        world.update(
            {
                "provider": bundle["provider"],
                "first_block": bundle["block"],
                "second_block": create_capacity_block(
                    api,
                    bundle["provider"]["id"],
                    "2026-08-12T08:00:00Z",
                    "2026-08-12T18:00:00Z",
                    total_slots=4,
                ),
            }
        )

        one_dependent = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"][:1],
            "2026-08-10T09:00:00Z",
            "2026-08-10T15:00:00Z",
            market_code="MKT-RDU",
        )
        match_reservation(api, one_dependent["id"])
        world["first_reservation"] = confirm_reservation(
            api, one_dependent["id"], world["first_block"]["id"]
        )

        two_dependents = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-12T09:00:00Z",
            "2026-08-12T15:00:00Z",
            market_code="MKT-RDU",
        )
        match_reservation(api, two_dependents["id"])
        world["second_reservation"] = confirm_reservation(
            api, two_dependents["id"], world["second_block"]["id"]
        )
        return world

    def test_two_confirmations_hold_three_days_and_consume_none(self, api):
        """Reserved days equal the RESERVE rows; used days are still zero.

        PRD 2.10: "First, for a given employee and benefit year, the sum of `days_delta`
        across all of that employee's entries in that year equals `entitlement_days_used`
        plus `entitlement_days_reserved`"

        Design: Difficulty/compensating_invariant/entitlement_days_reconcile_to_ledger_after_release_and_cancel
        """
        world = self._reconcile_world(api)

        entitlement = read_entitlement(api, world["employee"]["id"])
        assert_entitlement_projection(entitlement)
        assert entitlement["days_used"] == pytest.approx(0, abs=0.01)
        assert entitlement["days_reserved"] == pytest.approx(3, abs=0.01)
        assert entitlement["days_remaining"] == pytest.approx(7, abs=0.01)

        entries = read_employee_ledger(api, world["employee"]["id"])
        assert_ledger_sequence(entries, ["RESERVE", "RESERVE"])
        assert [e["days_delta"] for e in entries] == [
            pytest.approx(1, abs=0.01),
            pytest.approx(2, abs=0.01),
        ]
        assert_employee_days_reconcile(read_employee(api, world["employee"]["id"]), entries)

    def test_completion_appends_a_release_without_touching_the_reserve_row(self, api):
        """One day moves from reserved to used through two new rows, not an edit.

        PRD 3.7: "First a `RELEASE` entry whose `days_delta` is the negation of
        `days_charged_provisional`, `cents_delta` zero, `memo` `COMPLETE_RELEASE`,
        which hands back the optimistic hold."

        Design: Difficulty/compensating_invariant/entitlement_days_reconcile_to_ledger_after_release_and_cancel
        """
        world = self._reconcile_world(api)
        first_id = world["first_reservation"]["id"]

        completed = drive_to_completed(
            api,
            first_id,
            "2026-08-10T09:00:00Z",
            "2026-08-10T15:00:00Z",
            check_in_clock="2026-08-10T09:00:00Z",
            complete_clock="2026-08-10T15:00:00Z",
        )
        assert completed["days_charged_final"] == pytest.approx(1, abs=0.01)

        entitlement = read_entitlement(api, world["employee"]["id"])
        assert entitlement["days_used"] == pytest.approx(1, abs=0.01)
        assert entitlement["days_reserved"] == pytest.approx(2, abs=0.01)

        own_rows = read_reservation_ledger(api, first_id)
        assert_ledger_sequence(own_rows, ["RESERVE", "RELEASE", "COMMIT"])
        assert own_rows[0]["days_delta"] == pytest.approx(1, abs=0.01)
        assert own_rows[0]["memo"] == "CONFIRM"
        assert own_rows[1]["days_delta"] == pytest.approx(-1, abs=0.01)
        assert own_rows[2]["days_delta"] == pytest.approx(1, abs=0.01)

    def test_free_cancellation_returns_the_remaining_hold_and_no_money(self, api):
        """Five append-only rows sum to the one day actually consumed.

        PRD 3.7: "From `CONFIRMED`, cancellation is the exact compensating transition
        for confirmation: it appends a `RELEASE` entry whose `days_delta` is the negation
        of `days_charged_provisional`, `cents_delta` zero and `memo` `CANCEL`"

        Design: Difficulty/compensating_invariant/entitlement_days_reconcile_to_ledger_after_release_and_cancel
        """
        world = self._reconcile_world(api)
        drive_to_completed(
            api,
            world["first_reservation"]["id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T15:00:00Z",
            check_in_clock="2026-08-10T09:00:00Z",
            complete_clock="2026-08-10T15:00:00Z",
        )

        cancelled = cancel(api, world["second_reservation"]["id"])
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["penalty_cents"] == 0
        assert cancelled["billing_status"] == "NOT_BILLABLE"

        entitlement = read_entitlement(api, world["employee"]["id"])
        assert entitlement["days_used"] == pytest.approx(1, abs=0.01)
        assert entitlement["days_reserved"] == pytest.approx(0, abs=0.01)
        assert entitlement["days_remaining"] == pytest.approx(9, abs=0.01)

        entries = read_employee_ledger(api, world["employee"]["id"])
        assert_ledger_sequence(entries, ["RESERVE", "RESERVE", "RELEASE", "COMMIT", "RELEASE"])
        assert_ledger_memos(
            entries, ["CONFIRM", "CONFIRM", "COMPLETE_RELEASE", "COMPLETE_COMMIT", "CANCEL"]
        )
        deltas = [e["days_delta"] for e in entries]
        assert deltas[0] == pytest.approx(1, abs=0.01)
        assert deltas[1] == pytest.approx(2, abs=0.01)
        assert deltas[2] == pytest.approx(-1, abs=0.01)
        assert deltas[3] == pytest.approx(1, abs=0.01)
        assert deltas[4] == pytest.approx(-2, abs=0.01)
        assert sum(deltas) == pytest.approx(1, abs=0.01)
        assert all(e["cents_delta"] == 0 for e in entries)
        assert_employee_days_reconcile(read_employee(api, world["employee"]["id"]), entries)

        assert_block_seats_reconcile(
            read_capacity_block(api, world["first_block"]["id"]), 0, 1
        )
        assert_block_seats_reconcile(
            read_capacity_block(api, world["second_block"]["id"]), 0, 0
        )
        assert read_reservation(api, world["second_reservation"]["id"])[
            "matched_capacity_block_id"
        ] == world["second_block"]["id"]


class TestUsageLedgerEntryShape:
    def test_a_ledger_row_carries_no_version_and_no_updated_at(self, api):
        """The RESERVE row is a bucketed, append-only fact with no mutation surface.

        PRD 2.10: "Every movement of entitlement days or penalty money is recorded as a
        `UsageLedgerEntry`, and those entries are never updated or deleted."

        Design: Corner/entities/corner_usage_ledger_entry_is_immutable_and_versionless
        """
        world = setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-10T09:00:00Z",
            care_end_utc="2026-08-10T15:00:00Z",
            block_start_utc="2026-08-10T08:00:00Z",
            block_end_utc="2026-08-10T18:00:00Z",
            market_code="MKT-CLE",
        )

        rows, meta = validate_paginated(
            api.list_reservation_ledger_entries(
                world["reservation"]["id"], NETWORK_ADMIN, {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1

        row = rows[0]
        assert_usage_ledger_entry(row)
        assert row["entry_type"] == "RESERVE"
        assert row["days_delta"] == pytest.approx(1, abs=0.01)
        assert row["cents_delta"] == 0
        assert row["memo"] == "CONFIRM"
        assert row["reservation_id"] == world["reservation"]["id"]
        assert row["employee_id"] == world["employee"]["id"]
        assert str(row["benefit_year_start"]).startswith("2026-01-01")
        assert str(row["effective_at"]).startswith("2026-08-01T00:00:00")
