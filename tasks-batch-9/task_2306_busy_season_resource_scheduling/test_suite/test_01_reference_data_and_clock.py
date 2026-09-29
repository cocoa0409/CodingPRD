"""Reference data registration, list pagination and the logical clock."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_client,
    assert_hours,
    assert_pagination_meta,
    assert_pct,
    assert_staff_member,
    create_client_payload,
    create_review_capacity_window_payload,
    create_staff_member_payload,
    create_engagement,
    create_partner,
    create_client,
    create_senior,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    independence_officer_headers,
    make_engagement_partner_headers,
)


class TestClientRegistration:
    """Registering a client and reading it back."""

    def test_public_interest_flag_pins_rotation_limit_to_five(self, api, admin_headers):
        """A listed client gets the shorter partner rotation run.

        PRD 3.1: "That flag has one immediate effect: the server sets the derived
        `partner_rotation_limit_years` to 5 when `public_interest_entity` is true
        and to 7 otherwise."

        Design: Corner/entities/client_creation_pie_sets_rotation_limit_five
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        created = validate_success(
            api.create_client(
                create_client_payload(
                    name="Aurora Federal Bancorp",
                    industry_code="FINANCIAL_SERVICES",
                    public_interest_entity=True,
                    fiscal_year_end="2026-12-31",
                ),
                admin_headers,
            ),
            201,
        )

        assert_client(created)
        assert created["name"] == "Aurora Federal Bancorp"
        assert created["industry_code"] == "FINANCIAL_SERVICES"
        assert created["public_interest_entity"] is True
        assert created["fiscal_year_end"] == "2026-12-31"
        assert created["partner_rotation_limit_years"] == 5
        assert created["engagement_count"] == 0
        assert created["version"] == 1

    def test_omitted_public_interest_flag_defaults_false_with_limit_seven(
        self, api, admin_headers
    ):
        """Leaving the flag out yields the ordinary seven-year run.

        PRD 3.1: "The optional `public_interest_entity` flag marks listed and
        other public-interest clients and defaults to false when omitted."

        Design: Corner/entities/client_omitted_public_interest_entity_defaults_false_with_limit_seven
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        payload = create_client_payload(
            name="Meridian Manufacturing",
            industry_code="MANUFACTURING",
            public_interest_entity=None,
            fiscal_year_end="2026-12-31",
        )
        assert "public_interest_entity" not in payload

        created = validate_success(api.create_client(payload, admin_headers), 201)

        assert created["public_interest_entity"] is False
        assert created["partner_rotation_limit_years"] == 7
        assert created["engagement_count"] == 0

    def test_create_read_and_list_round_trip(self, api, admin_headers):
        """Two clients are written, read individually and paged over.

        PRD 2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        PRD 2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope."

        Design: Corner/endpoints/client_create_read_and_list_round_trip
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        first = validate_success(
            api.create_client(
                create_client_payload(
                    name="Meridian Manufacturing",
                    industry_code="MANUFACTURING",
                    public_interest_entity=False,
                    fiscal_year_end="2026-12-31",
                ),
                admin_headers,
            ),
            201,
        )
        second = validate_success(
            api.create_client(
                create_client_payload(
                    name="Harbor Federal Savings",
                    industry_code="FINANCIAL_SERVICES",
                    public_interest_entity=True,
                    fiscal_year_end="2026-06-30",
                ),
                admin_headers,
            ),
            201,
        )
        for record in (first, second):
            assert is_valid_uuid(record["id"])
            assert is_iso8601_timestamp(record["created_at"])
            assert is_iso8601_timestamp(record["updated_at"])
            assert isinstance(record["version"], int)

        read_response = api.get_client(
            first["id"],
            make_engagement_partner_headers(TEST_USERS["engagement_partner"]["user_id"]),
        )
        read_back = validate_success(read_response)
        assert read_back["name"] == "Meridian Manufacturing"
        assert read_back["industry_code"] == "MANUFACTURING"
        assert read_back["public_interest_entity"] is False
        assert read_back["fiscal_year_end"] == "2026-12-31"
        assert read_back["partner_rotation_limit_years"] == 7
        assert read_back["engagement_count"] == 0

        envelope = read_response.json()
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"])
        assert envelope["response_type"] == "object"

        rows, meta = validate_paginated(
            api.list_clients(independence_officer_headers(), limit=1, offset=1)
        )
        assert_pagination_meta(
            meta,
            expected_limit=1,
            expected_offset=1,
            expected_total=2,
            expected_has_more=False,
        )
        assert len(rows) == 1


