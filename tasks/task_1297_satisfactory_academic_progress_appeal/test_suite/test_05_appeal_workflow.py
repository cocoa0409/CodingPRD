"""The appeal lifecycle: screening, the info-request loop, and the decision."""
import pytest

from test_helpers import (
    AID_OFFICER, AUDITOR, COMMITTEE, NON_EXISTENT_UUID, REGISTRAR, api_client,
    decide_payload, document_payload, get_student, list_audit_events,
    list_notifications, make_student_headers, setup_appeal_under_review,
    setup_submitted_appeal, submit_appeal, validate_error,
    validate_paginated, validate_success,
)


def _walk_info_request_cycle(api, world):
    """screen -> request-info -> resubmit -> screen, returning the appeal."""
    appeal_id = world["appeal"]["id"]
    student_id = world["student"]["id"]
    screened = validate_success(api.screen_appeal(appeal_id, AID_OFFICER), 200)
    assert screened["status"] == "UNDER_REVIEW"
    info = validate_success(api.request_info(
        appeal_id, {"info_request_note": "Need physician statement"}, AID_OFFICER), 200)
    assert info["status"] == "MORE_INFO_REQUESTED"
    resubmitted = validate_success(api.resubmit_appeal(
        appeal_id,
        {"documents": [document_payload("PHYSICIAN_STATEMENT", "Attending note")]},
        make_student_headers(student_id)), 200)
    assert resubmitted["status"] == "SUBMITTED", "the info-request cycle closes"
    return resubmitted


class TestAppealInfoRequestCycle:
    """The Appeal machine cycles UNDER_REVIEW -> MORE_INFO_REQUESTED -> SUBMITTED."""

    def test_info_request_cycle_returns_to_submitted_and_is_repeatable(self, api):
        """PRD section 3.6: "an `AidOfficer` screens a `SUBMITTED` appeal, moving it to
        `UNDER_REVIEW` and appending `APPEAL_SCREENED`"
        PRD section 3.6: "When the file is thin, the officer requests more information,
        moving the appeal from `UNDER_REVIEW` to `MORE_INFO_REQUESTED`; the supplied
        `info_request_note` is recorded on the appeal's `rationale` field"
        PRD section 3.6: "The student then resubmits — owner only, else
        `ERR_OWNERSHIP_VIOLATION` — moving the appeal from `MORE_INFO_REQUESTED` back
        to `SUBMITTED`; resubmission appends at least one new document to the
        `documents` array"

        Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle_and_branching_decision
        """
        world = setup_submitted_appeal()
        resubmitted = _walk_info_request_cycle(api, world)
        assert len(resubmitted["documents"]) == 2, "resubmission appends documents"

        rescreened = validate_success(
            api.screen_appeal(world["appeal"]["id"], AID_OFFICER), 200)
        assert rescreened["status"] == "UNDER_REVIEW", "the loop is repeatable"

    def test_cycle_then_branching_decision_to_probation(self, api):
        """PRD section 3.6: "Approval `PROBATION_ONLY` likewise moves the appeal
        `UNDER_REVIEW` → `APPROVED` but moves the student from `SUSPENSION` to
        `PROBATION`, restoring eligibility immediately under continued scrutiny."

        Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle_and_branching_decision
        """
        world = setup_submitted_appeal()
        _walk_info_request_cycle(api, world)
        validate_success(api.screen_appeal(world["appeal"]["id"], AID_OFFICER), 200)

        decided = validate_success(api.decide_appeal(
            world["appeal"]["id"],
            decide_payload("APPROVED", resolution="PROBATION_ONLY",
                           rationale="Documented medical hardship"),
            COMMITTEE), 200)
        assert decided["status"] == "APPROVED"
        assert decided["resolution"] == "PROBATION_ONLY"
        assert get_student(world["student"]["id"])["sap_status"] == "PROBATION"


