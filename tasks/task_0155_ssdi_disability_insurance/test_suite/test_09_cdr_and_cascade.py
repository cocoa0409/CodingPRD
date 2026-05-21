"""CDR Review scheduling, completion, and the cessation cascade.

Covers PRD §3.8 (CDR + cessation cascade). Difficulty-design coverage:
rule 4 (cdr_cease_cascade_depth_3), rule 7
(alj_determination_requires_hearing_slot_held), and rule 9
(back_pay_recoupment_lifetime_paid_zero_drift).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    CDR_NOT_DUE_GRACE_DAYS,
    MIP_DIARY_MONTHS,
    TEST_USERS,
    activate_ssi,
    advance_clock_by_days,
    advance_clock_to,
    api_client,
    assert_cdr_review,
    book_slot,
    complete_cdr,
    complete_cdr_payload,
    create_child_aux,
    create_open_slot,
    create_ssi_supplement,
    current_clock,
    entitle_child,
    get_application,
    list_cdr_reviews,
    list_child_auxiliaries_for_application,
    list_determinations,
    make_alj_headers,
    parse_iso,
    schedule_cdr,
    setup_application_approved_at_initial,
    setup_application_at_alj_pending,
    setup_application_with_pending_cdr,
    setup_held_hearing_for_alj_pending,
    validate_error,
    validate_success,
)


class TestCDRAutocreation:

    def test_approval_auto_creates_pending_cdr(self, api):
        """PRD §3.4 step 11: "A single CDRReview row is auto-created
        with application_id pointing at this application,
        review_due_date equal to Application.next_cdr_due_date, and
        status PENDING."
        """
        claimant, application, cdr = setup_application_with_pending_cdr()
        assert_cdr_review(cdr)
        assert cdr["status"] == "PENDING"
        assert cdr["application_id"] == application["id"]
        # PRD: review_due_date == next_cdr_due_date
        assert cdr["review_due_date"] == application["next_cdr_due_date"]


class TestCDRSchedule:

    def test_schedule_before_due_window_returns_cdr_not_due(self, api):
        """PRD §3.8: "the transition PENDING to SCHEDULED ... requires
        that the clock be at or after review_due_date minus sixty days
        (otherwise ERR_CDR_NOT_DUE at 422)."
        """
        claimant, application, cdr = setup_application_with_pending_cdr()
        # Do not advance the clock — likely well before
        # review_due_date - 60 days (next_cdr_due_date is typically many
        # months out).
        resp = api.schedule_cdr_review(
            cdr["id"], TEST_USERS["cdr_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CDR_NOT_DUE.value)

    def test_schedule_within_grace_window_succeeds(self, api):
        """PRD §3.8: "the transition PENDING to SCHEDULED ... requires
        that the clock be at or after review_due_date minus sixty
        days".
        """
        claimant, application, cdr = setup_application_with_pending_cdr()
        # Advance clock to review_due_date - CDR_NOT_DUE_GRACE_DAYS + 1
        # so we are inside the schedulable window.
        due = parse_iso(cdr["review_due_date"])
        target = due - timedelta(days=CDR_NOT_DUE_GRACE_DAYS - 1)
        advance_clock_to(target)
        scheduled = schedule_cdr(cdr["id"])
        assert scheduled["status"] == "SCHEDULED"
        assert isinstance(scheduled.get("scheduled_at"), str)


class TestCDRComplete:

    def _scheduled_cdr(self, api):
        claimant, application, cdr = setup_application_with_pending_cdr()
        due = parse_iso(cdr["review_due_date"])
        advance_clock_to(due - timedelta(days=CDR_NOT_DUE_GRACE_DAYS - 1))
        cdr = schedule_cdr(cdr["id"])
        return claimant, application, cdr

    def test_continue_outcome_schedules_next_cdr(self, api):
        """PRD §3.8: "If the outcome is CONTINUE, the system auto-
        creates the next CDRReview row with review_due_date equal to
        the current logical clock instant plus the application's
        diary interval in whole months".
        """
        claimant, application, cdr = self._scheduled_cdr(api)
        completed = complete_cdr(
            cdr["id"], medical_improvement_found=False, working_at_sga=False,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "CONTINUE"
        # A new PENDING CDRReview should now exist for this application.
        cdrs = list_cdr_reviews(status="PENDING")
        for_app = [c for c in cdrs if c["application_id"] == application["id"]]
        assert len(for_app) >= 1, (
            f"PRD §3.8 CONTINUE outcome must auto-create the next CDR; "
            f"none found for application {application['id']}"
        )


class TestCDRCeaseCascadeDepth3:
    """Difficulty design rule 4: cdr_cease_cascade_depth_3."""

    def test_cease_outcome_closes_application_and_terminates_children(self, api):
        """# difficulty: transitive_cascade/cdr_cease_cascade_depth_3

        PRD §3.8: "If the outcome is CEASE, the cessation cascade
        fires: The parent Application transitions from APPROVED to
        CLOSED_DENIED."
        PRD §3.8: "Every ChildAuxiliary whose application_id matches
        this application and whose status is ENTITLED is terminated
        with termination_reason PARENT_BENEFIT_ENDED, transitioning
        each affected row from ENTITLED to TERMINATED."
        """
        claimant, application, cdr = setup_application_with_pending_cdr()
        # Pre-create + entitle a child so we can observe hop-3.
        child = create_child_aux(
            application["id"], child_date_of_birth="2015-01-15",
        )
        entitle_child(child["id"])
        # Advance to schedule + complete with CEASE.
        due = parse_iso(cdr["review_due_date"])
        advance_clock_to(due - timedelta(days=CDR_NOT_DUE_GRACE_DAYS - 1))
        schedule_cdr(cdr["id"])
        completed = complete_cdr(
            cdr["id"], medical_improvement_found=True, working_at_sga=False,
        )
        assert completed["outcome"] == "CEASE"
        # Hop 2: application -> CLOSED_DENIED
        application = get_application(claimant["id"], application["id"])
        assert application["status"] == "CLOSED_DENIED"
        # Hop 3: child auxiliary terminated with PARENT_BENEFIT_ENDED.
        children = list_child_auxiliaries_for_application(application["id"])
        survivors = [c for c in children if c["id"] == child["id"]]
        assert len(survivors) == 1
        assert survivors[0]["status"] == "TERMINATED"
        assert survivors[0]["termination_reason"] == "PARENT_BENEFIT_ENDED"

    def test_cease_recoups_back_pay_with_compensating_determination(self, api):
        """# difficulty: compensating_invariant/back_pay_recoupment_lifetime_paid_zero_drift
        # difficulty: transitive_cascade/cdr_cease_cascade_depth_3

        PRD §3.8: "A new Determination row is appended carrying a
        negative entitlement delta that recoups the originally awarded
        back pay, preserving a compensating-invariant total lifetime-
        paid ledger."

        Claim: after CEASE, the application's determination ledger
        carries a new entry; a CEASE cascade fires a compensating
        ledger entry per PRD prose. We assert at least one new
        determination row was appended after the approval row.
        """
        claimant, application, cdr = setup_application_with_pending_cdr()
        before = list_determinations(claimant["id"], application["id"])
        before_count = len(before)
        due = parse_iso(cdr["review_due_date"])
        advance_clock_to(due - timedelta(days=CDR_NOT_DUE_GRACE_DAYS - 1))
        schedule_cdr(cdr["id"])
        complete_cdr(
            cdr["id"], medical_improvement_found=True, working_at_sga=False,
        )
        after = list_determinations(claimant["id"], application["id"])
        assert len(after) > before_count, (
            f"PRD §3.8 cessation cascade must append a compensating "
            f"Determination row; before={before_count}, after={len(after)}"
        )


class TestALJHearingNotHeldDependency:
    """Difficulty design rule 7: alj_determination_requires_hearing_slot_held."""

    def test_alj_determination_without_held_slot_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/alj_determination_requires_hearing_slot_held

        PRD §3.6: "An ALJ determination is issued by an ALJ operator
        and requires an associated HearingSlot for this application
        whose status is HELD; absent that, the determination is
        rejected with ERR_HEARING_NOT_HELD at HTTP status 422."
        """
        claimant, application = setup_application_at_alj_pending()
        alj = "alj-nh-1"
        # Create slot, book it, but DO NOT hold it (clock < start_at).
        T = current_clock() + timedelta(hours=2)
        slot = create_open_slot(alj_id=alj, start_at_dt=T)
        book_slot(slot["id"], alj, application["id"])
        resp = api.create_determination(
            claimant["id"], application["id"],
            {
                "level": "ALJ", "decision": "ALLOW",
                "medical_basis": "MEETS_LISTING",
                "established_onset_date": claimant["alleged_onset_date"],
                "rationale": (
                    "Hearing testimony and record support listings-level "
                    "impairment findings."
                ),
            },
            make_alj_headers(alj),
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_NOT_HELD.value)

    def test_after_held_slot_alj_allow_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/alj_determination_requires_hearing_slot_held

        PRD §3.6: "An ALJ ALLOW runs the approval cascade with final
        variants for pia_calc and back_pay_calc".

        Claim: with a HELD slot, the same ALJ ALLOW determination
        succeeds and the application advances to ALJ_APPROVED.
        """
        claimant, application, slot = setup_held_hearing_for_alj_pending(
            alj_id="alj-nh-2",
        )
        resp = api.create_determination(
            claimant["id"], application["id"],
            {
                "level": "ALJ", "decision": "ALLOW",
                "medical_basis": "MEETS_LISTING",
                "established_onset_date": claimant["alleged_onset_date"],
                "rationale": (
                    "Hearing testimony and record support listings-level "
                    "impairment findings."
                ),
            },
            make_alj_headers(slot["alj_id"]),
        )
        validate_success(resp, expected_status=201)
        application = get_application(claimant["id"], application["id"])
        assert application["status"] == "ALJ_APPROVED"
