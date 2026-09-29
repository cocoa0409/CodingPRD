"""Endpoint surface behaviour of the Convention Center API.

Round trips through create, read and filtered list; action endpoints and their
coupled effects; and the computed money fields a read must expose.
"""

from test_helpers import (
    BALLROOM_B,
    EVENT_SERVICES,
    FACILITIES_PLANNER,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SETTLEMENT_ANALYST,
    SUNBELT_PROMOTER,
    VENUE_ADMIN,
    assert_fields,
    assert_money_cents,
    assert_pagination_meta,
    assert_settlement_money,
    booking_payload,
    client_payload,
    create_booking,
    get_success_data,
    make_licensee_headers,
    order_service,
    place_hold,
    publish_window,
    read_hold,
    read_service_order,
    register_client,
    register_space,
    setup_event_lifecycle,
    space_payload,
    validate_paginated,
    validate_success,
    vendor_payload,
)


def _assert_instant(actual, expected_seconds_precision, label):
    """Compare an instant field against ``YYYY-MM-DDTHH:MM:SS``.

    Fractional digits and the trailing zone marker are tolerated, since the
    specification stamps instants with three fractional digits.
    """
    assert isinstance(actual, str), f"{label} must be a string instant, got {actual!r}"
    assert actual.startswith(expected_seconds_precision), (
        f"{label}: expected {expected_seconds_precision}, got {actual}"
    )


def _assert_envelope_meta(response, label):
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str), f"{label}: meta.api_request_id missing"
    assert isinstance(
        meta.get("api_request_timestamp"), str
    ), f"{label}: meta.api_request_timestamp missing"


