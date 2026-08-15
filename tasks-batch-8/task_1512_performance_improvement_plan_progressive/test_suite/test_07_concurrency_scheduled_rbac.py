"""Concurrency (OCC), scheduled sweep, RBAC denials, check-in terminal lockdown,
legal override guard, and rebuttal window boundary."""
import pytest

from test_helpers import (
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    add_employee,
    create_employee,
    create_coaching_entries,
    create_and_submit_concern,
    create_and_accept_concern,
    create_and_publish_template,
    create_draft_pip,
    create_and_issue_pip,
    setup_concern_and_template,
    setup_issued_pip,
    setup_active_pip,
    create_check_in_payload,
    create_mark_held_payload,
    create_evidence_payload,
    create_rebuttal_payload,
    create_legal_review_payload,
    submit_legal_review_payload,
    create_and_submit_legal_review,
    propose_outcome,
    approve_outcome,
    get_pip,
    get_goals,
    set_clock,
    make_hrbp_headers,
    make_manager_headers,
    make_counsel_headers,
    make_director_headers,
    make_employee_headers,
)

LONG_REBUTTAL = (
    "Submitted at the exact window close boundary. The window is inclusive of "
    "the fifth day; this rebuttal must be accepted and the outcome decision "
    "must remain open for review. Body length exceeds the 100-character floor "
    "required by the validation rules."
)