class TestAppealDecisionCascade:
    """A WITH_PLAN approval mutates the appeal, the student, and the outbox."""

    def test_decide_with_plan_moves_student_to_plan_pending(self, api):
        """PRD section 3.6: "Approval `WITH_PLAN` moves the appeal `UNDER_REVIEW` →
        `APPROVED` and the student from `SUSPENSION` to `PLAN_PENDING`, holding aid
        until the plan of §3.7 exists."
        PRD section 3.6: "Every decision queues an `APPEAL_DECISION` notification at
        `decided_at` and appends `APPEAL_DECIDED`"

        Design: Difficulty/transitive_cascade/appeal_decision_cascade_to_notification
        """
        world = setup_appeal_under_review()
        decided = validate_success(api.decide_appeal(
            world["appeal"]["id"],
            decide_payload("APPROVED", resolution="WITH_PLAN",
                           rationale="Committee approval contingent on plan"),
            COMMITTEE), 200)
        assert decided["status"] == "APPROVED"
        assert decided["resolution"] == "WITH_PLAN"

        student = get_student(world["student"]["id"])
        assert student["sap_status"] == "PLAN_PENDING", (
            "the approval moves the student to PLAN_PENDING, not PROBATION")

        decisions = list_notifications(
            {"student_id": world["student"]["id"], "kind": "APPEAL_DECISION"})
        assert len(decisions) == 1
        assert decisions[0]["status"] == "QUEUED"

    def test_decide_with_plan_audit_trail_and_no_plan_yet(self, api):
        """PRD section 3.6: "Every decision queues an `APPEAL_DECISION` notification at
        `decided_at` and appends `APPEAL_DECIDED`; an approval additionally appends
        `STANDING_CHANGED`, and the queued notification adds its `NOTIFICATION_QUEUED`
        audit."
        PRD section 3.7: "An approved `WITH_PLAN` appeal leaves the student in
        `PLAN_PENDING`, and an `AidOfficer` converts that holding state into a
        monitored academic plan."

        Design: Difficulty/transitive_cascade/appeal_decision_cascade_to_notification
        """
        world = setup_appeal_under_review()
        validate_success(api.decide_appeal(
            world["appeal"]["id"],
            decide_payload("APPROVED", resolution="WITH_PLAN",
                           rationale="Committee approval contingent on plan"),
            COMMITTEE), 200)

        _events, meta = validate_paginated(api.list_audit_events(
            AUDITOR, params={"student_id": world["student"]["id"], "limit": 100}))
        assert meta["total_count"] == 18, (
            "every mutation on the path to the decision appends its audit row")

        plans, plans_meta = validate_paginated(api.list_plans(
            AID_OFFICER, params={"student_id": world["student"]["id"]}))
        assert plans_meta["total_count"] == 0, (
            "plan creation is a separate explicit POST, not part of the cascade")


def test_appeal_decide_before_review_rejected(api):
    """PRD section 3.6: "A decision attempted while the appeal is `SUBMITTED` or back
    in `MORE_INFO_REQUESTED` fails with `ERR_DECISION_REQUIRES_REVIEW`; one attempted
    on an appeal that already reached a terminal outcome is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/appeal_decide_before_review_rejected
    """
    world = setup_submitted_appeal()
    res = api.decide_appeal(
        world["appeal"]["id"],
        decide_payload("APPROVED", resolution="PROBATION_ONLY",
                       rationale="too hasty"),
        COMMITTEE)
    validate_error(res, "ERR_DECISION_REQUIRES_REVIEW")

    appeal = validate_success(api.get_appeal(world["appeal"]["id"], AID_OFFICER), 200)
    assert appeal["status"] == "SUBMITTED"
    assert get_student(world["student"]["id"])["sap_status"] == "SUSPENSION"


