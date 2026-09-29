"""Record shape, defaults, computed aggregates, listing and the not-found family."""
from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.assertions import (
    assert_branch,
    assert_common_fields,
    assert_deposit_market,
    assert_institution,
    assert_public_comment,
    assert_same_instant,
)
from test_helpers.factories import acquirer_payload, branch_payload
from test_helpers.fixtures import (
    application_under_review,
    create_acquirer,
    create_application,
    create_branch,
    create_market,
    create_regulatory_schedule,
    create_two_institutions,
    file_comment,
    open_comment_period,
    read_application,
    read_institution,
    read_market,
    reset_clock_to_epoch,
    set_clock,
    two_bank_world,
)
from test_helpers.test_users import SECOND_COMMENTER_USER_ID
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
COMMENTER = TEST_USERS["commenter_headers"]


class TestRecordCreationDefaults:
    """A fresh record stores what the caller supplied and derives the rest."""

    def test_institution_creation_stores_its_inputs_and_zeroes_its_aggregates(self):
        """PRD §3.1: "A newly registered institution is `ACTIVE`, with `total_deposits_usd` of 0 and
        `branch_count` of 0; `status` is one of `ACTIVE` or `MERGED_OUT` and only the service sets
        it."
        PRD §2.4: "Every record also carries `created_at`, an ISO 8601 UTC timestamp with three
        fractional digits, set once at creation and never modified."

        Design: Corner/entities/institution_creation_stores_every_input_field_and_defaults_the_aggregates
        """
        reset_clock_to_epoch()

        institution = validate_success(
            api_client.create_institution(acquirer_payload(), ANALYST), 201
        )

        assert_institution(institution)
        assert institution["legal_name"] == "Northbay National Bank"
        assert institution["charter_type"] == "NATIONAL"
        assert institution["primary_regulator"] == "OCC"
        assert institution["cet1_capital_usd"] == 200_000_000
        assert institution["latest_cra_rating"] == "SATISFACTORY"
        assert institution["status"] == "ACTIVE"
        assert institution["total_deposits_usd"] == 0
        assert institution["branch_count"] == 0
        assert institution["version"] == 1
        assert_same_instant(institution["created_at"], "2026-08-01T00:00:00Z", "created_at")

    def test_a_market_read_returns_the_stored_row_to_any_role(self):
        """PRD §3.1: "A market is created with `total_deposits_usd` of 0, `participant_count` of 0
        and `hhi_current` of 0."
        PRD §2.3: "Single-resource responses omit all four."

        Design: Corner/entities/deposit_market_retrieval_returns_the_stored_row
        """
        reset_clock_to_epoch()
        market = create_market()

        fetched = validate_success(api_client.get_deposit_market(market["id"], COMMENTER))

        assert_deposit_market(fetched)
        assert fetched["market_code"] == "KESTREL-MSA"
        assert fetched["market_type"] == "MSA"
        assert fetched["total_deposits_usd"] == 0
        assert fetched["participant_count"] == 0
        assert fetched["hhi_current"] == 0

    def test_a_comment_period_defaults_to_a_thirty_day_window(self):
        """PRD §3.7: "A comment period is either created automatically when a filing is accepted for
        review, or opened deliberately by a `CaseAnalyst` naming the `application_id`, the `opens_at`
        instant and an optional `duration_days` that defaults to 30 and, as a stored value, ranges
        from 1 through 90."
        PRD §3.7: "A newly created period is `OPEN` with `extension_count` of 0,
        `extended_days_total` of 0, `comment_count` of 0 and `substantive_protest_count` of 0, and it
        moves the application's community-review axis `NOT_OPEN → OPEN_FOR_COMMENT`."

        Design: Corner/entities/comment_period_duration_defaults_to_thirty_days
        """
        world = two_bank_world()

        period = open_comment_period(world["application"]["id"], "2026-09-01T00:00:00Z")

        assert period["duration_days"] == 30
        assert_same_instant(period["closes_at"], "2026-10-01T00:00:00Z", "closes_at")
        assert period["extension_count"] == 0
        assert period["extended_days_total"] == 0
        assert period["status"] == "OPEN"
        application = read_application(world["application"]["id"], world["acquirer"]["id"])
        assert application["public_review_status"] == "OPEN_FOR_COMMENT"


