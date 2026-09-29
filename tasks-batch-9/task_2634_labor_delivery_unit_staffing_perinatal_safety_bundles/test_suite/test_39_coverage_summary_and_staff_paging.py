"""Two read paths that must agree with something computed elsewhere.

The per-encounter coverage read is a pure projection of three separate
derivations taken at one instant, so it has to show the re-priced figures rather
than the ones written at creation, and the visitor allowance it reports is the
posture-clamped one. The staff roster read layers a role filter over the shared
pagination envelope, where the count must follow the filter and the declared
bounds must refuse rather than clamp.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_care_assignment,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assert_staff_member,
    assign_bed,
    advance_phase,
    bootstrap_unit,
    check_in_pass,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    create_pass,
    create_staff_member,
    create_unit,
    get_success_data,
    TEST_USERS,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
UNKNOWN_UNIT_ID = "00000000-0000-4000-8000-0000000000ff"
BEDSIDE_CAPACITY = 4.0
LATENT_RATIO_DEBIT = 1.0
CHARGE_HEADERS = TEST_USERS["charge_nurse_headers"]

SUMMARY_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_latent_patient_covered_by_one_shared_nurse():
    """An encounter walked from ANTEPARTUM to LATENT under a single RATIO_SHARED row,
    then read back through the coverage decomposition."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=SUMMARY_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    shift = create_active_shift(world, "charge", "BEDSIDE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-COVSUM-001",
        parity=1,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="RATIO_SHARED"
    )
    latent = advance_phase(world, encounter, "LATENT")
    summary = api_client.get_encounter_coverage_summary(
        encounter["id"], world.charge_headers
    )
    first_visitor = create_pass(world, encounter, person_name="Marcus Boyd")
    admitted = check_in_pass(world, first_visitor)
    second_visitor = create_pass(world, encounter, person_name="Rosa Kaminski")
    turned_away = api_client.check_in_pass(second_visitor["id"], world.access_headers)
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "assignment": assignment,
        "latent": latent,
        "summary": summary,
        "admitted": admitted,
        "turned_away": turned_away,
    }


def _scalar_values(payload):
    """Every scalar anywhere in a response body, so a projection can be checked
    without assuming the names it chose for its own keys."""
    found = []
    pending = [payload]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        else:
            found.append(item)
    return found


def test_the_patient_is_re_priced_upward_by_the_move_into_latent(
    one_latent_patient_covered_by_one_shared_nurse,
):
    """"The third step produces `required_coverage_units`: 0.0 when `labor_phase` is
    `DISCHARGED` or `TRANSFERRED_OUT`; otherwise 4.0 when one-to-one coverage is
    required; otherwise the acuity weight multiplied by the phase multiplier from the
    table above."

    Design: Corner/endpoints/encounter_coverage_summary_read_agrees_with_the_stored_assignment_and_shift_ledger
    """
    latent = one_latent_patient_covered_by_one_shared_nurse["latent"]
    assert_labor_encounter(latent)
    assert latent["labor_phase"] == "LATENT"
    assert latent["staffing_state"] == "RATIO_COVERED"
    assert latent["acuity_tier"] == "TIER_I"
    assert latent["one_to_one_required"] is False
    assert latent["required_coverage_units"] == pytest.approx(
        LATENT_RATIO_DEBIT, abs=1e-9
    )
    assert latent["assigned_coverage_units"] == pytest.approx(
        LATENT_RATIO_DEBIT, abs=1e-9
    )


def test_the_row_and_the_roster_ledger_both_carry_the_new_price(
    one_latent_patient_covered_by_one_shared_nurse,
):
    """"A `RATIO_SHARED` row debits the product of two factors: the acuity weight,
    which is 1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and 4.0 for
    `TIER_IV`; and the phase multiplier, which is 0.5 for `ANTEPARTUM`, 1.0 for
    `LATENT`, 1.5 for `ACTIVE_FIRST_STAGE`, 2.0 for `SECOND_STAGE`, 1.5 for
    `THIRD_STAGE_DELIVERED`, 0.5 for `POSTPARTUM_RECOVERY`, 0.0 for `DISCHARGED` and
    0.0 for `TRANSFERRED_OUT`."

    Design: Corner/endpoints/encounter_coverage_summary_read_agrees_with_the_stored_assignment_and_shift_ledger
    """
    setup = one_latent_patient_covered_by_one_shared_nurse
    world = setup["world"]
    row = get_success_data(
        api_client.get_care_assignment(setup["assignment"]["id"], world.charge_headers)
    )
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["coverage_mode"] == "RATIO_SHARED"
    assert row["staff_id"] == world.staff_id("charge")
    assert row["acuity_units_consumed"] == pytest.approx(LATENT_RATIO_DEBIT, abs=1e-9)
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["assigned_acuity_load_units"] == pytest.approx(
        LATENT_RATIO_DEBIT, abs=1e-9
    )
    assert shift["capacity_units_effective"] == pytest.approx(BEDSIDE_CAPACITY, abs=1e-9)


