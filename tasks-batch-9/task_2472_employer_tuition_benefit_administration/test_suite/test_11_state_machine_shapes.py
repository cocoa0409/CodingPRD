"""A bounded revision loop, and two status axes that refuse to be one field."""

from test_helpers import (
    AcademicStatus,
    ApprovalDecision,
    ApprovalRequestStatus,
    ClaimDecision,
    CompletionStatus,
    ERR_REVISION_LIMIT_REACHED,
    FundingModel,
    FundingStatus,
    InvoiceStatus,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_enrollment_axes,
    build_northwind_exception_program,
    build_northwind_revision_cycle,
    build_ridgeline_base,
    build_ridgeline_direct_bill_paid,
    resubmit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_revision_loop_is_traversable_exactly_twice(api):
    """Two full CHANGES_REQUESTED → SUBMITTED → UNDER_REVIEW laps, counter at 2.

    PRD §3.3: "A `decision` of `REQUEST_CHANGES` moves the request `UNDER_REVIEW →
    CHANGES_REQUESTED`, records `decision_note`, creates no listing, and opens the
    revision cycle."

    PRD §3.3: "From `CHANGES_REQUESTED` the requesting `Employee` may resubmit, moving
    the request `CHANGES_REQUESTED → SUBMITTED` and incrementing `revision_count` by 1;
    the resubmission may optionally replace `justification` and
    `requested_annual_cost_cents`, and each supplied value overwrites the previous one."

    Design: Difficulty/non_linear_state_machine/approval_request_revision_cycle_capped_at_two_rounds
    """
    s = build_northwind_exception_program(api)

    opened = s.open_approval_request(
        program_id=s.second_program_id,
        justification="Analytics degree needed for the demand-planning ladder.",
        requested_annual_cost_cents=540_000,
    )
    assert opened["status"] == ApprovalRequestStatus.SUBMITTED
    assert opened["revision_count"] == 0
    assert opened["decision_note"] is None

    assert s.review_request()["status"] == ApprovalRequestStatus.UNDER_REVIEW
    first_decision = s.decide_request(
        ApprovalDecision.REQUEST_CHANGES, "Add the manager endorsement."
    )
    assert first_decision["status"] == ApprovalRequestStatus.CHANGES_REQUESTED
    assert first_decision["decision_note"] == "Add the manager endorsement."

    first_lap = validate_success(
        api.resubmit_program_approval_request(
            s.request_id,
            resubmit_payload(
                justification="Manager endorsement attached; ladder plan revised."
            ),
            s.employee,
        )
    )
    assert first_lap["status"] == ApprovalRequestStatus.SUBMITTED
    assert first_lap["revision_count"] == 1
    assert (
        first_lap["justification"]
        == "Manager endorsement attached; ladder plan revised."
    )
    assert first_lap["requested_annual_cost_cents"] == 540_000

    assert s.review_request()["status"] == ApprovalRequestStatus.UNDER_REVIEW
    second_decision = s.decide_request(
        ApprovalDecision.REQUEST_CHANGES, "Cost estimate still exceeds the annual cap."
    )
    assert second_decision["status"] == ApprovalRequestStatus.CHANGES_REQUESTED
    assert (
        second_decision["decision_note"] == "Cost estimate still exceeds the annual cap."
    )

    second_lap = validate_success(
        api.resubmit_program_approval_request(
            s.request_id, resubmit_payload(requested_annual_cost_cents=480_000), s.employee
        )
    )
    assert second_lap["status"] == ApprovalRequestStatus.SUBMITTED
    assert second_lap["revision_count"] == 2
    assert second_lap["requested_annual_cost_cents"] == 480_000
    assert (
        second_lap["justification"]
        == "Manager endorsement attached; ladder plan revised."
    )


def test_a_third_resubmission_is_refused_and_no_listing_ever_materialises(api):
    """revision_count 2 closes the loop, and the REQUEST_CHANGES branch curates nothing.

    PRD §3.3: "Resubmission requires `revision_count` to be strictly less than 2, so
    the loop from `CHANGES_REQUESTED` back through `SUBMITTED` and `UNDER_REVIEW` to
    `CHANGES_REQUESTED` can run at most twice; a third resubmission attempt is refused
    with `ERR_REVISION_LIMIT_REACHED`."

    PRD §2.9: "The approval request's `revision_count` is less than 2; otherwise
    `ERR_REVISION_LIMIT_REACHED` (409). Applies to
    `POST /program-approval-requests/{id}/resubmit`."

    Design: Difficulty/non_linear_state_machine/approval_request_revision_cycle_capped_at_two_rounds
    """
    s = build_northwind_revision_cycle(api)

    validate_error(
        api.resubmit_program_approval_request(
            s.request_id, resubmit_payload(justification="One more try, please."), s.employee
        ),
        ERR_REVISION_LIMIT_REACHED,
        409,
    )

    unchanged = validate_success(
        api.get_program_approval_request(s.request_id, s.employee)
    )
    assert unchanged["status"] == ApprovalRequestStatus.CHANGES_REQUESTED
    assert unchanged["revision_count"] == 2
    assert unchanged["decision_note"] == "Third pass: cost still not funded."
    assert unchanged["requested_annual_cost_cents"] == 480_000

    _, meta = validate_paginated(
        api.list_catalog_listings(
            s.benefit_admin, {"source_request_id": s.request_id}
        )
    )
    assert meta["total_count"] == 0


def test_the_money_axis_advances_to_settled_while_the_academic_axis_lags(api):
    """A direct-bill term reaches SETTLED with no outcome on file at all.

    PRD §3.5: "When the enrollment's `funding_model` is `DIRECT_BILL`, a
    `TuitionInvoice` is raised against the enrollment: its `enrollment_id` points back
    at the enrollment, its `amount_cents` is the enrollment's `employer_reserved_cents`
    as of that moment, its `due_date` is the `term_start_date` advanced by 30 days, its
    `status` is `ISSUED` and its `paid_on` is null — and the enrollment's money axis
    moves `RESERVED → BILLED`."

    PRD §3.6: "What it pointedly does **not** do is touch the money axis: a
    reimbursement enrollment stays `RESERVED` until a claim is approved, and a
    direct-bill enrollment stays exactly where its invoice left it."

    Design: Difficulty/non_linear_state_machine/enrollment_academic_and_funding_axes_advance_independently
    """
    s = build_ridgeline_base(api)
    created = s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=4,
        funding_model=FundingModel.DIRECT_BILL,
    )
    assert created["gross_tuition_cents"] == 120_000
    assert created["employer_reserved_cents"] == 120_000

    confirmed = s.confirm_registration()
    assert_enrollment_axes(
        confirmed, AcademicStatus.IN_PROGRESS, FundingStatus.BILLED
    )

    invoices, invoice_meta = validate_paginated(
        api.list_enrollment_invoices(s.enrollment_id, s.benefit_admin)
    )
    assert invoice_meta["total_count"] == 1
    assert invoices[0]["amount_cents"] == 120_000
    assert invoices[0]["due_date"] == "2026-10-01"
    assert invoices[0]["status"] == InvoiceStatus.ISSUED
    assert invoices[0]["paid_on"] is None

    s.first_invoice()
    s.approve_invoice()
    s.pay_invoice()

    paid = s.read_enrollment()
    assert_enrollment_axes(paid, AcademicStatus.IN_PROGRESS, FundingStatus.SETTLED)
    assert paid["employer_disbursed_cents"] == 120_000
    _, outcome_meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert outcome_meta["total_count"] == 0

    s.post_outcome("2026-FA", CompletionStatus.PASSED, 4, 3.00)
    after_outcome = s.read_enrollment()
    assert_enrollment_axes(after_outcome, AcademicStatus.PASSED, FundingStatus.SETTLED)
    assert after_outcome["employer_disbursed_cents"] == 120_000