class TestStaffRoster:
    """Registering staff and the figures the server derives for them."""

    def test_domestic_manager_capacity_fields_derived_on_creation(
        self, api, admin_headers
    ):
        """A fresh domestic manager is review-capable and starts clean.

        PRD 3.1: "From `level` and `service_center` the server derives
        `review_capable`, which is true exactly when the level is `MANAGER` or
        `PARTNER` **and** the service centre is `DOMESTIC`."

        PRD 3.1: "A freshly registered staff member starts from a clean workload
        slate: `committed_hours_current_week` is 0.00, `workload_status` is
        `GREEN`, both `burnout_risk_score_actual` and
        `burnout_risk_score_committed` are 0.00, and `turnover_risk_band` is
        `LOW`."

        Design: Corner/entities/staff_member_computed_capacity_fields_derived_on_creation
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        created = validate_success(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Dana Whitfield",
                    level="MANAGER",
                    service_center="DOMESTIC",
                    industry_specialization="MANUFACTURING",
                    cpa_licensed=True,
                    base_weekly_cap_hours=45.00,
                    hourly_bill_rate=260.00,
                ),
                admin_headers,
            ),
            201,
        )

        assert_staff_member(created)
        assert created["review_capable"] is True
        assert_hours(created["committed_hours_current_week"], 0.00)
        assert_hours(created["effective_weekly_cap_hours"], 56.25)
        assert_hours(created["daily_capacity_hours"], 11.25)
        assert created["workload_status"] == "GREEN"
        assert_hours(created["burnout_risk_score_actual"], 0.00)
        assert_hours(created["burnout_risk_score_committed"], 0.00)
        assert created["turnover_risk_band"] == "LOW"

    def test_offshore_manager_is_not_review_capable(self, api, admin_headers):
        """The grade alone is not enough; the service centre decides too.

        PRD 3.1: "From `level` and `service_center` the server derives
        `review_capable`, which is true exactly when the level is `MANAGER` or
        `PARTNER` **and** the service centre is `DOMESTIC`."

        Design: Corner/entities/offshore_manager_computed_review_capable_false
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        created = validate_success(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Ravi Menon",
                    level="MANAGER",
                    service_center="OFFSHORE",
                    industry_specialization="MANUFACTURING",
                    cpa_licensed=True,
                    base_weekly_cap_hours=40.00,
                    hourly_bill_rate=95.00,
                ),
                admin_headers,
            ),
            201,
        )

        assert created["level"] == "MANAGER"
        assert created["service_center"] == "OFFSHORE"
        assert created["review_capable"] is False
        assert_hours(created["effective_weekly_cap_hours"], 50.00)
        assert_hours(created["daily_capacity_hours"], 10.00)

    def test_system_fields_generated_on_creation(self, api, admin_headers):
        """The identifier, both stamps and the counter come from the server.

        PRD 2.7: "`id` — a server-minted UUID, with no type prefix of any kind."

        PRD 2.7: "`version` — an integer that increments by one on every mutation
        of the row."

        Design: Corner/entities/staff_member_system_fields_generated_on_creation
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        senior = create_senior(api)

        read_back = validate_success(api.get_staff_member(senior["id"], admin_headers))

        assert read_back["id"] == senior["id"]
        assert is_valid_uuid(read_back["id"])
        assert read_back["version"] == 1
        assert is_iso8601_timestamp(read_back["created_at"])
        assert is_iso8601_timestamp(read_back["updated_at"])
        assert read_back["full_name"] == "Sam Oyelaran"
        assert_hours(read_back["base_weekly_cap_hours"], 40.00)

    def test_undeclared_level_is_rejected_and_writes_nothing(self, api, admin_headers):
        """A grade outside the four declared members never reaches the roster.

        PRD 2.9: "Request shape: every required field present, every type
        correct, every enumerated value a declared member, and every numeric
        field inside its declared range — including a phase's `expected_hours`
        strictly greater than zero and a booking's `allocated_hours` strictly
        greater than zero — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/staff_member_create_with_undeclared_level_enum_rejected
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        response = api.create_staff_member(
            create_staff_member_payload(
                full_name="Jess Nakamura",
                level="DIRECTOR",
                service_center="DOMESTIC",
                industry_specialization="MANUFACTURING",
                cpa_licensed=True,
                base_weekly_cap_hours=40.00,
                hourly_bill_rate=180.00,
            ),
            admin_headers,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)

        _, meta = validate_paginated(
            api.list_staff_members(admin_headers, level="SENIOR")
        )
        assert meta["total_count"] == 0


