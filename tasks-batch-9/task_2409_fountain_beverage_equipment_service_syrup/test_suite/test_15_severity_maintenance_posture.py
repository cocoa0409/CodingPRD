"""Severity grading, the filter derate, the due ladder and the posture bands.

Each test pins one edge of an integer or threshold rule: the symptom weight standing
alone, the exact urgent boundary, the score cap, the hardness derate on both sides of
the baseline, the three calendar outcomes of a due evaluation, and the posture bands
walked one overdue task at a time.
"""

import pytest

from test_helpers import (
    activate_agreement,
    complete_task,
    create_agreement,
    create_call,
    create_outlet,
    create_task,
    create_unit,
    evaluate_task,
    pin_clock,
    place_compliance_hold,
    read_outlet,
    read_unit,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
OFFICER = TEST_USERS["officer_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet_and_unit(activate=False, **outlet_overrides):
    """Riverside Diner with one machine placed under an 8000-gallon agreement."""
    pin_clock(CLOCK)
    outlet = create_outlet(
        name="Riverside Diner",
        account_code="OUT-1001",
        region_code="R-WEST",
        **outlet_overrides,
    )
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    if activate:
        activate_agreement(agreement["id"])
    return outlet, unit


class TestServiceCallSeverity:
    def test_a_leak_at_a_clean_outlet_scores_only_its_symptom_weight(self, api):
        """PRD §3.8: "The grade starts from the symptom's own weight: `NO_POUR` is worth
        60 points, `LEAK` 55, `OFF_RATIO` 40, `CO2_LOW` 30 and `ICE_FAULT` 25." With no
        surcharge to add, the band rule decides: "The `severity` band follows from the
        score with inclusive lower bounds: a score of 85 or more is `CRITICAL`, a score
        of 60 or more but under 85 is `URGENT`, and anything below 60 is `ROUTINE` — a
        score of exactly 85 is `CRITICAL` and a score of exactly 60 is `URGENT`."

        Design: Corner/calculations/severity_symptom_weight_alone_at_open_posture
        """
        outlet, unit = _outlet_and_unit(activate=True)
        assert read_outlet(outlet["id"])["service_posture"] == "OPEN"

        call = create_call(unit["id"], "LEAK", CLOCK)
        assert call["severity_score"] == 55
        assert call["severity"] == "ROUTINE"

    def test_a_score_of_exactly_sixty_is_urgent(self, api):
        """PRD §3.8: "The outlet's compliance posture adds nothing when `OPEN`, 15
        points when `RESTRICTED` and 30 points when `FROZEN`. The outlet's overdue
        maintenance adds 5 points for each task counted in `overdue_task_count`, but
        that component is capped at 20 points, so a fifth overdue task adds nothing
        further." The band edge is inclusive: "a score of exactly 85 is `CRITICAL` and a
        score of exactly 60 is `URGENT`."

        Design: Corner/calculations/severity_exactly_at_the_urgent_band_boundary
        """
        outlet, unit = _outlet_and_unit(activate=True)
        task = create_task(unit["id"], "PREVENTIVE", "2026-07-01T00:00:00Z")
        evaluate_task(task["id"], OFFICER)
        graded_against = read_outlet(outlet["id"])
        assert graded_against["overdue_task_count"] == 1
        assert graded_against["service_posture"] == "RESTRICTED"

        call = create_call(unit["id"], "OFF_RATIO", CLOCK)
        assert call["severity_score"] == 60
        assert call["severity"] == "URGENT"

    def test_a_sum_of_one_hundred_twenty_is_stored_as_one_hundred(self, api):
        """PRD §3.8: "A machine whose `calibration_status` is `OUT_OF_SPEC` adds a
        further 10 points. The sum of the base weight and the three surcharges is then
        capped at 100 and stored as `severity_score`." The failing measurement is what
        puts the machine there, per §3.3: "A `PASS` sets the unit's `calibration_status`
        to `IN_SPEC` and a `FAIL` sets it to `OUT_OF_SPEC`; in both cases the measured
        value is written to the unit's `brix_ratio_last_measured` and the unit's
        `version` advances by one."

        Design: Corner/calculations/severity_score_cap_clamps_a_sum_of_one_hundred_twenty
        """
        outlet, unit = _outlet_and_unit(activate=True)
        for day in ("01", "02", "03", "04"):
            overdue = create_task(unit["id"], "PREVENTIVE", f"2026-07-{day}T00:00:00Z")
            evaluate_task(overdue["id"], OFFICER)
        calibration = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-20T00:00:00Z")
        complete_task(calibration["id"], TECH, measured_brix_ratio=5.40)

        frozen = read_outlet(outlet["id"])
        assert frozen["overdue_task_count"] == 4
        assert frozen["service_posture"] == "FROZEN"
        assert read_unit(unit["id"])["calibration_status"] == "OUT_OF_SPEC"

        call = create_call(unit["id"], "NO_POUR", CLOCK)
        assert call["severity_score"] == 100
        assert call["severity"] == "CRITICAL"


class TestFilterIntervalDerate:
    def test_hard_water_shortens_the_stored_interval(self, api):
        """PRD §3.5: "The stored `effective_gallon_interval` is the submitted
        `gallon_interval` multiplied by a factor of one minus two percent for every
        grain per gallon by which the outlet's `water_hardness_gpg` exceeds the baseline
        of 10, where hardness at or below the baseline contributes nothing to the
        derate, and the result is rounded half up to two decimal places."

        Design: Corner/calculations/maintenance_hardness_derate_applied_to_the_filter_interval
        """
        _outlet, unit = _outlet_and_unit(water_hardness_gpg=18)

        task = create_task(
            unit["id"], "FILTER_CHANGE", "2026-09-01T00:00:00Z", gallon_interval=4000
        )
        assert task["gallon_interval"] == 4000
        assert task["effective_gallon_interval"] == pytest.approx(3360.00, abs=0.01)
        assert task["status"] == "SCHEDULED"
        assert task["breach_kind"] is None

    def test_soft_water_earns_no_credit_at_all(self, api):
        """PRD §3.5: "The stored `effective_gallon_interval` is the submitted
        `gallon_interval` multiplied by a factor of one minus two percent for every
        grain per gallon by which the outlet's `water_hardness_gpg` exceeds the baseline
        of 10, where hardness at or below the baseline contributes nothing to the
        derate, and the result is rounded half up to two decimal places."

        Design: Corner/calculations/maintenance_no_derate_below_the_hardness_baseline
        """
        _outlet, unit = _outlet_and_unit(water_hardness_gpg=6)

        task = create_task(
            unit["id"], "FILTER_CHANGE", "2026-09-01T00:00:00Z", gallon_interval=4000
        )
        assert task["effective_gallon_interval"] == pytest.approx(4000.00, abs=0.01)
        assert task["gallon_interval"] == 4000


class TestDueEvaluationLadder:
    def test_a_deadline_reached_this_very_instant_is_only_due(self, api):
        """PRD §3.5: "Otherwise, if the logical clock is at or past `due_at` but still
        inside that three-day grace band, the `breach_kind` becomes `DATE` and the task
        moves to `DUE`. A clock sitting exactly at `due_at` yields `DUE`."

        Design: Corner/calculations/maintenance_clock_exactly_at_due_at_is_due_not_overdue
        """
        outlet, unit = _outlet_and_unit()
        task = create_task(unit["id"], "PREVENTIVE", "2026-08-01T00:00:00Z")

        evaluated = evaluate_task(task["id"], OFFICER)
        assert evaluated["status"] == "DUE"
        assert evaluated["breach_kind"] == "DATE"

        after = read_outlet(outlet["id"])
        assert after["overdue_task_count"] == 0
        assert after["service_posture"] == "OPEN"

    def test_a_grace_band_expiring_on_the_instant_is_already_overdue(self, api):
        """PRD §3.5: "Otherwise, if the logical clock is at or past the task's `due_at`
        plus a 72-hour grace band, the `breach_kind` becomes `DATE` and the task goes to
        `OVERDUE`." Landing there is never quiet: "Both moves that land in `OVERDUE`
        additionally raise the owning outlet's `overdue_task_count` by one and recompute
        `service_posture`, and where that recomputation lands on `FROZEN` the outlet's
        `PENDING` stops are skipped and their allocations released as in §2.10."

        Design: Corner/calculations/maintenance_grace_expiring_exactly_at_seventy_two_hours_is_overdue
        """
        outlet, unit = _outlet_and_unit()
        task = create_task(unit["id"], "PREVENTIVE", "2026-07-29T00:00:00Z")

        evaluated = evaluate_task(task["id"], OFFICER)
        assert evaluated["status"] == "OVERDUE"
        assert evaluated["breach_kind"] == "DATE"

        after = read_outlet(outlet["id"])
        assert after["overdue_task_count"] == 1
        assert after["service_posture"] == "RESTRICTED"

    def test_an_evaluation_before_the_deadline_changes_nothing(self, api):
        """PRD §3.5: "Otherwise nothing has been breached: `breach_kind` stays null, the
        task's `status` is left exactly where it was, and because nothing was mutated the
        task's `version` does not advance."

        Design: Corner/calculations/maintenance_before_due_at_leaves_the_task_scheduled
        """
        outlet, unit = _outlet_and_unit()
        task = create_task(unit["id"], "PREVENTIVE", "2026-08-05T00:00:00Z")

        evaluated = evaluate_task(task["id"], OFFICER)
        assert evaluated["status"] == "SCHEDULED"
        assert evaluated["breach_kind"] is None

        after = read_outlet(outlet["id"])
        assert after["overdue_task_count"] == 0
        assert after["service_posture"] == "OPEN"


class TestPostureBands:
    def test_the_third_overdue_task_is_the_one_that_freezes_the_outlet(self, api):
        """PRD §2.10: "It is recomputed from the outlet's own two counters —
        `open_compliance_hold_count` and `overdue_task_count` — immediately after either
        counter changes, by a rule evaluated top to bottom in which the first matching
        clause wins: if the outlet has at least one open compliance hold **or** at least
        three overdue maintenance tasks the posture is `FROZEN`; otherwise, if it has at
        least one overdue maintenance task the posture is `RESTRICTED`; otherwise the
        posture is `OPEN`."

        Design: Corner/calculations/posture_bands_walk_open_restricted_restricted_frozen
        """
        outlet, unit = _outlet_and_unit()
        tasks = [
            create_task(unit["id"], "PREVENTIVE", "2026-07-01T00:00:00Z")
            for _ in range(3)
        ]
        opening = read_outlet(outlet["id"])
        assert opening["overdue_task_count"] == 0
        assert opening["service_posture"] == "OPEN"

        expected = [(1, "RESTRICTED"), (2, "RESTRICTED"), (3, "FROZEN")]
        for task, (count, posture) in zip(tasks, expected):
            evaluate_task(task["id"], OFFICER)
            walked = read_outlet(outlet["id"])
            assert walked["overdue_task_count"] == count
            assert walked["service_posture"] == posture

    def test_a_hold_freezes_an_outlet_that_owes_no_maintenance(self, api):
        """PRD §2.10: "Because the frozen clause is tested first, an outlet under a
        compliance hold is `FROZEN` even when it has zero overdue tasks."

        Design: Corner/calculations/posture_frozen_by_a_hold_with_zero_overdue_tasks
        """
        pin_clock(CLOCK)
        outlet = create_outlet(
            name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
        )

        held = place_compliance_hold(
            outlet["id"], OFFICER, hold_reason_code="SANITATION_LAPSE"
        )
        assert held["open_compliance_hold_count"] == 1
        assert held["overdue_task_count"] == 0
        assert held["service_posture"] == "FROZEN"
        assert held["status"] == "ACTIVE"
