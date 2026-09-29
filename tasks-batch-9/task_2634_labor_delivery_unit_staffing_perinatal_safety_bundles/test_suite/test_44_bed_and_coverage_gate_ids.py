"""Five bed and coverage refusals that all guard the same two operations.

The coverage floor and the bed requirement both block the antepartum-to-latent
edge, so the bed refusal is observable only on a patient whose staffing is
already satisfied. The operating-room probes are the mirror of that: an
available theatre bed offered to a labour admission must answer the eligibility
id rather than the availability id, while a blocked theatre bed offered to a
crash section must answer the availability id even though the team named
alongside it is also incomplete.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_cesarean_event,
    assert_labor_encounter,
    bootstrap_unit,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"


def _rn(full_name):
    return {
        "full_name": full_name,
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    }


ALDER_GROVE_STAFF = {
    "charge": _rn("Ingrid Solheim RN"),
    "second": _rn("Halldora Bjarnadottir RN"),
    "third": _rn("Amara Nwachukwu RN"),
    "ob": {
        "full_name": "Priya Raman MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
}


@pytest.fixture
def one_covered_patient_one_bare_patient_and_one_theatre_bed():
    """Eleven calls: two phase attempts, three bed attempts, then a crash section
    offered a blocked theatre bed and an incomplete team."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=2,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("OR-01", "OR")],
        staff_specs=ALDER_GROVE_STAFF,
        unit_overrides={"unit_name": "Alder Grove Birth Center LDR"},
    )
    shift = create_active_shift(world, "charge", "BEDSIDE", SHIFT_START, SHIFT_END)
    covered = create_encounter(
        world,
        patient_record_code="PRC-ALDER-3301",
        parity=1,
        gestational_age_weeks=39,
    )
    bare = create_encounter(
        world,
        patient_record_code="PRC-ALDER-3302",
        parity=1,
        gestational_age_weeks=39,
    )
    create_care_assignment(
        world,
        covered,
        shift,
        coverage_mode="RATIO_SHARED",
        expected_encounter_version=covered["version"],
    )
    without_coverage = api_client.advance_phase(
        bare["id"], {"target_phase": "LATENT"}, world.charge_headers
    )
    without_a_bed = api_client.advance_phase(
        covered["id"], {"target_phase": "LATENT"}, world.charge_headers
    )
    offered_a_theatre_bed = api_client.assign_bed(
        covered["id"], {"bed_id": world.bed_id("OR-01")}, world.charge_headers
    )
    attached = api_client.assign_bed(
        covered["id"], {"bed_id": world.bed_id("LDR-01")}, world.charge_headers
    )
    offered_a_second_bed = api_client.assign_bed(
        covered["id"], {"bed_id": world.bed_id("LDR-02")}, world.charge_headers
    )
    advanced = api_client.advance_phase(
        covered["id"], {"target_phase": "LATENT"}, world.charge_headers
    )
    get_success_data(
        api_client.patch_bed(
            world.bed_id("OR-01"), {"status": "BLOCKED"}, world.charge_headers
        )
    )
    event = get_success_data(
        api_client.create_cesarean(
            {"encounter_id": covered["id"], "urgency_class": "CATEGORY_1_CRASH"},
            world.ob_headers,
        )
    )
    team = [world.staff_id("charge"), world.staff_id("second"), world.staff_id("third")]
    on_a_blocked_theatre = api_client.mobilize_team(
        event["id"],
        {"or_bed_id": world.bed_id("OR-01"), "staff_ids": team},
        world.ob_headers,
    )
    get_success_data(
        api_client.patch_bed(
            world.bed_id("OR-01"), {"status": "AVAILABLE"}, world.charge_headers
        )
    )
    with_the_wrong_team = api_client.mobilize_team(
        event["id"],
        {"or_bed_id": world.bed_id("OR-01"), "staff_ids": team},
        world.ob_headers,
    )
    return {
        "world": world,
        "shift": shift,
        "covered": covered,
        "bare": bare,
        "event": event,
        "team": team,
        "without_coverage": without_coverage,
        "without_a_bed": without_a_bed,
        "offered_a_theatre_bed": offered_a_theatre_bed,
        "attached": attached,
        "offered_a_second_bed": offered_a_second_bed,
        "advanced": advanced,
        "on_a_blocked_theatre": on_a_blocked_theatre,
        "with_the_wrong_team": with_the_wrong_team,
    }