def test_appeal_resubmit_from_under_review_rejected(api):
    """PRD section 3.6: "The student then resubmits — owner only, else
    `ERR_OWNERSHIP_VIOLATION` — moving the appeal from `MORE_INFO_REQUESTED` back to
    `SUBMITTED`"
    PRD section 2.4: "6. **From-state validity** — the target resource must be in a
    valid from-state for the requested transition, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/appeal_resubmit_from_under_review_rejected
    """
    world = setup_appeal_under_review()
    res = api.resubmit_appeal(
        world["appeal"]["id"],
        {"documents": [document_payload("EXTRA", "x")]},
        make_student_headers(world["student"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")

    appeal = validate_success(api.get_appeal(world["appeal"]["id"], AID_OFFICER), 200)
    assert appeal["status"] == "UNDER_REVIEW"


def test_appeal_screen_after_denied_rejected(api):
    """PRD section 3.6: "`APPROVED`, `DENIED`, and `SUPERSEDED` are terminal: no
    further transition leaves them."
    PRD section 3.6: "Denial moves the appeal `UNDER_REVIEW` → `DENIED` and changes
    nothing else: the student remains in `SUSPENSION`, and the standing string, the
    window, and any queued reminders all stay as they were."

    Design: Corner/state_machines/appeal_screen_after_denied_rejected
    """
    world = setup_appeal_under_review()
    denied = validate_success(api.decide_appeal(
        world["appeal"]["id"],
        decide_payload("DENIED", rationale="Insufficient documentation"),
        COMMITTEE), 200)
    assert denied["status"] == "DENIED"

    res = api.screen_appeal(world["appeal"]["id"], AID_OFFICER)
    validate_error(res, "ERR_INVALID_STATE")
    res2 = api.decide_appeal(
        world["appeal"]["id"],
        decide_payload("APPROVED", resolution="PROBATION_ONLY",
                       rationale="reconsider"),
        COMMITTEE)
    validate_error(res2, "ERR_INVALID_STATE")

    appeal = validate_success(api.get_appeal(world["appeal"]["id"], AID_OFFICER), 200)
    assert appeal["status"] == "DENIED"
    assert get_student(world["student"]["id"])["sap_status"] == "SUSPENSION", (
        "denial changes nothing about the student's standing")


def test_student_cannot_decide_appeal(api):
    """PRD section 2.1: "When the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD section 3.6: "The decision belongs to a `CommitteeMember` and requires the
    appeal to sit in `UNDER_REVIEW`."

    Design: Corner/validations/student_cannot_decide_appeal
    """
    world = setup_submitted_appeal()
    res = api.decide_appeal(
        world["appeal"]["id"],
        decide_payload("APPROVED", resolution="PROBATION_ONLY",
                       rationale="self-approve"),
        make_student_headers(world["student"]["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")

    appeal = validate_success(api.get_appeal(world["appeal"]["id"], AID_OFFICER), 200)
    assert appeal["status"] == "SUBMITTED"


def test_registrar_cannot_decide_appeal(api):
    """PRD section 2.1: "`CommitteeMember` is the final step of the approval chain and
    records appeal decisions."
    PRD section 2.1: "When the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/registrar_cannot_decide_appeal
    """
    world = setup_appeal_under_review()
    res = api.decide_appeal(
        world["appeal"]["id"],
        decide_payload("APPROVED", resolution="PROBATION_ONLY",
                       rationale="registrar overreach"),
        REGISTRAR)
    validate_error(res, "ERR_UNAUTHORIZED")

    appeal = validate_success(api.get_appeal(world["appeal"]["id"], AID_OFFICER), 200)
    assert appeal["status"] == "UNDER_REVIEW"


def test_committee_cannot_screen_appeal(api):
    """PRD section 3.6: "Screening begins the office's work: an `AidOfficer` screens a
    `SUBMITTED` appeal, moving it to `UNDER_REVIEW` and appending `APPEAL_SCREENED`"
    PRD section 2.1: "When the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/committee_cannot_screen_appeal
    """
    world = setup_submitted_appeal()
    res = api.screen_appeal(world["appeal"]["id"], COMMITTEE)
    validate_error(res, "ERR_UNAUTHORIZED")

    appeal = validate_success(api.get_appeal(world["appeal"]["id"], AID_OFFICER), 200)
    assert appeal["status"] == "SUBMITTED"


def test_committee_decide_nonexistent_appeal_returns_not_found(api):
    """PRD section 2.4: "3. **Existence** — every identifier referenced by the path or
    the body is resolved left to right, else `ERR_NOT_FOUND` for the first identifier
    that does not resolve (see §2.9)."

    Design: Corner/validations/committee_decide_nonexistent_appeal_returns_not_found
    """
    res = api.decide_appeal(
        NON_EXISTENT_UUID,
        decide_payload("DENIED", rationale="no such appeal"),
        COMMITTEE)
    validate_error(res, "ERR_NOT_FOUND")
