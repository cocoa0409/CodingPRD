"""Two narrow write paths whose inputs are deliberately smaller than the enum.

The bed toggle accepts exactly two of the six bed statuses and refuses one of
those two on a bed a patient is lying in, so it has one shape refusal and one
state refusal on top of a working round trip. A visitor pass has the one body
field that is required in one branch and forbidden in the other, and its
freshness is a separate rung below its shape.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_instant_equals,
    assert_instant_is_null,
    assert_obstetric_unit,
    assert_support_pass,
    assign_bed,
    bootstrap_unit,
    create_encounter,
    get_success_data,
)

CLOCK_START = "2026-08-01T06:00:00Z"
PASS_VALID_UNTIL = "2026-08-02T06:00:00Z"
LAPSED_DOULA_CREDENTIAL = "2026-07-01T00:00:00Z"
LIVE_DOULA_CREDENTIAL = "2027-01-01T00:00:00Z"

TOGGLE_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_DOULA_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


def _bedded_unit(unit_name, patient_record_code):
    """Two LDR beds, the first one occupied by a walk-in, the second free."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=TOGGLE_STAFF,
        unit_overrides={"unit_name": unit_name},
    )
    encounter = create_encounter(
        world,
        patient_record_code=patient_record_code,
        parity=1,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    return world, encounter


@pytest.fixture
def a_free_bed_toggled_twice_and_an_occupied_bed_refused():
    """Four PATCH calls: block, unblock, block an occupied bed, then an out-of-enum
    target on the free one."""
    world, encounter = _bedded_unit("Rowan Perinatal Center LDR", "PRC-BEDPATCH-807")
    blocked = api_client.patch_bed(
        world.bed_id("LDR-02"), {"status": "BLOCKED"}, world.charge_headers
    )
    unblocked = api_client.patch_bed(
        world.bed_id("LDR-02"), {"status": "AVAILABLE"}, world.charge_headers
    )
    on_an_occupied_bed = api_client.patch_bed(
        world.bed_id("LDR-01"), {"status": "BLOCKED"}, world.charge_headers
    )
    out_of_enum = api_client.patch_bed(
        world.bed_id("LDR-02"), {"status": "TURNOVER"}, world.charge_headers
    )
    return {
        "world": world,
        "encounter": encounter,
        "blocked": blocked,
        "unblocked": unblocked,
        "on_an_occupied_bed": on_an_occupied_bed,
        "out_of_enum": out_of_enum,
    }


def test_the_manual_round_trip_between_available_and_blocked_is_open(
    a_free_bed_toggled_twice_and_an_occupied_bed_refused,
):
    """"A `ChargeNurse` may toggle a bed between `AVAILABLE` and `BLOCKED` by
    supplying `status`; those are the only two values that path accepts, and a bed
    currently `HELD`, `OCCUPIED` or `TURNOVER` cannot be blocked, which is refused
    with `ERR_BED_NOT_RELEASABLE`."

    Design: Corner/endpoints/bed_status_patch_flips_available_and_blocked_but_refuses_an_occupied_bed
    """
    setup = a_free_bed_toggled_twice_and_an_occupied_bed_refused
    assert setup["blocked"].status_code == 200
    blocked = get_success_data(setup["blocked"])
    assert_bed(blocked)
    assert blocked["status"] == "BLOCKED"
    assert setup["unblocked"].status_code == 200
    unblocked = get_success_data(setup["unblocked"])
    assert_bed(unblocked)
    assert unblocked["status"] == "AVAILABLE"


def test_a_bed_with_a_patient_in_it_cannot_be_blocked(
    a_free_bed_toggled_twice_and_an_occupied_bed_refused,
):
    """"**8.07** bed lifecycle guards, yielding `ERR_OR_BED_UNAVAILABLE`,
    `ERR_BED_HOLD_MISMATCH`, `ERR_BED_NOT_RELEASABLE`, `ERR_BED_HAS_FUTURE_HOLDS` or
    `ERR_ENCOUNTER_ALREADY_IN_BED`, on induction capacity holding, induction
    admission, encounter bed attachment, cesarean team mobilisation, bed status
    change and bed retirement."

    Design: Corner/endpoints/bed_status_patch_flips_available_and_blocked_but_refuses_an_occupied_bed
    """
    setup = a_free_bed_toggled_twice_and_an_occupied_bed_refused
    validate_error(
        setup["on_an_occupied_bed"], ApiErrorId.ERR_BED_NOT_RELEASABLE.value, 409
    )
    world = setup["world"]
    occupied = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert_bed(occupied)
    assert occupied["status"] == "OCCUPIED"
    assert occupied["current_encounter_id"] == setup["encounter"]["id"]


def test_a_lifecycle_only_status_is_refused_as_a_field_value(
    a_free_bed_toggled_twice_and_an_occupied_bed_refused,
):
    """"**Priority 5** — field types, enum membership, string lengths and numeric
    ranges, on every operation: `ERR_INVALID_FIELD_VALUE` at HTTP 400."

    Design: Corner/endpoints/bed_status_patch_flips_available_and_blocked_but_refuses_an_occupied_bed
    """
    setup = a_free_bed_toggled_twice_and_an_occupied_bed_refused
    validate_error(setup["out_of_enum"], ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400)
    world = setup["world"]
    free = get_success_data(
        api_client.get_bed(world.bed_id("LDR-02"), world.charge_headers)
    )
    assert_bed(free)
    assert free["status"] == "AVAILABLE"
    assert free["current_encounter_id"] is None
    assert free["held_booking_id"] is None
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] != "DIVERT"


