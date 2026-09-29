"""The first rungs of the refusal ladder, each probed against the rung below it.

An unparseable role must not be reported as an unauthorised one; an
unauthorised caller must not be told whether the record it named exists; a
missing path identifier must be reported before a missing body identifier; and a
stale revision must be reported before the referential mistake the same request
also made. Each pair is followed by a control that proves the suppressed
outcome was genuinely reachable.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_labor_encounter,
    assign_bed,
    bootstrap_unit,
    BOOTSTRAP_OFFICER_HEADERS,
    create_encounter,
    create_staff_member,
    create_unit,
    get_success_data,
    headers_for_role,
    reload_encounter,
    set_clock,
    TEST_USERS,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
UNKNOWN_BED_ID = "00000000-0000-4000-8000-000000000030"
UNKNOWN_ENCOUNTER_ID = "00000000-0000-4000-8000-000000000031"
UNRECOGNISED_ROLE = "UnitDirector"
CHARGE_HEADERS = TEST_USERS["charge_nurse_headers"]

LADDER_STAFF = {
    "charge": {
        "full_name": "Marguerite Deveraux RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_unit_creation_signed_with_a_role_that_does_not_exist():
    """A well-formed unit creation carrying a seventh, undefined role."""
    set_clock(CLOCK_START)
    response = api_client.create_unit(
        {
            "unit_name": "Rowan Perinatal Center LDR",
            "licensed_ldr_beds": 4,
            "licensed_or_rooms": 1,
        },
        headers_for_role(UNRECOGNISED_ROLE, "unit-director-01"),
    )
    return {"response": response}


@pytest.fixture
def a_bed_retirement_aimed_at_an_id_that_was_never_minted():
    """The officer-exclusive retirement path, tried first by a charge nurse."""
    set_clock(CLOCK_START)
    refused = api_client.delete_bed(UNKNOWN_BED_ID, CHARGE_HEADERS)
    permitted = api_client.delete_bed(UNKNOWN_BED_ID, BOOTSTRAP_OFFICER_HEADERS)
    return {"refused": refused, "permitted": permitted}


@pytest.fixture
def an_attachment_naming_two_records_that_do_not_exist():
    """assign-bed with a bogus path encounter and a bogus body bed, then a control."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=LADDER_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-LADDER-3004",
        parity=1,
        gestational_age_weeks=39,
    )
    both_bogus = api_client.assign_bed(
        UNKNOWN_ENCOUNTER_ID, {"bed_id": UNKNOWN_BED_ID}, world.charge_headers
    )
    body_bogus = api_client.assign_bed(
        encounter["id"], {"bed_id": UNKNOWN_BED_ID}, world.charge_headers
    )
    return {
        "world": world,
        "encounter": encounter,
        "both_bogus": both_bogus,
        "body_bogus": body_bogus,
    }


