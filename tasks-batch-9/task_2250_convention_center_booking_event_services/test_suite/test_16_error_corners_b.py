"""Error-precedence and rejection checks over the booking, labor, close,
settlement, amendment and fiscal gates."""

from datetime import datetime

from test_helpers import (
    ANALYST_TWO,
    BALLROOM_B,
    BALLROOM_C,
    EVENT_SERVICES,
    HALL_A,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SUNBELT_PROMOTER,
    VENUE_ADMIN,
    ApiErrorId,
    amendment_round_trip,
    approve_service_order,
    create_booking,
    finalize_settlement_after_dispute_window,
    labor_call_payload,
    make_analyst_headers,
    order_service,
    place_hold,
    publish_window,
    read_booking,
    read_client,
    read_hold,
    read_labor_call,
    read_license,
    read_service_order,
    read_settlement,
    read_space,
    read_union_jurisdiction,
    register_client,
    register_space,
    register_union_local,
    register_vendor,
    set_clock,
    setup_event_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant, tolerating the optional fractional part."""
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    return datetime.strptime(
        value.replace("Z", "+0000").replace(".000+0000", "+0000"), "%Y-%m-%dT%H:%M:%S%z"
    )


# ---------------------------------------------------------------------------
# Challenge round ceiling
# ---------------------------------------------------------------------------


def test_second_challenge_on_an_answered_hold_hits_the_round_cap(api):
    """PRD §3.3: "Finally the target's `challenge_round` must be strictly less than
    its class's `max_challenge_rounds`, else `ERR_CHALLENGE_LIMIT_REACHED`."

    Design: Corner/errors/second_challenge_beyond_the_round_cap_rejected
    """
    publish_window(api, "CITYWIDE_CONVENTION")
    publish_window(api, "LOCAL_EVENT")
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)

    promoter = register_client(api, **SUNBELT_PROMOTER)
    rotary = register_client(api, **RIVERBEND_ROTARY)
    association = register_client(api, **NATIONAL_WIDGET_ASSOCIATION)

    interval = {
        "move_in_start_date": "2028-01-28",
        "show_start_date": "2028-02-01",
        "show_end_date": "2028-02-03",
        "move_out_end_date": "2028-02-05",
    }
    consumer_booking = create_booking(
        api,
        promoter["id"],
        space["id"],
        event_name="Sunbelt Winter Market",
        event_class="CONSUMER_SHOW",
        **interval,
    )
    local_booking = create_booking(
        api,
        rotary["id"],
        space["id"],
        event_name="Riverbend Winter Fair",
        event_class="LOCAL_EVENT",
        **interval,
    )
    citywide_booking = create_booking(
        api,
        association["id"],
        space["id"],
        event_name="National Widget Winter Council",
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=3000,
        **interval,
    )

    consumer_hold = place_hold(api, consumer_booking["id"])
    local_hold = place_hold(api, local_booking["id"])
    citywide_hold = place_hold(api, citywide_booking["id"])

    validate_success(api.challenge_hold(consumer_hold["id"], local_hold["id"], headers=SALES_MANAGER))
    validate_success(api.answer_challenge(consumer_hold["id"], headers=SALES_MANAGER))

    resp = api.challenge_hold(consumer_hold["id"], citywide_hold["id"], headers=SALES_MANAGER)
    validate_error(resp, ApiErrorId.CHALLENGE_LIMIT_REACHED.value)

    target = read_hold(api, consumer_hold["id"])
    assert target["status"] == "ACTIVE"
    assert target["challenge_round"] == 1
    assert target["challenged_by_hold_id"] is None
    assert read_hold(api, local_hold["id"])["status"] == "RELEASED"
    assert read_hold(api, citywide_hold["id"])["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Calendar gates on the in-house transitions
# ---------------------------------------------------------------------------


def test_open_show_before_move_in_start_date_is_refused(api):
    """PRD §3.8: "Two guards apply: the logical clock date must have reached
    `move_in_start_date`, meaning it is that date or later, and an earlier attempt is
    refused with `ERR_MOVE_IN_NOT_REACHED`; and the booking's license must be
    `EXECUTED`, else `ERR_LICENSE_STATE_INVALID`."

    Design: Corner/errors/event_transitions_before_their_calendar_dates_rejected
    """
    state = setup_event_lifecycle(api, stage="definite", deposit_cents=200_000)
    booking_id = state["booking"]["id"]

    early = api.open_show(booking_id, headers=EVENT_SERVICES)
    validate_error(early, ApiErrorId.MOVE_IN_NOT_REACHED.value)

    set_clock(api, "2027-03-01T08:00:00Z")
    validate_success(api.open_show(booking_id, headers=EVENT_SERVICES))
    assert read_booking(api, booking_id)["status"] == "IN_HOUSE"


def test_close_on_the_last_move_out_day_is_refused(api):
    """PRD §3.8: "The logical clock date must be strictly past `move_out_end_date` —
    closing on the last move-out day itself is refused with `ERR_EVENT_NOT_ENDED`."

    Design: Corner/errors/event_transitions_before_their_calendar_dates_rejected
    """
    state = setup_event_lifecycle(api, stage="definite", deposit_cents=200_000)
    booking_id = state["booking"]["id"]

    set_clock(api, "2027-03-01T08:00:00Z")
    validate_success(api.open_show(booking_id, headers=EVENT_SERVICES))
    assert read_booking(api, booking_id)["status"] == "IN_HOUSE"

    set_clock(api, "2027-03-05T09:00:00Z")
    resp = api.close_booking(booking_id, headers=EVENT_SERVICES)
    validate_error(resp, ApiErrorId.EVENT_NOT_ENDED.value)

    booking = read_booking(api, booking_id)
    assert booking["status"] == "IN_HOUSE"
    assert booking["order_posture"] == "OPEN"

    _, meta = validate_paginated(api.list_settlements(headers=VENUE_ADMIN, booking_id=booking_id))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Labor work date inside the licensed period
# ---------------------------------------------------------------------------


def test_labor_call_outside_the_licensed_period_is_refused_on_both_edges(api):
    """PRD §3.6: "The `work_date` must fall inside the booking's closed interval from
    `move_in_start_date` through `move_out_end_date` — the first move-in day and the
    last move-out day both qualify — else `ERR_WORK_DATE_OUTSIDE_EVENT`."

    The accepted call is priced by PRD §3.6: "A call's `billed_hours` is its
    `crew_size` multiplied by the greater of the local's `min_call_hours` and the
    call's own span" and "The estimate, written at creation into
    `estimated_charge_cents`, is generous to the licensee: take the hours per crew
    member as the greater of the local's `min_call_hours` and the scheduled span,
    multiply by `crew_size` and by the local's `straight_time_rate_cents`, and round
    half up to whole cents."

    Design: Corner/errors/labor_call_with_a_work_date_outside_the_event_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    local = register_union_local(
        api,
        craft_name="Teamsters Local 7",
        covered_category="UTILITIES",
        straight_time_rate_cents=8000,
        max_crew_hours_per_day=12,
        overtime_multiplier=1.5,
        min_call_hours=4,
        st_window_start_hour=8,
        st_window_end_hour=17,
        lockout_active=False,
    )
    client = register_client(api, **SUNBELT_PROMOTER)
    booking = create_booking(api, client["id"], space["id"])

    def call_on(work_date):
        return api.create_labor_call(
            booking["id"],
            payload=labor_call_payload(local["id"], "UTILITIES", work_date, 8.0, 12.0, 1),
            headers=EVENT_SERVICES,
        )

    validate_error(call_on("2027-02-28"), ApiErrorId.WORK_DATE_OUTSIDE_EVENT.value)
    validate_error(call_on("2027-03-06"), ApiErrorId.WORK_DATE_OUTSIDE_EVENT.value)

    accepted = validate_success(call_on("2027-03-05"), 201)
    call = read_labor_call(api, accepted["id"])
    assert call["work_date"] == "2027-03-05"
    assert float(call["billed_hours"]) == 4.0
    assert call["estimated_charge_cents"] == 32000
    assert float(read_union_jurisdiction(api, local["id"])["committed_crew_hours"]) == 4.0

    _, meta = validate_paginated(api.list_labor_calls(headers=VENUE_ADMIN, booking_id=booking["id"]))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Close blocked by an unreconciled service order
# ---------------------------------------------------------------------------


def test_close_is_refused_while_a_service_order_is_still_only_estimated(api):
    """PRD §3.8: "And every service order on the booking must have `billing_status`
    `RECONCILED` or `VOID`, and every labor call must have `status` `ACTUALIZED` or
    `CANCELLED`; a service order still `UNBILLED` or `ESTIMATED`, or a labor call
    still `SCHEDULED` or `DISPATCHED`, refuses the close with
    `ERR_SERVICE_ORDERS_NOT_RECONCILED`."

    The order's timing is fixed by PRD §3.5: "It is `ADVANCE` when the logical clock
    date falls more than 30 days before the booking's `show_start_date`, and `LATE`
    otherwise — so an order placed exactly 30 days out is `LATE`, and one placed 31
    days out is `ADVANCE`."

    Design: Corner/errors/close_with_an_unreconciled_service_order_rejected
    """
    vendor = register_vendor(api)
    state = setup_event_lifecycle(api, stage="definite", deposit_cents=200_000)
    booking_id = state["booking"]["id"]

    set_clock(api, "2027-03-01T08:00:00Z")
    order = order_service(api, booking_id, vendor["id"], "CLEANING", 2000)
    approve_service_order(api, order["id"])
    validate_success(api.open_show(booking_id, headers=EVENT_SERVICES))
    set_clock(api, "2027-03-06T09:00:00Z")

    blocked = api.close_booking(booking_id, headers=EVENT_SERVICES)
    validate_error(blocked, ApiErrorId.SERVICE_ORDERS_NOT_RECONCILED.value)

    booking = read_booking(api, booking_id)
    assert booking["status"] == "IN_HOUSE"
    assert booking["order_posture"] == "OPEN"

    validate_success(api.reconcile_service_order(order["id"], 2600, headers=EVENT_SERVICES))
    reconciled = read_service_order(api, order["id"])
    assert reconciled["billing_status"] == "RECONCILED"
    assert reconciled["order_timing"] == "LATE"
    assert reconciled["estimated_charge_cents"] == 16200
    assert float(reconciled["actual_quantity"]) == 2600
    assert reconciled["actual_charge_cents"] == 21060

    validate_success(api.close_booking(booking_id, headers=EVENT_SERVICES))
    closed = read_booking(api, booking_id)
    assert closed["status"] == "CLOSED"
    assert closed["order_posture"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# The dispute window read from both sides
# ---------------------------------------------------------------------------

_BOAT_SHOW_DATES = {
    "event_name": "Sunbelt Boat Show",
    "move_in_start_date": "2027-06-09",
    "show_start_date": "2027-06-10",
    "show_end_date": "2027-06-12",
    "move_out_end_date": "2027-06-13",
}


def test_finalize_while_the_dispute_window_is_still_open_is_refused(api):
    """PRD §3.9: "the logical clock instant must be strictly past
    `dispute_deadline_utc`, else `ERR_DISPUTE_WINDOW_OPEN` — the licensee's window
    must have run out before the house may close the book."

    Design: Corner/errors/settlement_dispute_and_finalize_outside_their_windows_rejected
    """
    state = setup_event_lifecycle(
        api,
        stage="settlement_issued",
        space=BALLROOM_C,
        deposit_cents=1_300_000,
        booking=dict(_BOAT_SHOW_DATES),
    )
    settlement_id = state["settlement"]["id"]

    set_clock(api, "2027-06-20T10:00:00Z")
    resp = api.finalize_settlement(settlement_id, headers=make_analyst_headers(ANALYST_TWO))
    validate_error(resp, ApiErrorId.DISPUTE_WINDOW_OPEN.value)

    settlement = read_settlement(api, settlement_id)
    assert settlement["status"] == "ISSUED"
    assert _instant(settlement["dispute_deadline_utc"]) == _instant("2027-06-24T09:00:00Z")
    assert settlement["dispute_reason"] is None
    assert settlement["deposit_applied_cents"] == 0
    assert read_booking(api, state["booking"]["id"])["status"] == "CLOSED"
    assert read_client(api, state["client"]["id"])["outstanding_balance_cents"] == 0


def test_dispute_after_the_deadline_instant_is_refused(api):
    """PRD §3.9: "The logical clock instant must be at or before
    `dispute_deadline_utc`; disputing exactly at the deadline instant still counts,
    while disputing after it is `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Corner/errors/settlement_dispute_and_finalize_outside_their_windows_rejected
    """
    state = setup_event_lifecycle(
        api,
        stage="settlement_issued",
        space=BALLROOM_C,
        deposit_cents=1_300_000,
        booking=dict(_BOAT_SHOW_DATES),
    )
    settlement_id = state["settlement"]["id"]

    set_clock(api, "2027-06-25T10:00:00Z")
    resp = api.dispute_settlement(
        settlement_id,
        dispute_reason="labour hours look overstated",
        headers=state["licensee_headers"],
    )
    validate_error(resp, ApiErrorId.DISPUTE_WINDOW_CLOSED.value)

    settlement = read_settlement(api, settlement_id)
    assert settlement["status"] == "ISSUED"
    assert _instant(settlement["dispute_deadline_utc"]) == _instant("2027-06-24T09:00:00Z")
    assert settlement["dispute_reason"] is None
    assert settlement["deposit_applied_cents"] == 0
    assert read_booking(api, state["booking"]["id"])["status"] == "CLOSED"
    assert read_client(api, state["client"]["id"])["outstanding_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Amendment round ceiling
# ---------------------------------------------------------------------------


def test_fourth_amendment_round_is_refused_after_three_acceptances(api):
    """PRD §3.4: "And `amendment_round` must be strictly less than three, so a license
    that has already absorbed three accepted amendments refuses the fourth with
    `ERR_AMENDMENT_LIMIT_REACHED`."

    Design: Corner/errors/fourth_license_amendment_rejected
    """
    state = setup_event_lifecycle(api, stage="license_executed", deposit_cents=200_000)
    license_id = state["license"]["id"]
    client_id = state["client"]["id"]

    amendment_round_trip(api, license_id, client_id, "add a second loading dock slot")
    amendment_round_trip(api, license_id, client_id, "extend move-out by four hours")
    amendment_round_trip(api, license_id, client_id, "revise the rigging plot")

    settled_version = read_license(api, license_id)["version"]
    resp = api.create_amendment(
        license_id,
        expected_license_version=settled_version,
        amendment_note="one amendment too many",
        headers=SALES_MANAGER,
    )
    validate_error(resp, ApiErrorId.AMENDMENT_LIMIT_REACHED.value)

    license_row = read_license(api, license_id)
    assert license_row["status"] == "EXECUTED"
    assert license_row["amendment_round"] == 3
    assert license_row["pending_amendment_note"] is None
    assert license_row["version"] == settled_version
    assert license_row["deposit_held_cents"] == 90900


# ---------------------------------------------------------------------------
# Client standing gate on a fresh booking
# ---------------------------------------------------------------------------


def test_new_booking_for_a_hold_restricted_client_is_refused(api):
    """PRD §3.1: "A `HOLD_RESTRICTED` client may not have a new booking created, may
    not have a new hold placed, and may not have a booking confirmed as definite; all
    three are refused with `ERR_CLIENT_HOLD_RESTRICTED`."

    Design: Corner/errors/new_booking_for_a_hold_restricted_client_rejected
    """
    state = setup_event_lifecycle(
        api,
        stage="settlement_issued",
        event_class="CITYWIDE_CONVENTION",
        space=HALL_A,
        client=NATIONAL_WIDGET_ASSOCIATION,
        deposit_cents=8_000_000,
        booking={
            "event_name": "National Widget Convention",
            "move_in_start_date": "2028-05-10",
            "show_start_date": "2028-05-14",
            "show_end_date": "2028-05-17",
            "move_out_end_date": "2028-05-19",
            "projected_room_nights": 3000,
        },
    )
    other_space = register_space(api, **BALLROOM_B)
    settlement_id = state["settlement"]["id"]
    client_id = state["client"]["id"]

    finalize_settlement_after_dispute_window(api, settlement_id, at_utc="2028-05-30T10:00:00Z")

    resp = api.create_booking(
        client_id=client_id,
        space_id=other_space["id"],
        event_name="National Widget Winter Council",
        event_class="CITYWIDE_CONVENTION",
        move_in_start_date="2030-01-05",
        show_start_date="2030-01-08",
        show_end_date="2030-01-10",
        move_out_end_date="2030-01-12",
        projected_room_nights=2600,
        headers=SALES_MANAGER,
    )
    validate_error(resp, ApiErrorId.CLIENT_HOLD_RESTRICTED.value)

    client = read_client(api, client_id)
    assert client["booking_standing"] == "HOLD_RESTRICTED"
    assert client["outstanding_balance_cents"] == 20286000

    settlement = read_settlement(api, settlement_id)
    assert settlement["status"] == "FINAL"
    assert settlement["grand_total_cents"] == 20286000
    assert read_booking(api, state["booking"]["id"])["status"] == "SETTLED"
    assert read_space(api, other_space["id"])["committed_space_days"] == 0

    _, meta = validate_paginated(api.list_bookings(headers=VENUE_ADMIN, client_id=client_id))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Deposit credit gate on issuing a license
# ---------------------------------------------------------------------------


def test_issuing_a_license_without_deposit_credit_is_refused(api):
    """PRD §3.4: "A `SalesManager` may issue only while the associated booking is
    still `TENTATIVE` — a booking that has moved on is refused with
    `ERR_BOOKING_STATE_INVALID` — and only when the client's `credit_balance_cents` is
    at least this license's `deposit_required_cents`. A short balance is refused with
    `ERR_INSUFFICIENT_DEPOSIT_CREDIT` and HTTP 402, which is why §3.1's
    deposit-recording operation exists."

    Design: Corner/errors/license_issue_without_deposit_credit_rejected
    """
    state = setup_event_lifecycle(api, stage="license_draft")
    license_id = state["license"]["id"]

    resp = api.issue_license(license_id, headers=SALES_MANAGER)
    validate_error(resp, ApiErrorId.INSUFFICIENT_DEPOSIT_CREDIT.value)

    license_row = read_license(api, license_id)
    assert license_row["status"] == "DRAFT"
    assert license_row["deposit_required_cents"] == 90900
    assert license_row["deposit_held_cents"] == 0
    assert license_row["issued_at_utc"] is None
    assert read_client(api, state["client"]["id"])["credit_balance_cents"] == 0
    assert read_booking(api, state["booking"]["id"])["status"] == "TENTATIVE"
