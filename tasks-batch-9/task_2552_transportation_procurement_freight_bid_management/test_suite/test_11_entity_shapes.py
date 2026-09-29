"""Entity shape, defaults, computed fields and identifier resolution.

These probe the flat surface of the resource model: what a create returns, what a
read echoes back, which optional inputs carry declared defaults, which fields the
server derives for itself, and which identifier failure reports which code.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    OMIT,
    api_client,
    assert_carrier,
    assert_common_fields,
    assert_same_instant,
    assert_tender_event,
    bid_event_payload,
    carrier_payload,
    create_bid_event,
    get_success_data,
    is_valid_uuid,
    lane_payload,
    read_lane,
    read_rate_record,
    reefer_lane_payload,
    set_clock,
    setup_live_rate_record,
    validate_error,
    validate_paginated,
    validate_success,
)

# A freshly registered carrier: the provisional baseline of 90.00 weighted at
# 0.70, a capability score still at 0.00 weighted at 0.20, and a certificate
# with more than 90 days of headroom contributing 100.00 at 0.10.
FRESH_COMPOSITE_SCORE = 73.00

# Lane A's frozen baseline: round(1147 x 2.4000, 2) = 2752.80, + 137.55, x 550.
LANE_A_BASELINE_USD = 1589692.50

SECOND_CARRIER = {
    "legal_name": "Beacon Flatbed",
    "scac_code": "BFLX",
    "diversity_classification": "MWBE",
    "service_modes": ["FLATBED"],
    "fleet_power_units": 60,
    "cargo_limit_usd": 100000.00,
}
THIRD_CARRIER = {
    "legal_name": "Central Fleet",
    "scac_code": "CFLT",
    "service_modes": ["DRY_VAN", "REEFER"],
    "fleet_power_units": 200,
    "auto_liability_limit_usd": 2000000.00,
}


def _register(**overrides):
    """Registers one carrier and returns the created row."""
    return get_success_data(
        api_client.create_carrier(carrier_payload(**overrides), ANALYST)
    )


def _list_carriers(**params):
    return api_client.list_carriers(ANALYST, params or None)


class TestCarrierEntitySurface:
    """What registration writes, what a read echoes and what a list reports."""

    def test_registration_returns_every_declared_field_in_its_initial_state(self):
        """Creation answers 201 with the counters at zero and the standing unqualified.

        PRD §3.1: "A newly registered carrier is created with `status` set to
        `REGISTERED`, `status_reason` null, `capability_score` `0.00`,
        `published_scorecard_count` `0`, `active_primary_lane_count` `0`,
        `committed_volume_loads` `0` and `qualified_at` null."
        PRD §3.1: "Its `composite_score` is computed immediately and its
        `composite_score_variant` is `PROVISIONAL_SCREENING`, because no performance
        history exists yet"
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/carrier_creation_returns_declared_fields_and_registered_initial_state
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.create_carrier(carrier_payload(), ANALYST)
        carrier = validate_success(response, 201)
        assert response.json()["response_type"] == "object"

        assert_carrier(carrier)
        assert carrier["legal_name"] == "Alpha Freight Lines"
        assert carrier["scac_code"] == "ALFL"
        assert carrier["service_modes"] == ["DRY_VAN"]
        assert carrier["fleet_power_units"] == 120
        assert float(carrier["auto_liability_limit_usd"]) == 1000000.00
        assert float(carrier["cargo_limit_usd"]) == 250000.00
        assert_same_instant(carrier["insurance_expiry_date"], "2027-06-30T00:00:00Z")
        assert carrier["diversity_classification"] == "NONE"

        assert carrier["status"] == "REGISTERED"
        assert carrier["status_reason"] is None
        assert float(carrier["capability_score"]) == 0.00
        assert carrier["published_scorecard_count"] == 0
        assert carrier["active_primary_lane_count"] == 0
        assert carrier["committed_volume_loads"] == 0
        assert carrier["qualified_at"] is None
        assert carrier["composite_score_variant"] == "PROVISIONAL_SCREENING"
        assert float(carrier["composite_score"]) == FRESH_COMPOSITE_SCORE

        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta["api_request_timestamp"], str)

    def test_a_single_read_echoes_the_stored_row_without_recomputing_it(self):
        """A GET is not a mutation: no score moves and no version advances.

        PRD §2.6: "**`version`** (integer): a counter that increments by one on every
        mutation of the row, and which the concurrency guards of §2.8 compare against."
        PRD §3.2: "A carrier's `composite_score` is recomputed on every qualification
        decision, on every scorecard publication and on every administrative status
        change."

        Design: Corner/entities/carrier_retrieval_returns_the_stored_row_unchanged
        """
        set_clock(DEFAULT_CLOCK)
        created = _register()

        response = api_client.get_carrier(created["id"], CATEGORY_MANAGER)
        read = validate_success(response, 200)
        assert response.json()["response_type"] == "object"
        assert read["id"] == created["id"]
        assert read["scac_code"] == "ALFL"
        assert read["status"] == "REGISTERED"
        assert float(read["capability_score"]) == 0.00
        assert float(read["composite_score"]) == FRESH_COMPOSITE_SCORE
        assert read["version"] == 1, "a read is not a mutation"
        assert read["updated_at"] == created["updated_at"]

    def test_the_carrier_list_pages_and_reports_the_filtered_total(self):
        """total_count counts the whole filtered set, not the page.

        PRD §2.3: "`limit` bounds the number of items returned; when omitted it defaults
        to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope."
        PRD §2.4: "Carriers may be filtered by `status` and by `diversity_classification`,
        and are ordered by `created_at` ascending."

        Design: Corner/entities/carrier_listing_paginates_with_total_count_and_has_more
        """
        set_clock(DEFAULT_CLOCK)
        _register()
        _register(**SECOND_CARRIER)
        _register(**THIRD_CARRIER)

        first_response = _list_carriers(limit=2, offset=0)
        page_1, meta_1 = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert len(page_1) == 2
        assert meta_1["total_count"] == 3
        assert meta_1["has_more"] is True
        assert meta_1["limit"] == 2
        assert meta_1["offset"] == 0

        page_2, meta_2 = validate_paginated(_list_carriers(limit=2, offset=2))
        assert len(page_2) == 1
        assert meta_2["total_count"] == 3
        assert meta_2["has_more"] is False
        assert meta_2["offset"] == 2

        ids = [row["id"] for row in page_1 + page_2]
        assert len(set(ids)) == 3, "the two pages together cover every row exactly once"
        assert [row["scac_code"] for row in page_1 + page_2] == ["ALFL", "BFLX", "CFLT"]

    def test_the_system_fields_are_server_minted_and_the_version_starts_at_one(self):
        """id, created_at, updated_at and version come from the server and the clock.

        PRD §2.6: "**`id`** (string): a server-minted UUID, with no type prefix of any
        kind."
        PRD §2.6: "**`updated_at`** (string): an ISO 8601 UTC timestamp in the same
        format, refreshed on every mutation of the row"
        PRD §2.5: "Every instant the system writes or compares is read from a server-side
        **logical clock**, never from the host wall clock."

        Design: Corner/entities/carrier_system_fields_are_generated_and_version_starts_at_one
        """
        set_clock(DEFAULT_CLOCK)
        payload = carrier_payload()
        assert "id" not in payload and "version" not in payload

        carrier = _register()
        assert_common_fields(carrier, "carrier")
        assert is_valid_uuid(carrier["id"])
        assert_same_instant(carrier["created_at"], DEFAULT_CLOCK, "created_at")
        assert_same_instant(carrier["updated_at"], DEFAULT_CLOCK, "updated_at")
        assert carrier["version"] == 1
        assert carrier["status_reason"] is None
        assert carrier["qualified_at"] is None


