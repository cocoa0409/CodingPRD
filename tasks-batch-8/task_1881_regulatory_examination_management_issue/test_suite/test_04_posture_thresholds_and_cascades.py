"""Examination posture: FROZEN threshold boundary, posture gates on document
QC, and the accept/waive cascade that relaxes posture (PRD §3.3, §3.8, §2.5)."""
from test_helpers import (
    RAM,
    ApiErrorId,
    create_agency,
    create_document_submission_payload,
    create_examination,
    create_first_day_item,
    create_officer,
    create_reviewer,
    get_exam,
    issue_first_day_letter,
    make_compliance_reviewer_headers,
    make_remediation_owner_headers,
    set_logical_clock,
    setup_exam_with_overdue_items,
    validate_error,
    validate_paginated,
    validate_success,
    waive_item,
)


class TestFrozenThresholdBoundary:
    def test_exactly_three_overdue_items_freezes_exam(self, api):
        """PRD §3.8: "The examination is `FROZEN` when the overdue-item count
        reaches three (exactly three qualifies) or when the longest
        issue-overdue stretch reaches the escalation threshold; otherwise it is
        `RESTRICTED` when at least one first-day item is overdue or any
        milestone stands overdue; otherwise it is `NORMAL`."

        Three PENDING items due 2026-07-20 with the logical clock at
        2026-07-21: the count reaches three, and exactly three qualifies.

        Design: Difficulty/boundary_precision_check/posture_threshold_exactly_three_overdue_items
        """
        ctx = setup_exam_with_overdue_items(num_items=3)
        exam = get_exam(ctx["exam"]["id"])
        assert exam["overdue_item_count"] == 3
        assert exam["posture"] == "FROZEN", ">= 3 is inclusive at 3"

    def test_frozen_exam_blocks_document_submission(self, api):
        """PRD §3.3: "the whole submission is refused with
        `ERR_EXAM_POSTURE_FROZEN` whenever the examination's `posture` has
        degraded to `FROZEN` — a frozen examination accepts no further
        submissions until posture relaxes"

        Design: Difficulty/boundary_precision_check/posture_threshold_exactly_three_overdue_items
        """
        ctx = setup_exam_with_overdue_items(num_items=3)
        exam = get_exam(ctx["exam"]["id"])
        assert exam["posture"] == "FROZEN"
        officer = create_officer()
        owner_headers = make_remediation_owner_headers(officer["id"])
        resp = api.create_document_submission(
            ctx["items"][0]["id"], create_document_submission_payload(), owner_headers)
        validate_error(resp, ApiErrorId.ERR_EXAM_POSTURE_FROZEN)


class TestAcceptCascadeRelaxesPosture:
    def _setup_restricted_with_submission(self, api):
        ctx = setup_exam_with_overdue_items(num_items=1)
        officer = create_officer()
        reviewer = create_reviewer(certification_level="L1")
        ctx["owner_headers"] = make_remediation_owner_headers(officer["id"])
        ctx["reviewer_headers"] = make_compliance_reviewer_headers(reviewer["id"])
        sub = validate_success(
            api.create_document_submission(
                ctx["items"][0]["id"], create_document_submission_payload(),
                ctx["owner_headers"]),
            201)
        ctx["submission"] = sub
        return ctx

    def test_accept_transitions_item_and_recomputes_overdue_count(self, api):
        """PRD §3.3: "When acceptance lands, the submission moves
        `PENDING_REVIEW` → `ACCEPTED`, and the acceptance cascades: the parent
        item transitions `PENDING` → `SUBMITTED` with its `submitted_at` stamped
        at that moment, the examination's `overdue_item_count` and `posture` are
        recomputed — acceptance of an overdue item may relax a `FROZEN` or
        `RESTRICTED` posture — and the `version` of the submission, the item,
        and the examination each increments by one."

        Pre-state: one overdue PENDING item (overdue_item_count == 1).

        Design: Difficulty/transitive_cascade/document_accept_cascades_item_submitted_to_posture_relaxation
        """
        ctx = self._setup_restricted_with_submission(api)
        exam_pre = get_exam(ctx["exam"]["id"])
        assert exam_pre["overdue_item_count"] == 1
        assert exam_pre["posture"] == "RESTRICTED"

        accept = validate_success(
            api.accept_document_submission(
                ctx["submission"]["id"], ctx["reviewer_headers"]))
        assert accept["quality_status"] == "ACCEPTED"

        item = validate_success(api.get_first_day_item(ctx["items"][0]["id"], RAM))
        assert item["status"] == "SUBMITTED", "cascade hop 1: item PENDING -> SUBMITTED"
        assert item["submitted_at"], "submitted_at is stamped at acceptance"

        exam_post = get_exam(ctx["exam"]["id"])
        assert exam_post["overdue_item_count"] == 0, (
            "cascade hop 2: overdue count recomputed"
        )

    def test_accept_of_last_overdue_item_relaxes_posture_to_normal(self, api):
        """PRD §3.3: "When acceptance lands, the submission moves
        `PENDING_REVIEW` → `ACCEPTED`, and the acceptance cascades: the parent
        item transitions `PENDING` → `SUBMITTED` with its `submitted_at` stamped
        at that moment, the examination's `overdue_item_count` and `posture` are
        recomputed — acceptance of an overdue item may relax a `FROZEN` or
        `RESTRICTED` posture — and the `version` of the submission, the item,
        and the examination each increments by one."
        PRD §3.8: "otherwise it is `RESTRICTED` when at least one first-day item
        is overdue or any milestone stands overdue; otherwise it is `NORMAL`."

        Design: Difficulty/transitive_cascade/document_accept_cascades_item_submitted_to_posture_relaxation
        """
        ctx = self._setup_restricted_with_submission(api)
        assert get_exam(ctx["exam"]["id"])["posture"] == "RESTRICTED"
        validate_success(
            api.accept_document_submission(
                ctx["submission"]["id"], ctx["reviewer_headers"]))
        exam_post = get_exam(ctx["exam"]["id"])
        assert exam_post["posture"] == "NORMAL", (
            "cascade hop 3: with no overdue items remaining, posture relaxes"
        )


