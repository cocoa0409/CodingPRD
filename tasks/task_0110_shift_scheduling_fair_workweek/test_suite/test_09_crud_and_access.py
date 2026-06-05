"""CRUD defaults/validation, system fields, listing, template generation,
FK reverse-reachability, and role-based access control.

Covers Corner: entities (defaults, required fields, not-found, system fields,
invalid time window, listing), endpoints (template generate, FK reverse list),
rbac (manager-exclusive op, ownership, missing auth headers).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_manager_headers, make_worker_headers, build_user_headers,
    NON_EXISTENT_UUID, set_clock, setup_location, setup_worker, setup_pay_period,
    create_posted_shift, assign_worker, setup_shift_template,
)


M = make_manager_headers()


def test_create_location_applies_defaults(api):
    """PRD §3.1: "The advance_notice_days value defines the fair-workweek notice
    window in days and defaults to fourteen."
    PRD §3.1: "The overtime band is set by overtime_weekly_threshold_hours, defaulting
    to forty hours per pay-week, and overtime_multiplier, defaulting to
    one-and-a-half."
    PRD §3.1: "On creation a location's status is initialized to ACTIVE."

    Omitting the optional dials applies advance_notice_days=14,
    overtime_weekly_threshold_hours=40, overtime_multiplier=1.5, status ACTIVE.

    Design: Corner/entities/create_location_returns_201_with_defaults_applied
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.create_location(
        {"name": "L", "time_zone": "UTC", "overtime_cost_guardrail_cents": 100000}, M)
    data = validate_success(resp, 201)
    assert data["advance_notice_days"] == 14
    assert data["overtime_multiplier"] == 1.5
    assert data["overtime_weekly_threshold_hours"] == 40
    assert data["status"] == "ACTIVE"


def test_create_worker_missing_required_field_rejected(api):
    """PRD §2.7: "then well-formedness of the request body — required fields present,
    enums valid, durations greater than zero, headcount at least one
    (ERR_INVALID_REQUEST)."
    PRD §3.1: "A manager registers a Worker at a location, providing full_name, the
    login email (unique among workers within a location), and base_hourly_rate_cents."

    Registering a worker without the required base_hourly_rate_cents ->
    ERR_INVALID_REQUEST.

    Design: Corner/entities/create_worker_missing_required_field_returns_invalid_request
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    resp = api.create_worker(loc["id"], {"full_name": "W", "email": "w@x.com"}, M)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_worker_returns_not_found(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing resource
    produces ERR_NOT_FOUND immediately, before any later identifier or business rule
    is evaluated."

    GET /workers/{nonexistent uuid} -> ERR_NOT_FOUND.

    Design: Corner/entities/get_worker_nonexistent_returns_not_found
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.get_worker(NON_EXISTENT_UUID, M)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_shift_create_generates_system_fields(api):
    """PRD §3.3: "A freshly created shift's posted_utc is empty and its status is
    DRAFT."
    PRD §3.3: "A shift exposes a read-only duration_hours equal to the exact,
    unrounded span between its start and end, and a read-only headcount_filled equal
    to the count of its assignments in SCHEDULED, CONFIRMED, or COMPLETED."

    POST /locations/{id}/shifts sets status DRAFT, version 1, headcount_filled 0, and
    duration_hours 8 for a 09:00..17:00 window.

    Design: Corner/entities/system_fields_generated_on_shift_create
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    resp = api.create_shift(loc["id"], {
        "role_name": "Cashier", "start_utc": "2026-06-02T09:00:00Z",
        "end_utc": "2026-06-02T17:00:00Z", "headcount_required": 1}, M)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["duration_hours"] == 8
    assert data["headcount_filled"] == 0


