"""Intake and asset-registry corner tests: defaults, required fields, enums,
404 envelope, and sub-resource pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_break_report,
    assert_pipe_segment,
    create_break,
    create_segment,
    create_valve,
    get_break,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import (
    confirm_break_report_payload,
    create_break_report_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def test_create_pipe_segment_applies_defaults(api):
    """PRD §3.1: "A new segment's `condition_status` starts at `NONE`, both of
    its repeat-break counters (`repeat_break_count_36mo` and
    `provisional_break_count_36mo`) start at 0, and `replaced_at` is null."

    Design: Corner/entities/create_pipe_segment_applies_defaults
    """
    resp = _api.create_pipe_segment(
        {
            "segment_ref": "MAIN-8-OAK",
            "material": "DUCTILE_IRON",
            "diameter_inches": 8,
            "install_year": 1978,
        },
        ENGINEER,
    )
    seg = validate_success(resp, 201)
    assert_pipe_segment(seg)
    assert seg["condition_status"] == "NONE", (
        f"expected condition_status NONE, got {seg['condition_status']!r}"
    )
    assert seg["repeat_break_count_36mo"] == 0
    assert seg["provisional_break_count_36mo"] == 0
    assert seg["replaced_at"] is None
    assert isinstance(seg["version"], int) and seg["version"] >= 1


def test_create_break_report_missing_required_returns_invalid_request(api):
    """PRD §3.2: "A break enters the system when a `Dispatcher` files a report
    with a free-text `location_description` and a `source` of `CUSTOMER_CALL`,
    `SENSOR_SCADA`, or `CREW_OBSERVATION`."
    PRD §2.5: "Malformed fields, invalid enum values, non-positive quantities
    where a positive value is required, and windows whose start is not before
    their end are rejected with `ERR_VALIDATION` (HTTP 400) at the same tier as
    existence checking."

    Design: Corner/entities/create_break_report_missing_required_returns_invalid_request
    """
    resp = _api.create_break_report(
        {"location_description": "12 Nowhere Ln"},  # source omitted
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_segment_computed_field_input_ignored(api):
    """PRD §3.1: "A new segment's `condition_status` starts at `NONE`, both of
    its repeat-break counters (`repeat_break_count_36mo` and
    `provisional_break_count_36mo`) start at 0, and `replaced_at` is null."

    Design: Corner/entities/create_segment_computed_field_input_ignored
    """
    resp = _api.create_pipe_segment(
        {
            "segment_ref": "MAIN-8-OAK",
            "material": "PVC",
            "diameter_inches": 8,
            "install_year": 1999,
            "condition_status": "CANDIDATE",  # system-owned; must be ignored
        },
        ENGINEER,
    )
    seg = validate_success(resp, 201)
    assert seg["condition_status"] == "NONE", (
        f"client-supplied condition_status must be ignored; got {seg['condition_status']!r}"
    )


def test_get_break_report_not_found_returns_404(api):
    """PRD §2.5: "When a request references a resource by id — whether in the
    URL path or in the request body — each referenced id must exist; the first
    missing reference is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_break_report_not_found_returns_404
    """
    resp = _api.get_break_report(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_valves_list_pagination_defaults(api):
    """PRD §2.3: "List endpoints accept two optional query parameters: `limit`
    and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. List responses are sorted by `created_at`
    ascending. The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more` in addition to the standard request metadata."

    Design: Corner/entities/valves_list_pagination_defaults
    """
    seg = create_segment(segment_ref="MAIN-8-OAK", material="PVC",
                         diameter_inches=8, install_year=1999)
    create_valve(seg["id"], "V-1", coverage_zone="Z1", customers_served=100)
    create_valve(seg["id"], "V-2", coverage_zone="Z2", customers_served=50)

    resp = _api.list_segment_valves(seg["id"], DISPATCHER, params={"limit": 1, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 1, f"limit=1 must return exactly 1 entry, got {len(page1)}"
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    resp2 = _api.list_segment_valves(seg["id"], DISPATCHER)
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 2, f"default limit 10 must return both valves, got {len(page2)}"
    assert meta2["limit"] == 10
    assert meta2["has_more"] is False


def test_confirm_rejects_invalid_enum(api):
    """PRD §3.2: "A `Dispatcher` confirms a `REPORTED` report by supplying the
    `pipe_segment_id` it occurred on, the `break_type` (`CIRCUMFERENTIAL`,
    `SPLIT`, or `BLOWOUT`), and the `severity` (`LOW`, `MEDIUM`, or `HIGH`)."
    PRD §2.5: "Malformed fields, invalid enum values, non-positive quantities
    where a positive value is required, and windows whose start is not before
    their end are rejected with `ERR_VALIDATION` (HTTP 400) at the same tier as
    existence checking."

    Design: Corner/entities/confirm_rejects_invalid_enum
    """
    seg = create_segment(segment_ref="MAIN-8-OAK", material="PVC",
                         diameter_inches=8, install_year=1999)
    br = create_break(location_description="12 Oak St", source="CUSTOMER_CALL")
    resp = _api.confirm_break_report(
        br["id"],
        confirm_break_report_payload(
            pipe_segment_id=seg["id"], break_type="CRACKED", severity="LOW"
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    after = get_break(br["id"])
    assert after["break_status"] == "REPORTED", (
        f"rejected confirm must leave the break REPORTED, got {after['break_status']!r}"
    )


def test_break_report_initial_state_reported(api):
    """PRD §3.2: "The report is born with `break_status` `REPORTED`, no assigned
    segment, no `break_type`, no `severity`, and both `confirmed_at` and
    `repaired_at` null."

    Design: Corner/state_machines/break_report_initial_state_reported
    """
    resp = _api.create_break_report(
        create_break_report_payload(
            location_description="12 Oak St", source="CUSTOMER_CALL"
        ),
        DISPATCHER,
    )
    br = validate_success(resp, 201)
    assert_break_report(br)
    assert br["break_status"] == "REPORTED"
    assert br["pipe_segment_id"] is None
    assert br["break_type"] is None
    assert br["severity"] is None
    assert br["confirmed_at"] is None
    assert br["repaired_at"] is None
    assert isinstance(br["version"], int) and br["version"] >= 1
