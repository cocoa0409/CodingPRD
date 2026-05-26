"""Entity input validation: required fields, enums, time windows, system fields,
not-found, and missing-auth-header rejection.
"""
import re

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_unauthenticated_headers,
)


# ---------------------------------------------------------------------
# Required / type-constraint corner instances on POST /crew-members
# ---------------------------------------------------------------------

def test_create_crew_member_missing_employee_code_rejected(api, planner_headers):
    """PRD §2.9: "Generic schema conformance: required fields present,
    types/enums/formats valid, no unknown fields — else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_crew_member_missing_employee_code_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = {
        # employee_code intentionally omitted
        "full_name": "X",
        "rank": "CAPTAIN",
        "base_airport": "LAX",
        "seniority_number": 1,
        "line_type": "LINEHOLDER",
    }
    res = api.create_crew_member(payload, planner_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_crew_member_invalid_rank_enum_rejected(api, planner_headers):
    """PRD §3.2: "a `rank` from the set `CAPTAIN`, `FIRST_OFFICER`, `PURSER`,
    and `FLIGHT_ATTENDANT`".
    PRD §2.9: "types/enums/formats valid, no unknown fields — else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_crew_member_invalid_rank_enum_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = {
        "employee_code": "AB0001",
        "full_name": "X",
        "rank": "PILOT",  # not in the enum
        "base_airport": "LAX",
        "seniority_number": 1,
        "line_type": "LINEHOLDER",
    }
    res = api.create_crew_member(payload, planner_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ---------------------------------------------------------------------
# Time-window sanity on Pairing creation
# ---------------------------------------------------------------------

def test_create_pairing_invalid_time_window_close_after_start_rejected(api, planner_headers):
    """PRD §3.1: "Time-window sanity is enforced at creation and at open-bidding
    time: `bidding_close_utc` must be strictly less than `scheduled_start_utc`,
    and `scheduled_end_utc` must be strictly greater than `scheduled_start_utc`;
    any other arrangement is rejected with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/entities/create_pairing_invalid_time_window_close_after_start
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = {
        "pairing_code": "P-2026-200",
        "origin_base": "LAX",
        "scheduled_start_utc": "2026-06-02T00:00:00Z",
        "scheduled_end_utc": "2026-06-02T10:00:00Z",
        "required_captains": 1,
        "required_first_officers": 0,
        "required_cabin_crew": 0,
        # bidding_close_utc strictly greater than scheduled_start_utc — invalid
        "bidding_close_utc": "2026-06-02T01:00:00Z",
    }
    res = api.create_pairing(payload, planner_headers)
    validate_error(res, "ERR_INVALID_TIME_WINDOW", expected_status=422)


# ---------------------------------------------------------------------
# System-managed fields on POST /crew-members
# ---------------------------------------------------------------------

UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def test_create_crew_member_system_fields_minted_by_server(api, planner_headers):
    """PRD §2.4: "`id` (string): a server-minted UUID; it does **not** carry a
    type prefix and is the sole identifier used in URL paths and as the value
    of any foreign-key field that references this resource."
    PRD §2.4: "`version` (integer): a monotonically increasing counter that
    starts at 1 on creation and increments by exactly one on every mutation."

    Design: Corner/entities/create_crew_member_system_fields_minted_by_server
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = {
        "employee_code": "AB0002",
        "full_name": "X",
        "rank": "CAPTAIN",
        "base_airport": "LAX",
        "seniority_number": 2,
        "line_type": "LINEHOLDER",
    }
    res = api.create_crew_member(payload, planner_headers)
    data = validate_success(res, expected_status=201)
    assert UUID_REGEX.match(data["id"]), (
        f"id must be a raw UUID (no type prefix), got {data['id']!r}"
    )
    assert data["version"] == 1, f"version must start at 1, got {data['version']!r}"
    # created_at must be ISO 8601 UTC (PRD §2.4 says "with three fractional-second digits")
    assert isinstance(data["created_at"], str) and data["created_at"].endswith("Z")


# ---------------------------------------------------------------------
# Not-found on GET /crew-members/{id}
# ---------------------------------------------------------------------

def test_get_crew_member_not_found_returns_404(api, planner_headers):
    """PRD §2.9: "Path-segment existence: every `{id}` in the URL must resolve
    to an existing entity, left to right (else `ERR_NOT_FOUND`)."

    Design: Corner/entities/get_crew_member_not_found_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_crew_member("00000000-0000-0000-0000-000000000000", planner_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ---------------------------------------------------------------------
# Auth header presence (priority 1 of validation order)
# ---------------------------------------------------------------------

def test_request_without_user_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing or empty, the request is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/err_unauthenticated_missing_header
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.list_crew_members(make_unauthenticated_headers())
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
