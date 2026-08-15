"""Authentication context, validation ordering, and role-based denials."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_licensee,
    create_split_set,
    create_statement,
    create_work,
    create_work_payload,
    create_writer,
    list_split_lines,
    make_writer_headers,
    statement_line,
    submit_split_set,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST
from test_helpers.factories import create_advance_payload


class TestAuthContext:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if the value of `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_writers(headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_unknown_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing, or if the value of `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.1: "The system recognizes exactly six roles, spelled as follows: `PublisherAdmin`, `CopyrightSpecialist`, `RoyaltyAnalyst`, `FinanceManager`, `Auditor`, and `Writer`."

        Design: Corner/validations/unknown_role_header_rejected
        """
        resp = api.list_writers(build_user_headers("test-anon-1", "Anonymous"))
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_existence_check_precedes_state_on_missing_id(self, api):
        """PRD §2.8: "Path identifiers are validated left to right, and the first identifier that does not correspond to an existing resource ends the request with `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.8: "3. **Existence** — every path and body reference resolves, left to right, else `ERR_NOT_FOUND`."

        Design: Corner/validations/existence_check_precedes_state_on_missing_id
        """
        from test_helpers.fixtures import COPYRIGHT
        resp = api.submit_society_registration(NON_EXISTENT_UUID, COPYRIGHT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSplitLineOwnership:
    def test_writer_cannot_confirm_others_line(self, api):
        """PRD §2.1: "a Writer may confirm or reject only their own WRITER split lines (where the line's `writer_id` equals `X-User-ID`), and a Writer may read only their own earnings summary (where the addressed writer's `id` equals `X-User-ID`)."
        PRD §2.1: "a Writer touching a split line that is not their own WRITER line is instead rejected with `ERR_SPLIT_LINE_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/writer_cannot_confirm_others_line
        """
        w1 = create_writer(legal_name="W1")
        w2 = create_writer(legal_name="W2", pro_affiliation="BMI")
        work = create_work(title="Ownership Song")
        split_set = create_split_set(work["id"], [(w1["id"], 10000)])
        submit_split_set(split_set["id"])
        line = list_split_lines(split_set["id"])[0]
        assert line["participant_type"] == "WRITER"

        resp = api.confirm_split_line(line["id"], make_writer_headers(w2["id"]))
        validate_error(resp, ApiErrorId.ERR_SPLIT_LINE_OWNERSHIP_MISMATCH)

    def test_publisher_admin_cannot_confirm_writer_line(self, api):
        """PRD §3.3: "a `WRITER` line may be confirmed or rejected only by a `Writer` caller whose `X-User-ID` equals the line's `writer_id` — a `PublisherAdmin` may not touch a `WRITER` line at all — while a `PUBLISHER` line may be confirmed or rejected only by a `PublisherAdmin`. Any breach is rejected with `ERR_SPLIT_LINE_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/publisher_admin_cannot_confirm_writer_line
        """
        w1 = create_writer(legal_name="W1")
        work = create_work(title="Admin Line Song")
        split_set = create_split_set(work["id"], [(w1["id"], 10000)])
        submit_split_set(split_set["id"])
        line = list_split_lines(split_set["id"])[0]

        resp = api.confirm_split_line(line["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SPLIT_LINE_OWNERSHIP_MISMATCH)


class TestExclusiveOperations:
    def test_royalty_analyst_cannot_approve_advance(self, api):
        """PRD §2.1: "An attempt to perform an action outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)".
        PRD §3.7: "From there a `FinanceManager` drives the money. Approval moves the advance from `DRAFT` to `APPROVED`, but only while the writer is `ACTIVE` — approving for a `SUSPENDED` writer is rejected with `ERR_WRITER_NOT_ACTIVE`, and approval from any state other than `DRAFT` is `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/rbac/royalty_analyst_cannot_approve_advance
        """
        writer = create_writer(legal_name="W")
        payload = create_advance_payload(writer["id"], writer["version"], 1000)
        advance = validate_success(api.create_advance(payload, ADMIN), 201)

        resp = api.approve_advance(advance["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_publisher_admin_cannot_finalize_statement(self, api):
        """PRD §2.1: "An attempt to perform an action outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)".
        PRD §3.5: "Finalization — a `RoyaltyAnalyst` action from `ALLOCATED` only — locks the money."

        Design: Corner/rbac/publisher_admin_cannot_finalize_statement
        """
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "X", 100)],
            100,
            income_type="SYNC")
        assert statement["status"] == "RECEIVED"

        resp = api.finalize_royalty_statement(statement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_writer_cannot_create_works(self, api):
        """PRD §2.1: "An attempt to perform an action outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)".
        PRD §3.1: "A **Work** is created by a `PublisherAdmin` with a primary `title` and the `grant_date` of the original publishing grant — the date from which termination windows are projected decades later."

        Design: Corner/rbac/writer_cannot_create_works
        """
        writer = create_writer(legal_name="W")
        resp = api.create_work(
            create_work_payload(title="Nope"),
            make_writer_headers(writer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_writer_earnings_summary_other_forbidden(self, api):
        """PRD §3.1: "A `PublisherAdmin`, `RoyaltyAnalyst`, or `FinanceManager` may read any writer's summary; a `Writer` caller may read only their own — when the addressed writer's `id` does not equal `X-User-ID`, the read is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/writer_earnings_summary_other_forbidden
        """
        w1 = create_writer(legal_name="W1")
        w2 = create_writer(legal_name="W2", pro_affiliation="BMI")

        resp = api.get_earnings_summary(w2["id"], make_writer_headers(w1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        own = validate_success(
            api.get_earnings_summary(w1["id"], make_writer_headers(w1["id"])))
        assert own["writer_id"] == w1["id"]
