"""Entity creation, config defaults, required-field and type validation, system
fields, and not-found behaviour.

Corner queue: entities section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_director_headers, make_guardian_headers,
    ApiErrorId, register_guardian,
    api_client,
)


def test_create_camp_returns_201_with_config_defaults():
    """PRD §3.1: "A camp is created with a `name` and a set of optional configuration
    knobs that fall back to defaults when omitted: `counselor_camper_ratio`
    (default 6), `cit_counts_as_half` (default true), `deposit_cents` (default 25000,
    the non-refundable deposit that converts an offered application to a paid one),
    `deposit_grace_days` (default 7, the number of days an offered application may sit
    before intake expires it back to the waitlist), and `canteen_low_balance_cents`
    (default 1000, the balance at or below which a canteen account is marked low)."

    Design: Corner/entities/create_camp_returns_201_with_config_defaults
    """
    director = make_director_headers()
    get_success_data(api_client.set_clock("2026-04-01T00:00:00Z", director))
    data = validate_success(api_client.create_camp({"name": "Solo Camp"}, director),
                            expected_status=201)
    assert data["counselor_camper_ratio"] == 6, data["counselor_camper_ratio"]
    assert data["deposit_cents"] == 25_000, data["deposit_cents"]
    assert data["deposit_grace_days"] == 7, data["deposit_grace_days"]
    assert data["cit_counts_as_half"] is True, data["cit_counts_as_half"]
    assert data["canteen_low_balance_cents"] == 1_000, data["canteen_low_balance_cents"]
    assert data["version"] == 1, data["version"]


def test_create_session_missing_capacity_rejected():
    """PRD §3.1: "a total bed `capacity` across all of the session's cabins."
    PRD §3.10: "the basic request-shape checks — required fields present and
    well-typed, valid enum members, positive amounts where required, end after start,
    max age at least min age, and end minute after start minute
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_session_missing_capacity_returns_invalid_request
    """
    director = make_director_headers()
    get_success_data(api_client.set_clock("2026-04-01T00:00:00Z", director))
    camp = get_success_data(api_client.create_camp({"name": "C"}, director))
    resp = api_client.create_session(
        camp["id"],
        {"name": "S", "starts_on": "2026-07-01T00:00:00Z", "ends_on": "2026-07-14T00:00:00Z",
         "visiting_day_on": "2026-07-07T00:00:00Z"},
        director)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_session_nonexistent_returns_not_found():
    """PRD §2.6: "The request is rejected with `ERR_NOT_FOUND` corresponding to the
    first identifier in the path that does not resolve to an existing resource".

    Design: Corner/entities/get_session_nonexistent_returns_not_found
    """
    director = make_director_headers()
    get_success_data(api_client.set_clock("2026-04-01T00:00:00Z", director))
    resp = api_client.get_session("00000000-0000-4000-8000-000000000000", director)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_session_ends_before_starts_rejected():
    """PRD §3.1: "an end instant `ends_on` that must fall strictly after `starts_on`".
    PRD §3.1: "A start instant not strictly before the end, or a visiting day outside
    the session window, is rejected — the former as `ERR_INVALID_REQUEST` and the
    latter as `ERR_VISITING_DAY_OUT_OF_RANGE`."

    Design: Corner/entities/session_create_ends_before_starts_returns_invalid_request
    """
    director = make_director_headers()
    get_success_data(api_client.set_clock("2026-04-01T00:00:00Z", director))
    camp = get_success_data(api_client.create_camp({"name": "C"}, director))
    resp = api_client.create_session(
        camp["id"],
        {"name": "S", "starts_on": "2026-07-14T00:00:00Z", "ends_on": "2026-07-01T00:00:00Z",
         "visiting_day_on": "2026-07-07T00:00:00Z", "capacity": 10},
        director)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_cabin_max_age_below_min_age_rejected():
    """PRD §3.2: "a highest accepted camper age `max_age` (inclusive) that must be at
    least `min_age`".
    PRD §3.2: "A cabin where `max_age` is below `min_age` is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/cabin_create_max_age_below_min_age_returns_invalid_request
    """
    director = make_director_headers()
    get_success_data(api_client.set_clock("2026-04-01T00:00:00Z", director))
    camp = get_success_data(api_client.create_camp({"name": "C"}, director))
    sess = get_success_data(api_client.create_session(
        camp["id"], {"name": "S", "starts_on": "2026-07-01T00:00:00Z",
                     "ends_on": "2026-07-14T00:00:00Z",
                     "visiting_day_on": "2026-07-07T00:00:00Z", "capacity": 10}, director))
    resp = api_client.create_cabin(
        sess["id"], {"name": "Bad", "gender_band": "BOYS", "min_age": 12, "max_age": 8,
                     "bunk_capacity": 6}, director)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_camper_system_fields_stamped_on_create():
    """PRD §3.3: "A camper's `guardian_user_id` is set to the acting `X-User-ID`, and
    its `health_status` starts at `NONE`."

    Design: Corner/entities/camper_system_fields_ignored_on_create
    """
    guardian = register_guardian(email="cgr@x.com")
    g_id = guardian["id"]
    data = validate_success(api_client.create_camper(
        {"full_name": "Kid", "age": 9, "gender": "BOY"}, make_guardian_headers(g_id)),
        expected_status=201)
    assert data["health_status"] == "NONE", data["health_status"]
    assert data["guardian_user_id"] == g_id, data["guardian_user_id"]
