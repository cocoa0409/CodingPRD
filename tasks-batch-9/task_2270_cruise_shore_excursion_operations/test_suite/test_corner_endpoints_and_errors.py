"""Endpoint-surface behaviour and the refusal codes of the Cruise Shore Excursions API.

Covers partial catalog amendment, meeting reschedules, the per-port revenue report,
filtered and paginated collection reads, and the individual gates that refuse a write
on vetting, eligibility, deadlines, liability and seat arithmetic.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import INSTANTS
from test_helpers.test_users import TEST_USERS


# --------------------------------------------------------------------------
# Endpoint surface
# --------------------------------------------------------------------------

def test_a_partial_amendment_replaces_only_the_supplied_excursion_fields(api):
    """PRD §3.3: "While an item is still in `DRAFT` or `PENDING_REVIEW`, the manager may amend `title`, `duration_minutes`, `min_age`, `max_age`, `mobility_level`, `medical_warning_codes`, `languages`, `base_price_cents`, `price_tier` and `alternative_excursion_id`; supplied fields are replaced and omitted fields are left untouched."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/a_partial_patch_touches_only_the_named_excursion_fields
    """
    world = fixtures.setup_catalog_world(api, publish=False)

    excursion = validate_success(
        api.amend_excursion(
            world.excursion["id"],
            {"base_price_cents": 15000, "title": "Reef Snorkel Plus"},
            TEST_USERS["manager_headers"],
        ),
        200,
    )

    assert excursion["base_price_cents"] == 15000
    assert excursion["title"] == "Reef Snorkel Plus"
    assert excursion["price_tier"] == "PREMIUM"
    assert excursion["duration_minutes"] == 300
    assert excursion["min_age"] == 18
    assert excursion["mobility_level"] == "LEVEL_2"
    assert excursion["languages"] == ["EN", "ES"]
    assert excursion["catalog_status"] == "DRAFT"
    assert excursion["version"] == 2


def test_rescheduling_the_meeting_recomputes_the_scheduled_projection_and_band(api):
    """PRD §3.4: "Rescheduling a departure's meeting supplies a new `meeting_time_utc` and optionally a new `dispatch_dwell_minutes`."
    PRD §3.4: "It is refused unless the departure's `status` is `SCHEDULED` or `SELLING`, it re-checks the port call's published window and the meeting-point congestion sweep, and it recomputes both projections and both bands."
    PRD §3.4: "First compute the egress leg: at an `ALONGSIDE` port it is zero minutes; at a `TENDER` port it is the port's `tender_egress_minutes`, plus a further 20 minutes of penalty when the departure has no `tender_wave_id` assigned, because an unscheduled group waits for whatever boat it can get."
    PRD §3.4: "The ashore leg is then the excursion's `duration_minutes` plus 30 minutes of transfer buffer — 15 minutes at each end — plus the egress leg."
    PRD §3.4: "`projected_return_scheduled_utc` is that start advanced by the ashore leg."
    PRD §3.4: "`slack_minutes_scheduled` is the number of minutes from `projected_return_scheduled_utc` to the call's `all_aboard_utc`, less the port's `risk_buffer_minutes`; it may be negative."
    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Corner/endpoints/rescheduling_the_meeting_recomputes_the_projection_and_the_band
    """
    world = fixtures.setup_selling_departure(api)

    departure = fixtures.reschedule_meeting(
        api, world.departure["id"], "2026-09-15T10:00:00Z"
    )

    assert datetime.fromisoformat(
        departure["meeting_time_utc"].replace("Z", "+00:00")
    ) == datetime.fromisoformat("2026-09-15T10:00:00+00:00")
    assert departure["dispatch_dwell_minutes"] == 20
    assert datetime.fromisoformat(
        departure["projected_return_scheduled_utc"].replace("Z", "+00:00")
    ) == datetime.fromisoformat("2026-09-15T15:30:00+00:00")
    assert departure["slack_minutes_scheduled"] == 30
    assert departure["timing_risk_band_scheduled"] == "AMBER"
    assert departure["status"] == "SELLING"


def test_the_port_revenue_report_nets_to_zero_after_a_weather_cancellation(api):
    """PRD §3.5: "Step one is the tier multiplier: `price_tier` selects 9000 basis points for `VALUE`, 10000 for `STANDARD`, 11500 for `PREMIUM` and 13000 for `SIGNATURE`, and the list price is `base_price_cents` multiplied by that figure, divided by ten thousand, rounded half up to whole cents."
    PRD §3.5: "A `PRE_CRUISE` booking earns a reduction of 500 basis points only when the booking is made at least a full week ahead: take the number of minutes from the logical clock to the departure's `meeting_time_utc`, divide by 1440 and discard the remainder to get whole days to the meeting, and apply the reduction only when that whole-day figure is 7 or more; below 7 the pre-cruise adjustment is zero."
    PRD §3.5: "The channel price is the list price multiplied by ten thousand plus the adjustment in basis points, divided by ten thousand, rounded half up."
    PRD §3.5: "The loyalty component is 0 basis points for `NONE`, 250 for `SILVER`, 500 for `GOLD` and 800 for `PLATINUM`."
    PRD §3.5: "The group component is 1000 basis points when `party_size` is 6 or more, 500 when it is 4 or 5, and 0 below 4."
    PRD §3.5: "`per_guest_price_cents` is the channel price multiplied by ten thousand minus the blended discount in basis points, divided by ten thousand, rounded half up."
    PRD §3.5: "`quoted_total_cents` is then `per_guest_price_cents` multiplied by `party_size` exactly — an integer multiple of the rounded per-guest figure, never a re-derivation from `base_price_cents`."
    PRD §3.5: "`service_fee_cents` is the smaller of 1500 cents and 300 basis points of `quoted_total_cents` rounded half up; it is retained by the line and is never commissionable."
    PRD §3.5: "`charge_total_cents` is `quoted_total_cents` plus `service_fee_cents`, and it is the amount authorised at booking and captured at ticketing."
    PRD §3.7: "A booking whose `financial_status` was `CHARGED` or `PARTIALLY_REFUNDED` moves to `REFUNDED` with a `REFUND` entry of `refund_pct_bps` 10000 and `amount_cents` equal to `charge_total_cents` less whatever `refunded_cents` the booking had already accumulated, so the guest ends up whole including the service fee."
    PRD §3.7: "The `WEATHER` branch stops there: no goodwill credit, no reliability strike for the operator, no settlement penalty."
    PRD §3.9: "`gross_ticket_cents` is the sum of `quoted_total_cents` over the bookings whose `financial_status` is `CHARGED`, `PARTIALLY_REFUNDED`, `REFUNDED` or `RETAINED`, and `service_fee_cents` is the sum of those same bookings' `service_fee_cents`."
    PRD §3.9: "`refunds_cents` is the sum of `amount_cents` over those bookings' `REFUND` ledger entries, and `goodwill_cents` the sum over their `GOODWILL_CREDIT` and `REPATRIATION_ALLOWANCE` entries together."
    PRD §3.9: "`line_commission_cents` and `operator_payable_cents` are the sums of the same-named fields over the commission statements in scope whose `status` is `ISSUED`, `DISPUTED`, `ADJUSTED` or `SETTLED`."
    PRD §3.9: "`net_line_revenue_cents` is then `gross_ticket_cents` plus `service_fee_cents`, less `refunds_cents`, less `goodwill_cents`, less `operator_payable_cents`; it may legitimately be negative when the line refunded everything and paid goodwill on top."

    Design: Corner/endpoints/the_port_revenue_report_nets_to_zero_after_a_weather_cancellation
    """
    world = fixtures.setup_ticketed_booking(api)
    assert world.booking["per_guest_price_cents"] == 13110
    assert world.booking["quoted_total_cents"] == 26220
    assert world.booking["service_fee_cents"] == 787
    assert world.booking["charge_total_cents"] == 27007

    fixtures.cancel_departure(api, world.departure["id"], "WEATHER")

    report = validate_success(
        api.get_port_revenue_report(
            world.port["id"],
            TEST_USERS["finance_headers"],
            params={"voyage_code": "V2609"},
        ),
        200,
    )

    assert report["gross_ticket_cents"] == 26220
    assert report["service_fee_cents"] == 787
    assert report["refunds_cents"] == 27007
    assert report["goodwill_cents"] == 0
    assert report["line_commission_cents"] == 0
    assert report["operator_payable_cents"] == 0
    assert report["net_line_revenue_cents"] == 0


def test_the_port_revenue_report_counts_the_line_cancelled_booking_in_both_ratios(api):
    """PRD §3.7: "Every booking whose `fulfillment_status` is `BOOKED`, `TICKETED` or `CHECKED_IN` moves to `CANCELLED_BY_LINE`."
    PRD §3.7: "The departure's `status` becomes `CANCELLED_WEATHER` or `CANCELLED_OPERATIONAL` accordingly and `cancellation_cause` records `WEATHER` or `OPERATIONAL`."
    PRD §3.9: "The report echoes `port_id` and the `voyage_code` filter, reports `port_call_count` as the number of calls in scope, and `booking_count` as the count of every booking ever taken in scope — nothing is excluded from that denominator."
    PRD §3.9: "Three counts complete the picture: `cancelled_booking_count` over bookings whose `fulfillment_status` is `CANCELLED_BY_GUEST` or `CANCELLED_BY_LINE`, `completed_booking_count` over those in `COMPLETED`, and `no_show_booking_count` over those in `NO_SHOW`."
    PRD §3.9: "From them come two ratios: `cancellation_rate_bps` is the cancelled count multiplied by ten thousand, divided by `booking_count`, rounded half up, and `no_show_rate_bps` is the same computation on the no-show count."

    Design: Corner/endpoints/the_port_revenue_report_nets_to_zero_after_a_weather_cancellation
    """
    world = fixtures.setup_ticketed_booking(api)

    departure = fixtures.cancel_departure(api, world.departure["id"], "WEATHER")
    assert departure["status"] == "CANCELLED_WEATHER"
    assert departure["cancellation_cause"] == "WEATHER"

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "CANCELLED_BY_LINE"

    report = validate_success(
        api.get_port_revenue_report(
            world.port["id"],
            TEST_USERS["finance_headers"],
            params={"voyage_code": "V2609"},
        ),
        200,
    )

    assert report["port_id"] == world.port["id"]
    assert report["voyage_code"] == "V2609"
    assert report["port_call_count"] == 1
    assert report["booking_count"] == 1
    assert report["cancelled_booking_count"] == 1
    assert report["completed_booking_count"] == 0
    assert report["no_show_booking_count"] == 0
    assert report["cancellation_rate_bps"] == 10000
    assert report["no_show_rate_bps"] == 0


def test_departures_can_be_listed_by_the_tender_wave_they_were_assigned_to(api):
    """PRD §3.4: "The eligible pool is every wave on the departure's own port call whose `priority_class` is `EXCURSION_PRIORITY`, whose `window_end_utc` is at or before the departure's `meeting_time_utc` (a wave ending exactly at the meeting time is eligible), and whose `assigned_guest_count` plus the departure's whole `total_capacity` is at most its `guest_capacity` (an exact fit is eligible)."
    PRD §3.4: "Among the eligible pool the wave with the latest `window_end_utc` wins, because it keeps the group waiting on the pier for the shortest time; ties are broken by the lower `wave_index`, and then by the earlier `created_at`."
    PRD §3.4: "On success the departure's `tender_wave_id` becomes the winner's identifier, the winner's `assigned_guest_count` grows by the departure's `total_capacity` and its `assigned_departure_count` by 1, and both projections are recomputed — assigning a wave removes the 20-minute penalty and may simultaneously floor the actual-basis start."
    PRD §3.4: "Departures may be listed narrowed by `excursion_id`, `port_call_id`, `meeting_point_id`, `tender_wave_id` and `status`."
    PRD §2.3: "For each list response, `meta` carries `limit`, `offset`, `total_count` — the number of rows matching the filter before the window is applied — and `has_more`, true exactly when rows remain beyond the current window."

    Design: Corner/endpoints/departures_can_be_listed_by_the_tender_wave_they_were_assigned_to
    """
    world = fixtures.setup_selling_departure(
        api,
        tender=True,
        meeting_point={"name": "Tender Pontoon 2", "zone": "TENDER_PONTOON"},
        tender_waves=[
            {
                "wave_index": 1,
                "window_start_utc": "2026-09-15T07:30:00Z",
                "window_end_utc": "2026-09-15T08:00:00Z",
            },
            {
                "wave_index": 2,
                "window_start_utc": "2026-09-15T08:20:00Z",
                "window_end_utc": "2026-09-15T08:50:00Z",
            },
        ],
    )
    early_wave, late_wave = world.tender_waves
    assert world.departure["tender_wave_id"] == late_wave["id"]

    rows, meta = validate_paginated(
        api.list_departures(
            TEST_USERS["manager_headers"],
            params={"tender_wave_id": late_wave["id"], "status": "SELLING"},
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == world.departure["id"]

    empty_rows, empty_meta = validate_paginated(
        api.list_departures(
            TEST_USERS["manager_headers"],
            params={"tender_wave_id": early_wave["id"]},
        )
    )
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False
    assert empty_rows == []


def test_dispatch_is_refused_once_the_delay_drives_the_actual_band_red(api):
    """PRD §3.1: "Each report adds to `delay_minutes`, which may never be negative, and `effective_arrival_utc` is recomputed as `arrival_utc` shifted later by `delay_minutes`."
    PRD §3.1: "Every departure on the call has its actual-basis projection and `timing_risk_band_actual` recomputed on the spot, and the recomputation can cascade: each departure that is `SELLING` and whose `timing_risk_band_actual` has just become `RED` moves `SELLING → CLOSED`, and each of that departure's never-charged bookings — those still in `BOOKED` with `financial_status` `AUTHORIZED` — moves to `CANCELLED_BY_LINE` with `financial_status` `VOIDED`, an `AUTH_VOID` ledger entry of `amount_cents` 0 on the `LINE_CANCELLED_OPERATIONAL` `basis`, and its seats returned to its own channel bucket."
    PRD §3.4: "So when a wave is assigned, the start is the later of `meeting_time_utc` and the wave's `window_end_utc` advanced by the call's `delay_minutes`; when no wave is assigned, the start is `meeting_time_utc` advanced by `delay_minutes`."
    PRD §3.4: "`projected_return_actual_utc` is that start advanced by the same ashore leg, and `slack_minutes_actual` is the minutes from it to `all_aboard_utc`, less `risk_buffer_minutes`."
    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."
    PRD §3.6: "Four conditions must hold: the owning port call is `IN_PORT`, else `ERR_INVALID_DEPARTURE_STATE`; at least one booking on the departure has reached `CHECKED_IN`, else `ERR_INVALID_DEPARTURE_STATE`; at a `TENDER` port the departure has a `tender_wave_id` assigned, else `ERR_NO_ELIGIBLE_TENDER_WAVE`; and `timing_risk_band_actual` is not `RED`, else `ERR_TIMING_RISK_RED`."

    Design: Corner/endpoints/dispatch_is_refused_once_the_delay_drives_the_actual_band_red
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, INSTANTS["CALL_ARRIVAL"])
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])

    port_call = fixtures.record_delay(
        api, world.port_call["id"], 90, reason_code="WEATHER_HOLD"
    )
    assert port_call["delay_minutes"] == 90
    assert datetime.fromisoformat(
        port_call["effective_arrival_utc"].replace("Z", "+00:00")
    ) == datetime.fromisoformat("2026-09-15T09:30:00+00:00")

    validate_error(
        api.departure_operation(
            world.departure["id"],
            {"action": "DISPATCH"},
            TEST_USERS["port_agent_headers"],
        ),
        ApiErrorId.ERR_TIMING_RISK_RED,
    )

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "CLOSED"
    assert datetime.fromisoformat(
        departure["projected_return_actual_utc"].replace("Z", "+00:00")
    ) == datetime.fromisoformat("2026-09-15T16:00:00+00:00")
    assert departure["slack_minutes_actual"] == 0
    assert departure["timing_risk_band_actual"] == "RED"
    assert departure["slack_minutes_scheduled"] == 90
    assert departure["timing_risk_band_scheduled"] == "GREEN"

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "CHECKED_IN"