class TestServerOwnedFields:
    """Aggregates and stamps are derived by the service, never taken from the caller."""

    def test_a_new_branch_recomputes_its_owner_and_its_market(self):
        """PRD §2.8: "Four aggregates are recomputed from the includable set whenever a branch is
        created, whenever a branch changes `status`, and whenever a branch is reassigned from one
        owner to another at consummation."
        PRD §3.1: "A new branch is `OPEN`, and its `designation_application_id`, `notice_sent_at`,
        `planned_closure_date` and `notice_lead_days` are all null."

        Design: Corner/entities/institution_deposit_aggregates_are_computed_and_input_ignored
        """
        reset_clock_to_epoch()
        market = create_market()
        institution = create_acquirer()

        branch = create_branch(institution["id"], market["id"],
                               branch_name="Northbay Kestrel Main", deposits_usd=200_000_000)

        assert_branch(branch)
        assert branch["notice_lead_days"] is None
        owner = read_institution(institution["id"])
        assert owner["total_deposits_usd"] == 200_000_000
        assert owner["branch_count"] == 1
        market_after = read_market(market["id"])
        assert market_after["total_deposits_usd"] == 200_000_000
        assert market_after["participant_count"] == 1
        assert market_after["hhi_current"] == 10000, (
            "a single participant holds a 100 percent share, and 100 squared is 10000"
        )

    def test_a_comment_is_stamped_from_the_logical_clock_and_the_acting_user(self):
        """PRD §3.7: "The service stamps `received_at` from the logical clock and takes
        `commenter_user_id` from the acting `X-User-ID`."
        PRD §3.7: "`response_body` and `responded_at` begin null."

        Design: Corner/entities/public_comment_received_at_is_system_stamped_and_input_ignored
        """
        world = application_under_review()
        set_clock("2026-08-10T00:00:00Z")

        comment = file_comment(
            world["period"]["id"], commenter_user_id=SECOND_COMMENTER_USER_ID,
            commenter_name="Rowan Delgado", commenter_type="INDIVIDUAL", stance="OPPOSE",
            body="Branch hours have already been cut.", substantive=False,
        )

        assert_public_comment(comment)
        assert_same_instant(comment["received_at"], "2026-08-10T00:00:00Z", "received_at")
        assert comment["commenter_user_id"] == SECOND_COMMENTER_USER_ID
        assert comment["status"] == "RECEIVED"
        assert comment["response_body"] is None
        assert comment["responded_at"] is None

    def test_every_record_carries_a_version_counter_that_child_writes_bump(self):
        """PRD §2.4: "There are no exceptions in this domain: institutions, deposit markets,
        branches, merger applications, pro forma capital schedules, competitive analyses, comment
        periods, public comments, hearing requests, community benefits plans, commitment line items,
        approval decisions, approval conditions, systems conversion plans and performance reports all
        expose `id`, `created_at`, `updated_at` and `version`."
        PRD §2.9: "Every mutation, whether requested directly or applied as a cascade, refreshes the
        mutated record's `updated_at` and increments its `version` by 1."

        Design: Corner/entities/every_entity_is_mutable_and_carries_a_version_counter
        """
        world = two_bank_world()
        acquirer_id = world["acquirer"]["id"]

        schedule = create_regulatory_schedule(world["application"]["id"], acquirer_id)

        assert_common_fields(schedule, "pro forma schedule")
        assert schedule["version"] == 1
        application = read_application(world["application"]["id"], acquirer_id)
        assert application["version"] == 2, "the child create bumped the parent"
        assert is_iso8601_timestamp(application["updated_at"])
        assert_same_instant(application["updated_at"], "2026-08-01T00:00:00Z", "updated_at")


class TestListingFilterAndPagination:
    """A filtered list page reports its own totals."""

    def test_the_branch_list_filters_by_market_and_pages(self):
        """PRD §2.3: "For list responses the `meta` object carries four pagination fields alongside
        the request identifier and timestamp: `limit` and `offset` echoing the values in force for
        the page, `total_count` giving the number of records matching the filter before pagination is
        applied, and `has_more` reporting whether any matching record falls after the returned page."
        PRD §2.3: "the branch list accepts `institution_id`, `market_id`,
        `designation_application_id` and `status`"

        Design: Corner/entities/branch_listing_filters_by_market_and_paginates
        """
        reset_clock_to_epoch()
        kestrel = create_market()
        fernwood = create_market(market_code="FERNWOOD-MSA", market_name="Fernwood MSA",
                                 market_type="MSA")
        owner = create_acquirer()
        first = create_branch(owner["id"], kestrel["id"], branch_name="Northbay Kestrel Main",
                              deposits_usd=200_000_000)
        second = create_branch(owner["id"], kestrel["id"], branch_name="Northbay Kestrel North",
                               deposits_usd=30_000_000, service_type="LIMITED_SERVICE")
        outside = create_branch(owner["id"], fernwood["id"], branch_name="Northbay Fernwood",
                                deposits_usd=10_000_000)

        page_one, meta_one = validate_paginated(api_client.list_branches(
            ANALYST, params={"market_id": kestrel["id"], "limit": 1, "offset": 0}))
        page_two, meta_two = validate_paginated(api_client.list_branches(
            ANALYST, params={"market_id": kestrel["id"], "limit": 1, "offset": 1}))

        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert len(page_one) == 1
        assert page_one[0]["market_id"] == kestrel["id"]
        assert meta_two["has_more"] is False
        assert {page_one[0]["id"], page_two[0]["id"]} == {first["id"], second["id"]}
        assert outside["id"] not in {page_one[0]["id"], page_two[0]["id"]}, (
            "the Fernwood branch never appears under a Kestrel market filter"
        )


