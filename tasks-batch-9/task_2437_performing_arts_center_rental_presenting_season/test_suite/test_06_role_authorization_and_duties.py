"""Authorization: who may read an engagement, who may act on which endpoint,
what an unrecognized or absent role header produces, entity-backed ownership,
and the separation of duties between accepting a fee and finalizing the
settlement that pays it.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    book_rental_engagement,
    clear_presented_rider,
    confirm,
    counter_round,
    make_artist_representative_headers,
    make_finance_controller_headers,
    make_headers,
    make_partial_headers,
    make_programming_director_headers,
    make_rental_client_contact_headers,
    open_negotiation_round,
    read_engagement,
    reconcile_expenses,
    register_artist,
    register_hall,
    register_rental_client,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

DUAL_ROLE_USER_ID = "user-dual-1"
SECOND_CONTROLLER_USER_ID = "user-fc-2"


class TestEngagementReadAccess:

    def test_every_declared_role_may_read_the_engagement_it_takes_part_in(self):
        """The engagement read is the one place the whole cast meets: all six
        operator roles read the presented booking, the agency reads its own
        artist's engagement and the client contact reads its own rental. None of
        the reads mutates anything.

        PRD: "Read an engagement with all three state dimensions and every
        derived money field."

        Design: Corner/rbac/every_declared_role_may_read_the_engagement_it_participates_in
        """
        space = register_hall()
        artist = register_artist()
        client = register_rental_client()
        presented = book_presented_engagement(space["id"], artist["id"])
        rental = book_rental_engagement(
            space["id"], client["id"],
            load_in_start_utc="2026-10-01T08:00:00Z",
            performance_start_utc="2026-10-02T19:00:00Z",
            performance_end_utc="2026-10-02T22:00:00Z",
            load_out_end_utc="2026-10-03T02:00:00Z")

        operator_headers = [ADMIN, DIRECTOR, RENTAL_MANAGER, TECH_DIRECTOR,
                            BOX_OFFICE, FINANCE]
        for headers in operator_headers:
            read = validate_success(
                api_client.get_engagement(presented["id"], headers))
            assert read["id"] == presented["id"]

        agency_read = validate_success(api_client.get_engagement(
            presented["id"], make_artist_representative_headers(artist["id"])))
        assert agency_read["artist_id"] == artist["id"]

        contact_read = validate_success(api_client.get_engagement(
            rental["id"], make_rental_client_contact_headers(client["id"])))
        assert contact_read["rental_client_id"] == client["id"]

        assert read_engagement(presented["id"])["version"] == 1
        assert read_engagement(rental["id"])["version"] == 1


class TestEndpointRoleTables:

    def test_ticketing_and_negotiation_belong_to_different_roles(self):
        """The role column of each endpoint is exhaustive in both directions:
        the box office may not open a fee negotiation and the programming
        director may not draft a price tier. Neither refusal advances the
        engagement, so the version the client already held still pins the round
        it opens next.

        PRD: "the roles column is exhaustive — a role absent from a row is
        refused with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/box_office_manager_cannot_open_a_fee_negotiation
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        pinned_version = engagement["version"]

        validate_error(api_client.open_fee_negotiation(
            engagement["id"],
            {"offered_fee_cents": 300_000, "offered_artist_share_pct": 0.10,
             "expected_engagement_version": pinned_version},
            BOX_OFFICE), "ERR_ROLE_NOT_PERMITTED")

        validate_error(api_client.create_price_tier(
            engagement["id"],
            {"tier_name": "ORCH", "seats_allocated": 100,
             "base_price_cents": 10_000, "price_ceiling_cents": 15_000,
             "dynamic_pricing_enabled": False, "subscription_eligible": False},
            DIRECTOR), "ERR_ROLE_NOT_PERMITTED")

        assert read_engagement(engagement["id"])["ticketing_status"] == \
            "TICKETING_UNSET"

        opened = validate_success(api_client.open_fee_negotiation(
            engagement["id"],
            {"offered_fee_cents": 300_000, "offered_artist_share_pct": 0.10,
             "expected_engagement_version": pinned_version},
            DIRECTOR), expected_status=201)
        assert opened["status"] == "OFFERED"

        tier = validate_success(api_client.create_price_tier(
            engagement["id"],
            {"tier_name": "ORCH", "seats_allocated": 100,
             "base_price_cents": 10_000, "price_ceiling_cents": 15_000,
             "dynamic_pricing_enabled": False, "subscription_eligible": False},
            BOX_OFFICE), expected_status=201)
        assert tier["status"] == "ACTIVE"
        assert read_engagement(engagement["id"])["ticketing_status"] == \
            "TIERS_DRAFT"


