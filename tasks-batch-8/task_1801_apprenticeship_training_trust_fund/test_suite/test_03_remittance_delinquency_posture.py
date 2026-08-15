"""Audit flag/resubmit cycle, remittance, delinquency sweep, and the fund's
compliance posture (PRD §3.3, §2.6, §2.7)."""
from test_helpers import (
    ADMIN,
    CM1,
    ApiErrorId,
    approve_allocation,
    assert_instant_equals,
    assert_trust_fund_ledger,
    create_purchase,
    create_report,
    flag_report,
    get_allocation,
    get_apprentice,
    get_employer,
    get_fund,
    get_purchase,
    get_report,
    make_employer_rep_headers,
    propose_allocation,
    report_line,
    resubmit_report,
    run_ops,
    set_clock,
    setup_delinquent_employer,
    setup_fund_employer_apprentice,
    setup_paid_report,
    setup_submitted_report,
    validate_error,
    validate_success,
)


def test_flag_resubmit_cycle_returns_submitted(api):
    """PRD §3.3: "A `TrustAdmin` performing an audit may flag a `SUBMITTED`
    report, moving it to `FLAGGED`; flagging a report in any other status is
    rejected with `ERR_REPORT_NOT_FLAGGABLE`."
    PRD §3.3: "Resubmission is the employer's cure for a flagged report: it
    moves `FLAGGED` → `SUBMITTED` with a replacement `lines` array, and any
    report not in `FLAGGED` is refused with `ERR_REPORT_NOT_RESUBMITTABLE`."

    Design: Difficulty/non_linear_state_machine/contribution_report_flag_resubmit_cycle
    """
    _fund, employer, apprentice, report = setup_submitted_report(hours=100)
    assert report["contribution_due_cents"] == 50000

    flagged = flag_report(report["id"], reason="audit: hours overstated")
    assert flagged["status"] == "FLAGGED"
    assert flagged["flag_reason"] == "audit: hours overstated"

    resp = api.resubmit_report(
        report["id"],
        {"lines": [report_line(apprentice["id"], 90)]},
        make_employer_rep_headers(employer["id"]),
    )
    resubmitted = validate_success(resp, 200)
    assert resubmitted["status"] == "SUBMITTED", "audit rework loop closes"
    assert resubmitted["contribution_due_cents"] == 45000, "90h x 500c"
    assert resubmitted["flag_reason"] is None


def test_resubmit_reprices_and_adjusts_hours(api):
    """PRD §3.3: "Each old line's hours are debited from its apprentice and
    each new line's hours credited, with wage steps and rates recomputed in
    both directions — a downward correction can lower an apprentice's step."
    PRD §3.3: "The due is recomputed at the employer's current rate,
    `outstanding_cents` is recomputed, and `flag_reason` is cleared."

    Design: Difficulty/non_linear_state_machine/contribution_report_flag_resubmit_cycle
    """
    _fund, employer, apprentice, report = setup_submitted_report(hours=100)
    flag_report(report["id"])
    resubmit_report(employer, report["id"],
                    [report_line(apprentice["id"], 90)])

    after = get_apprentice(apprentice["id"])
    assert after["ojt_hours_accumulated"] == 90, (
        "100 hours debited, 90 credited"
    )
    assert get_employer(employer["id"])["outstanding_cents"] == 45000


def test_resubmit_with_identical_lines_keeps_hours(api):
    """PRD §3.3: "Each old line's hours are debited from its apprentice and
    each new line's hours credited, with wage steps and rates recomputed in
    both directions — a downward correction can lower an apprentice's step."

    Design: Difficulty/compensating_invariant/compensating_apprentice_hours
    """
    _fund, employer, apprentice, report = setup_submitted_report(hours=100)
    assert get_apprentice(apprentice["id"])["ojt_hours_accumulated"] == 100

    flag_report(report["id"])
    resubmit_report(employer, report["id"],
                    [report_line(apprentice["id"], 100)])

    after = get_apprentice(apprentice["id"])
    assert after["ojt_hours_accumulated"] == 100, (
        "debit-before-credit: neither double-counted (200) nor lost (0)"
    )
    assert get_report(report["id"])["contribution_due_cents"] == 50000


