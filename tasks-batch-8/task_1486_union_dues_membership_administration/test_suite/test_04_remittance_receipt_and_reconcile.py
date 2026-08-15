"""Employer checkoff remittances: receipt, lines, reconcile, and dispute."""
import pytest

from test_helpers import (
    ST,
    ApiErrorId,
    add_remittance_line,
    assert_remittance,
    create_remittance_line_payload,
    create_remittance_payload,
    create_resolve_dispute_payload,
    get_member,
    get_success_data,
    make_assessment_run,
    make_classification,
    make_employer,
    make_local,
    make_member,
    make_member_headers,
    make_remittance,
    reconcile_remittance,
    resolve_remittance,
    set_clock,
    setup_pct_local_with_journeyman,
    validate_error,
    validate_success,
)


def _setup_local_emp_member(api, member_name="Remit Rick"):
    local, cls = setup_pct_local_with_journeyman()
    emp = make_employer("Acme Widgets")
    member = make_member(
        local["id"], cls["id"], employer_id=emp["id"],
        full_name=member_name, member_number="M-001",
    )
    set_clock("2026-08-01T00:00:00Z")
    return local, cls, emp, member


class TestReceiptConstraints:
    def test_duplicate_remittance_period_rejected(self, api, office_clerk_headers):
        """PRD section on remittances: "One remittance may exist per employer
        and period; a duplicate is rejected with `ERR_REMITTANCE_EXISTS`."

        Design: Corner/errors/duplicate_remittance_period_rejected
        """
        local, _, emp, _ = _setup_local_emp_member(api)
        make_remittance(emp["id"], local["id"], "2026-08", 0)
        resp = api.create_remittance(
            create_remittance_payload(emp["id"], local["id"], "2026-08", 5000),
            office_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_EXISTS)

    def test_duplicate_remittance_line_rejected(self, api, office_clerk_headers):
        """PRD section on remittances: "a second line for the same member in
        the same remittance is rejected with `ERR_DUPLICATE_REMITTANCE_LINE`".

        Design: Corner/errors/duplicate_remittance_line_rejected
        """
        local, _, emp, member = _setup_local_emp_member(api, "Double Line")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 0)
        add_remittance_line(rem["id"], member["id"], 1000, 1000)
        resp = api.create_remittance_line(
            rem["id"],
            create_remittance_line_payload(member["id"], 2000, 2000),
            office_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REMITTANCE_LINE)

    def test_void_received_remittance_rejected(self, api, local_admin_headers):
        """PRD section on remittances: "the remittance must be `POSTED`
        (`ERR_REMITTANCE_NOT_POSTED`)" before it can be voided.

        Design: Corner/state_machines/void_received_remittance_rejected
        """
        local, _, emp, _ = _setup_local_emp_member(api)
        rem = make_remittance(emp["id"], local["id"], "2026-08", 0)
        resp = api.void_remittance(rem["id"], local_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_NOT_POSTED)

    def test_member_cannot_receive_remittance(self, api):
        """PRD section on roles: "A request whose role is declared but not
        permitted on the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." The endpoint table
        authorizes only OfficeClerk to receive a remittance.

        Design: Corner/rbac/member_cannot_receive_remittance
        """
        local, _, emp, _ = _setup_local_emp_member(api)
        resp = api.create_remittance(
            create_remittance_payload(emp["id"], local["id"], "2026-08", 0),
            make_member_headers("00000000-0000-0000-0000-000000000001"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestReconcile:
    def test_reconcile_unbalanced_header_rejected(self, api):
        """PRD section on reconciliation: "Next the header must balance:
        `remitted_cents` must equal the sum of the lines' `deducted_cents`,
        otherwise the reconcile is rejected with `ERR_REMITTANCE_UNBALANCED`".

        Design: Corner/validations/reconcile_unbalanced_header_rejected
        """
        local, _, emp, member = _setup_local_emp_member(api, "Balance Bob")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 999999)
        add_remittance_line(rem["id"], member["id"], 1000, 1000)
        resp = api.reconcile_remittance(rem["id"], ST)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_UNBALANCED)

    def test_resolve_without_active_dispute_rejected(self, api):
        """PRD section on reconciliation: a dispute resolution "requires
        `dispute_status` `DISPUTED` (`ERR_DISPUTE_NOT_ACTIVE` when the dispute
        is `NONE` or already `RESOLVED`)".

        Design: Corner/errors/resolve_without_active_dispute_rejected
        """
        local, _, emp, _ = _setup_local_emp_member(api)
        rem = make_remittance(emp["id"], local["id"], "2026-08", 0)
        resp = api.resolve_remittance_dispute(
            rem["id"], create_resolve_dispute_payload("nothing to resolve"), ST
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_ACTIVE)


