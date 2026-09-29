"""The cancellation deadline instant, the no-show cascade and the service-edge clock gates."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_ledger_memos,
    assert_ledger_sequence,
    cancel,
    capacity_block_payload,
    clock_payload,
    complete_payload,
    confirm_reservation,
    create_capacity_block,
    create_dependent,
    create_employee,
    create_reservation,
    mark_no_show,
    match_reservation,
    no_show_payload,
    read_capacity_block,
    read_employee,
    read_employee_ledger,
    read_entitlement,
    read_reservation,
    read_reservation_ledger,
    reservation_payload,
    set_clock,
    setup_confirmed_reservation,
    setup_enrolled_employee,
    setup_provider_with_block,
    validate_error,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]

DEADLINE_PLAN = {
    "annual_use_limit_days": 10,
    "copay_center_cents_per_day": 1500,
    "cancellation_window_hours": 24,
    "no_show_charge_cents": 12000,
}


class TestCancellationDeadlineInstant:
    """Two identical confirmed reservations cancelled one second apart."""

    @staticmethod
    def _two_confirmed_reservations(api) -> Dict[str, Any]:
        world = setup_enrolled_employee(api, plan_overrides=dict(DEADLINE_PLAN))
        second_employee = create_employee(
            api,
            world["employer"]["id"],
            world["plan"]["id"],
            "u_ee_deadline_2",
            employee_external_id="E-9002",
            email="second@deadline.test",
        )
        second_dependent = create_dependent(api, second_employee["id"])
        bundle = setup_provider_with_block(
            api,
            "2026-08-10T08:00:00Z",
            "2026-08-10T18:00:00Z",
            total_slots=4,
            market_code="MKT-ATL",
            daily_capacity_slots=4,
        )

        reservations = []
        for employee_id, dependent_ids in (
            (world["employee"]["id"], world["dependent_ids"]),
            (second_employee["id"], [second_dependent["id"]]),
        ):
            created = create_reservation(
                api,
                employee_id,
                dependent_ids,
                "2026-08-10T09:00:00Z",
                "2026-08-10T15:00:00Z",
                market_code="MKT-ATL",
            )
            match_reservation(api, created["id"])
            reservations.append(confirm_reservation(api, created["id"], bundle["block"]["id"]))

        return {
            "employee_ids": [world["employee"]["id"], second_employee["id"]],
            "block": bundle["block"],
            "on_time": reservations[0],
            "late": reservations[1],
        }

    def test_both_reservations_freeze_the_same_deadline_at_intake(self, api):
        """A 24-hour window on a 09:00Z care start pins 2026-08-09T09:00:00Z.

        PRD 3.7: "Whether it costs anything is decided by the frozen
        `cancellation_deadline_utc`, which was written at intake as `care_start_utc`
        moved earlier by the pinned plan's `cancellation_window_hours` and is never
        recomputed."

        Design: Difficulty/boundary_precision_check/cancel_exactly_at_deadline_is_free_one_second_later_costs_6000
        """
        world = self._two_confirmed_reservations(api)

        for reservation in (world["on_time"], world["late"]):
            assert str(reservation["cancellation_deadline_utc"]).startswith(
                "2026-08-09T09:00:00"
            )
            assert reservation["fulfillment_status"] == "CONFIRMED"
            assert reservation["penalty_cents"] == 0

    def test_cancelling_at_exactly_the_deadline_costs_nothing(self, api):
        """Equality is on time, so no penalty and no money row.

        PRD 3.7: "A cancellation is late exactly when the logical clock is strictly
        after that deadline; cancelling at precisely the deadline instant is on time."

        Design: Difficulty/boundary_precision_check/cancel_exactly_at_deadline_is_free_one_second_later_costs_6000
        """
        world = self._two_confirmed_reservations(api)
        set_clock(api, "2026-08-09T09:00:00Z")

        cancelled = cancel(api, world["on_time"]["id"], cancel_reason_code="SCHOOL_REOPENED")

        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["penalty_cents"] == 0
        assert cancelled["billing_status"] == "NOT_BILLABLE"

        ledger = read_reservation_ledger(api, world["on_time"]["id"])
        assert_ledger_sequence(ledger, ["RESERVE", "RELEASE"])
        assert_ledger_memos(ledger, ["CONFIRM", "CANCEL"])
        assert ledger[1]["days_delta"] == pytest.approx(-1, abs=0.01)
        assert all(row["cents_delta"] == 0 for row in ledger)

        employee = read_employee(api, world["employee_ids"][0])
        assert employee["entitlement_days_reserved"] == pytest.approx(0, abs=0.01)

    def test_cancelling_one_second_late_costs_half_the_no_show_charge(self, api):
        """One second past the deadline charges 6000 and accrues it.

        PRD 3.7: "A late cancellation *from `CONFIRMED`* sets `penalty_cents` to the
        plan's `no_show_charge_cents` multiplied by one half and rounded to a whole
        cent."

        Design: Difficulty/boundary_precision_check/cancel_exactly_at_deadline_is_free_one_second_later_costs_6000
        """
        world = self._two_confirmed_reservations(api)
        set_clock(api, "2026-08-09T09:00:01Z")

        cancelled = cancel(api, world["late"]["id"], cancel_reason_code="SCHOOL_REOPENED")

        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["penalty_cents"] == 6000
        assert cancelled["billing_status"] == "ACCRUED"

        ledger = read_reservation_ledger(api, world["late"]["id"])
        assert_ledger_sequence(ledger, ["RESERVE", "RELEASE", "LATE_CANCEL_CHARGE"])
        assert_ledger_memos(ledger, ["CONFIRM", "CANCEL", "LATE_CANCEL"])
        assert ledger[2]["days_delta"] == pytest.approx(0, abs=0.01)
        assert ledger[2]["cents_delta"] == 6000

        employee = read_employee(api, world["employee_ids"][1])
        assert employee["entitlement_days_reserved"] == pytest.approx(0, abs=0.01)

        block = read_capacity_block(api, world["block"]["id"])
        assert block["reserved_slots"] == 1
        assert block["block_status"] == "OPEN"


class TestNoShowCascade:
    """A second strike in one benefit year closes the benefit to the employee."""

    @staticmethod
    def _one_strike_world(api) -> Dict[str, Any]:
        world = setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-10T09:00:00Z",
            care_end_utc="2026-08-10T15:00:00Z",
            block_start_utc="2026-08-10T08:00:00Z",
            block_end_utc="2026-08-10T18:00:00Z",
            market_code="MKT-DEN",
            total_slots=4,
        )
        world["second_block"] = create_capacity_block(
            api,
            world["provider"]["id"],
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=4,
        )
        second = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-DEN",
        )
        match_reservation(api, second["id"])
        world["second_reservation"] = confirm_reservation(
            api, second["id"], world["second_block"]["id"]
        )

        set_clock(api, "2026-08-10T09:30:00Z")
        world["first_no_show"] = mark_no_show(
            api, world["reservation"]["id"], reason_code="FAMILY_NEVER_ARRIVED"
        )
        return world

    def test_the_first_strike_charges_in_full_and_leaves_the_employee_eligible(self, api):
        """One strike is not two, so intake stays open.

        PRD 3.7: "It sets `penalty_cents` to the plan's `no_show_charge_cents` as pinned
        at `plan_version_pinned` — the full charge, not a fraction"

        Design: Difficulty/transitive_cascade/no_show_cascades_charge_ledger_strike_count_then_bars_new_intake
        """
        world = self._one_strike_world(api)

        assert world["first_no_show"]["fulfillment_status"] == "NO_SHOW"
        assert world["first_no_show"]["penalty_cents"] == 12000
        assert world["first_no_show"]["billing_status"] == "ACCRUED"

        employee = read_employee(api, world["employee"]["id"])
        assert employee["no_show_strike_count"] == 1
        assert employee["eligibility_status"] == "ELIGIBLE"

        ledger = read_reservation_ledger(api, world["reservation"]["id"])
        assert_ledger_sequence(ledger, ["RESERVE", "RELEASE", "COMMIT", "NO_SHOW_CHARGE"])
        assert_ledger_memos(
            ledger, ["CONFIRM", "NO_SHOW_RELEASE", "NO_SHOW_COMMIT", "NO_SHOW"]
        )
        assert ledger[3]["cents_delta"] == 12000
        assert ledger[3]["days_delta"] == pytest.approx(0, abs=0.01)

    def test_the_second_strike_restricts_the_employee_and_burns_both_days(self, api):
        """Two NO_SHOW_CHARGE rows recompute eligibility to RESTRICTED.

        PRD 3.7: "recomputes `no_show_strike_count` from the number of
        `NO_SHOW_CHARGE` entries in the current benefit year, and recomputes
        `eligibility_status`, which becomes `RESTRICTED` once that strike count reaches
        two."

        Design: Difficulty/transitive_cascade/no_show_cascades_charge_ledger_strike_count_then_bars_new_intake
        """
        world = self._one_strike_world(api)
        set_clock(api, "2026-08-11T09:30:00Z")

        second = mark_no_show(
            api, world["second_reservation"]["id"], reason_code="FAMILY_NEVER_ARRIVED"
        )
        assert second["fulfillment_status"] == "NO_SHOW"
        assert second["penalty_cents"] == 12000
        assert second["billing_status"] == "ACCRUED"

        employee = read_employee(api, world["employee"]["id"])
        assert employee["no_show_strike_count"] == 2
        assert employee["eligibility_status"] == "RESTRICTED"
        assert employee["entitlement_days_used"] == pytest.approx(2, abs=0.01)
        assert employee["entitlement_days_reserved"] == pytest.approx(0, abs=0.01)

        entries = read_employee_ledger(api, world["employee"]["id"])
        assert len(entries) == 8
        assert sum(row["days_delta"] for row in entries) == pytest.approx(2, abs=0.01)
        assert sum(row["cents_delta"] for row in entries) == 24000

        projection = read_entitlement(api, world["employee"]["id"])
        assert projection["no_show_strike_count"] == 2
        assert projection["eligibility_status"] == "RESTRICTED"

    def test_a_restricted_employee_cannot_open_a_new_reservation(self, api):
        """The fourth cascade level: intake refuses the next request outright.

        PRD 3.4: "The employee's `eligibility_status` must be `ELIGIBLE`; a `RESTRICTED`
        employee (two or more no-show strikes this benefit year) or an `INELIGIBLE` one
        (non-active employment, or an employer whose contract is not active) is refused
        with `ERR_EMPLOYEE_NOT_ELIGIBLE`."

        Design: Difficulty/transitive_cascade/no_show_cascades_charge_ledger_strike_count_then_bars_new_intake
        """
        world = self._one_strike_world(api)
        set_clock(api, "2026-08-11T09:30:00Z")
        mark_no_show(api, world["second_reservation"]["id"], reason_code="FAMILY_NEVER_ARRIVED")

        refused = api.create_reservation(
            reservation_payload(
                world["employee"]["id"],
                world["dependent_ids"],
                "2026-08-20T09:00:00Z",
                "2026-08-20T15:00:00Z",
                market_code="MKT-DEN",
            ),
            CARE_COORDINATOR,
        )
        validate_error(refused, ApiErrorId.ERR_EMPLOYEE_NOT_ELIGIBLE.value, 409)

        blocked = api.list_reservations(CARE_COORDINATOR, {"limit": 50, "offset": 0})
        care_dates = [row["care_date"] for row in blocked.json()["data"]]
        assert all(not str(date).startswith("2026-08-20") for date in care_dates)


class TestServiceEdgeTemporalGates:
    def test_the_clock_and_window_gates_around_one_confirmed_reservation(self, api):
        """Block dating, block overlap, clock rewind, check-in lead and actual window.

        PRD 2.4: "The clock may only move forward — a target strictly earlier than the
        present value is rejected with `ERR_CLOCK_MOVES_BACKWARD`."

        PRD 3.3: "Blocks of the same provider on the same `service_date` may not overlap,
        and because each interval is treated as half-open, a block that starts at exactly
        the instant another ends is accepted; a genuine overlap returns
        `ERR_BLOCK_OVERLAP`."

        PRD 3.7: "The window opens one hour before `care_start_utc` — the logical clock
        must be at or after `care_start_utc` moved earlier by sixty minutes — and closes
        at `care_end_utc`, which the clock must still be strictly before; outside that
        window the answer is `ERR_CHECK_IN_TOO_EARLY`."

        Design: Corner/errors/corner_service_edge_temporal_error_battery
        """
        world = setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-13T09:00:00Z",
            care_end_utc="2026-08-13T15:00:00Z",
            block_start_utc="2026-08-13T08:00:00Z",
            block_end_utc="2026-08-13T18:00:00Z",
            market_code="MKT-ABQ",
            total_slots=4,
        )
        provider_id = world["provider"]["id"]
        reservation_id = world["reservation"]["id"]
        assert world["reservation"]["fulfillment_status"] == "CONFIRMED"

        spans_midnight = api.create_capacity_block(
            provider_id,
            capacity_block_payload("2026-08-14T22:00:00Z", "2026-08-15T02:00:00Z"),
            NETWORK_ADMIN,
        )
        validate_error(spans_midnight, ApiErrorId.ERR_BLOCK_DATE_MISMATCH.value, 400)

        abutting = create_capacity_block(
            api, provider_id, "2026-08-13T18:00:00Z", "2026-08-13T20:00:00Z", total_slots=2
        )
        assert abutting["service_date"].startswith("2026-08-13")

        overlapping = api.create_capacity_block(
            provider_id,
            capacity_block_payload(
                "2026-08-13T19:00:00Z", "2026-08-13T21:00:00Z", total_slots=2
            ),
            NETWORK_ADMIN,
        )
        validate_error(overlapping, ApiErrorId.ERR_BLOCK_OVERLAP.value, 409)

        rewound = api.set_clock(clock_payload("2026-07-31T23:59:59Z"), NETWORK_ADMIN)
        validate_error(rewound, ApiErrorId.ERR_CLOCK_MOVES_BACKWARD.value, 409)

        set_clock(api, "2026-08-13T07:59:00Z")
        too_early = api.check_in_reservation(reservation_id, CARE_COORDINATOR)
        validate_error(too_early, ApiErrorId.ERR_CHECK_IN_TOO_EARLY.value, 409)

        too_early_no_show = api.no_show_reservation(
            reservation_id, no_show_payload(reason_code="FAMILY_DID_NOT_ARRIVE"), CARE_COORDINATOR
        )
        validate_error(too_early_no_show, ApiErrorId.ERR_NO_SHOW_TOO_EARLY.value, 409)

        set_clock(api, "2026-08-13T08:00:00Z")
        checked_in = api.check_in_reservation(reservation_id, CARE_COORDINATOR)
        assert checked_in.status_code == 200
        assert checked_in.json()["data"]["fulfillment_status"] == "IN_SERVICE"

        wrong_day = api.complete_reservation(
            reservation_id,
            complete_payload("2026-08-12T09:00:00Z", "2026-08-13T15:00:00Z"),
            CARE_COORDINATOR,
        )
        validate_error(wrong_day, ApiErrorId.ERR_INVALID_ACTUAL_WINDOW.value, 400)

        after = read_reservation(api, reservation_id)
        assert after["fulfillment_status"] == "IN_SERVICE"
        assert after["billing_status"] == "NOT_BILLABLE"
        assert after["billable_hours_final"] is None