def test_resubmit_with_identical_lines_keeps_outstanding(api):
    """PRD §3.3: "The due is recomputed at the employer's current rate,
    `outstanding_cents` is recomputed, and `flag_reason` is cleared."
    PRD §2.6: "An employer's `outstanding_cents` is the sum of
    `contribution_due_cents` over that employer's reports in `SUBMITTED`,
    `FLAGGED`, or `DELINQUENT` status; DRAFT reports contribute nothing
    because their due is still null, and PAID reports are excluded."

    Design: Difficulty/compensating_invariant/compensating_apprentice_hours
    """
    _fund, employer, _apprentice, report = setup_submitted_report(hours=100)
    flag_report(report["id"])
    # FLAGGED reports still count toward outstanding.
    assert get_employer(employer["id"])["outstanding_cents"] == 50000
    resubmit_report(employer, report["id"],
                    [report_line(_apprentice["id"], 100)])
    assert get_employer(employer["id"])["outstanding_cents"] == 50000, (
        "identical replacement lines leave outstanding unchanged"
    )


def test_flag_draft_report_rejected(api):
    """PRD §3.3: "A `TrustAdmin` performing an audit may flag a `SUBMITTED`
    report, moving it to `FLAGGED`; flagging a report in any other status is
    rejected with `ERR_REPORT_NOT_FLAGGABLE`."

    Design: Corner/errors/error_report_not_flaggable_on_draft
    """
    _fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 10)],
    )
    resp = api.flag_report(report["id"], {"reason": "premature audit"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FLAGGABLE)
    assert get_report(report["id"])["status"] == "DRAFT"


def test_resubmit_submitted_report_rejected(api):
    """PRD §3.3: "Resubmission is the employer's cure for a flagged report: it
    moves `FLAGGED` → `SUBMITTED` with a replacement `lines` array, and any
    report not in `FLAGGED` is refused with `ERR_REPORT_NOT_RESUBMITTABLE`."

    Design: Corner/errors/error_resubmit_only_from_flagged
    """
    _fund, employer, apprentice, report = setup_submitted_report(hours=10)
    resp = api.resubmit_report(
        report["id"],
        {"lines": [report_line(apprentice["id"], 10)]},
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_RESUBMITTABLE)
    assert get_report(report["id"])["status"] == "SUBMITTED"


def test_remit_draft_report_rejected(api):
    """PRD §3.3: "Remittance settles a report: `SUBMITTED` or `DELINQUENT` →
    `PAID`, with any other source state rejected as `ERR_REPORT_NOT_PAYABLE`."

    Design: Corner/errors/error_remit_from_draft
    """
    _fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 10)],
    )
    resp = api.remit_report(
        report["id"], {"amount_tendered_cents": 5000},
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_PAYABLE)
    assert get_report(report["id"])["status"] == "DRAFT"


def test_remit_amount_mismatch_rejected(api):
    """PRD §3.3: "Ownership is enforced again, and the `amount_tendered_cents`
    must equal the `contribution_due_cents` exactly — neither partial payment
    nor overpayment is accepted; a mismatch is rejected with
    `ERR_REMITTANCE_AMOUNT_MISMATCH` (HTTP 400)."

    Design: Corner/errors/error_remittance_amount_mismatch
    """
    _fund, employer, _apprentice, report = setup_submitted_report(hours=100)
    assert report["contribution_due_cents"] == 50000
    resp = api.remit_report(
        report["id"], {"amount_tendered_cents": 49999},
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REMITTANCE_AMOUNT_MISMATCH)
    assert get_report(report["id"])["status"] == "SUBMITTED"


