"""Referential integrity and enum validation.

Before anything is written the service resolves every identifier, checks every
declared enumeration, insists on every required field, and then checks that the
rows it resolved actually agree with one another. Each refusal here must name
the right failure and must leave nothing at all behind.
"""
from test_helpers import (
    PROGRAMMER,
    RIGHTS_MANAGER,
    ApiErrorId,
    api_client,
    book_asset,
    booking_payload,
    catalogue_title,
    clearance_payload,
    clearance_version,
    read_asset,
    read_clearance,
    register_distributor,
    register_venue,
    setup_programming_baseline,
    showtime_payload,
    validate_error,
    validate_paginated,
)

# A syntactically valid UUID that no row in the service will ever carry, so the
# only thing that can fail is existence.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestIdentifierResolution:
    """An unresolved identifier names the entity type that was missing."""

    def test_showtime_read_with_unknown_id_names_the_missing_entity(self):
        """Reading a screening that does not exist is a screening-not-found.

        PRD: "When an operation addresses one resource and its payload names others,
        the addressed resource is resolved first, then each foreign key in the payload;
        the specific not-found error names the entity type that was missing —
        `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`,
        `ERR_BOOKING_NOT_FOUND`, `ERR_BOOKING_OFFER_NOT_FOUND`,
        `ERR_CLEARANCE_NOT_FOUND`, `ERR_DCP_ASSET_NOT_FOUND`, `ERR_KDM_KEY_NOT_FOUND`,
        `ERR_SHOWTIME_NOT_FOUND`, `ERR_SPECIAL_EVENT_NOT_FOUND`,
        `ERR_TICKET_ORDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND` or
        `ERR_SETTLEMENT_NOT_FOUND`."

        Design: Corner/entities/showtime_read_with_unknown_id_returns_showtime_not_found
        """
        response = api_client.get_showtime(MISSING_UUID, PROGRAMMER)

        error = validate_error(
            response, ApiErrorId.ERR_SHOWTIME_NOT_FOUND.value, expected_status=404
        )
        assert error["error_id"] == "ERR_SHOWTIME_NOT_FOUND", (
            "a well-formed id that resolves to nothing is a not-found, not a bad request"
        )
        assert error["message"].strip(), "the refusal carries a non-empty message"

    def test_clearance_creation_against_an_unknown_engagement_names_the_booking(self):
        """A resolvable title with an unresolvable engagement is a booking-not-found.

        PRD: "When an operation addresses one resource and its payload names others,
        the addressed resource is resolved first, then each foreign key in the payload;
        the specific not-found error names the entity type that was missing —
        `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`,
        `ERR_BOOKING_NOT_FOUND`, `ERR_BOOKING_OFFER_NOT_FOUND`,
        `ERR_CLEARANCE_NOT_FOUND`, `ERR_DCP_ASSET_NOT_FOUND`, `ERR_KDM_KEY_NOT_FOUND`,
        `ERR_SHOWTIME_NOT_FOUND`, `ERR_SPECIAL_EVENT_NOT_FOUND`,
        `ERR_TICKET_ORDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND` or
        `ERR_SETTLEMENT_NOT_FOUND`."

        Design: Corner/entities/clearance_creation_against_an_unknown_booking_returns_booking_not_found
        """
        register_venue()
        distributor = register_distributor()
        title = catalogue_title(distributor["id"])

        payload = clearance_payload(title["id"], MISSING_UUID)
        response = api_client.create_clearance(payload, RIGHTS_MANAGER)

        error = validate_error(
            response, ApiErrorId.ERR_BOOKING_NOT_FOUND.value, expected_status=404
        )
        assert error["error_id"] == "ERR_BOOKING_NOT_FOUND", (
            "the title resolved, so the engagement is the reference that failed"
        )

        rows, meta = validate_paginated(
            api_client.list_clearances(
                RIGHTS_MANAGER, params={"title_id": title["id"]}
            )
        )
        assert rows == [], "a refused lodgement writes no licence"
        assert meta["total_count"] == 0


