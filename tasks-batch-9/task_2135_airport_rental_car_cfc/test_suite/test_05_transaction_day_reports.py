"""Transaction-day reporting and the audit revision cycle."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_revision_cycle_returns_to_draft_and_counts_submissions(api):
    """PRD §3.5: "Each submission raises `submission_count` by 1, so a report that has been
    rejected and resubmitted carries a submission count above 1."
    PRD §3.5: "A rejected report is handed back to the operator, who reopens it, carrying
    `REJECTED → DRAFT` and clearing `rejection_reason` back to null; this closes the `DRAFT →
    SUBMITTED → UNDER_AUDIT → REJECTED → DRAFT` revision cycle, which may run any number of
    times."

    Design: Difficulty/non_linear_state_machine/report_rejection_revision_cycle_returns_to_draft_then_accepts
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=4,
        reported_gross_revenue_cents=3_000_000,
        reported_on_airport_transaction_days=900,
    )
    submitted = fx.submit_report(api, report["id"], operator)
    assert submitted["submission_count"] == 1
    fx.begin_audit(api, report["id"])

    rejected = validate_success(
        api.reject_report(
            report["id"],
            f.reject_report_payload(
                rejection_reason="Understated on-airport transaction days"
            ),
            AUDITOR,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "Understated on-airport transaction days"

    reopened = validate_success(api.reopen_report(report["id"], operator))
    assert reopened["status"] == "DRAFT", "a reopened report returns to DRAFT"
    assert reopened["rejection_reason"] is None, "reopening clears rejection_reason to null"

    resubmitted = fx.submit_report(api, report["id"], operator)
    assert resubmitted["submission_count"] == 2, (
        f"the second submission must raise submission_count to 2, "
        f"got {resubmitted['submission_count']}"
    )
    fx.begin_audit(api, report["id"])

    accepted = validate_success(
        api.accept_report(
            report["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=3_000_000,
                audited_on_airport_transaction_days=1_200,
            ),
            AUDITOR,
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["submission_count"] == 2
    assert accepted["rejection_reason"] is None


def test_acceptance_after_the_revision_cycle_posts_audited_days(api):
    """PRD §3.5: "The agreement's `accepted_report_count` rises by 1, its
    `gross_revenue_ytd_cents` rises by `audited_gross_revenue_cents`, and its
    `transaction_days_ytd` rises by `audited_on_airport_transaction_days`."
    PRD §3.5: "`variance_assessment_cents` is the greater of zero and
    `revenue_variance_cents`, multiplied by the agreement's `percentage_rent_rate_bps`,
    divided by 10,000 and rounded half up"
    PRD §3.5: "When `variance_assessment_cents` came out greater than zero, the agreement's
    `compliance_status` moves to `COVENANT_BREACH`, from either `COMPLIANT` or `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/report_rejection_revision_cycle_returns_to_draft_then_accepts
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=4,
        reported_gross_revenue_cents=3_000_000,
        reported_on_airport_transaction_days=900,
    )
    fx.submit_report(api, report["id"], operator)
    fx.begin_audit(api, report["id"])
    fx.reject_report(api, report["id"])
    fx.reopen_report(api, report["id"], operator)
    fx.submit_report(api, report["id"], operator)
    fx.begin_audit(api, report["id"])

    accepted = validate_success(
        api.accept_report(
            report["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=3_000_000,
                audited_on_airport_transaction_days=1_200,
            ),
            AUDITOR,
        )
    )

    assert accepted["audited_on_airport_transaction_days"] == 1_200
    assert accepted["revenue_variance_cents"] == 0, (
        "the corrected revenue matches the reported figure exactly"
    )
    assert accepted["variance_assessment_cents"] == 0
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["transaction_days_ytd"] == 1_200
    assert agreement["compliance_status"] == "COMPLIANT", (
        "a zero variance assessment leaves the compliance axis alone"
    )


def test_amended_report_supersedes_the_original(api):
    """PRD §3.5: "Before the cascade proper begins, there is a housekeeping step: if any
    *other* report of the same agreement, for the same `period_year` and `period_month`, is
    already in `ACCEPTED`, that earlier report is demoted `ACCEPTED → SUPERSEDED` — the
    terminal status for a displaced report — its own `version` advances by 1, and its
    contribution is subtracted from the agreement's `gross_revenue_ytd_cents`,
    `transaction_days_ytd` and `accepted_report_count` before anything is added back."
    PRD §3.5: "An already-`ACCEPTED` period is deliberately *not* blocked: amending a closed
    period is a legitimate audit outcome, and the amendment supersedes the earlier figure when
    it is itself accepted."

    Design: Difficulty/compensating_invariant/rent_ledger_conservation_when_amended_report_supersedes_original
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    original = fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    amendment = fx.create_report_under_audit(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=9_000_000,
        reported_on_airport_transaction_days=4_000,
    )

    accepted = validate_success(
        api.accept_report(
            amendment["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=9_000_000,
                audited_on_airport_transaction_days=4_000,
            ),
            AUDITOR,
        )
    )

    assert accepted["status"] == "ACCEPTED"
    superseded = validate_success(api.get_report(original["id"], ADMIN))
    assert superseded["status"] == "SUPERSEDED"
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["gross_revenue_ytd_cents"] == 9_000_000, (
        "the superseded 5,000,000 must be subtracted before the 9,000,000 is added"
    )
    assert agreement["transaction_days_ytd"] == 4_000
    assert agreement["accepted_report_count"] == 1


def test_amended_acceptance_recomputes_the_rent_ledger(api):
    """PRD §3.5: "Under the `CUMULATIVE_YTD` variant, the rent due to date is the greater of
    the year-to-date percentage rent and the minimum guarantee to date, and the installment
    for this acceptance is that rent due to date minus the agreement's
    `rent_billed_to_date_cents` as it stood before this acceptance."
    PRD §3.5: "The epilogue is identical for both variants. The agreement's
    `percentage_rent_accrued_cents` is set to the year-to-date percentage rent; its
    `rent_billed_to_date_cents` rises by the installment; its `last_installment_cents` is set
    to the installment; its `mag_shortfall_cents` is set to the greater of zero and the
    minimum guarantee to date minus the year-to-date percentage rent; and its `rent_tier`
    becomes `PERCENTAGE` when the year-to-date percentage rent is strictly greater than the
    minimum guarantee to date, and `MAG_FLOOR` otherwise."

    Design: Difficulty/compensating_invariant/rent_ledger_conservation_when_amended_report_supersedes_original
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    amendment = fx.create_report_under_audit(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=9_000_000,
        reported_on_airport_transaction_days=4_000,
    )

    accepted = validate_success(
        api.accept_report(
            amendment["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=9_000_000,
                audited_on_airport_transaction_days=4_000,
            ),
            AUDITOR,
        )
    )

    assert accepted["revenue_variance_cents"] == 0
    assert accepted["variance_assessment_cents"] == 0
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["percentage_rent_accrued_cents"] == 900_000, (
        "9,000,000 cents at 1000 bps accrues 900,000 cents of percentage rent"
    )
    assert agreement["rent_billed_to_date_cents"] == 1_000_000, (
        "the 1,000,000 cent monthly floor was already billed, so nothing more is due"
    )
    assert agreement["last_installment_cents"] == 0
    assert agreement["mag_shortfall_cents"] == 100_000
    assert agreement["rent_tier"] == "MAG_FLOOR"


def test_accepting_a_report_that_never_entered_audit_is_rejected(api):
    """PRD §3.5: "It requires the report to be in `UNDER_AUDIT` and requires both supplied
    figures — `audited_gross_revenue_cents` and `audited_on_airport_transaction_days` — to be
    at least 0."
    PRD §2.6: "State: the target resource sits in a from-state that the requested transition
    declares, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/accept_a_report_that_never_entered_audit_returns_invalid_state
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(api, agreement_id, operator)
    fx.submit_report(api, report["id"], operator)

    response = api.accept_report(
        report["id"], f.accept_report_payload(), AUDITOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = validate_success(api.get_report(report["id"], ADMIN))
    assert stored["status"] == "SUBMITTED"
    assert stored["audited_gross_revenue_cents"] is None
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["gross_revenue_ytd_cents"] == 0
    assert agreement["accepted_report_count"] == 0


def test_second_open_report_for_a_period_is_rejected(api):
    """PRD §3.5: "An agreement may hold at most one report per `period_year` and
    `period_month` combination in any of the statuses `DRAFT`, `SUBMITTED`, `UNDER_AUDIT` or
    `REJECTED`; a second draft for a period already occupied by one of those is rejected with
    `ERR_DUPLICATE_REPORT_PERIOD` (HTTP 409)."

    Design: Corner/validations/second_open_report_for_the_same_period_is_rejected
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(api, agreement_id, operator, period_year=2026, period_month=1)
    fx.submit_report(api, report["id"], operator)

    response = api.create_report(
        f.report_payload(
            agreement_id, period_year=2026, period_month=1,
            reported_gross_revenue_cents=9_000_000,
            reported_on_airport_transaction_days=4_000,
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD.value, 409)
    _rows, meta = validate_paginated(
        api.list_reports(ADMIN, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1, "the blocked period must still hold exactly one report"


def test_over_report_attracts_no_variance_assessment(api):
    """PRD §3.5: "`revenue_variance_cents` is set to `audited_gross_revenue_cents` minus
    `reported_gross_revenue_cents`, which may be negative when the operator over-reported;
    `variance_assessment_cents` is the greater of zero and `revenue_variance_cents`,
    multiplied by the agreement's `percentage_rent_rate_bps`, divided by 10,000 and rounded
    half up — so an under-report is assessed at the agreement's own rent rate while an
    over-report attracts no assessment at all"
    PRD §3.5: "When `variance_assessment_cents` came out greater than zero, the agreement's
    `compliance_status` moves to `COVENANT_BREACH`, from either `COMPLIANT` or `DELINQUENT`."

    Design: Corner/calculations/variance_assessment_ignores_negative_revenue_variance
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report_under_audit(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=8_000_000,
        reported_on_airport_transaction_days=4_000,
    )

    accepted = validate_success(
        api.accept_report(
            report["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=6_000_000,
                audited_on_airport_transaction_days=4_000,
            ),
            AUDITOR,
        )
    )

    assert accepted["revenue_variance_cents"] == -2_000_000
    assert accepted["variance_assessment_cents"] == 0, (
        "a negative variance is clamped to zero before the rate is applied"
    )
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["compliance_status"] == "COMPLIANT"
    assert agreement["gross_revenue_ytd_cents"] == 6_000_000
    assert agreement["percentage_rent_accrued_cents"] == 600_000
    assert agreement["rent_billed_to_date_cents"] == 1_000_000
    assert agreement["mag_shortfall_cents"] == 400_000


def test_submitted_report_does_not_feed_the_rent_ledger(api):
    """PRD §3.5: "Only reports in `ACCEPTED` status feed any of these accumulators — reports
    sitting in `DRAFT`, `SUBMITTED`, `UNDER_AUDIT`, `REJECTED` or `SUPERSEDED` contribute
    nothing."
    PRD §3.5: "Each submission raises `submission_count` by 1, so a report that has been
    rejected and resubmitted carries a submission count above 1."

    Design: Corner/calculations/rent_ledger_ignores_reports_that_are_only_submitted
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    second = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=2,
        reported_gross_revenue_cents=20_000_000,
        reported_on_airport_transaction_days=8_000,
    )

    submitted = validate_success(api.submit_report(second["id"], operator))

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_count"] == 1
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["gross_revenue_ytd_cents"] == 5_000_000, (
        "the merely submitted 20,000,000 must not enter the accrual input set"
    )
    assert agreement["transaction_days_ytd"] == 4_000
    assert agreement["accepted_report_count"] == 1
    assert agreement["percentage_rent_accrued_cents"] == 500_000
    assert agreement["rent_billed_to_date_cents"] == 1_000_000


def test_operator_cannot_submit_another_brands_report(api):
    """PRD §2.1: "Ownership checks on any resource that references a `Concessionaire` compare
    the resource's owning brand to `X-User-ID`: for every write endpoint whose authorised
    roles include `ConcessionaireOperator`, the server resolves the target resource's
    `agreement_id` to a `ConcessionAgreement`, reads that agreement's `concessionaire_id`, and
    requires it to equal `X-User-ID`. When it does not, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/concessionaire_operator_cannot_submit_another_operators_report
    """
    scenario = fx.setup_active_agreement(api)
    other = fx.add_brand_with_active_agreement(
        api, scenario["facility"]["id"], "BUD", "Budline Auto Rental"
    )
    report = fx.create_report(
        api, scenario["agreement"]["id"], scenario["operator"],
        period_year=2026, period_month=1,
    )

    response = api.submit_report(report["id"], other["operator"])

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    stored = validate_success(api.get_report(report["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["submission_count"] == 0


def test_operator_cannot_begin_an_audit(api):
    """PRD §2.1: "A caller whose role is recognised but who is not among the roles authorised
    for the endpoint being called receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "Open the audit: SUBMITTED -> UNDER_AUDIT | AuditOfficer"

    Design: Corner/rbac/concessionaire_operator_cannot_begin_an_audit
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(api, agreement_id, operator, period_year=2026, period_month=1)
    fx.submit_report(api, report["id"], operator)

    response = api.begin_audit_report(report["id"], operator)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    stored = validate_success(api.get_report(report["id"], ADMIN))
    assert stored["status"] == "SUBMITTED"