class TestDeclaredDefaultsAndComputedFields:
    """Omitted optional inputs land on their declared defaults, never on null."""

    def test_a_bid_event_omitting_every_optional_knob_takes_the_declared_defaults(self):
        """Six defaults at once, plus the event's zeroed counters.

        PRD §3.3: "Optionally it may state `fuel_index_per_mile`, a non-negative per-mile
        fuel adder defaulting to `0.4500`; `accessorial_inflation_factor`, between `1.00`
        and `2.00` and defaulting to `1.15`; `rounds_allowed`, an integer between 1 and 4
        defaulting to 2; `diversity_min_pct`, defaulting to `10.00`;
        `max_award_share_pct`, defaulting to `60.00`; and `max_carriers_per_lane`, an
        integer between 1 and 3 defaulting to 3."
        PRD §3.3: "The event is created with `status` `DRAFT`, `current_round_no` `0`,
        `lane_count` `0`, `invited_carrier_count` `0`, `accepted_invitation_count` `0`,
        `total_scope_volume_loads` `0`, `coverage_pct` `0.00`, `diversity_pct` `0.00`, and
        `baseline_cost_usd`, `award_cost_usd`, `savings_pct` and `awarded_at` all null."

        Design: Corner/entities/bid_event_create_omitting_optional_knobs_applies_declared_defaults
        """
        set_clock(DEFAULT_CLOCK)
        payload = bid_event_payload(
            name="Defaults Event",
            fuel_index_per_mile=OMIT,
            accessorial_inflation_factor=OMIT,
            rounds_allowed=OMIT,
            diversity_min_pct=OMIT,
            max_award_share_pct=OMIT,
            max_carriers_per_lane=OMIT,
        )
        assert "rounds_allowed" not in payload

        event = validate_success(api_client.create_bid_event(payload, ANALYST), 201)
        assert float(event["fuel_index_per_mile"]) == 0.4500
        assert float(event["accessorial_inflation_factor"]) == 1.15
        assert event["rounds_allowed"] == 2
        assert float(event["diversity_min_pct"]) == 10.00
        assert float(event["max_award_share_pct"]) == 60.00
        assert event["max_carriers_per_lane"] == 3

        assert event["status"] == "DRAFT"
        assert event["current_round_no"] == 0
        assert event["lane_count"] == 0
        assert event["invited_carrier_count"] == 0
        assert event["accepted_invitation_count"] == 0
        assert event["total_scope_volume_loads"] == 0
        assert float(event["coverage_pct"]) == 0.00
        assert float(event["diversity_pct"]) == 0.00
        assert event["baseline_cost_usd"] is None
        assert event["award_cost_usd"] is None
        assert event["savings_pct"] is None
        assert event["awarded_at"] is None

    def test_a_lane_without_seasonality_or_an_incumbent_still_validates(self):
        """The seasonality default plus the advisory flag that never blocks.

        PRD §3.3: "`seasonality_peak_index`, between `1.00` and `2.00` at 2 decimal
        places, defaulting to `1.00`; `incumbent_carrier_id`, defaulting to null; and
        `incumbent_rate_per_mile`, strictly positive at 4 decimal places, defaulting to
        null."
        PRD §3.3: "`NO_INCUMBENT_BASELINE` fires when either `incumbent_carrier_id` or
        `incumbent_rate_per_mile` is null; one without the other is not a usable
        baseline."
        PRD §3.3: "The other four — `VOLUME_VARIANCE_HIGH`, `SEASONALITY_EXTREME`,
        `NO_INCUMBENT_BASELINE` and `ACCESSORIAL_OUTLIER` — are advisory: they are
        recorded and they can affect downstream arithmetic, but they never stop a lane
        from progressing."
        PRD §3.3: "When `incumbent_rate_per_mile` is null the baseline is `0.00`
        outright."

        Design: Corner/entities/lane_create_omitting_seasonality_and_incumbent_applies_defaults_and_advisory_flag
        """
        set_clock(DEFAULT_CLOCK)
        event = create_bid_event(name="Lane Defaults Event")
        payload = reefer_lane_payload(seasonality_peak_index=OMIT)
        assert "incumbent_carrier_id" not in payload

        created = validate_success(
            api_client.create_lane(event["id"], payload, ANALYST), 201
        )
        assert float(created["seasonality_peak_index"]) == 1.00
        assert created["incumbent_carrier_id"] is None
        assert created["incumbent_rate_per_mile"] is None
        assert created["status"] == "DRAFT"
        assert float(created["awarded_coverage_pct"]) == 0.00
        assert created["data_quality_flags"] == ["NO_INCUMBENT_BASELINE"]

        validated = get_success_data(api_client.validate_lane(created["id"], ANALYST))
        assert validated["status"] == "VALIDATED"
        assert_same_instant(validated["validated_at"], DEFAULT_CLOCK, "validated_at")
        assert validated["data_quality_flags"] == ["NO_INCUMBENT_BASELINE"], (
            "an advisory flag is recorded and validation still succeeds"
        )
        assert float(validated["baseline_cost_usd"]) == 0.00
        assert validated["unallocated_volume_loads"] == 120

    def test_the_lane_baseline_and_flags_are_derived_rather_than_supplied(self):
        """No client input sets the baseline: validation computes it in three steps.

        PRD §3.3: "A new lane is created with `status` `DRAFT`,
        `unallocated_volume_loads` equal to its `annual_volume_loads`,
        `awarded_coverage_pct` `0.00`, and `baseline_cost_usd` and `validated_at` null."
        PRD §3.3: "First, multiply `mileage` by `incumbent_rate_per_mile` and round to 2
        decimal places to obtain the baseline linehaul per load. Second, add
        `accessorial_history_usd_per_load` to that already-rounded figure and round the
        sum to 2 decimal places to obtain the baseline cost per load. Third, multiply that
        already-rounded per-load figure by `annual_volume_loads` and round to 2 decimal
        places."
        PRD §3.3: "The baseline is a historical figure and is **never** touched by
        `accessorial_inflation_factor`; only forward-looking bid evaluation inflates
        accessorials."

        Design: Corner/entities/lane_computed_baseline_and_flags_are_derived_at_validation_not_supplied
        """
        set_clock(DEFAULT_CLOCK)
        carrier = _register()
        event = create_bid_event(name="Baseline Event")
        lane = validate_success(
            api_client.create_lane(
                event["id"],
                lane_payload(
                    seasonality_peak_index=1.20,
                    incumbent_carrier_id=carrier["id"],
                    incumbent_rate_per_mile=2.4000,
                ),
                ANALYST,
            ),
            201,
        )
        assert lane["status"] == "DRAFT"
        assert lane["baseline_cost_usd"] is None
        assert lane["validated_at"] is None
        assert lane["unallocated_volume_loads"] == 550
        assert read_lane(lane["id"])["baseline_cost_usd"] is None

        validated = get_success_data(api_client.validate_lane(lane["id"], ANALYST))
        assert validated["status"] == "VALIDATED"
        assert_same_instant(validated["validated_at"], DEFAULT_CLOCK, "validated_at")
        assert float(validated["baseline_cost_usd"]) == LANE_A_BASELINE_USD
        assert validated["data_quality_flags"] == [], (
            "1147 miles, 12.73 percent variance, seasonality 1.20 and an accessorial "
            "of 137.55 against a 275.28 ceiling all sit inside their tolerances"
        )
        assert validated["unallocated_volume_loads"] == 550
        assert float(validated["awarded_coverage_pct"]) == 0.00