class TestListPagination:
    """The two pagination query parameters and their bounds."""

    def test_limit_and_offset_bounds_are_enforced(self, api, manager_headers):
        """101 and -1 are refused; 100 is admissible.

        PRD 2.3: "A `limit` below 1 or above 100, or an `offset` below 0, or a
        non-integer value for either, is rejected with `ERR_INVALID_PAGINATION`
        (HTTP 422)."

        PRD 2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/validations/list_limit_above_hundred_rejected_as_invalid_pagination
        """

        set_clock(api, "2026-08-03T09:00:00Z")

        validate_error(
            api.list_staff_members(manager_headers, limit=101, offset=0),
            ApiErrorId.INVALID_PAGINATION.value,
            422,
        )
        validate_error(
            api.list_staff_members(manager_headers, limit=10, offset=-1),
            ApiErrorId.INVALID_PAGINATION.value,
            422,
        )

        accepted = api.list_staff_members(manager_headers, limit=100, offset=0)
        _, meta = validate_paginated(accepted)
        assert accepted.json()["meta"]["api_request_id"].startswith("req_")
        assert_pagination_meta(meta, expected_limit=100, expected_offset=0)


class TestReviewCapacityWindowDeclaration:
    """Who may own review capacity, and for which week."""

    def test_non_monday_week_start_is_rejected(self, api, admin_headers):
        """A Tuesday is not an ISO week start.

        PRD 2.4: "Wherever an input field named `week_start_date` is accepted,
        its value must itself be a Monday, or the request is rejected with
        `ERR_NOT_WEEK_START` (HTTP 422)."

        Design: Corner/validations/review_window_on_a_tuesday_rejected_as_not_week_start
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        reviewer = validate_success(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Mel Arbogast",
                    level="MANAGER",
                    service_center="DOMESTIC",
                    industry_specialization="MANUFACTURING",
                    cpa_licensed=True,
                    base_weekly_cap_hours=40.00,
                    hourly_bill_rate=260.00,
                ),
                admin_headers,
            ),
            201,
        )

        validate_error(
            api.create_review_capacity_window(
                create_review_capacity_window_payload(
                    reviewer["id"],
                    week_start_date="2026-08-04",
                    review_capacity_hours=10.00,
                ),
                admin_headers,
            ),
            ApiErrorId.NOT_WEEK_START.value,
            422,
        )

        window = validate_success(
            api.create_review_capacity_window(
                create_review_capacity_window_payload(
                    reviewer["id"],
                    week_start_date="2026-08-03",
                    review_capacity_hours=10.00,
                ),
                admin_headers,
            ),
            201,
        )
        assert window["week_start_date"] == "2026-08-03"
        assert_hours(window["committed_review_hours"], 0.00)
        assert_hours(window["remaining_review_hours"], 10.00)

    def test_offshore_manager_cannot_own_review_capacity(
        self, api, admin_headers, manager_headers
    ):
        """The window's reviewer must clear the same eligibility rule.

        PRD 3.5: "The same eligibility rule applies when a `FirmAdmin` declares a
        review capacity window for a `reviewer_staff_id`, and the refusal there
        carries the same code."

        Design: Corner/validations/review_window_for_offshore_manager_rejected_as_not_eligible
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        offshore_manager = validate_success(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Ines Duarte",
                    level="MANAGER",
                    service_center="OFFSHORE",
                    industry_specialization="MANUFACTURING",
                    cpa_licensed=False,
                    base_weekly_cap_hours=40.00,
                    hourly_bill_rate=120.00,
                ),
                admin_headers,
            ),
            201,
        )
        domestic_manager = validate_success(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Mel Arbogast",
                    level="MANAGER",
                    service_center="DOMESTIC",
                    industry_specialization="MANUFACTURING",
                    cpa_licensed=True,
                    base_weekly_cap_hours=40.00,
                    hourly_bill_rate=260.00,
                ),
                admin_headers,
            ),
            201,
        )

        read_offshore = validate_success(
            api.get_staff_member(offshore_manager["id"], manager_headers)
        )
        assert read_offshore["review_capable"] is False

        validate_error(
            api.create_review_capacity_window(
                create_review_capacity_window_payload(
                    offshore_manager["id"],
                    week_start_date="2026-08-03",
                    review_capacity_hours=10.00,
                ),
                admin_headers,
            ),
            ApiErrorId.REVIEW_OWNER_NOT_ELIGIBLE.value,
            422,
        )

        window = validate_success(
            api.create_review_capacity_window(
                create_review_capacity_window_payload(
                    domestic_manager["id"],
                    week_start_date="2026-08-03",
                    review_capacity_hours=10.00,
                ),
                admin_headers,
            ),
            201,
        )
        assert_hours(window["remaining_review_hours"], 10.00)


