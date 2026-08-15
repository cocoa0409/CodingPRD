"""Rooms, route-creation safety rules, envelope shape, and baseline auth."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_room,
    create_room,
    make_headers_without_user_id,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["museum_admin_headers"]
CURATOR = TEST_USERS["curator_headers"]


class TestRoomCreation:

    def test_room_create_defaults_status_open(self):
        """PRD section 3.1: "A new room starts in `OPEN` status; its only
        other state, `CLOSED_RESTORATION`, is reached exclusively through the
        incident cascade of §3.7."
        PRD section 2.4: "a `version`, an integer that increments by one on
        every mutation of the resource".

        Design: Corner/entities/room_create_defaults_status_open
        """
        resp = api_client.create_room(
            {
                "name": "Attic", "floor": 3, "capacity_max": 8,
                "safety_max_party": 6, "collection_tier": "STANDARD",
            },
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_room(data)
        assert data["status"] == "OPEN", (
            f"new room must start OPEN, got {data['status']}"
        )
        assert data["version"] == 1, (
            f"new room must start at version 1, got {data['version']}"
        )

    def test_room_missing_capacity_returns_invalid_request(self):
        """PRD section 2.9, tier 4: "required fields present, enum values
        inside their declared sets, integer bounds respected (a `party_size`
        of at least 1 for general and member bookings, `student_count` of at
        least 1, survey ratings between 1 and 5 inclusive, quiz values
        between 0 and 100 inclusive, `capacity_max` of at least 1), and
        kind-specific field-set discipline (a school booking must not carry
        `party_size`; general and member bookings must not carry the
        school-only fields); failures yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/room_missing_capacity_returns_invalid_request
        """
        resp = api_client.create_room(
            {
                "name": "Attic", "floor": 3,
                "safety_max_party": 6, "collection_tier": "STANDARD",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_missing_room_returns_not_found(self):
        """PRD section 2.8: "Path parameters are validated left to right:
        each `{id}` segment in the URL must resolve to an existing resource
        before the next segment or the request body is considered, and the
        first unresolvable segment is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_missing_room_returns_not_found
        """
        resp = api_client.get_room(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestErrorEnvelope:

    def test_error_envelope_shape_on_failure(self):
        """PRD section 2.2: "The `meta` object for error responses contains
        only `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error."
        PRD section 2.2: "The `message` provides a human-readable explanation
        of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        resp = api_client.get_room(NON_EXISTENT_UUID, ADMIN)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(error_data["message"], str) \
            and len(error_data["message"].strip()) > 0
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
            f"error meta must carry exactly api_request_id and "
            f"api_request_timestamp, got {sorted(meta.keys())}"
        )


class TestAuthentication:

    def test_missing_x_user_id_header_returns_unauthenticated(self):
        """PRD section 2.1: "A request missing either header, or presenting a
        role outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_x_user_id_header_returns_unauthenticated
        """
        room = create_room()
        resp = api_client.get_room(
            room["id"], make_headers_without_user_id("MuseumAdmin"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRouteCreationSafety:

    def test_candlelight_light_sensitive_route_rejected(self):
        """PRD section 2.7: "Second, the candlelight rule: a route whose
        `kind` is `CANDLELIGHT` may not include any `LIGHT_SENSITIVE` room,
        and this is enforced at route creation with
        `ERR_CANDLELIGHT_LIGHT_SENSITIVE` (HTTP 422)."

        Design: Corner/validations/candlelight_light_sensitive_route_rejected
        """
        room = create_room(name="Textile Gallery", floor=2, capacity_max=15,
                           safety_max_party=8,
                           collection_tier="LIGHT_SENSITIVE")
        resp = api_client.create_tour_route(
            {
                "name": "Candlelight Textiles", "kind": "CANDLELIGHT",
                "room_ids": [room["id"]], "duration_minutes": 60,
                "base_price_cents": 1500,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CANDLELIGHT_LIGHT_SENSITIVE)


class TestRoleDenial:

    def test_curator_cannot_create_room_forbidden(self):
        """PRD section 2.1: "A request whose role is not on the endpoint's
        authorized list, or that fails an ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: POST /rooms is authorized for MuseumAdmin only.

        Design: Corner/rbac/curator_cannot_create_room_forbidden
        """
        resp = api_client.create_room(
            {
                "name": "Attic", "floor": 3, "capacity_max": 8,
                "safety_max_party": 6, "collection_tier": "STANDARD",
            },
            CURATOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
