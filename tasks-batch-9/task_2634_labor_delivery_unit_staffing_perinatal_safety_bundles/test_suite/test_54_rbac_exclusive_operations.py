"""One sweep across the allow-list that shows it is a matrix and not a hierarchy.

The officer who created the unit and the bed is still refused the bed patch, and
the busiest writer in the domain is refused three of its neighbours' endpoints —
one of them on a unit whose posture would have refused the same call for a second,
later reason, so the 403 has to arrive before the 409. Two probes attack the
co-held endpoints rather than the exclusive ones, to show that sharing an endpoint
between two roles is not the same as opening it to six, and one read is refused
outright to show that reads are not automatically shared. The closing probe runs
the other way: the role with no exclusive operations at all still writes.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_induction_booking,
    assert_obstetric_unit,
    assert_shift_assignment,
    assert_support_pass,
    bootstrap_unit,
    create_encounter,
    get_success_data,
)

CLOCK_START = "2026-08-01T06:00:00Z"
STANDBY_WINDOW = ("2026-08-01T06:00:00Z", "2026-08-01T14:00:00Z")
REQUESTED_START = "2026-08-01T09:00:00Z"
EXPECTED_LABOR_MINUTES = 120
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
UNIT_NAME = "Ashgrove Commons Womens Hospital LDR"
ANNEX_NAME = "Ashgrove Annex LDR"

ASHGROVE_STAFF = {
    "charge": {
        "full_name": "Philippa Aldridge RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Corvin Halloway",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "bedside": {
        "full_name": "Rosamund Delacroix RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Tobias Wrenfield MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Seraphine Kalloway RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def eight_denials_and_three_admissions_across_the_six_role_matrix():
    """One unit, one bed, one encounter, one issued pass and one requested booking.

    The unit is left exactly as bootstrapped, so its readiness is `NOT_READY` and
    its posture `INDUCTION_FROZEN`; that is what makes the hold probe a request with
    two independent defects, and therefore diagnostic about ordering.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=ASHGROVE_STAFF,
        unit_overrides={"unit_name": UNIT_NAME},
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-ASHG-3301",
        parity=1,
        gestational_age_weeks=39,
    )
    support_pass = get_success_data(
        api_client.create_pass(
            {
                "encounter_id": encounter["id"],
                "person_name": "Delphine Marchetti",
                "credential_type": "PARTNER",
            },
            world.access_headers,
        )
    )
    booking = get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": "PRC-ASHG-3302",
                "gestational_age_weeks": 39,
                "indication_code": "PREECLAMPSIA",
                "requested_start_utc": REQUESTED_START,
                "expected_labor_minutes": EXPECTED_LABOR_MINUTES,
            },
            world.access_headers,
        )
    )
    unit_before_the_sweep = world.reload_unit()
    standby_payload = {
        "unit_id": world.unit_id,
        "staff_id": world.staff_id("anesthesia"),
        "role_slot": "OR_STANDBY",
        "shift_start_utc": STANDBY_WINDOW[0],
        "shift_end_utc": STANDBY_WINDOW[1],
    }
    charge_creates_a_unit = api_client.create_unit(
        {
            "unit_name": ANNEX_NAME,
            "licensed_ldr_beds": 2,
            "licensed_or_rooms": 1,
        },
        world.charge_headers,
    )
    officer_blocks_a_bed = api_client.patch_bed(
        world.bed_id("LDR-01"), {"status": "BLOCKED"}, world.officer_headers
    )
    charge_holds_capacity = api_client.hold_capacity(
        booking["id"],
        {
            "bed_id": world.bed_id("LDR-01"),
            "expected_unit_version": unit_before_the_sweep["version"],
        },
        world.charge_headers,
    )
    charge_checks_a_visitor_in = api_client.check_in_pass(
        support_pass["id"], world.charge_headers
    )
    charge_activates_a_bundle = api_client.create_activation(
        {
            "encounter_id": encounter["id"],
            "bundle_type": "SEVERE_HYPERTENSION",
            "activation_trigger": "CLINICIAN_JUDGMENT",
        },
        world.charge_headers,
    )
    obstetrician_rosters_a_shift = api_client.create_shift(
        standby_payload, world.ob_headers
    )
    coordinator_reads_readiness = api_client.get_readiness_report(
        world.unit_id, world.access_headers
    )
    bedside_reads_the_unit = api_client.get_unit(world.unit_id, world.bedside_headers)
    coordinator_reads_the_unit = api_client.get_unit(
        world.unit_id, world.access_headers
    )
    anesthesia_rosters_a_shift = api_client.create_shift(
        standby_payload, world.anesthesia_headers
    )
    return {
        "world": world,
        "encounter": encounter,
        "support_pass": support_pass,
        "booking": booking,
        "unit_before_the_sweep": unit_before_the_sweep,
        "charge_creates_a_unit": charge_creates_a_unit,
        "officer_blocks_a_bed": officer_blocks_a_bed,
        "charge_holds_capacity": charge_holds_capacity,
        "charge_checks_a_visitor_in": charge_checks_a_visitor_in,
        "charge_activates_a_bundle": charge_activates_a_bundle,
        "obstetrician_rosters_a_shift": obstetrician_rosters_a_shift,
        "coordinator_reads_readiness": coordinator_reads_readiness,
        "bedside_reads_the_unit": bedside_reads_the_unit,
        "coordinator_reads_the_unit": coordinator_reads_the_unit,
        "anesthesia_rosters_a_shift": anesthesia_rosters_a_shift,
        "bed_at_the_end": get_success_data(
            api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
        ),
        "booking_at_the_end": get_success_data(
            api_client.get_booking(booking["id"], world.access_headers)
        ),
        "pass_at_the_end": get_success_data(
            api_client.get_pass(support_pass["id"], world.access_headers)
        ),
        "units_at_the_end": api_client.list_units(
            world.officer_headers, params={"limit": 10, "offset": 0}
        ),
        "activations_at_the_end": api_client.list_activations(
            world.charge_headers, params={"limit": 10, "encounter_id": encounter["id"]}
        ),
    }