class TestLogicalClock:
    """The startup instant and what moving the clock recomputes."""

    def test_workload_read_defaults_to_the_clock_iso_week(self, api, manager_headers):
        """With no week supplied the read resolves the clock's own Monday.

        PRD 2.4: "Before any call is made, the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        PRD 3.4: "A per-staff computed read reports one ISO week's picture,
        defaulting to the ISO week of the logical clock when no `week_start_date`
        is supplied and rejecting a non-Monday value with `ERR_NOT_WEEK_START`."

        Design: Corner/endpoints/workload_read_without_a_week_defaults_to_the_clock_iso_week
        """

        clock = set_clock(api, "2026-08-01T00:00:00Z")
        assert clock["current_date"] == "2026-08-01"
        assert clock["iso_week_start_date"] == "2026-07-27"

        senior = create_senior(api)

        workload = validate_success(
            api.get_staff_workload(senior["id"], manager_headers)
        )

        assert workload["week_start_date"] == "2026-07-27"
        assert_hours(workload["committed_hours"], 0.00)
        assert_hours(workload["logged_hours"], 0.00)
        assert_hours(workload["approved_waiver_hours"], 0.00)
        assert_hours(workload["effective_weekly_cap_hours"], 50.00)
        assert_hours(workload["daily_capacity_hours"], 10.00)
        assert_hours(workload["remaining_week_hours"], 50.00)
        assert workload["workload_status"] == "GREEN"
        assert_hours(workload["burnout_risk_score_actual"], 0.00)
        assert_hours(workload["burnout_risk_score_committed"], 0.00)
        assert workload["turnover_risk_band"] == "LOW"

    def test_advancing_the_clock_alone_flips_schedule_risk(self, api, manager_headers):
        """Nothing about the engagement changes, only the distance to deadline.

        PRD 2.4: "Advancing the clock has consequences well beyond the returned
        payload. Every engagement's `schedule_risk_band` is recomputed, and for
        every staff member the server recomputes `committed_hours_current_week`,
        `effective_weekly_cap_hours`, `daily_capacity_hours`, `workload_status`,
        `burnout_risk_score_actual`, `burnout_risk_score_committed` and
        `turnover_risk_band`."

        PRD 3.2: "otherwise, if completion is strictly below 60.00 percent and
        there are 30 or fewer days to the deadline the band is `HIGH`"

        Design: Corner/endpoints/advancing_the_clock_alone_flips_schedule_risk_from_low_to_high
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        engagement = create_engagement(api, client["id"], partner["id"])

        before = validate_success(
            api.get_engagement(engagement["id"], manager_headers)
        )
        assert before["schedule_risk_band"] == "LOW"
        assert_pct(before["staffing_completion_pct"], 0.00)

        moved = set_clock(api, "2026-10-01T09:00:00Z")
        assert moved["current_date"] == "2026-10-01"
        assert moved["iso_week_start_date"] == "2026-09-28"

        after = validate_success(api.get_engagement(engagement["id"], manager_headers))
        assert after["schedule_risk_band"] == "HIGH"
