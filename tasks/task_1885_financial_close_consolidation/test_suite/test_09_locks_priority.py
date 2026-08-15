"""Validation priority pairs and lock gates."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_journal_entry_payload,
    set_clock, setup_open_period_with_entity, setup_soft_locked_period,
    create_balanced_je, post_je,
    drive_entity_period_to_ready, soft_lock_period, get_period_version,
    CONTROLLER, PREPARER, APPROVER,
    make_preparer_headers, make_approver_headers,
)
from test_helpers import api_client


class TestPriorityPairValidationConflict:
    def test_sod_violation_wins_over_period_locked(self, api):
        """PRD §2.9: "every request passes a fixed, eleven-tier validation order,
        evaluated in this sequence so that earlier failures mask later ones
        deterministically".
        PRD §2.9: "6. Segregation of duties, on the approve, post, confirm, clear,
        and verify endpoints — `ERR_SOD_VIOLATION`."
        PRD §2.9: "7. Close-posture and period-lock gates: no journal drafting,
        submission, or posting, no reconciliation change, and no task start on a
        soft-locked, hard-locked, or finalized period or entity-period —
        `ERR_PERIOD_LOCKED`".

        Design: Difficulty/priority_pair_validation_conflict/sod_violation_vs_period_locked_safety_over_state
        """
        period, entity, ep = setup_open_period_with_entity()
        prep1 = make_preparer_headers("prep-1")
        je = create_balanced_je(ep["id"], 1000, preparer_headers=prep1)
        get_success_data(api.submit_journal_entry(je["id"], prep1))
        # Drive the entity-period to SOFT_LOCKED
        drive_entity_period_to_ready(period["id"], ep["id"], fx_currency="USD")
        soft_lock_period(period["id"])
        # approve with the SAME user id as the preparer (SoD breach at priority 6)
        # while the period is locked (priority 7). Priority 6 fires first.
        same_user_approver = make_approver_headers("prep-1")
        res = api.approve_journal_entry(je["id"], same_user_approver)
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=409)
        after = validate_success(api.get_journal_entry(je["id"], PREPARER), 200)
        assert after["status"] == "SUBMITTED"

    def test_period_locked_error_when_sod_not_violated(self, api):
        """PRD §2.9: "7. Close-posture and period-lock gates: no journal drafting,
        submission, or posting, no reconciliation change, and no task start on a
        soft-locked, hard-locked, or finalized period or entity-period —
        `ERR_PERIOD_LOCKED`".
        PRD §3.5: "An `Approver` approves a `SUBMITTED` entry only when the
        approver differs from `preparer_user_id` (`ERR_SOD_VIOLATION`), ... and
        the parent entity-period is neither `SOFT_LOCKED` nor `HARD_LOCKED`".

        Design: Difficulty/priority_pair_validation_conflict/sod_violation_vs_period_locked_safety_over_state
        """
        period, entity, ep = setup_open_period_with_entity()
        prep1 = make_preparer_headers("prep-1")
        je = create_balanced_je(ep["id"], 1000, preparer_headers=prep1)
        get_success_data(api.submit_journal_entry(je["id"], prep1))
        drive_entity_period_to_ready(period["id"], ep["id"], fx_currency="USD")
        soft_lock_period(period["id"])
        # approve by a DIFFERENT user (no SoD breach) but period is locked → p7 fires
        res = api.approve_journal_entry(je["id"], APPROVER)
        validate_error(res, ApiErrorId.ERR_PERIOD_LOCKED, expected_status=409)

    def test_invalid_state_wins_over_temporal_recheck(self, api):
        """PRD §2.9: "5. State-machine legality: the requested transition must be
        permitted from the target resource's current state, on all action
        endpoints — `ERR_INVALID_STATE`."
        PRD §2.9: "9. Temporal windows: an entry date inside its period
        (`ERR_JE_OUT_OF_PERIOD`)".

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_business_temporal_state_over_temporal
        """
        period, entity, ep = setup_open_period_with_entity()
        # walk a valid JE to POSTED
        je = post_je(ep["id"], 2000)
        assert je["status"] == "POSTED"
        # re-submit the already-POSTED entry: state precondition fires first
        res = api.submit_journal_entry(je["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_journal_entry(je["id"], PREPARER), 200)
        assert after["status"] == "POSTED"

    def test_submit_from_draft_still_works_when_state_valid(self, api):
        """PRD §3.5: "Submission moves an entry from `DRAFT` to `SUBMITTED`".
        PRD §2.9: "5. State-machine legality: the requested transition must be
        permitted from the target resource's current state, on all action
        endpoints — `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_business_temporal_state_over_temporal
        """
        period, entity, ep = setup_open_period_with_entity()
        je = create_balanced_je(ep["id"], 2000)
        assert je["status"] == "DRAFT"
        submitted = validate_success(api.submit_journal_entry(je["id"], PREPARER), 200)
        assert submitted["status"] == "SUBMITTED"
