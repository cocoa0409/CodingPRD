"""Rolling stock maintenance cycle, turnaround buffer, retirement, and consist gating
on stock state (PRD §3.2, §3.3, §2.7)."""
import pytest

from test_helpers import (
    MECH,
    SCHED,
    assert_car_assignment,
    assign_car,
    complete_work_order,
    create_active_agreement,
    create_car_assignment_payload,
    create_draft_excursion,
    create_open_slot,
    create_scheduled_work_order,
    create_work_order_payload,
    retire_stock,
    roster_stock,
    setup_draft_excursion,
    setup_published_excursion,
    start_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestMaintenanceCycle:
    """AVAILABLE -> IN_MAINTENANCE -> AVAILABLE via work-order START/COMPLETE."""

    def test_stock_maintenance_cycle_statuses(self, api, mechanic_headers):
        """PRD §3.2: "Starting a work order — the `START` event by a `Mechanic` —
        requires the unit to be `AVAILABLE` and moves the order `SCHEDULED → IN_PROGRESS`
        while the unit itself flips `AVAILABLE → IN_MAINTENANCE`. Completing it — the
        `COMPLETE` event — moves the order `IN_PROGRESS → COMPLETED`, and the unit returns
        to `AVAILABLE` only if no other work order for it remains `IN_PROGRESS`".

        Design: Difficulty/non_linear_state_machine/rolling_stock_available_maintenance_cycle
        """
        car = roster_stock("COACH-9", "COACH_CAR", 40, 0)
        assert car["status"] == "AVAILABLE"
        wo = create_scheduled_work_order(car["id"], window_start="2026-10-20T09:00:00Z",
                                         window_end="2026-10-20T11:00:00Z", scope="INSPECTION")

        validate_success(api.work_order_event(wo["id"], {"event_type": "START"}, mechanic_headers), 200)
        mid = validate_success(api.get_rolling_stock(car["id"], mechanic_headers), 200)
        assert mid["status"] == "IN_MAINTENANCE", "START flips the unit to IN_MAINTENANCE"

        wo_after = validate_success(
            api.work_order_event(wo["id"], {"event_type": "COMPLETE"}, mechanic_headers), 200)
        assert wo_after["status"] == "COMPLETED"
        end = validate_success(api.get_rolling_stock(car["id"], mechanic_headers), 200)
        assert end["status"] == "AVAILABLE", "COMPLETE closes the loop back to AVAILABLE"

    def test_stock_version_advances_on_each_leg(self, api, mechanic_headers):
        """PRD §2.4: "`version` is an integer that starts at 1 at creation and
        increments by exactly 1 on every mutation of the resource, including automatic
        reconciliations."
        PRD §3.2: "Starting a work order — the `START` event by a `Mechanic` — requires
        the unit to be `AVAILABLE` and moves the order `SCHEDULED → IN_PROGRESS` while
        the unit itself flips `AVAILABLE → IN_MAINTENANCE`."

        Design: Difficulty/non_linear_state_machine/rolling_stock_available_maintenance_cycle
        """
        car = roster_stock("COACH-9", "COACH_CAR", 40, 0)
        assert car["version"] == 1, "creation starts the version at 1"
        wo = create_scheduled_work_order(car["id"], window_start="2026-10-20T09:00:00Z",
                                         window_end="2026-10-20T11:00:00Z", scope="INSPECTION")

        start_work_order(wo["id"])
        mid = validate_success(api.get_rolling_stock(car["id"], mechanic_headers), 200)
        assert mid["version"] == 2, "+1 when the unit flips to IN_MAINTENANCE"

        complete_work_order(wo["id"])
        end = validate_success(api.get_rolling_stock(car["id"], mechanic_headers), 200)
        assert end["version"] == 3, "+1 again when the unit returns to AVAILABLE"
        assert end["status"] == "AVAILABLE"


class TestTurnaroundBuffer:
    """The 60-minute turnaround buffer between work orders on the same unit."""

    def test_turnaround_buffer_30_min_gap_rejected(self, api, mechanic_headers):
        """PRD §2.7: "between two `SCHEDULED` or `IN_PROGRESS` work orders on the same
        unit there must be a gap of at least 60 minutes — the turnaround buffer — so
        mere adjacency without a 60-minute gap is a conflict, not a convenience."

        Design: Difficulty/resource_temporal_overlap/maintenance_turnaround_buffer_required
        """
        car = roster_stock("COACH-1", "COACH_CAR", 40, 0)
        create_scheduled_work_order(car["id"], window_start="2026-10-20T09:00:00Z",
                                    window_end="2026-10-20T11:00:00Z")

        # 30-minute gap after the first window ends at 11:00 -> inside the buffer
        res = api.create_work_order(
            create_work_order_payload(car["id"], window_start="2026-10-20T11:30:00Z",
                                      window_end="2026-10-20T13:00:00Z", scope="REPAIR"),
            mechanic_headers)
        validate_error(res, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT.value, expected_status=409)

    def test_turnaround_buffer_60_min_gap_accepted(self, api, mechanic_headers):
        """PRD §2.7: "between two `SCHEDULED` or `IN_PROGRESS` work orders on the same
        unit there must be a gap of at least 60 minutes — the turnaround buffer — so
        mere adjacency without a 60-minute gap is a conflict, not a convenience."

        Design: Difficulty/resource_temporal_overlap/maintenance_turnaround_buffer_required
        """
        car = roster_stock("COACH-1", "COACH_CAR", 40, 0)
        create_scheduled_work_order(car["id"], window_start="2026-10-20T09:00:00Z",
                                    window_end="2026-10-20T11:00:00Z")

        # Exactly 60 minutes of gap (11:00 end -> 12:00 start) satisfies the buffer
        res = api.create_work_order(
            create_work_order_payload(car["id"], window_start="2026-10-20T12:00:00Z",
                                      window_end="2026-10-20T14:00:00Z", scope="REPAIR"),
            mechanic_headers)
        wo2 = validate_success(res, 201)
        assert wo2["status"] == "SCHEDULED", "exactly 60-minute gap accepted"


class TestCarAssignRequiresAvailableStock:
    """CarAssignment -> RollingStock state dependency."""

    def _setup_in_maintenance_stock_and_draft_excursion(self, api):
        coach = roster_stock("COACH-1", "COACH_CAR", 40, 0)
        wo = create_scheduled_work_order(coach["id"], window_start="2026-10-20T09:00:00Z",
                                         window_end="2026-10-20T11:00:00Z", scope="REPAIR")
        start_work_order(wo["id"])
        scenario = setup_draft_excursion(car_specs=[], with_crew=False)
        return coach, wo, scenario

    def test_car_assign_in_maintenance_rejected(self, api, scheduler_headers):
        """PRD §3.3: "The unit must be `AVAILABLE` — `IN_MAINTENANCE` yields
        `ERR_STOCK_UNAVAILABLE`, `OUT_OF_SERVICE` yields `ERR_STOCK_OUT_OF_SERVICE`".

        Design: Difficulty/cross_entity_state_dependency/car_assign_requires_available_stock
        """
        coach, wo, scenario = self._setup_in_maintenance_stock_and_draft_excursion(api)
        res = api.create_car_assignment(
            create_car_assignment_payload(scenario["excursion"]["id"], coach["id"], "COACH", 1),
            scheduler_headers)
        validate_error(res, ApiErrorId.ERR_STOCK_UNAVAILABLE.value, expected_status=409)
        stock = validate_success(api.get_rolling_stock(coach["id"], scheduler_headers), 200)
        assert stock["status"] == "IN_MAINTENANCE", "rejection leaves the stock state untouched"

    def test_car_assign_succeeds_after_maintenance_completes(self, api, scheduler_headers):
        """PRD §3.2: "Completing it — the `COMPLETE` event — moves the order
        `IN_PROGRESS → COMPLETED`, and the unit returns to `AVAILABLE` only if no other
        work order for it remains `IN_PROGRESS`".
        PRD §3.3: "At assignment time the unit's `seat_capacity` is snapshotted into the
        assignment's `effective_capacity`, insulating the excursion's sellable inventory
        from later roster edits."

        Design: Difficulty/cross_entity_state_dependency/car_assign_requires_available_stock
        """
        coach, wo, scenario = self._setup_in_maintenance_stock_and_draft_excursion(api)
        complete_work_order(wo["id"])

        res = api.create_car_assignment(
            create_car_assignment_payload(scenario["excursion"]["id"], coach["id"], "COACH", 1),
            scheduler_headers)
        assignment = validate_success(res, 201)
        assert_car_assignment(assignment)
        assert assignment["effective_capacity"] == 40, "seat_capacity snapshotted at assignment"
        assert assignment["class_code"] == "COACH"


def test_retire_cancels_scheduled_work_orders_and_strips_draft_consist(api, mechanic_headers,
                                                                       scheduler_headers):
    """PRD §3.2: "Retirement ripples outward: every `SCHEDULED` work order for the unit
    is cancelled (`SCHEDULED → CANCELLED`), and the unit's car assignments are stripped
    from any `DRAFT` excursions, with each affected excursion's `version` incrementing
    by 1."
    PRD §3.3: "Every consist change — add or removal — increments the excursion's
    `version`."

    Design: Corner/state_machines/retire_cancels_scheduled_work_orders_and_strips_draft_consist
    """
    scenario = setup_draft_excursion(car_specs=[], with_crew=False)
    excursion = scenario["excursion"]
    ex_v0 = excursion["version"]

    coach = roster_stock("COACH-1", "COACH_CAR", 40, 0)
    wo = create_scheduled_work_order(coach["id"], window_start="2026-10-20T09:00:00Z",
                                     window_end="2026-10-20T10:00:00Z", scope="OVERHAUL")
    assign_car(excursion["id"], coach["id"], "COACH", 1)

    retired = retire_stock(coach["id"])
    assert retired["status"] == "OUT_OF_SERVICE"

    wo_data, _ = validate_paginated(api.list_stock_work_orders(coach["id"], mechanic_headers))
    assert len(wo_data) == 1
    assert wo_data[0]["id"] == wo["id"]
    assert wo_data[0]["status"] == "CANCELLED", "retire cascade cancels SCHEDULED work orders"

    ca_data, _ = validate_paginated(
        api.list_car_assignments(scheduler_headers, params={"excursion_id": excursion["id"]}))
    assert ca_data == [], "assignment stripped from the DRAFT excursion's consist"

    ex_after = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)
    assert ex_after["version"] == ex_v0 + 2, (
        "one bump for the assignment add, one for its removal on retire")


