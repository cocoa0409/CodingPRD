"""Floor-plan inventory: creation, defaults, computed fields, uniqueness, listing.

Translates queue-B (Corner) instances from sections `entities` and `endpoints`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId,
    assert_site, assert_floor, assert_neighborhood, assert_seat,
    TEST_USERS, make_employee_headers,
    create_site_payload, create_floor_payload, create_neighborhood_payload,
    create_seat_payload, create_employee_payload, create_reservation_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["facility_manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_create_site_returns_201_with_system_fields(api):
    """PRD §2.4: "Every primary resource is system-stamped with an id, a
    server-minted UUID carrying no type prefix, and a created_at timestamp in
    ISO 8601 UTC with three fractional digits. Most resources additionally carry
    an updated_at timestamp (same format, refreshed on every mutation) and a
    version integer that begins at 1 and increments by one on each mutation that
    changes the resource."
    PRD §3.1: "a site begins in status ACTIVE and may later be ARCHIVED."

    Design: Corner/entities/create_site_returns_201_with_system_fields
    """
    resp = api.create_site(create_site_payload(name="HQ", timezone="America/New_York"), FM)
    data = validate_success(resp, expected_status=201)
    assert_site(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["timezone"] == "America/New_York"


def test_get_site_not_found_returns_404(api):
    """PRD §2.5: "The system resolves every path identifier left to right and
    rejects the request with ERR_NOT_FOUND (HTTP 404) at the first segment that
    does not name an existing resource".

    Design: Corner/entities/get_site_not_found_returns_404
    """
    resp = api.get_site(NON_EXISTENT_UUID, FM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_reservation_missing_required_field_returns_invalid_request(api):
    """PRD §2.6: "structural well-formedness of the body — required fields present
    and correctly typed (ERR_INVALID_REQUEST)".
    PRD §2.6: "booking_date being an ISO calendar date of the form YYYY-MM-DD ...
    failing which the request is rejected with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_reservation_missing_required_field_returns_invalid_request
    """
    env = fx.setup_floor_plan(level=1, clock_date="2026-08-01", clock_minute=500)
    emp_id = env["employee"]["id"]
    seat_v = env["seat"]["version"]
    payload = create_reservation_payload(
        employee_id=emp_id, resource_type="SEAT", seat_id=env["seat"]["id"],
        start_minute=600, end_minute=660, expected_seat_version=seat_v)
    payload.pop("booking_date")  # omit a required field
    resp = api.create_reservation(payload, make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_floor_default_workday_window_applied(api):
    """PRD §2.7: "a floor opens at workday_start_minute (default 540, i.e. 9 hours
    past midnight, or 9:00 a.m.) and closes at workday_end_minute (default 1080,
    i.e. 18 hours past midnight, or 6:00 p.m.). A floor's capacity_minutes is a
    derived field equal to workday_end_minute minus workday_start_minute".

    Design: Corner/entities/floor_default_workday_window_applied
    """
    site = fx.create_site(name="HQc2")
    # supply only `level` so the server-side workday defaults must be applied
    resp = api.create_floor(site["id"], {"level": 2}, FM)
    data = validate_success(resp, expected_status=201)
    assert data["workday_start_minute"] == 540
    assert data["workday_end_minute"] == 1080
    assert data["capacity_minutes"] == 540


def test_neighborhood_effective_cap_seats_computed_from_seat_count(api):
    """PRD §3.9: "The budget, effective_cap_seats, is the seat count of the
    neighborhood (seats whose status is not RETIRED) multiplied by the
    neighborhood's capacity_cap_pct, divided by 100, rounded up to the next whole
    seat."
    PRD §2.8: "A neighborhood exposes a derived seat_count, the number of its
    seats whose status is not RETIRED".

    Design: Corner/entities/neighborhood_effective_cap_seats_computed_from_seat_count
    """
    site = fx.create_site(name="HQc3")
    floor = fx.create_floor(site["id"], level=3)
    nb = fx.create_neighborhood(floor["id"], name="N60", capacity_cap_pct=60)
    fx.create_seat(nb["id"], label="A")
    fx.create_seat(nb["id"], label="B")
    fx.create_seat(nb["id"], label="C")
    data = get_success_data(api.get_neighborhood(nb["id"], FM))
    assert data["seat_count"] == 3
    assert data["effective_cap_seats"] == 2  # ceil(3 * 60 / 100) == 2


def test_reservation_system_fields_start_booked_none(api):
    """PRD §3.4: "A new reservation enters occupancy_status BOOKED and
    billing_status NONE."

    Design: Corner/entities/reservation_system_fields_ignored_on_input
    """
    env = fx.setup_floor_plan(level=4, clock_date="2026-08-01", clock_minute=500)
    emp_id = env["employee"]["id"]
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=env["seat"]["id"],
            booking_date="2026-08-01", start_minute=600, end_minute=660,
            expected_seat_version=env["seat"]["version"]),
        make_employee_headers(emp_id))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"
    assert data["billing_status"] == "NONE"


def test_duplicate_employee_email_returns_duplicate(api):
    """PRD §3.6: "A duplicate email is rejected with ERR_DUPLICATE (HTTP 409)."

    Design: Corner/entities/duplicate_employee_email_returns_duplicate
    """
    api.create_employee(create_employee_payload(email="dup@x.com", full_name="First", team_code="ENG"), FM)
    resp = api.create_employee(
        create_employee_payload(email="dup@x.com", full_name="Second", team_code="SALES"), FM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_checkin_record_is_append_only_no_version(api):
    """PRD §2.4: "Two record types are immutable audit rows and therefore carry
    only id and created_at — they have no updated_at and no version: the CheckIn
    record that captures a single check-in, and the NoShowEvent row that records
    one strike-ledger adjustment."
    PRD §3.7: "it creates a CheckIn child whose checked_in_at_minute is the
    clock's current minute-of-day and whose within_grace flag is true".

    Design: Corner/entities/checkin_immutable_entity_has_no_version
    """
    env, resv = fx.setup_checked_in_reservation(
        booking_date="2026-08-02", start_minute=540, end_minute=600,
        checkin_minute=545, level=5)
    emp_id = env["employee"]["id"]
    resp = api.list_reservation_check_ins(resv["id"], make_employee_headers(emp_id))
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1, f"exactly one CheckIn expected, got {len(rows)}"
    row = rows[0]
    assert row["within_grace"] is True
    assert row["checked_in_at_minute"] == 545
    assert "version" not in row, "CheckIn must not carry a version field"
    assert "updated_at" not in row, "CheckIn must not carry an updated_at field"


def test_list_seats_paginated_envelope(api):
    """PRD §2.3: "List responses carry limit, offset, total_count, and has_more
    inside the envelope's meta object, where total_count is the full count of
    matching resources before pagination and has_more indicates whether further
    items remain beyond the current page."

    Design: Corner/endpoints/list_seats_paginated_envelope
    """
    site = fx.create_site(name="HQc18")
    floor = fx.create_floor(site["id"], level=18)
    nb = fx.create_neighborhood(floor["id"], name="N1")
    fx.create_seat(nb["id"], label="S1")
    fx.create_seat(nb["id"], label="S2")
    resp = api.list_seats(nb["id"], ANALYST, params={"limit": 10, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2
