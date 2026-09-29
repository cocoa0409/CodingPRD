"""Nine lookups that must each name their own resource, and the envelope itself.

Fifteen 404 identifiers collapse into one priority rule, so the only way to get
them wrong is to answer with somebody else's identifier; nine of them are
reachable only through a single-resource read, and they are fired here against a
database that holds nothing at all. The second half pins the error envelope: it
is not the success envelope with an extra key, and a refused write leaves its
collection exactly as empty as it found it.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_obstetric_unit,
    BOOTSTRAP_OFFICER_HEADERS,
    get_success_data,
    set_clock,
    TEST_USERS,
)

CLOCK_START = "2026-08-01T06:00:00Z"
REPORTING_CLOCK = "2026-09-01T06:00:00Z"
CHARGE_HEADERS = TEST_USERS["charge_nurse_headers"]
UNIT_NAME = "Larkspur Perinatal Center LDR"
ZERO_WIDTH_INSTANT = "2026-08-31T00:00:00Z"
NEVER_ISSUED = {
    "shift": "00000000-0000-4000-8000-000000000101",
    "care_assignment": "00000000-0000-4000-8000-000000000102",
    "booking": "00000000-0000-4000-8000-000000000103",
    "assessment": "00000000-0000-4000-8000-000000000104",
    "cesarean": "00000000-0000-4000-8000-000000000105",
    "drill": "00000000-0000-4000-8000-000000000106",
    "review": "00000000-0000-4000-8000-000000000107",
    "pass": "00000000-0000-4000-8000-000000000108",
    "snapshot": "00000000-0000-4000-8000-000000000109",
}


@pytest.fixture
def nine_reads_of_records_that_were_never_created():
    """One single-resource read per catalogue entry that has no other way in."""
    set_clock(CLOCK_START)
    return {
        "shift": api_client.get_shift(NEVER_ISSUED["shift"], CHARGE_HEADERS),
        "care_assignment": api_client.get_care_assignment(
            NEVER_ISSUED["care_assignment"], CHARGE_HEADERS
        ),
        "booking": api_client.get_booking(NEVER_ISSUED["booking"], CHARGE_HEADERS),
        "assessment": api_client.get_assessment(
            NEVER_ISSUED["assessment"], CHARGE_HEADERS
        ),
        "cesarean": api_client.get_cesarean(NEVER_ISSUED["cesarean"], CHARGE_HEADERS),
        "drill": api_client.get_drill(NEVER_ISSUED["drill"], CHARGE_HEADERS),
        "review": api_client.get_review(NEVER_ISSUED["review"], CHARGE_HEADERS),
        "pass": api_client.get_pass(NEVER_ISSUED["pass"], CHARGE_HEADERS),
        "snapshot": api_client.get_snapshot(
            NEVER_ISSUED["snapshot"], BOOTSTRAP_OFFICER_HEADERS
        ),
    }


def test_the_staffing_reads_name_the_staffing_records(
    nine_reads_of_records_that_were_never_created,
):
    """"**Priority 3** — existence of every identifier taken from the request path, on
    every operation that carries one, resolved strictly left to right so that a unit
    identifier is resolved before a bed or snapshot identifier in the same path and an
    activation identifier before a checklist item identifier; the fifteen possible
    outcomes are `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`, `ERR_CARE_ASSIGNMENT_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_ACTIVATION_NOT_FOUND`,
    `ERR_CHECKLIST_ITEM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
    `ERR_CESAREAN_EVENT_NOT_FOUND`, `ERR_DRILL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_PASS_NOT_FOUND` and `ERR_SNAPSHOT_NOT_FOUND`, each at HTTP 404."

    Design: Corner/errors/the_nine_remaining_not_found_ids_each_answer_404_with_their_own_id_in_the_envelope
    """
    setup = nine_reads_of_records_that_were_never_created
    validate_error(setup["shift"], ApiErrorId.ERR_SHIFT_NOT_FOUND.value, 404)
    validate_error(
        setup["care_assignment"], ApiErrorId.ERR_CARE_ASSIGNMENT_NOT_FOUND.value, 404
    )
    validate_error(setup["booking"], ApiErrorId.ERR_BOOKING_NOT_FOUND.value, 404)


def test_the_clinical_reads_name_the_clinical_records(
    nine_reads_of_records_that_were_never_created,
):
    """"When a request would fail more than one rule, the outcome is fully determined:
    rules are evaluated strictly in ascending priority order, and the first rule that
    fails produces the response." A read whose headers and role are both in order has
    only priority 3 left to fail on.

    Design: Corner/errors/the_nine_remaining_not_found_ids_each_answer_404_with_their_own_id_in_the_envelope
    """
    setup = nine_reads_of_records_that_were_never_created
    validate_error(setup["assessment"], ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value, 404)
    validate_error(
        setup["cesarean"], ApiErrorId.ERR_CESAREAN_EVENT_NOT_FOUND.value, 404
    )
    validate_error(setup["drill"], ApiErrorId.ERR_DRILL_NOT_FOUND.value, 404)


def test_the_review_pass_and_snapshot_reads_name_their_own_records(
    nine_reads_of_records_that_were_never_created,
):
    """"The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/the_nine_remaining_not_found_ids_each_answer_404_with_their_own_id_in_the_envelope
    """
    setup = nine_reads_of_records_that_were_never_created
    validate_error(setup["review"], ApiErrorId.ERR_REVIEW_NOT_FOUND.value, 404)
    validate_error(setup["pass"], ApiErrorId.ERR_PASS_NOT_FOUND.value, 404)
    validate_error(setup["snapshot"], ApiErrorId.ERR_SNAPSHOT_NOT_FOUND.value, 404)
    reported = [response.json()["data"]["error_id"] for response in setup.values()]
    assert len(set(reported)) == 9
    assert all(response.status_code == 404 for response in setup.values())


@pytest.fixture
def two_rejections_from_opposite_ends_of_the_ladder():
    """A repeated unit name at priority 13.1 and a zero-width reporting window at
    priority 14.2, each followed by a read of the collection it did not join."""
    set_clock(REPORTING_CLOCK)
    unit = get_success_data(
        api_client.create_unit(
            {
                "unit_name": UNIT_NAME,
                "licensed_ldr_beds": 3,
                "licensed_or_rooms": 1,
            },
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )
    get_success_data(
        api_client.create_bed(
            unit["id"], {"bed_label": "LDR-01", "bed_type": "LDR"},
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )
    live_version = get_success_data(
        api_client.get_unit(unit["id"], BOOTSTRAP_OFFICER_HEADERS)
    )["version"]
    repeated_name = api_client.create_unit(
        {
            "unit_name": UNIT_NAME,
            "licensed_ldr_beds": 8,
            "licensed_or_rooms": 2,
        },
        BOOTSTRAP_OFFICER_HEADERS,
    )
    zero_width_window = api_client.create_snapshot(
        unit["id"],
        {
            "period_start_utc": ZERO_WIDTH_INSTANT,
            "period_end_utc": ZERO_WIDTH_INSTANT,
            "expected_unit_version": live_version,
        },
        BOOTSTRAP_OFFICER_HEADERS,
    )
    units = api_client.list_units(
        BOOTSTRAP_OFFICER_HEADERS, params={"limit": 10, "offset": 0}
    )
    snapshots = api_client.list_unit_snapshots(
        unit["id"], BOOTSTRAP_OFFICER_HEADERS, params={"limit": 10, "offset": 0}
    )
    return {
        "unit": unit,
        "live_version": live_version,
        "repeated_name": repeated_name,
        "zero_width_window": zero_width_window,
        "units": units,
        "snapshots": snapshots,
    }


def test_a_repeated_unit_name_answers_in_the_error_envelope(
    two_rejections_from_opposite_ends_of_the_ladder,
):
    """"`unit_name` is a string of 1 to 120 characters and must be unique across all
    units; a repeat name is refused with `ERR_DUPLICATE_UNIT_NAME`."

    Design: Corner/errors/the_error_envelope_replaces_data_entirely_and_no_row_survives_a_rejected_write
    """
    setup = two_rejections_from_opposite_ends_of_the_ladder
    validate_error(
        setup["repeated_name"], ApiErrorId.ERR_DUPLICATE_UNIT_NAME.value, 409
    )
    body = setup["repeated_name"].json()
    assert body["response_type"] == "error"
    assert sorted(body["data"]) == ["error_id", "message"]
    assert body["data"]["message"].strip() != ""


def test_the_error_meta_carries_only_the_request_identity(
    two_rejections_from_opposite_ends_of_the_ladder,
):
    """"The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/the_error_envelope_replaces_data_entirely_and_no_row_survives_a_rejected_write
    """
    setup = two_rejections_from_opposite_ends_of_the_ladder
    meta = setup["repeated_name"].json()["meta"]
    assert sorted(meta) == ["api_request_id", "api_request_timestamp"]
    assert meta["api_request_id"].startswith("req_")
    assert meta["api_request_timestamp"].strip() != ""


def test_a_zero_width_reporting_window_is_refused_the_same_way(
    two_rejections_from_opposite_ends_of_the_ladder,
):
    """"A `PerinatalSafetyOfficer` computes a quality measure snapshot on a unit over
    the half-open window from `period_start_utc`, which is inclusive, to
    `period_end_utc`, which is exclusive and must be strictly greater than the start,
    refused otherwise with `ERR_MEASURE_PERIOD_INVALID`."

    Design: Corner/errors/the_error_envelope_replaces_data_entirely_and_no_row_survives_a_rejected_write
    """
    setup = two_rejections_from_opposite_ends_of_the_ladder
    refused = setup["zero_width_window"]
    validate_error(refused, ApiErrorId.ERR_MEASURE_PERIOD_INVALID.value, 422)
    body = refused.json()
    assert body["response_type"] == "error"
    assert "id" not in body["data"]


def test_neither_rejection_left_a_row_or_a_revision_behind(
    two_rejections_from_opposite_ends_of_the_ladder,
):
    """"The `response_type` is either "object" for a single resource or "array" for a
    list of resources." A refused write joins no collection, so both list reads answer
    in the success envelope with the counts they had before the two attempts.

    Design: Corner/errors/the_error_envelope_replaces_data_entirely_and_no_row_survives_a_rejected_write
    """
    setup = two_rejections_from_opposite_ends_of_the_ladder
    units = setup["units"].json()
    assert units["meta"]["total_count"] == 1
    assert units["response_type"] == "array"
    assert [row["unit_name"] for row in units["data"]] == [UNIT_NAME]
    snapshots = setup["snapshots"].json()
    assert snapshots["meta"]["total_count"] == 0
    assert snapshots["data"] == []
    unit = get_success_data(
        api_client.get_unit(setup["unit"]["id"], BOOTSTRAP_OFFICER_HEADERS)
    )
    assert_obstetric_unit(unit)
    assert unit["licensed_ldr_beds"] == 3
    assert unit["version"] == setup["live_version"]