def test_the_academic_axis_reaches_passed_while_the_money_axis_lags(api):
    """A reimbursement term sits at (PASSED, RESERVED) until the claim is approved.

    PRD §3.5: "When the `funding_model` is `REIMBURSEMENT`, no invoice is created at
    all and the money axis stays `RESERVED` until a claim is approved."

    PRD §3.6: "A passing outcome moves the academic axis `IN_PROGRESS → PASSED`, copies
    `credits_earned` onto the enrollment, and recomputes `persistence_risk_score`,
    `persistence_tier` and the employee's `coaching_hold`."

    Design: Difficulty/non_linear_state_machine/enrollment_academic_and_funding_axes_advance_independently
    """
    s = build_ridgeline_direct_bill_paid(api)
    second = s.enroll(
        term_code="2026-WI",
        term_start_date="2026-12-16",
        term_end_date="2027-03-31",
        credits=4,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    s.second_enrollment_id = s.enrollment_id
    assert second["gross_tuition_cents"] == 120_000
    assert second["employer_reserved_cents"] == 60_000

    confirmed = s.confirm_registration()
    assert_enrollment_axes(confirmed, AcademicStatus.IN_PROGRESS, FundingStatus.RESERVED)
    _, invoice_meta = validate_paginated(
        api.list_enrollment_invoices(s.enrollment_id, s.benefit_admin)
    )
    assert invoice_meta["total_count"] == 0

    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-WI", CompletionStatus.PASSED, 4, 3.00)
    after_outcome = s.read_enrollment()
    assert_enrollment_axes(after_outcome, AcademicStatus.PASSED, FundingStatus.RESERVED)
    assert after_outcome["employer_disbursed_cents"] == 0
    assert after_outcome["credits_earned"] == 4

    s.file_claim(120_000, "FRCC-2026WI-TWELLER-01")
    decided = s.decide_claim(ClaimDecision.APPROVE)
    assert decided["approved_amount_cents"] == 60_000
    assert decided["platform_admin_fee_cents"] == 3_000

    settled = s.read_enrollment()
    assert_enrollment_axes(settled, AcademicStatus.PASSED, FundingStatus.SETTLED)
    assert settled["employer_settled_cents"] == 60_000
    assert settled["employer_disbursed_cents"] == 60_000

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 180_000, 0, 1_820_000)
    assert_cap_pool_conserved(employee, 2_000_000)
