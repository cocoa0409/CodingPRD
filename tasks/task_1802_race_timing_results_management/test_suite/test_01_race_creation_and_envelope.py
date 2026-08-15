"""Race creation defaults, response envelope shape, and the error catalogue."""
import re

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_race_payload,
    create_timing_point_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
OP = TEST_USERS["timing_operator_headers"]


class TestRaceCreationDefaults:
    def test_race_creation_sets_initial_state_and_defaults(self, api):
        """PRD §3.1: "A new race starts in `DRAFT` with `amendment_count` at zero,
        and every lifecycle stamp — `timing_locked_at`, `provisional_published_at`,
        `protest_window_closes_at`, and `finalized_at` — is null, as are
        `locked_by_user_id` and the `timing_config_fingerprint`."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a UUID, with no type prefix."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."

        Design: Corner/entities/race_creation_sets_initial_state_and_defaults
        """
        resp = api.create_race(
            create_race_payload(name="Defaults 5K", distance_km=5.0,
                                course_type="UNCERTIFIED_COURSE",
                                course_time_limit_minutes=90),
            RD,
        )
        race = validate_success(resp, 201)
        assert race["status"] == "DRAFT", "A new race starts in DRAFT"
        assert race["amendment_count"] == 0
        assert race.get("qualifying_standard_ms") is None, (
            "qualifying_standard_ms is optional and absent means no qualifying event"
        )
        assert race["version"] == 1
        assert is_valid_uuid(race["id"]), "id is a server-minted bare UUID"
        assert is_iso8601_timestamp(race["created_at"])
        assert re.search(r"\.\d{3}Z$", race["created_at"]), (
            "created_at carries three fractional digits"
        )
        for stamp in ("timing_locked_at", "provisional_published_at",
                      "protest_window_closes_at", "finalized_at"):
            assert race.get(stamp) is None, f"{stamp} starts null"
        assert race.get("locked_by_user_id") is None
        assert race.get("timing_config_fingerprint") is None

    def test_race_creation_ignores_input_supplied_system_fields(self, api):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."
        PRD §2.5: "`version` (integer): a system-managed counter that increments
        by one on every modification of the resource."

        Design: Corner/entities/race_creation_sets_initial_state_and_defaults
        """
        payload = create_race_payload(name="Forged Fields 5K", distance_km=5.0,
                                      course_type="UNCERTIFIED_COURSE",
                                      course_time_limit_minutes=90)
        payload["id"] = "00000000-0000-0000-0000-000000000000"
        payload["version"] = 99
        race = validate_success(api.create_race(payload, RD), 201)
        assert is_valid_uuid(race["id"])
        assert race["id"] != "00000000-0000-0000-0000-000000000000", (
            "the server mints the id; an input-supplied id is ignored"
        )
        assert race["version"] == 1, "version is system-managed, not caller-set"
        assert race["status"] == "DRAFT"


class TestRaceCreationValidation:
    def test_race_create_missing_required_returns_400(self, api):
        """PRD §3.1: "A `RaceDirector` opens a new event by creating a **Race**
        with a display `name`, the scheduled `race_date`, the course `distance_km`
        in kilometers (which must be greater than zero), a `course_type` of either
        `CERTIFIED_COURSE` or `UNCERTIFIED_COURSE`, and a `course_time_limit_minutes`
        cutoff (also greater than zero)."
        PRD §5: `ERR_INVALID_REQUEST` | 400 Bad Request.

        Design: Corner/entities/race_create_missing_required_returns_400
        """
        payload = {
            "name": "Bad",
            "race_date": "2026-08-01T00:00:00Z",
            "distance_km": 5.0,
            "course_type": "UNCERTIFIED_COURSE",
        }
        resp = api.create_race(payload, RD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestExistenceAndEnvelope:
    def test_get_unknown_id_returns_404(self, api):
        """PRD §2.10: "Every identifier appearing in a request — each variable in
        the path and every `*_id` field in the body — must resolve to an existing
        resource. Resolution proceeds left to right, validating path identifiers
        first and body identifiers afterwards; the first unresolvable identifier
        yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_unknown_id_returns_404
        """
        resp = api.get_race(NON_EXISTENT_UUID, RD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_race(NON_EXISTENT_UUID, RD)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
            "error meta carries only api_request_id and api_request_timestamp"
        )
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_error_catalog_invalid_enum_returns_400(self, api):
        """PRD §5: `ERR_INVALID_REQUEST` | 400 Bad Request.
        PRD §3.1: "a `kind` of `START`, `SPLIT`, or `FINISH`" — any other enum
        member is an invalid request body.

        Design: Corner/errors/error_catalog_coverage_note
        """
        race = validate_success(api.create_race(
            create_race_payload(name="Enum 5K", distance_km=5.0,
                                course_type="UNCERTIFIED_COURSE",
                                course_time_limit_minutes=90),
            RD), 201)
        payload = create_timing_point_payload(
            race["id"], 1, "BOGUS", 0.0, "MAT-E1",
            deploy_at="2026-08-01T05:00:00Z",
            expected_teardown_at="2026-08-01T12:00:00Z")
        resp = api.create_timing_point(payload, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestImmediateConsistency:
    def test_mutation_visible_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §2.11: "Every mutation in the system commits atomically within its
        request; there is no eventual consistency anywhere in this API."

        Design: Corner/consistency_model/mutation_visible_in_same_response
        """
        race = validate_success(api.create_race(
            create_race_payload(name="Immediate 5K", distance_km=5.0,
                                course_type="UNCERTIFIED_COURSE",
                                course_time_limit_minutes=90),
            RD), 201)
        assert race["status"] == "DRAFT" and race["version"] == 1

        opened = validate_success(api.open_registration(race["id"], RD), 200)
        assert opened["status"] == "REGISTRATION_OPEN"
        assert opened["version"] == 2, (
            "the transition response carries the post-mutation state, no re-read"
        )
