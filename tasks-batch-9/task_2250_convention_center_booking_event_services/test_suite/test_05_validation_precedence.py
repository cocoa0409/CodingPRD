"""Requests that break two rules at once and must report the higher-precedence one."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BALLROOM_B,
    EVENT_SERVICES,
    HALL_A,
    LAPSED_GUARD_CO,
    SALES_MANAGER,
    SUNBELT_PROMOTER,
    VENUE_ADMIN,
    assert_fields,
    assert_money_cents,
    booking_payload,
    create_booking,
    draft_license,
    get_success_data,
    publish_window,
    read_client,
    read_license,
    read_space,
    register_client,
    register_space,
    register_vendor,
    service_order_payload,
    validate_error,
    validate_paginated,
)

BALLROOM_JUNE_DATES = {
    "move_in_start_date": "2027-06-08",
    "show_start_date": "2027-06-10",
    "show_end_date": "2027-06-12",
    "move_out_end_date": "2027-06-13",
}


def _draft_license_on_a_cancelled_booking(api: ApiClient):
    """A DRAFT license whose booking is CANCELLED and whose client has no credit."""
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **dict(BALLROOM_B))
    client = register_client(api, **dict(SUNBELT_PROMOTER))
    booking = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home & Garden Expo",
        event_class="CONSUMER_SHOW",
        **BALLROOM_JUNE_DATES,
    )
    license_row = draft_license(api, booking["id"])
    get_success_data(api.cancel_booking(booking["id"], headers=VENUE_ADMIN))
    return {"client": client, "booking": booking, "license": license_row}


def test_license_issue_reports_the_booking_state_not_the_short_balance(api: ApiClient):
    """Issuing against a cancelled booking with zero credit reports the state failure.

    PRD: "A `SalesManager` may issue only while the associated booking is still
    `TENTATIVE` — a booking that has moved on is refused with
    `ERR_BOOKING_STATE_INVALID` — and only when the client's
    `credit_balance_cents` is at least this license's `deposit_required_cents`."
    PRD: "9. **State validity.** The target resource is in a state from which the
    requested transition is declared, else the state-invalid code of the entity
    whose state fails the guard"
    PRD: "18. **Fiscal gates**, in this order: deposit credit sufficiency
    (`ERR_INSUFFICIENT_DEPOSIT_CREDIT`, HTTP 402), client standing
    (`ERR_CLIENT_HOLD_RESTRICTED`, HTTP 409), charge-line sign rules
    (`ERR_LINE_AMOUNT_INVALID`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/license_issue_reports_booking_state_before_insufficient_deposit_credit
    """
    world = _draft_license_on_a_cancelled_booking(api)

    response = api.issue_license(world["license"]["id"], headers=SALES_MANAGER)
    validate_error(response, ApiErrorId.BOOKING_STATE_INVALID, expected_status=409)
    assert response.status_code != 402
    assert response.json()["data"]["error_id"] != ApiErrorId.INSUFFICIENT_DEPOSIT_CREDIT.value


def test_refused_issue_moves_no_deposit_money(api: ApiClient):
    """The refused issue leaves the license DRAFT and both money accounts at zero.

    PRD: "On success `deposit_held_cents` is set to `deposit_required_cents`, the
    client's `credit_balance_cents` is decreased by exactly that amount, and
    `issued_at_utc` is stamped with the logical clock instant."
    PRD: "The license opens in `status` `DRAFT` with `deposit_held_cents` 0,
    `amendment_round` 0, `pending_amendment_note` null, and both `issued_at_utc` and
    `executed_at_utc` null."

    Design: Difficulty/priority_pair_validation_conflict/license_issue_reports_booking_state_before_insufficient_deposit_credit
    """
    world = _draft_license_on_a_cancelled_booking(api)

    api.issue_license(world["license"]["id"], headers=SALES_MANAGER)

    license_row = read_license(api, world["license"]["id"])
    assert_fields(license_row, status="DRAFT")
    assert_money_cents(license_row["deposit_held_cents"], 0, "deposit_held_cents")
    assert_money_cents(
        read_client(api, world["client"]["id"])["credit_balance_cents"], 0, "credit_balance_cents"
    )


def _booking_with_a_lapsed_security_vendor(api: ApiClient):
    """A live booking plus a vendor that is both uninsured and in the wrong category."""
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **dict(BALLROOM_B))
    vendor = register_vendor(api, **dict(LAPSED_GUARD_CO))
    client = register_client(api, **dict(SUNBELT_PROMOTER))
    booking = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home & Garden Expo",
        event_class="CONSUMER_SHOW",
        **BALLROOM_JUNE_DATES,
    )
    return {"booking": booking, "vendor": vendor}


def test_service_order_reports_the_lapsed_certificate_before_the_wrong_category(api: ApiClient):
    """An expired certificate outranks the category mismatch on the same request.

    PRD: "14. **Vendor and union eligibility**, in this order: vendor insurance
    currency (`ERR_VENDOR_COI_EXPIRED`), union lockout (`ERR_UNION_LOCKOUT`),
    rigging capability of the space (`ERR_SPACE_NOT_RIGGING_CAPABLE`), union
    jurisdiction match (`ERR_UNION_JURISDICTION_MISMATCH`), vendor category match
    (`ERR_VENDOR_CATEGORY_MISMATCH`), exclusive vendor requirement
    (`ERR_EXCLUSIVE_VENDOR_REQUIRED`), catering exclusivity
    (`ERR_CATERING_EXCLUSIVITY_VIOLATION`), outside-catering reason
    (`ERR_OUTSIDE_CATERING_REASON_REQUIRED`) — all HTTP 422."
    PRD: "The vendor's `coi_expiry_date` must be strictly after the logical clock
    date, else `ERR_VENDOR_COI_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/service_order_create_reports_expired_coi_before_vendor_category_mismatch
    """
    world = _booking_with_a_lapsed_security_vendor(api)

    response = api.create_service_order(
        world["booking"]["id"],
        payload=service_order_payload(world["vendor"]["id"], "UTILITIES", 120),
        headers=EVENT_SERVICES,
    )
    validate_error(response, ApiErrorId.VENDOR_COI_EXPIRED, expected_status=422)
    assert response.json()["data"]["error_id"] != ApiErrorId.VENDOR_CATEGORY_MISMATCH.value


def test_refused_service_order_is_not_recorded_against_the_booking(api: ApiClient):
    """No service-order row survives the refused creation.

    PRD: "The order records its `booking_id` and opens with two independent status
    dimensions on the same row: `approval_status` `PENDING_APPROVAL` and
    `billing_status` `UNBILLED`, with `estimated_charge_cents` 0, `actual_quantity`
    null and `actual_charge_cents` null."

    Design: Difficulty/priority_pair_validation_conflict/service_order_create_reports_expired_coi_before_vendor_category_mismatch
    """
    world = _booking_with_a_lapsed_security_vendor(api)

    api.create_service_order(
        world["booking"]["id"],
        payload=service_order_payload(world["vendor"]["id"], "UTILITIES", 120),
        headers=EVENT_SERVICES,
    )

    items, _meta = validate_paginated(
        api.list_service_orders(headers=EVENT_SERVICES, booking_id=world["booking"]["id"])
    )
    assert items == [], f"expected no service orders, got {items}"


def _hall_and_promoter(api: ApiClient):
    """A citywide window, a rigging-capable hall and a promoter client."""
    publish_window(api, "CITYWIDE_CONVENTION")
    space = register_space(api, **dict(HALL_A))
    client = register_client(api, **dict(SUNBELT_PROMOTER))
    return {"space": space, "client": client}


def _unqualified_citywide_payload(client_id: str, space_id: str):
    return booking_payload(
        client_id,
        space_id,
        event_name="Winter Consumer Spectacular",
        event_class="CITYWIDE_CONVENTION",
        move_in_start_date="2027-01-02",
        show_start_date="2027-01-04",
        show_end_date="2027-01-06",
        move_out_end_date="2027-01-07",
        projected_room_nights=100,
    )


def test_citywide_qualification_outranks_the_closed_booking_window(api: ApiClient):
    """A promoter asking for a citywide date five months out reports the qualification failure.

    PRD: "The **citywide qualification** gate applies only when `event_class` is
    `CITYWIDE_CONVENTION`: the named client's `organization_type` must be
    `NATIONAL_ASSOCIATION` and `projected_room_nights` must be at least 2,500."
    PRD: "8. **Citywide qualification.** On booking creation only, else
    `ERR_CITYWIDE_QUALIFICATION_NOT_MET` (HTTP 422)."
    PRD: "15. **Temporal windows**, in this order: booking window
    (`ERR_BOOKING_WINDOW_CLOSED`), maintenance blackout clearance
    (`ERR_MAINTENANCE_BLACKOUT_CONFLICT`), confirmed-hold date conflict
    (`ERR_SPACE_DATE_CONFLICT`), hold release deadline
    (`ERR_RELEASE_DEADLINE_PASSED`), challenge deadline
    (`ERR_CHALLENGE_DEADLINE_PASSED`), move-in reached
    (`ERR_MOVE_IN_NOT_REACHED`), event ended (`ERR_EVENT_NOT_ENDED`), dispute
    window closed (`ERR_DISPUTE_WINDOW_CLOSED`), dispute window still open
    (`ERR_DISPUTE_WINDOW_OPEN`), labor work date inside the event span
    (`ERR_WORK_DATE_OUTSIDE_EVENT`)."

    Design: Difficulty/priority_pair_validation_conflict/citywide_booking_reports_qualification_failure_before_closed_booking_window
    """
    world = _hall_and_promoter(api)

    response = api.create_booking(
        payload=_unqualified_citywide_payload(world["client"]["id"], world["space"]["id"]),
        headers=SALES_MANAGER,
    )
    validate_error(response, ApiErrorId.CITYWIDE_QUALIFICATION_NOT_MET, expected_status=422)
    assert response.json()["data"]["error_id"] != ApiErrorId.BOOKING_WINDOW_CLOSED.value


def test_refused_citywide_booking_charges_no_space_days(api: ApiClient):
    """The rejected booking leaves no row and no space-day commitment behind.

    PRD: "Creation also charges the space calendar."
    PRD: "Both derived counters, `committed_space_days` and
    `active_blackout_count`, initialize to 0; the first is the conserved space-day
    counter of §2.9, and the second simply counts the maintenance windows on this
    space that have reached `APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/citywide_booking_reports_qualification_failure_before_closed_booking_window
    """
    world = _hall_and_promoter(api)

    api.create_booking(
        payload=_unqualified_citywide_payload(world["client"]["id"], world["space"]["id"]),
        headers=SALES_MANAGER,
    )

    assert read_space(api, world["space"]["id"])["committed_space_days"] == 0

    items, _meta = validate_paginated(
        api.list_bookings(headers=SALES_MANAGER, client_id=world["client"]["id"])
    )
    assert items == [], f"expected no bookings, got {items}"
