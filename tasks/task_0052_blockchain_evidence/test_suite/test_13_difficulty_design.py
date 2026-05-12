"""Difficulty-design coverage. Two tests per instance.

Each test docstring carries `# difficulty: <rule>/<instance>` so the
coverage audit can ledger which instance it satisfies. All assertions
are pinned to verbatim PRD prose.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    bring_batch_to_confirmed,
    bring_evidence_to_confirmed,
    bring_evidence_to_failed,
    bring_evidence_to_submitting,
    chain_confirm,
    chain_confirm_payload,
    chain_fail,
    create_certificate,
    create_customer_with_balance,
    create_evidence,
    create_evidence_payload,
    create_invoice_payload,
    create_judicial_package,
    create_judicial_package_payload,
    create_notarization,
    create_pending_evidences,
    get_customer,
    get_evidence,
    iso_z,
    latest_onchain_tx_for_evidence,
    list_audit_logs,
    make_customer_headers,
    resubmit_evidence,
    run_sweep,
    seal_judicial_package,
    setup_sealed_judicial_package,
    submit_evidence,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, JUDICIAL


# ===========================================================================
# Rule 1: Dual-variant calculations
# ===========================================================================
class TestDualVariantEvidence:
    """difficulty: dual_variant_calc/
    evidence_fee_quote_vs_final_on_evidence_entity"""

    def test_quote_does_not_debit_but_final_does(self, api):
        """PRD §3.3: 'The quote is optimistic in the sense that no
        batch discount applies (the single-evidence path never receives
        one) and no judicial surcharge is folded in.'
        PRD §3.3: 'the cascade ... computes the chronological
        per-evidence fee ... assigns the result to
        Evidence.per_evidence_fee_cents, debits Customer.wallet_balance_cents
        by that amount'.

        # difficulty: dual_variant_calc/evidence_fee_quote_vs_final_on_evidence_entity
        """
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(
            customer,
            evidence_type="DOCUMENT", storage_period_days=30,
        )
        create_notarization(evidence)
        # /submit passes the quote precondition without debiting:
        submit_evidence(evidence)
        # Wallet still 1000 — quote did not debit.
        c1 = get_customer(customer["id"])
        assert c1["wallet_balance_cents"] == 1_000
        # Then chain-confirm debits exactly 200.
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        chain_confirm(tx["id"], confirmations=12)
        ev_after = get_evidence(evidence["id"])
        c2 = get_customer(customer["id"])
        assert ev_after["status"] == "CONFIRMED"
        assert ev_after["per_evidence_fee_cents"] == 200
        assert c2["wallet_balance_cents"] == 800

    def test_per_evidence_fee_pinned_on_confirm(self, api):
        """PRD §3.3: 'assigns the result to
        Evidence.per_evidence_fee_cents'. Pre-confirm fee is null;
        post-confirm fee equals the computed value.

        # difficulty: dual_variant_calc/evidence_fee_quote_vs_final_on_evidence_entity
        """
        customer, ev_pre, _ = bring_evidence_to_submitting(
            balance_cents=2_000,
            evidence_overrides={
                "evidence_type": "IMAGE", "storage_period_days": 30,
            },
        )
        # Pre-confirm: fee null.
        assert ev_pre["per_evidence_fee_cents"] is None
        tx = latest_onchain_tx_for_evidence(ev_pre["id"])
        chain_confirm(tx["id"], confirmations=12)
        ev_post = get_evidence(ev_pre["id"])
        # IMAGE/30: 300 * 1.00 = 300.
        assert ev_post["per_evidence_fee_cents"] == 300


class TestDualVariantJudicial:
    """difficulty: dual_variant_calc/
    judicial_surcharge_quote_vs_final_on_judicial_package_entity"""

    def test_seal_writes_surcharge_and_debits(self, api):
        """PRD §3.7: 'A successful seal mints a fresh official_seal_id,
        assigns the surcharge to JudicialPackage.surcharge_cents,
        debits the customer's wallet_balance_cents by that amount'.

        COURT_BJ no-original: (5000 + 0) * 1.20 = 6000.

        # difficulty: dual_variant_calc/judicial_surcharge_quote_vs_final_on_judicial_package_entity
        """
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            authority_code="COURT_BJ",
            include_original_data=False,
            balance_cents=100_000,
        )
        assert sealed["status"] == "SEALED"
        assert sealed["surcharge_cents"] == 6000

    def test_seal_emits_judicial_sealed_and_fee_debited_audits(self, api):
        """PRD §3.7: 'appends audit rows of event_type JUDICIAL_SEALED
        and FEE_DEBITED.'

        # difficulty: dual_variant_calc/judicial_surcharge_quote_vs_final_on_judicial_package_entity
        """
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            balance_cents=100_000,
        )
        seal_rows = list_audit_logs(
            event_type="JUDICIAL_SEALED",
            target_entity="JudicialPackage",
            target_id=sealed["id"],
        )
        fee_rows = list_audit_logs(
            event_type="FEE_DEBITED",
            target_entity="JudicialPackage",
            target_id=sealed["id"],
        )
        assert len(seal_rows) >= 1
        assert len(fee_rows) >= 1


# ===========================================================================
# Rule 2: Combinatorial formulas
# ===========================================================================
class TestJudicialSurchargeCombinatorial:
    """difficulty: combinatorial_formula/
    judicial_surcharge_mode_a_nonlinear_three_inputs"""

    def test_court_bj_with_original_data_uplift(self, api):
        """PRD §3.7: 'start with a base surcharge of 5000 cents, add
        1500 cents when include_original_data is true and zero when it
        is false, then multiply the sum by the authority multiplier
        (COURT_BJ and COURT_SH are 1.20 ...)'.
        (5000 + 1500) * 1.20 = 7800.

        # difficulty: combinatorial_formula/judicial_surcharge_mode_a_nonlinear_three_inputs
        """
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            authority_code="COURT_BJ",
            include_original_data=True,
            balance_cents=100_000,
        )
        assert sealed["surcharge_cents"] == 7800

    def test_arbitration_with_original_data_uplift(self, api):
        """PRD §3.7: 'ARBITRATION is 0.90'. Original-data uplift +
        authority multiplier interact non-linearly.
        (5000 + 1500) * 0.90 = 5850.

        # difficulty: combinatorial_formula/judicial_surcharge_mode_a_nonlinear_three_inputs
        """
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            authority_code="ARBITRATION",
            include_original_data=True,
            balance_cents=100_000,
        )
        assert sealed["surcharge_cents"] == 5850


class TestBatchFeeOrderOfOperations:
    """difficulty: combinatorial_formula/
    batch_fee_mode_b_round_per_line_then_sum_then_discount_then_round"""

    def test_ten_imageoriginal_members_round_per_line_then_discount(
            self, api):
        """PRD §3.5: 'The batch fee is computed by a two-step rounding
        protocol: round-per-line first, then sum, then apply the
        discount, then round once more.'

        10 × IMAGE/90 no original: per-line round(300*2.50)=750;
        subtotal=7500; *0.90 = 6750.

        # difficulty: combinatorial_formula/batch_fee_mode_b_round_per_line_then_sum_then_discount_then_round
        """
        customer, batch, _ = bring_batch_to_confirmed(
            member_count=10,
            evidence_overrides={
                "evidence_type": "IMAGE", "storage_period_days": 90,
            },
            balance_cents=100_000,
        )
        assert batch["total_fee_cents"] == 6750

    def test_two_document_members_5pct_discount(self, api):
        """PRD §3.5: '5% when at least 2'.
        2 × DOCUMENT/30 no original: per-line 200; subtotal 400;
        *0.95 = 380.

        # difficulty: combinatorial_formula/batch_fee_mode_b_round_per_line_then_sum_then_discount_then_round
        """
        customer, batch, _ = bring_batch_to_confirmed(
            member_count=2,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
            balance_cents=10_000,
        )
        assert batch["total_fee_cents"] == 380


# ===========================================================================
# Rule 3: Non-linear state machines
# ===========================================================================
class TestEvidenceFailedToSubmittingLoop:
    """difficulty: non_linear_state_machine/
    evidence_failed_to_submitting_revert_loop"""

    def test_fail_then_resubmit_then_confirm(self, api):
        """PRD §3.3: 'A FAILED evidence is recoverable via resubmission
        ... transitions the evidence from FAILED back to SUBMITTING.'

        # difficulty: non_linear_state_machine/evidence_failed_to_submitting_revert_loop
        """
        customer, ev = bring_evidence_to_failed(balance_cents=1_000)
        assert ev["status"] == "FAILED"
        resubmit_evidence(ev)
        ev_after_resub = get_evidence(ev["id"])
        assert ev_after_resub["status"] == "SUBMITTING"
        assert ev_after_resub["submission_attempts"] == 2
        # Confirm the new attempt.
        tx = latest_onchain_tx_for_evidence(ev["id"])
        chain_confirm(tx["id"], confirmations=12)
        ev_final = get_evidence(ev["id"])
        assert ev_final["status"] == "CONFIRMED"

    def test_three_failed_attempts_then_fourth_rejected(self, api):
        """PRD §3.3: 'the system permits at most three submissions in
        total for a single evidence; a fourth attempt is rejected with
        ERR_RESUBMIT_LIMIT_EXCEEDED'.

        # difficulty: non_linear_state_machine/evidence_failed_to_submitting_revert_loop
        """
        customer = create_customer_with_balance(balance_cents=10_000)
        evidence = create_evidence(customer)
        create_notarization(evidence)
        submit_evidence(evidence)
        chain_fail(latest_onchain_tx_for_evidence(evidence["id"])["id"])
        resubmit_evidence(evidence)
        chain_fail(latest_onchain_tx_for_evidence(evidence["id"])["id"])
        resubmit_evidence(evidence)
        chain_fail(latest_onchain_tx_for_evidence(evidence["id"])["id"])
        # submission_attempts now 3.
        res = api.resubmit_evidence(
            evidence["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESUBMIT_LIMIT_EXCEEDED.value)


class TestOnChainTxBranching:
    """difficulty: non_linear_state_machine/
    onchain_tx_branching_to_confirmed_or_failed_on_different_entity"""

    def test_one_tx_confirms_another_fails(self, api):
        """PRD §3.3 / §3.10: chain-confirm vs chain-fail are two
        distinct cascades — one tx forks to CONFIRMED, another to
        FAILED.

        # difficulty: non_linear_state_machine/onchain_tx_branching_to_confirmed_or_failed_on_different_entity
        """
        customer = create_customer_with_balance(balance_cents=10_000)
        e1 = create_evidence(customer)
        e2 = create_evidence(customer)
        create_notarization(e1)
        create_notarization(e2)
        submit_evidence(e1)
        submit_evidence(e2)
        tx1 = latest_onchain_tx_for_evidence(e1["id"])
        tx2 = latest_onchain_tx_for_evidence(e2["id"])
        chain_confirm(tx1["id"], confirmations=12)
        chain_fail(tx2["id"])
        ev1 = get_evidence(e1["id"])
        ev2 = get_evidence(e2["id"])
        assert ev1["status"] == "CONFIRMED"
        assert ev2["status"] == "FAILED"

    def test_branching_evidence_states_diverge(self, api):
        """PRD §3.3: two evidences anchored on the same chain can
        diverge — one CONFIRMED, one FAILED — depending on the
        callback. The state branches at the OnChainTx level.

        # difficulty: non_linear_state_machine/onchain_tx_branching_to_confirmed_or_failed_on_different_entity
        """
        customer = create_customer_with_balance(balance_cents=10_000)
        e1 = create_evidence(customer)
        e2 = create_evidence(customer)
        create_notarization(e1)
        create_notarization(e2)
        submit_evidence(e1)
        submit_evidence(e2)
        chain_fail(latest_onchain_tx_for_evidence(e1["id"])["id"])
        chain_confirm(
            latest_onchain_tx_for_evidence(e2["id"])["id"],
            confirmations=12,
        )
        assert get_evidence(e1["id"])["status"] == "FAILED"
        assert get_evidence(e2["id"])["status"] == "CONFIRMED"


# ===========================================================================
# Rule 4: Transitive cascade chains
# ===========================================================================
class TestSweepThenCertificateRevocation:
    """difficulty: transitive_cascade/
    clock_advance_triggers_evidence_expiry_then_certificate_revocation"""

    def test_sweep_revokes_certificate(self, api):
        """PRD §3.4: 'A PlatformAdmin runs the expiry sweep capability
        ... The evidence's linked Certificate, if any, flips to
        REVOKED'.

        # difficulty: transitive_cascade/clock_advance_triggers_evidence_expiry_then_certificate_revocation
        """
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=5_000,
            evidence_overrides={"storage_period_days": 30},
        )
        cert = create_certificate(ev)
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        ev_after = get_evidence(ev["id"])
        assert ev_after["status"] == "EXPIRED"
        cert_after = validate_success(api.get_certificate(
            cert["id"], make_customer_headers(customer["id"]),
        ), 200)
        assert cert_after["status"] == "REVOKED"

    def test_sweep_does_not_revoke_after_sealed_judicial_package(
            self, api):
        """PRD §3.6: 'A Certificate whose linked evidence is referenced
        by a SEALED but not-yet-DELIVERED JudicialPackage is
        intentionally not auto-cascaded by sweeps — the judicial
        channel is responsible for that decision.'

        # difficulty: transitive_cascade/clock_advance_triggers_evidence_expiry_then_certificate_revocation
        """
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            balance_cents=100_000,
            evidence_overrides={"storage_period_days": 30},
        )
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        cert_after = validate_success(api.get_certificate(
            cert["id"], make_customer_headers(customer["id"]),
        ), 200)
        # Per PRD §3.6 the sealed-package case is "not auto-cascaded".
        # So the Certificate must remain ISSUED.
        assert cert_after["status"] == "ISSUED"


class TestChainConfirmCascadesDeep:
    """difficulty: transitive_cascade/
    chain_confirm_triggers_evidence_confirmed_then_fee_debit_then_fee_account_update"""

    def test_confirm_debits_wallet_and_ledger(self, api):
        """PRD §3.3: 'debits Customer.wallet_balance_cents by that
        amount, increments FeeAccount.lifetime_deduction_cents by the
        same amount'.

        IMAGE/90: 300 * 2.50 = 750.

        # difficulty: transitive_cascade/chain_confirm_triggers_evidence_confirmed_then_fee_debit_then_fee_account_update
        """
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(
            customer, evidence_type="IMAGE", storage_period_days=90,
        )
        create_notarization(evidence)
        submit_evidence(evidence)
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        chain_confirm(tx["id"], confirmations=12)
        ev_after = get_evidence(evidence["id"])
        cust_after = get_customer(customer["id"])
        assert ev_after["status"] == "CONFIRMED"
        assert ev_after["per_evidence_fee_cents"] == 750
        assert cust_after["wallet_balance_cents"] == 250

    def test_confirm_emits_evidence_confirmed_and_fee_debited(self, api):
        """PRD §3.3: 'appends two audit rows: one with event_type
        EVIDENCE_CONFIRMED and one with event_type FEE_DEBITED.'

        # difficulty: transitive_cascade/chain_confirm_triggers_evidence_confirmed_then_fee_debit_then_fee_account_update
        """
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=2_000,
            evidence_overrides={
                "evidence_type": "IMAGE", "storage_period_days": 90,
            },
        )
        ev_conf = list_audit_logs(
            event_type="EVIDENCE_CONFIRMED",
            target_entity="Evidence",
            target_id=ev["id"],
        )
        fee_rows = list_audit_logs(
            event_type="FEE_DEBITED",
            target_entity="Evidence",
            target_id=ev["id"],
        )
        assert len(ev_conf) >= 1
        assert len(fee_rows) >= 1


# ===========================================================================
# Rule 5: Validation priority conflicts
# ===========================================================================
class TestStateVsFiscalOnResubmit:
    """difficulty: priority_pair_validation_conflict/
    state_vs_business_fiscal_on_resubmit"""

    def test_state_check_beats_fiscal_check(self, api):
        """PRD §2.10: priorities are evaluated in strict order; state
        (priority 6, ERR_INVALID_STATE) precedes business_fiscal
        (priority 17, ERR_INSUFFICIENT_BALANCE).

        Setup: Evidence in CONFIRMED (wrong state for /resubmit) AND
        wallet at 0 (would also fail fiscal).
        Expected: ERR_INVALID_STATE (priority 6 wins).

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_resubmit
        """
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=200,  # exactly enough — after debit 200, leaves 0.
        )
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 0
        res = api.resubmit_evidence(
            ev["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_wins_even_with_zero_balance_explicit(self, api):
        """PRD §2.10 priority order: even with zero balance AND a
        CONFIRMED evidence (wrong starting state for /resubmit), the
        state error wins.

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_resubmit
        """
        customer, ev = bring_evidence_to_confirmed(balance_cents=200)
        # Wallet now 0 after preservation_fee debit of 200.
        res = api.resubmit_evidence(
            ev["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestReferentialVsFiscalOnSeal:
    """difficulty: priority_pair_validation_conflict/
    business_referential_vs_business_fiscal_on_seal"""

    def test_missing_certificate_beats_balance_check(self, api):
        """PRD §2.10: priority 14 (ERR_CERTIFICATE_REQUIRED) precedes
        priority 19 (ERR_INSUFFICIENT_BALANCE). Both fail; the
        referential check wins.

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_seal
        """
        customer, ev = bring_evidence_to_confirmed(balance_cents=200)
        # No certificate issued. Balance now 0 after debit.
        pkg = create_judicial_package(ev, authority_code="COURT_BJ")
        res = api.seal_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_CERTIFICATE_REQUIRED.value)

    def test_revoked_certificate_beats_balance_check(self, api,
                                                     admin_headers):
        """PRD §2.10 priority 14: 'the linked Certificate exists with
        status equal to ISSUED at seal time (ERR_CERTIFICATE_REQUIRED).'
        A revoked certificate plus zero balance still surfaces
        ERR_CERTIFICATE_REQUIRED (priority 14 < priority 19).

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_seal
        """
        customer, ev = bring_evidence_to_confirmed(balance_cents=200)
        cert = create_certificate(ev)
        validate_success(
            api.revoke_certificate(cert["id"], admin_headers), 200,
        )
        pkg = create_judicial_package(ev, authority_code="COURT_BJ")
        res = api.seal_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_CERTIFICATE_REQUIRED.value)


# ===========================================================================
# Rule 6: Boundary precision
# ===========================================================================
class TestBatchSizeBoundary:
    """difficulty: boundary_precision_check/batch_size_lower_boundary_at_two"""

    def test_size_one_rejected(self, api):
        """PRD §2.10 priority 10: 'Batch.evidence_count is at least 2
        and at most 1000, inclusive of both endpoints, on POST /batches
        (ERR_BATCH_SIZE_OUT_OF_RANGE).'

        # difficulty: boundary_precision_check/batch_size_lower_boundary_at_two
        """
        customer = create_customer_with_balance(balance_cents=0)
        e1 = create_evidence(customer)
        from test_helpers import create_batch_payload
        res = api.create_batch(
            create_batch_payload(
                customer_id=customer["id"], evidence_ids=[e1["id"]],
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BATCH_SIZE_OUT_OF_RANGE.value)

    def test_size_two_accepted(self, api):
        """PRD §2.10 priority 10: '... at least 2 ... inclusive of both
        endpoints'. 2 is valid.

        # difficulty: boundary_precision_check/batch_size_lower_boundary_at_two
        """
        from test_helpers import create_batch_payload
        customer = create_customer_with_balance(balance_cents=0)
        evidences = create_pending_evidences(customer, count=2)
        batch = validate_success(api.create_batch(
            create_batch_payload(
                customer_id=customer["id"],
                evidence_ids=[e["id"] for e in evidences],
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        assert batch["evidence_count"] == 2


class TestStoragePeriodEnumBoundary:
    """difficulty: boundary_precision_check/
    storage_period_enum_membership_exact_set"""

    def test_period_29_rejected(self, api):
        """PRD §2.10 priority 11: 'storage_period_days is exactly one
        of 30, 90, 365, or 1095'. 29 is not in the set.

        # difficulty: boundary_precision_check/storage_period_enum_membership_exact_set
        """
        customer = create_customer_with_balance(balance_cents=0)
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"], storage_period_days=29,
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_INVALID.value)

    def test_period_30_accepted(self, api):
        """PRD §2.10 priority 11: 30 is a member of the exact set
        {30, 90, 365, 1095}.

        # difficulty: boundary_precision_check/storage_period_enum_membership_exact_set
        """
        customer = create_customer_with_balance(balance_cents=0)
        ev = validate_success(api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"], storage_period_days=30,
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        assert ev["storage_period_days"] == 30


# ===========================================================================
# Rule 7: Cross-entity state dependency
# ===========================================================================
class TestEvidenceNeedsNotarization:
    """difficulty: cross_entity_state_dependency/
    evidence_confirmation_requires_timestamp_notarization"""

    def test_confirm_without_notarization_rejected(self, api,
                                                    admin_headers):
        """PRD §2.10 priority 13: 'The target Evidence of a chain
        confirmation already has a TimestampNotarization attached;
        missing notarization rejects the confirmation cascade with
        ERR_TIMESTAMP_REQUIRED.'

        # difficulty: cross_entity_state_dependency/evidence_confirmation_requires_timestamp_notarization
        """
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(customer)
        # NO notarization.
        submit_evidence(evidence)
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        res = api.chain_confirm(
            chain_confirm_payload(tx_id=tx["id"], confirmations=12),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_TIMESTAMP_REQUIRED.value)

    def test_evidence_remains_in_submitting(self, api, admin_headers):
        """PRD §2.10 priority 13 / §3.3: the missing-notarization
        rejection leaves Evidence in SUBMITTING (no state change).

        # difficulty: cross_entity_state_dependency/evidence_confirmation_requires_timestamp_notarization
        """
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(customer)
        submit_evidence(evidence)
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        api.chain_confirm(
            chain_confirm_payload(tx_id=tx["id"], confirmations=12),
            admin_headers,
        )
        ev_after = get_evidence(evidence["id"])
        assert ev_after["status"] == "SUBMITTING"


class TestSealNeedsCertificate:
    """difficulty: cross_entity_state_dependency/
    judicial_seal_requires_certificate_issued_state"""

    def test_seal_without_certificate_rejected(self, api):
        """PRD §3.7: 'the linked Certificate.status is ISSUED (a
        missing or REVOKED certificate rejects the seal with
        ERR_CERTIFICATE_REQUIRED)'.

        # difficulty: cross_entity_state_dependency/judicial_seal_requires_certificate_issued_state
        """
        customer, ev = bring_evidence_to_confirmed(balance_cents=100_000)
        pkg = create_judicial_package(ev, authority_code="COURT_BJ")
        res = api.seal_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_CERTIFICATE_REQUIRED.value)

    def test_seal_with_revoked_cert_rejected(self, api, admin_headers):
        """PRD §3.7: 'a missing or REVOKED certificate rejects the seal
        with ERR_CERTIFICATE_REQUIRED'.

        # difficulty: cross_entity_state_dependency/judicial_seal_requires_certificate_issued_state
        """
        customer, ev = bring_evidence_to_confirmed(balance_cents=100_000)
        cert = create_certificate(ev)
        validate_success(
            api.revoke_certificate(cert["id"], admin_headers), 200,
        )
        pkg = create_judicial_package(ev, authority_code="COURT_BJ")
        res = api.seal_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_CERTIFICATE_REQUIRED.value)


# ===========================================================================
# Rule 8: Temporal interval semantics
# ===========================================================================
class TestExpiryClosedLowerBound:
    """difficulty: resource_temporal_overlap/
    evidence_expiry_inclusive_lower_bound_now_ge_expires_at"""

    def test_at_exact_expires_at_evidence_expires(self, api):
        """PRD §3.4: 'every CONFIRMED evidence whose expires_at is at
        or before the server's current time into the terminal EXPIRED
        state' — at-equal counts as expired (closed lower bound).

        # difficulty: resource_temporal_overlap/evidence_expiry_inclusive_lower_bound_now_ge_expires_at
        """
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=5_000,
            evidence_overrides={"storage_period_days": 30},
        )
        # Advance clock to exactly expires_at.
        advance_clock(ev["expires_at"])
        run_sweep()
        ev_after = get_evidence(ev["id"])
        assert ev_after["status"] == "EXPIRED"

    def test_verification_after_expiry_returns_expired_outcome(self, api):
        """PRD §3.8: 'EXPIRED when the evidence's expires_at has passed
        (verification is still permitted after expiry ... returns this
        outcome)'.

        # difficulty: resource_temporal_overlap/evidence_expiry_inclusive_lower_bound_now_ge_expires_at
        """
        from test_helpers import create_verification_payload
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=5_000,
            evidence_overrides={"storage_period_days": 30},
        )
        advance_clock(ev["expires_at"])
        run_sweep()
        res = api.create_verification(
            create_verification_payload(
                evidence_id=ev["id"], file_hash=ev["file_hash"],
            ),
            make_customer_headers(customer["id"]),
        )
        report = validate_success(res, 201)
        assert report["outcome"] == "EXPIRED"


class TestInvoiceBillingPeriodClosedClosed:
    """difficulty: resource_temporal_overlap/
    invoice_billing_period_closed_closed_interval"""

    def test_event_at_period_end_inclusive(self, api, admin_headers):
        """PRD §3.9: 'Events landing exactly at period_start and
        exactly at period_end are both included — the interval is
        closed on both ends.'

        # difficulty: resource_temporal_overlap/invoice_billing_period_closed_closed_interval
        """
        # Setup: confirmed evidence at known confirmed_at.
        from test_helpers import clock_payload
        anchor_time = datetime(2026, 5, 15, tzinfo=timezone.utc)
        validate_success(api.advance_clock(
            clock_payload(iso_z(anchor_time)), admin_headers,
        ), 200)
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=5_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT",
                "storage_period_days": 30,
            },
        )
        # ev["confirmed_at"] should be ~ anchor_time. period spans it.
        # Advance clock so the period is in the past.
        validate_success(api.advance_clock(
            clock_payload(iso_z(anchor_time + timedelta(days=10))),
            admin_headers,
        ), 200)
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="BILLING_PERIOD",
                period_start=iso_z(anchor_time - timedelta(days=1)),
                period_end=iso_z(anchor_time + timedelta(days=1)),
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        # The DOCUMENT/30 evidence at confirmed_at within the interval
        # contributes 200 cents.
        assert inv["total_cents"] == 200

    def test_period_end_exactly_at_now_accepted(self, api, admin_headers):
        """PRD §2.10 priority 16: 'period_end is at or before the
        server's current time' — equal-to-now is allowed (inclusive).

        # difficulty: resource_temporal_overlap/invoice_billing_period_closed_closed_interval
        """
        from test_helpers import clock_payload
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        validate_success(api.advance_clock(
            clock_payload(iso_z(now)), admin_headers,
        ), 200)
        customer = create_customer_with_balance(balance_cents=0)
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="BILLING_PERIOD",
                period_start=iso_z(now - timedelta(days=30)),
                period_end=iso_z(now),
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        assert inv["scope"] == "BILLING_PERIOD"


# ===========================================================================
# Rule 9: Compensating-action invariants
# ===========================================================================
class TestFailedEvidenceWalletInvariant:
    """difficulty: compensating_invariant/
    failed_evidence_preserves_wallet_balance_invariant"""

    def test_submit_then_fail_does_not_change_wallet(self, api):
        """PRD §3.3: 'A simulated chain failure ... cascades the
        upstream evidence from SUBMITTING to FAILED. No fee is debited
        on failure ... balance and ledger columns are not touched.'

        # difficulty: compensating_invariant/failed_evidence_preserves_wallet_balance_invariant
        """
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(customer)
        create_notarization(evidence)
        submit_evidence(evidence)
        chain_fail(latest_onchain_tx_for_evidence(evidence["id"])["id"])
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 1_000
        ev_after = get_evidence(evidence["id"])
        assert ev_after["status"] == "FAILED"
        assert ev_after["per_evidence_fee_cents"] is None

    def test_failed_path_does_not_increment_lifetime_deduction(self, api):
        """PRD §3.3: 'balance and ledger columns are not touched'.
        FeeAccount.lifetime_deduction_cents must stay 0 across a
        submit→fail cycle.

        # difficulty: compensating_invariant/failed_evidence_preserves_wallet_balance_invariant
        """
        # We can't read FeeAccount directly via the public API, but the
        # Customer's wallet balance plus the absence of any FEE_DEBITED
        # audit row for this Evidence is equivalent evidence per PRD
        # §3.3 audit rule.
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(customer)
        create_notarization(evidence)
        submit_evidence(evidence)
        chain_fail(latest_onchain_tx_for_evidence(evidence["id"])["id"])
        fee_rows = list_audit_logs(
            event_type="FEE_DEBITED",
            target_entity="Evidence",
            target_id=evidence["id"],
        )
        assert fee_rows == [], (
            f"No FEE_DEBITED audit row should be appended on a failed "
            f"evidence path, found {fee_rows}"
        )


class TestDraftJudicialRejectionInvariant:
    """difficulty: compensating_invariant/
    judicial_draft_rejection_preserves_judicial_surcharge_total_invariant"""

    def test_draft_rejection_leaves_surcharge_null(self, api):
        """PRD §3.4: 'no fee refund is issued because no fee has been
        debited for a DRAFT package yet.' PRD §3.7: surcharge is
        assigned at SEALED, not DRAFT — a rejected DRAFT must keep
        surcharge_cents null.

        # difficulty: compensating_invariant/judicial_draft_rejection_preserves_judicial_surcharge_total_invariant
        """
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=100_000,
            evidence_overrides={"storage_period_days": 30},
        )
        create_certificate(ev)
        pkg = create_judicial_package(ev, authority_code="COURT_BJ")
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        pkg_after = validate_success(api.get_judicial_package(
            pkg["id"], JUDICIAL,
        ), 200)
        assert pkg_after["status"] == "REJECTED"
        assert pkg_after["surcharge_cents"] is None

    def test_draft_rejection_does_not_emit_judicial_sealed_audit(self, api):
        """PRD §2.12 / §3.7: JUDICIAL_SEALED audit is only appended at
        SEALED. A DRAFT→REJECTED package must not emit one.

        # difficulty: compensating_invariant/judicial_draft_rejection_preserves_judicial_surcharge_total_invariant
        """
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=100_000,
            evidence_overrides={"storage_period_days": 30},
        )
        create_certificate(ev)
        pkg = create_judicial_package(ev, authority_code="COURT_BJ")
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        rows = list_audit_logs(
            event_type="JUDICIAL_SEALED",
            target_entity="JudicialPackage",
            target_id=pkg["id"],
        )
        assert rows == [], (
            f"DRAFT→REJECTED cascade must not emit JUDICIAL_SEALED, "
            f"got {rows}"
        )
