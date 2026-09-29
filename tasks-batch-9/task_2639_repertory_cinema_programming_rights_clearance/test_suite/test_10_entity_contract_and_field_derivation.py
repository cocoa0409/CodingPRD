"""Entity contract and field derivation.

Every resource the service mints must answer inside the standard envelope,
carry the four common properties, echo what the caller declared, fill in the
documented defaults for what the caller omitted, and derive its computed
fields from the parameters of the auditorium and the title rather than from
anything the caller supplied.
"""
from test_helpers import (
    ANONYMOUS,
    BOX_OFFICE,
    EXECUTIVE_DIRECTOR,
    PROGRAMMER,
    api_client,
    assert_fresh_resource,
    assert_member,
    assert_screen_block,
    assert_seat_conservation,
    assert_showtime,
    assert_title,
    assert_venue,
    catalogue_title,
    clearance_version,
    is_valid_uuid,
    member_payload,
    register_distributor,
    setup_programming_baseline,
    showtime_payload,
    validate_paginated,
    validate_success,
    venue_payload,
)


class TestAuditoriumRecordContract:
    """Registering the house is the first act, and it pins the whole contract."""

    def test_venue_registration_returns_the_envelope_and_every_declared_field(self):
        """A full registration answers 201 with the complete stored auditorium.

        PRD: "Every resource in the system carries four common properties. `id` is a
        server-minted UUID with no type prefix — clients never supply it. `created_at`
        is the ISO 8601 UTC instant of creation with three fractional digits.
        `updated_at` is the ISO 8601 UTC instant of the most recent mutation; at
        creation it equals `created_at`. `version` is an integer that starts at 1 and
        increments by exactly 1 on every mutation of that row, including mutations
        produced by a cascade rather than by a direct call to that resource."

        Design: Corner/entities/venue_creation_returns_envelope_and_every_declared_field
        """
        payload = venue_payload(name="Reel Repertory")

        response = api_client.create_venue(payload, EXECUTIVE_DIRECTOR)
        data = validate_success(response, expected_status=201)

        # The four common properties, at creation.
        assert_fresh_resource(data)
        assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
        assert "_" not in data["id"], "the id carries no type prefix"
        assert data["version"] == 1, "version starts at 1"
        assert data["updated_at"] == data["created_at"], (
            "at creation updated_at equals created_at"
        )
        assert data["created_at"].endswith("Z"), "created_at is a UTC instant"
        assert len(data["created_at"].split(".")[-1]) == 4, (
            f"created_at carries three fractional digits, got {data['created_at']!r}"
        )

        # Every declared field is echoed exactly as posted.
        assert_venue(data)
        assert data["name"] == "Reel Repertory"
        assert data["seat_capacity"] == 12
        assert data["house_hold_seats"] == 4
        assert data["trailer_reel_minutes"] == 12
        assert data["turnaround_minutes"] == 25
        assert data["min_useful_gap_minutes"] == 45
        assert data["dcp_ingest_lane_count"] == 2
        assert data["open_local_time"] == "11:00"
        assert data["last_start_local_time"] == "22:00"
        assert data["utc_offset_minutes"] == 0
        assert data["max_first_run_share"] == 0.60
        assert data["weekly_repertory_target"] == 3
        assert data["base_house_nut_weekly_cents"] == 200000
        assert data["supported_formats"] == ["DCP_2K", "DCP_4K"]

    def test_venue_optional_parameters_take_their_documented_defaults(self):
        """Omitting the six optional parameters fills each with its stated default.

        PRD: "Six further auditorium parameters are optional at registration and take
        documented defaults when omitted. `house_hold_seats` defaults to 0 and names
        the seats permanently withheld from sale for press and guests; it must be zero
        or more and strictly less than `seat_capacity`. `min_useful_gap_minutes`
        defaults to 45 and is the gap below which a hole left in a day's schedule is
        treated as fragmentation rather than as breathing room. `utc_offset_minutes`
        defaults to 0. `max_first_run_share` defaults to 0.60 and must be greater than
        0 and no more than 1. `weekly_repertory_target` defaults to 6 and must be zero
        or more. And `base_house_nut_weekly_cents` defaults to 480000 — four thousand
        eight hundred dollars a week — and is the board-approved ceiling on the weekly
        house nut: no engagement may ever be confirmed at a house nut above it."

        Design: Corner/entities/venue_defaults_applied_when_optional_fields_are_omitted
        """
        bare_payload = {
            "name": "Bare Minimum Cinema",
            "seat_capacity": 60,
            "trailer_reel_minutes": 8,
            "turnaround_minutes": 15,
            "dcp_ingest_lane_count": 1,
            "open_local_time": "13:00",
            "last_start_local_time": "23:00",
            "supported_formats": ["DCP_2K"],
        }

        response = api_client.create_venue(bare_payload, EXECUTIVE_DIRECTOR)
        data = validate_success(response, expected_status=201)

        assert data["house_hold_seats"] == 0
        assert data["min_useful_gap_minutes"] == 45
        assert data["utc_offset_minutes"] == 0
        assert data["max_first_run_share"] == 0.60
        assert data["weekly_repertory_target"] == 6
        assert data["base_house_nut_weekly_cents"] == 480000

        for field in (
            "house_hold_seats",
            "min_useful_gap_minutes",
            "utc_offset_minutes",
            "max_first_run_share",
            "weekly_repertory_target",
            "base_house_nut_weekly_cents",
        ):
            assert data[field] is not None, (
                f"{field} takes a documented default rather than staying null"
            )

        assert_venue(data)
        assert_fresh_resource(data)