def test_every_collection_listing_answers_with_the_paginated_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100."
    PRD §2.3: "For each list response, `meta` carries `limit`, `offset`, `total_count` — the number of rows matching the filter before the window is applied — and `has_more`, true exactly when rows remain beyond the current window."

    Design: Corner/endpoints/every_collection_listing_answers_with_the_paginated_envelope
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, INSTANTS["CALL_ARRIVAL"])
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    claim = fixtures.open_claim(
        api, incident["id"], claimed_amount_cents=5000000, basis_code="NEGLIGENCE"
    )
    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL"
    )

    listings = [
        (
            api.list_ports(TEST_USERS["guest_headers"], params={"country_code": "MX"}),
            1,
            world.port["id"],
        ),
        (
            api.list_meeting_points(
                TEST_USERS["desk_headers"], params={"port_id": world.port["id"]}
            ),
            1,
            world.meeting_point["id"],
        ),
        (
            api.list_operators(
                TEST_USERS["manager_headers"],
                params={"port_id": world.port["id"], "vetting_status": "APPROVED"},
            ),
            1,
            world.operator["id"],
        ),
        (
            api.list_safety_audits(
                TEST_USERS["manager_headers"],
                params={"operator_id": world.operator["id"]},
            ),
            1,
            None,
        ),
        (
            api.list_port_calls(
                TEST_USERS["port_agent_headers"], params={"voyage_code": "V2609"}
            ),
            1,
            world.port_call["id"],
        ),
        (
            api.list_tender_waves(
                TEST_USERS["port_agent_headers"],
                params={"port_call_id": world.port_call["id"]},
            ),
            0,
            None,
        ),
        (
            api.list_excursions(
                TEST_USERS["manager_headers"],
                params={"port_id": world.port["id"], "catalog_status": "PUBLISHED"},
            ),
            1,
            world.excursion["id"],
        ),
        (
            api.list_bookings(
                TEST_USERS["desk_headers"],
                params={
                    "departure_id": world.departure["id"],
                    "channel": "PRE_CRUISE",
                },
            ),
            1,
            world.booking["id"],
        ),
        (
            api.list_incidents(
                TEST_USERS["risk_officer_headers"],
                params={"booking_id": world.booking["id"]},
            ),
            1,
            incident["id"],
        ),
        (
            api.list_claims(
                TEST_USERS["risk_officer_headers"],
                params={"operator_id": world.operator["id"]},
            ),
            1,
            claim["id"],
        ),
    ]

    for response, expected_total, expected_row_id in listings:
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert meta["total_count"] == expected_total
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(rows) == expected_total
        if expected_row_id is not None:
            assert rows[0]["id"] == expected_row_id

    windowed_rows, windowed_meta = validate_paginated(
        api.list_commission_statements(
            TEST_USERS["finance_headers"],
            params={
                "operator_id": world.operator["id"],
                "basis": "PROVISIONAL",
                "limit": 1,
                "offset": 0,
            },
        )
    )
    assert windowed_meta["limit"] == 1
    assert windowed_meta["offset"] == 0
    assert windowed_meta["total_count"] == 1
    assert windowed_meta["has_more"] is False
    assert len(windowed_rows) == 1
    assert windowed_rows[0]["id"] == statement["id"]


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------

