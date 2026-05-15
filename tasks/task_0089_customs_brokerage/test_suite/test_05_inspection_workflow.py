"""Inspection scheduling, sample provisioning, and outcome handling
(PRD §3.7, §3.11)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    action_with_version_payload,
    advance_clock_to,
    api_client,
    assert_inspection_case,
    iso_utc,
    locate_settlement_for_declaration,
    make_client_user_headers,
    record_inspection_outcome,
    record_outcome_payload,
    reset_clock_to_epoch,
    setup_inspection_case,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import TEST_EPOCH


# ===========================================================================
# §3.7 — InspectionCase creation
# ===========================================================================
class TestInspectionCaseCreation:

    def test_create_inspection_case_initial_state(self, api):
        """PRD §3.7: "A newly-created case is in PENDING outcome with
        sample_provided_at set to null and penalty_amount initialised
        to zero."

        Claim: created InspectionCase has outcome=PENDING,
        sample_provided_at=None, penalty_amount=0.
        """
        ctx = setup_inspection_case(sample_required=False)
        case = ctx["inspection_case"]
        assert case["outcome"] == "PENDING"
        assert case.get("sample_provided_at") is None
        assert case.get("penalty_amount", 0) == 0
        assert_inspection_case(case)


# ===========================================================================
# §3.7 — Outcome RELEASE / DETENTION / PENALTY
# ===========================================================================
class TestInspectionOutcomes:

    def test_outcome_release_advances_declaration_to_released(self, api):
        """PRD §3.7: "A RELEASE outcome advances the declaration from
        INSPECTING to RELEASED and cascades to settlement creation in
        FINAL status with penalty_amount of zero."

        Claim: outcome=RELEASE → declaration=RELEASED, settlement created
        in FINAL with penalty_amount=0.
        """
        reset_clock_to_epoch()
        # scheduled_at must be <= now to satisfy precondition.
        ctx = setup_inspection_case(
            sample_required=False, scheduled_at=TEST_EPOCH - timedelta(hours=1),
        )
        case = ctx["inspection_case"]
        result = record_inspection_outcome(case, outcome="RELEASE")
        assert result["outcome"] == "RELEASE"
        # Refresh declaration.
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        assert dec["status"] == "RELEASED"
        # Verify settlement.
        settlement = locate_settlement_for_declaration(dec["id"])
        assert settlement is not None
        assert settlement["status"] == "FINAL"
        assert settlement.get("penalty_amount", 0) == 0

    def test_outcome_detention_no_settlement_created(self, api):
        """PRD §3.7: "A DETENTION outcome advances the declaration from
        INSPECTING to REJECTED, sets rejection_reason_code to
        INSPECTION_FAILED, creates a RejectionRecord, but does not
        create a settlement."

        Claim: outcome=DETENTION → declaration=REJECTED with
        rejection_reason_code=INSPECTION_FAILED, and no Settlement.
        """
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False, scheduled_at=TEST_EPOCH - timedelta(hours=1),
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="DETENTION")
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        assert dec["status"] == "REJECTED"
        assert dec["rejection_reason_code"] == "INSPECTION_FAILED"
        settlement = locate_settlement_for_declaration(dec["id"])
        assert settlement is None, (
            "DETENTION must NOT cascade to Settlement (PRD §3.7)"
        )

    def test_outcome_penalty_requires_positive_amount(self, api):
        """PRD §3.7: "an optional penalty_amount in declared_currency
        (required when outcome is PENALTY — it must be strictly positive)".

        Claim: outcome=PENALTY without penalty_amount > 0 → ERR_INVALID_INPUT.
        """
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False, scheduled_at=TEST_EPOCH - timedelta(hours=1),
        )
        case = ctx["inspection_case"]
        resp = api.record_inspection_outcome(
            case["id"],
            record_outcome_payload(outcome="PENALTY", version=case["version"]),
            TEST_USERS["inspection_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_outcome_penalty_creates_settlement_with_penalty(self, api):
        """PRD §3.7: "A PENALTY outcome advances the declaration from
        INSPECTING to REJECTED, sets rejection_reason_code to
        INSPECTION_FAILED, creates a RejectionRecord, and cascades to
        settlement creation in FINAL status with penalty_amount populated
        through the penalty-conversion calculation described in §3.8."
        PRD §3.8: "The penalty amount on the settlement, when the cascade
        is driven by an inspection PENALTY outcome, is the inspection
        case's penalty_amount (denominated in declared_currency)
        multiplied by fx_rate_to_settlement and rounded half-up to two
        decimals."

        Claim: outcome=PENALTY with penalty_amount=100 (USD declared,
        CNY settlement, fx=7.20) → Settlement.penalty_amount=720.00.
        """
        reset_clock_to_epoch()
        # Use HS 1000 (not in consumption tax / 8517 lookups) and CNY
        # settlement so fx_rate_to_settlement = 7.20.
        ctx = setup_inspection_case(
            sample_required=False, scheduled_at=TEST_EPOCH - timedelta(hours=1),
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
        assert dec["status"] == "REJECTED"
        assert dec["rejection_reason_code"] == "INSPECTION_FAILED"
        settlement = locate_settlement_for_declaration(dec["id"])
        assert settlement is not None
        assert settlement["status"] == "FINAL"
        assert settlement["penalty_amount"] == pytest.approx(720.00, abs=0.01), (
            f"Expected penalty_amount=720.00 (100 USD * 7.20 fx); got "
            f"{settlement.get('penalty_amount')}"
        )


# ===========================================================================
# §3.7 — Sample provisioning
# ===========================================================================
class TestSampleProvisioning:

    def test_outcome_blocked_when_sample_required_and_missing(self, api):
        """PRD §3.7: "The action is accepted only when the case's outcome
        is still PENDING, when the current instant is at or after
        scheduled_at, and — when sample_required is true — when
        sample_provided_at is non-null."

        Claim: sample_required=true + sample_provided_at=null →
        ERR_INVALID_STATE on record-outcome.
        """
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=True, scheduled_at=TEST_EPOCH - timedelta(hours=1),
        )
        case = ctx["inspection_case"]
        resp = api.record_inspection_outcome(
            case["id"],
            record_outcome_payload(outcome="RELEASE", version=case["version"]),
            TEST_USERS["inspection_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_provide_sample_unblocks_outcome(self, api):
        """PRD §3.7: "If sample_required is true, the client must confirm
        sample provision before the case can be closed; a ClientUser (or
        BrokerOps) invokes the sample-provision capability, which sets
        sample_provided_at to the current instant."

        Claim: ClientUser provides sample (with correct entity-backed
        X-User-ID), then RELEASE outcome succeeds.
        """
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=True, scheduled_at=TEST_EPOCH - timedelta(hours=1),
        )
        case = ctx["inspection_case"]
        # PRD §2.1: ClientUser X-User-ID must equal owning ClientCompany.id.
        client = ctx["client"]
        provide_resp = api.provide_sample(
            case["id"],
            action_with_version_payload(version=case["version"]),
            make_client_user_headers(client["id"]),
        )
        provided = validate_success(provide_resp)
        assert provided.get("sample_provided_at") is not None
        # Now record RELEASE.
        result = record_inspection_outcome(provided, outcome="RELEASE")
        assert result["outcome"] == "RELEASE"


# ===========================================================================
# §3.7 — Inspection-failed declarations cannot be amended
# ===========================================================================
class TestInspectionRejectionNotAmendable:

    def test_amend_after_inspection_failed_rejected(self, api):
        """PRD §3.7: "A declaration rejected due to INSPECTION_FAILED
        cannot be amended — amendment is reserved for paperwork-driven
        rejections, and inspection failures must be withdrawn instead.
        An attempt to amend an inspection-failed declaration is rejected
        with ERR_INSPECTION_REJECTION_NOT_AMENDABLE."

        Claim: declaration rejected via DETENTION → amend →
        ERR_INSPECTION_REJECTION_NOT_AMENDABLE.
        """
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False, scheduled_at=TEST_EPOCH - timedelta(hours=1),
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="DETENTION")
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        assert dec["rejection_reason_code"] == "INSPECTION_FAILED"
        resp = api.amend_declaration(
            dec["id"], action_with_version_payload(version=dec["version"]),
            TEST_USERS["declaration_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_REJECTION_NOT_AMENDABLE.value)
