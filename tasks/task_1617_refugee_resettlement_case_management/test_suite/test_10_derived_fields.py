"""Derived fields (PRD §2.8, §3.2, §3.3): case posture against the logical
clock, derived housing-unit status, and the vacate/rebook input-set rule.
"""
from test_helpers import (
    validate_success, make_case,
    make_housing_unit,
    make_housing_setup, vacate_setup, get_housing_unit, get_case,
    set_clock, setup_arrived_case,
)
from test_helpers.fixtures import CM, HC


class TestPostureTransitionsWithClock:
    def _arrived_case(self):
        # 30-day benchmarks of a case arrived 2026-08-10 are due 2026-09-09.
        return setup_arrived_case(case_number="CASE-CA1", household_size=1)

    def test_on_track_when_nearest_due_date_beyond_window(self, api):
        """PRD §3.3: "If any of the case's benchmarks is `PENDING` with a
        `due_date` strictly before today, the posture is `OVERDUE`.
        Otherwise, if any `PENDING` benchmark has a `due_date` on or before
        today plus a seven-day look-ahead window, the posture is `AT_RISK`.
        Otherwise the posture is `ON_TRACK`."

        Design: Corner/calculations/posture_transitions_with_clock
        """
        ctx = self._arrived_case()
        set_clock("2026-08-10T00:00:00Z")
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["posture"] == "ON_TRACK"

    def test_due_exactly_today_is_at_risk_not_overdue(self, api):
        """PRD §3.3: "The boundary matters: a benchmark due exactly today is
        `AT_RISK`, not `OVERDUE` — overdue requires the due date to be
        strictly in the past."

        Design: Corner/calculations/posture_transitions_with_clock
        """
        ctx = self._arrived_case()
        set_clock("2026-09-09T00:00:00Z")
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["posture"] == "AT_RISK"

    def test_one_day_past_due_is_overdue(self, api):
        """PRD §3.3: "If any of the case's benchmarks is `PENDING` with a
        `due_date` strictly before today, the posture is `OVERDUE`." and
        "overdue requires the due date to be strictly in the past."

        Design: Corner/calculations/posture_transitions_with_clock
        """
        ctx = self._arrived_case()
        set_clock("2026-09-10T00:00:00Z")
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["posture"] == "OVERDUE"


class TestHousingOccupancyConservation:
    def test_create_makes_unit_reserved(self, api):
        """PRD §3.2: "A fresh setup starts `PREPARING` with
        `furnishing_items_completed` empty, and its creation immediately
        recomputes the unit's derived status to `RESERVED` (or `OCCUPIED` if
        the window already covers today)." and "Otherwise, if at least one
        non-terminal setup exists for the unit, it reads `RESERVED`.
        Otherwise it reads `AVAILABLE`."

        Design: Difficulty/compensating_invariant/housing_occupancy_conservation
        """
        case = make_case(case_number="CASE-CI1", household_size=1)
        unit = make_housing_unit(address="210 Hickory St", bedrooms=1)
        assert get_housing_unit(unit["id"], headers=HC)["status"] == "AVAILABLE"
        make_housing_setup(case["id"], unit["id"],
                           occupancy_start="2026-08-10",
                           occupancy_end="2027-02-10")
        # Default clock 2026-08-01 is before occupancy_start, so the window
        # does not cover today and the unit reads RESERVED.
        assert get_housing_unit(unit["id"], headers=HC)["status"] == "RESERVED"

    def test_vacate_restores_available_and_terminal_setup(self, api):
        """PRD §3.2: "Vacating a setup — manually or through the transfer
        cascade — removes it from the non-terminal set, so the unit falls
        back to `AVAILABLE` unless another non-terminal setup still covers
        it." and "A setup in any of `PREPARING`, `READY`, or `OCCUPIED` may
        also be vacated by the coordinator, moving it to the terminal
        `VACATED` state and recomputing its unit's derived status."

        Design: Difficulty/compensating_invariant/housing_occupancy_conservation
        """
        case = make_case(case_number="CASE-CI1B", household_size=1)
        unit = make_housing_unit(address="211 Hickory St", bedrooms=1)
        setup = make_housing_setup(case["id"], unit["id"],
                                   occupancy_start="2026-08-10",
                                   occupancy_end="2027-02-10")
        vacated = vacate_setup(setup["id"])
        assert vacated["status"] == "VACATED"
        assert get_housing_unit(unit["id"], headers=HC)["status"] == "AVAILABLE"
        setups = validate_success(api.list_unit_housing_setups(unit["id"], HC))
        assert len(setups) == 1
        assert setups[0]["status"] == "VACATED"


class TestUnitRebookableAfterVacate:
    def test_overlapping_vacated_window_does_not_conflict(self, api):
        """PRD §3.2: "the new occupancy window must not overlap the window of
        any other non-terminal setup on the same unit, where overlap is
        judged on half-open intervals so a window starting the day another
        ends is allowed" and "A unit's `status` is never stored; it is
        derived on every read from the unit's non-terminal housing setups —
        those in `PREPARING`, `READY`, or `OCCUPIED`, with `VACATED` setups
        excluded".

        Design: Corner/calculations/unit_rebookable_after_vacate
        """
        case_a = make_case(case_number="CASE-CA4A", household_size=1)
        unit = make_housing_unit(address="440 Mulberry St", bedrooms=1)
        setup_a = make_housing_setup(case_a["id"], unit["id"],
                                     occupancy_start="2026-08-10",
                                     occupancy_end="2027-02-10")
        vacate_setup(setup_a["id"])
        case_b = make_case(case_number="CASE-CA4B", household_size=1,
                           scheduled_arrival_date="2026-09-01")
        resp = api.create_housing_setup(
            {"case_id": case_b["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2026-09-01", "occupancy_end": "2027-03-01"}, HC)
        setup_b = validate_success(resp, 201)
        assert setup_b["status"] == "PREPARING"
