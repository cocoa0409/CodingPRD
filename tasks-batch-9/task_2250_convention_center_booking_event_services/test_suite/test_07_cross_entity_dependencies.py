"""Transitions blocked by the state of a sibling entity rather than by the target's own."""

from test_helpers import (
    ANALYST_ONE,
    ANALYST_TWO,
    BALLROOM_B,
    EVENT_SERVICES,
    HALL_A,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    SALES_MANAGER,
    SPARKLECLEAN_EXCLUSIVE,
    TEAMSTERS_LOCAL_7,
    VENUE_ADMIN,
    ApiClient,
    ApiErrorId,
    append_line_item,
    assert_crew_hours,
    assert_fields,
    assert_money_cents,
    close_booking,
    confirm_definite,
    confirm_first_option,
    countersign_license,
    create_booking,
    draft_license,
    get_success_data,
    issue_license,
    issue_settlement,
    make_analyst_headers,
    open_settlement,
    open_show,
    order_service,
    pay_deposit,
    place_hold,
    publish_window,
    read_booking,
    read_client,
    read_hold,
    read_labor_call,
    read_license,
    read_service_order,
    read_union_jurisdiction,
    register_client,
    register_space,
    register_union_local,
    register_vendor,
    schedule_labor_call,
    set_clock,
    setup_event_lifecycle,
    validate_error,
)

CONVENTION_DATES = {
    "move_in_start_date": "2028-05-10",
    "show_start_date": "2028-05-14",
    "show_end_date": "2028-05-17",
    "move_out_end_date": "2028-05-19",
}

SIBLING_DATES = {
    "move_in_start_date": "2028-09-05",
    "show_start_date": "2028-09-08",
    "show_end_date": "2028-09-10",
    "move_out_end_date": "2028-09-12",
}


def _booking_with_an_issued_but_unsigned_license(api: ApiClient):
    """A TENTATIVE booking with a CONFIRMED first-option hold and an ISSUED license."""
    return setup_event_lifecycle(
        api,
        "license_issued",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
    )


def test_confirm_definite_is_refused_while_the_license_is_only_issued(api: ApiClient):
    """The booking's own state permits the move but the unsigned license blocks it.

    PRD: "The license whose booking is this booking must have `status`
    `EXECUTED`, else `ERR_LICENSE_STATE_INVALID`."
    PRD: "At least one hold on the booking must have `status` `CONFIRMED`, else
    `ERR_HOLD_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/booking_cannot_be_confirmed_definite_while_license_is_only_issued
    """
    world = _booking_with_an_issued_but_unsigned_license(api)

    response = api.confirm_definite_booking(world["booking"]["id"], headers=SALES_MANAGER)
    validate_error(response, ApiErrorId.LICENSE_STATE_INVALID, expected_status=409)

    assert_fields(read_booking(api, world["booking"]["id"]), status="TENTATIVE")


def test_refused_confirmation_leaves_the_license_and_the_hold_as_they_stood(api: ApiClient):
    """Neither the ISSUED license nor the CONFIRMED hold is disturbed by the refusal.

    PRD: "**Countersigning** drives `ISSUED → EXECUTED` and is reserved to the
    `Licensee` itself: the acting `X-User-ID` must equal the `client_id` of the
    license's booking, or the request is `ERR_NOT_RESOURCE_OWNER`."
    PRD: "Countersigning stamps `executed_at_utc` with the logical clock instant,
    and that stamp is written only on the *first* arrival at `EXECUTED` — later
    returns from an amendment round leave it untouched."

    Design: Difficulty/cross_entity_state_dependency/booking_cannot_be_confirmed_definite_while_license_is_only_issued
    """
    world = _booking_with_an_issued_but_unsigned_license(api)

    api.confirm_definite_booking(world["booking"]["id"], headers=SALES_MANAGER)

    license_row = read_license(api, world["license"]["id"])
    assert_fields(license_row, status="ISSUED")
    assert license_row.get("executed_at_utc") is None

    assert_fields(read_hold(api, world["hold"]["id"]), status="CONFIRMED", hold_rank=1)


def _sibling_order_under_a_settled_debt(api: ApiClient):
    """A pending order on one booking while another booking of the same client settles."""
    publish_window(api, "CITYWIDE_CONVENTION")
    hall = register_space(api, **dict(HALL_A))
    ballroom = register_space(api, **dict(BALLROOM_B))
    vendor = register_vendor(api, **dict(SPARKLECLEAN_EXCLUSIVE))
    client = register_client(api, **dict(NATIONAL_WIDGET_ASSOCIATION))
    pay_deposit(api, client["id"], 8000000)

    booking = create_booking(
        api,
        client["id"],
        hall["id"],
        event_name="National Widget Convention",
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=3000,
        **CONVENTION_DATES,
    )
    sibling = create_booking(
        api,
        client["id"],
        ballroom["id"],
        event_name="National Widget Fall Council",
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=2600,
        **SIBLING_DATES,
    )
    sibling_order = order_service(api, sibling["id"], vendor["id"], "CLEANING", 1000)

    hold = place_hold(api, booking["id"])
    confirm_first_option(api, hold["id"])
    license_row = draft_license(api, booking["id"])
    issue_license(api, license_row["id"])
    countersign_license(api, license_row["id"], client["id"])
    confirm_definite(api, booking["id"])

    open_show(api, booking["id"], at_utc="2028-05-10T08:00:00Z")
    close_booking(api, booking["id"], at_utc="2028-05-20T09:00:00Z")

    settlement = open_settlement(api, booking["id"], basis="CONTRACTED", analyst_id=ANALYST_ONE)
    append_line_item(
        api, settlement["id"], "RENTAL", 25200000, memo="contracted rental", analyst_id=ANALYST_ONE
    )
    issue_settlement(api, settlement["id"], analyst_id=ANALYST_ONE)
    set_clock(api, "2028-05-30T10:00:00Z")
    get_success_data(
        api.finalize_settlement(settlement["id"], headers=make_analyst_headers(ANALYST_TWO))
    )

    return {"client": client, "sibling": sibling, "sibling_order": sibling_order}


