"""Entity shape tests: declared field sets, defaults, computed money and listings."""

from test_helpers import (
    BALLROOM_B,
    BALLROOM_C,
    EVENT_SERVICES,
    EVENT_SERVICES_MANAGER_ID,
    FACILITIES_PLANNER,
    HALL_A,
    HALL_A1,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    NON_EXISTENT_UUID,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SETTLEMENT_ANALYST,
    SUNBELT_PROMOTER,
    VENUE_ADMIN,
    VOLT_OPEN_UTILITIES,
    ApiErrorId,
    assert_field_absent,
    assert_fields,
    assert_identity_and_audit_fields,
    assert_money_cents,
    assert_pagination_meta,
    booking_payload,
    client_payload,
    create_booking,
    order_service,
    publish_window,
    read_space,
    register_child_space,
    register_client,
    register_space,
    register_vendor,
    setup_event_lifecycle,
    space_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_client_creation_returns_the_full_declared_field_set(api):
    """PRD §3.1: "Four money and posture fields are server-derived and all start at their
    floor: `total_deposits_paid_cents`, `credit_balance_cents` and `outstanding_balance_cents`
    all initialize to 0, and `booking_standing` initializes to `GOOD`."

    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/entities/client_creation_returns_the_full_declared_field_set
    """
    response = api.create_client(payload=client_payload(**SUNBELT_PROMOTER), headers=VENUE_ADMIN)
    data = validate_success(response, 201)

    assert_fields(
        data,
        legal_name="Sunbelt Show Promotions",
        contact_email="ssp@example.org",
        organization_type="PROMOTER",
        booking_standing="GOOD",
    )
    assert_money_cents(data.get("total_deposits_paid_cents"), 0, "total_deposits_paid_cents")
    assert_money_cents(data.get("credit_balance_cents"), 0, "credit_balance_cents")
    assert_money_cents(data.get("outstanding_balance_cents"), 0, "outstanding_balance_cents")

    body = response.json()
    assert body["response_type"] == "object", f"expected an object envelope, got {body['response_type']!r}"
    assert "api_request_id" in body["meta"], f"meta is missing api_request_id: {body['meta']}"


def test_space_retrieval_by_id_returns_the_stored_row(api):
    """PRD §3.1: "Both derived counters, `committed_space_days` and `active_blackout_count`,
    initialize to 0; the first is the conserved space-day counter of §2.9, and the second simply
    counts the maintenance windows on this space that have reached `APPROVED`."

    Design: Corner/entities/space_retrieval_by_id_returns_the_stored_row
    """
    parent = register_space(api, **HALL_A)
    child = register_child_space(api, parent["id"], rigging_capable=True, **HALL_A1)

    response = api.get_space(child["id"], headers=FACILITIES_PLANNER)
    data = validate_success(response, 200)

    assert_fields(
        data,
        name="Hall A1",
        parent_space_id=parent["id"],
        daily_base_rate_cents=2_400_000,
        rigging_capable=True,
        committed_space_days=0,
        active_blackout_count=0,
    )


def test_booking_listing_filters_by_client_and_paginates(api):
    """PRD §2.3: "`offset` is the number of records to skip before the first returned record
    and defaults to 0. Both appear in the response `meta` alongside `total_count` (the number of
    records matching the filters, before pagination) and `has_more` (true when records remain
    beyond the returned page)."

    PRD §2.3: "Bookings may be filtered by `client_id`, `space_id`, `policy_window_id` and
    `status`."

    Design: Corner/entities/booking_listing_filters_by_client_and_paginates
    """
    publish_window(api, "CONSUMER_SHOW")
    meeting_room = register_space(api, **MEETING_ROOM_301)
    ballroom_b = register_space(api, **BALLROOM_B)
    ballroom_c = register_space(api, **BALLROOM_C)
    sunbelt = register_client(api, **SUNBELT_PROMOTER)
    rotary = register_client(api, **RIVERBEND_ROTARY)

    create_booking(
        api,
        sunbelt["id"],
        meeting_room["id"],
        event_name="Regional Gem Show",
        move_in_start_date="2027-03-01",
        show_start_date="2027-03-02",
        show_end_date="2027-03-04",
        move_out_end_date="2027-03-05",
    )
    create_booking(
        api,
        sunbelt["id"],
        ballroom_b["id"],
        event_name="Sunbelt Home Show",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )
    create_booking(
        api,
        sunbelt["id"],
        ballroom_c["id"],
        event_name="Sunbelt Boat Show",
        move_in_start_date="2027-09-06",
        show_start_date="2027-09-08",
        show_end_date="2027-09-10",
        move_out_end_date="2027-09-12",
    )
    rotary_booking = create_booking(
        api,
        rotary["id"],
        meeting_room["id"],
        event_name="Rotary Craft Bazaar",
        move_in_start_date="2027-11-01",
        show_start_date="2027-11-03",
        show_end_date="2027-11-05",
        move_out_end_date="2027-11-06",
    )

    first_response = api.list_bookings(headers=SALES_MANAGER, client_id=sunbelt["id"], limit=2, offset=0)
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", "a listing must report an array envelope"
    assert len(first_page) == 2, f"expected 2 rows on the first page, got {len(first_page)}"
    assert_pagination_meta(first_meta, total_count=3, limit=2, offset=0, has_more=True)

    second_response = api.list_bookings(headers=SALES_MANAGER, client_id=sunbelt["id"], limit=2, offset=2)
    second_page, second_meta = validate_paginated(second_response)
    assert len(second_page) == 1, f"expected 1 row on the second page, got {len(second_page)}"
    assert_pagination_meta(second_meta, total_count=3, offset=2, has_more=False)

    returned_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert rotary_booking["id"] not in returned_ids, "the other client's booking leaked past the filter"


def test_vendor_retrieval_with_an_unknown_identifier_not_found(api):
    """PRD §2.11: "**Path existence.** Every templated identifier in the URL resolves, validated
    strictly left to right. The first unresolvable segment decides the error, and the request is
    refused before any deeper segment is examined."

    PRD §2.11: "Each entity has its own code: `ERR_CLIENT_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`,
    `ERR_POLICY_WINDOW_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`,
    `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_LABOR_CALL_NOT_FOUND`, `ERR_CATERING_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, `ERR_BLACKOUT_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/vendor_retrieval_with_an_unknown_identifier_not_found
    """
    register_vendor(api)

    response = api.get_vendor(NON_EXISTENT_UUID, headers=EVENT_SERVICES)
    validate_error(response, ApiErrorId.VENDOR_NOT_FOUND.value)
    assert response.json()["response_type"] == "error", "a 404 must carry the error envelope"


def test_booking_creation_without_show_end_date_rejected(api):
    """PRD §2.11: "**Request body validity.** Types, enum membership, positive quantities, and
    the non-decreasing date ordering of a booking's four dates, else `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/booking_creation_without_show_end_date_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api, **SUNBELT_PROMOTER)

    payload = booking_payload(client["id"], space["id"], event_name="Regional Gem Show")
    payload.pop("show_end_date")

    response = api.create_booking(payload=payload, headers=SALES_MANAGER)
    validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_bookings(headers=SALES_MANAGER, space_id=space["id"]))
    assert_pagination_meta(meta, total_count=0)
    assert read_space(api, space["id"])["committed_space_days"] == 0, (
        "a rejected booking must not charge the space calendar"
    )


def test_space_creation_defaults_rigging_capable_to_false(api):
    """PRD §3.1: "Two optional inputs shape the space's behavior: `parent_space_id` nests the
    space under an existing one and defaults to null for a top-level space, and `rigging_capable`
    declares whether the ceiling grid will carry rigging work, defaulting to false."

    PRD §2.4: "`version` (integer): a counter that starts at 1 on creation and increments by
    exactly 1 on every mutation of that resource, including mutations the server performs on its
    own initiative as part of a cascade."

    Design: Corner/entities/space_creation_defaults_rigging_capable_to_false
    """
    response = api.create_space(payload=space_payload(**BALLROOM_B), headers=FACILITIES_PLANNER)
    data = validate_success(response, 201)

    assert data.get("rigging_capable") is False, f"rigging_capable must default to false, got {data.get('rigging_capable')!r}"
    assert "parent_space_id" in data, f"parent_space_id must be reported: {sorted(data)}"
    assert data["parent_space_id"] is None, f"parent_space_id must default to null, got {data['parent_space_id']!r}"
    assert_fields(data, committed_space_days=0, version=1)


def test_booking_creation_computes_the_three_money_fields_and_the_day_count(api):
    """PRD §3.2: "`gross_rental_cents` is the space's `daily_base_rate_cents` multiplied by those
    billable units, rounded half up to whole cents."

    PRD §3.2: "`deposit_required_cents` is `contracted_rental_cents` multiplied by one quarter,
    rounded half up to whole cents."

    PRD §3.2: "`space_days_committed` is the inclusive number of days from `move_in_start_date`
    through `move_out_end_date` — the difference in calendar days plus one — and the named space's
    `committed_space_days` rises by exactly that figure."

    Design: Corner/entities/booking_creation_computes_the_three_money_fields_and_the_day_count
    """
    window = publish_window(api, "CONSUMER_SHOW", rental_discount_pct=0.0)
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api, **SUNBELT_PROMOTER)

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Regional Gem Show",
            move_in_start_date="2027-03-01",
            show_start_date="2027-03-02",
            show_end_date="2027-03-04",
            move_out_end_date="2027-03-05",
        ),
        headers=SALES_MANAGER,
    )
    data = validate_success(response, 201)

    assert_money_cents(data.get("gross_rental_cents"), 363_600, "gross_rental_cents")
    assert_money_cents(data.get("contracted_rental_cents"), 363_600, "contracted_rental_cents")
    assert_money_cents(data.get("deposit_required_cents"), 90_900, "deposit_required_cents")
    assert_fields(data, space_days_committed=5, policy_window_id=window["id"])


def test_client_creation_mints_identity_timestamps_and_version_one(api):
    """PRD §2.4: "`version` (integer): a counter that starts at 1 on creation and increments by
    exactly 1 on every mutation of that resource, including mutations the server performs on its
    own initiative as part of a cascade."

    Design: Corner/entities/client_creation_mints_identity_timestamps_and_version_one
    """
    response = api.create_client(
        payload=client_payload(**NATIONAL_WIDGET_ASSOCIATION), headers=SALES_MANAGER
    )
    data = validate_success(response, 201)

    assert data.get("id"), "the created client must carry a non-empty id"
    assert_identity_and_audit_fields(data, expected_version=1)
    assert data["created_at"] == data["updated_at"], (
        f"an unmutated row must carry equal stamps, got {data['created_at']} and {data['updated_at']}"
    )

    stored = validate_success(api.get_client(data["id"], headers=VENUE_ADMIN), 200)
    assert_identity_and_audit_fields(stored, expected_version=1)
    assert stored["created_at"] == stored["updated_at"], (
        f"an unmutated row must carry equal stamps, got {stored['created_at']} and {stored['updated_at']}"
    )


def test_usage_record_cannot_be_updated_and_carries_no_version(api):
    """PRD §2.4: "A `SpaceUsageRecord` — the attestation of how a space was actually used on one
    calendar day — carries only `id` and `created_at`; it has no `updated_at` and no `version`."

    PRD §3.8: "Each record names its `booking_id`, the `usage_date` being attested, and the
    `usage_kind` — `MOVE_IN`, `SHOW`, `DARK`, `MOVE_OUT` or `HOLDOVER` — and the server stamps
    `recorded_by_user_id` from the acting `X-User-ID`."

    Design: Corner/entities/usage_record_cannot_be_updated_and_carries_no_version
    """
    context = setup_event_lifecycle(
        api,
        stage="in_house",
        space=dict(MEETING_ROOM_301),
        client=dict(SUNBELT_PROMOTER),
        booking={
            "event_name": "Regional Gem Show",
            "move_in_start_date": "2027-03-01",
            "show_start_date": "2027-03-02",
            "show_end_date": "2027-03-04",
            "move_out_end_date": "2027-03-05",
        },
        usage_records=[("2027-03-01", "MOVE_IN")],
    )
    booking_id = context["booking"]["id"]

    response = api.list_usage_records(headers=SETTLEMENT_ANALYST, booking_id=booking_id)
    rows, _ = validate_paginated(response)
    assert len(rows) == 1, f"expected exactly 1 attested day, got {len(rows)}"

    row = rows[0]
    assert_fields(
        row,
        booking_id=booking_id,
        usage_date="2027-03-01",
        usage_kind="MOVE_IN",
        recorded_by_user_id=EVENT_SERVICES_MANAGER_ID,
    )
    assert_field_absent(row, "version")


def test_service_order_junction_links_many_bookings_to_many_vendors(api):
    """PRD §3.5: "The order records its `booking_id` and opens with two independent status
    dimensions on the same row: `approval_status` `PENDING_APPROVAL` and `billing_status`
    `UNBILLED`, with `estimated_charge_cents` 0, `actual_quantity` null and `actual_charge_cents`
    null."

    PRD §2.3: "Service orders may be filtered by `booking_id`, `vendor_id`, `approval_status` and
    `billing_status`."

    Design: Corner/entities/service_order_junction_links_many_bookings_to_many_vendors
    """
    publish_window(api, "CONSUMER_SHOW")
    ballroom_b = register_space(api, **BALLROOM_B)
    ballroom_c = register_space(api, **BALLROOM_C)
    cleaning_vendor = register_vendor(api)
    utilities_vendor = register_vendor(api, **VOLT_OPEN_UTILITIES)
    client = register_client(api, **SUNBELT_PROMOTER)

    booking_b = create_booking(
        api,
        client["id"],
        ballroom_b["id"],
        event_name="Sunbelt Home Show",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )
    booking_c = create_booking(
        api,
        client["id"],
        ballroom_c["id"],
        event_name="Sunbelt Boat Show",
        move_in_start_date="2027-09-06",
        show_start_date="2027-09-08",
        show_end_date="2027-09-10",
        move_out_end_date="2027-09-12",
    )

    order_service(api, booking_b["id"], cleaning_vendor["id"], "CLEANING", 1000)
    order_service(api, booking_b["id"], utilities_vendor["id"], "UTILITIES", 200)
    order_service(api, booking_c["id"], cleaning_vendor["id"], "CLEANING", 1500)

    by_booking, booking_meta = validate_paginated(
        api.list_service_orders(headers=EVENT_SERVICES, booking_id=booking_b["id"])
    )
    assert_pagination_meta(booking_meta, total_count=2)
    assert {row["vendor_id"] for row in by_booking} == {cleaning_vendor["id"], utilities_vendor["id"]}, (
        "the booking projection must name both vendors ordered against it"
    )

    by_vendor, vendor_meta = validate_paginated(
        api.list_service_orders(headers=EVENT_SERVICES, vendor_id=cleaning_vendor["id"])
    )
    assert_pagination_meta(vendor_meta, total_count=2)
    assert {row["booking_id"] for row in by_vendor} == {booking_b["id"], booking_c["id"]}, (
        "the vendor projection must name both bookings it was ordered on"
    )
    for row in by_booking + by_vendor:
        assert_fields(
            row,
            approval_status="PENDING_APPROVAL",
            billing_status="UNBILLED",
            estimated_charge_cents=0,
        )
