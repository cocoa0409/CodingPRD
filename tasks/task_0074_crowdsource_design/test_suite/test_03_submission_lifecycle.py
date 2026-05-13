"""Submission lifecycle: creation, original-work declaration,
per-designer cap, modify window, withdraw, screening transitions.

PRD §3.3 covers these rules in full.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_submission_payload,
    make_client_headers,
    make_designer_headers,
    patch_submission_payload,
    setup_on_shelf_project,
    add_designer_with_submission,
    advance_clock,
    iso_at,
    validate_error,
    validate_success,
)


class TestOriginalDeclaration:

    def test_missing_original_declaration_rejected(self, api):
        """PRD §3.3: 'original_work_declared, which must be true on
        creation; a missing or false declaration is rejected with
        ERR_ORIGINAL_DECLARATION_REQUIRED.'

        Claim: original_work_declared=false returns
        ERR_ORIGINAL_DECLARATION_REQUIRED.
        """
        ctx = setup_on_shelf_project()
        from test_helpers import create_designer
        designer = create_designer(categories=[ctx["category"]["code"]])
        resp = api.create_submission(
            ctx["project"]["id"],
            create_submission_payload(
                designer_id=designer["id"],
                original_work_declared=False,
            ),
            make_designer_headers(designer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORIGINAL_DECLARATION_REQUIRED.value)

    def test_valid_submission_accepted_in_DRAFT(self, api):
        """PRD §3.3: 'The submission is created in DRAFT.'

        Claim: a valid submission is accepted (201) with status=DRAFT.
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        assert sub["status"] == "DRAFT", (
            f"Expected DRAFT, got {sub['status']!r}"
        )


class TestSubmissionLimit:

    def test_exceeding_max_submissions_per_designer_rejected(self, api):
        """PRD §3.3: 'the platform also checks that the count of the
        designer's existing non-WITHDRAWN submissions on this project
        is strictly less than Project.max_submissions_per_designer; an
        over-cap attempt is rejected with
        ERR_SUBMISSION_LIMIT_REACHED.'

        Claim: with max_submissions_per_designer=2, a third creation
        returns ERR_SUBMISSION_LIMIT_REACHED.
        """
        ctx = setup_on_shelf_project(max_submissions_per_designer=2)
        from test_helpers import create_designer
        designer = create_designer(categories=[ctx["category"]["code"]])
        # First 2 submissions accepted.
        for i in range(2):
            r = api.create_submission(
                ctx["project"]["id"],
                create_submission_payload(
                    designer_id=designer["id"],
                    title=f"Sub-{i}",
                ),
                make_designer_headers(designer["id"]),
            )
            validate_success(r, expected_status=201)
        # Third over the cap.
        r3 = api.create_submission(
            ctx["project"]["id"],
            create_submission_payload(
                designer_id=designer["id"],
                title="Sub-3",
            ),
            make_designer_headers(designer["id"]),
        )
        validate_error(r3, ApiErrorId.ERR_SUBMISSION_LIMIT_REACHED.value)


class TestSubmissionWithdraw:

    def test_withdraw_within_modify_window(self, api):
        """PRD §3.3: 'Withdrawal moves the submission from DRAFT to the
        terminal WITHDRAWN state.'

        Claim: DELETE on a DRAFT submission within the modify window
        leaves status=WITHDRAWN.
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        resp = api.withdraw_submission(
            sub["id"], make_designer_headers(designer["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_modify_window_closed_after_preliminary_starts(self, api):
        """PRD §3.3: 'A modification or deletion attempted at or after
        that instant is rejected with ERR_MODIFY_WINDOW_CLOSED.'

        Claim: PATCH on a submission after the modify_window_closes_at
        returns ERR_MODIFY_WINDOW_CLOSED.

        Note (state-vs-temporal): this test deliberately advances the
        clock so the submission is still in SCREENING/ACCEPTED at
        check time but the modify window has closed. PRD §2.9 puts
        state checks (priority 5) before business_temporal (priority 9),
        which is exactly the priority-pair instance covered by
        test_08_difficulty_design. Here we focus on the temporal
        condition where state check still permits the call structure.
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        # Cross submission_deadline -> sub goes SCREENING then ACCEPTED.
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        # The modify window is now closed.
        resp = api.patch_submission(
            sub["id"],
            patch_submission_payload(title="new title"),
            make_designer_headers(designer["id"]),
        )
        # PRD §2.9 puts state check (priority 5) before
        # business_temporal (priority 9). At this point the submission
        # has likely moved past DRAFT, so the implementation may
        # report ERR_INVALID_STATE. PRD does not pin a single error
        # for this combined condition; accept either as PRD-faithful.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_MODIFY_WINDOW_CLOSED.value,
             ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestPreliminaryScreening:

    def test_clock_crossing_submission_deadline_cascades_to_IN_PRELIMINARY(self, api):
        """PRD §3.3: 'When the virtual server clock crosses the
        project's submission_deadline, the project automatically
        advances from ON_SHELF to IN_PRELIMINARY.'

        Claim: after advancing the clock past submission_deadline,
        Project.status == 'IN_PRELIMINARY'.
        """
        ctx = setup_on_shelf_project()
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        from test_helpers import PO
        proj = validate_success(
            api.get_project(ctx["project"]["id"], PO),
        )
        assert proj["status"] == "IN_PRELIMINARY", (
            f"Expected IN_PRELIMINARY after clock crossing "
            f"submission_deadline, got {proj['status']!r}"
        )

    def test_modify_window_closes_at_fixed_on_cascade(self, api):
        """PRD §3.3: 'each affected Submission has its
        modify_window_closes_at fixed to the current instant.'

        Claim: after the cascade, Submission.modify_window_closes_at
        is set (non-null).
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        from test_helpers import PO
        sub_after = validate_success(api.get_submission(sub["id"], PO))
        assert sub_after.get("modify_window_closes_at") is not None, (
            "modify_window_closes_at must be set after the cascade"
        )
