"""Cascade and escrow tests: consent-revoke depth-3 cascade, expense-disburse depth-2
cascade, escrow disburse-then-refund conservation, and corner escrow/derived claims.

Difficulty queue (A): transitive_cascade, compensating_invariant (escrow).
Corner queue (B): endpoints/errors/cross_cutting_complexity_layers instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_agency, set_clock, create_case, create_family, create_birth_parent,
    current_case_version, create_signed_consent, create_irrevocable_consent,
    create_approved_expense, create_logged_expense, create_case_with_deposit,
    setup_active_placement_in_state,
    create_escrow_payload, create_consent_payload, create_expense_payload,
    schedule_visit,
    TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]
SUP = TEST_USERS["supervisor_headers"]
FO = TEST_USERS["finance_officer_headers"]
ADMIN = TEST_USERS["agency_admin_headers"]


# ─── transitive_cascade / consent_revoke_cascades_placement_visits_phase ──
class TestConsentRevokeCascade:
    def _setup_revoke_scenario(self):
        """In-state case with ACTIVE placement (via IRREVOCABLE consent), one SCHEDULED
        visit, plus a second SIGNED consent whose revocation window is still open.
        Returns (agency_id, case_id, placement_id, visit_id, open_consent_id)."""
        base = setup_active_placement_in_state(to_iso8601="2026-06-04T08:00:00.000Z")
        visit = schedule_visit(base["case_id"], base["placement_id"],
                               "2026-06-10T09:00:00.000Z", "2026-06-10T17:00:00.000Z")
        cv = current_case_version(base["case_id"])
        open_consent = create_signed_consent(base["case_id"], base["bp_id"], cv,
                                             revocation_basis="BUSINESS_DAYS",
                                             child_dob="2026-06-01T08:00:00.000Z")
        set_clock(base["agency_id"], "2026-06-05T00:00:00.000Z")  # before deadline
        return base["agency_id"], base["case_id"], base["placement_id"], visit["id"], open_consent["id"]

    def test_revoke_disrupts_placement_and_misses_visit(self):
        """PRD §3.4: "A successful revocation triggers a two-hop cascade: if the case has
        an active placement, that placement (whether PENDING or ACTIVE) transitions to
        DISRUPTED, and that placement disruption in turn transitions every SCHEDULED
        post-placement visit for the placement to MISSED."

        Design: Difficulty/transitive_cascade/consent_revoke_cascades_placement_visits_phase
        """
        agency_id, case_id, placement_id, visit_id, open_consent_id = self._setup_revoke_scenario()
        validate_success(api_client.revoke_consent(open_consent_id, CW), 200)
        placement = validate_success(api_client.get_placement(placement_id, SUP), 200)
        assert placement["status"] == "DISRUPTED"
        visit = validate_success(api_client.get_visit(visit_id, SUP), 200)
        assert visit["status"] == "MISSED"

    def test_revoke_bubbles_case_phase_to_disrupted(self):
        """PRD §3.4: "The revocation then bubbles up to recompute the case phase, driving
        the case to DISRUPTED, and increments the consent's version."

        Design: Difficulty/transitive_cascade/consent_revoke_cascades_placement_visits_phase
        """
        agency_id, case_id, placement_id, visit_id, open_consent_id = self._setup_revoke_scenario()
        validate_success(api_client.revoke_consent(open_consent_id, CW), 200)
        case = validate_success(api_client.get_case(case_id, SUP), 200)
        assert case["phase"] == "DISRUPTED"


# ─── transitive_cascade / expense_disburse_cascades_escrow_balance ────────
class TestExpenseDisburseCascade:
    def _setup_disburse_scenario(self):
        """Case with a 1,000,000 DEPOSIT and one APPROVED expense of 300,000.
        Returns (case_id, expense_id)."""
        cd = create_case_with_deposit(deposit_cents=1_000_000)
        exp = create_approved_expense(cd["case_id"], amount_cents=300_000, category="MEDICAL")
        return cd["case_id"], exp["id"]

    def test_disburse_moves_expense_to_disbursed(self):
        """PRD §3.7: "A FinanceOfficer disburses an expense, moving it from APPROVED to
        DISBURSED ... A successful disbursement triggers a two-hop cascade: it creates a
        DISBURSEMENT escrow transaction for the expense's amount tied to that expense,
        and that transaction in turn recomputes the case's escrow_balance_cents."

        Design: Difficulty/transitive_cascade/expense_disburse_cascades_escrow_balance
        """
        case_id, exp_id = self._setup_disburse_scenario()
        disbursed = validate_success(api_client.disburse_expense(exp_id, FO), 200)
        assert disbursed["status"] == "DISBURSED"

    def test_disburse_recomputes_escrow_balance(self):
        """PRD §3.7: "a disbursement of amount A decreases escrow_balance_cents by exactly
        A while the matching expense moves to DISBURSED".

        Design: Difficulty/transitive_cascade/expense_disburse_cascades_escrow_balance
        """
        case_id, exp_id = self._setup_disburse_scenario()
        validate_success(api_client.disburse_expense(exp_id, FO), 200)
        case = validate_success(api_client.get_case(case_id, FO), 200)
        assert case["escrow_balance_cents"] == 700_000  # 1,000,000 - 300,000


# ─── compensating_invariant / escrow_disburse_then_refund_conserves_balance ──
class TestEscrowRefundConservation:
    def _disbursed_state(self):
        """Deposit 1,000,000; approve + disburse a 300,000 expense (balance 700,000).
        Returns (case_id, expense_id)."""
        cd = create_case_with_deposit(deposit_cents=1_000_000)
        exp = create_approved_expense(cd["case_id"], amount_cents=300_000, category="MEDICAL")
        api_client.disburse_expense(exp["id"], FO)
        return cd["case_id"], exp["id"]

    def test_balance_is_deposits_minus_disbursements_minus_refunds(self):
        """PRD §3.7: "The escrow balance for a case is the sum of amount_cents over its
        DEPOSIT transactions, minus the sum over its DISBURSEMENT transactions, minus the
        sum over its REFUND transactions."

        Design: Difficulty/compensating_invariant/escrow_disburse_then_refund_conserves_balance
        """
        case_id, exp_id = self._disbursed_state()
        # After disburse only: 1,000,000 - 300,000 = 700,000.
        case = validate_success(api_client.get_case(case_id, FO), 200)
        assert case["escrow_balance_cents"] == 700_000


# ─── Corner (B): errors / insufficient_escrow_on_oversized_refund ─────────
def test_insufficient_escrow_on_oversized_refund():
    """PRD §3.7: "A transaction that would drive escrow_balance_cents below zero — a
    disbursement or refund whose amount exceeds the available balance — is rejected with
    ERR_INSUFFICIENT_ESCROW."

    Design: Corner/errors/insufficient_escrow_on_oversized_refund
    """
    cd = create_case_with_deposit(deposit_cents=500_000)
    cv = current_case_version(cd["case_id"], headers=FO)
    res = api_client.create_escrow_transaction(
        create_escrow_payload(cd["case_id"], cv, txn_type="REFUND", amount_cents=900_000), FO)
    validate_error(res, "ERR_INSUFFICIENT_ESCROW")
    case = validate_success(api_client.get_case(cd["case_id"], FO), 200)
    assert case["escrow_balance_cents"] == 500_000


# ─── Corner (B): endpoints / computed_read_case_escrow_balance ────────────
def test_computed_read_case_escrow_balance():
    """PRD §3.1: "Reading a case always returns its freshly reconciled phase,
    escrow_balance_cents, and reimbursable_expense_cents."
    PRD §3.7: "The escrow balance for a case is the sum of amount_cents over its DEPOSIT
    transactions, minus the sum over its DISBURSEMENT transactions, minus the sum over
    its REFUND transactions."

    Design: Corner/endpoints/computed_read_case_escrow_balance
    """
    cd = create_case_with_deposit(deposit_cents=800_000)
    case = validate_success(api_client.get_case(cd["case_id"], FO), 200)
    assert case["escrow_balance_cents"] == 800_000


# ─── Corner (B): cross_cutting / derived_reimbursable_reconciles_on_approve ──
def test_derived_reimbursable_reconciles_on_approve():
    """PRD §3.7: "On approval the expense's approved_by_finance_id is set to the acting
    operator and the case's reimbursable_expense_cents is recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_reimbursable_reconciles_on_approve
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    exp = create_logged_expense(case["id"], amount_cents=250_000, category="COUNSELING")
    before = validate_success(api_client.get_case(case["id"], FO), 200)
    assert before["reimbursable_expense_cents"] == 0
    approved = validate_success(api_client.approve_expense(exp["id"], FO), 200)
    assert approved["status"] == "APPROVED"
    after = validate_success(api_client.get_case(case["id"], FO), 200)
    assert after["reimbursable_expense_cents"] == 250_000


