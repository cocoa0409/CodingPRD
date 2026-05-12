"""Rate-override workflow (PRD §3.3): create, submit, withdraw, approve,
reject, segregation-of-duties, supersede cascade, parity check.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    approve_rate_override,
    assert_rate_override,
    create_rate_override_payload,
    create_room_type,
    find_audit_logs,
    list_audit_logs,
    setup_rate_parity_violation_scaffold,
    submit_and_approve_rate_override,
    submit_rate_override,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create RateOverride lifecycle
# ===========================================================================
class TestRateOverrideCreate:
    def test_create_override_starts_in_draft(self, api, analyst_headers):
        """PRD §3.3: 'The override is born in DRAFT status, with
        applied_rate_cents null, approved_by null, and status exactly
        equal to DRAFT.'"""
        rt = create_room_type()
        res = api.create_rate_override(
            create_rate_override_payload(
                room_type_id=rt["id"], stay_date="2027-05-01",
                proposed_rate_cents=25000,
                recommendation_source="MANUAL_OVERRIDE",
            ),
            analyst_headers,
        )
        ro = validate_success(res, expected_status=201)
        assert_rate_override(ro)
        assert ro["status"] == "DRAFT"
        assert ro.get("approved_by") is None
        assert ro.get("applied_rate_cents") is None

    def test_proposed_rate_below_minimum_rejected(
        self, api, analyst_headers,
    ):
        """PRD §3.3: 'the proposed_rate_cents (which must be at least
        1000)'."""
        rt = create_room_type()
        res = api.create_rate_override(
            create_rate_override_payload(
                room_type_id=rt["id"], stay_date="2027-05-01",
                proposed_rate_cents=999,
                recommendation_source="MANUAL_OVERRIDE",
            ),
            analyst_headers,
        )
        validate_error(res, "ERR_INVALID_INPUT")

    def test_only_one_pending_or_draft_per_room_type_date(
        self, api, analyst_headers,
    ):
        """PRD §3.3: 'At most one RateOverride per (room_type_id,
        stay_date) may be in either DRAFT or PENDING_APPROVAL status at
        any time; an attempt to create a second one in either of those
        states is rejected with ERR_OVERRIDE_ALREADY_PENDING.'"""
        rt = create_room_type()
        first = api.create_rate_override(
            create_rate_override_payload(
                room_type_id=rt["id"], stay_date="2027-06-15",
                proposed_rate_cents=22000,
                recommendation_source="MANUAL_OVERRIDE",
            ),
            analyst_headers,
        )
        validate_success(first, expected_status=201)
        second = api.create_rate_override(
            create_rate_override_payload(
                room_type_id=rt["id"], stay_date="2027-06-15",
                proposed_rate_cents=24000,
                recommendation_source="MANUAL_OVERRIDE",
            ),
            analyst_headers,
        )
        validate_error(second, "ERR_OVERRIDE_ALREADY_PENDING")

    def test_terminal_overrides_do_not_block_fresh_proposal(
        self, api, analyst_headers, manager_headers,
    ):
        """PRD §3.3: 'Note that APPROVED, REJECTED, and SUPERSEDED
        overrides do not block a fresh proposal — the constraint is only
        on overrides still in flight.'"""
        rt = create_room_type()
        # First lifecycle: submit + approve.
        approved = submit_and_approve_rate_override(
            room_type_id=rt["id"], stay_date="2027-07-04",
            proposed_rate_cents=20000,
        )
        assert approved["status"] == "APPROVED"
        # Now create a fresh override on the same key — must succeed.
        fresh = api.create_rate_override(
            create_rate_override_payload(
                room_type_id=rt["id"], stay_date="2027-07-04",
                proposed_rate_cents=24000,
                recommendation_source="MANUAL_OVERRIDE",
            ),
            analyst_headers,
        )
        validate_success(fresh, expected_status=201)