def test_the_charge_nurse_cannot_found_a_unit(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"This is the quality and safety authority: it stands up and reconfigures units and
    beds and performs every retrospective sign-off — closing a bundle debrief, validating
    and invalidating drills, closing an emergency cesarean case, requesting rework on and
    closing a newborn review, and creating and certifying quality measure snapshots." Also:
    "A request whose headers are well formed but whose role is not authorised for the
    requested operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` and HTTP 403."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    validate_error(
        setup["charge_creates_a_unit"],
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        403,
    )
    units = setup["units_at_the_end"].json()
    assert units["meta"]["total_count"] == 1
    assert [row["unit_name"] for row in units["data"]] == [UNIT_NAME]


def test_the_officer_who_created_the_bed_still_cannot_block_it(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"The charge nurse is the shift-by-shift owner of the unit's coverage: building,
    activating, relieving and cancelling shift assignments, attaching and blocking beds,
    creating and releasing care assignments, driving the labor phase ladder to discharge,
    admitting confirmed inductions, running readiness drills, and opening and scheduling
    newborn complication debriefs." The officer's own charter closes the other side of it:
    "It never documents primary care."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    validate_error(
        setup["officer_blocks_a_bed"],
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        403,
    )
    untouched = setup["bed_at_the_end"]
    assert_bed(untouched)
    assert untouched["status"] == "AVAILABLE"
    assert untouched["bed_label"] == "LDR-01"


def test_the_role_check_outranks_the_posture_check_on_the_same_request(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"**Priority 2** — role authorisation, on every operation without exception: a role
    not listed for the operation yields `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403." Also:
    "A hold is additionally blocked when the unit's posture is `INDUCTION_FROZEN` or
    `DIVERT`."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    unit = setup["unit_before_the_sweep"]
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    refused = setup["charge_holds_capacity"]
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_UNIT_POSTURE_BLOCKS_OPERATION.value
    )
    untouched = setup["booking_at_the_end"]
    assert_induction_booking(untouched)
    assert untouched["status"] == "REQUESTED"
    assert untouched["bed_id"] is None
    assert untouched["projected_occupancy_minutes"] is None


