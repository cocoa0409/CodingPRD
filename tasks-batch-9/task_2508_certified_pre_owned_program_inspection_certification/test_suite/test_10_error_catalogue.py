"""The shape of every refusal the certified pre-owned programme issues.

The programme distinguishes fifty-nine named failures, and a client's only
handle on which one occurred is the `error_id` string inside a fixed envelope.
That envelope has to be identical whatever went wrong: a uniqueness collision on
a franchise code, a path identifier that names no row, and a request body
missing a required field must all answer with the same three-part structure —
the `error` marker, a `data` object holding nothing but the identifier and a
human-readable message, and a `meta` object holding nothing but the request
identifier and its timestamp. In particular a rejection must never leak a
half-built resource back to the caller, and it must never dress an error as a
one-row collection by attaching pagination fields.
"""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_error_envelope,
    assert_millisecond_timestamp,
    create_dealer,
    create_dealer_payload,
    create_template_payload,
    unique_franchise_code,
    unique_template_code,
    validate_error,
)


def _only_the_error_envelope(response, error_id, expected_status):
    """Assert the refusal carries the declared envelope and nothing besides."""
    body = response.json()
    assert_error_envelope(body)
    data = validate_error(response, error_id, expected_status)
    assert set(data.keys()) == {"error_id", "message"}, (
        f"an error payload carries only the identifier and the message, got {data!r}"
    )
    assert isinstance(data["message"], str) and data["message"].strip(), (
        "the message must be a non-empty human-readable string"
    )
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"an error meta carries only the two request fields, got {meta!r}"
    )
    assert meta["api_request_id"].startswith("req_")
    assert_millisecond_timestamp(meta["api_request_timestamp"])
    return data


def test_a_franchise_code_collision_answers_with_the_envelope_and_no_dealer(
    api, admin_headers
):
    """A duplicate franchise code is refused without echoing a partial dealer.

    PRD §3.2: "The `franchise_code` must be non-empty and unique across all
    dealers — a duplicate is `ERR_DUPLICATE_RESOURCE`"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_carries_error_id_and_message
    """
    taken = unique_franchise_code()
    enrolled = create_dealer(api, admin_headers, franchise_code=taken)
    assert enrolled["franchise_code"] == taken

    collision = api.create_dealer(
        create_dealer_payload(
            name="Copycat Motors", franchise_code=taken, region_code="SOUTH"
        ),
        admin_headers,
    )
    data = _only_the_error_envelope(collision, ApiErrorId.ERR_DUPLICATE_RESOURCE, 409)
    assert "id" not in data, "a refused enrolment mints no identifier"
    assert "franchise_code" not in data


def test_an_unknown_vehicle_identifier_answers_with_the_envelope(api, admin_headers):
    """A path identifier that names no vehicle produces the typed not-found error.

    PRD §2.11: "the request is rejected at the first identifier that does not
    name an existing row"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/errors/error_envelope_carries_error_id_and_message
    """
    missing = api.get_vehicle(NON_EXISTENT_UUID, admin_headers)
    _only_the_error_envelope(missing, ApiErrorId.ERR_VEHICLE_NOT_FOUND, 404)


def test_a_missing_required_field_answers_with_the_envelope(api, admin_headers):
    """A template posted without its effective date is a plain schema violation.

    PRD §3.1: "an `effective_from` date given as `YYYY-MM-DD`, the date from
    which the published template may back inspections"
    PRD §2.10: "Schema validity of the request body and query parameters:
    required fields present, enum members recognised, numbers in range"
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format"

    Design: Corner/errors/error_envelope_carries_error_id_and_message
    """
    incomplete = api.create_checklist_template(
        create_template_payload(code=unique_template_code(), effective_from=None),
        admin_headers,
    )
    _only_the_error_envelope(incomplete, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_every_refusal_shares_one_envelope_regardless_of_what_failed(api):
    """Three unrelated failures are indistinguishable apart from their identifier.

    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format"
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_carries_error_id_and_message
    """
    taken = unique_franchise_code()
    create_dealer(api, ADMIN, franchise_code=taken)
    refusals = (
        (
            api.create_dealer(
                create_dealer_payload(name="Copycat Motors", franchise_code=taken),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_RESOURCE,
            409,
        ),
        (
            api.get_vehicle(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_VEHICLE_NOT_FOUND,
            404,
        ),
        (
            api.create_checklist_template(
                create_template_payload(
                    code=unique_template_code(), effective_from=None
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        ),
    )
    identifiers = []
    for response, error_id, status in refusals:
        body = response.json()
        assert body["response_type"] == "error"
        assert set(body.keys()) == {"response_type", "data", "meta"}, (
            f"an error body carries exactly three keys, got {sorted(body)}"
        )
        for pagination_field in ("limit", "offset", "total_count", "has_more"):
            assert pagination_field not in body["meta"], (
                f"{pagination_field} belongs to collections, not to refusals"
            )
        identifiers.append(_only_the_error_envelope(response, error_id, status)["error_id"])
    assert len(set(identifiers)) == 3, (
        "each distinct failure names its own identifier inside the shared envelope"
    )
