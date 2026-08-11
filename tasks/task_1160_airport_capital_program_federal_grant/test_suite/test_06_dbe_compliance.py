"""DBE reporting, adjudication boundary, and the withhold/release cascades (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_money,
    file_dbe_report, adjudicate_dbe_report, create_drawdown, certify_drawdown,
    setup_active_grant, setup_grant_with_contract, setup_grant_with_verified_invoice,
    create_contractor, award_contract, request_closeout, begin_audit, approve_closeout,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


class TestDbeGoalBoundary:
    def test_dbe_goal_exact_attainment_compliant(self):
        """PRD §3.6: "The decision compares the rounded `achieved_dbe_pct` against the
        contract's `dbe_goal_pct` on an inclusive boundary: meeting the goal exactly counts as
        attainment. When the rounded achievement is at least the goal, the report becomes
        `COMPLIANT`, the contract's `dbe_posture` is set to `COMPLIANT`".
        12,500.00 / 100,000.00 = 12.50, exactly the 12.50 goal.

        Design: Difficulty/boundary_precision_check/dbe_goal_exact_attainment
        """
        ctx = setup_grant_with_contract()
        report = file_dbe_report(ctx["contract"]["id"], ctx["contractor"]["id"],
                                 "2026-Q2", 12_500, 100_000)
        assert_money(report["achieved_dbe_pct"], 12.50, "achieved_dbe_pct")
        adjudicated = adjudicate_dbe_report(report["id"])
        assert adjudicated["status"] == "COMPLIANT"
        contract = validate_success(
            api_client.get_contract(ctx["contract"]["id"], SPONSOR), 200)
        assert contract["dbe_posture"] == "COMPLIANT"

    def test_dbe_goal_one_tenth_below_shortfall(self):
        """PRD §3.6: "When the rounded achievement falls below the goal, the report becomes
        `SHORTFALL` and the withholding cascade runs in three steps: the contract's
        `dbe_posture` is set to `NON_COMPLIANT`".
        12,490.00 / 100,000.00 = 12.49 < 12.50.

        Design: Difficulty/boundary_precision_check/dbe_goal_exact_attainment
        """
        ctx = setup_grant_with_contract()
        report = file_dbe_report(ctx["contract"]["id"], ctx["contractor"]["id"],
                                 "2026-Q3", 12_490, 100_000)
        assert_money(report["achieved_dbe_pct"], 12.49, "achieved_dbe_pct")
        adjudicated = adjudicate_dbe_report(report["id"])
        assert adjudicated["status"] == "SHORTFALL"
        contract = validate_success(
            api_client.get_contract(ctx["contract"]["id"], SPONSOR), 200)
        assert contract["dbe_posture"] == "NON_COMPLIANT"


class TestDbeCascades:
    def test_dbe_shortfall_cascade(self):
        """PRD §3.6: "When the rounded achievement falls below the goal, the report becomes
        `SHORTFALL` and the withholding cascade runs in three steps: the contract's
        `dbe_posture` is set to `NON_COMPLIANT`; every invoice of the contract currently in
        `VERIFIED` is moved to `WITHHELD`; and for each withheld invoice the contract's
        `invoiced_total` decreases by that invoice's gross amount while `remaining_value`
        increases correspondingly."

        Design: Difficulty/transitive_cascade/dbe_shortfall_cascade
        """
        ctx = setup_grant_with_verified_invoice()
        con_id = ctx["contract"]["id"]
        report = file_dbe_report(con_id, ctx["contractor"]["id"], "2026-Q2",
                                 12_490, 100_000)
        adjudicated = adjudicate_dbe_report(report["id"])
        assert adjudicated["status"] == "SHORTFALL"

        contract = validate_success(api_client.get_contract(con_id, SPONSOR), 200)
        assert contract["dbe_posture"] == "NON_COMPLIANT"  # link 1
        invoice = validate_success(
            api_client.get_invoice(ctx["invoice"]["id"], SPONSOR), 200)
        assert invoice["status"] == "WITHHELD"  # link 2
        assert_money(contract["invoiced_total"], 0.00, "invoiced_total")  # link 3
        assert_money(contract["remaining_value"], 500_000.00, "remaining_value")

    def test_dbe_compliant_release_cascade(self):
        """PRD §3.6: "the release cascade runs — every invoice of the contract currently in
        `WITHHELD` returns to `VERIFIED`, with `invoiced_total` and `remaining_value`
        recomputed accordingly."

        Design: Difficulty/transitive_cascade/dbe_shortfall_cascade
        """
        ctx = setup_grant_with_verified_invoice()
        con_id = ctx["contract"]["id"]
        shortfall = file_dbe_report(con_id, ctx["contractor"]["id"], "2026-Q2",
                                    12_490, 100_000)
        adjudicate_dbe_report(shortfall["id"])
        # A later compliant report reverses all three cascade links.
        recovery = file_dbe_report(con_id, ctx["contractor"]["id"], "2026-Q3",
                                   20_000, 100_000)
        adjudicated = adjudicate_dbe_report(recovery["id"])
        assert adjudicated["status"] == "COMPLIANT"

        contract = validate_success(api_client.get_contract(con_id, SPONSOR), 200)
        assert contract["dbe_posture"] == "COMPLIANT"
        invoice = validate_success(
            api_client.get_invoice(ctx["invoice"]["id"], SPONSOR), 200)
        assert invoice["status"] == "VERIFIED"
        assert_money(contract["invoiced_total"], 100_000.00, "invoiced_total")
        assert_money(contract["remaining_value"], 400_000.00, "remaining_value")


class TestDrawdownDbeGate:
    def test_drawdown_submit_blocked_by_dbe_noncompliance(self):
        """PRD §3.7: "every included invoice must still be `INCLUDED` and no included
        invoice's contract may carry a `dbe_posture` of `NON_COMPLIANT` (otherwise
        `ERR_PAYMENTS_WITHHELD_DBE`, HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/drawdown_submit_blocked_by_dbe_noncompliance
        """
        ctx = setup_grant_with_verified_invoice()
        con_id = ctx["contract"]["id"]
        drawdown = create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])
        certify_drawdown(drawdown["id"])
        # The invoice is already INCLUDED in a drawdown, so the shortfall cascade (which
        # flips only VERIFIED invoices) leaves it INCLUDED — the block lands on submit.
        report = file_dbe_report(con_id, ctx["contractor"]["id"], "2026-Q2",
                                 12_490, 100_000)
        adjudicate_dbe_report(report["id"])

        res = api_client.submit_drawdown(drawdown["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_PAYMENTS_WITHHELD_DBE, expected_status=422)
        invoice = validate_success(
            api_client.get_invoice(ctx["invoice"]["id"], SPONSOR), 200)
        assert invoice["status"] == "INCLUDED"

    def test_drawdown_submit_unblocked_after_compliant_readjudication(self):
        """PRD §3.6: "the release cascade runs — every invoice of the contract currently in
        `WITHHELD` returns to `VERIFIED`, with `invoiced_total` and `remaining_value`
        recomputed accordingly."
        PRD §3.7: "Submission is then the `FinanceOfficer`'s action, moving `CERTIFIED` to
        `SUBMITTED`" once the DBE posture gate passes.

        Design: Difficulty/cross_entity_state_dependency/drawdown_submit_blocked_by_dbe_noncompliance
        """
        ctx = setup_grant_with_verified_invoice()
        con_id = ctx["contract"]["id"]
        drawdown = create_drawdown(ctx["grant"]["id"], [ctx["invoice"]["id"]])
        certify_drawdown(drawdown["id"])
        report = file_dbe_report(con_id, ctx["contractor"]["id"], "2026-Q2",
                                 12_490, 100_000)
        adjudicate_dbe_report(report["id"])
        res = api_client.submit_drawdown(drawdown["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_PAYMENTS_WITHHELD_DBE, expected_status=422)

        recovery = file_dbe_report(con_id, ctx["contractor"]["id"], "2026-Q3",
                                   20_000, 100_000)
        adjudicate_dbe_report(recovery["id"])
        submitted = validate_success(api_client.submit_drawdown(drawdown["id"], FINANCE),
                                     200)
        assert submitted["status"] == "SUBMITTED"


class TestAdjudicationStateGuards:
    def test_dbe_report_double_adjudication_rejected(self):
        """PRD §3.6: "the report rests in `PENDING` awaiting adjudication".
        PRD §2.9: "state preconditions for the requested transition (generic failures carry
        `ERR_INVALID_STATE`, HTTP 409, while specific ones carry their dedicated codes)" —
        a COMPLIANT report is no longer PENDING, so a second adjudication is refused.

        Design: Corner/state_machines/dbe_report_double_adjudication_rejected
        """
        ctx = setup_grant_with_contract()
        report = file_dbe_report(ctx["contract"]["id"], ctx["contractor"]["id"],
                                 "2026-Q2", 12_500, 100_000)
        adjudicated = adjudicate_dbe_report(report["id"])
        assert adjudicated["status"] == "COMPLIANT"
        res = api_client.adjudicate_dbe_report(report["id"],
                                               TEST_USERS["compliance_officer_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        rows = validate_success(
            api_client.list_dbe_reports(ctx["contract"]["id"], SPONSOR), 200)
        row = [r for r in rows if r["id"] == report["id"]][0]
        assert row["status"] == "COMPLIANT"

    def test_adjudicate_report_on_closed_contract_rejected(self):
        """PRD §3.6: "A `ComplianceOfficer` adjudicates the report, but only while the
        contract is `AWARDED`; adjudicating against a `CLOSED` contract is rejected with
        `ERR_CONTRACT_CLOSED` (HTTP 409)."

        Design: Corner/validations/adjudicate_report_on_closed_contract_rejected
        """
        ctx = setup_active_grant_for_closeout()
        report = file_dbe_report(ctx["contract"]["id"], ctx["contractor"]["id"],
                                 "2026-Q2", 12_500, 100_000)
        close_grant(ctx["grant"]["id"])
        contract = validate_success(
            api_client.get_contract(ctx["contract"]["id"], SPONSOR), 200)
        assert contract["status"] == "CLOSED"

        res = api_client.adjudicate_dbe_report(report["id"],
                                               TEST_USERS["compliance_officer_headers"])
        validate_error(res, ApiErrorId.ERR_CONTRACT_CLOSED, expected_status=409)
        rows = validate_success(
            api_client.list_dbe_reports(ctx["contract"]["id"], SPONSOR), 200)
        row = [r for r in rows if r["id"] == report["id"]][0]
        assert row["status"] == "PENDING"


# Local composites built from test_helpers primitives (only the closed-contract guard
# needs this exact terminal arrangement).
def setup_active_grant_for_closeout():
    """ACTIVE grant + contractor + contract (no invoices, findings, or phases)."""
    ctx = setup_active_grant()
    contractor = create_contractor(ctx["sponsor"]["id"])
    contract = award_contract(ctx["grant"]["id"], ctx["project"]["id"], contractor["id"])
    return {**ctx, "contractor": contractor, "contract": contract}


def close_grant(grant_id):
    request_closeout(grant_id)
    begin_audit(grant_id)
    return approve_closeout(grant_id)