class TestCatalogueAndMembershipRecords:
    """The public catalogue and the membership card, read straight back."""

    def test_title_read_serves_the_stored_row_to_an_anonymous_browser(self):
        """A walk-up caller with no role header may read a catalogued title.

        PRD: "Titles are catalogued by a `Programmer` or an `ExecutiveDirector` with
        the `title_name` as it will be printed in the calendar, the original theatrical
        `release_year`, a `runtime_minutes` of at least 1 excluding trailers, an
        `is_first_run` flag distinguishing first-run art films from repertory and
        archival titles, a `native_format` drawn from the same five-format enumeration,
        and `rights_holder_distributor_id` naming the party that controls theatrical
        rights."

        PRD: "A request whose `X-User-Role` header is absent is treated as an anonymous
        walk-up caller and is admitted only on endpoints that explicitly list the
        anonymous role"

        Design: Corner/entities/title_retrieval_returns_the_stored_row_to_an_anonymous_caller
        """
        distributor = register_distributor()
        title = catalogue_title(distributor["id"])

        response = api_client.get_title(title["id"], ANONYMOUS)
        data = validate_success(response)

        assert_title(data)
        assert data["id"] == title["id"]
        assert data["title_name"] == "La Jetee Redux"
        assert data["release_year"] == 1962
        assert data["runtime_minutes"] == 104
        assert data["is_first_run"] is False
        assert data["native_format"] == "DCP_2K"
        assert data["rights_holder_distributor_id"] == distributor["id"]
        assert data["version"] == 1, "a pure read is not a mutation"

    def test_member_enrolment_mints_every_derived_field_at_prospect(self):
        """Opening a membership record fills in the whole derived standing block.

        PRD: "A new record starts in `PENDING` with an empty `donations` list, a null
        `expires_at`, `rolling_donation_cents` and `fiscal_ytd_donation_cents` at 0,
        `rolling_tier`, `fiscal_tier` and `effective_tier` all at `PROSPECT`,
        `discount_pct` at 0.00, `advance_access_hours` at 0, `comp_tickets_granted` and
        `comp_tickets_remaining` at 0, and `credit_balance_cents` at 0."

        Design: Corner/entities/member_system_fields_are_minted_by_the_server
        """
        response = api_client.create_member(member_payload(), BOX_OFFICE)
        data = validate_success(response, expected_status=201)

        assert is_valid_uuid(data["id"]), "the membership id is a server-minted UUID"
        assert data["version"] == 1
        assert data["status"] == "PENDING"
        assert data["donations"] == []
        assert data["expires_at"] is None
        assert data["rolling_donation_cents"] == 0
        assert data["fiscal_ytd_donation_cents"] == 0
        assert data["rolling_tier"] == "PROSPECT"
        assert data["fiscal_tier"] == "PROSPECT"
        assert data["effective_tier"] == "PROSPECT"
        assert data["discount_pct"] == 0.00
        assert data["advance_access_hours"] == 0
        assert data["comp_tickets_granted"] == 0
        assert data["comp_tickets_remaining"] == 0
        assert data["credit_balance_cents"] == 0

        assert_member(data)
        assert_fresh_resource(data)

    def test_titles_listing_reports_total_count_and_has_more_across_pages(self):
        """Two pages of a three-title catalogue carry the pre-pagination count.

        PRD: "For every list response the `meta` object carries `limit` (the effective
        page size), `offset` (the effective starting position), `total_count` (the
        number of rows matching the filters before pagination is applied) and
        `has_more` (true when rows remain beyond this page)."

        Design: Corner/entities/titles_listing_pages_with_total_count_and_has_more
        """
        distributor = register_distributor()
        first = catalogue_title(distributor["id"], title_name="La Jetee Redux")
        second = catalogue_title(distributor["id"], title_name="Sans Soleil Again")
        third = catalogue_title(distributor["id"], title_name="Nouvelle Vague Now")

        page_one, meta_one = validate_paginated(
            api_client.list_titles(PROGRAMMER, params={"limit": 2, "offset": 0})
        )
        assert len(page_one) == 2, "the first page carries the effective page size"
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["total_count"] == 3, "total_count counts rows before paging"
        assert meta_one["has_more"] is True, "a third row remains beyond this page"

        page_two, meta_two = validate_paginated(
            api_client.list_titles(PROGRAMMER, params={"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1, "the tail page carries the remainder"
        assert meta_two["limit"] == 2
        assert meta_two["offset"] == 2
        assert meta_two["total_count"] == 3, "total_count ignores the offset"
        assert meta_two["has_more"] is False, "nothing remains beyond the tail page"

        seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert len(seen) == len(set(seen)), "no row is served on both pages"
        assert set(seen) == {first["id"], second["id"], third["id"]}, (
            "the two pages together cover the whole catalogue"
        )


class TestScreeningGeometryDerivation:
    """The screen block is arithmetic on the booth parameters, never an input."""

    def test_showtime_block_geometry_is_derived_from_reel_runtime_and_turnaround(self):
        """A hand-placed screening computes end_at, blocked_until and its zeroed counters.

        PRD: "The screening's on-screen content runs for the auditorium's
        `trailer_reel_minutes` plus the title's `runtime_minutes` plus the screening's
        own `extra_minutes`, which is 0 at creation; `end_at` is `start_at` advanced by
        that total number of minutes, and `blocked_until` is `end_at` advanced by the
        auditorium's `turnaround_minutes`."

        PRD: "A successful placement creates the screening with status `SCHEDULED`,
        `sale_status` `DRAFT` and `playback_status` `UNVERIFIED`, with `surcharge_cents`
        at 0, `seats_sold` at 0, `gross_cents` at 0, `admissions_count` at 0,
        `cancel_reason` null and `slot_score` null."

        Design: Corner/entities/showtime_computed_fields_are_derived_from_the_geometry_formula
        """
        world = setup_programming_baseline()
        payload = showtime_payload(
            world["venue"]["id"],
            world["title"]["id"],
            world["booking"]["id"],
            world["clearance"]["id"],
            world["asset"]["id"],
            "2026-08-14T12:00:00Z",
            clearance_version(world["clearance"]["id"]),
        )

        response = api_client.create_showtime(payload, PROGRAMMER)
        data = validate_success(response, expected_status=201)

        # 12 minutes of trailers + 104 minutes of feature + 0 extra = 116 minutes on
        # screen, then 25 minutes of turnaround before the screen is free again.
        assert data["start_at"] == "2026-08-14T12:00:00.000Z"
        assert_screen_block(data, "2026-08-14T13:56:00.000Z", "2026-08-14T14:21:00.000Z")
        assert data["extra_minutes"] == 0
        assert data["surcharge_cents"] == 0

        assert data["status"] == "SCHEDULED"
        assert data["sale_status"] == "DRAFT"
        assert data["playback_status"] == "UNVERIFIED"
        assert data["cancel_reason"] is None
        assert data["slot_score"] is None, (
            "slot_score stays null on a hand-placed screening"
        )
        assert data["seats_sold"] == 0
        assert data["gross_cents"] == 0
        assert data["admissions_count"] == 0
        assert data["seats_available"] == 8, (
            "12 seats less the 4 house holds and nothing sold"
        )

        assert_showtime(data)
        assert_seat_conservation(data, world["venue"])
