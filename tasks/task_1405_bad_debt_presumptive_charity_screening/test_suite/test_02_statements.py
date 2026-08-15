"""Statement cycle: due-date computation, count accounting, invalid markings,
statement eligibility, immediate consistency, and version increments."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_statement,
    create_account,
    issue_statements,
    post_recovery,
    read_account,
    setup_posted_bad_debt_writeoff,
    validate_error,
    validate_success,
)

COLLECTOR = TEST_USERS["collector_headers"]


class TestStatementCycle:
    def test_statement_due_date_computed_from_cycle(self, api):
        """PRD §3.2: "Its `due_date` is the `guarantor_liability_date` plus
        thirty days multiplied by the `statement_index`, so statement one is due
        thirty days after liability began, statement two after sixty, and so
        on."
        PRD §3.2: "The statement captures `balance_at_issue_cents` as a snapshot
        of the account's `current_balance_cents` at issuance, and its
        `issued_at` is stamped from the logical clock."

        Liability date 2026-01-10 + 1 * 30 days = due date 2026-02-09.

        Design: Corner/entities/statement_due_date_computed_from_cycle
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-01-10",
            patient_mrn="MRN-K3", patient_name="K3")
        resp = api.issue_statement(account["id"], COLLECTOR)
        statement = validate_success(resp, 201)
        assert_statement(statement)
        assert statement["statement_index"] == 1
        assert statement["due_date"] == "2026-02-09"
        assert statement["status"] == "SENT"
        assert statement["balance_at_issue_cents"] == 100000

    def test_statement_issuance_immediately_visible(self, api):
        """PRD §3.2: "Although the statement lifecycle formally begins in
        `DRAFT`, creation issues the statement immediately: the persisted and
        observable status is always `SENT`, and `DRAFT` is never returned by the
        API."
        PRD §3.2: "the first statement is index 1."
        PRD §3.2: "Issuing a statement increments the account's
        `statements_sent_count` and bumps the account's `version`."

        Design: Corner/consistency_model/mutation_visible_in_same_request_response
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-T1", patient_name="T1")
        statement = validate_success(
            api.issue_statement(account["id"], COLLECTOR), 201)
        assert statement["status"] == "SENT"
        assert statement["statement_index"] == 1
        fetched = validate_success(api.get_account(account["id"], COLLECTOR), 200)
        assert fetched["statements_sent_count"] == 1

    def test_returned_statement_decrements_count(self, api):
        """PRD §3.2: "the account's `statements_sent_count` is decremented by
        one, because the count is defined as the number of the account's
        statements currently in `SENT` or `DELIVERED` status — a returned
        statement no longer counts toward the statement-cycle prerequisites that
        gate agency placement and write-off — and the account's `version` is
        incremented."

        Design: Corner/calculations/statement_returned_undeliverable_decrements_count
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-M1", patient_name="M1")
        first, _second = issue_statements(account["id"], count=2)
        assert read_account(account["id"])["statements_sent_count"] == 2

        validate_success(api.mark_statement_returned(first["id"], COLLECTOR), 200)
        after = read_account(account["id"])
        assert after["statements_sent_count"] == 1

    def test_mark_delivered_after_returned_rejected(self, api):
        """PRD §3.2: "A `Collector` may subsequently mark a `SENT` statement as
        delivered, moving it to `DELIVERED`, or as returned, moving it to
        `RETURNED_UNDELIVERABLE`; either marking against a statement not
        currently `SENT` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/statement_mark_delivered_from_returned_is_invalid
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-L1", patient_name="L1")
        statement = issue_statements(account["id"], count=1)[0]
        validate_success(api.mark_statement_returned(statement["id"], COLLECTOR), 200)

        resp = api.mark_statement_delivered(statement["id"], COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        unchanged = validate_success(api.get_statement(statement["id"], COLLECTOR), 200)
        assert unchanged["status"] == "RETURNED_UNDELIVERABLE"


class TestStatementEligibility:
    def test_statement_on_written_off_account_rejected(self, api):
        """PRD §3.2: "A `Collector` issues a statement against an account whose
        `status` is `OPEN`, `IN_EARLY_OUT`, or `IN_COLLECTIONS`; accounts in any
        other status are not statement-eligible and the issuance is rejected
        with `ERR_ACCOUNT_NOT_STATEMENT_ELIGIBLE`."

        Design: Corner/validations/statement_on_written_off_account_rejected
        """
        account, _write_off = setup_posted_bad_debt_writeoff(
            balance_cents=50000, guarantor_liability_date="2026-01-01")
        assert account["status"] == "WRITTEN_OFF"
        resp = api.issue_statement(account["id"], COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_STATEMENT_ELIGIBLE)


class TestAccountVersioning:
    def test_account_version_increments_per_mutation(self, api):
        """PRD §2.5: "a system-managed integer that increments by one on every
        mutation of the resource, including mutations caused indirectly by
        cascading side effects on a related resource."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-S2", patient_name="S2")
        v_initial = account["version"]

        validate_success(api.issue_statement(account["id"], COLLECTOR), 201)
        v_after_statement = read_account(account["id"])["version"]
        assert v_after_statement == v_initial + 1, (
            f"statement issuance must bump version by 1: {v_initial} -> "
            f"{v_after_statement}")

        post_recovery(account["id"], payment_kind="LUMP_SUM", amount_cents=5000)
        v_after_recovery = read_account(account["id"])["version"]
        assert v_after_recovery == v_after_statement + 1, (
            f"recovery posting must bump version by 1: {v_after_statement} -> "
            f"{v_after_recovery}")
