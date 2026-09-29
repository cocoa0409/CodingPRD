"""
The stored surface of each entity: declared fields, defaults, and immutability.

These exercise what the server accepts, what it fills in, what it refuses to be
told, and what it hands back on a read — the layer every richer scenario stands
on.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM_HEADERS,
    UNKNOWN_UUID,
    ApiClient,
    ApiErrorId,
    assert_common_fields,
    assert_engagement_common_fields,
    assert_envelope,
    factories,
    fixtures,
    make_investor_headers,
)


class TestTheatreSurface:
    """The house record carries the three declared inputs and both optionals."""

    def test_a_registered_house_reads_back_every_declared_field(self, api: ApiClient):
        """Seat count, top price, buffer and rent all survive the round trip.

        "A `GeneralManager` registers a theatre with a `name` of between 1 and
        120 characters as it appears on the license agreement, a `seat_count` of
        at least 1 sellable seat per performance, and a `top_ticket_price_cents`
        of at least 1 cent."

        Design: Corner/entities/theatre_creation_returns_all_declared_fields
        """
        response = api.create_theatre(
            factories.theatre_payload(
                name="Palace Theatre",
                seat_count=1200,
                top_ticket_price_cents=19900,
                changeover_buffer_days=3,
                weekly_fixed_rent_cents=8_500_000,
            ),
            GM_HEADERS,
        )
        body = response.json()
        assert_envelope(body, "object")
        created = get_success_data(response, 201)

        assert created["name"] == "Palace Theatre"
        assert created["seat_count"] == 1200
        assert created["top_ticket_price_cents"] == 19900
        assert created["changeover_buffer_days"] == 3
        assert created["weekly_fixed_rent_cents"] == 8_500_000
        assert_common_fields(created, expected_version=1)

        fetched = get_success_data(api.get_theatre(created["id"], GM_HEADERS), 200)
        assert fetched == created


class TestProductionSurface:
    """The production file publishes stored deal terms and derived ledger fields."""

    def test_a_freshly_opened_file_reads_back_terms_and_a_zeroed_ledger(
        self, api: ApiClient
    ):
        """Every rolled-up figure is 0 and every axis is at its starting state.

        "Every rolled-up money and point field — `budget_total_cents`,
        `budget_committed_cents`, `capital_raised_cents`,
        `released_capital_cents`, `escrow_balance_cents`,
        `recouped_amount_cents`, `deferred_royalty_cents`,
        `distributed_total_cents`, `distributable_cash_cents`,
        `total_pool_points`, and `active_investor_count` — initialises to 0, as
        does `recoupment_pct`, and its `version` begins at 1."

        Design: Corner/entities/production_retrieval_returns_stored_and_computed_fields
        """
        theatre_id = fixtures.new_theatre(api)
        created = get_success_data(
            api.create_production(
                factories.spelled_out_production_payload(
                    theatre_id,
                    title="The Understudy",
                    offering_entity_type="LP",
                    capitalization_target_cents=120_000_000,
                    reserve_target_cents=20_000_000,
                ),
                GM_HEADERS,
            ),
            201,
        )

        fetched = get_success_data(api.get_production(created["id"], GM_HEADERS), 200)
        assert fetched["title"] == "The Understudy"
        assert fetched["offering_entity_type"] == "LP"
        assert fetched["theatre_id"] == theatre_id
        assert fetched["capitalization_target_cents"] == 120_000_000
        assert fetched["reserve_target_cents"] == 20_000_000
        assert fetched["pre_recoupment_pool_pct"] == 0.35
        assert fetched["post_recoupment_pool_pct"] == 0.4
        assert fetched["subsidiary_rights_investor_share_pct"] == 0.4
        assert fetched["closing_notice_min_days"] == 14

        for field in (
            "budget_total_cents",
            "budget_committed_cents",
            "capital_raised_cents",
            "released_capital_cents",
            "escrow_balance_cents",
            "recouped_amount_cents",
            "deferred_royalty_cents",
            "distributed_total_cents",
            "distributable_cash_cents",
            "total_pool_points",
            "active_investor_count",
        ):
            assert fetched[field] == 0, f"{field} must initialise to 0"
        assert fetched["recoupment_pct"] == 0.0
        assert_common_fields(fetched, expected_version=1)

    def test_the_listing_pages_and_filters_on_the_state_axis(self, api: ApiClient):
        """Three files in one house page two-then-one, and the axis filter empties it.

        "`total_count` reflects the number of rows matching the filters before
        pagination is applied, and `has_more` states whether any matching row
        remains beyond the returned page."

        Design: Corner/entities/productions_listing_paginates_and_filters
        """
        theatre_id = fixtures.new_theatre(api)
        for title in ("First Company", "Second Company", "Third Company"):
            fixtures.new_production(api, theatre_id, title=title)

        first_page, first_meta = validate_paginated(
            api.list_productions(
                GM_HEADERS, {"theatre_id": theatre_id, "limit": 2, "offset": 0}
            )
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_productions(
                GM_HEADERS, {"theatre_id": theatre_id, "limit": 2, "offset": 2}
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        offering_rows, offering_meta = validate_paginated(
            api.list_productions(
                GM_HEADERS, {"theatre_id": theatre_id, "offering_status": "OFFERING"}
            )
        )
        assert offering_rows == []
        assert offering_meta["total_count"] == 0

    def test_forged_system_fields_in_the_body_are_ignored(self, api: ApiClient):
        """The client cannot mint an id, a version, or a starting state.

        "A freshly opened production file starts in a known state on every axis.
        Its `offering_status` is `DRAFT`, its `operating_status` is
        `PRE_PRODUCTION`, its `recoupment_status` is `UNRECOUPED`, its
        `budget_status` is `DRAFT`, and its `royalty_basis` is `FIXED_GROSS`."

        Design: Corner/entities/production_system_fields_input_ignored
        """
        theatre_id = fixtures.new_theatre(api)
        created = get_success_data(
            api.create_production(
                factories.production_payload(
                    theatre_id,
                    id="forged-id",
                    version=99,
                    created_at="1999-01-01T00:00:00.000Z",
                    offering_status="CAPITALIZED",
                    operating_status="RUNNING",
                    recoupment_status="RECOUPED",
                    budget_status="APPROVED",
                    royalty_basis="POOL",
                    recouped_amount_cents=99_000_000,
                ),
                GM_HEADERS,
            ),
            201,
        )

        assert created["id"] != "forged-id"
        assert created["created_at"] != "1999-01-01T00:00:00.000Z"
        assert_common_fields(created, expected_version=1)
        assert created["offering_status"] == "DRAFT"
        assert created["operating_status"] == "PRE_PRODUCTION"
        assert created["recoupment_status"] == "UNRECOUPED"
        assert created["budget_status"] == "DRAFT"
        assert created["royalty_basis"] == "FIXED_GROSS"
        assert created["recouped_amount_cents"] == 0


class TestUnknownIdentifiers:
    """A path identifier that resolves to nothing decides the rejection."""

    def test_each_unknown_path_id_reports_its_own_not_found_code(self, api: ApiClient):
        """Production, wrap, allocation and capital account each answer for themselves.

        "**Path existence.** Every path identifier resolves, left to right, else
        the matching 404 above."

        Design: Corner/entities/unknown_entity_ids_return_not_found
        """
        probes = (
            (api.get_production(UNKNOWN_UUID, GM_HEADERS), ApiErrorId.PRODUCTION_NOT_FOUND),
            (
                api.get_weekly_wrap(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.WEEKLY_WRAP_NOT_FOUND,
            ),
            (
                api.get_royalty_allocation(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.ROYALTY_ALLOCATION_NOT_FOUND,
            ),
            (
                api.get_investor_account(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.INVESTOR_ACCOUNT_NOT_FOUND,
            ),
        )
        for response, expected_error_id in probes:
            validate_error(response, expected_error_id)
            assert_envelope(response.json(), "error")
            assert response.json()["data"]["message"].strip()


class TestRequestShapeRules:
    """Absent required fields, undeclared enum members and reversed ranges all fail."""

    def test_a_body_missing_a_required_field_is_malformed(self, api: ApiClient):
        """A budget line with no amount and a house with no seat count both fail.

        "**Request shape.** Required body fields present; enum fields hold a
        declared member; integer fields are integers inside their declared
        constraints; percentage fields carry no more than their declared
        decimals; date fields are well-formed ISO 8601 calendar dates;
        `end_date` is on or after `start_date` and `expiration_date` is on or
        after `effective_date`; `limit` is between 1 and 100 inclusive and
        `offset` is at least 0. Any violation is `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/missing_required_body_fields_rejected
        """
        world = fixtures.base_world(api)

        without_amount = factories.budget_line_payload(
            world.production_id, 40_000_000, world.production_version()
        )
        without_amount.pop("amount_cents")
        validate_error(
            api.create_budget_line(without_amount, GM_HEADERS),
            ApiErrorId.INVALID_REQUEST,
        )

        without_seats = factories.theatre_payload(name="Cort Annex")
        without_seats.pop("seat_count")
        validate_error(
            api.create_theatre(without_seats, GM_HEADERS), ApiErrorId.INVALID_REQUEST
        )

        _, meta = validate_paginated(
            api.list_budget_lines(GM_HEADERS, {"production_id": world.production_id})
        )
        assert meta["total_count"] == 0
        production = world.production()
        assert production["budget_total_cents"] == 0
        assert production["version"] == 1

    def test_an_undeclared_enum_member_and_a_reversed_range_are_malformed(
        self, api: ApiClient
    ):
        """A made-up engagement type fails, and so does an end before a start.

        "Where two dates form a range, the later bound may equal the earlier
        bound but may not precede it: `end_date` must be on or after
        `start_date`, and `expiration_date` must be on or after
        `effective_date`."

        Design: Corner/entities/undeclared_enum_and_reversed_date_range_rejected
        """
        world = fixtures.base_world(api)

        validate_error(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    world.production_id,
                    world.theatre_id,
                    "2026-09-01",
                    "2026-09-30",
                    engagement_type="TECHNICAL",
                ),
                GM_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
        )

        validate_error(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    world.production_id,
                    world.theatre_id,
                    "2026-09-30",
                    "2026-08-10",
                ),
                GM_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
        )

        _, meta = validate_paginated(
            api.list_theatre_engagements(
                GM_HEADERS, {"theatre_id": world.theatre_id}
            )
        )
        assert meta["total_count"] == 0


class TestOptionalDefaults:
    """Every optional input has a documented default the server fills in."""

    def test_omitted_optionals_take_their_documented_defaults(self, api: ApiClient):
        """Buffer 3, rent 0, the four deal terms, and eight performances a week.

        "Four deal terms are optional and carry defaults:
        `pre_recoupment_pool_pct` defaults to 0.3500,
        `post_recoupment_pool_pct` defaults to 0.4000,
        `subsidiary_rights_investor_share_pct` defaults to 0.4000, and
        `closing_notice_min_days` defaults to 14 whole days."

        Design: Corner/entities/optional_input_defaults_applied_when_omitted
        """
        theatre = get_success_data(
            api.create_theatre(
                factories.theatre_payload(
                    name="Bare House", seat_count=800, top_ticket_price_cents=9900
                ),
                GM_HEADERS,
            ),
            201,
        )
        assert theatre["changeover_buffer_days"] == 3
        assert theatre["weekly_fixed_rent_cents"] == 0

        production = get_success_data(
            api.create_production(
                factories.production_payload(theatre["id"]), GM_HEADERS
            ),
            201,
        )
        assert production["pre_recoupment_pool_pct"] == 0.35
        assert production["post_recoupment_pool_pct"] == 0.4
        assert production["subsidiary_rights_investor_share_pct"] == 0.4
        assert production["closing_notice_min_days"] == 14
        assert production["royalty_basis"] == "FIXED_GROSS"
        assert production["offering_status"] == "DRAFT"
        assert production["operating_status"] == "PRE_PRODUCTION"

        budget = get_success_data(
            api.create_operating_budget(
                factories.operating_budget_payload(production["id"]), GM_HEADERS
            ),
            201,
        )
        assert budget["performances_per_week"] == 8
        assert budget["status"] == "DRAFT"


class TestWeeklyWrapComputedFields:
    """The wrap's derived figures come from the pinned rows, not from the body."""

    def test_forged_derived_figures_in_the_body_are_recomputed(self, api: ApiClient):
        """Capacity, capacity percentage, variable cost and both grosses are re-derived.

        "`capacity_gross_cents` is the pinned house's `seat_count` multiplied by
        its `top_ticket_price_cents` multiplied by the wrap's `performances` —
        what the week would have grossed with every seat sold at the top price at
        every performance."

        Design: Corner/entities/weekly_wrap_computed_fields_input_ignored
        """
        world = fixtures.running_world(api)
        world.set_clock("2026-09-07")

        created = get_success_data(
            api.create_weekly_wrap(
                factories.standard_week_payload(
                    world.production_id,
                    capacity_gross_cents=1,
                    paid_capacity_pct=0.9999,
                    variable_cost_cents=1,
                    adjusted_gross_cents=1,
                    royalty_base_cents=999_999_999,
                ),
                GM_HEADERS,
            ),
            201,
        )

        assert created["capacity_gross_cents"] == 191_040_000
        assert created["paid_capacity_pct"] == 0.8542
        assert created["variable_cost_cents"] == 3_250_000
        assert created["adjusted_gross_cents"] == 61_750_000
        assert created["royalty_base_cents"] == 28_250_000
        assert created["status"] == "DRAFT"
        assert created["royalty_basis_applied"] is None


class TestTheatreEngagementImmutability:
    """The booking record is written once and carries no revision metadata."""

    def test_the_booking_record_carries_only_an_id_and_a_created_stamp(
        self, api: ApiClient
    ):
        """No version, no updated stamp, and the read matches the write exactly.

        "A `TheatreEngagement` is a booking record that is written once and never
        modified, so it carries only `id` and `created_at`."

        Design: Corner/entities/theatre_engagement_is_immutable
        """
        world = fixtures.base_world(api)
        created = get_success_data(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    world.production_id, world.theatre_id, "2026-09-01", "2026-09-30"
                ),
                GM_HEADERS,
            ),
            201,
        )

        assert_engagement_common_fields(created)
        assert created["production_id"] == world.production_id
        assert created["theatre_id"] == world.theatre_id
        assert created["engagement_type"] == "PERFORMANCE_RUN"
        assert created["start_date"] == "2026-09-01"
        assert created["end_date"] == "2026-09-30"

        fetched = get_success_data(
            api.get_theatre_engagement(created["id"], GM_HEADERS), 200
        )
        assert fetched == created


class TestBodyForeignKeyResolution:
    """A body foreign key that resolves to nothing decides the rejection early."""

    def test_unknown_body_foreign_keys_report_their_own_not_found_code(
        self, api: ApiClient
    ):
        """The referential check answers ahead of both the state and securities gates.

        "**Body referential integrity.** Every foreign key supplied in the body —
        `production_id`, `theatre_id`, `offering_document_id`, `investor_id` —
        resolves to an existing row, else the matching 404
        (`ERR_PRODUCTION_NOT_FOUND`, `ERR_THEATRE_NOT_FOUND`,
        `ERR_OFFERING_DOCUMENT_NOT_FOUND`, `ERR_INVESTOR_NOT_FOUND`)."

        Design: Corner/entities/body_foreign_keys_validated_and_unknown_ids_rejected
        """
        validate_error(
            api.create_production(
                factories.production_payload(UNKNOWN_UUID), GM_HEADERS
            ),
            ApiErrorId.THEATRE_NOT_FOUND,
        )

        # A wrap against an unknown production cannot reach the performing gate.
        validate_error(
            api.create_weekly_wrap(
                factories.standard_week_payload(UNKNOWN_UUID), GM_HEADERS
            ),
            ApiErrorId.PRODUCTION_NOT_FOUND,
        )

        # An unverified investor's own subscription cannot reach the
        # accreditation gate while the instrument it names does not exist.
        investor = get_success_data(
            api.create_investor(
                factories.investor_payload(
                    legal_name="Unverified Party",
                    contact_email="unverified@example.com",
                ),
                COUNSEL_HEADERS,
            ),
            201,
        )
        assert investor["accreditation_status"] == "UNVERIFIED"
        investor_id = investor["id"]
        validate_error(
            api.create_subscription(
                factories.subscription_payload(UNKNOWN_UUID, investor_id, units=1),
                make_investor_headers(investor_id),
            ),
            ApiErrorId.OFFERING_DOCUMENT_NOT_FOUND,
        )

        _, meta = validate_paginated(
            api.list_investor_accounts(COMPTROLLER_HEADERS, None)
        )
        assert meta["total_count"] == 0
