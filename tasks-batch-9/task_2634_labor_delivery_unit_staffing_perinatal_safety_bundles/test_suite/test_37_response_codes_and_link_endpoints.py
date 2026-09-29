"""Three surface contracts a framework's defaults get wrong.

Whether a call answers 201 or 200 is decided by whether it mints a row, not by
its verb, and a retirement returns the closed row rather than an empty body. The
induction queue is the one list ordered by a derived rank instead of a
timestamp. And the shift link must both resolve its staff reference and confine
it to the named unit.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_induction_booking,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    BOOTSTRAP_OFFICER_HEADERS,
    create_staff_member,
    create_unit,
    get_success_data,
    set_clock,
    TEST_USERS,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
UNKNOWN_STAFF_ID = "00000000-0000-4000-8000-000000000040"
BEDSIDE_CAPACITY = 4.0
ACCESS_HEADERS = TEST_USERS["access_coordinator_headers"]
CHARGE_HEADERS = TEST_USERS["charge_nurse_headers"]


@pytest.fixture
def one_of_every_shape_of_write():
    """A creation, a nested creation, an action POST, a PATCH and a retirement."""
    set_clock(CLOCK_START)
    created_unit = api_client.create_unit(
        {
            "unit_name": "Rowan Perinatal Center LDR",
            "licensed_ldr_beds": 4,
            "licensed_or_rooms": 1,
        },
        BOOTSTRAP_OFFICER_HEADERS,
    )
    unit = get_success_data(created_unit)
    created_first_bed = api_client.create_bed(
        unit["id"], {"bed_label": "LDR-01", "bed_type": "LDR"}, BOOTSTRAP_OFFICER_HEADERS
    )
    created_second_bed = api_client.create_bed(
        unit["id"], {"bed_label": "LDR-02", "bed_type": "LDR"}, BOOTSTRAP_OFFICER_HEADERS
    )
    first_bed = get_success_data(created_first_bed)
    second_bed = get_success_data(created_second_bed)
    created_encounter = api_client.create_encounter(
        {
            "unit_id": unit["id"],
            "patient_record_code": "PRC-STATUS-2010",
            "parity": 1,
            "gestational_age_weeks": 39,
        },
        ACCESS_HEADERS,
    )
    encounter = get_success_data(created_encounter)
    attached = api_client.assign_bed(
        encounter["id"], {"bed_id": first_bed["id"]}, CHARGE_HEADERS
    )
    patched = api_client.patch_unit(
        unit["id"], {"max_daily_induction_bed_minutes": 1440}, BOOTSTRAP_OFFICER_HEADERS
    )
    retired = api_client.delete_bed(second_bed["id"], BOOTSTRAP_OFFICER_HEADERS)
    return {
        "unit": unit,
        "first_bed": first_bed,
        "second_bed": second_bed,
        "encounter": encounter,
        "created_unit": created_unit,
        "created_first_bed": created_first_bed,
        "created_second_bed": created_second_bed,
        "created_encounter": created_encounter,
        "attached": attached,
        "patched": patched,
        "retired": retired,
    }


def test_creations_answer_201_and_every_other_write_answers_200(
    one_of_every_shape_of_write,
):
    """"An endpoint that creates a new resource responds with 201 Created; an
    endpoint that modifies an existing resource, advances a state machine or reads
    data responds with 200 OK."

    Design: Corner/endpoints/create_endpoints_answer_201_while_action_patch_and_delete_endpoints_answer_200
    """
    setup = one_of_every_shape_of_write
    assert setup["created_unit"].status_code == 201
    assert setup["created_first_bed"].status_code == 201
    assert setup["created_second_bed"].status_code == 201
    assert setup["created_encounter"].status_code == 201
    assert setup["attached"].status_code == 200
    assert setup["patched"].status_code == 200


def test_a_retirement_answers_200_and_hands_back_the_closed_row(
    one_of_every_shape_of_write,
):
    """"Retirement of a bed responds with 200 OK and returns the updated resource,
    since the row is closed rather than erased."

    Design: Corner/endpoints/create_endpoints_answer_201_while_action_patch_and_delete_endpoints_answer_200
    """
    setup = one_of_every_shape_of_write
    assert setup["retired"].status_code == 200
    retired = get_success_data(setup["retired"])
    assert_bed(retired)
    assert retired["id"] == setup["second_bed"]["id"]
    assert retired["bed_label"] == "LDR-02"
    assert retired["status"] == "CLOSED"


def test_each_of_those_writes_actually_landed(one_of_every_shape_of_write):
    """"Attaching a bed is a separate `ChargeNurse` act naming `bed_id`; the bed
    must be of type `LDR` and `AVAILABLE`, it moves to `OCCUPIED` with
    `current_encounter_id` pointing at the encounter, and an encounter that already
    occupies a bed is refused with `ERR_ENCOUNTER_ALREADY_IN_BED`."

    Design: Corner/endpoints/create_endpoints_answer_201_while_action_patch_and_delete_endpoints_answer_200
    """
    setup = one_of_every_shape_of_write
    attached = get_success_data(setup["attached"])
    assert_labor_encounter(attached)
    assert attached["bed_id"] == setup["first_bed"]["id"]
    bed = get_success_data(
        api_client.get_bed(setup["first_bed"]["id"], BOOTSTRAP_OFFICER_HEADERS)
    )
    assert_bed(bed)
    assert bed["status"] == "OCCUPIED"
    assert bed["current_encounter_id"] == setup["encounter"]["id"]
    patched = get_success_data(setup["patched"])
    assert_obstetric_unit(patched)
    assert patched["max_daily_induction_bed_minutes"] == 1440
    assert patched["unit_name"] == "Rowan Perinatal Center LDR"


@pytest.fixture
def three_requests_queued_in_reverse_promotion_order():
    """One request per priority class, created worst-first and with start instants
    that disagree with the ladder."""
    set_clock(CLOCK_START)
    unit = create_unit(
        unit_name="Rowan Perinatal Center LDR",
        licensed_ldr_beds=4,
        licensed_or_rooms=1,
    )
    def _book(patient_record_code, gestational_age_weeks, indication_code, hhmm):
        return get_success_data(
            api_client.create_booking(
                {
                    "unit_id": unit["id"],
                    "patient_record_code": patient_record_code,
                    "gestational_age_weeks": gestational_age_weeks,
                    "indication_code": indication_code,
                    "requested_start_utc": f"2026-08-02T{hhmm}:00Z",
                },
                ACCESS_HEADERS,
            )
        )

    patient_request = _book("PRC-ORDER-A", 37, "ELECTIVE_NO_INDICATION", "07:00")
    elective = _book("PRC-ORDER-B", 39, "ELECTIVE_NO_INDICATION", "09:00")
    indicated = _book("PRC-ORDER-C", 41, "PREECLAMPSIA", "11:00")
    unfiltered = api_client.list_bookings(ACCESS_HEADERS, params={"limit": 100})
    filtered = api_client.list_bookings(
        ACCESS_HEADERS, params={"limit": 100, "priority_class": "ELECTIVE_39_WEEK"}
    )
    return {
        "unit": unit,
        "patient_request": patient_request,
        "elective": elective,
        "indicated": indicated,
        "unfiltered": unfiltered,
        "filtered": filtered,
    }


def test_the_queue_reads_back_in_promotion_order(
    three_requests_queued_in_reverse_promotion_order,
):
    """"Bookings may also be listed filtered by `unit_id`, `bed_id`,
    `encounter_id`, `status`, `priority_class` and `requested_day`, returned in the
    sweep's own promotion order so that a caller can read the queue before running
    it."

    Design: Corner/endpoints/induction_booking_list_orders_by_promotion_rank_not_by_creation_order
    """
    setup = three_requests_queued_in_reverse_promotion_order
    body = setup["unfiltered"].json()
    assert [row["patient_record_code"] for row in body["data"]] == [
        "PRC-ORDER-C",
        "PRC-ORDER-B",
        "PRC-ORDER-A",
    ]
    assert body["meta"]["total_count"] == 3
    assert body["meta"]["has_more"] is False


def test_that_order_is_the_rank_ladder_and_not_the_start_instants(
    three_requests_queued_in_reverse_promotion_order,
):
    """"Promotion inside the sweep runs the other way: candidates are ordered by
    priority rank ascending, then `requested_start_utc` ascending, then `created_at`
    ascending, and the record's `id` is never consulted."

    Design: Corner/endpoints/induction_booking_list_orders_by_promotion_rank_not_by_creation_order
    """
    setup = three_requests_queued_in_reverse_promotion_order
    assert setup["indicated"]["priority_class"] == "MEDICALLY_INDICATED"
    assert setup["elective"]["priority_class"] == "ELECTIVE_39_WEEK"
    assert setup["patient_request"]["priority_class"] == "PATIENT_REQUEST"
    rows = setup["unfiltered"].json()["data"]
    assert [row["requested_start_utc"][11:16] for row in rows] == [
        "11:00",
        "09:00",
        "07:00",
    ]
    for row in rows:
        assert_induction_booking(row)
        assert row["status"] == "REQUESTED"


def test_the_priority_class_filter_narrows_to_the_middle_rung(
    three_requests_queued_in_reverse_promotion_order,
):
    """"It is `ELECTIVE_39_WEEK` when `indication_code` is `GDM_CONTROLLED` or
    `ELECTIVE_NO_INDICATION` and `gestational_age_weeks` is 39 or greater."

    Design: Corner/endpoints/induction_booking_list_orders_by_promotion_rank_not_by_creation_order
    """
    setup = three_requests_queued_in_reverse_promotion_order
    body = setup["filtered"].json()
    assert [row["patient_record_code"] for row in body["data"]] == ["PRC-ORDER-B"]
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["id"] == setup["elective"]["id"]


@pytest.fixture
def a_roster_entry_offered_to_the_wrong_unit():
    """Two units, one nurse hired into the second, and three rostering attempts."""
    set_clock(CLOCK_START)
    first = create_unit(
        unit_name="Rowan Perinatal Center LDR",
        licensed_ldr_beds=4,
        licensed_or_rooms=1,
    )
    second = create_unit(
        unit_name="Thistledown Perinatal Center LDR",
        licensed_ldr_beds=2,
        licensed_or_rooms=1,
    )
    nurse = create_staff_member(
        second["id"],
        full_name="Dana Alvarez RN",
        staff_role="RN_LABOR_DELIVERY",
        fetal_monitoring_cert_level="ADVANCED",
        credential_expires_at="2027-06-30T00:00:00Z",
    )

    def _roster(unit_id, staff_id):
        return api_client.create_shift(
            {
                "unit_id": unit_id,
                "staff_id": staff_id,
                "role_slot": "BEDSIDE",
                "shift_start_utc": SHIFT_START,
                "shift_end_utc": SHIFT_END,
            },
            CHARGE_HEADERS,
        )

    on_a_phantom_nurse = _roster(first["id"], UNKNOWN_STAFF_ID)
    on_the_neighbours_nurse = _roster(first["id"], nurse["id"])
    accepted = _roster(second["id"], nurse["id"])
    scheduled = get_success_data(accepted)
    activated = api_client.activate_shift(scheduled["id"], CHARGE_HEADERS)
    first_unit_roster = api_client.list_shifts(
        CHARGE_HEADERS, params={"limit": 100, "unit_id": first["id"]}
    )
    return {
        "first": first,
        "second": second,
        "nurse": nurse,
        "on_a_phantom_nurse": on_a_phantom_nurse,
        "on_the_neighbours_nurse": on_the_neighbours_nurse,
        "accepted": accepted,
        "scheduled": scheduled,
        "activated": activated,
        "first_unit_roster": first_unit_roster,
    }


def test_an_unknown_staff_reference_is_a_body_lookup_failure(
    a_roster_entry_offered_to_the_wrong_unit,
):
    """"**Priority 4** — existence of every identifier taken from the request body,
    resolved in the order the fields are declared for that operation, yielding
    `ERR_ENCOUNTER_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
    `ERR_BED_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ACTIVATION_NOT_FOUND` or
    `ERR_UNIT_NOT_FOUND` at HTTP 404."

    Design: Corner/endpoints/shift_assignment_link_requires_the_staff_member_to_belong_to_the_named_unit
    """
    setup = a_roster_entry_offered_to_the_wrong_unit
    validate_error(
        setup["on_a_phantom_nurse"], ApiErrorId.ERR_STAFF_NOT_FOUND.value, 404
    )


def test_a_nurse_who_exists_next_door_is_a_scoping_failure(
    a_roster_entry_offered_to_the_wrong_unit,
):
    """"**Priority 7** — cross-aggregate scoping, meaning that every referenced
    record must belong to the same `ObstetricUnit` as the operation's subject:
    `ERR_CROSS_UNIT_REFERENCE` at HTTP 422, on care-assignment creation,
    shift-assignment creation, encounter bed attachment, cesarean team mobilisation,
    fetal escalation, drill scheduling and checklist item completion."

    Design: Corner/endpoints/shift_assignment_link_requires_the_staff_member_to_belong_to_the_named_unit
    """
    setup = a_roster_entry_offered_to_the_wrong_unit
    refused = setup["on_the_neighbours_nurse"]
    validate_error(refused, ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value, 422)
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_STAFF_NOT_FOUND.value
    assert setup["nurse"]["unit_id"] == setup["second"]["id"]


def test_the_entry_opens_scheduled_with_no_frozen_capacity(
    a_roster_entry_offered_to_the_wrong_unit,
):
    """"The entry opens in `SCHEDULED` with `assigned_acuity_load_units` at 0 and
    `capacity_units_effective` null, and it may be listed filtered by `unit_id`,
    `staff_id`, `role_slot`, `status` and `relieved_by_shift_id`, ordered by
    `shift_start_utc` ascending with `created_at` ascending as the tie-break."

    Design: Corner/endpoints/shift_assignment_link_requires_the_staff_member_to_belong_to_the_named_unit
    """
    setup = a_roster_entry_offered_to_the_wrong_unit
    assert setup["accepted"].status_code == 201
    scheduled = setup["scheduled"]
    assert_shift_assignment(scheduled)
    assert scheduled["unit_id"] == setup["second"]["id"]
    assert scheduled["staff_id"] == setup["nurse"]["id"]
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["capacity_units_effective"] is None
    assert scheduled["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
    empty = setup["first_unit_roster"].json()
    assert empty["data"] == []
    assert empty["meta"]["total_count"] == 0


def test_activation_freezes_the_bedside_ceiling(
    a_roster_entry_offered_to_the_wrong_unit,
):
    """"Otherwise a raw figure is taken as the smaller of two ceilings: the base for
    the slot, which is 3.0 for `CHARGE`, 4.0 for `BEDSIDE`, 4.0 for
    `ONE_TO_ONE_FLOAT`, 2.0 for `OR_STANDBY` and 6.0 for `TRIAGE`; and the ceiling
    implied by certification, which is 4.0 for `ADVANCED`, 3.0 for `BASIC` and 0.0
    for `EXPIRED`."

    Design: Corner/endpoints/shift_assignment_link_requires_the_staff_member_to_belong_to_the_named_unit
    """
    setup = a_roster_entry_offered_to_the_wrong_unit
    assert setup["activated"].status_code == 200
    activated = get_success_data(setup["activated"])
    assert_shift_assignment(activated)
    assert activated["status"] == "ACTIVE"
    assert activated["role_slot"] == "BEDSIDE"
    assert activated["capacity_units_effective"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )
    assert activated["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