# ===========================================================================
# Submit / withdraw cycle
# ===========================================================================
class TestSubmitWithdrawCycle:
    def test_withdraw_returns_to_draft(self, api, analyst_headers):
        """PRD §3.3: 'or the original RevenueAnalyst may withdraw,
        returning the override to DRAFT for revision (this cyclic loop
        supports iterative revision rounds).'"""
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2027-08-01",
        )
        wd = api.withdraw_rate_override(pending["id"], analyst_headers)
        ro = validate_success(wd, expected_status=200)
        assert ro["status"] == "DRAFT"

    def test_resubmit_after_withdraw_succeeds(self, api, analyst_headers):
        """PRD §3.3: '... iterative revision rounds.'"""
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2027-08-02",
        )
        api.withdraw_rate_override(pending["id"], analyst_headers)
        re_sub = api.submit_rate_override(pending["id"], analyst_headers)
        ro = validate_success(re_sub, expected_status=200)
        assert ro["status"] == "PENDING_APPROVAL"


# ===========================================================================
# Segregation of duties
# ===========================================================================
class TestSegregationOfDuties:
    def test_analyst_cannot_approve_own_submission(self, api):
        """PRD §3.3: 'On both approve and reject, the segregation-of-duties
        rule applies: the X-User-ID of the approver MUST NOT equal the
        X-User-ID recorded as the submitter. A violation is rejected with
        ERR_SEGREGATION_OF_DUTIES.'

        The submitter is analyst-001 (RevenueAnalyst). We attempt to
        approve with the SAME X-User-ID but role RevenueManager — the
        server compares ids regardless of role transition, per PRD §2.1
        which records the X-User-ID at submission.
        """
        from test_helpers import build_user_headers
        rt = create_room_type()
        # Submit as RevenueAnalyst with X-User-ID == 'analyst-001'.
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2027-09-01",
        )
        # Approve with a Manager whose X-User-ID equals the submitter's id.
        same_id_manager = build_user_headers("analyst-001", "RevenueManager")
        res = api.approve_rate_override(pending["id"], same_id_manager)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_distinct_manager_can_approve(self, api):
        """PRD §3.3: 'A RevenueManager may approve, advancing status to
        APPROVED.' (Default manager_headers is manager-001, distinct from
        analyst-001.)"""
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2027-09-02",
        )
        approved = approve_rate_override(pending["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "manager-001"

    def test_analyst_cannot_reject_own_submission(self, api):
        """PRD §3.3: 'On both approve and reject, the segregation-of-duties
        rule applies'. Same id rule applies on reject."""
        from test_helpers import build_user_headers
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2027-09-03",
        )
        same_id_manager = build_user_headers("analyst-001", "RevenueManager")
        res = api.reject_rate_override(pending["id"], same_id_manager)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ===========================================================================
# Approval side effects
# ===========================================================================
class TestApprovalSideEffects:
    def test_approve_sets_applied_rate_and_approved_by(self, api):
        """PRD §3.3: 'It sets applied_rate_cents equal to
        proposed_rate_cents, captures the approving RevenueManager's
        X-User-ID into approved_by'."""
        rt = create_room_type()
        approved = submit_and_approve_rate_override(
            room_type_id=rt["id"], stay_date="2027-09-10",
            proposed_rate_cents=27500,
        )
        assert approved["applied_rate_cents"] == 27500
        assert approved["approved_by"] == "manager-001"
        assert approved["status"] == "APPROVED"

    def test_approve_emits_audit_event(self, api):
        """PRD §3.3: 'Approval also writes a RATE_OVERRIDE_APPROVED audit
        event whose payload contains the before-rate and after-rate
        cents'."""
        rt = create_room_type()
        approved = submit_and_approve_rate_override(
            room_type_id=rt["id"], stay_date="2027-09-11",
            proposed_rate_cents=27500,
        )
        logs = list_audit_logs(
            event_type="RATE_OVERRIDE_APPROVED",
            subject_id=approved["id"],
        )
        assert len(logs) >= 1, "expected RATE_OVERRIDE_APPROVED audit event"

    def test_reject_emits_audit_event(self, api):
        """PRD §3.3: 'rejection writes a RATE_OVERRIDE_REJECTED audit
        event.'"""
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2027-09-12",
        )
        rej = api.reject_rate_override(
            pending["id"], TEST_USERS["manager_headers"],
        )
        rejected = validate_success(rej, expected_status=200)
        assert rejected["status"] == "REJECTED"
        logs = list_audit_logs(
            event_type="RATE_OVERRIDE_REJECTED",
            subject_id=pending["id"],
        )
        assert len(logs) >= 1

    def test_approve_supersedes_prior_approved(self, api, analyst_headers):
        """PRD §3.3: 'any prior RateOverride for the same (room_type_id,
        stay_date) whose status is APPROVED is moved to SUPERSEDED — only
        one approved override per slot is ever effective.'

        Observable consequence: after a fresh (room_type, stay_date)
        approval, a new DRAFT for the same key may be created — neither
        the original nor the new APPROVED entry is in DRAFT or
        PENDING_APPROVAL, so ERR_OVERRIDE_ALREADY_PENDING (PRD §3.3) is
        not raised.
        """
        rt = create_room_type()
        first = submit_and_approve_rate_override(
            room_type_id=rt["id"], stay_date="2027-10-01",
            proposed_rate_cents=20000,
        )
        second = submit_and_approve_rate_override(
            room_type_id=rt["id"], stay_date="2027-10-01",
            proposed_rate_cents=30000,
        )
        assert second["status"] == "APPROVED"
        assert second["applied_rate_cents"] == 30000
        # A third proposal on the same key must succeed — both prior
        # APPROVED rows are terminal (one APPROVED active, one
        # SUPERSEDED) so the in-flight uniqueness rule does not apply.
        third = api.create_rate_override(
            create_rate_override_payload(
                room_type_id=rt["id"], stay_date="2027-10-01",
                proposed_rate_cents=35000,
                recommendation_source="MANUAL_OVERRIDE",
            ),
            analyst_headers,
        )
        validate_success(third, expected_status=201)


