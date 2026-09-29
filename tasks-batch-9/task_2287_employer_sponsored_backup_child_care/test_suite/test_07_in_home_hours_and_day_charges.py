"""In-home billable hours, the eight-hour day constant and the two charge passes."""

from typing import Any, Dict

import pytest
from test_helpers import (
    TEST_USERS,
    assert_ledger_memos,
    assert_ledger_sequence,
    create_capacity_block,
    create_reservation,
    drive_to_completed,
    match_reservation,
    read_employee,
    read_entitlement,
    read_reservation,
    read_reservation_ledger,
    confirm_reservation,
    setup_confirmed_reservation,
    setup_matchable_world,
)

CARE_COORDINATOR = TEST_USERS["care_coordinator"]

IN_HOME_PLAN = {
    "annual_use_limit_days": 10,
    "copay_in_home_cents_per_hour": 400,
    "in_home_min_billable_hours": 4,
    "overage_rate_in_home_cents_per_hour": 3000,
}


class TestInHomeBillableFloor:
    def test_a_two_hour_visit_bills_the_four_hour_plan_floor(self, api):
        """Two requested hours, four billed hours, one entitlement day.

        PRD 3.6: "For in-home care, the raw hours are the total number of seconds
        between the window's start and its exclusive end divided by 3600, held as an
        exact decimal; that raw figure is then raised to the next whole multiple of a
        quarter hour; and the billable figure is the greater of that stepped value
        and the plan's `in_home_min_billable_hours` floor."

        Design: Corner/calculations/corner_in_home_min_billable_floor_lifts_two_hour_visit_to_four
        """
        world = setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-14T09:00:00Z",
            care_end_utc="2026-08-14T11:00:00Z",
            block_start_utc="2026-08-14T07:00:00Z",
            block_end_utc="2026-08-14T20:00:00Z",
            market_code="MKT-DEN",
            total_slots=1,
            provider_care_mode="IN_HOME",
            requested_care_mode="IN_HOME",
            plan_overrides=dict(IN_HOME_PLAN),
        )
        reservation = world["reservation"]

        assert reservation["fulfillment_status"] == "CONFIRMED"
        assert reservation["billable_hours_provisional"] == pytest.approx(4.00, abs=0.01)
        assert reservation["days_charged_provisional"] == pytest.approx(1, abs=0.01)
        assert reservation["covered_days"] == pytest.approx(1, abs=0.01)
        assert reservation["overage_days"] == pytest.approx(0, abs=0.01)
        assert reservation["copay_cents"] == 1600
        assert reservation["overage_cents"] == 0
        assert reservation["required_seats"] == 1

        employee = read_employee(api, world["employee"]["id"])
        assert employee["entitlement_days_reserved"] == pytest.approx(1, abs=0.01)
        assert employee["entitlement_days_used"] == pytest.approx(0, abs=0.01)

        ledger = read_reservation_ledger(api, reservation["id"])
        assert_ledger_sequence(ledger, ["RESERVE"])
        assert ledger[0]["days_delta"] == pytest.approx(1, abs=0.01)


class TestInHomeDayConstant:
    def test_exactly_eight_hours_is_one_day_and_one_more_minute_is_two(self, api):
        """The quarter-hour step lifts 8h01m to 8.25 and the day charge doubles.

        PRD 3.6: "For in-home care, one caregiver visit covers every dependent at
        once, so the days charged are the billable hours divided by eight and then
        raised to the next whole number; day counts are non-negative integers and the
        raise is exact."

        Design: Corner/calculations/corner_in_home_hours_per_day_constant_splits_eight_from_eight_oh_one
        """
        world = setup_matchable_world(
            api,
            care_start_utc="2026-08-14T09:00:00Z",
            care_end_utc="2026-08-14T17:00:00Z",
            block_start_utc="2026-08-14T07:00:00Z",
            block_end_utc="2026-08-14T20:00:00Z",
            market_code="MKT-DEN",
            total_slots=1,
            provider_care_mode="IN_HOME",
            requested_care_mode="IN_HOME",
            plan_overrides=dict(IN_HOME_PLAN),
        )
        second_block = create_capacity_block(
            api,
            world["provider"]["id"],
            "2026-08-15T07:00:00Z",
            "2026-08-15T20:00:00Z",
            total_slots=1,
        )
        one_minute_longer = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-15T09:00:00Z",
            "2026-08-15T17:01:00Z",
            market_code="MKT-DEN",
            requested_care_mode="IN_HOME",
        )

        match_reservation(api, world["reservation"]["id"])
        exactly_eight = confirm_reservation(
            api, world["reservation"]["id"], world["block"]["id"]
        )
        assert exactly_eight["billable_hours_provisional"] == pytest.approx(8.00, abs=0.01)
        assert exactly_eight["days_charged_provisional"] == pytest.approx(1, abs=0.01)
        assert exactly_eight["copay_cents"] == 3200

        match_reservation(api, one_minute_longer["id"])
        stepped = confirm_reservation(api, one_minute_longer["id"], second_block["id"])
        assert stepped["billable_hours_provisional"] == pytest.approx(8.25, abs=0.01)
        assert stepped["days_charged_provisional"] == pytest.approx(2, abs=0.01)
        assert stepped["covered_days"] == pytest.approx(2, abs=0.01)
        assert stepped["overage_days"] == pytest.approx(0, abs=0.01)
        assert stepped["copay_cents"] == 3300

        entitlement = read_entitlement(api, world["employee"]["id"])
        assert entitlement["days_reserved"] == pytest.approx(3, abs=0.01)
        assert entitlement["days_remaining"] == pytest.approx(7, abs=0.01)


