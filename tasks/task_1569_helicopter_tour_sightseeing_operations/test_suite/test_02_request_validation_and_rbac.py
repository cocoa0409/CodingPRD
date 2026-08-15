"""Authentication, authorization, and existence-priority rules (PRD §2.1, §2.9)."""
from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    ApiErrorId,
    create_base,
    create_booking,
    create_flight,
    create_pilot,
    file_complaint,
    list_duty_days,
    make_pilot_headers,
    passenger_entry,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import complaint_event

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
AGENT = TEST_USERS["booking_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REPORTER = TEST_USERS["community_reporter_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role the
    server does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    base = create_base()
    resp = api.get_base(base["id"], headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    resp = api.get_base(base["id"], headers=build_user_headers("w-1", "Wizard"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_not_found_beats_state_check(api):
    """PRD §2.9: "Every endpoint evaluates its guards in a fixed global
    order, and a failure at an earlier rung masks every later one."
    PRD §2.9: "4. **Existence** — path identifiers first, left to right, then
    body foreign keys. Failure: `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/not_found_beats_state_check
    """
    missing = "00000000-0000-4000-8000-000000000000"
    resp = api.flight_event(missing, {"event_type": "OPEN_BOARDING"}, DISP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    resp = api.complaint_event(missing, {"event_type": "REVIEW"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_dispatcher_cannot_manage_bases(api):
    """PRD §2.1: "A request whose role is not permitted on the target
    endpoint — or that violates an entity-backed ownership rule — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /bases is authorized for OpsAdmin only, while GET
    /bases/{id} is shared with Dispatcher.

    Design: Corner/rbac/dispatcher_cannot_manage_bases
    """
    base = create_base()
    resp = api.create_base(
        {
            "name": "H2",
            "quiet_hours_start_min_utc": 60,
            "quiet_hours_end_min_utc": 780,
            "current_waiver_version": "WAV-1",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    read = validate_success(api.get_base(base["id"], DISP))
    assert read["id"] == base["id"]


def test_booking_agent_cannot_create_flights(api):
    """PRD §2.1: "A request whose role is not permitted on the target
    endpoint — or that violates an entity-backed ownership rule — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /flights is authorized for Dispatcher only.

    Design: Corner/rbac/booking_agent_cannot_create_flights
    """
    env = setup_ops_env()
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T14:00:00Z",
        },
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    flights, meta = validate_paginated(
        api.list_flights(AGENT, params={"base_id": env["base"]["id"]})
    )
    assert meta["total_count"] == 0, "denied create must persist nothing"


def test_complaint_endpoints_role_restricted(api):
    """PRD §2.1: "A request whose role is not permitted on the target
    endpoint — or that violates an entity-backed ownership rule — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /complaints is authorized for CommunityReporter; POST
    /complaints/{id}/events is authorized for ComplianceOfficer.

    Design: Corner/rbac/complaint_endpoints_role_restricted
    """
    set_clock("2026-08-03T00:00:00Z")
    base = create_base()
    complaint = file_complaint(base["id"], "VILLAGE", "2026-08-02T10:00:00Z",
                               description="noise")

    resp = api.complaint_event(complaint["id"], {"event_type": "REVIEW"}, REPORTER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    resp = api.create_complaint(
        {
            "base_id": base["id"],
            "zone": "RIM",
            "observed_at": "2026-08-02T11:00:00Z",
            "description": "more noise",
            "reporter_ref": "r9",
        },
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    updated = complaint_event(complaint["id"], "REVIEW")
    assert updated["status"] == "UNDER_REVIEW"


def test_opsadmin_cannot_file_complaints(api):
    """PRD §2.1: "A request whose role is not permitted on the target
    endpoint — or that violates an entity-backed ownership rule — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /complaints is authorized for CommunityReporter only.

    Design: Corner/rbac/opsadmin_cannot_file_complaints
    """
    base = create_base()
    resp = api.create_complaint(
        {
            "base_id": base["id"],
            "zone": "AIRPORT",
            "observed_at": "2026-08-02T10:00:00Z",
            "description": "noise",
            "reporter_ref": "r1",
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_pilot_duty_days_scoped_to_self(api):
    """PRD §2.1: "Concretely, a pilot may acknowledge only a flight whose
    `pilot_id` equals `X-User-ID`, and may query duty-day ledgers only for
    their own `pilot_id`; a pilot reading another pilot's duty-day rows is
    rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/pilot_duty_days_scoped_to_self
    """
    env = setup_ops_env()
    pilot2 = create_pilot(display_name="Pat Two", certificate_no="C2")
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    rows = list_duty_days(env["pilot"]["id"], duty_date="2026-08-03")
    assert len(rows) == 1
    duty_day_id = rows[0]["id"]

    own = list_duty_days(
        env["pilot"]["id"], headers=make_pilot_headers(env["pilot"]["id"])
    )
    assert own[0]["pilot_id"] == env["pilot"]["id"]

    resp = api.list_duty_days(
        make_pilot_headers(env["pilot"]["id"]),
        params={"pilot_id": pilot2["id"]},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    resp = api.get_duty_day(duty_day_id, make_pilot_headers(pilot2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
