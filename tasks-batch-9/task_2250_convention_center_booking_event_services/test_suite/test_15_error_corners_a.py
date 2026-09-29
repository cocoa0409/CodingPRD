"""Error-precedence and rejection behaviour of the convention center API (part A)."""

from test_helpers import (
    ANALYST_ONE,
    BALLROOM_B,
    BALLROOM_C,
    EVENT_SERVICES,
    FACILITIES_PLANNER,
    MEETING_ROOM_301,
    NO_HEADERS,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SETTLEMENT_ANALYST,
    TEAMSTERS_LOCAL_7,
    VENUE_ADMIN,
    ApiErrorId,
    approve_blackout,
    approve_catering,
    booking_payload,
    catering_arrangement_payload,
    create_booking,
    labor_call_payload,
    make_analyst_headers,
    make_headers,
    place_hold,
    propose_blackout,
    propose_catering,
    publish_window,
    read_catering_arrangement,
    read_hold,
    read_labor_call,
    read_maintenance_blackout,
    read_settlement,
    read_space,
    read_union_jurisdiction,
    register_client,
    register_space,
    register_union_local,
    register_vendor,
    schedule_labor_call,
    service_order_payload,
    set_clock,
    settlement_line_item_payload,
    setup_event_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)

# A well-formed identifier that no row in an empty database can carry.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

CENTERPLATE_IN_HOUSE = {
    "legal_name": "Centerplate Convention Dining",
    "service_category": "CATERING",
    "vendor_tier": "EXCLUSIVE",
    "coi_expiry_date": "2030-01-01",
    "is_in_house_caterer": True,
}

COUSINS_KITCHEN_OUTSIDE = {
    "legal_name": "Cousin's Kitchen Catering",
    "service_category": "CATERING",
    "vendor_tier": "PREFERRED",
    "coi_expiry_date": "2030-01-01",
    "is_in_house_caterer": False,
}

TEAMSTERS_LOCAL_7_FULL = dict(
    TEAMSTERS_LOCAL_7,
    overtime_multiplier=1.5,
    min_call_hours=4,
    st_window_start_hour=8,
    st_window_end_hour=17,
    lockout_active=False,
)


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_with_missing_x_user_headers_rejected
    """
    response = api.get_booking(MISSING_UUID, headers=NO_HEADERS)

    validate_error(response, ApiErrorId.UNAUTHENTICATED.value)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_request_with_an_unrecognized_role_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_with_missing_x_user_headers_rejected
    """
    response = api.get_booking(MISSING_UUID, headers=make_headers("janitor-1", "Janitor"))

    validate_error(response, ApiErrorId.UNAUTHENTICATED.value)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


# --------------------------------------------------------------------------
# Existence, in the path and in the body
# --------------------------------------------------------------------------


