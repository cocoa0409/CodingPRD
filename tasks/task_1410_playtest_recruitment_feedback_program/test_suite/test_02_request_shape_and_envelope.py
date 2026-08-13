"""Request-shape rules: enum validity, session window rule, station
conditionality, build defaults, and the error envelope contract."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_build,
    create_build_payload,
    create_session_payload,
    create_station,
    create_study,
    get_success_data,
    is_valid_uuid,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]


def test_session_create_rejects_unknown_mode(api):
    """PRD §3.5: "A `Researcher` schedules a playtest session with a `study_id`,
    a `mode` of `REMOTE` or `IN_LAB`, a window from `starts_at` to `ends_at`,
    and a `seat_capacity` of at least 1."
    PRD §2.9: "Required fields are present, enum values are valid, and numeric
    ranges hold — `age_years` at least 13, `max_age` at least `min_age`,
    `cohort_capacity` at least 1, `incentive_budget_cents` at least 0,
    `max_keys` at least 1, `key_ttl_hours` at least 1, `seat_capacity` at least
    1, `reach_count` at least 0, `reproducibility_pct` between 0 and 1
    inclusive, `pass_threshold` between 0 and 100 inclusive, and each answer's
    `points` between 0 and its question's `max_points` inclusive; otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/session_create_rejects_invalid_mode_enum
    """
    study = create_study(open_recruitment=False, code="EN1")
    resp = api.create_session(
        create_session_payload(study["id"], "2026-08-10T10:00:00Z",
                               "2026-08-10T11:00:00Z", seat_capacity=4,
                               mode="HYBRID"), RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_session_create_rejects_inverted_window(api):
    """PRD §3.5: "The window's end must fall strictly after its start; a window
    that fails this is rejected with `ERR_WINDOW_VIOLATION`, not the generic
    request error."

    Design: Corner/entities/session_create_rejects_inverted_window
    """
    study = create_study(open_recruitment=False, code="WN1")
    resp = api.create_session(
        create_session_payload(study["id"], "2026-08-10T11:00:00Z",
                               "2026-08-10T10:00:00Z", seat_capacity=4), RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)


def test_in_lab_station_conditional_requirement(api):
    """PRD §3.5: "An `IN_LAB` session must name a `station_id` for an
    `AVAILABLE` station, and a `REMOTE` session must not carry a `station_id`
    at all — both violations are `ERR_STATION_REQUIRED`"

    Design: Corner/validations/in_lab_station_conditional_requirement
    """
    study = create_study(code="MODE")
    station = create_station(station_code="ST9", location="Lab B")
    # IN_LAB without station_id -> ERR_STATION_REQUIRED
    resp1 = api.create_session(
        create_session_payload(study["id"], "2026-08-10T10:00:00Z",
                               "2026-08-10T11:00:00Z", seat_capacity=4,
                               mode="IN_LAB"), RESEARCHER)
    validate_error(resp1, ApiErrorId.ERR_STATION_REQUIRED)
    # REMOTE carrying a station_id -> ERR_STATION_REQUIRED
    resp2 = api.create_session(
        create_session_payload(study["id"], "2026-08-10T10:00:00Z",
                               "2026-08-10T11:00:00Z", seat_capacity=4,
                               mode="REMOTE", station_id=station["id"]), RESEARCHER)
    validate_error(resp2, ApiErrorId.ERR_STATION_REQUIRED)
    # REMOTE without station_id -> created
    ok = validate_success(api.create_session(
        create_session_payload(study["id"], "2026-08-10T10:00:00Z",
                               "2026-08-10T11:00:00Z", seat_capacity=4,
                               mode="REMOTE"), RESEARCHER), expected_status=201)
    assert is_valid_uuid(ok["id"])
    assert ok["mode"] == "REMOTE"


def test_build_starts_staged_with_defaults(api):
    """PRD §3.4: "A build starts `STAGED` with `keys_active_count` at 0."
    PRD §3.4: "an optional `key_ttl_hours` — the hours from issuance until an
    unredeemed key expires — defaulting to 72 and never below 1"
    PRD §3.4: "Releasing moves `STAGED` → `RELEASED` and stamps `released_at`"

    Design: Corner/state_machines/build_initial_state_staged
    """
    study = create_study(open_recruitment=False, code="IS1")
    data = validate_success(api.create_build(
        create_build_payload(study["id"], build_label="0.1.0", max_keys=3), ADMIN),
        expected_status=201)
    assert_build(data)
    assert data["status"] == "STAGED"
    assert data["keys_active_count"] == 0
    assert data.get("released_at") is None, "released_at is stamped only at release"
    assert data["key_ttl_hours"] == 72, "omitted key_ttl_hours defaults to 72"


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    resp = api.get_study(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("response_type") == "error"
    meta = body.get("meta", {})
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "error meta contains only api_request_id and api_request_timestamp")
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    error = body["data"]
    assert error["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"].strip()
