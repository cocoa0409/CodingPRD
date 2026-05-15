"""Amendment cycle, withdrawal, and the depth-≥3 release cascade
(PRD §3.6, §3.10, §3.11, §2.8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    action_with_version_payload,
    advance_clock_to,
    api_client,
    create_declaration,
    emit_customs_response,
    locate_settlement_for_declaration,
    pre_validate_declaration,
    request_documents,
    reset_clock_to_epoch,
    setup_active_agreement,
    setup_declaration_in_amending,
    setup_declaration_in_filed,
    setup_declaration_in_rejected_via_emit,
    setup_declaration_released_via_emit,
    setup_settlement_in_advanced,
    validate_error,
    validate_success,
    withdraw_declaration,
)


# ===========================================================================
# §3.11 — Amendment lifecycle
# ===========================================================================
class TestAmendmentCycle:

    def test_amend_increments_count_and_clears_pin(self, api):
        """PRD §3.11: "The amendment transition increments amendment_count
        by one, clears rejection_reason_code, and clears
        pinned_agreement_version (forcing the next pre-validate to
        re-snapshot the agreement's version)."

        Claim: after amend, amendment_count goes from 0 to 1,
        rejection_reason_code is None, pinned_agreement_version is None.
        """
        ctx = setup_declaration_in_amending(reason_code="HS_MISMATCH")
        dec = ctx["declaration"]
        assert dec["status"] == "AMENDING"
        assert dec["amendment_count"] == 1
        assert dec.get("rejection_reason_code") in (None, "")
        assert dec.get("pinned_agreement_version") in (None,)

    def test_amend_cap_reached_blocks_fourth_amendment(self, api):
        """PRD §3.11: "The amendment cap is hard: a declaration whose
        amendment_count has already reached 3 cannot amend further and
        is rejected with ERR_AMENDMENT_CAP_REACHED."

        Claim: walk the full reject→amend→file→reject loop 3 times,
        then attempt a 4th amend → ERR_AMENDMENT_CAP_REACHED.

        Recipe (each lap):
          - amend (REJECTED → AMENDING; amendment_count++)
          - pre-validate (AMENDING → PRE_VALIDATED)
          - file (PRE_VALIDATED → FILED)
          - emit REJECT via _events/emit
        """
        from test_helpers import (
            attach_core_docs, file_declaration, pre_validate_declaration,
        )
        # Start: reject after first filing.
        ctx = setup_declaration_in_rejected_via_emit(reason_code="HS_MISMATCH")
        dec = ctx["declaration"]
        # Cycle 1 → 3 amendments.
        for cycle in range(3):
            # amend
            amended = validate_success(api.amend_declaration(
                dec["id"], action_with_version_payload(version=dec["version"]),
                TEST_USERS["declaration_officer_headers"],
            ))
            assert amended["amendment_count"] == cycle + 1
            # pre-validate (uses fresh DocReviewer id per cycle to avoid SoD collision)
            from test_helpers import make_doc_reviewer_headers, make_filing_officer_headers
            reviewer = make_doc_reviewer_headers(f"doc-reviewer-cycle-{cycle}")
            pre = validate_success(api.pre_validate_declaration(
                amended["id"],
                action_with_version_payload(version=amended["version"]),
                reviewer,
            ))
            # file
            filer = make_filing_officer_headers(f"filing-officer-cycle-{cycle}")
            filed = validate_success(api.file_declaration(
                pre["id"],
                action_with_version_payload(version=pre["version"]),
                filer,
            ))
            # Re-read to discover the new filing's id.
            from test_helpers import get_filing_for_declaration
            filing = filed.get("filing") if isinstance(filed, dict) else None
            if not (isinstance(filing, dict) and "id" in filing):
                filing = get_filing_for_declaration(filed["id"])
            assert filing is not None
            # emit REJECT
            emit_customs_response(filing["id"], response_type="REJECT",
                                  reason_code="HS_MISMATCH")
            dec = validate_success(api.get_declaration(
                filed["id"], TEST_USERS["broker_ops_headers"],
            ))
            assert dec["status"] == "REJECTED"

        # 4th amend attempt:
        resp = api.amend_declaration(
            dec["id"], action_with_version_payload(version=dec["version"]),
            TEST_USERS["declaration_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_CAP_REACHED.value)


# ===========================================================================
# §3.6 / §2.8 — Agreement version drift between pre-validate and file
# ===========================================================================
class TestAgreementVersionDrift:

    # DELETED test_agreement_mutated_between_prevalidate_and_file_rejects —
    # PRD §3.6 names ERR_AGREEMENT_VERSION_DRIFT but exposes no API-reachable
    # path that bumps agreement.version after activation without also
    # changing its status (which would fire a higher-priority error). The
    # asserted scenario is unreachable under any PRD-faithful setup.
    # Fails STEP 1b unique-derivability / skipped-as-failed.
    pass


# ===========================================================================
# §3.11 — Withdrawal
# ===========================================================================
class TestWithdrawal:

    def test_withdraw_from_draft(self, api):
        """PRD §3.11: "Withdrawal is reachable from DRAFT (when no filing
        yet exists) and from REJECTED (when a RejectionRecord exists for
        the declaration). It is performed by a BrokerOps operator".

        Claim: withdraw a DRAFT declaration → status=WITHDRAWN.
        """
        _, agreement = setup_active_agreement()
        dec = create_declaration(agreement["id"])
        result = withdraw_declaration(dec)
        assert result["status"] == "WITHDRAWN"

    def test_withdraw_from_rejected(self, api):
        """PRD §3.11: "Withdrawal is reachable from ... REJECTED (when a
        RejectionRecord exists for the declaration)."

        Claim: withdraw a REJECTED declaration → status=WITHDRAWN.
        """
        ctx = setup_declaration_in_rejected_via_emit(reason_code="HS_MISMATCH")
        result = withdraw_declaration(ctx["declaration"])
        assert result["status"] == "WITHDRAWN"

    def test_withdraw_blocked_when_settlement_advanced(self, api):
        """PRD §3.11: "It ... is blocked when any Settlement for the
        declaration is in ADVANCED or REIMBURSED status; the rejection
        code is ERR_SETTLEMENT_HAS_ADVANCE."

        Recipe: declaration → RELEASED → Settlement ADVANCED, then try
        to withdraw. The withdraw endpoint is reachable from REJECTED
        and DRAFT only, so an ADVANCED settlement only matters when the
        declaration is post-INSPECTING-PENALTY-REJECTED. We construct
        that path: INSPECTING → PENALTY → declaration=REJECTED + FINAL
        settlement → /advance → ADVANCED, then attempt withdrawal.

        Claim: withdrawal on a declaration with an ADVANCED settlement
        → ERR_SETTLEMENT_HAS_ADVANCE.
        """
        from test_helpers import (
            advance_settlement, record_inspection_outcome,
            setup_inspection_case,
        )
        reset_clock_to_epoch()
        from test_helpers.fixtures import TEST_EPOCH
        # PENALTY outcome cascades to a FINAL settlement and rejects the
        # declaration with INSPECTION_FAILED. PRD §3.7 says inspection-
        # failed cannot be amended but withdrawal IS permitted (PRD §3.11:
        # "Withdrawal is reachable from REJECTED when a RejectionRecord
        # exists"). So this test exercises the cross-entity gate.
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - timedelta(hours=1),
            default_settlement_currency="CNY",
            declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        settlement = locate_settlement_for_declaration(dec["id"])
        assert settlement is not None
        # Advance — use a SettlementOfficer id different from FILING_OFFICER_ID.
        advance_settlement(settlement, officer_id="settle-officer-distinct")
        # Withdrawal must now be blocked.
        resp = api.withdraw_declaration(
            dec["id"], action_with_version_payload(version=dec["version"]),
            TEST_USERS["broker_ops_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_HAS_ADVANCE.value)

    def test_withdraw_voids_final_settlement_cascade(self, api):
        """PRD §3.11: "If a Settlement exists for the declaration in
        PROVISIONAL or FINAL status, it is voided (status set to VOIDED)
        as a cascade."

        Recipe: declaration → INSPECTING → PENALTY creates a FINAL
        settlement (not yet advanced); withdraw the declaration → both
        declaration=WITHDRAWN and Settlement=VOIDED.

        Claim: post-withdraw, Settlement.status=VOIDED.
        """
        from test_helpers import (
            record_inspection_outcome, setup_inspection_case,
        )
        reset_clock_to_epoch()
        from test_helpers.fixtures import TEST_EPOCH
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - timedelta(hours=1),
            default_settlement_currency="CNY",
            declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        # Withdraw (FINAL settlement exists, not advanced yet).
        withdrawn = withdraw_declaration(dec)
        assert withdrawn["status"] == "WITHDRAWN"
        # Re-read settlement.
        settlement = locate_settlement_for_declaration(dec["id"])
        assert settlement is not None
        assert settlement["status"] == "VOIDED", (
            f"Settlement must be VOIDED after withdrawal cascade; got "
            f"{settlement['status']}"
        )


# ===========================================================================
# §2.8 / §3.6 — RELEASE cascade depth ≥ 3 + audit logging
# ===========================================================================
class TestReleaseCascade:

    def test_release_creates_final_settlement(self, api):
        """PRD §3.6: "A RELEASE response advances the declaration to
        RELEASED ..." and PRD §3.8: "The cascade from RELEASED (whether
        reached via the post-filing RELEASE response or via the
        post-inspection RELEASE outcome) creates a Settlement carrying
        the parent declaration_id".

        Claim: emit RELEASE on MATCHED filing → declaration=RELEASED AND
        a Settlement is auto-created in FINAL status.
        """
        ctx = setup_declaration_released_via_emit()
        assert ctx["declaration"]["status"] == "RELEASED"
        assert ctx["settlement"] is not None
        assert ctx["settlement"]["status"] == "FINAL"

    def test_audit_log_records_state_transition(self, api, broker_ops_headers):
        """PRD §2.8: "The single most important rule is that every
        state-changing action writes an AuditLog row with entity_type set
        to one of DECLARATION, SETTLEMENT, FILING, INSPECTION_CASE, or
        AGREEMENT, with entity_id set to the affected resource's id, and
        with event_type drawn from STATE_TRANSITION, FIELD_CHANGE,
        ADVANCE_PAID, REIMBURSED, AMENDMENT_FILED, and VOUCHER_DELIVERED."

        Claim: after declaration RELEASE, the audit log contains at
        least one STATE_TRANSITION entry for the declaration.
        """
        ctx = setup_declaration_released_via_emit()
        dec_id = ctx["declaration"]["id"]
        resp = api.list_audit_log(
            broker_ops_headers,
            params={"entity_id": dec_id, "event_type": "STATE_TRANSITION"},
        )
        body = validate_success(resp)
        rows = body if isinstance(body, list) else (
            body.get("items") or body.get("data") or body.get("audit_log") or []
        )
        if not isinstance(rows, list):
            rows = []
        assert len(rows) >= 1, "Declaration RELEASE must produce a STATE_TRANSITION audit row"
