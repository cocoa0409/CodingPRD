"""Six staffing refusals off one over-committed bedside shift.

Three of the six sit at different priorities — the shift-state guard, the
competency band and the capacity band — so the fixture makes each probe violate
exactly one rule. A single one-to-one row eats the whole four-unit ceiling
inclusively, which is what makes the very next shared request a capacity
refusal and the very next one-to-one request an exclusivity refusal: two
different ids from the same loaded shift, told apart only by coverage mode.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_care_assignment,
    assert_labor_encounter,
    assert_shift_assignment,
    bootstrap_unit,
    create_encounter,
    create_shift,
    get_success_data,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
DAY_SHIFT = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
EVENING_SHIFT = ("2026-08-01T15:00:00Z", "2026-08-01T20:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
BEDSIDE_CAPACITY = 4.0

THORNFIELD_STAFF = {
    "charge": {
        "full_name": "Marisol Quintero RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "expired_cert": {
        "full_name": "Odalys Ferreira RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "EXPIRED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "unqualified": {
        "full_name": "Teodoro Vance RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_loaded_bedside_shift_and_two_unusable_ones():
    """Seven probes: a scheduled entry used for coverage, an ineligible relief, a
    one-to-one that fits exactly, then capacity, exclusivity, standby and cert."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=THORNFIELD_STAFF,
        unit_overrides={"unit_name": "Thornfield Womens Pavilion LDR"},
    )
    active = create_shift(world, "charge", "BEDSIDE", *DAY_SHIFT)
    activated = get_success_data(
        api_client.activate_shift(active["id"], world.charge_headers)
    )
    scheduled = create_shift(world, "expired_cert", "BEDSIDE", *EVENING_SHIFT)
    or_standby = create_shift(world, "unqualified", "OR_STANDBY", *DAY_SHIFT)
    first = create_encounter(
        world,
        patient_record_code="PRC-THORN-2101",
        parity=1,
        gestational_age_weeks=39,
    )
    second = create_encounter(
        world,
        patient_record_code="PRC-THORN-2102",
        parity=2,
        gestational_age_weeks=39,
    )

    def _cover(encounter, shift, coverage_mode):
        return api_client.create_care_assignment(
            {
                "encounter_id": encounter["id"],
                "shift_assignment_id": shift["id"],
                "coverage_mode": coverage_mode,
                "expected_encounter_version": encounter["version"],
            },
            world.charge_headers,
        )

    on_a_scheduled_entry = _cover(first, scheduled, "RATIO_SHARED")
    ineligible_relief = api_client.relieve_shift(
        active["id"], {"relieved_by_shift_id": scheduled["id"]}, world.charge_headers
    )
    exclusive_row = _cover(first, active, "ONE_TO_ONE")
    over_capacity = _cover(second, active, "RATIO_SHARED")
    already_committed = _cover(second, active, "ONE_TO_ONE")
    unqualified_standby = api_client.activate_shift(
        or_standby["id"], world.charge_headers
    )
    uncertified_reading = api_client.create_assessment(
        {
            "encounter_id": first["id"],
            "interpreted_by_staff_id": world.staff_id("expired_cert"),
            "category": "CATEGORY_I",
            "baseline_rate_bpm": 140,
            "variability": "MODERATE",
        },
        world.charge_headers,
    )
    return {
        "world": world,
        "active": active,
        "activated": activated,
        "scheduled": scheduled,
        "or_standby": or_standby,
        "first": first,
        "second": second,
        "on_a_scheduled_entry": on_a_scheduled_entry,
        "ineligible_relief": ineligible_relief,
        "exclusive_row": exclusive_row,
        "over_capacity": over_capacity,
        "already_committed": already_committed,
        "unqualified_standby": unqualified_standby,
        "uncertified_reading": uncertified_reading,
    }


def test_a_scheduled_entry_cannot_carry_coverage(
    one_loaded_bedside_shift_and_two_unusable_ones,
):
    """"The named roster entry must be `ACTIVE` and its window must contain the current
    instant, failing which the request is refused with `ERR_SHIFT_NOT_ACTIVE`."

    Design: Corner/errors/six_staffing_error_ids_fire_on_six_different_edges_of_one_activated_bedside_shift
    """
    setup = one_loaded_bedside_shift_and_two_unusable_ones
    validate_error(
        setup["on_a_scheduled_entry"], ApiErrorId.ERR_SHIFT_NOT_ACTIVE.value, 409
    )
    assert setup["scheduled"]["status"] == "SCHEDULED"


