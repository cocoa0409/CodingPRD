"""Season records: registration echoes, declared defaults, computed money
fields, the append-only reserve ledger and referential integrity."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    create_performance_space_payload,
    create_rental_client_payload,
    create_rental_engagement_payload,
    create_subscription_package_payload,
    create_union_department_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    register_artist,
    register_hall,
    register_rental_client,
    register_union_department,
    reset_clock_to_season_default,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


class TestHallRegistration:

    def test_registering_a_hall_persists_every_capability_limit(self):
        """A hall registration echoes all eight declared capability and rate
        fields untouched, and an explicitly supplied status wins over the
        default.

        PRD: "A hall's `status` may be supplied at registration and defaults to
        `ACTIVE`; the only other value is `OFFLINE`, and an `OFFLINE` hall
        refuses new bookings."

        Design: Corner/entities/performance_space_creation_persists_every_capability_limit
        """
        reset_clock_to_season_default()

        payload = create_performance_space_payload(
            name="Studio Theatre",
            seat_capacity=240,
            base_facility_fee_cents=180_000,
            load_in_day_fee_cents=60_000,
            changeover_buffer_minutes=90,
            rigging_capacity_kg=1_800,
            house_power_amps=200,
            dmx_universes=2,
            status="OFFLINE",
        )
        space = validate_success(
            api_client.create_performance_space(payload, ADMIN), 201)

        assert space["name"] == "Studio Theatre"
        assert space["seat_capacity"] == 240
        assert space["base_facility_fee_cents"] == 180_000
        assert space["load_in_day_fee_cents"] == 60_000
        assert space["changeover_buffer_minutes"] == 90
        assert space["rigging_capacity_kg"] == 1_800
        assert space["house_power_amps"] == 200
        assert space["dmx_universes"] == 2
        assert space["status"] == "OFFLINE"

        assert is_valid_uuid(space["id"])
        assert len(space["id"]) == 36
        assert space["version"] == 1
        assert space["created_at"] == space["updated_at"]
        assert is_iso8601_timestamp(space["created_at"])

    def test_omitted_optional_fields_take_their_declared_defaults(self):
        """A union rate card registered without its four optional rate fields,
        a hall registered without a status, a client registered without a
        balance and an item registered without its reserve flag all fall back
        on the values the specification declares.

        PRD: "`overtime_multiplier` defaults to 1.5, `doubletime_multiplier`
        defaults to 2.0, `call_minimum_hours` defaults to 4 hours of guaranteed
        billable time per crew member per call, and `meal_penalty_cents`
        defaults to 3,500 cents"

        Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
        """
        reset_clock_to_season_default()

        department = validate_success(api_client.create_union_department(
            create_union_department_payload(department="STAGEHANDS",
                                            roster_size=20,
                                            straight_hourly_rate_cents=5_000),
            ADMIN), 201)
        assert department["overtime_multiplier"] == 1.5
        assert department["doubletime_multiplier"] == 2.0
        assert department["call_minimum_hours"] == 4
        assert department["meal_penalty_cents"] == 3_500

        space = register_hall()
        assert space["status"] == "ACTIVE"

        client = register_rental_client()
        assert client["outstanding_balance_cents"] == 0

        item = validate_success(api_client.create_equipment_item(
            {
                "category": "POWER_DISTRO",
                "model_name": "400A Distro",
                "on_hand_qty": 4,
                "daily_rate_cents": 25_000,
                "replacement_value_cents": 900_000,
            }, ADMIN), 201)
        assert item["reserve_funded"] is False
        assert item["reserved_qty"] == 0

        for row in (department, space, client, item):
            assert row["version"] == 1


class TestEngagementRecord:

    def test_rental_engagement_read_exposes_three_independent_dimensions(self):
        """Reading a freshly booked rental engagement shows all three status
        dimensions at their initial values at once, the rental discriminator
        with a null artist, and the two computed money fields already written.

        PRD: "A new engagement is born in `DRAFT` on the booking dimension,
        `UNASSESSED` on the clearance dimension and `TICKETING_UNSET` on the
        ticketing dimension."

        Design: Corner/entities/rental_engagement_read_exposes_three_independent_state_dimensions
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")
        created = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(space["id"], client["id"],
                                             title="Meridian Spring Program",
                                             performance_day_count=1,
                                             load_in_day_count=0),
            RENTAL_MANAGER), 201)

        engagement = validate_success(
            api_client.get_engagement(created["id"], FINANCE))

        assert engagement["lifecycle_status"] == "DRAFT"
        assert engagement["financial_clearance"] == "UNASSESSED"
        assert engagement["ticketing_status"] == "TICKETING_UNSET"

        assert engagement["engagement_type"] == "RENTAL"
        assert engagement["rental_client_id"] == client["id"]
        assert engagement.get("artist_id") is None

        # 500,000 per performance day, no load-in days, no discount and no
        # capacity surcharge at 1,200 seats; the deposit is 25% of that for a
        # grade A client, rounded up to the next multiple of 100 cents.
        assert engagement["facility_fee_cents"] == 500_000
        assert engagement["deposit_required_cents"] == 125_000
        assert engagement["deposit_paid_cents"] == 0

        assert engagement["negotiated_fee_cents"] == 0
        assert engagement["artist_share_pct"] == 0
        assert engagement["labor_estimate_total_cents"] == 0
        assert engagement["additional_equipment_cost_cents"] == 0
        assert engagement["risk_score"] == 0
        assert engagement["risk_tier"] == "LOW"
        assert engagement["negotiation_round_count"] == 0
        assert engagement["cancellation_fee_cents"] == 0
        assert engagement.get("fee_accepted_by_user_id") is None

        assert engagement["version"] == 1

    def test_computed_money_fields_are_written_per_engagement_type(self):
        """The same hall rate card and the same day counts produce a billed
        facility fee and deposit on a rental booking and zero on both counts
        for a presented booking.

        PRD: "A presented engagement has `facility_fee_cents` of 0 — the center
        does not rent the hall to itself"

        Design: Corner/entities/computed_money_fields_are_written_by_the_server_per_engagement_type
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")
        artist = register_artist(legal_name="Cadence Quartet")

        rental = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(space["id"], client["id"],
                                             title="Meridian Rental",
                                             performance_day_count=1,
                                             load_in_day_count=1),
            RENTAL_MANAGER), 201)
        presented = validate_success(api_client.create_engagement(
            {
                "engagement_type": "PRESENTED",
                "space_id": space["id"],
                "artist_id": artist["id"],
                "title": "Cadence Quartet Recital",
                "load_in_start_utc": "2026-10-10T08:00:00Z",
                "performance_start_utc": "2026-10-11T19:00:00Z",
                "performance_end_utc": "2026-10-11T22:00:00Z",
                "load_out_end_utc": "2026-10-12T02:00:00Z",
                "performance_day_count": 1,
                "load_in_day_count": 1,
            }, DIRECTOR), 201)

        # 500,000 for the performance day plus 200,000 for the load-in day.
        assert rental["facility_fee_cents"] == 700_000
        assert rental["deposit_required_cents"] == 175_000

        assert presented["facility_fee_cents"] == 0
        assert presented["deposit_required_cents"] == 0

        for row in (rental, presented):
            assert row["labor_estimate_total_cents"] == 0
            assert row["additional_equipment_cost_cents"] == 0
            assert row["deposit_paid_cents"] == 0
            assert row["risk_score"] == 0
            assert row["realized_gross_cents"] == 0
            assert row["realized_margin_cents"] == 0

    def test_system_fields_are_minted_at_creation_and_version_advances(self):
        """Creation mints the identity triple and leaves the acceptance stamp
        null; recording a deposit advances the version while the creation
        instant stays frozen.

        PRD: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on each mutation of that resource."

        Design: Corner/entities/system_fields_are_minted_at_creation_and_version_advances_per_write
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")
        created = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(space["id"], client["id"],
                                             title="System Field Probe",
                                             performance_day_count=1,
                                             load_in_day_count=1),
            RENTAL_MANAGER), 201)

        assert is_valid_uuid(created["id"])
        assert created["version"] == 1
        assert created["created_at"] == created["updated_at"]
        assert created.get("fee_accepted_by_user_id") is None
        created_at_at_birth = created["created_at"]

        after_deposit = validate_success(api_client.record_deposit(
            created["id"], {"amount_cents": 175_000}, RENTAL_MANAGER))

        assert after_deposit["version"] == 2
        assert after_deposit["deposit_paid_cents"] == 175_000
        assert after_deposit["created_at"] == created_at_at_birth
        assert is_iso8601_timestamp(after_deposit["updated_at"])