def test_assign_retired_stock_rejected(api, scheduler_headers, mechanic_headers):
    """PRD §3.3: "The unit must be `AVAILABLE` — `IN_MAINTENANCE` yields
    `ERR_STOCK_UNAVAILABLE`, `OUT_OF_SERVICE` yields `ERR_STOCK_OUT_OF_SERVICE`".

    Design: Corner/validations/assign_retired_stock_rejected
    """
    coach = roster_stock("COACH-1", "COACH_CAR", 40, 0)
    retire_stock(coach["id"])
    scenario = setup_draft_excursion(car_specs=[], with_crew=False)

    res = api.create_car_assignment(
        create_car_assignment_payload(scenario["excursion"]["id"], coach["id"], "COACH", 1),
        scheduler_headers)
    validate_error(res, ApiErrorId.ERR_STOCK_OUT_OF_SERVICE.value, expected_status=409)


def test_wo_create_overlapping_published_excursion_rejected(api, mechanic_headers):
    """PRD §3.2: "and the window must not intersect the `service_date` of a `PUBLISHED`
    or `BOARDING` excursion whose consist already includes this unit, otherwise
    `ERR_STOCK_COMMITTED`."

    Design: Corner/validations/wo_create_overlapping_published_excursion_rejected
    """
    scenario = setup_published_excursion()
    coach = scenario["cars"]["COACH-1"]["stock"]

    res = api.create_work_order(
        create_work_order_payload(coach["id"], window_start="2026-10-15T07:00:00Z",
                                  window_end="2026-10-15T09:00:00Z", scope="INSPECTION"),
        mechanic_headers)
    validate_error(res, ApiErrorId.ERR_STOCK_COMMITTED.value, expected_status=409)