class TestAcceptBlockedWhenExamFrozen:
    def _setup_frozen_with_pending_submission(self, api):
        """Three items due 2026-07-20 (overdue after the clock advance) plus a
        fourth item due later, holding a PENDING_REVIEW submission."""
        agency = create_agency(agency_code="CFPB3")
        exam = create_examination(
            agency["id"], exam_cycle_code="R", exam_type="COMPLIANCE",
            scheduled_start_date="2026-07-06T00:00:00Z",
            scheduled_end_date="2026-07-31T00:00:00Z")
        set_logical_clock("2026-07-01T00:00:00Z")
        for ref in ("F1", "F2", "F3"):
            create_first_day_item(exam["id"], request_ref=ref,
                                  due_date="2026-07-20T00:00:00Z")
        item4 = create_first_day_item(exam["id"], request_ref="F4",
                                      due_date="2026-08-20T00:00:00Z")
        issue_first_day_letter(exam["id"])
        officer = create_officer()
        reviewer = create_reviewer(certification_level="L1")
        owner_headers = make_remediation_owner_headers(officer["id"])
        reviewer_headers = make_compliance_reviewer_headers(reviewer["id"])
        submission = validate_success(
            api.create_document_submission(
                item4["id"], create_document_submission_payload(), owner_headers),
            201)
        set_logical_clock("2026-07-25T00:00:00Z")
        exam_now = get_exam(exam["id"])
        assert exam_now["posture"] == "FROZEN", "setup: three overdue items freeze the exam"
        return {
            "exam": exam_now, "item4": item4, "submission": submission,
            "reviewer_headers": reviewer_headers,
        }

    def test_accept_under_frozen_posture_rejected_invalid_state(self, api):
        """PRD §3.3: "Acceptance is deliberately strict: the submission must
        still be `PENDING_REVIEW`, its parent item must still be `PENDING`, the
        examination must be in `FIRST_DAY_ISSUED` or `FIELDWORK`, and the
        examination's `posture` must not be `FROZEN`; any shortfall is rejected
        with `ERR_INVALID_STATE`."

        The FROZEN posture makes exactly one accept precondition fail.

        Design: Difficulty/cross_entity_state_dependency/document_accept_blocked_when_exam_frozen
        """
        ctx = self._setup_frozen_with_pending_submission(api)
        resp = api.accept_document_submission(
            ctx["submission"]["id"], ctx["reviewer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_accept_leaves_submission_pending_review(self, api):
        """PRD §3.3: "Acceptance is deliberately strict: the submission must
        still be `PENDING_REVIEW`, its parent item must still be `PENDING`, the
        examination must be in `FIRST_DAY_ISSUED` or `FIELDWORK`, and the
        examination's `posture` must not be `FROZEN`; any shortfall is rejected
        with `ERR_INVALID_STATE`."

        A rejected acceptance mutates nothing: the submission and its item keep
        their prior states.

        Design: Difficulty/cross_entity_state_dependency/document_accept_blocked_when_exam_frozen
        """
        ctx = self._setup_frozen_with_pending_submission(api)
        validate_error(
            api.accept_document_submission(
                ctx["submission"]["id"], ctx["reviewer_headers"]),
            ApiErrorId.ERR_INVALID_STATE)
        sub = validate_success(
            api.get_document_submission(ctx["submission"]["id"], RAM))
        assert sub["quality_status"] == "PENDING_REVIEW"
        item = validate_success(api.get_first_day_item(ctx["item4"]["id"], RAM))
        assert item["status"] == "PENDING"


class TestOverdueCountInvariant:
    def test_waive_decrements_overdue_count_and_relaxes_posture(self, api):
        """PRD §3.3: "Waiving a `PENDING` item — a `RegulatoryAffairsManager`
        action requiring a non-empty `waived_reason` — moves it to the terminal
        `WAIVED` state, recomputes the examination's overdue count and posture
        just as an acceptance would, and bumps both the item's and the
        examination's `version`."
        PRD §3.8: "The examination is `FROZEN` when the overdue-item count
        reaches three (exactly three qualifies) or when the longest
        issue-overdue stretch reaches the escalation threshold"

        Three overdue items (FROZEN); waiving one leaves two (RESTRICTED).

        Design: Difficulty/compensating_invariant/overdue_item_count_invariant_under_waive_and_submit
        """
        ctx = setup_exam_with_overdue_items(num_items=3)
        assert get_exam(ctx["exam"]["id"])["overdue_item_count"] == 3
        assert get_exam(ctx["exam"]["id"])["posture"] == "FROZEN"

        waived = waive_item(ctx["items"][0]["id"])
        assert waived["status"] == "WAIVED"
        exam = get_exam(ctx["exam"]["id"])
        assert exam["overdue_item_count"] == 2, "waive decrements by exactly one"
        assert exam["posture"] == "RESTRICTED"

    def test_submit_accept_decrements_count_conserving_roster_total(self, api):
        """PRD §3.3: "Waiving a `PENDING` item — a `RegulatoryAffairsManager`
        action requiring a non-empty `waived_reason` — moves it to the terminal
        `WAIVED` state, recomputes the examination's overdue count and posture
        just as an acceptance would, and bumps both the item's and the
        examination's `version`."
        PRD §3.3: "When acceptance lands, the submission moves `PENDING_REVIEW`
        → `ACCEPTED`, and the acceptance cascades: the parent item transitions
        `PENDING` → `SUBMITTED` with its `submitted_at` stamped at that moment,
        the examination's `overdue_item_count` and `posture` are recomputed —
        acceptance of an overdue item may relax a `FROZEN` or `RESTRICTED`
        posture — and the `version` of the submission, the item, and the
        examination each increments by one."

        Waive one item, then submit-and-accept a second: the overdue count walks
        3 -> 2 -> 1 while the first-day roster stays at three rows.

        Design: Difficulty/compensating_invariant/overdue_item_count_invariant_under_waive_and_submit
        """
        ctx = setup_exam_with_overdue_items(num_items=3)
        officer = create_officer()
        reviewer = create_reviewer(certification_level="L1")
        owner_headers = make_remediation_owner_headers(officer["id"])
        reviewer_headers = make_compliance_reviewer_headers(reviewer["id"])

        waive_item(ctx["items"][0]["id"])
        exam = get_exam(ctx["exam"]["id"])
        assert exam["overdue_item_count"] == 2
        assert exam["posture"] == "RESTRICTED"

        sub = validate_success(
            api.create_document_submission(
                ctx["items"][1]["id"], create_document_submission_payload(),
                owner_headers),
            201)
        validate_success(api.accept_document_submission(sub["id"], reviewer_headers))

        exam = get_exam(ctx["exam"]["id"])
        assert exam["overdue_item_count"] == 1, "submit-accept decrements once more"
        assert exam["posture"] == "RESTRICTED"

        roster, meta = validate_paginated(
            api.list_first_day_items(ctx["exam"]["id"], RAM, params={"limit": 100}))
        assert meta["total_count"] == 3, "the roster is conserved across the operations"
        statuses = sorted(i["status"] for i in roster)
        assert statuses == ["PENDING", "SUBMITTED", "WAIVED"]


class TestImmediateConsistency:
    def test_posture_recompute_visible_immediately_after_clock_advance(self, api):
        """PRD §2.5: "Advancing the clock is a system event: it fires every
        clock-driven transition described in §3.8 (issues and milestones whose
        due dates have been crossed move to `OVERDUE`) and recomputes
        `overdue_item_count` and `posture` on every affected examination."
        PRD §3.8: "otherwise it is `RESTRICTED` when at least one first-day item
        is overdue or any milestone stands overdue; otherwise it is `NORMAL`."

        Design: Corner/consistency_model/immediate_consistency_posture_visible_in_same_response
        """
        agency = create_agency(agency_code="IM")
        exam = create_examination(agency["id"])
        set_logical_clock("2026-07-01T00:00:00Z")
        create_first_day_item(exam["id"], due_date="2026-07-20T00:00:00Z")
        issue_first_day_letter(exam["id"])
        assert get_exam(exam["id"])["posture"] == "NORMAL"

        set_logical_clock("2026-07-21T00:00:00Z")
        exam_after = get_exam(exam["id"])
        assert exam_after["posture"] == "RESTRICTED", (
            "the very next read observes the recomputed posture — no async lag"
        )
        assert exam_after["overdue_item_count"] == 1