def test_an_uncovered_patient_is_stopped_by_the_coverage_floor(
    one_covered_patient_one_bare_patient_and_one_theatre_bed,
):
    """"Moving `ANTEPARTUM` to `LATENT` requires the coverage axis to be
    `RATIO_COVERED` or `ONE_TO_ONE_COVERED`, refused otherwise with
    `ERR_ENCOUNTER_COVERAGE_INSUFFICIENT`; requires `bed_id` to be non-null with that
    bed `OCCUPIED` and of type `LDR`, refused otherwise with
    `ERR_ENCOUNTER_BED_NOT_ASSIGNED`; and requires the unit's posture to be anything
    other than `DIVERT`, refused otherwise with `ERR_UNIT_POSTURE_BLOCKS_OPERATION`."

    Design: Corner/errors/five_bed_and_coverage_gate_ids_separate_across_the_8_03_8_07_and_13_3_rungs
    """
    setup = one_covered_patient_one_bare_patient_and_one_theatre_bed
    refused = setup["without_coverage"]
    validate_error(refused, ApiErrorId.ERR_ENCOUNTER_COVERAGE_INSUFFICIENT.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_ENCOUNTER_BED_NOT_ASSIGNED.value
    )
    unmoved = reload_encounter(setup["world"], setup["bare"]["id"])
    assert_labor_encounter(unmoved)
    assert unmoved["labor_phase"] == "ANTEPARTUM"
    assert unmoved["staffing_state"] == "UNASSIGNED"


def test_a_covered_but_bedless_patient_reaches_the_bed_requirement(
    one_covered_patient_one_bare_patient_and_one_theatre_bed,
):
    """"**13.3** bed interval collision and bed eligibility, yielding
    `ERR_BED_TURNOVER_CONFLICT`, `ERR_BED_TYPE_NOT_ELIGIBLE` or
    `ERR_ENCOUNTER_BED_NOT_ASSIGNED`, on induction capacity holding, encounter bed
    attachment, phase advance and cesarean team mobilisation."

    Design: Corner/errors/five_bed_and_coverage_gate_ids_separate_across_the_8_03_8_07_and_13_3_rungs
    """
    setup = one_covered_patient_one_bare_patient_and_one_theatre_bed
    validate_error(
        setup["without_a_bed"], ApiErrorId.ERR_ENCOUNTER_BED_NOT_ASSIGNED.value, 409
    )


def test_a_theatre_bed_is_not_eligible_for_a_labour_admission(
    one_covered_patient_one_bare_patient_and_one_theatre_bed,
):
    """"`bed_type` is one of `LDR`, `OR`, `TRIAGE` or `POSTPARTUM`, and the type decides
    what the bed can be used for: only an `LDR` bed satisfies an induction hold or a
    walk-in admission, and only an `OR` bed satisfies a cesarean mobilisation, with a
    mismatch refused as `ERR_BED_TYPE_NOT_ELIGIBLE`."

    Design: Corner/errors/five_bed_and_coverage_gate_ids_separate_across_the_8_03_8_07_and_13_3_rungs
    """
    setup = one_covered_patient_one_bare_patient_and_one_theatre_bed
    refused = setup["offered_a_theatre_bed"]
    validate_error(refused, ApiErrorId.ERR_BED_TYPE_NOT_ELIGIBLE.value, 409)
    assert (
        refused.json()["data"]["error_id"] != ApiErrorId.ERR_OR_BED_UNAVAILABLE.value
    )


