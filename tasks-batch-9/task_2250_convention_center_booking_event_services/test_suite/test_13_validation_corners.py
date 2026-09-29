"""Boundary and cross-entity validation behaviour of the Convention Center API.

Each test builds its own state from an empty database through the documented
endpoints, then exercises one validation rule at the exact point where it
flips between acceptance and refusal.
"""

from test_helpers import (
    ApiErrorId,
    BALLROOM_B,
    EVENT_SERVICES,
    HALL_A,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SPARKLECLEAN_EXCLUSIVE,
    VENUE_ADMIN,
    VOLT_OPEN_UTILITIES,
    assert_fields,
    assert_money_cents,
    assert_pagination_meta,
    booking_payload,
    create_booking,
    place_hold,
    publish_window,
    read_booking,
    read_hold,
    read_service_order,
    register_client,
    register_space,
    register_vendor,
    service_order_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
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


def test_local_event_booking_at_the_close_month_boundary_is_accepted(api):
    """PRD §3.2: "The **booking window** gate counts whole months from the logical clock date forward to `show_start_date`; that count must be no greater than the class's `open_months_before` and no less than its `close_months_before`."

    A LOCAL_EVENT show opening 2026-11-01 sits exactly the window's three whole
    months away from the default clock of 2026-08-01, so the booking is legal.

    Design: Corner/validations/local_event_booking_at_the_close_month_boundary_is_accepted
    """
    window = publish_window(api, "LOCAL_EVENT")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api, **RIVERBEND_ROTARY)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Riverbend Harvest Gala",
            event_class="LOCAL_EVENT",
            move_in_start_date="2026-10-31",
            show_start_date="2026-11-01",
            show_end_date="2026-11-03",
            move_out_end_date="2026-11-04",
        ),
        headers=SALES_MANAGER,
    )
    created = validate_success(response, 201)

    booking = read_booking(api, created["id"])
    assert_fields(
        booking,
        status="TENTATIVE",
        policy_window_id=window["id"],
        space_days_committed=5,
    )
    assert_money_cents(booking["gross_rental_cents"], 4_800_000, "gross_rental_cents")
    assert_money_cents(booking["contracted_rental_cents"], 4_320_000, "contracted_rental_cents")
    assert_money_cents(booking["deposit_required_cents"], 1_080_000, "deposit_required_cents")


def test_citywide_qualification_satisfied_at_exactly_the_room_night_floor(api):
    """PRD §3.2: "The **citywide qualification** gate applies only when `event_class` is `CITYWIDE_CONVENTION`: the named client's `organization_type` must be `NATIONAL_ASSOCIATION` and `projected_room_nights` must be at least 2,500."

    A national association committing exactly 2,500 room nights meets both
    halves of the gate, so the citywide booking is accepted.

    Design: Corner/validations/citywide_qualification_satisfied_at_exactly_the_room_night_floor
    """
    publish_window(api, "CITYWIDE_CONVENTION")
    space = register_space(api, **HALL_A)
    client = register_client(api, **NATIONAL_WIDGET_ASSOCIATION)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="National Widget Convention",
            event_class="CITYWIDE_CONVENTION",
            move_in_start_date="2028-05-10",
            show_start_date="2028-05-14",
            show_end_date="2028-05-17",
            move_out_end_date="2028-05-19",
            projected_room_nights=2500,
        ),
        headers=SALES_MANAGER,
    )
    created = validate_success(response, 201)

    booking = read_booking(api, created["id"])
    assert_fields(booking, event_class="CITYWIDE_CONVENTION", projected_room_nights=2500)
    assert_money_cents(booking["contracted_rental_cents"], 25_200_000, "contracted_rental_cents")


