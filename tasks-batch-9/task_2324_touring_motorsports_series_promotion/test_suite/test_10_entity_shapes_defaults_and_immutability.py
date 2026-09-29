"""Entity envelopes, server-applied defaults, denormalized stop fields and the
one immutable audit record.

Every test builds the state it needs inside the test body or through the shared
fixtures, because the server is restarted against an empty database before each
test runs.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiClient,
    assert_immutable_common_fields,
    assert_season,
    assert_sorted_by,
    assert_tech_inspection,
    assert_tour_stop,
    assert_venue,
    assert_vehicle_entry,
    constants as C,
    fixtures as helpers,
    get_success_data,
    make_season_payload,
    make_tech_inspection_payload,
    make_venue_payload,
    validate_paginated,
    validate_success,
)


class TestSeasonCreationEnvelope:
    """The season creation response: envelope, identity and opening ledger."""

    def test_create_season_returns_the_creation_envelope_and_planning_status(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """A created season answers 201 in the object envelope, at version 1.

        PRD §4: "Operations that bring a new resource into existence return
        `201 Created` — season, venue, booking, competitor, vehicle entry,
        inspection, run-order segment, ticket tier, ticket order, sponsor,
        activation, safety plan, marketing allocation and settlement preparation,
        the last of these including a re-preparation out of dispute."

        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        PRD §2.4: "Almost every resource additionally carries `updated_at` — an
        ISO 8601 UTC timestamp with three fractional digits, refreshed on every
        mutation — and `version`, an integer that starts at 1 and increments by
        one on every mutation of that row, including mutations the server
        performs on its own initiative when a derived counter or a cascaded state
        change lands on the row."

        PRD §3.1: "A new season opens with `status` set to `PLANNING`, and only
        `PLANNING` and `CLOSED` are ever valid values for it."

        Design: Corner/entities/corner_create_season_returns_envelope_and_initial_ledger
        """
        response = api.create_season(make_season_payload(), headers=promoter_headers)
        row = validate_success(response, expected_status=201)

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")

        assert_season(row)
        assert row["status"] == "PLANNING"
        assert row["version"] == 1

    def test_new_season_opens_with_a_zeroed_ledger_and_zeroed_roll_ups(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """Nothing is allocated and no counter has moved on a brand new season.

        PRD §3.1: "Its ledger fields open at a known state:
        `marketing_allocated_cents` is 0 and `marketing_unallocated_cents` equals
        `total_marketing_budget_cents`."

        PRD §3.1: "Its roll-up counters — `booking_count`, `settled_stop_count`
        and `season_net_cents` — all open at 0."

        Design: Corner/entities/corner_create_season_returns_envelope_and_initial_ledger
        """
        budget = C.DEFAULT_SEASON_MARKETING_BUDGET_CENTS
        row = get_success_data(
            api.create_season(
                make_season_payload(total_marketing_budget_cents=budget),
                headers=promoter_headers,
            )
        )

        assert row["total_marketing_budget_cents"] == budget
        assert row["marketing_allocated_cents"] == 0
        assert row["marketing_unallocated_cents"] == budget
        assert row["booking_count"] == 0
        assert row["settled_stop_count"] == 0
        assert row["season_net_cents"] == 0

        reread = helpers.fetch_season(api, row["id"])
        assert reread["marketing_allocated_cents"] == 0
        assert reread["marketing_unallocated_cents"] == budget
        assert reread["booking_count"] == 0
        assert reread["settled_stop_count"] == 0
        assert reread["season_net_cents"] == 0


class TestVenueTurnaroundDefault:
    """The building's turnaround buffer when the client does not supply one."""

    def test_turnaround_hours_defaults_to_twelve_when_omitted(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """An omitted turnaround buffer comes back as the documented 12 hours.

        PRD §3.1: "Finally, `turnaround_hours` is the mandatory buffer the
        building requires after one tear-down before another load-in may begin;
        it may not be negative and defaults to 12 hours."

        Design: Corner/entities/corner_venue_turnaround_hours_default_is_applied_when_omitted
        """
        payload = make_venue_payload(turnaround_hours=None)
        assert "turnaround_hours" not in payload

        row = validate_success(
            api.create_venue(payload, headers=promoter_headers), expected_status=201
        )

        assert_venue(row)
        assert row["turnaround_hours"] == C.DEFAULT_VENUE_TURNAROUND_HOURS
        assert row["turnaround_hours"] == 12

    def test_defaulted_turnaround_hours_is_stored_on_the_row(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """The default was written to the row, not just to the create response.

        PRD §3.1: "Finally, `turnaround_hours` is the mandatory buffer the
        building requires after one tear-down before another load-in may begin;
        it may not be negative and defaults to 12 hours."

        Design: Corner/entities/corner_venue_turnaround_hours_default_is_applied_when_omitted
        """
        created = get_success_data(
            api.create_venue(
                make_venue_payload(turnaround_hours=None), headers=promoter_headers
            )
        )

        fetched = get_success_data(api.get_venue(created["id"], headers=promoter_headers))

        assert fetched["id"] == created["id"]
        assert fetched["turnaround_hours"] == 12
        assert fetched["floor_type"] == C.DEFAULT_VENUE_FLOOR_TYPE
        assert fetched["staging_bay_count"] == C.DEFAULT_VENUE_STAGING_BAY_COUNT
        assert fetched["seat_capacity"] == C.DEFAULT_VENUE_SEAT_CAPACITY


class TestSynthesizedTourStop:
    """The stop the server writes for a booking the promoter has accepted."""

    def test_synthesized_stop_denormalizes_market_and_date_and_opens_restricted(
        self, api: ApiClient, confirmed_booking: Dict[str, Any]
    ) -> None:
        """Acceptance writes one stop that carries the venue's market and the
        booking's date, and opens on the two documented states.

        PRD §3.1: "The server synthesizes exactly one `TourStop` for the booking,
        copying `season_id` from the booking, recording the booking as
        `venue_booking_id`, denormalizing `market_code` from the booked venue and
        `event_date` from the booking's `tour_date`."

        PRD §3.1: "The new stop opens with `sales_state` `SALES_PENDING` and
        `safety_state` `SAFETY_DRAFT`, and its posture is immediately computed,
        which yields `RESTRICTED`."

        Design: Corner/entities/corner_tour_stop_computed_fields_are_denormalized_from_the_booking
        """
        booking = confirmed_booking["booking"]
        venue = confirmed_booking["venue"]
        stop = helpers.fetch_stop(api, confirmed_booking["stop_id"])

        assert_tour_stop(stop)
        assert stop["season_id"] == confirmed_booking["season_id"]
        assert stop["venue_booking_id"] == confirmed_booking["booking_id"]
        assert stop["market_code"] == venue["market_code"]
        assert stop["market_code"] == C.DEFAULT_VENUE_MARKET_CODE
        assert stop["event_date"] == booking["tour_date"]
        assert stop["event_date"] == C.DEFAULT_TOUR_DATE
        assert stop["sales_state"] == "SALES_PENDING"
        assert stop["safety_state"] == "SAFETY_DRAFT"
        assert stop["readiness_posture"] == "RESTRICTED"

    def test_synthesized_stop_has_no_show_clock_and_zeroed_roll_ups(
        self, api: ApiClient, confirmed_booking: Dict[str, Any]
    ) -> None:
        """The fresh stop knows no show clock, sells nothing yet, and carries the
        documented show-window and pit-party defaults.

        PRD §3.2: "A newly synthesized stop knows its date and its market but not
        yet its clock."

        PRD §3.2: "`show_window_minutes` is the total on-floor minutes available
        to the run order and defaults to 150; `pit_party_price_cents` is the
        per-head price of the pre-show pit party add-on and defaults to 2450;
        `pit_party_capacity` is the maximum number of pit party heads the stop
        will sell and defaults to 0."

        PRD §3.5: "`expected_attendance` is itself derived as the smaller of the
        booked venue's `seat_capacity` and the sum of `allotment` over the stop's
        ticket tiers."

        PRD §3.4: "Each insert also refreshes the stop's
        `competition_segment_count`, which is the number of the stop's segments
        whose `segment_type` is `COMPETITION`, and recomputes the posture — which
        matters because a stop with zero competition segments is held at
        `RESTRICTED` and cannot open sales."

        Design: Corner/entities/corner_tour_stop_computed_fields_are_denormalized_from_the_booking
        """
        stop = helpers.fetch_stop(api, confirmed_booking["stop_id"])

        assert stop.get("doors_open_utc") is None
        assert stop.get("show_start_utc") is None
        assert stop["show_window_minutes"] == C.DEFAULT_SHOW_WINDOW_MINUTES
        assert stop["show_window_minutes"] == 150
        assert stop["pit_party_capacity"] == 0
        assert stop["expected_attendance"] == 0
        assert stop["competition_segment_count"] == 0
        assert stop["tickets_sold_count"] == 0
        assert stop["gross_ticket_revenue_cents"] == 0


class TestTechInspectionImmutability:
    """The one entity that carries no `updated_at` and no `version`."""

    def test_filed_inspections_carry_no_version_and_number_their_attempts(
        self,
        api: ApiClient,
        safety_inspector_headers: Dict[str, str],
    ) -> None:
        """Each filing is a new audit row numbered from the entry's attempt count,
        and no filing carries the mutable common fields.

        PRD §2.4: "There is exactly one exception: a `TechInspection` is an
        immutable audit record. It carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it entirely."

        PRD §3.3: "`attempt_no` is a 1-based index computed at insert time as the
        entry's `tech_attempt_count` plus one."

        Design: Corner/entities/corner_tech_inspection_is_an_immutable_append_only_record
        """
        state = helpers.stop_ready_for_sale(api)
        entry_id = helpers.staged_entry(api, state["stop_id"])["entry_id"]

        first = validate_success(
            api.create_tech_inspection(
                entry_id,
                make_tech_inspection_payload(
                    result="CONDITIONAL",
                    defect_severity="MINOR",
                    notes="Tether wear noted on the first attempt.",
                ),
                headers=safety_inspector_headers,
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_tech_inspection(
                entry_id,
                make_tech_inspection_payload(result="PASSED", defect_severity="NONE"),
                headers=safety_inspector_headers,
            ),
            expected_status=201,
        )

        assert_tech_inspection(first)
        assert_tech_inspection(second)
        assert first["attempt_no"] == 1
        assert second["attempt_no"] == 2
        assert first["id"] != second["id"]

        for row in (first, second):
            assert "updated_at" not in row
            assert "version" not in row

        reread = get_success_data(
            api.get_tech_inspection(first["id"], headers=safety_inspector_headers)
        )
        assert_immutable_common_fields(reread)
        assert reread["result"] == "CONDITIONAL"
        assert reread["defect_severity"] == "MINOR"
        assert reread["attempt_no"] == 1
        assert reread["created_at"] == first["created_at"]

    def test_inspection_history_is_append_only_and_ordered_by_attempt(
        self,
        api: ApiClient,
        safety_inspector_headers: Dict[str, str],
        promoter_headers: Dict[str, str],
    ) -> None:
        """Both attempts survive as separate rows, ordered by attempt number, and
        the second filing clears the entry.

        PRD §2.3: "Two collections override that default: the inspection history
        of a vehicle entry is ordered by `attempt_no` ascending, and the run order
        of a stop is ordered by `run_order_position` ascending."

        PRD §3.3: "The entry's `tech_attempt_count` is simply the number of
        inspection rows it has, and `failed_attempt_count` the number of those
        whose `result` is `FAILED`."

        PRD §3.3: "A `PASSED` result moves the entry to `TECH_CLEARED`, increments
        `tech_attempt_count` and re-scores readiness under `POST_STAGING`."

        Design: Corner/entities/corner_tech_inspection_is_an_immutable_append_only_record
        """
        state = helpers.stop_ready_for_sale(api)
        entry_id = helpers.staged_entry(api, state["stop_id"])["entry_id"]

        helpers.file_tech_inspection(
            api, entry_id, result="CONDITIONAL", defect_severity="MINOR"
        )
        helpers.file_tech_inspection(api, entry_id, result="PASSED", defect_severity="NONE")

        rows, meta = validate_paginated(
            api.list_tech_inspections(entry_id, headers=safety_inspector_headers)
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2
        assert_sorted_by(rows, "attempt_no")
        assert [row["attempt_no"] for row in rows] == [1, 2]
        assert [row["result"] for row in rows] == ["CONDITIONAL", "PASSED"]
        for row in rows:
            assert row["vehicle_entry_id"] == entry_id
            assert "version" not in row

        entry = get_success_data(api.get_vehicle_entry(entry_id, headers=promoter_headers))
        assert_vehicle_entry(entry)
        assert entry["tech_status"] == "TECH_CLEARED"
        assert entry["tech_attempt_count"] == 2
        assert entry["failed_attempt_count"] == 0
