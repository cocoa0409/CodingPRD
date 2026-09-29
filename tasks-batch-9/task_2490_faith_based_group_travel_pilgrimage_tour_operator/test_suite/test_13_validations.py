"""Individual guards refusing one call while the neighbouring call that differs
in exactly one input is accepted: mobility, catering lead time, room occupancy,
roommate membership, risk acknowledgement, the min-pax floor and pagination."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_room,
    confirm_traveler,
    create_advisory,
    create_departure,
    enrol_traveler,
    fully_paid_traveler,
    hold_filler_service,
    open_departure,
    open_sales,
    pay,
    program_with_departure,
    publish_advisory,
    read_departure,
    read_traveler,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
FINANCE = TEST_USERS["finance_controller"]


def test_a_walker_traveler_may_not_be_roomed_above_the_ground_floor(api):
    """PRD §3.5: "A traveler whose `mobility_code` is `WHEELCHAIR` or `WALKER`
    may not be assigned a room with `ground_floor` false; that is
    `ERR_MOBILITY_ACCOMMODATION_UNMET` (HTTP 422), and it outranks every other
    rooming rule, including the pairing and capacity checks."

    Design: Corner/validations/rooming_a_walker_traveler_above_ground_floor_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    walker = enrol_traveler(
        departure_id,
        full_name="Walker Traveler",
        date_of_birth="1949-04-02",
        room_type_requested="TWIN",
        mobility_code="WALKER",
    )
    able = enrol_traveler(
        departure_id,
        full_name="Able Traveler",
        date_of_birth="1975-01-10",
        room_type_requested="TWIN",
    )
    # The identical assignment, differing only in the mobility code, is accepted.
    assign_room(
        able["id"], room_type_assigned="TWIN", room_label="IL-402", ground_floor=False
    )

    response = api_client.assign_rooming(
        walker["id"],
        {"room_type_assigned": "TWIN", "room_label": "IL-403", "ground_floor": False},
        PLANNER,
    )
    validate_error(response, ApiErrorId.MOBILITY_ACCOMMODATION_UNMET.value)

    assert read_traveler(walker["id"])["room_label"] is None
    roomed = read_traveler(able["id"])
    assert roomed["room_label"] == "IL-402"
    assert roomed["ground_floor"] is False


def test_kosher_catering_eleven_days_out_is_inside_the_lead_time(api):
    """PRD §3.5: "Requesting `KOSHER` or `HALAL` catering requires lead time:
    when the whole-day difference between the departure's `departure_date` and
    the logical clock's date is strictly less than 21 days, any `dietary_codes`
    array containing `KOSHER` or `HALAL` is rejected with
    `ERR_DIETARY_LEAD_TIME_UNMET` (HTTP 422); exactly 21 days still qualifies."

    Design: Corner/validations/kosher_catering_requested_inside_lead_time_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    kosher = enrol_traveler(
        departure_id, full_name="Kosher Traveler", date_of_birth="1975-01-10"
    )
    vegetarian = enrol_traveler(
        departure_id, full_name="Vegetarian Traveler", date_of_birth="1976-03-12"
    )
    set_clock("2026-10-21T00:00:00Z")
    # The same call for a code with no lead time attached is accepted.
    assign_room(
        vegetarian["id"],
        room_type_assigned="DOUBLE",
        room_label="IL-210",
        dietary_codes=["VEGETARIAN"],
    )

    response = api_client.assign_rooming(
        kosher["id"],
        {
            "room_type_assigned": "DOUBLE",
            "room_label": "IL-211",
            "ground_floor": False,
            "dietary_codes": ["KOSHER"],
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.DIETARY_LEAD_TIME_UNMET.value)

    refused = read_traveler(kosher["id"])
    assert refused["room_label"] is None
    # Untouched, the array still holds the single default code.
    assert refused["dietary_codes"] == ["NONE"]
    assert read_traveler(vegetarian["id"])["dietary_codes"] == ["VEGETARIAN"]


def test_kosher_catering_exactly_twenty_one_days_out_still_qualifies(api):
    """PRD §3.5: "Requesting `KOSHER` or `HALAL` catering requires lead time:
    when the whole-day difference between the departure's `departure_date` and
    the logical clock's date is strictly less than 21 days, any `dietary_codes`
    array containing `KOSHER` or `HALAL` is rejected with
    `ERR_DIETARY_LEAD_TIME_UNMET` (HTTP 422); exactly 21 days still qualifies."

    Design: Corner/validations/kosher_catering_exactly_at_lead_time_accepted
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"],
        full_name="Kosher Traveler",
        date_of_birth="1975-01-10",
    )
    # 2026-10-11 is exactly 21 whole days before the 2026-11-01 departure.
    set_clock("2026-10-11T00:00:00Z")

    updated = validate_success(
        api_client.assign_rooming(
            traveler["id"],
            {
                "room_type_assigned": "DOUBLE",
                "room_label": "IL-212",
                "ground_floor": True,
                "dietary_codes": ["KOSHER", "VEGETARIAN"],
            },
            PLANNER,
        )
    )

    assert updated["room_type_assigned"] == "DOUBLE"
    assert updated["room_label"] == "IL-212"
    assert updated["ground_floor"] is True
    assert updated["dietary_codes"] == ["KOSHER", "VEGETARIAN"]


