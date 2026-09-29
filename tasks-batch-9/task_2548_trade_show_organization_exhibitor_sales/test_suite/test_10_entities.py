"""
Entity shapes as the contract declares them: created rows, retrieved rows,
declared defaults, server-minted system fields, filtered pages and the
existence errors that guard every reference.
"""

from datetime import datetime

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoothStatus,
    ExhibitorStatus,
    FloorPosture,
    PremiumZone,
    PriorityTier,
    ShowStatus,
    SpaceContractStatus,
    VenueContractStatus,
    assert_lead_scan,
    assert_show_area_ledger,
    assert_venue_contract,
    factories as f,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"
UNKNOWN_BOOTH_ID = "00000000-0000-4000-8000-000000000999"
UNKNOWN_SHOW_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_EXHIBITOR_ID = "00000000-0000-4000-8000-0000000000bb"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)
D010 = f.inline_booth_payload("D010", 10, 10)


def test_a_registered_agreement_echoes_its_rate_card_and_opens_in_draft(
    client: ApiClient,
):
    """
    Registration returns the whole declared row, unexecuted and uncounted.

    "A newly registered agreement has a `status` of `DRAFT`, a null `executed_at`, a
    null `terminated_effective_date`, and a `show_count` of zero."  "`version`, an
    integer that begins at 1 when the row is created and increases by exactly 1 on
    every mutation."

    Design: Corner/entities/venue_contract_creation_returns_every_declared_field
    """
    fx.set_clock(client, CLOCK)
    created = validate_success(
        client.create_venue_contract(f.venue_contract_payload(), fx.DIRECTOR_HEADERS),
        201,
    )
    assert_venue_contract(created, VenueContractStatus.DRAFT)
    assert created["executed_at"] is None
    assert created["terminated_effective_date"] is None
    assert created["version"] == 1
    assert created["show_count"] == 0
    assert created["committed_net_sqft_per_year"] == 1200
    assert created["attrition_allowance_pct"] == 15
    assert created["labor_rate_cents_per_hour"] == 9500
    assert created["electrical_rate_cents_per_amp"] == 4200
    assert created["material_handling_rate_cents_per_cwt"] == 8800

    reread = validate_success(
        client.get_venue_contract(created["id"], fx.DIRECTOR_HEADERS)
    )
    assert reread == created