def test_shift_invalid_time_window_rejected(api):
    """PRD §2.7: "After body shape comes the time-window check, that end_utc is
    strictly after start_utc on a shift, availability window, time-off request, or
    pay-period (ERR_INVALID_TIME_WINDOW)."

    POST /locations/{id}/shifts with end_utc <= start_utc -> ERR_INVALID_TIME_WINDOW.

    Design: Corner/entities/shift_invalid_time_window_returns_invalid_time_window
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    resp = api.create_shift(loc["id"], {
        "role_name": "Cashier", "start_utc": "2026-06-02T17:00:00Z",
        "end_utc": "2026-06-02T09:00:00Z", "headcount_required": 1}, M)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)


def test_list_shifts_pagination_envelope(api):
    """PRD §2.3: "List responses carry limit, offset, total_count, and has_more inside
    the meta object of the envelope."

    With two DRAFT shifts and limit=1, the list returns one item, total_count 2, and
    has_more true.

    Design: Corner/entities/list_shifts_pagination_envelope
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    get_success_data(api.create_shift(loc["id"], {
        "role_name": "Cashier", "start_utc": "2026-06-02T09:00:00Z",
        "end_utc": "2026-06-02T13:00:00Z", "headcount_required": 1}, M))
    get_success_data(api.create_shift(loc["id"], {
        "role_name": "Cashier", "start_utc": "2026-06-03T09:00:00Z",
        "end_utc": "2026-06-03T13:00:00Z", "headcount_required": 1}, M))
    resp = api.list_shifts(M, params={"location_id": loc["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_shift_generated_from_template_carries_template_id(api):
    """PRD §3.3: "The system creates a single DRAFT Shift whose start_utc and end_utc
    are derived by resolving the template's weekday, local start minute, and duration
    against the location's time zone for that week; its headcount_required is copied
    from the template's forecast headcount, and its template_id records the
    originating template."

    Generating from a template (forecast_headcount 2) yields a DRAFT shift with
    template_id set and headcount_required 2.

    Design: Corner/endpoints/shift_generated_from_template_carries_template_id
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    tpl = setup_shift_template(api, loc["id"], role_name="Cashier", weekday=0,
                              local_start_minute=540, duration_minutes=480,
                              forecast_headcount=2)
    resp = api.generate_shift(loc["id"], tpl["id"], {"week_start_local_date": "2026-06-01"}, M)
    data = validate_success(resp, 201)
    assert data["template_id"] == tpl["id"]
    assert data["headcount_required"] == 2
    assert data["status"] == "DRAFT"


def test_list_assignments_filtered_by_worker(api):
    """PRD §4: "GET /assignments — List assignments, filterable by shift, worker, or
    pay-period."
    PRD §3.5: "A manager assigns a worker to a shift directly by posting the shift_id,
    the worker_id."

    GET /assignments?worker_id=W returns exactly the worker's single assignment.

    Design: Corner/endpoints/fk_reverse_assignments_filtered_by_worker
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    resp = api.list_assignments(M, params={"worker_id": worker["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == asg["id"]


def test_worker_cannot_post_shift(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the target
    operation — or a Worker acting on a resource it does not own — is rejected with
    ERR_UNAUTHORIZED."
    PRD §4: "POST /locations/{locId}/shifts | Create an ad-hoc DRAFT shift | Manager"

    Creating a shift is Manager-exclusive; a Worker calling it -> ERR_UNAUTHORIZED.

    Design: Corner/rbac/worker_cannot_post_shift_returns_unauthorized
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    resp = api.create_shift(loc["id"], {
        "role_name": "Cashier", "start_utc": "2026-06-05T09:00:00Z",
        "end_utc": "2026-06-05T13:00:00Z", "headcount_required": 1},
        make_worker_headers(worker["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_worker_cannot_confirm_other_workers_assignment(api):
    """PRD §2.1: "A worker may confirm only an assignment whose worker_id equals
    X-User-ID."
    PRD §3.5: "A worker confirms their own scheduled assignment. Confirmation is
    permitted only from SCHEDULED (otherwise ERR_INVALID_ASSIGNMENT_STATE), only by
    the owning worker whose worker_id equals X-User-ID (otherwise ERR_UNAUTHORIZED)."

    Worker WB confirming WA's assignment -> ERR_UNAUTHORIZED.

    Design: Corner/rbac/worker_cannot_confirm_other_workers_assignment_returns_unauthorized
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    wa = setup_worker(api, loc["id"], full_name="WA", email="wa@x.com", base_hourly_rate_cents=2000)
    wb = setup_worker(api, loc["id"], full_name="WB", email="wb@x.com", base_hourly_rate_cents=2000)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], wa["id"])
    resp = api.confirm_assignment(loc["id"], asg["id"], make_worker_headers(wb["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: X-User-ID, identifying the acting user, and X-User-Role, declaring the
    capacity in which they act ... A request missing or malformed in either header is
    rejected with ERR_UNAUTHENTICATED."

    A request carrying neither auth header -> ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    resp = api.get_location(loc["id"], {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
