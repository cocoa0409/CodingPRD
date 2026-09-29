"""
Lifecycle edges: which transitions exist, which are refused, and what they carry.

Every row in this programme moves through a named set of states, and the edges
are as much a part of the contract as the arithmetic is. A batch that has been
handed back can be repaired and resubmitted; a batch that has been posted accepts
nothing but a reversal; a rejected exemption filing is finished on both of its
outbound edges; a separation is terminal and closes the payroll door behind it.
The refusals below are as load-bearing as the successes, because each one names
the state gate that produced it rather than a generic conflict.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ADMIN_REVIEWER,
    EMPLOYER_RIDGE,
    ERR_CLOSURE_STATE_INVALID,
    ERR_ENROLLMENT_NOT_DEDUCTIBLE,
    ERR_ENROLLMENT_STATE_INVALID,
    ERR_EXEMPTION_STATE_INVALID,
    ERR_REMITTANCE_STATE_INVALID,
    OFFICER,
    OFFICER_A,
    OFFICER_A_USER_ID,
    OFFICER_B,
    OFFICER_B_USER_ID,
    PARTICIPANT_ROSA,
    PROGRAM_YEAR_2026,
    PROGRAM_YEAR_2027,
    RECORDKEEPER,
    add_remittance_line,
    assert_basis_points,
    assert_cents,
    assert_nulls,
    assess_penalty,
    build_active_saver_environment,
    build_employer_environment,
    create_participant,
    create_remittance,
    decide_exemption,
    dispose_penalty,
    excess_cases_for_account,
    file_exemption,
    fund_account_by_remittance,
    make_employer_headers,
    make_participant_headers,
    opt_out,
    post_earnings,
    read_account,
    read_employer,
    read_enrollment,
    read_excess_case,
    read_exemption,
    read_remittance,
    read_transfer,
    reject_remittance,
    request_transfer,
    run_compliance_sweep,
    set_clock,
    submit_remittance,
)


def _build_stale_case_and_unsettled_rollover(api):
    """
    A saver whose account carries an uncorrected excess case past its 15 April
    2027 deadline and an indirect rollover that was never settled inside its
    sixty days, with the clock one day past the correction deadline.
    """
    env = build_active_saver_environment(
        api, program_years=[PROGRAM_YEAR_2026, PROGRAM_YEAR_2027])
    fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        8000000, 400000, "2026-03-06T00:00:00Z",
        posting_reference="PR-2026-0001")
    post_earnings(api, env["account_id"], 50000, "2026-03-06")

    set_clock(api, "2026-03-10T00:00:00Z")
    transfer = request_transfer(api, env["participant_id"], env["account_id"],
                               90000)
    env["transfer_id"] = transfer["id"]

    fund_account_by_remittance(
        api, env, "2026-03-01", "2026-03-31", "2026-04-03",
        8000000, 400000, "2026-04-05T00:00:00Z",
        posting_reference="PR-2026-0002")
    cases = excess_cases_for_account(api, env["account_id"])
    assert len(cases) == 1, f"expected one excess case, found {len(cases)}"
    env["excess_case_id"] = cases[0]["id"]

    set_clock(api, "2027-04-16T00:00:00Z")
    return env


def test_new_enrolment_opens_notified_at_the_programme_default_rate(api):
    """A freshly enrolled employee starts under notice at the programme's own rate.

    The employer supplies only the hire facts, so the seeded rate is the program
    year's 500 basis points attributed to the programme rather than to anybody's
    election, and the thirty-day notice window that opens on 1 January 2026 closes
    on 31 January 2026. No account exists yet, because opening one is the
    activation batch's work and not the enrolment's.

    "The enrolment is created in status `NOTIFIED`, and its `opt_out_deadline` is
    the date of creation plus the program year's `opt_out_window_days` — thirty
    days of notice under the default configuration."

    "Activation is never a request; it is the work of the auto-enrolment batch."

    Design: Corner/state_machines/enrollment_starts_in_notified_with_the_program_default_rate
    """
    env = build_employer_environment(api)
    saver = create_participant(api, PARTICIPANT_ROSA)

    enrollment = validate_success(api.create_enrollment(
        env["employer_id"],
        {"participant_id": saver["id"], "hire_date": "2026-01-05",
         "annual_compensation_cents": 9600000},
        make_employer_headers(env["employer_id"])), 201)

    assert enrollment["enrollment_status"] == "NOTIFIED"
    assert_basis_points(enrollment["contribution_rate_bp"], 500,
                        "contribution_rate_bp")
    assert enrollment["rate_source"] == "DEFAULT"
    assert enrollment["opt_out_deadline"] == "2026-01-31"
    assert enrollment["employer_id"] == env["employer_id"]
    assert enrollment["participant_id"] == saver["id"]

    _, meta = validate_paginated(
        api.list_participant_accounts(ADMIN, {"participant_id": saver["id"]}))
    assert meta["total_count"] == 0, (
        "no account may exist before the auto-enrolment batch runs")


def test_rejected_exemption_filing_accepts_no_further_transition(api):
    """A refused qualified-plan filing is finished on both of its outbound edges.

    The reviewer rejected the filing, so a second reviewer cannot approve it and
    an enforcement officer cannot revoke it either: revocation is an edge out of
    approval, not out of refusal. The coverage window the filing claimed is still
    on the record, and the employer never moved out of pending registration
    because a refused filing certifies nothing.

    "Deciding an already-decided certification is refused with
    `ERR_EXEMPTION_STATE_INVALID`."

    "Revoking a certification that is not `APPROVED` is refused with
    `ERR_EXEMPTION_STATE_INVALID`."

    Design: Corner/state_machines/rejected_exemption_certification_accepts_no_further_transition
    """
    env = build_employer_environment(api, employer=EMPLOYER_RIDGE, register=False)
    filed = file_exemption(api, env["employer_id"])
    decide_exemption(api, filed["id"], "REJECT",
                     "Plan document does not evidence a qualified plan",
                     headers=ADMIN_REVIEWER)

    validate_error(api.decide_exemption_certification(
        filed["id"],
        {"decision": "APPROVE", "decision_note": "Second look on appeal"},
        ADMIN), ERR_EXEMPTION_STATE_INVALID)
    validate_error(api.revoke_exemption_certification(
        filed["id"],
        {"revocation_reason": "Sponsor terminated the plan"},
        OFFICER), ERR_EXEMPTION_STATE_INVALID)

    certification = read_exemption(api, filed["id"])
    assert certification["status"] == "REJECTED"
    assert certification["coverage_period_start"] == "2026-01-01"
    assert certification["coverage_period_end"] == "2029-01-01"
    assert_nulls(certification, ["revoked_at"], "certification")

    employer = read_employer(api, env["employer_id"])
    assert employer["registration_status"] == "PENDING_REGISTRATION"
    assert employer["compliance_status"] == "COMPLIANT"


def test_handed_back_batch_is_repaired_and_returns_to_submitted(api):
    """A rejected batch is not dead: resubmission puts it back under reconciliation.

    The batch was handed back over a settlement failure, and resubmitting it on
    6 March 2026 re-runs the lateness check against the new submission clock.
    That clock is still inside the seven days the batch had from its 5 March pay
    date, so the repair cycle costs nothing in lateness, the old rejection reason
    is cleared, and no money has moved because posting has not happened.

    "Resubmission from `REJECTED` re-runs the reconciliation check and re-freezes
    `days_late` against the new submission clock, which is how a repair cycle
    accumulates lateness rather than escaping it."

    Design: Corner/state_machines/rejected_remittance_can_be_resubmitted_and_returns_to_submitted
    """
    env = build_active_saver_environment(api)
    set_clock(api, "2026-03-06T00:00:00Z")
    batch = create_remittance(api, env["employer_id"], "2026-02-01", "2026-02-28",
                              "2026-03-05", 400000)
    add_remittance_line(api, batch["id"], env["employer_id"],
                        env["enrollment_id"], 8000000, 400000)
    submit_remittance(api, batch["id"], env["employer_id"])
    reject_remittance(api, batch["id"],
                      "Bank file did not settle; resubmit after ACH repair")

    resubmitted = validate_success(api.submit_remittance(
        batch["id"], make_employer_headers(env["employer_id"]),
        {"submission_note": "ACH repaired, resubmitting the same batch"}))

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["days_late"] == 0
    assert resubmitted["line_count"] == 1
    assert_cents(resubmitted["total_allocated_cents"], 0,
                 "total_allocated_cents")
    assert_nulls(resubmitted, ["rejection_reason", "posted_at"], "batch")

    employer = read_employer(api, env["employer_id"])
    assert employer["compliance_status"] == "COMPLIANT"
    assert_cents(employer["unremitted_deduction_cents"], 0,
                 "unremitted_deduction_cents")

    _, meta = validate_paginated(
        api.list_employer_payroll_remittances(env["employer_id"], ADMIN))
    assert meta["total_count"] == 1, "the repair reuses the batch, it does not clone it"


def test_posted_batch_accepts_neither_a_new_line_nor_a_second_posting(api):
    """Once money has landed, the batch is closed to lines and to re-posting alike.

    The batch was posted with one 400000-cent line, and the door is shut on both
    sides: a second employee cannot be appended after the fact, and the
    recordkeeper cannot post the same batch twice under a fresh reference. The
    batch keeps the reference it was posted under, and the saver's account still
    shows one credit rather than two.

    "Lines are added to a batch one employee at a time while the batch is in
    `DRAFT` or `REJECTED`; adding a line to a batch in any other status is refused
    with `ERR_REMITTANCE_STATE_INVALID`."

    Design: Corner/state_machines/adding_a_line_to_a_posted_remittance_is_refused
    """
    env = build_active_saver_environment(api)
    posted = fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        8000000, 400000, "2026-03-06T00:00:00Z",
        posting_reference="PR-2026-0001")
    batch_id = posted["remittance_id"]

    validate_error(api.create_remittance_line(
        batch_id,
        {"enrollment_id": env["enrollment_id"], "gross_wages_cents": 1000000,
         "deducted_cents": 50000},
        make_employer_headers(env["employer_id"])), ERR_REMITTANCE_STATE_INVALID)
    validate_error(api.post_remittance(
        batch_id, {"posting_reference": "PR-2026-0001-RETRY"}, RECORDKEEPER),
        ERR_REMITTANCE_STATE_INVALID)

    batch = read_remittance(api, batch_id)
    assert batch["status"] == "POSTED"
    assert batch["line_count"] == 1
    assert batch["posting_reference"] == "PR-2026-0001"
    assert_cents(batch["total_allocated_cents"], 400000, "total_allocated_cents")

    _, meta = validate_paginated(api.list_remittance_lines(batch_id, RECORDKEEPER))
    assert meta["total_count"] == 1

    account = read_account(api, env["account_id"])
    assert_cents(account["balance_cents"], 400000, "balance_cents")
    assert_cents(account["ytd_contribution_cents"], 400000,
                 "ytd_contribution_cents")


def test_closure_cannot_be_completed_on_an_account_nobody_asked_to_close(api):
    """Completion is an edge out of a pending closure, not out of an open account.

    The saver never asked for the account to be closed, so the recordkeeper's
    completion call is refused on the account's state rather than on its balance —
    even though the balance is zero and would have satisfied the residual test if
    the state gate had let the request through. The account is untouched and still
    open for business.

    "The account must be in `CLOSURE_PENDING`, else `ERR_CLOSURE_STATE_INVALID`;
    its `balance_cents` must be exactly zero, else `ERR_RESIDUAL_BALANCE_PRESENT`;
    and no excess-contribution case of the account may remain in `DETECTED` or
    `METHOD_ELECTED`, since an unresolved correction cannot be executed against a
    closed account."

    Design: Corner/state_machines/closure_completion_on_an_open_account_is_refused
    """
    env = build_active_saver_environment(api)

    validate_error(api.complete_account_closure(
        env["account_id"], RECORDKEEPER,
        {"completion_note": "Closing without a request on file"}),
        ERR_CLOSURE_STATE_INVALID)

    account = read_account(api, env["account_id"])
    assert account["account_status"] == "OPEN"
    assert account["posture"] == "UNRESTRICTED"
    assert_cents(account["balance_cents"], 0, "balance_cents")
    assert_nulls(account, ["closed_at", "closure_reason"], "account")


def test_second_opt_out_on_an_already_opted_out_enrolment_is_refused(api):
    """A saver who has already left cannot leave twice, and the first reason stands.

    The affordability opt-out took the enrolment out of the programme, and a
    second attempt naming a different reason is refused on state: opting out is an
    edge out of notice or activity, and the saver's route back in is re-enrolment.
    The stored reason and the moment of departure are the ones the first request
    recorded.

    "Enrolment triggers are gated by `ERR_ENROLLMENT_STATE_INVALID`: opt-out
    requires `NOTIFIED` or `ACTIVE`, re-enrolment requires `OPTED_OUT`, a rate
    election requires `NOTIFIED` or `ACTIVE`, and an employment update requires any
    status other than `TERMINATED`."

    Design: Corner/state_machines/second_opt_out_on_an_already_opted_out_enrollment_is_refused
    """
    env = build_active_saver_environment(api)
    first = opt_out(api, env["enrollment_id"], env["participant_id"],
                    "AFFORDABILITY")

    validate_error(api.opt_out_enrollment(
        env["enrollment_id"], {"opt_out_reason_code": "OTHER"},
        make_participant_headers(env["participant_id"])),
        ERR_ENROLLMENT_STATE_INVALID)

    enrollment = read_enrollment(api, env["enrollment_id"])
    assert enrollment["enrollment_status"] == "OPTED_OUT"
    assert enrollment["opt_out_reason_code"] == "AFFORDABILITY"
    assert enrollment["opted_out_at"] == first["opted_out_at"]


def test_abating_the_only_assessment_restores_the_employer_to_compliant(api):
    """Abatement unwinds the penalty and hands the employer back its clean standing.

    A second officer abates the assessment the first officer raised — the two
    identities have to differ — and because nothing else is outstanding against
    this employer and it owes no withheld money, the enforcement dimension is
    re-derived all the way back to compliant rather than merely down to penalised.
    Both officers stay on the record, and no referral was ever raised.

    "The employer's `compliance_status` is then re-derived by the rules above,
    which is what lifts an employer out of `REFERRED`: if another assessment of
    that employer remains in `ASSESSED` or `AFFIRMED`, the employer falls back to
    `PENALIZED`; if none does and `unremitted_deduction_cents` is zero, it returns
    all the way to `COMPLIANT`."

    Design: Corner/state_machines/penalty_abatement_restores_the_employer_to_compliant
    """
    env = build_employer_environment(api, employer=EMPLOYER_RIDGE, register=False)
    set_clock(api, "2026-02-01T00:00:00Z")
    penalty = assess_penalty(api, env["employer_id"], "FAILURE_TO_ENROLL",
                             "2025-10-01", 30, headers=OFFICER_A)

    disposed = dispose_penalty(
        api, penalty["id"], "ABATE",
        "Employer produced timely enrolment evidence for every employee",
        headers=OFFICER_B)

    assert disposed["status"] == "ABATED"
    assert disposed["assessed_by_user_id"] == OFFICER_A_USER_ID
    assert disposed["disposed_by_user_id"] == OFFICER_B_USER_ID
    assert disposed["disposition_note"] == (
        "Employer produced timely enrolment evidence for every employee")

    employer = read_employer(api, env["employer_id"])
    assert employer["compliance_status"] == "COMPLIANT"
    assert employer["registration_status"] == "PENDING_REGISTRATION"
    assert_cents(employer["unremitted_deduction_cents"], 0,
                 "unremitted_deduction_cents")

    _, meta = validate_paginated(
        api.list_enforcement_referrals(penalty["id"], OFFICER_A))
    assert meta["total_count"] == 0, "an abated assessment leaves no referral behind"


def test_separation_terminates_the_enrolment_and_shuts_off_later_deductions(api):
    """A reported end date is terminal, and payroll cannot reach the saver after it.

    The employer reports a 28 February 2026 separation, which drives the enrolment
    straight to terminated. A line filed afterwards against that enrolment is
    refused as an incoherent deduction target even though its arithmetic is
    perfect, and the saver cannot be brought back by re-enrolment either, because
    nothing leads out of the terminal state. The account itself survives the
    employment relationship.

    "That single field terminates the enrolment: from either `ACTIVE` or
    `OPTED_OUT` the status becomes `TERMINATED`, and `TERMINATED` is terminal — no
    trigger ever moves an enrolment out of it, and any trigger attempted against
    one is refused with `ERR_ENROLLMENT_STATE_INVALID`."

    Design: Corner/state_machines/employment_end_date_terminates_enrollment_and_blocks_later_deductions
    """
    env = build_active_saver_environment(api)
    set_clock(api, "2026-03-06T00:00:00Z")
    batch = create_remittance(api, env["employer_id"], "2026-02-01", "2026-02-28",
                              "2026-03-05", 400000)
    employer_headers = make_employer_headers(env["employer_id"])

    terminated = validate_success(api.update_employment(
        env["enrollment_id"], {"employment_end_date": "2026-02-28"},
        employer_headers))

    assert terminated["enrollment_status"] == "TERMINATED"
    assert terminated["employment_end_date"] == "2026-02-28"

    validate_error(api.create_remittance_line(
        batch["id"],
        {"enrollment_id": env["enrollment_id"], "gross_wages_cents": 8000000,
         "deducted_cents": 400000},
        employer_headers), ERR_ENROLLMENT_NOT_DEDUCTIBLE)
    validate_error(api.reenroll(
        env["enrollment_id"], make_participant_headers(env["participant_id"]),
        {"reenroll_note": "Employee rehired next quarter"}),
        ERR_ENROLLMENT_STATE_INVALID)

    unchanged = read_remittance(api, batch["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["line_count"] == 0

    enrollment = read_enrollment(api, env["enrollment_id"])
    assert enrollment["enrollment_status"] == "TERMINATED"

    account = read_account(api, env["account_id"])
    assert account["account_status"] == "OPEN"
    assert account["posture"] == "UNRESTRICTED"


def test_sweep_expires_the_overdue_correction_and_books_its_excise_tax(api):
    """Time, not a request, ends an uncorrected excess — and it ends it expensively.

    The saver's 100000-cent excess was detected on 5 April 2026 and had until
    15 April 2027 to be corrected. The sweep runs one day later, so the case is
    expired and the six-percent excise tax of 6000 cents is booked against it. The
    money stays in the account and is now on the record as uncorrected, which keeps
    the account restricted; the employer, having remitted everything it withheld,
    is not swept into delinquency.

    "When the compliance sweep runs and finds a case in `DETECTED` or
    `METHOD_ELECTED` whose `deadline_date` is behind the clock date, the case moves
    to `EXPIRED` and the statutory excise tax is booked: `excise_tax_cents` becomes
    `detected_excess_cents` multiplied by 600 basis points — six percent — divided
    by 10000 and rounded half up to a whole cent."

    Design: Corner/state_machines/compliance_sweep_expires_a_stale_case_and_fails_an_unsettled_indirect_transfer
    """
    env = _build_stale_case_and_unsettled_rollover(api)

    result = run_compliance_sweep(api)

    assert result["expired_case_count"] == 1
    assert result["failed_transfer_count"] == 1
    assert result["delinquent_employer_count"] == 0
    assert result["assessments_created_count"] == 0

    case = read_excess_case(api, env["excess_case_id"])
    assert case["status"] == "EXPIRED"
    assert case["deadline_date"] == "2027-04-15"
    assert_cents(case["detected_excess_cents"], 100000, "detected_excess_cents")
    assert_cents(case["excise_tax_cents"], 6000, "excise_tax_cents")

    account = read_account(api, env["account_id"])
    assert_cents(account["uncorrected_excess_cents"], 100000,
                 "uncorrected_excess_cents")
    assert_cents(account["balance_cents"], 760000, "balance_cents")
    assert account["posture"] == "RESTRICTED"

    employer = read_employer(api, env["employer_id"])
    assert employer["compliance_status"] == "COMPLIANT"


def test_sweep_lapses_the_unsettled_indirect_rollover_into_a_taxable_payout(api):
    """A sixty-day rollover that never landed is deemed a taxable distribution.

    The 90000-cent indirect rollover was requested on 10 March 2026 and had to
    settle by 9 May 2026. Nobody settled it, so the sweep ends it: the in-flight
    leg is zeroed, the movement is stamped taxable, and none of the money comes
    back to the account. The five figures pinned at request time are untouched by
    the lapse — a 40-basis-point fee of 360 cents, a pro-rata basis portion of
    80000 cents against the account's pre-debit 400000-over-450000 split, a
    10000-cent taxable slice, 1000 cents of mandatory withholding and 88640 cents
    of net proceeds.

    "When the compliance sweep finds an `INDIRECT_60_DAY` transfer still in
    `REQUESTED` whose `settle_by_date` is behind the clock date, the transfer moves
    `REQUESTED → FAILED_TAXABLE`, `in_transit_cents` is zeroed and
    `is_taxable_distribution` is set to true."

    Design: Corner/state_machines/compliance_sweep_expires_a_stale_case_and_fails_an_unsettled_indirect_transfer
    """
    env = _build_stale_case_and_unsettled_rollover(api)

    result = run_compliance_sweep(api)

    assert result["failed_transfer_count"] == 1

    transfer = read_transfer(api, env["transfer_id"])
    assert transfer["status"] == "FAILED_TAXABLE"
    assert transfer["settle_by_date"] == "2026-05-09"
    assert transfer["is_taxable_distribution"] is True
    assert_cents(transfer["in_transit_cents"], 0, "in_transit_cents")
    assert_cents(transfer["fee_cents"], 360, "fee_cents")
    assert_cents(transfer["basis_portion_cents"], 80000, "basis_portion_cents")
    assert_cents(transfer["taxable_cents"], 10000, "taxable_cents")
    assert_cents(transfer["withholding_cents"], 1000, "withholding_cents")
    assert_cents(transfer["net_cents"], 88640, "net_cents")
    assert_nulls(transfer, ["settled_on", "settlement_reference", "return_reason"],
                 "transfer")