class TestSchemaGate:
    """A missing required field and an undeclared enum member both fail the schema."""

    def test_engagement_creation_without_min_run_days_is_a_schema_failure(self):
        """Omitting the promised playing days is refused and writes nothing.

        PRD: "Schema — on every write endpoint: the body parses as JSON, every required
        field is present and non-null, every field matches its declared type, every
        enumerated value is a declared member, every timestamp is ISO 8601 UTC, every
        amount in cents and every minute, day and seat count is a non-negative integer,
        `quantity` lies between 1 and 10 inclusive, and any interval's end is strictly
        after its start (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/booking_creation_without_min_run_days_returns_invalid_request
        """
        venue = register_venue()
        distributor = register_distributor()
        title = catalogue_title(distributor["id"])

        payload = booking_payload(title["id"], distributor["id"], venue["id"])
        payload.pop("min_run_days")

        response = api_client.create_booking(payload, PROGRAMMER)
        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        rows, meta = validate_paginated(
            api_client.list_bookings(PROGRAMMER, params={"venue_id": venue["id"]})
        )
        assert rows == [], "a refused opening creates no engagement"
        assert meta["total_count"] == 0, (
            "and therefore no opening negotiation round either"
        )

    def test_showtime_strand_outside_the_declared_enumeration_is_refused(self):
        """An undeclared strand fails the schema and draws nothing off the licence.

        PRD: "Schema — on every write endpoint: the body parses as JSON, every required
        field is present and non-null, every field matches its declared type, every
        enumerated value is a declared member, every timestamp is ISO 8601 UTC, every
        amount in cents and every minute, day and seat count is a non-negative integer,
        `quantity` lies between 1 and 10 inclusive, and any interval's end is strictly
        after its start (`ERR_INVALID_REQUEST`)."

        PRD: "It then draws down the licence: `screenings_used` rises by one,
        `screenings_remaining` falls by one, the licence's `version` increments, and the
        engagement's `scheduled_showtime_count` rises by one."

        Design: Corner/entities/showtime_strand_rejects_an_undeclared_enum_member
        """
        world = setup_programming_baseline()
        version_before = clearance_version(world["clearance"]["id"])

        payload = showtime_payload(
            world["venue"]["id"],
            world["title"]["id"],
            world["booking"]["id"],
            world["clearance"]["id"],
            world["asset"]["id"],
            "2026-08-14T12:00:00Z",
            version_before,
            strand="MIDNIGHT_CULT",
        )
        response = api_client.create_showtime(payload, PROGRAMMER)

        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        rows, meta = validate_paginated(
            api_client.list_showtimes(
                PROGRAMMER, params={"venue_id": world["venue"]["id"]}
            )
        )
        assert rows == [], "the refused placement created no screening"
        assert meta["total_count"] == 0

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 0, "nothing was drawn down"
        assert clearance["screenings_remaining"] == 6
        assert clearance["version"] == version_before, (
            "the licence was never mutated, so its version did not move"
        )


class TestReferenceAgreement:
    """Rows that resolve individually must still agree with one another."""

    def test_showtime_on_a_package_from_another_auditorium_is_a_disagreement(self):
        """A screening at one house cannot stand on a package booked into another.

        PRD: "Resolving individually is not enough: the referenced rows must also agree
        with one another, and a disagreement is reported as `ERR_REFERENCE_MISMATCH`. A
        clearance, its engagement and any screening standing on it must all name the
        same title; a screening's package must be for the same title as the screening; a
        screening, its engagement and its package must all name the same auditorium; a
        key must be bound to the same auditorium as the screening it is expected to
        cover; a settlement must name the engagement whose screenings it is settling;
        and when a new engagement supersedes an earlier one, the superseded engagement
        must itself be withdrawn."

        Design: Corner/entities/showtime_referencing_a_dcp_asset_from_another_venue_is_refused
        """
        world = setup_programming_baseline()
        annex = register_venue(
            name="Annex Screen",
            seat_capacity=40,
            house_hold_seats=0,
            trailer_reel_minutes=10,
            turnaround_minutes=20,
            min_useful_gap_minutes=30,
            dcp_ingest_lane_count=1,
            open_local_time="12:00",
            last_start_local_time="21:00",
            utc_offset_minutes=0,
            max_first_run_share=0.50,
            weekly_repertory_target=2,
            supported_formats=["DCP_2K"],
            base_house_nut_weekly_cents=100000,
        )
        annex_asset = book_asset(
            world["title"]["id"],
            world["distributor"]["id"],
            annex["id"],
            carrier_ref="WB-77199",
        )

        # Every id below resolves; the auditoriums simply disagree.
        payload = showtime_payload(
            world["venue"]["id"],
            world["title"]["id"],
            world["booking"]["id"],
            world["clearance"]["id"],
            annex_asset["id"],
            "2026-08-14T12:00:00Z",
            clearance_version(world["clearance"]["id"]),
        )
        response = api_client.create_showtime(payload, PROGRAMMER)

        validate_error(
            response, ApiErrorId.ERR_REFERENCE_MISMATCH.value, expected_status=422
        )

        assert read_asset(annex_asset["id"])["venue_id"] == annex["id"], (
            "the package stays bound to the auditorium it was booked into"
        )
        for venue_id in (world["venue"]["id"], annex["id"]):
            rows, meta = validate_paginated(
                api_client.list_showtimes(PROGRAMMER, params={"venue_id": venue_id})
            )
            assert rows == [], "no screening was created at either auditorium"
            assert meta["total_count"] == 0

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_remaining"] == 6, (
            "the refused placement drew nothing off the allowance"
        )
        assert clearance["screenings_used"] == 0