def _setup_delinquent_report(hours=200, rate=500, period=(2026, 5),
                             clock_start="2026-06-01T00:00:00Z",
                             overdue_to="2026-06-16T00:00:00Z"):
    """One employer with a SUBMITTED report swept to DELINQUENT; fund in
    COMPLIANCE_HOLD. Returns (fund, employer, apprentice, report)."""
    fund, employer, apprentice, report = setup_submitted_report(
        hours=hours, rate=rate, period=period, clock=clock_start,
    )
    set_clock(overdue_to)
    run_ops(fund["id"])
    return fund, employer, apprentice, get_report(report["id"])


def test_remit_cures_employer_and_posture(api):
    """PRD §3.3: "An accepted remittance stamps `remitted_at`, drops the
    employer's `outstanding_cents` by the paid amount, adds the paid amount to
    the fund's `contributions_received_cents` with `available_cents`
    recomputed and the fund's `version` advanced by one, and then runs the
    cure cascade: if the employer has no remaining `DELINQUENT` reports it
    returns `DELINQUENT` → `ACTIVE`, and if that cure drops the fund's
    `delinquent_employer_count` to zero the fund's `posture` clears
    `COMPLIANCE_HOLD` → `OPERATING`."

    Design: Difficulty/transitive_cascade/remit_cure_chain_report_employer_fund
    """
    fund, employer, _apprentice, report = _setup_delinquent_report()
    assert report["status"] == "DELINQUENT"
    assert get_employer(employer["id"])["status"] == "DELINQUENT"
    assert get_fund(fund["id"])["posture"] == "COMPLIANCE_HOLD"

    resp = api.remit_report(
        report["id"], {"amount_tendered_cents": 100000},
        make_employer_rep_headers(employer["id"]),
    )
    paid = validate_success(resp, 200)
    assert paid["status"] == "PAID"
    assert paid["remitted_at"] is not None

    employer_after = get_employer(employer["id"])
    assert employer_after["status"] == "ACTIVE", (
        "cured by the remittance itself, no separate call"
    )
    assert employer_after["outstanding_cents"] == 0

    fund_after = get_fund(fund["id"])
    assert fund_after["posture"] == "OPERATING", (
        "third hop: the cure drops the delinquent count to zero"
    )
    assert fund_after["delinquent_employer_count"] == 0


def test_remit_posts_contribution_and_clears_outstanding(api):
    """PRD §2.6: "`contributions_received_cents` is the sum of
    `contribution_due_cents` across all PAID contribution reports of all the
    fund's employers."
    PRD §2.6: "An employer's `outstanding_cents` is the sum of
    `contribution_due_cents` over that employer's reports in `SUBMITTED`,
    `FLAGGED`, or `DELINQUENT` status; DRAFT reports contribute nothing
    because their due is still null, and PAID reports are excluded."

    Design: Difficulty/transitive_cascade/remit_cure_chain_report_employer_fund
    """
    fund, employer, _apprentice, report = _setup_delinquent_report()
    resp = api.remit_report(
        report["id"], {"amount_tendered_cents": 100000},
        make_employer_rep_headers(employer["id"]),
    )
    validate_success(resp, 200)

    fund_after = get_fund(fund["id"])
    assert fund_after["contributions_received_cents"] == 100000
    assert_trust_fund_ledger(fund_after)
    assert fund_after["available_cents"] == 100000
    assert get_employer(employer["id"])["outstanding_cents"] == 0, (
        "PAID reports are excluded from outstanding"
    )


