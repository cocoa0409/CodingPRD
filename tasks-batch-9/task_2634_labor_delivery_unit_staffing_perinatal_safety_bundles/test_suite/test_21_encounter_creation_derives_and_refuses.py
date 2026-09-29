"""What creating a walk-in patient does, and what it refuses to do.

Omitted obstetric optionals take their low-risk defaults, a breech multipara is
tiered and priced from the same payload, the admission instant comes from the
logical clock, an unknown encounter id is answered by name, and two malformed
payloads are rejected before any row is written.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    BOOTSTRAP_OFFICER_HEADERS,
    TEST_USERS,
    create_bed,
    create_unit,
    get_success_data,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
CLOCK_ADMISSION = "2026-08-01T09:15:00Z"
UNKNOWN_ENCOUNTER_ID = "00000000-0000-4000-8000-000000000001"

CHARGE_HEADERS = TEST_USERS["charge_nurse_headers"]


def _unit_with_one_bed(unit_name):
    unit = create_unit(unit_name=unit_name, licensed_ldr_beds=4, licensed_or_rooms=1)
    create_bed(unit["id"], "LDR-01", "LDR")
    return unit


def test_omitted_obstetric_optionals_take_the_low_risk_defaults():
    """"optionally `prior_cesarean` defaulting to false, `fetus_count` as an
    integer no smaller than 1 defaulting to 1, and `presentation` of `VERTEX`,
    `BREECH` or `OTHER` defaulting to `VERTEX`."

    Design: Corner/entities/omitted_encounter_optionals_default_to_singleton_vertex_without_prior_cesarean
    """
    set_clock(CLOCK_START)
    unit = _unit_with_one_bed("Sagebrush Birth Center LDR")
    encounter = get_success_data(
        api_client.create_encounter(
            {
                "unit_id": unit["id"],
                "patient_record_code": "PRC-DEF-1001",
                "parity": 0,
                "gestational_age_weeks": 39,
            },
            CHARGE_HEADERS,
        )
    )
    assert_labor_encounter(encounter)
    assert encounter["fetus_count"] == 1
    assert encounter["presentation"] == "VERTEX"
    assert encounter["prior_cesarean"] is False
    assert encounter["episiotomy_performed"] is False
    assert encounter["magnesium_infusion_active"] is False
    assert encounter["review_required"] is False
    assert encounter["labor_phase"] == "ANTEPARTUM"
    assert encounter["staffing_state"] == "UNASSIGNED"
    assert encounter["bed_id"] is None
    assert encounter["source_booking_id"] is None
    assert encounter["is_ntsv"] is True
    assert encounter["acuity_tier"] == "TIER_I"
    assert encounter["required_coverage_units"] == pytest.approx(0.5, abs=1e-9)
    assert encounter["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)
    assert encounter["version"] == 1


def test_a_breech_multipara_is_tiered_and_priced_from_the_same_payload():
    """"`is_ntsv` is true when all five of the following hold: `parity` is 0,
    `prior_cesarean` is false, `gestational_age_weeks` is 37 or greater,
    `fetus_count` is exactly 1, and `presentation` is `VERTEX`. It is false when
    any one of them fails."

    Design: Corner/entities/breech_multiparous_encounter_computes_tier_ii_required_0_8_and_is_ntsv_false
    """
    set_clock(CLOCK_START)
    unit = _unit_with_one_bed("Ironwood Maternity LDR")
    encounter = get_success_data(
        api_client.create_encounter(
            {
                "unit_id": unit["id"],
                "patient_record_code": "PRC-BRE-2002",
                "parity": 2,
                "gestational_age_weeks": 39,
                "prior_cesarean": False,
                "fetus_count": 1,
                "presentation": "BREECH",
            },
            CHARGE_HEADERS,
        )
    )
    assert_labor_encounter(encounter)
    assert encounter["presentation"] == "BREECH"
    assert encounter["acuity_tier"] == "TIER_II"
    assert encounter["required_coverage_units"] == pytest.approx(0.8, abs=1e-9)
    assert encounter["one_to_one_required"] is False
    assert encounter["is_ntsv"] is False
    unit_after = get_success_data(
        api_client.get_unit(unit["id"], BOOTSTRAP_OFFICER_HEADERS)
    )
    assert unit_after["coverage_deficit_units"] == pytest.approx(0.8, abs=1e-9)


def test_the_admission_instant_comes_from_the_logical_clock():
    """"The encounter opens with `labor_phase` at `ANTEPARTUM`, `staffing_state` at
    `UNASSIGNED`, `admitted_at` at the current instant, `bed_id` null,
    `source_booking_id` null, `magnesium_infusion_active` false,
    `episiotomy_performed` false, `review_required` false, and `delivery_mode` and
    `delivery_recorded_at` null."

    Design: Corner/entities/encounter_admitted_at_is_stamped_from_the_logical_clock_at_the_moment_of_admission
    """
    set_clock(CLOCK_START)
    unit = _unit_with_one_bed("Foxglove Perinatal LDR")
    set_clock(CLOCK_ADMISSION)
    encounter = get_success_data(
        api_client.create_encounter(
            {
                "unit_id": unit["id"],
                "patient_record_code": "PRC-SYS-3003",
                "parity": 1,
                "gestational_age_weeks": 40,
            },
            CHARGE_HEADERS,
        )
    )
    assert_labor_encounter(encounter)
    assert_instant_equals(encounter["admitted_at"], CLOCK_ADMISSION, "admitted_at")
    assert_instant_is_null(
        encounter["delivery_recorded_at"], "delivery_recorded_at"
    )
    assert encounter["delivery_mode"] is None
    assert encounter["unit_id"] == unit["id"]
    assert encounter["version"] == 1


def test_an_unknown_encounter_id_is_answered_by_its_own_name():
    """The fifteen path-existence outcomes include `ERR_ENCOUNTER_NOT_FOUND`,
    "each at HTTP 404".

    Design: Corner/entities/get_labor_encounter_with_an_unknown_id_returns_encounter_not_found
    """
    set_clock(CLOCK_START)
    response = api_client.get_encounter(UNKNOWN_ENCOUNTER_ID, CHARGE_HEADERS)
    validate_error(response, ApiErrorId.ERR_ENCOUNTER_NOT_FOUND.value, 404)


def test_an_encounter_without_parity_writes_nothing_at_all():
    """A walk-in names "`parity` as an integer no smaller than 0", which is
    required, and "**Priority 5** — field types, enum membership, string lengths
    and numeric ranges, on every operation: `ERR_INVALID_FIELD_VALUE` at HTTP
    400."

    Design: Corner/entities/creating_an_encounter_without_parity_is_rejected_before_any_row_is_written
    """
    set_clock(CLOCK_START)
    unit = _unit_with_one_bed("Hawthorn Womens Hospital LDR")
    response = api_client.create_encounter(
        {
            "unit_id": unit["id"],
            "patient_record_code": "PRC-MISSING-4004",
            "gestational_age_weeks": 39,
        },
        CHARGE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400)
    rows = api_client.list_encounters(
        CHARGE_HEADERS, params={"unit_id": unit["id"], "limit": 10}
    ).json()["data"]
    assert rows == []
    unit_after = get_success_data(
        api_client.get_unit(unit["id"], BOOTSTRAP_OFFICER_HEADERS)
    )
    assert unit_after["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)


def test_a_gestational_age_of_forty_five_weeks_is_out_of_range():
    """A walk-in names "`gestational_age_weeks` as an integer from 20 to 44", so
    45 falls outside the declared range.

    Design: Corner/entities/gestational_age_weeks_of_45_is_rejected_as_out_of_the_declared_20_to_44_range
    """
    set_clock(CLOCK_START)
    unit = _unit_with_one_bed("Cottonwood Perinatal LDR")
    response = api_client.create_encounter(
        {
            "unit_id": unit["id"],
            "patient_record_code": "PRC-RANGE-5005",
            "parity": 0,
            "gestational_age_weeks": 45,
        },
        CHARGE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400)
