"""Response envelope shape, pagination contract, header presence, and 404 family."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_rehearsal_slot_payload,
    create_season_payload,
    is_iso8601_timestamp,
    make_faire_day,
    make_season,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_response_envelope_shapes(api, operator_headers, any_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."
    PRD §2.2: "The `data` field contains the resource object or an array of resource
    objects."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/response_envelope_shapes
    """
    res = api.create_season(create_season_payload(name="Envelope Revel"), operator_headers)
    season = validate_success(res, 201)
    body = res.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["id"] == season["id"]

    err_res = api.get_season(NON_EXISTENT_UUID, any_headers)
    error = validate_error(err_res, ApiErrorId.ERR_SEASON_NOT_FOUND, expected_status=404)
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert error["error_id"] == "ERR_SEASON_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_pagination_defaults_and_fields(api, any_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; when omitted it defaults to 10, and it accepts a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies how many items to skip and
    defaults to 0."
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/pagination_defaults_and_fields
    """
    season = make_season(name="Pages Revel")
    for day in range(6, 18):  # 2026-06-06 .. 2026-06-17 -> 12 faire days
        make_faire_day(season["id"], f"2026-06-{day:02d}T00:00:00Z")

    page1, meta1 = validate_paginated(
        api.list_faire_days(any_headers, params={"season_id": season["id"]})
    )
    assert len(page1) == 10
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_faire_days(any_headers, params={"season_id": season["id"], "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False


def test_missing_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming their operational capacity. A request
    in which either header is missing or empty is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.9: "the server evaluates them in a fixed nine-layer order, and the first
    failing layer determines the error returned" — header presence (layer 1) fires
    even though the path id is also unknown (layer 3).

    Design: Corner/validations/missing_headers_rejected
    """
    res = api.get_season(NON_EXISTENT_UUID, headers=None)
    validate_error(
        res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=400
    )


def test_body_fk_contract_not_found(api, cast_director_headers):
    """PRD §2.9: "Only after the path resolves are foreign keys in the request body —
    `season_id`, `faire_day_id`, `contract_id`, `application_id`, `performer_id`,
    `target_faire_day_id`, every entry of `depends_on_task_ids`, `linked_order_id`,
    and `linked_permit_id` — checked against the same 404 family."

    Design: Corner/validations/body_fk_contract_not_found
    """
    res = api.create_rehearsal_slot(
        create_rehearsal_slot_payload(NON_EXISTENT_UUID), cast_director_headers
    )
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_FOUND, expected_status=404)


def test_resource_not_found_sampling(api, any_headers):
    """PRD §2.9: "Resource identifiers in the path are validated left to right, and
    the first missing one produces its resource-specific 404: `ERR_SEASON_NOT_FOUND`,
    `ERR_FAIRE_DAY_NOT_FOUND`, `ERR_PERFORMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SLOT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_BOOTH_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, `ERR_RAIN_CHECK_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, or `ERR_TASK_NOT_FOUND`."

    Design: Corner/errors/resource_not_found_sampling
    """
    cases = [
        (api.get_faire_day, ApiErrorId.ERR_FAIRE_DAY_NOT_FOUND),
        (api.get_performer, ApiErrorId.ERR_PERFORMER_NOT_FOUND),
        (api.get_cast_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_rehearsal_slot, ApiErrorId.ERR_SLOT_NOT_FOUND),
        (api.get_vendor, ApiErrorId.ERR_VENDOR_NOT_FOUND),
        (api.get_vendor_application, ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api.get_booth_assignment, ApiErrorId.ERR_BOOTH_NOT_FOUND),
        (api.get_food_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (api.get_ticket_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_ticket, ApiErrorId.ERR_TICKET_NOT_FOUND),
        (api.get_rain_check, ApiErrorId.ERR_RAIN_CHECK_NOT_FOUND),
        (api.get_volunteer_shift, ApiErrorId.ERR_SHIFT_NOT_FOUND),
        (api.get_conduct_case, ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.get_build_task, ApiErrorId.ERR_TASK_NOT_FOUND),
    ]
    for getter, error_id in cases:
        res = getter(NON_EXISTENT_UUID, any_headers)
        validate_error(res, error_id, expected_status=404)