class TestEngagementListing:

    def test_engagement_listing_paginates_and_filters(self):
        """The engagement listing reports the filtered count rather than the
        page length, derives has_more from the window, defaults the page size,
        and answers a filter that matches nothing with an empty page.

        PRD: "`total_count` reports the number of items matching the filter
        before the window is applied, and `has_more` is true when items remain
        beyond the current window."

        Design: Corner/entities/engagement_listing_paginates_and_filters_with_total_count_and_has_more
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")

        windows = [
            ("Booking One", "2026-10-01T08:00:00Z", "2026-10-02T19:00:00Z",
             "2026-10-02T22:00:00Z", "2026-10-03T02:00:00Z"),
            ("Booking Two", "2026-10-10T08:00:00Z", "2026-10-11T19:00:00Z",
             "2026-10-11T22:00:00Z", "2026-10-12T02:00:00Z"),
            ("Booking Three", "2026-10-20T08:00:00Z", "2026-10-21T19:00:00Z",
             "2026-10-21T22:00:00Z", "2026-10-22T02:00:00Z"),
        ]
        booked_ids = []
        for title, load_in, start, end, load_out in windows:
            row = validate_success(api_client.create_engagement(
                create_rental_engagement_payload(
                    space["id"], client["id"], title=title,
                    load_in_start_utc=load_in, performance_start_utc=start,
                    performance_end_utc=end, load_out_end_utc=load_out,
                    performance_day_count=1, load_in_day_count=0),
                RENTAL_MANAGER), 201)
            booked_ids.append(row["id"])

        page_one, meta_one = validate_paginated(api_client.list_engagements(
            RENTAL_MANAGER,
            {"rental_client_id": client["id"], "limit": 2, "offset": 0}))
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(api_client.list_engagements(
            RENTAL_MANAGER,
            {"rental_client_id": client["id"], "limit": 2, "offset": 2}))
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False

        seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert len(seen) == len(set(seen))
        assert set(seen) == set(booked_ids)

        unpaged, meta_unpaged = validate_paginated(api_client.list_engagements(
            FINANCE, {"rental_client_id": client["id"]}))
        assert meta_unpaged["limit"] == 10
        assert len(unpaged) == 3
        assert meta_unpaged["has_more"] is False

        empty, meta_empty = validate_paginated(api_client.list_engagements(
            FINANCE, {"rental_client_id": client["id"],
                      "lifecycle_status": "CANCELLED"}))
        assert empty == []
        assert meta_empty["total_count"] == 0


class TestRequestValidation:

    def test_reading_an_absent_engagement_id_is_a_not_found(self):
        """A well-formed identifier that resolves to nothing is reported as the
        engagement-specific 404 rather than as an invalid request.

        PRD: "A request naming a labor call under an engagement that does not
        exist yields `ERR_ENGAGEMENT_NOT_FOUND` before the labor call is ever
        looked up."

        Design: Corner/entities/reading_absent_engagement_id_returns_engagement_not_found
        """
        reset_clock_to_season_default()

        body = validate_error(
            api_client.get_engagement(NON_EXISTENT_UUID, FINANCE),
            "ERR_ENGAGEMENT_NOT_FOUND", 404)
        assert isinstance(body["message"], str) and body["message"].strip()

    def test_creating_an_engagement_with_missing_or_disordered_fields(self):
        """A create missing both day counts and a create whose performance
        window runs backwards are both invalid requests, and neither leaves a
        partial booking behind.

        PRD: "the engagement's four instants in non-decreasing order:
        `load_in_start_utc` at or before `performance_start_utc`, which is at
        or before `performance_end_utc`, which is at or before
        `load_out_end_utc`."

        Design: Corner/entities/creating_engagement_with_missing_required_fields_is_invalid_request
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")

        missing = create_rental_engagement_payload(space["id"], client["id"],
                                                   title="No Day Counts")
        missing.pop("performance_day_count")
        missing.pop("load_in_day_count")
        validate_error(api_client.create_engagement(missing, RENTAL_MANAGER),
                       "ERR_INVALID_REQUEST", 400)

        inverted = create_rental_engagement_payload(
            space["id"], client["id"], title="Inverted Window",
            performance_start_utc="2026-10-02T22:00:00Z",
            performance_end_utc="2026-10-02T19:00:00Z",
            performance_day_count=1, load_in_day_count=0)
        validate_error(api_client.create_engagement(inverted, RENTAL_MANAGER),
                       "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(api_client.list_engagements(
            RENTAL_MANAGER, {"space_id": space["id"]}))
        assert meta["total_count"] == 0

    def test_enum_and_numeric_bound_violations_are_invalid_requests(self):
        """A credit grade outside the closed enum and a performance day count
        one below its declared minimum are both rejected before any money is
        computed.

        PRD: "Required fields present, enum values in range, numbers inside
        their declared bounds"

        Design: Corner/entities/rental_client_with_unknown_credit_rating_enum_is_invalid_request
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")

        validate_error(api_client.create_rental_client(
            create_rental_client_payload(org_name="Unrated Consortium",
                                         contact_email="ops@unrated.example",
                                         credit_rating="AA"),
            RENTAL_MANAGER), "ERR_INVALID_REQUEST", 400)

        validate_error(api_client.create_engagement(
            create_rental_engagement_payload(space["id"], client["id"],
                                             title="Zero Day Booking",
                                             performance_day_count=0,
                                             load_in_day_count=0),
            RENTAL_MANAGER), "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(api_client.list_engagements(
            RENTAL_MANAGER, {"space_id": space["id"]}))
        assert meta["total_count"] == 0


class TestReserveLedgerImmutability:

    def test_reserve_ledger_entries_are_append_only_running_totals(self):
        """Ledger rows carry no mutation-tracking fields, and appending a
        second movement leaves the first row's running balance frozen at its
        historical value.

        PRD: "A `ReserveLedgerEntry` is append-only and immutable once written,
        so it carries only `id` and `created_at`; it has **no** `updated_at`
        field and **no** `version` field at all."

        Design: Corner/entities/reserve_ledger_entry_is_append_only_with_no_version_field
        """
        reset_clock_to_season_default()

        opening = validate_success(api_client.create_reserve_ledger_entry(
            {"entry_type": "OPENING_BALANCE", "amount_cents": 8_000_000,
             "memo": "FY27 capital reserve opening balance"}, ADMIN), 201)
        adjustment = validate_success(api_client.create_reserve_ledger_entry(
            {"entry_type": "MANUAL_ADJUSTMENT", "amount_cents": -1_000_000,
             "memo": "Transfer to orchestra shell purchase"}, ADMIN), 201)

        for row in (opening, adjustment):
            assert "version" not in row
            assert "updated_at" not in row
            assert is_valid_uuid(row["id"])
            assert is_iso8601_timestamp(row["created_at"])
            assert row.get("engagement_id") is None

        assert opening["balance_after_cents"] == 8_000_000
        assert adjustment["balance_after_cents"] == 7_000_000

        entries, meta = validate_paginated(
            api_client.list_reserve_ledger_entries(FINANCE,
                                                   {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 2
        replayed = {row["id"]: row for row in entries}
        assert replayed[opening["id"]]["balance_after_cents"] == 8_000_000


class TestReferentialIntegrity:

    def test_labor_call_resolves_the_path_parent_before_the_body_reference(self):
        """A labor call under a live engagement naming an unknown department is
        a department 404; the same call under an unknown engagement is an
        engagement 404 even though its department reference is valid.

        PRD: "Body-referenced identifiers are resolved after path identifiers:
        `space_id` yields `ERR_SPACE_NOT_FOUND`"

        Design: Corner/entities/labor_call_under_unknown_department_returns_department_not_found
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")
        department = register_union_department(department="STAGEHANDS",
                                              roster_size=20,
                                              straight_hourly_rate_cents=5_000)
        engagement = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(space["id"], client["id"],
                                             title="Parent Probe",
                                             performance_day_count=1,
                                             load_in_day_count=1),
            RENTAL_MANAGER), 201)

        call_window = {"crew_size": 4,
                       "call_start_utc": "2026-10-01T08:00:00Z",
                       "call_end_utc": "2026-10-01T12:00:00Z"}

        validate_error(api_client.create_labor_call(
            engagement["id"],
            dict(union_department_id=NON_EXISTENT_UUID, **call_window),
            TECH_DIRECTOR), "ERR_DEPARTMENT_NOT_FOUND", 404)

        validate_error(api_client.create_labor_call(
            NON_EXISTENT_UUID,
            dict(union_department_id=department["id"], **call_window),
            TECH_DIRECTOR), "ERR_ENGAGEMENT_NOT_FOUND", 404)

        _, meta = validate_paginated(api_client.list_engagement_labor_calls(
            engagement["id"], TECH_DIRECTOR))
        assert meta["total_count"] == 0
        assert validate_success(api_client.get_engagement(
            engagement["id"], FINANCE))["labor_estimate_total_cents"] == 0

    def test_subscription_package_resolves_every_array_element(self):
        """Each element of the engagement array is resolved, so a package whose
        first element is live and whose second is dangling is refused and no
        package row survives.

        PRD: "Every element of `included_engagement_ids` must name an existing
        engagement — a dangling element yields `ERR_ENGAGEMENT_NOT_FOUND`"

        Design: Corner/entities/subscription_package_referencing_absent_engagement_returns_not_found
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        engagement = validate_success(api_client.create_engagement(
            {
                "engagement_type": "PRESENTED",
                "space_id": space["id"],
                "artist_id": artist["id"],
                "title": "Cadence Quartet Recital",
                "load_in_start_utc": "2026-10-10T08:00:00Z",
                "performance_start_utc": "2026-10-11T19:00:00Z",
                "performance_end_utc": "2026-10-11T22:00:00Z",
                "load_out_end_utc": "2026-10-12T02:00:00Z",
                "performance_day_count": 1,
                "load_in_day_count": 1,
            }, DIRECTOR), 201)

        validate_error(api_client.create_subscription_package(
            create_subscription_package_payload(
                [engagement["id"], NON_EXISTENT_UUID],
                name="Chamber Series", package_price_cents=1_500_000,
                subscription_tier_name="ORCH", seats_per_order=2),
            BOX_OFFICE), "ERR_ENGAGEMENT_NOT_FOUND", 404)

        survivor = validate_success(
            api_client.get_engagement(engagement["id"], FINANCE))
        assert survivor["version"] == 1
        assert survivor["ticketing_status"] == "TICKETING_UNSET"
