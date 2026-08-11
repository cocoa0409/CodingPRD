"""RBAC corners: exclusive operations and the unauthenticated gate
(PRD 2.1, 4)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    TEST_USERS,
    create_case_payload,
    create_hearing_payload,
    create_landlord_payload,
    create_service_attempt_payload,
    create_tenancy_payload,
    create_unit_payload,
    make_deputy_headers,
    make_landlord_headers,
    make_mediator_headers,
    set_clock,
    setup_case_filed,
    setup_case_hearing_scheduled,
    setup_case_notice_expired,
    prepare_package,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestLandlordCannotReviewPackage:
    """Corner instance: review is CourtClerk-exclusive."""

    def test_landlord_review_forbidden(self, api):
        """PRD 2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with ERR_FORBIDDEN (HTTP 403)";
        the per-endpoint role assignments are listed in §4" — and PRD §4
        assigns the review endpoint to CourtClerk alone.

        Design: Corner/rbac/landlord_cannot_review_package
        """
        ctx = setup_case_notice_expired("CA")
        package = prepare_package(ctx)  # fully paid
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.review_filing_package(package["id"], {"decision": "ACCEPT"}, ll)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestClerkCannotCreateCase:
    """Corner instance: case creation is Landlord-exclusive."""

    def test_clerk_create_case_forbidden(self, api):
        """PRD 2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with ERR_FORBIDDEN (HTTP 403)";
        the per-endpoint role assignments are listed in §4" — and PRD §4
        assigns case creation to Landlord alone.

        Design: Corner/rbac/clerk_cannot_create_case
        """
        landlord = validate_success(api.create_landlord(
            create_landlord_payload(), TEST_USERS["admin_headers"]), 201)
        ll = make_landlord_headers(landlord["id"])
        unit = validate_success(api.create_unit(
            create_unit_payload(landlord["id"], "CA"), ll), 201)
        tenancy = validate_success(api.create_tenancy(
            create_tenancy_payload(unit["id"]), ll), 201)
        resp = api.create_case(
            create_case_payload(tenancy["id"], "NONPAYMENT"),
            TEST_USERS["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestMediatorCannotScheduleHearing:
    """Corner instance: hearing scheduling is CourtClerk-exclusive."""

    def test_mediator_schedule_forbidden(self, api):
        """PRD 2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with ERR_FORBIDDEN (HTTP 403);
        the per-endpoint role assignments are listed in §4" — and PRD §4
        assigns hearing scheduling to CourtClerk alone.

        Design: Corner/rbac/mediator_cannot_schedule_hearing
        """
        ctx = setup_case_filed("CA")
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(),
            make_mediator_headers("med-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestDeputyCanServeButNotConclude:
    """Corner instance: SheriffDeputy shares service recording with
    ProcessServer but may not conclude a hearing."""

    def test_deputy_serves_but_conclude_forbidden(self, api):
        """PRD 2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with ERR_FORBIDDEN (HTTP 403);
        the per-endpoint role assignments are listed in §4" — PRD §4 lists
        service-attempt recording for ProcessServer and SheriffDeputy but
        hearing conclusion for CourtClerk alone.

        Design: Corner/rbac/deputy_can_serve_but_not_conclude
        """
        ctx = setup_case_filed("CA")
        set_clock("2026-06-01T11:00:00Z")
        dep = make_deputy_headers("dep-5")
        attempt = validate_success(api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="Dee A",
                                           served_at="2026-06-01T10:00:00Z"),
            dep), 201)
        assert attempt["result"] == "SERVED"

        # The deputy-served case proceeds to a hearing (clerk), then the
        # deputy's conclude attempt is rejected.
        from test_helpers import schedule_hearing

        hearing = schedule_hearing(ctx)
        resp = api.conclude_hearing(hearing["id"], {}, dep)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestMissingAuthHeadersReturnsUnauthenticated:
    """Corner instance: no X-User-Role/X-User-ID headers -> 401."""

    def test_missing_headers_rejected(self, api):
        """PRD 2.1: "A request with missing headers, or whose role is not one
        of these declared values, is rejected with ERR_UNAUTHENTICATED
        (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        landlord = validate_success(api.create_landlord(
            create_landlord_payload(), TEST_USERS["admin_headers"]), 201)
        ll = make_landlord_headers(landlord["id"])
        unit = validate_success(api.create_unit(
            create_unit_payload(landlord["id"], "CA"), ll), 201)
        tenancy = validate_success(api.create_tenancy(
            create_tenancy_payload(unit["id"]), ll), 201)
        resp = api.create_case(
            create_case_payload(tenancy["id"], "NONPAYMENT"),
            headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