class TestParallelDimensionsDispute:
    """A remittance carries two independent state dimensions; reconcile with a
    non-zero variance moves only the dispute dimension."""

    def _setup_disputed_remittance(self, api):
        local, cls, emp, member = _setup_local_emp_member(api, "Para Pam")
        make_assessment_run(local["id"], "2026-08")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 17500)
        add_remittance_line(rem["id"], member["id"], 17500, 900000)
        return local, member, rem

    def test_reconcile_dispute_moves_only_dispute_dimension(self, api):
        """PRD section on reconciliation: "When any variance is non-zero or the
        missing-member list is non-empty, the remittance instead remains
        `RECEIVED` and its `dispute_status` moves from `NONE` to `DISPUTED`".
        The line records "variance_cents, the line's deducted amount minus the
        final assessed amount, and `line_status`: `MATCHED` when the variance
        is zero, `UNDER_DEDUCTED` when negative, and `OVER_DEDUCTED` when
        positive".

        Design: Difficulty/non_linear_state_machine/remittance_parallel_dims_dispute
        """
        _, member, rem = self._setup_disputed_remittance(api)
        reconciled = reconcile_remittance(rem["id"])
        assert_remittance(reconciled)
        assert reconciled["status"] == "RECEIVED", "status dimension does not move on dispute"
        assert reconciled["dispute_status"] == "DISPUTED"
        assert reconciled["expected_total_cents"] == 18000, (
            "sum of FINAL assessed dues over roster members with a non-terminal assessment"
        )
        lines = get_success_data(api.list_remittance_lines(rem["id"], ST))
        assert len(lines) == 1
        assert lines[0]["variance_cents"] == -500, "17500 deducted minus 18000 assessed"
        assert lines[0]["line_status"] == "UNDER_DEDUCTED"

    def test_finalization_lands_despite_dispute_and_resolve_closes_both_dims(self, api):
        """PRD section on reconciliation: "the assessments still finalize and
        deltas still post exactly as in the clean case" — the member's arrears
        carry the 3000 provisional charge plus the 15000 supplemental delta.
        And "The remittance's `dispute_status` becomes `RESOLVED` and its
        `status` becomes `RECONCILED`."

        Design: Difficulty/non_linear_state_machine/remittance_parallel_dims_dispute
        """
        _, member, rem = self._setup_disputed_remittance(api)
        reconcile_remittance(rem["id"])
        member_mid = get_member(member["id"])
        assert member_mid["arrears_cents"] == 18000, (
            "provisional 3000 plus 15000 supplemental charge posted despite the dispute"
        )
        resolved = resolve_remittance(rem["id"], "accept union FINAL amounts; member self-pays remainder")
        assert resolved["status"] == "RECONCILED"
        assert resolved["dispute_status"] == "RESOLVED"


class TestReconcileValidationPriority:
    """Both a roster violation and a header imbalance hold; the roster
    re-validation is pinned to run first."""

    def _setup_withdrawn_member_line(self, api):
        local, cls, emp, member = _setup_local_emp_member(api, "Walt Withdraw")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 999999)
        add_remittance_line(rem["id"], member["id"], 1000, 1000)
        return local, member, rem

    def test_roster_revalidation_precedes_header_balance(self, api):
        """PRD section on reconciliation: "Roster re-validation runs first,
        before any variance is computed: if any line's member no longer
        qualifies for the roster — for instance because the member withdrew
        after the line was entered — the entire reconcile is rejected with
        `ERR_MEMBER_NOT_ON_ROSTER`; this is a validation failure, not a
        reconciliation outcome."

        Design: Difficulty/priority_pair_validation_conflict/reconcile_referential_vs_fiscal_priority
        """
        _, member, rem = self._setup_withdrawn_member_line(api)
        withdraw = api.withdraw_member(member["id"], make_member_headers(member["id"]))
        validate_success(withdraw, 200)
        resp = api.reconcile_remittance(rem["id"], ST)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ON_ROSTER, 422)

    def test_header_imbalance_surfaces_once_roster_is_clean(self, api):
        """PRD section on reconciliation: "Next the header must balance:
        `remitted_cents` must equal the sum of the lines' `deducted_cents`,
        otherwise the reconcile is rejected with `ERR_REMITTANCE_UNBALANCED`".
        With the member still on the roster, the fiscal check is the one that
        fires.

        Design: Difficulty/priority_pair_validation_conflict/reconcile_referential_vs_fiscal_priority
        """
        _, member, rem = self._setup_withdrawn_member_line(api)
        resp = api.reconcile_remittance(rem["id"], ST)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_UNBALANCED)
