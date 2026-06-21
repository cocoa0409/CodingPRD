"""Difficulty Rule 2 — combinatorial_formula.

Multi-input non-linear formulas: criticality classification (4 inputs +
analyte/age branch) and TAT chronological evaluation pinned by min(released_at)
across multiple Results.
"""
from test_helpers import (
    accession_specimen,
    bootstrap_actors,
    collect_specimen,
    complete_instrument_run,
    create_instrument_run,
    create_order,
    create_result,
    create_specimen,
    get_lab_order,
    get_lab_order_version,
    register_patient,
    release_result,
    set_clock,
    setup_released_result,
    transit_specimen,
)


class TestCriticalityClassifyAcrossTiers:
    """PRD §3.5: criticality is computed by a two-stage rule combining numeric
    bounds and the NEONATE override for K / GLUCOSE.
    """

    def test_three_tier_outcomes_normal_critical_high_neonate_panic(self, api):
        """PRD §3.5: "a `numeric_value` at or above `critical_high` yields `CRITICAL_HIGH`,
        a `numeric_value` strictly below `reference_low` or strictly above `reference_high`
        (but still inside the critical band) yields `ABNORMAL`, and otherwise `NORMAL`."
        PRD §3.5: "a glucose reading (`analyte_code` of `GLUCOSE`) at or below 40.00 mg/dL
        likewise classifies as `PANIC`. `PANIC` supersedes any `CRITICAL_LOW`,
        `CRITICAL_HIGH`, or `ABNORMAL` base tier."

        Design: Difficulty/combinatorial_formula/criticality_classify_three_input_nonlinear_with_age_branch
        """
        actors = bootstrap_actors(
            clock="2026-05-28T08:00:00Z", panels=["CMP", "GLUC"]
        )
        # Three patients: two ADULT, one NEONATE (born 6 days before clock).
        pat_a = register_patient(
            actors.lt_id, mrn="MRN-C00100", full_name="Adult A",
            date_of_birth="1980-01-01",
        )
        pat_b = register_patient(
            actors.lt_id, mrn="MRN-C00200", full_name="Adult B",
            date_of_birth="1980-01-01",
        )
        pat_c = register_patient(
            actors.lt_id, mrn="MRN-C00300", full_name="Neo C",
            date_of_birth="2026-05-22",
        )
        assert pat_a["age_band"] == "ADULT"
        assert pat_b["age_band"] == "ADULT"
        assert pat_c["age_band"] == "NEONATE"

        # Result A: ADULT, K=4.50 in [reference_low, reference_high] → NORMAL.
        a_bundle = setup_released_result(
            actors, pat_a,
            panel_code="CMP", container_code="GREEN",
            analyte_code="K", numeric_value=4.50, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
            run_start="2026-05-28T09:00:00Z", run_end="2026-05-28T09:10:00Z",
        )
        # Advance clock past the per-collector 5-minute window (PRD §3.3).
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        # Result B: ADULT, K=6.00 == critical_high → CRITICAL_HIGH (PRD §2.4 inclusive).
        b_bundle = setup_released_result(
            actors, pat_b,
            panel_code="CMP", container_code="GREEN",
            analyte_code="K", numeric_value=6.00, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
            run_start="2026-05-28T09:15:00Z", run_end="2026-05-28T09:25:00Z",
        )
        # Advance clock again so the third specimen's collection is outside the
        # 5-minute window around the second collection.
        set_clock("2026-05-28T08:20:00Z", actors.director_id)
        # Result C: NEONATE, GLUCOSE=40.00 == critical_low → base would be
        # CRITICAL_LOW; NEONATE override → PANIC.
        c_bundle = setup_released_result(
            actors, pat_c,
            panel_code="GLUC", container_code="GRAY",
            analyte_code="GLUCOSE", numeric_value=40.00, unit="mg/dL",
            reference_low=70.00, reference_high=110.00,
            critical_low=40.00, critical_high=500.00,
            run_start="2026-05-28T09:30:00Z", run_end="2026-05-28T09:40:00Z",
        )

        assert a_bundle["result"]["criticality"] == "NORMAL", (
            f"ADULT K=4.50 inside reference range must be NORMAL; "
            f"got {a_bundle['result']['criticality']!r}"
        )
        assert b_bundle["result"]["criticality"] == "CRITICAL_HIGH", (
            f"ADULT K=6.00 == critical_high must be CRITICAL_HIGH; "
            f"got {b_bundle['result']['criticality']!r}"
        )
        assert c_bundle["result"]["criticality"] == "PANIC", (
            f"NEONATE GLUCOSE=40.00 (override) must be PANIC; "
            f"got {c_bundle['result']['criticality']!r}"
        )

    def test_abnormal_tier_when_outside_reference_but_inside_critical_band(self, api):
        """PRD §3.5: "a `numeric_value` strictly below `reference_low` or strictly above
        `reference_high` (but still inside the critical band) yields `ABNORMAL`"

        Design: Difficulty/combinatorial_formula/criticality_classify_three_input_nonlinear_with_age_branch
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-ABN100", full_name="Adult",
            date_of_birth="1980-01-01",
        )

        # K=5.50 — strictly above reference_high=5.10 but below critical_high=6.00.
        bundle = setup_released_result(
            actors, patient,
            panel_code="CMP", container_code="GREEN",
            analyte_code="K", numeric_value=5.50, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        assert bundle["result"]["criticality"] == "ABNORMAL", (
            f"K=5.50 strictly > reference_high (5.10), < critical_high (6.00) "
            f"must classify as ABNORMAL; got {bundle['result']['criticality']!r}"
        )


class TestTatPinnedFromEarliestReleasedAt:
    """PRD §3.6: TAT is computed at first release and pinned from min(released_at)
    across all Results of the order.
    """

    def test_tat_pinned_to_minimum_released_at_across_results(self, api):
        """PRD §3.6: "the integer minutes between `ordered_at` and the earliest
        `released_at` of any released result on the order"
        PRD §3.6: "A lab order's `turn_around_time_minutes` is computed when the first
        result on the order is released."

        Design: Difficulty/combinatorial_formula/tat_pinned_evaluation_order_ordered_to_accessioned_to_released
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-O00100", date_of_birth="1980-01-01",
        )

        # Single order at 08:00, two specimens, two runs, two results.
        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp2 = create_specimen(actors, order["id"], container_code="RED")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])
        set_clock("2026-05-28T08:30:00Z", actors.director_id)
        accession_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:45:00Z", actors.director_id)
        accession_specimen(actors, sp2["id"])
        run1 = create_instrument_run(
            actors, sp1["id"], "2026-05-28T09:00:00Z", "2026-05-28T09:20:00Z"
        )
        complete_instrument_run(actors, run1["id"])
        run2 = create_instrument_run(
            actors, sp2["id"], "2026-05-28T09:30:00Z", "2026-05-28T09:50:00Z"
        )
        complete_instrument_run(actors, run2["id"])
        res1 = create_result(
            actors, order["id"], sp1["id"], run1["id"],
            analyte_code="GLUCOSE", numeric_value=95.00, unit="mg/dL",
            reference_low=70.00, reference_high=110.00,
            critical_low=40.00, critical_high=500.00,
        )
        res2 = create_result(
            actors, order["id"], sp2["id"], run2["id"],
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        ord_v1 = get_lab_order_version(actors, order["id"])
        # Release res1 at 09:30 → 90 min after 08:00.
        set_clock("2026-05-28T09:30:00Z", actors.director_id)
        release_result(actors, res1["id"], ord_v1)
        ord_v2 = get_lab_order_version(actors, order["id"])
        # Release res2 at 10:00 — should NOT change pinned TAT (still 90).
        set_clock("2026-05-28T10:00:00Z", actors.director_id)
        release_result(actors, res2["id"], ord_v2)

        final = get_lab_order(actors, order["id"])
        assert final["turn_around_time_minutes"] == 90, (
            f"TAT must be pinned at first release (90 min); "
            f"got {final['turn_around_time_minutes']}"
        )
        assert final["status"] == "RESULTED", (
            f"order must remain RESULTED; got {final['status']!r}"
        )

    def test_tat_floor_truncates_fractional_minute_toward_zero(self, api):
        """PRD §2.4: "Turn-around-time figures derived from clock subtraction are
        returned as integer minutes, computed by truncating any fractional seconds
        toward zero (floor)."

        Design: Difficulty/combinatorial_formula/tat_pinned_evaluation_order_ordered_to_accessioned_to_released
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["GLUC"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-FLR100", date_of_birth="1980-01-01",
        )

        # Order at 08:00:00; first release at 08:30:45 → 30 min 45 sec → floor = 30 min.
        order = create_order(
            actors, patient["id"], panel_code="GLUC", priority="ROUTINE"
        )
        sp = create_specimen(actors, order["id"], container_code="GRAY")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])
        accession_specimen(actors, sp["id"])
        run = create_instrument_run(
            actors, sp["id"], "2026-05-28T08:20:00Z", "2026-05-28T08:30:00Z"
        )
        complete_instrument_run(actors, run["id"])
        result = create_result(
            actors, order["id"], sp["id"], run["id"],
            analyte_code="GLUCOSE", numeric_value=95.00, unit="mg/dL",
            reference_low=70.00, reference_high=110.00,
            critical_low=40.00, critical_high=500.00,
        )
        ord_v = get_lab_order_version(actors, order["id"])
        set_clock("2026-05-28T08:30:45Z", actors.director_id)
        release_result(actors, result["id"], ord_v)

        final = get_lab_order(actors, order["id"])
        # 30 min 45 sec → floor 30 min.
        assert final["turn_around_time_minutes"] == 30, (
            f"floor of (08:30:45 − 08:00:00) = 30 min; got {final['turn_around_time_minutes']}"
        )