class TestAuthenticationLayer:

    def test_unknown_role_or_absent_headers_are_reported_as_unauthenticated(self):
        """An undeclared role name is an authentication failure, reported before
        the path is resolved — an absent engagement never even gets looked up —
        and a request carrying neither identity header fails the same way
        without leaking the resource it asked for.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the
        eight role names enumerated below, the request is rejected with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

        Design: Corner/rbac/request_with_missing_or_undeclared_auth_headers_is_unauthenticated
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])

        validate_error(api_client.get_engagement(
            NON_EXISTENT_UUID, make_headers("user-scanner-1", "TicketScanner")),
            "ERR_MISSING_AUTH_HEADERS")

        body = validate_error(api_client.get_engagement(
            engagement["id"], make_partial_headers()),
            "ERR_MISSING_AUTH_HEADERS")
        assert "id" not in body


class TestEntityBackedOwnership:

    def test_an_agency_may_only_file_the_rider_of_its_own_artist(self):
        """Two artists share the season. The agency of the second artist is a
        recognized role on the rider endpoint, so its attempt on the first
        artist's engagement fails the ownership comparison rather than the role
        check; the owning agency then files successfully.

        PRD: "Concretely, an `ArtistRepresentative` may act on an engagement
        only when that engagement's `artist_id` equals `X-User-ID`"

        Design: Corner/rbac/artist_representative_of_another_artist_is_forbidden
        """
        space = register_hall()
        own_artist = register_artist(legal_name="Cadence Quartet")
        other_artist = register_artist(legal_name="Harbour Brass Collective")
        engagement = book_presented_engagement(
            space["id"], own_artist["id"],
            load_in_start_utc="2026-10-01T08:00:00Z",
            performance_start_utc="2026-10-02T19:00:00Z",
            performance_end_utc="2026-10-02T22:00:00Z",
            load_out_end_utc="2026-10-03T02:00:00Z")

        rider_payload = {"submitted_rigging_kg": 1_000,
                         "requested_power_amps": 200,
                         "requested_dmx_universes": 2,
                         "requires_orchestra_pit": False}

        validate_error(api_client.submit_tech_rider(
            engagement["id"], rider_payload,
            make_artist_representative_headers(other_artist["id"])),
            "ERR_NOT_RESOURCE_OWNER")

        submitted = validate_success(api_client.submit_tech_rider(
            engagement["id"], rider_payload,
            make_artist_representative_headers(own_artist["id"])),
            expected_status=201)
        assert submitted["review_status"] == "SUBMITTED"

        riders, meta = validate_paginated(
            api_client.list_engagement_tech_riders(engagement["id"],
                                                   TECH_DIRECTOR))
        assert meta["total_count"] == 1
        assert riders[0]["id"] == submitted["id"]


class TestSegregationOfDuties:

    def test_the_controller_who_accepted_the_fee_may_not_finalize_the_settlement(self):
        """One operator identifier accepts the artist's counter and later runs
        the risk assessment. That identifier is barred from finalizing the
        settlement that pays the guarantee it agreed to; a second controller
        closes the engagement instead.

        PRD: "the acting `X-User-ID` must differ from the engagement's
        `fee_accepted_by_user_id`, and an attempt by the very controller who
        accepted the artist's fee is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/finance_controller_who_accepted_the_fee_cannot_finalize_the_settlement
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        clear_presented_rider(engagement["id"], artist["id"])
        add_price_tier(engagement["id"], tier_name="ORCH", seats_allocated=100,
                       base_price_cents=10_000, price_ceiling_cents=15_000)

        dual_director = make_programming_director_headers(DUAL_ROLE_USER_ID)
        round_data = open_negotiation_round(engagement["id"], 400_000, 0.10,
                                            headers=dual_director)
        counter_round(round_data["id"], artist["id"], 400_000, 0.15)
        accepted = validate_success(api_client.accept_fee_negotiation(
            round_data["id"], dual_director))
        assert accepted["accepted_fee_cents"] == 400_000
        assert accepted["accepted_by_user_id"] == DUAL_ROLE_USER_ID

        assessed = assess_risk(
            engagement["id"],
            headers=make_finance_controller_headers(DUAL_ROLE_USER_ID))
        assert assessed["risk_score"] == 33
        assert assessed["financial_clearance"] == "CLEARED"
        assert assessed["projected_gross_cents"] == 800_000
        assert assessed["projected_margin_cents"] == 150_000
        assert assessed["fee_accepted_by_user_id"] == DUAL_ROLE_USER_ID

        confirm(engagement["id"])
        set_clock("2026-10-12T00:00:00Z")
        settlement = validate_success(
            api_client.open_settlement(engagement["id"], FINANCE),
            expected_status=201)
        reconciled = reconcile_expenses(settlement["id"], 0)
        assert reconciled["guarantee_cents"] == 400_000
        assert reconciled["amount_payable_to_artist_cents"] == 400_000
        assert reconciled["net_to_center_cents"] == -400_000

        validate_error(api_client.finalize_settlement(
            settlement["id"],
            make_finance_controller_headers(DUAL_ROLE_USER_ID)),
            "ERR_SEGREGATION_OF_DUTIES")

        settlements, _ = validate_paginated(
            api_client.list_engagement_settlements(engagement["id"], FINANCE))
        assert settlements[0]["status"] == "EXPENSES_RECONCILED"
        assert settlements[0]["finalized_by_user_id"] is None
        assert read_engagement(engagement["id"])["lifecycle_status"] == "PERFORMED"

        finalized = validate_success(api_client.finalize_settlement(
            settlement["id"],
            make_finance_controller_headers(SECOND_CONTROLLER_USER_ID)))
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_by_user_id"] == SECOND_CONTROLLER_USER_ID

        after = read_engagement(engagement["id"])
        assert after["lifecycle_status"] == "SETTLED"
        assert after["realized_margin_cents"] == -400_000

        artist_after = validate_success(
            api_client.get_artist(artist["id"], DIRECTOR))
        assert artist_after["lifetime_guarantee_paid_cents"] == 400_000
