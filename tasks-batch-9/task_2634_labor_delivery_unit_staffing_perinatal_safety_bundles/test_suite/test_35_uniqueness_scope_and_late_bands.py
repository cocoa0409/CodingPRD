"""Three rules whose scope is narrower than the obvious implementation of them.

A patient record code is unique per unit and only among live records, so the
same code readmits after a transfer-out and coexists in a second unit. A booking
request that is wrong in both shape and timing is answered on shape. And a
certification refused for an empty cohort must not be reported as one refused
for an unfinished reporting period.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_induction_booking,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_snapshot,
    bootstrap_unit,
    create_bed,
    create_snapshot,
    create_unit,
    get_success_data,
    reload_encounter,
    set_clock,
    TEST_USERS,
)

CLOCK_START = "2026-08-01T06:00:00Z"
ONE_SECOND_ON = "2026-08-01T06:00:01Z"
ALREADY_PAST = "2026-07-31T12:00:00Z"
PERIOD_START = "2026-09-01T00:00:00Z"
PERIOD_END = "2026-10-01T00:00:00Z"
SHARED_RECORD_CODE = "PRC-UNIQUE-1301"
DEFAULT_LABOR_MINUTES = 720
ACCESS_HEADERS = TEST_USERS["access_coordinator_headers"]

UNIQUENESS_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Teodoro Marchetti MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": True,
    },
}

MEASURE_STAFF = dict(
    UNIQUENESS_STAFF,
    officer={
        "full_name": "Perpetua Lindqvist RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": False,
    },
    certifier={
        "full_name": "Ambrose Kirkpatrick RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "or_circulating_qualified": False,
    },
)


def _admit(unit_id, patient_record_code):
    """One walk-in admission attempt, signed by the access coordinator."""
    return api_client.create_encounter(
        {
            "unit_id": unit_id,
            "patient_record_code": patient_record_code,
            "parity": 1,
            "gestational_age_weeks": 39,
        },
        ACCESS_HEADERS,
    )


@pytest.fixture
def one_record_code_offered_to_two_units_and_then_reused():
    """The same code: refused in its own unit, accepted next door, accepted again
    once the first holder has been transferred out."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=UNIQUENESS_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    annex = create_unit(
        unit_name="Rowan Perinatal Center Annex",
        licensed_ldr_beds=2,
        licensed_or_rooms=1,
    )
    create_bed(annex["id"], "LDR-01", "LDR")
    first = get_success_data(_admit(world.unit_id, SHARED_RECORD_CODE))
    collision = _admit(world.unit_id, SHARED_RECORD_CODE)
    next_door = _admit(annex["id"], SHARED_RECORD_CODE)
    transferred = get_success_data(
        api_client.transfer_out_encounter(first["id"], {}, world.ob_headers)
    )
    readmission = _admit(world.unit_id, SHARED_RECORD_CODE)
    return {
        "world": world,
        "annex": annex,
        "first": first,
        "collision": collision,
        "next_door": next_door,
        "transferred": transferred,
        "readmission": readmission,
    }


def test_the_code_collides_while_its_holder_is_still_live(
    one_record_code_offered_to_two_units_and_then_reused,
):
    """"A walk-in admission is created by a `ChargeNurse` or a `PatientAccessCoordinator`
    naming `unit_id`, `patient_record_code` — a string of 1 to 60 characters that
    must be unique within the unit among encounters in non-terminal phases, refused
    otherwise with `ERR_DUPLICATE_PATIENT_RECORD_CODE` — `parity` as an integer no
    smaller than 0, `gestational_age_weeks` as an integer from 20 to 44, and
    optionally `prior_cesarean` defaulting to false, `fetus_count` as an integer no
    smaller than 1 defaulting to 1, and `presentation` of `VERTEX`, `BREECH` or
    `OTHER` defaulting to `VERTEX`."

    Design: Corner/validations/duplicate_patient_record_code_collides_only_while_the_first_encounter_is_non_terminal
    """
    setup = one_record_code_offered_to_two_units_and_then_reused
    validate_error(
        setup["collision"], ApiErrorId.ERR_DUPLICATE_PATIENT_RECORD_CODE.value, 409
    )
    assert setup["first"]["patient_record_code"] == SHARED_RECORD_CODE
    assert setup["first"]["labor_phase"] == "ANTEPARTUM"