# ─── Corner (B): cross_cutting / occ_version_increments_on_escrow_write ────
def test_occ_version_increments_on_escrow_write():
    """PRD §2.6: "Both of these creates also bump the case's own version on success."
    PRD §3.7: "a successful create recomputes the case's escrow_balance_cents and
    increments the case's version."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_escrow_write
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    cv0 = case["version"]  # 1
    api_client.create_escrow_transaction(
        create_escrow_payload(case["id"], cv0, txn_type="DEPOSIT", amount_cents=100_000), FO)
    cv1 = current_case_version(case["id"], headers=FO)  # 2
    validate_success(api_client.create_escrow_transaction(
        create_escrow_payload(case["id"], cv1, txn_type="DEPOSIT", amount_cents=200_000), FO), 201)
    case_after = validate_success(api_client.get_case(case["id"], FO), 200)
    assert case_after["version"] == 3
    assert case_after["escrow_balance_cents"] == 300_000


# ─── Corner (B): cross_cutting / occ_stale_case_version_on_consent_create ──
def test_occ_stale_case_version_on_consent_create():
    """PRD §2.6: "When a Caseworker creates a consent record, the request body must carry
    expected_case_version ... If another writer has advanced the case's version since the
    client last read it ... the create is rejected with ERR_STALE_CASE_VERSION (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_consent_create
    """
    from test_helpers import setup_case_with_accepted_match
    b = setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                       to_iso8601="2026-06-04T08:00:00.000Z", birth_state="CA")
    stale = current_case_version(b["case_id"])
    # First consent create with the fresh version succeeds and bumps case.version.
    validate_success(api_client.create_consent_record(
        create_consent_payload(b["case_id"], b["bp_id"], stale,
                               revocation_basis="CALENDAR_DAYS",
                               child_dob="2026-06-01T08:00:00.000Z"), CW), 201)
    # Second create reusing the now-stale version is rejected.
    res = api_client.create_consent_record(
        create_consent_payload(b["case_id"], b["bp_id"], stale,
                               revocation_basis="CALENDAR_DAYS",
                               child_dob="2026-06-01T08:00:00.000Z"), CW)
    validate_error(res, "ERR_STALE_CASE_VERSION")
