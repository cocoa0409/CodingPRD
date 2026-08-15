"""Envelope conventions, validation priority, RBAC boundaries, and OCC rules."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    OPS,
    UW,
    ApiErrorId,
    acknowledge,
    assert_version_incremented,
    board_loan,
    create_application_payload,
    create_program_option_payload,
    create_std_mod_program,
    get_application,
    get_loan,
    get_success_data,
    is_iso8601_timestamp,
    make_borrower,
    make_borrower_headers,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthenticationAndShapePriority:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "Every request carries two HTTP headers: `X-User-ID` (the
        acting principal) and `X-User-Role` (one of the declared roles). A
        request missing either header, or carrying an `X-User-Role` that is not
        one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/evaluation_missing_auth_headers_returns_401
        """
        borrower = make_borrower(full_name="Noah N", email="noah@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-VAL1", delinquency_days=150)
        app = submit_application(
            loan, borrower["id"], hardship_type="OTHER", stated_income=100_000
        )
        # The request is sent WITHOUT the X-User-ID / X-User-Role headers.
        res = api.acknowledge_application(app["id"], headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_request_shape_error_precedes_existence(self, api):
        """PRD §2.7: "When multiple validation rules could fire on a single
        request, the server evaluates them in this fixed priority order,
        returning the first failure:" — "3. **Request shape** — required fields
        present, enum members valid, integer types well-formed, else
        `ERR_VALIDATION`." precedes "4. **Path existence** — path-template
        resources resolved left-to-right ...".

        Design: Corner/validations/request_shape_error_precedes_existence
        """
        borrower = make_borrower(full_name="Olga O", email="olga@x.com")
        # The loan id does not exist AND the body omits required hardship_type.
        res = api.create_application(
            NON_EXISTENT_UUID,
            {"expected_loan_version": 1, "stated_monthly_income_cents": 100_000},
            make_borrower_headers(borrower["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_nested_parent_not_found_returns_typed_404(self, api):
        """PRD §2.8: "Parameterized paths are validated left-to-right. For
        example, fetching a document under an application resolves the loan id
        first (if present in the path), then the application id, then the
        document id — each miss returning its own 404 (`ERR_LOAN_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, ...)".

        Design: Corner/validations/nested_parent_not_found_returns_typed_404
        """
        borrower = make_borrower(full_name="Pete P", email="pete@x.com")
        res = api.submit_document(
            NON_EXISTENT_UUID,
            {"doc_type": "BANK_STATEMENT"},
            make_borrower_headers(borrower["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND, expected_status=404)


class TestProgramConfiguration:
    def test_program_rank_duplicate_rejected(self, api, admin_headers):
        """PRD §3.5: "`waterfall_rank` (evaluation order, unique across all
        programs — a duplicate submission is rejected with
        `ERR_PROGRAM_RANK_DUPLICATE`)".

        Design: Corner/validations/program_rank_duplicate_rejected
        """
        create_std_mod_program()  # STD_MOD at rank 1
        res = api.create_program_option(
            create_program_option_payload(
                code="FLEX_MOD", waterfall_rank=1, target_dti_bp=2500,
                rate_floor_bp=300, max_term_months=360,
                max_forbearance_pct_bp=2000,
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_PROGRAM_RANK_DUPLICATE, expected_status=409)

    def test_borrower_cannot_create_program_option(self, api, admin_headers):
        """PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: POST /program-options — "ServicingAdmin".

        Design: Corner/rbac/borrower_cannot_create_program_option
        """
        borrower = make_borrower(full_name="Ada A", email="ada@x.com")
        res = api.create_program_option(
            create_program_option_payload(code="HACK", waterfall_rank=9),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        data, meta = validate_paginated(api.list_program_options(admin_headers))
        assert meta["total_count"] == 0, "no program may be created by a Borrower"


class TestBorrowerOwnership:
    def test_borrower_cannot_touch_foreign_borrower_resources(self, api):
        """PRD §2.1: "`Borrower` — the mortgagor. `X-User-ID` **is** the `id` of
        the acting `Borrower` entity; any resource chained through a loan
        (applications, notices, plans, payments, modification signing, appeals)
        resolves to a loan whose `borrower_id` must equal the caller's
        `X-User-ID`, otherwise the request is rejected with
        `ERR_BORROWER_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/borrower_cannot_touch_foreign_borrower_resources
        """
        owner = make_borrower(full_name="Eli E", email="eli@x.com")
        stranger = make_borrower(full_name="Eve F", email="evef@x.com")
        loan = board_loan(owner["id"], loan_number="LN-RBAC5", delinquency_days=150)
        app = submit_application(
            loan, owner["id"], hardship_type="MEDICAL", stated_income=100_000
        )
        acknowledge(app["id"])
        res = api.submit_document(
            app["id"],
            {"doc_type": "BANK_STATEMENT"},
            make_borrower_headers(stranger["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BORROWER_OWNERSHIP, expected_status=403)
        docs = get_success_data(api.list_documents(app["id"], OPS))
        assert docs == [], "no document may be created for a foreign borrower"


class TestEnvelopesAndPagination:
    def test_list_pagination_defaults_and_envelope(self, api, admin_headers):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. `limit` defaults to 10, is clamped to a minimum of 1 and a
        maximum of 100; `offset` defaults to 0. List responses sort by
        `created_at` ascending. The `meta` block of a list response includes
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_defaults_envelope_and_filtering
        """
        create_std_mod_program()
        get_success_data(api.create_program_option(
            create_program_option_payload(
                code="FLEX_MOD", waterfall_rank=2, target_dti_bp=2500,
                rate_floor_bp=300, max_term_months=360,
                max_forbearance_pct_bp=2000,
            ), admin_headers))
        p3 = get_success_data(api.create_program_option(
            create_program_option_payload(
                code="LEGACY_MOD", waterfall_rank=3, target_dti_bp=3600,
                rate_floor_bp=400, max_term_months=360,
                max_forbearance_pct_bp=1000,
            ), admin_headers))
        get_success_data(api.retire_program_option(p3["id"], admin_headers))

        body = api.list_program_options(admin_headers)
        data, meta = validate_paginated(body)
        assert body.json()["response_type"] == "array"
        assert isinstance(body.json()["meta"]["api_request_id"], str)
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_program_options(admin_headers, params={"limit": 2})
        )
        assert len(data2) == 2
        assert meta2["has_more"] is True

        data3, meta3 = validate_paginated(
            api.list_program_options(admin_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data3) == 1
        assert meta3["has_more"] is False

    def test_error_envelope_exact_shape(self, api, ops_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error. The
        `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_exact_shape
        """
        res = api.get_escrow_analysis(NON_EXISTENT_UUID, ops_headers)
        assert res.status_code == 404
        body = res.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert body["data"]["error_id"] == "ERR_ESCROW_ANALYSIS_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestOptimisticConcurrency:
    def test_stale_loan_version_rejected_on_application_create(self, api):
        """PRD §2.5: "Submitting a loss-mitigation application (the
        create-application endpoint under a loan) requires
        `expected_loan_version`, matched against the loan's current `version`. A
        mismatch is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412)."
        PRD §3.2: "The submission also bumps the loan's `version` by one".

        Design: Corner/complexity_layers/occ_stale_loan_version_on_application_create
        """
        borrower = make_borrower(full_name="Hugo H", email="hugo@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-OCC1", delinquency_days=150)
        stale_version = loan["version"]
        first = submit_application(
            loan, borrower["id"], hardship_type="MEDICAL", stated_income=100_000
        )
        # The first create advanced Loan.version; replaying the stale view fails.
        res = api.create_application(
            loan["id"],
            create_application_payload(
                expected_loan_version=stale_version,
                hardship_type="DISASTER", stated_monthly_income_cents=200_000,
            ),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STALE_LOAN_VERSION, expected_status=412)
        apps = get_success_data(api.list_loan_applications(loan["id"], OPS))
        assert len(apps) == 1
        assert apps[0]["id"] == first["id"]
        assert apps[0]["status"] == "SUBMITTED"

    def test_correct_version_supersede_succeeds(self, api):
        """PRD §3.2: "Supersession is implicit: if the loan already has a
        non-terminal application, submitting a new one auto-withdraws the old
        one. The superseded application lands in `WITHDRAWN` with
        `superseded_by_application_id` set to the new application's id."
        PRD §3.2: "The submission also bumps the loan's `version` by one and
        transitions the loan's `workout_status` from `DELINQUENT` to
        `LOSS_MIT_REVIEW`."

        Design: Corner/complexity_layers/occ_correct_version_supersede_succeeds
        """
        borrower = make_borrower(full_name="Juan J", email="juan@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-OCC3", delinquency_days=150)
        first = submit_application(
            loan, borrower["id"], hardship_type="MEDICAL", stated_income=100_000
        )
        current = get_loan(loan["id"])
        res = api.create_application(
            loan["id"],
            create_application_payload(
                expected_loan_version=current["version"],
                hardship_type="DISASTER", stated_monthly_income_cents=200_000,
            ),
            make_borrower_headers(borrower["id"]),
        )
        second = validate_success(res, 201)
        assert second["status"] == "SUBMITTED"

        old = get_application(first["id"])
        assert old["status"] == "WITHDRAWN"
        assert old["superseded_by_application_id"] == second["id"]

        bumped = get_loan(loan["id"])
        assert_version_incremented(bumped["version"], current["version"], min_increment=1)