def test_holding_revoke_on_the_pass_does_not_confer_check_in(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"This non-clinical access and scheduling role requests induction bookings, holds and
    releases labor-delivery-recovery bed capacity, re-queues bumped bookings, cancels
    bookings, and admits and checks support persons in and out at the door."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    validate_error(
        setup["charge_checks_a_visitor_in"],
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        403,
    )
    untouched = setup["pass_at_the_end"]
    assert_support_pass(untouched)
    assert untouched["status"] == "ISSUED"
    assert untouched["checked_in_at"] is None


def test_a_co_held_write_endpoint_still_denies_the_roles_outside_its_pair(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"This role holds no operation exclusively — by design, every capability it has is
    shared with at least one other role — and works at the bedside of one encounter:
    activating hemorrhage and hypertension bundles, completing timed checklist items,
    interpreting fetal monitoring strips and opening the escalation chain."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    validate_error(
        setup["charge_activates_a_bundle"],
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        403,
    )
    activations = setup["activations_at_the_end"].json()
    assert activations["meta"]["total_count"] == 0
    assert activations["data"] == []


def test_the_obstetrician_is_outside_the_roster_pair(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"It staffs operating-room standby coverage, sharing shift creation with the charge
    nurse, schedules and documents cesarean readiness drills, and reads the readiness and
    operating-room surfaces." The physician's own charter names a different list: "The
    physician of record owns the irreversible clinical decisions: escalating a bundle's
    stage, resolving a bundle, rescinding a bundle, standing down a fetal escalation chain,
    confirming an induction, transferring a patient out, and the entire emergency cesarean
    sequence from declaration through mobilisation, incision, delivery and abort."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    validate_error(
        setup["obstetrician_rosters_a_shift"],
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        403,
    )


def test_a_read_is_not_automatically_shared_with_everyone(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"| GET | /obstetric-units/{unitId}/readiness-report | Reads the readiness
    decomposition: the current validated drill, the rolling mean over the last three
    measured events, the standby test and the branch that produced the state. | ChargeNurse,
    ObstetricianAttending, AnesthesiaLead, PerinatalSafetyOfficer |"

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    validate_error(
        setup["coordinator_reads_readiness"],
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        403,
    )


def test_the_unit_read_admits_all_six_roles(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"| GET | /obstetric-units/{unitId} | Reads one unit with its derived posture,
    coverage deficit, readiness state, both breach counters and both bed-minute maps. |
    ChargeNurse, BedsideNurse, ObstetricianAttending, AnesthesiaLead,
    PerinatalSafetyOfficer, PatientAccessCoordinator |"

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    world = setup["world"]
    for response in (
        setup["bedside_reads_the_unit"],
        setup["coordinator_reads_the_unit"],
    ):
        assert response.status_code == 200
        seen = get_success_data(response)
        assert_obstetric_unit(seen)
        assert seen["id"] == world.unit_id
        assert seen["unit_name"] == UNIT_NAME


def test_an_empty_exclusive_list_is_not_a_read_only_role(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"Like the bedside nurse this role holds nothing exclusively by design."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    created = setup["anesthesia_rosters_a_shift"]
    assert created.status_code == 201
    shift = get_success_data(created)
    assert_shift_assignment(shift)
    assert shift["status"] == "SCHEDULED"
    assert shift["role_slot"] == "OR_STANDBY"
    assert shift["staff_id"] == setup["world"].staff_id("anesthesia")


def test_the_scheduled_entry_freezes_no_capacity_until_it_is_activated(
    eight_denials_and_three_admissions_across_the_six_role_matrix,
):
    """"A single roster entry read exposes `capacity_units_effective`, the snapshot frozen
    at activation, alongside `assigned_acuity_load_units`, the conserved total that section
    3.3 defines."

    Design: Corner/rbac/every_exclusive_operation_denies_the_other_five_roles_while_the_shared_reads_admit_all_six
    """
    setup = eight_denials_and_three_admissions_across_the_six_role_matrix
    shift = get_success_data(setup["anesthesia_rosters_a_shift"])
    fresh = get_success_data(
        api_client.get_shift(shift["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(fresh)
    assert fresh["capacity_units_effective"] is None
    assert fresh["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
