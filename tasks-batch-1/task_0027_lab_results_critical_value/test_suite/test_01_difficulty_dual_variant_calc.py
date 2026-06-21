"""Difficulty Rule 1 — dual_variant_calc.

Identical inputs produce demonstrably different outputs under two PRD-declared
variants of the same calculation: criticality (NEONATE vs ADULT age_band on
the same K reading), and turn-around-time (clinical_chronology vs lab_processing
on the same order timestamps).
"""
from test_helpers import (
    bootstrap_actors,
    get_lab_order,
    register_patient,
    set_clock,
    setup_released_result,
)


class TestCriticalityNeonateVsAdultOnSameKValue:
    """PRD §3.5: age_band override on a NEONATE makes the same K=6.50 reading
    classify as PANIC, while on an ADULT it classifies as CRITICAL_HIGH.
    """

    def test_neonate_k_at_6_50_classifies_panic_while_adult_classifies_critical_high(self, api):
        """PRD §3.5: "a potassium reading (`analyte_code` of `K`) at or above 6.50 mmol/L
        OR at or below 2.50 mmol/L immediately classifies as `PANIC` regardless of the
        base tier"
        PRD §3.5: "the same `numeric_value`, `analyte_code`, and range bounds can yield
        a different `criticality` for two patients whose only difference is their `age_band`."

        Design: Difficulty/dual_variant_calc/criticality_neonate_panic_vs_adult_critical_high_on_same_k_value
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z")

        # A neonate (8 days old at clock=2026-05-28) and an adult, identical labs.
        pat_neo = register_patient(
            actors.lt_id,
            mrn="MRN-NEO001",
            full_name="Neo Baby",
            date_of_birth="2026-05-20",
        )
        pat_adult = register_patient(
            actors.lt_id,
            mrn="MRN-ADL001",
            full_name="Adult One",
            date_of_birth="1990-01-01",
        )
        assert pat_neo["age_band"] == "NEONATE", (
            f"NEONATE expected (8 days old); got {pat_neo['age_band']!r}"
        )
        assert pat_adult["age_band"] == "ADULT", (
            f"ADULT expected (36 years old); got {pat_adult['age_band']!r}"
        )

        neo_bundle = setup_released_result(
            actors,
            pat_neo,
            panel_code="CMP",
            container_code="GREEN",
            analyte_code="K",
            numeric_value=6.50,
            unit="mmol/L",
            reference_low=3.50,
            reference_high=5.10,
            critical_low=2.50,
            critical_high=6.00,
            run_start="2026-05-28T09:00:00Z",
            run_end="2026-05-28T09:20:00Z",
        )
        # Advance clock past the per-collector 5-minute window (PRD §3.3) before
        # the second specimen is collected by the same phlebotomist.
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        adult_bundle = setup_released_result(
            actors,
            pat_adult,
            panel_code="CMP",
            container_code="GREEN",
            analyte_code="K",
            numeric_value=6.50,
            unit="mmol/L",
            reference_low=3.50,
            reference_high=5.10,
            critical_low=2.50,
            critical_high=6.00,
            run_start="2026-05-28T09:30:00Z",
            run_end="2026-05-28T09:50:00Z",
        )

        assert neo_bundle["result"]["criticality"] == "PANIC", (
            f"neonate K=6.50 must classify as PANIC; got {neo_bundle['result']['criticality']!r}"
        )
        assert adult_bundle["result"]["criticality"] == "CRITICAL_HIGH", (
            f"adult K=6.50 must classify as CRITICAL_HIGH; got {adult_bundle['result']['criticality']!r}"
        )

    def test_neonate_glucose_at_40_classifies_panic_while_adult_classifies_critical_low(self, api):
        """PRD §3.5: "a glucose reading (`analyte_code` of `GLUCOSE`) at or below 40.00 mg/dL
        likewise classifies as `PANIC`."
        PRD §3.5: "a `numeric_value` at or below `critical_low` yields `CRITICAL_LOW`"

        Design: Difficulty/dual_variant_calc/criticality_neonate_panic_vs_adult_critical_high_on_same_k_value
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z")

        pat_neo = register_patient(
            actors.lt_id,
            mrn="MRN-NEO002",
            full_name="Neo Baby 2",
            date_of_birth="2026-05-20",
        )
        pat_adult = register_patient(
            actors.lt_id,
            mrn="MRN-ADL002",
            full_name="Adult Two",
            date_of_birth="1990-01-01",
        )

        # GLUCOSE=40.00 with critical_low=40.00.
        # NEONATE → PANIC (override per PRD §3.5).
        # ADULT → CRITICAL_LOW (base tier: numeric_value <= critical_low).
        neo_bundle = setup_released_result(
            actors,
            pat_neo,
            panel_code="GLUC",
            container_code="GRAY",
            analyte_code="GLUCOSE",
            numeric_value=40.00,
            unit="mg/dL",
            reference_low=70.00,
            reference_high=110.00,
            critical_low=40.00,
            critical_high=500.00,
            run_start="2026-05-28T09:00:00Z",
            run_end="2026-05-28T09:20:00Z",
        )
        # Advance clock past the per-collector 5-minute window (PRD §3.3) before
        # the second specimen is collected by the same phlebotomist.
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        adult_bundle = setup_released_result(
            actors,
            pat_adult,
            panel_code="GLUC",
            container_code="GRAY",
            analyte_code="GLUCOSE",
            numeric_value=40.00,
            unit="mg/dL",
            reference_low=70.00,
            reference_high=110.00,
            critical_low=40.00,
            critical_high=500.00,
            run_start="2026-05-28T09:30:00Z",
            run_end="2026-05-28T09:50:00Z",
        )

        assert neo_bundle["result"]["criticality"] == "PANIC", (
            f"neonate GLUCOSE=40.00 must classify as PANIC; got {neo_bundle['result']['criticality']!r}"
        )
        assert adult_bundle["result"]["criticality"] == "CRITICAL_LOW", (
            f"adult GLUCOSE=40.00 (== critical_low) must classify as CRITICAL_LOW; "
            f"got {adult_bundle['result']['criticality']!r}"
        )