def test_in_house_catering_naming_an_outside_vendor_rejected(api):
    """PRD §3.7: "The exclusivity pairing must hold: an `IN_HOUSE` arrangement requires the named vendor's `is_in_house_caterer` to be true, and an `OUTSIDE_EXCEPTION` arrangement requires it to be false — naming the house caterer as an outside exception is as much a violation as naming an outside firm as the house caterer, and both are `ERR_CATERING_EXCLUSIVITY_VIOLATION`."

    Every field of the proposal is a legal enum value; the violation is visible
    only by joining to the vendor row.

    Design: Corner/validations/in_house_catering_naming_an_outside_vendor_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    in_house = register_vendor(
        api,
        legal_name="Centerplate Convention Dining",
        service_category="CATERING",
        vendor_tier="EXCLUSIVE",
        coi_expiry_date="2030-01-01",
        is_in_house_caterer=True,
    )
    outside = register_vendor(
        api,
        legal_name="Cousin's Kitchen Catering",
        service_category="CATERING",
        vendor_tier="PREFERRED",
        coi_expiry_date="2030-01-01",
        is_in_house_caterer=False,
    )
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"])

    response = api.create_catering_arrangement(
        booking["id"],
        vendor_id=outside["id"],
        arrangement_type="IN_HOUSE",
        estimated_fnb_cents=900_000,
        headers=EVENT_SERVICES,
    )
    validate_error(response, ApiErrorId.CATERING_EXCLUSIVITY_VIOLATION.value)

    rows, meta = validate_paginated(
        api.list_catering_arrangements(
            headers=EVENT_SERVICES, booking_id=booking["id"], limit=10, offset=0
        )
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == [], f"no arrangement should have been persisted, got {rows}"

    accepted = api.create_catering_arrangement(
        booking["id"],
        vendor_id=in_house["id"],
        arrangement_type="IN_HOUSE",
        estimated_fnb_cents=900_000,
        headers=EVENT_SERVICES,
    )
    validate_success(accepted, 201)


def test_confirm_first_option_after_the_release_deadline_rejected(api):
    """PRD §3.3: "**Confirming first option** drives `ACTIVE → CONFIRMED` and is the step that converts a queue position into a commitment; a `SalesManager` may take it only on a hold that is `ACTIVE`, whose `hold_rank` is exactly 1 — a hold at rank 2 or worse is refused with `ERR_HOLD_NOT_FIRST_OPTION` — and only while the logical clock instant is at or before `release_deadline_utc`, with a lapsed deadline refused as `ERR_RELEASE_DEADLINE_PASSED`."

    Nothing about the rank-1 ACTIVE hold changes; only the clock moves one day
    past the release deadline stamped at show start less three whole months.

    Design: Corner/validations/confirm_first_option_after_the_release_deadline_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"])
    hold = place_hold(api, booking["id"])
    set_clock(api, "2026-12-03T00:00:00Z")

    response = api.confirm_first_option(hold["id"], headers=SALES_MANAGER)
    validate_error(response, ApiErrorId.RELEASE_DEADLINE_PASSED.value)

    stored_hold = read_hold(api, hold["id"])
    _assert_instant(
        stored_hold["release_deadline_utc"], "2026-12-02T00:00:00", "release_deadline_utc"
    )
    assert_fields(stored_hold, status="ACTIVE", hold_rank=1)
    assert_fields(read_booking(api, booking["id"]), status="TENTATIVE")


def test_third_hold_on_a_two_hold_consumer_show_rejected(api):
    """PRD §3.3: "The booking's `hold_count` must be strictly less than the class's `max_holds_per_booking`, so a booking already carrying its ceiling of live holds is refused with `ERR_HOLD_LIMIT_REACHED`."

    The refused request is identical in shape to the two that succeeded; only
    the aggregate has changed.

    Design: Corner/validations/third_hold_on_a_two_hold_consumer_show_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"])
    first_hold = place_hold(api, booking["id"])
    second_hold = place_hold(api, booking["id"])
    version_before = read_booking(api, booking["id"])["version"]

    response = api.create_hold(
        booking["id"], expected_booking_version=version_before, headers=SALES_MANAGER
    )
    validate_error(response, ApiErrorId.HOLD_LIMIT_REACHED.value)

    assert_fields(read_booking(api, booking["id"]), hold_count=2, version=version_before)
    assert_fields(read_hold(api, first_hold["id"]), hold_rank=1)
    assert_fields(read_hold(api, second_hold["id"]), hold_rank=2)

    _, meta = validate_paginated(
        api.list_holds(headers=VENUE_ADMIN, booking_id=booking["id"], limit=10, offset=0)
    )
    assert_pagination_meta(meta, total_count=2)


def test_exclusive_vendor_rule_binds_only_where_an_exclusive_vendor_exists(api):
    """PRD §3.5: "And the exclusive-vendor rule: if any vendor registered for the submitted `service_category` carries `vendor_tier` `EXCLUSIVE`, then the named vendor must be that exclusive vendor, and naming anyone else is refused with `ERR_EXCLUSIVE_VENDOR_REQUIRED`."

    Two orders differ only in service_category: cleaning has a house vendor on
    file so the OPEN cleaner is refused, while utilities has none so the
    identically tiered vendor is accepted.

    Design: Corner/validations/exclusive_vendor_rule_binds_only_where_an_exclusive_vendor_exists
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    exclusive_cleaner = register_vendor(api, **SPARKLECLEAN_EXCLUSIVE)
    open_cleaner = register_vendor(
        api,
        legal_name="Budget Cleaners",
        service_category="CLEANING",
        vendor_tier="OPEN",
        coi_expiry_date="2030-01-01",
    )
    open_utilities = register_vendor(api, **VOLT_OPEN_UTILITIES)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"])

    refused = api.create_service_order(
        booking["id"],
        payload=service_order_payload(open_cleaner["id"], "CLEANING", 1000),
        headers=EVENT_SERVICES,
    )
    validate_error(refused, ApiErrorId.EXCLUSIVE_VENDOR_REQUIRED.value)

    accepted = api.create_service_order(
        booking["id"],
        payload=service_order_payload(open_utilities["id"], "UTILITIES", 100),
        headers=EVENT_SERVICES,
    )
    utilities_order = validate_success(accepted, 201)

    stored = read_service_order(api, utilities_order["id"])
    assert_fields(
        stored, vendor_id=open_utilities["id"], approval_status="PENDING_APPROVAL"
    )

    _, meta = validate_paginated(
        api.list_service_orders(
            headers=EVENT_SERVICES, booking_id=booking["id"], limit=10, offset=0
        )
    )
    assert_pagination_meta(meta, total_count=1)

    house_cleaning_order = api.create_service_order(
        booking["id"],
        payload=service_order_payload(exclusive_cleaner["id"], "CLEANING", 1000),
        headers=EVENT_SERVICES,
    )
    validate_success(house_cleaning_order, 201)
