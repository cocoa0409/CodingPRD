"""Flight-log filing: hobbs computation and guards, pickup-failure
suspension threshold, and the suspension cascade onto scheduled slots."""
import pytest

from test_helpers import (
    ApiErrorId,
    book_slot_in,
    file_flight_log,
    get_slot,
    make_pilot_headers,
    schedule_slot,
    setup_operation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN


class TestHobbsComputation:

    def test_hobbs_hours_rounded_to_tenth(self, api):
        """PRD §2.9: "A flight log's billable duration is its shutdown
        reading minus its engine-start reading, rounded to the nearest tenth
        of an hour."

        Readings 100.0 -> 101.5 yield exactly 1.5 billable hours.

        Design: Corner/calculations/hobbs_hours_computed_rounded_to_tenth
        """
        sc = setup_operation(base_code="KHOB")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=2)
        schedule_slot(slot["id"])
        log = file_flight_log(slot["id"], hobbs_out=100.0, hobbs_in=101.5)
        assert log["hobbs_hours"] == pytest.approx(1.5, abs=0.001), (
            f"hobbs_hours must be 101.5 - 100.0 = 1.5, got "
            f"{log['hobbs_hours']}"
        )
        assert log["aircraft_id"] == sc["aircraft"]["id"]
        assert log["pilot_id"] == sc["pilot"]["id"]
        assert get_slot(slot["id"])["status"] == "FLOWN"

    def test_hobbs_in_not_greater_than_out_rejected(self, api):
        """PRD §3.6: "then the hobbs sanity check — `hobbs_in` must be
        strictly greater than `hobbs_out`, else `ERR_INVALID_HOBBS`
        (HTTP 422)".

        Equal readings are not strictly greater, so filing is rejected.

        Design: Corner/calculations/hobbs_in_le_hobbs_out_rejected
        """
        sc = setup_operation(base_code="KHBE")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        schedule_slot(slot["id"])
        slot_now = get_slot(slot["id"])
        resp = api.file_flight_log(
            slot["id"],
            {"hobbs_out": 100.0, "hobbs_in": 100.0,
             "pickup_technique": "GROUND_PICKUP", "pickup_outcome": "CLEAN",
             "tow_field_notes": ""},
            make_pilot_headers(slot_now["assigned_pilot_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_HOBBS, expected_status=422)


class TestPickupFailureThreshold:

    def _book_four_hourly_slots(self, sc, date_local="2026-08-13"):
        """Four adjacent 1-hour slots inside a 12:00-19:00 approval window."""
        slots = []
        for hour in (14, 15, 16, 17):
            slots.append(book_slot_in(
                sc, planned_start=f"{date_local}T{hour:02d}:00:00Z",
                planned_duration_hours=1))
        return slots

    def test_three_failed_pickups_suspend_pilot_while_hours_accumulate(
            self, api):
        """PRD §3.6: "A log filed with `pickup_outcome` `FAILED` increments
        the pilot's `season_pickup_failure_count` by one; when that count
        reaches three — exactly three suspends, two does not — the pilot is
        automatically suspended to `SUSPENDED`". PRD §2.9: "Seasonal
        utilization is reckoned against the active season, which runs from
        May 1 through September 30: only flight time logged within that
        window accrues toward an aircraft's or pilot's season totals."

        After three 1-hour FAILED flights in August, the pilot's
        season_hours_flown grows linearly to 3.0 while the failure counter
        trips the status gate at exactly 3.

        Design: Difficulty/dual_variant_calc/pickup_failure_count_vs_season_hours_divergence
        """
        sc = setup_operation(base_code="KDV3",
                             window_start="2026-08-13T12:00:00Z",
                             window_end="2026-08-13T19:00:00Z")
        slots = self._book_four_hourly_slots(sc)[:3]
        for i, slot in enumerate(slots):
            schedule_slot(slot["id"])
            file_flight_log(slot["id"], hobbs_out=100.0 + i * 100,
                            hobbs_in=101.0 + i * 100,
                            pickup_outcome="FAILED")
        pilot = validate_success(api.get_pilot(sc["pilot"]["id"], ADMIN),
                                 expected_status=200)
        assert pilot["season_hours_flown"] == pytest.approx(3.0, abs=0.001), (
            f"three 1-hour flights must accrue 3.0 season hours, got "
            f"{pilot['season_hours_flown']}"
        )
        assert pilot["season_pickup_failure_count"] == 3
        assert pilot["status"] == "SUSPENDED", (
            f"third FAILED pickup must suspend the pilot, got "
            f"{pilot['status']}"
        )

    def test_two_failed_pickups_do_not_suspend_but_hours_accumulate(
            self, api):
        """PRD §3.6: "when that count reaches three — exactly three suspends,
        two does not". PRD §2.9: "only flight time logged within that window
        accrues toward an aircraft's or pilot's season totals."

        FAILED, CLEAN, FAILED: the failure counter gates at 2 (no
        suspension) while the hours aggregate reaches 3.0 — the two pilot
        aggregates evolve under different algorithms on the same log stream.

        Design: Difficulty/dual_variant_calc/pickup_failure_count_vs_season_hours_divergence
        """
        sc = setup_operation(base_code="KDV2",
                             window_start="2026-08-13T12:00:00Z",
                             window_end="2026-08-13T19:00:00Z")
        slots = self._book_four_hourly_slots(sc)[:3]
        outcomes = ["FAILED", "CLEAN", "FAILED"]
        for i, (slot, outcome) in enumerate(zip(slots, outcomes)):
            schedule_slot(slot["id"])
            file_flight_log(slot["id"], hobbs_out=100.0 + i * 100,
                            hobbs_in=101.0 + i * 100,
                            pickup_outcome=outcome)
        pilot = validate_success(api.get_pilot(sc["pilot"]["id"], ADMIN),
                                 expected_status=200)
        assert pilot["season_hours_flown"] == pytest.approx(3.0, abs=0.001)
        assert pilot["season_pickup_failure_count"] == 2, (
            f"only FAILED logs increment the counter, got "
            f"{pilot['season_pickup_failure_count']}"
        )
        assert pilot["status"] == "ACTIVE", (
            f"two failures do not suspend, got {pilot['status']}"
        )


class TestPilotSuspensionCascade:

    def test_suspension_reverts_scheduled_slot_to_booked(self, api):
        """PRD §3.6: "when that count reaches three — exactly three suspends,
        two does not — the pilot is automatically suspended to `SUSPENDED`,
        and every `SCHEDULED` slot assigned to that pilot reverts to `BOOKED`
        with its `assigned_pilot_id` cleared for re-selection."

        The third FAILED log suspends the pilot; the slot still scheduled
        for later that day reverts.

        Design: Difficulty/transitive_cascade/pilot_suspension_cascade_depth2
        """
        sc = setup_operation(base_code="KPS1",
                             window_start="2026-08-13T12:00:00Z",
                             window_end="2026-08-13T19:00:00Z")
        s1, s2, s3, s4 = (book_slot_in(
            sc, planned_start=f"2026-08-13T{h:02d}:00:00Z",
            planned_duration_hours=1) for h in (14, 15, 16, 17))
        for i, slot in enumerate((s1, s2)):
            schedule_slot(slot["id"])
            file_flight_log(slot["id"], hobbs_out=100.0 + i * 100,
                            hobbs_in=101.0 + i * 100, pickup_outcome="FAILED")
        schedule_slot(s3["id"])
        schedule_slot(s4["id"])
        file_flight_log(s3["id"], hobbs_out=300.0, hobbs_in=301.0,
                        pickup_outcome="FAILED")
        pilot = validate_success(api.get_pilot(sc["pilot"]["id"], ADMIN),
                                 expected_status=200)
        assert pilot["status"] == "SUSPENDED"
        assert pilot["season_pickup_failure_count"] == 3
        s4_after = get_slot(s4["id"])
        assert s4_after["status"] == "BOOKED", (
            f"SCHEDULED slot of a suspended pilot must revert to BOOKED, "
            f"got {s4_after['status']}"
        )
        assert s4_after["assigned_pilot_id"] is None, (
            f"assigned_pilot_id must be cleared for re-selection, got "
            f"{s4_after['assigned_pilot_id']}"
        )

    def test_suspension_reverts_every_scheduled_slot(self, api):
        """PRD §3.6: "every `SCHEDULED` slot assigned to that pilot reverts
        to `BOOKED` with its `assigned_pilot_id` cleared for re-selection."

        Two scheduled slots are both swept by the same suspension cascade.

        Design: Difficulty/transitive_cascade/pilot_suspension_cascade_depth2
        """
        sc = setup_operation(base_code="KPS2",
                             window_start="2026-08-13T12:00:00Z",
                             window_end="2026-08-13T19:00:00Z")
        s1, s2, s3, s4, s5 = (book_slot_in(
            sc, planned_start=f"2026-08-13T{h:02d}:00:00Z",
            planned_duration_hours=1) for h in (12, 13, 14, 15, 16))
        for i, slot in enumerate((s1, s2)):
            schedule_slot(slot["id"])
            file_flight_log(slot["id"], hobbs_out=100.0 + i * 100,
                            hobbs_in=101.0 + i * 100, pickup_outcome="FAILED")
        schedule_slot(s3["id"])
        schedule_slot(s4["id"])
        schedule_slot(s5["id"])
        file_flight_log(s3["id"], hobbs_out=300.0, hobbs_in=301.0,
                        pickup_outcome="FAILED")
        pilot = validate_success(api.get_pilot(sc["pilot"]["id"], ADMIN),
                                 expected_status=200)
        assert pilot["status"] == "SUSPENDED"
        for trailing in (s4, s5):
            after = get_slot(trailing["id"])
            assert after["status"] == "BOOKED", (
                f"every SCHEDULED slot must revert to BOOKED, got "
                f"{after['status']} for {trailing['id']}"
            )
            assert after["assigned_pilot_id"] is None