def test_a_relief_needs_an_active_partner_on_the_same_slot(
    one_loaded_bedside_shift_and_two_unusable_ones,
):
    """"The relieving entry must itself be `ACTIVE`, must belong to the same `unit_id`,
    must occupy the same `role_slot`, and must belong to a different `staff_id`; any of
    those failing is refused with `ERR_RELIEVING_SHIFT_INELIGIBLE`."

    Design: Corner/errors/six_staffing_error_ids_fire_on_six_different_edges_of_one_activated_bedside_shift
    """
    setup = one_loaded_bedside_shift_and_two_unusable_ones
    validate_error(
        setup["ineligible_relief"], ApiErrorId.ERR_RELIEVING_SHIFT_INELIGIBLE.value, 409
    )
    still_active = get_success_data(
        api_client.get_shift(setup["active"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(still_active)
    assert still_active["status"] == "ACTIVE"
    assert still_active["relieved_by_shift_id"] is None


def test_one_exclusive_row_consumes_the_whole_ceiling(
    one_loaded_bedside_shift_and_two_unusable_ones,
):
    """"A `ONE_TO_ONE` row debits the covering entry's entire `capacity_units_effective`,
    whatever that value is."

    Design: Corner/errors/six_staffing_error_ids_fire_on_six_different_edges_of_one_activated_bedside_shift
    """
    setup = one_loaded_bedside_shift_and_two_unusable_ones
    assert setup["activated"]["capacity_units_effective"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )
    assert setup["exclusive_row"].status_code == 201
    row = get_success_data(setup["exclusive_row"])
    assert_care_assignment(row)
    assert row["coverage_mode"] == "ONE_TO_ONE"
    assert row["status"] == "ACTIVE"
    assert row["acuity_units_consumed"] == pytest.approx(BEDSIDE_CAPACITY, abs=1e-9)
    covered = reload_encounter(setup["world"], setup["first"]["id"])
    assert_labor_encounter(covered)
    assert covered["staffing_state"] == "ONE_TO_ONE_COVERED"


def test_the_inclusive_ceiling_is_full_so_the_next_shared_row_is_refused(
    one_loaded_bedside_shift_and_two_unusable_ones,
):
    """"Capacity is the last thing checked when a row is created or a shift relieved:
    the covering entry's `assigned_acuity_load_units` plus the new debit must be no
    greater than its `capacity_units_effective`, with the boundary allowed, and an
    excess is refused with `ERR_STAFF_ACUITY_CAPACITY_EXCEEDED`."

    Design: Corner/errors/six_staffing_error_ids_fire_on_six_different_edges_of_one_activated_bedside_shift
    """
    setup = one_loaded_bedside_shift_and_two_unusable_ones
    validate_error(
        setup["over_capacity"], ApiErrorId.ERR_STAFF_ACUITY_CAPACITY_EXCEEDED.value, 409
    )
    loaded = get_success_data(
        api_client.get_shift(setup["active"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(loaded)
    assert loaded["assigned_acuity_load_units"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )


def test_the_same_shift_refuses_a_second_exclusive_patient_for_a_different_reason(
    one_loaded_bedside_shift_and_two_unusable_ones,
):
    """"It reaches `ONE_TO_ONE_COVERED` from `UNASSIGNED`, `RATIO_COVERED` or
    `COVERAGE_BREACH` when a `ONE_TO_ONE` row is created, and that creation carries
    three extra gates: the covering entry's `role_slot` must be `BEDSIDE` or
    `ONE_TO_ONE_FLOAT`, refused otherwise with `ERR_ROLE_SLOT_NOT_ELIGIBLE`; the staff
    member must hold no other `ACTIVE` care assignment on a different encounter, refused
    otherwise with `ERR_STAFF_NOT_EXCLUSIVELY_AVAILABLE`; and the member's
    `fetal_monitoring_cert_level` must be `BASIC` or `ADVANCED`, and must be `ADVANCED`
    when the encounter's tier is `TIER_IV`, refused otherwise with
    `ERR_MONITORING_CERT_INSUFFICIENT`."

    Design: Corner/errors/six_staffing_error_ids_fire_on_six_different_edges_of_one_activated_bedside_shift
    """
    setup = one_loaded_bedside_shift_and_two_unusable_ones
    refused = setup["already_committed"]
    validate_error(refused, ApiErrorId.ERR_STAFF_NOT_EXCLUSIVELY_AVAILABLE.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_STAFF_ACUITY_CAPACITY_EXCEEDED.value
    )
    uncovered = reload_encounter(setup["world"], setup["second"]["id"])
    assert_labor_encounter(uncovered)
    assert uncovered["staffing_state"] == "UNASSIGNED"
    assert uncovered["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)


def test_an_unqualified_member_cannot_open_operating_room_standby(
    one_loaded_bedside_shift_and_two_unusable_ones,
):
    """"A slot of `OR_STANDBY` additionally demands that the member's
    `or_circulating_qualified` be true and `drill_currency_state` be `CURRENT`, failing
    which the attempt is refused with `ERR_OR_STANDBY_NOT_QUALIFIED`; satisfying it is
    the lever that lifts a unit's `cesarean_readiness_state` out of `DEGRADED`."

    Design: Corner/errors/six_staffing_error_ids_fire_on_six_different_edges_of_one_activated_bedside_shift
    """
    setup = one_loaded_bedside_shift_and_two_unusable_ones
    validate_error(
        setup["unqualified_standby"], ApiErrorId.ERR_OR_STANDBY_NOT_QUALIFIED.value, 422
    )
    unchanged = get_success_data(
        api_client.get_shift(setup["or_standby"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(unchanged)
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["role_slot"] == "OR_STANDBY"
    assert unchanged["capacity_units_effective"] is None


def test_an_expired_monitoring_certificate_cannot_interpret_a_tracing(
    one_loaded_bedside_shift_and_two_unusable_ones,
):
    """"The interpreter's `fetal_monitoring_cert_level` must be `BASIC` or `ADVANCED`,
    refused otherwise with `ERR_MONITORING_CERT_INSUFFICIENT`, and the interpreter must
    be on the case in the sense described for checklist performers, refused otherwise
    with `ERR_PERFORMER_NOT_ON_CASE`."

    Design: Corner/errors/six_staffing_error_ids_fire_on_six_different_edges_of_one_activated_bedside_shift
    """
    setup = one_loaded_bedside_shift_and_two_unusable_ones
    refused = setup["uncertified_reading"]
    validate_error(refused, ApiErrorId.ERR_MONITORING_CERT_INSUFFICIENT.value, 422)
    assert (
        refused.json()["data"]["error_id"] != ApiErrorId.ERR_PERFORMER_NOT_ON_CASE.value
    )
    rows = api_client.list_assessments(
        setup["world"].charge_headers,
        params={"limit": 10, "encounter_id": setup["first"]["id"]},
    ).json()
    assert rows["meta"]["total_count"] == 0
