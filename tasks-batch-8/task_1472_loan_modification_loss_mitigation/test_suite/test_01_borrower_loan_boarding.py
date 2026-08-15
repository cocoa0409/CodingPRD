"""Borrower/loan boarding, initial states, and resource reachability."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_application,
    assert_borrower,
    assert_loan,
    assert_timestamp_instant,
    board_loan,
    create_application_payload,
    create_loan_payload,
    get_application,
    get_success_data,
    is_valid_uuid,
    make_borrower,
    make_borrower_headers,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)
class TestBorrowerCreation:
    def test_borrower_defaults_and_common_fields(self, api, admin_headers):
        """PRD §3.1: "A `ServicingAdmin` seeds the book by creating a `Borrower`
        with `full_name`, `email`, and optionally `mailing_address`. The borrower's
        `status` is `ACTIVE` — borrower deactivation is out of scope and no other
        borrower state exists."
        PRD §2.4: "Every persisted entity carries `id` as a server-minted UUID with
        no type prefix, `created_at` as an ISO 8601 UTC timestamp with three
        fractional digits, and — for entities with full common fields — `updated_at`
        (same timestamp format) and `version` (an integer that increments on every
        mutation)."
        PRD §2.4: "Before any such call, the clock starts at exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/entities/borrower_creation_defaults_and_common_fields
        """
        res = api.create_borrower(
            {"full_name": "Default Dan", "email": "dan@x.com"}, admin_headers
        )
        borrower = validate_success(res, 201)
        assert_borrower(borrower)
        assert borrower["status"] == "ACTIVE"
        assert borrower["mailing_address"] is None
        assert is_valid_uuid(borrower["id"])
        assert isinstance(borrower["version"], int)
        assert_timestamp_instant(borrower["created_at"], "2026-08-01T00:00:00Z")


class TestLoanBoarding:
    def test_loan_computed_fields_and_initial_state(self, api, admin_headers):
        """PRD §3.1: "First, `current_pi_cents`, the amortized monthly
        principal-and-interest implied by `unpaid_principal_balance_cents`,
        `interest_rate_bp`, and `remaining_term_months` under a standard annuity at
        the note rate, rounded half-up to whole cents. Second, `workout_status`:
        when `delinquency_days` is greater than zero the loan enters `DELINQUENT`;
        otherwise it enters `PERFORMING`."
        PRD §3.1: "A loan also carries `suspense_cents` (unapplied trial payments,
        initially zero) and `deferred_principal_cents` (non-interest-bearing
        forborne principal, initially zero)"
        PRD §3.9: "A loan's `foreclosure_status` is a computed mirror of its latest
        non-`CANCELLED` `ForeclosureCase`: `NONE` when no active case exists"

        Design: Corner/entities/loan_creation_computed_fields_and_initial_state
        """
        borrower = make_borrower(full_name="Eve E", email="eve@x.com")
        loan = get_success_data(
            api.create_loan(
                create_loan_payload(
                    borrower["id"],
                    loan_number="LN-ENT1A",
                    arrears_cents=1_200_000,
                    escrow_balance_cents=30_000,
                    escrow_monthly_cents=30_000,
                    delinquency_days=150,
                ),
                admin_headers,
            )
        )
        assert_loan(loan)
        assert loan["current_pi_cents"] == 143_286
        assert loan["workout_status"] == "DELINQUENT"
        assert loan["foreclosure_status"] == "NONE"
        assert loan["suspense_cents"] == 0
        assert loan["deferred_principal_cents"] == 0

    def test_loan_input_defaults_and_performing_state(self, api, admin_headers):
        """PRD §3.1: "Three fields default to zero when omitted: `arrears_cents`
        (accrued delinquent arrears — principal-and-interest plus escrow plus
        fees), `escrow_balance_cents`, and `escrow_monthly_cents`."
        PRD §3.1: "Second, `workout_status`: when `delinquency_days` is greater
        than zero the loan enters `DELINQUENT`; otherwise it enters `PERFORMING`."

        Design: Corner/entities/loan_creation_computed_fields_and_initial_state
        """
        borrower = make_borrower(full_name="Eve E2", email="eve2@x.com")
        loan = get_success_data(
            api.create_loan(
                create_loan_payload(borrower["id"], loan_number="LN-ENT1B"),
                admin_headers,
            )
        )
        assert loan["workout_status"] == "PERFORMING"
        assert loan["arrears_cents"] == 0
        assert loan["escrow_balance_cents"] == 0
        assert loan["escrow_monthly_cents"] == 0

    def test_get_loan_not_found(self, api, admin_headers):
        """PRD §2.8: "Parameterized paths are validated left-to-right. For
        example, fetching a document under an application resolves the loan id
        first (if present in the path), then the application id, then the
        document id — each miss returning its own 404 (`ERR_LOAN_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, ...)".

        Design: Corner/entities/loan_get_not_found_returns_404
        """
        res = api.get_loan(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_LOAN_NOT_FOUND, expected_status=404)


class TestApplicationIntake:
    def test_application_initial_state_and_checklist(self, api, admin_headers):
        """PRD §3.2: "On success the application is created in `SUBMITTED` with
        `acknowledgement_due_at` set to its `created_at` plus five days."
        PRD §3.3: "`outstanding_doc_categories` is the subset of {`INCOME_PROOF`,
        `HARDSHIP_AFFIDAVIT`, `BANK_STATEMENT`} lacking an `ACCEPTED`,
        non-`SUPERSEDED` document."

        Design: Corner/entities/application_initial_state_and_computed_checklist
        """
        borrower = make_borrower(full_name="Fay F", email="fay@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-ENT2", delinquency_days=150)
        app = submit_application(
            loan, borrower["id"], hardship_type="DISASTER", stated_income=300_000
        )
        assert_application(app)
        assert app["status"] == "SUBMITTED"
        assert sorted(app["outstanding_doc_categories"]) == sorted(
            ["INCOME_PROOF", "HARDSHIP_AFFIDAVIT", "BANK_STATEMENT"]
        )
        assert app["verified_monthly_income_cents"] == 0
        assert app["completed_at"] is None
        assert_timestamp_instant(
            app["acknowledgement_due_at"], "2026-08-06T00:00:00Z"
        )

    def test_children_reachable_from_parents(self, api, admin_headers):
        """PRD §3.3: "the same field ties waterfall evaluations, trial plans,
        modifications, and denial notices back to their owning application, and
        `loan_id` ties applications, foreclosure cases, and escrow analyses back
        to their loan."
        PRD §4: GET /loans/{id}/applications "List applications for a loan";
        GET /loans "List loans with pagination".

        Design: Corner/entities/fk_reverse_reachability_subresource_and_filtered_list
        """
        borrower = make_borrower(full_name="Hal H", email="hal@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-ENT4", delinquency_days=150)
        app = submit_application(
            loan, borrower["id"], hardship_type="OTHER", stated_income=100_000
        )

        sub = get_success_data(api.list_loan_applications(loan["id"], admin_headers))
        assert any(a["id"] == app["id"] for a in sub), (
            "application must be discoverable under its parent loan"
        )

        loans, meta = validate_paginated(api.list_loans(admin_headers))
        assert any(l["id"] == loan["id"] for l in loans), (
            "loan must be discoverable via the list endpoint"
        )

    def test_acknowledge_twice_rejected(self, api, agent_headers):
        """PRD §3.3: "A `LossMitAgent` acknowledges a `SUBMITTED` application,
        moving it to `ACKNOWLEDGED` and stamping `acknowledged_at`.
        Acknowledging from any other state is rejected with
        `ERR_APPLICATION_STATE_INVALID`."

        Design: Corner/state_machines/acknowledge_twice_rejected_invalid_transition
        """
        borrower = make_borrower(full_name="Ida I", email="ida@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-SM1", delinquency_days=150)
        app = submit_application(
            loan, borrower["id"], hardship_type="MEDICAL", stated_income=100_000
        )
        first = validate_success(api.acknowledge_application(app["id"], agent_headers), 200)
        assert first["status"] == "ACKNOWLEDGED"
        assert first["acknowledged_at"] is not None

        res = api.acknowledge_application(app["id"], agent_headers)
        validate_error(res, ApiErrorId.ERR_APPLICATION_STATE_INVALID, expected_status=409)
        after = get_application(app["id"])
        assert after["status"] == "ACKNOWLEDGED"
        assert after["acknowledged_at"] == first["acknowledged_at"]
