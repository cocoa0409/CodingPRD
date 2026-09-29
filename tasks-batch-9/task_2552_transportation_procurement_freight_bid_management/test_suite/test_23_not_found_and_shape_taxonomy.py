"""The two lowest rungs of the check ladder, read as an error taxonomy.

Thirteen entity types each own a distinct 404 identifier, and a well-formed
identifier is looked up in the table named by its own path segment rather than
globally. One rung above, four unrelated shape violations — an undeclared enum
member, an inverted interval, an out-of-range percentage and negative money —
all collapse into the single 400 identifier, and they answer before any foreign
key, state or fiscal rule gets a chance to.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    COMPLIANCE,
    CONTRACT_ADMIN,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    add_lane,
    api_client,
    carrier_status_change_payload,
    create_bid_event,
    create_carrier,
    create_qualified_carrier,
    lane_payload,
    read_carrier,
    read_event,
    scorecard_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# The probe identifier belongs to no table at all.
PROBE_ID = NON_EXISTENT_UUID

# An undeclared carrier status, an inverted measurement period, a percentage
# above the declared ceiling and a negative money amount.
UNDECLARED_STATUS = "PROBATION"
INVERTED_PERIOD = {
    "period_start": "2026-10-01T00:00:00Z",
    "period_end": "2026-09-01T00:00:00Z",
}
CORRECTED_PERIOD = {
    "period_start": "2026-09-01T00:00:00Z",
    "period_end": "2026-10-01T00:00:00Z",
}
OUT_OF_RANGE_ON_TIME_PCT = 101.00
IN_RANGE_ON_TIME_PCT = 100.00
NEGATIVE_ACCESSORIAL_USD = -137.55
CORRECTED_ACCESSORIAL_USD = 137.55
SHAPE_PROBE_LANE_CODE = "L-SHAPE"


def _not_found_probes():
    """One probe per entity type, each hitting its own path segment."""
    return [
        ("ERR_CARRIER_NOT_FOUND", api_client.get_carrier(PROBE_ID, ANALYST)),
        (
            "ERR_QUALIFICATION_REVIEW_NOT_FOUND",
            api_client.screen_capability(PROBE_ID, COMPLIANCE, {}),
        ),
        ("ERR_BID_EVENT_NOT_FOUND", api_client.get_bid_event(PROBE_ID, ANALYST)),
        ("ERR_LANE_NOT_FOUND", api_client.get_lane(PROBE_ID, ANALYST)),
        ("ERR_BID_ROUND_NOT_FOUND", api_client.get_bid_round(PROBE_ID, ANALYST)),
        ("ERR_INVITATION_NOT_FOUND", api_client.get_invitation(PROBE_ID, ANALYST)),
        ("ERR_LANE_BID_NOT_FOUND", api_client.get_lane_bid(PROBE_ID, ANALYST)),
        (
            "ERR_OPTIMIZATION_RUN_NOT_FOUND",
            api_client.get_optimization_run(PROBE_ID, ANALYST),
        ),
        (
            "ERR_AWARD_ALLOCATION_NOT_FOUND",
            api_client.get_award_allocation(PROBE_ID, CATEGORY_MANAGER),
        ),
        ("ERR_CONTRACT_NOT_FOUND", api_client.get_contract(PROBE_ID, CONTRACT_ADMIN)),
        (
            "ERR_RATE_RECORD_NOT_FOUND",
            api_client.get_rate_record(PROBE_ID, CONTRACT_ADMIN),
        ),
        ("ERR_MINI_BID_NOT_FOUND", api_client.get_mini_bid(PROBE_ID, CATEGORY_MANAGER)),
        (
            "ERR_SCORECARD_NOT_FOUND",
            api_client.publish_scorecard(PROBE_ID, CATEGORY_MANAGER),
        ),
    ]


def _change_status(carrier_id, **overrides):
    """Attempts an administrative status change without asserting the outcome."""
    return api_client.change_carrier_status(
        carrier_id, carrier_status_change_payload(**overrides), COMPLIANCE
    )


def _draft_scorecard(carrier_id, **overrides):
    """Attempts to draft a scorecard without asserting the outcome."""
    return api_client.create_scorecard(
        carrier_id, scorecard_payload(**overrides), CATEGORY_MANAGER
    )


def _create_lane(event_id, **overrides):
    """Attempts to add a lane without asserting the outcome."""
    return api_client.create_lane(event_id, lane_payload(**overrides), ANALYST)


def _count_scorecards(carrier_id):
    _rows, meta = validate_paginated(
        api_client.list_carrier_scorecards(carrier_id, CATEGORY_MANAGER)
    )
    return meta["total_count"]


class TestEveryEntityOwnsItsOwnNotFoundId:
    """Thirteen path segments, thirteen distinct 404 identifiers."""

    def test_each_path_segment_answers_with_its_own_entitys_not_found_id(self):
        """No generic 404 and no neighbouring entity's identifier anywhere.

        PRD §2.9: "**Path identifiers.** Every identifier appearing in the request path
        must resolve to an existing row, validated **left to right** — the parent segment
        before the child segment"
        PRD §2.9: "Each entity raises its own 404: a carrier raises
        `ERR_CARRIER_NOT_FOUND`, a qualification review
        `ERR_QUALIFICATION_REVIEW_NOT_FOUND`, a bid event `ERR_BID_EVENT_NOT_FOUND`, a
        lane `ERR_LANE_NOT_FOUND`, a bid round `ERR_BID_ROUND_NOT_FOUND`, an invitation
        `ERR_INVITATION_NOT_FOUND`, a lane bid `ERR_LANE_BID_NOT_FOUND`, an optimization
        run `ERR_OPTIMIZATION_RUN_NOT_FOUND`, an award allocation
        `ERR_AWARD_ALLOCATION_NOT_FOUND`, a contract `ERR_CONTRACT_NOT_FOUND`, a rate
        record `ERR_RATE_RECORD_NOT_FOUND`, a mini-bid `ERR_MINI_BID_NOT_FOUND` and a
        scorecard `ERR_SCORECARD_NOT_FOUND`. This applies to every endpoint carrying a
        path parameter."

        Design: Corner/errors/every_not_found_id_is_reachable_on_its_own_entity
        """
        set_clock(DEFAULT_CLOCK)
        probes = _not_found_probes()
        assert len(probes) == 13

        observed = []
        for expected_id, response in probes:
            validate_error(response, expected_id, 404)
            observed.append(response.json()["data"]["error_id"])
        assert len(set(observed)) == 13, "each entity owns a distinct identifier"

    def test_an_identifier_is_resolved_in_its_own_table_and_lists_never_404(self):
        """A real lane id is not a rate record, and an unknown filter is an empty page.

        PRD §2.9: "so a request naming a non-existent parent fails on the parent even
        when the child identifier is also wrong"
        PRD §2.9: "This applies to every endpoint carrying a path parameter."
        PRD §2.4: "Each collection therefore declares its filter set explicitly, and
        every filter is optional"
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope."

        Design: Corner/errors/every_not_found_id_is_reachable_on_its_own_entity
        """
        set_clock(DEFAULT_CLOCK)
        event = create_bid_event()
        lane = add_lane(event["id"])
        carrier = create_carrier()

        validate_error(
            api_client.get_rate_record(lane["id"], CONTRACT_ADMIN),
            "ERR_RATE_RECORD_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_lane(carrier["id"], ANALYST), "ERR_LANE_NOT_FOUND", 404
        )

        response = api_client.list_lanes(ANALYST, {"bid_event_id": PROBE_ID})
        assert response.status_code == 200, "an unknown filter value is not a 404"
        rows, meta = validate_paginated(response)
        assert rows == []
        assert meta["total_count"] == 0


class TestMalformedBodiesCollapseToOneIdentifier:
    """Four unrelated shape violations, one 400, and no later rule consulted."""

    def test_four_different_shape_violations_all_answer_invalid_request(self):
        """Enum, interval, range and sign, none of them reaching a business rule.

        PRD §2.9: "**Body shape.** On every POST endpoint, each input field that has no
        declared default must be present; each supplied value must match its declared
        type; each enum value must be a declared member of its enumeration; integers
        standing for volumes or counts must be non-negative; money and rate values must
        be non-negative; and wherever an interval is supplied, its start must be strictly
        before its end"
        PRD §2.9: "Any violation is `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "The payload carries `period_start` and `period_end`, with `period_end`
        strictly after `period_start`; `on_time_pct`, a percentage between `0.00` and
        `100.00` at 2 decimal places"
        PRD §3.3: "and `accessorial_history_usd_per_load`, a non-negative money amount at
        2 decimal places"

        Design: Corner/errors/malformed_bodies_are_all_reported_as_invalid_request
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        event = create_bid_event()

        validate_error(
            _change_status(carrier["id"], to_status=UNDECLARED_STATUS),
            "ERR_INVALID_REQUEST",
            400,
        )
        inverted = _draft_scorecard(carrier["id"], **INVERTED_PERIOD)
        validate_error(inverted, "ERR_INVALID_REQUEST", 400)
        assert inverted.json()["data"]["error_id"] != "ERR_RATE_INTERVAL_OVERLAP", (
            "shape precedes business time"
        )
        validate_error(
            _draft_scorecard(
                carrier["id"], **CORRECTED_PERIOD, on_time_pct=OUT_OF_RANGE_ON_TIME_PCT
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            _create_lane(
                event["id"],
                lane_code=SHAPE_PROBE_LANE_CODE,
                accessorial_history_usd_per_load=NEGATIVE_ACCESSORIAL_USD,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        assert read_carrier(carrier["id"])["status"] == "QUALIFIED"
        assert _count_scorecards(carrier["id"]) == 0
        assert read_event(event["id"])["lane_count"] == 0

    def test_correcting_only_the_offending_field_makes_each_call_succeed(self):
        """Nothing else was masking: one field per call was the whole objection.

        PRD §3.1: "A carrier whose `status` is `REGISTERED`, `SCREENING`, `QUALIFIED`,
        `WATCHLIST` or `CONDITIONALLY_QUALIFIED` may be moved to `SUSPENDED`."
        PRD §3.2: "The scorecard is created with `status` `DRAFT`, `published_at` null and
        `disputed_reason` null"
        PRD §3.3: "A new lane is created with `status` `DRAFT`,
        `unallocated_volume_loads` equal to its `annual_volume_loads`,
        `awarded_coverage_pct` `0.00`, and `baseline_cost_usd` and `validated_at` null."

        Design: Corner/errors/malformed_bodies_are_all_reported_as_invalid_request
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        event = create_bid_event()

        drafted = validate_success(
            _draft_scorecard(
                carrier["id"], **CORRECTED_PERIOD, on_time_pct=IN_RANGE_ON_TIME_PCT
            ),
            201,
        )
        assert drafted["status"] == "DRAFT"
        assert drafted["published_at"] is None
        assert _count_scorecards(carrier["id"]) == 1

        created = validate_success(
            _create_lane(
                event["id"],
                lane_code=SHAPE_PROBE_LANE_CODE,
                accessorial_history_usd_per_load=CORRECTED_ACCESSORIAL_USD,
            ),
            201,
        )
        assert created["status"] == "DRAFT"
        assert read_event(event["id"])["lane_count"] == 1

        suspended = validate_success(_change_status(carrier["id"]))
        assert suspended["status"] == "SUSPENDED"
