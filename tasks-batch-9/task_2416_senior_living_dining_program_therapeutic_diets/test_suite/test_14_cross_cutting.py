"""Cross-cutting layers: optimistic concurrency, filtered pagination and denormalized counters."""
from test_helpers import (
    CLINICAL_STAFF,
    DIETITIAN,
    DINING_MANAGER,
    ApiErrorId,
    add_verified_resident,
    create_community,
    create_reservation,
    create_resident,
    create_venue,
    read_community,
    read_reservation,
    read_seat_availability,
    release_reservation,
    resident_version,
    set_clock,
    set_dining_status,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
)


def test_the_dining_status_moves_bump_the_version_the_order_create_must_match(api):
    """Two participation changes the ordering clinician never made advance the resident's `version`
    to 3, so the create pinned at 1 is refused; the refusal itself moves nothing and the re-read
    version is accepted, after which the create bumps the version once more.

    PRD: "Creating a diet order requires the non-optional field `expected_resident_version`, carrying
    the client's last observed `version` of the target `Resident`. If that value does not equal the
    resident's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_resident_version_on_diet_order_create
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Fergus Danvers", baseline_weight_kg=74.0
    )
    assert resident["version"] == 1

    away = set_dining_status(resident["id"], "ON_LEAVE")
    back = set_dining_status(resident["id"], "ACTIVE")
    assert away["version"] == 2
    assert back["version"] == 3
    assert back["dining_status"] == "ACTIVE"

    stale = api.create_diet_order(
        {
            "resident_id": resident["id"],
            "texture_level": "REGULAR",
            "liquid_consistency": "THIN",
            "expected_resident_version": 1,
        },
        CLINICAL_STAFF,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(
        api.list_diet_orders(CLINICAL_STAFF, params={"resident_id": resident["id"]})
    )
    assert meta["total_count"] == 0
    assert resident_version(resident["id"]) == 3

    accepted = validate_success(
        api.create_diet_order(
            {
                "resident_id": resident["id"],
                "texture_level": "REGULAR",
                "liquid_consistency": "THIN",
                "expected_resident_version": 3,
            },
            CLINICAL_STAFF,
        ),
        201,
    )

    assert accepted["review_status"] == "AWAITING_DIETITIAN"
    assert resident_version(resident["id"]) == 4


def test_another_residents_booking_invalidates_the_observed_venue_version(api):
    """The venue keeps ten free seats, yet the second booking pinned at the pre-booking version is
    refused on concurrency alone; the re-read version lets the identical payload through.

    PRD: "Creating a seating reservation requires the non-optional field `expected_venue_version`,
    carrying the client's last observed `version` of the target `DiningVenue`. If that value does not
    equal the venue's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_venue_version_on_reservation_create
    """
    set_clock("2026-08-10T09:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    venue = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=12,
        care_levels_served=["ASSISTED_LIVING"],
    )
    assert venue["version"] == 1
    resident_a = add_verified_resident(community, "Resident A", baseline_weight_kg=70.0)
    resident_b = add_verified_resident(community, "Resident B", baseline_weight_kg=71.0)

    first = create_reservation(
        resident_a["id"],
        venue["id"],
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=1,
        expected_venue_version=1,
    )
    assert first["status"] == "RESERVED"

    payload = {
        "resident_id": resident_b["id"],
        "venue_id": venue["id"],
        "service_date": "2026-08-11",
        "meal_period": "LUNCH",
        "seat_start_utc": "2026-08-11T12:00:00Z",
        "party_size": 1,
        "expected_venue_version": 1,
    }
    stale = api.create_reservation(payload, DINING_MANAGER)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
    assert venue_version(venue["id"]) == 2

    second = validate_success(
        api.create_reservation(dict(payload, expected_venue_version=2), DINING_MANAGER),
        201,
    )
    assert second["status"] == "RESERVED"

    availability = read_seat_availability(venue["id"], "2026-08-11", "LUNCH")
    assert availability["committed_seats"] == 2
    assert availability["open_seats"] == 10


def test_the_status_filter_narrows_the_population_the_window_then_pages(api):
    """`total_count` counts the two `RESERVED` rows rather than all three, the released middle row is
    skipped instead of reordered, an offset past the end is an empty page rather than an error, and
    the released row is still reachable under its own filter.

    PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of
    rows matching the filters before the window is applied) and `has_more` (true when rows remain
    beyond the current window)."

    Design: Corner/cross_cutting_layers/reservation_listing_filter_with_limit_and_offset
    """
    set_clock("2026-08-10T09:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    venue = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=12,
        care_levels_served=["ASSISTED_LIVING"],
    )
    residents = [
        add_verified_resident(community, name, baseline_weight_kg=weight)
        for name, weight in (
            ("Resident A", 70.0),
            ("Resident B", 71.0),
            ("Resident C", 72.0),
        )
    ]
    bookings = [
        create_reservation(
            resident["id"],
            venue["id"],
            "2026-08-11",
            "LUNCH",
            "2026-08-11T12:00:00Z",
            party_size=1,
        )
        for resident in residents
    ]
    released = release_reservation(bookings[1]["id"], reason="family outing")
    assert released["status"] == "RELEASED"

    reserved_filter = {
        "venue_id": venue["id"],
        "service_date": "2026-08-11",
        "meal_period": "LUNCH",
        "status": "RESERVED",
    }

    page_one, meta_one = validate_paginated(
        api.list_reservations(
            DINING_MANAGER, params=dict(reserved_filter, limit=1, offset=0)
        )
    )
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [bookings[0]["id"]]

    page_two, meta_two = validate_paginated(
        api.list_reservations(
            DINING_MANAGER, params=dict(reserved_filter, limit=1, offset=1)
        )
    )
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False
    assert [row["id"] for row in page_two] == [bookings[2]["id"]]

    page_three, meta_three = validate_paginated(
        api.list_reservations(
            DINING_MANAGER, params=dict(reserved_filter, limit=1, offset=2)
        )
    )
    assert meta_three["total_count"] == 2
    assert meta_three["has_more"] is False
    assert page_three == []

    released_rows, released_meta = validate_paginated(
        api.list_reservations(
            DINING_MANAGER, params={"venue_id": venue["id"], "status": "RELEASED"}
        )
    )
    assert released_meta["total_count"] == 1
    assert released_rows[0]["id"] == bookings[1]["id"]
    assert read_reservation(bookings[1]["id"])["status"] == "RELEASED"


def test_the_pending_count_recomputes_over_both_status_axes(api):
    """`CHANGES_REQUESTED` still counts as pending, an approval drops its order out through the
    review axis, and a discontinuation drops the other one out through the clinical axis alone even
    though its `review_status` never moves.

    PRD: "A community's `pending_dietitian_review_count` is a denormalized count of that community's
    diet orders whose `review_status` is `AWAITING_DIETITIAN`, `CHANGES_REQUESTED` or
    `REREVIEW_REQUIRED` **and** whose `clinical_status` is `PENDING_REVIEW` or `ACTIVE`; it is
    recomputed in full on every write that touches a diet order's `review_status`, including writes
    that leave the count unchanged."

    Design: Corner/cross_cutting_layers/community_pending_review_count_reconciles_across_writes
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    assert community["pending_dietitian_review_count"] == 0
    assert community["active_menu_cycle_id"] is None
    resident_a = create_resident(
        community["id"], full_name="Resident A", baseline_weight_kg=70.0
    )
    resident_b = create_resident(
        community["id"], full_name="Resident B", baseline_weight_kg=71.0
    )
    order_a = validate_success(
        api.create_diet_order(
            {
                "resident_id": resident_a["id"],
                "texture_level": "REGULAR",
                "liquid_consistency": "THIN",
                "expected_resident_version": resident_a["version"],
            },
            CLINICAL_STAFF,
        ),
        201,
    )
    order_b = validate_success(
        api.create_diet_order(
            {
                "resident_id": resident_b["id"],
                "texture_level": "MINCED_MOIST",
                "liquid_consistency": "THIN",
                "expected_resident_version": resident_b["version"],
            },
            CLINICAL_STAFF,
        ),
        201,
    )
    assert read_community(community["id"])["pending_dietitian_review_count"] == 2

    changes = validate_success(
        api.dietitian_review_diet_order(
            order_b["id"],
            {"decision": "REQUEST_CHANGES", "reviewer_note": "confirm swallow assessment"},
            DIETITIAN,
        )
    )
    assert changes["review_status"] == "CHANGES_REQUESTED"
    assert read_community(community["id"])["pending_dietitian_review_count"] == 2

    approved = validate_success(
        api.dietitian_review_diet_order(order_a["id"], {"decision": "APPROVE"}, DIETITIAN)
    )
    assert approved["review_status"] == "APPROVED"
    assert approved["clinical_status"] == "ACTIVE"
    assert read_community(community["id"])["pending_dietitian_review_count"] == 1

    discontinued = validate_success(
        api.discontinue_diet_order(
            order_b["id"], {"reason": "resident transferred"}, CLINICAL_STAFF
        )
    )

    assert discontinued["clinical_status"] == "DISCONTINUED"
    assert discontinued["review_status"] == "CHANGES_REQUESTED"
    assert read_community(community["id"])["pending_dietitian_review_count"] == 0