def test_the_scope_stops_at_the_units_edge(
    one_record_code_offered_to_two_units_and_then_reused,
):
    """"**Priority 13** covers structural uniqueness and interval collision in three
    sub-bands, all at HTTP 409: **13.1** uniqueness, yielding
    `ERR_DUPLICATE_PATIENT_RECORD_CODE`, `ERR_DUPLICATE_BED_LABEL` or
    `ERR_DUPLICATE_UNIT_NAME`, on unit creation, bed creation, walk-in encounter
    creation and induction admission; **13.2** staff shift interval collision and
    maximum span, yielding `ERR_SHIFT_WINDOW_OVERLAP` or
    `ERR_SHIFT_WINDOW_TOO_LONG`, on shift-assignment creation; **13.3** bed interval
    collision and bed eligibility, yielding `ERR_BED_TURNOVER_CONFLICT`,
    `ERR_BED_TYPE_NOT_ELIGIBLE` or `ERR_ENCOUNTER_BED_NOT_ASSIGNED`, on induction
    capacity holding, encounter bed attachment, phase advance and cesarean team
    mobilisation." The scope is the
    unit, so the neighbouring unit takes the same code at the same instant.

    Design: Corner/validations/duplicate_patient_record_code_collides_only_while_the_first_encounter_is_non_terminal
    """
    setup = one_record_code_offered_to_two_units_and_then_reused
    next_door = get_success_data(setup["next_door"])
    assert_labor_encounter(next_door)
    assert next_door["unit_id"] == setup["annex"]["id"]
    assert next_door["patient_record_code"] == SHARED_RECORD_CODE
    assert next_door["id"] != setup["first"]["id"]


def test_a_transferred_out_holder_releases_the_code(
    one_record_code_offered_to_two_units_and_then_reused,
):
    """"Transfer-out is an `ObstetricianAttending` act from `ANTEPARTUM`, `LATENT`
    or `ACTIVE_FIRST_STAGE` to `TRANSFERRED_OUT`, and it is a compensating exit
    rather than a completion." The exit is terminal, so it leaves the uniqueness
    scope and the same code readmits.

    Design: Corner/validations/duplicate_patient_record_code_collides_only_while_the_first_encounter_is_non_terminal
    """
    setup = one_record_code_offered_to_two_units_and_then_reused
    gone = reload_encounter(setup["world"], setup["first"]["id"])
    assert_labor_encounter(gone)
    assert gone["labor_phase"] == "TRANSFERRED_OUT"
    assert gone["required_coverage_units"] == pytest.approx(0.0, abs=1e-9)
    readmission = get_success_data(setup["readmission"])
    assert_labor_encounter(readmission)
    assert readmission["labor_phase"] == "ANTEPARTUM"
    assert readmission["patient_record_code"] == SHARED_RECORD_CODE
    assert readmission["id"] != setup["first"]["id"]
    assert_instant_equals(readmission["admitted_at"], CLOCK_START, "admitted_at")


@pytest.fixture
def three_induction_requests_probing_shape_then_timing():
    """One request wrong in both range and timing, one exactly at the current
    instant, and one a single second later."""
    set_clock(CLOCK_START)
    unit = create_unit(
        unit_name="Rowan Perinatal Center LDR",
        licensed_ldr_beds=4,
        licensed_or_rooms=1,
    )

    def _book(gestational_age_weeks, requested_start_utc):
        return api_client.create_booking(
            {
                "unit_id": unit["id"],
                "patient_record_code": "PRC-BOOK-1420",
                "gestational_age_weeks": gestational_age_weeks,
                "indication_code": "ELECTIVE_NO_INDICATION",
                "requested_start_utc": requested_start_utc,
            },
            ACCESS_HEADERS,
        )

    out_of_range_and_in_the_past = _book(19, ALREADY_PAST)
    exactly_now = _book(39, CLOCK_START)
    one_second_on = _book(39, ONE_SECOND_ON)
    return {
        "unit": unit,
        "out_of_range_and_in_the_past": out_of_range_and_in_the_past,
        "exactly_now": exactly_now,
        "one_second_on": one_second_on,
    }


def test_field_shape_is_answered_before_the_temporal_window(
    three_induction_requests_probing_shape_then_timing,
):
    """"**Priority 5** — field types, enum membership, string lengths and numeric
    ranges, on every operation: `ERR_INVALID_FIELD_VALUE` at HTTP 400."

    Design: Corner/validations/invalid_gestational_age_at_priority_5_outranks_the_past_booking_start_at_priority_14_2
    """
    setup = three_induction_requests_probing_shape_then_timing
    refused = setup["out_of_range_and_in_the_past"]
    validate_error(refused, ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_BOOKING_START_IN_PAST.value
    )


def test_the_current_instant_itself_counts_as_the_past(
    three_induction_requests_probing_shape_then_timing,
):
    """"An induction request is created by a `PatientAccessCoordinator` or an
    `ObstetricianAttending`, naming `unit_id`, `patient_record_code` as a string of
    1 to 60 characters, `gestational_age_weeks` as an integer from 20 to 44, an
    `indication_code` of `PREECLAMPSIA`, `POST_DATES_41W`, `FGR`, `PROM`,
    `GDM_CONTROLLED` or `ELECTIVE_NO_INDICATION`, a `requested_start_utc` strictly
    after the current instant — refused otherwise with `ERR_BOOKING_START_IN_PAST` —
    and optionally `expected_labor_minutes` as an integer from 60 to 2160,
    defaulting to 720."

    Design: Corner/validations/invalid_gestational_age_at_priority_5_outranks_the_past_booking_start_at_priority_14_2
    """
    setup = three_induction_requests_probing_shape_then_timing
    validate_error(
        setup["exactly_now"], ApiErrorId.ERR_BOOKING_START_IN_PAST.value, 422
    )