@pytest.fixture
def four_visitor_passes_offered_on_one_patient():
    """A doula pass with no credential, a partner pass carrying one, a doula pass
    carrying a lapsed one, then the two well-formed passes."""
    world, encounter = _bedded_unit("Thistledown Perinatal Center LDR", "PRC-DOULA-116")

    def _issue(payload):
        return api_client.create_pass(
            dict(payload, encounter_id=encounter["id"]), world.access_headers
        )

    missing_field = _issue({"person_name": "Imani Boyd", "credential_type": "DOULA_CERTIFIED"})
    forbidden_field = _issue(
        {
            "person_name": "Marcus Boyd",
            "credential_type": "PARTNER",
            "doula_certification_expires_at": LIVE_DOULA_CREDENTIAL,
        }
    )
    lapsed = _issue(
        {
            "person_name": "Imani Boyd",
            "credential_type": "DOULA_CERTIFIED",
            "doula_certification_expires_at": LAPSED_DOULA_CREDENTIAL,
        }
    )
    doula = _issue(
        {
            "person_name": "Imani Boyd",
            "credential_type": "DOULA_CERTIFIED",
            "doula_certification_expires_at": LIVE_DOULA_CREDENTIAL,
        }
    )
    partner = _issue({"person_name": "Marcus Boyd", "credential_type": "PARTNER"})
    return {
        "world": world,
        "encounter": encounter,
        "missing_field": missing_field,
        "forbidden_field": forbidden_field,
        "lapsed": lapsed,
        "doula": doula,
        "partner": partner,
    }


def test_the_doula_expiry_is_required_in_one_branch_and_forbidden_in_the_other(
    four_visitor_passes_offered_on_one_patient,
):
    """"A `PatientAccessCoordinator` or `ChargeNurse` issues a support person pass
    on an encounter, naming `person_name` of 1 to 120 characters, an immutable
    `credential_type` of `PARTNER`, `DOULA_CERTIFIED`, `STUDENT_OBSERVER` or
    `INTERPRETER`, a `doula_certification_expires_at` which is required when the
    credential is `DOULA_CERTIFIED` and forbidden otherwise and which must be
    strictly after the current instant, refused otherwise with
    `ERR_DOULA_CREDENTIAL_EXPIRED`, and an optional `or_credentialed` flag defaulting
    to false."

    Design: Corner/endpoints/doula_certification_expiry_is_required_for_a_doula_pass_and_forbidden_for_a_partner_pass
    """
    setup = four_visitor_passes_offered_on_one_patient
    validate_error(
        setup["missing_field"], ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400
    )
    validate_error(
        setup["forbidden_field"], ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400
    )


def test_a_lapsed_credential_is_a_visitation_refusal_not_a_shape_refusal(
    four_visitor_passes_offered_on_one_patient,
):
    """"**11.6** visitation safety, yielding `ERR_SUPPORT_PASS_EXPIRED`,
    `ERR_DOULA_CREDENTIAL_EXPIRED` or `ERR_VISITATION_RESTRICTED_BY_PROCEDURE`, on
    support pass issuance and support pass check-in."

    Design: Corner/endpoints/doula_certification_expiry_is_required_for_a_doula_pass_and_forbidden_for_a_partner_pass
    """
    setup = four_visitor_passes_offered_on_one_patient
    refused = setup["lapsed"]
    validate_error(refused, ApiErrorId.ERR_DOULA_CREDENTIAL_EXPIRED.value, 422)
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_FIELD_VALUE.value


def test_an_issued_pass_carries_the_documented_defaults_and_a_computed_horizon(
    four_visitor_passes_offered_on_one_patient,
):
    """"The pass opens at `ISSUED` with `valid_until` set to the current instant plus
    24 hours, and an issued pass occupies nothing until it is checked in."

    Design: Corner/endpoints/doula_certification_expiry_is_required_for_a_doula_pass_and_forbidden_for_a_partner_pass
    """
    setup = four_visitor_passes_offered_on_one_patient
    assert setup["doula"].status_code == 201
    doula = get_success_data(setup["doula"])
    assert_support_pass(doula)
    assert doula["status"] == "ISSUED"
    assert doula["credential_type"] == "DOULA_CERTIFIED"
    assert doula["or_credentialed"] is False
    assert doula["reentry_count"] == 0
    assert_instant_is_null(doula["checked_in_at"], "checked_in_at")
    assert_instant_is_null(doula["checked_out_at"], "checked_out_at")
    assert_instant_equals(doula["valid_until"], PASS_VALID_UNTIL, "valid_until")
    assert doula["version"] == 1


def test_the_partner_pass_leaves_the_doula_field_null_and_only_two_rows_exist(
    four_visitor_passes_offered_on_one_patient,
):
    """"Passes are listed by `encounter_id`, `status` and `credential_type`, ordered
    by `created_at` ascending." The two rejected shapes and the lapsed credential
    created nothing, so exactly two rows stand behind this patient.

    Design: Corner/endpoints/doula_certification_expiry_is_required_for_a_doula_pass_and_forbidden_for_a_partner_pass
    """
    setup = four_visitor_passes_offered_on_one_patient
    assert setup["partner"].status_code == 201
    partner = get_success_data(setup["partner"])
    assert_support_pass(partner)
    assert partner["credential_type"] == "PARTNER"
    assert partner["doula_certification_expires_at"] is None
    assert_instant_equals(partner["valid_until"], PASS_VALID_UNTIL, "valid_until")
    body = api_client.list_passes(
        setup["world"].access_headers,
        params={"limit": 100, "encounter_id": setup["encounter"]["id"]},
    ).json()
    assert body["meta"]["total_count"] == 2
    assert [row["credential_type"] for row in body["data"]] == [
        "DOULA_CERTIFIED",
        "PARTNER",
    ]
