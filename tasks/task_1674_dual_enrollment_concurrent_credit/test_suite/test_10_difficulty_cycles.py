"""Difficulty rule non_linear_state_machine: the Enrollment REGISTERED ->
WITHDRAWN -> REGISTERED compensation loop, and the CredentialApplication
SUBMITTED -> UNDER_REVIEW -> NEEDS_REVISION -> SUBMITTED -> UNDER_REVIEW ->
APPROVED revision loop (PRD 3.3, 3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    begin_review,
    create_credential_application,
    first_invoice_for_enrollment,
    get_credential_application,
    get_enrollment,
    get_invoice,
    get_offering,
    list_invoices_for_enrollment,
    make_credential_reviewer_headers,
    make_instructor_headers,
    open_offering,
    register_and_confirm,
    reinstate_enrollment,
    set_clock,
    setup_base,
    validate_error,
    validate_success,
    withdraw_enrollment,
)

REVIEWER_1 = make_credential_reviewer_headers("rev-1")
REVIEWER_2 = make_credential_reviewer_headers("rev-2")


def _setup_withdrawn_cycle():
    """MATH151 (placement 70) fixture; student REGISTERED; clock inside the
    mismatch window; enrollment withdrawn."""
    ctx = setup_base(
        course_overrides={
            "course_code": "MATH151",
            "title": "College Algebra",
            "placement_exam_code": "MATH",
            "min_placement_score": 70,
        }
    )
    pair = register_and_confirm(
        ctx, placement={"exam_code": "MATH", "score": 85, "taken_at": "2026-08-01T00:00:00Z"}
    )
    ctx["student"] = pair["student"]
    ctx["enrollment"] = pair["enrollment"]
    set_clock("2026-09-12T00:00:00Z")
    ctx["withdrawn"] = withdraw_enrollment(pair["enrollment"]["id"])
    return ctx


class TestEnrollmentWithdrawReinstateCycle:
    def test_withdraw_then_reinstate_closes_the_cycle(self, api):
        """PRD 3.5: "Withdraw moves the enrollment to `WITHDRAWN`, sets `grade` to
        `W`, stamps `withdrawn_at` with the current logical-clock timestamp,
        decrements `seats_taken` by 1, and increments the offering's `version`."
        PRD 3.5: "Reinstate clears `grade` to null and `withdrawn_at` to null,
        increments `seats_taken` by 1, increments the offering's `version`, and
        creates a brand-new `Invoice` per §3.7 — the previous invoice keeps its own
        state and refund fields."

        Design: Difficulty/non_linear_state_machine/enrollment_withdraw_reinstate_cycle
        """
        ctx = _setup_withdrawn_cycle()
        withdrawn = ctx["withdrawn"]
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["grade"] == "W"
        assert_same_instant(
            withdrawn["withdrawn_at"], "2026-09-12T00:00:00Z", "Enrollment.withdrawn_at"
        )
        offering_after_withdraw = get_offering(ctx["offering"]["id"])
        assert offering_after_withdraw["seats_taken"] == 0

        reinstated = reinstate_enrollment(ctx["offering"]["id"], ctx["enrollment"]["id"])
        assert reinstated["status"] == "REGISTERED", (
            "The cycle REGISTERED -> WITHDRAWN -> REGISTERED closes"
        )
        assert reinstated["grade"] is None, "Reinstate clears grade to null"
        assert reinstated["withdrawn_at"] is None, "Reinstate clears withdrawn_at to null"
        offering_after = get_offering(ctx["offering"]["id"])
        assert offering_after["seats_taken"] == 1
        assert offering_after["seats_available"] == 1

    def test_reinstate_issues_a_new_invoice_and_preserves_the_old_audit(self, api):
        """PRD 3.5: "Reinstate clears `grade` to null and `withdrawn_at` to null,
        increments `seats_taken` by 1, increments the offering's `version`, and
        creates a brand-new `Invoice` per §3.7 — the previous invoice keeps its own
        state and refund fields."
        PRD 3.7: "When an enrollment reaches `REGISTERED` — by confirm, by waitlist
        promotion, or by reinstate — an `Invoice` is created."
        PRD 3.7: "The invoice records its own `enrollment_id` and the
        `funding_agreement_id` used for the allocation, tracks what has actually
        been collected per payer — `paid_state_cents`, `paid_district_cents`, and
        `paid_family_cents`, each starting at 0 — and its `status` starts at
        `ISSUED` with `refund_status` `NONE`."

        Design: Difficulty/non_linear_state_machine/enrollment_withdraw_reinstate_cycle
        """
        ctx = _setup_withdrawn_cycle()
        first_invoice = first_invoice_for_enrollment(ctx["enrollment"]["id"])

        reinstate_enrollment(ctx["offering"]["id"], ctx["enrollment"]["id"])

        invoices = list_invoices_for_enrollment(ctx["enrollment"]["id"])
        assert len(invoices) == 2, (
            f"Reinstate issues a brand-new invoice alongside the old one; expected "
            f"2 invoices, got {len(invoices)}"
        )
        old_invoice = get_invoice(first_invoice["id"])
        assert old_invoice["refund_pct"] == 50, (
            f"The old invoice keeps its refund fields as audit: refund_pct 50, got "
            f"{old_invoice['refund_pct']}"
        )
        assert old_invoice["refund_estimate_cents"] == 60000
        new_invoice = next(inv for inv in invoices if inv["id"] != first_invoice["id"])
        assert new_invoice["status"] == "ISSUED"
        assert new_invoice["refund_status"] == "NONE"
        assert new_invoice["tuition_total_cents"] == 120000


def _setup_credential_loop():
    """DRAFT offering whose instructor has an application pushed through one
    request-revision; returns (ctx, application)."""
    ctx = setup_base(approve_credential=False, open_offering_flag=False)
    application = create_credential_application(
        ctx["instructor"]["id"], ctx["course"]["id"]
    )
    begin_review(application["id"], REVIEWER_1)
    return ctx, application


class TestCredentialRevisionLoop:
    def test_request_revision_then_resubmit_releases_review_ownership(self, api):
        """PRD 3.3: "Request-revision moves it to `NEEDS_REVISION` and records an
        optional `decision_reason`."
        PRD 3.3: "From `NEEDS_REVISION`, the applicant — the `Instructor` whose
        `X-User-ID` equals `instructor_id`, else `ERR_NOT_RESOURCE_OWNER` —
        resubmits, returning the application to `SUBMITTED` and clearing
        `reviewed_by` to null, releasing the prior review ownership."

        Design: Difficulty/non_linear_state_machine/credential_revision_loop
        """
        ctx, application = _setup_credential_loop()
        revised = validate_success(
            api.request_credential_revision(
                application["id"],
                {"decision_reason": "Need syllabus with college-level outcomes"},
                REVIEWER_1,
            )
        )
        assert revised["status"] == "NEEDS_REVISION"
        assert revised["decision_reason"] == "Need syllabus with college-level outcomes"

        resubmitted = validate_success(
            api.resubmit_credential_application(
                application["id"], make_instructor_headers(ctx["instructor"]["id"])
            )
        )
        assert resubmitted["status"] == "SUBMITTED", "The loop returns to SUBMITTED"
        assert resubmitted["reviewed_by"] is None, (
            "Resubmit releases the prior review ownership"
        )

    def test_second_reviewer_can_claim_and_approve_after_resubmit(self, api):
        """PRD 3.3: "From `NEEDS_REVISION`, the applicant — the `Instructor` whose
        `X-User-ID` equals `instructor_id`, else `ERR_NOT_RESOURCE_OWNER` —
        resubmits, returning the application to `SUBMITTED` and clearing
        `reviewed_by` to null, releasing the prior review ownership."
        PRD 3.4: "Opening requires both referenced terms to be `OPEN` (else
        `ERR_TERM_NOT_OPEN`), the course to be `ACTIVE` (else `ERR_INVALID_STATE`),
        and an `APPROVED` `CredentialApplication` to exist matching the offering's
        `instructor_id` and `course_id` (else `ERR_INSTRUCTOR_NOT_CREDENTIALED`,
        HTTP 409)."

        Design: Difficulty/non_linear_state_machine/credential_revision_loop
        """
        ctx, application = _setup_credential_loop()
        validate_success(api.request_credential_revision(application["id"], {}, REVIEWER_1))
        validate_success(
            api.resubmit_credential_application(
                application["id"], make_instructor_headers(ctx["instructor"]["id"])
            )
        )

        reclaimed = begin_review(application["id"], REVIEWER_2)
        assert reclaimed["reviewed_by"] == "rev-2", (
            "A different reviewer can claim the resubmitted application"
        )
        approved = validate_success(api.approve_credential_application(application["id"], {}, REVIEWER_2))
        assert approved["status"] == "APPROVED"

        opened = open_offering(ctx["offering"]["id"])
        assert opened["status"] == "OPEN", (
            "With the credential now APPROVED, the credential gate passes"
        )