def test_one_second_later_is_accepted_and_opens_on_its_defaults(
    three_induction_requests_probing_shape_then_timing,
):
    """"The booking opens in `REQUESTED` with `bump_count` at 0, `bed_id`,
    `encounter_id`, `hold_expires_at` and `projected_occupancy_minutes` all null,
    and consumes no budget at all."

    Design: Corner/validations/invalid_gestational_age_at_priority_5_outranks_the_past_booking_start_at_priority_14_2
    """
    booking = get_success_data(
        three_induction_requests_probing_shape_then_timing["one_second_on"]
    )
    assert_induction_booking(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["priority_class"] == "ELECTIVE_39_WEEK"
    assert booking["expected_labor_minutes"] == DEFAULT_LABOR_MINUTES
    assert booking["projected_occupancy_minutes"] is None
    assert booking["bed_id"] is None
    assert booking["encounter_id"] is None
    assert_instant_is_null(booking["hold_expires_at"], "hold_expires_at")
    assert booking["bump_count"] == 0
    assert booking["version"] == 1


@pytest.fixture
def a_draft_snapshot_over_an_empty_future_window():
    """A snapshot whose cohort is empty and whose period is still open, offered
    for certification by an officer who did not create it."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[],
        staff_specs=MEASURE_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    snapshot = create_snapshot(world, PERIOD_START, PERIOD_END, acting_key="officer")
    refused = api_client.certify_snapshot(
        snapshot["id"], world.officer_headers_for("certifier")
    )
    reread = api_client.get_snapshot(snapshot["id"], world.officer_headers_for("certifier"))
    return {
        "world": world,
        "snapshot": snapshot,
        "refused": refused,
        "reread": reread,
    }


def test_the_empty_cohort_is_reported_before_the_open_period(
    a_draft_snapshot_over_an_empty_future_window,
):
    """"Both denominators must be 1 or more, since an empty cohort is readable as
    a draft but never certifiable, refused otherwise with
    `ERR_EMPTY_MEASURE_DENOMINATOR`."

    Design: Corner/validations/empty_measure_denominator_at_priority_16_outranks_the_still_open_reporting_period
    """
    refused = a_draft_snapshot_over_an_empty_future_window["refused"]
    validate_error(refused, ApiErrorId.ERR_EMPTY_MEASURE_DENOMINATOR.value, 409)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_MEASURE_PERIOD_NOT_CLOSED.value
    assert reported != ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value


def test_the_uncertifiable_draft_is_still_readable(
    a_draft_snapshot_over_an_empty_future_window,
):
    """"The authoritative figures use `delivery_recorded_at` as the attribution
    instant; `attribution_basis` is always `DELIVERY_COHORT`, and these are the
    figures certification freezes and any external submission reports."

    Design: Corner/validations/empty_measure_denominator_at_priority_16_outranks_the_still_open_reporting_period
    """
    setup = a_draft_snapshot_over_an_empty_future_window
    snapshot = get_success_data(setup["reread"])
    assert_snapshot(snapshot)
    assert snapshot["status"] == "DRAFT"
    assert snapshot["attribution_basis"] == "DELIVERY_COHORT"
    assert snapshot["ntsv_cesarean_numerator"] == 0
    assert snapshot["ntsv_cesarean_denominator"] == 0
    assert snapshot["episiotomy_numerator"] == 0
    assert snapshot["episiotomy_denominator"] == 0
    assert_instant_is_null(snapshot["certified_at"], "certified_at")
    assert snapshot["certified_by_user_id"] is None


def test_every_rate_over_an_empty_denominator_stays_null(
    a_draft_snapshot_over_an_empty_future_window,
):
    """"Each rate — `ntsv_cesarean_rate_pct` and `episiotomy_rate_pct` — is null
    when its own denominator is 0 — never 0.0 — and otherwise is 100.0 multiplied
    by that numerator and divided by that denominator, rounded to 4 decimal places
    half-up."

    Design: Corner/validations/empty_measure_denominator_at_priority_16_outranks_the_still_open_reporting_period
    """
    snapshot = get_success_data(
        a_draft_snapshot_over_an_empty_future_window["reread"]
    )
    assert snapshot["ntsv_cesarean_rate_pct"] is None
    assert snapshot["episiotomy_rate_pct"] is None
    assert snapshot["shadow_ntsv_rate_pct"] is None
    assert snapshot["composite_quality_index"] is None
