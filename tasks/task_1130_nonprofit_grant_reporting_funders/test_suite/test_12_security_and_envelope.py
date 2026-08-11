"""Authentication, authorization, funder ownership scoping, segregation of
duties, and the error envelope (PRD §2.1, §2.2, §2.9)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_error_envelope,
    create_expense,
    create_funder,
    create_grant,
    create_match_contribution,
    document_contribution,
    edit_report,
    make_funder_headers,
    make_officer_headers,
    set_clock,
    setup_active_grant,
    start_report,
    submit_report,
    validate_error,
    validate_success,
    build_user_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAuthentication:
    def test_missing_auth_header_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        create_funder(funder_type="STATE")
        resp = api.list_grants(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_officer_cannot_post_expense_forbidden(self, api):
        """PRD §2.1: "Once authenticated, the acting role must appear in the
        endpoint's authorized role list; a role mismatch is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST `/expenses/{id}/post` — "Post a DRAFT expense (poster
        differs from creator)" is authorized for FinanceManager only.

        Design: Corner/rbac/officer_cannot_post_expense_forbidden
        """
        ctx = setup_active_grant()
        expense = create_expense(ctx["grant"]["id"], amount_cents=5000)

        resp = api.post_expense(expense["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_funder_cannot_review_other_funders_grant(self, api):
        """PRD §2.1: "When `X-User-Role` is `Funder`, `X-User-ID` is the `id` of
        the acting `Funder` entity; any funder-scoped action compares the
        target grant's `funder_id` against `X-User-ID`, and a mismatch is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/funder_cannot_review_other_funders_grant
        """
        ctx = setup_active_grant()
        other_funder = create_funder(funder_type="STATE")
        r1 = ctx["reports"][0]
        set_clock("2026-06-15T00:00:00Z")
        start_report(r1["id"])
        edit_report(r1["id"])
        submit_report(r1["id"])

        resp = api.start_review_report(
            r1["id"], make_funder_headers(other_funder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:
    def test_sod_expense_create_then_post_same_user(self, api):
        """PRD §2.9: "Posting an expense requires that the poster differ from
        the expense's `created_by_user_id`; a match is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.9: "The comparisons are by opaque user identifier — they do not
        involve role checks, and two different staff members sharing a role
        still satisfy the rule as long as their `X-User-ID` values differ."

        Design: Corner/rbac/sod_expense_create_then_post_same_user
        """
        ctx = setup_active_grant()
        same_person = make_officer_headers("u-1")
        expense = create_expense(
            ctx["grant"]["id"], created_by=same_person, amount_cents=5000,
        )

        # The same person now wears the FinanceManager hat.
        resp = api.post_expense(
            expense["id"], build_user_headers("u-1", "FinanceManager"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_sod_match_verify_own_documentation(self, api):
        """PRD §2.9: "Verifying a match contribution requires that the verifier
        differ from the contribution's `documented_by_user_id`; again a match
        is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.5: "Verification moves a `DOCUMENTED` contribution to `VERIFIED`
        and is performed by a `FinanceManager`; the verifier must differ from
        the documenter — an acting `X-User-ID` equal to `documented_by_user_id`
        is rejected with `ERR_SEGREGATION_OF_DUTIES` — and on success
        `verified_by_user_id` is set."

        Design: Corner/rbac/sod_match_verify_own_documentation
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        contribution = create_match_contribution(
            gid, contribution_type="CASH", valuation_basis="ACTUAL_COST",
            documented_value_cents=7_000_000,
        )
        document_contribution(
            contribution["id"], documented_by=make_officer_headers("u-9"),
        )

        resp = api.verify_match_contribution(
            contribution["id"], build_user_headers("u-9", "FinanceManager"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        verified = validate_success(api.verify_match_contribution(
            contribution["id"], build_user_headers("fin-2", "FinanceManager"),
        ))
        assert verified["status"] == "VERIFIED"


class TestErrorEnvelope:
    def test_error_envelope_shape_on_404(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: \"error\"", a `data`
        object carrying `error_id` and `message`, and "The `meta` object for
        error responses contains only `api_request_id` and
        `api_request_timestamp`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/error_envelope_shape_on_404
        """
        create_funder(funder_type="STATE")
        resp = api.get_report(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert_error_envelope(resp.json())


class TestUniqueness:
    def test_duplicate_award_number_rejected(self, api):
        """PRD §3.1: "One uniqueness rule guards creation: `award_number` must
        be unique per funder, so two grants from the same funder carrying the
        same award number are rejected with `ERR_DUPLICATE_AWARD_NUMBER`
        (HTTP 409)."

        Design: Corner/validations/duplicate_award_number_rejected
        """
        f1 = create_funder(funder_type="STATE")
        f2 = create_funder(funder_type="FOUNDATION")
        base = {
            "award_number": "AW-DUP",
            "title": "T",
            "award_amount_cents": 500,
            "start_date": "2026-06-01",
            "end_date": "2027-05-31",
            "reporting_frequency": "ANNUAL",
        }
        validate_success(
            api.create_grant({"funder_id": f1["id"], **base}, OFFICER),
            expected_status=201,
        )

        resp = api.create_grant({"funder_id": f1["id"], **base}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AWARD_NUMBER)

        # Same award_number under a different funder is allowed.
        ok = api.create_grant({"funder_id": f2["id"], **base}, OFFICER)
        validate_success(ok, expected_status=201)
