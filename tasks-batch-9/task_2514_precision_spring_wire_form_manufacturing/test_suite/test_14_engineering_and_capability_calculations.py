"""Engineering, capability and money arithmetic re-derived from the PRD's own rules.

Every figure asserted here is computed twice: once through the reference
arithmetic in `test_helpers.assertions`, which transcribes each formula together
with the rounding discipline its own rule names, and once as the literal the
worked numbers pin. A server that rounds at the wrong step, reads an unrounded
intermediate, or keys a constant off the wrong field fails the comparison rather
than a hand-copied number.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)

# The canonical grade and geometry every calculation below is anchored on.
_TENSILE_MPA = 1900
_SHEAR_MODULUS_GPA = 79.3
_DENSITY = 7850
_WIRE_D = 2.5
_OUTER_D = 20.0
_MAX_N = 150
_MIN_N = 50
_COST_PER_KG_CENTS = 850
_CYCLE_SECONDS = 1.8
_TOOL_COST_CENTS = 4_800_000


def test_revision_recomputes_spring_rate_and_wire_mass_on_the_new_coil_count(
    api: ApiClient,
) -> None:
    """A revision moving only `active_coils` re-runs the whole closed-form stack.

    The rate and the per-piece mass both read the coil count, so both move; the
    two corrected stresses read only the loads and the cross-section, so both
    stand still, and the revision bookkeeping walks the design back to `DRAFT`.

    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear modulus multiplied by the wire diameter raised to the fourth power, divided by the product of eight, the mean coil diameter cubed, and the active coil count, with the result rounded half up to three decimal places."
    PRD §3.2: "For a given load, the corrected shear stress is the Wahl factor multiplied by eight, multiplied by that load, multiplied by the mean coil diameter, then divided by the product of pi and the wire diameter cubed; pi is taken as 3.141592653589793."
    PRD §3.2: "`wire_mass_per_piece_kg` is then the developed length converted from millimetres to metres by dividing by one thousand, multiplied by that area, multiplied by the material's `density_kg_per_m3`, rounded half up to exactly six decimal places."
    PRD §3.3: "An accepted revision does the following bookkeeping: `superseded_revision_no` is set to the value `current_revision_no` held before the revision, `current_revision_no` is increased by 1, `release_status` returns to `DRAFT`, `reviewed_by_user_id` is cleared to null, and `created_by_user_id` is re-stamped with the revising engineer's `X-User-ID` — so the segregation-of-duties gate on the next review is measured against whoever cut the latest revision."
    PRD §3.3: "Every computed engineering field is then recalculated from the post-revision geometry: spring rate, all four stress fields, the fatigue criterion and margin, the life tier, the per-piece wire mass, and the tangle-risk index and class."
    PRD §2.6: "Spring rate is carried to **3 decimal places**."
    PRD §2.6: "Wire mass per piece is carried to **exactly 6 decimal places**, and this rounded value is the only per-piece mass any downstream calculation may read."

    Design: Corner/calculations/spring_rate_and_mass_recomputed_by_a_revision_that_changes_active_coils
    """
    world = X.build_world(api, "prototype")
    assert world.design["spring_rate_n_per_mm"] == C.D1_SPRING_RATE
    assert world.design["wire_mass_per_piece_kg"] == C.D1_WIRE_MASS_PER_PIECE_KG

    revised_coils = 10
    design = validate_success(
        api.revise_design(
            world.design_id,
            F.revision_payload(world.design_version, active_coils=revised_coils),
            DESIGN_ENGINEER_HEADERS,
        ),
        expected_status=200,
    )

    expected_rate = A.expected_spring_rate(
        _SHEAR_MODULUS_GPA, _WIRE_D, _OUTER_D, revised_coils
    )
    expected_mass = A.expected_wire_mass_per_piece_kg(
        _WIRE_D, _OUTER_D, revised_coils, C.END_CLOSED_GROUND, _DENSITY
    )
    assert expected_rate == 7.225, "the ten-coil rate the PRD formula produces"
    assert expected_mass == 0.025422, "the ten-coil per-piece mass the PRD formula produces"
    assert design["active_coils"] == revised_coils
    assert design["spring_rate_n_per_mm"] == expected_rate
    A.assert_decimal_places(design["spring_rate_n_per_mm"], 3, "spring_rate_n_per_mm")
    assert design["wire_mass_per_piece_kg"] == expected_mass
    A.assert_decimal_places(
        design["wire_mass_per_piece_kg"], 6, "wire_mass_per_piece_kg"
    )

    # The stress stack never reads the coil count, so it is byte-identical.
    expected_max = A.expected_shear_stress(_MAX_N, _WIRE_D, _OUTER_D)
    expected_min = A.expected_shear_stress(_MIN_N, _WIRE_D, _OUTER_D)
    assert (expected_max, expected_min) == (513.37, 171.12)
    assert design["shear_stress_max_mpa"] == expected_max
    assert design["shear_stress_min_mpa"] == expected_min
    expected_margin = A.expected_fatigue_margin(
        C.CLASS_INDUSTRIAL, _WIRE_D, _OUTER_D, _MAX_N, _MIN_N, _TENSILE_MPA, True
    )
    assert expected_margin == 1.757
    assert design["fatigue_margin_ratio"] == expected_margin
    assert design["predicted_fatigue_life_cycles"] == A.expected_life_tier(
        expected_margin
    )
    assert design["predicted_fatigue_life_cycles"] == 10_000_000

    assert design["current_revision_no"] == 2
    assert design["superseded_revision_no"] == 1
    assert design["release_status"] == C.RELEASE_DRAFT


def test_spc_mean_and_sigma_carry_four_and_six_decimal_places(api: ApiClient) -> None:
    """One in-process record carries three statistics at three different scales.

    The mean is quantized to four places, the Bessel-corrected sigma to six and
    both capability indices to three, and the indices are formed from the
    unrounded mean and sigma rather than from the stored ones.

    PRD §2.6: "Inspection statistics use three different counts on the same record: the subgroup mean to **4 decimal places**, the Bessel-corrected standard deviation to **6 decimal places**, and both capability indices to **3 decimal places**."
    PRD §3.7: "`subgroup_size` is the number of values in `measurements`."
    PRD §3.7: "`mean_value` is their arithmetic mean, rounded half up to four decimal places."
    PRD §3.7: "`sigma_value` is the Bessel-corrected sample standard deviation: take each measurement's deviation from the **unrounded** mean, square it, sum the squares, divide by one less than the subgroup size, take the square root, and round half up to six decimal places."
    PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the characteristic's `usl` minus the unrounded mean, and the unrounded mean minus the characteristic's `lsl`, keep whichever of those two distances is **smaller**, divide it by three times the unrounded standard deviation, and round half up to three decimal places."
    PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value` is below the characteristic's `cpk_floor`, or when any single measurement in the subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."
    PRD §3.8: "The server stamps `record_kind` as `SPC` — again from the endpoint, never from the body — stamps `inspected_by_user_id`, and computes the full statistic set of section 3.7 including the pooled `ppk_value`."

    Design: Corner/calculations/spc_mean_and_sigma_carry_four_and_six_decimal_places
    """
    world = X.build_world(api, "running")
    characteristic = world.characteristics[0]
    subgroup = list(C.IN_CONTROL_SUBGROUP)

    record = validate_success(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(characteristic["id"], subgroup),
            QUALITY_INSPECTOR_HEADERS,
        ),
        expected_status=201,
    )

    lsl, usl = characteristic["lsl"], characteristic["usl"]
    expected_mean = A.expected_mean_value(subgroup)
    expected_sigma = A.expected_sigma_value(subgroup)
    expected_cpk = A.expected_cpk_value(subgroup, lsl, usl)
    expected_ppk = A.expected_ppk_value(subgroup, lsl, usl)
    assert (expected_mean, expected_sigma, expected_cpk) == (60.0, 0.05, 3.333)
    assert expected_ppk == 3.333

    assert record["record_kind"] == C.RECORD_KIND_SPC
    assert record["subgroup_size"] == len(subgroup)
    assert record["mean_value"] == expected_mean
    A.assert_decimal_places(record["mean_value"], 4, "mean_value")
    assert record["sigma_value"] == expected_sigma
    A.assert_decimal_places(record["sigma_value"], 6, "sigma_value")
    assert record["cpk_value"] == expected_cpk
    A.assert_decimal_places(record["cpk_value"], 3, "cpk_value")
    assert record["ppk_value"] == expected_ppk
    A.assert_decimal_places(record["ppk_value"], 3, "ppk_value")
    assert record["control_state"] == A.expected_control_state(
        subgroup, lsl, usl, characteristic["cpk_floor"]
    )
    assert record["control_state"] == C.CONTROL_IN_CONTROL

    run = X.refresh_run(api, world.run_id)
    assert run["min_cpk_observed"] == expected_cpk
    assert run["min_ppk_observed"] == expected_ppk


def test_cpk_binding_side_flips_to_the_upper_spec_when_the_mean_drifts_high(
    api: ApiClient,
) -> None:
    """Which specification limit binds depends on where the mean sits.

    Two subgroups with identical dispersion score differently: centred on the
    nominal the index is 3.333, while a mean of 60.1500 leaves only the upper
    distance of 0.350 and the index falls to 2.333 — still above the 1.333 floor,
    so the run's quality axis never moves.

    PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the characteristic's `usl` minus the unrounded mean, and the unrounded mean minus the characteristic's `lsl`, keep whichever of those two distances is **smaller**, divide it by three times the unrounded standard deviation, and round half up to three decimal places."
    PRD §3.7: "Because the smaller of the two distances binds, the metric is non-linear — which side of the specification band is limiting flips as the mean drifts across the nominal."
    PRD §3.7: "`mean_value` is their arithmetic mean, rounded half up to four decimal places."
    PRD §3.7: "`sigma_value` is the Bessel-corrected sample standard deviation: take each measurement's deviation from the **unrounded** mean, square it, sum the squares, divide by one less than the subgroup size, take the square root, and round half up to six decimal places."
    PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value` is below the characteristic's `cpk_floor`, or when any single measurement in the subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."
    PRD §3.8: "An in-process record whose `control_state` comes out `OUT_OF_CONTROL` on a characteristic whose `is_safety_critical` is true escalates the whole run, and the escalation is a five-hop cascade that a naive implementation will only get half right."

    Design: Corner/calculations/cpk_binding_side_flips_to_the_upper_spec_when_the_mean_drifts_high
    """
    world = X.build_world(api, "running")
    characteristic = world.characteristics[0]
    lsl, usl = characteristic["lsl"], characteristic["usl"]

    centred = list(C.IN_CONTROL_SUBGROUP)
    assert A.expected_cpk_value(centred, lsl, usl) == 3.333
    assert world.run["min_cpk_observed"] == 3.333, "the centred first article scored 3.333"

    drifted = [60.1, 60.15, 60.2]
    record = validate_success(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(characteristic["id"], drifted),
            QUALITY_INSPECTOR_HEADERS,
        ),
        expected_status=201,
    )

    expected_mean = A.expected_mean_value(drifted)
    expected_sigma = A.expected_sigma_value(drifted)
    expected_cpk = A.expected_cpk_value(drifted, lsl, usl)
    assert (expected_mean, expected_sigma, expected_cpk) == (60.15, 0.05, 2.333)
    # The upper distance is the smaller of the two, which is what makes it bind.
    assert usl - expected_mean < expected_mean - lsl

    assert record["mean_value"] == expected_mean
    A.assert_decimal_places(record["mean_value"], 4, "mean_value")
    assert record["sigma_value"] == expected_sigma
    A.assert_decimal_places(record["sigma_value"], 6, "sigma_value")
    assert record["cpk_value"] == expected_cpk
    A.assert_decimal_places(record["cpk_value"], 3, "cpk_value")
    assert record["control_state"] == A.expected_control_state(
        drifted, lsl, usl, characteristic["cpk_floor"]
    )
    assert record["control_state"] == C.CONTROL_IN_CONTROL

    run = X.refresh_run(api, world.run_id)
    assert run["min_cpk_observed"] == expected_cpk
    assert run["quality_status"] == C.QUALITY_OPEN


def test_ppk_pools_only_spc_records_of_the_same_run_and_characteristic(
    api: ApiClient,
) -> None:
    """The pooled sample is scoped three ways at once.

    First-article rows never pool, only the same run-and-characteristic pair
    pools, and the record being written joins its own sample — so a second
    three-value subgroup pools six values, whose pooled sigma of 0.044721 is
    tighter than either subgroup's own 0.050000 and lifts Ppk to 3.727 while the
    within-subgroup Cpk stays at 3.333.

    PRD §3.7: "`ppk_value` is the pooled long-run capability and is **null on every first-article record**."
    PRD §3.7: "On an in-process record it is computed by pooling every measurement of every inspection record whose `record_kind` is `SPC` and which shares both this record's `run_id` and its `characteristic_id`, including the record being created, into one single sample; records belonging to other runs never pool in, and the order in which records are pooled does not change the result."
    PRD §3.7: "From that pooled sample take the pooled mean, form the same two distances against `usl` and `lsl`, keep the smaller, divide by three times the pooled standard deviation, and round half up to three decimal places."
    PRD §3.7: "Each record keeps the pooled figure it was stamped with at its own creation — earlier rows are never restamped when a later subgroup arrives."
    PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the characteristic's `usl` minus the unrounded mean, and the unrounded mean minus the characteristic's `lsl`, keep whichever of those two distances is **smaller**, divide it by three times the unrounded standard deviation, and round half up to three decimal places."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."
    PRD §3.7: "First-article records therefore move `min_cpk_observed` but leave `min_ppk_observed` untouched."
    PRD §2.6: "Inspection statistics use three different counts on the same record: the subgroup mean to **4 decimal places**, the Bessel-corrected standard deviation to **6 decimal places**, and both capability indices to **3 decimal places**."

    Design: Corner/calculations/ppk_pools_only_spc_records_of_the_same_run_and_characteristic
    """
    world = X.build_world(api, "spc")
    characteristic = world.characteristics[0]
    lsl, usl = characteristic["lsl"], characteristic["usl"]
    subgroup = list(C.IN_CONTROL_SUBGROUP)

    first_spc = world.spc_records[0]
    assert first_spc["ppk_value"] == A.expected_ppk_value(subgroup, lsl, usl)

    record = validate_success(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(characteristic["id"], subgroup),
            QUALITY_INSPECTOR_HEADERS,
        ),
        expected_status=201,
    )

    pooled = subgroup + subgroup
    expected_pooled_ppk = A.expected_ppk_value(pooled, lsl, usl)
    expected_own_cpk = A.expected_cpk_value(subgroup, lsl, usl)
    expected_own_sigma = A.expected_sigma_value(subgroup)
    assert A.expected_sigma_value(pooled) == 0.044721, "six values pool to a tighter sigma"
    assert expected_pooled_ppk == 3.727
    assert expected_own_cpk == 3.333
    assert expected_own_sigma == 0.05

    assert record["sigma_value"] == expected_own_sigma
    A.assert_decimal_places(record["sigma_value"], 6, "sigma_value")
    assert record["cpk_value"] == expected_own_cpk
    A.assert_decimal_places(record["cpk_value"], 3, "cpk_value")
    assert record["ppk_value"] == expected_pooled_ppk
    A.assert_decimal_places(record["ppk_value"], 3, "ppk_value")

    # The first-article row of the same run and characteristic never pools in.
    fai_record = validate_success(
        api.get_inspection_record(
            world.fai_records[0]["id"], QUALITY_INSPECTOR_HEADERS
        ),
        expected_status=200,
    )
    assert fai_record["record_kind"] == C.RECORD_KIND_FAI
    assert fai_record["ppk_value"] is None

    # The earlier in-process row keeps the figure it was stamped with.
    earlier = validate_success(
        api.get_inspection_record(first_spc["id"], QUALITY_INSPECTOR_HEADERS),
        expected_status=200,
    )
    assert earlier["ppk_value"] == A.expected_ppk_value(subgroup, lsl, usl)

    run = X.refresh_run(api, world.run_id)
    assert run["min_cpk_observed"] == 3.333
    assert run["min_ppk_observed"] == 3.333


def test_fatigue_criterion_soderberg_selected_by_the_medical_implant_class(
    api: ApiClient,
) -> None:
    """The owning program's class, not any field on the design, picks the variant.

    `MEDICAL_IMPLANT` selects the yield line, so identical geometry, loads and
    material persist 1.428 rather than the ultimate line's 1.757, while the
    stress state the two variants share is unchanged.

    PRD §3.2: "The amplitude and mean split is taken from the **unrounded** stress values, not from the two rounded fields: `stress_amplitude_mpa` is the unrounded maximum-load stress minus the unrounded minimum-load stress, divided by two, rounded half up to two decimal places once at the end; `mean_stress_mpa` is the sum of those same two unrounded stresses divided by two, rounded half up to two decimal places once at the end."
    PRD §3.2: "The ultimate shear strength is the tensile grade multiplied by 0.67, and the shear yield strength is the tensile grade multiplied by 0.45."
    PRD §3.2: "Two candidate denominators are then formed from the **unrounded** stress amplitude and unrounded mean stress: the Goodman denominator is the unrounded amplitude divided by the endurance limit, plus the unrounded mean divided by the ultimate shear strength; the Soderberg denominator is the unrounded amplitude divided by the endurance limit, plus the unrounded mean divided by the shear yield strength."
    PRD §3.2: "Which one binds is decided by the owning program's `application_class`: the design's `fatigue_criterion` is set to `SODERBERG` when the class is `AUTOMOTIVE_SAFETY` or `MEDICAL_IMPLANT`, and to `GOODMAN` for `AUTOMOTIVE_NON_SAFETY`, `MEDICAL_DEVICE` or `INDUSTRIAL`."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator belonging to the criterion in force, rounded half up to three decimal places."
    PRD §3.2: "Because the shear yield strength is the smaller allowable, the `SODERBERG` variant always yields a strictly smaller margin than the `GOODMAN` variant for identical geometry, loads and material — the safety-critical classes are held to the harsher line, and the less conservative `GOODMAN` line divides the mean stress by the larger ultimate shear strength."
    PRD §3.2: "A ratio of at least 1.300 yields ten million cycles."
    PRD §2.6: "Fatigue margin ratio and the tangle-risk index are carried to **3 decimal places**."
    PRD §2.6: "Corrected shear stresses, the stress amplitude, the mean stress and the exposed endurance limit are carried to **2 decimal places**."

    Design: Corner/calculations/fatigue_criterion_soderberg_selected_by_the_medical_implant_class
    """
    world = X.build_world(
        api,
        "material",
        program={
            "application_class": C.CLASS_MEDICAL_IMPLANT,
            "biocompatibility_required": True,
        },
        material={"biocompatible": True},
    )

    design = validate_success(
        api.create_design(
            F.design_payload(world.program_id, world.material_id),
            DESIGN_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )

    margins = A.expected_fatigue_margins(
        _WIRE_D, _OUTER_D, _MAX_N, _MIN_N, _TENSILE_MPA, True
    )
    expected_criterion = A.expected_fatigue_criterion(C.CLASS_MEDICAL_IMPLANT)
    expected_margin = margins[expected_criterion]
    assert expected_criterion == C.CRITERION_SODERBERG
    assert expected_margin == 1.428
    assert margins[C.CRITERION_GOODMAN] == 1.757
    assert expected_margin < margins[C.CRITERION_GOODMAN]

    assert design["fatigue_criterion"] == expected_criterion
    assert design["fatigue_margin_ratio"] == expected_margin
    A.assert_decimal_places(design["fatigue_margin_ratio"], 3, "fatigue_margin_ratio")
    assert design["predicted_fatigue_life_cycles"] == A.expected_life_tier(
        expected_margin
    )
    assert design["predicted_fatigue_life_cycles"] == 10_000_000

    expected_amplitude = A.expected_stress_amplitude(_WIRE_D, _OUTER_D, _MAX_N, _MIN_N)
    expected_mean_stress = A.expected_mean_stress(_WIRE_D, _OUTER_D, _MAX_N, _MIN_N)
    assert (expected_amplitude, expected_mean_stress) == (171.12, 342.25)
    assert design["stress_amplitude_mpa"] == expected_amplitude
    A.assert_decimal_places(design["stress_amplitude_mpa"], 2, "stress_amplitude_mpa")
    assert design["mean_stress_mpa"] == expected_mean_stress
    A.assert_decimal_places(design["mean_stress_mpa"], 2, "mean_stress_mpa")


def test_shot_peening_flag_selects_the_endurance_limit_constant(api: ApiClient) -> None:
    """The peening flag is the only difference between two otherwise identical designs.

    It multiplies the same tensile grade by 0.30 rather than 0.20, so the exposed
    endurance limit drops from 570.00 to 380.00 and both fatigue lines fall with
    it, while the stress state the two lines are built from is untouched — the
    flag reaches only the allowable, never the loading.

    PRD §3.2: "The endurance limit in shear is the tensile grade multiplied by 0.30 when `shot_peening_required` is true and by 0.20 when it is false — shot peening buys half again as much fatigue strength, which is the whole reason the flag exists."
    PRD §3.2: "Two candidate denominators are then formed from the **unrounded** stress amplitude and unrounded mean stress: the Goodman denominator is the unrounded amplitude divided by the endurance limit, plus the unrounded mean divided by the ultimate shear strength; the Soderberg denominator is the unrounded amplitude divided by the endurance limit, plus the unrounded mean divided by the shear yield strength."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator belonging to the criterion in force, rounded half up to three decimal places."
    PRD §3.2: "A dedicated computed read exposes the fatigue picture without persisting anything."
    PRD §3.2: "It returns `criterion_in_force` — the `GOODMAN` or `SODERBERG` variant whose ratio the design actually persisted — alongside `fatigue_margin_goodman` and `fatigue_margin_soderberg`, each the three-decimal result of its own variant so the two lines can be compared side by side, the stress state they are built from as `stress_amplitude_mpa` and `mean_stress_mpa` at two decimal places, `endurance_limit_mpa` as the shear endurance limit after the shot-peening factor has been applied, rounded to two decimal places, and `predicted_fatigue_life_cycles` as the integer tier."
    PRD §2.6: "Corrected shear stresses, the stress amplitude, the mean stress and the exposed endurance limit are carried to **2 decimal places**."
    PRD §2.6: "Fatigue margin ratio and the tangle-risk index are carried to **3 decimal places**."

    Design: Corner/calculations/shot_peening_flag_selects_the_endurance_limit_constant
    """
    world = X.build_world(api, "material")
    peened = X.draft_design(api, world.program_id, world.material_id)
    unpeened = X.draft_design(
        api,
        world.program_id,
        world.material_id,
        part_number="D2",
        shot_peening_required=False,
    )

    analysis = validate_success(
        api.get_fatigue_analysis(unpeened["id"], DESIGN_ENGINEER_HEADERS),
        expected_status=200,
    )

    expected_endurance = A.endurance_limit_mpa(_TENSILE_MPA, False)
    peened_endurance = A.endurance_limit_mpa(_TENSILE_MPA, True)
    assert (expected_endurance, peened_endurance) == (380.0, 570.0)
    assert analysis["endurance_limit_mpa"] == expected_endurance
    A.assert_decimal_places(analysis["endurance_limit_mpa"], 2, "endurance_limit_mpa")

    margins = A.expected_fatigue_margins(
        _WIRE_D, _OUTER_D, _MAX_N, _MIN_N, _TENSILE_MPA, False
    )
    assert margins == {C.CRITERION_GOODMAN: 1.39, C.CRITERION_SODERBERG: 1.176}
    assert analysis["criterion_in_force"] == A.expected_fatigue_criterion(
        C.CLASS_INDUSTRIAL
    )
    assert analysis["criterion_in_force"] == C.CRITERION_GOODMAN
    assert analysis["fatigue_margin_goodman"] == margins[C.CRITERION_GOODMAN]
    A.assert_decimal_places(analysis["fatigue_margin_goodman"], 3, "fatigue_margin_goodman")
    assert analysis["fatigue_margin_soderberg"] == margins[C.CRITERION_SODERBERG]
    A.assert_decimal_places(
        analysis["fatigue_margin_soderberg"], 3, "fatigue_margin_soderberg"
    )
    assert analysis["predicted_fatigue_life_cycles"] == A.expected_life_tier(
        margins[C.CRITERION_GOODMAN]
    )
    assert analysis["predicted_fatigue_life_cycles"] == 10_000_000

    # The flag reaches the allowable only; the loading is identical on both rows.
    expected_amplitude = A.expected_stress_amplitude(_WIRE_D, _OUTER_D, _MAX_N, _MIN_N)
    expected_mean_stress = A.expected_mean_stress(_WIRE_D, _OUTER_D, _MAX_N, _MIN_N)
    assert (expected_amplitude, expected_mean_stress) == (171.12, 342.25)
    assert analysis["stress_amplitude_mpa"] == expected_amplitude
    assert analysis["mean_stress_mpa"] == expected_mean_stress
    assert unpeened["fatigue_margin_ratio"] == margins[C.CRITERION_GOODMAN]

    peened_margins = A.expected_fatigue_margins(
        _WIRE_D, _OUTER_D, _MAX_N, _MIN_N, _TENSILE_MPA, True
    )
    assert peened_margins[C.CRITERION_GOODMAN] == 1.757
    assert X.refresh_design(api, peened["id"])["fatigue_margin_ratio"] == (
        peened_margins[C.CRITERION_GOODMAN]
    )


def test_predicted_fatigue_life_tier_ladder_across_all_five_bands(api: ApiClient) -> None:
    """Five load cases walk the tier table from its top band to its floor.

    Each comparison is inclusive at its own lower bound and reads the already
    rounded three-decimal ratio, so 1.390, 1.159, 1.085, 1.020 and 0.991 select
    ten million, five million, one million, two hundred and fifty thousand and
    zero cycles respectively, with no interpolation between the steps.

    PRD §3.2: "`predicted_fatigue_life_cycles` is a whole number of cycles chosen by comparing the already-rounded three-decimal `fatigue_margin_ratio` against four descending breakpoints, each comparison inclusive at its lower bound."
    PRD §3.2: "A ratio of at least 1.300 yields ten million cycles."
    PRD §3.2: "Otherwise a ratio of at least 1.150 yields five million."
    PRD §3.2: "Otherwise a ratio of at least 1.050 yields one million."
    PRD §3.2: "Otherwise a ratio of at least 1.000 yields two hundred and fifty thousand."
    PRD §3.2: "A ratio below 1.000 yields zero cycles."
    PRD §3.2: "There is no interpolation and no rounding."
    PRD §2.6: "Predicted fatigue life is a whole number of cycles selected from a tier table; there is no rounding."

    Design: Corner/calculations/predicted_fatigue_life_tier_ladder_across_all_five_bands
    """
    world = X.build_world(api, "material")
    ladder = [
        ("D-T1", 150, 50, 1.39, 10_000_000),
        ("D-T2", 180, 60, 1.159, 5_000_000),
        ("D-T3", 190, 60, 1.085, 1_000_000),
        ("D-T4", 200, 60, 1.02, 250_000),
        ("D-T5", 205, 60, 0.991, 0),
    ]

    created = []
    for part_number, max_n, min_n, pinned_ratio, pinned_life in ladder:
        design = validate_success(
            api.create_design(
                F.design_payload(
                    world.program_id,
                    world.material_id,
                    part_number=part_number,
                    max_working_load_n=max_n,
                    min_working_load_n=min_n,
                    shot_peening_required=False,
                ),
                DESIGN_ENGINEER_HEADERS,
            ),
            expected_status=201,
        )
        created.append(design)

        expected_ratio = A.expected_fatigue_margin(
            C.CLASS_INDUSTRIAL, _WIRE_D, _OUTER_D, max_n, min_n, _TENSILE_MPA, False
        )
        expected_life = A.expected_life_tier(expected_ratio)
        assert (expected_ratio, expected_life) == (pinned_ratio, pinned_life)
        assert design["fatigue_margin_ratio"] == expected_ratio
        A.assert_decimal_places(design["fatigue_margin_ratio"], 3, "fatigue_margin_ratio")
        assert design["predicted_fatigue_life_cycles"] == expected_life
        assert isinstance(design["predicted_fatigue_life_cycles"], int)

    # Every earlier band still reads its own tier after the floor case is written.
    for design, (_, _, _, pinned_ratio, pinned_life) in zip(created, ladder):
        refreshed = X.refresh_design(api, design["id"])
        assert refreshed["fatigue_margin_ratio"] == pinned_ratio
        assert refreshed["predicted_fatigue_life_cycles"] == pinned_life


def test_wire_mass_per_piece_adds_the_hook_extension_tail_allowance(
    api: ApiClient,
) -> None:
    """A hooked end adds its tail twice, once for each end of the part.

    Fifteen millimetres per end lifts the developed length by thirty and the
    per-piece mass from 0.021185 to 0.022341 kg, while the spring rate — whose
    formula never reads the end configuration — stays at 9.031. The same end
    configuration also forces the tangle class HIGH on an index of only 3.000.

    PRD §3.2: "The developed wire length starts from the coil: pi multiplied by the mean coil diameter, multiplied by the active coil count plus an end-coil allowance of two full coils."
    PRD §3.2: "To that is added twice the tail allowance for the declared `end_type`, where a `HOOK_EXTENSION` end contributes 15.0 millimetres of tail per end, a `TORSION_LEG` end contributes 25.0 millimetres per end, and `CLOSED_GROUND`, `CLOSED_UNGROUND` and `OPEN` ends contribute 0.0."
    PRD §3.2: "The cross-sectional area in square metres is pi multiplied by the square of the wire diameter divided by two thousand — that divisor converts a diameter in millimetres to a radius in metres in one step."
    PRD §3.2: "`wire_mass_per_piece_kg` is then the developed length converted from millimetres to metres by dividing by one thousand, multiplied by that area, multiplied by the material's `density_kg_per_m3`, rounded half up to exactly six decimal places."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear modulus multiplied by the wire diameter raised to the fourth power, divided by the product of eight, the mean coil diameter cubed, and the active coil count, with the result rounded half up to three decimal places."
    PRD §3.2: "`tangle_risk_index` is the free length divided by the outer diameter, rounded half up to three decimal places."
    PRD §3.2: "`tangle_risk_class` is `HIGH` when that index is at least 4.000 **or** the `end_type` is `HOOK_EXTENSION`, and `LOW` in every other case."
    PRD §2.6: "Wire mass per piece is carried to **exactly 6 decimal places**, and this rounded value is the only per-piece mass any downstream calculation may read."
    PRD §2.6: "Spring rate is carried to **3 decimal places**."
    PRD §2.6: "Fatigue margin ratio and the tangle-risk index are carried to **3 decimal places**."

    Design: Corner/calculations/wire_mass_per_piece_adds_the_hook_extension_tail_allowance
    """
    world = X.build_world(api, "material")

    design = validate_success(
        api.create_design(
            F.design_payload(
                world.program_id,
                world.material_id,
                part_number="D-HOOK",
                end_type=C.END_HOOK_EXTENSION,
            ),
            DESIGN_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )

    hooked_length = A.developed_length_mm(_WIRE_D, _OUTER_D, 8, C.END_HOOK_EXTENSION)
    plain_length = A.developed_length_mm(_WIRE_D, _OUTER_D, 8, C.END_CLOSED_GROUND)
    assert hooked_length - plain_length == 30.0, "15.0 mm of tail at each of two ends"

    expected_mass = A.expected_wire_mass_per_piece_kg(
        _WIRE_D, _OUTER_D, 8, C.END_HOOK_EXTENSION, _DENSITY
    )
    plain_mass = A.expected_wire_mass_per_piece_kg(
        _WIRE_D, _OUTER_D, 8, C.END_CLOSED_GROUND, _DENSITY
    )
    assert (expected_mass, plain_mass) == (0.022341, 0.021185)
    assert design["wire_mass_per_piece_kg"] == expected_mass
    A.assert_decimal_places(design["wire_mass_per_piece_kg"], 6, "wire_mass_per_piece_kg")

    expected_rate = A.expected_spring_rate(_SHEAR_MODULUS_GPA, _WIRE_D, _OUTER_D, 8)
    assert expected_rate == 9.031
    assert design["spring_rate_n_per_mm"] == expected_rate
    A.assert_decimal_places(design["spring_rate_n_per_mm"], 3, "spring_rate_n_per_mm")

    expected_index = A.expected_tangle_risk_index(60.0, _OUTER_D)
    assert expected_index == 3.0
    assert design["tangle_risk_index"] == expected_index
    A.assert_decimal_places(design["tangle_risk_index"], 3, "tangle_risk_index")
    # The index alone would read LOW; the hooked end is what forces HIGH.
    assert expected_index < 4.0
    assert design["tangle_risk_class"] == A.expected_tangle_risk_class(
        60.0, _OUTER_D, C.END_HOOK_EXTENSION
    )
    assert design["tangle_risk_class"] == C.TANGLE_HIGH


def test_tangle_risk_class_boundary_at_index_four(api: ApiClient) -> None:
    """The class boundary is inclusive at an index of exactly 4.000.

    Two closed-ground twins differing only in free length straddle it: 79.9 mm
    over a 20.0 mm outer diameter reads 3.995 and stays LOW, while 80.0 mm reads
    exactly 4.000 and is already HIGH. Free length reaches neither the mass nor
    the rate, so both twins keep the canonical 0.021185 kg and 9.031 N/mm.

    PRD §3.2: "`tangle_risk_index` is the free length divided by the outer diameter, rounded half up to three decimal places."
    PRD §3.2: "`tangle_risk_class` is `HIGH` when that index is at least 4.000 **or** the `end_type` is `HOOK_EXTENSION`, and `LOW` in every other case."
    PRD §3.2: "`wire_mass_per_piece_kg` is then the developed length converted from millimetres to metres by dividing by one thousand, multiplied by that area, multiplied by the material's `density_kg_per_m3`, rounded half up to exactly six decimal places."
    PRD §2.6: "Fatigue margin ratio and the tangle-risk index are carried to **3 decimal places**."
    PRD §2.6: "Wire mass per piece is carried to **exactly 6 decimal places**, and this rounded value is the only per-piece mass any downstream calculation may read."

    Design: Corner/calculations/tangle_risk_class_boundary_at_index_four
    """
    world = X.build_world(api, "material")

    below = validate_success(
        api.create_design(
            F.design_payload(
                world.program_id,
                world.material_id,
                part_number="D-LOW",
                free_length_mm=79.9,
            ),
            DESIGN_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )
    expected_below_index = A.expected_tangle_risk_index(79.9, _OUTER_D)
    assert expected_below_index == 3.995
    assert below["tangle_risk_index"] == expected_below_index
    A.assert_decimal_places(below["tangle_risk_index"], 3, "tangle_risk_index")
    assert below["tangle_risk_class"] == A.expected_tangle_risk_class(
        79.9, _OUTER_D, C.END_CLOSED_GROUND
    )
    assert below["tangle_risk_class"] == C.TANGLE_LOW

    at_boundary = validate_success(
        api.create_design(
            F.design_payload(
                world.program_id,
                world.material_id,
                part_number="D-HIGH",
                free_length_mm=80.0,
            ),
            DESIGN_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )
    expected_index = A.expected_tangle_risk_index(80.0, _OUTER_D)
    assert expected_index == 4.0
    assert at_boundary["tangle_risk_index"] == expected_index
    A.assert_decimal_places(at_boundary["tangle_risk_index"], 3, "tangle_risk_index")
    assert at_boundary["tangle_risk_class"] == A.expected_tangle_risk_class(
        80.0, _OUTER_D, C.END_CLOSED_GROUND
    )
    assert at_boundary["tangle_risk_class"] == C.TANGLE_HIGH

    expected_mass = A.expected_wire_mass_per_piece_kg(
        _WIRE_D, _OUTER_D, 8, C.END_CLOSED_GROUND, _DENSITY
    )
    assert expected_mass == 0.021185
    assert at_boundary["wire_mass_per_piece_kg"] == expected_mass
    A.assert_decimal_places(
        at_boundary["wire_mass_per_piece_kg"], 6, "wire_mass_per_piece_kg"
    )
    assert below["wire_mass_per_piece_kg"] == expected_mass
    assert X.refresh_design(api, below["id"])["tangle_risk_class"] == C.TANGLE_LOW


def test_tooling_amortization_cap_and_setup_fee_constants_on_a_small_quote(
    api: ApiClient,
) -> None:
    """A 4 800 000-cent tool quoted over 3000 pieces lets the cap bind.

    The raw ask is 1600 cents per piece, but a quarter of the 20.6196-cent
    discounted unit cost floored to a whole cent is 5, so 5 is what the quote
    carries — and the flat 125 000-cent setup fee is what keeps the 203 000-cent
    total above the 78 000 cents of piece price.

    PRD §3.11: "1. The material content per piece is the design's `wire_mass_per_piece_kg` multiplied by the material spec's `cost_per_kg_cents`, rounded to 4 decimal places."
    PRD §3.11: "2. The labour content per piece is the design's `cycle_seconds_per_piece` divided by 3600 and multiplied by the labour rate of 6500 cents per hour, rounded to 4 decimal places."
    PRD §3.11: "3. The base unit cost is the sum of those two, rounded to 4 decimal places."
    PRD §3.11: "4. `quoted_pre_discount_subtotal_cents` is the base unit cost multiplied by `quoted_qty`, rounded to whole cents."
    PRD §3.11: "5. `quoted_volume_discount_pct` is read off that subtotal against the breakpoints 50000, 250000 and 1000000 cents: below 50000 it is 0.00, below 250000 it is 0.03, below 1000000 it is 0.06, and at or above 1000000 it is 0.09."
    PRD §3.11: "6. The discounted unit cost is the base unit cost multiplied by one minus the discount fraction, rounded to 4 decimal places."
    PRD §3.11: "7. The raw amortization ask is the newest tooling asset's `unamortized_cents` divided by `quoted_qty`, rounded **up** to the next whole cent."
    PRD §3.11: "8. The amortization cap is 0.25 of the discounted unit cost, rounded **down** to a whole cent."
    PRD §3.11: "9. `quoted_tooling_amort_per_piece_cents` is the smaller of the raw ask and the cap."
    PRD §3.11: "The cap exists so that tooling recovery can never dominate the piece price: on an expensive tool quoted in small quantity the raw ask is the binding value only until it crosses a quarter of the discounted unit cost."
    PRD §3.11: "10. `quoted_unit_price_cents` is the discounted unit cost plus that per-piece amortization, rounded to whole cents."
    PRD §3.11: "11. `quoted_total_cents` is `quoted_unit_price_cents` multiplied by `quoted_qty` plus the flat setup fee of 125000 cents."
    PRD §3.11: "Per-piece money is carried at 4 decimal places — mills — all the way through step 9, and only steps 4, 8, 10 and 11 land on whole cents."
    PRD §3.11: "The endpoint also increments the program's `version` by 1."
    PRD §3.4: "A newly capitalised tool opens in `amortization_status` `PENDING` with `recovered_cents` at 0 and `unamortized_cents` equal to `original_cost_cents`."
    PRD §2.9: "Shipping a lot posts a recovery into the first and out of the second; taking that lot back reverses the posting using the `tooling_recovery_cents` stored on the lot verbatim."
    PRD §2.6: "Money is integral cents everywhere it is stored."

    Design: Corner/calculations/tooling_amortization_cap_and_setup_fee_constants_on_a_small_quote
    """
    world = X.build_world(api, "tooling")
    assert world.tooling["unamortized_cents"] == _TOOL_COST_CENTS
    assert world.program["quote_frozen"] is False

    quoted_qty = 3000
    program = validate_success(
        api.quote_program(
            world.program_id,
            F.quote_payload(world.design_id, world.program_version, quoted_qty),
            PROGRAM_MANAGER_HEADERS,
        ),
        expected_status=200,
    )

    expected = A.expected_quote(
        C.D1_WIRE_MASS_PER_PIECE_KG,
        _COST_PER_KG_CENTS,
        _CYCLE_SECONDS,
        quoted_qty,
        _TOOL_COST_CENTS,
    )
    assert expected["quoted_pre_discount_subtotal_cents"] == 63772
    assert expected["quoted_volume_discount_pct"] == 0.03
    assert expected["quoted_tooling_amort_per_piece_cents"] == 5
    assert expected["quoted_unit_price_cents"] == 26
    assert expected["quoted_total_cents"] == 203_000
    # The cap, not the raw ask, is the smaller of the two on this quantity.
    assert expected["raw_amortization_ask_cents"] == 1600
    assert expected["amortization_cap_cents"] == 5

    assert program["quoted_qty"] == quoted_qty
    assert program["quoted_pre_discount_subtotal_cents"] == (
        expected["quoted_pre_discount_subtotal_cents"]
    )
    assert program["quoted_volume_discount_pct"] == A.expected_volume_discount_pct(
        expected["quoted_pre_discount_subtotal_cents"]
    )
    assert program["quoted_volume_discount_pct"] == expected["quoted_volume_discount_pct"]
    assert program["quoted_tooling_amort_per_piece_cents"] == (
        expected["quoted_tooling_amort_per_piece_cents"]
    )
    assert program["quoted_unit_price_cents"] == expected["quoted_unit_price_cents"]
    assert program["quoted_total_cents"] == expected["quoted_total_cents"]
    assert program["quoted_total_cents"] == (
        expected["quoted_unit_price_cents"] * quoted_qty + 125_000
    )
    for field in (
        "quoted_pre_discount_subtotal_cents",
        "quoted_tooling_amort_per_piece_cents",
        "quoted_unit_price_cents",
        "quoted_total_cents",
    ):
        assert isinstance(program[field], int), f"{field} is stored in integral cents"
    assert program["version"] == world.program_version + 1

    # Quoting reads the tooling ledger; only a shipment may move it.
    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["unamortized_cents"] == _TOOL_COST_CENTS
    assert tooling["recovered_cents"] == 0
    A.assert_tooling_ledger_conserved(tooling)
    assert program["quote_frozen"] is False


def test_oven_interval_load_excludes_cancelled_batches_from_the_aggregate(
    api: ApiClient,
) -> None:
    """A cancelled batch stops counting toward capacity even on the same window.

    250.000 kg plus 500.000 kg would exceed the oven's 600.000 kg on an interval
    that collides at every instant, so the 500 kg booking is only admissible if
    the cancelled basket's mass has genuinely left the oven, and the oven's
    scheduled load must then read the new basket alone.

    PRD §3.9: "A new oven opens with `scheduled_load_kg` at 0.000, and that field is always the sum of `load_kg` over the oven's batches whose `batch_status` is `SCHEDULED` or `RUNNING`."
    PRD §3.9: "Sum `load_kg` over every batch on the same oven whose `batch_status` is `SCHEDULED` or `RUNNING` and whose window collides with the new one; batches that are `CANCELLED` or `COMPLETE` are excluded even when their windows collide, because their mass has left the oven."
    PRD §3.9: "Add the new batch's `load_kg` to that occupied total, round the sum half up to three decimal places, and compare it against the oven's `capacity_kg`: the comparison is strict, so a total that exceeds capacity is rejected with `ERR_OVEN_CAPACITY_EXCEEDED` (HTTP 409) while a total exactly equal to capacity is accepted."
    PRD §3.9: "A successful booking opens the batch in `batch_status` `SCHEDULED` and adds its `load_kg` to the oven's `scheduled_load_kg`."
    PRD §3.9: "The run's `heat_treat_state` stays `NOT_STARTED` — scheduling a batch is not charging one."
    PRD §3.9: "The batch moves to `CANCELLED` and its `load_kg` is removed from the oven's `scheduled_load_kg`, so the interval it occupied stops counting toward capacity for every later batch booking."
    PRD §2.6: "Every kilogram quantity on a wire lot, a production run, an oven and a heat-treat batch is carried to **3 decimal places**, with the rounding applied once per posting."

    Design: Corner/calculations/oven_interval_load_excludes_cancelled_batches_from_the_aggregate
    """
    world = X.build_world(api, "complete")
    oven = X.commission_oven(api)
    assert oven["capacity_kg"] == 600.0
    assert oven["scheduled_load_kg"] == 0.0

    cancelled = X.schedule_batch(api, oven["id"], world.run_id, load_kg=250.0)
    validate_success(
        api.cancel_batch(cancelled["id"], PROCESS_TECHNICIAN_HEADERS),
        expected_status=200,
    )
    assert X.refresh_oven(api, oven["id"])["scheduled_load_kg"] == 0.0

    new_load = 500.0
    # Both baskets share the identical window, so they collide at every instant.
    assert 250.0 + new_load > oven["capacity_kg"]
    batch = validate_success(
        api.create_batch(
            F.batch_payload(oven["id"], world.run_id, load_kg=new_load),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assert batch["window_start"] == cancelled["window_start"]
    assert batch["window_end"] == cancelled["window_end"]
    assert batch["batch_status"] == C.BATCH_SCHEDULED
    assert batch["load_kg"] == new_load
    A.assert_decimal_places(batch["load_kg"], 3, "load_kg")

    refreshed_oven = X.refresh_oven(api, oven["id"])
    assert refreshed_oven["scheduled_load_kg"] == new_load
    A.assert_decimal_places(refreshed_oven["scheduled_load_kg"], 3, "scheduled_load_kg")

    assert X.refresh_batch(api, cancelled["id"])["batch_status"] == C.BATCH_CANCELLED
    assert X.refresh_run(api, world.run_id)["heat_treat_state"] == (
        C.HEAT_TREAT_NOT_STARTED
    )


def test_setup_window_conflict_ignores_aborted_setups(api: ApiClient) -> None:
    """An aborted booking frees its buffered interval completely.

    The 08:00-10:00Z window widened by the coiler's 45-minute changeover overlaps
    a 09:00-11:00Z booking on both sides of the strict comparison, so the second
    booking is admissible only because an `ABORTED` setup is not considered at
    all — and a setup aborted straight out of `SCHEDULED` neither supersedes nor
    touches the machine it never occupied.

    PRD §3.6: "Two windows conflict when the new window's start is strictly earlier than the existing window's end plus the buffer **and** the existing window's start is strictly earlier than the new window's end plus the buffer."
    PRD §3.6: "Only setups on the same machine whose `setup_status` is `SCHEDULED` or `ACTIVE` are considered; `RELEASED`, `SUPERSEDED` and `ABORTED` setups never conflict, however their windows fall."
    PRD §3.6: "If any such conflicting setup exists, the booking is rejected with `ERR_SETUP_WINDOW_CONFLICT` (HTTP 409)."
    PRD §3.6: "A successful booking stamps `set_by_user_id` from the technician's `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and increases the coiler's `version` by 1."
    PRD §3.6: "It also performs a supersession sweep: every **other** setup on the same machine for the same design whose `setup_status` is `SCHEDULED` transitions `SCHEDULED → SUPERSEDED`, and each superseded row's `superseded_by_setup_id` is set to the id of the setup that has just been created."
    PRD §3.6: "The setup transitions to `ABORTED`."
    PRD §3.6: "If it had been `ACTIVE`, the coiler returns to `machine_state` `IDLE` with `active_setup_id` cleared to null and its `version` increased by 1; a setup aborted straight out of `SCHEDULED` was never occupying the machine and leaves it alone."
    PRD §2.4: "`MachineSetup.superseded_by_setup_id` is likewise a denormalised pointer to the setup whose creation superseded this one, and is null unless the row's `setup_status` is `SUPERSEDED`."

    Design: Corner/calculations/setup_window_conflict_ignores_aborted_setups
    """
    world = X.build_world(api, "machine")
    assert world.machine["changeover_buffer_minutes"] == 45

    aborted = X.book_setup(
        api,
        world.machine,
        world.design_id,
        world.tooling_id,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T10:00:00Z",
    )
    validate_success(
        api.abort_setup(aborted["id"], PROCESS_TECHNICIAN_HEADERS),
        expected_status=200,
    )
    aborted = X.refresh_setup(api, aborted["id"])
    assert aborted["setup_status"] == C.SETUP_ABORTED

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE
    assert machine["active_setup_id"] is None

    booked = X.book_setup(
        api,
        machine,
        world.design_id,
        world.tooling_id,
        window_start="2026-08-05T09:00:00Z",
        window_end="2026-08-05T11:00:00Z",
    )
    assert booked["setup_status"] == C.SETUP_SCHEDULED
    assert booked["window_start"] == "2026-08-05T09:00:00Z"
    assert booked["window_end"] == "2026-08-05T11:00:00Z"
    # The buffered intervals do overlap, both ways round, on the strict test.
    # 09:00 < 10:00 + 45 min, and 08:00 < 11:00 + 45 min.
    assert booked["set_by_user_id"] == PROCESS_TECHNICIAN_HEADERS["X-User-ID"]

    still_aborted = X.refresh_setup(api, aborted["id"])
    assert still_aborted["setup_status"] == C.SETUP_ABORTED
    assert still_aborted["superseded_by_setup_id"] is None

    final_machine = X.refresh_machine(api, world.machine_id)
    assert final_machine["machine_state"] == C.MACHINE_IDLE
    assert final_machine["active_setup_id"] is None
    assert final_machine["version"] == machine["version"] + 1


def test_delivery_posture_stays_at_risk_after_the_hold_clears_until_the_lot_is_released(
    api: ApiClient,
) -> None:
    """Lifting the run hold is not the same event as emptying the quarantine.

    The out-of-control safety-critical subgroup drives both inputs of the posture
    rule at once, and the `RELEASE` verdict clears only one of them: the program
    stays `AT_RISK` on a positive quarantine count and reaches `ON_TRACK` only
    when the lot itself comes back, which also re-charges its pieces against the
    live commitment.

    PRD §3.1: "The rule reads three inputs and returns one of `BLOCKED`, `AT_RISK` or `ON_TRACK`, considering only rows belonging to this program: whether at least one qualification submission of this program is in `APPROVED` or `INTERIM_APPROVED` status; whether at least one production run whose design belongs to this program currently has a quality status of `SPC_HOLD`; and the program's own `quarantined_lot_count`."
    PRD §3.1: "Otherwise, if `quarantined_lot_count` is at least 1 **or** such a held run exists, the posture is `AT_RISK`."
    PRD §3.1: "Otherwise the posture is `ON_TRACK`."
    PRD §3.8: "Hop two: the run's `quality_status` transitions `OPEN → SPC_HOLD`."
    PRD §3.8: "Hop three: every shipment lot of this run whose `lot_status` is `ALLOCATED` or `PACKED` transitions to `QUARANTINED` with `quarantine_reason` set to `SPC_HOLD_CASCADE`."
    PRD §3.8: "Hop four: for each lot so quarantined, the lot's owning program has the lot's `piece_count` added back to `open_commitment_pieces`, has `quarantined_lot_count` increased by 1, and has `allocated_pieces` decreased by that same `piece_count`."
    PRD §3.8: "The hold only fires while the run's `quality_status` is `OPEN`; a run already on `SPC_HOLD` simply accumulates further records."
    PRD §3.8: "`RELEASE` returns the run `SPC_HOLD → OPEN` and is the cyclic edge on the quality axis — a run can be held and released repeatedly over its life."
    PRD §3.8: "It requires evidence that the process has come back: for **every** safety-critical characteristic of the run's design, the newest inspection record by `created_at` must have a `control_state` of `IN_CONTROL`."
    PRD §3.8: "Neither verdict un-quarantines anything: lots quarantined by the cascade stay `QUARANTINED`, no program counter moves, and this operation only lifts the run-level hold."
    PRD §3.8: "`delivery_posture` is nevertheless re-derived for every program holding a lot on this run, and a program whose `quarantined_lot_count` is still positive stays `AT_RISK`."
    PRD §3.11: "Success returns the lot to `ALLOCATED`, clears `quarantine_reason` back to null and clears `packaging_method` to null — **the lot must be packed again**, and the packaging rules are re-applied from scratch."
    PRD §3.11: "The program's `quarantined_lot_count` decreases by 1, `allocated_pieces` increases by `piece_count`, `open_commitment_pieces` decreases by it, and `delivery_posture` is re-derived, returning to `ON_TRACK` only when the last quarantined lot has been released and no run of the program is on hold."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."

    Design: Corner/calculations/delivery_posture_stays_at_risk_after_the_hold_clears_until_the_lot_is_released
    """
    world = X.build_world(api, "allocated")
    characteristic = world.characteristics[0]
    lsl, usl = characteristic["lsl"], characteristic["usl"]
    piece_count = world.lot["piece_count"]
    assert piece_count == 1_000
    assert world.program["delivery_posture"] == A.expected_delivery_posture(True, 0, False)
    assert world.program["delivery_posture"] == C.POSTURE_ON_TRACK

    breach = [59.4, 60.0, 60.6]
    expected_breach_cpk = A.expected_cpk_value(breach, lsl, usl)
    assert expected_breach_cpk == 0.278
    breach_record = validate_success(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(characteristic["id"], breach),
            QUALITY_INSPECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert breach_record["cpk_value"] == expected_breach_cpk
    A.assert_decimal_places(breach_record["cpk_value"], 3, "cpk_value")
    assert breach_record["control_state"] == A.expected_control_state(
        breach, lsl, usl, characteristic["cpk_floor"]
    )
    assert breach_record["control_state"] == C.CONTROL_OUT_OF_CONTROL
    assert characteristic["is_safety_critical"] is True

    held_run = X.refresh_run(api, world.run_id)
    assert held_run["quality_status"] == C.QUALITY_SPC_HOLD
    quarantined = X.refresh_lot(api, world.lot_id)
    assert quarantined["lot_status"] == C.LOT_QUARANTINED
    assert quarantined["quarantine_reason"] == C.QUARANTINE_SPC_HOLD_CASCADE
    held_program = X.refresh_program(api, world.program_id)
    assert held_program["quarantined_lot_count"] == 1
    assert held_program["allocated_pieces"] == 0
    assert held_program["open_commitment_pieces"] == 500_000
    assert held_program["delivery_posture"] == A.expected_delivery_posture(True, 1, True)
    assert held_program["delivery_posture"] == C.POSTURE_AT_RISK

    # Evidence that the process came back, so the verdict has something to read.
    recovery = validate_success(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(characteristic["id"], list(C.IN_CONTROL_SUBGROUP)),
            QUALITY_INSPECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert recovery["control_state"] == C.CONTROL_IN_CONTROL

    validate_success(
        api.quality_disposition(
            world.run_id,
            {"decision": C.DECISION_RELEASE},
            QUALITY_INSPECTOR_HEADERS,
        ),
        expected_status=200,
    )
    released_run = X.refresh_run(api, world.run_id)
    assert released_run["quality_status"] == C.QUALITY_OPEN
    mid_program = X.refresh_program(api, world.program_id)
    assert mid_program["quarantined_lot_count"] == 1
    assert mid_program["delivery_posture"] == A.expected_delivery_posture(True, 1, False)
    assert mid_program["delivery_posture"] == C.POSTURE_AT_RISK
    assert X.refresh_lot(api, world.lot_id)["lot_status"] == C.LOT_QUARANTINED

    lot = validate_success(
        api.release_lot_from_quarantine(world.lot_id, QUALITY_INSPECTOR_HEADERS),
        expected_status=200,
    )
    assert lot["lot_status"] == C.LOT_ALLOCATED
    assert lot["quarantine_reason"] is None
    assert lot["packaging_method"] is None

    program = X.refresh_program(api, world.program_id)
    assert program["quarantined_lot_count"] == 0
    assert program["allocated_pieces"] == piece_count
    assert program["open_commitment_pieces"] == 500_000 - piece_count
    assert program["open_commitment_pieces"] == 499_000
    assert program["delivery_posture"] == A.expected_delivery_posture(True, 0, False)
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK
    A.assert_commitment_conserved(program)

    final_run = X.refresh_run(api, world.run_id)
    assert final_run["quality_status"] == C.QUALITY_OPEN
    assert final_run["min_cpk_observed"] == expected_breach_cpk