def test_a_third_traveler_cannot_join_a_double_room_label(api):
    """PRD §3.5: "And the room must have space: the count of travelers already
    assigned to the same `room_label` on the same departure plus this one must not
    exceed the capacity of `room_type_assigned`, which is 1 for `SINGLE` and 2 for
    both `DOUBLE` and `TWIN`; exceeding it is `ERR_ROOM_CAPACITY_EXCEEDED` (HTTP
    409)."

    Design: Corner/validations/third_traveler_in_a_double_room_label_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    first = enrol_traveler(
        departure_id, full_name="Room Mate One", date_of_birth="1975-01-10"
    )
    second = enrol_traveler(
        departure_id, full_name="Room Mate Two", date_of_birth="1976-03-12"
    )
    third = enrol_traveler(
        departure_id, full_name="Room Mate Three", date_of_birth="1977-07-19"
    )
    assign_room(first["id"], room_type_assigned="DOUBLE", room_label="IL-204")
    assign_room(
        second["id"],
        room_type_assigned="DOUBLE",
        room_label="IL-204",
        roommate_pilgrim_id=first["id"],
    )

    response = api_client.assign_rooming(
        third["id"],
        {"room_type_assigned": "DOUBLE", "room_label": "IL-204", "ground_floor": False},
        PLANNER,
    )
    validate_error(response, ApiErrorId.ROOM_CAPACITY_EXCEEDED.value)

    assert read_traveler(third["id"])["room_label"] is None
    assert read_traveler(first["id"])["room_label"] == "IL-204"
    paired = read_traveler(second["id"])
    assert paired["room_label"] == "IL-204"
    assert paired["roommate_pilgrim_id"] == first["id"]


def test_a_roommate_from_another_departure_is_refused(api):
    """PRD §3.5: "A supplied `roommate_pilgrim_id` must name a different traveler
    on the same departure whose `booking_status` is not `CANCELLED` and whose
    `room_type_requested` equals this traveler's `room_type_requested`; naming
    oneself, a traveler on another departure, a cancelled traveler or a
    mismatched preference is `ERR_ROOMMATE_INVALID` (HTTP 422)."

    Design: Corner/validations/roommate_nominated_from_another_departure_rejected
    """
    program, november = program_with_departure()
    december = create_departure(
        program["id"],
        departure_date="2026-12-06",
        return_date="2026-12-16",
        deposit_due_date="2026-09-20",
        final_payment_due_date="2026-11-20",
    )
    hold_filler_service(program, november)
    hold_filler_service(program, december)
    open_sales(november["id"])
    open_sales(december["id"])
    here = enrol_traveler(
        november["id"], full_name="November Traveler", date_of_birth="1975-01-10"
    )
    elsewhere = enrol_traveler(
        december["id"], full_name="December Traveler", date_of_birth="1976-03-12"
    )

    response = api_client.assign_rooming(
        here["id"],
        {
            "room_type_assigned": "DOUBLE",
            "room_label": "IL-206",
            "ground_floor": False,
            "roommate_pilgrim_id": elsewhere["id"],
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.ROOMMATE_INVALID.value)

    refused = read_traveler(here["id"])
    assert refused["room_label"] is None
    assert refused["roommate_pilgrim_id"] is None
    assert read_traveler(elsewhere["id"])["roommate_pilgrim_id"] is None


def test_confirming_into_a_restricted_posture_needs_the_acknowledgement(api):
    """PRD §3.5: "The departure's `risk_posture` must not be `SUSPENDED`, failing
    which the answer is `ERR_DEPARTURE_POSTURE_BLOCKS_CONFIRM` (HTTP 422); and
    when the posture is `RESTRICTED`, the traveler's `risk_acknowledged` must be
    true, failing which the answer is `ERR_RISK_ACKNOWLEDGEMENT_REQUIRED`."

    Design: Corner/validations/confirm_on_restricted_departure_without_acknowledgement_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    silent = enrol_traveler(
        departure_id,
        full_name="Unacknowledged Traveler",
        date_of_birth="1975-01-10",
    )
    signed = enrol_traveler(
        departure_id,
        full_name="Acknowledged Traveler",
        date_of_birth="1976-03-12",
        risk_acknowledged=True,
    )
    for traveler in (silent, signed):
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    advisory = create_advisory(country="IL", level="RECONSIDER", source="MOFA")
    publish_advisory(advisory["id"])
    # The traveler who signed confirms under the very same posture.
    assert confirm_traveler(signed["id"])["booking_status"] == "CONFIRMED"

    response = api_client.confirm_pilgrim(silent["id"], PLANNER)
    validate_error(response, ApiErrorId.RISK_ACKNOWLEDGEMENT_REQUIRED.value)

    assert read_departure(departure_id)["risk_posture"] == "RESTRICTED"
    refused = read_traveler(silent["id"])
    assert refused["risk_acknowledged"] is False
    assert refused["booking_status"] == "DEPOSITED"


