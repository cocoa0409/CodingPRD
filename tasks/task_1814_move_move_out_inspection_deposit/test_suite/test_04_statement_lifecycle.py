"""Deposit statement lifecycle: the DRAFT -> ISSUED -> DISPUTED -> DRAFT
revision cycle, issuance gating, disbursement gating on the current
statement, supersession, and the one-active-statement rule."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    create_disbursement_payload,
    create_deduction_payload,
    create_dispute_payload,
    create_statement_for,
    create_statement_payload,
    get_dispute,
    get_statement,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    make_tenant_headers,
    setup_issued_statement_with_damage,
    setup_notice_given,
    setup_vacated_tenancy,
    setup_vacated_with_statement,
    validate_error,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


def _list_deductions(tenancy_id):
    resp = api_client.list_deductions(PM, params={"tenancy_id": tenancy_id, "limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", [])


def _setup_disputed_statement():
    """Canonical VACATED tenancy (paint 60,000c), statement issued timely at
    2026-08-10, disputed by the tenant for 20,000c."""
    ctx = setup_issued_statement_with_damage()
    ten = ctx["tenancy"]
    resp = api_client.create_dispute(
        create_dispute_payload(statement_id=ctx["statement"]["id"],
                               disputed_amount_cents=20_000,
                               reason="paint was already worn"),
        make_tenant_headers(ten["id"]),
    )
    ctx["dispute"] = get_success_data(resp)
    return ctx


class TestStatementRevisionCycle:
    def test_reopen_compensates_billed_lines_back_to_draft(self):
        """PRD §3.5: "A statement under dispute can be pulled back for
        revision: reopening a `DISPUTED` statement — which requires an active
        dispute in `OPEN`, `MANAGER_COUNTERED`, or `ESCALATED_SMALL_CLAIMS` to
        exist — is a compensating action that returns the statement to `DRAFT`.
        Its `BILLED` lines revert to `DRAFT` with `statement_id` cleared,
        `released_cents` resets to zero, `refund_due_cents` resets to zero,
        `issued_at`, `deadline_on`, and `late` are cleared, the active dispute
        moves to `WITHDRAWN`, and the tenancy's deduction counters and
        `version` are recomputed."

        After reopen: statement DRAFT, the paint line back to DRAFT with
        statement_id null, dispute WITHDRAWN, tenancy totals back to
        pending 60,000 / billed 0.

        Design: Difficulty/non_linear_state_machine/statement_revision_cycle_draft_issued_disputed_draft
        """
        ctx = _setup_disputed_statement()
        stmt = ctx["statement"]
        disp = ctx["dispute"]
        ten_id = ctx["tenancy"]["id"]

        validate_success(api_client.reopen_statement(stmt["id"], PM))

        stmt_after = get_statement(stmt["id"])
        assert stmt_after["status"] == "DRAFT", (
            f"cycle ISSUED -> DISPUTED -> DRAFT, got {stmt_after['status']}"
        )
        assert stmt_after["released_cents"] == 0
        assert stmt_after["refund_due_cents"] == 0
        assert stmt_after["issued_at"] is None
        assert stmt_after["deadline_on"] is None
        lines = _list_deductions(ten_id)
        assert lines, "the paint line must still exist"
        for line in lines:
            assert line["status"] == "DRAFT", f"line must revert to DRAFT: {line}"
            assert line["statement_id"] is None, f"statement_id must be cleared: {line}"
        assert get_dispute(disp["id"])["status"] == "WITHDRAWN"
        ten = get_tenancy(ten_id)
        assert ten["total_deductions_cents"] == 0
        assert ten["pending_deductions_cents"] == 60_000

    def test_second_issue_restores_totals(self):
        """PRD §3.5: "The statement's totals are computed at this point:
        `interest_cents` snapshots the tenancy's accrued interest,
        `deduction_total_cents` sums the swept lines (each already rounded to
        cents at creation, then summed), and `refund_due_cents` is the deposit
        plus `interest_cents` minus `deduction_total_cents`."

        The statement row cycles ISSUED -> DISPUTED -> DRAFT -> ISSUED again;
        the second issuance recomputes deduction_total 60,000 and refund_due
        149,337 on the same row.

        Design: Difficulty/non_linear_state_machine/statement_revision_cycle_draft_issued_disputed_draft
        """
        ctx = _setup_disputed_statement()
        stmt = ctx["statement"]
        validate_success(api_client.reopen_statement(stmt["id"], PM))
        api_client.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, ADMIN)
        reissued = validate_success(api_client.issue_statement(stmt["id"], PM))
        assert reissued["status"] == "ISSUED"
        assert reissued["deduction_total_cents"] == 60_000
        assert reissued["refund_due_cents"] == 149_337, (
            f"200000 + 9337 - 60000 = 149337, got {reissued['refund_due_cents']}"
        )


class TestDisbursementRequiresIssuedStatement:
    def _setup_draft_statement(self):
        ctx = setup_vacated_with_statement()  # DRAFT statement, not issued
        return ctx

    def test_refund_rejected_while_statement_draft(self):
        """PRD §3.7: "and that current statement must be `ISSUED` or `SETTLED`,
        so writing a check against a `DRAFT` (or dispute-locked) current
        statement is rejected with `ERR_INVALID_STATE_TRANSITION`."

        A REFUND disbursement against the DRAFT current statement fails.

        Design: Difficulty/cross_entity_state_dependency/disbursement_requires_issued_statement
        """
        ctx = self._setup_draft_statement()
        resp = api_client.create_disbursement(
            create_disbursement_payload(tenancy_id=ctx["tenancy"]["id"],
                                        statement_id=ctx["statement"]["id"],
                                        kind="REFUND", amount_cents=1_000),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_refund_succeeds_after_issue_and_reserves(self):
        """PRD §3.7: "A created disbursement starts in `SENT` with `sent_at`
        stamped from the logical clock — checks are considered mailed
        immediately — and a `REFUND` immediately reserves its amount by adding
        it to the tenancy's `reserved_cents`, shrinking the remaining balance
        until the check clears."

        After issuance the identical request succeeds (201, SENT) and
        reserved_cents rises by the amount.

        Design: Difficulty/cross_entity_state_dependency/disbursement_requires_issued_statement
        """
        ctx = self._setup_draft_statement()
        api_client.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, ADMIN)
        validate_success(api_client.issue_statement(ctx["statement"]["id"], PM))
        resp = api_client.create_disbursement(
            create_disbursement_payload(tenancy_id=ctx["tenancy"]["id"],
                                        statement_id=ctx["statement"]["id"],
                                        kind="REFUND", amount_cents=1_000),
            PM,
        )
        disb = validate_success(resp, expected_status=201)
        assert disb["status"] == "SENT"
        ten = get_tenancy(ctx["tenancy"]["id"])
        assert ten["reserved_cents"] == 1_000, (
            f"REFUND reserves immediately: expected 1000, got {ten['reserved_cents']}"
        )


class TestIssueGuards:
    def test_issue_requires_vacated(self):
        """PRD §3.5: "Issuance is the statutory moment, and it requires the
        tenancy to be `VACATED`; issuing earlier is rejected with
        `ERR_TENANCY_NOT_VACATED`."

        Issuing while the tenancy is still NOTICE_GIVEN (statement DRAFT,
        move-out not completed) fails; the statement stays DRAFT.

        Design: Corner/validations/issue_requires_vacated_rejected
        """
        ctx = setup_notice_given(keys_returned=2, fobs_returned=1)
        stmt = create_statement_for(ctx["tenancy"]["id"])
        resp = api_client.issue_statement(stmt["id"], PM)
        validate_error(resp, ApiErrorId.ERR_TENANCY_NOT_VACATED)
        assert get_statement(stmt["id"])["status"] == "DRAFT"

    def test_issue_on_superseded_statement_rejected(self):
        """PRD §3.5: "Creating against a tenancy whose previous statement is
        `DISPUTED` is the deliberate create-with-supersede path: the
        predecessor flips to `SUPERSEDED`, any active dispute riding on it is
        withdrawn". PRD §3.5: "Reopening a statement that is not `DISPUTED` is
        rejected with `ERR_INVALID_STATE_TRANSITION`." and the same state-guard
        family of PRD §2.9: "fifth, state preconditions on the target resources
        (the state-guard errors such as `ERR_INVALID_STATE_TRANSITION` and
        `ERR_TENANCY_NOT_VACATED`)".

        SUPERSEDED is terminal for issuance: issuing the superseded S1 fails;
        S1 stays SUPERSEDED and S2 stays DRAFT.

        Design: Corner/state_machines/issue_on_superseded_statement_rejected
        """
        ctx = _setup_disputed_statement()
        stmt1 = ctx["statement"]
        stmt2 = create_statement_for(ctx["tenancy"]["id"])
        assert get_statement(stmt1["id"])["status"] == "SUPERSEDED"
        resp = api_client.issue_statement(stmt1["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_statement(stmt1["id"])["status"] == "SUPERSEDED"
        assert get_statement(stmt2["id"])["status"] == "DRAFT"

    def test_second_statement_while_draft_active_rejected(self):
        """PRD §3.5: "Only one active statement may exist per tenancy: if a
        `DRAFT` or `ISSUED` statement already exists, creation is rejected with
        `ERR_STATEMENT_ALREADY_ACTIVE`."

        A second create with the freshly observed (correct) OCC version still
        fails; only the first statement exists (statement_seq 1).

        Design: Corner/validations/second_statement_while_draft_active_rejected
        """
        ctx = setup_vacated_with_statement()
        ten_id = ctx["tenancy"]["id"]
        stmt1 = ctx["statement"]
        ten = get_tenancy(ten_id)
        resp = api_client.create_statement(
            create_statement_payload(tenancy_id=ten_id,
                                     expected_tenancy_version=ten["version"]),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_ALREADY_ACTIVE)
        data = get_success_data(api_client.list_statements(
            PM, params={"tenancy_id": ten_id, "limit": 100}))
        rows = data if isinstance(data, list) else data.get("data", [])
        assert len(rows) == 1 and rows[0]["id"] == stmt1["id"]
        assert rows[0]["statement_seq"] == 1
