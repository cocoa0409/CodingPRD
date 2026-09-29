"""A support pass check-in turns on the state of a cesarean event it never names.

Two check-ins hit the same endpoint on the same encounter at the same instant
with the same occupancy figure. The partner pass is refused because an event on
the encounter is in TEAM_MOBILIZED; the OR-credentialed doula is admitted, and
lands exactly on the allowance of 1 that the same event forces.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_cesarean_event,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_instant_equals,
    assert_instant_is_null,
    assert_support_pass,
    bootstrap_unit,
    create_active_shift,
    create_encounter,
    create_pass,
    declare_cesarean,
    get_success_data,
    mobilize_cesarean,
    reload_encounter,
    reload_pass,
    setup_validated_drill,
)

CLOCK_START = "2026-08-25T08:00:00Z"
CLOCK_SETTLED = "2026-08-25T08:30:00Z"
SHIFT_START = "2026-08-25T08:00:00Z"
SHIFT_END = "2026-08-25T18:00:00Z"
SIMULATED_INCISION = "2026-08-25T08:20:00Z"
DOULA_CERT_EXPIRY = "2027-01-31T00:00:00Z"
EXPECTED_PASS_VALIDITY = "2026-08-26T08:30:00Z"

VISIT_STAFF = {
    "ob": {
        "full_name": "Isambard Ketteridge MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "or_circulating_qualified": True,
    },
    "anesthesia": {
        "full_name": "Leontine Bruggeman MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": False,
    },
    "tech": {
        "full_name": "Thandeka Mokoena",
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": True,
    },
    "neonatal": {
        "full_name": "Emyr Llewellyn-Price",
        "staff_role": "NEONATAL_RESUSCITATOR",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": False,
    },
    "charge": {
        "full_name": "Guadalupe Serrano RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Hyacinth Okwuosa RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def two_passes_against_a_mobilized_theatre():
    """An ANTEPARTUM encounter with no care assignment, one PARTNER pass and one
    OR-credentialed DOULA_CERTIFIED pass, and a mobilized CATEGORY_2_URGENT
    event holding the operating room."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=2,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("OR-01", "OR")],
        staff_specs=VISIT_STAFF,
        unit_overrides={"unit_name": "Bramblewick Shore Maternity"},
    )
    drill = setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at=CLOCK_START,
        incision_at=SIMULATED_INCISION,
        document_clock=CLOCK_SETTLED,
    )
    for key in ("anesthesia", "tech", "neonatal"):
        create_active_shift(world, key, "BEDSIDE", SHIFT_START, SHIFT_END)

    encounter = create_encounter(
        world,
        patient_record_code="PRC-VISIT-6620",
        parity=1,
        gestational_age_weeks=39,
        prior_cesarean=False,
        fetus_count=1,
        presentation="VERTEX",
    )
    partner_pass = create_pass(
        world, encounter, person_name="Cassius Odenigbo", credential_type="PARTNER"
    )
    doula_pass = create_pass(
        world,
        encounter,
        person_name="Marisol Etxeberria",
        credential_type="DOULA_CERTIFIED",
        doula_certification_expires_at=DOULA_CERT_EXPIRY,
        or_credentialed=True,
    )
    event = declare_cesarean(world, encounter, urgency_class="CATEGORY_2_URGENT")
    mobilized = mobilize_cesarean(
        world, event, "OR-01", staff_keys=["anesthesia", "tech", "neonatal"]
    )

    partner_refused = api_client.check_in_pass(partner_pass["id"], world.access_headers)
    doula_admitted = api_client.check_in_pass(doula_pass["id"], world.access_headers)
    return {
        "world": world,
        "drill": drill,
        "encounter": encounter,
        "partner_pass": partner_pass,
        "doula_pass": doula_pass,
        "event": event,
        "mobilized": mobilized,
        "partner_refused": partner_refused,
        "doula_admitted": doula_admitted,
    }


def test_the_partner_is_refused_by_the_procedure_not_the_count(
    two_passes_against_a_mobilized_theatre,
):
    """"If any cesarean event on the encounter sits in `TEAM_MOBILIZED` or
    `INCISION_RECORDED`, the check-in is refused with
    `ERR_VISITATION_RESTRICTED_BY_PROCEDURE` unless this pass is a
    `DOULA_CERTIFIED` pass whose `or_credentialed` is true."

    Design: Difficulty/cross_entity_state_dependency/mobilized_cesarean_event_blocks_partner_pass_check_in_while_admitting_or_credentialed_doula_pass
    """
    response = two_passes_against_a_mobilized_theatre["partner_refused"]
    validate_error(
        response, ApiErrorId.ERR_VISITATION_RESTRICTED_BY_PROCEDURE.value, 422
    )
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_SUPPORT_OCCUPANCY_EXCEEDED.value
    )