def test_a_patient_already_in_a_bed_cannot_take_a_second_one(
    one_covered_patient_one_bare_patient_and_one_theatre_bed,
):
    """"Attaching a bed is a separate `ChargeNurse` act naming `bed_id`; the bed must be
    of type `LDR` and `AVAILABLE`, it moves to `OCCUPIED` with `current_encounter_id`
    pointing at the encounter, and an encounter that already occupies a bed is refused
    with `ERR_ENCOUNTER_ALREADY_IN_BED`."

    Design: Corner/errors/five_bed_and_coverage_gate_ids_separate_across_the_8_03_8_07_and_13_3_rungs
    """
    setup = one_covered_patient_one_bare_patient_and_one_theatre_bed
    world = setup["world"]
    assert setup["attached"].status_code == 200
    validate_error(
        setup["offered_a_second_bed"], ApiErrorId.ERR_ENCOUNTER_ALREADY_IN_BED.value, 409
    )
    taken = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert_bed(taken)
    assert taken["status"] == "OCCUPIED"
    assert taken["current_encounter_id"] == setup["covered"]["id"]
    spare = get_success_data(
        api_client.get_bed(world.bed_id("LDR-02"), world.charge_headers)
    )
    assert_bed(spare)
    assert spare["status"] == "AVAILABLE"
    assert spare["current_encounter_id"] is None
    assert get_success_data(setup["advanced"])["labor_phase"] == "LATENT"


def test_a_blocked_theatre_bed_is_reported_before_the_team_is_examined(
    one_covered_patient_one_bare_patient_and_one_theatre_bed,
):
    """"It names `or_bed_id`, which must be a bed of `bed_type` `OR` on the encounter's
    own unit whose `status` is `AVAILABLE`, refused otherwise with
    `ERR_OR_BED_UNAVAILABLE`, and `staff_ids`, an array of 3 to 12 staff identifiers
    whose payload order is preserved verbatim in `mobilized_staff_ids`."

    Design: Corner/errors/five_bed_and_coverage_gate_ids_separate_across_the_8_03_8_07_and_13_3_rungs
    """
    setup = one_covered_patient_one_bare_patient_and_one_theatre_bed
    refused = setup["on_a_blocked_theatre"]
    validate_error(refused, ApiErrorId.ERR_OR_BED_UNAVAILABLE.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_CESAREAN_TEAM_INCOMPLETE.value
    )
    assert len(setup["team"]) == 3


def test_the_team_refusal_was_waiting_behind_the_bed_refusal(
    one_covered_patient_one_bare_patient_and_one_theatre_bed,
):
    """"That array must contain at least one staff member with `staff_role`
    `ANESTHESIOLOGIST`, at least one `SURGICAL_TECH` whose `or_circulating_qualified` is
    true, and at least one `NEONATAL_RESUSCITATOR`, each holding an `ACTIVE` roster entry
    on the unit, refused otherwise with `ERR_CESAREAN_TEAM_INCOMPLETE`."

    Design: Corner/errors/five_bed_and_coverage_gate_ids_separate_across_the_8_03_8_07_and_13_3_rungs
    """
    setup = one_covered_patient_one_bare_patient_and_one_theatre_bed
    world = setup["world"]
    validate_error(
        setup["with_the_wrong_team"], ApiErrorId.ERR_CESAREAN_TEAM_INCOMPLETE.value, 422
    )
    event = get_success_data(
        api_client.get_cesarean(setup["event"]["id"], world.ob_headers)
    )
    assert_cesarean_event(event)
    assert event["status"] == "DECISION_DECLARED"
    assert event["or_bed_id"] is None
    theatre = get_success_data(
        api_client.get_bed(world.bed_id("OR-01"), world.charge_headers)
    )
    assert_bed(theatre)
    assert theatre["status"] == "AVAILABLE"
    assert theatre["current_encounter_id"] is None
