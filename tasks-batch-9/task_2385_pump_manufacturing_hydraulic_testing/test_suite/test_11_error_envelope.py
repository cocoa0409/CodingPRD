"""Authentication headers and the single shape every rejection is returned in.

Both checks in this file look at the envelope rather than the domain.  Every
request must carry an identity and a role, and a request that carries neither is
rejected before anything else about it is considered, so an unauthenticated
caller can never learn whether its body was well formed or whether its role
would have been allowed.  Once a request is rejected, the response body has the
same three top-level members with the same two members under `data` and the same
two under `meta`, whatever the reason and whatever the status code, so a client
can parse any failure the same way.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    Role,
    assert_error_envelope,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import (
    APPLICATION_ENGINEER,
    PLATFORM_ADMIN,
    headers_without_user_id,
)


# ─────────────────────────────────────────────────────────────────────────────
# Authentication comes before everything else
# ─────────────────────────────────────────────────────────────────────────────
class TestMissingIdentityHeader:
    """A request without an identity is turned away before it is examined."""

    def test_a_foundry_create_without_the_user_id_header_is_unauthenticated(self, api):
        """An absent identity header is rejected as unauthenticated, and nothing else.

        The body deliberately omits the foundry's name, its approved alloys and
        its concurrent pour capacity, and the role header names an actor who
        would in fact be allowed to register a foundry.  Because the identity and
        role headers are checked first and the first violated check ends the
        request, the answer is the unauthenticated rejection: the malformed body
        is never reported and the caller's role is never weighed.  No foundry is
        registered.

        Design: Corner/errors/create_foundry_missing_x_user_id_header_returns_unauthenticated
        """
        response = api.create_foundry(
            {"foundry_code": "FDY-NORTH"},
            headers_without_user_id(Role.PLATFORM_ADMIN),
        )
        validate_error(response, ApiErrorId.UNAUTHENTICATED)

        error_id = response.json()["data"]["error_id"]
        assert error_id != "ERR_INVALID_REQUEST", "the body is never examined"
        assert error_id != "ERR_UNAUTHORIZED", "the role is never weighed"

        _, meta = validate_paginated(api.list_foundries(PLATFORM_ADMIN))
        assert meta["total_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# One envelope for every rejection
# ─────────────────────────────────────────────────────────────────────────────
class TestErrorEnvelopeAcrossStatusClasses:
    """Seven rejections spanning every status class the contract issues."""

    @pytest.fixture
    def world(self, api):
        """A registered foundry, model, pattern, config and an open enquiry."""
        ctx = X.setup_master_data(api)
        ctx["duty"] = X.create_duty_application(api)
        return ctx

    @pytest.fixture
    def rejections(self, api, world):
        """One deliberately refused request per documented failure class."""
        return [
            (
                ApiErrorId.UNAUTHENTICATED,
                401,
                lambda: api.create_foundry(
                    F.foundry_payload(), headers_without_user_id(Role.PLATFORM_ADMIN)
                ),
            ),
            (
                ApiErrorId.UNAUTHORIZED,
                403,
                lambda: api.create_pump_model(
                    F.pump_model_payload(), world["foundry_headers"]
                ),
            ),
            (
                ApiErrorId.INVALID_REQUEST,
                400,
                lambda: api.create_foundry(
                    {"foundry_code": "FDY-SOUTH"}, PLATFORM_ADMIN
                ),
            ),
            (
                ApiErrorId.NOT_FOUND,
                404,
                lambda: api.get_foundry(NON_EXISTENT_UUID, PLATFORM_ADMIN),
            ),
            (
                ApiErrorId.DUPLICATE_CODE,
                409,
                lambda: api.create_foundry(
                    F.foundry_payload(foundry_code=world["foundry"]["foundry_code"]),
                    PLATFORM_ADMIN,
                ),
            ),
            (
                ApiErrorId.STALE_DUTY_APPLICATION_VERSION,
                412,
                lambda: api.create_selection(
                    F.selection_payload(
                        world["duty"]["id"],
                        world["model"]["id"],
                        world["config"]["id"],
                        world["duty"]["version"] + 1,
                    ),
                    APPLICATION_ENGINEER,
                ),
            ),
            (
                ApiErrorId.SUCCESSOR_MODEL_INVALID,
                422,
                lambda: api.supersede_pump_model(
                    world["model"]["id"],
                    F.supersede_model_payload(world["model"]["id"]),
                    PLATFORM_ADMIN,
                ),
            ),
        ]

    def test_every_rejected_request_returns_the_same_three_member_envelope(
        self, rejections
    ):
        """Missing credentials, a forbidden role, a bad body, an unknown row, a
        duplicate code, a stale version token and an invalid successor all come
        back in one shape.

        Each response carries `response_type` set to `error`, a `data` object
        holding exactly the error identifier and a human readable message, and a
        `meta` object holding only the request identifier and the request
        timestamp.  Nothing else appears at any level, so the member names are
        identical across all seven answers even though their status codes span
        401, 403, 400, 404, 409, 412 and 422.

        Design: Corner/errors/error_envelope_is_identical_across_status_classes_for_rejected_requests
        """
        shapes = set()
        seen_statuses = set()

        for error_id, status, call in rejections:
            response = call()
            validate_error(response, error_id)
            assert response.status_code == status

            body = response.json()
            assert_error_envelope(body, error_id)
            assert set(body) == {"response_type", "data", "meta"}
            assert set(body["data"]) == {"error_id", "message"}
            assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
            assert body["response_type"] == "error"
            assert isinstance(body["data"]["message"], str) and body["data"]["message"]

            shapes.add(
                (
                    tuple(sorted(body)),
                    tuple(sorted(body["data"])),
                    tuple(sorted(body["meta"])),
                    body["response_type"],
                )
            )
            seen_statuses.add(status)

        assert seen_statuses == {400, 401, 403, 404, 409, 412, 422}
        assert len(shapes) == 1, f"rejections disagree on their envelope: {shapes}"

    def test_none_of_the_rejected_requests_changed_any_stored_state(
        self, api, world, rejections
    ):
        """A rejection is inert: nothing is created, mutated or superseded.

        The two attempts to register a foundry leave the single registered
        foundry standing alone, the forbidden model create adds no model, the
        stale enquiry token creates no selection and leaves the enquiry open at
        the version it already had, and the refused supersede leaves the model
        orderable with no successor recorded.

        Design: Corner/errors/error_envelope_is_identical_across_status_classes_for_rejected_requests
        """
        for _, _, call in rejections:
            call()

        _, foundry_meta = validate_paginated(api.list_foundries(PLATFORM_ADMIN))
        assert foundry_meta["total_count"] == 1

        _, model_meta = validate_paginated(api.list_pump_models(PLATFORM_ADMIN))
        assert model_meta["total_count"] == 1

        _, selection_meta = validate_paginated(api.list_selections(PLATFORM_ADMIN))
        assert selection_meta["total_count"] == 0

        duty = X.reread_duty_application(api, world["duty"]["id"])
        assert duty["status"] == "OPEN"
        assert duty["version"] == world["duty"]["version"]

        model = X.reread_pump_model(api, world["model"]["id"])
        assert model["status"] == "ORDERABLE"
        assert model["superseded_by_model_id"] is None

        stored = get_success_data(api.get_foundry(world["foundry"]["id"], PLATFORM_ADMIN))
        assert stored["foundry_code"] == world["foundry"]["foundry_code"]
        assert stored["version"] == world["foundry"]["version"]