def test_run_ops_delinquency_strictly_greater_boundary(api):
    """PRD §3.3: "The run examines every report of the fund still in `DRAFT`,
    `SUBMITTED`, or `FLAGGED`, processed in ascending `due_date` order with
    ties broken by creation timestamp, earliest first, and moves to
    `DELINQUENT` each report whose due date is strictly earlier than the
    current logical time — a report exactly at its due instant is still
    timely."
    PRD §3.3: "It then re-derives each employer's status: `DELINQUENT` when
    the employer has at least one `DELINQUENT` report, `ACTIVE` otherwise."

    Design: Corner/calculations/delinquency_run_ops_marks_overdue_reports
    """
    fund, employer, _apprentice, report = setup_submitted_report(
        hours=100, period=(2026, 6), clock="2026-07-01T00:00:00Z",
    )
    assert_instant_equals(
        get_report(report["id"])["due_date"], "2026-07-15T00:00:00Z",
    )

    # At exactly the due instant the report is still timely.
    set_clock("2026-07-15T00:00:00Z")
    run_ops(fund["id"])
    assert get_report(report["id"])["status"] == "SUBMITTED"

    # One day past, the next ops run flips the whole chain.
    set_clock("2026-07-16T00:00:00Z")
    run_ops(fund["id"])
    assert get_report(report["id"])["status"] == "DELINQUENT"
    assert get_employer(employer["id"])["status"] == "DELINQUENT"
    fund_after = get_fund(fund["id"])
    assert fund_after["posture"] == "COMPLIANCE_HOLD"
    assert fund_after["delinquent_employer_count"] == 1


def _setup_hold_with_requested_purchase():
    """Funded fund + ACTIVE allocation + REQUESTED purchase, then a second
    employer's overdue DRAFT report flips the fund to COMPLIANCE_HOLD."""
    fund, employer, _apprentice, _report = setup_paid_report(
        hours=1000, rate=500, period=(2026, 3), clock="2026-06-01T00:00:00Z",
    )
    allocation = propose_allocation(fund["id"], 100000)
    allocation = approve_allocation(allocation["id"], approver_headers=CM1)
    purchase = create_purchase(allocation["id"], 50000,
                               description="Training transformers")
    setup_delinquent_employer(
        fund, period=(2026, 5), overdue_to="2026-06-16T00:00:00Z",
    )
    return fund, allocation, purchase


def test_purchase_approve_rejected_under_compliance_hold(api):
    """PRD §2.7: "While the posture is `COMPLIANCE_HOLD`, exactly three
    approval operations are refused with `ERR_FUND_ON_COMPLIANCE_HOLD`
    (HTTP 409): approval of a funding allocation, approval of an equipment
    purchase, and approval of an instructor pay claim."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_purchase_approve_blocked_under_compliance_hold
    """
    fund, _allocation, purchase = _setup_hold_with_requested_purchase()
    assert get_fund(fund["id"])["posture"] == "COMPLIANCE_HOLD", (
        "precondition: the second employer's overdue DRAFT flipped the fund"
    )

    resp = api.approve_equipment_purchase(purchase["id"], CM1)
    validate_error(resp, ApiErrorId.ERR_FUND_ON_COMPLIANCE_HOLD)
    assert get_purchase(purchase["id"])["status"] == "REQUESTED"


def test_compliance_hold_leaves_purchase_and_allocation_untouched(api):
    """PRD §2.7: "While the posture is `COMPLIANCE_HOLD`, exactly three
    approval operations are refused with `ERR_FUND_ON_COMPLIANCE_HOLD`
    (HTTP 409): approval of a funding allocation, approval of an equipment
    purchase, and approval of an instructor pay claim."
    PRD §3.7: "Approval stamps `decided_by_user_id` — null until the purchase
    is decided — and encumbers the allocation: `encumbered_cents` grows by the
    purchase amount and `remaining_cents` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_purchase_approve_blocked_under_compliance_hold
    """
    fund, allocation, purchase = _setup_hold_with_requested_purchase()
    assert get_fund(fund["id"])["posture"] == "COMPLIANCE_HOLD"

    resp = api.approve_equipment_purchase(purchase["id"], CM1)
    validate_error(resp, ApiErrorId.ERR_FUND_ON_COMPLIANCE_HOLD)

    purchase_after = get_purchase(purchase["id"])
    assert purchase_after["status"] == "REQUESTED"
    assert purchase_after["decided_by_user_id"] is None

    allocation_after = get_allocation(allocation["id"])
    assert allocation_after["encumbered_cents"] == 0, (
        "no approval happened, so no encumbrance was recorded"
    )