class TestNotFoundAndMalformedRequests:
    """Unresolvable identifiers and malformed bodies each have their own error."""

    def test_an_unknown_schedule_id_in_the_path_is_not_found(self):
        """PRD §2.4: "A path identifier that does not resolve produces the not-found error for that
        record type — `ERR_INSTITUTION_NOT_FOUND`, `ERR_MARKET_NOT_FOUND`, `ERR_BRANCH_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`,
        `ERR_COMMENT_PERIOD_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_HEARING_REQUEST_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`,
        `ERR_CONDITION_NOT_FOUND`, `ERR_CONVERSION_PLAN_NOT_FOUND` or `ERR_REPORT_NOT_FOUND` — all at
        HTTP 404."

        Design: Corner/entities/get_unknown_pro_forma_schedule_not_found
        """
        reset_clock_to_epoch()

        response = api_client.get_pro_forma_schedule(NON_EXISTENT_UUID, ANALYST)

        validate_error(response, ApiErrorId.ERR_SCHEDULE_NOT_FOUND.value, 404)

    def test_a_branch_without_deposits_is_a_malformed_request(self):
        """PRD §3.1: "Adding one names its owner through `institution_id`, its market through
        `market_id`, its `branch_name`, and the `deposits_usd` booked at that office, which must be
        strictly greater than 0."
        PRD §2.5: "Any failure is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/branch_without_deposits_usd_invalid_request
        """
        reset_clock_to_epoch()
        market = create_market()
        owner = create_acquirer()

        response = api_client.create_branch(
            {"institution_id": owner["id"], "market_id": market["id"],
             "branch_name": "Northbay Kestrel Main"},
            ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        assert read_market(market["id"])["participant_count"] == 0, (
            "no branch row was created, so the market still has no participants"
        )

    def test_an_undeclared_charter_type_fails_the_body_shape_check(self):
        """PRD §2.5: "Request-body shape: the body parses; every required input field is present;
        every enum-typed value is a declared member of its enumeration; every USD amount is a
        non-negative integer; every examiner score is an integer from 0 through 100 inclusive;
        `term_years` is from 1 through 10 inclusive; `duration_days` is from 7 through 90 inclusive;
        and every supplied timestamp is a valid UTC instant."
        PRD §3.1: "A mismatched pair is refused with `ERR_REGULATOR_CHARTER_MISMATCH`."

        Design: Corner/entities/institution_with_undeclared_charter_type_invalid_request
        """
        reset_clock_to_epoch()

        response = api_client.create_institution(
            acquirer_payload(legal_name="Undeclared Charter Bank", charter_type="CREDIT_UNION",
                             primary_regulator="OCC"),
            ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_a_branch_naming_an_unknown_market_is_not_found(self):
        """PRD §2.4: "A foreign key carried in a request body that does not resolve produces the same
        family of not-found errors at HTTP 404: an unresolvable institution reference yields
        `ERR_INSTITUTION_NOT_FOUND`, an unresolvable market reference `ERR_MARKET_NOT_FOUND`, an
        unresolvable application reference `ERR_APPLICATION_NOT_FOUND`, an unresolvable
        comment-period reference `ERR_COMMENT_PERIOD_NOT_FOUND`, an unresolvable comment reference
        `ERR_COMMENT_NOT_FOUND`, an unresolvable benefits-plan reference `ERR_PLAN_NOT_FOUND` and an
        unresolvable decision reference `ERR_DECISION_NOT_FOUND`."

        Design: Corner/entities/branch_with_unknown_market_id_not_found
        """
        reset_clock_to_epoch()
        owner = create_acquirer()

        response = api_client.create_branch(
            branch_payload(owner["id"], NON_EXISTENT_UUID, branch_name="Orphan Branch",
                           deposits_usd=10_000_000),
            ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_MARKET_NOT_FOUND.value, 404)
        assert read_institution(owner["id"])["branch_count"] == 0

    def test_an_analysis_naming_an_unknown_application_is_not_found(self):
        """PRD §2.5: "Existence of every foreign key carried in the request body — the appropriate
        not-found error."
        PRD §3.5: "A `CaseAnalyst` names the `application_id` and the `market_id`, and the request is
        refused with `ERR_NO_MARKET_OVERLAP` unless both the acquirer and the target each hold at
        least one includable branch in that market."

        Design: Corner/entities/competitive_analysis_with_unknown_application_not_found
        """
        reset_clock_to_epoch()
        market = create_market()

        response = api_client.create_competitive_analysis(
            {"application_id": NON_EXISTENT_UUID, "market_id": market["id"]}, ANALYST
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, 404)
