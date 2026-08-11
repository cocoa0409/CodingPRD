"""Grant closeout: final settlement, cascades, audit findings, and funds conservation
(PRD §3.4, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_grant, assert_money, assert_grant_funds_conserved,
    file_invoice, verify_invoice, award_contract,
    create_drawdown, certify_drawdown, submit_drawdown, approve_drawdown,
    create_submitted_drawdown, create_amendment, current_grant_version,
    record_finding, request_closeout, begin_audit, approve_closeout,
    setup_grant_with_verified_invoice, setup_grant_under_audit,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestCloseoutFinalSettlement:
    def test_closeout_deobligates_unused_federal_balance(self):
        """PRD §3.9: "the final federal figure is exactly `federal_drawn`; the released
        amount is `federal_obligated` minus `federal_drawn`, never negative by construction;
        `federal_obligated` is then reduced to `federal_drawn`, de-obligating the unused
        balance".
        The provisional drawdown ledger (one APPROVED 81,000.00 request) reconciles with the
        final variant: obligated 900,000.00 -> 81,000.00.

        Design: Difficulty/dual_variant_calc/drawdown_provisional_vs_closeout_final
        """
        ctx = setup_grant_with_verified_invoice()
        grant_id = ctx["grant"]["id"]
        approve_drawdown(create_submitted_drawdown(grant_id, [ctx["invoice"]["id"]])["id"])
        request_closeout(grant_id)
        begin_audit(grant_id)
        grant = approve_closeout(grant_id)
        assert_grant(grant)
        assert grant["status"] == "CLOSED"
        assert_money(grant["federal_obligated"], 81_000.00, "federal_obligated")
        assert_money(grant["federal_drawn"], 81_000.00, "federal_drawn")
        assert_money(grant["federal_available"], 0.00, "federal_available")

    def test_closeout_credits_npe_with_released_entitlement(self):
        """PRD §3.9: "and the sponsor's `npe_entitlement_available` is credited with the
        entitlement portion of the release — the smaller of the released amount and the
        grant's `entitlement_portion`."
        Release 900,000 - 81,000 = 819,000 (entirely entitlement-funded): the sponsor's NPE
        returns from 4,100,000.00 to 4,919,000.00.

        Design: Difficulty/dual_variant_calc/drawdown_provisional_vs_closeout_final
        """
        ctx = setup_grant_with_verified_invoice()
        grant_id = ctx["grant"]["id"]
        approve_drawdown(create_submitted_drawdown(grant_id, [ctx["invoice"]["id"]])["id"])
        request_closeout(grant_id)
        begin_audit(grant_id)
        approve_closeout(grant_id)
        sponsor = validate_success(api_client.get_sponsor(ctx["sponsor"]["id"], SPONSOR),
                                   200)
        assert_money(sponsor["npe_entitlement_available"], 4_919_000.00,
                     "npe_entitlement_available")


class TestCloseoutCascade:
    def _setup_grant_with_paid_and_verified_invoices(self):
        """ACTIVE grant; INV-1 (100,000) driven to PAID via an APPROVED drawdown; INV-2
        (50,000) left VERIFIED. Contract retainage_held 15,000.00."""
        ctx = setup_grant_with_verified_invoice(invoice_number="INV-1",
                                                gross_amount=100_000)
        grant_id = ctx["grant"]["id"]
        approve_drawdown(create_submitted_drawdown(grant_id, [ctx["invoice"]["id"]])["id"])
        inv2 = file_invoice(ctx["contract"]["id"], ctx["contractor"]["id"],
                            invoice_number="INV-2", period="2026-06", gross_amount=50_000)
        inv2 = verify_invoice(inv2["id"])
        request_closeout(grant_id)
        begin_audit(grant_id)
        return ctx, inv2

    def test_closeout_cascade_closes_contracts_and_releases_retainage(self):
        """PRD §3.9: "every child contract still `AWARDED` moves to `CLOSED` with its
        `retainage_held` released to 0".

        Design: Difficulty/transitive_cascade/closeout_approval_cascade
        """
        ctx, _ = self._setup_grant_with_paid_and_verified_invoices()
        grant = approve_closeout(ctx["grant"]["id"])
        assert grant["status"] == "CLOSED"  # link 1
        contract = validate_success(
            api_client.get_contract(ctx["contract"]["id"], SPONSOR), 200)
        assert contract["status"] == "CLOSED"  # link 2
        assert_money(contract["retainage_held"], 0.00,
                     "retainage_held released by the cascade")

    def test_closeout_cascade_pays_invoices_outside_federal_ledger(self):
        """PRD §3.9: "every invoice of those contracts still in `VERIFIED` or `WITHHELD`
        moves to `PAID`, with those payments treated as sponsor-local obligations — they are
        not added to `federal_drawn`".

        Design: Difficulty/transitive_cascade/closeout_approval_cascade
        """
        ctx, inv2 = self._setup_grant_with_paid_and_verified_invoices()
        approve_closeout(ctx["grant"]["id"])
        invoice = validate_success(api_client.get_invoice(inv2["id"], SPONSOR), 200)
        assert invoice["status"] == "PAID"  # link 3
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        # Only the APPROVED drawdown's 81,000.00 ever entered the federal ledger.
        assert_money(grant["federal_drawn"], 81_000.00, "federal_drawn")


class TestCloseoutFindingGate:
    def test_closeout_blocked_by_open_findings(self):
        """PRD §3.9: "Approval of the closeout is the `FAAManager`'s final fiscal act on the
        grant, guarded by two checks: zero audit findings may remain `OPEN` and zero grant
        assets may remain in `DISPOSAL_REQUESTED`, with either blockage rejected as
        `ERR_CLOSEOUT_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/closeout_blocked_by_open_findings
        """
        ctx = setup_grant_under_audit()
        finding = record_finding(ctx["grant"]["id"], description="missing payroll records")
        assert finding["status"] == "OPEN"
        res = api_client.approve_closeout(ctx["grant"]["id"], FAA)
        validate_error(res, ApiErrorId.ERR_CLOSEOUT_BLOCKED, expected_status=422)
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert grant["status"] == "UNDER_AUDIT"

    def test_closeout_succeeds_after_finding_resolved(self):
        """PRD §3.9: "Each finding starts `OPEN`, and a `ComplianceOfficer` resolves findings
        — again only while the grant is `UNDER_AUDIT`, with attempts against a grant in any
        other status rejected as `ERR_INVALID_STATE` (HTTP 409) — moving them to the terminal
        `RESOLVED`."
        With no findings OPEN and no disposals pending, approval closes the grant.

        Design: Difficulty/cross_entity_state_dependency/closeout_blocked_by_open_findings
        """
        ctx = setup_grant_under_audit()
        grant_id = ctx["grant"]["id"]
        finding = record_finding(grant_id, description="missing payroll records")
        res = api_client.approve_closeout(grant_id, FAA)
        validate_error(res, ApiErrorId.ERR_CLOSEOUT_BLOCKED, expected_status=422)

        resolved = validate_success(
            api_client.resolve_audit_finding(finding["id"], COMPLIANCE), 200)
        assert resolved["status"] == "RESOLVED"
        grant = approve_closeout(grant_id)
        assert grant["status"] == "CLOSED"


class TestGrantFundsConservation:
    def test_grant_funds_conservation_forward_and_amendment(self):
        """PRD §3.4: "`federal_available`, always the obligated amount minus the drawn
        amount."
        The invariant holds after the forward drawdown approval (900,000 = 81,000 +
        819,000) and after the amendment approval grows the obligation (1,100,000 = 81,000 +
        1,019,000).

        Design: Difficulty/compensating_invariant/grant_funds_conservation
        """
        ctx = setup_grant_with_verified_invoice()
        grant_id = ctx["grant"]["id"]
        approve_drawdown(create_submitted_drawdown(grant_id, [ctx["invoice"]["id"]])["id"])
        grant = validate_success(api_client.get_grant(grant_id, SPONSOR), 200)
        assert_money(grant["federal_obligated"], 900_000.00, "federal_obligated")
        assert_money(grant["federal_drawn"], 81_000.00, "federal_drawn")
        assert_money(grant["federal_available"], 819_000.00, "federal_available")
        assert_grant_funds_conserved(grant)

        amendment = create_amendment(grant_id, 100_000, "added scope",
                                     current_grant_version(grant_id))
        validate_success(api_client.approve_amendment(amendment["id"], FAA), 200)
        grant = validate_success(api_client.get_grant(grant_id, SPONSOR), 200)
        assert_money(grant["federal_obligated"], 1_100_000.00,
                     "federal_obligated after amendment")
        assert_money(grant["federal_available"], 1_019_000.00,
                     "federal_available after amendment")
        assert_grant_funds_conserved(grant)

    def test_grant_funds_conservation_after_closeout(self):
        """PRD §3.4: "`federal_available`, always the obligated amount minus the drawn
        amount."
        PRD §3.9: "the sponsor's `npe_entitlement_available` is credited with the
        entitlement portion of the release — the smaller of the released amount and the
        grant's `entitlement_portion`."
        After the closeout de-obligation: 81,000 = 81,000 + 0, and the sponsor's NPE shows
        4,919,000.00 (the 200,000 amendment delta fully released).

        Design: Difficulty/compensating_invariant/grant_funds_conservation
        """
        ctx = setup_grant_with_verified_invoice()
        grant_id = ctx["grant"]["id"]
        approve_drawdown(create_submitted_drawdown(grant_id, [ctx["invoice"]["id"]])["id"])
        amendment = create_amendment(grant_id, 100_000, "added scope",
                                     current_grant_version(grant_id))
        validate_success(api_client.approve_amendment(amendment["id"], FAA), 200)

        request_closeout(grant_id)
        begin_audit(grant_id)
        grant = approve_closeout(grant_id)
        assert grant["status"] == "CLOSED"
        assert_money(grant["federal_obligated"], 81_000.00, "federal_obligated")
        assert_money(grant["federal_drawn"], 81_000.00, "federal_drawn")
        assert_money(grant["federal_available"], 0.00, "federal_available")
        assert_grant_funds_conserved(grant)

        sponsor = validate_success(api_client.get_sponsor(ctx["sponsor"]["id"], SPONSOR),
                                   200)
        assert_money(sponsor["npe_entitlement_available"], 4_919_000.00,
                     "npe_entitlement_available")


class TestAuditRoleGates:
    def test_auditor_exclusive_begin_audit(self):
        """PRD §4: begin-audit is listed under "Auditor opens the closeout audit" with
        authorized role Auditor.
        PRD §2.1: "only after the caller is authenticated does the system check whether the
        role is permitted to invoke the requested endpoint, rejecting impermissible
        combinations with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/auditor_exclusive_begin_audit
        """
        ctx = setup_grant_with_verified_invoice()
        # No drawdown remains pending: approve it so closeout can be requested.
        grant_id = ctx["grant"]["id"]
        approve_drawdown(create_submitted_drawdown(grant_id, [ctx["invoice"]["id"]])["id"])
        request_closeout(grant_id)

        res = api_client.begin_audit(grant_id, SPONSOR)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        grant = begin_audit(grant_id)
        assert grant["status"] == "UNDER_AUDIT"
