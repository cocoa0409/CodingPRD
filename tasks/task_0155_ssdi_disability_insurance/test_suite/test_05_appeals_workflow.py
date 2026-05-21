"""Reconsideration, ALJ, Appeals Council, SoD, appeal window, remand cycle.

Covers PRD §3.6 (appeals workflow) and difficulty-design rule 3
(non_linear_state_machine — application_appeals_remand_cycle) and rule 5
(priority_pair_validation_conflict).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    APPEAL_WINDOW_DAYS,
    TEST_USERS,
    advance_clock_by_days,
    advance_clock_to,
    api_client,
    appeal_application,
    appeal_payload,
    book_slot,
    create_determination_payload,
    create_open_slot,
    current_clock,
    get_application,
    hold_slot,
    issue_determination,
    make_alj_headers,
    make_claimant_headers,
    setup_application_at_appeals_council,
    setup_application_at_alj_pending,
    setup_application_at_initial_review,
    setup_application_at_reconsideration,
    setup_application_initial_denied,
    setup_held_hearing_for_alj_pending,
    validate_error,
    validate_success,
)


class TestSegregationOfDuties:

    def test_recon_by_initial_examiner_returns_sod(self, api):
        """PRD §3.6: "A reconsideration determination is issued by a
        DDS examiner, but the segregation-of-duties rule binds: the
        acting examiner's X-User-ID must not equal the application's
        last_initial_examiner_id. A violation is rejected with
        ERR_SEGREGATION_OF_DUTIES at HTTP status 403, and this binding
        applies to both the ALLOW and DENY branches at reconsideration
        with equal force."
        """
        claimant, application = setup_application_at_reconsideration(
            examiner_headers=TEST_USERS["dds_examiner_headers"],
        )
        payload = create_determination_payload(
            level="RECONSIDERATION", decision="ALLOW",
            medical_basis="MEETS_LISTING",
            established_onset_date=claimant["alleged_onset_date"],
        )
        # Same examiner as the INITIAL denial.
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["dds_examiner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_recon_by_different_examiner_succeeds(self, api):
        """PRD §3.6: "the acting examiner's X-User-ID must not equal
        the application's last_initial_examiner_id."
        """
        claimant, application = setup_application_at_reconsideration(
            examiner_headers=TEST_USERS["dds_examiner_headers"],
        )
        payload = create_determination_payload(
            level="RECONSIDERATION", decision="DENY",
            medical_basis="NOT_DISABLED",
        )
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["dds_examiner_2_headers"],
        )
        validate_success(resp, expected_status=201)

    def test_sod_binding_applies_to_deny_branch(self, api):
        """PRD §3.6: "this binding applies to both the ALLOW and DENY
        branches at reconsideration with equal force."
        """
        claimant, application = setup_application_at_reconsideration(
            examiner_headers=TEST_USERS["dds_examiner_headers"],
        )
        payload = create_determination_payload(
            level="RECONSIDERATION", decision="DENY",
            medical_basis="NOT_DISABLED",
        )
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["dds_examiner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestAppealWindow:

    def test_appeal_within_window_succeeds(self, api):
        """PRD §3.6: "the temporal precondition is that the current
        logical clock instant is on or before the last determination's
        created_at plus APPEAL_WINDOW_DAYS (which is sixty days)".
        """
        claimant, application = setup_application_initial_denied()
        # Appeal immediately (well within 60 days).
        appealed = appeal_application(
            claimant["id"], application["id"],
            target_level="RECONSIDERATION",
        )
        assert appealed["status"] == "RECONSIDERATION"

    def test_appeal_after_window_returns_expired(self, api):
        """PRD §3.6: "a late appeal is rejected with
        ERR_APPEAL_WINDOW_EXPIRED at HTTP status 409."
        """
        claimant, application = setup_application_initial_denied()
        # Advance clock past 60 days.
        advance_clock_by_days(APPEAL_WINDOW_DAYS + 1)
        resp = api.appeal_application(
            claimant["id"], application["id"],
            appeal_payload(target_level="RECONSIDERATION"),
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value)


class TestRemandCycle:
    """Difficulty design rule 3: application_appeals_remand_cycle."""

    def test_remand_returns_application_to_reconsideration(self, api):
        """# difficulty: non_linear_state_machine/application_appeals_remand_cycle

        PRD §3.6: "A REMAND at this level — and REMAND is valid only at
        APPEALS_COUNCIL — cycles the application back to
        RECONSIDERATION so a new examiner action can occur."
        """
        claimant, application, _ = setup_application_at_appeals_council()
        payload = create_determination_payload(
            level="APPEALS_COUNCIL", decision="REMAND",
            rationale=(
                "Insufficient development of vocational record requires "
                "further reconsideration."
            ),
        )
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["appeals_council_headers"],
        )
        validate_success(resp, expected_status=201)
        application = get_application(claimant["id"], application["id"])
        assert application["status"] == "RECONSIDERATION"

    def test_remand_preserves_last_initial_examiner_id(self, api):
        """# difficulty: non_linear_state_machine/application_appeals_remand_cycle

        PRD §3.6: "The remand preserves the application's
        last_initial_examiner_id, meaning the segregation-of-duties
        bond persists through the cycle: the examiner who issued the
        original initial determination remains barred from any
        subsequent reconsideration on this application."
        """
        claimant, application, _ = setup_application_at_appeals_council()
        before = application.get("last_initial_examiner_id")
        assert before is not None
        # Remand
        api.create_determination(
            claimant["id"], application["id"],
            create_determination_payload(
                level="APPEALS_COUNCIL", decision="REMAND",
                rationale=(
                    "Insufficient development; reconsideration directed "
                    "for further review of vocational evidence."
                ),
            ),
            TEST_USERS["appeals_council_headers"],
        )
        application = get_application(claimant["id"], application["id"])
        assert application["status"] == "RECONSIDERATION"
        assert application.get("last_initial_examiner_id") == before, (
            f"last_initial_examiner_id must be preserved across REMAND; "
            f"was {before}, now {application.get('last_initial_examiner_id')}"
        )

    def test_post_remand_recon_with_same_examiner_still_blocked(self, api):
        """# difficulty: non_linear_state_machine/application_appeals_remand_cycle

        PRD §3.6: "the examiner who issued the original initial
        determination remains barred from any subsequent
        reconsideration on this application."

        Claim: after REMAND back to RECONSIDERATION, the initial
        examiner still cannot adjudicate.
        """
        claimant, application, _ = setup_application_at_appeals_council()
        api.create_determination(
            claimant["id"], application["id"],
            create_determination_payload(
                level="APPEALS_COUNCIL", decision="REMAND",
                rationale=(
                    "Insufficient development; reconsideration directed "
                    "for further review of vocational evidence."
                ),
            ),
            TEST_USERS["appeals_council_headers"],
        )
        # The initial examiner is dds-examiner-0001 (the setup's default).
        # Try to ALLOW at RECONSIDERATION as that examiner.
        resp = api.create_determination(
            claimant["id"], application["id"],
            create_determination_payload(
                level="RECONSIDERATION", decision="ALLOW",
                medical_basis="MEETS_LISTING",
                established_onset_date=claimant["alleged_onset_date"],
            ),
            TEST_USERS["dds_examiner_headers"],  # same as initial
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestALJWorkflow:

    def test_alj_determination_without_held_hearing_rejected(self, api):
        """PRD §3.6: "An ALJ determination is issued by an ALJ operator
        and requires an associated HearingSlot for this application
        whose status is HELD; absent that, the determination is
        rejected with ERR_HEARING_NOT_HELD at HTTP status 422."
        """
        claimant, application = setup_application_at_alj_pending()
        # No HearingSlot at HELD has been created.
        payload = create_determination_payload(
            level="ALJ", decision="ALLOW",
            medical_basis="MEETS_LISTING",
            established_onset_date=claimant["alleged_onset_date"],
        )
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["alj_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_NOT_HELD.value)

    def test_alj_allow_with_held_hearing_approves(self, api):
        """PRD §3.6: "An ALJ ALLOW runs the approval cascade with final
        variants for pia_calc and back_pay_calc — full year-of-onset
        earnings rather than truncated, and the absolute twelve-month
        pre-filing back-pay cap."
        """
        claimant, application, slot = setup_held_hearing_for_alj_pending()
        payload = create_determination_payload(
            level="ALJ", decision="ALLOW",
            medical_basis="MEETS_LISTING",
            established_onset_date=claimant["alleged_onset_date"],
        )
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            make_alj_headers(slot["alj_id"]),
        )
        validate_success(resp, expected_status=201)
        application = get_application(claimant["id"], application["id"])
        assert application["status"] == "ALJ_APPROVED"


class TestRecondHearingSlotPriorityPairing:
    """Difficulty design rule 5: state_vs_business_safety_recon_double_fail."""

    def test_state_check_wins_over_sod(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_recon_double_fail

        PRD §2.9: "state validity follows: an operation on an entity
        that is not currently in a state permitting the requested
        transition is rejected with ERR_INVALID_STATE at HTTP status
        409. After state validity come the domain-specific business
        checks (segregation of duties at reconsideration, ...)".

        Claim: an application in INITIAL_REVIEW (not RECON-eligible)
        plus a RECON determination from the initial examiner causes
        ERR_INVALID_STATE (state fail wins over SoD).
        """
        # Application stays in INITIAL_REVIEW (no INITIAL determination
        # was issued yet) — but to set last_initial_examiner_id we need
        # a prior INITIAL. Use setup_application_initial_denied which
        # stamps last_initial_examiner_id then DOES advance to
        # INITIAL_DENIED. Then re-submit? PRD does not allow that.
        # Cleaner: PRD scaffold says state vs SoD: status=INITIAL_REVIEW
        # plus a stamped last_initial_examiner_id. The PRD §3.4 says
        # last_initial_examiner_id is stamped on both ALLOW and DENY at
        # INITIAL — once stamped, state is INITIAL_DENIED or APPROVED.
        # In INITIAL_DENIED we are still NOT in RECONSIDERATION, so a
        # RECON determination yields state fail. Use INITIAL_DENIED as
        # the state.
        claimant, application = setup_application_initial_denied(
            examiner_headers=TEST_USERS["dds_examiner_headers"],
        )
        # Application is INITIAL_DENIED; the SoD-violating examiner
        # would have stamped last_initial_examiner_id=dds-examiner-0001.
        # Issuing a RECONSIDERATION determination is illegal because
        # the application is not yet in RECONSIDERATION status; PRD's
        # priority order says state precedes SoD.
        payload = create_determination_payload(
            level="RECONSIDERATION", decision="ALLOW",
            medical_basis="MEETS_LISTING",
            established_onset_date=claimant["alleged_onset_date"],
        )
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["dds_examiner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
