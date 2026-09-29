"""Core entity behaviour: creation, retrieval, listing, defaults and rejections.

This module covers the foundational contract of the flat `/mmm` topology — what a
create call returns, what a read-back returns, how a list endpoint orders and
pages its rows, which identifiers produce which 404, which omissions and which
out-of-domain values produce a 400, and where a cross-market reference is refused
with a 422 even though both rows resolve.

Every test builds its own state from scratch: the harness relaunches the API
against an empty database before each individual test.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    NOT_FOUND_BY_COLLECTION,
    ApiClient,
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import test_users as users

# A syntactically valid UUID that no create call in this module ever mints.
_FAKE_ID = "00000000-0000-4000-8000-000000000000"


def _envelope(response: Any) -> Dict[str, Any]:
    """The whole decoded body, for the envelope members `validate_success` drops."""
    return response.json()


def test_market_creation_returns_declared_fields_and_zeroed_derived_state(
    api: ApiClient,
) -> None:
    """PRD 3.1: "A freshly registered market reports `celled_population` of 0, `held_out_population` of 0, `held_out_population_pct` of 0.00 and a `data_posture` of `RESTRICTED`, since it has neither a sealed window nor a published run."
    PRD 2.8: "A market also publishes two convenience projections alongside its posture: `published_model_run_id`, which resolves to the `id` of the single run of that market whose `publication_status` is `PUBLISHED` and is null when no such run exists, and the population aggregates described in §3.1."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and increments by one on every mutation of that row, including mutations caused indirectly by a cascade fired from another resource."
    PRD 2.4: "Creating a resource returns HTTP 201."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/market_creation_returns_declared_fields_and_zeroed_derived_state
    """
    fixtures.set_clock(api)

    response = api.create_market(
        {
            "market_code": "US_CORE",
            "name": "US Core Brand Market",
            "total_population": 10000000,
            "annual_budget_ceiling_cents": 5000000000,
            "currency_code": "USD",
        },
        users.DATA_ENGINEER,
    )
    market = validate_success(response, 201)

    body = _envelope(response)
    assert body["response_type"] == "object", body["response_type"]
    assertions.assert_request_meta(body["meta"])

    # The declared inputs come back unchanged.
    assert market["market_code"] == "US_CORE", market["market_code"]
    assert market["name"] == "US Core Brand Market", market["name"]
    assert market["total_population"] == 10000000, market["total_population"]
    assert market["annual_budget_ceiling_cents"] == 5000000000, market
    assert market["currency_code"] == "USD", market["currency_code"]

    # The derived state is materialised at its zero value, not left null.
    assert market["celled_population"] == 0, market["celled_population"]
    assert market["held_out_population"] == 0, market["held_out_population"]
    assert float(market["held_out_population_pct"]) == 0.00, market
    assertions.assert_percentage(
        market["held_out_population_pct"], "held_out_population_pct"
    )
    assert market["data_posture"] == "RESTRICTED", market["data_posture"]
    assert market["published_model_run_id"] is None, market["published_model_run_id"]

    # Identity, timestamps and the mutation counter.
    assert isinstance(market["id"], str) and market["id"], market["id"]
    assert is_valid_uuid(market["id"]), market["id"]
    assert market["version"] == 1, market["version"]
    assert is_iso8601_timestamp(market["created_at"]), market["created_at"]
    assert is_iso8601_timestamp(market["updated_at"]), market["updated_at"]
    assert market["created_at"] == market["updated_at"], market
    assertions.assert_market(market)

    rows, meta = validate_paginated(api.list_markets(users.AUDITOR))
    assertions.assert_page_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [market["id"]], rows


def test_market_and_channel_retrieval_by_id_returns_stored_row(api: ApiClient) -> None:
    """PRD 2.4: "Every other successful operation — reads, revisions and the action endpoints that drive state machines — returns HTTP 200."
    PRD 3.1: "`adstock_decay_rate` is the geometric carryover weight applied per lag period; it must be at least 0.00 and at most 0.95 and must carry exactly two decimal places."
    PRD 3.1: "Two contractual bounds complete the row: `min_spend_cents`, the per-planning-horizon spend floor the optimizer must honour, at least zero; and `max_spend_cents`, the per-planning-horizon ceiling, which must be at least as large as `min_spend_cents`."
    PRD 3.1: "Finally, `status` defaults to `ACTIVE` and must be one of `ACTIVE`, `PAUSED` or `RETIRED`."

    Design: Corner/entities/market_and_channel_retrieval_by_id_returns_stored_row
    """
    fixtures.set_clock(api)
    market = fixtures.create_market(api)
    channel = fixtures.create_channel(api, factories.a_search_payload(market["id"]))

    market_response = api.get_market(market["id"], users.AUDITOR)
    stored_market = validate_success(market_response, 200)
    assert _envelope(market_response)["response_type"] == "object"
    assert stored_market["id"] == market["id"], stored_market["id"]
    assert stored_market["market_code"] == "US_CORE", stored_market["market_code"]
    assert stored_market["total_population"] == 10000000, stored_market
    assertions.assert_market(stored_market)

    channel_response = api.get_media_channel(channel["id"], users.AUDITOR)
    stored = validate_success(channel_response, 200)
    assert _envelope(channel_response)["response_type"] == "object"
    assert stored["id"] == channel["id"], stored["id"]
    assert stored["market_id"] == market["id"], stored["market_id"]
    assert stored["channel_code"] == "A_SEARCH", stored["channel_code"]
    assert stored["channel_type"] == "SEARCH", stored["channel_type"]

    # The declared two-decimal precision survives persistence.
    assert float(stored["adstock_decay_rate"]) == 0.50, stored["adstock_decay_rate"]
    assertions.assert_decimal_places(stored["adstock_decay_rate"], 2, "adstock_decay_rate")
    assert stored["adstock_max_lag_periods"] == 2, stored["adstock_max_lag_periods"]
    assert stored["saturation_half_point_cents"] == 200000, stored
    assert stored["response_ceiling_units"] == 1200, stored["response_ceiling_units"]
    assert stored["min_spend_cents"] == 200000, stored["min_spend_cents"]
    assert stored["max_spend_cents"] == 3000000, stored["max_spend_cents"]

    assert stored["status"] == "ACTIVE", stored["status"]
    assert stored["version"] == 1, stored["version"]
    assertions.assert_media_channel(stored)


def test_media_channel_listing_orders_by_created_at_with_pagination_envelope(
    api: ApiClient,
) -> None:
    """PRD 2.3: "List results are always ordered by `created_at` ascending."
    PRD 2.3: "A row's `id` is never a sort key, never a tie-break, and never an input to any allocation or evaluation order anywhere in this service."
    PRD 2.3: "When a list endpoint responds, the `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true when rows remain beyond the current window."
    PRD 3.1: "Channels can be listed filtered by `market_id`, by `channel_code` or by `status`."

    Design: Corner/entities/media_channel_listing_orders_by_created_at_with_pagination_envelope
    """
    fixtures.set_clock(api)
    market = fixtures.create_market(api)
    market_id = market["id"]

    # Created in deliberately non-alphabetical order, each write separated in
    # time so that created_at is strictly increasing and the tie-break on
    # channel_code cannot come into play.
    fixtures.create_channel(api, factories.c_video_payload(market_id))
    fixtures.set_clock(api, "2026-08-01T01:00:00Z")
    fixtures.create_channel(api, factories.a_search_payload(market_id))
    fixtures.set_clock(api, "2026-08-01T02:00:00Z")
    fixtures.create_channel(api, factories.b_social_payload(market_id))

    full_response = api.list_media_channels(users.AUDITOR, {"market_id": market_id})
    rows, meta = validate_paginated(full_response)
    assert _envelope(full_response)["response_type"] == "array"
    assertions.assert_page_meta(meta, total_count=3, has_more=False)
    codes = factories.field_of(rows, "channel_code")
    assert codes == ["C_VIDEO", "A_SEARCH", "B_SOCIAL"], codes
    assertions.assert_created_at_ascending(rows)

    # channel_code is only the tie-break, so the page is NOT alphabetical.
    assert codes != ["A_SEARCH", "B_SOCIAL", "C_VIDEO"], codes
    assertions.assert_not_ordered_by_id(rows)

    first_page, first_meta = validate_paginated(
        api.list_media_channels(
            users.AUDITOR, {"market_id": market_id, "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, first_page
    assert factories.field_of(first_page, "channel_code") == ["C_VIDEO", "A_SEARCH"]
    assertions.assert_page_meta(
        first_meta, limit=2, offset=0, total_count=3, has_more=True
    )

    second_page, second_meta = validate_paginated(
        api.list_media_channels(
            users.AUDITOR, {"market_id": market_id, "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1, second_page
    assert factories.field_of(second_page, "channel_code") == ["B_SOCIAL"]
    assertions.assert_page_meta(
        second_meta, limit=2, offset=2, total_count=3, has_more=False
    )

    filtered, filtered_meta = validate_paginated(
        api.list_media_channels(
            users.AUDITOR, {"market_id": market_id, "channel_code": "B_SOCIAL"}
        )
    )
    assert len(filtered) == 1, filtered
    assert filtered[0]["channel_code"] == "B_SOCIAL", filtered[0]
    assertions.assert_page_meta(filtered_meta, total_count=1, has_more=False)


@pytest.mark.parametrize(
    "collection,expected_error_id",
    sorted(NOT_FOUND_BY_COLLECTION.items()),
    ids=sorted(NOT_FOUND_BY_COLLECTION),
)
def test_every_entity_path_id_not_found_returns_matching_error(
    api: ApiClient, collection: str, expected_error_id: str
) -> None:
    """PRD 2.5: "Path parameters are resolved before any body is examined, left to right, and an unresolvable identifier yields the 404 belonging to that collection: `ERR_MARKET_NOT_FOUND`, `ERR_MEDIA_CHANNEL_NOT_FOUND`, `ERR_GEO_CELL_NOT_FOUND`, `ERR_DATA_WINDOW_NOT_FOUND`, `ERR_SPEND_OBSERVATION_NOT_FOUND`, `ERR_SALES_OBSERVATION_NOT_FOUND`, `ERR_MODEL_RUN_NOT_FOUND`, `ERR_CHANNEL_CONTRIBUTION_NOT_FOUND`, `ERR_EXPERIMENT_NOT_FOUND`, `ERR_CALIBRATION_RECORD_NOT_FOUND`, `ERR_BUDGET_SCENARIO_NOT_FOUND`, `ERR_BUDGET_ALLOCATION_NOT_FOUND` or `ERR_RECONCILIATION_REPORT_NOT_FOUND`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/every_entity_path_id_not_found_returns_matching_error
    """
    # Thirteen collections, thirteen distinct identifiers.
    assert len(set(NOT_FOUND_BY_COLLECTION.values())) == 13, NOT_FOUND_BY_COLLECTION

    fixtures.set_clock(api)
    market = fixtures.create_market(api)

    response = api.get_collection_item(collection, _FAKE_ID, users.AUDITOR)
    error = validate_error(response, expected_error_id, 404)
    assert _envelope(response)["response_type"] == "error"
    assert error["message"].strip(), error

    # The market that DOES exist proves the 404 is about the unknown id alone.
    stored = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    assert stored["id"] == market["id"], stored["id"]


@pytest.mark.parametrize(
    "omitted_field", ["market_code", "population", "max_spend_cents"]
)
def test_create_calls_missing_required_fields_are_rejected(
    api: ApiClient, omitted_field: str
) -> None:
    """PRD 2.5: "A body that fails to parse, omits a required field, carries an enum value outside its declared set, carries a numeric value outside its declared range, or carries a date that is not an ISO 8601 UTC-midnight instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD 3.1: "Registration supplies a `market_code`, which must be an uppercase snake-case identifier of three to thirty-two characters beginning with a letter and composed thereafter of uppercase letters, digits and underscores, and which must be unique across every market in the system; a `name` between one and one hundred twenty characters; a `total_population` of at least one thousand, which serves as the denominator of every holdout-share rule; an `annual_budget_ceiling_cents` of zero or more, which is the hard fiscal ceiling no single budget scenario may exceed; and optionally a `currency_code`, three uppercase letters, defaulting to `USD`."
    PRD 3.1: "A cell carries its `market_id`, a `cell_code` of two to sixteen characters beginning with an uppercase letter and continuing with uppercase letters, digits or underscores, unique within the market, and a `population` strictly greater than zero."
    PRD 3.1: "Two contractual bounds complete the row: `min_spend_cents`, the per-planning-horizon spend floor the optimizer must honour, at least zero; and `max_spend_cents`, the per-planning-horizon ceiling, which must be at least as large as `min_spend_cents`."

    Design: Corner/entities/create_calls_missing_required_fields_are_rejected
    """
    fixtures.set_clock(api)
    market = fixtures.create_market(api)
    market_id = market["id"]

    if omitted_field == "market_code":
        response = api.create_market(
            factories.without(
                factories.market_payload(name="No Code Market"),
                "market_code",
                "currency_code",
            ),
            users.DATA_ENGINEER,
        )
    elif omitted_field == "population":
        response = api.create_geo_cell(
            factories.without(
                factories.geo_cell_payload(market_id, cell_code="GC01"), "population"
            ),
            users.DATA_ENGINEER,
        )
    else:
        response = api.create_media_channel(
            factories.without(
                factories.a_search_payload(market_id), "max_spend_cents", "status"
            ),
            users.DATA_ENGINEER,
        )

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert _envelope(response)["response_type"] == "error"
    assert error["message"].strip(), error

    # A rejected create persists nothing: the only row anywhere is the setup market.
    _, market_meta = validate_paginated(api.list_markets(users.AUDITOR))
    assertions.assert_page_meta(market_meta, total_count=1)
    _, cell_meta = validate_paginated(
        api.list_geo_cells(users.AUDITOR, {"market_id": market_id})
    )
    assertions.assert_page_meta(cell_meta, total_count=0)
    _, channel_meta = validate_paginated(
        api.list_media_channels(users.AUDITOR, {"market_id": market_id})
    )
    assertions.assert_page_meta(channel_meta, total_count=0)


def test_optional_inputs_fall_back_to_declared_defaults(api: ApiClient) -> None:
    """PRD 3.1: "Registration supplies a `market_code`, which must be an uppercase snake-case identifier of three to thirty-two characters beginning with a letter and composed thereafter of uppercase letters, digits and underscores, and which must be unique across every market in the system; a `name` between one and one hundred twenty characters; a `total_population` of at least one thousand, which serves as the denominator of every holdout-share rule; an `annual_budget_ceiling_cents` of zero or more, which is the hard fiscal ceiling no single budget scenario may exceed; and optionally a `currency_code`, three uppercase letters, defaulting to `USD`."
    PRD 3.1: "Finally, `status` defaults to `ACTIVE` and must be one of `ACTIVE`, `PAUSED` or `RETIRED`."
    PRD 3.1: "A new cell starts with `assignment_state` `UNASSIGNED`, a null `assigned_experiment_id` and a null `washout_until_date`."
    PRD 3.2: "A new window opens in `OPEN` status with `sales_period_count`, `spend_observation_count` and `lag_completeness_pct` all at zero, `reopen_count` at 0 and `reopen_reason` null."
    PRD 3.4: "`control_variables` is an optional array drawn from `PRICE_INDEX`, `DISTRIBUTION_INDEX`, `MACRO_INDEX` and `SEASONALITY_WEEK_OF_YEAR`; `seasonality_mode` is one of `NONE`, `WEEK_OF_YEAR` or `MONTH_OF_YEAR` and defaults to `WEEK_OF_YEAR`."
    PRD 3.4: "Finally, `holdout_periods` is optional, defaults to 1, must be at least 1, and must be strictly less than the window's `expected_period_count` — a run cannot hold out its entire training set."
    PRD 3.4: "A newly created run reports `fit_status` `PENDING`, `validation_status` `UNVALIDATED`, `calibration_status` `NOT_REQUIRED` and `publication_status` `UNPUBLISHED`."

    Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
    """
    fixtures.set_clock(api)

    market = validate_success(
        api.create_market(
            factories.without(factories.market_payload(), "currency_code"),
            users.DATA_ENGINEER,
        ),
        201,
    )
    channel = validate_success(
        api.create_media_channel(
            factories.without(factories.a_search_payload(market["id"]), "status"),
            users.DATA_ENGINEER,
        ),
        201,
    )
    cell = fixtures.create_geo_cell(api, market["id"], "GC01", 1000000)
    window = fixtures.create_data_window(api, market["id"])

    # carryover_attribution_mode is supplied explicitly because the run
    # specification declares it as a required field.
    run = validate_success(
        api.create_model_run(
            factories.without(
                factories.model_run_payload(
                    market["id"], window["id"], [channel["id"]]
                ),
                "control_variables",
                "seasonality_mode",
                "holdout_periods",
            ),
            users.MODELER,
        ),
        201,
    )
    assert run["seasonality_mode"] == "WEEK_OF_YEAR", run["seasonality_mode"]
    assert run["holdout_periods"] == 1, run["holdout_periods"]
    assertions.assert_run_state(
        run, "PENDING", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )

    stored_market = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    assert stored_market["currency_code"] == "USD", stored_market["currency_code"]

    stored_channel = validate_success(
        api.get_media_channel(channel["id"], users.AUDITOR), 200
    )
    assert stored_channel["status"] == "ACTIVE", stored_channel["status"]

    stored_cell = validate_success(api.get_geo_cell(cell["id"], users.AUDITOR), 200)
    assert stored_cell["assignment_state"] == "UNASSIGNED", stored_cell
    assert stored_cell["assigned_experiment_id"] is None, stored_cell
    assert stored_cell["washout_until_date"] is None, stored_cell

    stored_window = validate_success(
        api.get_data_window(window["id"], users.AUDITOR), 200
    )
    assert stored_window["status"] == "OPEN", stored_window["status"]
    assert stored_window["reopen_count"] == 0, stored_window["reopen_count"]
    assert stored_window["reopen_reason"] is None, stored_window["reopen_reason"]
    assert stored_window["sales_period_count"] == 0, stored_window
    assert stored_window["spend_observation_count"] == 0, stored_window
    assert float(stored_window["lag_completeness_pct"]) == 0.00, stored_window


def test_sales_observation_avg_price_cents_is_computed_not_supplied(
    api: ApiClient,
) -> None:
    """PRD 3.2: "On acceptance the row's `avg_price_cents` is computed as `revenue_cents` divided by `units_sold`, rounded half-up to a whole cent; it is reporting only."
    PRD 3.2: "The parent window then increases its `sales_period_count` by one and recomputes `lag_completeness_pct` as one hundred multiplied by `sales_period_count`, divided by `expected_period_count`, rounded half-up to two decimal places — which, because each period admits at most one sales row, is exactly the share of the window's expected periods that carry a sales observation."
    PRD 3.2: "Sales observations may be listed filtered by `data_window_id`."

    Design: Corner/entities/sales_observation_avg_price_cents_is_computed_not_supplied
    """
    fixtures.set_clock(api)
    market = fixtures.create_market(api)
    window = fixtures.create_data_window(api, market["id"])

    # avg_price_cents is not part of the request schema at all: only units_sold
    # and revenue_cents are supplied, in period order.
    expected_avg_price_cents = [5000, 5100, 5000, 5000]

    for period, row, expected in zip(
        factories.WINDOW_PERIODS, factories.F1_SALES_ROWS, expected_avg_price_cents
    ):
        payload = factories.sales_observation_payload(
            window["id"], period, row["units_sold"], row["revenue_cents"]
        )
        assert "avg_price_cents" not in payload, payload

        response = api.create_sales_observation(payload, users.DATA_ENGINEER)
        observation = validate_success(response, 201)
        assert _envelope(response)["response_type"] == "object"
        assert observation["avg_price_cents"] == expected, (
            period,
            observation["avg_price_cents"],
        )
        assert observation["units_sold"] == row["units_sold"], observation
        assert observation["revenue_cents"] == row["revenue_cents"], observation
        assertions.assert_sales_observation(observation)

    stored_window = validate_success(
        api.get_data_window(window["id"], users.AUDITOR), 200
    )
    assert stored_window["sales_period_count"] == 4, stored_window
    assert float(stored_window["lag_completeness_pct"]) == 100.00, stored_window

    rows, meta = validate_paginated(
        api.list_sales_observations(users.AUDITOR, {"data_window_id": window["id"]})
    )
    assertions.assert_page_meta(meta, total_count=4)
    assertions.assert_ordered_by(rows, "period_start_date")
    assert rows[1]["avg_price_cents"] == 5100, rows[1]
    assert [row["avg_price_cents"] for row in rows] == expected_avg_price_cents, rows


def test_spend_observation_system_fields_are_server_generated(api: ApiClient) -> None:
    """PRD 2.4: "`id` is a server-minted UUID with no type prefix and is never supplied by a client."
    PRD 2.4: "`created_at` and `updated_at` are ISO 8601 timestamps in UTC with exactly three fractional-second digits; `created_at` is fixed at insertion and `updated_at` is refreshed on every mutation of the row."
    PRD 2.7: "Every accepted spend-observation write increments the parent window's `version`, and the response echoes the post-write value in the observation's `data_window_version_after`, so a client filing a series of observations can chain its writes without re-reading the window between them."
    PRD 3.2: "When no incumbent existed, the new row's `is_restatement` is false and its `superseded_by_id` stays null."
    PRD 3.2: "Every accepted spend write recomputes the parent window's `spend_observation_count` over its non-superseded rows only, increments the window's `version`, and stamps the observation's `data_window_version_after` with the post-write value."
    PRD 3.2: "Delivered `impressions` are recorded for reporting and enter no calculation anywhere."

    Design: Corner/entities/spend_observation_system_fields_are_server_generated
    """
    fixtures.set_clock(api)
    market = fixtures.create_market(api)
    channel = fixtures.create_channel(api, factories.a_search_payload(market["id"]))
    window = fixtures.create_data_window(api, market["id"])
    fixtures.file_sales_rows(api, window["id"])

    # The window version is read from the server immediately before the write, so
    # the concurrency input is an observed value rather than a literal.
    observed_version = fixtures.window_version(api, window["id"])

    response = api.create_spend_observation(
        factories.spend_observation_payload(
            window["id"],
            channel["id"],
            "2026-08-03T00:00:00Z",
            400000,
            observed_version,
            impressions=4000,
        ),
        users.DATA_ENGINEER,
    )
    observation = validate_success(response, 201)

    assert isinstance(observation["id"], str) and observation["id"], observation["id"]
    assert is_valid_uuid(observation["id"]), observation["id"]
    assert observation["version"] == 1, observation["version"]
    assert is_iso8601_timestamp(observation["created_at"]), observation["created_at"]
    assert is_iso8601_timestamp(observation["updated_at"]), observation["updated_at"]
    assert observation["created_at"] == observation["updated_at"], observation

    # The write incremented the parent exactly once, and the echo proves it.
    assert observation["data_window_version_after"] == observed_version + 1, (
        observed_version,
        observation["data_window_version_after"],
    )
    assert observation["superseded_by_id"] is None, observation["superseded_by_id"]
    assert observation["is_restatement"] is False, observation["is_restatement"]

    assert observation["spend_cents"] == 400000, observation["spend_cents"]
    assert observation["impressions"] == 4000, observation["impressions"]
    assertions.assert_spend_observation(observation)

    stored_window = validate_success(
        api.get_data_window(window["id"], users.AUDITOR), 200
    )
    assert stored_window["version"] == observation["data_window_version_after"], (
        stored_window["version"],
        observation["data_window_version_after"],
    )
    assert stored_window["spend_observation_count"] == 1, stored_window


@pytest.mark.parametrize(
    "violation",
    [
        "design_type_outside_enum",
        "adstock_decay_rate_above_ceiling",
        "window_end_before_start",
        "weekly_span_not_a_multiple_of_seven",
    ],
)
def test_enum_and_range_violations_are_rejected(
    api: ApiClient, violation: str
) -> None:
    """PRD 2.5: "A body that fails to parse, omits a required field, carries an enum value outside its declared set, carries a numeric value outside its declared range, or carries a date that is not an ISO 8601 UTC-midnight instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD 3.6: "The body carries the `market_id`, the `channel_id` whose incrementality is being measured — which must belong to that market, or `ERR_CHANNEL_NOT_IN_MARKET` — and a `design_type` of either `GEO_HOLDOUT`, which consumes real geographic cell population, or `AUDIENCE_SPLIT`, which declares its arm sizes directly and consumes no cells at all."
    PRD 3.1: "`adstock_decay_rate` is the geometric carryover weight applied per lag period; it must be at least 0.00 and at most 0.95 and must carry exactly two decimal places."
    PRD 3.2: "A `DataEngineer` opens a window by naming its `market_id`, its `window_start_date` and `window_end_date` (both ISO 8601 dates at UTC midnight, with the end strictly after the start), and its `granularity`, which must be either `WEEKLY` or `DAILY`."
    PRD 3.2: "That division must come out exact — a window spanning a number of days that is not a whole multiple of its period length is rejected with `ERR_INVALID_REQUEST`, because a partial trailing period would silently distort every per-period average downstream."

    Design: Corner/entities/enum_and_range_violations_are_rejected
    """
    fixtures.set_clock(api)
    market = fixtures.create_market(api)
    market_id = market["id"]
    channel = fixtures.create_channel(api, factories.a_search_payload(market_id))

    if violation == "design_type_outside_enum":
        response = api.create_experiment(
            factories.experiment_payload(
                market_id, channel["id"], design_type="MULTI_CELL"
            ),
            users.EXPERIMENT_DESIGNER,
        )
    elif violation == "adstock_decay_rate_above_ceiling":
        response = api.create_media_channel(
            factories.without(
                factories.media_channel_payload(
                    market_id,
                    channel_code="D_DISPLAY",
                    channel_type="DISPLAY",
                    adstock_decay_rate=0.99,
                ),
                "status",
            ),
            users.DATA_ENGINEER,
        )
    elif violation == "window_end_before_start":
        response = api.create_data_window(
            factories.data_window_payload(
                market_id,
                window_start_date="2026-08-31T00:00:00Z",
                window_end_date="2026-08-03T00:00:00Z",
            ),
            users.DATA_ENGINEER,
        )
    else:
        response = api.create_data_window(
            factories.data_window_payload(
                market_id,
                window_start_date="2026-08-03T00:00:00Z",
                window_end_date="2026-09-02T00:00:00Z",
            ),
            users.DATA_ENGINEER,
        )

    # A type-constraint breach is a 400, never a 409 or a 422: validate_error
    # cross-checks the status the error catalogue pins to ERR_INVALID_REQUEST.
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert _envelope(response)["response_type"] == "error"
    assert error["message"].strip(), error

    _, experiment_meta = validate_paginated(
        api.list_experiments(users.AUDITOR, {"market_id": market_id})
    )
    assertions.assert_page_meta(experiment_meta, total_count=0)
    _, channel_meta = validate_paginated(
        api.list_media_channels(users.AUDITOR, {"market_id": market_id})
    )
    assertions.assert_page_meta(channel_meta, total_count=1)
    _, window_meta = validate_paginated(
        api.list_data_windows(users.AUDITOR, {"market_id": market_id})
    )
    assertions.assert_page_meta(window_meta, total_count=0)


@pytest.mark.parametrize(
    "foreign_key,expected_error_id",
    [
        ("market_id", ApiErrorId.ERR_MARKET_NOT_FOUND.value),
        ("data_window_id", ApiErrorId.ERR_DATA_WINDOW_NOT_FOUND.value),
        ("budget_scenario_id", ApiErrorId.ERR_BUDGET_SCENARIO_NOT_FOUND.value),
    ],
)
def test_body_foreign_key_that_does_not_exist_returns_matching_not_found(
    api: ApiClient, foreign_key: str, expected_error_id: str
) -> None:
    """PRD 2.5: "Foreign keys carried in a request body are resolved after the body's shape has been validated, and an unresolvable body reference yields the same collection-specific 404 — a `market_id` that names nothing gives `ERR_MARKET_NOT_FOUND`, a `channel_id`, an element of `included_channel_ids` or a channel named inside a platform line gives `ERR_MEDIA_CHANNEL_NOT_FOUND`, an element of `treatment_cell_ids` or `control_cell_ids` gives `ERR_GEO_CELL_NOT_FOUND`, a `data_window_id` gives `ERR_DATA_WINDOW_NOT_FOUND`, a `model_run_id` gives `ERR_MODEL_RUN_NOT_FOUND`, an `experiment_id` gives `ERR_EXPERIMENT_NOT_FOUND`, and a `budget_scenario_id` gives `ERR_BUDGET_SCENARIO_NOT_FOUND`."
    PRD 2.12: "Existence comes next, in three steps: path identifiers are resolved left to right, then the request body's shape, required fields, enum membership, numeric ranges and date formats are checked, then the foreign keys carried in the body are resolved."

    Design: Corner/entities/body_foreign_key_that_does_not_exist_returns_matching_not_found
    """
    fixtures.set_clock(api)
    market = fixtures.create_market(api)
    market_id = market["id"]
    channel = fixtures.create_channel(api, factories.a_search_payload(market_id))
    window = fixtures.create_data_window(api, market_id)

    if foreign_key == "market_id":
        response = api.create_media_channel(
            factories.without(
                factories.media_channel_payload(
                    _FAKE_ID,
                    channel_code="E_OOH",
                    channel_type="OOH",
                    adstock_decay_rate=0.1,
                    adstock_max_lag_periods=1,
                    saturation_half_point_cents=100000,
                    response_ceiling_units=500,
                    min_spend_cents=100000,
                    max_spend_cents=1000000,
                ),
                "status",
            ),
            users.DATA_ENGINEER,
        )
    elif foreign_key == "data_window_id":
        response = api.create_model_run(
            factories.without(
                factories.model_run_payload(market_id, _FAKE_ID, [channel["id"]]),
                "control_variables",
                "seasonality_mode",
                "holdout_periods",
            ),
            users.MODELER,
        )
    else:
        response = api.create_budget_allocation(
            factories.budget_allocation_payload(_FAKE_ID, channel["id"], 1500000),
            users.BRAND_PLANNER,
        )

    error = validate_error(response, expected_error_id, 404)
    assert _envelope(response)["response_type"] == "error"
    assert error["message"].strip(), error

    # Nothing is persisted, and the existing rows are untouched.
    _, channel_meta = validate_paginated(
        api.list_media_channels(users.AUDITOR, {"market_id": market_id})
    )
    assertions.assert_page_meta(channel_meta, total_count=1)
    _, run_meta = validate_paginated(
        api.list_model_runs(users.AUDITOR, {"market_id": market_id})
    )
    assertions.assert_page_meta(run_meta, total_count=0)
    _, allocation_meta = validate_paginated(api.list_budget_allocations(users.AUDITOR))
    assertions.assert_page_meta(allocation_meta, total_count=0)
    stored_window = validate_success(
        api.get_data_window(window["id"], users.AUDITOR), 200
    )
    assert stored_window["id"] == window["id"], stored_window["id"]


def test_flat_topology_cross_reference_integrity_channel_must_belong_to_market(
    api: ApiClient,
) -> None:
    """PRD 3.6: "The body carries the `market_id`, the `channel_id` whose incrementality is being measured — which must belong to that market, or `ERR_CHANNEL_NOT_IN_MARKET` — and a `design_type` of either `GEO_HOLDOUT`, which consumes real geographic cell population, or `AUDIENCE_SPLIT`, which declares its arm sizes directly and consumes no cells at all."
    PRD 3.4: "It carries `included_channel_ids`, an array of between one and eight distinct media-channel identifiers, every one of which must reference a channel whose market matches the run's market — a channel from another market is `ERR_CHANNEL_NOT_IN_MARKET`."
    PRD 2.5: "Parent-to-child navigation is performed by filtering a list endpoint, never by walking a nested URL: a market's channels are found by filtering the media-channel list on `market_id`, a run's contributions by filtering the channel-contribution list on `model_run_id`, and an experiment's enlisted cells by filtering the geographic-cell list on `assigned_experiment_id`."

    Design: Corner/entities/flat_topology_cross_reference_integrity_channel_must_belong_to_market
    """
    fixtures.set_clock(api)
    us_market = fixtures.create_market(api)
    eu_market = fixtures.create_second_market(
        api, total_population=8000000, annual_budget_ceiling_cents=4000000000
    )

    own_channel = fixtures.create_channel(
        api, factories.a_search_payload(us_market["id"])
    )
    foreign_channel = fixtures.create_channel(
        api,
        factories.without(
            factories.media_channel_payload(
                eu_market["id"],
                channel_code="F_FOREIGN",
                channel_type="DISPLAY",
                adstock_decay_rate=0.2,
                adstock_max_lag_periods=1,
                saturation_half_point_cents=100000,
                response_ceiling_units=600,
                min_spend_cents=100000,
                max_spend_cents=1000000,
            ),
            "status",
        ),
    )
    window = fixtures.create_data_window(api, us_market["id"])

    # The foreign channel resolves, so the answer is a referential 422, not a 404.
    experiment_response = api.create_experiment(
        factories.experiment_payload(us_market["id"], foreign_channel["id"]),
        users.EXPERIMENT_DESIGNER,
    )
    validate_error(
        experiment_response, ApiErrorId.ERR_CHANNEL_NOT_IN_MARKET.value, 422
    )
    assert _envelope(experiment_response)["response_type"] == "error"

    # One foreign channel in included_channel_ids poisons the whole list.
    run_response = api.create_model_run(
        factories.without(
            factories.model_run_payload(
                us_market["id"],
                window["id"],
                [own_channel["id"], foreign_channel["id"]],
            ),
            "control_variables",
            "seasonality_mode",
            "holdout_periods",
        ),
        users.MODELER,
    )
    validate_error(run_response, ApiErrorId.ERR_CHANNEL_NOT_IN_MARKET.value, 422)
    assert _envelope(run_response)["response_type"] == "error"

    _, experiment_meta = validate_paginated(
        api.list_experiments(users.AUDITOR, {"market_id": us_market["id"]})
    )
    assertions.assert_page_meta(experiment_meta, total_count=0)
    _, run_meta = validate_paginated(
        api.list_model_runs(users.AUDITOR, {"market_id": us_market["id"]})
    )
    assertions.assert_page_meta(run_meta, total_count=0)

    # The foreign row is intact; only the cross-market use was refused.
    stored_foreign = validate_success(
        api.get_media_channel(foreign_channel["id"], users.AUDITOR), 200
    )
    assert stored_foreign["market_id"] == eu_market["id"], stored_foreign["market_id"]
    assert stored_foreign["channel_code"] == "F_FOREIGN", stored_foreign