def test_every_unknown_path_identifier_returns_its_own_not_found(api):
    """PRD §2.8: "7: every identifier in the URL path resolves to a stored row, else that entity's own 404 code."
    PRD §2.9: "Each entity answers with its own code, all of them 404: `ERR_PORT_NOT_FOUND`, `ERR_MEETING_POINT_NOT_FOUND`, `ERR_PORT_CALL_NOT_FOUND`, `ERR_TENDER_WAVE_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_EXCURSION_NOT_FOUND`, `ERR_DEPARTURE_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND`."

    Design: Corner/errors/every_unknown_path_identifier_returns_its_own_not_found
    """
    missing = "11111111-1111-4111-8111-111111111111"
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])

    validate_error(
        api.get_port(missing, TEST_USERS["desk_headers"]),
        ApiErrorId.ERR_PORT_NOT_FOUND,
    )
    validate_error(
        api.get_meeting_point(missing, TEST_USERS["desk_headers"]),
        ApiErrorId.ERR_MEETING_POINT_NOT_FOUND,
    )
    validate_error(
        api.get_port_call(missing, TEST_USERS["port_agent_headers"]),
        ApiErrorId.ERR_PORT_CALL_NOT_FOUND,
    )
    validate_error(
        api.get_tender_wave(missing, TEST_USERS["port_agent_headers"]),
        ApiErrorId.ERR_TENDER_WAVE_NOT_FOUND,
    )
    validate_error(
        api.get_operator(missing, TEST_USERS["vetting_officer_headers"]),
        ApiErrorId.ERR_OPERATOR_NOT_FOUND,
    )
    validate_error(
        api.get_safety_audit(missing, TEST_USERS["vetting_officer_headers"]),
        ApiErrorId.ERR_AUDIT_NOT_FOUND,
    )
    validate_error(
        api.get_excursion(missing, TEST_USERS["manager_headers"]),
        ApiErrorId.ERR_EXCURSION_NOT_FOUND,
    )
    validate_error(
        api.get_departure(missing, TEST_USERS["manager_headers"]),
        ApiErrorId.ERR_DEPARTURE_NOT_FOUND,
    )
    validate_error(
        api.get_guest(missing, TEST_USERS["desk_headers"]),
        ApiErrorId.ERR_GUEST_NOT_FOUND,
    )
    validate_error(
        api.get_booking(missing, TEST_USERS["desk_headers"]),
        ApiErrorId.ERR_BOOKING_NOT_FOUND,
    )
    validate_error(
        api.get_ledger_entry(missing, TEST_USERS["finance_headers"]),
        ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND,
    )
    validate_error(
        api.get_incident(missing, TEST_USERS["risk_officer_headers"]),
        ApiErrorId.ERR_INCIDENT_NOT_FOUND,
    )
    validate_error(
        api.get_claim(missing, TEST_USERS["risk_officer_headers"]),
        ApiErrorId.ERR_CLAIM_NOT_FOUND,
    )
    validate_error(
        api.get_commission_statement(missing, TEST_USERS["finance_headers"]),
        ApiErrorId.ERR_STATEMENT_NOT_FOUND,
    )