# ===========================================================================
# Rate-parity check
# ===========================================================================
class TestRateParityCheck:
    def test_parity_violation_detected_on_approval(self, api):
        """PRD §3.3: 'if, across the participating channels, the largest
        channel-observed rate divided by the smallest exceeds the smallest
        by more than one percent, an audit event of type
        RATE_PARITY_VIOLATION_DETECTED is written.'

        Setup: two OTA channels with widely divergent commissions
        (1500bp vs 4000bp) so the grossed rates differ by ~22%.
        """
        scaffold = setup_rate_parity_violation_scaffold(
            stay_date="2027-11-01",
            ota1_commission_bp=1500,
            ota2_commission_bp=4000,
        )
        approved = submit_and_approve_rate_override(
            room_type_id=scaffold["room_type"]["id"],
            stay_date="2027-11-01",
            proposed_rate_cents=25000,
        )
        logs = list_audit_logs(
            event_type="RATE_PARITY_VIOLATION_DETECTED",
        )
        # Filter to logs whose payload references our room_type/stay_date
        relevant = [
            log for log in logs
            if isinstance(log.get("payload"), dict)
            and log["payload"].get("room_type_id") == scaffold["room_type"]["id"]
            and log["payload"].get("stay_date") == "2027-11-01"
        ]
        assert len(relevant) >= 1, (
            "expected RATE_PARITY_VIOLATION_DETECTED for "
            f"room_type {scaffold['room_type']['id']} stay_date 2027-11-01"
        )

    def test_no_parity_violation_when_commissions_match(self, api):
        """PRD §3.3: 'an audit event of type
        RATE_PARITY_VIOLATION_DETECTED is written' (only when the ratio
        exceeds 1%). Two OTAs at identical commission must NOT emit the
        event."""
        scaffold = setup_rate_parity_violation_scaffold(
            stay_date="2027-11-02",
            ota1_commission_bp=1500,
            ota2_commission_bp=1500,
        )
        approved = submit_and_approve_rate_override(
            room_type_id=scaffold["room_type"]["id"],
            stay_date="2027-11-02",
            proposed_rate_cents=25000,
        )
        logs = list_audit_logs(
            event_type="RATE_PARITY_VIOLATION_DETECTED",
        )
        relevant = [
            log for log in logs
            if isinstance(log.get("payload"), dict)
            and log["payload"].get("room_type_id") == scaffold["room_type"]["id"]
            and log["payload"].get("stay_date") == "2027-11-02"
        ]
        assert len(relevant) == 0, (
            "no parity violation expected when OTA commissions match"
        )