def test_approval_is_refused_once_the_parent_posture_turned_locked(api: ApiClient):
    """A debt settled on another booking locks this booking and closes the approval edge.

    PRD: "What the posture gates: creating a service order, a labor call or a
    catering arrangement under the booking, and approving a service order or a
    catering arrangement, all require `OPEN`."
    PRD: "1. `LOCKED` when the booking's `status` is `RELEASED`, `CANCELLED` or
    `SETTLED`, or when the owning client's `booking_standing` is `HOLD_RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/service_order_cannot_be_approved_once_parent_booking_posture_is_locked
    """
    world = _sibling_order_under_a_settled_debt(api)

    response = api.approve_service_order(world["sibling_order"]["id"], headers=EVENT_SERVICES)
    validate_error(response, ApiErrorId.ORDER_POSTURE_NOT_OPEN, expected_status=409)

    assert_fields(read_booking(api, world["sibling"]["id"]), order_posture="LOCKED")
    assert_fields(read_client(api, world["client"]["id"]), booking_standing="HOLD_RESTRICTED")


def test_locked_posture_leaves_the_order_unpriced_on_both_axes(api: ApiClient):
    """The refused approval advances neither status dimension and prices nothing.

    PRD: "The order records its `booking_id` and opens with two independent status
    dimensions on the same row: `approval_status` `PENDING_APPROVAL` and
    `billing_status` `UNBILLED`, with `estimated_charge_cents` 0, `actual_quantity`
    null and `actual_charge_cents` null."
    PRD: "A posture that is not permissive enough for the requested operation
    yields `ERR_ORDER_POSTURE_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/service_order_cannot_be_approved_once_parent_booking_posture_is_locked
    """
    world = _sibling_order_under_a_settled_debt(api)

    api.approve_service_order(world["sibling_order"]["id"], headers=EVENT_SERVICES)

    order = read_service_order(api, world["sibling_order"]["id"])
    assert_fields(order, approval_status="PENDING_APPROVAL", billing_status="UNBILLED")
    assert_money_cents(order["estimated_charge_cents"], 0, "estimated_charge_cents")


def _scheduled_call_under_a_fresh_lockout(api: ApiClient):
    """A SCHEDULED utilities call whose local declared a lockout after the call was written."""
    world = setup_event_lifecycle(
        api,
        "in_house",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
    )
    local = register_union_local(api, **dict(TEAMSTERS_LOCAL_7))
    call = schedule_labor_call(
        api,
        world["booking"]["id"],
        local["id"],
        "UTILITIES",
        "2027-03-01",
        8.0,
        12.0,
        2,
    )
    get_success_data(
        api.update_union_jurisdiction(local["id"], lockout_active=True, headers=VENUE_ADMIN)
    )
    world["local"] = local
    world["labor_call"] = call
    return world


def test_dispatch_is_refused_after_the_local_declares_a_lockout(api: ApiClient):
    """A call written while the local was open cannot be dispatched once it locks out.

    PRD: "While `lockout_active` is true no new call may be scheduled against the
    local and no already-scheduled call may be dispatched — both are refused with
    `ERR_UNION_LOCKOUT`."
    PRD: "**Dispatching** drives `SCHEDULED → DISPATCHED` and requires the booking
    to have reached `IN_HOUSE`, else `ERR_BOOKING_STATE_INVALID`, and the local's
    `lockout_active` to still be false, else `ERR_UNION_LOCKOUT`."

    Design: Difficulty/cross_entity_state_dependency/labor_call_cannot_be_dispatched_after_its_local_declares_a_lockout
    """
    world = _scheduled_call_under_a_fresh_lockout(api)

    response = api.dispatch_labor_call(world["labor_call"]["id"], headers=EVENT_SERVICES)
    validate_error(response, ApiErrorId.UNION_LOCKOUT, expected_status=422)

    assert_fields(read_labor_call(api, world["labor_call"]["id"]), status="SCHEDULED")
    assert_fields(read_booking(api, world["booking"]["id"]), status="IN_HOUSE")


def test_lockout_leaves_the_call_priced_and_the_hours_committed(api: ApiClient):
    """The refused dispatch keeps 64000 cents and 8.0 crew-hours exactly where they were.

    PRD: "Dispatch moves no money at all: `estimated_charge_cents` was already
    written at creation."
    PRD: "A call's `billed_hours` is its `crew_size` multiplied by the greater of
    the local's `min_call_hours` and the call's own span — the scheduled span while
    the call is `SCHEDULED` or `DISPATCHED`, and the actual span once it is
    `ACTUALIZED`."

    Design: Difficulty/cross_entity_state_dependency/labor_call_cannot_be_dispatched_after_its_local_declares_a_lockout
    """
    world = _scheduled_call_under_a_fresh_lockout(api)

    api.dispatch_labor_call(world["labor_call"]["id"], headers=EVENT_SERVICES)

    call = read_labor_call(api, world["labor_call"]["id"])
    assert_money_cents(call["estimated_charge_cents"], 64000, "estimated_charge_cents")
    assert_crew_hours(call["billed_hours"], 8.0)

    local = read_union_jurisdiction(api, world["local"]["id"])
    assert local["lockout_active"] is True
    assert_crew_hours(local["committed_crew_hours"], 8.0)