def test_writes_against_a_cancelled_departure_are_refused_on_both_paths(api):
    """PRD §2.8: "17: the requested departure operation is declared for the departure's `status` and the owning port call is in the state that operation needs, else `ERR_INVALID_DEPARTURE_STATE`; this covers dispatch without an `IN_PORT` call, completion from anything but `OPERATING`, rebalancing or rescheduling a terminal departure, guest cancellation against a departure that has moved on, and check-in against a departure that is no longer live."
    PRD §2.8: "18: a new booking names a departure whose `status` is `SELLING`, else `ERR_DEPARTURE_NOT_SELLING`; the ticketing action additionally accepts a `CLOSED` departure so guests booked before the cutoff can still be ticketed."
    PRD §3.7: "The departure's `status` becomes `CANCELLED_WEATHER` or `CANCELLED_OPERATIONAL` accordingly and `cancellation_cause` records `WEATHER` or `OPERATIONAL`."
    PRD §3.7: "Cancelling a departure that never sold anything simply releases the assigned tender wave's counters, since there are no bookings to cascade into."

    Design: Corner/errors/writes_against_a_cancelled_departure_are_refused_on_both_paths
    """
    world = fixtures.setup_selling_departure(api)
    guest = fixtures.create_guest(api, voyage_code="V2609")

    cancelled = fixtures.cancel_departure(api, world.departure["id"], "OPERATIONAL")
    assert cancelled["status"] == "CANCELLED_OPERATIONAL"
    assert cancelled["cancellation_cause"] == "OPERATIONAL"
    current_version = cancelled["version"]

    validate_error(
        api.rebalance_allocation(
            world.departure["id"],
            {
                "expected_departure_version": current_version,
                "precruise_allocation": 20,
                "onboard_allocation": 20,
            },
            TEST_USERS["manager_headers"],
        ),
        ApiErrorId.ERR_INVALID_DEPARTURE_STATE,
    )

    validate_error(
        api.create_booking(
            factories.create_booking_payload(
                world.departure["id"], guest["id"], current_version
            ),
            TEST_USERS["desk_headers"],
        ),
        ApiErrorId.ERR_DEPARTURE_NOT_SELLING,
    )

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "CANCELLED_OPERATIONAL"
    assert departure["precruise_allocation"] == 25
    assert departure["precruise_sold_seats"] == 0