def test_every_single_entity_read_reports_its_own_not_found_code(api):
    """PRD §2.11: "Each entity has its own code: `ERR_CLIENT_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`, `ERR_POLICY_WINDOW_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_LABOR_CALL_NOT_FOUND`, `ERR_CATERING_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_BLACKOUT_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/every_path_identifier_miss_returns_not_found
    """
    probes = [
        (api.get_client(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.CLIENT_NOT_FOUND),
        (api.get_space(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.SPACE_NOT_FOUND),
        (
            api.get_policy_window(MISSING_UUID, headers=VENUE_ADMIN),
            ApiErrorId.POLICY_WINDOW_NOT_FOUND,
        ),
        (api.get_booking(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.BOOKING_NOT_FOUND),
        (api.get_hold(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.HOLD_NOT_FOUND),
        (api.get_license(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.LICENSE_NOT_FOUND),
        (api.get_vendor(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.VENDOR_NOT_FOUND),
        (
            api.get_union_jurisdiction(MISSING_UUID, headers=VENUE_ADMIN),
            ApiErrorId.JURISDICTION_NOT_FOUND,
        ),
        (
            api.get_service_order(MISSING_UUID, headers=VENUE_ADMIN),
            ApiErrorId.SERVICE_ORDER_NOT_FOUND,
        ),
        (api.get_labor_call(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.LABOR_CALL_NOT_FOUND),
        (
            api.get_catering_arrangement(MISSING_UUID, headers=VENUE_ADMIN),
            ApiErrorId.CATERING_NOT_FOUND,
        ),
        (api.get_settlement(MISSING_UUID, headers=VENUE_ADMIN), ApiErrorId.SETTLEMENT_NOT_FOUND),
        (
            api.get_maintenance_blackout(MISSING_UUID, headers=VENUE_ADMIN),
            ApiErrorId.BLACKOUT_NOT_FOUND,
        ),
    ]

    for response, error_id in probes:
        validate_error(response, error_id.value)


def test_body_foreign_key_misses_report_their_own_not_found_code(api):
    """PRD §2.11: "**Body reference existence.** Every foreign identifier carried in the request body resolves, validated in the order the endpoint declares its input fields, using the same 404 codes."

    Design: Corner/errors/body_foreign_key_misses_return_not_found
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"], event_class="CONSUMER_SHOW")
    hold = place_hold(api, booking["id"])

    ghost_dates = {
        "event_name": "Ghost Show",
        "move_in_start_date": "2027-04-01",
        "show_start_date": "2027-04-02",
        "show_end_date": "2027-04-04",
        "move_out_end_date": "2027-04-05",
    }

    missing_client = api.create_booking(
        payload=booking_payload(MISSING_UUID, space["id"], **ghost_dates), headers=SALES_MANAGER
    )
    missing_space = api.create_booking(
        payload=booking_payload(client["id"], MISSING_UUID, **ghost_dates), headers=SALES_MANAGER
    )
    missing_vendor = api.create_service_order(
        booking["id"],
        payload=service_order_payload(MISSING_UUID, "CLEANING", 1000),
        headers=EVENT_SERVICES,
    )
    missing_local = api.create_labor_call(
        booking["id"],
        payload=labor_call_payload(MISSING_UUID, "CLEANING", "2027-03-01", 8.0, 12.0, 2),
        headers=EVENT_SERVICES,
    )
    missing_challenger = api.challenge_hold(
        hold["id"], challenger_hold_id=MISSING_UUID, headers=SALES_MANAGER
    )
    missing_settlement = api.create_settlement_line_item(
        payload=settlement_line_item_payload(MISSING_UUID, "ADJUSTMENT", -1000, memo="ghost"),
        headers=SETTLEMENT_ANALYST,
    )

    validate_error(missing_client, ApiErrorId.CLIENT_NOT_FOUND.value)
    validate_error(missing_space, ApiErrorId.SPACE_NOT_FOUND.value)
    validate_error(missing_vendor, ApiErrorId.VENDOR_NOT_FOUND.value)
    validate_error(missing_local, ApiErrorId.JURISDICTION_NOT_FOUND.value)
    validate_error(missing_challenger, ApiErrorId.HOLD_NOT_FOUND.value)
    validate_error(missing_settlement, ApiErrorId.SETTLEMENT_NOT_FOUND.value)

    unchanged_hold = read_hold(api, hold["id"])
    assert unchanged_hold["status"] == "ACTIVE"
    assert unchanged_hold["challenged_by_hold_id"] is None

    _, meta = validate_paginated(api.list_bookings(headers=VENUE_ADMIN, client_id=client["id"]))
    assert meta["total_count"] == 1


# --------------------------------------------------------------------------
# Booking creation: policy window resolution and date ordering
# --------------------------------------------------------------------------


def test_booking_for_an_unpublished_event_class_reports_policy_window_missing(api):
    """PRD §3.2: "the server resolves `policy_window_id` by looking up the published policy window whose `event_class` equals the submitted one — a lookup that must succeed, or the request fails with `ERR_POLICY_WINDOW_MISSING` before the dates are even inspected."

    Design: Corner/errors/booking_for_an_unpublished_event_class_rejected
    """
    publish_window(api, "LOCAL_EVENT")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Sunbelt Home Show",
            event_class="CONSUMER_SHOW",
            move_in_start_date="2027-06-08",
            show_start_date="2027-06-10",
            show_end_date="2027-06-12",
            move_out_end_date="2027-06-13",
        ),
        headers=SALES_MANAGER,
    )

    validate_error(response, ApiErrorId.POLICY_WINDOW_MISSING.value)

    _, meta = validate_paginated(api.list_bookings(headers=VENUE_ADMIN))
    assert meta["total_count"] == 0
    assert read_space(api, space["id"])["committed_space_days"] == 0


def _consumer_show_ballroom_fixture(api):
    """Publish the consumer-show window and register Ballroom B plus one client."""
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api)
    return space, client


def test_booking_with_show_end_before_show_start_rejected(api):
    """PRD §3.2: "The four dates must be non-decreasing in exactly that order, so move-in may begin on the same day the show opens but never after it, the show may be a single day, and move-out may end on the last show day but never before it; any other ordering is `ERR_INVALID_REQUEST`."

    Design: Corner/errors/booking_with_out_of_order_event_dates_rejected
    """
    space, client = _consumer_show_ballroom_fixture(api)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Reversed Show",
            event_class="CONSUMER_SHOW",
            move_in_start_date="2027-06-08",
            show_start_date="2027-06-12",
            show_end_date="2027-06-10",
            move_out_end_date="2027-06-13",
        ),
        headers=SALES_MANAGER,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_bookings(headers=VENUE_ADMIN))
    assert meta["total_count"] == 0
    assert read_space(api, space["id"])["committed_space_days"] == 0


def test_booking_with_move_in_after_show_start_rejected(api):
    """PRD §3.2: "The four dates must be non-decreasing in exactly that order, so move-in may begin on the same day the show opens but never after it, the show may be a single day, and move-out may end on the last show day but never before it; any other ordering is `ERR_INVALID_REQUEST`."

    Design: Corner/errors/booking_with_out_of_order_event_dates_rejected
    """
    space, client = _consumer_show_ballroom_fixture(api)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Late Move In",
            event_class="CONSUMER_SHOW",
            move_in_start_date="2027-06-11",
            show_start_date="2027-06-10",
            show_end_date="2027-06-12",
            move_out_end_date="2027-06-13",
        ),
        headers=SALES_MANAGER,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_bookings(headers=VENUE_ADMIN))
    assert meta["total_count"] == 0
    assert read_space(api, space["id"])["committed_space_days"] == 0


def test_booking_with_move_out_before_show_end_rejected(api):
    """PRD §3.2: "The four dates must be non-decreasing in exactly that order, so move-in may begin on the same day the show opens but never after it, the show may be a single day, and move-out may end on the last show day but never before it; any other ordering is `ERR_INVALID_REQUEST`."

    Design: Corner/errors/booking_with_out_of_order_event_dates_rejected
    """
    space, client = _consumer_show_ballroom_fixture(api)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Early Move Out",
            event_class="CONSUMER_SHOW",
            move_in_start_date="2027-06-08",
            show_start_date="2027-06-10",
            show_end_date="2027-06-12",
            move_out_end_date="2027-06-11",
        ),
        headers=SALES_MANAGER,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_bookings(headers=VENUE_ADMIN))
    assert meta["total_count"] == 0
    assert read_space(api, space["id"])["committed_space_days"] == 0


# --------------------------------------------------------------------------
# Transitions attempted from a source state that does not declare them
# --------------------------------------------------------------------------


def test_answer_challenge_on_an_active_hold_rejected(api):
    """PRD §3.3: "The hold must be `CHALLENGED`, and the logical clock instant must be at or before `challenge_deadline_utc`; answering exactly at the deadline instant still counts, while answering after it is refused with `ERR_CHALLENGE_DEADLINE_PASSED`."

    PRD §2.11: "**State validity.** The target resource is in a state from which the requested transition is declared, else the state-invalid code of the entity whose state fails the guard"

    Design: Corner/errors/hold_and_blackout_transitions_from_the_wrong_source_state_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api)
    booking = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home Show",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )
    hold = place_hold(api, booking["id"])

    response = api.answer_challenge(hold["id"], headers=SALES_MANAGER)

    validate_error(response, ApiErrorId.HOLD_STATE_INVALID.value)

    unchanged = read_hold(api, hold["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["challenge_round"] == 0


def test_approve_of_an_already_approved_blackout_rejected(api):
    """PRD §3.10: "Approving or deferring a window that is not `PROPOSED` is refused with `ERR_BLACKOUT_STATE_INVALID`."

    Design: Corner/errors/hold_and_blackout_transitions_from_the_wrong_source_state_rejected
    """
    space = register_space(api, **BALLROOM_C)
    blackout = propose_blackout(
        api, space["id"], "2027-12-01", "2027-12-10", project_kind="CAPITAL_PROJECT", buffer_days=2
    )
    approve_blackout(api, blackout["id"])

    response = api.approve_maintenance_blackout(blackout["id"], headers=FACILITIES_PLANNER)

    validate_error(response, ApiErrorId.BLACKOUT_STATE_INVALID.value)

    assert read_maintenance_blackout(api, blackout["id"])["status"] == "APPROVED"
    assert read_space(api, space["id"])["active_blackout_count"] == 1


def test_actualize_of_a_scheduled_labor_call_rejected(api):
    """PRD §3.6: "**Actualizing** drives `DISPATCHED → ACTUALIZED`; the `EventServicesManager` submits `actual_start_hour` and `actual_end_hour`, which must satisfy the actual start being strictly less than the actual end, else `ERR_INVALID_REQUEST`."

    PRD §2.11: "**State validity.** The target resource is in a state from which the requested transition is declared, else the state-invalid code of the entity whose state fails the guard"

    Design: Corner/errors/labor_call_and_catering_transitions_from_the_wrong_source_state_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    local = register_union_local(api, **TEAMSTERS_LOCAL_7_FULL)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"], event_class="CONSUMER_SHOW")
    call = schedule_labor_call(
        api, booking["id"], local["id"], "UTILITIES", "2027-03-01", 8.0, 12.0, 2
    )

    response = api.actualize_labor_call(
        call["id"], actual_start_hour=8.0, actual_end_hour=12.0, headers=EVENT_SERVICES
    )

    validate_error(response, ApiErrorId.LABOR_CALL_STATE_INVALID.value)

    unchanged = read_labor_call(api, call["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["actual_charge_cents"] is None
    assert unchanged["actual_start_hour"] is None
    assert unchanged["estimated_charge_cents"] == 64_000


def test_deny_of_an_approved_catering_arrangement_rejected(api):
    """PRD §3.7: "**Denying** drives `PROPOSED → DENIED` from a `PROPOSED` arrangement and sets `buyout_fee_cents` to 0."

    PRD §2.11: "**State validity.** The target resource is in a state from which the requested transition is declared, else the state-invalid code of the entity whose state fails the guard"

    Design: Corner/errors/labor_call_and_catering_transitions_from_the_wrong_source_state_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    outside_vendor = register_vendor(api, **COUSINS_KITCHEN_OUTSIDE)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"], event_class="CONSUMER_SHOW")
    arrangement = propose_catering(
        api,
        booking["id"],
        outside_vendor["id"],
        "OUTSIDE_EXCEPTION",
        1_000_000,
        exception_reason="ETHNIC_CUISINE",
    )
    approve_catering(api, arrangement["id"])

    response = api.deny_catering_arrangement(arrangement["id"], headers=EVENT_SERVICES)

    validate_error(response, ApiErrorId.CATERING_STATE_INVALID.value)

    unchanged = read_catering_arrangement(api, arrangement["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["buyout_fee_cents"] == 250_000


# --------------------------------------------------------------------------
# Uniqueness scopes
# --------------------------------------------------------------------------


def test_second_policy_window_for_the_same_event_class_rejected(api):
    """PRD §3.1: "There is at most one window per `event_class`, and a second attempt at the same class is refused with `ERR_POLICY_WINDOW_EXISTS`."

    Design: Corner/errors/duplicate_window_license_and_catering_creations_rejected
    """
    publish_window(api, "CONSUMER_SHOW")

    response = api.create_policy_window(
        event_class="CONSUMER_SHOW",
        priority_rank=3,
        open_months_before=12,
        close_months_before=1,
        max_holds_per_booking=1,
        challenge_response_hours=24,
        rental_discount_pct=0.05,
        max_challenge_rounds=1,
        headers=VENUE_ADMIN,
    )

    validate_error(response, ApiErrorId.POLICY_WINDOW_EXISTS.value)

    windows, meta = validate_paginated(api.list_policy_windows(headers=VENUE_ADMIN))
    assert meta["total_count"] == 1
    assert windows[0]["open_months_before"] == 18


def test_second_license_on_one_booking_rejected(api):
    """PRD §3.4: "If the booking already carries a license whose `status` is `DRAFT`, `ISSUED`, `EXECUTED` or `AMENDMENT_PENDING`, the request is refused with `ERR_LICENSE_ALREADY_EXISTS`; a booking whose only prior license was `VOIDED` or `TERMINATED` may be drafted afresh."

    Design: Corner/errors/duplicate_window_license_and_catering_creations_rejected
    """
    context = setup_event_lifecycle(api, stage="license_draft")
    booking_id = context["booking"]["id"]
    license_id = context["license"]["id"]

    response = api.create_license(booking_id, headers=SALES_MANAGER)

    validate_error(response, ApiErrorId.LICENSE_ALREADY_EXISTS.value)

    licenses, meta = validate_paginated(
        api.list_licenses(headers=VENUE_ADMIN, booking_id=booking_id)
    )
    assert meta["total_count"] == 1
    assert licenses[0]["id"] == license_id
    assert licenses[0]["status"] == "DRAFT"


def test_second_live_catering_arrangement_on_one_booking_rejected(api):
    """PRD §3.7: "A booking may carry only one live arrangement: if one already exists whose `status` is `PROPOSED`, `APPROVED` or `CLOSED`, the proposal is refused with `ERR_CATERING_ALREADY_EXISTS`, while a prior `DENIED` arrangement leaves the way clear."

    Design: Corner/errors/duplicate_window_license_and_catering_creations_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    in_house_vendor = register_vendor(api, **CENTERPLATE_IN_HOUSE)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"], event_class="CONSUMER_SHOW")
    arrangement = propose_catering(api, booking["id"], in_house_vendor["id"], "IN_HOUSE", 900_000)

    response = api.create_catering_arrangement(
        booking["id"],
        payload=catering_arrangement_payload(in_house_vendor["id"], "IN_HOUSE", 500_000),
        headers=EVENT_SERVICES,
    )

    validate_error(response, ApiErrorId.CATERING_ALREADY_EXISTS.value)

    arrangements, meta = validate_paginated(
        api.list_catering_arrangements(headers=VENUE_ADMIN, booking_id=booking["id"])
    )
    assert meta["total_count"] == 1
    assert arrangements[0]["id"] == arrangement["id"]
    assert arrangements[0]["estimated_fnb_cents"] == 900_000


# --------------------------------------------------------------------------
# Settlement stage guards and charge-line sign rules
# --------------------------------------------------------------------------


def test_settlement_duplicates_bad_line_amounts_and_wrong_stage_exits_rejected(api):
    """PRD §3.9: "Exactly one settlement may exist per booking, and a second attempt is refused with `ERR_SETTLEMENT_ALREADY_EXISTS`."

    PRD §3.9: "The sign rule is enforced at append time: every line whose `line_kind` is not `ADJUSTMENT` must carry a strictly positive `amount_cents`, an `ADJUSTMENT` line may be negative, but no append may drive the settlement's subtotal to zero or below."

    PRD §3.9: "**Escalating** drives `DISPUTED → ARBITRATION` and is available only once `revision_round` has reached two or more; escalating too early is refused with `ERR_SETTLEMENT_REVISION_LIMIT_REACHED`."

    PRD §3.9: "The arbitration door drives `ARBITRATION → FINAL` and belongs to the `VenueAdmin`; it requires only that the settlement be in `ARBITRATION`, and it applies neither the dispute-window check nor the segregation check."

    PRD §2.11: "**State validity.** The target resource is in a state from which the requested transition is declared, else the state-invalid code of the entity whose state fails the guard"

    Design: Corner/errors/settlement_stage_duplicates_and_bad_line_amounts_rejected
    """
    context = setup_event_lifecycle(
        api,
        stage="settlement_draft",
        event_class="CONSUMER_SHOW",
        space=BALLROOM_C,
        deposit_cents=1_300_000,
        booking={
            "event_name": "Sunbelt Boat Show",
            "move_in_start_date": "2027-06-09",
            "show_start_date": "2027-06-10",
            "show_end_date": "2027-06-12",
            "move_out_end_date": "2027-06-13",
        },
        settlement_basis="CONTRACTED",
        analyst_id=ANALYST_ONE,
    )
    booking_id = context["booking"]["id"]
    settlement_id = context["settlement"]["id"]
    analyst = make_analyst_headers(ANALYST_ONE)

    duplicate = api.create_settlement(booking_id, basis="ACTUAL_USAGE", headers=analyst)
    validate_error(duplicate, ApiErrorId.SETTLEMENT_ALREADY_EXISTS.value)

    zero_rental = api.create_settlement_line_item(
        payload=settlement_line_item_payload(settlement_id, "RENTAL", 0, memo="zero rental"),
        headers=analyst,
    )
    validate_error(zero_rental, ApiErrorId.LINE_AMOUNT_INVALID.value)

    early_escalate = api.escalate_settlement(settlement_id, headers=analyst)
    validate_error(early_escalate, ApiErrorId.SETTLEMENT_STATE_INVALID.value)

    rental_line = api.create_settlement_line_item(
        payload=settlement_line_item_payload(
            settlement_id, "RENTAL", 5_000_000, memo="contracted rental"
        ),
        headers=analyst,
    )
    validate_success(rental_line, 201)

    erasing_adjustment = api.create_settlement_line_item(
        payload=settlement_line_item_payload(
            settlement_id, "ADJUSTMENT", -5_000_000, memo="erase the subtotal"
        ),
        headers=analyst,
    )
    validate_error(erasing_adjustment, ApiErrorId.LINE_AMOUNT_INVALID.value)

    issued = api.issue_settlement(settlement_id, headers=analyst)
    validate_success(issued, 200)

    arbitrate = api.arbitrate_finalize_settlement(settlement_id, headers=VENUE_ADMIN)
    validate_error(arbitrate, ApiErrorId.SETTLEMENT_STATE_INVALID.value)

    settlement = read_settlement(api, settlement_id)
    assert settlement["status"] == "ISSUED"
    assert settlement["line_subtotal_cents"] == 5_000_000
    assert settlement["facility_service_fee_cents"] == 350_000
    assert settlement["grand_total_cents"] == 5_350_000

    _, line_meta = validate_paginated(
        api.list_settlement_line_items(headers=VENUE_ADMIN, settlement_id=settlement_id)
    )
    assert line_meta["total_count"] == 1

    _, settlement_meta = validate_paginated(
        api.list_settlements(headers=VENUE_ADMIN, booking_id=booking_id)
    )
    assert settlement_meta["total_count"] == 1


# --------------------------------------------------------------------------
# Vendor, space and union join mismatches
# --------------------------------------------------------------------------


def test_rigging_order_on_a_space_that_cannot_take_rigging_rejected(api):
    """PRD §3.5: "A `RIGGING` order requires the booking's space to have `rigging_capable` true, else `ERR_SPACE_NOT_RIGGING_CAPABLE`."

    Design: Corner/errors/service_and_labor_category_mismatches_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B, rigging_capable=False)
    rigging_vendor = register_vendor(
        api,
        legal_name="SkyHook Rigging",
        service_category="RIGGING",
        vendor_tier="EXCLUSIVE",
        coi_expiry_date="2030-01-01",
    )
    client = register_client(api)
    booking = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home Show",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )

    response = api.create_service_order(
        booking["id"],
        payload=service_order_payload(rigging_vendor["id"], "RIGGING", 4),
        headers=EVENT_SERVICES,
    )

    validate_error(response, ApiErrorId.SPACE_NOT_RIGGING_CAPABLE.value)

    _, meta = validate_paginated(
        api.list_service_orders(headers=VENUE_ADMIN, booking_id=booking["id"])
    )
    assert meta["total_count"] == 0


def test_labor_call_outside_the_locals_covered_category_rejected(api):
    """PRD §3.6: "The local's `covered_category` must equal the submitted `work_category`, since each local claims exactly one category of show-floor work, else `ERR_UNION_JURISDICTION_MISMATCH`."

    Design: Corner/errors/service_and_labor_category_mismatches_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B, rigging_capable=False)
    local = register_union_local(api, **TEAMSTERS_LOCAL_7_FULL)
    client = register_client(api)
    booking = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home Show",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )

    response = api.create_labor_call(
        booking["id"],
        payload=labor_call_payload(local["id"], "CLEANING", "2027-06-08", 8.0, 12.0, 2),
        headers=EVENT_SERVICES,
    )

    validate_error(response, ApiErrorId.UNION_JURISDICTION_MISMATCH.value)

    _, meta = validate_paginated(
        api.list_labor_calls(headers=VENUE_ADMIN, booking_id=booking["id"])
    )
    assert meta["total_count"] == 0
    assert read_union_jurisdiction(api, local["id"])["committed_crew_hours"] == 0


def test_service_order_naming_a_vendor_of_another_category_rejected(api):
    """PRD §3.5: "The vendor's own `service_category` must equal the submitted `service_category`, else `ERR_VENDOR_CATEGORY_MISMATCH`."

    Design: Corner/errors/service_and_labor_category_mismatches_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B, rigging_capable=False)
    cleaning_vendor = register_vendor(
        api,
        legal_name="SparkleClean Facility Services",
        service_category="CLEANING",
        vendor_tier="EXCLUSIVE",
        coi_expiry_date="2030-01-01",
    )
    client = register_client(api)
    booking = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home Show",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )

    response = api.create_service_order(
        booking["id"],
        payload=service_order_payload(cleaning_vendor["id"], "SECURITY", 3),
        headers=EVENT_SERVICES,
    )

    validate_error(response, ApiErrorId.VENDOR_CATEGORY_MISMATCH.value)

    _, meta = validate_paginated(
        api.list_service_orders(headers=VENUE_ADMIN, booking_id=booking["id"])
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Catering exception reasons
# --------------------------------------------------------------------------


def test_outside_catering_without_an_exception_reason_rejected(api):
    """PRD §3.7: "And the reason pairing must hold in both directions: `exception_reason` must be non-null when `arrangement_type` is `OUTSIDE_EXCEPTION` and must be null when it is `IN_HOUSE`, else `ERR_OUTSIDE_CATERING_REASON_REQUIRED`."

    Design: Corner/errors/outside_catering_without_an_exception_reason_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    in_house_vendor = register_vendor(api, **CENTERPLATE_IN_HOUSE)
    outside_vendor = register_vendor(api, **COUSINS_KITCHEN_OUTSIDE)
    client = register_client(api)
    gem_show = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Regional Gem Show",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-03-01",
        show_start_date="2027-03-02",
        show_end_date="2027-03-04",
        move_out_end_date="2027-03-05",
    )
    coin_show = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Regional Coin Show",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-04-01",
        show_start_date="2027-04-02",
        show_end_date="2027-04-04",
        move_out_end_date="2027-04-05",
    )

    reasonless_exception = api.create_catering_arrangement(
        gem_show["id"],
        payload=catering_arrangement_payload(
            outside_vendor["id"], "OUTSIDE_EXCEPTION", 1_000_000
        ),
        headers=EVENT_SERVICES,
    )
    validate_error(reasonless_exception, ApiErrorId.OUTSIDE_CATERING_REASON_REQUIRED.value)

    reasonless_in_house = api.create_catering_arrangement(
        coin_show["id"],
        payload=catering_arrangement_payload(in_house_vendor["id"], "IN_HOUSE", 1_000_000),
        headers=EVENT_SERVICES,
    )
    accepted = validate_success(reasonless_in_house, 201)
    assert accepted["exception_reason"] is None
    assert accepted["status"] == "PROPOSED"
    assert accepted["buyout_fee_cents"] == 0

    _, meta = validate_paginated(
        api.list_catering_arrangements(headers=VENUE_ADMIN, booking_id=gem_show["id"])
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Booking window and the challenge ladder
# --------------------------------------------------------------------------


def test_local_event_booking_two_months_out_rejected(api):
    """PRD §3.2: "The **booking window** gate counts whole months from the logical clock date forward to `show_start_date`; that count must be no greater than the class's `open_months_before` and no less than its `close_months_before`."

    PRD §3.2: "but refuses one 49 months away as too early and one 5 months away as too late — both with `ERR_BOOKING_WINDOW_CLOSED`."

    Design: Corner/errors/local_event_booking_two_months_out_rejected
    """
    publish_window(api, "LOCAL_EVENT")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api, **RIVERBEND_ROTARY)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Riverbend Autumn Dinner",
            event_class="LOCAL_EVENT",
            move_in_start_date="2026-09-30",
            show_start_date="2026-10-01",
            show_end_date="2026-10-03",
            move_out_end_date="2026-10-04",
        ),
        headers=SALES_MANAGER,
    )

    validate_error(response, ApiErrorId.BOOKING_WINDOW_CLOSED.value)

    _, meta = validate_paginated(api.list_bookings(headers=VENUE_ADMIN))
    assert meta["total_count"] == 0
    assert read_space(api, space["id"])["committed_space_days"] == 0


def _two_class_hold_fixture(api):
    """Two overlapping Ballroom B holds: one CONSUMER_SHOW, one LOCAL_EVENT."""
    publish_window(api, "LOCAL_EVENT")
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    promoter = register_client(api)
    rotary = register_client(api, **RIVERBEND_ROTARY)
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
    consumer_hold = place_hold(api, consumer_booking["id"])
    local_hold = place_hold(api, local_booking["id"])
    return consumer_hold, local_hold


def test_challenge_by_a_lower_priority_hold_rejected(api):
    """PRD §3.3: "the `priority_rank` of the policy window governing the challenger's booking must be strictly less than the `priority_rank` of the policy window governing the target's booking — a lower rank number is the better claim, and equal ranks do not permit a challenge. Either failure is `ERR_CHALLENGE_NOT_PERMITTED`."

    Design: Corner/errors/challenge_of_a_higher_ranked_class_and_expired_challenge_answer_rejected
    """
    consumer_hold, local_hold = _two_class_hold_fixture(api)

    response = api.challenge_hold(
        local_hold["id"], challenger_hold_id=consumer_hold["id"], headers=SALES_MANAGER
    )

    validate_error(response, ApiErrorId.CHALLENGE_NOT_PERMITTED.value)

    unchanged = read_hold(api, local_hold["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["challenge_round"] == 0


def test_answer_challenge_after_the_challenge_deadline_rejected(api):
    """PRD §3.3: "The hold must be `CHALLENGED`, and the logical clock instant must be at or before `challenge_deadline_utc`; answering exactly at the deadline instant still counts, while answering after it is refused with `ERR_CHALLENGE_DEADLINE_PASSED`."

    PRD §3.3: "On success the target's `challenged_by_hold_id` is set to the challenger's identifier, its `challenge_round` increments by 1, and its `challenge_deadline_utc` is stamped at the logical clock instant plus the class's `challenge_response_hours` hours."

    Design: Corner/errors/challenge_of_a_higher_ranked_class_and_expired_challenge_answer_rejected
    """
    consumer_hold, local_hold = _two_class_hold_fixture(api)

    accepted_challenge = api.challenge_hold(
        consumer_hold["id"], challenger_hold_id=local_hold["id"], headers=SALES_MANAGER
    )
    validate_success(accepted_challenge, 200)

    challenged = read_hold(api, consumer_hold["id"])
    assert challenged["status"] == "CHALLENGED"
    assert challenged["challenge_round"] == 1
    assert challenged["challenged_by_hold_id"] == local_hold["id"]
    assert challenged["challenge_deadline_utc"][:19] == "2026-08-03T00:00:00"

    set_clock(api, "2026-08-03T00:00:01Z")
    response = api.answer_challenge(consumer_hold["id"], headers=SALES_MANAGER)

    validate_error(response, ApiErrorId.CHALLENGE_DEADLINE_PASSED.value)
