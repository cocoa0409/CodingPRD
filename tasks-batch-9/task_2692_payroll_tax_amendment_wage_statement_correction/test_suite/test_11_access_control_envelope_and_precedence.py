"""Access control, the response envelope and the cross-cutting refusals.

These are the checks that sit above the domain: the header gate, the role gate,
the two identity gates for the entity-backed roles, the per-entity 404 family,
the uniqueness family, the pagination band, the declared envelope, and the case
version assertion that guards an amendment create.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUPLICATE_AGENCY_CODE,
    ERR_DUPLICATE_EMPLOYER_FEIN,
    ERR_DUPLICATE_FILED_RETURN,
    ERR_DUPLICATE_NOTICE_NUMBER,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_IDENTITY_NOT_RESOLVABLE,
    ERR_INVALID_PAGINATION,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_CASE_VERSION,
    ERR_UNAUTHENTICATED,
    NOT_FOUND_BY_COLLECTION,
)
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_error_body_is_minimal,
    assert_pagination,
    assert_response_type,
)
from test_helpers.constants import CANON_CLOCK, MAX_LIMIT, UNKNOWN_CASE_ID, UNKNOWN_ID_TEMPLATE
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    EMPTY_USER_ID_HEADERS,
    NO_HEADERS,
    OFFICER_HEADERS,
    PREPARER_HEADERS,
    make_employee_headers,
    make_employer_rep_headers,
    make_role_headers,
)


UNKNOWN_EMPLOYEE_ID = UNKNOWN_ID_TEMPLATE.format(9902)


def _total(api, list_call, params, headers):
    _, meta = validate_paginated(list_call(params, headers))
    return meta["total_count"]


class TestHeaderAuthentication:
    def test_the_header_gate_answers_401_and_exempts_only_the_clock_setter(self, api):
        """A wholly headerless read and a create whose `X-User-ID` is present but empty are the
        same failure, and it is an authentication failure rather than an authorisation or a
        schema one. The clock setter is the one endpoint that works with no headers at all,
        which is observable in the `created_at` the next write stamps.

        PRD: "If either header is missing or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD: "Authentication and authorization come first, in four steps: header presence (`ERR_UNAUTHENTICATED`), then role recognition and endpoint authorisation (`ERR_FORBIDDEN_ROLE`), then entity-backed identity resolution (`ERR_IDENTITY_NOT_RESOLVABLE`), then ownership scope for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`)."
        PRD: "The logical-clock setter is the single exception to header enforcement: it is available to all seven roles and it does not require the two headers to be present at all."
        PRD: "Every row also carries a `created_at` timestamp: an ISO 8601 UTC instant with exactly three fractional-second digits, stamped from the logical clock described in §2.5."

        Design: Corner/rbac/call_with_missing_x_user_role_header_returns_unauthenticated
        """
        fx.set_clock(api, CANON_CLOCK)

        validate_error(api.list_employers({}, NO_HEADERS), ERR_UNAUTHENTICATED, 401)
        validate_error(
            api.create_employer(f.employer_payload(), EMPTY_USER_ID_HEADERS),
            ERR_UNAUTHENTICATED,
            401,
        )

        assert _total(api, api.list_employers, {}, ADMIN_HEADERS) == 0

        validate_success(api.set_clock("2026-05-01T00:00:00Z", NO_HEADERS))
        employer = validate_success(
            api.create_employer(f.employer_payload(), ADMIN_HEADERS), 201
        )
        assert employer["created_at"] == "2026-05-01T00:00:00.000Z"


class TestRoleAuthorisation:
    def test_an_unauthorised_role_is_refused_before_any_identifier_is_looked_up(self, api):
        """Three creates carry roles the endpoint does not authorise and two of them also carry
        fabricated identifiers that would otherwise be 404s; each answers 403, and an
        undeclared role name is refused by the very same rule. Nothing is written.

        PRD: "If `X-User-Role` is not one of the seven role names declared below, or is a declared role that the addressed endpoint does not authorise, the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD: "Checks are evaluated in this sequence, and the first failure wins."
        PRD: "Existence comes next: path-parameter existence is checked before body foreign-key existence, both yielding the 404 family described in §2.9."

        Design: Corner/rbac/payroll_analyst_creating_an_employer_is_forbidden
        """
        fx.set_clock(api, CANON_CLOCK)

        validate_error(
            api.create_employer(f.employer_payload(), ANALYST_HEADERS), ERR_FORBIDDEN_ROLE, 403
        )
        validate_error(
            api.create_control_remediation(
                f.control_remediation_payload(UNKNOWN_CASE_ID), PREPARER_HEADERS
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.create_statement(
                f.statement_payload(UNKNOWN_CASE_ID, UNKNOWN_EMPLOYEE_ID), ANALYST_HEADERS
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.list_employers({}, make_role_headers("TaxWizard", "u_wizard_one")),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        assert _total(api, api.list_employers, {}, ADMIN_HEADERS) == 0
        assert _total(api, api.list_control_remediations, {}, AUDITOR_HEADERS) == 0
        assert _total(api, api.list_statements, {}, PREPARER_HEADERS) == 0


class TestEntityBackedIdentity:
    def test_an_employer_rep_identity_that_names_no_employer_is_refused_as_unresolvable(
        self, api
    ):
        """For an entity-backed caller the `X-User-ID` is itself a foreign key, so the same
        absent UUID that would be a 404 in the path is a 403 in the header — and the refusal
        arrives even though the employer actually addressed does exist.

        PRD: "For both entity-backed roles, if `X-User-ID` does not name an existing `Employer` row (for `EmployerRep`) or an existing `Employee` row (for `EmployeeSelfService`), the request is rejected with `ERR_IDENTITY_NOT_RESOLVABLE` and HTTP 403."
        PRD: "When `X-User-Role` is `EmployerRep`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` compare the resource's employer foreign-key field to `X-User-ID`."

        Design: Corner/rbac/employer_rep_with_an_unresolvable_identity_is_forbidden
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)

        validate_error(
            api.get_employer(
                employer["id"], make_employer_rep_headers(UNKNOWN_ID_TEMPLATE.format(9903))
            ),
            ERR_IDENTITY_NOT_RESOLVABLE,
            403,
        )

        own = validate_success(
            api.get_employer(employer["id"], make_employer_rep_headers(employer["id"]))
        )
        assert own["id"] == employer["id"]