def test_issuing_the_final_statement_before_the_all_aboard_close_is_refused(api):
    """PRD §2.8: "22: issuing a `FINAL` statement requires the owning port call to have reached `CLOSED`, else `ERR_PORT_CALL_NOT_CLOSED`."
    PRD §3.1: "The same agent closes the call at the all-aboard deadline, moving `IN_PORT → CLOSED`, permitted only once the logical clock has reached `all_aboard_utc`."
    PRD §3.6: "Completion moves `OPERATING → COMPLETED` and carries the `actual_return_utc` instant at which the group actually got back."
    PRD §3.6: "It is recorded on the departure, and every booking in `CHECKED_IN` moves `CHECKED_IN → COMPLETED`."
    PRD §3.9: "The new statement is created in `DRAFT` with `issued_at` and `settled_at` both absent, and all nine waterfall steps computed onto it."
    PRD §3.9: "It requires that no liability claim for the same operator and port call is in `SUBMITTED`, `UNDER_OPERATOR_REVIEW` or `DISPUTED`, else `ERR_OPEN_CLAIM_BLOCKS_ISSUE`, because money does not move while liability is unresolved; and on a `FINAL` `basis` it additionally requires the owning port call to have reached `CLOSED`, else `ERR_PORT_CALL_NOT_CLOSED`, since the final basis is not knowable until the all-aboard deadline has passed and every booking has reached a terminal fulfillment state."

    Design: Corner/errors/issuing_the_final_statement_before_the_all_aboard_close_is_refused
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, INSTANTS["CALL_ARRIVAL"])
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:30:00Z")
    fixtures.complete_departure(
        api, world.departure["id"], "2026-09-15T14:30:00Z"
    )
    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="FINAL"
    )
    assert statement["status"] == "DRAFT"

    validate_error(
        api.statement_transition(
            statement["id"], {"action": "ISSUE"}, TEST_USERS["finance_headers"]
        ),
        ApiErrorId.ERR_PORT_CALL_NOT_CLOSED,
    )

    stored = validate_success(
        api.get_commission_statement(statement["id"], TEST_USERS["finance_headers"]),
        200,
    )
    assert stored["status"] == "DRAFT"
    assert stored["basis"] == "FINAL"
    assert stored.get("issued_at") is None

    port_call = validate_success(
        api.get_port_call(world.port_call["id"], TEST_USERS["port_agent_headers"]), 200
    )
    assert port_call["status"] == "IN_PORT"

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "COMPLETED"


def test_the_four_vetting_gates_each_refuse_their_own_defect(api):
    """PRD §3.2: "The operator is born in `vetting_status` `DRAFT` with `vetting_cycle_count` 0, `safety_score` 0, `reliability_strikes` 0, `liability_reserve_cents` 0 and `latest_audit_auditor_user_id` null."
    PRD §3.2: "Assign base weights of 0.5, 0.3 and 0.2 to the audits in that order, truncated to however many audits are in the window, then divide each base weight by the sum of the base weights actually used, so that with three audits the weights stay 0.5, 0.3 and 0.2, with two they become 0.625 and 0.375, and with one it becomes 1.0."
    PRD §3.2: "The weighted average is the sum of each audit's `raw_score` multiplied by its renormalised weight."
    PRD §3.2: "Submitting moves `DRAFT → SUBMITTED`, and demands two things: at least one safety audit already exists for this operator, else `ERR_AUDIT_REQUIRED`; and `insurance_expiry_date` is strictly later than the logical clock, else `ERR_INSURANCE_EXPIRED`."
    PRD §3.2: "Submission recomputes `safety_score`."
    PRD §3.2: "Four conditions must hold: the approving `X-User-ID` differs from `latest_audit_auditor_user_id`, else `ERR_AUDITOR_CANNOT_APPROVE`; `insurance_expiry_date` is strictly later than the logical clock, else `ERR_INSURANCE_EXPIRED`; `insurance_liability_limit_cents` is at least 100000000 — one million currency units of per-occurrence cover — else `ERR_INSURANCE_LIMIT_INSUFFICIENT`; and `safety_score` is at least 60, else `ERR_SAFETY_SCORE_BELOW_FLOOR`."

    Design: Corner/errors/the_four_vetting_gates_each_refuse_their_own_defect
    """
    world = fixtures.setup_port_world(api)

    without_audit = fixtures.create_operator(
        api, world.port["id"], legal_name="Reef Runners A", contact_email="a@ops.example"
    )
    validate_error(
        api.vetting_action(
            without_audit["id"],
            {"action": "SUBMIT"},
            TEST_USERS["vetting_officer_headers"],
        ),
        ApiErrorId.ERR_AUDIT_REQUIRED,
    )

    lapsed_cover = fixtures.create_operator(
        api,
        world.port["id"],
        legal_name="Reef Runners B",
        contact_email="b@ops.example",
        insurance_expiry_date="2026-07-01T00:00:00Z",
    )
    fixtures.record_safety_audit(api, lapsed_cover["id"])
    validate_error(
        api.vetting_action(
            lapsed_cover["id"],
            {"action": "SUBMIT"},
            TEST_USERS["vetting_officer_headers"],
        ),
        ApiErrorId.ERR_INSURANCE_EXPIRED,
    )

    thin_cover = fixtures.create_operator(
        api,
        world.port["id"],
        legal_name="Reef Runners C",
        contact_email="c@ops.example",
        insurance_liability_limit_cents=99999999,
    )
    fixtures.record_safety_audit(api, thin_cover["id"])
    fixtures.vetting_action(api, thin_cover["id"], "SUBMIT")
    validate_error(
        api.vetting_action(
            thin_cover["id"],
            {"action": "APPROVE"},
            TEST_USERS["vetting_officer_headers"],
        ),
        ApiErrorId.ERR_INSURANCE_LIMIT_INSUFFICIENT,
    )

    weak_score = fixtures.create_operator(
        api, world.port["id"], legal_name="Reef Runners D", contact_email="d@ops.example"
    )
    fixtures.record_safety_audit(api, weak_score["id"], raw_score=50)
    fixtures.vetting_action(api, weak_score["id"], "SUBMIT")
    validate_error(
        api.vetting_action(
            weak_score["id"],
            {"action": "APPROVE"},
            TEST_USERS["vetting_officer_headers"],
        ),
        ApiErrorId.ERR_SAFETY_SCORE_BELOW_FLOOR,
    )

    assert fixtures.get_operator(api, without_audit["id"])["vetting_status"] == "DRAFT"
    assert fixtures.get_operator(api, lapsed_cover["id"])["vetting_status"] == "DRAFT"
    assert fixtures.get_operator(api, thin_cover["id"])["vetting_status"] == "SUBMITTED"
    weak_stored = fixtures.get_operator(api, weak_score["id"])
    assert weak_stored["vetting_status"] == "SUBMITTED"
    assert weak_stored["safety_score"] == 50


def test_the_mobility_language_and_voyage_gates_each_refuse_their_own_defect(api):
    """PRD §3.5: "The guest's `mobility_level` ranks `WHEELCHAIR` at 1, `ASSISTED` at 2 and `FULL` at 3."
    PRD §3.5: "The excursion's `mobility_level` requires rank 1 for `LEVEL_1`, rank 2 for `LEVEL_2`, and rank 3 for both `LEVEL_3` and `LEVEL_4`."
    PRD §3.5: "A guest whose rank is below the required rank is refused with `ERR_MOBILITY_RESTRICTION`."
    PRD §3.5: "Language fourth: `language_choice` must be a member of the excursion's `languages`, else `ERR_LANGUAGE_UNAVAILABLE`."
    PRD §3.5: "The guest's `voyage_code` must equal the `voyage_code` of the port call the departure runs on, else `ERR_VOYAGE_MISMATCH` — nobody books ashore time on a voyage they are not sailing."
    PRD §3.5: "`precruise_sold_seats` counts the seats consumed by bookings on this departure whose `channel` is `PRE_CRUISE` and whose `fulfillment_status` is neither `CANCELLED_BY_GUEST` nor `CANCELLED_BY_LINE`; `onboard_sold_seats` counts the same for `ONBOARD`."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/errors/the_mobility_language_and_voyage_gates_each_refuse_their_own_defect
    """
    world = fixtures.setup_selling_departure(api)
    version = fixtures.get_departure_version(api, world.departure["id"])

    wheelchair_guest = fixtures.create_guest(
        api, full_name="Wren Alba", mobility_level="WHEELCHAIR"
    )
    validate_error(
        api.create_booking(
            factories.create_booking_payload(
                world.departure["id"], wheelchair_guest["id"], version
            ),
            TEST_USERS["desk_headers"],
        ),
        ApiErrorId.ERR_MOBILITY_RESTRICTION,
    )

    german_guest = fixtures.create_guest(api, full_name="Lior Danes")
    validate_error(
        api.create_booking(
            factories.create_booking_payload(
                world.departure["id"],
                german_guest["id"],
                version,
                language_choice="DE",
            ),
            TEST_USERS["desk_headers"],
        ),
        ApiErrorId.ERR_LANGUAGE_UNAVAILABLE,
    )

    other_voyage_guest = fixtures.create_guest(
        api, full_name="Vero Nunes", voyage_code="V2610"
    )
    validate_error(
        api.create_booking(
            factories.create_booking_payload(
                world.departure["id"], other_voyage_guest["id"], version
            ),
            TEST_USERS["desk_headers"],
        ),
        ApiErrorId.ERR_VOYAGE_MISMATCH,
    )

    rows, meta = validate_paginated(
        api.list_bookings(
            TEST_USERS["desk_headers"], params={"departure_id": world.departure["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 0
    assert departure["version"] == version


def test_the_medical_acknowledgement_is_demanded_only_where_the_flag_sets_intersect(api):
    """PRD §3.5: "A booking names the `departure_id` and the `guest_id` of the lead guest whose age, mobility and medical flags gate the whole party, a `party_size` between 1 and 20 inclusive, a `channel` of `PRE_CRUISE` or `ONBOARD`, a `language_choice` from the same seven-language set, the `expected_departure_version` demanded by §2.7, and an optional `medical_warning_acknowledged` boolean that defaults to false."
    PRD §3.5: "Intersect the guest's `medical_flags` with the excursion's `medical_warning_codes`; if that intersection is non-empty and `medical_warning_acknowledged` is not true, the booking is refused with `ERR_MEDICAL_ACK_REQUIRED`."
    PRD §3.5: "When the intersection is empty the acknowledgement flag is simply ignored, whatever its value."
    PRD §3.5: "A new booking is created with `fulfillment_status` `BOOKED`, `financial_status` `AUTHORIZED`, `alternative_offer_status` `NONE`, `alternative_departure_id` absent, `return_guarantee_honored` true, `commission_accrued_cents` 0, `refunded_cents` 0, `retained_cents` 0 and `goodwill_credit_cents` 0."
    PRD §3.5: "Before the release, the effective allocations are simply `precruise_allocation` and `onboard_allocation` as stored."
    PRD §3.5: "From those, `effective_precruise_available` is the effective pre-cruise allocation less `precruise_sold_seats`, floored at 0, and `effective_onboard_available` is the effective onboard allocation less `onboard_sold_seats`, floored at 0."

    Design: Corner/errors/the_medical_acknowledgement_is_demanded_only_where_the_flag_sets_intersect
    """
    world = fixtures.setup_selling_departure(
        api,
        excursion={"medical_warning_codes": ["MOTION_SICKNESS", "ALTITUDE"]},
    )
    version = fixtures.get_departure_version(api, world.departure["id"])

    intersecting_guest = fixtures.create_guest(
        api, full_name="Mira Oyelaran", medical_flags=["MOTION_SICKNESS"]
    )
    validate_error(
        api.create_booking(
            factories.create_booking_payload(
                world.departure["id"], intersecting_guest["id"], version, party_size=1
            ),
            TEST_USERS["desk_headers"],
        ),
        ApiErrorId.ERR_MEDICAL_ACK_REQUIRED,
    )

    disjoint_guest = fixtures.create_guest(
        api, full_name="Cass Iwu", medical_flags=["CARDIAC"]
    )
    booking = fixtures.create_booking(
        api, world.departure["id"], disjoint_guest["id"], party_size=1
    )
    assert booking["medical_warning_acknowledged"] is False
    assert booking["party_size"] == 1
    assert booking["fulfillment_status"] == "BOOKED"
    assert booking["financial_status"] == "AUTHORIZED"

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 1
    assert departure["effective_precruise_available"] == 24


def test_a_meeting_time_before_the_ships_arrival_is_refused(api):
    """PRD §3.1: "The port-call lifecycle runs `PLANNED → OPEN_FOR_SALE → IN_PORT → CLOSED`, with `CANCELLED` reachable from either of the first two states."
    PRD §3.4: "The `meeting_time_utc` must fall inside the port call's inclusive published window from `arrival_utc` to `all_aboard_utc` — measured against the published schedule, not against a delayed `effective_arrival_utc` — else `ERR_MEETING_TIME_OUTSIDE_CALL`."
    PRD §2.3: "For each list response, `meta` carries `limit`, `offset`, `total_count` — the number of rows matching the filter before the window is applied — and `has_more`, true exactly when rows remain beyond the current window."

    Design: Corner/errors/a_meeting_time_before_the_ships_arrival_is_refused
    """
    world = fixtures.setup_catalog_world(api)
    port_call = fixtures.create_port_call(api, world.port["id"])
    fixtures.open_port_call_sales(api, port_call["id"])

    validate_error(
        api.create_departure(
            factories.create_departure_payload(
                world.excursion["id"],
                port_call["id"],
                world.meeting_point["id"],
                meeting_time_utc="2026-09-15T07:00:00Z",
            ),
            TEST_USERS["manager_headers"],
        ),
        ApiErrorId.ERR_MEETING_TIME_OUTSIDE_CALL,
    )

    rows, meta = validate_paginated(
        api.list_departures(
            TEST_USERS["manager_headers"], params={"port_call_id": port_call["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    stored_call = validate_success(
        api.get_port_call(port_call["id"], TEST_USERS["port_agent_headers"]), 200
    )
    assert stored_call["status"] == "OPEN_FOR_SALE"


def test_the_third_dispute_round_is_refused(api):
    """PRD §3.8: "From `FILED` the `RiskOfficer` either closes it without a claim, moving `FILED → CLOSED_NO_CLAIM` and optionally recording a `resolution_note`, or opens a claim, moving `FILED → CLAIM_OPENED`."
    PRD §3.8: "Sending the claim to the operator moves `SUBMITTED → UNDER_OPERATOR_REVIEW`, permitted only while the operator's `vetting_status` is not `TERMINATED`, else `ERR_INVALID_CLAIM_ACTION`."
    PRD §3.8: "Recording the operator's rebuttal moves `UNDER_OPERATOR_REVIEW → DISPUTED` and increases `dispute_round_count` by 1, permitted only while `dispute_round_count` is below 2, else `ERR_DISPUTE_ROUNDS_EXHAUSTED`."
    PRD §3.8: "Sending a disputed claim back moves `DISPUTED → UNDER_OPERATOR_REVIEW`, permitted while `dispute_round_count` is at most 2, else the same `ERR_DISPUTE_ROUNDS_EXHAUSTED`."
    PRD §3.8: "The loop `UNDER_OPERATOR_REVIEW → DISPUTED → UNDER_OPERATOR_REVIEW` therefore runs at most twice."

    Design: Corner/errors/the_third_dispute_round_is_refused
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, INSTANTS["CALL_ARRIVAL"])
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=5000000)

    opener = TEST_USERS["risk_officer_headers"]
    fixtures.claim_action(api, claim["id"], "SEND_TO_OPERATOR", headers=opener)
    first_dispute = fixtures.claim_action(
        api, claim["id"], "RECORD_DISPUTE", headers=opener
    )
    assert first_dispute["dispute_round_count"] == 1
    fixtures.claim_action(api, claim["id"], "SEND_TO_OPERATOR", headers=opener)
    second_dispute = fixtures.claim_action(
        api, claim["id"], "RECORD_DISPUTE", headers=opener
    )
    assert second_dispute["dispute_round_count"] == 2
    returned = fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR", headers=opener
    )
    assert returned["status"] == "UNDER_OPERATOR_REVIEW"

    validate_error(
        api.claim_action(claim["id"], {"action": "RECORD_DISPUTE"}, opener),
        ApiErrorId.ERR_DISPUTE_ROUNDS_EXHAUSTED,
    )

    stored_claim = validate_success(api.get_claim(claim["id"], opener), 200)
    assert stored_claim["status"] == "UNDER_OPERATOR_REVIEW"
    assert stored_claim["dispute_round_count"] == 2

    stored_incident = validate_success(api.get_incident(incident["id"], opener), 200)
    assert stored_incident["status"] == "CLAIM_OPENED"