class TestIdentifierAndBodyShapeFailures:
    """Which failure reports which code, and that nothing is persisted when it does."""

    def test_an_unknown_carrier_id_reports_the_carriers_own_not_found_code(self):
        """A well-formed but unknown path id resolves to that entity's own 404.

        PRD §2.9: "Every identifier appearing in the request path must resolve to an
        existing row, validated **left to right**"
        PRD §2.9: "Each entity raises its own 404: a carrier raises
        `ERR_CARRIER_NOT_FOUND`"

        Design: Corner/entities/carrier_get_with_unknown_id_returns_carrier_not_found
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.get_carrier(NON_EXISTENT_UUID, ANALYST)
        error = validate_error(response, "ERR_CARRIER_NOT_FOUND", 404)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""

        _, meta = validate_paginated(_list_carriers())
        assert meta["total_count"] == 0, "a failed read creates nothing"

    def test_a_missing_required_field_is_a_body_shape_rejection(self):
        """scac_code has no declared default, so its absence is a 400.

        PRD §2.9: "On every POST endpoint, each input field that has no declared default
        must be present; each supplied value must match its declared type; each enum value
        must be a declared member of its enumeration"
        PRD §3.1: "its `scac_code`, exactly four uppercase letters in the range A through
        Z, which must be unique across every carrier in the system"

        Design: Corner/entities/carrier_create_missing_scac_code_returns_invalid_request
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.create_carrier(carrier_payload(scac_code=OMIT), ANALYST)
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(_list_carriers())
        assert meta["total_count"] == 0, "nothing was persisted"

    def test_an_undeclared_service_mode_is_rejected_and_so_is_an_empty_set(self):
        """The enum membership and non-empty constraints are both body shape rules.

        PRD §3.1: "its `service_modes`, a non-empty set drawn from `DRY_VAN`, `REEFER` and
        `FLATBED`"
        PRD §2.9: "each enum value must be a declared member of its enumeration"

        Design: Corner/entities/carrier_create_with_undeclared_service_mode_returns_invalid_request
        """
        set_clock(DEFAULT_CLOCK)
        validate_error(
            api_client.create_carrier(
                carrier_payload(
                    legal_name="Box Truck Only",
                    scac_code="BTOX",
                    service_modes=["BOX_TRUCK"],
                    fleet_power_units=10,
                    cargo_limit_usd=100000.00,
                ),
                ANALYST,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.create_carrier(
                carrier_payload(scac_code="EMTY", service_modes=[]), ANALYST
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        _, meta = validate_paginated(_list_carriers())
        assert meta["total_count"] == 0

    def test_objective_weights_that_do_not_sum_to_one_are_refused(self):
        """Each weight is individually legal, so only the cross-field sum catches it.

        PRD §3.3: "four weights — `cost_weight`, `service_weight`, `capacity_weight` and
        `diversity_weight` — each between `0.00` and `1.00` at 2 decimal places, which
        **must sum to exactly `1.00`**, a payload that does not being rejected with
        `ERR_INVALID_REQUEST` (400)"
        PRD §2.9: "wherever an interval is supplied, its start must be strictly before its
        end — `effective_from` before `effective_to`, `period_start` before `period_end`,
        `window_open_at` before `window_close_at`, `contract_effective_from` before
        `contract_effective_to`"

        Design: Corner/entities/bid_event_create_with_weights_not_summing_to_one_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        validate_error(
            api_client.create_bid_event(
                bid_event_payload(name="Bad Weights Event", cost_weight=0.60), ANALYST
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        # The same rung refuses a contract window that does not move forward.
        validate_error(
            api_client.create_bid_event(
                bid_event_payload(
                    name="Bad Window Event",
                    contract_effective_from="2027-09-01T00:00:00Z",
                    contract_effective_to="2027-09-01T00:00:00Z",
                ),
                ANALYST,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

    def test_a_lane_under_an_unknown_event_reports_the_parent_not_found(self):
        """The path parent is checked at rung 3, before the body is even inspected.

        PRD §2.9: "Every identifier appearing in the request path must resolve to an
        existing row, validated **left to right** — the parent segment before the child
        segment — so a request naming a non-existent parent fails on the parent even when
        the child identifier is also wrong."
        PRD §2.9: "a bid event `ERR_BID_EVENT_NOT_FOUND`"

        Design: Corner/entities/lane_create_under_unknown_bid_event_returns_bid_event_not_found
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.create_lane(
            NON_EXISTENT_UUID, lane_payload(), ANALYST
        )
        validate_error(response, "ERR_BID_EVENT_NOT_FOUND", 404)

        body = get_success_data(api_client.list_lanes(ANALYST))
        rows = body["data"] if isinstance(body, dict) and "data" in body else body
        assert rows == [], "no lane row was created under a non-existent event"


class TestTenderEventImmutability:
    """The one resource with no version, no updated_at and no mutation path."""

    def test_a_tender_outcome_cannot_be_restated_under_the_same_load_reference(self):
        """The append-only log protects itself with the load-reference uniqueness rule.

        PRD §2.6: "A tender outcome is an immutable append to a log, so a tender event
        carries only `id` and `created_at`. It has **no** `updated_at` field and **no**
        `version` field, and nothing in the system ever mutates one after it is appended."
        PRD §3.9: "a `load_reference` of 1 to 32 characters, unique within that rate
        record — a repeat is rejected with `ERR_DUPLICATE_LOAD_REFERENCE` (409), while the
        same reference under a different record is legal"
        PRD §3.9: "A record with 4 tenders of which all 4 were rejected has a
        `rejection_pct` of `100.00` but has not met the sample gate, so it is **not** at
        risk — a small sample is not evidence."

        Design: Corner/entities/tender_event_is_immutable_and_carries_no_version_or_update_path
        """
        ctx = setup_live_rate_record()
        first = validate_success(
            api_client.create_tender_event(
                ctx["rate_record"]["id"],
                {
                    "outcome": "REJECTED",
                    "load_reference": "LD-2001",
                    "reject_reason": "No power available",
                },
                ANALYST,
            ),
            201,
        )
        assert_tender_event(first)
        assert first["outcome"] == "REJECTED"
        assert first["load_reference"] == "LD-2001"
        assert first["reject_reason"] == "No power available"
        assert first["position_used"] == "PRIMARY"
        assert_same_instant(first["tendered_at"], "2026-09-01T00:00:00Z", "tendered_at")

        validate_error(
            api_client.create_tender_event(
                ctx["rate_record"]["id"],
                {"outcome": "ACCEPTED", "load_reference": "LD-2001"},
                ANALYST,
            ),
            "ERR_DUPLICATE_LOAD_REFERENCE",
            409,
        )

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["tender_count"] == 1, "the refused restatement appended nothing"
        assert float(record["rejection_pct"]) == 100.00
        assert record["status"] == "LIVE", "one tender is below the sample gate of five"