class TestOwnershipScope:
    def test_the_rep_reads_its_own_chain_and_is_refused_the_sibling_employers(self, api):
        """Ownership follows the row's employer chain, not the endpoint: the very same read is
        200 on the rep's own case and 403 on the neighbour's. An employee reads its own row,
        and a staff caller reads either case, so the restriction is entity-backed only.

        PRD: "If the identity resolves but the addressed row lies outside the caller's own scope — an employer reading another employer's chain, or an employee touching another employee's statement or repayment — the rejection is `ERR_NOT_RESOURCE_OWNER`, also HTTP 403."
        PRD: "When `X-User-Role` is `EmployeeSelfService`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's employee foreign-key field to `X-User-ID`."
        PRD: "An `EmployerRep` may add employees to its own roster and read within its own chain; an `EmployeeSelfService` caller may acknowledge its own corrected statements, agree to its own repayment arrangements, and read its own employee row, statements and repayments."

        Design: Corner/rbac/employer_rep_cannot_read_another_employers_case
        """
        fx.set_clock(api, CANON_CLOCK)
        acme = fx.make_employer(api, deposit_schedule="MONTHLY")
        borealis = fx.make_employer(
            api, legal_name="Borealis Foods", fein="98-7654321", deposit_schedule="MONTHLY"
        )
        agency = fx.make_federal_agency(api)
        acme_case = fx.make_correction_case(api, acme["id"], agency["id"])
        borealis_case = fx.make_correction_case(api, borealis["id"], agency["id"])
        dana = fx.make_employee(api, acme["id"])
        acme_rep = make_employer_rep_headers(acme["id"])

        own = validate_success(api.get_correction_case(acme_case["id"], acme_rep))
        assert own["id"] == acme_case["id"]

        validate_error(
            api.get_correction_case(borealis_case["id"], acme_rep),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )

        self_read = validate_success(
            api.get_employee(dana["id"], make_employee_headers(dana["id"]))
        )
        assert self_read["id"] == dana["id"]

        staff_read = validate_success(
            api.get_correction_case(borealis_case["id"], ANALYST_HEADERS)
        )
        assert staff_read["id"] == borealis_case["id"]


