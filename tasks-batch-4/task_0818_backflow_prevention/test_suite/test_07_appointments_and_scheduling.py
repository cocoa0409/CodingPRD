"""Test-appointment scheduling: tester double-booking, premises buffer, time-range, cancel lockdown."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories, fixtures, make_tester_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _two_connections_one_tester(api):
    conn1 = fixtures.create_connection(api, ADMIN)
    conn2 = fixtures.create_connection(api, ADMIN, hazard_class="LOW_HAZARD")
    dev1 = fixtures.create_device(conn1["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                  install_date="2026-01-01T00:00:00Z")
    dev2 = fixtures.create_device(conn2["id"], api, ADMIN, device_type="DC", hazard_rating="LOW",
                                  install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    return dev1, dev2, tester


def _one_connection_two_devices_one_tester(api):
    conn = fixtures.create_connection(api, ADMIN)
    dev1 = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                  install_date="2026-01-01T00:00:00Z")
    dev2 = fixtures.create_device(conn["id"], api, ADMIN, device_type="DC", hazard_rating="LOW",
                                  install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    return dev1, dev2, tester


# --------------------------------------------------------------------------- #
# Difficulty/resource_temporal_overlap/tester_double_booked_half_open_overlap
# --------------------------------------------------------------------------- #
def test_tester_double_booked_on_overlap(api):
    """PRD §3.2: "the new appointment's half-open interval from `scheduled_start` up to
    `scheduled_end` must not overlap the interval of any other `BOOKED` appointment for the
    same `tester_id`. Because the intervals are half-open, back-to-back adjacency — where
    one appointment's start equals another's end — does not overlap and is allowed; any true
    overlap is rejected with `ERR_TESTER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/tester_double_booked_half_open_overlap
    """
    dev1, dev2, tester = _two_connections_one_tester(api)
    fixtures.book_appointment(dev1["id"], tester["id"],
                              "2026-04-10T09:00:00Z", "2026-04-10T10:00:00Z", api)
    payload = factories.appointment_payload(dev2["id"], tester["id"],
                                            scheduled_start="2026-04-10T09:30:00Z",
                                            scheduled_end="2026-04-10T10:30:00Z")
    validate_error(api.create_appointment(payload, make_tester_headers(tester["id"])),
                   ApiErrorId.ERR_TESTER_DOUBLE_BOOKED)


def test_tester_back_to_back_adjacency_allowed(api):
    """PRD §3.2: "Because the intervals are half-open, back-to-back adjacency — where one
    appointment's start equals another's end — does not overlap and is allowed".

    Design: Difficulty/resource_temporal_overlap/tester_double_booked_half_open_overlap
    """
    dev1, dev2, tester = _two_connections_one_tester(api)
    fixtures.book_appointment(dev1["id"], tester["id"],
                              "2026-04-10T09:00:00Z", "2026-04-10T10:00:00Z", api)
    payload = factories.appointment_payload(dev2["id"], tester["id"],
                                            scheduled_start="2026-04-10T10:00:00Z",
                                            scheduled_end="2026-04-10T11:00:00Z")
    data = validate_success(api.create_appointment(payload, make_tester_headers(tester["id"])),
                            expected_status=201)
    assert data["status"] == "BOOKED", f"adjacency booking should succeed, got {data['status']}"


# --------------------------------------------------------------------------- #
# Difficulty/resource_temporal_overlap/premises_buffer_conflict_within_60_min
# --------------------------------------------------------------------------- #
def test_premises_buffer_conflict_within_60_min(api):
    """PRD §3.2: "for any two `BOOKED` appointments on devices that share a service
    connection, the gap between their intervals must be at least 60 minutes. Intervals
    closer than that buffer — including exact adjacency, which the tester rule would
    otherwise permit — are rejected with `ERR_PREMISES_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/premises_buffer_conflict_within_60_min
    """
    dev1, dev2, tester = _one_connection_two_devices_one_tester(api)
    fixtures.book_appointment(dev1["id"], tester["id"],
                              "2026-04-11T09:00:00Z", "2026-04-11T10:00:00Z", api)
    payload = factories.appointment_payload(dev2["id"], tester["id"],
                                            scheduled_start="2026-04-11T10:30:00Z",
                                            scheduled_end="2026-04-11T11:00:00Z")
    validate_error(api.create_appointment(payload, make_tester_headers(tester["id"])),
                   ApiErrorId.ERR_PREMISES_BUFFER_CONFLICT)


def test_premises_buffer_exactly_60_min_allowed(api):
    """PRD §3.2: "for any two `BOOKED` appointments on devices that share a service
    connection, the gap between their intervals must be at least 60 minutes."

    Design: Difficulty/resource_temporal_overlap/premises_buffer_conflict_within_60_min
    """
    dev1, dev2, tester = _one_connection_two_devices_one_tester(api)
    fixtures.book_appointment(dev1["id"], tester["id"],
                              "2026-04-11T09:00:00Z", "2026-04-11T10:00:00Z", api)
    payload = factories.appointment_payload(dev2["id"], tester["id"],
                                            scheduled_start="2026-04-11T11:00:00Z",
                                            scheduled_end="2026-04-11T12:00:00Z")
    data = validate_success(api.create_appointment(payload, make_tester_headers(tester["id"])),
                            expected_status=201)
    assert data["status"] == "BOOKED", \
        f"a 60-minute gap satisfies the buffer, got {data['status']}"


# --------------------------------------------------------------------------- #
# Corner/validations/appointment_end_not_after_start_returns_time_range
# --------------------------------------------------------------------------- #
def test_appointment_end_not_after_start_returns_time_range(api):
    """PRD §3.2: "The window itself must be well-formed, with `scheduled_end` strictly later
    than `scheduled_start`; an ill-formed window yields `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/appointment_end_not_after_start_returns_time_range
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    payload = factories.appointment_payload(dev["id"], tester["id"],
                                            scheduled_start="2026-04-21T10:00:00Z",
                                            scheduled_end="2026-04-21T09:00:00Z")
    validate_error(api.create_appointment(payload, make_tester_headers(tester["id"])),
                   ApiErrorId.ERR_INVALID_TIME_RANGE)


# --------------------------------------------------------------------------- #
# Corner/state_machines/cancel_already_cancelled_appointment_returns_not_booked
# --------------------------------------------------------------------------- #
def test_cancel_already_cancelled_appointment_returns_not_booked(api):
    """PRD §3.2: "cancelling an appointment that is not `BOOKED` returns
    `ERR_APPOINTMENT_NOT_BOOKED`."

    Design: Corner/state_machines/cancel_already_cancelled_appointment_returns_not_booked
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    appt = fixtures.book_appointment(dev["id"], tester["id"],
                                     "2026-04-20T09:00:00Z", "2026-04-20T10:00:00Z", api)
    headers = make_tester_headers(tester["id"])
    get_success_data(api.cancel_appointment(appt["id"], headers))
    validate_error(api.cancel_appointment(appt["id"], headers), ApiErrorId.ERR_APPOINTMENT_NOT_BOOKED)
