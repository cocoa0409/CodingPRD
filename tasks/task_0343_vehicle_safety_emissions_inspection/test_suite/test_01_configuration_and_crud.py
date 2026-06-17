"""Configuration CRUD, computed copies, defaults, listing, auth, and RBAC.

Covers Corner queue instances under sections: entities, errors, rbac.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID,
    create_station_payload, create_vehicle_class_profile_payload,
    assert_station, assert_inspection_record, assert_state_report_line,
    TEST_USERS,
)
from test_helpers import fixtures as F

SM = TEST_USERS["station_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
RECEP = TEST_USERS["receptionist_headers"]


# ===========================================================================
# Section: entities
# ===========================================================================
def test_create_station_returns_201_with_system_fields(api):
    """PRD §3.1: "At creation the system initializes the station's
    `next_certificate_seq` to 1; this monotonic counter supplies the next
    certificate serial and increments by one each time a serial is minted."
    PRD §2.4: "a `version`, an integer that begins at its initial value and
    increments by one on every mutation."

    Design: Corner/entities/create_station_returns_201_with_system_fields
    """
    resp = api.create_station(create_station_payload(
        name="Acme Inspections", state_code="CA", certificate_serial_prefix="CA-",
        repair_cost_limit_cents=60000, analyzer_count=2), SM)
    data = validate_success(resp, 201)
    assert_station(data)
    assert data["next_certificate_seq"] == 1, "next_certificate_seq must initialize to 1"
    assert data["version"] == 1, "version must begin at 1"
    assert data["state_code"] == "CA"


def test_get_station_not_found_returns_404(api):
    """PRD §2.6: "The first id that does not resolve to an existing entity causes
    the request to be rejected with `ERR_NOT_FOUND` before any further reference or
    business rule is evaluated."

    Design: Corner/entities/get_station_not_found_returns_404
    """
    validate_error(api.get_station(NON_EXISTENT_UUID, SM),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_station_missing_required_field_returns_422(api):
    """PRD §2.9: "Request well-formedness is fourth: a missing required field, an
    invalid enum member, a VIN that is not exactly 17 uppercase alphanumeric
    characters, a `state_code` that is not exactly two uppercase letters, or a
    negative integer where a non-negative one is required yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_station_missing_required_field_returns_422
    """
    validate_error(
        api.create_station(
            {"name": "NoLimit", "state_code": "CA", "certificate_serial_prefix": "CA-"}, SM),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_appointment_bad_vin_length_returns_422(api):
    """PRD §2.9: "a VIN that is not exactly 17 uppercase alphanumeric characters,
    a `state_code` that is not exactly two uppercase letters, or a negative
    integer where a non-negative one is required yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_appointment_bad_vin_length_returns_422
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    validate_error(
        api.create_appointment(F.create_appointment_payload(
            lane["id"], vehicle_vin="SHORTVIN"), RECEP),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_appointment_invalid_enum_kind_returns_422(api):
    """PRD §2.9: "Request well-formedness is fourth: a missing required field, an
    invalid enum member, a VIN that is not exactly 17 uppercase alphanumeric
    characters, a `state_code` that is not exactly two uppercase letters, or a
    negative integer where a non-negative one is required yields
    `ERR_INVALID_REQUEST`."
    PRD §2.10: "Other closed enumerations introduced in their respective workflows
    include appointment `kind` (`APPOINTMENT` or `WALK_IN`)"

    Design: Corner/entities/create_appointment_invalid_enum_kind_returns_422
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    validate_error(
        api.create_appointment(F.create_appointment_payload(
            lane["id"], kind="DROP_OFF"), RECEP),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_appointment_default_status_is_booked(api):
    """PRD §3.2: "A new appointment starts in `BOOKED`."

    Design: Corner/entities/appointment_default_status_is_booked
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    appt = F.book_appointment(api, lane["id"])
    assert appt["status"] == "BOOKED", f"expected BOOKED, got {appt['status']}"


def test_vehicle_class_profile_reinspection_window_default_30(api):
    """PRD §3.1: "A profile also carries `reinspection_window_days`, the number of
    days after the original inspection during which the first reinspection's
    service fee is waived; this is an integer of at least 0 and defaults to 30."

    Design: Corner/entities/vehicle_class_profile_reinspection_window_default_30
    """
    station = F.create_station(api)
    resp = api.create_vehicle_class_profile({
        "station_id": station["id"], "vehicle_class": "LIGHT_TRUCK",
        "base_fee_cents": 3000, "obd_required": True, "checklist_item_count": 3}, SM)
    data = validate_success(resp, 201)
    assert data["reinspection_window_days"] == 30, \
        f"omitted reinspection_window_days must default to 30, got {data['reinspection_window_days']}"


def test_inspection_record_copies_vin_and_class_from_appointment(api):
    """PRD §3.4: "The record copies its `station_id`, `vehicle_vin`, and
    `vehicle_class` from the consumed appointment and its lane's station."
    PRD §3.4: "Its computed `reinspection_index` is 0 for an original inspection
    and is set to the chain head's index plus one for a reinspection."

    Design: Corner/entities/inspection_record_copies_vin_and_class_from_appointment
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    appt = F.book_and_check_in(api, lane["id"], vehicle_vin="1HGCM82633A004352",
                               vehicle_class="PASSENGER")
    record = F.open_record(api, appt["id"])
    assert_inspection_record(record)
    assert record["vehicle_vin"] == "1HGCM82633A004352"
    assert record["vehicle_class"] == "PASSENGER"
    assert record["station_id"] == station["id"]
    assert record["reinspection_index"] == 0
    assert record["status"] == "IN_PROGRESS"


def test_list_vehicle_class_profiles_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping inside the
    `meta` object, namely `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_vehicle_class_profiles_pagination_envelope
    """
    station = F.create_station(api)
    F.create_profile(api, station["id"], vehicle_class="PASSENGER")
    F.create_profile(api, station["id"], vehicle_class="MOTORCYCLE",
                     base_fee_cents=1500, obd_required=False, checklist_item_count=1)
    resp = api.list_vehicle_class_profiles(SM, params={"station_id": station["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, "two of ten should not have more pages"


def test_immutable_state_report_line_has_only_id_and_created_at(api):
    """PRD §2.4: "A report line is immutable once attached: it carries only an `id`
    and a `created_at`, and has no `updated_at` and no `version`."
    PRD §3.11: "On attach, the line snapshots the record's overall outcome into
    `reported_result` (`PASS` or `FAIL`) and the record's frozen `fee_cents` into
    the line's own `fee_cents`; it carries the owning `batch_id` and the source
    `record_id`."

    Design: Corner/entities/immutable_state_report_line_has_no_version_field
    """
    station, record, batch, line = F.setup_open_batch_with_line(
        api, record_safety_pass=False)
    resp = api.list_state_report_lines(SM, params={"record_id": record["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected one line for the record, got {len(data)}"
    line_row = data[0]
    assert_state_report_line(line_row)
    assert line_row["reported_result"] == "FAIL"
    assert line_row["fee_cents"] == 3700
    assert "version" not in line_row, "StateReportLine must not carry a version field"
    assert "updated_at" not in line_row, "StateReportLine must not carry an updated_at field"


# ===========================================================================
# Section: errors (auth)
# ===========================================================================
def test_request_without_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing or malformed in either header is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    station = F.create_station(api)
    no_auth = {"Content-Type": "application/json"}
    validate_error(api.get_station(station["id"], no_auth),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Section: rbac
# ===========================================================================
def test_inspector_cannot_issue_certificate_returns_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.10: "A `StationManager` issues a `Certificate` and its physical sticker
    for a passed record."

    Design: Corner/rbac/inspector_cannot_issue_certificate_returns_forbidden
    """
    station, profile, lane, appt, passed = F.setup_passed_passenger_record(api)
    resp = api.create_certificate(
        F.create_certificate_payload(passed["id"], passed["version"]), INSP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_station_manager_cannot_decide_state_batch_returns_forbidden(api):
    """PRD §2.1: "A `StateAuditor` is the external jurisdiction reviewer who accepts
    or rejects submitted state report batches and otherwise has read-only access."
    PRD §3.11: "A `StateAuditor` then renders a `decision` of accept or reject on
    the submitted batch: acceptance advances `SUBMITTED → ACCEPTED` (terminal) and
    rejection advances `SUBMITTED → REJECTED`, each bumping the `version`."

    Design: Corner/rbac/station_manager_cannot_decide_state_batch_returns_forbidden
    """
    station, record, submitted = F.setup_submitted_batch(api)
    resp = api.decide_state_report_batch(submitted["id"], {"decision": "ACCEPT"}, SM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