def test_closing_sales_one_fully_paid_traveler_short_of_min_pax_is_refused(api):
    """PRD §3.1: "Its guards are evaluated in a fixed order: first whether the
    final variant finds a tier covering the fully-paid confirmed paying count,
    including the case of a count of zero, failing which the answer is
    `ERR_NO_APPLICABLE_PRICE_TIER`; then whether that same count reaches the
    departure's `min_pax`, failing which the answer is `ERR_MIN_PAX_NOT_MET`;
    then whether `pending_modification_required` is false, failing which the
    answer is `ERR_PENDING_MODIFICATION_UNRATIFIED`."

    Design: Corner/validations/close_sales_below_min_pax_rejected
    """
    stage = open_departure(departure_overrides={"min_pax": 2})
    departure_id = stage["departure"]["id"]
    # One traveler in the final variant's population, against a floor of two.
    settled = fully_paid_traveler(departure_id, full_name="Confirmed Traveler")
    waiting = enrol_traveler(
        departure_id, full_name="Inquiry Traveler", date_of_birth="1976-03-12"
    )

    response = api_client.close_departure_sales(departure_id, PLANNER)
    validate_error(response, ApiErrorId.MIN_PAX_NOT_MET.value)

    live = read_departure(departure_id)
    assert live["status"] == "OPEN_FOR_SALE"
    assert live["final_tier_code"] is None
    assert read_traveler(settled["id"])["booking_status"] == "CONFIRMED"
    assert read_traveler(waiting["id"])["booking_status"] == "INQUIRY"


def test_a_limit_one_past_the_maximum_is_refused_rather_than_clamped(api):
    """PRD §2.3: "A `limit` below 1, a `limit` above 100, an `offset` below 0, or
    either parameter carrying a non-integer value is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/list_limit_above_maximum_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    enrol_traveler(departure_id, full_name="Traveler A", date_of_birth="1975-01-10")

    response = api_client.list_pilgrims(
        PLANNER, {"departure_id": departure_id, "limit": 101, "offset": 0}
    )

    validate_error(response, ApiErrorId.INVALID_PAGINATION.value)