class TestPathParameterNotFound:
    def test_every_collection_names_its_own_entity_in_its_404(self, api):
        """One absent identifier per collection, twelve collections, twelve distinct codes: a
        single shared not-found code would satisfy any one of these probes and fail the set.

        PRD: "Consequently there is no left-to-right path hierarchy to validate: each endpoint carries at most one path parameter, and that parameter must name an existing row of its own entity or the request fails with HTTP 404 carrying the entity-specific code — `ERR_EMPLOYER_NOT_FOUND`, `ERR_TAX_AGENCY_NOT_FOUND`, `ERR_AGENCY_ACCOUNT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_REGISTER_LINE_NOT_FOUND`, `ERR_DEPOSIT_RECORD_NOT_FOUND`, `ERR_FILED_RETURN_NOT_FOUND`, `ERR_CORRECTION_CASE_NOT_FOUND`, `ERR_DISCREPANCY_NOT_FOUND`, `ERR_AMENDED_RETURN_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_WAGE_REPAYMENT_NOT_FOUND`, `ERR_AGENCY_NOTICE_NOT_FOUND` or `ERR_CONTROL_REMEDIATION_NOT_FOUND`."
        PRD: "The path parameter is always named after the entity it addresses."
        PRD: "`PlatformAdmin` is the operations superuser and may perform every declared operation, but it earns no exemption from the segregation-of-duties rules described in §2.8 — an admin who prepared an amendment still cannot sign it."

        Design: Corner/errors/every_path_parameter_not_found_returns_its_entity_specific_error
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)

        collections = (
            "tax-agencies",
            "agency-accounts",
            "employees",
            "payroll-register-lines",
            "deposit-records",
            "filed-returns",
            "discrepancies",
            "amended-returns",
            "corrected-wage-statements",
            "wage-repayments",
            "agency-notices",
            "control-remediations",
        )
        for index, collection in enumerate(collections, start=9001):
            validate_error(
                api.get_by_collection(
                    collection, UNKNOWN_ID_TEMPLATE.format(index), ADMIN_HEADERS
                ),
                NOT_FOUND_BY_COLLECTION[collection],
                404,
            )

        survivor = validate_success(api.get_employer(employer["id"], ADMIN_HEADERS))
        assert survivor["id"] == employer["id"]
        assert _total(api, api.list_employers, {}, ADMIN_HEADERS) == 1


class TestNaturalKeyUniqueness:
    def test_each_uniqueness_scope_answers_with_its_own_conflict_code(self, api):
        """Four scopes, four codes: the employer number and the agency code are global, the
        filed-return key is the five-part period-and-form tuple, and the notice number is
        unique only inside its issuing agency — which is why the same number is accepted
        again on a different agency.

        PRD: "That number is globally unique across all employers; a second employer claiming a `fein` already in use is refused with `ERR_DUPLICATE_EMPLOYER_FEIN`."
        PRD: "Its `agency_code` is a globally unique short identifier of between 3 and 16 characters drawn from upper-case letters, digits and hyphens; a duplicate is refused with `ERR_DUPLICATE_AGENCY_CODE`."
        PRD: "At most one return may exist for a given employer, agency, tax year, quarter and `form_code` combination; a duplicate is refused with `ERR_DUPLICATE_FILED_RETURN`."
        PRD: "`notice_number` must be unique within its issuing agency, and a duplicate is refused with `ERR_DUPLICATE_NOTICE_NUMBER`."

        Design: Corner/errors/duplicate_natural_keys_are_rejected
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api, deposit_schedule="MONTHLY")
        federal = fx.make_federal_agency(api)
        state = fx.make_state_agency(api)
        fx.make_filed_return(api, employer["id"], federal["id"])
        validate_success(
            api.create_agency_notice(
                f.agency_notice_payload(
                    employer["id"], federal["id"], notice_number="CP-136-01"
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        validate_error(
            api.create_employer(
                f.employer_payload(legal_name="Acme Holdings", authorization_limit_cents=100000),
                ADMIN_HEADERS,
            ),
            ERR_DUPLICATE_EMPLOYER_FEIN,
            409,
        )
        validate_error(
            api.create_tax_agency(
                f.federal_agency_payload(interest_rate_bps_annual=700), ADMIN_HEADERS
            ),
            ERR_DUPLICATE_AGENCY_CODE,
            409,
        )
        validate_error(
            api.create_filed_return(
                f.filed_return_payload(
                    employer["id"],
                    federal["id"],
                    filed_at="2025-05-01T00:00:00Z",
                    reported_taxable_wage_cents=1,
                    reported_withheld_cents=1,
                ),
                PREPARER_HEADERS,
            ),
            ERR_DUPLICATE_FILED_RETURN,
            409,
        )
        validate_error(
            api.create_agency_notice(
                f.agency_notice_payload(
                    employer["id"],
                    federal["id"],
                    notice_number="CP-136-01",
                    quarter=2,
                    response_due_date="2026-07-31",
                ),
                OFFICER_HEADERS,
            ),
            ERR_DUPLICATE_NOTICE_NUMBER,
            409,
        )

        elsewhere = validate_success(
            api.create_agency_notice(
                f.agency_notice_payload(
                    employer["id"],
                    state["id"],
                    notice_number="CP-136-01",
                    response_due_date="2026-07-31",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert elsewhere["agency_id"] == state["id"]
        assert elsewhere["notice_number"] == "CP-136-01"
        assert _total(api, api.list_employers, {"fein": "12-3456789"}, ADMIN_HEADERS) == 1


class TestPaginationBounds:
    def test_the_inclusive_upper_bound_passes_and_everything_outside_the_band_is_refused(
        self, api
    ):
        """The band is 1 through 100 inclusive, so 100 is a success that echoes itself back
        while 101 and 0 are both refusals, and a negative offset fails on its own account.
        No refusal returns a partial page.

        PRD: "`limit` defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
        PRD: "`offset` defaults to 0 and may not be negative."
        PRD: "A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, or either value supplied as something other than an integer, is rejected with `ERR_INVALID_PAGINATION` and HTTP 400."

        Design: Corner/errors/list_with_limit_over_max_returns_invalid_pagination
        """
        fx.set_clock(api, CANON_CLOCK)
        fx.make_employer(api)

        rows, meta = validate_paginated(api.list_employers({"limit": MAX_LIMIT}, ADMIN_HEADERS))
        assert_pagination(meta, limit=MAX_LIMIT, offset=0, total_count=1, has_more=False)
        assert len(rows) == 1

        for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
            error_payload = validate_error(
                api.list_employers(params, ADMIN_HEADERS), ERR_INVALID_PAGINATION, 400
            )
            assert isinstance(error_payload, dict), params
            assert set(error_payload) == {"error_id", "message"}, params


class TestResponseEnvelope:
    def test_object_list_and_error_bodies_each_declare_their_own_shape(self, api):
        """The same resource read three ways: as one object, as a page of objects, and as a
        failure. All three carry the request identifiers; only the list carries the four
        pagination fields; and the failure collapses its payload to two keys.

        PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
        PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/success_and_error_responses_use_the_declared_envelope
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)

        single = api.get_employer(employer["id"], ADMIN_HEADERS)
        assert single.status_code == 200
        assert_response_type(single, "object")
        assert_envelope_meta(single)
        single_body = single.json()
        assert single_body["meta"]["api_request_id"].startswith("req_")
        assert single_body["data"]["id"] == employer["id"]

        listing = api.list_employers({}, ADMIN_HEADERS)
        assert listing.status_code == 200
        assert_response_type(listing, "array")
        assert_envelope_meta(listing)
        listing_body = listing.json()
        assert isinstance(listing_body["data"], list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in listing_body["meta"], field

        failure = api.get_employer(UNKNOWN_ID_TEMPLATE.format(9999), ADMIN_HEADERS)
        validate_error(failure, ERR_EMPLOYER_NOT_FOUND, 404)
        assert_response_type(failure, "error")
        assert_envelope_meta(failure)
        assert_error_body_is_minimal(failure)
        failure_body = failure.json()
        assert set(failure_body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert failure_body["data"]["message"].strip()


class TestCaseVersionGuard:
    def test_a_version_read_before_reconciliation_is_already_stale_when_the_draft_opens(
        self, api
    ):
        """The guarded write is a child create, and the parent moved behind the caller's back:
        reconciliation and each categorisation bumped the case, so the version captured at
        creation is refused, and only the re-read value is accepted — after which it too is
        spent, because opening the draft bumps the case again.

        PRD: "Creating an amended return requires a field named `expected_correction_case_version`, carrying the `version` of the `CorrectionCase` the client last read."
        PRD: "If the value does not equal the case's current `version`, the create is rejected with `ERR_STALE_CASE_VERSION` and HTTP 412."
        PRD: "Creating the draft increments the *case's* `version` by 1, which is why two drafts cannot be created against one observed case version in succession."

        Design: Corner/cross-cutting complexity layers/stale_case_version_blocks_amended_return_creation
        """
        ctx = fx.federal_scenario(api)
        stale_version = ctx["case"]["version"]
        validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))
        fx.categorize_all(api, fx.discrepancies_by_detected_category(api, ctx["case_id"]))
        fresh_version = fx.case_version(api, ctx["case_id"])
        assert fresh_version > stale_version

        validate_error(
            api.create_amended_return(
                f.amended_return_payload(ctx["case_id"], stale_version), PREPARER_HEADERS
            ),
            ERR_STALE_CASE_VERSION,
            412,
        )
        assert _total(
            api, api.list_amended_returns, {"correction_case_id": ctx["case_id"]}, PREPARER_HEADERS
        ) == 0

        draft = validate_success(
            api.create_amended_return(
                f.amended_return_payload(ctx["case_id"], fresh_version), PREPARER_HEADERS
            ),
            201,
        )

        assert draft["status"] == "DRAFT"
        assert _total(
            api, api.list_amended_returns, {"correction_case_id": ctx["case_id"]}, PREPARER_HEADERS
        ) == 1
        assert fx.case_version(api, ctx["case_id"]) > fresh_version