class TestOptimisticConcurrency:
    def test_issue_with_stale_expected_version_rejected(self, api):
        """PRD §2.8: "Issuing a plan requires the request body to carry
        `expected_pip_version`, holding the `version` of the plan the client last
        observed; if the plan's current `version` has since advanced — because
        another writer mutated the plan after the client read it — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "the plan's `version` increments" (on issuance).
        PRD §2.6: the optimistic-concurrency check "is evaluated before any
        business rule on the plan-mutating endpoints that carry it".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_pip_issue
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        hrbp_headers = make_hrbp_headers(cast["hrbp_id"])
        # First issuance with the observed version succeeds and advances version.
        resp = api.issue_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            {"expected_pip_version": pip["version"]},
            hrbp_headers,
        )
        validate_success(resp)
        # A retry carrying the same (now stale) snapshot must be rejected: the
        # version mismatch surfaces ERR_STALE_VERSION before the state check.
        resp = api.issue_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            {"expected_pip_version": pip["version"]},  # stale snapshot
            hrbp_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_issue_with_current_expected_version_accepted(self, api):
        """PRD §2.8: "Issuing a plan requires the request body to carry
        `expected_pip_version`, holding the `version` of the plan the client last
        observed" — a snapshot matching the live version passes the check.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_pip_issue
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        resp = api.issue_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            {"expected_pip_version": pip["version"]},
            make_hrbp_headers(cast["hrbp_id"]),
        )
        issued = validate_success(resp)
        assert issued["status"] == "ISSUED"

    def test_outcome_approve_with_stale_expected_version_rejected(self, api):
        """PRD §2.8: "Approving an outcome decision carries the identical
        requirement: the body must contain `expected_pip_version` matching the
        plan's current `version`, and a mismatch is rejected with the same
        `ERR_STALE_VERSION` and HTTP 412".
        PRD §3.6: "Approval stamps `decided_at` and `decided_by_director_id`,
        opens the employee's rebuttal window ..., and increments the plan's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_outcome_approve
        """
        ctx = setup_active_pip()
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Proposing an extension of the plan window.")
        decision = validate_success(resp, expected_status=201)
        # Director snapshots the plan version...
        snapshot = get_pip(ctx)["version"]
        # ...the first approval succeeds with it (and advances the version).
        resp = api.approve_outcome_decision(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], decision["id"],
            {"expected_pip_version": snapshot},
            make_director_headers(director["id"]),
        )
        validate_success(resp)
        # A retried approval carrying the same stale snapshot must be rejected:
        # the version mismatch surfaces ERR_STALE_VERSION before the state check.
        resp = api.approve_outcome_decision(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], decision["id"],
            {"expected_pip_version": snapshot},
            make_director_headers(director["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestCheckInMissedSweep:
    def test_unheld_checkin_swept_to_missed_after_three_days(self, api):
        """PRD §3.4: "A check-in still unheld more than three days past
        `scheduled_for` is swept to `MISSED` automatically when the clock
        advances".

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_pip_auto_activates_at_start_date
        """
        ctx = setup_active_pip()
        # scheduled_for 2026-08-11; advance 4 days past -> sweep fires.
        set_clock(ctx["ou_id"], "2026-08-15T10:00:00Z")
        resp = api.list_check_ins(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        checkins = get_success_data(resp)
        by_id = {c["id"]: c for c in checkins}
        assert by_id[ctx["check_in_id"]]["status"] == "MISSED", (
            "check-in unheld more than three days past scheduled_for must be "
            f"swept to MISSED, got {by_id[ctx['check_in_id']]['status']}"
        )


class TestRbacDenials:
    def test_manager_cannot_accept_concern(self, api):
        """PRD §3.2: "An HRBP then adjudicates the submission — and it must be an
        HRBP other than the manager who raised it (`ERR_SEGREGATION_OF_DUTIES`)".
        PRD §2.1: "A caller whose role is not permitted for an endpoint ... is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." — POST
        .../performance-concerns/{id}/accept is HRBusinessPartner-only per §4.

        Design: Corner/rbac/manager_cannot_accept_concern
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        concern = create_and_submit_concern(cast, entry_ids)
        resp = api.accept_concern(
            cast["ou_id"], cast["emp_id"], concern["id"],
            make_manager_headers(cast["mgr_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_hrbp_cannot_approve_outcome_decision(self, api):
        """PRD §3.6: "Approval belongs to an `HRDirector`".
        PRD §2.1: "A caller whose role is not permitted for an endpoint ... is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." — POST
        .../outcome-decisions/{id}/approve is HRDirector-only per §4.

        Design: Corner/rbac/hrbp_cannot_approve_outcome_decision
        """
        ctx = setup_active_pip()
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Proposing an extension of the plan window.")
        decision = validate_success(resp, expected_status=201)
        pip_now = get_pip(ctx)
        resp = api.approve_outcome_decision(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], decision["id"],
            {"expected_pip_version": pip_now["version"]},
            make_hrbp_headers(ctx["hrbp_id"]),  # HRBP role on a director endpoint
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_employee_cannot_create_pip(self, api):
        """PRD §2.1: "A caller whose role is not permitted for an endpoint ... is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." — POST
        /hr-org-units/{ouId}/employees/{empId}/pips is HRBusinessPartner-only
        per §4.

        Design: Corner/rbac/employee_cannot_create_pip
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        resp = api.create_pip(
            cast["ou_id"], cast["emp_id"],
            {"concern_id": concern["id"], "template_id": template["id"],
             "start_date": "2026-08-01T00:00:00Z"},
            make_employee_headers(cast["emp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_other_counsel_cannot_claim_review(self, api):
        """PRD §3.5: "The assigned counsel — and only that counsel
        (`ERR_FORBIDDEN`) — claims the review, moving it `REQUESTED` →
        `IN_REVIEW`".

        Design: Corner/rbac/legal_counsel_cannot_claim_other_counsels_review
        """
        ctx = setup_issued_pip()
        counsel1 = add_employee(ctx["ou_id"], "Counsel1", "l1@x.com", job_level=8)
        counsel2 = add_employee(ctx["ou_id"], "Counsel2", "l2@x.com", job_level=8)
        resp = api.create_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_legal_review_payload(counsel1["id"]),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        review = validate_success(resp, expected_status=201)
        resp = api.claim_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], review["id"],
            make_counsel_headers(counsel2["id"]),  # not the assigned counsel
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestCheckInTerminalLockdown:
    def test_mark_held_twice_rejected(self, api):
        """PRD §3.4: "The check-in must still be `SCHEDULED` (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/checkin_invalid_transition_held_to_held
        """
        ctx = setup_active_pip()
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        validate_success(api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_mark_held_payload(notes="Initial mid-plan review."),
            hrbp_headers,
        ))
        resp = api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_mark_held_payload(notes="Attempted double-mark of the same check-in."),
            hrbp_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEvidenceTerminalLockdown:
    def test_exclude_on_admissible_evidence_rejected(self, api):
        """PRD §3.4: "an item not in `PENDING_REVIEW` rejects the attempt with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/evidence_terminal_lockdown_admissible
        """
        ctx = setup_active_pip()
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        # Manager submits evidence so the issuing HRBP may adjudicate (§3.4 SoD).
        mgr_headers = make_manager_headers(ctx["mgr_id"])
        goals = get_goals(ctx)
        resp = api.submit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_evidence_payload(goals[0]["id"], observed_value=1,
                                    source="SYSTEM_REPORT"),
            mgr_headers,
        )
        ev = validate_success(resp, expected_status=201)["id"]
        validate_success(api.admit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"], ev,
            hrbp_headers,
        ))
        resp = api.exclude_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"], ev,
            hrbp_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestLegalOverrideGuard:
    def test_override_of_proceed_recommendation_rejected(self, api):
        """PRD §3.5: "An HRDirector may override counsel, but only a `SUBMITTED`
        review whose recommendation is `REJECT` — overriding any other
        recommendation fails with `ERR_LEGAL_OVERRIDE_NOT_ALLOWED`".

        Design: Corner/state_machines/legal_review_override_of_non_reject_recommendation_rejected
        """
        ctx = setup_issued_pip()
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        review = create_and_submit_legal_review(
            ctx, hrbp_id=ctx["hrbp_id"],
            recommendation="PROCEED",
            rationale="No risk factors present; documentation is complete.",
        )
        resp = api.override_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], review["id"],
            make_director_headers(director["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEGAL_OVERRIDE_NOT_ALLOWED)


class TestRebuttalWindowBoundary:
    def _setup_approved_termination(self, api, post_approve_clock):
        ctx = setup_active_pip(
            category="CONDUCT",
            goal_blueprints=[
                {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
            ],
        )
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        ctx["director_id"] = director["id"]
        create_and_submit_legal_review(
            ctx, hrbp_id=ctx["hrbp_id"],
            rationale="Documentation is complete; no elevated legal risk.",
        )
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                               rationale="No improvement observed over the full plan window.")
        decision = validate_success(resp, expected_status=201)
        ctx["decision_id"] = decision["id"]
        validate_success(approve_outcome(ctx, decision["id"], director_id=director["id"]))
        set_clock(ctx["ou_id"], post_approve_clock)
        return ctx

    def test_rebuttal_at_exactly_five_days_accepted(self, api):
        """PRD §3.7: "Filing must land inside the window: the clock reading at or
        before five days after the decision's `decided_at`, failing which the
        submission is rejected with `ERR_REBUTTAL_WINDOW_CLOSED`." — "at or
        before" makes the exact five-day mark inclusive.

        Design: Difficulty/boundary_precision_check/rebuttal_window_close_at_exactly_plus_5_days
        """
        # decided_at = 2026-09-01T00:00:00Z; exactly +5 days is allowed.
        ctx = self._setup_approved_termination(api, "2026-09-06T00:00:00Z")
        resp = api.create_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_rebuttal_payload(ctx["decision_id"], body=LONG_REBUTTAL),
            make_employee_headers(ctx["emp_id"]),
        )
        rebuttal = validate_success(resp, expected_status=201)
        assert rebuttal["status"] == "SUBMITTED"

    def test_rebuttal_one_second_past_window_rejected(self, api):
        """PRD §3.7: "Filing must land inside the window: the clock reading at or
        before five days after the decision's `decided_at`, failing which the
        submission is rejected with `ERR_REBUTTAL_WINDOW_CLOSED`."

        Design: Corner/validations/rebuttal_submitted_after_window_returns_409
        """
        # decided_at = 2026-09-01T00:00:00Z; one second past +5 days is rejected.
        ctx = self._setup_approved_termination(api, "2026-09-06T00:00:01Z")
        resp = api.create_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_rebuttal_payload(ctx["decision_id"], body=LONG_REBUTTAL),
            make_employee_headers(ctx["emp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REBUTTAL_WINDOW_CLOSED)

    def test_rebuttal_by_non_subject_rejected(self, api):
        """PRD §3.7: "The plan's subject employee — and only that employee, with
        the acting identity compared against the plan's own employee
        (`ERR_REBUTTAL_NOT_SUBJECT`, HTTP 403) — may file a rebuttal".

        Design: Corner/validations/rebuttal_submitted_by_non_subject_returns_403
        """
        ctx = self._setup_approved_termination(api, "2026-09-03T00:00:00Z")
        other = add_employee(
            ctx["ou_id"], "E2 Other", "e2@x.com", job_family="ENGINEERING",
            job_level=5, manager_id=ctx["mgr_id"],
        )
        resp = api.create_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_rebuttal_payload(ctx["decision_id"], body=LONG_REBUTTAL),
            make_employee_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REBUTTAL_NOT_SUBJECT)
