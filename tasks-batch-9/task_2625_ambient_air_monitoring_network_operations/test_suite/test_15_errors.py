"""Rejection contracts: the error envelope, pagination bounds and terminal states.

Each test drives a real rejection through the HTTP surface and then reads the
affected rows back to prove the refusal left no partial write behind.
"""

from test_helpers import (
    ADMIN_HEADERS,
    EPA_HEADERS,
    NON_EXISTENT_UUID,
    PM_HEADERS,
    QA_HEADERS,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_POLLUTANT_NOT_FOUND,
    assert_hour_budget_conserved,
    assert_meta_envelope,
    assert_pct,
    canonical_environment,
    data_batch_payload,
    demonstration_payload,
    exclusion_payload,
    find_by_id,
    get_success_data,
    operating_site_environment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-01-05T00:00:00Z"


def assert_error_body(response, error_id, status):
    """Assert the full rejection envelope, not merely the identifier."""
    error_data = validate_error(response, error_id, status)
    body = response.json()
    assert body["response_type"] == "error", body["response_type"]
    assert_meta_envelope(body)
    assert set(error_data.keys()) == {"error_id", "message"}, sorted(error_data)
    assert error_data["message"].strip() != ""
    return error_data


def assert_instant(actual, expected):
    """Compare a server instant against an expected UTC instant."""
    assert type(actual) is str, f"expected an instant string, got {actual!r}"
    assert actual.endswith("Z"), f"expected a UTC instant, got {actual!r}"
    assert actual[:19] == expected[:19], f"expected {expected}, got {actual}"


def test_every_error_response_uses_the_declared_error_envelope(api):
    """A 404 and a 400 both arrive in the declared rejection envelope.

    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/every_error_response_uses_the_declared_error_envelope
    """
    set_clock(api, CLOCK)

    not_found = assert_error_body(
        api.get_pollutant(NON_EXISTENT_UUID, PM_HEADERS), ERR_POLLUTANT_NOT_FOUND, 404
    )
    assert not_found["error_id"] == "ERR_POLLUTANT_NOT_FOUND"

    malformed = assert_error_body(
        api.create_pollutant(
            {
                "code": "PM25",
                "averaging_period_hours": 24,
                "standard_form": "NOT_A_FORM",
                "primary_standard_value": 9.0,
            },
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    assert "id" not in malformed
    assert malformed["error_id"] == "ERR_INVALID_REQUEST"


def test_pagination_arguments_outside_the_declared_bounds_return_invalid_request(api):
    """The page-size band is one to a hundred and the offset may not be negative.

    PRD 2.3: "`limit` controls page size: it defaults to 10, may be no smaller than 1 and no larger than 100."
    PRD 2.3: "A `limit` outside the 1-to-100 band, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/pagination_arguments_outside_the_declared_bounds_return_invalid_request
    """
    env = operating_site_environment(api)

    for params in (
        {"network_id": env.network_id, "limit": 0},
        {"network_id": env.network_id, "limit": 101},
        {"network_id": env.network_id, "offset": -1},
    ):
        assert_error_body(api.list_sites(PM_HEADERS, params), ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_sites(PM_HEADERS, {"network_id": env.network_id, "limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert rows[0]["id"] == env.site_id


def test_a_non_concurred_demonstration_is_terminal_and_its_exclusions_are_rejected(api):
    """A refused demonstration ends the workflow and deducts no hours.

    PRD 3.6: "A non-concurrence advances `SUBMITTED → NON_CONCURRED` and stops far earlier."
    PRD 3.6: "Every exclusion under the demonstration whose `status` is `PROPOSED` moves to `REJECTED` with its `version` incremented, and `effective_at` stays null."
    PRD 3.6: "Both branches advance out of `SUBMITTED`, both stamp `determined_by_user_id` from the calling `X-User-ID` and `determined_at` from the logical clock, both increment the demonstration's `version`, and both are terminal: `CONCURRED` and `NON_CONCURRED` admit no further transition, and a second determination is rejected with `ERR_ALREADY_TERMINAL`."

    Design: Corner/errors/a_non_concurred_demonstration_is_terminal_and_its_exclusions_are_rejected
    """
    env = canonical_environment(api)
    batch = validate_success(
        api.create_data_batch(data_batch_payload(env.monitor_id, 2025, 1), QA_HEADERS), 201
    )

    demonstration = validate_success(
        api.create_demonstration(
            demonstration_payload(
                env.site_id,
                env.pollutant_id,
                event_type="HIGH_WIND_DUST",
                event_start_date="2025-01-01T00:00:00Z",
                event_end_date="2025-01-05T00:00:00Z",
                narrative="Regional dust storm with blowing soil",
            ),
            PM_HEADERS,
        ),
        201,
    )
    exclusion = validate_success(
        api.create_exclusion(
            demonstration["id"], exclusion_payload(batch["id"], 0, 120), PM_HEADERS
        ),
        201,
    )
    validate_success(
        api.submit_demonstration(
            demonstration["id"], {"submission_note": "Dust event demonstration"}, PM_HEADERS
        ),
        200,
    )
    determined = validate_success(
        api.decide_demonstration(
            demonstration["id"],
            {"determination": "NON_CONCUR", "determination_note": "Conceptual model unsupported"},
            EPA_HEADERS,
        ),
        200,
    )
    assert determined["status"] == "NON_CONCURRED"
    assert determined["determined_by_user_id"] == "epa-1"
    assert_instant(determined["determined_at"], CLOCK)
    assert determined["excluded_hour_total"] == 0

    rows, _ = validate_paginated(
        api.list_demonstration_exclusions(demonstration["id"], PM_HEADERS)
    )
    rejected = find_by_id(rows, exclusion["id"])
    assert rejected is not None
    assert rejected["status"] == "REJECTED"
    assert rejected["effective_at"] is None

    unchanged = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert unchanged["event_excluded_hour_count"] == 0
    assert unchanged["adjusted_scheduled_hour_count"] == 2160
    assert unchanged["valid_hour_count"] == 2160
    assert_pct(unchanged["completeness_pct"], 100.0)
    assert_hour_budget_conserved(unchanged)

    assert_error_body(
        api.request_demonstration_info(
            demonstration["id"],
            {"info_request_note": "Please supply the back-trajectory analysis"},
            EPA_HEADERS,
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    after = get_success_data(api.get_demonstration(demonstration["id"], PM_HEADERS))
    assert after["status"] == "NON_CONCURRED"
    assert after["info_request_count"] == 0
