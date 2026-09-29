"""Two constant tables, each read at the point where its entries disagree.

The frozen capacity of a roster entry is the smaller of a slot ceiling and a
certification ceiling, so two nurses activated into the same `BEDSIDE` slot
separate purely on their cert level. The induction priority ladder has one
numeric constant, and three requests differing only in indication and
gestational age pin all three of its branches at once.
"""

import pytest

from test_helpers import (
    api_client,
    assert_induction_booking,
    assert_shift_assignment,
    activate_shift,
    bootstrap_unit,
    create_shift,
    get_success_data,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
BASIC_BEDSIDE_CAPACITY = 3.0
ADVANCED_BEDSIDE_CAPACITY = 4.0
DEFAULT_LABOR_MINUTES = 720

CERT_STAFF = {
    "charge": {
        "full_name": "Brigid Nolan RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "advanced": {
        "full_name": "Corinne Adeyemi RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def two_bedside_entries_separated_only_by_certification():
    """One BASIC and one ADVANCED nurse activated into the same BEDSIDE slot."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[],
        staff_specs=CERT_STAFF,
        unit_overrides={"unit_name": "Aspenglade Perinatal LDR"},
    )
    basic_scheduled = create_shift(
        world, "charge", "BEDSIDE", SHIFT_START, SHIFT_END
    )
    advanced_scheduled = create_shift(
        world, "advanced", "BEDSIDE", SHIFT_START, SHIFT_END
    )
    basic_active = activate_shift(world, basic_scheduled)
    advanced_active = activate_shift(world, advanced_scheduled)
    return {
        "world": world,
        "basic_scheduled": basic_scheduled,
        "advanced_scheduled": advanced_scheduled,
        "basic_active": basic_active,
        "advanced_active": advanced_active,
    }


def _request(world, patient_record_code, gestational_age_weeks, indication_code, hhmm):
    """One induction request with `expected_labor_minutes` deliberately omitted."""
    return get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": patient_record_code,
                "gestational_age_weeks": gestational_age_weeks,
                "indication_code": indication_code,
                "requested_start_utc": f"2026-08-02T{hhmm}:00Z",
            },
            world.access_headers,
        )
    )


@pytest.fixture
def three_requests_across_the_priority_ladder():
    """GDM at 38 weeks, GDM at 39 weeks, and preeclampsia at 30 weeks."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=CERT_STAFF,
        unit_overrides={"unit_name": "Rosemont Induction Suite LDR"},
    )
    at_38 = _request(world, "PRC-GA38-1414", 38, "GDM_CONTROLLED", "08:00")
    at_39 = _request(world, "PRC-GA39-1515", 39, "GDM_CONTROLLED", "12:00")
    preeclamptic = _request(world, "PRC-PRE30-1616", 30, "PREECLAMPSIA", "16:00")
    return {
        "world": world,
        "at_38": at_38,
        "at_39": at_39,
        "preeclamptic": preeclamptic,
    }


def test_the_certification_ceiling_binds_below_the_bedside_base(
    two_bedside_entries_separated_only_by_certification,
):
    """"Otherwise a raw figure is taken as the smaller of two ceilings: the base
    for the slot, which is 3.0 for `CHARGE`, 4.0 for `BEDSIDE`, 4.0 for
    `ONE_TO_ONE_FLOAT`, 2.0 for `OR_STANDBY` and 6.0 for `TRIAGE`; and the ceiling
    implied by certification, which is 4.0 for `ADVANCED`, 3.0 for `BASIC` and 0.0
    for `EXPIRED`."

    Design: Corner/calculations/bedside_slot_with_basic_certification_binds_the_cert_cap_at_3_0_not_the_base_at_4_0
    """
    setup = two_bedside_entries_separated_only_by_certification
    basic = setup["basic_active"]
    assert_shift_assignment(basic)
    assert basic["role_slot"] == "BEDSIDE"
    assert basic["status"] == "ACTIVE"
    assert basic["capacity_units_effective"] == pytest.approx(
        BASIC_BEDSIDE_CAPACITY, abs=1e-9
    )
    assert basic["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_advanced_nurse_in_the_same_slot_freezes_a_whole_unit_higher(
    two_bedside_entries_separated_only_by_certification,
):
    """"A `BASIC`-certified nurse in the `BEDSIDE` slot therefore carries 3.0
    units, and the same nurse in the `CHARGE` slot carries 2.0." Neither entry is
    `CHARGE` and neither nurse holds an assignment, so nothing but the cert
    ceiling separates the two figures.

    Design: Corner/calculations/bedside_slot_with_basic_certification_binds_the_cert_cap_at_3_0_not_the_base_at_4_0
    """
    setup = two_bedside_entries_separated_only_by_certification
    advanced = setup["advanced_active"]
    assert_shift_assignment(advanced)
    assert advanced["role_slot"] == "BEDSIDE"
    assert advanced["capacity_units_effective"] == pytest.approx(
        ADVANCED_BEDSIDE_CAPACITY, abs=1e-9
    )
    assert advanced["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
    world = setup["world"]
    stored = get_success_data(
        api_client.get_shift(setup["basic_active"]["id"], world.charge_headers)
    )
    assert stored["capacity_units_effective"] == pytest.approx(
        BASIC_BEDSIDE_CAPACITY, abs=1e-9
    )
    assert stored["capacity_units_effective"] < advanced["capacity_units_effective"]


def test_capacity_is_null_until_the_entry_is_activated(
    two_bedside_entries_separated_only_by_certification,
):
    """"The entry opens in `SCHEDULED` with `assigned_acuity_load_units` at 0 and
    `capacity_units_effective` null" — so the 3.0 is produced by the activation
    and not by the rostering call.

    Design: Corner/calculations/bedside_slot_with_basic_certification_binds_the_cert_cap_at_3_0_not_the_base_at_4_0
    """
    scheduled = two_bedside_entries_separated_only_by_certification["basic_scheduled"]
    assert_shift_assignment(scheduled)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["capacity_units_effective"] is None
    assert scheduled["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_thirty_nine_week_boundary_is_inclusive(
    three_requests_across_the_priority_ladder,
):
    """"It is `ELECTIVE_39_WEEK` when `indication_code` is `GDM_CONTROLLED` or
    `ELECTIVE_NO_INDICATION` and `gestational_age_weeks` is 39 or greater. It is
    `PATIENT_REQUEST` otherwise."

    Design: Corner/calculations/elective_induction_boundary_flips_patient_request_at_38_weeks_to_elective_at_39
    """
    setup = three_requests_across_the_priority_ladder
    at_38 = setup["at_38"]
    at_39 = setup["at_39"]
    assert_induction_booking(at_38)
    assert_induction_booking(at_39)
    assert at_38["indication_code"] == at_39["indication_code"] == "GDM_CONTROLLED"
    assert at_38["gestational_age_weeks"] == 38
    assert at_38["priority_class"] == "PATIENT_REQUEST"
    assert at_39["gestational_age_weeks"] == 39
    assert at_39["priority_class"] == "ELECTIVE_39_WEEK"


def test_a_medical_indication_short_circuits_regardless_of_gestational_age(
    three_requests_across_the_priority_ladder,
):
    """"It is `MEDICALLY_INDICATED` when `indication_code` is `PREECLAMPSIA`,
    `POST_DATES_41W`, `FGR` or `PROM`." That branch is tested first, so 30 weeks
    never reaches the elective comparison.

    Design: Corner/calculations/elective_induction_boundary_flips_patient_request_at_38_weeks_to_elective_at_39
    """
    setup = three_requests_across_the_priority_ladder
    world = setup["world"]
    preeclamptic = setup["preeclamptic"]
    assert_induction_booking(preeclamptic)
    assert preeclamptic["gestational_age_weeks"] == 30
    assert preeclamptic["priority_class"] == "MEDICALLY_INDICATED"
    for booking, expected in (
        (setup["at_38"], "PATIENT_REQUEST"),
        (setup["at_39"], "ELECTIVE_39_WEEK"),
        (preeclamptic, "MEDICALLY_INDICATED"),
    ):
        stored = get_success_data(
            api_client.get_booking(booking["id"], world.access_headers)
        )
        assert stored["priority_class"] == expected
        assert stored["bump_count"] == 0


def test_the_omitted_labor_allowance_defaults_to_twelve_hours(
    three_requests_across_the_priority_ladder,
):
    """"and optionally `expected_labor_minutes` as an integer from 60 to 2160,
    defaulting to 720."

    Design: Corner/calculations/elective_induction_boundary_flips_patient_request_at_38_weeks_to_elective_at_39
    """
    setup = three_requests_across_the_priority_ladder
    assert setup["at_39"]["expected_labor_minutes"] == DEFAULT_LABOR_MINUTES
    assert setup["at_38"]["expected_labor_minutes"] == DEFAULT_LABOR_MINUTES
    assert setup["at_38"]["bump_count"] == 0
