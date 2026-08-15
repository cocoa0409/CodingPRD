"""Submittal review cycle, excusable-delay credit, and vacate-review reversal."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_submittal,
    create_active_project,
    create_submittal,
    review_submittal,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
)


def _project_and_submittal(api, spec_section="03 30 00", **project_overrides):
    project = create_active_project(**project_overrides)
    submittal = create_submittal(project["id"], spec_section=spec_section)
    return project, submittal


class TestReviseResubmitCycle:
    def test_resubmit_increments_revision_and_reopens_review(self, api):
        """PRD 3.2: "A `Contractor` resubmits a submittal sitting in
        `REVISE_AND_RESUBMIT`: `revision_number` increments by one, `received_at`
        is re-stamped from the clock, `due_at` is recomputed from the new
        `received_at`, `reviewed_at` returns to null, `credited_delay_days` resets
        to zero, and the submittal is `UNDER_REVIEW` again."

        Design: Difficulty/non_linear_state_machine/submittal_revise_resubmit_cycle
        """
        project, submittal = _project_and_submittal(api)
        assert submittal["revision_number"] == 1
        review_submittal(submittal["id"], "REVISE_AND_RESUBMIT", review_notes="Stamp missing")
        project_id = project["id"]
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.resubmit_submittal(submittal["id"], contractor_headers)
        resubmitted = validate_success(resp, 200)
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["revision_number"] == 2
        assert resubmitted["credited_delay_days"] == 0

    def test_approve_after_resubmit_lands_approved_with_zero_credit(self, api):
        """PRD 3.2: "`APPROVED` moves the submittal to `APPROVED`;
        `APPROVED_AS_NOTED` moves it to `APPROVED_AS_NOTED`; both stamp
        `reviewed_at` from the clock and then run the excusable-delay chain: the
        submittal's `credited_delay_days` becomes the number of whole calendar days
        between the date portion of `reviewed_at` and the date portion of `due_at`,
        or zero when the review lands on or before the due date — a review exactly
        on the due date credits nothing."

        Design: Difficulty/non_linear_state_machine/submittal_revise_resubmit_cycle
        """
        project, submittal = _project_and_submittal(api)
        review_submittal(submittal["id"], "REVISE_AND_RESUBMIT", review_notes="Stamp missing")
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        api.resubmit_submittal(submittal["id"], contractor_headers)
        final = review_submittal(submittal["id"], "APPROVED")
        assert final["status"] == "APPROVED"
        assert final["revision_number"] == 2
        # resubmitted and re-reviewed at the same default clock date -> no lateness
        assert final["credited_delay_days"] == 0
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 0


class TestVacateReviewConservesExcusableDelay:
    def _late_approved_submittal(self, api, outcome="APPROVED_AS_NOTED"):
        project, submittal = _project_and_submittal(api)
        set_clock("2026-08-14T09:00:00Z")
        reviewed = review_submittal(submittal["id"], outcome)
        return project, submittal, reviewed

    def test_late_review_credits_days_onto_project(self, api):
        """PRD 3.2: "the submittal's `credited_delay_days` becomes the number of
        whole calendar days between the date portion of `reviewed_at` and the date
        portion of `due_at`, or zero when the review lands on or before the due
        date" and "The project's `excusable_delay_days` is then recomputed as the
        sum of `credited_delay_days` over all of its submittals and RFIs".

        Design: Difficulty/compensating_invariant/vacate_review_conserves_excusable_delay_days
        """
        project, submittal, reviewed = self._late_approved_submittal(api)
        # received 2026-08-01, due 2026-08-11, reviewed 2026-08-14 -> 3 days late
        assert reviewed["credited_delay_days"] == 3
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 3

    def test_vacate_review_subtracts_credit_and_resets_submittal(self, api):
        """PRD 3.2: "vacating returns the submittal to `UNDER_REVIEW`, subtracts
        its credited days out of the project's `excusable_delay_days` and resets
        them to zero, clears `reviewed_at`, re-stamps `received_at`, recomputes
        `due_at`, and re-runs the posture and draft-invoice recompute chain."

        Design: Difficulty/compensating_invariant/vacate_review_conserves_excusable_delay_days
        """
        project, submittal, reviewed = self._late_approved_submittal(api)
        assert reviewed["credited_delay_days"] == 3
        resp = api.vacate_submittal_review(submittal["id"], make_architect_headers())
        vacated = validate_success(resp, 200)
        assert vacated["status"] == "UNDER_REVIEW"
        assert vacated["credited_delay_days"] == 0
        assert vacated["reviewed_at"] is None
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 0


class TestReviewDueDateEquality:
    def test_review_on_due_date_credits_zero(self, api):
        """PRD 3.2: "the submittal's `credited_delay_days` becomes the number of
        whole calendar days between the date portion of `reviewed_at` and the date
        portion of `due_at`, or zero when the review lands on or before the due
        date — a review exactly on the due date credits nothing."

        Design: Difficulty/boundary_precision_check/submittal_review_due_date_equality
        """
        project, submittal = _project_and_submittal(api)
        # received at the 2026-08-01 default clock with the default 10-day window
        assert submittal["due_at"].startswith("2026-08-11T00:00:00")
        set_clock("2026-08-11T00:00:00Z")
        reviewed = review_submittal(submittal["id"], "APPROVED")
        assert reviewed["credited_delay_days"] == 0

    def test_review_one_day_late_credits_exactly_one(self, api):
        """PRD 3.2: "the submittal's `credited_delay_days` becomes the number of
        whole calendar days between the date portion of `reviewed_at` and the date
        portion of `due_at`, or zero when the review lands on or before the due
        date — a review exactly on the due date credits nothing."

        Design: Difficulty/boundary_precision_check/submittal_review_due_date_equality
        """
        project = create_active_project()
        # S1 reviewed exactly on its due date -> 0
        s1 = create_submittal(project["id"], spec_section="03 30 00")
        set_clock("2026-08-11T00:00:00Z")
        r1 = review_submittal(s1["id"], "APPROVED")
        assert r1["credited_delay_days"] == 0
        # S2 received 2026-08-11 (due 2026-08-21), reviewed 2026-08-22 -> 1
        s2 = create_submittal(project["id"], spec_section="05 12 00",
                              required_on_site_date="2026-09-01")
        set_clock("2026-08-22T00:00:00Z")
        r2 = review_submittal(s2["id"], "APPROVED_AS_NOTED")
        assert r2["credited_delay_days"] == 1
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 1


class TestSubmittalInvalidStates:
    def test_review_rejected_submittal_returns_invalid_state(self, api):
        """PRD 3.2: "Reviewing a submittal that is not `UNDER_REVIEW`, resubmitting
        one that is not in `REVISE_AND_RESUBMIT`, or vacating one that is not in
        `APPROVED` or `APPROVED_AS_NOTED` all fail with
        `ERR_SUBMITTAL_INVALID_STATE` (HTTP 409)." Also: "`REJECTED` is terminal".

        Design: Corner/state_machines/review_rejected_submittal_returns_invalid_state
        """
        project, submittal = _project_and_submittal(api)
        review_submittal(submittal["id"], "REJECTED", review_notes="Not per spec")
        resp = api.review_submittal(submittal["id"], {"outcome": "APPROVED"},
                                    make_architect_headers())
        validate_error(resp, ApiErrorId.ERR_SUBMITTAL_INVALID_STATE, 409)
        current = get_success_data(api.get_submittal(submittal["id"], make_architect_headers()))
        assert current["status"] == "REJECTED"
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 0

    def test_resubmit_under_review_submittal_returns_invalid_state(self, api):
        """PRD 3.2: "Reviewing a submittal that is not `UNDER_REVIEW`, resubmitting
        one that is not in `REVISE_AND_RESUBMIT`, or vacating one that is not in
        `APPROVED` or `APPROVED_AS_NOTED` all fail with
        `ERR_SUBMITTAL_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/resubmit_under_review_submittal_returns_invalid_state
        """
        project, submittal = _project_and_submittal(api)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.resubmit_submittal(submittal["id"], contractor_headers)
        validate_error(resp, ApiErrorId.ERR_SUBMITTAL_INVALID_STATE, 409)
        current = get_success_data(api.get_submittal(submittal["id"], make_architect_headers()))
        assert current["revision_number"] == 1


class TestExcusableCreditExcludesRejected:
    def test_excusable_credit_excludes_rejected_review(self, api):
        """PRD 3.2: "`REVISE_AND_RESUBMIT` and `REJECTED` both stamp `reviewed_at`
        but set `credited_delay_days` to zero — contractor-caused rework earns no
        excusable credit — and trigger no project recompute."

        Design: Corner/calculations/excusable_credit_excludes_rejected_review
        """
        project, submittal = _project_and_submittal(api)
        set_clock("2026-08-14T09:00:00Z")
        reviewed = review_submittal(submittal["id"], "REJECTED",
                                    review_notes="Wrong mix design")
        assert reviewed["status"] == "REJECTED"
        assert reviewed["credited_delay_days"] == 0
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 0


class TestDefaultReviewWindows:
    def test_default_review_windows_applied_to_due_dates(self, api):
        """PRD 3.2: "its `due_at` computed as `received_at` plus the project's
        `review_window_days_submittal` calendar days" and PRD 3.4: "`due_at` is
        computed as `received_at` plus the project's `review_window_days_rfi`
        calendar days."

        Design: Corner/calculations/default_review_windows_applied_to_due_dates
        """
        from test_helpers import create_rfi
        project = create_active_project(
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 10000000}],
        )
        submittal = create_submittal(project["id"])
        rfi = create_rfi(project["id"], question="Confirm lintel bearing")
        assert submittal["received_at"].startswith("2026-08-01T00:00:00")
        assert submittal["due_at"].startswith("2026-08-11T00:00:00")
        assert rfi["received_at"].startswith("2026-08-01T00:00:00")
        assert rfi["due_at"].startswith("2026-08-08T00:00:00")


class TestLateReviewCascadesToInvoiceCancel:
    def _setup_invoice_scenario(self, api):
        """ACTIVE project; submittal received at default clock (due 2026-08-11);
        clock at 2026-11-05; DRAFT invoice for 2026-10-01..2026-11-30."""
        from test_helpers import create_draft_invoice
        project = create_active_project(grace_days=5)
        submittal = create_submittal(project["id"], spec_section="05 12 00")
        set_clock("2026-11-05T09:00:00Z")
        invoice = create_draft_invoice(project["id"], "2026-10-01", "2026-11-30")
        return project, submittal, invoice

    def test_late_approval_credits_97_days(self, api):
        """PRD 3.2: "the submittal's `credited_delay_days` becomes the number of
        whole calendar days between the date portion of `reviewed_at` and the date
        portion of `due_at`" and PRD 2.11: "The project's `excusable_delay_days` is
        the sum of `credited_delay_days` over all of the project's submittals and
        RFIs, recomputed after every submittal review, submittal vacate, RFI
        answer, and clarification-drawing issuance."

        Design: Difficulty/transitive_cascade/late_review_credit_cascades_to_invoice_cancel
        """
        project, submittal, invoice = self._setup_invoice_scenario(api)
        assert invoice["billable_days"] == 31
        set_clock("2026-11-16T09:00:00Z")
        reviewed = review_submittal(submittal["id"], "APPROVED")
        assert reviewed["credited_delay_days"] == 97  # 2026-08-11 -> 2026-11-16
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["excusable_delay_days"] == 97

    def test_late_approval_auto_cancels_draft_invoice(self, api):
        """PRD 3.8: "On any change to the project's `excusable_delay_days` or
        `adjusted_substantial_completion_date`, and again when substantial
        completion is achieved (which fixes the horizon end to
        `substantial_completion_actual_date`), every invoice of the project still
        in `DRAFT` recomputes its `horizon_start_date`, `horizon_end_date`,
        `billable_days`, and `amount_cents`; a draft whose `billable_days` falls to
        zero automatically transitions to `CANCELLED` and releases its period."

        Design: Difficulty/transitive_cascade/late_review_credit_cascades_to_invoice_cancel
        """
        project, submittal, invoice = self._setup_invoice_scenario(api)
        set_clock("2026-11-16T09:00:00Z")
        review_submittal(submittal["id"], "APPROVED")
        invoice = get_success_data(
            api.get_additional_service_invoice(invoice["id"], make_firm_admin_headers()))
        # horizon_start = 2026-09-30 + 97 days + 5 grace = 2027-01-10
        assert invoice["horizon_start_date"] == "2027-01-10"
        assert invoice["billable_days"] == 0
        assert invoice["status"] == "CANCELLED"


class TestCreateSubmittalBeforeActivation:
    def test_create_submittal_before_activation_returns_not_active(self, api):
        """PRD 3.1: "Creating a submittal, site visit, RFI, payment application,
        change order, or punch list item requires the project to be `ACTIVE`; ...
        Any of these creations attempted against a project in any other state is
        rejected with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/state_machines/create_submittal_before_activation_returns_not_active
        """
        from test_helpers import create_project
        project = create_project(
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 10000000}],
        )
        resp = api.create_submittal(
            {"project_id": project["id"], "spec_section": "03 30 00",
             "required_on_site_date": "2026-08-25"},
            make_contractor_headers(project["contractor_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACTIVE, 409)
        current = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert current["status"] == "SETUP"
