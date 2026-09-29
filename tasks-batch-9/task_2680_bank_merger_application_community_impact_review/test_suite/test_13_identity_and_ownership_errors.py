"""Identity errors: unresolvable paths, missing credentials and the two ownership checks."""
from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.factories import pro_forma_schedule_payload
from test_helpers.fixtures import (
    application_under_review,
    create_acquirer,
    create_application,
    create_regulatory_schedule,
    create_target,
    create_third_party,
    file_substantive_protest,
    read_application,
    read_hearing_request,
    request_hearing,
    reset_clock_to_epoch,
    submit_application,
)
from test_helpers.test_users import (
    COMMENTER_USER_ID,
    SECOND_COMMENTER_USER_ID,
    make_commenter_headers,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
COMMENTER = TEST_USERS["commenter_headers"]
SECOND_COMMENTER = TEST_USERS["second_commenter_headers"]


class TestUnresolvablePathIdentifiers:
    """Each record type answers a bad path identifier with its own not-found error."""

    def test_01_every_record_type_has_its_own_not_found_error(self):
        """PRD §2.4: "A path identifier that does not resolve produces the not-found error for that
        record type — `ERR_INSTITUTION_NOT_FOUND`, `ERR_MARKET_NOT_FOUND`, `ERR_BRANCH_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`,
        `ERR_COMMENT_PERIOD_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_HEARING_REQUEST_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`,
        `ERR_CONDITION_NOT_FOUND`, `ERR_CONVERSION_PLAN_NOT_FOUND` or `ERR_REPORT_NOT_FOUND` — all at
        HTTP 404."
        PRD §2.5: "Existence of every identifier in the request path, resolved left to right — the
        appropriate not-found error."

        Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        reset_clock_to_epoch()

        expectations = [
            (api_client.get_institution, ApiErrorId.ERR_INSTITUTION_NOT_FOUND),
            (api_client.get_branch, ApiErrorId.ERR_BRANCH_NOT_FOUND),
            (api_client.get_competitive_analysis, ApiErrorId.ERR_ANALYSIS_NOT_FOUND),
            (api_client.get_comment_period, ApiErrorId.ERR_COMMENT_PERIOD_NOT_FOUND),
            (api_client.get_hearing_request, ApiErrorId.ERR_HEARING_REQUEST_NOT_FOUND),
            (api_client.get_benefits_plan, ApiErrorId.ERR_PLAN_NOT_FOUND),
            (api_client.get_line_item, ApiErrorId.ERR_LINE_ITEM_NOT_FOUND),
            (api_client.get_approval_decision, ApiErrorId.ERR_DECISION_NOT_FOUND),
            (api_client.get_approval_condition, ApiErrorId.ERR_CONDITION_NOT_FOUND),
            (api_client.get_conversion_plan, ApiErrorId.ERR_CONVERSION_PLAN_NOT_FOUND),
            (api_client.get_performance_report, ApiErrorId.ERR_REPORT_NOT_FOUND),
        ]

        for read, expected in expectations:
            response = read(NON_EXISTENT_UUID, ANALYST)
            validate_error(response, expected.value, 404)

        institutions, meta = validate_paginated(api_client.list_institutions(ANALYST))
        assert meta["total_count"] == 0, "none of the failed reads created anything"
        assert institutions == []


class TestUnauthenticatedRequests:
    """Authentication is decided before the identifier is even resolved."""

    def test_02_absent_or_undeclared_credentials_are_unauthenticated(self):
        """PRD §2.1: "Every request to every endpoint, including reads, must carry two headers:
        `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in
        which that principal is acting."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five declared
        role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "The authentication check always precedes the authorization check; no other
        validation runs before either."

        Design: Corner/errors/missing_or_undeclared_role_header_is_unauthenticated
        """
        reset_clock_to_epoch()
        institution = create_acquirer()

        no_headers = api_client.get_institution(institution["id"], {})
        bogus_role = api_client.get_institution(
            institution["id"], build_user_headers("auditor-1", "Auditor"))
        no_user_id = api_client.get_institution(
            institution["id"], {"X-User-Role": "CaseAnalyst"})

        validate_error(no_headers, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        validate_error(bogus_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        validate_error(no_user_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        fetched = validate_success(api_client.get_institution(institution["id"], ANALYST))
        assert fetched["id"] == institution["id"], (
            "the identifier was always valid, so only the credentials were at fault"
        )


class TestFilerOwnership:
    """A stranger institution cannot act on another acquirer's filing."""

    def test_03_a_stranger_institution_is_refused_on_every_filer_scoped_write(self):
        """PRD §2.1: "A `Filer` whose `X-User-ID` does not match the application's `acquirer_id` is
        rejected with `ERR_NOT_APPLICATION_FILER` (HTTP 403)."
        PRD §2.5: "Filer ownership — the acting `X-User-ID` equals the target application's
        `acquirer_id` — `ERR_NOT_APPLICATION_FILER`."
        PRD §2.5: "Optimistic concurrency: `expected_application_version` equals the referenced
        application's current `version` — `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

        Design: Corner/errors/filer_scoped_write_by_another_institution_is_forbidden
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        stranger = create_third_party()
        application = create_application(acquirer["id"], target["id"])
        stranger_headers = make_filer_headers(stranger["id"])

        refused_submit = api_client.submit_merger_application(application["id"], stranger_headers)
        refused_patch = api_client.amend_merger_application(
            application["id"], {"total_consideration_usd": 1}, stranger_headers)
        refused_schedule = api_client.create_pro_forma_schedule(
            pro_forma_schedule_payload(application["id"], 1), stranger_headers)

        validate_error(refused_submit, ApiErrorId.ERR_NOT_APPLICATION_FILER.value, 403)
        validate_error(refused_patch, ApiErrorId.ERR_NOT_APPLICATION_FILER.value, 403)
        validate_error(refused_schedule, ApiErrorId.ERR_NOT_APPLICATION_FILER.value, 403)
        unchanged = read_application(application["id"], acquirer["id"])
        assert unchanged["filing_status"] == "DRAFT"
        assert unchanged["total_consideration_usd"] == 250_000_000
        assert unchanged["version"] == 1
        schedules, meta = validate_paginated(api_client.list_pro_forma_schedules(
            ANALYST, params={"application_id": application["id"]}))
        assert meta["total_count"] == 0
        assert schedules == []

    def test_04_the_owning_acquirer_makes_the_same_three_writes(self):
        """PRD §2.1: "Concretely, a `Filer` may act on a merger application only when `X-User-ID`
        equals that application's `acquirer_id`, and the same comparison reaches every record that
        hangs off the application — its pro forma capital schedules, its branch designations, its
        community benefits plans and line items, its comment responses, its consummation, its systems
        conversion plan and its performance reports."
        PRD §3.4: "A successful filing sets `filing_status` to `SUBMITTED` and increments the
        application's `version` by 1."

        Design: Corner/errors/filer_scoped_write_by_another_institution_is_forbidden
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        owner_headers = make_filer_headers(acquirer["id"])

        amended = validate_success(api_client.amend_merger_application(
            application["id"], {"total_consideration_usd": 260_000_000}, owner_headers))
        create_regulatory_schedule(application["id"], acquirer["id"])
        submitted = submit_application(application["id"], acquirer["id"])

        assert amended["total_consideration_usd"] == 260_000_000
        assert submitted["filing_status"] == "SUBMITTED"
        schedules, meta = validate_paginated(api_client.list_pro_forma_schedules(
            ANALYST, params={"application_id": application["id"]}))
        assert meta["total_count"] == 1


class TestHearingRequestOwnership:
    """Only the petitioner may withdraw the petition."""

    def test_05_another_commenter_cannot_withdraw_the_petition(self):
        """PRD §2.1: "Ownership among commenters is therefore commenter-to-commenter: a
        `PublicCommenter` may withdraw only a hearing request whose `requester_user_id` equals the
        acting `X-User-ID`, and any other commenter attempting the withdrawal is rejected with
        `ERR_NOT_REQUEST_OWNER` (HTTP 403)."
        PRD §2.5: "Hearing-request ownership on withdrawal — `ERR_NOT_REQUEST_OWNER`."

        Design: Corner/errors/withdrawing_another_commenters_hearing_request_is_forbidden
        """
        world = application_under_review()
        protest = file_substantive_protest(world["period"]["id"])
        petition = request_hearing(world["application"]["id"], protest["id"])
        assert petition["requester_user_id"] == COMMENTER_USER_ID

        response = api_client.withdraw_hearing_request(
            petition["id"], make_commenter_headers(SECOND_COMMENTER_USER_ID))

        validate_error(response, ApiErrorId.ERR_NOT_REQUEST_OWNER.value, 403)
        assert read_hearing_request(petition["id"])["status"] == "PENDING"
        application = read_application(world["application"]["id"], world["acquirer"]["id"])
        assert application["public_review_status"] == "HEARING_PENDING"

    def test_06_the_petitioner_withdraws_their_own_petition(self):
        """PRD §3.8: "Withdrawal drives `PENDING → WITHDRAWN`, leaves `extension_days_granted` at 0,
        and applies exactly the same axis fallback as a denial — `PROTEST_PENDING` when
        `unresolved_protest_count` is at least 1 and no other petition is `PENDING`,
        `OPEN_FOR_COMMENT` when that count is 0 and no other petition is `PENDING`."

        Design: Corner/errors/withdrawing_another_commenters_hearing_request_is_forbidden
        """
        world = application_under_review()
        protest = file_substantive_protest(world["period"]["id"])
        petition = request_hearing(world["application"]["id"], protest["id"])

        withdrawn = validate_success(api_client.withdraw_hearing_request(petition["id"], COMMENTER))

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["extension_days_granted"] == 0
        application = read_application(world["application"]["id"], world["acquirer"]["id"])
        assert application["public_review_status"] == "PROTEST_PENDING", (
            "the protest is still unresolved, so the axis falls back to the protest state"
        )