def test_the_refused_partner_pass_is_untouched(two_passes_against_a_mobilized_theatre):
    """"The pass opens at `ISSUED` with `valid_until` set to the current instant
    plus 24 hours, and an issued pass occupies nothing until it is checked in" —
    and "a first check-in from `ISSUED` does not touch that counter".

    Design: Difficulty/cross_entity_state_dependency/mobilized_cesarean_event_blocks_partner_pass_check_in_while_admitting_or_credentialed_doula_pass
    """
    setup = two_passes_against_a_mobilized_theatre
    support_pass = reload_pass(setup["world"], setup["partner_pass"]["id"])
    assert_support_pass(support_pass)
    assert support_pass["credential_type"] == "PARTNER"
    assert support_pass["status"] == "ISSUED"
    assert_instant_is_null(support_pass["checked_in_at"], "checked_in_at")
    assert support_pass["reentry_count"] == 0
    assert support_pass["version"] == 1


def test_the_or_credentialed_doula_is_admitted(two_passes_against_a_mobilized_theatre):
    """"which is the one pass allowed to follow the patient into theatre" —
    "Success sets `checked_in_at` to the current instant and clears
    `checked_out_at` to null".

    Design: Difficulty/cross_entity_state_dependency/mobilized_cesarean_event_blocks_partner_pass_check_in_while_admitting_or_credentialed_doula_pass
    """
    setup = two_passes_against_a_mobilized_theatre
    support_pass = get_success_data(setup["doula_admitted"])
    assert_support_pass(support_pass)
    assert support_pass["credential_type"] == "DOULA_CERTIFIED"
    assert support_pass["or_credentialed"] is True
    assert support_pass["status"] == "CHECKED_IN"
    assert_instant_equals(support_pass["checked_in_at"], CLOCK_SETTLED, "checked_in_at")
    assert_instant_is_null(support_pass["checked_out_at"], "checked_out_at")
    assert support_pass["reentry_count"] == 0
    assert_instant_equals(
        support_pass["valid_until"], EXPECTED_PASS_VALIDITY, "valid_until"
    )


def test_the_mobilized_event_holds_the_operating_room(
    two_passes_against_a_mobilized_theatre,
):
    """"Mobilising takes the OR bed from `AVAILABLE` to `OCCUPIED`" — the event
    the passes have no reference to is reachable only sideways through the
    encounter they share.

    Design: Difficulty/cross_entity_state_dependency/mobilized_cesarean_event_blocks_partner_pass_check_in_while_admitting_or_credentialed_doula_pass
    """
    setup = two_passes_against_a_mobilized_theatre
    world = setup["world"]
    event = setup["mobilized"]
    assert_cesarean_event(event)
    assert event["status"] == "TEAM_MOBILIZED"
    assert event["or_bed_id"] == world.bed_id("OR-01")
    bed = get_success_data(api_client.get_bed(world.bed_id("OR-01"), world.charge_headers))
    assert_bed(bed)
    assert bed["status"] == "OCCUPIED"


def test_the_restriction_is_not_keyed_on_the_labor_phase(
    two_passes_against_a_mobilized_theatre,
):
    """The encounter never leaves its opening "`labor_phase` at `ANTEPARTUM`",
    yet mobilisation "sets the encounter's `one_to_one_required` to true with the
    usual re-pricing", giving "4.0 when one-to-one coverage is required".

    Design: Difficulty/cross_entity_state_dependency/mobilized_cesarean_event_blocks_partner_pass_check_in_while_admitting_or_credentialed_doula_pass
    """
    setup = two_passes_against_a_mobilized_theatre
    encounter = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "ANTEPARTUM"
    assert encounter["one_to_one_required"] is True
    assert encounter["acuity_tier"] == "TIER_IV"
    assert encounter["required_coverage_units"] == pytest.approx(4.0, abs=1e-9)
    assert encounter["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_uncovered_requirement_freezes_the_unit(
    two_passes_against_a_mobilized_theatre,
):
    """"`INDUCTION_FROZEN` when the deficit is 4.0 or greater" — the uncovered
    4.0 requirement is a 4.0 deficit, and that posture is the second, agreeing
    route to an allowance of 1.

    Design: Difficulty/cross_entity_state_dependency/mobilized_cesarean_event_blocks_partner_pass_check_in_while_admitting_or_credentialed_doula_pass
    """
    unit = two_passes_against_a_mobilized_theatre["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(4.0, abs=1e-9)
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert unit["cesarean_readiness_state"] == "DEGRADED"