@pytest.fixture
def a_stale_read_used_to_build_a_cross_unit_request():
    """A care assignment naming another unit's entry, sent with a stale version."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=LADDER_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    annex = create_unit(
        unit_name="Rowan Perinatal Center Annex",
        licensed_ldr_beds=2,
        licensed_or_rooms=1,
    )
    annex_staff = create_staff_member(
        annex["id"],
        full_name="Dana Alvarez RN",
        staff_role="RN_LABOR_DELIVERY",
        fetal_monitoring_cert_level="ADVANCED",
        credential_expires_at="2027-01-01T00:00:00Z",
    )
    annex_shift = get_success_data(
        api_client.create_shift(
            {
                "unit_id": annex["id"],
                "staff_id": annex_staff["id"],
                "role_slot": "CHARGE",
                "shift_start_utc": SHIFT_START,
                "shift_end_utc": SHIFT_END,
            },
            CHARGE_HEADERS,
        )
    )
    get_success_data(api_client.activate_shift(annex_shift["id"], CHARGE_HEADERS))
    encounter = create_encounter(
        world,
        patient_record_code="PRC-LADDER-6007",
        parity=1,
        gestational_age_weeks=39,
    )
    stale_version = encounter["version"]
    assign_bed(world, encounter, "LDR-01")
    payload = {
        "encounter_id": encounter["id"],
        "shift_assignment_id": annex_shift["id"],
        "coverage_mode": "RATIO_SHARED",
        "expected_encounter_version": stale_version,
    }
    on_a_stale_read = api_client.create_care_assignment(payload, world.charge_headers)
    fresh_version = reload_encounter(world, encounter["id"])["version"]
    on_a_fresh_read = api_client.create_care_assignment(
        dict(payload, expected_encounter_version=fresh_version), world.charge_headers
    )
    return {
        "world": world,
        "encounter": encounter,
        "stale_version": stale_version,
        "fresh_version": fresh_version,
        "on_a_stale_read": on_a_stale_read,
        "on_a_fresh_read": on_a_fresh_read,
    }


def test_an_undefined_role_is_a_header_fault_not_a_permission_fault(
    a_unit_creation_signed_with_a_role_that_does_not_exist,
):
    """"A request missing either header, or carrying a role string that is not one
    of the six defined below, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP 400."

    Design: Corner/validations/unknown_x_user_role_is_rejected_at_priority_1_before_the_permission_check_at_priority_2
    """
    response = a_unit_creation_signed_with_a_role_that_does_not_exist["response"]
    validate_error(
        response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400
    )
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value
    )


def test_the_rejected_creation_wrote_no_unit(
    a_unit_creation_signed_with_a_role_that_does_not_exist,
):
    """"**Priority 1** — authentication context, on every operation without
    exception: a missing or unrecognised `X-User-ID` or `X-User-Role` yields
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` at HTTP 400." Refusing before the
    write means the collection is still empty afterwards.

    Design: Corner/validations/unknown_x_user_role_is_rejected_at_priority_1_before_the_permission_check_at_priority_2
    """
    # A refused Response is falsy, so the refusal has to be read off its status:
    # the header fault is "rejected with ... HTTP 400".
    assert (
        a_unit_creation_signed_with_a_role_that_does_not_exist["response"].status_code
        == 400
    )
    body = api_client.list_units(
        BOOTSTRAP_OFFICER_HEADERS, params={"limit": 10, "offset": 0}
    ).json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0


def test_the_allow_list_is_consulted_before_the_record_is_looked_up(
    a_bed_retirement_aimed_at_an_id_that_was_never_minted,
):
    """"**Priority 2** — role authorisation, on every operation without exception:
    a role not listed for the operation yields `ERR_INSUFFICIENT_PERMISSIONS` at
    HTTP 403."

    Design: Corner/validations/insufficient_permissions_at_priority_2_outranks_a_nonexistent_bed_id_at_priority_3
    """
    setup = a_bed_retirement_aimed_at_an_id_that_was_never_minted
    validate_error(setup["refused"], ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    assert (
        setup["refused"].json()["data"]["error_id"]
        != ApiErrorId.ERR_BED_NOT_FOUND.value
    )


def test_the_same_id_really_is_unknown_to_a_permitted_caller(
    a_bed_retirement_aimed_at_an_id_that_was_never_minted,
):
    """"**Priority 3** — existence of every identifier taken from the request path,
    on every operation that carries one, resolved strictly left to right so that a
    unit identifier is resolved before a bed or snapshot identifier in the same path
    and an activation identifier before a checklist item identifier; the fifteen
    possible outcomes are `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`,
    `ERR_CARE_ASSIGNMENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_ACTIVATION_NOT_FOUND`, `ERR_CHECKLIST_ITEM_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CESAREAN_EVENT_NOT_FOUND`,
    `ERR_DRILL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_PASS_NOT_FOUND` and
    `ERR_SNAPSHOT_NOT_FOUND`, each at HTTP 404."

    Design: Corner/validations/insufficient_permissions_at_priority_2_outranks_a_nonexistent_bed_id_at_priority_3
    """
    setup = a_bed_retirement_aimed_at_an_id_that_was_never_minted
    validate_error(setup["permitted"], ApiErrorId.ERR_BED_NOT_FOUND.value, 404)


def test_the_path_identifier_is_resolved_before_the_body_identifier(
    an_attachment_naming_two_records_that_do_not_exist,
):
    """"**Priority 4** — existence of every identifier taken from the request body,
    resolved in the order the fields are declared for that operation, yielding
    `ERR_ENCOUNTER_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
    `ERR_BED_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ACTIVATION_NOT_FOUND` or
    `ERR_UNIT_NOT_FOUND` at HTTP 404."

    Design: Corner/validations/nonexistent_path_encounter_at_priority_3_outranks_the_nonexistent_body_bed_id_at_priority_4
    """
    setup = an_attachment_naming_two_records_that_do_not_exist
    validate_error(setup["both_bogus"], ApiErrorId.ERR_ENCOUNTER_NOT_FOUND.value, 404)
    assert (
        setup["both_bogus"].json()["data"]["error_id"]
        != ApiErrorId.ERR_BED_NOT_FOUND.value
    )
    validate_error(setup["body_bogus"], ApiErrorId.ERR_BED_NOT_FOUND.value, 404)


def test_neither_refusal_moved_the_real_bed_or_the_real_encounter(
    an_attachment_naming_two_records_that_do_not_exist,
):
    """"Attaching a bed is a separate `ChargeNurse` act naming `bed_id`; the bed
    must be of type `LDR` and `AVAILABLE`, it moves to `OCCUPIED` with
    `current_encounter_id` pointing at the encounter, and an encounter that already
    occupies a bed is refused with `ERR_ENCOUNTER_ALREADY_IN_BED`."

    Design: Corner/validations/nonexistent_path_encounter_at_priority_3_outranks_the_nonexistent_body_bed_id_at_priority_4
    """
    setup = an_attachment_naming_two_records_that_do_not_exist
    world = setup["world"]
    bed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert_bed(bed)
    assert bed["status"] == "AVAILABLE"
    assert bed["current_encounter_id"] is None
    encounter = reload_encounter(world, setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["bed_id"] is None


def test_the_revision_guard_is_checked_before_any_business_rule(
    a_stale_read_used_to_build_a_cross_unit_request,
):
    """"**Priority 6** — the revision guard described in section 2.4, on
    care-assignment creation, induction capacity holding, snapshot creation and
    bundle rescission, yielding `ERR_STALE_ENCOUNTER_VERSION`,
    `ERR_STALE_UNIT_VERSION` or `ERR_STALE_ACTIVATION_VERSION` at HTTP 412; it is
    checked before any state-machine or business rule for those four operations."

    Design: Corner/validations/stale_encounter_version_at_priority_6_outranks_the_cross_unit_shift_reference_at_priority_7
    """
    setup = a_stale_read_used_to_build_a_cross_unit_request
    assert setup["stale_version"] == 1
    assert setup["fresh_version"] == 2
    validate_error(
        setup["on_a_stale_read"], ApiErrorId.ERR_STALE_ENCOUNTER_VERSION.value, 412
    )
    assert (
        setup["on_a_stale_read"].json()["data"]["error_id"]
        != ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value
    )


def test_the_scoping_refusal_is_reachable_once_the_read_is_fresh(
    a_stale_read_used_to_build_a_cross_unit_request,
):
    """"**Priority 7** — cross-aggregate scoping, meaning that every referenced
    record must belong to the same `ObstetricUnit` as the operation's subject:
    `ERR_CROSS_UNIT_REFERENCE` at HTTP 422, on care-assignment creation,
    shift-assignment creation, encounter bed attachment, cesarean team mobilisation,
    fetal escalation, drill scheduling and checklist item completion."

    Design: Corner/validations/stale_encounter_version_at_priority_6_outranks_the_cross_unit_shift_reference_at_priority_7
    """
    setup = a_stale_read_used_to_build_a_cross_unit_request
    validate_error(
        setup["on_a_fresh_read"], ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value, 422
    )
    encounter = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["staffing_state"] == "UNASSIGNED"
    assert encounter["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)
    assert encounter["version"] == 2