def test_an_adjudication_beyond_the_operators_cover_is_refused(api):
    """PRD §3.2: "The operator is born in `vetting_status` `DRAFT` with `vetting_cycle_count` 0, `safety_score` 0, `reliability_strikes` 0, `liability_reserve_cents` 0 and `latest_audit_auditor_user_id` null."
    PRD §3.8: "The claim is created in `status` `SUBMITTED` with `submitted_by_user_id` from the header, `dispute_round_count` 0, and `liability_share_bps`, `settlement_amount_cents`, `operator_charge_cents` and `adjudicated_by_user_id` all at their zero or absent defaults."
    PRD §3.8: "Sending the claim to the operator moves `SUBMITTED → UNDER_OPERATOR_REVIEW`, permitted only while the operator's `vetting_status` is not `TERMINATED`, else `ERR_INVALID_CLAIM_ACTION`."
    PRD §3.8: "The `operator_charge_cents` actually charged to the operator is `settlement_amount_cents` multiplied by `liability_share_bps`, divided by ten thousand, rounded half up, and it may not exceed the operator's `insurance_liability_limit_cents` — the limit itself is acceptable — else `ERR_CLAIM_EXCEEDS_INSURANCE_LIMIT`."
    PRD §3.8: "The operator's `liability_reserve_cents` grows by that amount."

    Design: Corner/errors/an_adjudication_beyond_the_operators_cover_is_refused
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, INSTANTS["CALL_ARRIVAL"])
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=500000000)
    fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR", headers=TEST_USERS["risk_officer_headers"]
    )

    validate_error(
        api.claim_action(
            claim["id"],
            {
                "action": "ADJUDICATE_UPHELD",
                "liability_share_bps": 4000,
                "settlement_amount_cents": 500000000,
            },
            TEST_USERS["second_risk_officer_headers"],
        ),
        ApiErrorId.ERR_CLAIM_EXCEEDS_INSURANCE_LIMIT,
    )

    stored_claim = validate_success(
        api.get_claim(claim["id"], TEST_USERS["risk_officer_headers"]), 200
    )
    assert stored_claim["status"] == "UNDER_OPERATOR_REVIEW"
    assert stored_claim["operator_charge_cents"] == 0
    assert stored_claim.get("adjudicated_by_user_id") is None

    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["liability_reserve_cents"] == 0

    stored_incident = validate_success(
        api.get_incident(incident["id"], TEST_USERS["risk_officer_headers"]), 200
    )
    assert stored_incident["status"] == "CLAIM_OPENED"


def test_a_party_larger_than_its_own_channel_bucket_is_refused(api):
    """PRD §3.5: "`precruise_sold_seats` counts the seats consumed by bookings on this departure whose `channel` is `PRE_CRUISE` and whose `fulfillment_status` is neither `CANCELLED_BY_GUEST` nor `CANCELLED_BY_LINE`; `onboard_sold_seats` counts the same for `ONBOARD`."
    PRD §3.5: "`seats_available_total` is `total_capacity` less both sold counts."
    PRD §3.5: "Before the release, the effective allocations are simply `precruise_allocation` and `onboard_allocation` as stored."
    PRD §3.5: "From those, `effective_precruise_available` is the effective pre-cruise allocation less `precruise_sold_seats`, floored at 0, and `effective_onboard_available` is the effective onboard allocation less `onboard_sold_seats`, floored at 0."
    PRD §3.5: "A booking is admitted only when its `party_size` is at most the effective available seats of its own `channel`; otherwise it is refused with `ERR_CHANNEL_ALLOCATION_EXHAUSTED`."
    PRD §3.5: "Note carefully that `seats_available_total` may be positive while the requested channel is exhausted — an exhausted channel refuses the sale even with free seats on the departure — and that every pre-cruise request made at or after the release is refused here."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/errors/a_party_larger_than_its_own_channel_bucket_is_refused
    """
    world = fixtures.setup_selling_departure(
        api, departure={"precruise_allocation": 4, "onboard_allocation": 36}
    )
    first_guest = fixtures.create_guest(api, voyage_code="V2609")
    fixtures.create_booking(
        api, world.departure["id"], first_guest["id"], party_size=4
    )

    sold_out = fixtures.get_departure(api, world.departure["id"])
    assert sold_out["precruise_sold_seats"] == 4
    assert sold_out["effective_precruise_available"] == 0
    assert sold_out["effective_onboard_available"] == 36
    assert sold_out["seats_available_total"] == 36

    second_guest = fixtures.create_guest(
        api, full_name="Nils Berg", voyage_code="V2609"
    )
    validate_error(
        api.create_booking(
            factories.create_booking_payload(
                world.departure["id"],
                second_guest["id"],
                sold_out["version"],
                party_size=1,
            ),
            TEST_USERS["desk_headers"],
        ),
        ApiErrorId.ERR_CHANNEL_ALLOCATION_EXHAUSTED,
    )

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["version"] == sold_out["version"]
    assert departure["precruise_sold_seats"] == 4
    assert departure["seats_available_total"] == 36
