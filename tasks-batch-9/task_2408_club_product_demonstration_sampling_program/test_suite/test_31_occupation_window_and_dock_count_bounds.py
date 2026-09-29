"""Both edges of an occupation window, and the upper bound on a dock count."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    find_row,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.factories import reservation_payload
from test_helpers.fixtures import (
    approve,
    new_club,
    new_demo_event,
    new_equipment_unit,
    new_manufacturer,
    new_non_food_product,
    ship,
    submit,
)
from test_helpers.types import (
    DayPart,
    EquipmentType,
    ProductCategory,
    ReservationStatus,
    ShipmentStatus,
)


def test_a_hold_is_accepted_only_when_it_covers_setup_and_the_full_window(api):
    """PRD §3.5: "The interval must genuinely cover the demonstration plus its setup: `window_start_utc` must be at or before the event's `event_window_start_utc` less 45 minutes, and `window_end_utc` must be at or after the event's `event_window_end_utc`; anything narrower is refused with `ERR_RESERVATION_WINDOW_INSUFFICIENT`."

    PRD §3.5: "A successful hold opens with `reservation_status` `HELD` and `buffer_minutes` fixed at 30 — that value is not a client input and is always 30 minutes."

    PRD §2.8: "**Reservation coverage.** A reservation's `window_start_utc` must be at or before 45 minutes ahead of the event's `event_window_start_utc`, and its `window_end_utc` at or after the event's `event_window_end_utc` — otherwise `ERR_RESERVATION_WINDOW_INSUFFICIENT` (422)."

    Design: Corner/validations/reservation_coverage_passes_only_when_both_edges_are_satisfied
    """
    vendor = new_manufacturer(api, legal_name="Kirkbourne Media", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6031",
        name="Kirkbourne Club 6031",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="KM-HDP-031",
        name="Wireless Headphones",
        category=ProductCategory.ELECTRONICS,
        unit_cost_cents=8900,
        samples_per_case=2,
        weekly_sample_case_pool=20,
    )
    unit = new_equipment_unit(
        api, club["id"], asset_tag="EQ-6031-TV", equipment_type=EquipmentType.TV_CART
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])
    club_headers = make_club_headers(club["id"])

    validate_error(
        api.create_reservation(
            reservation_payload(
                unit["id"],
                event["id"],
                "2026-09-14T08:16:00Z",
                "2026-09-14T13:30:00Z",
            ),
            club_headers,
        ),
        ApiErrorId.RESERVATION_WINDOW_INSUFFICIENT,
        422,
    )

    validate_error(
        api.create_reservation(
            reservation_payload(
                unit["id"],
                event["id"],
                "2026-09-14T08:15:00Z",
                "2026-09-14T12:59:00Z",
            ),
            club_headers,
        ),
        ApiErrorId.RESERVATION_WINDOW_INSUFFICIENT,
        422,
    )

    accepted = validate_success(
        api.create_reservation(
            reservation_payload(
                unit["id"],
                event["id"],
                "2026-09-14T08:15:00Z",
                "2026-09-14T13:00:00Z",
            ),
            club_headers,
        ),
        201,
    )
    assert accepted["reservation_status"] == ReservationStatus.HELD
    assert accepted["buffer_minutes"] == 30

    rows, meta = validate_paginated(
        api.list_reservations(club_headers, {"equipment_unit_id": unit["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == accepted["id"]


def test_a_dock_count_above_the_manifest_is_refused_and_the_load_stays_in_transit(api):
    """PRD §3.7: "`cases_received` may not exceed `cases_shipped`, and a count that does is refused with `ERR_RECEIVED_EXCEEDS_SHIPPED`."

    PRD §3.7: "When `cases_received` is greater than zero but strictly less than `cases_shipped`, the shipment lands `SHORT`, and this is the branch with teeth."

    PRD §3.7: "`short_cases` is in every case the shortfall — `cases_shipped` less `cases_received`, floored at zero — and it reads zero for as long as the load is unreceived."

    PRD §2.8: "**Receipt bound.** A load's `cases_received` may not exceed its `cases_shipped` — otherwise `ERR_RECEIVED_EXCEEDS_SHIPPED` (422)."

    Design: Corner/validations/receiving_more_cases_than_were_shipped_is_rejected
    """
    vendor = new_manufacturer(api, legal_name="Loxley Provisions", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6032",
        name="Loxley Club 6032",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="LP-JAR-032",
        name="Glass Jar Set",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1500,
        samples_per_case=6,
        weekly_sample_case_pool=20,
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])
    club_headers = make_club_headers(club["id"])

    shipment = ship(api, event["id"], vendor["id"], 2, carrier_reference="TRK-66032")

    validate_error(
        api.receive_shipment(shipment["id"], {"cases_received": 3}, club_headers),
        ApiErrorId.RECEIVED_EXCEEDS_SHIPPED,
        422,
    )

    manifest = validate_success(
        api.list_shipments(event["id"], make_manufacturer_headers(vendor["id"]))
    )
    assert find_row(manifest, id=shipment["id"])["shipment_status"] == (
        ShipmentStatus.IN_TRANSIT
    )

    received = validate_success(
        api.receive_shipment(shipment["id"], {"cases_received": 1}, club_headers)
    )
    assert received["shipment_status"] == ShipmentStatus.SHORT
    assert received["cases_received"] == 1
    assert received["short_cases"] == 1
    assert received["received_at"] is not None