class TestTurnAroundTimeClinicalChronologyVsLabProcessing:
    """PRD §3.6: identical timestamps yield different turn_around_time_minutes
    under the two declared variants — clinical_chronology spans ordered_at→released_at,
    lab_processing spans accessioned_at→released_at.
    """

    def test_tat_clinical_chronology_is_pinned_and_lab_processing_excludes_pre_analytic(self, api):
        """PRD §3.6: "The default flavor, which is what `turn_around_time_minutes`
        is pinned to on the order, is `clinical_chronology`: the integer minutes between
        `ordered_at` and the earliest `released_at` of any released result on the order"
        PRD §3.6: "The alternative flavor, `lab_processing`, spans the earliest
        `accessioned_at` of any accessioned specimen of the order to the earliest
        `released_at`; it excludes the pre-analytic transit and accessioning time and
        therefore yields a smaller value than `clinical_chronology` for the same
        underlying timestamps."

        Design: Difficulty/dual_variant_calc/tat_clinical_chronology_vs_lab_processing_on_lab_order
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["GLUC"])
        patient = register_patient(
            actors.lt_id,
            mrn="MRN-TAT001",
            date_of_birth="1985-05-05",
        )

        # Order placed at 08:00 (current clock).
        from test_helpers import (
            accession_specimen,
            collect_specimen,
            complete_instrument_run,
            create_instrument_run,
            create_order,
            create_result,
            create_specimen,
            get_lab_order_version,
            release_result,
            transit_specimen,
        )

        order = create_order(actors, patient["id"], panel_code="GLUC", priority="ROUTINE")
        sp = create_specimen(actors, order["id"], container_code="GRAY")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])
        # Advance clock to 08:30 — accessioned_at will pin to this.
        set_clock("2026-05-28T08:30:00Z", actors.director_id)
        accession_specimen(actors, sp["id"])
        run = create_instrument_run(
            actors, sp["id"], "2026-05-28T08:35:00Z", "2026-05-28T08:55:00Z"
        )
        complete_instrument_run(actors, run["id"])
        result = create_result(
            actors, order["id"], sp["id"], run["id"],
            analyte_code="GLUCOSE",
            numeric_value=90.00,
            unit="mg/dL",
            reference_low=70.00,
            reference_high=110.00,
            critical_low=40.00,
            critical_high=500.00,
        )
        ord_v = get_lab_order_version(actors, order["id"])
        # Release at 09:30 — released_at pins here.
        set_clock("2026-05-28T09:30:00Z", actors.director_id)
        release_result(actors, result["id"], ord_v)

        # Default (no tat_variant param): clinical_chronology — 90 min (08:00 → 09:30).
        default_order = get_lab_order(actors, order["id"])
        assert default_order["turn_around_time_minutes"] == 90, (
            f"clinical_chronology TAT must be 90 (ordered_at 08:00 → released_at 09:30); "
            f"got {default_order['turn_around_time_minutes']}"
        )
        assert default_order["status"] == "RESULTED", (
            f"order must transition to RESULTED after first release; got {default_order['status']!r}"
        )

        # tat_variant=lab_processing — 60 min (08:30 → 09:30).
        lab_order = get_lab_order(actors, order["id"], tat_variant="lab_processing")
        assert lab_order["turn_around_time_minutes"] == 60, (
            f"lab_processing TAT must be 60 (accessioned_at 08:30 → released_at 09:30); "
            f"got {lab_order['turn_around_time_minutes']}"
        )

    def test_tat_default_variant_query_matches_pinned_clinical_chronology(self, api):
        """PRD §3.6: "the default `tat_variant`, omitted or set to `clinical_chronology`, returns the stored value"

        Design: Difficulty/dual_variant_calc/tat_clinical_chronology_vs_lab_processing_on_lab_order
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["GLUC"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-TATD01", date_of_birth="1985-05-05",
        )
        from test_helpers import (
            accession_specimen,
            collect_specimen,
            complete_instrument_run,
            create_instrument_run,
            create_order,
            create_result,
            create_specimen,
            get_lab_order_version,
            release_result,
            transit_specimen,
        )

        order = create_order(actors, patient["id"], panel_code="GLUC", priority="ROUTINE")
        sp = create_specimen(actors, order["id"], container_code="GRAY")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])
        set_clock("2026-05-28T08:30:00Z", actors.director_id)
        accession_specimen(actors, sp["id"])
        run = create_instrument_run(
            actors, sp["id"], "2026-05-28T08:35:00Z", "2026-05-28T08:55:00Z"
        )
        complete_instrument_run(actors, run["id"])
        result = create_result(
            actors, order["id"], sp["id"], run["id"],
            analyte_code="GLUCOSE",
            numeric_value=90.00,
            unit="mg/dL",
            reference_low=70.00,
            reference_high=110.00,
            critical_low=40.00,
            critical_high=500.00,
        )
        ord_v = get_lab_order_version(actors, order["id"])
        set_clock("2026-05-28T09:30:00Z", actors.director_id)
        release_result(actors, result["id"], ord_v)

        # tat_variant=clinical_chronology must equal the pinned default.
        explicit = get_lab_order(actors, order["id"], tat_variant="clinical_chronology")
        omitted = get_lab_order(actors, order["id"])
        assert explicit["turn_around_time_minutes"] == omitted["turn_around_time_minutes"] == 90, (
            f"clinical_chronology variant (default) must equal stored value; "
            f"omitted={omitted['turn_around_time_minutes']} explicit={explicit['turn_around_time_minutes']}"
        )
