"""Body-shape refusals, list windowing and the identifier-resolution family."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
    ApiErrorId,
    assert_created_at_ascending,
    make_manufacturer_headers,
)
from test_helpers.factories import (
    club_payload,
    demo_event_payload,
    demonstrator_payload,
    food_product_payload,
    manufacturer_payload,
)
from test_helpers.types import ClubTier, DayPart, ProductCategory

UNKNOWN_EVENT_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_PRODUCT_ID = "00000000-0000-4000-8000-0000000000ff"


def test_demonstrator_listing_windows_rows_and_refuses_a_zero_limit(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object, where `total_count` is the number of rows matching the filters before the window is applied and `has_more` states whether any rows remain beyond the window."

    PRD §2.3: "A `limit` outside the inclusive range from 1 to 100, a negative `offset`, or a non-integer value for either is rejected with `ERR_VALIDATION` (HTTP 400)."

    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/entities/demonstrator_listing_paginates_with_limit_offset_and_total_count
    """
    club = validate_success(
        api.create_club(
            club_payload(club_number="C6002", daily_event_capacity=3, food_station_count=1),
            ADMIN_HQ_HEADERS,
        ),
        201,
    )
    ordered_ids = []
    for name, rate in (("Ada Reyes", 2000), ("Bo Ferrand", 2100), ("Cy Okafor", 2200)):
        worker = validate_success(
            api.create_demonstrator(
                demonstrator_payload(club["id"], full_name=name, hourly_rate_cents=rate),
                STAFF_OPS_HEADERS,
            ),
            201,
        )
        ordered_ids.append(worker["id"])

    first_page, first_meta = validate_paginated(
        api.list_demonstrators(
            STAFF_OPS_HEADERS,
            {"home_club_id": club["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    assert_created_at_ascending(first_page)
    assert [row["id"] for row in first_page] == ordered_ids[:2]

    second_page, second_meta = validate_paginated(
        api.list_demonstrators(
            STAFF_OPS_HEADERS,
            {"home_club_id": club["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False
    assert second_page[0]["id"] == ordered_ids[2]

    validate_error(
        api.list_demonstrators(
            STAFF_OPS_HEADERS, {"home_club_id": club["id"], "limit": 0}
        ),
        ApiErrorId.VALIDATION,
        400,
    )


def test_product_creation_without_samples_per_case_persists_nothing(api):
    """PRD §2.8: "Every required field present, every enum member legal, every numeric range respected, every date and instant well formed — otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/product_create_missing_required_samples_per_case_is_rejected
    """
    vendor = validate_success(
        api.create_manufacturer(
            manufacturer_payload(legal_name="Corran Dairy"), ADMIN_HQ_HEADERS
        ),
        201,
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])

    payload = food_product_payload(
        vendor["id"],
        sku="CD-YOG-001",
        name="Greek Yogurt Cups",
        category=ProductCategory.DAIRY,
        unit_cost_cents=150,
        weekly_sample_case_pool=12,
    )
    payload.pop("samples_per_case")

    validate_error(
        api.create_product(payload, vendor_headers), ApiErrorId.VALIDATION, 400
    )

    rows, meta = validate_paginated(
        api.list_products(vendor_headers, {"manufacturer_id": vendor["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_club_creation_refuses_an_over_range_capacity_and_an_unlisted_tier(api):
    """PRD §3.1: "A club is registered with a `club_number` that must be unique across the whole chain and must read as the letter C followed by exactly four digits, a display `name`, a `region_code` used only for reporting and never as an input to any selector or ranking, a `club_tier` of `FLAGSHIP`, `STANDARD` or `SATELLITE` that feeds the invoice base-fee multiplier, a `daily_event_capacity` from 1 through 12 that caps how many demonstrations may be live at that site on one date, a `food_station_count` from 0 through 8 counting the health-code-approved sampling stations, and a `health_permit_expires_on` date from the local health department."

    PRD §2.8: "Every required field present, every enum member legal, every numeric range respected, every date and instant well formed — otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/club_create_rejects_out_of_range_and_illegal_enum_values
    """
    validate_error(
        api.create_club(
            club_payload(
                club_number="C6006",
                name="Grantley Club 6006",
                club_tier=ClubTier.STANDARD,
                daily_event_capacity=13,
                food_station_count=1,
            ),
            ADMIN_HQ_HEADERS,
        ),
        ApiErrorId.VALIDATION,
        400,
    )

    validate_error(
        api.create_club(
            club_payload(
                club_number="C6006",
                name="Grantley Club 6006",
                club_tier="MEGA",
                daily_event_capacity=4,
                food_station_count=1,
            ),
            ADMIN_HQ_HEADERS,
        ),
        ApiErrorId.VALIDATION,
        400,
    )

    accepted = validate_success(
        api.create_club(
            club_payload(
                club_number="C6006",
                name="Grantley Club 6006",
                club_tier=ClubTier.STANDARD,
                daily_event_capacity=12,
                food_station_count=8,
            ),
            ADMIN_HQ_HEADERS,
        ),
        201,
    )
    assert accepted["daily_event_capacity"] == 12
    assert accepted["food_station_count"] == 8


def test_reading_an_unpersisted_event_id_returns_the_event_specific_not_found(api):
    """PRD §2.8: "The 404 family is: `ERR_MANUFACTURER_NOT_FOUND`, `ERR_CLUB_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_DEMO_EVENT_NOT_FOUND`, `ERR_DEMONSTRATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, and `ERR_RESOURCE_NOT_FOUND` for every other resource type — equipment units, equipment reservations, sample shipments, sample reconciliations, cancellation credits, club-product baselines and certifications."

    Design: Corner/entities/get_demo_event_with_unknown_path_id_returns_not_found
    """
    response = api.get_demo_event(UNKNOWN_EVENT_ID, ADMIN_HQ_HEADERS)

    error = validate_error(response, ApiErrorId.DEMO_EVENT_NOT_FOUND, 404)
    assert error["error_id"] != ApiErrorId.RESOURCE_NOT_FOUND
    assert error["message"].strip() != ""
    assert response.json()["response_type"] == "error"


def test_booking_with_an_unresolvable_product_reference_reports_the_product(api):
    """PRD §2.8: "Booking a demo event, for instance, resolves `manufacturer_id` first, then `club_id`, then `product_id`, so a request naming a bad manufacturer and a bad product reports the manufacturer."

    PRD §2.8: "This rung guards demo-event creation, product creation, baseline creation, demonstrator creation, equipment-unit creation, equipment-reservation creation, assignment creation, and the assignment-history injection capability, and it uses whichever member of the 404 family matches the unresolved reference."

    Design: Corner/entities/demo_event_create_with_unknown_product_id_returns_product_not_found
    """
    vendor = validate_success(
        api.create_manufacturer(
            manufacturer_payload(legal_name="Ilvermore Beverages"), ADMIN_HQ_HEADERS
        ),
        201,
    )
    club = validate_success(
        api.create_club(club_payload(club_number="C6008"), ADMIN_HQ_HEADERS), 201
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])

    validate_error(
        api.create_demo_event(
            demo_event_payload(
                vendor["id"],
                club["id"],
                UNKNOWN_PRODUCT_ID,
                event_date="2026-09-14",
                day_part=DayPart.MORNING,
                requested_sample_cases=2,
            ),
            vendor_headers,
        ),
        ApiErrorId.PRODUCT_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(
        api.list_demo_events(vendor_headers, {"manufacturer_id": vendor["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