class TestProvisionalVersusFinalDayCharge:
    """One plan design, one reservation, two disagreeing charge passes."""

    @staticmethod
    def _six_hour_visit_world(api) -> Dict[str, Any]:
        return setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-10T09:00:00Z",
            care_end_utc="2026-08-10T15:00:00Z",
            block_start_utc="2026-08-10T08:00:00Z",
            block_end_utc="2026-08-10T19:00:00Z",
            market_code="MKT-BOS",
            total_slots=1,
            provider_care_mode="IN_HOME",
            requested_care_mode="IN_HOME",
            plan_overrides=dict(IN_HOME_PLAN),
        )

    def test_the_provisional_pass_reads_the_requested_window(self, api):
        """Six requested hours produce one day and a 2400-cent copay.

        PRD 3.6: "At confirmation the window used is the *requested* one —
        `care_start_utc` to `care_end_utc` — and the result is written to
        `billable_hours_provisional`."

        Design: Difficulty/dual_variant_calc/in_home_day_charge_provisional_one_day_vs_final_two_days
        """
        world = self._six_hour_visit_world(api)
        reservation = world["reservation"]

        assert reservation["billable_hours_provisional"] == pytest.approx(6.00, abs=0.01)
        assert reservation["days_charged_provisional"] == pytest.approx(1, abs=0.01)
        assert reservation["copay_cents"] == 2400
        assert reservation["covered_days"] == pytest.approx(1, abs=0.01)
        assert reservation["overage_days"] == pytest.approx(0, abs=0.01)
        assert reservation["billable_hours_final"] is None
        assert reservation["days_charged_final"] is None
        assert reservation["billing_status"] == "NOT_BILLABLE"

        ledger = read_reservation_ledger(api, reservation["id"])
        assert_ledger_sequence(ledger, ["RESERVE"])
        assert ledger[0]["days_delta"] == pytest.approx(1, abs=0.01)
        assert ledger[0]["cents_delta"] == 0

    def test_the_final_pass_reads_the_actual_window_and_disagrees(self, api):
        """Nine and a half delivered hours turn one provisional day into two.

        PRD 3.7: "Completion re-runs stages one through four of the charge arithmetic
        against the *actual* window rather than the requested one, writing
        `billable_hours_final` and `days_charged_final` and then overwriting
        `covered_days`, `overage_days`, `overage_tier_multiplier`, `copay_cents` and
        `overage_cents` from that final pass."

        Design: Difficulty/dual_variant_calc/in_home_day_charge_provisional_one_day_vs_final_two_days
        """
        world = self._six_hour_visit_world(api)
        reservation_id = world["reservation"]["id"]

        completed = drive_to_completed(
            api,
            reservation_id,
            "2026-08-10T09:00:00Z",
            "2026-08-10T18:30:00Z",
            check_in_clock="2026-08-10T08:30:00Z",
            complete_clock="2026-08-10T19:00:00Z",
        )

        assert completed["fulfillment_status"] == "COMPLETED"
        assert completed["billing_status"] == "ACCRUED"
        assert completed["billable_hours_provisional"] == pytest.approx(6.00, abs=0.01)
        assert completed["days_charged_provisional"] == pytest.approx(1, abs=0.01)
        assert completed["billable_hours_final"] == pytest.approx(9.50, abs=0.01)
        assert completed["days_charged_final"] == pytest.approx(2, abs=0.01)
        assert completed["days_charged_final"] != completed["days_charged_provisional"]
        assert completed["covered_days"] == pytest.approx(2, abs=0.01)
        assert completed["overage_days"] == pytest.approx(0, abs=0.01)
        assert completed["overage_tier_multiplier"] == pytest.approx(1.00, abs=0.01)
        assert completed["copay_cents"] == 3800
        assert completed["overage_cents"] == 0

        echoed = read_reservation(api, reservation_id)
        assert echoed["billable_hours_final"] == pytest.approx(9.50, abs=0.01)
        assert echoed["copay_cents"] == 3800

    def test_completion_releases_the_hold_before_committing_the_real_days(self, api):
        """Three ledger rows carry plus one, minus one and plus two days.

        PRD 3.7: "First a `RELEASE` entry whose `days_delta` is the negation of
        `days_charged_provisional`, `cents_delta` zero, `memo` `COMPLETE_RELEASE`,
        which hands back the optimistic hold."

        Design: Difficulty/dual_variant_calc/in_home_day_charge_provisional_one_day_vs_final_two_days
        """
        world = self._six_hour_visit_world(api)
        reservation_id = world["reservation"]["id"]

        drive_to_completed(
            api,
            reservation_id,
            "2026-08-10T09:00:00Z",
            "2026-08-10T18:30:00Z",
            check_in_clock="2026-08-10T08:30:00Z",
            complete_clock="2026-08-10T19:00:00Z",
        )

        ledger = read_reservation_ledger(api, reservation_id)
        assert_ledger_sequence(ledger, ["RESERVE", "RELEASE", "COMMIT"])
        assert_ledger_memos(ledger, ["CONFIRM", "COMPLETE_RELEASE", "COMPLETE_COMMIT"])
        deltas = [row["days_delta"] for row in ledger]
        assert deltas[0] == pytest.approx(1, abs=0.01)
        assert deltas[1] == pytest.approx(-1, abs=0.01)
        assert deltas[2] == pytest.approx(2, abs=0.01)
        assert all(row["cents_delta"] == 0 for row in ledger)

        employee = read_employee(api, world["employee"]["id"])
        assert employee["entitlement_days_used"] == pytest.approx(2, abs=0.01)
        assert employee["entitlement_days_reserved"] == pytest.approx(0, abs=0.01)

        entitlement = read_entitlement(api, world["employee"]["id"])
        assert entitlement["days_used"] == pytest.approx(2, abs=0.01)
        assert entitlement["days_remaining"] == pytest.approx(8, abs=0.01)
