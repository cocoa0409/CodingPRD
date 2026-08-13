"""Task submission: dual strength variants, classification boundaries, and the
evidence/hazard gates (PRD §3.3); REPLACED-pole lockout (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_budget,
    create_crew,
    create_inspection_task_payload,
    create_manual_task,
    create_open_cycle,
    create_pole,
    default_photos,
    fund_order,
    get_pole,
    get_task,
    list_audits,
    make_contractor_headers,
    make_inspector_headers,
    qa_review_task,
    setup_open_cycle_with_task,
    submit_task,
    validate_error,
    validate_paginated,
    validate_success,
)

# Readings on a SOUTHERN_PINE class-3 pole (required shell 2.00) that make the two
# strength variants diverge (PRD §3.3): conservative 54.00 / statistical 73.40.
DIVERGENT_READINGS = dict(
    shell_thickness_in=1.50, sound_wood_pct=80, decay_pocket_depth_in=1.2,
    moisture_pct=25, hazard_flag=False,
)
# Readings that compute effective_rs 28.00 (REJECT_PRIORITY) on a class-3
# SOUTHERN_PINE pole under the CONSERVATIVE policy.
PRIORITY_REJECT_READINGS = dict(
    shell_thickness_in=2.00, sound_wood_pct=30, decay_pocket_depth_in=0.4,
    moisture_pct=25,
)


class TestDualStrengthVariants:
    def _submit_divergent(self, api, program_manager_headers):
        pole = create_pole(pole_number="P-DV1", species="SOUTHERN_PINE",
                           original_class="3", install_date="1990-01-01",
                           gis_tag="URBAN")
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0,
                                  strength_variant_policy="CONSERVATIVE")
        task = create_manual_task(cycle["id"], pole["id"])
        submitted = submit_task(task["id"], **DIVERGENT_READINGS)
        return pole, cycle, submitted

    def test_strength_variants_diverge_on_same_readings_values(
            self, api, program_manager_headers):
        """PRD §3.3: "Submission computes the pole's remaining strength twice, under
        two variants, and stores both on the task."
        PRD §3.3: "The task's `effective_rs_pct` is then the single variant selected by
        the owning cycle's `strength_variant_policy`."
        PRD §3.3: "at least 45.00 but below 60.00 yields `MONITOR`".

        Design: Difficulty/dual_variant_calc/strength_variants_diverge_on_same_readings
        """
        _, _, submitted = self._submit_divergent(api, program_manager_headers)
        assert submitted["rs_conservative_pct"] == pytest.approx(54.00, abs=0.005), (
            f"conservative variant: got {submitted['rs_conservative_pct']}"
        )
        assert submitted["rs_statistical_pct"] == pytest.approx(73.40, abs=0.005), (
            f"statistical variant: got {submitted['rs_statistical_pct']}"
        )
        assert submitted["effective_rs_pct"] == pytest.approx(54.00, abs=0.005), (
            "CONSERVATIVE policy selects the conservative variant"
        )
        assert submitted["classification"] == "MONITOR"

    def test_strength_variants_diverge_pole_untouched_by_submit(
            self, api, program_manager_headers):
        """PRD §3.3: "A successful submission stamps `submitted_by_user_id` from the
        caller's `X-User-ID` — the value that later drives segregation of duties — and
        moves the task from `OPEN` to `SUBMITTED`."
        PRD §3.4: "An `ACCEPT` decision moves the task to the terminal `ACCEPTED`
        state and runs the pole's classification cascade."

        Design: Difficulty/dual_variant_calc/strength_variants_diverge_on_same_readings
        """
        pole, _, submitted = self._submit_divergent(api, program_manager_headers)
        assert submitted["submitted_by_user_id"] == "insp-1"
        after = get_pole(pole["id"])
        assert after["current_classification"] == "NONE"
        assert after["current_remaining_strength_pct"] is None
        assert after["last_inspection_date"] is None
        assert after["status"] == "IN_SERVICE"


class TestClassificationBoundary:
    def _two_boundary_tasks(self, api):
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0,
                                  strength_variant_policy="CONSERVATIVE")
        p1 = create_pole(pole_number="P-B60")
        p2 = create_pole(pole_number="P-B59")
        t1 = create_manual_task(cycle["id"], p1["id"])
        t2 = create_manual_task(cycle["id"], p2["id"])
        return t1, t2

    def test_classification_boundary_60_is_serviceable(self, api, program_manager_headers):
        """PRD §3.3: "The comparisons run against the two-decimal rounded value, so an
        effective strength of exactly 60.00 is `SERVICEABLE`, exactly 45.00 is
        `MONITOR`, and exactly 30.00 is `REJECT_ROUTINE`."

        Design: Difficulty/boundary_precision_check/classification_boundary_exactly_60_is_serviceable
        """
        t1, _ = self._two_boundary_tasks(api)
        submitted = submit_task(
            t1["id"], shell_thickness_in=2.00, sound_wood_pct=62,
            decay_pocket_depth_in=0.4, moisture_pct=25,
        )
        assert submitted["effective_rs_pct"] == pytest.approx(60.00, abs=0.005)
        assert submitted["classification"] == "SERVICEABLE", (
            "inclusive lower bound: exactly 60.00 is SERVICEABLE"
        )

    def test_classification_boundary_59_90_is_monitor(self, api, program_manager_headers):
        """PRD §3.3: "at least 60.00 yields `SERVICEABLE`; at least 45.00 but below
        60.00 yields `MONITOR`".

        Design: Difficulty/boundary_precision_check/classification_boundary_exactly_60_is_serviceable
        """
        _, t2 = self._two_boundary_tasks(api)
        submitted = submit_task(
            t2["id"], shell_thickness_in=2.00, sound_wood_pct=61.9,
            decay_pocket_depth_in=0.4, moisture_pct=25,
        )
        assert submitted["effective_rs_pct"] == pytest.approx(59.90, abs=0.005)
        assert submitted["classification"] == "MONITOR", (
            "one step below the inclusive boundary classifies MONITOR"
        )


class TestMoistureDerate:
    def test_moisture_derate_applies_over_threshold(self, api, program_manager_headers):
        """PRD §3.3: "From that base it subtracts a decay penalty of 5.0 points per
        inch of `decay_pocket_depth_in`, and finally applies a moisture derate: when
        `moisture_pct` exceeds 30.0 the result is multiplied by 0.95, otherwise by 1.00.
        The outcome is clamped between 0 and 100 and stored as `rs_conservative_pct`."

        Design: Corner/calculations/moisture_derate_applies_over_threshold
        """
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0,
                                  strength_variant_policy="CONSERVATIVE")
        p_wet = create_pole(pole_number="P-M35", species="LARCH", original_class="2",
                            install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                            gis_tag="RURAL", height_ft=35)
        p_dry = create_pole(pole_number="P-M25", species="LARCH", original_class="2",
                            install_date="2001-05-01", gis_lat=46.1, gis_lon=-121.1,
                            gis_tag="RURAL", height_ft=35)
        t_wet = create_manual_task(cycle["id"], p_wet["id"])
        t_dry = create_manual_task(cycle["id"], p_dry["id"])
        wet = submit_task(t_wet["id"], shell_thickness_in=2.25, sound_wood_pct=100,
                          decay_pocket_depth_in=0.0, moisture_pct=35)
        dry = submit_task(t_dry["id"], shell_thickness_in=2.25, sound_wood_pct=100,
                          decay_pocket_depth_in=0.0, moisture_pct=25)
        # LARCH factor 1.02: base 102; wet -> 102 * 0.95 = 96.90; dry -> clamped 100.
        assert wet["rs_conservative_pct"] == pytest.approx(96.90, abs=0.005)
        assert dry["rs_conservative_pct"] == pytest.approx(100.00, abs=0.005)


class TestSubmissionGates:
    def test_submit_twice_rejected(self, api, program_manager_headers):
        """PRD §3.3: "Submission is permitted only while the task is `OPEN`, only while
        the owning cycle is still `OPEN` (else `ERR_CYCLE_NOT_OPEN`), and only while the
        pole has not been `REPLACED` (else `ERR_POLE_REPLACED`)."

        Design: Corner/state_machines/submit_twice_rejected
        """
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-2S", "species": "LARCH",
                            "original_class": "2", "install_date": "2001-05-01",
                            "gis_tag": "RURAL", "height_ft": 35}
        )
        first = submit_task(task["id"], shell_thickness_in=2.00, sound_wood_pct=90,
                            decay_pocket_depth_in=0.0, moisture_pct=20)
        assert first["status"] == "SUBMITTED"
        resp = api.submit_inspection_task(
            task["id"],
            {
                "shell_thickness_in": 2.00, "sound_wood_pct": 90,
                "decay_pocket_depth_in": 0.0, "moisture_pct": 20,
                "photos": default_photos(),
            },
            make_inspector_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_task(task["id"])
        assert after["status"] == "SUBMITTED"
        assert after["shell_thickness_in"] == pytest.approx(2.00), (
            "the rejected second submit must not overwrite the first readings"
        )

    def test_photo_evidence_missing_decay_pocket_rejected(self, api, program_manager_headers):
        """PRD §3.3: "every submission must contain at least one `GROUNDLINE` photo and
        at least one `TAG` photo, and a classification of `REJECT_PRIORITY` or
        `REJECT_ROUTINE` additionally requires at least one `DECAY_POCKET` photo;
        insufficient coverage is rejected with `ERR_PHOTO_EVIDENCE_REQUIRED`."

        Design: Corner/errors/photo_evidence_missing_decay_pocket_rejected
        """
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-PH"}
        )
        resp = api.submit_inspection_task(
            task["id"],
            dict(PRIORITY_REJECT_READINGS, hazard_flag=True,
                 photos=default_photos("GROUNDLINE", "TAG")),
            make_inspector_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PHOTO_EVIDENCE_REQUIRED)
        after = get_task(task["id"])
        assert after["status"] == "OPEN"

    def test_submit_hazard_flag_error_wins_over_photo(self, api, program_manager_headers):
        """PRD §2.8: "a hazard-flag failure at stage 7 surfaces before a photo-coverage
        failure at stage 10, even when both would independently apply."
        PRD §3.3: "when the computed classification is `REJECT_PRIORITY`, the payload's
        `hazard_flag` must be true — an inspector who has found a pole that far gone is
        required to declare the hazard — and a missing or false flag is rejected with
        `ERR_HAZARD_FLAG_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_submit
        """
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-PC3"}
        )
        resp = api.submit_inspection_task(
            task["id"],
            dict(PRIORITY_REJECT_READINGS, hazard_flag=False, photos=[]),
            make_inspector_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_HAZARD_FLAG_REQUIRED)

    def test_submit_hazard_violation_leaves_task_open(self, api, program_manager_headers):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, and the
        stages are evaluated in a strict order; a failure at an earlier stage is
        reported and masks every later check."
        A rejected submission mutates nothing: the task stays OPEN with no computed
        strength fields and no auto-created audit.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_submit
        """
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-PC3"}
        )
        resp = api.submit_inspection_task(
            task["id"],
            dict(PRIORITY_REJECT_READINGS, hazard_flag=False, photos=[]),
            make_inspector_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_HAZARD_FLAG_REQUIRED)
        after = get_task(task["id"])
        assert after["status"] == "OPEN"
        assert after["effective_rs_pct"] is None
        assert after["classification"] is None
        assert list_audits(params={"inspection_task_id": task["id"]}) == []


class TestSubmitOnReplacedPole:
    def _replaced_pole_with_open_task(self, api, program_manager_headers):
        """Drive a pole to REPLACED through the documented cascade (PRD §3.4 + §3.8):
        REJECT_PRIORITY accept -> PRIORITY_REJECT -> fund the auto-created order ->
        complete -> REPLACED. A second OPEN task is created after the first task
        reaches its terminal ACCEPTED state, and remains OPEN on the pole."""
        budget = create_budget(fiscal_year=2026, total_cents=1_000_000)
        crew = create_crew(crew_code="CR-X")
        pole, cycle, task_bad = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-RP"}
        )
        submit_task(
            task_bad["id"],
            **dict(PRIORITY_REJECT_READINGS, hazard_flag=True,
                   photos=default_photos("GROUNDLINE", "TAG", "DECAY_POCKET")),
        )
        qa_review_task(task_bad["id"], "ACCEPT")
        # First task is terminal now, so a recheck task may be created on the pole.
        task_open = create_manual_task(
            cycle["id"], pole["id"],
            due_window_start="2026-08-21T00:00:00Z",
            due_window_end="2026-08-30T00:00:00Z",
        )
        data, _ = validate_paginated(
            api.list_replacement_work_orders(program_manager_headers,
                                             params={"pole_id": pole["id"]})
        )
        assert len(data) == 1, "REJECT_PRIORITY accept must auto-create one order"
        order = data[0]
        fund_order(order["id"], budget["id"], budget["version"])
        resp = api.complete_replacement_work_order(
            order["id"], {"actual_cost_cents": 250000},
            make_contractor_headers(crew["id"]),
        )
        completed = validate_success(resp, expected_status=200)
        assert completed["status"] == "COMPLETED"
        pole_after = get_pole(pole["id"])
        assert pole_after["status"] == "REPLACED"
        return pole_after, cycle, task_open

    def test_submit_on_replaced_pole_rejected(self, api, program_manager_headers):
        """PRD §3.8: "From that point on, the pole is closed to new field work: task
        submission, manual task creation, treatment-order creation, and
        replacement-order creation targeting a `REPLACED` pole are all rejected with
        `ERR_POLE_REPLACED`."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_pole_replaced
        """
        pole, _, task_open = self._replaced_pole_with_open_task(
            api, program_manager_headers
        )
        resp = api.submit_inspection_task(
            task_open["id"],
            {
                "shell_thickness_in": 2.50, "sound_wood_pct": 90,
                "decay_pocket_depth_in": 0.0, "moisture_pct": 20,
                "photos": default_photos(),
            },
            make_inspector_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_POLE_REPLACED)
        assert get_task(task_open["id"])["status"] == "OPEN"

    def test_manual_task_on_replaced_pole_rejected(self, api, program_manager_headers):
        """PRD §3.2: "the pole must not be `REPLACED` (`ERR_POLE_REPLACED`)".

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_pole_replaced
        """
        pole, cycle, _ = self._replaced_pole_with_open_task(
            api, program_manager_headers
        )
        resp = api.create_inspection_task(
            create_inspection_task_payload(
                cycle["id"], pole["id"],
                due_window_start="2026-09-01T00:00:00Z",
                due_window_end="2026-09-10T00:00:00Z",
            ),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_POLE_REPLACED)
