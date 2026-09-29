"""Entity-shape behaviour: created fields, defaults, computed columns and lookups.

Every assertion in this module is derived from the PRD narrative alone. State is
built through the declared HTTP surface only, because the server is restarted
with an empty database before each test.
"""

from datetime import datetime

import pytest

from test_helpers import (
    CANONICAL_CLOCK,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_CHANGE_REQUEST_NOT_FOUND,
    ERR_DATA_BATCH_NOT_FOUND,
    ERR_DEMONSTRATION_NOT_FOUND,
    ERR_DESIGN_VALUE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALIDATION_NOT_FOUND,
    ERR_MONITOR_NOT_FOUND,
    ERR_NETWORK_NOT_FOUND,
    ERR_PACKAGE_NOT_FOUND,
    ERR_POLLUTANT_NOT_FOUND,
    ERR_REFERENCE_METHOD_NOT_FOUND,
    ERR_SITE_NOT_FOUND,
    NON_EXISTENT_UUID,
    approve_monitor,
    assert_hour_budget_conserved,
    assert_immutable_record,
    assert_pct,
    assert_site_census_partitioned,
    assert_siting_codes,
    assert_versioned_record,
    commission_monitor,
    create_network,
    create_pollutant,
    create_reference_method,
    data_batch_payload,
    demonstration_payload,
    exclusion_payload,
    find_by_id,
    get_success_data,
    monitor_payload,
    pollutant_payload,
    set_clock,
    site_payload,
    validate_error,
    validate_paginated,
    validate_success,
    zero_check_payload,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable moment in time."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_create_pollutant_returns_every_declared_field(api, admin_headers):
    """Registering a pollutant echoes all seven inputs and carries no revision counter.

    PRD §4: "Creation endpoints — those that mint a new resource — return HTTP 201 with the created resource in `data`."
    PRD §2.4: "Both therefore carry only `id` and `created_at`: neither `updated_at` nor `version` exists on a pollutant, and neither `updated_at` nor `version` exists on a quality-control event."

    Design: Corner/entities/create_pollutant_returns_every_declared_field
    """
    set_clock(api, CANONICAL_CLOCK)

    response = api.create_pollutant(pollutant_payload(), admin_headers)
    data = validate_success(response, expected_status=201)

    assert data["code"] == "PM25"
    assert data["standard_form"] == "ANNUAL_MEAN"
    assert data["averaging_period_hours"] == 24
    assert data["primary_standard_value"] == pytest.approx(9.0, abs=0.01)
    assert data["design_value_years"] == 3
    assert data["completeness_threshold_pct"] == pytest.approx(75.0, abs=0.01)
    assert data["rounding_decimals"] == 1

    assert_immutable_record(data)

    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_get_pollutant_by_id_returns_the_stored_row(api, admin_headers, qa_headers):
    """A read of one pollutant returns exactly what registration persisted.

    PRD §4: "Every other successful call returns HTTP 200, with the modified resource in `data` for mutations, the requested resource or page of resources for reads, and an empty object for the clock-setting capability."
    PRD §3.1: "Any operator in any of the five roles may read a single pollutant, read a single method, or list the methods designated for a pollutant."

    Design: Corner/entities/get_pollutant_by_id_returns_the_stored_row
    """
    set_clock(api, CANONICAL_CLOCK)
    created = validate_success(
        api.create_pollutant(pollutant_payload(), admin_headers), expected_status=201
    )

    fetched = validate_success(api.get_pollutant(created["id"], qa_headers))

    assert fetched["id"] == created["id"]
    assert fetched["code"] == "PM25"
    assert fetched["primary_standard_value"] == pytest.approx(9.0, abs=0.01)
    assert fetched["completeness_threshold_pct"] == pytest.approx(75.0, abs=0.01)
    assert fetched["rounding_decimals"] == 1
    assert fetched["averaging_period_hours"] == 24
    assert fetched["standard_form"] == "ANNUAL_MEAN"
    assert fetched["design_value_years"] == 3


def test_list_reference_methods_for_a_pollutant_paginates_and_filters(
    api, admin_headers, epa_headers, pm_headers
):
    """A pollutant's method list reports the pre-window total and honours the standing filter.

    PRD §2.3: "For list responses, the `meta` object carries `limit` and `offset` as applied, `total_count` as the number of rows matching the filter before the page window is taken, and `has_more` as a boolean that is true when rows remain beyond the current window."
    PRD §3.1: "That listing returns methods in any standing and accepts an optional `designation_status` filter along with the usual `limit` and `offset`."
    PRD §3.1: "A change to `WITHDRAWN` additionally sets `withdrawn_on` to the logical-clock instant; a change to any other status leaves `withdrawn_on` null."

    Design: Corner/entities/list_reference_methods_for_a_pollutant_paginates_and_filters
    """
    set_clock(api, CANONICAL_CLOCK)
    pollutant = create_pollutant(api)
    first = create_reference_method(api, pollutant["id"])
    second = create_reference_method(
        api,
        pollutant["id"],
        method_code="RFPS-0617-002",
        designation_type="FEM",
        effective_from="2021-01-01T00:00:00Z",
        max_span_drift_pct=6.0,
        zero_drift_limit=2.0,
    )
    get_success_data(
        api.change_designation(
            second["id"],
            {
                "new_designation_status": "WITHDRAWN",
                "determination_note": "Superseded by a later method",
            },
            epa_headers,
        )
    )

    page_response = api.list_pollutant_reference_methods(
        pollutant["id"], pm_headers, params={"limit": 1, "offset": 0}
    )
    rows, meta = validate_paginated(page_response)
    assert page_response.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    filtered_rows, filtered_meta = validate_paginated(
        api.list_pollutant_reference_methods(
            pollutant["id"],
            pm_headers,
            params={"designation_status": "WITHDRAWN", "limit": 10, "offset": 0},
        )
    )
    assert len(filtered_rows) == 1
    assert filtered_rows[0]["id"] == second["id"]
    assert filtered_rows[0]["id"] != first["id"]
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert filtered_rows[0]["designation_status"] == "WITHDRAWN"
    assert _instant(filtered_rows[0]["withdrawn_on"]) == _instant(CANONICAL_CLOCK)


def test_unknown_path_ids_return_entity_specific_not_found_errors(
    api, admin_headers, qa_headers
):
    """Each resource family answers an unresolvable path identifier with its own code.

    PRD §2.6: "The full set of path-resolution failures is `ERR_POLLUTANT_NOT_FOUND`, `ERR_REFERENCE_METHOD_NOT_FOUND`, `ERR_NETWORK_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_MONITOR_NOT_FOUND`, `ERR_DATA_BATCH_NOT_FOUND`, `ERR_INVALIDATION_NOT_FOUND`, `ERR_DEMONSTRATION_NOT_FOUND`, `ERR_DESIGN_VALUE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND` and `ERR_PACKAGE_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found_errors
    """
    set_clock(api, CANONICAL_CLOCK)

    cases = [
        (ERR_POLLUTANT_NOT_FOUND, lambda: api.get_pollutant(NON_EXISTENT_UUID, admin_headers)),
        (
            ERR_REFERENCE_METHOD_NOT_FOUND,
            lambda: api.get_reference_method(NON_EXISTENT_UUID, admin_headers),
        ),
        (ERR_NETWORK_NOT_FOUND, lambda: api.get_network(NON_EXISTENT_UUID, admin_headers)),
        (ERR_SITE_NOT_FOUND, lambda: api.get_site(NON_EXISTENT_UUID, admin_headers)),
        (ERR_MONITOR_NOT_FOUND, lambda: api.get_monitor(NON_EXISTENT_UUID, admin_headers)),
        (ERR_DATA_BATCH_NOT_FOUND, lambda: api.get_data_batch(NON_EXISTENT_UUID, admin_headers)),
        (
            ERR_INVALIDATION_NOT_FOUND,
            lambda: api.withdraw_invalidation(
                NON_EXISTENT_UUID, {"withdrawn_reason": "no such row"}, qa_headers
            ),
        ),
        (
            ERR_DEMONSTRATION_NOT_FOUND,
            lambda: api.get_demonstration(NON_EXISTENT_UUID, admin_headers),
        ),
        (
            ERR_DESIGN_VALUE_NOT_FOUND,
            lambda: api.get_design_value(NON_EXISTENT_UUID, admin_headers),
        ),
        (ERR_ASSESSMENT_NOT_FOUND, lambda: api.get_assessment(NON_EXISTENT_UUID, admin_headers)),
        (
            ERR_CHANGE_REQUEST_NOT_FOUND,
            lambda: api.get_change_request(NON_EXISTENT_UUID, admin_headers),
        ),
        (ERR_PACKAGE_NOT_FOUND, lambda: api.get_package(NON_EXISTENT_UUID, admin_headers)),
    ]

    seen = []
    for expected_error_id, call in cases:
        response = call()
        error_data = validate_error(response, expected_error_id, expected_status=404)
        assert response.json()["response_type"] == "error"
        assert "id" not in error_data
        seen.append(error_data["error_id"])

    assert len(set(seen)) == 12


def test_unknown_body_foreign_keys_return_entity_specific_not_found_errors(
    api, monitor_env, admin_headers, qa_headers, pm_headers
):
    """Body references resolve in declared field order, each raising its own code.

    PRD §2.6: "References supplied inside a request body are resolved the same way, in the order the endpoint declares its input fields, and they raise the same not-found codes: `ERR_POLLUTANT_NOT_FOUND`, `ERR_REFERENCE_METHOD_NOT_FOUND`, `ERR_NETWORK_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_MONITOR_NOT_FOUND`, `ERR_DATA_BATCH_NOT_FOUND` and `ERR_ASSESSMENT_NOT_FOUND`."
    PRD §3.3: "The installation names `site_id` for the site it is bolted to and `reference_method_id` for the designated method it implements, and carries `poc`, the parameter occurrence code that distinguishes co-located instruments measuring the same pollutant at one site."

    Design: Corner/entities/unknown_body_foreign_keys_return_entity_specific_not_found_errors
    """
    env = monitor_env

    both_unknown = api.create_monitor(
        monitor_payload(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            poc=2,
            is_primary_for_design_value=False,
            installed_at="2025-01-01T00:00:00Z",
        ),
        admin_headers,
    )
    validate_error(both_unknown, ERR_SITE_NOT_FOUND, expected_status=404)

    unknown_method = api.create_monitor(
        monitor_payload(
            env.site_id,
            NON_EXISTENT_UUID,
            poc=2,
            is_primary_for_design_value=False,
            installed_at="2025-01-01T00:00:00Z",
        ),
        admin_headers,
    )
    validate_error(unknown_method, ERR_REFERENCE_METHOD_NOT_FOUND, expected_status=404)

    unknown_network = api.create_site(
        site_payload(
            NON_EXISTENT_UUID,
            site_code="S-777",
            site_type="BACKGROUND",
            latitude=39.9,
            longitude=-105.1,
            population_served=0,
            distance_to_roadway_m=150.0,
        ),
        admin_headers,
    )
    validate_error(unknown_network, ERR_NETWORK_NOT_FOUND, expected_status=404)

    unknown_monitor = api.create_data_batch(
        data_batch_payload(NON_EXISTENT_UUID, 2025, 1), qa_headers
    )
    validate_error(unknown_monitor, ERR_MONITOR_NOT_FOUND, expected_status=404)

    unknown_assessment = api.create_change_request(
        {
            "site_id": env.site_id,
            "request_type": "SHUTDOWN",
            "justification": "Lease ended",
            "assessment_id": NON_EXISTENT_UUID,
        },
        pm_headers,
    )
    validate_error(unknown_assessment, ERR_ASSESSMENT_NOT_FOUND, expected_status=404)

    unknown_pollutant = api.create_package(
        {"network_id": env.network_id, "pollutant_id": NON_EXISTENT_UUID, "year": 2025},
        pm_headers,
    )
    validate_error(unknown_pollutant, ERR_POLLUTANT_NOT_FOUND, expected_status=404)

    monitors, monitor_meta = validate_paginated(
        api.list_monitors(pm_headers, params={"site_id": env.site_id, "limit": 100, "offset": 0})
    )
    assert monitor_meta["total_count"] == 1
    assert monitors[0]["id"] == env.monitor_id

    _sites, site_meta = validate_paginated(
        api.list_sites(pm_headers, params={"network_id": env.network_id, "limit": 100, "offset": 0})
    )
    assert site_meta["total_count"] == 1

    _batches, batch_meta = validate_paginated(
        api.list_data_batches(pm_headers, params={"limit": 100, "offset": 0})
    )
    assert batch_meta["total_count"] == 0

    _requests, request_meta = validate_paginated(
        api.list_change_requests(pm_headers, params={"limit": 100, "offset": 0})
    )
    assert request_meta["total_count"] == 0

    _packages, package_meta = validate_paginated(
        api.list_packages(pm_headers, params={"limit": 100, "offset": 0})
    )
    assert package_meta["total_count"] == 0


def test_omitting_a_required_pollutant_field_returns_invalid_request(api, admin_headers):
    """A registration missing the standard level is structurally invalid and persists nothing.

    PRD §2.11: "Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_UNAUTHORIZED`), then structural validity of the request body and pagination parameters (`ERR_INVALID_REQUEST`), then resolution of path identifiers left to right, then resolution of body references in declared field order."
    PRD §3.1: "`primary_standard_value` carries the numeric level of the standard in the pollutant's own reporting units and must be greater than zero."

    Design: Corner/entities/omitting_a_required_pollutant_field_returns_invalid_request
    """
    set_clock(api, CANONICAL_CLOCK)

    response = api.create_pollutant(
        {"code": "PM25", "averaging_period_hours": 24, "standard_form": "ANNUAL_MEAN"},
        admin_headers,
    )
    validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

    # No catalogue entry was persisted, so the same code is still free to register.
    retry = api.create_pollutant(pollutant_payload(), admin_headers)
    validate_success(retry, expected_status=201)


def test_omitted_optional_inputs_take_their_declared_defaults(api, base_env, admin_headers):
    """Omitted optional inputs land on the exact defaults the narrative states.

    PRD §3.1: "`design_value_years` is the number of consecutive calendar years averaged into a design value; it defaults to 3, and every pollutant in this system uses exactly 3."
    PRD §3.1: "`completeness_threshold_pct` is the minimum rounded quarterly completeness a quarter must reach before it may be used for regulatory purposes; it defaults to 75.0 and must be greater than 0 and no more than 100."
    PRD §3.1: "`rounding_decimals` is the number of decimal places used both for annual-statistic rounding and for design-value truncation; it defaults to 1 and must be at least 0 and at most 3."
    PRD §3.3: "The operator also supplies `installed_at`, the instant the instrument was physically installed, and may set `is_primary_for_design_value`, which defaults to false and is the operator's nomination of this instrument as the site's primary sampler for design-value work."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    env = base_env

    pm10 = validate_success(
        api.create_pollutant(
            {
                "code": "PM10",
                "averaging_period_hours": 24,
                "standard_form": "PERCENTILE_98",
                "primary_standard_value": 150.0,
            },
            admin_headers,
        ),
        expected_status=201,
    )
    assert pm10["design_value_years"] == 3
    assert pm10["completeness_threshold_pct"] == pytest.approx(75.0, abs=0.01)
    assert pm10["rounding_decimals"] == 1

    site_body = site_payload(env.network_id, site_code="S-002")
    del site_body["distance_to_source_m"]
    site = validate_success(api.create_site(site_body, admin_headers), expected_status=201)
    assert site["distance_to_source_m"] == pytest.approx(0.0, abs=0.01)
    assert_siting_codes(site, [])

    monitor_body = monitor_payload(site["id"], env.method_id, installed_at="2025-06-01T00:00:00Z")
    del monitor_body["is_primary_for_design_value"]
    monitor = validate_success(
        api.create_monitor(monitor_body, admin_headers), expected_status=201
    )
    assert monitor["is_primary_for_design_value"] is False


def test_data_batch_computed_hour_fields_are_populated_at_creation(api, monitor_env, qa_headers):
    """A clean 2160-hour quarter is fully complete and eligible in the creation response itself.

    PRD §3.4: "Sixth, `completeness_pct` is `valid_hour_count` divided by `adjusted_scheduled_hour_count`, multiplied by 100 and rounded to one decimal place, except that when `adjusted_scheduled_hour_count` is zero the value is 0.0 rather than an error."
    PRD §3.4: "Seventh, `regulatory_use_eligible` is true exactly when that *rounded* `completeness_pct` is greater than or equal to the pollutant's `completeness_threshold_pct`; the comparison is inclusive at the threshold, and it uses the rounded figure and never the raw ratio."
    PRD §3.4: "A quarter is born with `validation_status` `RAW` and `submission_status` `UNSUBMITTED`, with `reopen_count` at 0 and `invalidation_applied_by_user_ids` an empty list."

    Design: Corner/entities/data_batch_computed_hour_fields_are_populated_at_creation
    """
    env = monitor_env

    batch = validate_success(
        api.create_data_batch(data_batch_payload(env.monitor_id, 2025, 1), qa_headers),
        expected_status=201,
    )

    assert batch["scheduled_hour_count"] == 2160
    assert batch["excused_hour_count"] == 0
    assert batch["invalidated_hour_count"] == 0
    assert batch["event_excluded_hour_count"] == 0
    assert batch["adjusted_scheduled_hour_count"] == 2160
    assert batch["valid_hour_count"] == 2160
    assert_pct(batch["completeness_pct"], 100.0)
    assert batch["regulatory_use_eligible"] is True
    assert batch["validation_status"] == "RAW"
    assert batch["submission_status"] == "UNSUBMITTED"
    assert batch["reopen_count"] == 0
    assert batch["invalidation_applied_by_user_ids"] == []
    assert_hour_budget_conserved(batch)


def test_monitoring_site_system_fields_are_server_assigned_at_creation(
    api, admin_headers, pm_headers
):
    """Proposing a site assigns its lifecycle, revision and census fields without being asked.

    PRD §3.2: "A proposed site enters `status` `PROPOSED` with `siting_waiver_granted` false, and the network's `total_site_count`, `proposed_site_count` and `waiver_required_site_count` are recomputed."
    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."
    PRD §3.2: "A site that arrived at its position through a relocation carries `replaces_site_id` pointing at the site it took over from; the field is null on every site that has not replaced another."

    Design: Corner/entities/monitoring_site_system_fields_are_server_assigned_at_creation
    """
    set_clock(api, CANONICAL_CLOCK)
    network = create_network(api)

    site = validate_success(
        api.create_site(site_payload(network["id"]), admin_headers), expected_status=201
    )

    assert_versioned_record(site)
    assert site["status"] == "PROPOSED"
    assert site["version"] == 1
    assert site["siting_waiver_granted"] is False
    assert site["siting_waiver_required"] is False
    assert site["siting_violation_codes"] == []
    assert site["operations_start_at"] is None
    assert site["suspended_at"] is None
    assert site["replaces_site_id"] is None
    assert site["operating_monitor_count"] == 0
    assert site["current_attainment_status"] == "UNDETERMINED"

    census = validate_success(api.get_network(network["id"], pm_headers))
    assert census["total_site_count"] == 1
    assert census["proposed_site_count"] == 1
    assert census["operating_site_count"] == 0
    assert census["waiver_required_site_count"] == 0
    assert_site_census_partitioned(census)


def test_invalid_enum_and_out_of_range_numeric_inputs_are_rejected(
    api, monitor_env, admin_headers, qa_headers, pm_headers
):
    """Off-enum and out-of-band values are structural failures that write nothing.

    PRD §2.11: "Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_UNAUTHORIZED`), then structural validity of the request body and pagination parameters (`ERR_INVALID_REQUEST`), then resolution of path identifiers left to right, then resolution of body references in declared field order."
    PRD §3.2: "Location is given as `latitude` in decimal degrees north, between -90 and 90 inclusive, and `longitude` in decimal degrees east, between -180 and 180 inclusive."
    PRD §3.3: "A `poc` must be at least 1 and at most 9, and the triple of the site, the pollutant reached through the instrument's method, and the `poc` must be unique among instruments that are not decommissioned — a decommissioned instrument frees its code for reuse."
    PRD §3.4: "`scheduled_hour_count` records how many sampling hours were scheduled for the quarter and must be at least 1 and at most 2232; it is the denominator before any hours are removed."
    PRD §2.3: "A `limit` outside the 1-to-100 band, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/invalid_enum_and_out_of_range_numeric_inputs_are_rejected
    """
    env = monitor_env

    off_enum_code = api.create_pollutant(
        {
            "code": "PM1",
            "averaging_period_hours": 24,
            "standard_form": "ANNUAL_MEAN",
            "primary_standard_value": 9.0,
        },
        admin_headers,
    )
    validate_error(off_enum_code, ERR_INVALID_REQUEST, expected_status=400)

    bad_latitude = api.create_site(
        site_payload(
            env.network_id,
            site_code="S-003",
            site_type="BACKGROUND",
            latitude=95.0,
            longitude=-105.1,
            population_served=0,
            distance_to_roadway_m=150.0,
        ),
        admin_headers,
    )
    validate_error(bad_latitude, ERR_INVALID_REQUEST, expected_status=400)

    bad_poc = api.create_monitor(
        monitor_payload(
            env.site_id,
            env.method_id,
            poc=12,
            is_primary_for_design_value=False,
            installed_at="2025-01-01T00:00:00Z",
        ),
        admin_headers,
    )
    validate_error(bad_poc, ERR_INVALID_REQUEST, expected_status=400)

    bad_hour_count = api.create_data_batch(
        data_batch_payload(env.monitor_id, 2025, 1, scheduled_hour_count=2400), qa_headers
    )
    validate_error(bad_hour_count, ERR_INVALID_REQUEST, expected_status=400)

    bad_limit = api.list_sites(
        admin_headers, params={"network_id": env.network_id, "limit": 500, "offset": 0}
    )
    validate_error(bad_limit, ERR_INVALID_REQUEST, expected_status=400)

    _sites, site_meta = validate_paginated(
        api.list_sites(pm_headers, params={"network_id": env.network_id, "limit": 100, "offset": 0})
    )
    assert site_meta["total_count"] == 1

    _monitors, monitor_meta = validate_paginated(
        api.list_monitors(pm_headers, params={"site_id": env.site_id, "limit": 100, "offset": 0})
    )
    assert monitor_meta["total_count"] == 1

    _batches, batch_meta = validate_paginated(
        api.list_data_batches(pm_headers, params={"limit": 100, "offset": 0})
    )
    assert batch_meta["total_count"] == 0


def test_qc_event_is_immutable_and_exposes_no_version_field(
    api, monitor_env, tech_headers, qa_headers, pm_headers
):
    """A second activity leaves the first event row untouched and neither row carries a revision counter.

    PRD §3.3: "Because the event row is immutable, it carries only an identifier and a creation timestamp, with no revision counter."
    PRD §3.3: "For a zero check the identical banding applies to the absolute value of `zero_drift_value`, rounded to two decimal places, against the method's `zero_drift_limit`."
    PRD §3.3: "An instrument's quality-control history is listed most recent `performed_at` first, with optional filters on `event_type` and on `outcome`."

    Design: Corner/entities/qc_event_is_immutable_and_exposes_no_version_field
    """
    env = monitor_env

    validate_success(
        api.create_qc_event(
            env.monitor_id,
            zero_check_payload(performed_at="2026-01-04T00:00:00Z", zero_drift_value=0.4),
            tech_headers,
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_monitor_qc_events(env.monitor_id, qa_headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2

    span_rows = [row for row in rows if row["event_type"] == "SPAN_CHECK"]
    zero_rows = [row for row in rows if row["event_type"] == "ZERO_CHECK"]
    assert len(span_rows) == 1
    assert len(zero_rows) == 1

    span = span_rows[0]
    assert _instant(span["performed_at"]) == _instant("2026-01-02T00:00:00Z")
    assert span["span_drift_pct"] == pytest.approx(2.0, abs=0.01)
    assert span["outcome"] == "PASS"
    assert zero_rows[0]["outcome"] == "PASS"

    for row in rows:
        assert_immutable_record(row)

    monitor = validate_success(api.get_monitor(env.monitor_id, pm_headers))
    assert _instant(monitor["last_zero_check_at"]) == _instant("2026-01-04T00:00:00Z")
    assert _instant(monitor["last_span_check_at"]) == _instant("2026-01-02T00:00:00Z")


def test_event_exclusion_junction_links_one_demonstration_to_two_monitor_quarters(
    api, monitor_env, admin_headers, qa_headers, pm_headers
):
    """One demonstration carries a nomination against each of two co-located quarters.

    PRD §3.6: "An accepted nomination is created with `status` `PROPOSED`, `hours_affected` set to `end_hour_index` less `start_hour_index`, and `effective_at` null."
    PRD §3.6: "Crucially, nothing else moves: the demonstration's `excluded_hour_total` is unchanged because only effective exclusions count toward it, and the target quarter's hour accounting is unchanged for exactly the same reason."
    PRD §3.6: "A demonstration's own exclusions are listed ordered by `data_batch_id` and then `start_hour_index`, filterable by `status` and by `data_batch_id`."

    Design: Corner/entities/event_exclusion_junction_links_one_demonstration_to_two_monitor_quarters
    """
    env = monitor_env

    second_monitor = validate_success(
        api.create_monitor(
            monitor_payload(
                env.site_id,
                env.method_id,
                poc=2,
                is_primary_for_design_value=False,
                installed_at="2022-12-20T00:00:00Z",
            ),
            admin_headers,
        ),
        expected_status=201,
    )
    approve_monitor(api, second_monitor["id"])
    commission_monitor(api, second_monitor["id"])

    batch_a = validate_success(
        api.create_data_batch(
            data_batch_payload(
                env.monitor_id,
                2024,
                3,
                scheduled_hour_count=2208,
                quarterly_mean_concentration=9.2,
                quarterly_mean_concentration_event_adjusted=7.9,
            ),
            qa_headers,
        ),
        expected_status=201,
    )
    batch_b = validate_success(
        api.create_data_batch(
            data_batch_payload(
                second_monitor["id"],
                2024,
                3,
                scheduled_hour_count=2208,
                quarterly_mean_concentration=9.4,
                quarterly_mean_concentration_event_adjusted=8.1,
            ),
            qa_headers,
        ),
        expected_status=201,
    )

    demonstration = validate_success(
        api.create_demonstration(
            demonstration_payload(env.site_id, env.pollutant_id), pm_headers
        ),
        expected_status=201,
    )

    exclusion_a = validate_success(
        api.create_exclusion(
            demonstration["id"], exclusion_payload(batch_a["id"], 1008, 1200), pm_headers
        ),
        expected_status=201,
    )
    exclusion_b = validate_success(
        api.create_exclusion(
            demonstration["id"], exclusion_payload(batch_b["id"], 1008, 1200), pm_headers
        ),
        expected_status=201,
    )

    assert exclusion_a["hours_affected"] == 192
    assert exclusion_b["hours_affected"] == 192
    for exclusion in (exclusion_a, exclusion_b):
        assert exclusion["status"] == "PROPOSED"
        assert exclusion["effective_at"] is None
        assert exclusion["demonstration_id"] == demonstration["id"]

    demo_rows, demo_meta = validate_paginated(
        api.list_demonstration_exclusions(
            demonstration["id"], pm_headers, params={"limit": 100, "offset": 0}
        )
    )
    assert demo_meta["total_count"] == 2
    assert find_by_id(demo_rows, exclusion_a["id"]) is not None
    assert find_by_id(demo_rows, exclusion_b["id"]) is not None

    rows_a, meta_a = validate_paginated(
        api.list_batch_exclusions(batch_a["id"], pm_headers, params={"limit": 100, "offset": 0})
    )
    assert meta_a["total_count"] == 1
    assert rows_a[0]["id"] == exclusion_a["id"]

    rows_b, meta_b = validate_paginated(
        api.list_batch_exclusions(batch_b["id"], pm_headers, params={"limit": 100, "offset": 0})
    )
    assert meta_b["total_count"] == 1
    assert rows_b[0]["id"] == exclusion_b["id"]

    refreshed = validate_success(api.get_demonstration(demonstration["id"], pm_headers))
    assert refreshed["excluded_hour_total"] == 0