def test_the_decomposition_read_reports_the_re_priced_figures(
    one_latent_patient_covered_by_one_shared_nurse,
):
    """"Whenever a tier or a phase changes, every affected row is re-priced in place,
    and the order of the two ledger movements is fixed: the old value is credited back
    first and the new value debited second, never the reverse." The read is therefore
    taken at the current instant and must not repeat the 0.5 the row was created with.

    Design: Corner/endpoints/encounter_coverage_summary_read_agrees_with_the_stored_assignment_and_shift_ledger
    """
    setup = one_latent_patient_covered_by_one_shared_nurse
    assert setup["summary"].status_code == 200
    summary = get_success_data(setup["summary"])
    reported = _scalar_values(summary)
    assert setup["encounter"]["id"] in reported
    assert "LATENT" in reported
    assert LATENT_RATIO_DEBIT in reported
    assert 0.5 not in reported


def test_the_frozen_posture_clamps_the_visitor_allowance_to_one(
    one_latent_patient_covered_by_one_shared_nurse,
):
    """"If the unit's `staffing_posture` is `INDUCTION_FROZEN` or `DIVERT`, the
    allowance is reduced to 1 whenever it was larger than 1."

    Design: Corner/endpoints/encounter_coverage_summary_read_agrees_with_the_stored_assignment_and_shift_ledger
    """
    setup = one_latent_patient_covered_by_one_shared_nurse
    unit = setup["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert setup["admitted"]["status"] == "CHECKED_IN"
    validate_error(
        setup["turned_away"], ApiErrorId.ERR_SUPPORT_OCCUPANCY_EXCEEDED.value, 409
    )


@pytest.fixture
def five_staff_of_whom_three_are_labour_nurses():
    """A roster whose three nurses are discontiguous in creation order, read six ways."""
    unit = create_unit(
        unit_name="Thistledown Perinatal Center LDR",
        licensed_ldr_beds=4,
        licensed_or_rooms=1,
    )
    roster = []
    for full_name, staff_role, cert in (
        ("Ana Reyes RN", "RN_LABOR_DELIVERY", "ADVANCED"),
        ("Ben Okafor MD", "OB_ATTENDING", "ADVANCED"),
        ("Cleo Marchetti RN", "RN_LABOR_DELIVERY", "BASIC"),
        ("Dev Patel RN", "RN_LABOR_DELIVERY", "BASIC"),
        ("Eli Sandoval ST", "SURGICAL_TECH", "BASIC"),
    ):
        roster.append(
            create_staff_member(
                unit["id"],
                full_name=full_name,
                staff_role=staff_role,
                fetal_monitoring_cert_level=cert,
                credential_expires_at=LIVE_CREDENTIAL,
            )
        )

    def _read(unit_id, params):
        return api_client.list_unit_staff_members(unit_id, CHARGE_HEADERS, params=params)

    nurses_page_one = _read(
        unit["id"], {"staff_role": "RN_LABOR_DELIVERY", "limit": 2, "offset": 0}
    )
    nurses_page_two = _read(
        unit["id"], {"staff_role": "RN_LABOR_DELIVERY", "limit": 2, "offset": 2}
    )
    everyone = _read(unit["id"], {"limit": 10, "offset": 0})
    over_the_ceiling = _read(unit["id"], {"limit": 101, "offset": 0})
    under_the_floor = _read(unit["id"], {"limit": 0, "offset": 0})
    under_a_phantom_unit = _read(UNKNOWN_UNIT_ID, {"limit": 10, "offset": 0})
    return {
        "unit": unit,
        "ana": roster[0],
        "ben": roster[1],
        "eli": roster[4],
        "nurses_page_one": nurses_page_one,
        "nurses_page_two": nurses_page_two,
        "everyone": everyone,
        "over_the_ceiling": over_the_ceiling,
        "under_the_floor": under_the_floor,
        "under_a_phantom_unit": under_a_phantom_unit,
    }


def test_the_count_follows_the_filter_rather_than_the_table(
    five_staff_of_whom_three_are_labour_nurses,
):
    """"The `meta` block of a list response reports the `limit` and `offset` actually
    applied, the `total_count` of rows matching the filter before the window was
    applied, and `has_more`, which is true when rows matching the filter remain beyond
    the returned window and false otherwise."

    Design: Corner/endpoints/staff_member_list_total_count_counts_the_filtered_set_and_an_out_of_range_limit_is_rejected
    """
    setup = five_staff_of_whom_three_are_labour_nurses
    assert setup["nurses_page_one"].status_code == 200
    body = setup["nurses_page_one"].json()
    assert body["meta"]["limit"] == 2
    assert body["meta"]["offset"] == 0
    assert body["meta"]["total_count"] == 3
    assert body["meta"]["total_count"] != 5
    assert body["meta"]["has_more"] is True
    assert [row["full_name"] for row in body["data"]] == [
        "Ana Reyes RN",
        "Cleo Marchetti RN",
    ]


def test_the_second_filtered_page_holds_the_last_nurse_alone(
    five_staff_of_whom_three_are_labour_nurses,
):
    """"Staff may be listed within a unit or across the whole system, filtered by
    `staff_role`, `employment_status`, `drill_currency_state` and
    `or_circulating_qualified`, ordered by `created_at` ascending, and a single read
    exposes `capacity_units`, `last_validated_drill_at` and `drill_currency_state`, the
    three values that gate operating-room standby coverage and unit readiness."

    Design: Corner/endpoints/staff_member_list_total_count_counts_the_filtered_set_and_an_out_of_range_limit_is_rejected
    """
    setup = five_staff_of_whom_three_are_labour_nurses
    body = setup["nurses_page_two"].json()
    assert body["meta"]["limit"] == 2
    assert body["meta"]["offset"] == 2
    assert body["meta"]["total_count"] == 3
    assert body["meta"]["has_more"] is False
    assert [row["full_name"] for row in body["data"]] == ["Dev Patel RN"]
    shown = [
        row["full_name"]
        for response in (setup["nurses_page_one"], setup["nurses_page_two"])
        for row in response.json()["data"]
    ]
    assert "Ben Okafor MD" not in shown
    assert "Eli Sandoval ST" not in shown


def test_the_unfiltered_page_shows_all_five_in_creation_order(
    five_staff_of_whom_three_are_labour_nurses,
):
    """"Three fields are not the caller's to set: `employment_status` opens at
    `ACTIVE` and may later be moved to `ON_LEAVE` or `INACTIVE`; `drill_currency_state`
    opens at `LAPSED`; and `last_validated_drill_at` opens null."

    Design: Corner/endpoints/staff_member_list_total_count_counts_the_filtered_set_and_an_out_of_range_limit_is_rejected
    """
    setup = five_staff_of_whom_three_are_labour_nurses
    body = setup["everyone"].json()
    assert body["meta"]["limit"] == 10
    assert body["meta"]["offset"] == 0
    assert body["meta"]["total_count"] == 5
    assert body["meta"]["has_more"] is False
    assert len(body["data"]) == 5
    assert body["data"][0]["full_name"] == "Ana Reyes RN"
    assert body["data"][0]["unit_id"] == setup["unit"]["id"]
    for row in body["data"]:
        assert_staff_member(row)
        assert row["employment_status"] == "ACTIVE"
        assert row["drill_currency_state"] == "LAPSED"
    assert setup["eli"]["drill_currency_state"] == "LAPSED"
    assert setup["ben"]["capacity_units"] == pytest.approx(0.0, abs=1e-9)


def test_both_out_of_range_limits_are_refused_rather_than_clamped(
    five_staff_of_whom_three_are_labour_nurses,
):
    """"A `limit` below 1 or above 100, or a negative `offset`, is a field-value
    failure and is rejected with `ERR_INVALID_FIELD_VALUE` and HTTP 400."

    Design: Corner/endpoints/staff_member_list_total_count_counts_the_filtered_set_and_an_out_of_range_limit_is_rejected
    """
    setup = five_staff_of_whom_three_are_labour_nurses
    validate_error(
        setup["over_the_ceiling"], ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400
    )
    validate_error(
        setup["under_the_floor"], ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400
    )


def test_a_nested_list_under_a_phantom_parent_is_a_404_not_an_empty_page(
    five_staff_of_whom_three_are_labour_nurses,
):
    """"**Priority 3** — existence of every identifier taken from the request path, on every
    operation that carries one, resolved strictly left to right so that a unit
    identifier is resolved before a bed or snapshot identifier in the same path and
    an activation identifier before a checklist item identifier; the fifteen
    possible outcomes are `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`,
    `ERR_CARE_ASSIGNMENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_ACTIVATION_NOT_FOUND`, `ERR_CHECKLIST_ITEM_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CESAREAN_EVENT_NOT_FOUND`,
    `ERR_DRILL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_PASS_NOT_FOUND` and
    `ERR_SNAPSHOT_NOT_FOUND`, each at HTTP 404."

    Design: Corner/endpoints/staff_member_list_total_count_counts_the_filtered_set_and_an_out_of_range_limit_is_rejected
    """
    setup = five_staff_of_whom_three_are_labour_nurses
    refused = setup["under_a_phantom_unit"]
    validate_error(refused, ApiErrorId.ERR_UNIT_NOT_FOUND.value, 404)
    assert refused.status_code != 200
