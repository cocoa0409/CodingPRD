"""The uniform error envelope and the authentication rung that runs ahead of existence."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assertions,
    build_user_headers,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import OFFICER, REGULATOR
from test_helpers.test_users import OFFICER_USER_ID

NO_ROLE_HEADERS = {"X-User-ID": OFFICER_USER_ID, "Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = build_user_headers(OFFICER_USER_ID, "NotARealRole")


def test_authentication_answers_before_existence_and_in_the_same_envelope(client):
    """A caller with no role header learns nothing about whether the identifier it asked for exists,
    an unrecognised role string is unauthenticated rather than unauthorised, and only an
    authenticated regulator gets the 404 — all four refusals arriving in the identical two-field
    error envelope with nothing written.

    PRD: "1. **Authentication** — headers present and the role recognised, else
    `ERR_UNAUTHENTICATED`. Applies to every endpoint."
    PRD: "2. **Role authorisation** — the acting role appears in the endpoint's authorised-role
    list, else `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."
    PRD: "When a single request violates more than one rule, the response is determined by the
    **first** rule that fails in the ordering below, not by the most severe violation."
    PRD: "4. **Existence** — every identifier in the URL path is resolved left to right, then every
    foreign key in the request body is resolved; the first unresolved identifier yields
    `ERR_RESOURCE_NOT_FOUND`."
    PRD: "- The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD: "- The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD: "- The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/request_missing_x_user_role_header_unauthenticated
    """
    fixtures.set_clock(client)
    depository = fixtures.create_draft_depository(client)
    version_before = depository["version"]

    unauthenticated = client.get_depository(depository["id"], NO_ROLE_HEADERS)
    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    unauthenticated_unknown_id = client.get_depository(
        NON_EXISTENT_UUID, NO_ROLE_HEADERS
    )
    validate_error(unauthenticated_unknown_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    unrecognised_role = client.get_depository(NON_EXISTENT_UUID, UNKNOWN_ROLE_HEADERS)
    validate_error(unrecognised_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    authenticated_miss = client.get_depository(NON_EXISTENT_UUID, REGULATOR)
    validate_error(authenticated_miss, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

    for response in (
        unauthenticated,
        unauthenticated_unknown_id,
        unrecognised_role,
        authenticated_miss,
    ):
        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assertions.assert_envelope_meta(body)
        assert set(body["data"]) == {"error_id", "message"}
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]

    still_there = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert still_there["version"] == version_before
    _depositories, meta = validate_paginated(client.list_depositories(REGULATOR))
    assert meta["total_count"] == 1