def test_client_and_space_round_trip_through_create_read_and_list(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Three clients and one space are created, then read back singly and through
    a filtered listing that must narrow the three clients to one.

    Design: Corner/endpoints/client_and_space_round_trip_through_create_read_and_list
    """
    national = get_success_data(
        api.create_client(payload=client_payload(**NATIONAL_WIDGET_ASSOCIATION), headers=VENUE_ADMIN)
    )
    rotary = get_success_data(
        api.create_client(payload=client_payload(**RIVERBEND_ROTARY), headers=SALES_MANAGER)
    )
    promoter = get_success_data(
        api.create_client(payload=client_payload(**SUNBELT_PROMOTER), headers=SALES_MANAGER)
    )
    space = get_success_data(
        api.create_space(payload=space_payload(**BALLROOM_B), headers=FACILITIES_PLANNER)
    )

    single_client_response = api.get_client(national["id"], headers=SALES_MANAGER)
    single_client = validate_success(single_client_response, 200)
    assert single_client_response.json()["response_type"] == "object"
    assert_fields(single_client, legal_name="National Widget Association")
    _assert_envelope_meta(single_client_response, "single client read")

    list_response = api.list_clients(
        headers=SETTLEMENT_ANALYST, organization_type="PROMOTER", limit=10, offset=0
    )
    rows, meta = validate_paginated(list_response)
    assert list_response.json()["response_type"] == "array"
    assert_pagination_meta(meta, total_count=1, has_more=False)
    listed_ids = [row["id"] for row in rows]
    assert listed_ids == [promoter["id"]], f"expected only the promoter, got {listed_ids}"
    assert national["id"] not in listed_ids, "the national association must not match the filter"
    assert rotary["id"] not in listed_ids, "the local organization must not match the filter"
    _assert_envelope_meta(list_response, "filtered client listing")

    space_response = api.get_space(space["id"], headers=EVENT_SERVICES)
    stored_space = validate_success(space_response, 200)
    assert_money_cents(stored_space["daily_base_rate_cents"], 1_200_000, "daily_base_rate_cents")
    assert stored_space["rigging_capable"] is False, (
        f"rigging_capable must default to false, got {stored_space['rigging_capable']!r}"
    )
    _assert_envelope_meta(space_response, "single space read")


def test_service_order_approve_moves_both_dimensions_and_writes_the_estimate(api):
    """PRD §3.5: "Approval simultaneously drives the billing dimension `UNBILLED → ESTIMATED` on the same row and writes `estimated_charge_cents` from the pricing calculation over `ordered_quantity`."

    One thousand square feet of advance-timed exclusive cleaning prices at only
    6,000 cents, so the minimum order floor binds at 15,000 cents.

    Design: Corner/endpoints/service_order_approve_moves_both_dimensions_and_writes_the_estimate
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    vendor = get_success_data(api.create_vendor(payload=vendor_payload(), headers=EVENT_SERVICES))
    client = register_client(api, **SUNBELT_PROMOTER)
    booking = create_booking(api, client["id"], space["id"])
    order = order_service(api, booking["id"], vendor["id"], "CLEANING", 1000)

    response = api.approve_service_order(order["id"], headers=EVENT_SERVICES)
    validate_success(response, 200)
    assert response.json()["response_type"] == "object"

    stored = read_service_order(api, order["id"])
    assert_fields(
        stored,
        approval_status="APPROVED",
        billing_status="ESTIMATED",
        order_timing="ADVANCE",
    )
    assert_money_cents(stored["estimated_charge_cents"], 15_000, "estimated_charge_cents")
    assert stored["estimated_charge_cents"] != 6_000, (
        "the unfloored base units charge must not be stored"
    )
    assert stored["actual_quantity"] is None, (
        f"actual_quantity must still be null, got {stored['actual_quantity']!r}"
    )
    assert stored["actual_charge_cents"] is None, (
        f"actual_charge_cents must still be null, got {stored['actual_charge_cents']!r}"
    )


def test_hold_challenge_links_the_challenger_to_the_challenged_hold(api):
    """PRD §3.3: "On success the target's `challenged_by_hold_id` is set to the challenger's identifier, its `challenge_round` increments by 1, and its `challenge_deadline_utc` is stamped at the logical clock instant plus the class's `challenge_response_hours` hours."

    The self-referential edge is written on the challenged hold, and the list
    filter on challenged_by_hold_id must find it from the challenger's side.

    Design: Corner/endpoints/hold_challenge_links_the_challenger_to_the_challenged_hold
    """
    publish_window(api, "CITYWIDE_CONVENTION")
    publish_window(api, "LOCAL_EVENT")
    space = register_space(api, **BALLROOM_B)
    rotary = register_client(api, **RIVERBEND_ROTARY)
    national = register_client(api, **NATIONAL_WIDGET_ASSOCIATION)

    local_booking = get_success_data(
        api.create_booking(
            payload=booking_payload(
                rotary["id"],
                space["id"],
                event_name="Riverbend Winter Fair",
                event_class="LOCAL_EVENT",
                move_in_start_date="2028-01-28",
                show_start_date="2028-02-01",
                show_end_date="2028-02-03",
                move_out_end_date="2028-02-05",
            ),
            headers=SALES_MANAGER,
        )
    )
    citywide_booking = get_success_data(
        api.create_booking(
            payload=booking_payload(
                national["id"],
                space["id"],
                event_name="National Widget Winter Council",
                event_class="CITYWIDE_CONVENTION",
                move_in_start_date="2028-01-28",
                show_start_date="2028-02-01",
                show_end_date="2028-02-03",
                move_out_end_date="2028-02-05",
                projected_room_nights=3000,
            ),
            headers=SALES_MANAGER,
        )
    )
    local_hold = place_hold(api, local_booking["id"])
    citywide_hold = place_hold(api, citywide_booking["id"])

    challenge_response = api.challenge_hold(
        local_hold["id"], challenger_hold_id=citywide_hold["id"], headers=SALES_MANAGER
    )
    validate_success(challenge_response, 200)

    list_response = api.list_holds(
        headers=FACILITIES_PLANNER, challenged_by_hold_id=citywide_hold["id"], limit=10, offset=0
    )
    rows, meta = validate_paginated(list_response)

    challenged = read_hold(api, local_hold["id"])
    assert_fields(
        challenged,
        status="CHALLENGED",
        challenged_by_hold_id=citywide_hold["id"],
        challenge_round=1,
    )
    _assert_instant(
        challenged["challenge_deadline_utc"], "2026-08-04T00:00:00", "challenge_deadline_utc"
    )

    challenger = read_hold(api, citywide_hold["id"])
    assert_fields(challenger, status="ACTIVE")
    assert challenger["challenged_by_hold_id"] is None, (
        f"the challenger must carry no inbound challenge, got "
        f"{challenger['challenged_by_hold_id']!r}"
    )

    assert_pagination_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [local_hold["id"]], (
        f"the filter must return only the challenged hold, got {[r['id'] for r in rows]}"
    )


def test_settlement_read_exposes_the_computed_money_fields(api):
    """PRD §3.9: "Step five: `grand_total_cents` is the subtotal plus the facility service fee less the deposit applied."

    A single rental line of 5,400,000 cents draws the mid-band facility service
    fee, and the deposit stays unapplied while the settlement is only ISSUED.

    Design: Corner/endpoints/settlement_read_exposes_the_computed_money_fields
    """
    state = setup_event_lifecycle(
        api,
        stage="settlement_issued",
        event_class="CONSUMER_SHOW",
        space=BALLROOM_B,
        client=SUNBELT_PROMOTER,
        deposit_cents=1_400_000,
        booking={
            "event_name": "Sunbelt Home Show",
            "move_in_start_date": "2027-06-08",
            "show_start_date": "2027-06-10",
            "show_end_date": "2027-06-12",
            "move_out_end_date": "2027-06-13",
        },
        open_show_at="2027-06-08T08:00:00Z",
        close_at="2027-06-14T09:00:00Z",
        settlement_basis="CONTRACTED",
        rental_line_cents=5_400_000,
    )
    settlement_id = state["settlement"]["id"]
    rental_line_id = state["line_items"][0]["id"]

    settlement_response = api.get_settlement(
        settlement_id, headers=make_licensee_headers(state["client"]["id"])
    )
    settlement = validate_success(settlement_response, 200)

    lines_response = api.list_settlement_line_items(
        headers=SETTLEMENT_ANALYST, settlement_id=settlement_id, limit=10, offset=0
    )
    rows, meta = validate_paginated(lines_response)

    assert_settlement_money(
        settlement,
        line_subtotal_cents=5_400_000,
        facility_service_fee_cents=378_000,
        grand_total_cents=5_778_000,
        deposit_applied_cents=0,
    )
    assert_fields(settlement, revision_round=0)
    _assert_instant(
        settlement["dispute_deadline_utc"], "2027-06-24T09:00:00", "dispute_deadline_utc"
    )

    assert_pagination_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [rental_line_id], (
        f"expected the single rental line, got {[r['id'] for r in rows]}"
    )
    assert_fields(rows[0], line_kind="RENTAL")
    assert_money_cents(rows[0]["amount_cents"], 5_400_000, "amount_cents")
