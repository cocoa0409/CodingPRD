"""Cross-entity gating, interval semantics on shared resources, and the seat and
money conservation identities that must survive a whole sequence of operations.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import INSTANTS
from test_helpers.test_users import TEST_USERS

CHECKIN_CLOCK = "2026-09-15T08:30:00Z"


# ---------------------------------------------------------------------------
# Excursion x TourOperator: publication is gated on the operator's standing
# ---------------------------------------------------------------------------

def test_publish_is_refused_while_the_owning_operator_is_still_submitted(api):
    """PRD §3.3: "The owning operator's `vetting_status` must be `APPROVED`, else `ERR_OPERATOR_NOT_APPROVED`."
    PRD §3.3: "The item is created in `catalog_status` `DRAFT` with `published_at` null."

    Design: Difficulty/cross_entity_state_dependency/excursion_publish_is_gated_on_the_owning_operator_reaching_approved
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(api)
    meeting_point = fixtures.create_meeting_point(api, port["id"])
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(api, operator["id"])
    operator = fixtures.vetting_action(api, operator["id"], "SUBMIT")
    assertions.assert_field_values(operator, vetting_status="SUBMITTED")

    excursion = fixtures.create_excursion(api, port["id"], operator["id"])
    excursion = fixtures.catalog_action(api, excursion["id"], "SUBMIT_REVIEW")
    assertions.assert_field_values(excursion, catalog_status="PENDING_REVIEW")
    assert excursion["languages"] == ["EN", "ES"], excursion["languages"]

    port_call = fixtures.create_port_call(api, port["id"])
    fixtures.open_port_call_sales(api, port_call["id"])
    departure = fixtures.create_departure(
        api, excursion["id"], port_call["id"], meeting_point["id"]
    )
    assertions.assert_field_values(departure, status="SCHEDULED")

    refused = api.catalog_action(
        excursion["id"], {"action": "PUBLISH"}, TEST_USERS["manager_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_OPERATOR_NOT_APPROVED.value)

    after = validate_success(
            api.get_excursion(excursion["id"], TEST_USERS["manager_headers"]), 200
        )
    
    assertions.assert_field_values(after, catalog_status="PENDING_REVIEW")
    assert after.get("published_at") is None, after.get("published_at")
    assertions.assert_no_version_drift(excursion, after)
    assertions.assert_field_values(
        fixtures.get_departure(api, departure["id"]), status="SCHEDULED"
    )


def test_approving_the_operator_unblocks_publish_and_drags_the_departure_to_selling(api):
    """PRD §3.3: "Publication records `published_at` as the logical-clock instant, and it opens sales downstream: every departure of this excursion that is still `SCHEDULED` and whose port call is `OPEN_FOR_SALE` moves `SCHEDULED → SELLING`."
    PRD §3.4: "The scheduled band's one job happens at the `SCHEDULED → SELLING` transition, which freezes `return_guarantee_eligible` to true exactly when the excursion's `return_guarantee` is true and `timing_risk_band_scheduled` is not `RED` at that instant."

    Design: Difficulty/cross_entity_state_dependency/excursion_publish_is_gated_on_the_owning_operator_reaching_approved
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(api)
    meeting_point = fixtures.create_meeting_point(api, port["id"])
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(api, operator["id"])
    fixtures.vetting_action(api, operator["id"], "SUBMIT")

    excursion = fixtures.create_excursion(api, port["id"], operator["id"])
    fixtures.catalog_action(api, excursion["id"], "SUBMIT_REVIEW")
    port_call = fixtures.create_port_call(api, port["id"])
    fixtures.open_port_call_sales(api, port_call["id"])
    departure = fixtures.create_departure(
        api, excursion["id"], port_call["id"], meeting_point["id"]
    )

    validate_error(
        api.catalog_action(
            excursion["id"], {"action": "PUBLISH"}, TEST_USERS["manager_headers"]
        ),
        ApiErrorId.ERR_OPERATOR_NOT_APPROVED.value,
    )

    operator = fixtures.vetting_action(api, operator["id"], "APPROVE")
    assertions.assert_field_values(operator, vetting_status="APPROVED")

    published = fixtures.catalog_action(api, excursion["id"], "PUBLISH")
    assertions.assert_field_values(published, catalog_status="PUBLISHED")
    assert published["published_at"].startswith("2026-08-01T00:00:00"), (
        published["published_at"]
    )

    reread = fixtures.get_departure(api, departure["id"])
    assertions.assert_field_values(
        reread, status="SELLING", return_guarantee_eligible=False
    )


# ---------------------------------------------------------------------------
# CommissionStatement x LiabilityClaim: issue is gated sideways on the
# (operator, port call) tuple
# ---------------------------------------------------------------------------

def test_statement_issue_is_refused_while_a_claim_for_the_pair_is_under_operator_review(api):
    """PRD §3.9: "It requires that no liability claim for the same operator and port call is in `SUBMITTED`, `UNDER_OPERATOR_REVIEW` or `DISPUTED`, else `ERR_OPEN_CLAIM_BLOCKS_ISSUE`, because money does not move while liability is unresolved; and on a `FINAL` `basis` it additionally requires the owning port call to have reached `CLOSED`, else `ERR_PORT_CALL_NOT_CLOSED`, since the final basis is not knowable until the all-aboard deadline has passed and every booking has reached a terminal fulfillment state."

    Design: Difficulty/cross_entity_state_dependency/statement_issue_is_gated_on_no_open_liability_claim_for_the_same_operator_and_port_call
    """
    world = fixtures.setup_selling_departure(api)
    _, booking = fixtures.create_guest_and_booking(
        api, world, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    fixtures.ticket_booking(api, booking["id"])

    fixtures.set_clock(api, CHECKIN_CLOCK)
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.check_in_booking(api, booking["id"])

    incident = fixtures.file_incident(
        api,
        booking["id"],
        category="SERVICE_FAILURE",
        severity="MODERATE",
        occurred_utc=CHECKIN_CLOCK,
        narrative="Snorkel gear failure reported by the guest before the sailing.",
    )
    claim = fixtures.open_claim(
        api, incident["id"], claimed_amount_cents=60000,
        basis_code="EQUIPMENT_FAILURE",
    )
    claim = fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR",
        headers=TEST_USERS["risk_officer_headers"],
    )
    assertions.assert_field_values(claim, status="UNDER_OPERATOR_REVIEW")

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL"
    )
    assertions.assert_field_values(statement, status="DRAFT")

    refused = api.statement_transition(
        statement["id"], {"action": "ISSUE"}, TEST_USERS["finance_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_ISSUE.value)

    after = validate_success(
            api.get_commission_statement(
                statement["id"], TEST_USERS["finance_headers"]
            ),
            200,
        )
    
    assertions.assert_field_values(after, status="DRAFT")
    assert after.get("issued_at") is None, after.get("issued_at")
    assertions.assert_no_version_drift(statement, after)


def test_denying_the_claim_unblocks_issue_without_touching_the_waterfall_figures(api):
    """PRD §3.8: "Denying a claim moves it to `ADJUDICATED_DENIED`, a terminal state, requires only the same segregation-of-duties check, moves no money, and closes the incident `CLAIM_OPENED → CLOSED_DENIED`."
    PRD §3.9: "Issuing moves `DRAFT → ISSUED`, re-runs and freezes all nine steps onto the row, and stamps `issued_at` with the logical-clock instant."
    PRD §3.9: "Step two charges the port infrastructure fee on gross, before any commission is deducted: `port_fee_cents` is 250 basis points of `gross_ticket_cents` rounded half up."
    PRD §3.9: "Step four sets `claim_offset_cents` to the exact sum of `operator_charge_cents` over the liability claims for the same operator and port call whose `status` is `ADJUDICATED_UPHELD` or `SETTLED`."
    PRD §3.9: "Step six computes `payable_pre_rebate_cents` as `gross_ticket_cents` less `port_fee_cents`, less `line_commission_cents`, less `claim_offset_cents`, less `operational_penalty_cents`, floored at zero — all exact integer arithmetic."

    Design: Difficulty/cross_entity_state_dependency/statement_issue_is_gated_on_no_open_liability_claim_for_the_same_operator_and_port_call
    """
    world = fixtures.setup_selling_departure(api)
    _, booking = fixtures.create_guest_and_booking(
        api, world, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    booking = fixtures.ticket_booking(api, booking["id"])
    assertions.assert_field_values(
        booking, quoted_total_cents=48508, service_fee_cents=1455,
        charge_total_cents=49963, financial_status="CHARGED",
    )

    fixtures.set_clock(api, CHECKIN_CLOCK)
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.check_in_booking(api, booking["id"])

    incident = fixtures.file_incident(
        api,
        booking["id"],
        category="SERVICE_FAILURE",
        severity="MODERATE",
        occurred_utc=CHECKIN_CLOCK,
        narrative="Snorkel gear failure reported by the guest before the sailing.",
    )
    claim = fixtures.open_claim(
        api, incident["id"], claimed_amount_cents=60000,
        basis_code="EQUIPMENT_FAILURE",
    )
    fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR",
        headers=TEST_USERS["risk_officer_headers"],
    )
    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL"
    )
    validate_error(
        api.statement_transition(
            statement["id"], {"action": "ISSUE"}, TEST_USERS["finance_headers"]
        ),
        ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_ISSUE.value,
    )

    denied = fixtures.adjudicate_denied(api, claim["id"])
    assertions.assert_field_values(denied, status="ADJUDICATED_DENIED")
    incident_after = validate_success(
            api.get_incident(incident["id"], TEST_USERS["risk_officer_headers"]), 200
        )
    
    assertions.assert_field_values(incident_after, status="CLOSED_DENIED")

    issued = fixtures.statement_transition(api, statement["id"], "ISSUE")
    assertions.assert_field_values(
        issued,
        status="ISSUED",
        basis="PROVISIONAL",
        booking_line_count=1,
        gross_ticket_cents=48508,
        port_fee_cents=1213,
        line_commission_cents=8731,
        claim_offset_cents=0,
        operational_penalty_cents=0,
        payable_pre_rebate_cents=38564,
        rebate_bps=0,
        rebate_cents=0,
        adjustment_cents=0,
        operator_payable_cents=38564,
    )
    assert issued["issued_at"].startswith("2026-09-15T08:30:00"), issued["issued_at"]


# ---------------------------------------------------------------------------
# Booking x PortCall: check-in is gated on the ship actually being alongside
# ---------------------------------------------------------------------------

def test_check_in_inside_the_window_is_refused_while_the_port_call_is_not_in_port(api):
    """PRD §3.6: "Check-in moves `TICKETED → CHECKED_IN` and needs the owning port call to be `IN_PORT`, else `ERR_INVALID_BOOKING_ACTION`, and the departure's `status` to still be `SELLING` or `CLOSED`, else `ERR_INVALID_DEPARTURE_STATE`."
    PRD §3.6: "It is permitted only while the logical clock lies inside the inclusive window running from 45 minutes before `meeting_time_utc` to 10 minutes after it; outside that window it is refused with `ERR_CHECKIN_WINDOW_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/booking_check_in_is_gated_on_the_port_call_reaching_in_port
    """
    world = fixtures.setup_ticketed_booking(api, booking={"party_size": 4})
    assertions.assert_field_values(world.port_call, status="OPEN_FOR_SALE")

    # 08:30Z sits inside the inclusive check-in window [08:15Z, 09:10Z].
    fixtures.set_clock(api, CHECKIN_CLOCK)

    refused = api.fulfillment_action(
        world.booking["id"], {"action": "CHECK_IN"}, TEST_USERS["desk_headers"]
    )
    # The window is open, so the refusal is the port-call gate and not
    # ERR_CHECKIN_WINDOW_CLOSED.
    validate_error(refused, ApiErrorId.ERR_INVALID_BOOKING_ACTION.value)

    after = fixtures.get_booking(api, world.booking["id"])
    assertions.assert_field_values(
        after, fulfillment_status="TICKETED", financial_status="CHARGED"
    )
    assertions.assert_no_version_drift(world.booking, after)


def test_arriving_the_ship_unblocks_the_identical_check_in_request(api):
    """PRD §3.1: "A `PortAgent` marks arrival, moving `OPEN_FOR_SALE → IN_PORT`, and may do so only once the logical clock has reached `effective_arrival_utc`; earlier, the request is `ERR_INVALID_PORT_CALL_ACTION`."
    PRD §3.6: "Check-in moves `TICKETED → CHECKED_IN` and needs the owning port call to be `IN_PORT`, else `ERR_INVALID_BOOKING_ACTION`, and the departure's `status` to still be `SELLING` or `CLOSED`, else `ERR_INVALID_DEPARTURE_STATE`."
    PRD §3.4: "A departure moves `SELLING → CLOSED` when its port call moves `IN_PORT → CLOSED`; when a recorded delay pushes its `timing_risk_band_actual` to `RED`; or when the logical clock reaches 60 minutes before its `meeting_time_utc`."

    Design: Difficulty/cross_entity_state_dependency/booking_check_in_is_gated_on_the_port_call_reaching_in_port
    """
    world = fixtures.setup_ticketed_booking(api, booking={"party_size": 4})
    fixtures.set_clock(api, CHECKIN_CLOCK)

    validate_error(
        api.fulfillment_action(
            world.booking["id"], {"action": "CHECK_IN"}, TEST_USERS["desk_headers"]
        ),
        ApiErrorId.ERR_INVALID_BOOKING_ACTION.value,
    )

    port_call = fixtures.arrive_port_call(api, world.port_call["id"])
    assertions.assert_field_values(port_call, status="IN_PORT")

    checked_in = fixtures.check_in_booking(api, world.booking["id"])
    assertions.assert_field_values(
        checked_in, fulfillment_status="CHECKED_IN", financial_status="CHARGED"
    )
    assertions.assert_field_values(
        fixtures.get_departure(api, world.departure["id"]), status="CLOSED"
    )


# ---------------------------------------------------------------------------
# MeetingPoint: half-open windows, an end-side buffer and an aggregate ceiling
# ---------------------------------------------------------------------------

def test_third_overlapping_group_breaches_the_aggregate_meeting_point_ceiling(api):
    """PRD §3.4: "A departure occupies its meeting point from 15 minutes before its `meeting_time_utc` — the setup period — up to but not including the instant `dispatch_dwell_minutes` plus the meeting point's `slot_buffer_minutes` after its `meeting_time_utc`."
    PRD §3.4: "The check is not pairwise: sweep the candidate's window together with the peers' windows and take the greatest number of windows covering any single instant, counting the candidate itself."
    PRD §3.4: "If that peak exceeds the meeting point's `max_concurrent_groups`, the request is refused with `ERR_MEETING_POINT_CONGESTED` — the violation belongs to the group that pushes the peak over the limit, and no individual pair need be in breach."

    Design: Difficulty/resource_temporal_overlap/meeting_point_windows_are_half_open_with_an_end_side_buffer_and_an_aggregate_group_ceiling
    """
    world = fixtures.setup_selling_departure(
        api,
        meeting_point={
            "name": "Pier Apron A",
            "zone": "PIER_APRON",
            "max_concurrent_groups": 2,
            "slot_buffer_minutes": 10,
        },
    )
    # E1 meets 09:00Z with dwell 20, so it occupies [08:45Z, 09:30Z).
    assertions.assert_field_values(world.departure, status="SELLING")
    # E2 meets 09:10Z with dwell 20, so it occupies [08:55Z, 09:40Z).
    second = fixtures.create_departure(
        api, world.excursion["id"], world.port_call["id"], world.meeting_point["id"],
        meeting_time_utc="2026-09-15T09:10:00Z",
    )
    assertions.assert_field_values(second, status="SELLING")

    # The 09:20Z candidate occupies [09:05Z, 09:50Z), pushing the peak to 3.
    refused = api.create_departure(
        {
            "excursion_id": world.excursion["id"],
            "port_call_id": world.port_call["id"],
            "meeting_point_id": world.meeting_point["id"],
            "meeting_time_utc": "2026-09-15T09:20:00Z",
            "dispatch_dwell_minutes": 20,
            "total_capacity": 40,
            "precruise_allocation": 25,
            "onboard_allocation": 15,
        },
        TEST_USERS["manager_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_MEETING_POINT_CONGESTED.value)

    _, meta = validate_paginated(
        api.list_departures(
            TEST_USERS["manager_headers"],
            params={"meeting_point_id": world.meeting_point["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 2, meta


def test_candidate_starting_where_a_peer_window_ends_is_admitted(api):
    """PRD §3.4: "Two windows collide when they share at least one instant, so a window that ends at exactly the instant another begins does not collide."
    PRD §3.4: "A new departure lands in `status` `SCHEDULED`, or straight into `SELLING` when its excursion is already `PUBLISHED` and its port call is already `OPEN_FOR_SALE`."

    Design: Difficulty/resource_temporal_overlap/meeting_point_windows_are_half_open_with_an_end_side_buffer_and_an_aggregate_group_ceiling
    """
    world = fixtures.setup_selling_departure(
        api,
        meeting_point={
            "name": "Pier Apron A",
            "zone": "PIER_APRON",
            "max_concurrent_groups": 2,
            "slot_buffer_minutes": 10,
        },
    )
    # E1 occupies [08:45Z, 09:30Z); E2 occupies [08:55Z, 09:40Z).
    second = fixtures.create_departure(
        api, world.excursion["id"], world.port_call["id"], world.meeting_point["id"],
        meeting_time_utc="2026-09-15T09:10:00Z",
    )

    # The 09:55Z candidate occupies [09:40Z, 10:25Z) and only touches E2's end.
    admitted = fixtures.create_departure(
        api, world.excursion["id"], world.port_call["id"], world.meeting_point["id"],
        meeting_time_utc="2026-09-15T09:55:00Z",
    )
    assertions.assert_departure(admitted)
    assertions.assert_field_values(admitted, status="SELLING")
    assert admitted["meeting_time_utc"].startswith("2026-09-15T09:55:00"), (
        admitted["meeting_time_utc"]
    )
    assertions.assert_field_values(
        fixtures.get_departure(api, world.departure["id"]), status="SELLING"
    )
    assertions.assert_field_values(
        fixtures.get_departure(api, second["id"]), status="SELLING"
    )

    _, meta = validate_paginated(
        api.list_departures(
            TEST_USERS["manager_headers"],
            params={"meeting_point_id": world.meeting_point["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 3, meta


# ---------------------------------------------------------------------------
# TenderWave: closed windows, so a shared endpoint collides
# ---------------------------------------------------------------------------

def test_wave_starting_at_the_instant_another_ends_collides(api):
    """PRD §3.1: "Wave windows are **closed** intervals with zero buffer and single occupancy: a candidate wave whose window shares even one instant with another non-cancelled wave on the same call is refused with `ERR_TENDER_WAVE_OVERLAP`, and because the interval is closed, a wave beginning at the exact instant another ends does collide — one pontoon cannot serve two waves at that instant."

    Design: Difficulty/resource_temporal_overlap/tender_wave_windows_are_closed_intervals_so_a_shared_endpoint_collides
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_tender_port(api)
    port_call = fixtures.create_port_call(api, port["id"])
    assertions.assert_field_values(port_call, status="PLANNED")
    first = fixtures.create_tender_wave(
        api, port_call["id"], wave_index=1,
        window_start_utc="2026-09-15T08:30:00Z",
        window_end_utc="2026-09-15T08:50:00Z",
        guest_capacity=100, priority_class="EXCURSION_PRIORITY",
    )
    assertions.assert_tender_wave(first)

    refused = api.create_tender_wave(
        port_call["id"],
        {
            "wave_index": 2,
            "window_start_utc": "2026-09-15T08:50:00Z",
            "window_end_utc": "2026-09-15T09:10:00Z",
            "guest_capacity": 100,
            "priority_class": "GENERAL",
        },
        TEST_USERS["port_agent_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_TENDER_WAVE_OVERLAP.value)

    _, meta = validate_paginated(
        api.list_tender_waves(
            TEST_USERS["port_agent_headers"],
            params={"port_call_id": port_call["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, meta


def test_wave_starting_one_minute_after_a_peer_ends_is_admitted(api):
    """PRD §3.1: "Wave windows are **closed** intervals with zero buffer and single occupancy: a candidate wave whose window shares even one instant with another non-cancelled wave on the same call is refused with `ERR_TENDER_WAVE_OVERLAP`, and because the interval is closed, a wave beginning at the exact instant another ends does collide — one pontoon cannot serve two waves at that instant."
    PRD §3.1: "A new wave starts with `assigned_guest_count` and `assigned_departure_count` both 0; each is maintained as the running total over the departures assigned to that wave whose `status` is neither `CANCELLED_WEATHER` nor `CANCELLED_OPERATIONAL`, the former summing those departures' `total_capacity` and the latter counting them."

    Design: Difficulty/resource_temporal_overlap/tender_wave_windows_are_closed_intervals_so_a_shared_endpoint_collides
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_tender_port(api)
    port_call = fixtures.create_port_call(api, port["id"])
    fixtures.create_tender_wave(
        api, port_call["id"], wave_index=1,
        window_start_utc="2026-09-15T08:30:00Z",
        window_end_utc="2026-09-15T08:50:00Z",
        guest_capacity=100, priority_class="EXCURSION_PRIORITY",
    )

    validate_error(
        api.create_tender_wave(
            port_call["id"],
            {
                "wave_index": 2,
                "window_start_utc": "2026-09-15T08:50:00Z",
                "window_end_utc": "2026-09-15T09:10:00Z",
                "guest_capacity": 100,
                "priority_class": "GENERAL",
            },
            TEST_USERS["port_agent_headers"],
        ),
        ApiErrorId.ERR_TENDER_WAVE_OVERLAP.value,
    )

    admitted = fixtures.create_tender_wave(
        api, port_call["id"], wave_index=2,
        window_start_utc="2026-09-15T08:51:00Z",
        window_end_utc="2026-09-15T09:10:00Z",
        guest_capacity=100, priority_class="GENERAL",
    )
    assertions.assert_field_values(
        admitted, wave_index=2, priority_class="GENERAL",
        assigned_guest_count=0, assigned_departure_count=0,
    )
    assert admitted["window_start_utc"].startswith("2026-09-15T08:51:00"), (
        admitted["window_start_utc"]
    )

    _, meta = validate_paginated(
        api.list_tender_waves(
            TEST_USERS["port_agent_headers"],
            params={"port_call_id": port_call["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 2, meta


# ---------------------------------------------------------------------------
# Conserved quantity: seats
# ---------------------------------------------------------------------------

def test_seat_conservation_holds_after_every_pre_cruise_booking(api):
    """PRD §3.5: "`precruise_sold_seats` counts the seats consumed by bookings on this departure whose `channel` is `PRE_CRUISE` and whose `fulfillment_status` is neither `CANCELLED_BY_GUEST` nor `CANCELLED_BY_LINE`; `onboard_sold_seats` counts the same for `ONBOARD`."
    PRD §3.5: "`seats_available_total` is `total_capacity` less both sold counts."
    PRD §3.5: "Before the release, the effective allocations are simply `precruise_allocation` and `onboard_allocation` as stored."
    PRD §3.5: "From those, `effective_precruise_available` is the effective pre-cruise allocation less `precruise_sold_seats`, floored at 0, and `effective_onboard_available` is the effective onboard allocation less `onboard_sold_seats`, floored at 0."

    Design: Difficulty/compensating_invariant/seat_conservation_holds_per_channel_bucket_across_booking_and_cancellation
    """
    world = fixtures.setup_selling_departure(api)
    opening = fixtures.get_departure(api, world.departure["id"])
    assertions.assert_seat_conservation(opening)
    assertions.assert_field_values(
        opening, total_capacity=40, precruise_allocation=25, onboard_allocation=15,
        precruise_sold_seats=0, onboard_sold_seats=0, seats_available_total=40,
        effective_precruise_available=25, effective_onboard_available=15,
    )

    expected = [
        (4, 36, 21, 15),
        (8, 32, 17, 15),
        (12, 28, 13, 15),
    ]
    for index, (sold, available, precruise_free, onboard_free) in enumerate(expected):
        guest = fixtures.create_guest(
            api, full_name=f"Guest {index}", voyage_code=world.port_call["voyage_code"],
            loyalty_tier="GOLD",
        )
        fixtures.create_booking(
            api, world.departure["id"], guest["id"], party_size=4,
            channel="PRE_CRUISE",
        )
        departure = fixtures.get_departure(api, world.departure["id"])
        assertions.assert_seat_conservation(departure)
        assertions.assert_field_values(
            departure,
            precruise_sold_seats=sold,
            onboard_sold_seats=0,
            seats_available_total=available,
            effective_precruise_available=precruise_free,
            effective_onboard_available=onboard_free,
            precruise_allocation=25,
            onboard_allocation=15,
            total_capacity=40,
        )


def test_cancelling_every_booking_returns_the_departure_to_its_opening_seat_position(api):
    """PRD §3.5: "A cancellation always reduces the sold count of the booking's own `channel` by the booking's `party_size`."
    PRD §3.5: "`precruise_allocation` and `onboard_allocation` must at all times sum exactly to `total_capacity`; there is no slack bucket, and a violation is `ERR_ALLOCATION_MISMATCH`."
    PRD §3.7: "A booking still in `BOOKED` moves `BOOKED → CANCELLED_BY_GUEST` with `financial_status` `AUTHORIZED → VOIDED`, an `AUTH_VOID` entry of `amount_cents` 0 and `refund_pct_bps` 0 on the `GUEST_INITIATED` `basis`, `retained_cents` left at 0, and its seats returned to its channel bucket."

    Design: Difficulty/compensating_invariant/seat_conservation_holds_per_channel_bucket_across_booking_and_cancellation
    """
    world = fixtures.setup_selling_departure(api)
    bookings = []
    for index in range(3):
        guest = fixtures.create_guest(
            api, full_name=f"Guest {index}", voyage_code=world.port_call["voyage_code"],
            loyalty_tier="GOLD",
        )
        bookings.append(
            fixtures.create_booking(
                api, world.departure["id"], guest["id"], party_size=4,
                channel="PRE_CRUISE",
            )
        )

    booked = fixtures.get_departure(api, world.departure["id"])
    assertions.assert_seat_conservation(booked)
    assertions.assert_field_values(booked, precruise_sold_seats=12,
                                   seats_available_total=28)

    expected = [
        (8, 32, 17),
        (4, 36, 21),
        (0, 40, 25),
    ]
    for booking, (sold, available, precruise_free) in zip(bookings, expected):
        cancelled = fixtures.cancel_booking(
            api, booking["id"], reason_code="GUEST_CHANGED_PLANS"
        )
        assertions.assert_field_values(
            cancelled, fulfillment_status="CANCELLED_BY_GUEST",
            financial_status="VOIDED", refunded_cents=0, retained_cents=0,
        )
        departure = fixtures.get_departure(api, world.departure["id"])
        assertions.assert_seat_conservation(departure)
        assertions.assert_field_values(
            departure,
            precruise_sold_seats=sold,
            onboard_sold_seats=0,
            seats_available_total=available,
            effective_precruise_available=precruise_free,
            effective_onboard_available=15,
            precruise_allocation=25,
            onboard_allocation=15,
            total_capacity=40,
        )


# ---------------------------------------------------------------------------
# Conserved quantity: money
# ---------------------------------------------------------------------------

def test_guest_cancellation_at_the_tier_edge_splits_the_charge_into_refund_and_retention(api):
    """PRD §3.7: "Below that but at 1440 minutes or more, the refund is 7500 basis points of `quoted_total_cents`."
    PRD §3.7: "`financial_status` then follows from the arithmetic: add the refund to the booking's existing `refunded_cents`, and if the new total is zero the status is `RETAINED`, if it is at least `charge_total_cents` the status is `REFUNDED`, and otherwise it is `PARTIALLY_REFUNDED`, with `retained_cents` set to `charge_total_cents` less the new refunded total."
    PRD §3.7: "A refund of more than zero writes a `REFUND` entry for the computed amount; a refund of zero instead writes a `RETENTION` entry whose `amount_cents` is the whole `charge_total_cents`."

    Design: Difficulty/compensating_invariant/money_conservation_holds_because_every_charged_cent_is_either_refunded_or_retained
    """
    world = fixtures.setup_ticketed_booking(
        api, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    assertions.assert_field_values(
        world.booking, quoted_total_cents=48508, service_fee_cents=1455,
        charge_total_cents=49963, financial_status="CHARGED",
    )

    # Exactly 1440 minutes before the 09:00Z meeting time — the 7500 bps edge.
    fixtures.set_clock(api, "2026-09-14T09:00:00Z")
    cancelled = fixtures.cancel_booking(
        api, world.booking["id"], reason_code="GUEST_CHANGED_PLANS"
    )
    assertions.assert_field_values(
        cancelled,
        fulfillment_status="CANCELLED_BY_GUEST",
        financial_status="PARTIALLY_REFUNDED",
        charge_total_cents=49963,
        refunded_cents=36381,
        retained_cents=13582,
    )
    assertions.assert_money_conservation(cancelled)

    entries, meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={"booking_id": world.booking["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, meta
    assertions.assert_field_values(
        entries[0], entry_kind="REFUND", amount_cents=36381, refund_pct_bps=7500,
        basis="GUEST_INITIATED",
    )


def test_no_show_on_all_aboard_closure_retains_the_whole_charge(api):
    """PRD §3.1: "Closure is the busiest cascade of the day: every departure still `SELLING` moves `SELLING → CLOSED`; every booking still in `TICKETED` moves `TICKETED → NO_SHOW` with `financial_status` moving `CHARGED → RETAINED` and a `RETENTION` ledger entry whose `amount_cents` equals the booking's `charge_total_cents` on the `NO_SHOW` `basis`; and every booking whose `alternative_offer_status` is `OFFERED` flips to `EXPIRED`, because an unaccepted rebooking offer has no meaning once the ship has sailed."
    PRD §3.1: "The same agent closes the call at the all-aboard deadline, moving `IN_PORT → CLOSED`, permitted only once the logical clock has reached `all_aboard_utc`."

    Design: Difficulty/compensating_invariant/money_conservation_holds_because_every_charged_cent_is_either_refunded_or_retained
    """
    world = fixtures.setup_ticketed_booking(
        api, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )

    fixtures.set_clock(api, CHECKIN_CLOCK)
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T16:35:00Z")
    closed_call = fixtures.port_call_transition(
        api, world.port_call["id"], "CLOSE_ALL_ABOARD"
    )
    assertions.assert_field_values(closed_call, status="CLOSED")

    booking = fixtures.get_booking(api, world.booking["id"])
    assertions.assert_field_values(
        booking,
        fulfillment_status="NO_SHOW",
        financial_status="RETAINED",
        charge_total_cents=49963,
        refunded_cents=0,
        retained_cents=49963,
    )
    assertions.assert_money_conservation(booking)

    entries, meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"],
            params={"booking_id": world.booking["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, meta
    assertions.assert_field_values(
        entries[0], entry_kind="RETENTION", amount_cents=49963, refund_pct_bps=0,
        basis="NO_SHOW",
    )
    assertions.assert_field_values(
        fixtures.get_departure(api, world.departure["id"]), status="CLOSED"
    )


def test_two_bookings_pushed_down_opposite_money_paths_still_balance(api):
    """PRD §3.7: "On the booking side, `refunded_cents` is the running sum of `REFUND` entries, `goodwill_credit_cents` is the running sum of `GOODWILL_CREDIT` and `REPATRIATION_ALLOWANCE` entries together, and `retained_cents` is `charge_total_cents` less `refunded_cents` once `financial_status` is terminal and 0 while it is still `AUTHORIZED`."
    PRD §3.5: "`charge_total_cents` is `quoted_total_cents` plus `service_fee_cents`, and it is the amount authorised at booking and captured at ticketing."

    Design: Difficulty/compensating_invariant/money_conservation_holds_because_every_charged_cent_is_either_refunded_or_retained
    """
    world = fixtures.setup_ticketed_booking(
        api, guest={"loyalty_tier": "GOLD"}, booking={"party_size": 4}
    )
    booking_p = world.booking
    assertions.assert_charge_total_is_quote_plus_fee(booking_p)
    assertions.assert_quote_is_per_guest_times_party(booking_p)

    guest_q = fixtures.create_guest(
        api, full_name="Ben Ortiz", birth_date="1979-11-20T00:00:00Z",
        voyage_code=world.port_call["voyage_code"], loyalty_tier="GOLD",
    )
    booking_q = fixtures.create_booking(
        api, world.departure["id"], guest_q["id"], party_size=4, channel="PRE_CRUISE"
    )
    booking_q = fixtures.ticket_booking(api, booking_q["id"])
    assertions.assert_field_values(booking_q, charge_total_cents=49963,
                                   financial_status="CHARGED")

    fixtures.set_clock(api, "2026-09-14T09:00:00Z")
    fixtures.cancel_booking(api, booking_p["id"], reason_code="GUEST_CHANGED_PLANS")
    booking_p = fixtures.get_booking(api, booking_p["id"])
    assertions.assert_money_conservation(booking_p)
    assertions.assert_money_conservation(fixtures.get_booking(api, booking_q["id"]))

    fixtures.set_clock(api, CHECKIN_CLOCK)
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T16:35:00Z")
    fixtures.port_call_transition(api, world.port_call["id"], "CLOSE_ALL_ABOARD")

    booking_p = fixtures.get_booking(api, booking_p["id"])
    booking_q = fixtures.get_booking(api, booking_q["id"])
    assertions.assert_money_conservation(booking_p)
    assertions.assert_money_conservation(booking_q)
    assertions.assert_field_values(
        booking_p, financial_status="PARTIALLY_REFUNDED", refunded_cents=36381,
        retained_cents=13582,
    )
    assertions.assert_field_values(
        booking_q, financial_status="RETAINED", refunded_cents=0,
        retained_cents=49963,
    )

    charged = booking_p["charge_total_cents"] + booking_q["charge_total_cents"]
    refunded = booking_p["refunded_cents"] + booking_q["refunded_cents"]
    retained = booking_p["retained_cents"] + booking_q["retained_cents"]
    assert charged == 99926, charged
    assert refunded == 36381, refunded
    assert retained == 63545, retained
    assert charged == refunded + retained, (charged, refunded, retained)