def test_a_planning_edition_reads_back_with_a_zeroed_area_ledger(client: ApiClient):
    """
    A freshly created edition reports zeros, and invents neither its sellable area
    nor its advance deadline before publication.

    "A newly created edition starts with a `status` of `PLANNING`, a
    `selection_round` of 0, a `floor_posture` of `OPEN`, a null `cancellation_reason`,
    and every area and money ledger ... initialised to zero, with
    `advance_order_deadline` unset until the floor plan is published."

    Design: Corner/entities/get_show_returns_the_stored_row_with_its_area_ledger
    """
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)

    show = validate_success(
        client.get_show(env["show"]["id"], fx.SALES_REP_HEADERS)
    )
    assert show["status"] == ShowStatus.PLANNING
    assert show["selection_round"] == 0
    assert show["venue_contract_id"] == env["venue_contract"]["id"]
    assert show["base_rate_cents_per_sqft"] == 3275
    assert_show_area_ledger(show, 0, 0, 0, 0, 0)
    assert show["floor_posture"] == FloorPosture.OPEN
    assert show["upheld_violation_count"] == 0
    assert show["net_sellable_sqft"] == 0
    assert show["advance_order_deadline"] is None
    assert show["cancellation_reason"] is None

    agreement = validate_success(
        client.get_venue_contract(env["venue_contract"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert agreement["show_count"] == 1


def test_the_booth_page_reports_its_window_and_its_filtered_total(client: ApiClient):
    """
    Three available booths read two at a time, then the empty held page.

    "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filter
    before the page window is applied, and `has_more` is true exactly when rows
    matching the filter remain beyond the current window."

    Design: Corner/entities/booth_listing_filters_by_status_and_paginates
    """
    fx.set_clock(client, CLOCK)
    env = fx.show_with_booths(client, [A100, C050, D010])
    show_id = env["show"]["id"]

    first_page, meta = validate_paginated(
        client.list_booths(
            fx.SALES_REP_HEADERS,
            {"show_id": show_id, "status": BoothStatus.AVAILABLE,
             "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    second_page, meta = validate_paginated(
        client.list_booths(
            fx.SALES_REP_HEADERS,
            {"show_id": show_id, "status": BoothStatus.AVAILABLE,
             "limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1
    assert meta["total_count"] == 3
    assert meta["offset"] == 2
    assert meta["has_more"] is False
    assert all(row["show_id"] == show_id for row in first_page + second_page)

    held_page, meta = validate_paginated(
        client.list_booths(
            fx.SALES_REP_HEADERS, {"show_id": show_id, "status": BoothStatus.HELD}
        )
    )
    assert held_page == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_an_unknown_booth_id_is_a_not_found_and_not_an_empty_body(
    client: ApiClient,
):
    """
    A well-formed identifier that resolves to nothing.

    "**Existence**, path resources before body references, in this order: venue
    contract (`ERR_VENUE_CONTRACT_NOT_FOUND`), show (`ERR_SHOW_NOT_FOUND`), exhibitor
    (`ERR_EXHIBITOR_NOT_FOUND`), booth (`ERR_BOOTH_NOT_FOUND`)"

    Design: Corner/entities/get_booth_with_unknown_id_returns_booth_not_found
    """
    fx.set_clock(client, CLOCK)

    validate_error(
        client.get_booth(UNKNOWN_BOOTH_ID, fx.FLOOR_MANAGER_HEADERS),
        ApiErrorId.BOOTH_NOT_FOUND,
        404,
    )


def test_a_show_missing_its_base_rate_is_refused_before_anything_is_written(
    client: ApiClient,
):
    """
    Every other field is valid; the omitted required input still stops the write.

    "The body must parse; every input field the endpoint requires must be present"
    "Failures here are `ERR_VALIDATION` (HTTP 422). These are structural, single-field
    checks that consult no stored data, which is why they outrank even existence."

    Design: Corner/entities/show_creation_without_base_rate_returns_validation
    """
    fx.set_clock(client, CLOCK)
    agreement = fx.executed_venue_contract(client)

    body = f.show_payload(agreement["id"])
    body.pop("base_rate_cents_per_sqft")
    validate_error(
        client.create_show(body, fx.DIRECTOR_HEADERS),
        ApiErrorId.VALIDATION,
        422,
    )

    rows, meta = validate_paginated(
        client.list_venue_contract_shows(agreement["id"], fx.DIRECTOR_HEADERS)
    )
    assert rows == []
    assert meta["total_count"] == 0
    reread = validate_success(
        client.get_venue_contract(agreement["id"], fx.DIRECTOR_HEADERS)
    )
    assert reread["show_count"] == 0


def test_omitted_optional_inputs_take_exactly_their_declared_defaults(
    client: ApiClient,
):
    """
    A booth with no zone, an exhibitor with no history, a contract with no placement
    flag and no booth list, under an agreement with no fee schedule.

    "an optional `premium_zone`, one of `NONE`, `MAIN_AISLE`, `ENTRANCE` or
    `FOOD_COURT`, which defaults to `NONE` when omitted"  "the number of consecutive
    prior editions it has exhibited at, at least zero, defaulting to zero when
    omitted"  "A new contract opens in `OFFERED` status with `negotiation_round` at 0,
    `requested_discount_pct` and `approved_discount_pct` at 0"  "When the field is
    omitted at registration, it defaults to three buckets — 25 percent at 180 days
    out, 50 percent at 90 days out, and 100 percent at zero days out."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    show_id = env["show"]["id"]

    booth = validate_success(
        client.create_booth(
            show_id,
            f.booth_payload("Z900", 20, 20, location_class="INLINE",
                            max_height_ft=12, premium_zone=None),
            fx.FLOOR_MANAGER_HEADERS,
        ),
        201,
    )
    assert booth["premium_zone"] == PremiumZone.NONE
    assert booth["area_sqft"] == 400

    exhibitor = fx.exhibitor(client, "Default Trading Co", fx.SALES_REP_HEADERS,
                             contact_email="sales@default.example")
    assert exhibitor["consecutive_years"] == 0
    assert exhibitor["ledger_points"] == 0
    assert exhibitor["penalty_points"] == 0
    assert exhibitor["status"] == ExhibitorStatus.ACTIVE

    validate_success(client.publish_floor_plan(show_id, fx.DIRECTOR_HEADERS))
    contract = fx.offered_contract(client, show_id, exhibitor["id"], 400)
    assert contract["premium_placement_requested"] is False
    assert contract["requested_discount_pct"] == 0
    assert contract["approved_discount_pct"] == 0
    assert contract["negotiation_round"] == 0
    assert contract["status"] == SpaceContractStatus.OFFERED
    assert contract["offered_booth_ids"] == [booth["id"]]

    agreement = validate_success(
        client.get_venue_contract(env["venue_contract"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert agreement["cancellation_fee_schedule"] == [
        {"min_days_out": 180, "pct": 25},
        {"min_days_out": 90, "pct": 50},
        {"min_days_out": 0, "pct": 100},
    ]
    assert agreement["status"] == VenueContractStatus.EXECUTED


def test_publication_floors_the_aisle_deduction_and_dates_the_advance_window(
    client: ApiClient,
):
    """
    A 100000 sqft hall at a forty percent aisle ratio, moving in on 2027-03-01.

    "On success the system writes `net_sellable_sqft` as the show's `gross_sqft`
    multiplied by one hundred less its `aisle_ratio_pct`, divided by one hundred, with
    any fractional square foot discarded downward."  "Publication also computes the
    edition's `advance_order_deadline` as the date of `move_in_start` less twenty-one
    days"

    Design: Corner/entities/publish_computes_net_sellable_sqft_and_advance_order_deadline
    """
    fx.set_clock(client, CLOCK)
    env = fx.show_with_booths(client, [A100, C050])
    before_version = env["show"]["version"]

    published = validate_success(
        client.publish_floor_plan(env["show"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert published["status"] == ShowStatus.SPACE_SELECTION
    assert published["net_sellable_sqft"] == 60000
    assert published["advance_order_deadline"] == "2027-02-08"
    assert_show_area_ledger(published, 600, 0, 0, 600, 0)
    assert published["floor_posture"] == FloorPosture.OPEN
    assert published["version"] == before_version + 1


def test_an_exhibitor_row_is_minted_server_side_with_every_counter_at_zero(
    client: ApiClient,
):
    """
    Only the three declared inputs come from the request.

    "Every resource in this system is addressed by an `id` that is a server-minted
    UUID with no type prefix; clients never supply one."  "A new account has a
    `status` of `ACTIVE` and every point counter at zero: `ledger_points`,
    `sponsorship_fulfillment_points` and `penalty_points`."

    Design: Corner/entities/exhibitor_creation_assigns_system_fields_only_on_the_server
    """
    fx.set_clock(client, CLOCK)

    exhibitor = validate_success(
        client.create_exhibitor(
            f.exhibitor_payload("Nordic Furnishings", "sales@nordic.example",
                                consecutive_years=6),
            fx.SALES_REP_HEADERS,
        ),
        201,
    )
    assert is_valid_uuid(exhibitor["id"])
    assert is_iso8601_timestamp(exhibitor["created_at"])
    assert exhibitor["created_at"].startswith("2026-08-15T00:00:00")
    assert exhibitor["updated_at"].startswith("2026-08-15T00:00:00")
    assert exhibitor["version"] == 1
    assert exhibitor["status"] == ExhibitorStatus.ACTIVE
    assert exhibitor["ledger_points"] == 0
    assert exhibitor["sponsorship_fulfillment_points"] == 0
    assert exhibitor["penalty_points"] == 0
    assert exhibitor["space_points_provisional"] == 0
    assert exhibitor["space_points_certified"] == 0
    assert exhibitor["provisional_priority_points"] == 0
    assert exhibitor["certified_priority_points"] == 0
    assert exhibitor["priority_tier"] == PriorityTier.BRONZE
    assert exhibitor["consecutive_years"] == 6


def test_an_undeclared_enum_and_an_out_of_range_percentage_are_both_structural(
    client: ApiClient,
):
    """
    A location class outside the declared four, and an aisle ratio above one hundred.

    "every enumerated field must hold a declared value; every field naming cents,
    square feet, a percentage or a quantity must be an integer within range
    (percentage fields from 0 through 100, money and area fields at zero or above,
    quantities of at least 1)"

    Design: Corner/entities/undeclared_enum_and_out_of_range_percentage_are_rejected
    """
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    show_id = env["show"]["id"]

    validate_error(
        client.create_booth(
            show_id,
            f.booth_payload("R001", 20, 20, location_class="ROUND",
                            premium_zone="NONE", max_height_ft=12),
            fx.FLOOR_MANAGER_HEADERS,
        ),
        ApiErrorId.VALIDATION,
        422,
    )
    booths, meta = validate_paginated(
        client.list_booths(fx.FLOOR_MANAGER_HEADERS, {"show_id": show_id})
    )
    assert booths == []
    assert meta["total_count"] == 0

    validate_error(
        client.create_show(
            f.show_payload(
                env["venue_contract"]["id"], name="Bad Ratio Expo",
                edition_year=2028, move_in_start="2028-03-01",
                event_start="2028-03-05", event_end="2028-03-07",
                move_out_end="2028-03-09", gross_sqft=90000, aisle_ratio_pct=140,
                base_rate_cents_per_sqft=3000, selection_desk_capacity=1,
            ),
            fx.DIRECTOR_HEADERS,
        ),
        ApiErrorId.VALIDATION,
        422,
    )
    agreement = validate_success(
        client.get_venue_contract(env["venue_contract"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert agreement["show_count"] == 1


def test_a_nested_create_resolves_its_parent_before_the_child_payload(
    client: ApiClient,
):
    """
    A booth filed under a show identifier that resolves to nothing.

    "The same left-to-right discipline governs every reverse-reachability list: a
    request for the shows under a venue contract, the booths of a show, the service
    orders of a contract or the scans of a registration first resolves the parent and
    reports the parent's own not-found error if it is missing."

    Design: Corner/entities/booth_creation_under_an_unknown_show_returns_show_not_found
    """
    fx.set_clock(client, CLOCK)

    validate_error(
        client.create_booth(UNKNOWN_SHOW_ID, A100, fx.FLOOR_MANAGER_HEADERS),
        ApiErrorId.SHOW_NOT_FOUND,
        404,
    )

    booths, meta = validate_paginated(client.list_booths(fx.FLOOR_MANAGER_HEADERS))
    assert booths == []
    assert meta["total_count"] == 0


def test_a_body_reference_to_an_unknown_exhibitor_holds_no_booth(client: ApiClient):
    """
    The cross-reference travels in the body and is resolved before any hold is taken.

    "Body references are checked here too: `venue_contract_id` on show creation,
    `show_id` and `exhibitor_id` on contract creation, `exhibitor_id` on appointment
    booking and on deal proposal, every element of `booth_ids`, and `registration_id`
    on a lead scan."

    Design: Corner/entities/space_contract_rejects_an_unknown_exhibitor_reference
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    booth_id = env["booth_by_number"]["A100"]["id"]
    pinned_version = fx.show_version(client, show_id)

    validate_error(
        client.create_space_contract(
            f.space_contract_payload(
                show_id, UNKNOWN_EXHIBITOR_ID, pinned_version, 400,
                premium_placement_requested=True, booth_ids=[booth_id],
            ),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.EXHIBITOR_NOT_FOUND,
        404,
    )

    booth = fx.read_booth(client, booth_id)
    assert booth["status"] == BoothStatus.AVAILABLE
    assert booth["space_contract_id"] is None

    show = fx.read_show(client, show_id)
    assert show["held_net_sqft"] == 0
    assert show["available_net_sqft"] == 600
    assert show["version"] == pinned_version


def test_a_recorded_scan_can_only_ever_be_re_read(client: ApiClient):
    """
    The one append-only row in the system, readable from both sides.

    "One entity is deliberately exempt: a lead scan is an append-only record with no
    update endpoint, so a lead scan carries only `id` and `created_at`. It has no
    `updated_at` and no `version` field at all."  "A successful scan increments the
    registration's `lead_scan_count` and its `version`."

    Design: Corner/entities/lead_scan_is_immutable_and_exposes_no_version_field
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    exhibitor = fx.exhibitor(client, "Nordic Furnishings",
                             contact_email="sales@nordic.example",
                             consecutive_years=6)
    contract = fx.signed_contract(
        client, show_id, exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], 389070,
        premium_placement_requested=True,
    )
    fx.transition(client, show_id, ShowStatus.SELLING)
    registration = fx.registration(
        client, show_id, fx.REGISTRANT_HEADERS, company_name="Delta Retail Group",
        job_title="VP Procurement", email="r1@delta.example",
    )
    fx.transition(client, show_id, ShowStatus.ON_SITE)
    fx.set_clock(client, "2027-03-05T10:00:00Z")

    scan = validate_success(
        client.create_lead_scan(
            contract["id"],
            f.lead_scan_payload(registration["id"], "2027-03-05T10:05:00Z"),
            fx.make_exhibitor_headers(exhibitor["id"]),
        ),
        201,
    )
    assert_lead_scan(scan)
    # The PRD pins that `scanned_at` is a valid ISO 8601 UTC instant and that it
    # is the instant the request named; it does not pin whether the server echoes
    # the client's rendering or restates it with three fractional digits, so the
    # instant is compared rather than the byte string.
    assert is_iso8601_timestamp(scan["scanned_at"])
    assert (
        datetime.fromisoformat(scan["scanned_at"].replace("Z", "+00:00"))
        == datetime.fromisoformat("2027-03-05T10:05:00+00:00")
    )

    from_the_contract, meta = validate_paginated(
        client.list_contract_lead_scans(contract["id"], fx.FLOOR_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert from_the_contract[0]["id"] == scan["id"]
    assert from_the_contract[0]["space_contract_id"] == contract["id"]

    from_the_badge, meta = validate_paginated(
        client.list_registration_lead_scans(registration["id"], fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1
    assert from_the_badge[0]["registration_id"] == registration["id"]
    assert_lead_scan(from_the_badge[0])

    reread = validate_success(
        client.get_registration(registration["id"], fx.DIRECTOR_HEADERS)
    )
    assert reread["lead_scan_count"] == 1
